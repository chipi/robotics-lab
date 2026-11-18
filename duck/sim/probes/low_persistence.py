"""Can a lower floor margin catch low boxes without phantom obstacles, if a 5 cm cell must read above the margin in K
different frames? From recorded runs (depth frames' derived points, the truth's scene): per margin and K, phantom cells
on flat floor (per minute of run) against the low boxes caught (a box with at least one such cell on it).

    uv run python sim/probes/low_persistence.py /work/robotics-lab/data ch13 ch14 ch15 --since run-20261118-0054
Flat floor and boxes as floor_heights.py; returns within MAX_RANGE_M only (what the memory keeps).
"""

import collections
import json
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floor_heights import CLEAR_M, LOW_M, ON_M  # noqa: E402
from room_vs_truth import box_distance  # noqa: E402

CELL_M, MAX_RANGE_M = 0.05, 1.0
MARGINS = ((0.08, 0.03), (0.04, 0.03), (0.035, 0.02), (0.03, 0.02), (0.025, 0.02))
KS = (1, 2, 3, 4, 6)


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    phantom = collections.Counter()          # (margin, k) -> floor cells
    caught = collections.Counter()           # (margin, k) -> boxes
    boxes_seen, minutes, runs = 0, 0.0, 0
    lowest_caught = collections.defaultdict(list)
    for prefix in args:
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            scene = json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text())
            things = scene.get("boxes", [])
            drops = [{"cx": (h["x0"] + h["x1"]) / 2, "cy": (h["y0"] + h["y1"]) / 2, "hx": (h["x1"] - h["x0"]) / 2,
                      "hy": (h["y1"] - h["y0"]) / 2, "yaw": h["yaw"]} for h in scene.get("hazards") or []]
            low = [b for b in things if b.get("z0", 0.0) < 0.01 and b.get("z1", 1.0) <= LOW_M]
            floor_cells = {m: collections.defaultdict(set) for m in MARGINS}
            box_cells = {m: collections.defaultdict(lambda: collections.defaultdict(set)) for m in MARGINS}
            seen = set()
            epoch, t_first, t_last = None, None, None
            try:
                for t, k, p in Follower(run_dir, keep_raw=True).poll():
                    if k == "epoch":
                        epoch = p["map_to_world"]
                    elif k == "depth_frame" and epoch and p.get("pose"):
                        t_first = t if t_first is None else t_first
                        t_last = t
                        c, s = math.cos(epoch[2]), math.sin(epoch[2])
                        px, py = p["pose"][:2]
                        frame = p.get("seq", t)
                        for q in (p.get("derived") or {}).get("points") or []:
                            if q[3] not in ("f", "o"):
                                continue
                            r = math.dist(q[:2], (px, py))
                            if r > MAX_RANGE_M:
                                continue
                            wx, wy = epoch[0] + c * q[0] - s * q[1], epoch[1] + s * q[0] + c * q[1]
                            cell = (round(wx / CELL_M), round(wy / CELL_M))
                            on = [i for i, b in enumerate(low) if box_distance(wx, wy, b) <= ON_M]
                            is_floor = not on and all(box_distance(wx, wy, b) > CLEAR_M for b in things + drops)
                            if on:
                                seen.add(on[0])
                            for m in MARGINS:
                                if q[2] < m[0] + m[1] * r:
                                    continue
                                if on:
                                    box_cells[m][on[0]][cell].add(frame)
                                elif is_floor:
                                    floor_cells[m][cell].add(frame)
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
                continue
            runs += 1
            boxes_seen += len(seen)
            minutes += ((t_last or 0) - (t_first or 0)) / 60.0
            for m in MARGINS:
                for kk in KS:
                    phantom[(m, kk)] += sum(1 for fr in floor_cells[m].values() if len(fr) >= kk)
                    hit = [i for i, cells in box_cells[m].items() if any(len(fr) >= kk for fr in cells.values())]
                    caught[(m, kk)] += len(hit)
                    if m == MARGINS[3] and kk == 3:
                        lowest_caught["caught"] += [round(low[i]["z1"], 3) for i in hit]
                        lowest_caught["missed"] += [round(low[i]["z1"], 3) for i in seen if i not in hit]
    print(f"{runs} runs, {minutes:.1f} min of depth frames, {boxes_seen} low boxes seen (returns within {MAX_RANGE_M} m)")
    for m in MARGINS:
        row = "  ".join(f"K{kk}: {phantom[(m, kk)] / max(minutes, 1e-9):5.1f}/min {caught[(m, kk)]}/{boxes_seen}"
                        for kk in KS)
        print(f"margin {m[0]:.3f} + {m[1]:.2f}/m | phantom floor cells per minute, boxes caught | {row}")
    print("at margin 0.030 + 0.02/m, K3: caught heights", sorted(lowest_caught["caught"]),
          "missed heights", sorted(lowest_caught["missed"]))


if __name__ == "__main__":
    main()
