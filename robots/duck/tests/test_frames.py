"""One frame for the grid, the belief and the memory (RFC-0016 §6; the advisor's R2; no simulator).
Run: cd robots/duck && uv run python tests/test_frames.py"""

import math
import functools
import sys
import time
import types

from duck_lab.nav.anomaly import Returns
from duck_lab.nav.frames import Localizer, compose, move_grid, move_xy
from duck_lab.nav.grid import LETHAL_COST, CostGrid
from duck_lab.nav.run import LOW_CELL_M, Navigator
from duck_lab.nav.side_drops import SuspectMemory
from duck_lab.plugins.mapd import Mapd
from duck_lab.profile import load
from worldmodel.objects import Part, load_kinds
from worldmodel.semantic_map import SemanticMap, Tracked

P = load("sim")
FIX = P.localisation.fix
MOVE_M = FIX.move_m
SD = (P.sensors.tof8x8.side_drops.suspect_frames, P.sensors.tof8x8.side_drops.suspect_ratio, P.sensors.tof8x8.side_drops.clear_m)
grid_of = functools.partial(CostGrid.from_map_grid, lethal_m=P.footprint.lethal_m, inflate_m=P.footprint.inflate_m)
failures = []
NS = 1_000_000_000


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def near(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b)) and len(a) == len(b)


def still(max_jump_m=0.3):
    """A localizer whose odometry stands still, mapd's first fix at (1, 1)."""
    loc = Localizer(FIX, history=1000, max_jump_m=max_jump_m, hold_n=None)
    for k in range(400):
        loc.on_odom(k * NS, (0.0, 0.0, 0.0))
    loc.on_fix(0, (1.0, 1.0, 0.0))
    return loc


# --- the delta between the belief's frame and mapd's ---------------------------------------------------------------------
a = still()
check("a taken fix: the frames are one (delta zero)", near(a.delta(), (0.0, 0.0, 0.0)), a.delta())
a.on_fix(1 * NS, (1.0, 1.9, 0.0))                       # mapd's pose jumps 0.9 m: held
check("a held jump: the belief stays, the delta is the jump the other way",
      a.last_fix["status"] == "held" and near(a.pose(), (1.0, 1.0, 0.0)) and near(a.delta(), (0.0, -0.9, 0.0)), a.delta())
check("... and mapd's pose through the delta is the belief",
      near(compose(a.delta(), (1.0, 1.9, 0.0)), a.pose()), compose(a.delta(), (1.0, 1.9, 0.0)))
check("... the frames are parted", a.parted())
a.on_fix(2 * NS, (1.0, 1.0, 0.0))                       # mapd comes back
check("mapd back at the belief: the frames are together again", near(a.delta(), (0.0, 0.0, 0.0), 1e-9) and not a.parted(), a.delta())
n = still()
n.nudge(0.0, 0.3)
check("a landmarks' nudge is a delta too: belief = mapd + the nudge", near(n.delta(), (0.0, 0.3, 0.0)), n.delta())
n.on_fix(1 * NS, (1.0, 1.0, 0.0))
check("... that survives the next fix", abs(n.delta()[1] - 0.3) < 0.01, n.delta())
r = Localizer(FIX, max_jump_m=0.3, hold_n=None)
for k in range(10):
    r.on_odom(k * NS, (0.0, 0.0, 0.0))
r.on_fix(0, (0.0, 0.0, 0.0))
r.on_fix(1 * NS, (0.0, 0.0, 0.5))                       # mapd turned 0.5 rad: over the gate's 0.35, held
check("a held turn: the delta is the turn back", r.last_fix["status"] == "held" and near(r.delta(), (0.0, 0.0, -0.5)), r.delta())

# --- a loop closure is held like any large fix, and the landmarks take it (K26) -----------------------------------------
t = still()
t.on_fix(1 * NS, (1.0, 1.9, 0.0), closure="loop closure")
check("a large loop closure is held: the belief stays, the record says why",
      t.last_fix["status"] == "held" and t.last_fix["closure"] == "loop closure" and near(t.pose(), (1.0, 1.0, 0.0))
      and t.rejected == 1, t.last_fix)
check("... it is pending, as the frame change it would make", t.closure_pending() and near(t.closure_frame(), (0.0, 0.9, 0.0)),
      t.closure_frame())
check("... and the frames are parted by it", t.parted() and near(t.delta(), (0.0, -0.9, 0.0)), t.delta())
for k in range(2, 12):
    t.on_fix(k * NS, (1.0, 1.9, 0.0))                     # mapd goes on in the closure's frame, as it did in both recorded closures
check("mapd's later fixes agreeing with the closure's frame do not take it", t.last_fix["status"] == "held"
      and t.last_fix["closure"] == "loop closure" and near(t.pose(), (1.0, 1.0, 0.0)) and t.closure_pending(), t.last_fix)
n = Localizer(FIX, history=1000, max_jump_m=0.3)          # the gate's hold_n (5): an ordinary jump is taken once 5 fixes agree
for k in range(400):
    n.on_odom(k * NS, (0.0, 0.0, 0.0))
n.on_fix(0, (1.0, 1.0, 0.0))
for k in range(1, 6):
    n.on_fix(k * NS, (1.0, 1.9, 0.0))
check("with hold_n, an ordinary large fix is taken late as before", n.last_fix["status"] == "late" and near(n.pose(), (1.0, 1.9, 0.0)),
      n.last_fix)
c = Localizer(FIX, history=1000, max_jump_m=0.3)
for k in range(400):
    c.on_odom(k * NS, (0.0, 0.0, 0.0))
c.on_fix(0, (1.0, 1.0, 0.0))
c.on_fix(1 * NS, (1.0, 1.9, 0.0), closure="loop closure")
for k in range(2, 12):
    c.on_fix(k * NS, (1.0, 1.9, 0.0))
check("with hold_n, a loop closure is not taken late however many fixes agree", c.last_fix["status"] == "held"
      and near(c.pose(), (1.0, 1.0, 0.0)) and c.closure_pending(), c.last_fix)
h = t.accept_closure()
check("the landmarks agree: the belief takes mapd's frame, nothing is pending, the frames are one",
      near(h, (0.0, 0.9, 0.0)) and near(t.pose(), (1.0, 1.9, 0.0)) and not t.closure_pending() and t.closure_frame() is None
      and near(t.delta(), (0.0, 0.0, 0.0), 1e-9), (h, t.pose()))
check("... and nothing is left to accept", t.accept_closure() is None)
t.on_fix(12 * NS, (1.0, 1.9, 0.0))
check("... the next fix, in the same frame, is an ordinary taken one", t.last_fix["status"] == "taken" and "closure" not in t.last_fix, t.last_fix)
b = still()
b.on_fix(1 * NS, (1.0, 1.9, 0.0), closure="loop closure")
b.on_fix(2 * NS, (1.0, 1.05, 0.0))
check("mapd back at the belief's frame ends it: a fix that is not large is taken, nothing pending",
      b.last_fix["status"] == "taken" and not b.closure_pending() and "closure" not in b.last_fix, b.last_fix)
b.on_fix(3 * NS, (1.0, 1.95, 0.0))
check("... and a large fix after that, with no closure behind it, is held as ever", b.last_fix["status"] == "held"
      and "closure" not in b.last_fix and not b.closure_pending(), b.last_fix)
s = still()
s.on_fix(1 * NS, (1.0, 1.05, 0.0), closure="loop closure")
check("a loop closure that is not large is taken, not marked, nothing pending",
      s.last_fix["status"] == "taken" and "closure" not in s.last_fix and not s.closure_pending(), s.last_fix)
r = Localizer(FIX, max_jump_m=0.3, hold_n=None)
for k in range(10):
    r.on_odom(k * NS, (0.0, 0.0, 0.0))
r.on_fix(0, (0.0, 0.0, 0.0))
r.on_fix(1 * NS, (0.0, 0.0, 0.7), closure="loop closure")  # explore-p4s-fix-r2's closure turned the belief 0.70 rad, and moved it 2.3 m
check("a loop closure that only turns the belief (0.7 rad) is held too, and its frame is the turn",
      r.last_fix["status"] == "held" and near(r.closure_frame(), (0.0, 0.0, 0.7)), (r.last_fix, r.closure_frame()))
u = still()
u.on_fix(1 * NS, (1.0, 1.9, 0.0))
check("the same fix without a closure is held, and no closure is pending", u.last_fix["status"] == "held"
      and "closure" not in u.last_fix and not u.closure_pending() and u.closure_frame() is None, u.last_fix)

# --- when the memory moves ------------------------------------------------------------------------------------------------
m = still()
check("nothing to move at the start", m.memory_delta() is None and not m.memory_pending())
m.on_fix(1 * NS, (1.03, 1.0, 0.0))
check("a 3 cm fix: the memory stays", m.memory_delta() is None)
m.on_fix(2 * NS, (1.06, 1.0, 0.0))
check("... and 6 cm from where it sits: it moves", m.memory_pending(), MOVE_M)
d = m.memory_delta()
check("the move is the belief's change since the memory last moved, new <- old", d is not None and near(d, (0.06, 0.0, 0.0), 1e-9), d)
check("... and the memory then sits in the new frame", m.memory_delta() is None and not m.memory_pending())
h = still()
h.on_fix(1 * NS, (1.0, 1.9, 0.0))
check("a held jump moves no memory: the belief did not move", h.memory_delta() is None)
h.on_fix(2 * NS, (1.0, 1.9, 0.0), closure="loop closure")
check("a loop closure held after it moves no memory either", h.memory_delta() is None)
h.accept_closure()
d = h.memory_delta()
check("a loop closure the landmarks took: the memory moves by the belief's change", d is not None and near(d, (0.0, 0.9, 0.0), 1e-9), d)
k = still()
k.nudge(0.1, -0.2)
check("a nudge moves the memory by the step", near(k.memory_delta(), (0.1, -0.2, 0.0), 1e-9))
q = still()
q.on_fix(1 * NS, (1.0, 1.0, 0.3))
d = q.memory_delta()
check("a turn of 0.3 rad moves it (the delta carries the yaw; the pivot is the belief's origin)", d is not None and abs(d[2] - 0.3) < 1e-9, d)

# --- mapd's grid in the belief's frame: the walls relative to the duck --------------------------------------------------
res = 0.05


def wall_grid(x_wall, y_wall, origin=(-1.0, -1.0), w=100, h=100):
    cells = ["."] * (w * h)
    cells[int((y_wall - origin[1]) / res) * w + int((x_wall - origin[0]) / res)] = "#"
    return {"res_m": res, "origin": list(origin), "width": w, "height": h, "cells": "".join(cells)}


def wall_at(g):
    """The centre of the (only) wall cell."""
    i = g["cells"].index("#")
    return (g["origin"][0] + (i % g["width"] + 0.5) * g["res_m"], g["origin"][1] + (i // g["width"] + 0.5) * g["res_m"])


# the duck stands at (0, 0) by the truth; a wall is 2 m ahead (x = 2). mapd's frame jumps +0.9 in y: its pose says (0, 0.9),
# its grid has the wall at (2, 0.9); the belief held at (0, 0).
jump = Localizer(FIX, max_jump_m=0.3, hold_n=None)
for kk in range(10):
    jump.on_odom(kk * NS, (0.0, 0.0, 0.0))
jump.on_fix(0, (0.0, 0.0, 0.0))
jump.on_fix(1 * NS, (0.0, 0.9, 0.0))
mg = wall_grid(2.0 + res / 2 - 0.025, 0.9 + 0.025)
wm = wall_at(mg)
framed = move_grid(mg, jump.delta())
wb = wall_at(framed)
check("mapd's frame jumped 0.9 m, the belief held: unframed, the wall is 0.9 m off its true place relative to the duck",
      abs(wm[1]) > 0.8, wm)
check("framed, the wall is where it is relative to the duck (2 m ahead, level)", abs(wb[0] - 2.0) < 0.05 and abs(wb[1]) < 0.05, wb)
check("a shift keeps the cells and the size", framed["cells"] == mg["cells"] and framed["width"] == mg["width"], framed["origin"])
check("no delta: the grid is the grid", move_grid(mg, None) is mg and move_grid(mg, (0.0, 0.0, 0.0)) is mg)
rot = move_grid(wall_grid(1.0, 0.0), (0.0, 0.0, math.pi / 2))
wr = wall_at(rot)
check("a quarter turn: a wall 1 m ahead is 1 m to the left", abs(wr[0] - 0.0) < 0.06 and abs(wr[1] - 1.0) < 0.06, wr)
check("... on an axis-aligned grid of the same resolution", rot["res_m"] == res and len(rot["cells"]) == rot["width"] * rot["height"]
      and rot["cells"].count("#") == 1, (rot["width"], rot["height"], rot["cells"].count("#")))
tilt = move_grid(wall_grid(1.0, 0.0), (0.5, -0.3, 0.2))
wt = wall_at(tilt)
want = move_xy((0.5, -0.3, 0.2), (1.0, 0.0))
check("a tilt and a shift: the wall lands where the frame change puts it", math.dist(wt, want) < 0.06, (wt, want))
cost = grid_of(framed)
check("the framed grid is a cost grid the planner reads: the wall's cell is lethal there",
      cost.at(*cost.cell(*wb)) >= LETHAL_COST, cost.at(*cost.cell(*wb)))


# --- the memory moves with it (Navigator.move_memory, on a stand-in with the same fields) -------------------------------
class _Mem:
    move_memory = Navigator.move_memory

    def __init__(self):
        self.rows, self.loc = [], Localizer(FIX)
        self.localisation = types.SimpleNamespace(pose=self.loc.pose)
        self.blocked = [(1.0, 0.0), (2.0, 0.5)]
        self._seen = set()
        self._low = {(round(1.0 / LOW_CELL_M), 0): {1, 2, 3}}
        self.drops, self.edges = [(0.5, 0.5)], [(0.0, 1.0)]
        self.glanced, self.step_looked = [(0.2, 0.2)], [(0.3, 0.3)]
        self.locomotion = types.SimpleNamespace(tight_spots=[[(0.1, 0.1), 5.0]])
        self.floor_seen = {(20, 0), (21, 0)}                # 5 cm cells: (1.0, 0.0), (1.05, 0.0)
        self.suspects = SuspectMemory(*SD)
        self.suspects.suspected = {(10, 10)}                # 5 cm cells: (0.5, 0.5)
        self.suspects.below[(10, 10)] = 7
        self.semantic = SemanticMap(load_kinds())
        self.semantic.objects.append(Tracked("chair_1", "chair", 1.0, 1.0, [Part(1.0, 1.0, 0.2, 0.1, 0.0, 0.0, 0.5)]))
        self.semantic.anchors["lm_1"] = (3.0, 3.0)
        import threading
        self._sem_lock = threading.Lock()
        self._moves, self.on_move = [], None
        self._returns = Returns(4.0)
        self._returns.add(1.0, [[1.0, 0.0, 0.0, "f"]])
        self.told = []

    def record(self, **row):
        self.rows.append(row)


mem = _Mem()
mem.on_move = mem.told.append
mem.move_memory((0.0, 0.9, 0.0))
check("the obstacle points move by the delta", [tuple(round(v, 3) for v in b) for b in mem.blocked] == [(1.0, 0.9), (2.0, 1.4)],
      mem.blocked)
check("... and the set that keeps them apart follows", (round(1.0 / 0.03), round(0.9 / 0.03)) in mem._seen)
check("the drops, the measured edges, what was glanced at and looked at move",
      mem.drops == [(0.5, 1.4)] and mem.edges == [(0.0, 1.9)] and mem.glanced == [(0.2, 1.1)] and mem.step_looked == [(0.3, 1.2)],
      (mem.drops, mem.edges, mem.glanced, mem.step_looked))
check("the tight-pivot spot moves, its time stays", mem.locomotion.tight_spots == [[(0.1, 1.0), 5.0]], mem.locomotion.tight_spots)
check("the floor the sensor saw moves (5 cm cells)", mem.floor_seen == {(20, 18), (21, 18)}, sorted(mem.floor_seen))
check("the depth returns of the last seconds (room_disagrees) move, their kind kept", mem._returns.last(1.0) == [(1.0, 0.9, "f")],
      mem._returns.last(1.0))
check("the low-band cells move with their frames", mem._low == {(round(1.0 / LOW_CELL_M), round(0.9 / LOW_CELL_M)): {1, 2, 3}}, mem._low)
check("the suspected drops and their counts move", mem.suspects.suspected == {(10, 28)} and mem.suspects.below[(10, 28)] == 7,
      (mem.suspects.suspected, dict(mem.suspects.below)))
o = mem.semantic.objects[0]
check("the objects and their parts move", near((o.x, o.y), (1.0, 1.9)) and near((o.parts[0].x, o.parts[0].y), (1.0, 1.9)), (o.x, o.y))
check("the landmarks' anchors do not: they are what the belief is checked against", mem.semantic.anchors == {"lm_1": (3.0, 3.0)})
check("the move is kept for a leg's goal and told to the explorer, and recorded",
      mem._moves == [(0.0, 0.9, 0.0)] and mem.told == [(0.0, 0.9, 0.0)] and mem.rows[-1]["event"] == "memory_moved"
      and mem.rows[-1]["delta"] == [0.0, 0.9, 0.0], mem.rows[-1])
turn = _Mem()
turn.move_memory((0.0, 0.0, math.pi / 2))
check("a quarter turn turns the points about the map's origin: (1, 0) is (0, 1)",
      near(turn.blocked[0], (0.0, 1.0)) and near(turn.drops[0], (-0.5, 0.5)), (turn.blocked, turn.drops))
o = turn.semantic.objects[0]
check("... the object's part turns too", near((o.parts[0].x, o.parts[0].y), (-1.0, 1.0)) and abs(o.parts[0].yaw - math.pi / 2) < 1e-9,
      (o.parts[0].x, o.parts[0].y, o.parts[0].yaw))
# the same point through a localizer: a belief that moved by a nudge, the memory by memory_delta, the pose agrees
lc = still()
lc.on_odom(500 * NS, (0.5, 0.0, 0.0))
p_before = lc.pose()
mem_pt = move_xy((0.0, 0.0, 0.0), (p_before[0], p_before[1]))          # a point the memory placed at the belief's pose
lc.nudge(0.0, 0.3)
p_after = lc.pose()
moved = move_xy(lc.memory_delta(), mem_pt)
check("a point placed at the belief stays at the belief after the belief's frame moved (the pose and the memory agree)",
      near(moved, p_after[:2], 1e-9), (moved, p_after))


# --- the gate follows mapd's own account (the localisation plugin's _watch) -----------------------------------------------
class _Watch:
    """The localisation plugin (mapd) watching mapd's account of itself, and the rows it records."""

    def __init__(self):
        self.rows, self.mapd = [], Mapd(P)

    def record(self, **row):
        self.rows.append(row)

    def _watch_mapd(self, st):
        return self.mapd._watch(st, self.record)


def status(lost=None, loops=0, relocs=0, islands=0):
    return {"state": {"pose": {"x": 0, "y": 0, "yaw": 0}, "lost": lost}, "loops": loops, "relocalizations": relocs,
            "island_keyframes": islands}


w = _Watch()
check("mapd tracking quietly: no trust, nothing to take", w._watch_mapd(status()) is None and w._watch_mapd(status()) is None)
check("a loop closure and mapd not lost: a large fix may be taken", w._watch_mapd(status(loops=1)) == "loop closure")
check("... the next status, unchanged, still within its credit", w._watch_mapd(status(loops=1)) == "loop closure")
w.mapd._loop_credit = time.monotonic() - 1.0
check("... but not after loop_credit_s", w._watch_mapd(status(loops=1)) is None)
w = _Watch()
w._watch_mapd(status())
check("a loop counter that stepped while mapd is lost: held", w._watch_mapd(status(lost="carried", loops=1)) is None)
check("... and not afterwards either, until mapd knows where it is and closes another",
      w._watch_mapd(status(loops=1)) is None and w._watch_mapd(status(loops=2)) == "loop closure")
w = _Watch()
w._watch_mapd(status())
check("a relocalization stepping: held, even with a loop closure at the same time",
      w._watch_mapd(status(loops=1, relocs=1)) is None)
w = _Watch()
w._watch_mapd(status(loops=3))
check("mapd's first look with loops already counted is not a step", w._watch_mapd(status(loops=3)) is None)
w = _Watch()
w._watch_mapd(status())
w._watch_mapd(status(loops=1))
w.mapd._loop_credit = None
check("a consumed credit is gone", w._watch_mapd(status(loops=1)) is None)


# --- frames_parted --------------------------------------------------------------------------------------------------------
class _Parts:
    _watch_frames = Navigator._watch_frames

    def __init__(self, loc):
        self.rows, self.loc, self._parted_at, self.profile, self.anomalies = [], loc, None, P, []
        self.localisation = types.SimpleNamespace(seen=None, frame_delta=loc.delta)

    def record(self, **row):
        self.rows.append(row)

    def anomaly(self, kind, summary, severity=None, **fields):     # (the robot-tagged one: tests/test_anomaly.py reads what it says)
        self.anomalies.append(kind)


pl = still()
pt = _Parts(pl)
pt._watch_frames()
check("frames together: nothing said", pt.rows == [])
pl.on_fix(1 * NS, (1.0, 1.9, 0.0))
pt._watch_frames()
pt._watch_frames()
check("parted: said once, with the delta", [r["event"] for r in pt.rows] == ["frames_parted"]
      and pt.rows[0]["delta"] == [0.0, -0.9, 0.0], pt.rows)
pl.on_fix(2 * NS, (1.0, 2.5, 0.0))
pt._watch_frames()
check("parted further (over 0.25 m more): said again", [r["event"] for r in pt.rows] == ["frames_parted", "frames_parted"], pt.rows)
pl.on_fix(3 * NS, (1.0, 1.0, 0.0))
pt._watch_frames()
check("together again: said", pt.rows[-1]["event"] == "frames_joined", pt.rows[-1])
small = _Parts(still())
small.loc.nudge(0.0, 0.1)
small._watch_frames()
check("a 10 cm nudge is not parting", small.rows == [])

print("FRAMES", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
