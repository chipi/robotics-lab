"""The guardrails only the simulator's truth can check, and the staircase guard (RFC-0021 step 6, RFC-0022): the runner's.

`TruthGuard` checks a goal run's contact, fall, drop clearance and the robot inside a no-go area against the truth (the
trunk's pose and height) and the apartment's layout; the runner breaks the run through the navigator API's `goal.break`.
The navigator's own guardrails (the speed cap, the no-go area in its planner, the clock, stuck) are its own
(duck_lab.nav.guardrails.Guard). The staircase guard is the explorations' kill switch: the truth aborts a run when the
trunk comes within GUARD_M of the staircase opening or drops, so a failing cliff check ends in an abort, not a fall."""

import json
import math
from pathlib import Path

from labrunner.geometry import FALLEN_Z_M, FOOTPRINT_M, LAYOUT, footprint_distance, obstacles
from worldmodel.site import inside

TRUTH = ("contact", "fall", "drop_clearance", "no_go_area")         # by the truth (no_go_area: the robot inside it)
STAIRS = (-0.40, 0.00, -1.40, -0.70)
GUARD_M = 0.05


def stairs_distance(p) -> float:
    x0, x1, y0, y1 = STAIRS
    return math.hypot(max(x0 - p[0], 0, p[0] - x1), max(y0 - p[1], 0, p[1] - y1))


def load_layout(path: Path = LAYOUT) -> tuple:
    """(obstacles, drops) of the apartment's layout, or ([], []) when there is none: no truth to check against."""
    try:
        lay = json.loads(Path(path).read_text())
    except OSError:
        return [], []
    drops = [g for g in lay["geoms"] if g["name"].startswith("floor_") and g["pos"][2] + g["size"][2] < -1e-6]
    if not drops:
        # the apartment's one drop is the stairwell: an opening in the floor, with no floor geom below it (the explorer's truth
        # guard uses the same rectangle)
        x0, x1, y0, y1 = STAIRS
        drops = [{"name": "stairwell", "type": "box", "pos": [(x0 + x1) / 2, (y0 + y1) / 2, 0.0],
                  "size": [(x1 - x0) / 2, (y1 - y0) / 2, 0.0], "yaw": 0.0}]
    return obstacles(lay), drops


class TruthGuard:
    """The runner's side (RFC-0021 step 6): the guardrails only the simulator's truth can check, against the layout."""

    def __init__(self, guardrails: list, layout: tuple | None = None):
        self.by_name: dict = {}
        for g in guardrails:
            if g["name"] in TRUTH:
                self.by_name.setdefault(g["name"], []).append(g)
        self.obs, self.drops = layout if layout is not None else load_layout()
        self.checked = list(self.by_name)

    def check(self, pose: tuple, z: float) -> tuple | None:
        """(name, detail) of the first guardrail the truth (the trunk's x, y, yaw and height) breaks, else None."""
        if "fall" in self.by_name and z < FALLEN_Z_M:
            return "fall", f"the trunk is {z:.3f} m high: the robot fell"
        for g in self.by_name.get("no_go_area", []):
            if inside(pose[:2], [tuple(q) for q in g["outline"]]):
                return "no_go_area", f"the robot is inside the no-go area {g['area']}"
        if "contact" in self.by_name and self.obs:
            best = min(self.obs, key=lambda o: footprint_distance(pose[:2], o))
            d = footprint_distance(pose[:2], best)
            if d < FOOTPRINT_M:
                return "contact", f"the trunk is {d:.3f} m from {best['name']}: a part can touch it"
        for g in self.by_name.get("drop_clearance", []):
            if self.drops:
                best = min(self.drops, key=lambda o: footprint_distance(pose[:2], o))
                d = footprint_distance(pose[:2], best)
                if d < g["m"]:
                    return "drop_clearance", f"the trunk is {d:.2f} m from the drop {best['name']}, nearer than {g['m']:g} m"
        return None
