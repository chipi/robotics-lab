"""The floor as the duck could stand on it, and how much of it the duck's map knows (RFC-0008, challenges 22 and 23; the
apartment's scoreboard can use the same).

The truth side of an exploration's score, with no simulator. It takes a layout (sim/apartment_layout.json's shape: geoms
with a name, a type, a position, a size and a yaw; floors are `floor_*`, a floor whose top is below 0 and is not a
`floor_step*` is a drop) and says:

- `reachable_floor(layout, start)`: a lattice over the level-0 floors, cut where the duck could not be (nearer an
  obstacle's outline than its footprint, nearer a drop than the planner's lethal zone), cut again to what is connected to
  the start;
- `known_test(grid, start)` and `coverage_by(points, known, regions)`: mapd's grid read cell by cell against those points,
  the share known overall and in each region (a region is a name and a test of a point).

`reachable`, `coverage` and `edge_band` are the same for a challenge's `Scene`, whose areas are the regions.
"""

import math
from collections import deque

from duck_lab.challenge.scene import Scene, _inside, layout
from duck_lab.nav.evaluate import FOOTPRINT_M, PROFILE, footprint_distance, obstacles
from duck_lab.nav.frames import compose, inverse

DROP_LETHAL_M = PROFILE.error_budget.drop_lethal_m

STEP_M = 0.05         # the lattice's cell, mapd's finest (0.0455 m raw)


def _is_drop(g: dict) -> bool:
    return g["name"].startswith("floor_") and not g["name"].startswith("floor_step") and g["pos"][2] + g["size"][2] < -1e-6


def _extent(lay: dict) -> tuple:
    xs, ys = [], []
    for g in lay["geoms"]:
        if g["name"].startswith("floor_") and g["type"] == "box":
            c, s = math.cos(g["yaw"]), math.sin(g["yaw"])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                dx, dy = sx * g["size"][0], sy * g["size"][1]
                xs.append(g["pos"][0] + c * dx - s * dy)
                ys.append(g["pos"][1] + s * dx + c * dy)
    return min(xs), max(xs), min(ys), max(ys)


def lattice(lay: dict, step: float = STEP_M, landmarks: bool = False) -> dict:
    """{(i, j): (x, y)}: lattice points on a level-0 floor, at least FOOTPRINT_M from every obstacle's outline and
    DROP_LETHAL_M from every drop's: where the planner can put the duck, so what a complete map must know."""
    obs = obstacles(lay, landmarks=landmarks)
    drops = [g for g in lay["geoms"] if _is_drop(g)]
    floors = [g for g in lay["geoms"] if g["name"].startswith("floor_") and g["type"] == "box" and g not in drops]
    x0, x1, y0, y1 = _extent(lay)
    out = {}
    for i in range(int((x1 - x0) / step) + 1):
        for j in range(int((y1 - y0) / step) + 1):
            p = (x0 + (i + 0.5) * step, y0 + (j + 0.5) * step)
            if not any(footprint_distance(p, f) <= 1e-9 for f in floors):
                continue
            if any(footprint_distance(p, g) < FOOTPRINT_M for g in obs):
                continue
            if any(footprint_distance(p, g) < DROP_LETHAL_M for g in drops):
                continue
            out[(i, j)] = p
    return out


def reachable_floor(lay: dict, start: tuple = (0.0, 0.0), step: float = STEP_M, landmarks: bool = False) -> list:
    """The lattice's points connected to the start (8-connected steps of one cell): the floor a complete exploration can
    stand on. The start's nearest lattice point seeds it, and must be within two cells of it."""
    cells = lattice(lay, step, landmarks)
    if not cells:
        return []
    seed = min(cells, key=lambda k: math.dist(cells[k], start[:2]))
    if math.dist(cells[seed], start[:2]) > 2 * step:
        return []
    seen, todo = {seed}, deque([seed])
    while todo:
        i, j = todo.popleft()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                n = (i + di, j + dj)
                if n in cells and n not in seen:
                    seen.add(n)
                    todo.append(n)
    return [cells[k] for k in seen]


def known_test(grid: dict, start: dict) -> "callable":
    """A test of a world point: does mapd's grid hold a known cell (free or occupied) there? `start` is the run's start.json
    (the map-frame pose, the truth pose, the odometry scale), which puts the world frame into the map's."""
    map_from_world = compose(tuple(start["map"]), inverse(tuple(start["truth"])))
    s = start["scale"]
    res, (ox, oy) = grid["res_m"] * s, (grid["origin"][0] * s, grid["origin"][1] * s)
    w, h, cells = grid["width"], grid["height"], grid["cells"]

    def known(p: tuple) -> bool:
        mx, my, _ = compose(map_from_world, (p[0], p[1], 0.0))
        cx, cy = math.floor((mx - ox) / res), math.floor((my - oy) / res)
        return 0 <= cx < w and 0 <= cy < h and cells[cy * w + cx] != "?"
    return known


def coverage_by(points: list, known, regions: dict) -> dict:
    """The share of `points` the map knows, overall and in each region (a name -> a test of a point; a point is counted in
    the first region that holds it): {"all": share, "regions": {name: share}, "cells": {name: n}}."""
    seen = {name: [0, 0] for name in regions}
    total = [0, 0]
    for p in points:
        k = known(p)
        total[0] += k
        total[1] += 1
        for name, holds in regions.items():
            if holds(p):
                seen[name][0] += k
                seen[name][1] += 1
                break
    share = lambda n: round(n[0] / n[1], 3) if n[1] else 0.0       # noqa: E731
    return {"all": share(total), "regions": {n: share(v) for n, v in seen.items()}, "cells": {n: v[1] for n, v in seen.items()}}


def edge_band_of(lay: dict, band_m: float, points: list) -> float:
    """The share of `points` within band_m of an obstacle's outline or a drop's: the floor the planner keeps away from and
    the sensor sees at a grazing angle, which a bar short of 100 % has to allow for."""
    near = obstacles(lay, landmarks=False) + [g for g in lay["geoms"] if _is_drop(g)]
    return sum(any(footprint_distance(p, g) < band_m for g in near) for p in points) / len(points) if points else 0.0


# ---- a challenge's scene ---------------------------------------------------------------------------------------------

def in_area(p: tuple, area) -> bool:
    return _inside(p, area)


def reachable(scene: Scene, start: tuple = (0.0, 0.0), step: float = STEP_M) -> list:
    return reachable_floor(layout(scene), start, step)


def coverage(scene: Scene, grid: dict, start: dict, points: list | None = None) -> dict:
    """coverage_by for a scene: its reachable floor (from where the duck starts), its areas the regions; the shares as
    {"all": share, "areas": {name: share}, "cells": {name: n}}."""
    pts = reachable(scene, tuple(start["truth"][:2])) if points is None else points
    out = coverage_by(pts, known_test(grid, start), {a.name: (lambda p, a=a: in_area(p, a)) for a in scene.areas})
    return {"all": out["all"], "areas": out["regions"], "cells": out["cells"]}


def edge_band(scene: Scene, band_m: float, points: list | None = None) -> float:
    return edge_band_of(layout(scene), band_m, reachable(scene) if points is None else points)
