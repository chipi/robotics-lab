"""The navigator's pure functions (no simulator). Run: cd duck && uv run python tests/test_nav.py"""

import math
import sys

from duck_lab.nav.follow import FollowState, step
from duck_lab.nav.grid import MARGIN_COST, CostGrid, plan, thin

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def room(w=30, h=20, wall_x=None, door=None, unknown=()):
    """A w x h grid at 10 cm, origin (0, 0): free, a border of walls, optional wall at column wall_x
    with a door (rows door[0]..door[1]), optional unknown cells."""
    rows = []
    for cy in range(h):
        row = []
        for cx in range(w):
            c = "."
            if cx in (0, w - 1) or cy in (0, h - 1):
                c = "#"
            if wall_x is not None and cx == wall_x and not (door and door[0] <= cy <= door[1]):
                c = "#"
            if (cx, cy) in unknown:
                c = "?"
            row.append(c)
        rows.append("".join(row))
    return {"res_m": 0.1, "origin": [0.0, 0.0], "width": w, "height": h, "cells": "".join(rows)}


g = CostGrid.from_map_grid(room())
check("walls at 10 cm cells, by edge distance: cell 1 lethal (5 cm), 2-3 margin (15, 25 cm), 4 free (35 cm)", math.isinf(g.at(1, 10)) and g.at(2, 10) == MARGIN_COST and g.at(3, 10) == MARGIN_COST and g.at(4, 10) == 1.0,
      (g.at(1, 10), g.at(2, 10), g.at(3, 10), g.at(4, 10)))
p = plan(g, (0.5, 0.5), (2.5, 1.5))
check("open room: a path, start cell to goal cell", p and g.cell(*p[0]) == (5, 5) and g.cell(*p[-1]) == (25, 15),
      p and (p[0], p[-1]))
check("goal inside a wall's clearance is refused", plan(g, (0.5, 0.5), (0.1, 1.0)) is None)

walled = CostGrid.from_map_grid(room(wall_x=15, door=(11, 18)))  # 0.8 m, as the apartment's doors
p = plan(walled, (0.5, 0.5), (2.5, 0.5))
door_ok = p and all(not math.isinf(walled.at(*walled.cell(*q))) for q in p)
through = p and any(abs(q[0] - 1.55) < 0.1 for q in p) and all(
    q[1] >= 1.1 for q in p if abs(q[0] - 1.55) < 0.1)
check("through the door, never through the wall", door_ok and through, p and [q for q in p if abs(q[0] - 1.55) < 0.1])
check("closed wall: no path", plan(CostGrid.from_map_grid(room(wall_x=15)), (0.5, 0.5), (2.5, 0.5)) is None)

unk = {(cx, cy) for cx in range(8, 22) for cy in range(3, 9)}
gu = CostGrid.from_map_grid(room(unknown=unk))
pu = plan(gu, (0.5, 0.5), (2.5, 0.5))
check("unknown is expensive but not forbidden", pu is not None)
check("thin keeps the ends, ~30 cm apart", thin(p)[0] == p[0] and thin(p)[-1] == p[-1]
      and all(math.dist(a, b) >= 0.29 for a, b in zip(thin(p)[:-2], thin(p)[1:-1])))

# Following: a straight path ahead.
path = [(0.1 * i, 0.0) for i in range(21)]
st = FollowState()
tw, done = step(path, (0.0, 0.0, 0.0), 0.0, st)
check("heading on the path: walk at 0.3, no turn", (round(tw.vx, 2), round(tw.vyaw, 2)) == (0.3, 0.0) and not done, tw)
tw, done = step(path, (1.95, 0.02, 0.0), 1.0, st)
check("within 15 cm of the end: stop, done", (tw.vx, tw.vyaw) == (0.0, 0.0) and done, tw)

st = FollowState()
tw, _ = step(path, (0.0, 0.0, math.radians(120)), 10.0, st)
check("90+ deg off: turn on the spot with the kick", tw.vx == 0 and tw.vyaw == -1.2 and st.turning, tw)
tw, _ = step(path, (0.0, 0.0, math.radians(100)), 11.5, st)
check("after 1 s, hold the turn at 0.8", tw.vx == 0 and tw.vyaw == -0.8, tw)
tw, _ = step(path, (0.0, 0.0, math.radians(10)), 12.0, st)
check("within 15 deg: walk again, steering", tw.vx == 0.3 and -1.0 <= tw.vyaw < 0 and not st.turning, tw)
tw, _ = step(path, (0.0, 0.0, math.radians(30)), 12.5, st)
check("30 deg off while walking: steer, do not stop to turn", tw.vx == 0.3 and tw.vyaw < 0, tw)

# A goal beyond what mapd has seen: unknown ground, not refused.
small = CostGrid.from_map_grid(room(w=10, h=10))
check("goal outside the grid: plan refuses on the bare grid", plan(small, (0.5, 0.5), (2.0, 0.5)) is None)
grown = small.covering([(0.5, 0.5), (2.0, 0.5)])
check("covering grows the grid; old cells keep their cost", grown.width > small.width
      and grown.at(*grown.cell(0.05, 0.5)) == small.at(*small.cell(0.05, 0.5)), (grown.width, grown.origin))
pg = plan(grown, (0.45, 0.45), (2.0, 0.45))
check("covering: a path to the goal, but never through the known wall",
      pg is None or all(not math.isinf(grown.at(*grown.cell(*q))) for q in pg), pg and pg[-1])
grown2 = small.covering([(0.5, 0.5), (0.5, -1.0)])
check("covering grows downward too, origin moves", grown2.origin[1] < small.origin[1], grown2.origin)

# Doorways at mapd's 5 cm cells (run 4: the office doorway closed on 10 cm cells).
def gap_grid(gap_cells):
    w, h, res = 40, 30, 0.05
    rows = []
    for cy in range(h):
        lo = 15 - gap_cells // 2
        rows.append("".join("#" if cx == 20 and not (lo <= cy < lo + gap_cells) else "." for cx in range(w)))
    return CostGrid.from_map_grid({"res_m": res, "origin": [0.0, 0.0], "width": w, "height": h, "cells": "".join(rows)})


check("a 45 cm gap (the office doorway has 42 cm free) is passable at 5 cm cells",
      plan(gap_grid(9), (0.3, 0.75), (1.7, 0.75)) is not None)
check("a 15 cm gap is not", plan(gap_grid(3), (0.3, 0.75), (1.7, 0.75)) is None)

# A duck that drifted into a wall's lethal zone can still get out (run 2 stranded it).
pe = plan(g, (0.25, 1.0), (1.5, 1.0))
check("start in the lethal zone: a path out", pe is not None and g.cell(*pe[-1]) == (15, 10), pe and pe[:3])

# The reflex's memory: an obstacle the sensor saw blocks the straight line.
open_room = CostGrid.from_map_grid(room())
blocked = open_room.with_blocked([(1.5, 1.0)])
check("a blocked point is grown like a wall", math.isinf(blocked.at(*blocked.cell(1.5, 1.0)))
      and math.isinf(blocked.at(*blocked.cell(1.65, 1.0))) and not math.isinf(open_room.at(*open_room.cell(1.5, 1.0))))
pb = plan(blocked, (0.5, 1.0), (2.5, 1.0))
check("the path goes around the blocked point", pb and min(math.dist(q, (1.5, 1.0)) for q in pb) > 0.2,
      pb and round(min(math.dist(q, (1.5, 1.0)) for q in pb), 2))

# Frames: map <- odom from one fix, then odometry carries the pose.
from duck_lab.nav.frames import Localizer, compose, inverse  # noqa: E402

a = (1.0, 2.0, math.radians(30))
back = compose(a, inverse(a))
check("compose with the inverse is the identity", all(abs(v) < 1e-9 for v in back), back)
loc = Localizer()
check("no pose before the first fix", loc.pose() is None)
loc.on_odom(1_000, (0.5, 0.0, 0.0))
check("a fix needs odometry within 0.1 s", not loc.on_fix(500_000_000, (3.0, 1.0, math.pi / 2)))
check("a fix next to odometry is taken", loc.on_fix(2_000, (3.0, 1.0, math.pi / 2)))
loc.on_odom(3_000, (1.5, 0.0, 0.0))  # walked 1 m along odometry's x
x, y, yaw = loc.pose()
check("1 m along odom x is 1 m along map y when the map is turned 90 deg",
      abs(x - 3.0) < 1e-9 and abs(y - 2.0) < 1e-9 and abs(yaw - math.pi / 2) < 1e-9, (x, y, yaw))

print("NAV", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
