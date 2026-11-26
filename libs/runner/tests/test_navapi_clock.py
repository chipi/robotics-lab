"""lab-nav-server's clock (phase 5 item 4b unit B8, RFC-0025 question 7): the simulator's time is kept beside the wall clock's, and a real-time
factor under the threshold is the anomaly `rtf_low`, told to the navigator once, with no verdict for the run. Stand-in robot, host, sampler
and navigator: nothing starts.
Run: cd libs/runner && uv run python tests/test_navapi_clock.py"""

import atexit
import json
import os
import shutil
import tempfile
import types
from pathlib import Path

from labrunner import navapi, robots
from runfile import installation, registry
from runfile.navcontract import CONTRACT
from runfile.truthcopy import TruthLog
from simhost import truth
from simhost.truth import RTF_LOW, Sampler as RealSampler

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="navapi-clock-"))
atexit.register(shutil.rmtree, tmp, True)
profile = {"profile_version": 1, "id": "rover", "label": "Rover", "kind": "rover",
           "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                         "physicalParameters": {"maximumSpeed": 0.5}},
           "control": {}, "footprint": {"radius_m": 0.1, "height_m": 0.2, "overhead_clear_m": 0.3, "goal_clearance_m": 0.3},
           "judge": {"fall_z_m": 0.05, "drop_margin_m": 0.15, "reached_m": 0.25, "bounds_margin_m": 0.05},
           "locomotion": {"cruise_mps": 0.3},
           "plugins": {"locomotion": "wheels@1"}, "variants": {"sim": {}, "real": {}}}
own = tmp / "own.json"
own.write_text(json.dumps(profile))
fake = types.SimpleNamespace(NAME="rover", PAYLOAD=["/bin/false"], NAVIGATOR_API=["rover-nav"], SIM=tmp, PROFILE=own)
sent = []
contract = [CONTRACT]
NOW = {"clock": {"sim_s": 10.0, "wall_s": 10.0, "rtf": 1.0}}


class Proc:
    pid, returncode = 4242, None

    def __init__(self, cmd, **kw):
        pass

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, t=None):
        pass


class Camera:
    def __init__(self, host, sock):
        self.path = Path(sock)

    def start(self):
        return self

    def stop(self):
        pass


class Sampler:
    """The clock the test says; the threshold's rule is the real one's."""

    def __init__(self, host, on_sample):
        self.samples, self.error = 1, None

    def start(self):
        pass

    def stop(self):
        pass

    def clock(self):
        return NOW["clock"]

    rtf = lambda self: (NOW["clock"] or {}).get("rtf")      # noqa: E731
    rtf_low = RealSampler.rtf_low


class Guard:
    checked = []

    def __init__(self, *a, **k):
        pass

    def check(self, pose, z):
        return None


def copy(src, dst, key, truth_, run=None):
    return types.SimpleNamespace(truth=truth_, run=run, finish=lambda: None, pump=lambda: None, stats=lambda: {})


def api(self, method, params=None):
    sent.append((method, params))
    if method == "hello":
        return {"name": "rover", "version": "1", "contract": contract[0], "kinds": [], "camera": False}
    if method == "goal.start":
        return {"run_key": f"rover/apartment/g{self.goals}", "profile": None}
    return {}


real_get, real_popen, real_api, real_connect, real_start = (robots.get, navapi.subprocess.Popen, navapi.NavRunner.api,
                                                             navapi.NavRunner._connect, navapi.GoalWatch.start)
real_module = registry.module
robots.get = lambda name=None: fake
registry.module = lambda name, inst=False: fake
navapi.subprocess.Popen = lambda cmd, *a, **kw: real_popen(cmd, *a, **kw) if cmd[0] == "git" else Proc(cmd, **kw)     # git: the run's build reads the commit
navapi.CameraServer, navapi.Sampler, navapi.TruthGuard, navapi.TruthCopy = Camera, Sampler, Guard, copy
navapi.truth_connections = lambda pid, port: 1
navapi.NavRunner.api, navapi.NavRunner._connect = api, lambda self: None
navapi.GoalWatch.start = lambda self: self
os.environ[installation.ENV] = str(tmp / "installation-missing.json")
robots._resolved.clear()
host = types.SimpleNamespace(source=tmp / "host.json", truth_port=7000, sockets={"depth": tmp / "d.sock", "map": tmp / "m.sock",
                             "camera": tmp / "c.sock", "gate": tmp / "g.sock"})


def goal(r):
    r.goal = None
    sent.clear()
    r.call("goal.start", {"kind": "point", "goal": [0, 0], "conditions": {"guardrails": []}})
    return r.goal


def told():
    return [p for m, p in sent if m == "goal.anomaly"]


try:
    r = navapi.NavRunner(host, tmp / "data", tmp / "out")
    check("the threshold is simhost's RTF_LOW (0.95) unless the runner is given another", r.rtf_low == RTF_LOW == 0.95, r.rtf_low)
    g = goal(r)
    g.check_clock()
    r.call("goal.status", {})
    check("a run at factor 1.0: the navigator is told nothing", told() == [] and g.rtf_low is None, told())

    NOW["clock"] = {"sim_s": 4.0, "wall_s": 4.0, "rtf": 0.5}
    g.check_clock()
    check("must fail: a factor of 0.5 in the first 4 s is not judged (the first samples are noise)", told() == [] and g.rtf_low is None, told())

    NOW["clock"] = {"sim_s": 7.2, "wall_s": 10.0, "rtf": 0.72}
    r.call("goal.status", {})
    g.check_clock()
    t = told()
    check("must fail: 0.72 after 10 s tells the navigator goal.anomaly rtf_low, with the clock and the threshold, in words",
          len(t) == 1 and t[0]["kind"] == "rtf_low" and t[0]["values"] == {"sim_s": 7.2, "wall_s": 10.0, "rtf": 0.72, "below": 0.95}
          and "0.72 of real time" in t[0]["summary"] and "no verdict" in t[0]["summary"], t)
    check("... the status poll tells it (a client that reads the run's end reads its rtf_low); it is held, so a second look tells nothing more",
          g.rtf_low is not None and len([m for m, _ in sent if m == "goal.anomaly"]) == 1, sent)
    g.finish()
    s = json.loads((g.dir / "runner.json").read_text())
    check("runner.json records the clock and says why the run has no verdict", s["clock"] == NOW["clock"]
          and s["no_verdict"] == "rtf_low: 0.72 under 0.95", {k: s.get(k) for k in ("clock", "no_verdict")})

    NOW["clock"] = {"sim_s": 9.6, "wall_s": 10.0, "rtf": 0.96}
    g = goal(r)
    g.check_clock()
    g.finish()
    s = json.loads((g.dir / "runner.json").read_text())
    check("must fail: 0.96 is not under 0.95: no anomaly, no 'no verdict', the clock still recorded",
          told() == [] and s["no_verdict"] is None and s["clock"]["rtf"] == 0.96, (told(), s["no_verdict"]))

    NOW["clock"] = {"sim_s": 9.6, "wall_s": 10.0, "rtf": 0.96}
    strict = navapi.NavRunner(host, tmp / "data", tmp / "out2", rtf_low=1.5)
    g = goal(strict)
    g.check_clock()
    check("a runner given --rtf-low 1.5 (the live test's way to prove the check) tells it at 0.96", len(told()) == 1 and told()[0]["values"]["below"] == 1.5, told())
    strict.close()

    contract[0] = "1.5"
    old = navapi.NavRunner(host, tmp / "data", tmp / "out3")
    g = goal(old)
    NOW["clock"] = {"sim_s": 7.0, "wall_s": 10.0, "rtf": 0.7}
    g.check_clock()
    g.finish()
    s = json.loads((g.dir / "runner.json").read_text())
    check("a 1.5 navigator cannot record it, so it is not asked (a method it does not have): runner.json still says no verdict",
          told() == [] and s["no_verdict"] == "rtf_low: 0.7 under 0.95", (told(), s["no_verdict"]))
    old.close()
    contract[0] = CONTRACT

    NOW["clock"] = None
    g = goal(r)
    g.check_clock()
    g.finish()
    s = json.loads((g.dir / "runner.json").read_text())
    check("a host with no simulated time (the NXT's) has no clock, and no check: nothing told, no verdict withheld",
          told() == [] and s["clock"] is None and s["no_verdict"] is None, s["clock"])

    from labrunner.challenge import clocked
    ok = {"pass": True, "failed": [], "status": "reached"}
    check("lab-challenge: a verdict stands at a good factor and is withheld under it (pass null, no_verdict says why, the rest kept)",
          clocked(ok, None) is ok and clocked(ok, {"sim_s": 7.2, "wall_s": 10.0, "rtf": 0.72})
          == {"pass": None, "failed": [], "status": "reached", "no_verdict": "rtf_low: 0.72 under 0.95"})
    log = TruthLog(tmp / "t.jsonl")
    log.add(1_000_000_000, (1.0, 2.0, 0.5), 0.1, (1, 0, 0, 0), sim_time=12.3456789)
    log.add(2_000_000_000, (1.0, 2.0, 0.5))
    log.close()
    lines = [json.loads(x) for x in (tmp / "t.jsonl").read_text().splitlines()]
    again = TruthLog.load(tmp / "t.jsonl")
    check("the truth log keeps the simulator's time beside the wall clock's in each sample, and reads it back",
          lines[0]["sim_time"] == 12.3457 and "sim_time" not in lines[1] and again.samples[0]["sim_time"] == 12.3457, lines)
    r.close()
finally:
    robots.get, registry.module, navapi.subprocess.Popen = real_get, real_module, real_popen
    navapi.NavRunner.api, navapi.NavRunner._connect, navapi.GoalWatch.start = real_api, real_connect, real_start

print()
print("NAVAPI CLOCK", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
