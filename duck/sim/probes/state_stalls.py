"""Stalls of the robot's state stream: depth frames keep coming while the state they are paired with stays the same
(pair_dt_ms grows past STALL_MS). Per stall: when, how long, and what the navigator had just done (the last event
before it, and whether a glance or a cliff stop came within LEAD_S before). A stalled state stream is a stalled gait:
a duck fell during one (challenge 9 seed 10, 2026-11-17).

    uv run python sim/probes/state_stalls.py /work/robotics-lab/data ch9 ch10 [--since run-20261117-07]
"""

import sys
from pathlib import Path

from miniview.mcapio import Follower

STALL_MS = 200.0
LEAD_S = 0.5


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    runs = stalls = after_look = 0
    for prefix in args:
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            try:
                recs = list(Follower(run_dir, keep_raw=True).poll())
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
                continue
            runs += 1
            events, start, worst = [], None, 0.0
            for t, k, p in recs:
                if k == "event":
                    events.append((t, p.get("kind")))
                elif k == "depth_frame":
                    dt = abs(p.get("pair_dt_ms") or 0.0)
                    if dt > STALL_MS:
                        start = start if start is not None else t
                        worst = max(worst, dt)
                    elif start is not None:
                        stalls += 1
                        before = [e for e in events if e[0] <= start]
                        near = [kind for te, kind in before if start - te <= LEAD_S + worst / 1000.0
                                and kind in ("glance", "cliff_stop", "edge_ends")]
                        after_look += 1 if near else 0
                        last = before[-1] if before else (0.0, "-")
                        print(f"{run_dir.parent.name}/{run_dir.name}: stall at {start:.2f} s, {worst:.0f} ms; last event "
                              f"{last[1]} at {last[0]:.2f} s; glance/cliff stop just before: {near or 'no'}")
                        start, worst = None, 0.0
    print(f"== {runs} runs, {stalls} state stalls over {STALL_MS:.0f} ms, {after_look} of them within {LEAD_S} s "
          f"(+ the stall) of a glance or a cliff stop")


if __name__ == "__main__":
    main()
