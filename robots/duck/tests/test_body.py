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
fake = types.SimpleNamespace(robot_sock="/nowhere", client="lab-go", _sid=1, _t0=0.0, _closing=closing,
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

print("BODY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
