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
LETHAL_M = 0.12   # 15 cm (run 7) closed the doorway once the obstacle layer added the cabinet and wall;
                  # run 5's touches at 12 cm came from the cabinet's unmapped side, which the layer now sees
INFLATE_M = 0.28
# Unknown ground can hide a drop (the staircase reads as nothing until the cliff check sees it), so it
# costs more than the margin round something already seen: with unknown cheaper, the planner took a
# long detour through unmapped corridor toward the stairs rather than pass the office cabinet.
MARGIN_COST = 10.0
# 40, not 100: at 100 challenge 11 (ten seeds) walked longer round the hole (seed 6: 5.5 m against 4.4 m flat), drifted
# more, and three seeds stopped 0.26-0.30 m from the goal (6 of 10 passed, against 8 flat).
MARGIN_EDGE_COST = 40.0    # the margin ring's cost at the lethal edge (margin_cost)


def margin_cost(d: float, lethal_m: float, inflate_m: float) -> float:
    """The margin ring's cost at d from an obstacle: MARGIN_EDGE_COST at the lethal edge, falling quadratically to
    FREE_COST at inflate_m. Nav2's inflation layer decays exponentially (its docs; docs/wip/PRIOR-ART.md) and has an
    inscribed level this ring does not; the shape is ours, the idea theirs. A flat ring (MARGIN_COST everywhere in it) gave
    the shortest path no reason to keep off an obstacle once it was in the ring, so plans hugged the lethal edge round
    corners: exploring b5 r2's plans passed the corridor console's corner at 0.115 m, the following added ~3 cm, and the
    trunk touched it at 0.075 m (sim/probes/corner_seen.py: the corner had been seen within 1 cm). Replayed on 109 recorded
    plans (sim/probes/margin_replay.py): plans within 0.15 m of an obstacle 32 flat, 24 with the edge at 10, 13 at 40, 7 at
    100; none became unreachable; median length unchanged, the worst +62 % at 40. The lethal zone, and with it what fits
    through a doorway, does not change."""
    u = (inflate_m - d) / (inflate_m - lethal_m)
    return FREE_COST + (MARGIN_EDGE_COST - FREE_COST) * max(0.0, min(1.0, u)) ** 2
# An obstacle's own cell is infinite: never crossed. The lethal zone grown round it is LETHAL_COST:
# not planned through, except to escape from where the duck already stands (ESCAPE_M) - which must not
# let a path through the obstacle itself (a 50 cm escape walked through a wall in a test).
LETHAL_COST = 1e9
UNKNOWN_COST = 15.0  # unknown cells are expensive, not forbidden
# Unknown floor next to something known is likely more of it - the unseen side of a cabinet. Exploration
# trial 7 planned 5-9 cm past the cabinet's unseen east face and wedged the duck there. Such cells cost
# more, so a path takes the unseen side of furniture only when no seen way exists.
SHADOW_M = 0.30
SHADOW_COST = 60.0
FREE_COST = 1.0


# Drops get more room than walls, sized from the error budget (docs/wip/SIDE-DROPS.md, 2026-11-17): the cliff check's
# corridor (cliff.CORRIDOR_DROP_M, 0.25 m aside) plus the following's (~3 cm) and the belief's (~2.5 cm) error, rounded up,
# so a path held at the ring keeps a known drop out of the corridor and the duck is not stopped again for it (trial 2's
# stop, replan and stop again). 0.45 (the stop distance of the time) also stood in for how far a hole met head-on goes,
# and closed challenge 11's passage beside a pit; the duck now looks along the edge for that (run.Navigator.look_along).
# (Trial 3 tried "do not stop again for a remembered drop" instead: that switched off the cliff check over the
# unremembered part of the same staircase, and the duck fell. Never again: the cliff check stops for every drop it sees.)
DROP_LETHAL_M = 0.35
DROP_INFLATE_M = 0.55


def _grow(cost: list, w: int, h: int, centres: list, res: float,
          lethal_m: float = None, inflate_m: float = None) -> None:
    """Mark the lethal disc and the margin ring around each obstacle cell, in place. By distance from
    a cell's centre to the obstacle cell's edge (centre distance minus half a cell), not by whole
    cells: rounding up to whole 10 cm cells closed the office doorway (a 42 cm gap the 14 cm duck
    walks through) in phase 1's run 4."""
    lethal_m = LETHAL_M if lethal_m is None else lethal_m
    inflate_m = INFLATE_M if inflate_m is None else inflate_m
    reach = math.ceil(inflate_m / res) + 1
    rings = []
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            gap = math.hypot(dx, dy) * res - res / 2
            if gap < inflate_m:
                rings.append((dx, dy, gap < lethal_m, gap))
    for cx, cy in centres:
        for dx, dy, is_lethal, gap in rings:
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                i = y * w + x
                if dx == 0 and dy == 0:
                    cost[i] = math.inf
                else:
                    cost[i] = max(cost[i], LETHAL_COST if is_lethal else margin_cost(gap, lethal_m, inflate_m))


class EmptyMap(ValueError):
    pass


def _grow_points(cost: list, w: int, h: int, origin: tuple, res: float, points: list,
                 lethal_m: float = None, inflate_m: float = None) -> set:
    """Mark the lethal disc and the margin ring around each exact obstacle point, in place, by the distance
    from a cell's centre to the point itself (the clearance model, docs/wip/CLEARANCE-MODEL.md): a point is
    not rounded to its cell, which cost up to a cell of room. The point's own cell is infinite. Returns
    the cells that hold points."""
    lethal_m = LETHAL_M if lethal_m is None else lethal_m
    inflate_m = INFLATE_M if inflate_m is None else inflate_m
    reach = math.ceil(inflate_m / res) + 1
    own = set()
    for px, py in points:
        cx, cy = math.floor((px - origin[0]) / res + 1e-9), math.floor((py - origin[1]) / res + 1e-9)
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                x, y = cx + dx, cy + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                i = y * w + x
                if dx == 0 and dy == 0:
                    cost[i] = math.inf
                    own.add((x, y))
                    continue
                d = math.hypot(origin[0] + (x + 0.5) * res - px, origin[1] + (y + 0.5) * res - py)
                if d < lethal_m:
                    cost[i] = max(cost[i], LETHAL_COST)
                elif d < inflate_m:
                    cost[i] = max(cost[i], margin_cost(d, lethal_m, inflate_m))
    return own


def _near_square(px: float, py: float, x0: float, y0: float, res: float, within_m: float) -> bool:
    """Whether (px, py) lies in the square [x0, x0+res] x [y0, y0+res] or within within_m of it."""
    dx = max(x0 - px, 0.0, px - (x0 + res))
    dy = max(y0 - py, 0.0, py - (y0 + res))
    return math.hypot(dx, dy) <= within_m


@dataclass
class CostGrid:
    res: float
    origin: tuple
    width: int
    height: int
    cost: list   # row-major from the lowest y; inf on obstacles, LETHAL_COST round them
    points: tuple = ()           # exact obstacle points (map metres) the zones were grown from
    point_cells: frozenset = frozenset()     # the cells holding them: their room is the points', not the cells'

    @classmethod
    def from_map_grid(cls, grid: dict, explained_by: list = ()) -> "CostGrid":
        """The cost grid from mapd's map.grid. explained_by: exact obstacle points (map metres); a wall cell
        with one inside it or within half a cell of it is left out, as the points describe that obstacle
        more precisely (with_points adds them). A cell without one stays, grown as a whole cell."""
        res, (ox, oy) = grid["res_m"], grid["origin"]
        w, h, cells = grid["width"], grid["height"], grid["cells"]
        if res <= 0 or w == 0 or h == 0:
            raise EmptyMap("map.grid is empty: mapd has no stop yet")
        if len(cells) != w * h:
            raise ValueError(f"map.grid has {len(cells)} cells for {w}x{h}")
        # every wall mapd saw, explained or not, still casts its shadow: the unseen side of a face the duck saw up close is
        # the case SHADOW_COST is for (exploration trial 7)
        seen_walls = [(i % w, i // w) for i, c in enumerate(cells) if c == "#"]
        if explained_by:
            near = {}
            for px, py in explained_by:                  # bucket the points by cell, so each wall cell checks a few
                near.setdefault((math.floor((px - ox) / res), math.floor((py - oy) / res)), []).append((px, py))
            listed = list(cells)
            for i, c in enumerate(cells):
                if c != "#":
                    continue
                cx, cy = i % w, i // w
                x0, y0 = ox + cx * res, oy + cy * res
                if any(_near_square(px, py, x0, y0, res, res / 2)
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1) for px, py in near.get((cx + dx, cy + dy), ())):
                    listed[i] = "."
            cells = "".join(listed)
        cost = [UNKNOWN_COST if c == "?" else FREE_COST for c in cells]
        walls = [(i % w, i // w) for i, c in enumerate(cells) if c == "#"]
        _grow(cost, w, h, walls, res)
        reach = math.ceil(SHADOW_M / res) + 1
        ring = [(dx, dy) for dx in range(-reach, reach + 1) for dy in range(-reach, reach + 1)
                if math.hypot(dx, dy) * res - res / 2 < SHADOW_M]
        for cx, cy in seen_walls:
            for dx, dy in ring:
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h and cells[y * w + x] == "?":
                    cost[y * w + x] = max(cost[y * w + x], SHADOW_COST)
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

    def with_blocked(self, points: list, lethal_m: float = None, inflate_m: float = None) -> "CostGrid":
        """This grid with obstacles the depth reflex saw added (map metres), grown like walls. The
        reflex's memory: mapd may not hold what the sensor saw (something above the floor, or seen
        between stops), and without it the next plan walks back into it."""
        if not points:
            return self
        cost = list(self.cost)
        _grow(cost, self.width, self.height, [self.cell(*p) for p in points], self.res, lethal_m, inflate_m)
        return CostGrid(self.res, self.origin, self.width, self.height, cost, self.points, self.point_cells)

    def with_points(self, points: list) -> "CostGrid":
        """This grid with exact obstacle points added, their zones grown from the points themselves (the
        clearance model): the navigator's own memory of depth hits, as from_map_grid's explained_by."""
        if not points:
            return self
        cost = list(self.cost)
        own = _grow_points(cost, self.width, self.height, self.origin, self.res, points)
        return CostGrid(self.res, self.origin, self.width, self.height, cost,
                        self.points + tuple(tuple(p[:2]) for p in points), self.point_cells | frozenset(own))

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
        return CostGrid(self.res, origin, w, h, cost, self.points,
                        frozenset((x + left, y + down) for x, y in self.point_cells))


ESCAPE_M = 0.5          # a duck stopped at the cliff-stop distance (45 cm) is inside a drop's lethal zone
ESCAPE_COST = 100.0


def nearest_free(grid: CostGrid, goal: tuple, within_m: float, room_m: float = 0.0) -> tuple | None:
    """The centre of the cell nearest goal (map metres) that is not lethal and has room_m clear of obstacles round it,
    within within_m of it; None if there is none. A goal inside a drop's ring is held off at it (the operator, 2026-11-17).
    room_m: the duck must be able to turn where it stops (exploring b1 r3, b2 r1, b3 r1: held off 9-11 cm from the cabinet
    or the shelf, every next leg refused with no room to turn, the run trapped)."""
    g = grid.cell(*goal)
    if grid.inside(*g) and grid.at(*g) < LETHAL_COST and (not room_m or clearance(grid, grid.centre(*g), room_m) >= room_m):
        return grid.centre(*g)
    reach = math.ceil(within_m / grid.res)
    best = None
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            c = (g[0] + dx, g[1] + dy)
            if not grid.inside(*c) or grid.at(*c) >= LETHAL_COST or (room_m and clearance(grid, grid.centre(*c), room_m) < room_m):
                continue
            p = grid.centre(*c)
            d = math.dist(p, goal)
            if d <= within_m and (best is None or d < best[0]):
                best = (d, p)
    return best[1] if best else None


def plan(grid: CostGrid, start: tuple, goal: tuple) -> list | None:
    """A* from start to goal (map metres), 8-connected. The path as cell centres in metres, from the
    start's cell to the goal's, or None when the goal cannot be reached. The goal may not be lethal;
    the start may (the duck is already there), and then lethal cells within ESCAPE_M of it may be
    crossed, at a high cost, to get out - never re-entered once the path is out."""
    s, g = grid.cell(*start), grid.cell(*goal)
    if not grid.inside(*g) or grid.at(*g) >= LETHAL_COST:
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
            if here >= LETHAL_COST:
                # Only an escape: from a lethal cell (the start's, or one reached from it) to the next,
                # within ESCAPE_M of the start. A path on free floor never enters a lethal zone.
                if grid.at(*c) < LETHAL_COST or math.hypot(n[0] - s[0], n[1] - s[1]) * grid.res > ESCAPE_M:
                    continue
                here = ESCAPE_COST
            nd = d + step * here
            if nd < best.get(n, math.inf):
                best[n] = nd
                came[n] = c
                heapq.heappush(frontier, (nd + math.dist(n, g), nd, n))
    return None


def clearance(grid: CostGrid, xy: tuple, max_m: float) -> float:
    """Distance (m) from xy to the nearest obstacle within max_m, max_m when none is that close: to an exact
    obstacle point where the grid has them (with_points), else to an obstacle cell's square from xy itself,
    not from its cell's centre (the clearance model, docs/wip/CLEARANCE-MODEL.md)."""
    cx, cy = grid.cell(*xy)
    r = math.ceil(max_m / grid.res) + 1
    best = max_m
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            n = (cx + dx, cy + dy)
            if grid.inside(*n) and math.isinf(grid.at(*n)) and n not in grid.point_cells:
                x0, y0 = grid.origin[0] + n[0] * grid.res, grid.origin[1] + n[1] * grid.res
                gx = max(x0 - xy[0], 0.0, xy[0] - (x0 + grid.res))
                gy = max(y0 - xy[1], 0.0, xy[1] - (y0 + grid.res))
                best = min(best, math.hypot(gx, gy))
    for p in grid.points:
        best = min(best, math.dist(xy, p))
    return best


def path_length(points: list) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def keep_current(grid: CostGrid, current: list, pose: tuple, new: list, switch_m: float = 0.3) -> bool:
    """Hysteresis for replanning: keep following `current` (the path still ahead) while none of it is
    lethal on the new grid and the new path is not at least switch_m shorter. Phase 1 run 11, goal 20:
    obstacle-layer replans flipped between two routes for 12 s at the office doorway."""
    if not current:
        return False
    if any(grid.inside(*grid.cell(*q)) and grid.at(*grid.cell(*q)) >= LETHAL_COST for q in current):
        return False
    return path_length([pose[:2]] + list(current)) < path_length(new) + switch_m


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
