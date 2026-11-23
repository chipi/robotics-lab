"""What the body does in recorded runs, for the body anomalies' limits (phase 5 item 3 step 3): per joint the current and the
tracking error (commanded angle less measured angle), as percentiles over every sample and as the longest stretch over a few
candidate limits; the hottest servo; the loop rate. Reads the signals step 2 records (runs from 2026-11-23 on).

    uv run python sim/probes/body_limits.py <run folder or a folder holding runs>...
"""

import math
import sys
from collections import defaultdict
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab.nav.runlog import JOINTS

CURRENT_LIMITS_MA = (300, 500, 700, 900)
TRACKING_LIMITS_RAD = (0.1, 0.2, 0.3, 0.5)


def runs(args):
    for a in args:
        for mc in sorted(Path(a).rglob("run.mcap")):
            yield mc.parent


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else math.nan


def longest(samples, limit):
    """The longest stretch, in seconds, with the value over `limit` at every sample."""
    best, start = 0.0, None
    for t, x in samples:
        if x > limit:
            start = t if start is None else start
            best = max(best, t - start)
        else:
            start = None
    return best


def main() -> None:
    cur, err = defaultdict(list), defaultdict(list)
    hot, loop, n_runs = [], [], 0
    for run in runs(sys.argv[1:]):
        sig = [(t, p["values"]) for t, k, p in Follower(run).poll() if k == "signals"]
        if not any(f"joint_{JOINTS[0]}_target" in v for _, v in sig):
            continue
        n_runs += 1
        for j in JOINTS:
            a, tg, ma = f"joint_{j}", f"joint_{j}_target", f"joint_{j}_ma"
            cur[j].append([(t, v[ma]) for t, v in sig if ma in v])
            err[j].append([(t, abs(v[tg] - v[a])) for t, v in sig if tg in v and a in v])
        hot += [v["motor_max_c"] for _, v in sig if "motor_max_c" in v]
        loop += [v["loop_hz"] for _, v in sig if "loop_hz" in v]
    print(f"{n_runs} runs with body signals")
    for name, data, limits, unit in (("current", cur, CURRENT_LIMITS_MA, "mA"), ("tracking error", err, TRACKING_LIMITS_RAD, "rad")):
        print(f"\n{name} ({unit}): p50 p99 p99.9 max; then per limit the longest stretch over it in any run (s)")
        for j in JOINTS:
            flat = [x for r in data[j] for _, x in r]
            if not flat:
                print(f"  {j:16s} not reported")
                continue
            stretches = [max(longest(r, lim) for r in data[j]) for lim in limits]
            print(f"  {j:16s} {pct(flat, .5):7.2f} {pct(flat, .99):7.2f} {pct(flat, .999):7.2f} {max(flat):7.2f}  | "
                  + "  ".join(f">{lim}: {s:5.1f}" for lim, s in zip(limits, stretches)))
    if hot:
        print(f"\nhottest servo (C): min {min(hot)} max {max(hot)} over {len(hot)} polls")
    if loop:
        print(f"loop (Hz): p0.1 {pct(loop, .001):.2f} p1 {pct(loop, .01):.2f} p50 {pct(loop, .5):.2f} min {min(loop):.2f}")


if __name__ == "__main__":
    main()
