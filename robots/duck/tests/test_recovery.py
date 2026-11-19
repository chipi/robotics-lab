"""Before "trapped" (nav/recovery.py, Explorer.recovered; no simulator). Run: cd robots/duck && uv run python tests/test_recovery.py"""

import math
import sys

from duck_lab.nav import recovery
from duck_lab.nav.explore_run import Explorer

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        failures.append(name)


# --- which motion ---------------------------------------------------------------------------------------------------------
pose = (0.0, 0.0, 0.0)                    # facing +x
drop_left = ((0.0, 0.3), "drop")           # a drop 0.3 m to the left
check("room ahead, nothing in front: a creep", recovery.choose(0, 376, False, None) == "creep")
check("room ahead and a hazard: a creep first (attempt 0), an arc next (attempt 1), a creep again (2)",
      [recovery.choose(a, 376, False, drop_left) for a in (0, 1, 2)] == ["creep", "arc", "creep"])
check("a remembered drop in front forbids a creep: the arc away", recovery.choose(0, 376, True, drop_left) == "arc")
check("less than 250 mm ahead: neither (a creep needs 150 mm at its end and 100 mm to go): the survey alone",
      recovery.choose(0, 249, False, drop_left) == "stand" and recovery.choose(1, 113, False, drop_left) == "stand")
check("250-299 mm ahead (b11 r3 and r5): a creep, no arc (an arc reaches 0.2 m and the footprint)",
      recovery.choose(0, 283, False, drop_left) == "creep" and recovery.choose(1, 283, False, drop_left) == "creep"
      and recovery.choose(1, 283, False, None) == "creep")
check("... and not a creep that does not gain room: the survey alone", recovery.choose(0, 283, False, drop_left, creep_ok=False) == "stand")
check("a creep that does not gain room, with room for an arc: the arc", recovery.choose(0, 320, False, drop_left, creep_ok=False) == "arc")
check("it gains room when the room ahead is a turn's room and more than here (b11 r5: 0.136 -> 0.178; r3: 0.114 -> 0.088)",
      recovery.creep_gains_room(0.136, 0.178, 0.17) and not recovery.creep_gains_room(0.114, 0.088, 0.17)
      and not recovery.creep_gains_room(0.30, 0.25, 0.17) and not recovery.creep_gains_room(0.10, 0.16, 0.17))
check("the room now and ahead from remembered points: 0.138 m from a point behind-left, 0.178 m after 0.10 m ahead",
      abs(recovery.projected_room((0.0, 0.0, 0.0), [(-0.04, 0.132)], 0.10)[0] - 0.138) < 0.01
      and recovery.projected_room((0.0, 0.0, 0.0), [(-0.04, 0.132)], 0.10)[1] > 0.17 and recovery.projected_room((0.0, 0.0, 0.0), [], 0.1)[0] == math.inf)
check("no sensor reading: the survey alone", recovery.choose(0, None, False, drop_left) == "stand")
check("room, a drop in front and no hazard to turn from: the survey alone", recovery.choose(0, 400, True, None) == "stand")
check("250 mm is room for a creep, 249 is not", recovery.choose(0, 250, False, None) == "creep" and recovery.choose(0, 249, False, None) == "stand")

check("a drop within 0.6 m and 35 deg of the heading is in front",
      recovery.drop_ahead(pose, [(0.5, 0.1)]) and not recovery.drop_ahead(pose, [(0.5, 0.5)]) and not recovery.drop_ahead(pose, [(0.7, 0.0)])
      and not recovery.drop_ahead(pose, [(-0.3, 0.0)]))
check("the hazard is the nearest drop within 1 m, else the nearest obstacle point within 0.4 m, else none",
      recovery.hazard(pose, [(0.0, 0.9), (0.0, -0.4)], [(0.1, 0.1)]) == ((0.0, -0.4), "drop")
      and recovery.hazard(pose, [(0.0, 1.5)], [(0.3, 0.2), (0.1, 0.1)]) == ((0.1, 0.1), "obstacle")
      and recovery.hazard(pose, [(0.0, 1.5)], [(0.5, 0.5)]) is None and recovery.hazard(pose, [], []) is None)
check("a turn away from a point on the left is to the right, from one on the right to the left",
      recovery.turn_away(pose, (0.0, 0.3)) == -1.0 and recovery.turn_away(pose, (0.0, -0.3)) == 1.0
      and recovery.turn_away((0.0, 0.0, math.pi / 2), (-0.3, 0.0)) == -1.0)

# --- a run that starts beside a drop leaves it ----------------------------------------------------------------------------
dock = (0.0, 0.0, -math.pi / 2)            # facing the drop at y -0.3
away = recovery.away_target(dock, [(0.0, -0.3)], lambda p: True)
check("a drop 0.3 m ahead: the first leg is directly away from it, 0.5 m out", away is not None
      and abs(away[0]) < 1e-9 and abs(away[1] - 0.5) < 1e-9, away)
away = recovery.away_target(dock, [(0.0, -0.3)], lambda p: p[1] < 0.45 and p[0] > 0.1)
check("the first place that is accepted: not straight away if that is refused, a 30 deg side, a nearer distance",
      away is not None and away[0] > 0.1 and math.dist(away, (0.0, 0.0)) in (0.4, 0.5, 0.6), away)
check("a drop beyond the start margin: no first leg", recovery.away_target(dock, [(0.0, -0.8)], lambda p: True) is None)
check("no drop: no first leg", recovery.away_target(dock, [], lambda p: True) is None)
check("nothing accepted: no first leg (the explorer goes on as before)", recovery.away_target(dock, [(0.0, -0.3)], lambda p: False) is None)
check("it is not tied to a place: the same rule at another pose and heading",
      all(abs(math.dist(recovery.away_target((5.0, 3.0, 0.0), [(5.2, 3.0)], lambda p: True), (5.0, 3.0)) - 0.5) < 1e-9 for _ in (0,)))


# --- the ladder: a refusal at the pose costs a recovery first -------------------------------------------------------------
class _Nav:
    def __init__(self):
        self.recoveries = []

    def recover(self, attempt):
        self.recoveries.append(attempt)


def explorer():
    ex = Explorer.__new__(Explorer)
    ex.nav, ex.attempts = _Nav(), 0
    return ex


no_room = {"status": "refused", "why": "no room to turn (0.20 m to an obstacle, 0.25 m to a drop)"}
ex = explorer()
got = [ex.recovered(no_room) for _ in range(7)]
check("'no room to turn': three recoveries (attempts 0, 1, 2), then the refusal counts", got == [True] * 3 + [False] * 4
      and ex.nav.recoveries == [0, 1, 2], (got, ex.nav.recoveries))
ex = explorer()
check("a start in a lethal cell ('no path' with start_lethal) is a pose problem too",
      ex.recovered({"status": "refused", "why": "no path on the map", "start_lethal": True}) and ex.nav.recoveries == [0])
ex = explorer()
check("so is 'start boxed in' (after the explorer has forgotten the points once)", ex.recovered({"status": "refused", "why": "start boxed in"}))
ex = explorer()
check("a target with no path (a free start) is not: it is the target's problem",
      not ex.recovered({"status": "refused", "why": "no path on the map", "start_lethal": False}) and ex.nav.recoveries == [])
check("a stall, a timeout, an abort are not refusals at the pose",
      not any(explorer().recovered({"status": s, "why": "no room to turn"}) for s in ("stalled", "timeout", "aborted", "reached")))
ex = explorer()
ex.recovered(no_room)
ex.attempts = 0                                          # a leg was reached
check("a reached leg gives the recoveries back", ex.recovered(no_room) and ex.nav.recoveries == [0, 0])

# --- the motions (Navigator._walk, on a stand-in whose pose follows the commands at 10 Hz) --------------------------------
from duck_lab.nav.follow import Twist  # noqa: E402
from duck_lab.nav.run import Navigator  # noqa: E402


class _Tof:
    nearest_mm = 800


class _Frame:
    ok, block, drops = True, None, []


class _Walker:
    _walk = Navigator._walk
    abort = None

    def __init__(self):
        self.pose, self.tof, self._fv, self.sent, self.blocked = (0.0, 0.0, 0.0), _Tof(), None, [], []

    @property
    def loc(self):
        walker = self

        class Loc:
            def pose(self):
                return walker.pose
        return Loc()

    def move(self, tw):
        self.sent.append(tw)
        x, y, yaw = self.pose
        self.pose = (x + tw.vx * 0.1 * math.cos(yaw), y + tw.vx * 0.1 * math.sin(yaw), yaw + tw.vyaw * 0.1)


import duck_lab.nav.run as _run  # noqa: E402

_run.time.sleep = lambda s: None                       # the stand-in's clock is the commands, not the wall
w = _Walker()
why = w._walk(0.0, 0.10, 0.2, 0.0, timeout_s=1e9)
check("a creep walks 0.10 m ahead and stops with a zero command", why is None and abs(math.dist(w.pose[:2], (0, 0)) - 0.10) < 0.03
      and w.sent[-1] == Twist(), (why, w.pose))
w = _Walker()
w.tof.nearest_mm = 240
check("... not at all with less than 250 mm ahead", w._walk(0.0, 0.10, 0.2, 0.0, 1e9) == "no room ahead" and w.pose == (0.0, 0.0, 0.0))
w = _Walker()
f = _Frame()
f.drops = [(0.4, 0.0, 0.5)]
w._fv = f
check("... nor with a drop in the frame within the cliff-stop distance", w._walk(0.0, 0.10, 0.2, 0.0, 1e9) == "drop")
w = _Walker()
f = _Frame()
f.block = 0.2
w._fv = f
check("... nor with an obstacle in its corridor", w._walk(0.0, 0.10, 0.2, 0.0, 1e9) == "obstacle")
w = _Walker()
w.abort = "truth guard"
check("... nor after an abort", w._walk(0.0, 0.10, 0.2, 0.0, 1e9) == "abort")
w = _Walker()


class _Closing:
    """A sensor whose nearest return falls 2 m per m walked (a wall ahead, close)."""
    @property
    def nearest_mm(self):
        return 300 - 2000 * w.pose[0]


w.tof = _Closing()
why = w._walk(0.0, 0.10, 0.2, 0.0, 1e9)
check("a creep stops when the sensor shows less than the footprint and margin plus what is left to go (150 mm + the rest)",
      why == "no room ahead" and 0.04 < w.pose[0] < 0.09 and w.sent[-1] == Twist(), (why, w.pose))
w = _Walker()
w.blocked = [(0.2, 0.15)]                                # a remembered point beside the way, 0.25 m off
why = w._walk(0.0, 0.10, 0.2, 0.0, 1e9)
check("... and when the remembered obstacles are nearer than at the start (by 1 cm): it does not walk toward them",
      why == "closer to something" and w.pose[0] < 0.08, (why, w.pose))
w = _Walker()
w.blocked = [(-0.3, 0.1)]
check("a remembered point behind, getting farther: not a reason to stop", w._walk(0.0, 0.10, 0.2, 0.0, 1e9) is None)
w = _Walker()
why = w._walk(0.7, 0.0, 0.2, -1.0, 1e9)
check("an arc turns 0.7 rad to the right while walking, and stops", why is None and abs(w.pose[2] + 0.7) < 0.15 and w.pose[0] > 0.0,
      (why, w.pose))
w = _Walker()
check("a walk that has not got there when the time is out says so", w._walk(0.0, 5.0, 0.2, 0.0, 0.0) == "time")

# --- Navigator.recover end to end on the stand-in: the choice, the walk, the survey, the event --------------------------------
from duck_lab.nav.grid import CostGrid  # noqa: E402
from duck_lab.nav.side_drops import SuspectMemory  # noqa: E402


class _Recoverer(_Walker):
    recover = Navigator.recover
    _walk = Navigator._walk
    hazards = Navigator.hazards
    costs_here = Navigator.costs_here

    def __init__(self, points=()):
        super().__init__()
        self.blocked, self.drops, self.edges, self.suspects, self.rows, self.surveys = list(points), [], [], SuspectMemory(), [], 0
        self.semantic_points = lambda: []

    def grid(self):
        return CostGrid.from_map_grid({"res_m": 0.05, "origin": [-2.0, -2.0], "width": 80, "height": 80, "cells": "." * 6400})

    def survey(self):
        self.surveys += 1
        return True

    def record(self, **row):
        self.rows.append(row)


rc = _Recoverer([(-0.04, 0.132)])                   # b11 r5's shape: a point 0.138 m behind-left, room ahead
rc.tof.nearest_mm = 283
out = rc.recover(0)
ev = rc.rows[-1]
check("recover on a pose with 283 mm ahead and 0.138 m of room that a creep takes to 0.178: a creep, then a survey, one event",
      out["action"] == "creep" and rc.surveys == 1 and ev["event"] == "recovery" and ev["action"] == "creep"
      and ev["moved_m"] > 0.05 and ev["room_ahead_m"] > ev["room_m"] and ev["nearest_mm"] == 283, ev)
rc = _Recoverer([(0.12, -0.05), (0.10, -0.08)])      # b11 r3's shape: the memory is ahead-right, a creep walks into it
rc.tof.nearest_mm = 283
out = rc.recover(0)
check("... with the memory ahead (a creep would take the room from 0.12 to 0.09 m): the survey alone, no motion",
      out["action"] == "stand" and rc.surveys == 1 and rc.pose == (0.0, 0.0, 0.0) and rc.rows[-1]["moved_m"] == 0.0, rc.rows[-1])
rc = _Recoverer([(0.0, 0.3)])
rc.tof.nearest_mm = 600
rc.drops = [(0.0, 0.4)]
out = rc.recover(1)
check("attempt 1 with room and a drop 0.4 m to the left: an arc to the right, away from it", out["action"] == "arc"
      and out["turned_rad"] > 0.3 and rc.pose[2] < 0.0, (out, rc.pose))

print("RECOVERY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
