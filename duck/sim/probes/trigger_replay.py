"""RFC-0012's first trigger, replayed on recorded runs before it is built (docs/wip/SIDE-DROPS.md): "unseen floor beside the
way". floor_seen is rebuilt from each depth frame's derived floor points (map frame, FLOOR_CELL_M cells, as the navigator
keeps it); at each tick the band BAND_M aside of the path's next AHEAD_M is sampled on both sides, and the trigger fires
on a side whose unseen fraction is at least FRAC, unless that stretch was looked at already (a fire covers COVER_M of the
way ahead on its side). Per run: fires (the cost: each is a stop and a glance), and, where the scene has a drop, whether a
fire came on the drop's side before the trunk's closest approach to it.

    uv run python sim/probes/trigger_replay.py ch1 ch2 ch3 ch4 ch10 ch11
"""

import json
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

DATA = Path("/work/robotics-lab/data")
CELL = 0.05                                  # run.FLOOR_CELL_M
BAND_M = (0.15, 0.45)                        # aside of the path: from just outside the sensor's cone to the drop margin
AHEAD_M, FRAC, COVER_M = 0.6, 0.5, 0.9


def band_cells(path, pose, side):
    """Cells in the band on one side of the path's next AHEAD_M (from the point nearest the pose)."""
    if len(path) < 2:
        return []
    k = min(range(len(path)), key=lambda i: math.dist(path[i], pose[:2]))
    out, walked = [], 0.0
    for i in range(k, len(path) - 1):
        a, b = path[i], path[i + 1]
        seg = math.dist(a, b)
        if seg < 1e-6:
            continue
        nx, ny = -(b[1] - a[1]) / seg, (b[0] - a[0]) / seg          # left of the way
        for off in (BAND_M[0] + 0.05 * j for j in range(int((BAND_M[1] - BAND_M[0]) / 0.05) + 1)):
            x, y = a[0] + side * off * nx, a[1] + side * off * ny
            out.append((round(x / CELL), round(y / CELL)))
        walked += seg
        if walked > AHEAD_M:
            break
    return out


def drop_distance(truth, scene):
    hz = scene.get("hazards") or []
    if not hz:
        return None
    best = math.inf
    for h in hz:
        b = {"cx": (h["x0"] + h["x1"]) / 2, "cy": (h["y0"] + h["y1"]) / 2, "hx": (h["x1"] - h["x0"]) / 2,
             "hy": (h["y1"] - h["y0"]) / 2, "yaw": h["yaw"]}
        best = min(best, box_distance(truth[0], truth[1], b))
    return best


for prefix in sys.argv[1:]:
    totals = []
    for d in sorted((DATA / "runs" / "duck").glob(f"{prefix}-s*/run-20261116-*")):
        scene = json.loads((DATA / "scenes" / d.parent.name / "scene.json").read_text())
        seen, plan, fires, looked, first_fire_t, closest = set(), None, [], [], None, (math.inf, None)
        epoch = None
        for t, k, p in Follower(d, keep_raw=True).poll():
            if k == "epoch":
                epoch = p["map_to_world"]
            elif k == "plan":
                plan = p.get("path")
            elif k == "depth_frame":
                for q in (p.get("derived") or {}).get("points") or []:
                    if q[3] == "f":
                        seen.add((round(q[0] / CELL), round(q[1] / CELL)))
            elif k == "tick" and plan and p.get("belief"):
                pose = p["belief"]
                if p.get("truth"):
                    dd = drop_distance(p["truth"], scene)
                    if dd is not None and dd < closest[0]:
                        closest = (dd, t)
                for side in (1, -1):
                    if any(s == side and math.dist(at, pose[:2]) < COVER_M for at, s in looked):
                        continue
                    cells = band_cells(plan, pose, side)
                    if cells and sum(c not in seen for c in cells) / len(cells) >= FRAC:
                        fires.append((round(t, 1), side))
                        looked.append((tuple(pose[:2]), side))
                        if first_fire_t is None:
                            first_fire_t = t
        line = f"{d.parent.name:9s} {d.name}: {len(fires)} fires"
        if closest[1] is not None:
            before = [f for f in fires if f[0] <= closest[1]]
            line += f"; closest to the drop {closest[0]:.3f} m at {closest[1]:.1f} s, fires before it: {len(before)}"
        print(line, fires[:6])
        totals.append(len(fires))
    if totals:
        print(f"== {prefix}: {len(totals)} runs, fires per run median {sorted(totals)[len(totals) // 2]}, max {max(totals)}")
