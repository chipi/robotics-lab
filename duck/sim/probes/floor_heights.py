"""How high flat floor reads, by range, against what a floor margin must catch (cliff.FLOOR_MARGIN_M): the heights the
depth frames recorded for every return (derived points, any kind), split by what the truth says it hit. Flat floor:
returns more than CLEAR_M from every box and drop of the scene; a box: returns within ON_M of a box no taller than
LOW_M (the small things a margin can hide). Per range band: floor p99, p99.9 and max; boxes p10 and p50.

    uv run python sim/probes/floor_heights.py /work/robotics-lab/data ch1 ch2 ch15 [--since run-20261117-07]
"""

import collections
import json
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

CLEAR_M, ON_M, LOW_M = 0.15, 0.02, 0.30
BANDS = ((0.0, 0.4), (0.4, 0.7), (0.7, 1.0), (1.0, 1.5), (1.5, 9.9))


def band(r):
    return next(b for b in BANDS if b[0] <= r < b[1])


def pct(xs, q):
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    floor, boxes = collections.defaultdict(list), collections.defaultdict(list)
    for prefix in args:
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            scene = json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text())
            things = scene.get("boxes", [])
            drops = [{"cx": (h["x0"] + h["x1"]) / 2, "cy": (h["y0"] + h["y1"]) / 2, "hx": (h["x1"] - h["x0"]) / 2,
                      "hy": (h["y1"] - h["y0"]) / 2, "yaw": h["yaw"]} for h in scene.get("hazards") or []]
            low = [b for b in things if b.get("z0", 0.0) < 0.01 and b.get("z1", 1.0) <= LOW_M]
            epoch = None
            try:
                recs = Follower(run_dir, keep_raw=True).poll()
                for t, k, p in recs:
                    if k == "epoch":
                        epoch = p["map_to_world"]
                    elif k == "depth_frame" and epoch and p.get("pose"):
                        c, s = math.cos(epoch[2]), math.sin(epoch[2])
                        px, py = p["pose"][:2]
                        for q in (p.get("derived") or {}).get("points") or []:
                            if q[3] not in ("f", "o"):
                                continue
                            wx, wy = epoch[0] + c * q[0] - s * q[1], epoch[1] + s * q[0] + c * q[1]
                            r = math.dist(q[:2], (px, py))
                            on = [b for b in low if box_distance(wx, wy, b) <= ON_M]
                            if on:
                                boxes[band(r)].append((q[2], on[0]["z1"]))
                            elif all(box_distance(wx, wy, b) > CLEAR_M for b in things + drops):
                                floor[band(r)].append(q[2])
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
    allf = [(h, (lo + hi) / 2) for (lo, hi), hs in floor.items() for h in hs if hi <= 1.0]
    allb = [(h, (lo + hi) / 2) for (lo, hi), hs in boxes.items() for h, _ in hs if hi <= 1.0]
    for base, per in ((0.08, 0.03), (0.05, 0.03), (0.04, 0.03), (0.04, 0.02), (0.035, 0.02)):
        ff = sum(1 for h, r in allf if h >= base + per * r)
        bb = sum(1 for h, r in allb if h >= base + per * r)
        print(f"margin {base:.3f} + {per:.2f}/m (to 1 m): flat floor read as obstacle {ff} of {len(allf)} "
              f"({ff / max(1, len(allf)):.5f}); low-box returns caught {bb} of {len(allb)} ({bb / max(1, len(allb)):.2f})")
    for b in BANDS:
        f = sorted(floor[b])
        bx = sorted(h for h, _ in boxes[b])
        tall = sorted(z for _, z in boxes[b])
        print(f"range {b[0]:.1f}-{b[1]:.1f} m: flat floor {len(f)} returns, p99 {pct(f, 0.99):+.3f} p99.9 {pct(f, 0.999):+.3f} "
              f"max {f[-1] if f else float('nan'):+.3f} m | low boxes {len(bx)} returns, p10 {pct(bx, 0.1):+.3f} "
              f"p50 {pct(bx, 0.5):+.3f} m (boxes {pct(tall, 0.0):.2f}-{tall[-1] if tall else float('nan'):.2f} m tall)")


if __name__ == "__main__":
    main()
