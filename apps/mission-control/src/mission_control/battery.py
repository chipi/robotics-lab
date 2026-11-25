"""The battery rule, one definition for every robot (the operator's decision, review round 3): low under 20 %, and not low again until it is over 25 %
(a hysteresis: a sag under load is not a recovery). It gives the robot view's `battery` field and the `low_battery` alarm from the same state, so the view,
the alarm and the page's Readiness card agree. A robot whose status carries no percent has no rule: `view` is None and nothing is raised."""

LOW_PCT, CLEAR_PCT = 20, 25
GAP_S = 30.0        # a low battery is raised again every 30 s while it holds, so a major alarm stays inside the page's 60 s window


class BatteryRule:
    def __init__(self, module: str = "robot", hint: str = ""):
        self.module, self.hint = module, hint
        self.low = False
        self._last = None

    def update(self, status: dict | None, now: float) -> list:
        """Advance the state from a status and return the alarms to raise (RFC-0019's record, source "robot")."""
        pct = (status or {}).get("battery_pct")
        if pct is None:
            return []
        self.low = pct < LOW_PCT or (self.low and pct < CLEAR_PCT)
        if not self.low or (self._last is not None and now - self._last < GAP_S):
            return []
        self._last = now
        values = {"battery_pct": pct}
        if "battery_mv" in status:
            values["battery_mv"] = status["battery_mv"]
        return [{"anomaly": "low_battery", "severity": "major", "source": "robot", "module": self.module, "t": now,
                 "summary": f"the battery is at {pct} %{self.hint}", "values": values}]

    def view(self, status: dict | None) -> dict | None:
        pct = (status or {}).get("battery_pct")
        if pct is None:
            return None
        return {"pct": pct, "low": self.low, "low_pct": LOW_PCT, "clear_pct": CLEAR_PCT}
