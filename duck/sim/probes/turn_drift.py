"""How the duck moves while it turns, from the truth (RFC-0008 §4, margins from measurement: challenges 5, 6, 7). Over a
challenge's runs: every stretch of ticks commanded as a pivot (no forward speed, a turn rate) or an arc (forward and turn),
with how far the trunk moved, how much it turned, and how its distance to the nearest wall changed; and the last seconds
before each refusal, tick by tick.

    uv run python sim/probes/turn_drift.py /work/robotics-lab/data ch5 [run-20261117]

The optional third argument keeps only runs named from it on (runs recorded with the pivot's creep compensation).
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402


def kind_of(cmd) -> str:
    if not cmd:
        return "stop"
    vx, vyaw = cmd
    if vx <= 1e-3 and abs(vyaw) > 1e-3:          # a pivot steps back against its creep (PIVOT_BACK_MPS)
        return "pivot"
    if abs(vx) >= 1e-3 and abs(vyaw) > 0.3:
        return "arc"
    if abs(vx) >= 1e-3:
        return "walk"
    return "stop"


def main() -> None:
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    since = sys.argv[3] if len(sys.argv) > 3 else ""
    stretches = {"pivot": [], "arc": []}
    for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-*/*")):
        if run_dir.name < since:
            continue
        scene = json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text())
        walls = [b for b in scene.get("boxes", []) if b.get("z1", 1) > 0.02]
        near = lambda tr: min(box_distance(tr[0], tr[1], b) for b in walls)  # noqa: E731
        ticks, refusals = [], []
        for t, k, p in Follower(run_dir).poll():
            if k == "tick" and p.get("truth"):
                ticks.append((t, p["truth"], p.get("cmd")))
            elif k == "event" and p.get("kind") == "refused":
                refusals.append((t, p.get("text", "")))
        # stretches of one kind
        i = 0
        while i < len(ticks):
            kd = kind_of(ticks[i][2])
            j = i
            while j + 1 < len(ticks) and kind_of(ticks[j + 1][2]) == kd:
                j += 1
            if kd in stretches and j > i:
                a, b = ticks[i][1], ticks[j + 1][1] if j + 1 < len(ticks) else ticks[j][1]
                turn = math.atan2(math.sin(b[2] - a[2]), math.cos(b[2] - a[2]))
                stretches[kd].append({"run": run_dir.parent.name, "t": round(ticks[i][0], 1), "s": round(ticks[j][0] - ticks[i][0], 1),
                                      "moved_m": round(math.dist(a[:2], b[:2]), 3), "turned_deg": round(math.degrees(turn), 0),
                                      "wall_before": round(near(a), 3), "wall_after": round(near(b), 3)})
            i = j + 1
        for tr_t, text in refusals:
            print(f"\n{run_dir.parent.name}: refused at {tr_t:.1f} s ({text})")
            for t, tr, cmd in ticks:
                if tr_t - 6.0 <= t <= tr_t + 0.05 and round(t * 10) % 5 == 0:
                    print(f"   {t:6.1f}  cmd {kind_of(cmd):5s} {cmd}  truth ({tr[0]:+.3f}, {tr[1]:+.3f}, {math.degrees(tr[2]):+5.0f} deg)  wall {near(tr):.3f}")
    for kd, ss in stretches.items():
        if not ss:
            continue
        rate = sorted(s["moved_m"] / max(abs(s["turned_deg"]), 1) * 360 for s in ss if abs(s["turned_deg"]) >= 20)
        closer = sorted(s["wall_before"] - s["wall_after"] for s in ss)
        print(f"\n{kd}: {len(ss)} stretches; moved per full turn (turns of 20 deg or more): "
              f"p50 {rate[len(rate) // 2]:.3f} m, p95 {rate[int(len(rate) * 0.95)]:.3f} m" if rate else f"\n{kd}: {len(ss)} stretches")
        print(f"   closer to the wall by: p50 {closer[len(closer) // 2]:+.3f} m, p95 {closer[int(len(closer) * 0.95)]:+.3f} m, max {closer[-1]:+.3f} m")
        moved = sorted(s["moved_m"] for s in ss)
        print(f"   moved per stretch: p50 {moved[len(moved) // 2]:.3f} m, p95 {moved[int(len(moved) * 0.95)]:.3f} m, "
              f"max {moved[-1]:.3f} m")


if __name__ == "__main__":
    main()
