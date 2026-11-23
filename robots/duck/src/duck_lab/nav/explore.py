"""Exploring (RFC-0002 §3.8, step 7): the nearest worthwhile frontier — seen floor next to unknown.

Pure: frontiers(map_grid, scale) -> clusters of frontier points (map metres, scaled like the
navigator's grid); pick(clusters, pose, avoid) -> the point to go to next, or None.
"""

import math

MIN_CLUSTER_M = 0.20       # frontier stretches shorter than this are noise, not a way on
AVOID_M = 0.40             # a target this close to a failed one, a drop or an obstacle is skipped
RETIRED_M = 0.07           # a frontier cell this close to a retired one is retired too: a cell and a half of mapd's 0.0455 m
STANDOFF_M = 0.15          # stop this far back from the frontier, on the seen side
# The floor right round the duck stays unknown (the depth sensor does not see its own feet), so the
# nearest "frontier" is always underfoot: the first trial's first leg went 5 cm.
MIN_DIST_M = 0.6
GAIN_PER_M = 1.0           # a metre of frontier is worth a metre of walking (explore_lite's gain/potential)
# Unknown beside a wall or an object the map has seen is most often that wall going on: its face along the duck's way
# was never in the depth sensor's 45 deg wedge. Exploring baseline b1 (EXPLORE-PROGRESS.md): 18 of 34 targets were in
# or within 15 cm of a wall, the cabinet, the stairs or the office landmark, and every run ended trapped beside one.
WALL_M = 0.30              # frontier cells this close to an occupied cell are not a way on


def frontiers(grid: dict, scale: float = 1.0, wall_m: float = WALL_M, obstacles: list = ()) -> list:
    """Clusters (8-connected) of free cells with an unknown neighbour and no occupied cell, nor any of obstacles (map
    points: the navigator's remembered obstacle points), within wall_m, as lists of map points. A 0.8 m doorway keeps its
    middle 0.2 m."""
    res, (ox, oy) = grid["res_m"] * scale, (grid["origin"][0] * scale, grid["origin"][1] * scale)
    w, h, cells = grid["width"], grid["height"], grid["cells"]
    if not res or not w or not h:
        return []

    def at(x, y):
        return cells[y * w + x] if 0 <= x < w and 0 <= y < h else "?"

    r = math.ceil(wall_m / res) if wall_m > 0 else 0
    occupied = {(i % w, i // w) for i, c in enumerate(cells) if c == "#"}
    occupied |= {(math.floor((p[0] - ox) / res), math.floor((p[1] - oy) / res)) for p in obstacles}

    def by_wall(x, y):
        return r and any((x + dx, y + dy) in occupied for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                         if math.hypot(dx, dy) * res <= wall_m + 1e-9)

    front = set()
    for y in range(h):
        for x in range(w):
            if at(x, y) != ".":
                continue
            if any(at(x + dx, y + dy) == "?" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) and not by_wall(x, y):
                front.add((x, y))
    clusters, seen = [], set()
    for start in front:
        if start in seen:
            continue
        stack, members = [start], []
        seen.add(start)
        while stack:
            c = stack.pop()
            members.append(c)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (c[0] + dx, c[1] + dy)
                    if n in front and n not in seen:
                        seen.add(n)
                        stack.append(n)
        if len(members) * res >= MIN_CLUSTER_M:
            clusters.append([(ox + (x + 0.5) * res, oy + (y + 0.5) * res) for x, y in members])
    return clusters


def without_retired(clusters: list, retired: list, within_m: float = None) -> list:
    """The clusters less their cells within RETIRED_M of a retired frontier cell (a stretch a target with no path on
    the map took out); clusters left empty are dropped. Retired cells are not avoided at AVOID_M as failed targets
    are: 190 of them did that in b6 r1, their discs covered every frontier, and the run ended with rooms unseen."""
    within_m = RETIRED_M if within_m is None else within_m
    left = [[p for p in c if all(math.dist(p, r) > within_m for r in retired)] for c in clusters]
    return [c for c in left if c]


def pick(clusters: list, pose: tuple, avoid: list, ok=None) -> tuple | None:
    """A frontier point to go to. Clusters are ranked as explore_lite ranks them: distance to their
    nearest usable point minus GAIN_PER_M x their size (the extent of the cluster), so a wide opening
    into a room beats a sliver next to the duck (trial 6 went back and forth between corridor slivers).
    A usable point is at least MIN_DIST_M away and not within AVOID_M of anything in avoid; the goal is
    pulled STANDOFF_M back toward the duck so it sits on seen floor, and ok(goal), when given, must
    accept it (the navigator: not inside a lethal zone)."""
    ranked = []
    for cluster in clusters:
        usable = []
        for p in cluster:
            d = math.dist(p, pose[:2])
            if d < MIN_DIST_M or any(math.dist(p, a) < AVOID_M for a in avoid):
                continue
            usable.append((d, p))
        if usable:
            xs, ys = [p[0] for p in cluster], [p[1] for p in cluster]
            extent = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            ranked.append((min(usable)[0] - GAIN_PER_M * extent, sorted(usable)))
    for _, usable in sorted(ranked, key=lambda r: r[0]):
        for d, p in usable:
            k = (d - STANDOFF_M) / d
            goal = (pose[0] + k * (p[0] - pose[0]), pose[1] + k * (p[1] - pose[1]))
            if ok is None or ok(goal):
                return goal
    return None

# Challenge 22 (docs/wip/CH22-RIM.md): mapd draws a hole as free and the navigator knows only the rim it was shown, so a frontier
# at an unseen stretch of the rim is a target on the edge, approached from the side where the cliff check does not look.
RIM_M = 0.35           # the ring round a target looked at: the judge's 0.15 m, the belief's error, the frontier's pull-back
RIM_UNSEEN = 0.10      # the share at which a target counts as on a rim (a straight rim 0.2 m off); recorded in `pick`, not enforced


def rim_unseen(grid: dict, goal: tuple, seen_at, radius_m: float = RIM_M) -> float:
    """The share of mapd's free cells within radius_m of goal in which the depth sensor never saw floor (seen_at(xy) False): a
    hole mapd drew as free, a stairwell (upstream #599). Unknown cells are not counted; no free cell, 0."""
    res, (ox, oy), w, h = grid["res_m"], grid["origin"], grid["width"], grid["height"]
    r = math.ceil(radius_m / res)
    cx, cy = math.floor((goal[0] - ox) / res), math.floor((goal[1] - oy) / res)
    free = unseen = 0
    for y in range(max(cy - r, 0), min(cy + r + 1, h)):
        for x in range(max(cx - r, 0), min(cx + r + 1, w)):
            p = (ox + (x + 0.5) * res, oy + (y + 0.5) * res)
            if grid["cells"][y * w + x] != "." or math.dist(p, goal) > radius_m:
                continue
            free += 1
            unseen += not seen_at(p)
    return unseen / free if free else 0.0
