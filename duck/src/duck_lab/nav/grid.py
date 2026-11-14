"""A cost map from mapd's map.grid, and A* on it (RFC-0002 §3.8, steps 1-2).

map.grid: res_m, origin (map coordinates of the low corner of cell (0, 0)), width, height, and cells:
one character per cell, row-major from the lowest y — `?` unknown, `.` free, `#` occupied.
"""

import heapq
import math
from dataclasses import dataclass

# Two layers around every obstacle, as Nav2 does. Within LETHAL_M (about the duck's half-width plus
# a little) the duck must not go. Out to INFLATE_M — the clearance upstream's autod keeps, plus a
# margin for what mapd has not seen of an obstacle and for odometry error (phase 1, run 1) — cells
# are expensive, not forbidden: plans keep off walls, and a duck that drifted into the margin can
# still get out (run 2, all impassable, stranded it).
LETHAL_M = 0.12
INFLATE_M = 0.28
# Unknown ground can hide a drop (the staircase reads as nothing until the cliff check sees it), so it
# costs more than the margin round something already seen: with unknown cheaper, the planner took a
# long detour through unmapped corridor toward the stairs rather than pass the office cabinet.
MARGIN_COST = 10.0
UNKNOWN_COST = 15.0  # unknown cells are expensive, not forbidden
FREE_COST = 1.0


def _grow(cost: list, w: int, h: int, centres: list, res: float) -> None:
    """Mark the lethal disc and the margin ring around each obstacle cell, in place."""
    lethal = math.ceil(LETHAL_M / res)
    margin = math.ceil(INFLATE_M / res)
    rings = [(dx, dy, dx * dx + dy * dy <= lethal * lethal)
             for dx in range(-margin, margin + 1) for dy in range(-margin, margin + 1)
             if dx * dx + dy * dy <= margin * margin]
    for cx, cy in centres:
        for dx, dy, is_lethal in rings:
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                i = y * w + x
                cost[i] = math.inf if is_lethal else max(cost[i], MARGIN_COST)


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
    def from_map_grid(cls, grid: dict) -> "CostGrid":
        res, (ox, oy) = grid["res_m"], grid["origin"]
        w, h, cells = grid["width"], grid["height"], grid["cells"]
        if res <= 0 or w == 0 or h == 0:
            raise EmptyMap("map.grid is empty: mapd has no stop yet")
        if len(cells) != w * h:
            raise ValueError(f"map.grid has {len(cells)} cells for {w}x{h}")
        cost = [UNKNOWN_COST if c == "?" else FREE_COST for c in cells]
        _grow(cost, w, h, [(i % w, i // w) for i, c in enumerate(cells) if c == "#"], res)
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

    def with_blocked(self, points: list) -> "CostGrid":
        """This grid with obstacles the depth reflex saw added (map metres), grown like walls. The
        reflex's memory: mapd may not hold what the sensor saw (something above the floor, or seen
        between stops), and without it the next plan walks back into it."""
        if not points:
            return self
        cost = list(self.cost)
        _grow(cost, self.width, self.height, [self.cell(*p) for p in points], self.res)
        return CostGrid(self.res, self.origin, self.width, self.height, cost)

    def covering(self, points: list, margin_m: float = 0.5) -> "CostGrid":
        """This grid grown with unknown cells until it covers every point (plus a margin): a goal
        beyond what mapd has seen is unknown ground, expensive but not forbidden."""
        m = math.ceil(margin_m / self.res)
        cells = [self.cell(*p) for p in points]
        left = max(0, -min(c[0] for c in cells) + m)
        down = max(0, -min(c[1] for c in cells) + m)
        right = max(0, max(c[0] for c in cells) - self.width + 1 + m)
        up = max(0, max(c[1] for c in cells) - self.height + 1 + m)
        if not (left or down or right or up):
            return self
        w, h = self.width + left + right, self.height + down + up
        cost = [UNKNOWN_COST] * (w * h)
        for cy in range(self.height):
            row = self.cost[cy * self.width:(cy + 1) * self.width]
            start = (cy + down) * w + left
            cost[start:start + self.width] = row
        origin = (self.origin[0] - left * self.res, self.origin[1] - down * self.res)
        return CostGrid(self.res, origin, w, h, cost)


ESCAPE = 2
ESCAPE_COST = 100.0


def plan(grid: CostGrid, start: tuple, goal: tuple) -> list | None:
    """A* from start to goal (map metres), 8-connected. The path as cell centres in metres, from the
    start's cell to the goal's, or None when the goal cannot be reached. The goal may not be lethal;
    the start may (the duck is already there), and lethal cells within ESCAPE cells of it may be
    crossed, at a high cost, to get out."""
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
                if not grid.inside(*n) or max(abs(n[0] - s[0]), abs(n[1] - s[1])) > ESCAPE:
                    continue
                here = ESCAPE_COST
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
