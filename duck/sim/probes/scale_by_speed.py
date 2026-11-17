"""The odometry scale still missing, by commanded speed, from recorded challenge runs: over walking windows (the same
forward speed asked, turning slowly, WINDOW_S long), truth distance / believed distance. 1.0: the navigator's one
odom_scale (calibration/<robot>.json, measured at 0.3 m/s) is right at that speed; below 1: the belief walks too far,
above: too short. The belief carries mapd's corrections, so this is what is left after them.

    uv run python sim/probes/scale_by_speed.py /work/robotics-lab/data ch10 ch11 [--since run-20261117-07]
"""

import collections
import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

WINDOW_S = 1.0
MAX_YAW_RATE = 0.3          # rad/s asked: straight enough


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    ratios = collections.defaultdict(list)
    for prefix in args:
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            try:
                ticks = [(t, p) for t, k, p in Follower(run_dir).poll()
                         if k == "tick" and p.get("belief") and p.get("truth") and p.get("cmd")]
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
                continue
            i = 0
            while i < len(ticks):
                t0, p0 = ticks[i]
                vx, vyaw = p0["cmd"]
                if vx <= 0.05 or abs(vyaw) > MAX_YAW_RATE:
                    i += 1
                    continue
                j = i
                while j + 1 < len(ticks) and ticks[j + 1][0] - t0 <= WINDOW_S and \
                        abs(ticks[j + 1][1]["cmd"][0] - vx) < 0.01 and abs(ticks[j + 1][1]["cmd"][1]) <= MAX_YAW_RATE:
                    j += 1
                if ticks[j][0] - t0 >= WINDOW_S * 0.9:
                    b = math.dist(p0["belief"][:2], ticks[j][1]["belief"][:2])
                    tr = math.dist(p0["truth"][:2], ticks[j][1]["truth"][:2])
                    if b > 0.05:
                        ratios[round(vx, 2)].append(tr / b)
                i = j + 1
    for vx in sorted(ratios):
        r = sorted(ratios[vx])
        print(f"asked {vx:.2f} m/s: {len(r)} windows; truth/belief p50 {r[len(r) // 2]:.3f}, "
              f"p10 {r[len(r) // 10]:.3f}, p90 {r[len(r) * 9 // 10]:.3f}")


if __name__ == "__main__":
    main()
