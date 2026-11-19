"""How far the navigator's remembered obstacle points sit from the scene's real surfaces: each world record's points, put
into the world frame with the run's epoch (map_to_world), against the nearest box. A point off every surface is
misplaced; the ones in free floor are what shrink the pivot room.

    uv run python sim/probes/point_error.py ch7-s1/run-20261116-191428
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

data = Path("/work/robotics-lab/data")
run = sys.argv[1]
boxes = json.loads((data / "scenes" / run.split("/")[0] / "scene.json").read_text())["boxes"]
epoch, seen = None, 0
for t, k, p in Follower(data / "runs" / "duck" / run, keep_raw=True).poll():
    if k == "epoch":
        epoch = p["map_to_world"]
    elif k == "world" and epoch:
        c, s = math.cos(epoch[2]), math.sin(epoch[2])
        pts = p.get("obstacles") or []
        errs = sorted(min(box_distance(epoch[0] + c * x - s * y, epoch[1] + s * x + c * y, b) for b in boxes)
                      for x, y in (q[:2] for q in pts[seen:]))
        if errs:
            print(f"{t:6.2f} {len(pts) - seen:4d} new points: off the nearest surface median {errs[len(errs) // 2] * 1000:.0f} mm, "
                  f"p90 {errs[int(len(errs) * 0.9)] * 1000:.0f} mm, max {errs[-1] * 1000:.0f} mm")
        seen = len(pts)
