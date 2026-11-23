"""A robot registered with no navigator (the NXT: no `payload`, no `navigator_api`) is refused by the runner's commands in one clear line,
naming the robot, before anything starts: lab-nav-server and lab-go used to die on `list(None)` (or, on the NXT's host file, on the
duck's `sockets`). The real registration of robots/nxt-shooterbot, a test installation and host file; nothing starts.
Run: cd libs/runner && uv run python tests/test_no_navigator.py"""

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import simhost
from labrunner import remote, robots
from labrunner.navapi import NavRunner
from runfile import installation, truthcopy

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


REPO = Path(__file__).resolve().parents[3]
tmp = Path(tempfile.mkdtemp(prefix="no-navigator-"))
atexit.register(shutil.rmtree, tmp, True)
inst = tmp / "installation.json"
inst.write_text(json.dumps({"installation": 1, "robots": {"nxt-shooterbot": {"registration": str(REPO / "robots" / "nxt-shooterbot" / "registration.json")}}}))
host_file = tmp / "host.json"
host_file.write_text(json.dumps({"host": 1, "kind": "nxt-kinematic-sim", "robot": "nxt-1", "state": str(tmp / "state"),
                                 "nxt_web": {"url": "http://127.0.0.1:1", "project": str(tmp)}, "scene": str(REPO / "scenes" / "apartment" / "scene.json"),
                                 "start": [0, 2, 1.5707963], "params": None}))
os.environ[installation.ENV] = str(inst)
robots.select("nxt-shooterbot")
host = simhost.load(host_file)
# a duck-style host (sockets, no truth), as the runner's own tests stand one in: on it the runner got as far as `list(None)`
duckish = types.SimpleNamespace(truth_port=None, source=host_file, sockets={k: tmp / f"{k}.sock" for k in ("robot", "depth", "map", "gate", "camera")})


def refused(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e.code)
    return None


WHY = "robot 'nxt-shooterbot' has no navigator API"
for kind in ("NAVIGATOR_API", "PAYLOAD"):
    said = refused(lambda: robots.navigator_command(kind))
    check(f"{kind}: the registry's answer is a refusal that names the robot and says it has no navigator API, not a None", said is not None and WHY in said, said)

said = refused(lambda: NavRunner(duckish, tmp / "data", tmp / "out"))
check("lab-nav-server's runner refuses before it starts anything (no camera, no process, no output folder)", said is not None and WHY in said
      and not (tmp / "out").exists(), said)
said = refused(lambda: remote.Remote(duckish, tmp / "run", "apartment", "go-1", tmp / "data", "nxt-shooterbot/apartment/go-1", truthcopy.TruthLog(tmp / "t.jsonl")))
check("the payload's remote refuses the same way, not on list(None)", said is not None and WHY in said, said)

env = dict(os.environ, ROBOTICS_LAB_HOST=str(host_file))
for cmd in ([sys.executable, "-m", "labrunner.navapi", "--robot", "nxt-shooterbot", "--data", str(tmp / "d1"), "--out", str(tmp / "o1")],
            [sys.executable, "-m", "labrunner.go", "1", "1", "--robot", "nxt-shooterbot", "--miniview-data", str(tmp / "d2"), "--out", str(tmp / "o2")]):
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    check(f"{cmd[2].rsplit('.', 1)[1]} on the command line: exit 1, one line naming the robot, no traceback",
          p.returncode == 1 and WHY in p.stderr and "Traceback" not in p.stderr, (p.returncode, p.stderr[-300:]))

print("test_no_navigator", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
