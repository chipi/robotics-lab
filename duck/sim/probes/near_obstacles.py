"""The remembered obstacle points nearest the duck at a time in a run: where they are, against the belief.

    uv run python sim/probes/near_obstacles.py RUN_DIR T [N]
"""

import math
import sys
from pathlib import Path

from runfile.mcapio import Follower


def main() -> None:
    run, at = Path(sys.argv[1]), float(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    rows = list(Follower(run).poll())
    t0 = next(t for t, k, p in rows if k == "tick")
    tick = world = None
    for t, k, p in rows:
        if t - t0 > at:
            break
        if k == "tick" and p.get("belief"):
            tick = p
        if k == "world":
            world = p
    pose = tick["belief"]
    print(f"belief {[round(v, 3) for v in pose]} truth {[round(v, 3) for v in tick['truth']]}")
    obs = world.get("obstacles") or []
    pts = [(math.dist(pose[:2], q[:2]), q) for q in obs]
    pts.sort(key=lambda e: e[0])
    c, s = math.cos(-pose[2]), math.sin(-pose[2])
    for d, q in pts[:n]:
        dx, dy = q[0] - pose[0], q[1] - pose[1]
        print(f"  {d:.3f} m  at {[round(v, 3) for v in q[:2]]}  ahead {c * dx - s * dy:+.3f} left {s * dx + c * dy:+.3f}  {q[2:]}")
    print(f"world keys {sorted(world)}; {len(obs)} obstacle points; first {obs[:1]}")


if __name__ == "__main__":
    main()
