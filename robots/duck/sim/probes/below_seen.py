"""Did the forward sensor already see the side drops? Per recorded run of a challenge with a drop: the depth frames' derived
"below" points (b: under the floor by more than EXTRA_M), put into the world frame with the run's epoch, counted inside the
true hazard (a drop seen) and outside it (a false one), and the first time one landed inside, against the trunk's closest
approach to the drop. Today such points are discarded unless a cliff stop dead ahead turns them into drops.

    uv run python sim/probes/below_seen.py ch10 ch11
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

DATA = Path("/work/robotics-lab/data")


def rects(scene):
    return [{"cx": (h["x0"] + h["x1"]) / 2, "cy": (h["y0"] + h["y1"]) / 2, "hx": (h["x1"] - h["x0"]) / 2,
             "hy": (h["y1"] - h["y0"]) / 2, "yaw": h["yaw"]} for h in scene.get("hazards") or []]


for prefix in sys.argv[1:]:
    seen_runs, n_runs, flat = 0, 0, []
    for d in sorted((DATA / "runs" / "duck").glob(f"{prefix}-s*/run-20261116-*")):
        hz = rects(json.loads((DATA / "scenes" / d.parent.name / "scene.json").read_text()))
        if not hz:             # no drop in the scene: every below point is a false one
            n = sum(sum(1 for q in (p.get("derived") or {}).get("points") or [] if q[3] == "b")
                    for t, k, p in Follower(d, keep_raw=True).poll() if k == "depth_frame")
            flat.append(n)
            continue
        n_runs += 1
        epoch, inside, outside, first_in, closest = None, 0, 0, None, (math.inf, None)
        for t, k, p in Follower(d, keep_raw=True).poll():
            if k == "epoch":
                epoch = p["map_to_world"]
            elif k == "tick" and p.get("truth"):
                dd = min(box_distance(p["truth"][0], p["truth"][1], b) for b in hz)
                if dd < closest[0]:
                    closest = (dd, t)
            elif k == "depth_frame" and epoch:
                c, s = math.cos(epoch[2]), math.sin(epoch[2])
                for q in (p.get("derived") or {}).get("points") or []:
                    if q[3] != "b":
                        continue
                    wx, wy = epoch[0] + c * q[0] - s * q[1], epoch[1] + s * q[0] + c * q[1]
                    if min(box_distance(wx, wy, b) for b in hz) < 0.03:
                        inside += 1
                        if first_in is None:
                            first_in = t
                    else:
                        outside += 1
        if first_in is not None:
            seen_runs += 1
        when = f"first inside at {first_in:.1f} s" if first_in is not None else "never inside"
        print(f"{d.parent.name:9s} {d.name}: below points inside the drop {inside}, outside {outside}; {when}; "
              f"closest approach {closest[0]:.3f} m at {closest[1]:.1f} s")
    if n_runs:
        print(f"== {prefix}: the drop's below points seen in {seen_runs} of {n_runs} runs")
    if flat:
        flat.sort()
        print(f"== {prefix}: no drop in the scene, below points per run: median {flat[len(flat) // 2]}, max {flat[-1]}, "
              f"runs with none {sum(1 for v in flat if v == 0)} of {len(flat)}")
