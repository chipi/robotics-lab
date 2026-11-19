"""The pivot gate's room at each refusal for "no room to turn", three ways, against the truth: as the navigator computes it
(grid.clearance: cell centre to an obstacle cell's edge), to the obstacle cells' squares from the belief itself, and to the
remembered obstacle points (3 cm apart, exact hits). The truth is the trunk's footprint distance to the scene's boxes.

    uv run python sim/probes/room_models.py /work/robotics-lab/data ch7
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab.nav.evaluate import footprint_distance
from duck_lab.nav.grid import CostGrid, clearance
from duck_lab.profile import load as load_profile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402

MAX_M = 0.3


def grid_of(w: dict) -> CostGrid:
    g = w["grid"]
    cost = [math.inf if c == "#" else 0.0 for c in g["cells"]]
    fp = load_profile("sim").footprint
    return CostGrid(g["res"], tuple(g["origin"]), g["w"], g["h"], cost, fp.lethal_m, fp.inflate_m)


def to_squares(grid: CostGrid, xy: tuple, max_m: float) -> float:
    best = max_m
    for i in range(grid.width):
        for j in range(grid.height):
            if math.isinf(grid.at(i, j)):
                x0, y0 = grid.origin[0] + i * grid.res, grid.origin[1] + j * grid.res
                dx = max(x0 - xy[0], 0.0, xy[0] - (x0 + grid.res))
                dy = max(y0 - xy[1], 0.0, xy[1] - (y0 + grid.res))
                best = min(best, math.hypot(dx, dy))
    return best


data, prefix = Path(sys.argv[1]), sys.argv[2]
print(f"{'run':38s} {'now':>6s} {'squares':>7s} {'points':>6s} {'truth':>6s}")
for d in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-20261116-*")):
    scene = json.loads((data / "scenes" / d.parent.name / "scene.json").read_text())
    world, belief, truth, refused = None, None, None, False
    for t, k, p in Follower(d, keep_raw=True).poll():
        if k == "world":
            world = p
        elif k == "tick":
            belief, truth = p.get("belief") or belief, p.get("truth") or truth
        elif k == "event" and p.get("kind") == "refused" and "no room to turn" in p.get("text", ""):
            refused = True
            break
    if not (refused and world and belief and truth):
        continue
    grid = grid_of(world)
    pts = world.get("obstacles") or []
    now = clearance(grid, belief[:2], MAX_M)
    sq = to_squares(grid, belief[:2], MAX_M)
    pt = min((math.dist(belief[:2], q[:2]) for q in pts), default=MAX_M)
    tr = min(box_distance(truth[0], truth[1], b) for b in scene["boxes"])
    print(f"{d.parent.name + '/' + d.name:38s} {now:6.3f} {sq:7.3f} {pt:6.3f} {tr:6.3f}")
