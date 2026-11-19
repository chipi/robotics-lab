"""The duck's odometry scale against simulator truth, from navigator logs (ticks.jsonl: the believed
pose and the truth each tick). Over walking stretches only (forward speed asked, no stop events),
per stretch: truth distance / believed distance. The calibration factor is the median.

    robots/duck/.venv/bin/python robots/duck/sim/odom_scale.py robots/duck/runs/phase1-run1/ticks.jsonl [more.jsonl ...]
"""
import json
import math
import statistics
import sys

NET = "--net" in sys.argv
ratios, total_truth, total_belief = [], 0.0, 0.0
for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
    rows = [json.loads(l) for l in open(path)]
    stretch = []
    for r in rows + [{}]:
        walking = r.get("vx", 0) > 0 and "event" not in r and "truth" in r and "pose" in r
        if walking:
            stretch.append(r)
            continue
        if len(stretch) >= 20:          # at least 2 s of walking
            b = math.dist(stretch[0]["pose"][:2], stretch[-1]["pose"][:2]) if NET else sum(math.dist(a["pose"][:2], c["pose"][:2]) for a, c in zip(stretch, stretch[1:]))
            t = math.dist(stretch[0]["truth"][:2], stretch[-1]["truth"][:2]) if NET else sum(math.dist(a["truth"][:2], c["truth"][:2]) for a, c in zip(stretch, stretch[1:]))
            if b > 0.3:
                ratios.append(t / b)
                total_truth += t
                total_belief += b
        stretch = []
print(f"stretches {len(ratios)}; truth/belief median {statistics.median(ratios):.3f}, "
      f"quartiles {statistics.quantiles(ratios, n=4)[0]:.3f}-{statistics.quantiles(ratios, n=4)[2]:.3f}; "
      f"pooled {total_truth / total_belief:.3f} over {total_belief:.1f} m believed")
