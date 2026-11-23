"""The explorer's hazard set is the planner's (explore_run.Explorer.avoid / hazard_costs), and a frontier beside floor the
sensor never saw is measured (explore.rim_unseen, recorded, not enforced; challenge 22's rim, docs/wip/CH22-RIM.md). No simulator.
Run: cd robots/duck && uv run python tests/test_explore_hazards.py"""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from duck_lab.nav import explore
from duck_lab.nav.explore import frontiers, pick, rim_unseen
from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.grid import LETHAL_COST, CostGrid
from duck_lab.nav.run import Navigator

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def grid(rows, res=0.1):
    rows = list(reversed(rows))
    return {"res_m": res, "origin": [0.0, 0.0], "width": len(rows[0]), "height": len(rows), "cells": "".join(rows)}


def explorer(drops=(), edges=(), suspected=(), failed=()):
    nav = SimpleNamespace(drops=list(drops), edges=list(edges), suspects=SimpleNamespace(points=lambda: list(suspected)),
                          drop_lethal_m=0.35, drop_inflate_m=0.55, edge_lethal_m=0.2, edge_inflate_m=0.35)
    nav.hazards = lambda: Navigator.hazards(nav)
    ex = Explorer.__new__(Explorer)
    ex.nav, ex.failed = nav, list(failed)
    return ex


# the explorer avoids what the planner avoids: drops, the edges a glance measured, the suspected drops
ex = explorer(drops=[(0.5, 0.5)], edges=[(1.0, 0.0)], suspected=[(0.0, 1.0)], failed=[(2.0, 2.0)])
check("avoid: failed targets, drops, edges and suspects", set(ex.avoid()) == {(2.0, 2.0), (0.5, 0.5), (1.0, 0.0), (0.0, 1.0)}, ex.avoid())
line = [(1.2, y / 10) for y in range(-2, 3)]           # a frontier 0.2-0.3 m from an edge point at (1.0, 0.0)
picked = pick([line], (0.0, 0.0, 0.0), explorer(edges=[(1.0, 0.0)]).avoid())
check("must fail: a frontier target within AVOID_M of an edge is skipped", picked is None, picked)
check("... and with no edge remembered the same frontier is picked", pick([line], (0.0, 0.0, 0.0), explorer().avoid()) is not None)

open_room = grid(["..........."] * 12)
base = CostGrid.from_map_grid(open_room, lethal_m=0.12, inflate_m=0.3)
for kind, ex in (("a drop", explorer(drops=[(0.3, 0.3)])), ("an edge", explorer(edges=[(0.3, 0.3)])),
                 ("a suspected drop", explorer(suspected=[(0.3, 0.3)]))):
    c = ex.hazard_costs(base)
    cx, cy = c.cell(0.3, 0.38)
    check(f"reachability costs: a goal 8 cm from {kind} is lethal", c.at(cx, cy) >= LETHAL_COST, c.at(cx, cy))
far = explorer(edges=[(0.3, 0.3)]).hazard_costs(base)
check("... and one 0.6 m away is not", far.at(*far.cell(0.3, 0.9)) < LETHAL_COST)
out_of_grid = explorer(edges=[(0.3, 3.0)]).hazard_costs(base)
check("an edge beyond mapd's grid still grows its zone (covering)", out_of_grid.inside(*out_of_grid.cell(0.3, 3.0)))

# the rim: a frontier whose standing place has floor the sensor never saw beside it
fx = json.loads((Path(__file__).parent / "fixtures" / "ch22_rim_pick.json").read_text())
g, res, (ox, oy), w = fx["grid"], fx["grid"]["res_m"], fx["grid"]["origin"], fx["grid"]["width"]


def seen_at(p):
    return fx["hole"][int((p[1] - oy) // res) * w + int((p[0] - ox) // res)] == "0"


def standable(goal):
    """What the run's reachable() asked, approximated: mapd free at the goal, floor seen within 0.1 m of it."""
    cx, cy = int((goal[0] - ox) // res), int((goal[1] - oy) // res)
    near = [(ox + (cx + dx + 0.5) * res, oy + (cy + dy + 0.5) * res) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)]
    return g["cells"][cy * w + cx] == "." and any(seen_at(p) and math.dist(p, goal) <= 0.1 for p in near)


clusters = frontiers(g, 1.0, obstacles=[tuple(p) for p in fx["obstacles"]])
avoid, pose, rec = [tuple(a) for a in fx["avoid"]], tuple(fx["pose"]), tuple(fx["target"])
check("fixture: the recorded pick replays to the recorded target", (got := pick(clusters, pose, avoid, ok=standable)) is not None
      and math.dist(got, rec) < 0.05, got)
share = rim_unseen(g, rec, seen_at)
check("the recorded target stood on the hole's rim: much of the free ground round it was never seen", share >= explore.RIM_UNSEEN, round(share, 3))
check("... a target out in the room has none", rim_unseen(g, (0.5, -1.0), seen_at) == 0.0, rim_unseen(g, (0.5, -1.0), seen_at))
after = pick(clusters, pose, avoid, ok=lambda goal: standable(goal) and rim_unseen(g, goal, seen_at) < explore.RIM_UNSEEN)
check("must fail: with the rim rule the recorded target is not picked", after is None or math.dist(after, rec) > 0.3, after)
check("... what is picked instead is clear of the hole", after is None or rim_unseen(g, after, seen_at) < explore.RIM_UNSEEN)

shadow = grid(["..........", "..........", "..........", "..........", ".........."])
check("rim_unseen: all seen is 0", rim_unseen(shadow, (0.5, 0.25), lambda p: True) == 0.0)
check("rim_unseen: none seen is 1", rim_unseen(shadow, (0.5, 0.25), lambda p: False) == 1.0)
check("rim_unseen: unknown cells are not counted", rim_unseen(grid(["??????????"] * 5), (0.5, 0.25), lambda p: False) == 0.0)
half = rim_unseen(shadow, (0.5, 0.25), lambda p: p[0] < 0.5)
check("rim_unseen: half the ring unseen is about half", 0.3 < half < 0.7, round(half, 3))

print("EXPLORE HAZARDS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
