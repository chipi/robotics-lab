"""The navigator's pure functions (no simulator). Run: cd duck && uv run python tests/test_nav.py"""

import math
import sys

from duck_lab.nav.follow import FollowState, step
from duck_lab.nav.grid import CostGrid, plan, thin

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
check("cells parse; walls inflated by 20 cm", math.isinf(g.at(2, 10)) and not math.isinf(g.at(3, 10)),
      (g.at(2, 10), g.at(3, 10)))
p = plan(g, (0.5, 0.5), (2.5, 1.5))
check("open room: a path, start cell to goal cell", p and g.cell(*p[0]) == (5, 5) and g.cell(*p[-1]) == (25, 15),
      p and (p[0], p[-1]))
check("goal inside a wall's clearance is refused", plan(g, (0.5, 0.5), (0.1, 1.0)) is None)

walled = CostGrid.from_map_grid(room(wall_x=15, door=(12, 17)))
p = plan(walled, (0.5, 0.5), (2.5, 0.5))
door_ok = p and all(not math.isinf(walled.at(*walled.cell(*q))) for q in p)
through = p and any(abs(q[0] - 1.55) < 0.1 for q in p) and all(
    q[1] >= 1.2 for q in p if abs(q[0] - 1.55) < 0.1)
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
