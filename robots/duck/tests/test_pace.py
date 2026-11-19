"""Pace from the map ahead (nav/pace.py, RFC-0012 section 2.2; no simulator). Run: cd robots/duck && uv run python tests/test_pace.py"""

import sys

from duck_lab.nav import pace
from duck_lab.nav.grid import CostGrid
from duck_lab.profile import load

P = load("sim")
PACE = P.locomotion.pace
NUMS = dict(look_m=PACE.look_m, unknown_reach_m=PACE.unknown_reach_m, narrow_m=P.locomotion.slow_clearance_m,
            drop_near_m=P.error_budget.drop_inflate_m + P.error_budget.corridor_m)
FP = P.footprint

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def grid(rows: list, res: float = 0.05) -> CostGrid:
    """rows from the highest y down, as written: '.' free, '#' wall, '?' unknown."""
    rows = rows[::-1]
    g = {"res_m": res, "origin": [0.0, 0.0], "width": len(rows[0]), "height": len(rows), "cells": "".join(rows)}
    return CostGrid.from_map_grid(g, lethal_m=FP.lethal_m, inflate_m=FP.inflate_m)


def way(x0, x1, y=0.5, step=0.1):
    n = round((x1 - x0) / step)
    return [(x0 + step * i, y) for i in range(1, n + 1)]


W = 60
open_floor = grid(["." * W] * 20)
check("the profile's pace: caution is the slowest walk, cruise the cruise", PACE.caution_mps == P.locomotion.slowest_mps < P.locomotion.cruise_mps)
kind, why, v = pace.pace(open_floor, way(0.5, 2.5), (0.5, 0.5, 0.0), [], **NUMS)
check("known open floor with nothing near the way: cruise", kind == pace.CRUISE, (kind, why, v))

kind, why, v = pace.pace(open_floor, way(0.5, 2.5), (0.5, 0.5, 0.0), [(1.0, 0.5 + 0.6)], **NUMS)
check("a known drop 0.6 m beside the way, 0.5 m ahead: caution, by the drop", kind == pace.CAUTION and v["trigger"] == "drop", (kind, why, v))
kind, why, v = pace.pace(open_floor, way(0.5, 2.5), (0.5, 0.5, 0.0), [(2.2, 0.5 + 0.6)], **NUMS)
check("... not yet when it is past the look distance (1.7 m ahead of 0.7)", kind == pace.CRUISE, (kind, why, v))
kind, why, v = pace.pace(open_floor, way(0.5, 2.5), (0.5, 0.5, 0.0), [(1.0, 0.5 + 1.2)], **NUMS)
check("... nor when it is beyond the error budget's reach of the way (1.2 m aside)", kind == pace.CRUISE, (kind, why, v))

corridor = grid(["." * W] * 6 + ["#" * W] + ["." * W] * 6 + ["#" * W] + ["." * W] * 6)
kind, why, v = pace.pace(corridor, way(0.5, 2.5, y=0.5), (0.5, 0.5, 0.0), [], **NUMS)
check("a passage 0.3 m wide between two walls: caution, narrow", kind == pace.CAUTION and v["trigger"] == "narrow", (kind, why, v))

unseen = grid(["." * 30 + "?" * 30] * 20)
kind, why, v = pace.pace(unseen, way(1.2, 3.0), (1.2, 0.5, 0.0), [], **NUMS)
check("unseen floor within 0.4 m along the way (known to x = 1.5): caution, unknown", kind == pace.CAUTION and v["trigger"] == "unknown", (kind, why, v))
kind, why, v = pace.pace(unseen, way(0.5, 3.0), (0.5, 0.5, 0.0), [], **NUMS)
check("... and cruise while it is farther than that (0.9 m ahead, past the 0.4 m reach)", kind == pace.CRUISE, (kind, why, v))

pts = pace.ahead(way(0.5, 2.5), (0.5, 0.5, 0.0), 0.7)
check("ahead: the pose, then every 0.1 m out to the look distance", [round(d, 2) for _, d in pts] == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
      [round(d, 2) for _, d in pts])
check("ahead: a short path is all of it", len(pace.ahead([(0.6, 0.5)], (0.5, 0.5, 0.0), 0.7)) == 2)

print("PACE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
