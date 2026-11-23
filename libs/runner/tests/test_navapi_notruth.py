"""lab-nav-server on a host with and without the truth (phase 5, "Before step 6"): the host file's `truth_port: null` is the one signal.
With truth: the camera server, `--camera`, a sampler, a TruthLog, a TruthGuard and the truth_connections check per goal. Without: none
of them, the official copy made unpaired. A stand-in robot, host and navigator process: nothing starts.
Run: cd libs/runner && uv run python tests/test_navapi_notruth.py"""

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

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="navapi-notruth-"))
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

made = {"camera": [], "popen": [], "sampler": [], "guard": [], "copy": [], "connections": [], "api": []}


class Camera:
    def __init__(self, host, sock):
        self.path = Path(sock)
        made["camera"].append(self)

    def start(self):
        return self

    def stop(self):
        pass


class Proc:
    pid, returncode = 4242, None

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        made["popen"].append(self)

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, t=None):
        pass


class Sampler:
    def __init__(self, host, on_sample):
        self.samples, self.error = 1, None
        made["sampler"].append(self)

    def start(self):
        pass

    def stop(self):
        pass

    clock = lambda self: None                # noqa: E731 - no simulated time here: no clock, no rtf_low
    rtf_low = lambda self, below=0.95: None  # noqa: E731


class Guard:
    checked = ["contact"]

    def __init__(self, guardrails, profile=None, scene=None):
        made["guard"].append(guardrails)

    def check(self, pose, z):
        return None


def copy(src, dst, key, truth, run=None):
    c = types.SimpleNamespace(truth=truth, run=run, finish=lambda: None, pump=lambda: None, stats=lambda: {})
    made["copy"].append(c)
    return c


def connections(pid, port):
    made["connections"].append((pid, port))
    return 1


def api(self, method, params=None):
    made["api"].append((method, params))
    if method == "hello":
        return {"name": "rover", "version": "1", "contract": CONTRACT, "kinds": [], "camera": False}
    if method == "goal.start":
        return {"run_key": f"rover/apartment/g{self.goals}", "profile": None}
    return {}


reals = {n: getattr(navapi, n) for n in ("CameraServer", "Sampler", "TruthGuard", "TruthCopy", "truth_connections")}
real_module = registry.module
real_get, real_popen, real_api, real_connect, real_start = (robots.get, navapi.subprocess.Popen, navapi.NavRunner.api,
                                                             navapi.NavRunner._connect, navapi.GoalWatch.start)
robots.get = lambda name=None: fake
registry.module = lambda name, inst=False: fake
navapi.subprocess.Popen = Proc
navapi.CameraServer, navapi.Sampler, navapi.TruthGuard, navapi.TruthCopy, navapi.truth_connections = Camera, Sampler, Guard, copy, connections
navapi.NavRunner.api, navapi.NavRunner._connect = api, lambda self: None
navapi.GoalWatch.start = lambda self: self
os.environ[installation.ENV] = str(tmp / "installation-missing.json")
robots._resolved.clear()


variants = []
real_read = robots.read_profile


def read_profile(path, variant="sim"):
    variants.append(variant)
    return real_read(path, variant)


def with_variant(value):
    """The installation, naming the robot's variant (or not)."""
    f = tmp / f"installation-{value}.json"
    f.write_text(json.dumps({"installation": 1, "robots": {"rover": {"variant": value} if value else {}}}))
    os.environ[installation.ENV] = str(f)


def host(truth):
    return types.SimpleNamespace(source=tmp / "host.json", truth_port=7000 if truth else None,
                                 sockets={"depth": tmp / "d.sock", "map": tmp / "m.sock", "camera": tmp / "c.sock",
                                          "gate": tmp / "g.sock"})


def runner(truth, name):
    for k in made:
        made[k].clear()
    try:
        r = navapi.NavRunner(host(truth), tmp / "data", tmp / name)
    except Exception as e:      # noqa: BLE001 - said by the check, not a crash of the script
        return None, f"{type(e).__name__}: {e}"
    return r, None


def goal(r, guardrails):
    r.goal = None
    r.call("goal.start", {"kind": "point", "goal": [0, 0], "conditions": {"guardrails": guardrails}})
    return r.goal


try:
    # --- with truth: what it was, unchanged ----------------------------------------------------------------------------------
    r, err = runner(True, "truth")
    cmd = made["popen"][0].cmd if made["popen"] else []
    check("with truth: starts, serves the camera, and hands the navigator --camera", r is not None and len(made["camera"]) == 1
          and "--camera" in cmd and cmd[cmd.index("--camera") + 1] == str(tmp / "c.sock"), err or cmd)
    check("with truth: the navigator is given the robot's depth and map sockets", "--depth" in cmd and "--map" in cmd, cmd)
    g = goal(r, [{"name": "contact"}]) if r else None
    check("with truth: a goal has a sampler, a TruthLog, a TruthGuard, and its official copy is paired by the log",
          g is not None and g.sampler is not None and g.truth_log is not None and g.guard is not None
          and made["copy"][-1].truth == g.truth_log.nearest, [made["sampler"], made["guard"]])
    if g is not None:
        g._sample(types.SimpleNamespace(wall_ns=1, pose=(0, 0, 0), z=0.3, quat=(1, 0, 0, 0), sim_time=None))
    check("with truth: nothing is not enforced, the truth guard has the goal's guardrails", g is not None and getattr(g, "not_enforced", None) == [], g and getattr(g, "not_enforced", None))
    check("must fail: with truth the official run records judge_truth available, nothing unenforced",
          g is not None and made["copy"][-1].run.get("judge_truth") == {"available": True, "reason": None, "unenforced": []},
          made["copy"][-1].run)
    check("must fail: with truth the navigator is given the registration's profile (the installation names none)",
          "--profile" in cmd and cmd[cmd.index("--profile") + 1] == str(own), cmd)
    check("with truth: the navigator's connections to the truth are looked at", made["connections"] == [(4242, 7000)], made["connections"])
    if r:
        r.close()

    # --- without truth ---------------------------------------------------------------------------------------------------------
    r, err = runner(False, "notruth")
    cmd = made["popen"][0].cmd if made["popen"] else []
    check("must fail: a host with truth_port null starts (no ValueError)", r is not None, err)
    check("must fail: without truth no camera server is made and the navigator is given no --camera",
          r is not None and made["camera"] == [] and "--camera" not in cmd and "--depth" in cmd, cmd)
    g = goal(r, [{"name": "contact"}, {"name": "stuck"}]) if r else None
    check("must fail: without truth a goal has no sampler, no TruthLog, no TruthGuard", g is not None and g.sampler is None
          and g.truth_log is None and g.guard is None and made["sampler"] == [] and made["guard"] == [],
          (made["sampler"], made["guard"]))
    check("must fail: without truth the official copy is made, and pairs no tick",
          g is not None and made["copy"] and made["copy"][-1].truth(10 ** 9, 10 ** 8) is None, made["copy"])
    check("must fail: without truth the navigator is given the registration's profile too",
          "--profile" in cmd and cmd[cmd.index("--profile") + 1] == str(own), cmd)
    check("without truth there is no truth_connections check", made["connections"] == [], made["connections"])
    if g is not None:
        g.finish()
        s = json.loads((g.dir / "runner.json").read_text())
        check("without truth a goal finishes and its runner.json has no truth checked or sampled",
              s["truth_checked"] == [] and s["truth_samples"] == 0, s)
        check("must fail: without truth runner.json says truth is not available, and why",
              (s.get("judge_truth") or {}).get("available") is False and "truth_port is null" in ((s.get("judge_truth") or {}).get("reason") or ""),
              s.get("judge_truth"))
        check("must fail: the goal's record lists the truth guardrails it asked for and no one enforced, and only those",
              s.get("not_enforced") == ["contact"], s.get("not_enforced"))
    g = goal(r, [{"name": "fall"}, {"name": "no_go_area", "area": "a", "outline": []}, {"name": "fall"}, {"name": "drop_clearance", "m": 0.3},
                 {"name": "contact"}, {"name": "speed_cap"}]) if r else None
    check("must fail: every truth guardrail is listed once, in the order asked (fall, no_go_area, drop_clearance, contact)",
          g is not None and getattr(g, "not_enforced", None) == ["fall", "no_go_area", "drop_clearance", "contact"], g and getattr(g, "not_enforced", None))
    sent = [p for m, p in made["api"] if m == "goal.start"][-1]
    check("must fail: without truth goal.start tells the navigator which truth guardrails no one checks (contract 1.2)",
          sent.get("not_enforced") == ["fall", "no_go_area", "drop_clearance", "contact"], sent)
    check("must fail: without truth the official run records judge_truth: not available, the unenforced listed",
          made["copy"][-1].run.get("judge_truth") == {"available": False, "reason": f"truth_port is null in {tmp / 'host.json'}",
                                                      "unenforced": ["fall", "no_go_area", "drop_clearance", "contact"]},
          made["copy"][-1].run)
    goal(r, [{"name": "stuck"}])
    sent = [p for m, p in made["api"] if m == "goal.start"][-1]
    check("and says nothing when every guardrail is the navigator's own (a 1.1 navigator sees the goal it always saw)",
          "not_enforced" not in sent and sent.get("conditions") == {"guardrails": [{"name": "stuck"}]}, sent)
    g = goal(r, []) if r else None
    check("a goal with no truth guardrail has nothing not enforced", g is not None and getattr(g, "not_enforced", None) == [], g and getattr(g, "not_enforced", None))
    if r:
        r.close()

    # --- the variant: the installation's, else sim with truth and the base (real) profile without -----------------------------------
    robots.read_profile, navapi.robots.read_profile = read_profile, read_profile
    for truth, installed, want in ((True, None, "sim"), (False, None, "real"), (True, "real", "real"), (False, "sim", "sim")):
        with_variant(installed)
        variants.clear()
        r, err = runner(truth, f"variant-{truth}-{installed}")
        cmd = made["popen"][0].cmd if made["popen"] else []
        handed = cmd[cmd.index("--variant") + 1] if "--variant" in cmd else None
        if r:
            goal(r, [])
            r.close()
        what = ("with" if truth else "without") + " truth, " + (f"the installation names {installed}" if installed else "none named")
        check(f"must fail: {what}: the navigator is given --variant {want}", handed == want, handed or err)
        check(f"must fail: {what}: the referee reads variant {want}", variants == [want], variants)
finally:
    robots.read_profile = real_read
    robots.get, navapi.subprocess.Popen, navapi.NavRunner.api, navapi.NavRunner._connect = real_get, real_popen, real_api, real_connect
    navapi.GoalWatch.start, registry.module = real_start, real_module
    for n, v in reals.items():
        setattr(navapi, n, v)
    robots._resolved.clear()
    os.environ.pop(installation.ENV, None)

print()
print("NAVAPI NO TRUTH", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
