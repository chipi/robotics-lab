"""lab-nav-server's part of a calibration (contract 1.3): the navigator's calibration.* methods pass through, and with a truth the runner
samples the host's truth from the start, then adds `reference` (how far the truth says the robot went between the navigator's marks) to
the status of a procedure that is done. Without a truth the reference is null. The navigator never sees it. A stand-in sampler and
navigator: nothing starts. Run: cd libs/runner && uv run python tests/test_navapi_calibration.py"""

import types

from labrunner import navapi

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


T0, STEP_NS = 1_000_000_000_000, 50_000_000
made = []


class Sampler:
    """A truth that walks straight along x at 1 m/s, one sample each 50 ms for a second, handed over when it starts."""

    def __init__(self, host, on_sample):
        self.on_sample, self.stops = on_sample, 0
        made.append(self)

    def start(self):
        for i in range(21):
            self.on_sample(types.SimpleNamespace(wall_ns=T0 + i * STEP_NS, pose=(i * 0.05, 0.0, 0.0), z=0.3, quat=(1, 0, 0, 0)))
        return self

    def stop(self):
        self.stops += 1


real_sampler = navapi.Sampler
navapi.Sampler = Sampler
asked, answers = [], {}


def runner(truth):
    r = object.__new__(navapi.NavRunner)
    r.has_truth, r.host, r.calibration = truth, types.SimpleNamespace(truth_port=7000 if truth else None), None
    r.api = lambda method, params=None: (asked.append((method, params)), answers[method]())[1]
    return r


MARKS = [{"name": "start", "wall_ns": T0 + 2 * STEP_NS, "odom": [0, 0]}, {"name": "end", "wall_ns": T0 + 17 * STEP_NS, "odom": [0.8, 0]}]
DONE = {"state": "done", "procedure": "odometry_scale", "measured": {"odom_m": 0.8}, "marks": MARKS}
try:
    r = runner(True)
    answers.update({"calibration.list": lambda: {"procedures": [{"id": "odometry_scale"}]}, "calibration.start": lambda: {"ok": True},
                    "calibration.status": lambda: {"state": "running", "step": "walk"}, "calibration.cancel": lambda: {"ok": True}})
    check("calibration.list passes through unchanged", r.call("calibration.list", {}) == {"procedures": [{"id": "odometry_scale"}]})
    check("a start that was refused (busy, held) samples no truth", (answers.update({"calibration.start": lambda: {"error": {"code": "busy"}}}),
          r.call("calibration.start", {"procedure": "odometry_scale"}))[1] == {"error": {"code": "busy"}} and made == [])
    answers["calibration.start"] = lambda: {"ok": True}
    r.call("calibration.start", {"procedure": "odometry_scale"})
    check("a start that took samples the truth from then on, and passes the call on as it came",
          len(made) == 1 and asked[-1] == ("calibration.start", {"procedure": "odometry_scale"}), asked[-1])
    st = r.call("calibration.status", {})
    check("a status while it runs carries no reference", st == {"state": "running", "step": "walk"} and made[0].stops == 0, st)
    answers["calibration.status"] = lambda: dict(DONE)
    st = r.call("calibration.status", {})
    check("done: the reference is the truth's distance between the marks (0.75 m, from 0.1 to 0.85 on x), by truth",
          st["reference"] == {"by": "truth", "distance_m": 0.75, "from": [0.1, 0.0], "to": [0.85, 0.0]} and st["measured"] == {"odom_m": 0.8}, st)
    check("the sampler is stopped once the end is read, and a second poll of the same end answers the same, stopping nothing twice",
          r.call("calibration.status", {})["reference"]["distance_m"] == 0.75 and made[0].stops == 1)
    r.call("calibration.start", {"procedure": "odometry_scale"})
    check("the next start samples afresh", len(made) == 2 and made[1].stops == 0)
    answers["calibration.status"] = lambda: {"state": "cancelled", "reason": "x", "marks": MARKS}
    st = r.call("calibration.status", {})
    check("an end that is not done has no reference, and stops the sampler", "reference" not in st and made[1].stops == 1, st)
    answers["calibration.status"] = lambda: {**DONE, "marks": [{"name": "start", "wall_ns": T0 + 10 ** 12}, {"name": "end", "wall_ns": T0 + 10 ** 12 + 1}]}
    r.call("calibration.start", {"procedure": "odometry_scale"})
    check("marks the truth log has nothing near give a null reference, never a guess", r.call("calibration.status", {})["reference"] is None)
    r.call("calibration.start", {"procedure": "odometry_scale"})
    r.close = navapi.NavRunner.close.__get__(r)
    r.goal, r.rpc, r.proc, r.camera = None, None, types.SimpleNamespace(poll=lambda: 0), None
    r.log, r.sock, r.dir = types.SimpleNamespace(close=lambda: None), types.SimpleNamespace(unlink=lambda missing_ok: None), types.SimpleNamespace(rmdir=lambda: None)
    r.close()
    check("closing the runner stops a calibration's sampler", made[-1].stops == 1, made[-1].stops)

    made.clear()
    answers["calibration.status"] = lambda: dict(DONE)
    r = runner(False)
    r.call("calibration.start", {"procedure": "odometry_scale"})
    st = r.call("calibration.status", {})
    check("without a truth no sampler is made, and a done procedure's reference is null: the operator's tape is it",
          made == [] and st["reference"] is None and st["measured"] == {"odom_m": 0.8}, (made, st))
finally:
    navapi.Sampler = real_sampler

print()
print("NAVAPI CALIBRATION", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
