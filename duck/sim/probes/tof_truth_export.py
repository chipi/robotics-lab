"""Export, for depth frames of a run in a time span, what the true sensor pose needs (the truth's whole pose at the nearest
tick, the measured joints at the nearest state sample) and what the cliff check believed (cliff.sensor_pose from the
paired state), to JSON for sim/probes/tof_truth.py (MuJoCo's Python).

    uv run python sim/probes/tof_truth_export.py <data> <run key> <from s> <to s> <out.json>
"""

import bisect
import json
import math
import sys
from pathlib import Path

from runfile import keys
from runfile.mcapio import Follower

from duck_lab.nav import cliff
from duck_lab.replay import state_of

data, key, t0, t1, out = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), Path(sys.argv[5])
frames, ticks, sigs = [], [], []
for t, kind, p in Follower(keys.run_dir(data, key), keep_raw=True).poll():
    if kind == "depth_frame" and "state" in p and t0 <= t <= t1:
        frames.append((t, p))
    elif kind == "tick" and p.get("truth_3d"):
        ticks.append((t, p["truth"], p["truth_3d"]))
    elif kind == "signals" and "joint_neck_pitch" in p["values"]:
        sigs.append((t, {k.removeprefix("joint_"): v for k, v in p["values"].items() if k.startswith("joint_")}))
tt, st_ = [x[0] for x in ticks], [x[0] for x in sigs]
rows = []
for t, p in frames:
    k = min(bisect.bisect_left(tt, t), len(tt) - 1)
    s = min(bisect.bisect_left(st_, t), len(st_) - 1)
    height, q = cliff.sensor_pose(state_of(p))
    fwd = cliff.rotate(q, (1.0, 0.0, 0.0))
    rows.append({"t": t, "truth": ticks[k][1], "truth_3d": ticks[k][2], "joints": sigs[s][1],
                 "believed": {"height": height, "pitch_down_deg": math.degrees(math.asin(-fwd[2]))},
                 "drop": bool((p.get("derived") or {}).get("drop_points")),
                 "distance_mm": p["distance_mm"], "status": p["status"],
                 "believed_dirs": [cliff.rotate(q, b) for b in cliff.BEAMS]})
out.write_text(json.dumps(rows))
print(f"{len(rows)} frames -> {out}")
