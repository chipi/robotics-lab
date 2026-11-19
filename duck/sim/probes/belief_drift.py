"""How far the duck's belief of its pose is from the truth, and how fast that error changes (the error budget behind
the drop rings assumes ~2.5 cm: docs/wip/SIDE-DROPS.md). Per tick: the belief (map frame) put into the world through
the run's newest epoch, against the truth. Two numbers per challenge:

- absolute: |belief - truth| over every tick;
- relative over DT_S: how much that error vector changes in DT_S seconds. A drop is remembered with the belief of the
  moment it was seen and passed later with the belief of then: the change between the two is what the ring must cover,
  not the absolute error (both are in the same drifting map).

    uv run python sim/probes/belief_drift.py /work/robotics-lab/data ch10 ch11 [--since run-20261117]
"""

import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

DT_S = (5.0, 10.0, 20.0)


def pct(xs, q):
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    for prefix in args:
        absolute, rel = [], {dt: [] for dt in DT_S}
        worst = []
        runs = 0
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            try:
                recs = list(Follower(run_dir).poll())
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
                continue
            epoch, errs = None, []
            for t, k, p in recs:
                if k == "epoch":
                    epoch = p["map_to_world"]
                elif k == "tick" and epoch and p.get("belief") and p.get("truth"):
                    bx, by = p["belief"][:2]
                    c, s = math.cos(epoch[2]), math.sin(epoch[2])
                    wx, wy = epoch[0] + c * bx - s * by, epoch[1] + s * bx + c * by
                    errs.append((t, wx - p["truth"][0], wy - p["truth"][1]))
            if not errs:
                continue
            runs += 1
            mags = [math.hypot(ex, ey) for _, ex, ey in errs]
            absolute += mags
            worst.append((max(mags), f"{run_dir.parent.name}/{run_dir.name}"))
            for dt in DT_S:
                j = 0
                for i, (t, ex, ey) in enumerate(errs):
                    while j < len(errs) and errs[j][0] < t + dt:
                        j += 1
                    if j >= len(errs):
                        break
                    rel[dt].append(math.hypot(errs[j][1] - ex, errs[j][2] - ey))
        absolute.sort()
        print(f"== {prefix}: {runs} runs, {len(absolute)} ticks")
        print(f"   absolute error: p50 {pct(absolute, 0.5):.3f} m, p95 {pct(absolute, 0.95):.3f} m, max {absolute[-1]:.3f} m"
              if absolute else "   no ticks")
        for dt in DT_S:
            r = sorted(rel[dt])
            if r:
                print(f"   change over {dt:4.0f} s: p50 {pct(r, 0.5):.3f} m, p95 {pct(r, 0.95):.3f} m, max {r[-1]:.3f} m")
        for m, name in sorted(worst, reverse=True)[:3]:
            print(f"   worst run: {name} max {m:.3f} m")


if __name__ == "__main__":
    main()
