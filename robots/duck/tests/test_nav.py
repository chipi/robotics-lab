"""The navigator's pure functions (no simulator). Run: cd robots/duck && uv run python tests/test_nav.py"""

import math
import functools
import sys

from duck_lab.nav.follow import FollowState, step
from duck_lab.nav.grid import LETHAL_COST, MARGIN_COST, CostGrid, plan, thin
from duck_lab.profile import load

P = load("sim")
LETHAL_M, INFLATE_M = P.footprint.lethal_m, P.footprint.inflate_m
DROP_LETHAL_M, DROP_INFLATE_M = P.error_budget.drop_lethal_m, P.error_budget.drop_inflate_m
FIX = P.localisation.fix
grid_of = functools.partial(CostGrid.from_map_grid, lethal_m=LETHAL_M, inflate_m=INFLATE_M)
walk = functools.partial(step, loco=P.locomotion)

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


g = grid_of(room())
check("walls at 10 cm cells, by edge distance: cell 1 lethal (5 cm), 2-3 margin (15, 25 cm), 4 free (35 cm)",
      g.at(1, 10) >= LETHAL_COST and 1.0 < g.at(3, 10) < g.at(2, 10) < LETHAL_COST and g.at(4, 10) == 1.0,
      (g.at(1, 10), g.at(2, 10), g.at(3, 10), g.at(4, 10)))
# The ring is graded, not flat (grid.margin_cost): a flat ring let plans hug the lethal edge round corners (exploring b5
# r2 touched the corridor console's corner at 0.075 m after plans passed it at 0.115 m).
from duck_lab.nav.grid import MARGIN_EDGE_COST, margin_cost  # noqa: E402

check("the margin costs most at the lethal edge and falls to free at its outer edge",
      margin_cost(0.12, 0.12, 0.28) == MARGIN_EDGE_COST and margin_cost(0.28, 0.12, 0.28) == 1.0
      and margin_cost(0.15, 0.12, 0.28) > margin_cost(0.25, 0.12, 0.28))
p = plan(g, (0.5, 0.5), (2.5, 1.5))
check("open room: a path, start cell to goal cell", p and g.cell(*p[0]) == (5, 5) and g.cell(*p[-1]) == (25, 15),
      p and (p[0], p[-1]))
check("goal inside a wall's clearance is refused", plan(g, (0.5, 0.5), (0.1, 1.0)) is None)

walled = grid_of(room(wall_x=15, door=(11, 18)))  # 0.8 m, as the apartment's doors
p = plan(walled, (0.5, 0.5), (2.5, 0.5))
door_ok = p and all(walled.at(*walled.cell(*q)) < LETHAL_COST for q in p)
through = p and any(abs(q[0] - 1.55) < 0.1 for q in p) and all(
    q[1] >= 1.1 for q in p if abs(q[0] - 1.55) < 0.1)
check("through the door, never through the wall", door_ok and through, p and [q for q in p if abs(q[0] - 1.55) < 0.1])
check("closed wall: no path", plan(grid_of(room(wall_x=15)), (0.5, 0.5), (2.5, 0.5)) is None)

unk = {(cx, cy) for cx in range(8, 22) for cy in range(3, 9)}
gu = grid_of(room(unknown=unk))
pu = plan(gu, (0.5, 0.5), (2.5, 0.5))
check("unknown is expensive but not forbidden", pu is not None)
check("thin keeps the ends, ~30 cm apart", thin(p)[0] == p[0] and thin(p)[-1] == p[-1]
      and all(math.dist(a, b) >= 0.29 for a, b in zip(thin(p)[:-2], thin(p)[1:-1])))

# Following: a straight path ahead.
path = [(0.1 * i, 0.0) for i in range(21)]
st = FollowState()
tw, done = walk(path, (0.0, 0.0, 0.0), 0.0, st)
check("heading on the path: walk at 0.3, no turn", (round(tw.vx, 2), round(tw.vyaw, 2)) == (0.3, 0.0) and not done, tw)
tw, done = walk(path, (1.95, 0.02, 0.0), 1.0, st)
check("within 15 cm of the end: stop, done", (tw.vx, tw.vyaw) == (0.0, 0.0) and done, tw)

st = FollowState()
tw, _ = walk(path, (0.0, 0.0, math.radians(120)), 10.0, st)
check("90+ deg off: turn on the spot with the kick", tw.vx == 0 and tw.vyaw == -1.2 and st.turning, tw)
tw, _ = walk(path, (0.0, 0.0, math.radians(100)), 11.5, st)
check("after 1 s, hold the turn at 0.8", tw.vx == 0 and tw.vyaw == -0.8, tw)
tw, _ = walk(path, (0.0, 0.0, math.radians(10)), 12.0, st)
check("within 15 deg: walk again, steering", tw.vx == 0.3 and -1.0 <= tw.vyaw < 0 and not st.turning, tw)
tw, _ = walk(path, (0.0, 0.0, math.radians(30)), 12.5, st)
check("30 deg off while walking: steer, do not stop to turn", tw.vx == 0.3 and tw.vyaw < 0, tw)

# A bend next to an obstacle (phase 1 runs 9/10: the office doorway cut 7-8 cm from the cabinet).
bend = [(0.1 * i, 0.0) for i in range(6)] + [(0.5, 0.1 * j) for j in range(1, 6)]   # east 0.5 m, then north
pre = (0.35, 0.0, 0.0)                                                                # 15 cm before the corner
tw_far, _ = walk(bend, pre, 20.0, FollowState())
tw_near, _ = walk(bend, pre, 20.0, FollowState(), near=True)
check("near an obstacle the lookahead stays on the leg before the bend (no early cut)",
      abs(tw_near.vyaw) < abs(tw_far.vyaw) and tw_near.vyaw < 0.6, (round(tw_far.vyaw, 2), round(tw_near.vyaw, 2)))

# No room to pivot (phase 1 run 12: a contact while turning on the spot by the cabinet): turn while
# walking slowly instead.
st_arc = FollowState()
tw_arc, _ = walk(path, (0.0, 0.0, math.radians(120)), 30.0, st_arc, pivot_ok=False)
check("no room to pivot: the turn is an arc at the slowest walk", st_arc.turning and tw_arc.vx == 0.2 and tw_arc.vyaw < 0,
      tw_arc)
st_k = FollowState()                       # a pivot whose kick did not start the stepping
for t in (40.0, 40.5, 41.0, 41.5, 42.0, 42.5):
    tw_k, _ = walk(path, (0.0, 0.0, math.radians(120)), t, st_k)
check("a pivot that gains no yaw for a second kicks again (1.2 rad/s), not 0.8 for ever",
      abs(tw_k.vyaw) == 1.2, tw_k)
st_m = FollowState()                       # one that turns: kick once, then hold
for i, t in enumerate((50.0, 50.5, 51.0, 51.5, 52.0, 52.5)):
    tw_m, _ = walk(path, (0.0, 0.0, math.radians(170 - 10 * i)), t, st_m)
check("a pivot that turns holds at 0.8 after its kick", abs(tw_m.vyaw) == 0.8, tw_m)
tw_piv, _ = walk(path, (0.0, 0.0, math.radians(120)), 30.0, FollowState())
check("room to pivot: the turn stays on the spot", tw_piv.vx == 0.0, tw_piv)
# A robot whose pivot creeps forward (the simulator: calibration/sim.json "pivot") turns stepping back against it; an arc
# and a walk are not changed by it.
st_b = FollowState()
tw_b, _ = walk(path, (0.0, 0.0, math.radians(120)), 60.0, st_b, pivot_vx=-0.06)
tw_b2, _ = walk(path, (0.0, 0.0, math.radians(100)), 61.5, st_b, pivot_vx=-0.06)
check("a pivot kicks standing (vx 0) and holds with the robot's pivot speed", tw_b.vx == 0.0 and tw_b2.vx == -0.06
      and (tw_b.vyaw, tw_b2.vyaw) == (-1.2, -0.8), (tw_b, tw_b2))
tw_ba, _ = walk(path, (0.0, 0.0, math.radians(120)), 62.0, FollowState(), pivot_ok=False, pivot_vx=-0.06)
tw_bw, _ = walk(path, (0.0, 0.0, 0.0), 63.0, FollowState(), pivot_vx=-0.06)
check("an arc and a walk ignore the pivot speed", tw_ba.vx == 0.2 and tw_bw.vx == 0.3, (tw_ba, tw_bw))
# Turning hard within an obstacle's margin, the duck walks slower (RFC-0012's caution pace): the apartment's goal 12
# (2026-11-17) cut the office cabinet's corner at 0.3 m/s turning 0.5-0.8 rad/s, 7 cm from it against the 12 cm margin.
off = (0.0, 0.0, math.radians(-20))       # walking with the path 20 deg to the left: 0.52 rad/s, under the 45 deg pivot
tw_hard_near, _ = walk(path, off, 70.0, FollowState(), near=True)
tw_hard_far, _ = walk(path, off, 71.0, FollowState(), near=False)
tw_straight_near, _ = walk(path, (0.0, 0.0, 0.0), 72.0, FollowState(), near=True)
check("turning hard near an obstacle: the slow pace", abs(tw_hard_near.vyaw) >= 0.4 and tw_hard_near.vx == 0.2,
      tw_hard_near)
check("... not in the open, nor walking straight near one", tw_hard_far.vx == 0.3 and tw_straight_near.vx == 0.3,
      (tw_hard_far, tw_straight_near))
# The margin's cost missed it: the apartment's goal 11 (2026-11-17, run apartment-1117b) turned 0.7-1.0 rad/s at 0.3 m/s
# from 17 to 7 cm off the cabinet with near false. Measured clearance under SLOW_CLEAR_M slows a hard turn too.
tw_hard_close, _ = walk(path, off, 73.0, FollowState(), close=True)
check("turning hard close to an obstacle by clearance: the slow pace", tw_hard_close.vx == 0.2, tw_hard_close)

# A goal beyond what mapd has seen: unknown ground, not refused.
small = grid_of(room(w=10, h=10))
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
    return grid_of({"res_m": res, "origin": [0.0, 0.0], "width": w, "height": h, "cells": "".join(rows)})


check("a 45 cm gap (the office doorway has 42 cm free) is passable at 5 cm cells",
      plan(gap_grid(9), (0.3, 0.75), (1.7, 0.75)) is not None)
check("a 15 cm gap is not", plan(gap_grid(3), (0.3, 0.75), (1.7, 0.75)) is None)

# A duck that drifted into a wall's lethal zone can still get out (run 2 stranded it).
pe = plan(g, (0.25, 1.0), (1.5, 1.0))
check("start in the lethal zone: a path out", pe is not None and g.cell(*pe[-1]) == (15, 10), pe and pe[:3])

# The reflex's memory: an obstacle the sensor saw blocks the straight line.
open_room = grid_of(room())
blocked = open_room.with_blocked([(1.5, 1.0)])
check("a blocked point is grown like a wall", math.isinf(blocked.at(*blocked.cell(1.5, 1.0)))
      and blocked.at(*blocked.cell(1.65, 1.0)) >= LETHAL_COST and not math.isinf(open_room.at(*open_room.cell(1.5, 1.0))))
pb = plan(blocked, (0.5, 1.0), (2.5, 1.0))
check("the path goes around the blocked point", pb and min(math.dist(q, (1.5, 1.0)) for q in pb) > 0.2,
      pb and round(min(math.dist(q, (1.5, 1.0)) for q in pb), 2))

# Drops (exploration trials 2 and 3): plans keep out of the cliff check's stop range of a known drop,
# a duck stopped inside that range can leave, and no path ever crosses the drop itself.

fine = grid_of({"res_m": 0.05, "origin": [0.0, 0.0], "width": 60, "height": 40, "cells": "." * 2400})
drop = (1.5, 1.0)
dg = fine.with_blocked([drop], DROP_LETHAL_M, DROP_INFLATE_M)
pd = plan(dg, (0.3, 1.0), (2.7, 1.0))
check("a path past a known drop keeps 45 cm (the cliff-stop distance) from it",
      pd is not None and min(math.dist(q, drop) for q in pd) >= 0.45 - 0.03,
      pd and round(min(math.dist(q, drop) for q in pd), 3))
pe2 = plan(dg, (1.5, 1.42), (1.5, 1.9))
check("a duck stopped 42 cm from a drop (inside its zone) can leave, away from it",
      pe2 is not None and all(math.dist(q, drop) > 0.4 for q in pe2), pe2 and pe2[:2])
pthru = plan(dg, (1.5, 1.42), (1.5, 0.58))
check("no path crosses the drop itself, even escaping", pthru is None or all(math.dist(q, drop) > 0.05 for q in pthru),
      pthru and min(math.dist(q, drop) for q in pthru))

# Phase 1 run 9: the 0.5 m escape let a duck on free floor cut through a cabinet's lethal zone (truth
# 7.8 cm from it). The escape is for a duck already in a lethal zone, and a path that leaves one never
# goes back in.
narrow = gap_grid(4)                                   # a 20 cm gap: lethal all across (12 cm from each side)
s_free = (0.7, 0.75)                                   # free floor, 0.30 m from the wall: not lethal
check("start on free floor: no lethal-zone shortcut through a gap 0.5 m away",
      narrow.at(*narrow.cell(*s_free)) < LETHAL_COST and plan(narrow, s_free, (1.7, 0.75)) is None,
      plan(narrow, s_free, (1.7, 0.75)) and len(plan(narrow, s_free, (1.7, 0.75))))
pe3 = plan(g, (0.25, 1.0), (1.5, 1.0))
check("a path that escapes a lethal zone never re-enters one",
      pe3 is not None and not any(g.at(*g.cell(*q)) >= LETHAL_COST for q in pe3[next(i for i, q in enumerate(pe3) if g.at(*g.cell(*q)) < LETHAL_COST):]),
      pe3 and pe3[:4])

# Unknown beside a known obstacle (exploration trial 7: a path along a cabinet's unseen face wedged
# the duck): costs more than open unknown, so the plan goes round on seen floor when it can.
from duck_lab.nav.grid import SHADOW_COST, UNKNOWN_COST  # noqa: E402

rows_sh = []
for cy in range(20):
    rows_sh.append("".join("#" if cx == 15 and 8 <= cy <= 11 else "?" if 16 <= cx <= 22 and 5 <= cy <= 14 else "."
                           for cx in range(30)))
sh = grid_of({"res_m": 0.1, "origin": [0.0, 0.0], "width": 30, "height": 20, "cells": "".join(rows_sh)})
check("unknown next to a known obstacle costs more than open unknown",
      sh.at(17, 10) >= SHADOW_COST and sh.at(21, 6) == UNKNOWN_COST, (sh.at(17, 10), sh.at(21, 6)))   # >=: also in a graded margin

# Replan hysteresis (phase 1 run 11, goal 20: two routes flipped for 12 s at the office doorway).
from duck_lab.nav.grid import keep_current  # noqa: E402

here = (0.5, 1.0, 0.0)
north = [(0.5 + 0.1 * i, 1.0 + 0.02 * i) for i in range(1, 21)]      # ~2.0 m, clear
south = [(0.5 + 0.1 * i, 1.0 - 0.02 * i) for i in range(1, 21)]      # the same length the other way
check("a clear current path is kept against an equally long new one", keep_current(open_room, north, here, south))
check("a current path that became lethal is dropped",
      not keep_current(open_room.with_blocked([north[5]]), north, here, south))
check("a much shorter new path wins", not keep_current(open_room, north + [(2.5, 2.5), (2.5, 1.4)], here, south))

from duck_lab.nav.grid import clearance  # noqa: E402

check("clearance: 5 cm cells, a point 5 cells from a wall cell is 0.225 m from its edge; open floor reads the search radius",
      abs(clearance(gap_grid(9), (0.775, 0.1), 0.3) - 0.225) < 0.03 and clearance(fine, (1.5, 1.0), 0.3) == 0.3,
      (clearance(gap_grid(9), (0.775, 0.1), 0.3), clearance(fine, (1.5, 1.0), 0.3)))

# The clearance model (docs/wip/CLEARANCE-MODEL.md): exact obstacle points over mapd's whole cells.
RES = 0.0455                                      # the simulator's 5 cm cells, scaled by its odometry (0.91)


def corridor_map(half_m, length_m=1.0, ox=-0.3, below_m=0.2):
    """mapd's view of a corridor along x: the cells holding the two wall surfaces at y = ±half_m, as mapd marks
    them, and the exact points on those surfaces every 3 cm (the navigator's memory)."""
    w, h = int((length_m + 0.6) / RES) + 1, int((2 * half_m + 0.4) / RES) + 3
    origin = (ox, -half_m - below_m)
    rows = [["."] * w for _ in range(h)]
    pts = []
    for i in range(int(length_m / 0.03) + 1):
        x = 0.03 * i
        for y in (-half_m, half_m):
            pts.append((x, y))
            rows[math.floor((y - origin[1]) / RES)][math.floor((x - origin[0]) / RES)] = "#"
    g = {"res_m": RES, "origin": list(origin), "width": w, "height": h, "cells": "".join("".join(r) for r in rows)}
    return g, pts


g45, p45 = corridor_map(0.205)                    # a 45 cm corridor's walls (4 cm thick): surfaces 0.205 m out
cells_only = grid_of(g45).with_blocked(p45)          # the navigator before: cells, and points rounded to cells
exact = grid_of(g45, explained_by=p45).with_points(p45)
explained = grid_of(g45, explained_by=p45)
partly = grid_of(g45, explained_by=[p for p in p45 if p[0] < 0.3])
check("a mapd wall cell with an exact point in it is left to the points; one without stays",
      not any(math.isinf(v) for v in explained.cost)
      and math.isinf(partly.at(*partly.cell(0.8, 0.205))) and not math.isinf(partly.at(*partly.cell(0.1, 0.205))))
g40, p40 = corridor_map(0.18, below_m=0.183)      # a 40 cm corridor, its walls where the cells fall worst
check("a 40 cm corridor: cells and rounded points close it at this alignment, exact points keep it open (LETHAL_M unchanged)",
      plan(grid_of(g40).with_blocked(p40), (-0.2, 0.0), (0.9, 0.0)) is None
      and plan(grid_of(g40, explained_by=p40).with_points(p40), (-0.2, 0.0), (0.9, 0.0)) is not None)
check("an exact point's own cell is never crossed, and its lethal zone is measured from the point",
      math.isinf(exact.at(*exact.cell(0.3, 0.205))) and exact.at(*exact.cell(0.3, 0.205 - LETHAL_M + 0.03)) >= LETHAL_COST
      and exact.at(*exact.cell(0.3, 0.0)) < LETHAL_COST)
empty = grid_of({"res_m": 0.05, "origin": [0.0, 0.0], "width": 20, "height": 20, "cells": "." * 400})
dot = empty.with_points([(0.51, 0.5)])
just_out = [(x, y) for x in range(20) for y in range(20)
            if LETHAL_M + 0.003 < math.dist(empty.centre(x, y), (0.51, 0.5)) < LETHAL_M + 0.025]
check("a cell whose centre is just beyond LETHAL_M of an exact point is passable (the point is not rounded to its cell)",
      just_out and all(dot.at(*c) < LETHAL_COST for c in just_out), len(just_out))
room_c, room_e = clearance(cells_only, (0.3, 0.07), 0.3), clearance(exact, (0.3, 0.07), 0.3)
check("clearance to exact points is the distance itself (0.135 m); from cells and rounded points it read short (0.116)",
      abs(room_e - 0.135) < 1e-6 and room_c < room_e - 0.01, (round(room_c, 3), round(room_e, 3)))
one = grid_of({"res_m": 0.05, "origin": [0.0, 0.0], "width": 10, "height": 10,
                              "cells": "".join("#" if (i % 10, i // 10) == (5, 5) else "." for i in range(100))})
check("clearance to a cell is to its square from the position itself, not from the position's cell centre",
      abs(clearance(one, (0.20, 0.27), 0.3) - 0.05) < 1e-9 and abs(clearance(one, (0.24, 0.27), 0.3) - 0.01) < 1e-9,
      (clearance(one, (0.20, 0.27), 0.3), clearance(one, (0.24, 0.27), 0.3)))
wall_map = {"res_m": 0.05, "origin": [0.0, 0.0], "width": 10, "height": 10,      # a wall column at x cell 4, unknown beyond it
            "cells": "".join(("#" if x == 4 else "?" if x > 4 else ".") for y in range(10) for x in range(10))}
on_wall = [(0.22, 0.025 + 0.05 * j) for j in range(10)]
shaded = grid_of(wall_map, explained_by=on_wall)
check("an explained wall still casts its shadow: the unknown cell behind it costs SHADOW_COST (exploration trial 7)",
      shaded.at(5, 5) == SHADOW_COST and not math.isinf(shaded.at(4, 5)), (shaded.at(5, 5), shaded.at(4, 5)))
mixed = grid_of({"res_m": 0.05, "origin": [0.0, 0.0], "width": 20, "height": 20,
                                "cells": "".join("#" if (i % 20, i // 20) == (10, 12) else "." for i in range(400))},
                               ).with_points([(0.525, 0.30)])
room_m = clearance(mixed, (0.525, 0.50), 0.3)                    # the wall cell's square 0.10 m away, the point 0.20 m
check("clearance on a mixed grid: an unexplained wall cell nearer than any point is the room, not the point",
      abs(room_m - 0.10) < 1e-9, room_m)
lone = {"res_m": 0.05, "origin": [0.0, 0.0], "width": 10, "height": 10,
        "cells": "".join("#" if (i % 10, i // 10) == (5, 5) else "." for i in range(100))}
inside_tol = grid_of(lone, explained_by=[(0.30 + 0.4 * 0.05, 0.275)])     # 0.4 of a cell past its edge
beyond_tol = grid_of(lone, explained_by=[(0.30 + 0.6 * 0.05, 0.275)])     # 0.6 of a cell past it
check("a point within half a cell of a wall cell explains it; one further out does not",
      not math.isinf(inside_tol.at(5, 5)) and math.isinf(beyond_tol.at(5, 5)), (inside_tol.at(5, 5), beyond_tol.at(5, 5)))
grown = exact.covering([(-2.0, -2.0)])
check("covering() keeps the points and moves their cells with the grid's new origin",
      grown.points == exact.points and all(math.isinf(grown.at(*c)) for c in grown.point_cells)
      and grown.cell(0.3, 0.205) in grown.point_cells)

# Frames: map <- odom from one fix, then odometry carries the pose.
from duck_lab.nav.frames import Localizer, compose, inverse  # noqa: E402

a = (1.0, 2.0, math.radians(30))
back = compose(a, inverse(a))
check("compose with the inverse is the identity", all(abs(v) < 1e-9 for v in back), back)
loc = Localizer(FIX)
check("no pose before the first fix", loc.pose() is None)
loc.on_odom(1_000, (0.5, 0.0, 0.0))
check("a fix needs odometry within 0.1 s", not loc.on_fix(500_000_000, (3.0, 1.0, math.pi / 2)))
check("a fix next to odometry is taken", loc.on_fix(2_000, (3.0, 1.0, math.pi / 2)))
loc.on_odom(3_000, (1.5, 0.0, 0.0))  # walked 1 m along odometry's x
x, y, yaw = loc.pose()
check("1 m along odom x is 1 m along map y when the map is turned 90 deg",
      abs(x - 3.0) < 1e-9 and abs(y - 2.0) < 1e-9 and abs(yaw - math.pi / 2) < 1e-9, (x, y, yaw))

# A fix that would jump the belief is held (explore-b10a-r1: 0.9 m in one tick while pivoting), taken when 5 agree; the
# landmarks' offset survives the next fix and fades.
HOLD_N, OFFSET_HALF_S = FIX.hold_n, FIX.offset_half_s

NS = 1_000_000_000
g = Localizer(FIX, max_jump_m=0.3)
for k in range(30):
    g.on_odom(k * NS, (0.1 * k, 0.0, 0.0))
check("the first fix is taken, whatever it is", g.on_fix(0, (5.0, 5.0, 0.0)) and g.last_fix["status"] == "taken"
      and g.last_fix["before"] is None)
check("a fix next to the belief is taken", g.on_fix(1 * NS, (5.1, 5.0, 0.0)) and g.last_fix["status"] == "taken"
      and g.last_fix["moved_m"] < 0.01, g.last_fix)
g.on_fix(2 * NS, (5.2, 5.9, 0.0))                     # 0.9 m sideways in one fix
check("a fix that moves the belief 0.9 m is held: the belief stays, the record has its raw pose, t_ns, odometry",
      g.last_fix["status"] == "held" and abs(g.pose()[1] - 5.0) < 1e-9
      and g.last_fix["raw"] == [5.2, 5.9, 0.0] and g.last_fix["t_ns"] == 2 * NS and g.last_fix["odom_t_ns"] == 2 * NS
      and g.last_fix["odom"] == [0.2, 0.0, 0.0] and abs(g.last_fix["moved_m"] - 0.9) < 0.01 and g.rejected == 1,
      g.last_fix)
for k in range(3, 2 + HOLD_N):
    g.on_fix(k * NS, (5.0 + 0.1 * k, 5.9, 0.0))
check(f"{HOLD_N} fixes in a row that agree: the jump is taken, late", g.last_fix["status"] == "late"
      and abs(g.pose()[1] - 5.9) < 0.01, g.last_fix)
nl = Localizer(FIX, max_jump_m=0.3, hold_n=None)
for k in range(30):
    nl.on_odom(k * NS, (0.0, 0.0, 0.0))
nl.on_fix(0, (1.0, 1.0, 0.0))
for k in range(1, 25):
    nl.on_fix(k * NS, (1.0, 5.0, 0.0))              # mapd lost itself 4 m away and says so, steadily, for 24 s
check("hold_n None (the navigator's): a persistent jump is never taken, the belief stays", nl.last_fix["status"] == "held"
      and abs(nl.pose()[1] - 1.0) < 1e-9 and nl.rejected == 24, nl.last_fix)
h = Localizer(FIX, max_jump_m=0.3)
for k in range(30):
    h.on_odom(k * NS, (0.0, 0.0, 0.0))
h.on_fix(0, (1.0, 1.0, 0.0))
for k, y in enumerate((2.0, 3.0, 2.0, 3.0, 2.0, 3.0), start=1):    # 1 m jumps that disagree with each other: never taken
    h.on_fix(k * NS, (1.0, y, 0.0))
check("held fixes that disagree are never taken", h.last_fix["status"] == "held" and abs(h.pose()[1] - 1.0) < 1e-9, h.last_fix)
free = Localizer(FIX)
free.on_odom(0, (0.0, 0.0, 0.0))
free.on_fix(0, (0.0, 0.0, 0.0))
free.on_fix(0, (9.0, 9.0, 0.0))
check("without a limit every fix is taken (the old behaviour)", abs(free.pose()[0] - 9.0) < 1e-9)
n = Localizer(FIX)
for k in range(200):
    n.on_odom(k * NS, (0.0, 0.0, 0.0))
n.on_fix(0, (1.0, 1.0, 0.0))
step = n.nudge(0.0, 0.3)
check("a nudge moves the belief now", abs(n.pose()[1] - 1.3) < 1e-9 and step == (0.0, 0.3), n.pose())
n.on_fix(1 * NS, (1.0, 1.0, 0.0))
check("... and survives the next fix (mapd's pose is replaced each second, the landmarks' correction is not)",
      abs(n.pose()[1] - 1.3) < 0.01, n.pose())
n.on_fix(int(OFFSET_HALF_S * NS) + 1 * NS, (1.0, 1.0, 0.0))
check("... and halves in OFFSET_HALF_S", abs(n.pose()[1] - 1.15) < 0.01, n.pose())
n.nudge(0.0, 5.0)
check("the total correction is capped", math.hypot(*n.offset) <= 1.0 + 1e-9, n.offset)

# A goal inside a drop's ring: the duck goes as close as is safe (the operator, 2026-11-17), so the planner needs the free
# cell nearest the goal within reach; none within it (a goal across a drop) leaves the refusal.
from duck_lab.nav.grid import nearest_free  # noqa: E402

ring = grid_of({"res_m": 0.05, "origin": [0.0, 0.0], "width": 40, "height": 20, "cells": "." * 800})
ring = ring.with_blocked([(1.0, 0.75)], 0.32, 0.5)              # a drop point; the goal 0.3 m from it, inside its ring
held = nearest_free(ring, (1.0, 0.45), 0.2)
check("a goal inside a ring: the nearest free cell, within reach of it, out of the ring",
      held is not None and math.dist(held, (1.0, 0.45)) <= 0.2 and ring.at(*ring.cell(*held)) < LETHAL_COST
      and math.dist(held, (1.0, 0.75)) > 0.32, held)
check("none within reach: no hold-off (refused as before)", nearest_free(ring, (1.0, 0.75), 0.2) is None)
check("a free goal is its own nearest free cell", math.dist(nearest_free(ring, (0.3, 0.3), 0.2), (0.3, 0.3)) < 0.05)
# A goal inside an object (exploring b3 r1: the office shelf): held off where the duck can still turn, not 11 cm from it.
from duck_lab.nav.grid import clearance as _clear  # noqa: E402

shelf = grid_of(room(w=40, h=40))       # 4 x 4 m at 10 cm, walls round it
shelf = shelf.with_points([(1.0 + i * 0.05, 1.0 + j * 0.05) for i in range(4) for j in range(4)])   # a 0.2 m object
inside_goal = (1.08, 1.08)
plain = nearest_free(shelf, inside_goal, 0.3)
roomy = nearest_free(shelf, inside_goal, 0.3, room_m=0.17)
check("held off without room: right against the object (what trapped b3 r1)",
      plain is not None and _clear(shelf, plain, 0.17) < 0.17, (plain, plain and round(_clear(shelf, plain, 0.17), 3)))
check("held off with room_m: a point with room to turn", roomy is not None and _clear(shelf, roomy, 0.17) >= 0.17,
      (roomy, roomy and round(_clear(shelf, roomy, 0.17), 3)))
check("... and none within reach with room: no hold-off", nearest_free(shelf, inside_goal, 0.1, room_m=0.17) is None)

# mapd's own account (RFC-0019): its lost reason and counters recorded when they change, so a jump can be read against it.
from duck_lab.nav.run import Navigator  # noqa: E402


class _Nav:
    def __init__(self):
        self.rows, self.loc = [], Localizer(FIX)

    def record(self, **row):
        self.rows.append(row)


w = _Nav()
ok_st = {"state": {"pose": {"x": 0, "y": 0, "yaw": 0}}, "loops": 0, "relocalizations": 0, "island_keyframes": 0}
Navigator._watch_mapd(w, ok_st)
Navigator._watch_mapd(w, ok_st)
check("mapd tracking quietly: nothing recorded", w.rows == [], w.rows)
Navigator._watch_mapd(w, {"state": {"lost": "bumped"}, "loops": 0, "relocalizations": 0, "island_keyframes": 0})
Navigator._watch_mapd(w, {"state": {"pose": {"x": 0.9, "y": 0, "yaw": 0}}, "loops": 0, "relocalizations": 1,
                          "island_keyframes": 0})
check("mapd lost (bumped), then found again by a relocalization: both recorded, with what changed",
      [(r["event"], r["lost"], r["relocalizations"], r["changed"]) for r in w.rows]
      == [("mapd_status", "bumped", 0, ["lost"]), ("mapd_status", None, 1, ["lost", "relocalizations"])], w.rows)

print("NAV", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
