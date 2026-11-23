"""The guardrails only the simulator's truth can check, and the drop guard (RFC-0021 step 6, RFC-0022): the runner's.

`TruthGuard` checks a goal run's contact, fall, drop clearance and the robot inside a no-go area against the truth (the
trunk's pose and height), the simulator's layout (what the robot can walk into) and the scene's drops (runfile.scenefile: the
scene's own, a scene with none has none); the runner breaks the run through the navigator API's `goal.break`. The navigator's own
guardrails (the speed cap, the no-go area in its planner, the clock, stuck) are its own (duck_lab.nav.guardrails.Guard). The drop
guard is the explorations' kill switch: the truth stops a run when the trunk comes within GUARD_M of a drop or drops, so a failing
cliff check ends in a stop, not a fall."""

import json
import math
from pathlib import Path

from labrunner import geometry
from labrunner.geometry import footprint_distance, obstacles
from runfile.scenefile import Scene
from worldmodel.site import inside

TRUTH = ("contact", "fall", "drop_clearance", "no_go_area")         # by the truth (no_go_area: the robot inside it)
GUARD_M = 0.05


def drop_distance(scene: Scene, p) -> float:
    """The trunk's distance to the scene's nearest drop's outline; infinite in a scene with none."""
    return min((footprint_distance(p, g) for g in scene.drop_geoms()), default=math.inf)


def load_layout(scene: Scene, path: Path | None = None) -> tuple:
    """(obstacles of the simulator's layout (`path`, else the robot's: labrunner.geometry), the scene's drops); no obstacles when
    there is no layout: no truth to check against."""
    try:
        obs = obstacles(json.loads(Path(path or geometry.layout_path()).read_text()))
    except OSError:
        obs = []
    return obs, scene.drop_geoms()


class TruthGuard:
    """The runner's side (RFC-0021 step 6): the guardrails only the simulator's truth can check, against the layout."""

    def __init__(self, guardrails: list, layout: tuple | None = None, profile=None, scene: Scene | None = None):
        """`layout`: (obstacles, drops), else the simulator's layout's and `scene`'s drops (load_layout); `profile`: the robot's
        profile this goal is judged by (its footprint and fall height); None: labrunner.geometry's."""
        p = profile if profile is not None else geometry.profile()
        self.fallen_z, self.footprint = p.judge.fall_z_m, p.footprint.radius_m
        self.by_name: dict = {}
        for g in guardrails:
            if g["name"] in TRUTH:
                self.by_name.setdefault(g["name"], []).append(g)
        if layout is None and scene is None:
            raise ValueError("a truth guard needs the scene (its drops) or a layout")
        self.obs, self.drops = layout if layout is not None else load_layout(scene)
        self.checked = list(self.by_name)

    def check(self, pose: tuple, z: float) -> tuple | None:
        """(name, detail) of the first guardrail the truth (the trunk's x, y, yaw and height) breaks, else None."""
        if "fall" in self.by_name and z < self.fallen_z:
            return "fall", f"the trunk is {z:.3f} m high: the robot fell"
        for g in self.by_name.get("no_go_area", []):
            if inside(pose[:2], [tuple(q) for q in g["outline"]]):
                return "no_go_area", f"the robot is inside the no-go area {g['area']}"
        if "contact" in self.by_name and self.obs:
            best = min(self.obs, key=lambda o: footprint_distance(pose[:2], o))
            d = footprint_distance(pose[:2], best)
            if d < self.footprint:
                return "contact", f"the trunk is {d:.3f} m from {best['name']}: a part can touch it"
        for g in self.by_name.get("drop_clearance", []):
            if self.drops:
                best = min(self.drops, key=lambda o: footprint_distance(pose[:2], o))
                d = footprint_distance(pose[:2], best)
                if d < g["m"]:
                    return "drop_clearance", f"the trunk is {d:.2f} m from the drop {best['name']}, nearer than {g['m']:g} m"
        return None
