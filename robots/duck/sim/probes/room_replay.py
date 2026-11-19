"""What sets the room to turn at a recorded pose: the room with and without the drops' rings, and the lethal mapd cells
near the duck. Challenge 11 seed 4, gate4, stuck facing a pit for 70 s: 0.123 m either way, from a mapd cell 9 cm
closer than the block it stands for (the drops' rings were blamed first, wrongly).

    python sim/probes/room_replay.py RUN_DIR 77        (or a legacy folder's ticks.jsonl)
Reads the last world event before T (s): mapd's grid, the obstacle points, and drops + edges together (the record does
not tell them apart, so every one gets the drops' ring).
"""

import json
import math
import sys
from pathlib import Path

import legacy_rows

from duck_lab.nav.grid import CostGrid, clearance
from duck_lab.profile import load as load_profile

PROFILE = load_profile("sim")
DROP_LETHAL_M, DROP_INFLATE_M = PROFILE.error_budget.drop_lethal_m, PROFILE.error_budget.drop_inflate_m
PIVOT_OBSTACLE_M = PROFILE.footprint.lethal_m + PROFILE.locomotion.pivot.obstacle_margin_m
SLOW_CLEAR_M = PROFILE.locomotion.slow_clearance_m


def main() -> None:
    path, at = Path(sys.argv[1]), float(sys.argv[2])
    world = pose = None
    for e in legacy_rows.load(path.parent if path.name == "ticks.jsonl" else path)[1]:
        if e.get("t", 0) > at:
            break
        if e.get("event") == "world":
            world = e
        if "pose" in e and "event" not in e:
            pose = e["pose"]
    blocked = [tuple(q[:2]) for q in world["blocked"]]
    drops = [tuple(q[:2]) for q in world["drops"]]
    base = CostGrid.from_map_grid(world["grid"], explained_by=blocked, lethal_m=PROFILE.footprint.lethal_m,
                                  inflate_m=PROFILE.footprint.inflate_m)
    base = base.covering([pose[:2]] + blocked + drops).with_points(blocked)
    reach = max(PIVOT_OBSTACLE_M, SLOW_CLEAR_M)
    with_drops = clearance(base.with_blocked(drops, DROP_LETHAL_M, DROP_INFLATE_M), pose[:2], reach)
    without = clearance(base, pose[:2], reach)
    near_drop = min((math.dist(pose[:2], d) for d in drops), default=float("inf"))
    near_point = min((math.dist(pose[:2], b) for b in blocked), default=float("inf"))
    print(f"pose {[round(v, 3) for v in pose]}; nearest obstacle point {near_point:.3f} m, nearest drop or edge "
          f"point {near_drop:.2f} m")
    print(f"room with the drops' rings {with_drops:.3f} m, without {without:.3f} m; a turn on the spot needs "
          f"{PIVOT_OBSTACLE_M:.2f}")
    cx, cy = base.cell(*pose[:2])
    for dx in range(-5, 6):
        for dy in range(-5, 6):
            n = (cx + dx, cy + dy)
            if base.inside(*n) and math.isinf(base.at(*n)) and n not in base.point_cells:
                x0, y0 = base.origin[0] + n[0] * base.res, base.origin[1] + n[1] * base.res
                gx = max(x0 - pose[0], 0.0, pose[0] - (x0 + base.res))
                gy = max(y0 - pose[1], 0.0, pose[1] - (y0 + base.res))
                if math.hypot(gx, gy) < 0.2:
                    print(f"  lethal mapd cell {n}: square from ({x0:.3f}, {y0:.3f}), {math.hypot(gx, gy):.3f} m away")


if __name__ == "__main__":
    main()
