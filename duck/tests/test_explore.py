"""Frontier exploration's pure functions. Run: cd duck && uv run python tests/test_explore.py"""

import math
import sys

from duck_lab.nav.explore import frontiers, pick

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def grid(rows, res=0.1):
    """rows top-down as drawn; map.grid is row-major from the lowest y, so reverse."""
    rows = list(reversed(rows))
    return {"res_m": res, "origin": [0.0, 0.0], "width": len(rows[0]), "height": len(rows), "cells": "".join(rows)}


#           x: 0123456789
g = grid(["??????????",
          "#........?",
          "#........?",
          "#........?",
          "##########"])
cl = frontiers(g)
check("two frontier stretches: the top edge and the right edge (one 8-connected cluster)", len(cl) == 1, len(cl))
check("frontier points are free cells next to unknown", all(0.0 < p[1] < 0.5 for p in cl[0]), cl[0][:3])
closed = grid(["##########",
               "#........#",
               "##########"])
check("a closed room has no frontier", frontiers(closed) == [])
tiny = grid(["##?#######",
             "#........#",
             "##########"])
check("a one-cell gap is noise, not a frontier (under 20 cm)", frontiers(tiny) == [])

target = pick(cl, (0.15, 0.15, 0.0), avoid=[])
check("pick: nothing underfoot - the nearest frontier at least 0.6 m away, pulled back 15 cm",
      target is not None and 0.6 - 0.15 - 1e-9 <= math.dist(target, (0.15, 0.15)) < 0.8, target)
refuse_all = pick(cl, (0.15, 0.15, 0.0), avoid=[], ok=lambda g: False)
check("pick asks ok() and returns None when nothing is acceptable", refuse_all is None)
only_far = pick(cl, (0.15, 0.15, 0.0), avoid=[], ok=lambda g: g[0] > 0.6)
check("pick returns the nearest acceptable goal", only_far is not None and only_far[0] > 0.6, only_far)
far = pick(cl, (0.15, 0.15, 0.0), avoid=[(0.15, 0.35), (0.25, 0.35), (0.35, 0.35), (0.45, 0.35), (0.55, 0.35)])
check("pick skips frontiers near something to avoid", far is None or far[0] > 0.55 or far[1] < 0.2, far)
check("pick with everything avoided: None", pick(cl, (0.15, 0.15, 0.0), avoid=[p for c in cl for p in c]) is None)
sliver = [(0.8, y / 10) for y in range(-1, 3)]            # 0.3 m of frontier, 0.8 m away
opening = [(1.5, y / 10) for y in range(-10, 11)]          # 2 m of frontier, 1.5 m away
chosen = pick([sliver, opening], (0.0, 0.0, 0.0), avoid=[])
check("pick prefers a wide opening a little further on to a sliver nearby",
      chosen is not None and chosen[0] > 1.0, chosen)
near_only = pick([sliver, [(4.0, 0.0), (4.0, 0.1), (4.0, 0.2)]], (0.0, 0.0, 0.0), avoid=[])
check("but not a small frontier far away over a near one of the same size", near_only is not None and near_only[0] < 1.0,
      near_only)
scaled = frontiers(g, scale=0.9)
check("scale applies to the frontier points like the navigator's grid", max(p[0] for p in scaled[0]) < max(p[0] for p in cl[0]))

print("EXPLORE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
