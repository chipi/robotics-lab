"""A goal's guardrails (RFC-0014 §3.4.8): what a goal run must not do, checked where it can act: by the navigator, or by the
runner where only the simulator's truth can tell (RFC-0021 step 6).

Mission Control merges the robot's, the site's and the goal's guardrails into one list and hands it to `goal.start`
(duck_lab.nav.server); `Guard` arms the navigator with it and watches the clock, and `TruthGuard` is the runner's
(labrunner.guard), which reads the truth:

- `max_speed {mps}`: the navigator's forward command is clamped (`Navigator.speed_cap`), at the source of every move.
- `no_go_area {area, outline}`: the outline's points are obstacles for the planner (`Navigator.keepout`), so a path never
  enters it (lethal in the planner, as the RFC says), and the truth is watched for the robot inside it.
- `time_limit {seconds}`: the run's clock.
- `stuck`: the navigator's own "walking without getting anywhere" decision (nav/stuck.py).
- `contact`, `fall`, `drop_clearance {m}`: in the simulator by the truth (the body server's trunk pose and height) against the
  apartment's layout, as the challenge judge and the phase 1 evaluation read it: contact is the trunk centre within
  FOOTPRINT_M of an obstacle's outline, a fall is the trunk below FALLEN_Z_M, a drop_clearance is the trunk centre within `m`
  of a drop's outline. The navigator never reads the truth; the runner does, and a real robot would
  report these itself (RFC-0014 §3.4.1: a run says which conditions were checkable).

A broken guardrail stops the run: the guard calls `on_break(name, detail)` (the runner, through the API's `goal.break`), the
run sets `nav.abort` (every loop of the navigator and the explorer ends at its next tick, the robot is stopped) and ends
`stopped_by_guardrail`."""

import math
import threading
import time

from worldmodel.site import inside

WATCH_S = 0.05
KEEPOUT_SPACING_M = 0.05
NAVIGATOR = ("stuck", "time_limit", "no_go_area", "max_speed")      # the navigator checks (no_go_area: in its planner)
SUPPORTED = ("contact", "fall", "drop_clearance", "stuck", "time_limit", "no_go_area", "max_speed")


def keepout_points(polygon: list, spacing: float = KEEPOUT_SPACING_M) -> list:
    """Points over the outline and inside it, on a grid: obstacles the planner will not path through."""
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    pts, x = [], min(xs)
    while x <= max(xs) + 1e-9:
        y = min(ys)
        while y <= max(ys) + 1e-9:
            if inside((x, y), polygon):
                pts.append((round(x, 3), round(y, 3)))
            y += spacing
        x += spacing
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):          # the outline itself, so a thin area still blocks
        n = max(1, int(math.dist((x0, y0), (x1, y1)) / spacing))
        pts.extend((round(x0 + (x1 - x0) * i / n, 3), round(y0 + (y1 - y0) * i / n, 3)) for i in range(n + 1))
    return pts


class Guard:
    """The navigator's side: the speed cap and the keep-out armed, the clock watched. It reads no truth."""

    def __init__(self, nav, guardrails: list, on_break, t0: float | None = None):
        self.nav, self.guardrails, self.on_break = nav, guardrails, on_break
        self.t0 = time.monotonic() if t0 is None else t0
        self.by_name: dict = {}
        for g in guardrails:
            self.by_name.setdefault(g["name"], []).append(g)
        self._stop = threading.Event()
        self.checked = [n for n in self.by_name if n in NAVIGATOR]

    def arm(self) -> None:
        speeds = [g["mps"] for g in self.by_name.get("max_speed", [])]
        if speeds:
            self.nav.speed_cap = min(speeds)
        points: list = []
        for g in self.by_name.get("no_go_area", []):
            points.extend(keepout_points([tuple(p) for p in g["outline"]]))
        self.nav.keepout = points
        threading.Thread(target=self._watch, name="guardrails", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _watch(self) -> None:
        while not self._stop.wait(WATCH_S):
            try:
                broken = self.check()
            except Exception:                                    # noqa: BLE001 - a failing check must not end the run
                continue
            if broken:
                self.on_break(*broken)
                return

    def check(self, now: float | None = None) -> tuple | None:
        """(name, detail) of the first guardrail broken now, else None."""
        now = time.monotonic() if now is None else now
        elapsed = now - self.t0
        for g in self.by_name.get("time_limit", []):
            if elapsed > g["seconds"]:
                return "time_limit", f"the time limit of {g['seconds']:g} s is spent"
        return None
