"""Around the walk's start, what the cliff check believed against what was true: per depth frame, the trunk's pitch from
the paired state (the IMU, what cliff.sensor_pose uses) against the truth's (the simulator's whole pose, ADR-0016) at
the nearest tick, the head joints at the nearest state sample, and how much farther than the predicted floor the
bottom rows read (median over their valid beams).

    uv run python sim/probes/pitch_at_start.py <data folder> <run key> <from s> <to s>
"""

import bisect
import math
import statistics
import sys
from pathlib import Path

from runfile import keys
from runfile.mcapio import Follower

from duck_lab.nav import cliff
from duck_lab.replay import state_of


def pitch_deg(q) -> float:
    w, x, y, z = q
    return math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))


def main() -> None:
    data, key, t0, t1 = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    frames, truth, joints = [], [], []
    for t, kind, p in Follower(keys.run_dir(data, key), keep_raw=True).poll():
        if kind == "depth_frame" and "state" in p:
            frames.append((t, p))
        elif kind == "tick" and p.get("truth_3d"):
            truth.append((t, pitch_deg(p["truth_3d"]["quat"])))
        elif kind == "signals":
            v = p["values"]
            if "joint_head_pitch" in v:
                joints.append((t, v.get("joint_neck_pitch"), v.get("joint_head_pitch")))
    tt, jt = [x[0] for x in truth], [x[0] for x in joints]
    print(" time   imu pitch  true pitch  neck   head   excess(bottom rows)  drop?")
    for t, p in frames:
        if not t0 <= t <= t1:
            continue
        st = state_of(p)
        height, q = cliff.sensor_pose(st)
        ex = []
        for i, beam in enumerate(cliff.BEAMS):
            if i // 8 < 6 or p["status"][i] not in cliff.VALID or p["distance_mm"][i] <= 0:
                continue
            d = cliff.rotate(q, beam)
            if d[2] > -0.15:
                continue
            ex.append(p["distance_mm"][i] / 1000.0 / beam[0] - (-height / d[2]))
        k = min(bisect.bisect_left(tt, t), len(tt) - 1)
        j = min(bisect.bisect_left(jt, t), len(jt) - 1) if jt else None
        neck, head = (joints[j][1], joints[j][2]) if j is not None else (None, None)
        drop = "DROP" if (p.get("derived") or {}).get("drop_points") else ""
        print(f"{t:6.2f}  {pitch_deg(st['imu']['quat']):+7.2f}   {truth[k][1]:+7.2f}   "
              f"{math.degrees(neck or 0):+5.1f}  {math.degrees(head or 0):+5.1f}   "
              f"{(statistics.median(ex) * 100 if ex else float('nan')):+6.1f} cm            {drop}")


if __name__ == "__main__":
    main()
