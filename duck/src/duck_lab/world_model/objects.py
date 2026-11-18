"""Objects (RFC-0016): everything in a room is an object; some are landmarks. An object is a kind (with its defaults
from kinds.json: permanence, landmark value, room hints) and parts, each a box in plan with a bottom and a top. How the
duck may pass a part follows from its height: over it (no higher than WALK_OVER_M, docs/wip/STEPS.md: about 1 cm),
under it (its bottom above the duck's head, OVERHEAD_M), or around it.
"""

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from duck_lab.nav.cliff import OVERHEAD_M

KINDS_FILE = Path(__file__).with_name("kinds.json")
WALK_OVER_M = 0.01         # the walking policy crosses about 1 cm (STEPS.md, 2026-11-18)


def load_kinds(path: Path = KINDS_FILE) -> dict:
    return json.loads(path.read_text())["kinds"]


@dataclass(frozen=True)
class Part:
    """A box in plan: centre (x, y), half sizes (hx, hy), yaw; bottom z0 and top z1 above the floor."""
    x: float
    y: float
    hx: float
    hy: float
    yaw: float
    z0: float
    z1: float

    @property
    def traversal(self) -> str:
        if self.z1 <= WALK_OVER_M:
            return "over"
        if self.z0 >= OVERHEAD_M:
            return "under"
        return "around"

    def distance(self, p: tuple) -> float:
        """Plan distance from p to this part's outline (0 inside)."""
        c, s = math.cos(-self.yaw), math.sin(-self.yaw)
        dx, dy = p[0] - self.x, p[1] - self.y
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return math.hypot(max(abs(lx) - self.hx, 0.0), max(abs(ly) - self.hy, 0.0))

    def outline(self, spacing: float = 0.03) -> list:
        """Points along the outline, spacing apart, in this part's frame's parent."""
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        pts = []
        for ax, ay, bx, by in ((-1, -1, 1, -1), (1, -1, 1, 1), (1, 1, -1, 1), (-1, 1, -1, -1)):
            x0, y0, x1, y1 = ax * self.hx, ay * self.hy, bx * self.hx, by * self.hy
            n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / spacing))
            for i in range(n):
                lx, ly = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
                pts.append((self.x + c * lx - s * ly, self.y + s * lx + c * ly))
        return pts

    def moved(self, pose: tuple) -> "Part":
        """This part expressed in the parent frame of pose (pose ∘ part)."""
        c, s = math.cos(pose[2]), math.sin(pose[2])
        return replace(self, x=pose[0] + c * self.x - s * self.y, y=pose[1] + s * self.x + c * self.y,
                       yaw=self.yaw + pose[2])

    def shifted(self, dx: float, dy: float) -> "Part":
        return replace(self, x=self.x + dx, y=self.y + dy)


def part_from_geom(g: dict) -> Part:
    """A layout geom (sim/apartment_layout.json) as a part: round shapes by their bounding box in plan."""
    x, y, z = g["pos"]
    s, t = g["size"], g["type"]
    if t == "box":
        hx, hy, hz = s[0], s[1], s[2]
    elif t == "cylinder":
        hx = hy = s[0]
        hz = s[1]
    elif t == "capsule":
        hx = hy = s[0]
        hz = s[1] + s[0]
    elif t in ("ellipsoid", "4"):           # sim/layout.py writes mjGEOM_ELLIPSOID as "4" (lm_bedroom)
        hx, hy, hz = s[0], s[1], s[2]
    else:                                   # sphere
        hx = hy = hz = s[0]
    return Part(x, y, hx, hy, g.get("yaw", 0.0), max(0.0, z - hz), z + hz)


def distance(parts, p: tuple) -> float:
    return min(q.distance(p) for q in parts)


def blocking(parts) -> list:
    return [q for q in parts if q.traversal == "around"]
