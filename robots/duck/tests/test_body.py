"""The run keeps the body (phase 5 item 3, RFC-0023 §7 step 2, the operator's decisions of 2026-11-23): per joint the commanded angle,
the velocity and the current as signals beside the measured angle, an empty list from robotd "not reported" (absent, never zero);
the state's loop rate, safety flags and movement limits on every tick; robot.health polled as signals, its verdict's changes as
events. Every name the navigator writes is declared in the run's signals. Run: cd robots/duck && uv run python tests/test_body.py"""

import math
import sys

from duck_lab.nav import body
from duck_lab.nav.runlog import JOINTS, SIGNALS

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


n = len(JOINTS)
state = {"joints": [0.1] * n, "targets": [0.2 + i for i in range(n)], "velocities": [-0.5] * n, "currents_ma": [120.0] * n,
         "loop": {"hz": 49.8, "missed": 3}, "move": {"requested": [0.2, 0, 0], "applied": [0.1, 0, 0], "limited_by": ["tilt", "ramp"]},
         "safety": {"fallen": False, "limp": False, "picked_up": True, "gravity": [0, 0, -1]}}
v = body.state_values(state)
check("per joint: the commanded angle, the velocity and the current, by name", v["joint_left_hip_yaw_target"] == 0.2
      and v[f"joint_{JOINTS[-1]}_target"] == 0.2 + n - 1 and v["joint_left_knee_vel"] == -0.5 and v["joint_mouth_ma"] == 120.0, v)
check("the loop's rate and misses, the safety flags as 0/1, the limits as text", v["loop_hz"] == 49.8 and v["loop_missed"] == 3
      and v["fallen"] == 0 and v["picked_up"] == 1 and v["limp"] == 0 and v["move_limited_by"] == "tilt,ramp", v)
quiet = body.state_values({**state, "velocities": [], "currents_ma": [], "move": {"limited_by": []}})
check("must fail: an empty list is not reported: absent, never zero",
      not any(k.endswith(("_vel", "_ma")) for k in quiet) and "joint_left_knee_target" in quiet, sorted(k for k in quiet if "knee" in k))
check("no limit is an empty text, not absent", quiet["move_limited_by"] == "")
short = body.state_values({**state, "targets": [0.0] * (n - 1)})
check("must fail: a list of the wrong length is not taken (robotd's joint order or count changed)",
      not any(k.endswith("_target") for k in short), [k for k in short if k.endswith("_target")][:3])
check("an old state message (no loop, safety or move): nothing invented", body.state_values({"joints": [0.0] * n}) == {})
nan = body.state_values({**state, "velocities": [math.nan] * n})
check("a value that is not a number is left out", not any(k.endswith("_vel") for k in nan))

health = {"healthy": True, "battery": {"volts": 7.4, "percent": 50.0}, "motors": {"hottest": "left_knee", "max_c": 32.0, "mean_c": 31.5},
          "cpu_temp_c": 48.2, "control_loop": {"target_hz": 50.0, "achieved_hz": 49.9, "ticks": 100, "missed": 2, "last_tick_age_ms": 4},
          "bus": {"consecutive_errors": 0, "startup_failures": 0, "missing": []}}
h = body.health_values(health)
check("health: verdict, battery, motors, CPU, loop and bus as signals", h == {
    "health_ok": 1, "health_degraded": 0, "battery_v": 7.4, "battery_pct": 50.0, "motor_hottest": "left_knee", "motor_max_c": 32.0,
    "motor_mean_c": 31.5, "cpu_temp_c": 48.2, "loop_target_hz": 50.0, "loop_achieved_hz": 49.9, "loop_tick_age_ms": 4,
    "bus_errors": 0, "bus_missing": 0}, h)
bare = body.health_values({"healthy": False, "degraded": True, "reason": "bus: servo 3 missing", "bus": {"missing": [3]}})
check("must fail: what robotd leaves out is absent, not zero (no battery, motors or CPU in this answer)",
      bare == {"health_ok": 0, "health_degraded": 1, "bus_errors": 0, "bus_missing": 1}, bare)
check("the verdict, for an event when it changes", body.health_verdict(health) == {"healthy": True, "degraded": False, "reason": None}
      and body.health_verdict({"healthy": False, "degraded": True, "reason": "x"}) == {"healthy": False, "degraded": True, "reason": "x"})

declared = {s["name"]: s for s in SIGNALS}
produced = set(v) | set(h) | set(bare) | set(quiet)
check("must fail: every name the navigator writes is declared in the run's signals", produced <= set(declared),
      sorted(produced - set(declared)))
text = {k for k in produced if isinstance({**v, **h, **quiet}.get(k), str)}
check("text values are declared as text, numbers as numbers", all(declared[k]["kind"] == ("text" if k in text else "number")
                                                                 for k in produced), [(k, declared[k]["kind"]) for k in produced if
                                                                                      declared[k]["kind"] != ("text" if k in text else "number")])
check("units: rad, rad/s, mA per joint", declared["joint_left_knee_target"]["unit"] == "rad"
      and declared["joint_left_knee_vel"]["unit"] == "rad/s" and declared["joint_left_knee_ma"]["unit"] == "mA")

# the health thread (Navigator._health) with a stand-in robot: polled until the run closes, the verdict's changes as events, a failed
# ask said once and retried
import threading  # noqa: E402
import types  # noqa: E402

from duck_lab.nav import run as navrun  # noqa: E402

answers = [health, health, {**health, "healthy": False, "degraded": True, "reason": "bus: servo 3 missing"}, OSError("gone"),
           OSError("gone"), {**health, "healthy": False, "degraded": True, "reason": "bus: servo 3 missing"}]
asked, opened, rows, sigs = [], [], [], []


class FakeRpc:
    def __init__(self, path, client=None):
        opened.append(client)

    def call(self, method, params=None):
        asked.append(method)
        a = answers[len(asked) - 1]
        if isinstance(a, Exception):
            raise a
        return a

    def close(self):
        pass


closing = threading.Event()
fake = types.SimpleNamespace(robot_sock="/nowhere", client="lab-go", _sid=1, _t0=0.0, _closing=closing, _body=None,
                             _stop_on_health=lambda h: None,
                             runlog=types.SimpleNamespace(signals=lambda sid, t, v: sigs.append(v)),
                             record=lambda **row: rows.append(row))
fake._closing.wait = lambda s: len(asked) >= len(answers)      # one ask per tick, closed after the last answer
real_rpc, navrun.Rpc = navrun.Rpc, FakeRpc
try:
    navrun.Navigator._health(fake)
finally:
    navrun.Rpc = real_rpc
events = [(r["healthy"], r["degraded"], r["reason"]) for r in rows]
check("health is asked on its own connection, named after the run's client", opened[0] == "lab-go-health" and set(asked) == {"robot.health"},
      opened)
check("each answer is kept as signals", len(sigs) == 4 and sigs[0]["battery_v"] == 7.4 and sigs[2]["health_ok"] == 0, len(sigs))
check("must fail: the verdict is an event when it changes, the first answer included, not every poll",
      events[:2] == [(True, False, None), (False, True, "bus: servo 3 missing")], events)
check("must fail: a failed ask is said once, the connection is opened again after each, and the next answer is an event even with "
      "the verdict as before", [e for e in events if e[2] and e[2].startswith("not asked")] == [(None, None, "not asked: OSError: gone")]
      and events[-1] == (False, True, "bus: servo 3 missing") and len(opened) == 3, (events, opened))

# the body's anomalies (phase 5 item 3 step 3): body.BodyWatch at the profile's joints.limits
from duck_lab.nav import anomaly as anom  # noqa: E402

LIM = {"current_ma": 100, "current_s": 1.0, "tracking_rad": 0.5, "tracking_s": 1.0, "hot_c": 60.0, "loop_min_hz": 45.0, "loop_slow_s": 2.0}
KNEE = JOINTS.index("left_knee")


def st(ma=10.0, err=0.0, hz=50.0, **over):
    cur = [10.0] * n
    cur[KNEE] = ma
    tg = [0.0] * n
    tg[KNEE] = err
    return {"joints": [0.0] * n, "targets": tg, "currents_ma": cur, "loop": {"hz": hz, "missed": 0}, **over}


def run_states(w, states, dt=0.1):
    return [a for i, s in enumerate(states) for a in w.state(i * dt, s)]


w = body.BodyWatch(LIM, JOINTS)
got = run_states(w, [st(ma=150)] * 25)
check("must fail: a joint at or over its current for the hold is joint_overload, said once a stretch",
      [a["kind"] for a in got] == ["joint_overload"] and got[0]["values"]["joint"] == "left_knee" and got[0]["margin"] == 50.0
      and got[0]["values"]["held_s"] == 1.0, got)
check("must fail: over the limit for less than the hold is nothing", run_states(body.BodyWatch(LIM, JOINTS), [st(ma=150)] * 10) == [])
again = run_states(w, [st(ma=10)] + [st(ma=150)] * 12, dt=0.1)
check("must fail: a new stretch after the current came back under is said again", [a["kind"] for a in again] == ["joint_overload"], again)
trk = run_states(body.BodyWatch(LIM, JOINTS), [st(err=0.7)] * 12)
check("must fail: a joint over its tracking error for the hold is joint_tracking, with the error and the margin",
      [a["kind"] for a in trk] == ["joint_tracking"] and trk[0]["values"]["error_rad"] == 0.7 and abs(trk[0]["margin"] - 0.2) < 1e-9, trk)
check("must fail: tracking_rad null (the real duck, not measured) checks no tracking and says so",
      run_states(body.BodyWatch({**LIM, "tracking_rad": None}, JOINTS), [st(err=2.0)] * 30) == []
      and "joint_tracking" in body.BodyWatch({**LIM, "tracking_rad": None}, JOINTS).checked()["not_checked"])
slow = run_states(body.BodyWatch(LIM, JOINTS), [st(hz=40.0)] * 22)
check("must fail: the loop under its rate for loop_slow_s is loop_slow", [a["kind"] for a in slow] == ["loop_slow"], slow)
check("must fail: nothing reported is nothing checked (empty currents, no loop): absent, never zero",
      run_states(body.BodyWatch(LIM, JOINTS), [{"joints": [0.0] * n, "targets": [0.0] * n, "currents_ma": []}] * 30) == [])
hw = body.BodyWatch(LIM, JOINTS)
hot = hw.health(0.0, {**health, "motors": {"hottest": "right_knee", "max_c": 63.0, "mean_c": 40.0}})
check("must fail: the hottest servo at or over hot_c is motor_hot, at once (a poll is 10 s)",
      [a["kind"] for a in hot] == ["motor_hot"] and hot[0]["values"]["joint"] == "right_knee", hot)
check("motor_hot is said once while it stays hot", hw.health(10.0, {**health, "motors": {"hottest": "right_knee", "max_c": 64.0}}) == [])
sick = {**health, "healthy": False, "degraded": True, "reason": "bus: servo 3 missing"}
v1 = hw.health(20.0, sick)
check("must fail: robotd not healthy is robot_unhealthy, major, said when it changes",
      [(a["kind"], a.get("severity")) for a in v1] == [("robot_unhealthy", "major")] and hw.health(30.0, sick) == [], v1)
deg = hw.health(40.0, {**health, "degraded": True, "reason": "battery low"})
check("degraded but healthy is minor", [(a["kind"], a.get("severity")) for a in deg] == [("robot_unhealthy", "minor")], deg)
check("healthy again, then sick: said again", hw.health(50.0, health) == [] and len(hw.health(60.0, sick)) == 1)
check("every body anomaly is a kind the record knows", all(anom.record(a["kind"], a["summary"], a.get("severity"), margin=a.get("margin"),
                                                                       values=a.get("values")) for a in got + trk + slow + hot + v1))

# stopping on its own health (phase 5 B2): body.StopWatch at the profile's hot_c and health block, from each health answer
def attempt(fn):
    try:
        return fn()
    except Exception as e:      # noqa: BLE001 - a missing piece is a failed check, not a crash
        return f"{type(e).__name__}: {e}"


def stops(**over):
    return body.StopWatch({"hot_c": 60.0}, {"battery_min_pct": 15.0, "battery_low_s": 10.0, **over})


low = {**health, "battery": {"volts": 6.7, "percent": 10.0}}
check("must fail: a healthy stub with a cool servo and half a battery is not a stop", attempt(lambda: stops().health(0.0, health)) is None)
hot_stop = attempt(lambda: stops().health(0.0, {**health, "motors": {"hottest": "right_knee", "max_c": 60.0, "mean_c": 40.0}}))
check("must fail: the hottest servo at hot_c is a stop, named motor_hot, with the servo and the temperature",
      isinstance(hot_stop, tuple) and hot_stop[0] == "motor_hot" and "right_knee" in hot_stop[1] and "60" in hot_stop[1], hot_stop)
check("must fail: just under hot_c is not a stop",
      attempt(lambda: stops().health(0.0, {**health, "motors": {"hottest": "right_knee", "max_c": 59.9}})) is None)
sw = attempt(stops)
first, second = attempt(lambda: sw.health(0.0, low)), attempt(lambda: sw.health(10.0, low))
check("must fail: a battery under the threshold is a stop, named battery_low, once it has held for battery_low_s (two polls), not at the first",
      first is None and isinstance(second, tuple) and second[0] == "battery_low" and "10" in second[1], (first, second))
sw2 = attempt(stops)
attempt(lambda: sw2.health(0.0, low))
attempt(lambda: sw2.health(5.0, health))
check("must fail: a battery that came back over the threshold starts the hold again", attempt(lambda: sw2.health(10.0, low)) is None)
check("must fail: a battery the robot does not report is not checked (absent, never zero)",
      attempt(lambda: stops(battery_low_s=0.0).health(0.0, {k: v for k, v in health.items() if k != "battery"})) is None)
unhealthy = attempt(lambda: stops().health(0.0, sick))
check("must fail: robotd not healthy is a stop, named robot_unhealthy, with its reason",
      isinstance(unhealthy, tuple) and unhealthy[0] == "robot_unhealthy" and "bus: servo 3 missing" in unhealthy[1], unhealthy)
check("must fail: degraded but healthy is not a stop (it is a minor anomaly)",
      attempt(lambda: stops().health(0.0, {**health, "degraded": True, "reason": "battery low"})) is None)

# the profile: the real duck's limits in the base (Pollen's numbers, tracking not measured), the simulator's in variants.sim
from pathlib import Path  # noqa: E402

from runfile.profile import load_profile  # noqa: E402

PROFILE = Path(__file__).resolve().parents[1] / "profile.json"
real, sim = load_profile(PROFILE, "real").get("joints.limits"), load_profile(PROFILE, "sim").get("joints.limits")
check("the real duck: Pollen's numbers (900 mA of the servo's 1000, hot at 60 C), tracking not measured (null)",
      real["current_ma"] == 900 and real["hot_c"] == 60.0 and real["tracking_rad"] is None, real)
check("the simulator: its own current (the stand-in's scale) and a tracking limit; the rest the base's",
      sim["current_ma"] == 120 and sim["tracking_rad"] == 0.5 and sim["hot_c"] == 60.0 and sim["loop_min_hz"] == 45.0, sim)

# the navigator raises them: the state stream and the health thread hand each found anomaly to Navigator.anomaly
raised = []
nav = types.SimpleNamespace(_body=body.BodyWatch({**LIM, "current_s": 0.0}, JOINTS), anomaly=lambda kind, summary, **f: raised.append(kind))
for _ in range(15):
    navrun.Navigator._check_body(nav, st(ma=150))
check("must fail: the state stream's check raises joint_overload through Navigator.anomaly", raised == ["joint_overload"], raised)
broken = types.SimpleNamespace(_body=types.SimpleNamespace(state=lambda t, s: 1 / 0), anomaly=lambda **f: None)
navrun.Navigator._check_body(broken, st())
check("a failing watch stops itself and never the state stream", broken._body is None)
answers = [sick]
asked.clear()
rows.clear()
raised.clear()
fake._body, fake.anomaly = body.BodyWatch(LIM, JOINTS), lambda kind, summary, **f: raised.append(kind)
fake._closing.wait = lambda s: len(asked) >= len(answers)
real_rpc, navrun.Rpc = navrun.Rpc, FakeRpc
try:
    navrun.Navigator._health(fake)
finally:
    navrun.Rpc = real_rpc
check("must fail: the health thread raises robot_unhealthy beside its robot_health event", raised == ["robot_unhealthy"]
      and [r.get("healthy") for r in rows] == [False], (raised, rows))
handed = []
answers = [sick]
asked.clear()
rows.clear()
fake._stop_on_health = handed.append
fake._closing.wait = lambda s: len(asked) >= len(answers)
real_rpc, navrun.Rpc = navrun.Rpc, FakeRpc
try:
    navrun.Navigator._health(fake)
finally:
    navrun.Rpc = real_rpc
check("must fail: the health thread hands each answer to the stop check, after the anomalies", handed == [sick], handed)

# the navigator API serves them live (contract 1.1): the navigator's own record hands each anomaly row, once written, to on_anomaly
heard, written = [], []
rec_nav = types.SimpleNamespace(on_decision=None, on_anomaly=heard.append, _log=None, _sid=1, _t0=0.0, watch=None,
                                runlog=types.SimpleNamespace(row=lambda sid, row: written.append(row)))
navrun.Navigator._record(rec_nav, **anom.record("joint_overload", "left_knee over", values={"joint": "left_knee"}))
navrun.Navigator._record(rec_nav, event="leg", n=1)
check("must fail: an anomaly row is handed to on_anomaly after it is written, with its t; no other row is",
      [h["anomaly"] for h in heard] == ["joint_overload"] and "t" in heard[0] and len(written) == 2, heard)

print("BODY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
