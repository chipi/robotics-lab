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

- Without a truth (its runner told the navigator `not_enforced`, phase 5 B3) the robot's own sensors stand in for those three
  (`RobotSide`): a fall is the IMU's tilt held past `robot_guards.fall_tilt_deg` (or mapd lost as `fell`), a contact is mapd
  newly lost as `bumped` or `carried`, a drop_clearance is the belief's distance to the drops the forward sensor has seen. They
  are weaker than the truth: each says what it cannot see (`RobotSide`), and where a runner has the truth they are not armed.

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
ROBOT_SIDE = ("fall", "contact", "drop_clearance")      # the truth ones the robot's own sensors stand in for, in the order checked
MAPD_BREAKS = {"bumped": "contact", "carried": "contact", "fell": "fall"}      # mapd's `lost` reasons (RFC-0002 §3.6) that are a guardrail


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


_UNSEEN = object()


class RobotSide:
    """The robot-side replacement for the truth guardrails (phase 5 B3), for the names asked and not enforced by the runner.
    `check(t, tilt, mapd, drop_m)` gives (name, detail) of the first one broken, else None; every input may be missing (not checked).
    - fall: the trunk's tilt (the larger of pitch and roll, deg) at or over robot_guards.fall_tilt_deg for fall_s, or mapd lost as
      `fell`. Cannot see a fall that stays under the angle (onto a ledge), nor one the IMU stopped reporting.
    - contact: mapd lost as `bumped` or `carried` *since the goal began*: the first account of mapd is the baseline, so a duck that
      was already carried when the goal started is not a contact of the goal's. Cannot see a touch mapd did not feel.
    - drop_clearance m: the belief's distance to the nearest drop the forward sensor has seen (a cliff stop's points, a glance's
      edges) under m. Cannot see a drop it has not seen (an unmapped rim approached from the side: docs/wip/CH22-RIM.md); the
      points lie in the drop, so the distance is at least the truth's to its outline, up to the seen part's depth."""

    def __init__(self, guardrails: list, enforce, cfg):
        """`guardrails`: the goal's list; `enforce`: the names to check here (the runner's `not_enforced`); `cfg`: the profile's
        robot_guards block (fall_tilt_deg, fall_s)."""
        asked = {g["name"] for g in guardrails}
        self.names = [n for n in ROBOT_SIDE if n in asked and n in set(enforce)]
        self.drop_m = max((g["m"] for g in guardrails if g["name"] == "drop_clearance"), default=None)
        self.tilt_deg, self.tilt_s = cfg["fall_tilt_deg"], cfg["fall_s"]
        self._tilted_since = None
        self._lost = _UNSEEN

    def check(self, t: float, tilt, mapd, drop_m) -> tuple | None:
        new = None
        if mapd is not None:
            lost = mapd.get("lost")
            new = lost if self._lost is not _UNSEEN and lost != self._lost else None
            self._lost = lost
        if "fall" in self.names:
            over = tilt is not None and max(abs(tilt[0]), abs(tilt[1])) >= self.tilt_deg
            self._tilted_since = (self._tilted_since if self._tilted_since is not None else t) if over else None
            if over and t - self._tilted_since >= self.tilt_s:
                return "fall", f"the trunk has been tilted {max(abs(tilt[0]), abs(tilt[1])):.0f} deg, at or over {self.tilt_deg:g} deg, for {t - self._tilted_since:.1f} s: the robot fell"
            if MAPD_BREAKS.get(new) == "fall":
                return "fall", f"mapd is lost: {new}"
        if "contact" in self.names and MAPD_BREAKS.get(new) == "contact":
            return "contact", f"mapd is lost: {new}" + (" (the robot was lifted)" if new == "carried" else " (it felt a knock)")
        if "drop_clearance" in self.names and drop_m is not None and self.drop_m is not None and drop_m < self.drop_m:
            return "drop_clearance", f"the robot is {drop_m:.2f} m from a drop its sensor saw, nearer than {self.drop_m:g} m"
        return None


class Guard:
    """The navigator's side: the speed cap and the keep-out armed, the clock watched, and the robot-side replacements for the truth
    guardrails when a `robot` is given. It reads no truth."""

    def __init__(self, nav, guardrails: list, on_break, t0: float | None = None, robot: RobotSide | None = None):
        self.nav, self.guardrails, self.on_break, self.robot = nav, guardrails, on_break, robot
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
        return self.robot.check(now, self.nav._tilt(), self.nav.localisation.seen, self._drop_m()) if self.robot else None

    def _drop_m(self) -> float | None:
        """The belief's distance to the nearest drop the forward sensor has seen, in map metres: the cliff stops' points (nav.drops) and
        the edges a glance measured (nav.edges); the suspected cells are guesses, not seen. None before one."""
        pose, drops = self.nav.localisation.pose(), list(self.nav.drops) + list(self.nav.edges)
        return min(math.dist(pose[:2], d) for d in drops) if pose is not None and drops else None
