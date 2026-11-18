"""Look before you step (stream A, 2026-11-17; the operator chose both this rule and side scanning, this one first): the
duck walks only over floor its depth sensor has seen.

Exploring batch b2 run 2 walked east along the staircase opening's south edge and cut its corner: the opening was never
in the 45 deg wedge (first beside the duck, then a few cm left of the wedge's edge, the corner itself in the blind zone
under the head), mapd draws the stairwell as free (upstream #599), and no drop was remembered; the harness's truth guard
ended the run 0.05 m from the opening. Here, the strip the duck is about to walk over is checked against the floor the
sensor has seen; the first unseen spot is returned for the navigator to look at before stepping on.

Pure: unseen_ahead(path_ahead, pose, seen) -> the nearest unseen spot in the strip, or None.
"""

import math

FROM_M = 0.20       # nearer than this the sensor cannot see the floor (under the head): seen on the way, or not checked
TO_M = 0.40         # the strip checked: about a second and a half of walking at ARC_MPS-WALK_MPS
HALF_WIDTH_M = 0.10  # the trunk's half width (0.083, evaluate.FOOTPRINT_M) and a margin
STEP_M = 0.05       # probe spacing, along and across: the floor cells are 5 cm (run.FLOOR_CELL_M)


def strip(path_ahead: list, pose: tuple, from_m: float = FROM_M, to_m: float = TO_M,
          half_width_m: float = HALF_WIDTH_M, step_m: float = STEP_M) -> list:
    """Probe points covering the part of the path between from_m and to_m of walking from the pose, across the duck's
    width, nearest first. The path is followed from the pose through path_ahead's points."""
    pts = [tuple(pose[:2])] + [tuple(q[:2]) for q in path_ahead]
    out, walked = [], 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        s = 0.0
        while s <= seg:
            d = walked + s
            if d > to_m:
                return out
            if d >= from_m:
                cx, cy = a[0] + ux * s, a[1] + uy * s
                n = round(half_width_m / step_m)
                for k in sorted(range(-n, n + 1), key=abs):
                    out.append((cx - uy * k * step_m, cy + ux * k * step_m))
            s += step_m
        walked += seg
    return out


def unseen_ahead(path_ahead: list, pose: tuple, seen, skip=(), **kw) -> tuple | None:
    """The nearest probe point of the strip ahead where seen(point) is false, or None when the sensor has seen floor
    under all of it. skip: points already looked at and found walkable or settled otherwise (within STEP_M)."""
    for p in strip(path_ahead, pose, **kw):
        if seen(p):
            continue
        if any(math.dist(p, q) <= STEP_M for q in skip):
            continue
        return p
    return None
