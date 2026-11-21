"""For one challenge run: the tick where the trunk (truth) came closest to a drop, what the duck was doing then (vx, vyaw,
turning), the navigator's belief of the nearest drop/edge point it held (the last "world" event's drops), and how far
that believed point is from the truth trunk and from the believed pose.

    .venv/bin/python sim/probes/drop_closest.py <challenge> <seed> <ticks.jsonl>
"""
import json
import math
import sys

from labrunner.challenges import build
from labrunner.judge import Judge
from labrunner.geometry import footprint_distance

ch, seed, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
judge = Judge(build(ch, seed))
best, world, events = None, None, []
for line in open(path):
    r = json.loads(line)
    if r.get("event") == "world":
        world = r
    if r.get("event") in ("glance", "plan", "refused", "pivot", "recovery"):
        events.append((r.get("t"), r["event"], r.get("status") or r.get("why")))
    if "truth" in r and r.get("event") is None:
        p = r["truth"][:2]
        d = min(footprint_distance(p, g) for g in judge.drops)
        if best is None or d < best[0]:
            best = (d, r, world)
d, r, w = best
print(f"closest {d:.3f} m at t={r['t']:.2f}  truth={[round(x, 3) for x in r['truth']]}  pose={[round(x, 3) for x in r['pose']]}")
print(f"  vx={r.get('vx')} vyaw={r.get('vyaw')} turning={r.get('turning')} nearest_mm={r.get('nearest_mm')}")
drops = [tuple(p) for p in (w or {}).get("drops", [])]
if drops:
    near_belief = min(drops, key=lambda q: math.dist(q, r["pose"][:2]))
    print(f"  believed drop points {len(drops)}; nearest to the believed pose {math.dist(near_belief, r['pose'][:2]):.3f} m "
          f"at {near_belief}; that point is {math.dist(near_belief, r['truth'][:2]):.3f} m from the truth trunk")
else:
    print("  no believed drop points in the last world event")
print("  belief error (pose vs truth) {:.3f} m".format(math.dist(r["pose"][:2], r["truth"][:2])))
print("  events before it:", [e for e in events if e[0] is not None and e[0] <= r["t"]][-6:])
