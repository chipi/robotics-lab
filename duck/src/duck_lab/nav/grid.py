"""A cost map from mapd's map.grid, and A* on it (RFC-0002 §3.8, steps 1-2).

map.grid: res_m, origin (map coordinates of the low corner of cell (0, 0)), width, height, and cells:
one character per cell, row-major from the lowest y — `?` unknown, `.` free, `#` occupied.
"""

import heapq
import math
from dataclasses import dataclass

# Obstacles grow by the clearance upstream's autod keeps (15 cm) plus about the duck's half-width.
INFLATE_M = 0.20
UNKNOWN_COST = 5.0   # unknown cells are expensive, not forbidden
FREE_COST = 1.0


class EmptyMap(ValueError):
    pass


@dataclass
class CostGrid:
    res: float
    origin: tuple
    width: int
    height: int
    cost: list   # row-major from the lowest y; math.inf where the duck must not go

    @classmethod
    def from_map_grid(cls, grid: dict, inflate_m: float = INFLATE_M) -> "CostGrid":
        res, (ox, oy) = grid["res_m"], grid["origin"]
        w, h, cells = grid["width"], grid["height"], grid["cells"]
        if res <= 0 or w == 0 or h == 0:
            raise EmptyMap("map.grid is empty: mapd has no stop yet")
        if len(cells) != w * h:
            raise ValueError(f"map.grid has {len(cells)} cells for {w}x{h}")
        cost = [UNKNOWN_COST if c == "?" else FREE_COST for c in cells]
        r = math.ceil(inflate_m / res)
        offsets = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if dx * dx + dy * dy <= r * r]
        for i, c in enumerate(cells):
            if c != "#":
                continue
            cx, cy = i % w, i // w
            for dx, dy in offsets:
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h:
                    cost[y * w + x] = math.inf
        return cls(res, (ox, oy), w, h, cost)

    def cell(self, x: float, y: float) -> tuple:
        # The epsilon keeps a point on a cell edge in the upper cell: 0.5 / 0.1 is 4.999… in floats.
        return (math.floor((x - self.origin[0]) / self.res + 1e-9),
                math.floor((y - self.origin[1]) / self.res + 1e-9))

    def centre(self, cx: int, cy: int) -> tuple:
        return self.origin[0] + (cx + 0.5) * self.res, self.origin[1] + (cy + 0.5) * self.res

    def inside(self, cx: int, cy: int) -> bool:
        return 0 <= cx < self.width and 0 <= cy < self.height

    def at(self, cx: int, cy: int) -> float:
        return self.cost[cy * self.width + cx] if self.inside(cx, cy) else math.inf


def plan(grid: CostGrid, start: tuple, goal: tuple) -> list | None:
    """A* from start to goal (map metres), 8-connected. The path as cell centres in metres, from the
    start's cell to the goal's, or None when the goal cannot be reached. The start may sit inside an
    inflated obstacle (the duck is already there); the goal may not."""
    s, g = grid.cell(*start), grid.cell(*goal)
    if not grid.inside(*g) or math.isinf(grid.at(*g)):
        return None
    if not grid.inside(*s):
        return None
    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]
    best = {s: 0.0}
    came = {}
    frontier = [(math.dist(s, g), 0.0, s)]
    while frontier:
        _, d, c = heapq.heappop(frontier)
        if c == g:
            path = [c]
            while c in came:
                c = came[c]
                path.append(c)
            return [grid.centre(*p) for p in reversed(path)]
        if d > best.get(c, math.inf):
            continue
        for dx, dy, step in steps:
            n = (c[0] + dx, c[1] + dy)
            here = grid.at(*n)
            if math.isinf(here):
                continue
            nd = d + step * here
            if nd < best.get(n, math.inf):
                best[n] = nd
                came[n] = c
                heapq.heappush(frontier, (nd + math.dist(n, g), nd, n))
    return None


def thin(path: list, spacing: float = 0.3) -> list:
    """Keep a waypoint about every `spacing` metres, and always the last."""
    if not path:
        return []
    out = [path[0]]
    for p in path[1:-1]:
        if math.dist(out[-1], p) >= spacing:
            out.append(p)
    if len(path) > 1:
        out.append(path[-1])
    return out
