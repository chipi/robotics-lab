"""Per challenge run in a data folder: depth frames, frames whose recorded drop_points are not empty, cliff stops, and
whether its scene has a drop at all (a lower floor: miniview's scene hazards). The counts the cliff fix is judged on.

    uv run python sim/probes/drop_census.py <data folder>
"""

import collections
import json
import sys
from pathlib import Path

from miniview import keys
from miniview.mcapio import Follower

data = Path(sys.argv[1])
rows = []
for run_dir in sorted((data / "runs" / "duck").glob("ch*/*")):
    key = keys.key_of(data, run_dir)
    scene = run_dir.parent.name
    sc = json.loads((data / "scenes" / scene / "scene.json").read_text())
    frames = drops = stops = 0
    for t, kind, p in Follower(run_dir, keep_raw=True).poll():
        if kind == "depth_frame":
            frames += 1
            drops += bool((p.get("derived") or {}).get("drop_points"))
        elif kind == "event" and p.get("kind") == "cliff_stop":
            stops += 1
    rows.append({"key": key, "challenge": scene.split("-")[0], "has_drop": bool(sc.get("hazards")), "frames": frames,
                 "drop_frames": drops, "cliff_stops": stops})
by = collections.defaultdict(lambda: collections.Counter())
for r in rows:
    c = by[r["challenge"]]
    c["runs"] += 1
    c["frames"] += r["frames"]
    c["drop_frames"] += r["drop_frames"]
    c["cliff_stops"] += r["cliff_stops"]
    c["runs_with_stop"] += r["cliff_stops"] > 0
    c["has_drop"] += r["has_drop"]
print("challenge  runs  scenes-with-drop  frames  drop-frames  cliff-stops  runs-with-a-stop")
for ch, c in sorted(by.items()):
    print(f"{ch:9s}  {c['runs']:4d}  {c['has_drop']:16d}  {c['frames']:6d}  {c['drop_frames']:11d}  {c['cliff_stops']:11d}  {c['runs_with_stop']:16d}")
Path(sys.argv[2] if len(sys.argv) > 2 else "/dev/null").write_text(json.dumps(rows, indent=1))
