"""Exploring (RFC-0002 §3.8, step 7): the nearest worthwhile frontier — seen floor next to unknown.

Pure: frontiers(map_grid, scale) -> clusters of frontier points (map metres, scaled like the
navigator's grid); pick(clusters, pose, avoid) -> the point to go to next, or None.
"""

import math

MIN_CLUSTER_M = 0.20       # frontier stretches shorter than this are noise, not a way on
AVOID_M = 0.40             # a target this close to a failed one, a drop or an obstacle is skipped
STANDOFF_M = 0.15          # stop this far back from the frontier, on the seen side
# The floor right round the duck stays unknown (the depth sensor does not see its own feet), so the
# nearest "frontier" is always underfoot: the first trial's first leg went 5 cm.
MIN_DIST_M = 0.6
GAIN_PER_M = 1.0           # a metre of frontier is worth a metre of walking (explore_lite's gain/potential)


def frontiers(grid: dict, scale: float = 1.0) -> list:
    """Clusters (8-connected) of free cells with an unknown neighbour, as lists of map points."""
    res, (ox, oy) = grid["res_m"] * scale, (grid["origin"][0] * scale, grid["origin"][1] * scale)
    w, h, cells = grid["width"], grid["height"], grid["cells"]
    if not res or not w or not h:
        return []

    def at(x, y):
        return cells[y * w + x] if 0 <= x < w and 0 <= y < h else "?"

    front = set()
    for y in range(h):
        for x in range(w):
            if at(x, y) != ".":
                continue
            if any(at(x + dx, y + dy) == "?" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
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
