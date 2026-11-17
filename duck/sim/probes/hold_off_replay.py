"""At a recorded "no path" refusal: would holding the goal off have given a way (run.HOLD_OFF_M, HOLD_DETOUR)? The grid
rebuilt from the last world record and the refusal's own drops and edges (split rings), nearest_free(goal, HOLD_OFF_M),
and a plan from the pose, kept only when no longer than HOLD_DETOUR times the straight line + 0.3 m.

    uv run python sim/probes/hold_off_replay.py ch10-s2/run-... ch8-s1/run-...
"""
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, CostGrid, nearest_free, path_length, plan
from duck_lab.nav.run import EDGE_INFLATE_M, EDGE_LETHAL_M, HOLD_DETOUR, HOLD_OFF_M

for run in sys.argv[1:]:
    world = ref = None
    for t, k, p in Follower(Path("/work/robotics-lab/data/runs/duck") / run, keep_raw=True).poll():
        if k == "world":
            world = p
        elif k == "event" and p.get("kind") == "refused" and (p.get("raw") or {}).get("goal"):
            ref = p["raw"]
    g0 = world["grid"]
    grid = CostGrid.from_map_grid({"res_m": g0["res"], "origin": g0["origin"], "width": g0["w"], "height": g0["h"],
                                   "cells": g0["cells"]}, explained_by=world.get("obstacles") or [])
    drops, edges = [tuple(d) for d in ref.get("drops") or []], [tuple(d) for d in ref.get("edges") or []]
    blocked = [tuple(b) for b in world.get("obstacles") or []]
    goal, pose = tuple(ref["goal"]), tuple(ref["pose"][:2])
    grid = grid.covering([pose, goal] + blocked + drops + edges).with_points(blocked)
    grid = grid.with_blocked(drops, DROP_LETHAL_M, DROP_INFLATE_M).with_blocked(edges, EDGE_LETHAL_M, EDGE_INFLATE_M)
    aim = nearest_free(grid, goal, HOLD_OFF_M)
    p = plan(grid, pose, aim) if aim else None
    if p and path_length([pose] + p) > HOLD_DETOUR * math.dist(pose, aim) + 0.3:
        p = None
    print(f"{run}: goal lethal {grid.at(*grid.cell(*goal)) >= 1e9}; held-off aim "
          f"{None if aim is None else [round(v, 3) for v in aim]} ({'-' if aim is None else f'{math.dist(aim, goal):.3f} m short'}); "
          f"plan {'none' if p is None else f'{path_length([pose] + p):.2f} m'}; robot {math.dist(pose, goal):.3f} m from the goal")
