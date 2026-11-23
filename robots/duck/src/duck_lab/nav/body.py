"""The body as a run keeps it (phase 5 item 3, RFC-0023 §7 step 2, the operator's decisions of 2026-11-23): robotd's state and health
answers as the run's signals. Per joint the commanded angle (`targets`), the velocity and the current (`currents_ma`, magnitude) beside
the measured angle, which runlog already keeps; robot-wide the state's loop rate, safety flags and movement limits on every tick, and
robot.health's verdict, battery, motors, CPU, loop and bus when it is polled.

robotd leaves out what it does not measure: an empty list, a missing block. Those are absent here, never zero (a signal missing from a
tick is not reported). In the simulator the current is a stand-in (the actuator force, not a servo's current) and the battery and
temperatures are constants (PHASE5-ITEM3-BODY-DATA.md)."""

import math

JOINT_LISTS = (("targets", "target"), ("velocities", "vel"), ("currents_ma", "ma"))
FLAGS = ("fallen", "limp", "picked_up")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def state_values(s: dict, joints: tuple | None = None) -> dict:
    """One robot.state's body signals: a per-joint list only when it has one number per joint (robotd's JOINT_NAMES order)."""
    if joints is None:
        from duck_lab.nav.runlog import JOINTS as joints
    v = {}
    for key, suffix in JOINT_LISTS:
        vals = s.get(key) or []
        if len(vals) == len(joints) and all(_num(x) for x in vals):
            v.update({f"joint_{n}_{suffix}": x for n, x in zip(joints, vals)})
    loop = s.get("loop")
    if isinstance(loop, dict):
        v.update({f"loop_{k}": loop[k] for k in ("hz", "missed") if _num(loop.get(k))})
    safety = s.get("safety")
    if isinstance(safety, dict):
        v.update({f: int(safety[f]) for f in FLAGS if isinstance(safety.get(f), bool)})
    move = s.get("move")
    if isinstance(move, dict) and isinstance(move.get("limited_by"), list):
        v["move_limited_by"] = ",".join(str(x) for x in move["limited_by"])
    return v


def health_values(h: dict) -> dict:
    """One robot.health answer as signals; a block robotd leaves out stays out."""
    v = {"health_ok": int(bool(h.get("healthy"))), "health_degraded": int(bool(h.get("degraded")))}
    bat = h.get("battery") or {}
    v.update({k: bat[f] for k, f in (("battery_v", "volts"), ("battery_pct", "percent")) if _num(bat.get(f))})
    mot = h.get("motors") or {}
    if isinstance(mot.get("hottest"), str):
        v["motor_hottest"] = mot["hottest"]
    v.update({f"motor_{k}": mot[k] for k in ("max_c", "mean_c") if _num(mot.get(k))})
    if _num(h.get("cpu_temp_c")):
        v["cpu_temp_c"] = h["cpu_temp_c"]
    loop = h.get("control_loop") or {}
    v.update({k: loop[f] for k, f in (("loop_target_hz", "target_hz"), ("loop_achieved_hz", "achieved_hz"),
                                      ("loop_tick_age_ms", "last_tick_age_ms")) if _num(loop.get(f))})
    bus = h.get("bus")
    if isinstance(bus, dict):
        if _num(bus.get("consecutive_errors", 0)):
            v["bus_errors"] = bus.get("consecutive_errors", 0)
        v["bus_missing"] = len(bus.get("missing") or [])
    return v


def health_verdict(h: dict) -> dict:
    """What robot.health says of itself: an event is recorded when this changes."""
    return {"healthy": bool(h.get("healthy")), "degraded": bool(h.get("degraded")), "reason": h.get("reason")}


SIGNALS = [{"name": n, "kind": "number", **({"unit": u} if u else {})} for n, u in (
    ("loop_hz", "Hz"), ("loop_missed", None), ("fallen", None), ("limp", None), ("picked_up", None),
    ("health_ok", None), ("health_degraded", None), ("battery_v", "V"), ("battery_pct", "%"), ("motor_max_c", "degC"),
    ("motor_mean_c", "degC"), ("cpu_temp_c", "degC"), ("loop_target_hz", "Hz"), ("loop_achieved_hz", "Hz"),
    ("loop_tick_age_ms", "ms"), ("bus_errors", None), ("bus_missing", None))]
SIGNALS += [{"name": "move_limited_by", "kind": "text"}, {"name": "motor_hottest", "kind": "text"}]


def joint_signals(joints: tuple) -> list:
    """The three per-joint lists' declarations, beside runlog's measured angle."""
    units = {"target": "rad", "vel": "rad/s", "ma": "mA"}
    return [{"name": f"joint_{n}_{s}", "kind": "number", "unit": units[s]} for n in joints for _, s in JOINT_LISTS]
