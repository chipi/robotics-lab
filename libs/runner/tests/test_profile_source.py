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
from runfile import installation, scenefile
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
           "control": {}, "footprint": {"radius_m": 0.1, "height_m": 0.2, "overhead_clear_m": 0.3, "goal_clearance_m": 0.3},
           "judge": {"fall_z_m": 0.05, "drop_margin_m": 0.15, "reached_m": 0.25, "bounds_margin_m": 0.05},
           "locomotion": {"cruise_mps": 0.3},
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

# --- the referee reads the version the navigator runs (the operator's decision e) ----------------------------------------
from runfile.profile import checksum  # noqa: E402

(folder / "current").write_text("2\n")
inst_file = tmp / "installation-store.json"
inst_file.write_text(json.dumps({"installation": 1, "robots": {"rover": {"profile": str(folder)}}}))
os.environ[installation.ENV] = str(inst_file)
robots.get = lambda name=None: fake
from labrunner import navapi  # noqa: E402 - its course modules read the robot (the stand-in) when imported
from labrunner.guard import TruthGuard  # noqa: E402
robots._resolved.clear()
sum1, sum2 = checksum(json.loads((folder / "1.json").read_text())), checksum(json.loads((folder / "2.json").read_text()))
try:
    judged = robots.profile("sim")
    check("the referee's profile is the installation's current version, not the robot's own file",
          robots.profile_file() == folder / "2.json" and judged.locomotion.cruise_mps == 0.25, robots.profile_file())
    check("it says which: path, checksum, version, and the schema version the checksum was taken in",
          judged.meta == {"path": str(folder / "2.json"), "checksum": sum2, "version": 2, "profile_version": 1}, judged.meta)
    store.use("rover", 1)
    check("resolved once in a course's process: a version chosen after it started does not part the referee from its navigator",
          robots.profile_file() == folder / "2.json" and robots.given_profile() == folder / "2.json")

    # a course's runner hands its navigator the referee's file, never the folder (which the navigator would read again)
    seen = {}

    class Started(Exception):
        pass

    def popen(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        raise Started()

    def copy(*a, run=None, **kw):
        seen["run"] = run
        return types.SimpleNamespace()

    remote.subprocess.Popen, real_copy = popen, remote.TruthCopy
    remote.TruthCopy = copy
    (tmp / "run2").mkdir()
    tempfile.tempdir = str(tmp)                          # the payload's socket folder, removed with the rest
    try:
        remote.Remote(host, tmp / "run2", "apartment", "r2", tmp / "data", "rover/apartment/r2",
                      truth_log=types.SimpleNamespace(nearest=None), run={"kind": "go-to"})
    except Started:
        pass
    finally:
        remote.subprocess.Popen, remote.TruthCopy = real_popen, real_copy
        tempfile.tempdir = None
    cmd = seen.get("cmd") or []
    handed = cmd[cmd.index("--profile") + 1] if "--profile" in cmd else None
    check("must fail: the navigator is handed the file the referee judges by, not the store's folder (version 2, though 1 is "
          "current now)", handed == str(folder / "2.json"), handed)
    env = seen.get("env") or {}
    check("must fail: the navigator's process does not inherit the installation file (the operator's decision i) nor the host "
          "file, while the runner has the installation's", installation.ENV in os.environ and installation.ENV not in env
          and "ROBOTICS_LAB_HOST" not in env and "PATH" in env, sorted(k for k in env if k.startswith("ROBOTICS")))
    apartment = scenefile.describe(scenefile.REPOSITORY / "apartment" / "scene.json")
    check("the official run records the referee's profile and the scene file it judges in beside the runner's own fields",
          seen.get("run") == {"kind": "go-to", "judge_profile": judged.meta, "judge_scene": apartment}, seen.get("run"))

    # lab-nav-server runs many goals: it reads the profile again at each goal.start
    goals, calls = [], []

    class Watch:
        def __init__(self, runner, key, guardrails, judge, theirs):
            goals.append((key, judge.meta, theirs))

        def start(self):
            return self

        def finish(self):
            pass

    real_watch, navapi.GoalWatch = navapi.GoalWatch, Watch
    runner = navapi.NavRunner.__new__(navapi.NavRunner)
    runner.goal, runner.goals, runner.route, runner.robot_name = None, 0, {"checks": 0, "max": None}, "rover"
    answer = {"checksum": sum1, "version": 1}

    def api(method, params=None):
        calls.append(method)
        return {"run_key": f"rover/apartment/g{len(goals)}", "profile": dict(answer)} if method == "goal.start" else {}

    runner.api = api
    runner._merge = lambda route: None
    try:
        runner.call("goal.start", {"kind": "point", "goal": [0, 0]})
        check("a goal is judged by the version current at its goal.start (version 1, chosen after the server started)",
              goals[-1][1]["version"] == 1 and goals[-1][1]["checksum"] == sum1 and goals[-1][2] == answer, goals[-1])
        store.use("rover", 2)
        runner.goal = None
        answer.update(checksum=sum2, version=2)
        runner.call("goal.start", {"kind": "point", "goal": [0, 0]})
        check("the next goal after a version is chosen: the referee reads it again (version 2)", goals[-1][1]["version"] == 2,
              goals[-1])
        runner.goal = None
        answer.update(checksum=sum1, version=1)          # the navigator read another version than the runner did
        calls.clear()
        try:
            runner.call("goal.start", {"kind": "point", "goal": [0, 0]})
            said = "no error"
        except RuntimeError as e:
            said = str(e)
        check("must fail: a navigator on another version than the referee read is cancelled and said, never judged by other numbers",
              "the profile changed while the goal started" in said and calls == ["goal.start", "goal.cancel"], (said, calls))
    finally:
        navapi.GoalWatch = real_watch
finally:
    robots.get = real_get
    robots._resolved.clear()
    os.environ.pop(installation.ENV, None)

# the gate's socket has one source (the second review's finding 5): the installation's, where Mission Control reads it, else the host's
robots.get = lambda name=None: fake
try:
    sim_host = types.SimpleNamespace(sockets={"gate": tmp / "host-gate.sock"})
    os.environ[installation.ENV] = str(tmp / "installation-none.json")
    check("no installation: the gate is the host file's", robots.gate_socket(sim_host) == tmp / "host-gate.sock")
    (tmp / "installation-gate.json").write_text(json.dumps({"installation": 1, "robots": {"rover": {"gate": str(tmp / "inst-gate.sock")}}}))
    os.environ[installation.ENV] = str(tmp / "installation-gate.json")
    check("must fail: the installation names the gate: lab-gate and lab-nav-server use it, not the host file's (one path with "
          "Mission Control's)", robots.gate_socket(sim_host) == tmp / "inst-gate.sock", robots.gate_socket(sim_host))
    (tmp / "installation-nogate.json").write_text(json.dumps({"installation": 1, "robots": {"rover": {"navigator": "127.0.0.1:9"}}}))
    os.environ[installation.ENV] = str(tmp / "installation-nogate.json")
    check("the robot in the installation with no gate named: the host file's", robots.gate_socket(sim_host) == tmp / "host-gate.sock")
finally:
    robots.get = real_get
    os.environ.pop(installation.ENV, None)

# the truth guard judges with the goal's profile: its footprint and fall height
big = types.SimpleNamespace(footprint=types.SimpleNamespace(radius_m=0.5), judge=types.SimpleNamespace(fall_z_m=0.3))
wall = [{"name": "wall", "type": "box", "pos": [1.0, 0.0, 0.0], "size": [0.1, 1.0, 0.5], "yaw": 0.0}]
rails = [{"name": "contact"}, {"name": "fall"}]
check("the truth guard's contact is the judged profile's footprint (0.5 m: 0.4 m from a wall is contact)",
      (TruthGuard(rails, (wall, []), profile=big).check((0.5, 0.0, 0.0), 1.0) or ("",))[0] == "contact")
check("and its fall height (0.3 m: a trunk at 0.2 m fell)", (TruthGuard(rails, ([], []), profile=big).check((0, 0, 0), 0.2) or ("",))[0] == "fall")

print()
print("PROFILE SOURCE", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
