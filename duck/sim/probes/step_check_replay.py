"""Replay "look before you step" (nav/step_check.py) on recorded exploring runs, offline: the floor the depth sensor had
seen is rebuilt from the miniview run's depth frames (their derived floor points, map frame, 5 cm cells as
run.FLOOR_CELL_M); the path from the duck's plan events and its pose from the ticks. At each walking tick the rule
would have stopped the duck where unseen_ahead returns a spot; the replay counts those stops (one per spot: after a
look the spot is skipped) and says where the first one in a time window happened.

    .venv/bin/python sim/probes/step_check_replay.py RUN_DIR MINIVIEW_RUN_DIR [t_from t_to]

What the replay cannot know: what a look would have shown (it marks the spot looked at and goes on), so after the first
stop the run in the replay is not the run the rule would have produced. Its numbers are how often the rule fires on
the walking the duck actually did, and whether it fires before a known bad moment.
"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav.step_check import STEP_M, unseen_ahead
from miniview.mcapio import Follower

CELL = 0.05


def main():
    run, mv = Path(sys.argv[1]), Path(sys.argv[2])
    w0, w1 = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) > 4 else (None, None)
    frames = sorted((t, p) for t, k, p in Follower(mv, keep_raw=True).poll() if k == "depth_frame")
    floor, fi = set(), 0

    def seen(p):
        cx, cy = round(p[0] / CELL), round(p[1] / CELL)
        return any((cx + dx, cy + dy) in floor for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    path, looked, stops, walking_ticks = None, [], [], 0
    for line in open(run / "ticks.jsonl"):
        r = json.loads(line)
        t = r.get("t", 0)
        while fi < len(frames) and frames[fi][0] <= t:
            for q in ((frames[fi][1].get("derived") or {}).get("points") or []):
                if q[3] == "f":
                    floor.add((round(q[0] / CELL), round(q[1] / CELL)))
            fi += 1
        ev = r.get("event")
        if ev == "plan" and r.get("path"):
            path = [tuple(q) for q in r["path"]]
        elif ev in ("leg", "reached", "refused"):
            path = None
        if "event" in r or not path or not r.get("pose") or (r.get("vx") or 0) <= 0:
            continue
        walking_ticks += 1
        pose = r["pose"]
        k = min(range(len(path)), key=lambda i: math.dist(path[i], pose[:2]))
        u = unseen_ahead(path[k + 1:], pose, seen, skip=looked)
        if u is not None:
            looked.append(u)
            stops.append((t, u, tuple(round(v, 2) for v in pose[:2]), tuple(round(v, 2) for v in r.get("truth", [0, 0])[:2])))
    print(f"walking ticks {walking_ticks}, stops to look {len(stops)} ({len(stops) / max(1, walking_ticks) * 100:.1f} % of "
          f"walking ticks), duration {t:.0f} s")
    for t, u, pose, truth in stops:
        if w0 is None or w0 <= t <= w1:
            print(f"  {t:7.2f} look at ({u[0]:.2f},{u[1]:.2f}) from belief {pose}, truth {truth}")


if __name__ == "__main__":
    main()
