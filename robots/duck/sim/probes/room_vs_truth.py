"""How far the navigator's `room` (its clearance: the trunk's centre to the nearest obstacle cell's edge on its map) is from
the truth (the trunk's centre to the nearest real wall, from the scene's boxes), sample by sample over a challenge's runs; and
the belief's position error beside it, one candidate cause. RFC-0008 step 3, the clearance model: challenge 5's refusals
("no room to turn", room 0.07 m) came where the truth had the trunk ~0.2 m from the wall.

    uv run python sim/probes/room_vs_truth.py /work/robotics-lab/data ch5
"""

import bisect
import json
import math
import statistics
import sys
from pathlib import Path

from runfile.mcapio import Follower


def box_distance(px: float, py: float, b: dict) -> float:
    """From a point to an (oriented) box's footprint: 0 inside."""
    c, s = math.cos(-b.get("yaw", 0.0)), math.sin(-b.get("yaw", 0.0))
    dx, dy = px - b["cx"], py - b["cy"]
    lx, ly = c * dx - s * dy, s * dx + c * dy
    ox, oy = max(abs(lx) - b["hx"], 0.0), max(abs(ly) - b["hy"], 0.0)
    return math.hypot(ox, oy)


def quantiles(xs: list) -> str:
    xs = sorted(xs)
    q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]  # noqa: E731
    return f"p5 {q(0.05):+.3f}  p50 {q(0.5):+.3f}  p95 {q(0.95):+.3f}  (n {len(xs)})"


def main() -> None:
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    gaps, beliefs, at_refusal = [], [], []
    for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-*/*")):
        scene = json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text())
        walls = [b for b in scene.get("boxes", []) if b.get("z1", 1) > 0.02]          # what stands above the floor
        ticks, sig, refusals = [], [], []
        for t, kind, p in Follower(run_dir).poll():
            if kind == "tick" and p.get("truth"):
                ticks.append((t, p["truth"], p.get("belief")))
            elif kind == "signals" and p["values"].get("room_m") is not None:
                sig.append((t, p["values"]["room_m"]))
            elif kind == "event" and p.get("kind") == "refused":
                refusals.append(t)
        if not ticks:
            continue
        tt = [x[0] for x in ticks]
        for t, room in sig:
            i = min(bisect.bisect_left(tt, t), len(tt) - 1)
            _, tr, _ = ticks[i]
            true_room = min(box_distance(tr[0], tr[1], b) for b in walls)
            if room < 0.169:                    # the room is capped at the search radius (PIVOT_OBSTACLE_M = 0.17): only real readings
                gaps.append(room - true_room)
        for t, tr, be in ticks:
            pass
        for tr_t in refusals:
            i = min(bisect.bisect_left([s[0] for s in sig], tr_t), len(sig) - 1)
            room = sig[i][1] if sig else None
            j = min(bisect.bisect_left(tt, tr_t), len(tt) - 1)
            _, tr, _ = ticks[j]
            at_refusal.append((run_dir.parent.name, round(room, 3) if room is not None else None,
                               round(min(box_distance(tr[0], tr[1], b) for b in walls), 3)))
    print(f"{prefix}: room (navigator) minus the truth's centre-to-wall distance, where the room was below its cap:")
    print("  " + quantiles(gaps) if gaps else "  no samples")
    print("at each refusal (scene, room, truth centre-to-wall):")
    for r in at_refusal:
        print("  ", r)


if __name__ == "__main__":
    main()
