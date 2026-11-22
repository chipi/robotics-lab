"""The runner reads a payload by the navigator contract (libs/runner/CONTRACT.md): a stand-in payload, its own process, answers as
its environment says, and the runner (labrunner.remote.Remote) gives its goals in the contract's shape, takes its ends as the
course's status, breaks a goal with goal.break, and refuses (the must-fail cases) another major version of the contract and a
state the contract does not have. No robot's package: a stand-in registration. Run: cd libs/runner && uv run python tests/test_remote_contract.py"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import types
from pathlib import Path

from labrunner import remote, robots
from runfile import installation
from runfile.navcontract import ContractError

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="remote-contract-"))
atexit.register(shutil.rmtree, tmp, True)
SEEN = tmp / "seen.jsonl"
STAND_IN = tmp / "stand_in.py"
STAND_IN.write_text('''
import argparse, json, os, socketserver
ap = argparse.ArgumentParser()
ap.add_argument("--listen")
a, _ = ap.parse_known_args()
seen = open(os.environ["SEEN"], "a")
class H(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            req = json.loads(line)
            m, p = req["method"], req.get("params") or {}
            seen.write(json.dumps([m, p]) + "\\n"); seen.flush()
            if m == "hello":
                r = {"name": "stand-in", "version": "0", "contract": os.environ["CONTRACT"], "kinds": ["point"], "camera": False}
            elif m == "goal.start":
                r = {"run_key": "rover/apartment/c1"}
            elif m == "goal.status":
                r = {"state": os.environ["STATE"], "reason": "said by the stand-in", "result": {"time_s": 1.0}, "broken": None,
                     "pose": [0, 0, 0]}
            else:
                r = {"ok": True}
            self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": r}) + "\\n").encode()); self.wfile.flush()
            if m == "stop":
                os._exit(0)
socketserver.UnixStreamServer(a.listen, H).serve_forever()
''')

profile = {"profile_version": 1, "id": "rover", "label": "Rover", "kind": "rover",
           "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                         "physicalParameters": {"maximumSpeed": 0.5}},
           "control": {}, "footprint": {"radius_m": 0.1, "height_m": 0.2, "overhead_clear_m": 0.3, "goal_clearance_m": 0.3},
           "judge": {"fall_z_m": 0.05, "drop_margin_m": 0.15, "reached_m": 0.25, "bounds_margin_m": 0.05},
           "locomotion": {"cruise_mps": 0.3}, "plugins": {"locomotion": "wheels@1"}, "variants": {"sim": {}, "real": {}}}
own = tmp / "own.json"
own.write_text(json.dumps(profile))
fake = types.SimpleNamespace(NAME="rover", PAYLOAD=[sys.executable, str(STAND_IN)], NAVIGATOR_API=["/bin/false"], SIM=tmp, PROFILE=own)
robots.get = lambda name=None: fake
(tmp / "installation.json").write_text(json.dumps({"installation": 1, "robots": {"rover": {"profile": str(own)}}}))
os.environ[installation.ENV] = str(tmp / "installation.json")
robots._resolved.clear()


class Copy:
    rec, follower = None, types.SimpleNamespace(dir=tmp / "no-run")

    def __init__(self, *a, **kw):
        pass

    def pump(self):
        pass


remote.TruthCopy = Copy
host = types.SimpleNamespace(sockets={"robot": tmp / "r.sock", "depth": tmp / "d.sock", "map": tmp / "m.sock"}, truth_port=1)
tempfile.tempdir = str(tmp)                           # the payload's socket folder, removed with the rest


def payload(contract: str, state: str, n: int):
    os.environ.update(SEEN=str(SEEN), CONTRACT=contract, STATE=state)
    SEEN.write_text("")
    out = tmp / f"run{n}"
    out.mkdir()
    return remote.Remote(host, out, "apartment", f"c{n}", tmp / "data", f"rover/apartment/c{n}", truth_log=types.SimpleNamespace(nearest=None),
                         payload=fake.PAYLOAD)


def seen() -> list:
    return [json.loads(line) for line in SEEN.read_text().splitlines()]


try:
    payload("2.0", "reached", 1)
    said = "not refused"
except ContractError as e:
    said = str(e)
check("must fail: a payload speaking another major version of the contract is refused, both versions said", "2.0" in said
      and "1.0" in said, said)

nav = payload("1.0", "stopped_by_guardrail", 2)
nav.break_goal("contact", "touched the box")
out = nav.go_to((1.5, -0.5), 7)
calls = seen()
start = next((p for m, p in calls if m == "goal.start"), None)
check("a point goal is given in the contract's shape: params x, y and conditions.done_when.within_s",
      start == {"kind": "point", "params": {"x": 1.5, "y": -0.5}, "conditions": {"done_when": {"within_s": 7.0}}}, start)
check("the goal's end is the course's status, its reason the course's why", out["status"] == "stopped_by_guardrail"
      and out["why"] == "said by the stand-in" and out["time_s"] == 1.0, out)
check("a guardrail the runner checks by the truth breaks the goal with goal.break, naming it",
      ["goal.break", {"name": "contact", "detail": "touched the box"}] in calls, calls)
check("the old methods are not called", not any(m in ("start", "status", "cancel") for m, _ in calls), [m for m, _ in calls])
nav.close()

nav = payload("1.0", "aborted", 3)
box = ["still polling after 10 s: a state that is not an end was waited on"]


def goal():
    try:
        nav.go_to((1.0, 0.0), 5)
        box[0] = "taken"
    except remote.PayloadError as e:
        box[0] = str(e)


t = threading.Thread(target=goal, daemon=True)
t.start()
t.join(10.0)
said = box[0]
nav.close()
check("must fail: a state the contract does not have is the payload's error, naming the state", "'aborted'" in said, said)

nav = payload("1.7", "done", 4)
check("a minor version of the contract is taken", nav.name == "stand-in")
r = nav.explore(1.0, objects=True)
start = next((p for m, p in seen() if m == "goal.start"), None)
check("an explore goal is given as budget.minutes, its options as params", start == {"kind": "explore", "params": {"objects": True},
                                                                                     "budget": {"minutes": 1.0}}, start)
check("an explore that ends done answers its result", r == {"time_s": 1.0}, r)
nav.close()
tempfile.tempdir = None

print()
print("REMOTE CONTRACT", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
