"""Was the corner the duck touched ever seen? (stream A, 2026-11-17: every exploring contact so far was a corner beside the
duck while it turned past it.) For a contact at time T and a corner (world x, y): every depth frame of the run's Observatory
record in [T - WINDOW_S, T], its obstacle points (the navigator's own derived points) taken relative to the frame's belief
pose and placed from the truth pose at that time (the nearest tick), so what is measured is the duck's view of the corner
relative to itself, not its map's drift. Prints, per frame that saw an obstacle point within NEAR_M of the corner, how far
the nearest one was from the corner, and when; and the last time the corner was seen within SEEN_M of where it is.

    .venv/bin/python sim/probes/corner_seen.py RUN_DIR MINIVIEW_DIR T CORNER_X CORNER_Y
"""

import bisect
import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

WINDOW_S, NEAR_M, SEEN_M = 30.0, 0.25, 0.05

run, mv = Path(sys.argv[1]), Path(sys.argv[2])
T, corner = float(sys.argv[3]), (float(sys.argv[4]), float(sys.argv[5]))
ticks = []
for line in open(run / "ticks.jsonl"):
    r = json.loads(line)
    if "event" not in r and r.get("truth"):
        ticks.append((r["t"], r["truth"]))
ts = [t for t, _ in ticks]
last_seen, rows = None, []
for t, k, p in Follower(mv, keep_raw=True).poll():
    if k != "depth_frame" or not T - WINDOW_S <= t <= T or not p.get("pose"):
        continue
    i = min(max(bisect.bisect_left(ts, t), 0), len(ts) - 1)
    tr = ticks[i][1]
    b = p["pose"]
    cb, sb = math.cos(-b[2]), math.sin(-b[2])
    ct, st = math.cos(tr[2]), math.sin(tr[2])
    best = None
    for q in ((p.get("derived") or {}).get("points") or []):
        if q[3] != "o":
            continue
        dx, dy = q[0] - b[0], q[1] - b[1]
        rx, ry = cb * dx - sb * dy, sb * dx + cb * dy
        w = (tr[0] + ct * rx - st * ry, tr[1] + st * rx + ct * ry)
        d = math.dist(w, corner)
        if best is None or d < best:
            best = d
    if best is not None and best <= NEAR_M:
        rows.append((t, best, math.dist(tr[:2], corner)))
        if best <= SEEN_M:
            last_seen = t
print(f"contact at {T} s, corner {corner}: {len(rows)} frames saw an obstacle point within {NEAR_M} m of it in the last "
      f"{WINDOW_S:.0f} s; last seen within {SEEN_M} m: {f'{T - last_seen:.1f} s before' if last_seen else 'never'}")
for t, d, dc in rows[-8:]:
    print(f"  {t:7.2f} nearest seen point {d:.3f} m from the corner (duck {dc:.2f} m from it)")
