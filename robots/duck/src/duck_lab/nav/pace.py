"""Pace: how fast to walk, from the map ahead (RFC-0012 §2.2). Pure: the cost grid, the path and the known hazards in, a pace out.

A robot has a few named speeds. Cruise is the way ahead known and clear; caution is anything near the way that a slower walk
helps with (more frames per metre, more time to decide): a known drop or edge near the path, a narrow passage, floor the map has
not seen. Creep (the last part before a stop or through a squeeze) is the same speed for the duck, which cannot walk slower than
caution (`locomotion.slowest_mps`). What is looked at is the path's next `look_m` (the profile's `locomotion.pace`), so it slows
before it arrives. The duck's numbers are the profile's; the two distances that are the error budget's and the follower's are
passed in, not repeated.
"""

import math

from duck_lab.nav.grid import SHADOW_COST, UNKNOWN_COST, clearance

CRUISE, CAUTION = "cruise", "caution"
SAMPLE_M = 0.1                 # the path is looked at every 0.1 m (its waypoints are 0.1 m apart once thinned; the follower's tail is 0.3)


def ahead(path: list, pose: tuple, look_m: float) -> list:
    """(point, distance along the path) from the pose, every SAMPLE_M, out to look_m: the pose itself, then the path from its
    next waypoint on (the follower's, which is the lookahead's target and past)."""
    out, here, travelled = [(pose[:2], 0.0)], pose[:2], 0.0
    for q in path:
        seg = math.dist(here, q)
        n = max(1, math.ceil(seg / SAMPLE_M - 1e-9))
        for k in range(1, n + 1):
            p = (here[0] + (q[0] - here[0]) * k / n, here[1] + (q[1] - here[1]) * k / n)
            d = travelled + seg * k / n
            if d > look_m + 1e-9:
                return out
            out.append((p, d))
        travelled += seg
        here = q
    return out


def pace(costs, path: list, pose: tuple, hazards: list, *, look_m: float, unknown_reach_m: float, narrow_m: float,
         drop_near_m: float) -> tuple:
    """(CRUISE or CAUTION, the reason, the numbers it compared): the nearest trigger along the path's next look_m.
    hazards: the known drops and measured edges (map metres); narrow_m: a point of the path with an obstacle closer than this
    is a narrow passage; drop_near_m: a hazard closer to the path than this is near the way; unknown_reach_m: floor the map has
    not seen (an unknown cell, or one in the shadow of a wall) within this far along the path."""
    for p, d in ahead(path, pose, look_m):
        near = min((math.dist(p, h) for h in hazards), default=math.inf)
        if near < drop_near_m:
            return CAUTION, "a known drop beside the way", {"trigger": "drop", "along_m": round(d, 2), "distance_m": round(near, 3),
                                                            "limit_m": drop_near_m}
        room = clearance(costs, p, narrow_m)
        if room < narrow_m:
            return CAUTION, "a narrow passage ahead", {"trigger": "narrow", "along_m": round(d, 2), "distance_m": round(room, 3),
                                                       "limit_m": narrow_m}
        if d <= unknown_reach_m:
            c = costs.cell(*p)
            if costs.inside(*c) and costs.at(*c) in (UNKNOWN_COST, SHADOW_COST):
                return CAUTION, "floor ahead the map has not seen", {"trigger": "unknown", "along_m": round(d, 2),
                                                                     "limit_m": unknown_reach_m}
    return CRUISE, "the way ahead is known and clear", {"look_m": look_m}
