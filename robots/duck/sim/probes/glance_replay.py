"""Why the removed head glance (challenge 5, 2026-11-16 17:16) read the left wall ~10 cm short: each depth frame of a run's
window, replayed through the cliff check as the navigator derived it (replay.state_of, the simulator's calibration), with
the sensor's yaw against the trunk, the obstacle returns' sideways distance (the glance's measure: |ay|, min and 5th
percentile, beyond the footprint), the floor returns, and the truth's distance to the corridor's long walls.

    uv run python sim/probes/glance_replay.py ch5-s1/run-20261116-171623 12.0 15.2
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab import replay
from cliff_shim import cliff
from duck_lab.nav.run import load_tof

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

data = Path("/work/robotics-lab/data")
run, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
walls = [b for b in json.loads((data / "scenes" / run.split("/")[0] / "scene.json").read_text())["boxes"]
         if b["name"] in ("corr_n", "corr_s")]
cliff.configure(**load_tof("sim"))
truth = None
for t, k, p in Follower(data / "runs" / "duck" / run, keep_raw=True).poll():
    if k == "tick" and p.get("truth"):
        truth = p["truth"]
    if k != "depth_frame" or not (t0 <= t <= t1) or not p.get("state"):
        continue
    st = replay.state_of(p)
    q = p["state"]["tof"]["quat"]                                  # w, x, y, z: the sensor's yaw against the trunk
    yaw = math.degrees(math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2)))
    fr = {k2: p[k2] for k2 in ("rows", "cols", "distance_mm", "status")}
    rel = cliff.depth_points(fr, st)
    side = 1.0 if yaw > 0 else -1.0
    lat = sorted(side * ay for ax, ay, _, kind in rel if kind == "obstacle" and side * ay > 0.083)
    floor = sum(1 for *_, kind in rel if kind == "floor")
    d = {b["name"]: round(box_distance(truth[0], truth[1], b), 3) for b in walls} if truth else {}
    print(f"{t:6.2f} sensor yaw {yaw:+5.0f} deg: obstacle |ay| min {lat[0] if lat else float('nan'):.3f} "
          f"p5 {lat[len(lat) // 20] if lat else float('nan'):.3f} ({len(lat)} returns), floor {floor}; truth {d}")
