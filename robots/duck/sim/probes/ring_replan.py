"""KNOWN-ISSUES K27: each refused leg of an exploring run, re-planned on the world it was refused on (the last "world" event before
it) with the drop ring at each size given: plannable or not, and the goal's distance to the nearest remembered drop.

    .venv/bin/python sim/probes/ring_replan.py <ticks.jsonl> <lethal_m>[,<lethal_m>...]
"""
import json
import math
import sys

from duck_lab.nav.grid import CostGrid, plan
from duck_lab.profile import load

P = load("sim")
sizes = [float(x) for x in sys.argv[2].split(",")]
world = None
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r.get("event") == "world":
        world = r
    if r.get("event") != "refused" or "goal" not in r or world is None:
        continue
    blocked = [tuple(b) for b in world["blocked"]]
    drops = [tuple(d) for d in world["drops"]]
    base = CostGrid.from_map_grid(world["grid"], explained_by=blocked, lethal_m=P.footprint.lethal_m,
                                  inflate_m=P.footprint.inflate_m).with_points(blocked)
    goal, pose = tuple(r["goal"][:2]), tuple(r["pose"][:2])
    near = min((math.dist(goal, d) for d in drops), default=math.inf)
    out = []
    for s in sizes:
        g = base.with_blocked(drops, s, P.error_budget.edge_inflate_m) if drops else base
        g = g.covering([goal, pose])
        out.append(f"{s:.2f}:{'path' if plan(g, pose, goal) else 'none'}")
    print(f"t={r['t']:7.2f} goal={[round(v, 2) for v in goal]} nearest drop {near:.3f} m  " + "  ".join(out))
