"""Does a glance leave the head where it was? From a recorded run: the head joints and the odometry's
truth/belief ratio over walking windows, with the glances in each window.

    uv run python sim/probes/head_after_glance.py /work/robotics-lab/data/runs/duck/ch11-s7/run-20261118-003418
"""

import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

WINDOW_S = 3.0
HEAD = ("joint_neck_pitch", "joint_head_pitch", "joint_head_yaw", "joint_head_roll")


def main() -> None:
    rows = list(Follower(Path(sys.argv[1])).poll())
    ticks = [(t, p) for t, k, p in rows if k == "tick" and p.get("belief") and p.get("truth") and p.get("cmd")]
    head = [(t, p["values"]) for t, k, p in rows if k == "signals" and HEAD[0] in p.get("values", {})]
    events = [(t, p.get("kind")) for t, k, p in rows if k == "event"]
    if not head:
        print("no head joints recorded; signals keys:",
              next((sorted(p["values"]) for t, k, p in rows if k == "signals"), None))
    t_start = ticks[0][0]

    def head_at(t):
        before = [v for th, v in head if th <= t]
        return before[-1] if before else {}

    w0, acc, prev = None, [0.0, 0.0], None
    for t, p in ticks:
        w = int((t - t_start) / WINDOW_S)
        if w0 is None:
            w0 = w
        if w != w0:
            ev = [e for te, e in events if w0 * WINDOW_S <= te - t_start < w * WINDOW_S and e in ("glance", "step_look")]
            h = head_at(t)
            angles = " ".join(f"{math.degrees(h.get(n, 0.0)):+6.1f}" for n in HEAD)
            ratio = f"{acc[0] / acc[1]:.2f}" if acc[1] > 0.05 else "  - "
            print(f"{w0 * WINDOW_S:5.0f}s  truth/belief {ratio}  head (neck, pitch, yaw, roll) {angles}  {' '.join(ev)}")
            w0, acc = w, [0.0, 0.0]
        if prev and prev["cmd"][0] > 0.05:
            acc[0] += math.dist(prev["truth"][:2], p["truth"][:2])
            acc[1] += math.dist(prev["belief"][:2], p["belief"][:2])
        prev = p


if __name__ == "__main__":
    main()
