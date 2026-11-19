"""A better rule for `room_disagrees` (K36), measured on the apartment recordings: at each "no room to turn" refusal, the map's nearest obstacle (its
occupied cells and remembered points within 0.6 m of the belief pose) and what the depth sensor saw in that direction in the last 4 s (frames
within 20 degrees of its bearing, returns within 1.5 m). "agrees": an obstacle return within 8 cm of the map's distance; "disagrees": floor
returned at or beyond the map's obstacle and no obstacle return near it; "unseen": the sensor did not look that way (no verdict). Against the
truth (the map's room more than 5 cm tighter than the layout's clearance at the truth pose) and against the rule the navigator has (the
sensor's nearest return ahead at 280 mm or more).

    uv run python sim/probes/room_rule.py [RUN ...]       # default: every apartment run with depth frames
"""
import bisect
import json
import math
import sys
from collections import Counter
from pathlib import Path

from runfile import mcapio

from map_range import distance

DATA = Path("/work/robotics-lab/data/runs/duck/apartment")
WINDOW_S, LOOK_DEG, NEAR_M, SEE_M = 4.0, 20.0, 0.6, 1.5
rows = []
names = sys.argv[1:] or sorted(p.name for p in DATA.iterdir() if p.is_dir())
for name in names:
    recs = mcapio.read(DATA / name, keep_raw=True)
    frames = [(t, p) for t, k, p in recs if k == "depth_frame" and p.get("derived")]
    if not frames:
        continue
    ft = [t for t, _ in frames]
    epoch = next((p["map_to_world"] for t, k, p in recs if k == "epoch"), None)
    worlds = [(t, p) for t, k, p in recs if k == "world"]
    wt = [t for t, _ in worlds]
    for t, k, p in recs:
        if k != "event" or p.get("kind") != "refused":
            continue
        raw = p.get("raw") or {}
        dec = (p.get("decision") or {}).get("values") or {}
        if "no room to turn" not in (raw.get("why") or (p.get("decision") or {}).get("reason") or ""):
            continue
        pose, tr = raw.get("pose"), raw.get("truth")
        if not pose or not tr or "room_m" not in dec:
            continue
        room_map = dec["room_m"]
        room_truth = distance(tr[0], tr[1])
        label_wrong = room_truth - room_map > 0.05
        near_mm = dec.get("nearest_mm")
        old = near_mm is not None and near_mm >= 280
        # the map's nearest obstacle (cells and remembered points) round the belief pose
        i = bisect.bisect_right(wt, t) - 1
        verdict, dm, th = "no map", None, None
        if i >= 0:
            w = worlds[i][1]
            g = w["grid"]
            res, (ox, oy), W = g["res"], g["origin"], g["w"]
            best = (math.inf, None)
            r = int(NEAR_M / res) + 1
            cx0, cy0 = int((pose[0] - ox) / res), int((pose[1] - oy) / res)
            for cy in range(cy0 - r, cy0 + r + 1):
                for cx in range(cx0 - r, cx0 + r + 1):
                    if 0 <= cx < W and 0 <= cy < g["h"] and g["cells"][cy * W + cx] == "#":
                        qx, qy = ox + (cx + .5) * res, oy + (cy + .5) * res
                        d = math.hypot(qx - pose[0], qy - pose[1])
                        if d < best[0]:
                            best = (d, (qx, qy))
            for q in w.get("obstacles") or []:
                d = math.hypot(q[0] - pose[0], q[1] - pose[1])
                if d < best[0]:
                    best = (d, (q[0], q[1]))
            dm = best[0]
            if dm <= NEAR_M:
                th = math.atan2(best[1][1] - pose[1], best[1][0] - pose[0])
                lo = bisect.bisect_left(ft, t - WINDOW_S)
                hi = bisect.bisect_right(ft, t)
                looked, near_o, floor_beyond = 0, False, False
                for _, f in frames[lo:hi]:
                    for q in f["derived"]["points"]:
                        dx, dy = q[0] - pose[0], q[1] - pose[1]
                        d = math.hypot(dx, dy)
                        if d > SEE_M or d < 0.02:
                            continue
                        if abs(math.degrees((math.atan2(dy, dx) - th + math.pi) % (2 * math.pi) - math.pi)) > LOOK_DEG:
                            continue
                        looked += 1
                        if q[3] == "o" and d <= dm + 0.08:
                            near_o = True
                        if q[3] == "f" and d >= dm - 0.02:
                            floor_beyond = True
                verdict = "unseen" if not looked else "agrees" if near_o else "disagrees" if floor_beyond else "unclear"
            else:
                verdict = "map obstacle far"
        rows.append((name, t, room_map, room_truth, label_wrong, old, verdict, dm))
print("refusals", len(rows))
c = Counter()
for r in rows:
    c[("old fires" if r[5] else "old quiet", "map wrong" if r[4] else "map ok")] += 1
print("OLD rule (near_mm >= 280):")
for k, v in sorted(c.items()):
    print("  ", k, v)
c = Counter()
for r in rows:
    c[(r[6], "map wrong" if r[4] else "map ok")] += 1
print("NEW rule verdicts:")
for k, v in sorted(c.items()):
    print("  ", k, v)

