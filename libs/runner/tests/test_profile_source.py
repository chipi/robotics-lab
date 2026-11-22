"""Which profile a robot runs on this machine (phase 5 step 1, labrunner.robots.profile_source): none named, the robot's own (no
--profile); a version's file; the version store's folder, its current version; and, the must-fail case, a named profile that does
not exist refuses the robot before any navigator process starts (no silent fallback). No robot's package: a stand-in registration.
Run: cd libs/runner && uv run python tests/test_profile_source.py"""

import atexit
import json
import os
import shutil
import tempfile
import types
from pathlib import Path

from labrunner import remote, robots
from labrunner.robots import ProfileSourceError, profile_source
from runfile import installation
from runfile.profilestore import Store, resolve

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="profile-source-"))
atexit.register(shutil.rmtree, tmp, True)


def inst(robots_):
    p = tmp / f"installation-{len(list(tmp.glob('installation-*')))}.json"
    p.write_text(json.dumps({"installation": 1, "robots": robots_}))
    return installation.load(p)


profile = {"profile_version": 1, "id": "rover", "label": "Rover", "kind": "rover",
           "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                         "physicalParameters": {"maximumSpeed": 0.5}},
           "control": {}, "footprint": {"radius_m": 0.1, "height_m": 0.2}, "locomotion": {"cruise_mps": 0.3},
           "plugins": {"locomotion": "wheels@1"}, "variants": {"sim": {}, "real": {}}}
own = tmp / "own.json"
own.write_text(json.dumps(profile))

check("no installation file: the robot's own profile (no --profile)", profile_source("rover", None) is None)
check("the robot not in the installation: its own profile", profile_source("rover", inst({})) is None)
check("in it with no profile named: its own profile", profile_source("rover", inst({"rover": {"navigator": "127.0.0.1:8061"}})) is None)
check("a version's file named: that file", profile_source("rover", inst({"rover": {"profile": str(own)}})) == own)

store = Store(tmp / "state" / "profiles")
store.seed("rover", own)
v2 = json.loads(own.read_text())
v2["locomotion"]["cruise_mps"] = 0.25
store.save("rover", v2)
folder = tmp / "state" / "profiles" / "rover"
check("the version store's folder named: the folder, handed on as it is (each run reads its current version then)",
      profile_source("rover", inst({"rover": {"profile": str(folder)}})) == folder)
check("the folder's current version, as a run reads it: version 2", resolve(folder) == folder / "2.json")
store.use("rover", 1)
check("going back in the store changes what the next run reads, with no runner restarted", resolve(folder) == folder / "1.json")
check("a version's file named is read as it is", resolve(own) == own)


def refused(i, why):
    try:
        profile_source("rover", i)
    except ProfileSourceError as e:
        return why in str(e), str(e)
    return False, "not refused"


ok, why = refused(inst({"rover": {"profile": str(tmp / "missing.json")}}), "does not exist: refused")
check("must fail: a named file that does not exist is refused, never the robot's own instead", ok, why)
empty = tmp / "state" / "profiles" / "empty"
empty.mkdir()
ok, why = refused(inst({"rover": {"profile": str(empty)}}), "has no version yet")
check("a version store with no version yet is refused", ok, why)
(folder / "current").write_text("9\n")
ok, why = refused(inst({"rover": {"profile": str(folder)}}), "cannot say its current version")
check("a store whose current names a missing version is refused", ok, why)

# the runner refuses before any navigator process starts
fake = types.SimpleNamespace(NAME="rover", PAYLOAD=["/bin/false"], NAVIGATOR_API=["/bin/false"], SIM=tmp, PROFILE=own)
real_get, real_popen = robots.get, remote.subprocess.Popen
started = []
robots.get = lambda name=None: fake
remote.subprocess.Popen = lambda *a, **kw: started.append(a) or (_ for _ in ()).throw(AssertionError("a process was started"))
os.environ[installation.ENV] = str(tmp / "installation-missing.json")
(tmp / "installation-missing.json").write_text(json.dumps({"installation": 1, "robots": {"rover": {"profile": str(tmp / "nope.json")}}}))
host = types.SimpleNamespace(sockets={"robot": tmp / "r.sock", "depth": tmp / "d.sock", "map": tmp / "m.sock"}, truth_port=1)
try:
    try:
        remote.Remote(host, tmp / "run", "apartment", "r1", tmp / "data", "rover/apartment/r1", truth_log=None)
        said = "no error"
    except ProfileSourceError as e:
        said = str(e)
finally:
    robots.get, remote.subprocess.Popen = real_get, real_popen
    os.environ.pop(installation.ENV, None)
check("must fail: a course's runner with a missing named profile refuses, and starts no navigator", "does not exist" in said
      and started == [] and not (tmp / "run").exists(), (said, started))

print()
print("PROFILE SOURCE", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
