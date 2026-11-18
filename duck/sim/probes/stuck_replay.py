"""Stuck detection (nav/stuck.py) replayed on recorded runs (format 2: depth frames, ticks with the belief and the command,
the truth): each verdict, and whether the truth agrees (the trunk moved under STUCK_TRUTH_M in the window: really stuck).

    uv run python sim/probes/stuck_replay.py /work/robotics-lab/data ch16 [ch1 ...] [--since run-20261118]
Exit 0 when every verdict is true stuck (no false alarm) — the false-alarm check for normal runs.
"""

import math
import sys
from pathlib import Path

from miniview.mcapio import Follower

from duck_lab.nav.stuck import StuckWatch

STUCK_TRUTH_M = 0.05


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    runs = verdicts = false_alarms = 0
    for prefix in args:
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            try:
                rows = list(Follower(run_dir, keep_raw=True).poll())
            except Exception:  # noqa: BLE001
                print(f"unreadable: {run_dir}")
                continue
            runs += 1
            watch, odom, last, truth_at = StuckWatch(), 0.0, None, []
            for t, k, p in rows:
                if k == "tick" and p.get("belief") and p.get("cmd"):
                    b = p["belief"]
                    if last is not None:
                        odom += math.dist(b[:2], last[:2])
                    last = b
                    truth_at.append((t, p.get("truth")))
                    out = watch.update(t, p["cmd"][0] > 0.05, tuple(b[:2]))
                    if out:
                        verdicts += 1
                        past = [tr for tt, tr in truth_at if t - tt <= out["seconds"] and tr]
                        moved = math.dist(past[0][:2], past[-1][:2]) if len(past) > 1 else None
                        real = moved is not None and moved < STUCK_TRUTH_M
                        false_alarms += not real
                        print(f"{run_dir.parent.name}/{run_dir.name} t {t:.1f}: stuck {out}; truth moved "
                              f"{moved if moved is None else round(moved, 3)} m -> {'REAL' if real else 'FALSE ALARM'}")
                        watch.reset()
    print(f"STUCK-REPLAY runs {runs}, verdicts {verdicts}, false alarms {false_alarms}")
    sys.exit(0 if false_alarms == 0 else 1)


if __name__ == "__main__":
    main()
