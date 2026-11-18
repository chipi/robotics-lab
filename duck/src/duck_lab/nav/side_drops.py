"""Drops beside the way: suspected from the forward sensor, confirmed or cleared by a glance (docs/wip/SIDE-DROPS.md,
RFC-0008 §4's drops "suspected or confirmed", RFC-0012's first attention trigger).

The forward sensor's below-floor returns ("below": under the floor by more than cliff.EXTRA_M) fall inside a real drop
in every recorded run of challenges 10 and 11. One by one they cannot be trusted: drop-free runs have 14-72 each. Kept
per cell, a cell that keeps putting below returns there, more often than floor, is a drop suspected: replayed over the
recorded challenge runs (sim/probes/below_cells.py), K 5 / ratio 3 caught 36 of 40 side drops 14-18 s before the closest
approach, with a false cell in 8 of 273 drop-free runs (at most 2 cells). A glance confirms or clears a suspicion
(sim/probes/glance_floor.py: no false drops in 14 looks; the edge within -4.7/+0.6 cm).
"""

import collections
import math

from duck_lab.nav.cliff import EXTRA_M

CELL_M = 0.05
BELOW_SLOPE = 0.035          # m more below the floor per m of range (below_counts; replayed, docs/wip/SIDE-DROPS.md)
SUSPECT_FRAMES = 5           # frames that put a below-floor return in the cell
SUSPECT_RATIO = 3.0          # and at least this many times the frames that put floor there
# floor a glance saw this near a suspected cell clears it: returns lie a few cm apart at 0.8 m and the map drifts between
# the suspicion and the look (challenge 10 seed 8: 5 cm left a suspicion beside the goal, and the leg was refused)
CLEAR_M = 0.10


def below_counts(height_m: float, range_m: float) -> bool:
    """A below-floor return (height above the floor, negative) deep enough for its range to count toward a suspicion:
    cliff.EXTRA_M at the duck, BELOW_SLOPE more a metre. A far floor return read just past EXTRA_M is the trunk's pitch
    (walking sway), not a hole: 3 deg at 1.5 m is 8 cm (the false suspicions that closed challenge 10's goal sat 6.6-7.9
    cm below, 1.1-2.4 m away)."""
    return height_m <= -(EXTRA_M + BELOW_SLOPE * range_m)


def cell_of(x: float, y: float) -> tuple:
    return round(x / CELL_M), round(y / CELL_M)


class SuspectMemory:
    """Below-floor and floor frames per cell (map frame); the cells that became suspected drops."""

    def __init__(self, frames: int = SUSPECT_FRAMES, ratio: float = SUSPECT_RATIO):
        self.frames, self.ratio = frames, ratio
        self.below, self.floor = collections.Counter(), collections.Counter()
        self.suspected = set()          # cells
        self.cleared = set()            # cells a glance saw as floor: never suspected again from the forward sensor
        self.confirmed = set()          # cells taken into a measured drop: not suspected again either

    def add_frame(self, points: list) -> list:
        """points: (x, y, kind) in the map frame, one frame's. Returns the cells newly suspected."""
        fb = {cell_of(x, y) for x, y, k in points if k == "below"}
        ff = {cell_of(x, y) for x, y, k in points if k == "floor"}
        for c in fb:
            self.below[c] += 1
        for c in ff:
            self.floor[c] += 1
        new = []
        for c in fb:
            if c in self.suspected or c in self.cleared or c in self.confirmed:
                continue
            if self.below[c] >= self.frames and self.below[c] >= self.ratio * self.floor[c]:
                self.suspected.add(c)
                new.append(c)
        return new

    def points(self) -> list:
        return [(c[0] * CELL_M, c[1] * CELL_M) for c in sorted(self.suspected)]

    def near(self, xy: tuple, within_m: float) -> list:
        """Suspected cells within within_m of xy, as points."""
        return [p for p in self.points() if math.dist(p, xy) <= within_m]

    def clear(self, floor_points: list, within_m: float = CLEAR_M) -> int:
        """A glance saw floor there: the suspected cells within within_m of floor_points are cleared. Returns how many."""
        # over a copy: the depth-frame thread adds cells meanwhile (challenge 9, gate6: "Set changed size during
        # iteration"); copying a set is one C call, which that thread cannot interleave with
        gone = {c for c in set(self.suspected)
                if any(math.dist((c[0] * CELL_M, c[1] * CELL_M), q) <= within_m for q in floor_points)}
        self.suspected -= gone
        self.cleared |= gone
        return len(gone)

    def confirm_near(self, edge_points: list, within_m: float) -> list:
        """Suspected cells within within_m of a measured edge's points are that drop: they leave the suspected set,
        confirmed without a glance. Returns their points."""
        got = sorted(c for c in set(self.suspected)       # over a copy, as clear
                     if any(math.dist((c[0] * CELL_M, c[1] * CELL_M), q) <= within_m for q in edge_points))
        self.suspected -= set(got)
        self.confirmed |= set(got)
        return [(c[0] * CELL_M, c[1] * CELL_M) for c in got]


def in_the_way(path: list, suspected: list, within_m: float) -> list:
    """The suspected drops within within_m of a path's segments, in the order given."""
    def seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        return math.dist(p, (a[0] + t * dx, a[1] + t * dy))
    segs = list(zip(path, path[1:])) or [(q, q) for q in path]
    return [p for p in suspected if any(seg(p, a, b) <= within_m for a, b in segs)]


# Where a hole met head-on ends (the operator's choice, 2026-11-17): a cliff stop sees 20-40 cm of an edge, so the duck
# looks along it both ways. A drop's lethal ring then only has to cover the measurement's error; its length is looked at,
# not assumed (DROP_LETHAL_M 0.45 had done both, and closed challenge 11's passage while keeping challenge 9's refusal).
CONTINUES_M = 0.15          # a rim point this near a look's target: the drop goes on there


def edge_axis(points: list, heading: float) -> tuple:
    """The unit direction of the edge a cliff stop saw: the principal axis of its points when they spread sideways over
    more than a cell, else across the heading (one column of points lies along the beam: its axis is the beam's)."""
    c, s = math.cos(heading), math.sin(heading)
    lateral = [-(p[0]) * s + p[1] * c for p in points]
    if len(points) >= 2 and max(lateral) - min(lateral) > CELL_M:
        mx, my = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
        sxx = sum((p[0] - mx) ** 2 for p in points)
        syy = sum((p[1] - my) ** 2 for p in points)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
        a = 0.5 * math.atan2(2 * sxy, sxx - syy)
        return math.cos(a), math.sin(a)
    return -s, c


def _ends(points: list, heading: float) -> tuple:
    """The edge's centre, its axis, and the extent of the points along it (lo, hi)."""
    ux, uy = edge_axis(points, heading)
    mx, my = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    ts = [(p[0] - mx) * ux + (p[1] - my) * uy for p in points]
    return (mx, my), (ux, uy), min(ts), max(ts)


def look_targets(points: list, heading: float, beyond_m: float) -> list:
    """The two points to look at: on the edge's line, beyond_m past each end of what the stop saw."""
    (mx, my), (ux, uy), lo, hi = _ends(points, heading)
    return [(mx + (lo - beyond_m) * ux, my + (lo - beyond_m) * uy), (mx + (hi + beyond_m) * ux, my + (hi + beyond_m) * uy)]


def continues(rim: list, target: tuple, within_m: float = CONTINUES_M) -> bool:
    """A look at target found the drop going on there: its rim reaches the target."""
    return any(math.dist(p, target) <= within_m for p in rim)


def continuation(points: list, heading: float, side: int, length_m: float, step_m: float = 0.05) -> list:
    """Points along the edge's line beyond the seen end on one side (side -1: the lo end, +1: the hi end), length_m long:
    the hole taken to go on where a look saw it go on, or could not see."""
    (mx, my), (ux, uy), lo, hi = _ends(points, heading)
    start = hi if side > 0 else lo
    n = int(round(length_m / step_m))
    return [(mx + (start + side * k * step_m) * ux, my + (start + side * k * step_m) * uy) for k in range(1, n + 1)]


SETTLE_FRAMES, SETTLE_TOL_DEG = 5, 3.0


def head_settled(dirs: list, frames: int = SETTLE_FRAMES, tol_deg: float = SETTLE_TOL_DEG) -> bool:
    """dirs: the sensor's (yaw, pitch) in degrees against the trunk, one per frame since the look was commanded. Settled:
    the last `frames` hold within tol_deg in both, and the sensor has moved more than tol_deg from where it faced in yaw or
    pitch (frames from before the head started to move are not the look). Yaw alone never settled a look straight ahead,
    which only pitches the head down (challenge 11 seed 5)."""
    if len(dirs) < frames:
        return False
    last = dirs[-frames:]
    still = all(max(d[i] for d in last) - min(d[i] for d in last) < tol_deg for i in (0, 1))
    moved = any(abs(dirs[-1][i] - dirs[0][i]) > tol_deg for i in (0, 1))
    return still and moved


def edge_from_glance(frames: list, origin: tuple, bearing: float) -> tuple:
    """A glance's frames, each a list of (x, y, kind) in the map frame, seen from origin (x, y): (rim, below, floor). The
    floor's boundary is traced per direction from origin, in BIN_DEG bins of bearing, all frames pooled (a frame that saw only the
    pit's far wall in a bin started its run there): in each bin, the end of the
    floor's run out from the duck (no gap in range over RIM_GAP_M) short of the bin's nearest below-floor return. rim:
    those boundary points, which lie along the real edge
    whatever the angle of the look to it (taking the farthest floor along the look's own direction instead put the rim
    across the look, and extended that across the way: challenge 11 seed 2 then planned into an unseen block); below: the
    below-floor returns beyond their bin's boundary; floor: every floor return. No below return in a bin: no rim there.
    bearing is kept for the caller's record."""
    rim, below, floor = [], [], []

    def polar(p):
        dx, dy = p[0] - origin[0], p[1] - origin[1]
        return int(math.floor(math.degrees(math.atan2(dy, dx)) / BIN_DEG)), math.hypot(dx, dy)

    bins_f, bins_b = collections.defaultdict(list), collections.defaultdict(list)
    for pts in frames:
        for x, y, k in pts:
            if k == "floor":
                floor.append((x, y))
                b, r = polar((x, y))
                bins_f[b].append((r, (x, y)))
            elif k == "below":
                b, r = polar((x, y))
                bins_b[b].append((r, (x, y)))
    for b, bs in bins_b.items():
        nearest = min(r for r, _ in bs)
        short = sorted((r, p) for r, p in bins_f.get(b, ()) if r < nearest)
        if not short:
            # below-floor returns and no floor before them: a drop (challenge 11 seed 8: the duck stood ~0.17 m from the
            # pit; this look reported floor and cleared a true suspicion). Its rim is the nearest of them; the edge may lie
            # nearer, but a look aimed far does not see the near floor at all, so the floor between is unknown, not drop
            # (marking it drop put a "drop" 0.11 m from the duck in seed 6). A stray return or two is not a drop.
            if len(bs) >= UNSEEN_RIM_MIN:
                r0, p0 = min(bs)
                rim.append(p0)
                below.extend(p for r, p in bs if r > r0)
            continue
        r_rim, p_rim = short[0]
        for r, p in short[1:]:
            if r - r_rim > RIM_GAP_M:
                break
            r_rim, p_rim = r, p
        rim.append(p_rim)
        below.extend(p for r, p in bs if r > r_rim)
    return rim, below, floor


BIN_DEG = 4.0
# The floor's run from the duck ends at a gap in range wider than this: floor returns beyond it are not the floor the duck
# stands on (challenge 10 seed 1: the pit's far wall, whose band at floor height reads as floor, became the rim).
RIM_GAP_M = 0.15
UNSEEN_RIM_MIN = 5          # below-floor returns in a direction (all the look's frames) to call it a drop with no floor seen

