"""The navigator's belief against the simulator's truth while walking, by the speed commanded (K8): per speed, straight (the
turn asked under TURN_RAD_S) and turning, the belief's path length over the truth's, from the runs' ticks.jsonl (the challenge
runner's `--out`). 1.000 is a belief that walks the truth's distance; a belief step over STEP_MAX_M in one tick is a fix, not
odometry, and is left out with the truth beside it.

    robots/duck/.venv/bin/python robots/duck/sim/odom_by_speed.py <dir with run folders or ticks.jsonl files> [more ...]
"""
import collections
import json
import math
import sys
from pathlib import Path

STEP_MAX_M, GAP_MAX_S = 0.15, 0.5
TURN_RAD_S = 0.4         # the profile's locomotion.slow_yaw_rad_s: a harder turn than this is an arc


def main() -> None:
    files = []
    for a in sys.argv[1:]:
        p = Path(a)
        files += [p] if p.is_file() else sorted(p.rglob("ticks.jsonl"))
    belief, truth = collections.Counter(), collections.Counter()
    for f in files:
        rows = [r for r in map(json.loads, f.read_text().splitlines()) if "pose" in r and "truth" in r and "event" not in r]
        for a, b in zip(rows, rows[1:]):
            if a["vx"] <= 0.05 or abs(b["vx"] - a["vx"]) > 0.01 or b["t"] - a["t"] > GAP_MAX_S:
                continue
            step = math.dist(a["pose"][:2], b["pose"][:2])
            if step > STEP_MAX_M:
                continue
            key = (round(a["vx"], 2), "turning" if abs(a["vyaw"]) >= TURN_RAD_S else "straight")
            belief[key] += step
            truth[key] += math.dist(a["truth"][:2], b["truth"][:2])
    print(f"{len(files)} runs")
    for key in sorted(truth):
        print(f"commanded {key[0]:.2f} m/s, {key[1]:8}: truth {truth[key]:7.2f} m, belief {belief[key]:7.2f} m, "
              f"belief/truth {belief[key] / truth[key]:.3f}")
    print(f"all walking: belief/truth {sum(belief.values()) / sum(truth.values()):.3f} over {sum(truth.values()):.1f} m")


if __name__ == "__main__":
    main()
