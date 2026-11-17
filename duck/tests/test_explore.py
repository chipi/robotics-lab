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
cl = frontiers(g, wall_m=0)     # the basics, without the seen-wall rule (tested below)
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
scaled = frontiers(g, scale=0.9, wall_m=0)     # a 3-row room: every frontier is within 0.3 m of its walls
check("scale applies to the frontier points like the navigator's grid", max(p[0] for p in scaled[0]) < max(p[0] for p in frontiers(g, wall_m=0)[0]))

# Unknown beside a seen wall is that wall going on (baseline b1: targets inside the corridor wall, the cabinet). A wall
# seen to x=0.4, unknown past it: the free cells within 0.3 m of the wall's end are no way on; the open edge further from
# it still is.
#                    x: 0123456789
wall_end = grid(["??????????",
                 "????######",
                 "?.........",
                 "?.........",
                 "?.........",
                 "?.........",
                 "?.........",
                 "??????????"])
we = [p for c in frontiers(wall_end) for p in c]
check("no frontier within 0.3 m of a seen wall", we and all(min(math.dist(p, (x / 10 + 0.05, 6.5 / 10)) for x in range(4, 10))
                                                            > 0.3 for p in we), sorted(we)[:3])
check("... the open edges away from it stay frontiers", any(p[1] < 0.25 for p in we), sorted(we, key=lambda p: p[1])[:2])
check("with wall_m 0 the old behaviour: frontier right under the wall's end", any(
    math.dist(p, (0.35, 0.55)) < 0.06 for c in frontiers(wall_end, wall_m=0) for p in c))
# A 0.8 m doorway (res 0.1) in a seen wall, unknown beyond: its middle is still a way on.
#                     x: 0123456789ab
door_open = grid(["????????????",
                  "#..........#",
                  "#..........#",
                  "#..........#",
                  "#..........#",
                  "#..........#",
                  "#..........#",
                  "#..........#",
                  "############"])
dm = [p for c in frontiers(door_open) for p in c]
check("a 0.8 m doorway keeps its middle as a frontier", dm and all(0.4 <= p[0] <= 0.8 for p in dm), sorted(dm))
check("... and not its sides", not any(p[0] < 0.4 or p[0] > 0.8 for p in dm))
# The same doorway, its wall known only as the navigator's obstacle points (mapd left those cells unknown).
door_unseen = grid(["????????????",
                    "????????????",
                    "#..........#",
                    "#..........#",
                    "#..........#",
                    "#..........#",
                    "#..........#",
                    "#..........#",
                    "############"])
pts = [(x / 10 + 0.05, 0.75) for x in (0, 1, 10, 11)]
dp = [p for c in frontiers(door_unseen, obstacles=pts) for p in c]
check("the navigator's obstacle points count as a wall too", dp and all(0.4 <= p[0] <= 0.8 for p in dp), sorted(dp))
post = [(0.55, 0.75)]              # a post the depth sensor saw, in the open edge's unknown
near_post = [p for c in frontiers(door_unseen, obstacles=post) for p in c if math.dist(p, post[0]) <= 0.3]
check("... a frontier cell within 0.3 m of an obstacle point is no way on", not near_post, near_post)

print("EXPLORE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
