"""What a run records of its own build and of the commands it sent (RFC-0025 section 3.7, the eval harness's build identity): the
runner's `--depth-impairment SEED` reaching the navigator through the payload and the navigator API (and refused for the real duck),
and each command's requested and applied values, differing when the speed cap applies, the follower's `vx` kept as it was. No simulator.
Run: cd robots/duck && uv run python tests/test_run_identity.py"""

import subprocess
import sys
import tempfile
import types
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab import payload
from duck_lab.nav import run as nav_run
from duck_lab.nav import server
from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import RunLog
from duck_lab.plugins.tof8x8 import Tof8x8

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="run-identity-"))
STUB = {"robot": "/nonexistent/robot.sock", "depth": "/nonexistent/tof.sock", "map": "/nonexistent/map.sock"}
real = {k: getattr(nav_run, k) for k in ("Rpc", "StateStream")}
real_open = Tof8x8.open
Tof8x8.open = lambda self, path: None
for k in real:
    setattr(nav_run, k, lambda *a, **kw: type("Stub", (), {"close": lambda self: None, "latest": None})())


def sim_payload(name, **kw):
    return payload.Payload(STUB, tmp / name, tmp / "data", "apartment", name, "sim", **kw)


try:
    # ---- the impairment from the runner: payload and navigator API -------------------------------------------------------------
    plain = sim_payload("plain")
    check("a payload with no option runs the profile's setting: the impairment off", plain.nav.range.impairment.enabled is False)
    on = sim_payload("on", depth_impairment=5)
    imp = on.nav.range.impairment
    check("the payload's depth_impairment reaches its navigator: enabled, with that seed", imp.enabled and imp.seed == 5, imp.record())
    try:
        payload.Payload(STUB, tmp / "real", tmp / "data", "apartment", "real", None, depth_impairment=5)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: the payload for the real duck refuses it", refused)
    cli = subprocess.run([sys.executable, "-m", "duck_lab.payload", "--robot", "r", "--depth", "d", "--map", "m", "--listen", str(tmp / "p.sock"),
                          "--out", str(tmp / "cli"), "--data", str(tmp / "cli-data"), "--scene", "apartment", "--name", "n",
                          "--variant", "real", "--depth-impairment", "5"], capture_output=True, text=True, timeout=120)
    check("must fail: duck-payload --variant real --depth-impairment is refused at the command line, before anything starts",
          cli.returncode == 2 and "simulator" in cli.stderr and not (tmp / "cli").exists(), (cli.returncode, cli.stderr[-200:]))

    taken = {}

    class Caught(Exception):
        pass

    def navigator(**kw):
        taken.update(kw)
        raise Caught()

    real_nav = server.Navigator
    server.Navigator = navigator
    try:
        srv = server.NavServer(STUB, tmp / "data2", tmp / "out2", depth_impairment=7)
        try:
            server.GoalRun(srv, {"kind": "point", "params": {"x": 1.0, "y": 0.0}, "goal_run": {"id": 1}}).start()
        except Caught:
            pass
    finally:
        server.Navigator = real_nav
    check("the navigator API hands every goal's navigator the setting: enabled, with its seed",
          taken.get("depth_impairment") == {"enabled": True, "seed": 7}, taken)
    try:
        server.NavServer(STUB, tmp / "d", tmp / "o", variant=None, depth_impairment=7)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: the navigator API for the real duck refuses it", refused)

    # ---- the command sent: requested and applied ---------------------------------------------------------------------------------
    nav = Navigator(STUB, calibration="sim", log=tmp / "ticks.jsonl")
    sent, rows = [], []
    nav.locomotion.command = lambda vx, vyaw: sent.append((vx, vyaw))
    nav.localisation.pose = lambda: (1.0, 2.0, 0.3)
    nav._tilt = lambda: None
    nav.record = lambda **row: rows.append(row)

    nav.speed_cap = None
    nav.move(Twist(0.2, 0.5))
    r = rows[-1]
    check("no cap: the requested and the applied command are the same, and the existing fields are as before",
          r["requested"] == {"vx": 0.2, "vyaw": 0.5} and r["applied"] == {"vx": 0.2, "vyaw": 0.5} and r["vx"] == 0.2 and r["vyaw"] == 0.5
          and sent[-1] == (0.2, 0.5), r)
    nav.speed_cap = 0.1
    nav.move(Twist(0.2, 0.5))
    r = rows[-1]
    check("a speed cap of 0.1: requested vx 0.2, applied vx 0.1, which is what the robot was sent; yaw is not capped",
          r["requested"] == {"vx": 0.2, "vyaw": 0.5} and r["applied"] == {"vx": 0.1, "vyaw": 0.5} and sent[-1] == (0.1, 0.5), (r, sent[-1]))
    check("and `vx` keeps its meaning, the follower's command (0.2), not the capped one", r["vx"] == 0.2, r["vx"])
    nav.move(Twist(-0.2, 0.0))
    check("a backward command is capped the same way", rows[-1]["requested"]["vx"] == -0.2 and rows[-1]["applied"]["vx"] == -0.1, rows[-1])
    nav.move(Twist())
    check("a stop is a stop in both", rows[-1]["requested"] == rows[-1]["applied"] == {"vx": 0.0, "vyaw": 0.0}, rows[-1])
    nav.speed_cap = 0.3
    nav.move(Twist(0.2, 0.0))
    check("a cap above the command changes nothing", rows[-1]["requested"] == rows[-1]["applied"], rows[-1])
finally:
    Tof8x8.open = real_open
    for k, v in real.items():
        setattr(nav_run, k, v)

# ---- in the format 2 run: additive, beside the tick's own `cmd` -----------------------------------------------------------------
rl = RunLog(tmp / "obs", "apartment", "cmd1", "exploration", None)
sid = rl.new_session()
rl.row(sid, {"t": 0.1, "pose": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.5, "requested": {"vx": 0.2, "vyaw": 0.5},
             "applied": {"vx": 0.1, "vyaw": 0.5}})
rl.row(sid, {"t": 0.2, "pose": [0.0, 0.0, 0.0], "vx": 0.2, "vyaw": 0.5})
ticks = [p for _, k, p in Follower(rl.finish().parent, keep_raw=True).poll() if k == "tick"]
check("the run's tick keeps `cmd` as the follower's [0.2, 0.5] and carries requested and applied beside it",
      len(ticks) == 2 and ticks[0]["cmd"] == [0.2, 0.5] and ticks[0]["raw"].get("applied") == {"vx": 0.1, "vyaw": 0.5}
      and ticks[0]["raw"].get("requested") == {"vx": 0.2, "vyaw": 0.5}, ticks[0] if ticks else ticks)
check("an old tick, without them, reads as it did", ticks[1]["cmd"] == [0.2, 0.5] and "applied" not in ticks[1]["raw"], ticks[1])

print()
print("RUN IDENTITY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
