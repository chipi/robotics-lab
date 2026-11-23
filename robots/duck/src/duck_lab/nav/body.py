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


class Held:
    """A value over its limit, held: `over(t, is_over)` gives how long it has been over once that reaches hold_s, once a stretch
    (said again only after the value came back under)."""

    def __init__(self, hold_s: float):
        self.hold_s, self.since, self.said = hold_s, None, False

    def over(self, t: float, is_over: bool) -> float | None:
        if not is_over:
            self.since, self.said = None, False
            return None
        if self.since is None:
            self.since = t
        if self.said or t - self.since < self.hold_s:
            return None
        self.said = True
        return t - self.since


LIMITS = ("current_ma", "current_s", "tracking_rad", "tracking_s", "hot_c", "loop_min_hz", "loop_slow_s")


class BodyWatch:
    """The body's anomalies (phase 5 item 3 step 3, RFC-0023 §7 step 3) at the profile's joints.limits: joint_overload (a joint's
    current at or over current_ma for current_s), joint_tracking (its commanded angle less its angle over tracking_rad for
    tracking_s; not checked when tracking_rad is null), loop_slow (the state's loop rate under loop_min_hz for loop_slow_s), from
    each state; motor_hot (the hottest servo at or over hot_c) and robot_unhealthy (robotd's verdict: major when not healthy, minor
    when degraded, said when it changes) from each health answer. Each returns the anomalies to raise, as Navigator.anomaly's
    arguments; a value robotd did not report is not checked (absent, never zero)."""

    def __init__(self, limits: dict, joints: tuple):
        self.lim, self.joints = {k: limits.get(k) for k in LIMITS}, tuple(joints)
        self._held: dict = {}
        self._verdict = None

    def checked(self) -> dict:
        """The limits in force and what is not checked, for the run's body_watch event."""
        not_checked = {}
        if self.lim["tracking_rad"] is None:
            not_checked["joint_tracking"] = "the profile's joints.limits.tracking_rad is null: not measured on this robot"
        return {"limits": dict(self.lim), "not_checked": not_checked}

    def _over(self, key, hold_s: float, t: float, is_over: bool) -> float | None:
        if key not in self._held:
            self._held[key] = Held(hold_s)
        return self._held[key].over(t, is_over)

    def state(self, t: float, s: dict) -> list:
        lim, n, out = self.lim, len(self.joints), []
        cur = s.get("currents_ma") or []
        if len(cur) == n:
            for j, ma in zip(self.joints, cur):
                if not _num(ma):
                    continue
                held = self._over(("ma", j), lim["current_s"], t, ma >= lim["current_ma"])
                if held is not None:
                    out.append({"kind": "joint_overload", "margin": round(ma - lim["current_ma"], 1),
                                "summary": f"{j} at {ma:.0f} mA, at or over {lim['current_ma']:g} mA for {held:.1f} s",
                                "values": {"joint": j, "ma": round(ma, 1), "limit_ma": lim["current_ma"], "held_s": round(held, 2),
                                           "margin_unit": "mA"}})
        angles, targets = s.get("joints") or [], s.get("targets") or []
        if lim["tracking_rad"] is not None and len(angles) == n and len(targets) == n:
            for j, a, g in zip(self.joints, angles, targets):
                if not (_num(a) and _num(g)):
                    continue
                err = abs(g - a)
                held = self._over(("track", j), lim["tracking_s"], t, err > lim["tracking_rad"])
                if held is not None:
                    out.append({"kind": "joint_tracking", "margin": round(err - lim["tracking_rad"], 3),
                                "summary": f"{j} {err:.2f} rad from its commanded angle, over {lim['tracking_rad']:g} rad for "
                                           f"{held:.1f} s",
                                "values": {"joint": j, "error_rad": round(err, 3), "target_rad": round(g, 3), "angle_rad": round(a, 3),
                                           "limit_rad": lim["tracking_rad"], "held_s": round(held, 2), "margin_unit": "rad"}})
        hz = (s.get("loop") or {}).get("hz")
        if _num(hz):
            held = self._over("loop", lim["loop_slow_s"], t, hz < lim["loop_min_hz"])
            if held is not None:
                out.append({"kind": "loop_slow", "margin": round(lim["loop_min_hz"] - hz, 2),
                            "summary": f"robotd's control loop at {hz:.1f} Hz, under {lim['loop_min_hz']:g} Hz for {held:.1f} s",
                            "values": {"loop_hz": round(hz, 2), "limit_hz": lim["loop_min_hz"], "held_s": round(held, 2),
                                       "margin_unit": "Hz"}})
        return out

    def health(self, t: float, h: dict) -> list:
        out = []
        m = h.get("motors") or {}
        if _num(m.get("max_c")) and self._over("hot", 0.0, t, m["max_c"] >= self.lim["hot_c"]) is not None:
            out.append({"kind": "motor_hot", "margin": round(m["max_c"] - self.lim["hot_c"], 1),
                        "summary": f"the hottest servo, {m.get('hottest') or '?'}, at {m['max_c']:.0f} C, at or over "
                                   f"{self.lim['hot_c']:g} C",
                        "values": {"joint": m.get("hottest"), "max_c": m["max_c"], "limit_c": self.lim["hot_c"], "margin_unit": "C"}})
        v = health_verdict(h)
        verdict = None if v["healthy"] and not v["degraded"] else v
        if verdict is not None and verdict != self._verdict:
            word = "degraded" if v["healthy"] else "not healthy"
            out.append({"kind": "robot_unhealthy", "severity": "minor" if v["healthy"] else "major",
                        "summary": f"robotd says it is {word}" + (f": {v['reason']}" if v["reason"] else ""),
                        "values": {"healthy": v["healthy"], "degraded": v["degraded"], "reason": v["reason"]}})
        self._verdict = verdict
        return out


class StopWatch:
    """What stops a goal on the robot's own health (phase 5 B2): `health(t, h)` from each robot.health answer gives (name, detail) of
    the first cause, else None. motor_hot: the hottest servo at or over the profile's joints.limits.hot_c. battery_low: the battery
    percent under health.battery_min_pct for health.battery_low_s (the hold restarts when it comes back over). robot_unhealthy:
    robotd's verdict is not healthy (degraded alone is a minor anomaly, not a stop). A value robotd did not report is not checked.
    The stale streams are the navigator's watchdog's. Unlike BodyWatch, a cause is answered at every poll while it holds: the
    navigator decides what a second answer means."""

    def __init__(self, limits: dict, health: dict):
        self.hot_c = limits["hot_c"]
        self.min_pct, self.low_s = health["battery_min_pct"], health["battery_low_s"]
        self._low_since = None

    def health(self, t: float, h: dict) -> tuple | None:
        m = h.get("motors") or {}
        if _num(m.get("max_c")) and m["max_c"] >= self.hot_c:
            return "motor_hot", f"the hottest servo, {m.get('hottest') or '?'}, is at {m['max_c']:.0f} C, at or over {self.hot_c:g} C"
        pct = (h.get("battery") or {}).get("percent")
        if _num(pct) and pct < self.min_pct:
            if self._low_since is None:
                self._low_since = t
            if t - self._low_since >= self.low_s:
                return "battery_low", f"the battery is at {pct:.0f} %, under {self.min_pct:g} % for {t - self._low_since:.0f} s"
        else:
            self._low_since = None
        if not h.get("healthy"):
            reason = h.get("reason")
            return "robot_unhealthy", "robotd says it is not healthy" + (f": {reason}" if reason else "")
        return None
