"""A challenge's scene (ADR-0015): boxes and floor slabs in the challenge's own frame, the duck's start at the origin
facing +x, the goal, and what counts as right. `moved` applies the start's jitter by moving the world (the body server
always starts the duck at the origin); `mjcf`, `miniview_scene` and `layout` write the same scene for the simulator,
for Observatory, and for the truth checks.

A slab is a floor: its top is the floor's level, 0 for the start's, below 0 for the floor beyond a drop.
"""

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from duck_lab.nav.frames import compose, inverse

UPSTREAM = Path(os.environ.get("DUCK_SIM_RL", "/work/pollen/microduck_rl")) / "src" / "mjlab_microduck" / "robot" / "microduck"
SCENARIOS = Path(os.path.expanduser("~/.cache/duck-sim/scenarios"))
SLAB_M = 0.05                 # a floor slab's thickness
TOF_RANGE_M = 4.0             # the simulated depth sensor's range (microduck_rl sim/tof.py MAX_RANGE): beyond it, "no target"
# The trunk stands this far ahead of the start once the duck has settled (truth at a run's start, 2026-11-16's challenge
# runs: x 0.044-0.058 m, y about 0); contacts are judged from the trunk, so a wall close ahead is placed from here.
TRUNK_START = (0.05, 0.0)
WALL_RGBA = "0.75 0.75 0.78 1"
FLOOR_RGBA = "0.45 0.5 0.55 1"
LOW_RGBA = "0.35 0.25 0.35 1"


def _inside(p: tuple, b) -> bool:
    c, s = math.cos(b.yaw), math.sin(b.yaw)
    dx, dy = p[0] - b.cx, p[1] - b.cy
    return abs(c * dx + s * dy) <= b.hx and abs(-s * dx + c * dy) <= b.hy


@dataclass(frozen=True)
class Box:
    name: str
    cx: float
    cy: float
    hx: float
    hy: float
    z0: float
    z1: float
    yaw: float = 0.0

    def moved(self, t: tuple) -> "Box":
        x, y, yaw = compose(t, (self.cx, self.cy, self.yaw))
        return replace(self, cx=round(x, 4), cy=round(y, 4), yaw=round(math.remainder(yaw, math.tau), 5))

    def corners(self) -> list:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return [(self.cx + c * dx - s * dy, self.cy + s * dx + c * dy)
                for dx, dy in ((-self.hx, -self.hy), (self.hx, -self.hy), (self.hx, self.hy), (-self.hx, self.hy))]


def slab(name: str, x0: float, x1: float, y0: float, y1: float, top: float = 0.0) -> Box:
    """A floor from x0..x1 × y0..y1 (challenge frame), its top at `top`."""
    return Box(name, (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, top - SLAB_M, top)


def wall(name: str, x0: float, y0: float, x1: float, y1: float, thick: float = 0.04, height: float = 0.5) -> Box:
    """A wall from (x0, y0) to (x1, y1), centred on that line."""
    return Box(name, (x0 + x1) / 2, (y0 + y1) / 2, math.hypot(x1 - x0, y1 - y0) / 2, thick / 2, 0.0, height,
               math.atan2(y1 - y0, x1 - x0))


@dataclass
class Scene:
    id: str                       # Observatory's scene id and the scenario folder: the challenge and the seed, `ch2-s3`
    name: str
    boxes: list                   # walls and furniture: what the duck must not touch
    floors: list                  # slabs; one whose top is below 0 is beyond a drop
    goal: tuple                   # (x, y) in the world (after `moved`)
    right: str                    # "reach", or "refuse" where refusing is right (a goal beyond a drop)
    time_s: float
    jitter: tuple = (0.0, 0.0, 0.0)   # the start's offset and yaw in the challenge frame
    notes: dict = field(default_factory=dict)   # what the seed drew (widths, depths): kept in the run's results
    mode: str = "go"              # "go" (one goal), "sequence" (`goals` in turn, one reset), "explore" (cover `areas`)
    goals: tuple = ()             # a sequence's goals (x, y), in order
    areas: tuple = ()             # an exploration's rooms, as footprint boxes the coverage is scored in; the start's first

    def drops(self) -> list:
        """Floors below 0 beyond an edge: holes to keep away from. A `step*` floor is a step to walk down, not a drop."""
        return [f for f in self.floors if f.z1 < -1e-6 and not f.name.startswith("step")]

    def floor_top(self, p: tuple) -> float:
        """The top of the floor under p (0 where none): the highest piece that holds it, a bar under 6 cm deep left out
        (walked over, not stood on), so a fall is judged from the floor the duck is on, not from 0. A drop is no floor:
        over a hole the fall is judged from 0, as before."""
        holes = self.drops()
        tops = [f.z1 for f in self.floors if f not in holes and min(f.hx, f.hy) >= 0.03 and _inside(p, f)]
        return max(tops, default=0.0)

    def bounds(self) -> tuple:
        pts = [p for b in self.boxes + self.floors for p in b.corners()]
        return (round(min(p[0] for p in pts), 3), round(max(p[0] for p in pts), 3),
                round(min(p[1] for p in pts), 3), round(max(p[1] for p in pts), 3))


def moved(scene: Scene, start: tuple) -> Scene:
    """The scene as the duck meets it when it starts at `start` (challenge frame): the world moved by the inverse, so the
    duck is at the origin facing +x, where the body server puts it."""
    t = inverse(start)
    gx, gy, _ = compose(t, (scene.goal[0], scene.goal[1], 0.0))
    goals = tuple((round(x, 4), round(y, 4)) for x, y, _ in (compose(t, (g[0], g[1], 0.0)) for g in scene.goals))
    return replace(scene, boxes=[b.moved(t) for b in scene.boxes], floors=[f.moved(t) for f in scene.floors],
                   goal=(round(gx, 4), round(gy, 4)), jitter=tuple(start), goals=goals,
                   areas=tuple(a.moved(t) for a in scene.areas))


def _geom(b: Box, rgba: str) -> str:
    hz = (b.z1 - b.z0) / 2
    qw, qz = math.cos(b.yaw / 2), math.sin(b.yaw / 2)       # a quaternion: the angle unit is the robot file's compiler's
    return (f'<geom name="{b.name}" type="box" size="{b.hx:.4f} {b.hy:.4f} {hz:.4f}" pos="{b.cx:.4f} {b.cy:.4f} {b.z0 + hz:.4f}" '
            f'quat="{qw:.6f} 0 0 {qz:.6f}" rgba="{rgba}"/>')


def mjcf(scene: Scene, root: Path = SCENARIOS, upstream: Path = UPSTREAM) -> Path:
    """The simulator's scene file, in the scenario's own folder (never upstream's): upstream's scene_backlash.xml (its
    keyframes), the full-collision backlash robot by absolute path, `assets` linked (the robot's meshdir is relative to
    the scene file), and the floor plane replaced by the scene's slabs and boxes."""
    out = root / scene.id
    out.mkdir(parents=True, exist_ok=True)
    if not (out / "assets").exists():
        os.symlink(upstream / "assets", out / "assets")
    source = (upstream / "scene_backlash.xml").read_text()
    include = '<include file="robot_groundcontact_backlash.xml" />'
    floor = '<geom name="floor" size="0 0 0.05" pos="0 0 0" type="plane" material="groundplane" />'
    if source.count(include) != 1 or source.count(floor) != 1:
        raise RuntimeError("upstream scene_backlash.xml changed shape; update duck_lab.challenge.scene")
    geoms = [_geom(f, LOW_RGBA if f.z1 < -1e-6 else FLOOR_RGBA) for f in scene.floors] + [_geom(b, WALL_RGBA) for b in scene.boxes]
    text = source.replace(include, f'<include file="{upstream / "robot_allcollisions_backlash.xml"}" />')
    text = text.replace(floor, "\n        ".join(geoms))
    p = out / "scene.xml"
    p.write_text(f"<!-- Generated by robotics-lab duck_lab.challenge ({scene.id}); do not edit. -->\n" + text)
    return p


def miniview_scene(scene: Scene) -> dict:
    """Observatory's scene (CONTRACT.md): the boxes, and each lower floor as a drop hazard turned with its yaw."""
    boxes = [{"name": b.name, "cx": b.cx, "cy": b.cy, "z0": b.z0, "z1": b.z1, "hx": b.hx, "hy": b.hy, "yaw": b.yaw}
             for b in scene.boxes]
    hazards = [{"name": f.name, "kind": "drop", "x0": f.cx - f.hx, "x1": f.cx + f.hx, "y0": f.cy - f.hy, "y1": f.cy + f.hy,
                "yaw": f.yaw, "depth": round(-f.z1, 3)} for f in scene.drops()]
    return {"id": scene.id, "name": scene.name, "kind": "challenge", "frame": "world", "bounds": list(scene.bounds()),
            "boxes": boxes, "hazards": hazards}


def layout(scene: Scene) -> dict:
    """The geoms in sim/apartment_layout.json's shape, so the evaluation's footprint checks apply; floors are `floor_*`."""
    def g(b: Box, name: str) -> dict:
        hz = (b.z1 - b.z0) / 2
        return {"name": name, "type": "box", "pos": [b.cx, b.cy, b.z0 + hz], "size": [b.hx, b.hy, hz], "yaw": b.yaw,
                "collides": True}
    return {"scene": scene.id, "geoms": [g(f, f"floor_{f.name}") for f in scene.floors] + [g(b, b.name) for b in scene.boxes]}
