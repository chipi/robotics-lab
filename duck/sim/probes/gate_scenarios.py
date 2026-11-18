"""RFC-0017 §5 step 3: the gate in front of the simulator's robotd, three scenarios, judged by the simulator's truth.

    cd duck && .venv/bin/python sim/probes/gate_scenarios.py        # resets the simulator before each scenario (~45 s each)

The gate (duck_lab.gate_proxy) listens on a socket of its own in a temporary folder and forwards to ~/.cache/duck-sim/duck-a.sock;
each navigator is a `duck-go` process (python -m duck_lab.nav.run) started with --robot-socket and --client, so it takes the
lease before it does anything. The simulator is the shared one and needs no one else using it; the runs write no miniview run.

  a. a second navigator is refused, and the first goes on;
  b. the first navigator is killed (SIGKILL): the robot stops and is free at once;
  c. a client frozen (SIGSTOP) past its lease, then resumed, is refused: the robot was stopped and freed while it slept.

Not in `make test-duck`: it needs the simulator and moves it. Prints PASS/FAIL per check and exits 1 on any FAIL."""

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from duck_lab.gate_proxy import Proxy
from duck_lab.nav import simreset
from duck_lab.nav.client import SIM, LeaseLost, Rpc
from duck_lab.nav.run import Body

LEASE_S = 10.0
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:220]}]" if detail else ""), flush=True)
    if not cond:
        failures.append(name)


def wait_for(cond, timeout, every=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


def navigator(gate: Path, client: str, x: float, y: float, out: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k != "MINIVIEW_DATA"}      # these runs write no miniview run
    return subprocess.Popen([sys.executable, "-m", "duck_lab.nav.run", str(x), str(y), "--robot-socket", str(gate), "--client", client,
                             "--timeout", "90"], stdout=open(out, "w"), stderr=subprocess.STDOUT, env=env)


def last_json(path: Path) -> dict:
    for line in reversed(path.read_text().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {}


def displacement(body: Body, seconds: float) -> float:
    a = body.pose()
    time.sleep(seconds)
    b = body.pose()
    return math.dist(a[:2], b[:2])


def scenario(name: str):
    print(f"\n--- {name}", flush=True)
    simreset.reset("apartment_backlash")
    tmp = Path(tempfile.mkdtemp(prefix="gate-scenario-"))
    proxy = Proxy(tmp / "gate.sock", SIM / "duck-a.sock", log=tmp / "gate.jsonl", lease_s=LEASE_S)
    proxy.start()
    return tmp, proxy, Body()


def who(gate: Path) -> dict:
    rpc = Rpc(gate, client="probe")
    try:
        return rpc.call("gate.who")
    finally:
        rpc.close()


def moving(body: Body, start: tuple, metres: float = 0.3):
    return lambda: math.dist(body.pose()[:2], start[:2]) > metres


# --- a: a second navigator is refused -------------------------------------------------------------
tmp, proxy, body = scenario("a: a second navigator is refused")
gate = tmp / "gate.sock"
start = body.pose()
n1 = navigator(gate, "nav-1", 1.5, 0.5, tmp / "n1.out")
check("the first navigator takes the lease and starts walking", wait_for(moving(body, start), 60) is not None and who(gate).get("holder") == "nav-1", who(gate))
n2 = navigator(gate, "nav-2", 0.0, 2.0, tmp / "n2.out")
n2.wait(timeout=60)
r2 = last_json(tmp / "n2.out")
check("the second navigator is refused with who holds it, before it moves anything", n2.returncode == 3 and r2.get("status") == "refused"
      and r2.get("gate") == "held" and r2.get("holder") == "nav-1", (n2.returncode, r2))
at = body.pose()
check("and the first goes on", n1.poll() is None or n1.returncode == 0)
n1.wait(timeout=120)
r1 = last_json(tmp / "n1.out")
check("the first navigator reaches its goal", n1.returncode == 0 and r1.get("status") == "reached", (n1.returncode, r1))
end = body.pose()
check("it walked on after the refusal (truth)", math.dist(end[:2], start[:2]) > math.dist(at[:2], start[:2]) - 0.05 and math.dist(end[:2], (1.5, 0.5)) < 0.6, (at, end))
check("the lease is free when it is done", wait_for(lambda: who(gate).get("holder") is None, 5) is not None)
events = [json.loads(l)["event"] for l in (tmp / "gate.jsonl").read_text().splitlines()]
check("the gate's log has the refusal and the release", "refused" in events and "released" in events, events)
proxy.stop()

# --- b: the first navigator is killed ----------------------------------------------------------------
tmp, proxy, body = scenario("b: the first navigator is killed")
gate = tmp / "gate.sock"
start = body.pose()
n1 = navigator(gate, "nav-1", 4.0, 0.0, tmp / "n1.out")
check("walking under the lease", wait_for(moving(body, start), 60) is not None and who(gate).get("holder") == "nav-1")
n1.send_signal(signal.SIGKILL)
n1.wait(timeout=10)
check("the connection closing frees the robot at once (no waiting for the lease to expire)", wait_for(lambda: who(gate).get("holder") is None, 3) is not None, who(gate))
time.sleep(2.0)
d = displacement(body, 1.5)
check("and the robot stopped: it does not walk on (truth, 1.5 s)", d < 0.03, d)
events = [json.loads(l) for l in (tmp / "gate.jsonl").read_text().splitlines()]
check("the log says the navigator disconnected, and the gate ended its lease on that", any(e["event"] == "disconnected" and e["client"] == "nav-1" for e in events)
      and any(e["event"] == "disconnected" and e.get("why", "").startswith("disconnect of nav-1") for e in events), [e["event"] for e in events])
rpc = Rpc(gate, client="nav-3")
try:
    check("a new navigator can take the robot straight away", rpc.call("gate.acquire")["lease_id"] >= 2)
except LeaseLost as exc:
    check("a new navigator can take the robot straight away", False, exc)
finally:
    rpc.close()
proxy.stop()

# --- c: a frozen client, resumed, is refused ------------------------------------------------------------
tmp, proxy, body = scenario("c: a client frozen past its lease, then resumed")
gate = tmp / "gate.sock"
start = body.pose()
n1 = navigator(gate, "nav-1", 4.0, 0.0, tmp / "n1.out")
check("walking under the lease", wait_for(moving(body, start), 60) is not None and who(gate).get("holder") == "nav-1")
n1.send_signal(signal.SIGSTOP)
check("frozen, the socket still open: the lease runs out on the gate's own clock", wait_for(lambda: who(gate).get("holder") is None, LEASE_S + 6) is not None, who(gate))
time.sleep(1.5)
d = displacement(body, 1.5)
check("the gate stopped the robot when it expired the lease (truth: it stands)", d < 0.03, d)
n1.send_signal(signal.SIGCONT)
n1.wait(timeout=60)
r1 = last_json(tmp / "n1.out")
check("the navigator that wakes up is refused: lease ended, expired", n1.returncode == 4 and r1.get("status") == "interrupted"
      and r1.get("gate") == "lease_ended" and r1.get("reason") == "expired", (n1.returncode, r1))
d = displacement(body, 1.5)
check("and it did not move the robot again", d < 0.03 and who(gate).get("holder") is None, d)
proxy.stop()

print()
print("GATE SCENARIOS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
