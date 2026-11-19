"""Replay the planner on recorded exploring runs with the margin ring flat (the old cost) and graded (grid.margin_cost):
for each recorded plan, the navigator's map as the run's last "world" event before it gave it (mapd's grid, the obstacle
points, the drops), the plan's pose and goal; each version's path, its length and its closest approach to an obstacle
(clearance at every path point). The question: do paths keep further off obstacles where there is room, without getting
much longer, and does anything that was reachable become unreachable?

    .venv/bin/python sim/probes/margin_replay.py runs/explore-b5-r2 runs/explore-b3-r3 ...
"""

import json
import statistics
import sys
from pathlib import Path

from duck_lab.nav import grid as G
from duck_lab.profile import load as load_profile

PROFILE = load_profile("sim")
from duck_lab.nav.grid import CostGrid, clearance, path_length, plan

FLAT = lambda d, lethal_m, inflate_m: G.MARGIN_COST  # noqa: E731
GRADED = G.margin_cost


def costs(world: dict) -> CostGrid:
    blocked = [tuple(p) for p in world.get("blocked", [])]
    c = CostGrid.from_map_grid(world["grid"], explained_by=blocked, lethal_m=PROFILE.footprint.lethal_m,
                               inflate_m=PROFILE.footprint.inflate_m).with_points(blocked)
    drops = [tuple(d[:2]) for d in world.get("drops", [])]
    return c.with_blocked(drops, PROFILE.error_budget.drop_lethal_m, PROFILE.error_budget.drop_inflate_m) if drops else c


rows, lost, gained = [], 0, 0
for run in map(Path, sys.argv[1:]):
    world = None
    for line in open(run / "ticks.jsonl"):
        r = json.loads(line)
        if r.get("event") == "world":
            world = r
        if r.get("event") != "plan" or world is None or not r.get("path"):
            continue
        out = {}
        for name, fn in (("flat", FLAT), ("graded", GRADED)):
            G.margin_cost = fn
            try:
                cg = costs(world)
                p = plan(cg, tuple(r["pose"][:2]), tuple(r["goal"]))
            except Exception:  # noqa: BLE001 - an empty map: skip the plan
                p = None
            if p:
                inner = p[2:-2] or p                     # its start and end are where they are
                out[name] = (path_length(p), min(clearance(cg, q, 0.5) for q in inner))
            else:
                out[name] = None
        G.margin_cost = GRADED
        if out["flat"] and not out["graded"]:
            lost += 1
        if out["graded"] and not out["flat"]:
            gained += 1
        if out["flat"] and out["graded"]:
            rows.append((run.name, r["t"], out["flat"], out["graded"]))

near_flat = sum(f[1] < 0.15 for _, _, f, g in rows)
near_graded = sum(g[1] < 0.15 for _, _, f, g in rows)
longer = [g[0] / f[0] - 1 for _, _, f, g in rows if f[0] > 0]
print(f"MARGIN-REPLAY plans {len(rows)} (+{lost} reachable only with the flat ring, +{gained} only with the graded)")
print(f"  closest approach median: flat {statistics.median(f[1] for _, _, f, _ in rows):.3f} m, graded "
      f"{statistics.median(g[1] for _, _, _, g in rows):.3f} m")
print(f"  plans passing within 0.15 m of an obstacle: flat {near_flat}, graded {near_graded}")
print(f"  path length, graded vs flat: median {statistics.median(longer) * 100:+.1f} %, worst {max(longer) * 100:+.1f} %")
