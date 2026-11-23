"""The navigator's own anomalies (RFC-0019 step 1, PHASE3-PREP B1): the record, the stateful rules, and each raise point on a navigator
built from the duck's real plugins with its sockets replaced by stubs (no simulator): the fix gate, the relocaliser, stuck, the frames,
the explorer's refusal burst, the turn rules, the planner's refusals, the head, the camera, the streams' watchdog and the lease. Each
case also says what must NOT raise it. An anomaly is a row of the run's log and nothing else: it carries no decision, and the
navigator's own rows are the same with and without it.
Run: cd robots/duck && uv run python tests/test_anomaly.py"""

import collections
import io
import json
import math
import sys
import threading
import time
import types

from duck_lab.nav import anomaly as anom, explore_run, run, server
from duck_lab.nav.client import LeaseLost
from duck_lab.nav.follow import Twist
from duck_lab.nav.frames import Localizer
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import JOINTS
from duck_lab.nav.side_drops import SuspectMemory
from duck_lab.profile import load

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


SIM, REAL = load("sim"), load(None)
NS = 1_000_000_000

# ---- the record ----------------------------------------------------------------------------------------------------------------
row = anom.record("fix_jump_held", "mapd moved the belief 0.90 m; held", belief=(1.94, -1.0123), mapd=(2.5, 0.1), values={"jump_m": 0.9}, margin=0.6)
check("the record has RFC-0019 section 2.1's fields, source robot, as an event row", {"event", "anomaly", "source", "module", "severity", "detector",
      "version", "summary", "values", "margin", "where", "evidence", "related"} <= set(row) and row["event"] == "anomaly" and row["source"] == "robot"
      and row["module"] == "localizer" and row["detector"] == "fix_gate" and row["version"] == 1 and row["severity"] == "major", row)
check("where: the belief and mapd's place in the map frame, rounded; no truth (the run's own row has it)",
      row["where"] == {"frame": "map", "belief": [1.94, -1.012], "mapd": [2.5, 0.1]} and "decision" not in row, row["where"])
check("every kind has a module, a detector and a severity the format knows", all(m and d and s in anom.SEVERITIES for m, d, s in anom.KINDS.values())
      and len(anom.KINDS) == 19 and anom.SOURCE.get("guardrail_unenforced") == "harness", sorted(anom.KINDS))
try:
    anom.record("stuck", "x", "dire")
    check("a severity the format does not know is refused", False)
except ValueError:
    check("a severity the format does not know is refused", True)
check("a severity given wins over the kind's", anom.record("frames_parted", "x", "major")["severity"] == "major"
      and anom.record("frames_parted", "x")["severity"] == "minor")
check("over: metres past the distance limit when past it, else radians past the turn limit",
      anom.over(0.9, 0.3, 0.1, 0.35) == (0.9 - 0.3, "m") and anom.over(0.1, 0.3, 0.5, 0.35)[1] == "rad")

# ---- the stateful rules, with an explicit clock ------------------------------------------------------------------------------------
gate = anom.PlaceGate(0.10, 5.0)
check("a place is said once: the same pose again is not, a pose 0.2 m away is, the same place after the gap is",
      gate.allow(0.0, (1.0, 1.0, 0.0)) and not gate.allow(1.0, (1.03, 1.0, 0.5)) and gate.allow(2.0, (1.2, 1.0, 0.0)) and not gate.allow(3.0, (1.2, 1.0))
      and gate.allow(8.0, (1.2, 1.0)))

burst = anom.RefusalBurst(3, 0.10)
check("refusal burst: the third refusal at one pose says it, once; a fourth does not",
      [burst.refused((1.0, 1.0)), burst.refused((1.02, 1.0)), burst.refused((1.0, 1.03)), burst.refused((1.0, 1.0))] == [None, None, 3, None])
burst.reset()
check("refusal burst: a refusal 0.3 m away starts a new streak, and a reset (a leg that was not refused) starts one too",
      [burst.refused((1.0, 1.0)), burst.refused((1.0, 1.0)), burst.refused((1.3, 1.0)), burst.refused((1.3, 1.0))] == [None, None, None, None]
      and burst.refused((1.3, 1.0)) == 3)
burst.reset()
check("refusal burst: two refusals are not a burst", burst.refused((0, 0)) is None and burst.refused((0, 0)) is None)

POSE = SIM.anomalies.head_walk_pose
OFF, HOLD = SIM.anomalies.head_off_walk_rad, SIM.anomalies.head_off_walk_s
joints = dict(POSE)
head = anom.HeadWatch(POSE, OFF, HOLD)


def tilted(by):
    return {**POSE, "head_pitch": POSE["head_pitch"] + by}


check("head: the walking pose itself, and a sway inside the limit, say nothing", head.update(0.0, True, dict(POSE)) is None
      and head.update(5.0, True, tilted(OFF - 0.01)) is None)
check("head: off the pose by more than the limit, walking: nothing until it has lasted the hold time",
      head.update(10.0, True, tilted(OFF + 0.05)) is None and head.update(10.0 + HOLD - 0.1, True, tilted(OFF + 0.05)) is None)
ev = head.update(10.0 + HOLD + 0.01, True, tilted(OFF + 0.05))
check("head: ... then once, with the joint and how far", ev is not None and ev["joint"] == "head_pitch" and abs(ev["deviation_rad"] - (OFF + 0.05)) < 1e-9, ev)
check("head: ... and not again while it stays off", head.update(20.0, True, tilted(OFF + 0.05)) is None)
check("head: back within the limit re-arms it", head.update(21.0, True, dict(POSE)) is None and head.update(22.0, True, tilted(OFF + 0.05)) is None
      and head.update(22.0 + HOLD + 0.1, True, tilted(OFF + 0.05)) is not None)
head = anom.HeadWatch(POSE, OFF, HOLD)
check("head: standing (a glance) with the head turned says nothing, however long", all(head.update(t * 1.0, False, tilted(1.0)) is None for t in range(10)))
check("head: ... and the clock starts when walking starts", head.update(10.0, True, tilted(1.0)) is None and head.update(10.0 + HOLD + 0.1, True, tilted(1.0)))
check("head: a state with none of the joints says nothing", anom.HeadWatch(POSE, OFF, HOLD).update(0.0, True, {}) is None)

beat = anom.Staleness(3.0, 0.0)
check("stale: quiet inside the limit, said once when past it, again only after the stream has spoken",
      beat.check(2.9) is None and abs(beat.check(3.5) - 3.5) < 1e-9 and beat.check(9.0) is None
      and (beat.seen(10.0) or beat.check(12.0)) is None and abs(beat.check(13.5) - 3.5) < 1e-9)


# ---- a navigator from the duck's real plugins, its sockets replaced ----------------------------------------------------------------
class Rpc:
    """robotd and mapd as the navigator calls them: every call collected; the map's grid; a command that fails when told to."""

    def __init__(self, grid=None):
        self.calls, self.grid, self.fail, self.status = [], grid, None, {"state": {}}

    def call(self, method, params=None):
        self.calls.append((method, params))
        if self.fail is not None and method == "robot.move":
            raise self.fail
        if method == "map.grid":
            return dict(self.grid)
        if method == "map.status":
            return self.status
        return {}


def make_grid(width, height, walls=(), res=0.05):
    """A map of known free floor with walls: (x0, y0, x1, y1) boxes in metres."""
    cells = ["."] * (width * height)
    for x0, y0, x1, y1 in walls:
        for cy in range(int(y0 / res), int(y1 / res) + 1):
            for cx in range(int(x0 / res), int(x1 / res) + 1):
                if 0 <= cx < width and 0 <= cy < height:
                    cells[cy * width + cx] = "#"
    return {"res_m": res, "origin": [0.0, 0.0], "width": width, "height": height, "cells": "".join(cells)}


def navigator(grid=None, pose=(1.0, 2.5, 0.0), nearest_mm=600, profile=REAL):
    """A Navigator in the real duck's variant: scale 1, its plugins built, nothing connected; the log is in memory."""
    nav = Navigator.__new__(Navigator)
    nav.robot, nav.mapd = Rpc(), Rpc(grid)
    nav.configure(profile)
    nav.localisation.bind(nav.mapd)
    nav._t0, nav._log, nav.body, nav.state = time.monotonic(), io.StringIO(), None, types.SimpleNamespace(latest=None, _thread=None)
    nav._states, nav._fv, nav.sense, nav._logging_failed = collections.deque(maxlen=40), None, {}, False
    nav.blocked, nav._seen, nav._low, nav._drop_streak, nav._drop_frame, nav._depth, nav._block = [], set(), {}, 0, None, None, None
    nav.floor_seen, nav.glanced, nav.step_looked, nav.drops, nav.edges, nav._moves = set(), [], [], [], [], []
    sd = nav.profile.sensors.tof8x8.side_drops
    nav.suspects = SuspectMemory(sd.suspect_frames, sd.suspect_ratio, sd.clear_m)
    nav._map_raw, nav.fix_fault, nav.fault_grid, nav.frames_on, nav._world_key = None, None, False, True, None
    nav.abort, nav.semantic, nav.room, nav.area, nav.area_agrees = None, None, None, None, None
    nav._sem_lock, nav._closing, nav._closure_window = threading.Lock(), threading.Event(), []
    nav.range._nearest_mm = nearest_mm
    nav.range.unseen_ahead = lambda *a, **k: None          # the step check looks at floor not yet seen: not what is under test here
    nav.localisation.on_odom(NS, pose)
    nav.loc.on_fix(NS, pose)
    return nav


def rows(nav):
    return [json.loads(line) for line in nav._log.getvalue().splitlines()]


def anomalies(nav, kind=None):
    return [r for r in rows(nav) if r.get("event") == "anomaly" and (kind is None or r["anomaly"] == kind)]


nav = navigator()
nav.anomaly("stuck", "no way", values={"moved_m": 0.01})
r = anomalies(nav)
check("Navigator.anomaly writes one row: the record, the belief's place, a time; no decision", len(r) == 1 and r[0]["anomaly"] == "stuck"
      and r[0]["where"] == {"frame": "map", "belief": [1.0, 2.5]} and isinstance(r[0]["t"], float) and "decision" not in r[0], r)
nav.record = lambda **row: (_ for _ in ()).throw(RuntimeError("the log is full"))
err = io.StringIO()
sys.stderr, keep = err, sys.stderr
try:
    nav.anomaly("stuck", "no way")
finally:
    sys.stderr = keep
check("a failure to write one is said on stderr and never raised", "stuck not recorded" in err.getvalue() and "the log is full" in err.getvalue())

# ---- fix_jump_held: every held fix, none throttled (through Navigator.fix, with mapd's status as the stub says it) ---------------------
def fix_at(nav, k, x, y, yaw=0.0):
    """mapd's pose at second k, the odometry standing still at the start: nav.fix() asks mapd, the gate decides, the navigator watches."""
    nav.localisation.on_odom(k * NS, (1.0, 2.5, 0.0))
    nav.mapd.status = {"state": {"pose": {"x": x, "y": y, "yaw": yaw}, "t_ns": k * NS}}
    return nav.fix()


nav = navigator()
check("a fix the gate took: nothing said", fix_at(nav, 2, 1.02, 2.5) and anomalies(nav) == [] and nav.loc.last_fix["status"] == "taken", nav.loc.last_fix)
for k in range(1, 9):
    fix_at(nav, 2 + k, 1.0, 2.5 + 0.9)
r = anomalies(nav, "fix_jump_held")
check("a mapd fix that would move the belief 0.9 m, held: one anomaly for each of 8 in a row, where the `fix` event keeps 3 of them",
      len(r) == 8 and all(x["severity"] == "major" and x["values"]["jump_m"] == 0.9 for x in r)
      and len([x for x in rows(nav) if x.get("event") == "fix" and x["status"] == "held"]) == 3, (len(r), len([x for x in rows(nav) if x.get("event") == "fix"])))
check("... with the numbers: the margin past the gate's 0.3 m, mapd's own place, what the gate saw", abs(r[0]["margin"] - 0.6) < 1e-9
      and r[0]["values"]["margin_unit"] == "m" and r[0]["where"]["mapd"] == [1.0, 3.4] and r[0]["where"]["belief"] == [1.02, 2.5]
      and r[0]["values"]["held_total"] == 1 and r[7]["values"]["held_total"] == 8 and r[0]["evidence"]["fix_t_ns"] == 3 * NS, r[0])
check("... and the same fixes part the frames (the existing watch), said once", [x["anomaly"] for x in anomalies(nav)].count("frames_parted") == 1)
turn = navigator()
fix_at(turn, 2, 1.0, 2.5, 0.6)
r = anomalies(turn, "fix_jump_held")
check("a fix that only turns the belief 0.6 rad (limit 0.35) is held too, the margin in radians", len(r) == 1 and r[0]["values"]["margin_unit"] == "rad"
      and abs(r[0]["margin"] - 0.25) < 1e-3, r)

# ---- a loop closure (K26): held with the same anomaly; the landmarks take it, or it stays held --------------------------------
from worldmodel.objects import load_kinds  # noqa: E402
from worldmodel.relocalise import Relocaliser  # noqa: E402
from worldmodel.semantic_map import CONFIRM_N, Detection, SemanticMap  # noqa: E402


def closure_at(nav, k, x, y, loops):
    """mapd's pose at second k with its loop counter at `loops` (the odometry standing still at (1.0, 2.5))."""
    nav.localisation.on_odom(k * NS, (1.0, 2.5, 0.0))
    nav.mapd.status = {"state": {"pose": {"x": x, "y": y, "yaw": 0.0}, "t_ns": k * NS}, "loops": loops}
    return nav.fix()


def closed_navigator(fridge_at):
    """A navigator whose mapd closed a loop at second 3 and moved the belief 0.9 m, with a fridge anchored at `fridge_at`."""
    nav = navigator()
    closure_at(nav, 2, 1.0, 2.5, 0)
    closure_at(nav, 3, 1.0, 3.4, 1)
    sm = SemanticMap(load_kinds(), "apartment")
    for k in range(CONFIRM_N):
        sm.integrate([Detection("fridge", fridge_at[0], fridge_at[1], 0.3, 0.0, 1.8, math.hypot(*fridge_at))], (0.0, 0.0, 0.0), float(k))
    sm.anchor_landmarks()
    nav.semantic, nav.reloc = sm, Relocaliser(sm, numbers=nav.profile.localisation.landmarks)
    return nav


def look_at_fridge(nav, looks, t0=10.0):
    """`looks` sightings of a fridge 1 m ahead of the belief, 0.5 s apart; what _probe_closure said to each."""
    fridge = [Detection("fridge", 1.0, 0.0, 0.3, 0.0, 1.8, 1.0)]
    return [nav._probe_closure(fridge, nav.loc.pose(), t0 + 0.5 * k) for k in range(looks)]


nav = closed_navigator((2.0, 3.4))
r = anomalies(nav, "fix_jump_held")
fixes = [x for x in rows(nav) if x.get("event") == "fix"]
check("mapd's loop closure moving the belief 0.9 m: held, the belief stays, the one anomaly says it was the loop closure",
      nav.loc.last_fix["status"] == "held" and abs(nav.loc.pose()[1] - 2.5) < 1e-9 and len(r) == 1 and r[0]["values"]["closure"] == "loop closure"
      and "loop closure" in r[0]["summary"] and r[0]["severity"] == "major", (nav.loc.last_fix, r))
check("... and the `fix` event's decision says it is held until the landmarks agree", len(fixes) == 1 and fixes[0]["status"] == "held"
      and fixes[0]["closure"] == "loop closure" and "until the landmarks agree" in fixes[0]["decision"]["reason"], fixes)
fix_at(nav, 4, 1.0, 3.4)
check("a fix after it, the credit spent: held with the closure still pending; the duck's fixes go on", nav.loc.last_fix["status"] == "held"
      and nav.loc.closure_pending() and len(anomalies(nav, "fix_jump_held")) == 2, nav.loc.last_fix)
check("no sighting yet: nothing to judge by, still held", look_at_fridge(nav, 1) == [False] and nav.loc.closure_pending())
taken = look_at_fridge(nav, 4, t0=20.0)
checks = [x for x in rows(nav) if x.get("event") == "closure_check"]
check("a fridge sighted where the closure puts it (4 looks, min_n): the closure is taken, the belief moves with it",
      taken == [False, False, False, True] and abs(nav.loc.pose()[1] - 3.4) < 1e-9 and not nav.loc.closure_pending(), (taken, nav.loc.pose()))
check("... and the check is a row with the numbers", len(checks) == 1 and checks[0]["status"] == "agrees" and checks[0]["taken"] is True
      and checks[0]["n"] == 4 and abs(checks[0]["median"][1]) < 1e-6 and checks[0]["agree_m"] == SIM.localisation.closure.agree_m
      and "; taken" in checks[0]["decision"]["reason"], checks)
check("... the memory follows (the move is the closure's)", nav.loc.memory_pending() and abs(nav.loc.memory_delta()[1] - 0.9) < 1e-9)

nav = closed_navigator((2.0, 2.5))
taken = look_at_fridge(nav, 4)
checks = [x for x in rows(nav) if x.get("event") == "closure_check"]
check("a fridge where the belief put it, not where the closure does (0.9 m off): the landmarks disagree, the closure stays held",
      taken == [False] * 4 and len(checks) == 1 and checks[0]["status"] == "disagrees" and checks[0]["taken"] is False
      and abs(checks[0]["median"][1] + 0.9) < 1e-6 and nav.loc.closure_pending() and abs(nav.loc.pose()[1] - 2.5) < 1e-9, (taken, checks))
check("... a later fix still comes in and is held: the duck does not freeze", fix_at(nav, 5, 1.0, 3.4) and nav.loc.last_fix["status"] == "held"
      and nav.localisation.pose() is not None)
fix_at(nav, 6, 1.0, 2.55)
check("... and mapd back at the belief's frame ends it, with nothing taken", not nav.loc.closure_pending() and nav.loc.last_fix["status"] == "taken")
nav = closed_navigator((2.0, 3.4))
nav.frames_on = False
check("without the frames (--no-frames) there is no closure to judge", look_at_fridge(nav, 4) == [False] * 4)

# ---- frames_parted: the existing event's moments ------------------------------------------------------------------------------------


class Parts:
    _watch_frames = Navigator._watch_frames

    def __init__(self, loc):
        self.rows, self.anoms, self.loc, self._parted_at, self.profile = [], [], loc, None, SIM
        self.localisation = types.SimpleNamespace(seen=None, frame_delta=loc.delta)

    def record(self, **row):
        self.rows.append(row)

    def anomaly(self, kind, summary, severity=None, **f):
        self.anoms.append((kind, severity, f))


def still():
    loc = Localizer(SIM.localisation.fix, max_jump_m=0.3, hold_n=None)
    loc.on_odom(NS, (1.0, 2.0, 0.0))
    loc.on_fix(NS, (1.0, 2.0, 0.0))
    return loc


pl = still()
pt = Parts(pl)
pt._watch_frames()
check("frames together: no anomaly", pt.anoms == [])
pl.on_odom(2 * NS, (1.0, 2.0, 0.0))
pl.on_fix(2 * NS, (1.0, 2.9, 0.0))
pt._watch_frames()
pt._watch_frames()
check("parted by a held fix: one anomaly, major, the margin past the 0.25 m", [(k, s) for k, s, _ in pt.anoms] == [("frames_parted", "major")]
      and abs(pt.anoms[0][2]["margin"] - 0.65) < 1e-9 and pt.anoms[0][2]["values"]["fix"] == "held", pt.anoms)
pl.on_odom(3 * NS, (1.0, 2.0, 0.0))
pl.on_fix(3 * NS, (1.0, 3.5, 0.0))
pt._watch_frames()
check("parted another 0.25 m further: said again, with the event", len(pt.anoms) == 2 and [r["event"] for r in pt.rows] == ["frames_parted"] * 2)
small = Parts(still())
small.loc.nudge(0.3, 0.0)
small._watch_frames()
check("the landmarks' offset parts the frames without a held fix: minor", [(k, s) for k, s, _ in small.anoms] == [("frames_parted", None)]
      and anom.KINDS["frames_parted"][2] == "minor")
small2 = Parts(still())
small2.loc.nudge(0.1, 0.0)
small2._watch_frames()
check("a 10 cm offset is not parting", small2.anoms == [])

# ---- the turn rules and the planner's refusals, through _go_to ------------------------------------------------------------------------


def squeezed(nearest_mm):
    """The duck facing remembered obstacle points 0.14 m ahead: 0.14 m of room by the map (the lethal ring is 0.12 m, so the
    start is free; a turn on the spot needs 0.15 m, an arc needs the floor 0.25 m ahead), the depth sensor reading nearest_mm."""
    nav = navigator(make_grid(100, 100), pose=(1.0, 2.5, 0.0), nearest_mm=nearest_mm)
    nav._remember([(x, y / 100) for x in (0.14, 0.28) for y in range(-30, 31, 3)], (1.0, 2.5, 0.0))     # (the second row makes the floor 0.25 m ahead lethal)
    return nav


def see(nav, points, ago=0.0):
    """A depth frame the navigator saw `ago` seconds ago: (x, y, kind) in map metres."""
    nav._returns.add(time.monotonic() - nav._t0 - ago, [[x, y, 0.0, k] for x, y, k in points])


AHEAD_FLOOR = [(1.3, 2.5, "f"), (1.5, 2.5, "f"), (1.8, 2.5, "f")]      # floor 0.3, 0.5 and 0.8 m ahead of the pose, all inside the 1.5 m look
nav = squeezed(600)
see(nav, AHEAD_FLOOR + [(1.0, 3.0, "o")])
out = nav.go_to((0.5, 2.5), 5.0)
r = anomalies(nav)
v = r[0]["values"] if r else {}
check("no room to turn by the map (0.14 m), the sensor returned floor 0.3 m that way and no obstacle: refused, room_disagrees said, info, "
      "with the bearing, the map's distance and the floor return",
      out["status"] == "refused" and out["why"].startswith("no room to turn") and [x["anomaly"] for x in r] == ["room_disagrees"]
      and r[0]["severity"] == "info" and v["bearing_deg"] == 0.0 and abs(v["map_m"] - 0.14) < 0.005 and v["floor_beyond_m"] == 0.3
      and v["obstacle_m"] is None and 0.1 < v["room_m"] < 0.15 and v["margin_unit"] == "m"
      and abs(r[0]["margin"] - (0.3 - (v["map_m"] - REAL.anomalies.room_disagrees_floor_slack_m))) < 1e-3, (out, r))
check("... the refusal itself is the same row as before: a decision, the room, the sensor's reading",
      any(x.get("event") == "refused" and x["why"] == "no room to turn" and x["nearest_mm"] == 600 and x["decision"]["rule"] == "refused" for x in rows(nav)))
check("... the side return (1.0, 3.0), 90 deg off the map's bearing, is not one of the returns that way", v.get("returns") == 3, v)
nav.go_to((0.5, 2.5), 5.0)
check("a second refusal at the same pose is not said again (one for a place), a refusal 0.3 m away is",
      len(anomalies(nav)) == 1 and nav._once_here("room_disagrees", (1.0, 2.5, 0.0)) is False and nav._once_here("room_disagrees", (1.3, 2.5, 0.0)) is True)

nav = squeezed(600)
see(nav, AHEAD_FLOOR + [(1.16, 2.5, "o")])
out = nav.go_to((0.5, 2.5), 5.0)
check("an obstacle return 0.16 m ahead (within 8 cm of the map's 0.14 m): the sensor agrees, refused, nothing said",
      out["status"] == "refused" and anomalies(nav) == [], (out, anomalies(nav)))
nav = squeezed(600)
see(nav, AHEAD_FLOOR + [(1.4, 2.5, "o")])
out = nav.go_to((0.5, 2.5), 5.0)
check("an obstacle return 0.4 m ahead, far past the map's 0.14 m, with floor beyond the map's: disagrees, said (a farther obstacle is no agreement)",
      out["status"] == "refused" and [x["anomaly"] for x in anomalies(nav)] == ["room_disagrees"], (out, anomalies(nav)))
for name, frames in (("no frame at all", []), ("only frames to the side, 90 deg off", [([(1.0, 3.0, "f"), (1.0, 3.4, "f")], 0.0)]),
                     ("only a frame 5 s old, outside the 4 s", [(AHEAD_FLOOR, 5.0)]),
                     ("floor only farther than the 1.5 m", [([(2.8, 2.5, "f")], 0.0)]),
                     ("only a below-the-floor return that way: neither floor nor obstacle (unclear)", [([(1.3, 2.5, "b")], 0.0)])):
    nav = squeezed(600)
    for pts, ago in frames:
        see(nav, pts, ago)
    out = nav.go_to((0.5, 2.5), 5.0)
    check(f"no verdict, nothing said ({name}): refused", out["status"] == "refused" and anomalies(nav) == [], (out, anomalies(nav)))
nav = squeezed(200)
see(nav, AHEAD_FLOOR)
out = nav.go_to((0.5, 2.5), 5.0)
check("the sensor's own nearest reading (200 mm here) is no part of the rule: floor returned beyond the map's obstacle says it at any reading",
      [x["anomaly"] for x in anomalies(nav)] == ["room_disagrees"], anomalies(nav))

# the check only raises an anomaly: the leg ends the same way and every other row is the same, with the sensor agreeing and disagreeing
quiet, loud = squeezed(600), squeezed(600)
see(quiet, AHEAD_FLOOR + [(1.16, 2.5, "o")])
see(loud, AHEAD_FLOOR)
oq, ol = quiet.go_to((0.5, 2.5), 5.0), loud.go_to((0.5, 2.5), 5.0)
keep = lambda nav: [{k: v for k, v in r.items() if k not in ("t", "time_s", "wall_ns")} for r in rows(nav) if r.get("event") != "anomaly"]  # noqa: E731
check("driving is unchanged: the same refusal and the same rows (the anomaly aside) whether the sensor agreed or disagreed",
      {k: v for k, v in oq.items() if k != "time_s"} == {k: v for k, v in ol.items() if k != "time_s"} and keep(quiet) == keep(loud)
      and len(anomalies(quiet)) == 0 and len(anomalies(loud)) == 1, (oq, ol))

# the returns' memory: bounded in time and in size, and moved with the memory
ret = anom.Returns(4.0)
for i in range(2000):
    ret.add(i * 0.01, [[1.0, 0.0, 0.0, "f"]] * 64)
check("the returns are bounded in size: 2000 frames 10 ms apart hold the frame cap, the newest last",
      len(ret._frames) == anom.RETURNS_MAX_FRAMES and ret._frames[-1][0] == 1999 * 0.01, len(ret._frames))
ret = anom.Returns(4.0)
for i in range(40):
    ret.add(i * 0.5, [[1.0, 0.0, 0.0, "f"]])
check("... and in time: frames 0.5 s apart over 20 s hold the last 4 s (9 frames)", len(ret._frames) == 9 and ret._frames[0][0] == 15.5, len(ret._frames))
ret = anom.Returns(4.0)
ret.add(1.0, [[1.0, 0.0, 0.0, "o"]])
ret.add(2.0, [[2.0, 0.0, 0.0, "f"]])
check("the returns of the window only, [t - 4, t]: older and later ones are not read", [len(ret.last(t)) for t in (0.5, 1.0, 2.0, 5.0, 5.1)] == [0, 1, 2, 2, 1])
ret.move(lambda p: (p[0], p[1] + 1.0))
check("the returns move with the memory (the frame change), their kinds kept", ret.last(2.0) == [(1.0, 1.0, "o"), (2.0, 1.0, "f")], ret.last(2.0))
GRID = make_grid(100, 100, walls=[(1.0, 2.0, 1.0, 3.0)])
w = anom.nearest_obstacle((0.8, 2.5, 0.0), GRID, [], 0.6)
check("the map's nearest obstacle: a wall cell's centre 0.2 m away; a remembered point nearer wins; none inside the radius is None",
      w is not None and abs(w[0] - 0.225) < 0.03 and anom.nearest_obstacle((0.8, 2.5, 0.0), GRID, [(0.85, 2.5)], 0.6)[1] == (0.85, 2.5)
      and anom.nearest_obstacle((3.0, 3.0, 0.0), GRID, [], 0.6) is None, w)

BOX = [(3.5, 3.5, 3.55, 4.5), (4.45, 3.5, 4.5, 4.5), (3.5, 3.5, 4.5, 3.55), (3.5, 4.45, 4.5, 4.5)]      # a closed box, 1 m inside
nav = navigator(make_grid(100, 100, walls=BOX), pose=(1.0, 1.0, 0.0))
out = nav.go_to((4.0, 4.0), 5.0)
r = anomalies(nav)
check("a goal in a walled box, the start in the open with nothing within 0.30 m: refused 'no path', and refused_unexplained said, minor",
      out["status"] == "refused" and out["why"] == "no path on the map" and [x["anomaly"] for x in r] == ["refused_unexplained"]
      and r[0]["severity"] == "minor" and r[0]["values"]["clear_m"] == 0.30 and r[0]["values"]["goal"] == [4.0, 4.0], (out, r))
nav = navigator(make_grid(100, 100, walls=BOX + [(0.9, 0.0, 0.95, 5.0)]), pose=(1.0, 1.0, 0.0))
out = nav.go_to((4.0, 4.0), 5.0)
check("the same with a wall 0.05 m from the pose: the map explains it, nothing said", out["status"] == "refused" and anomalies(nav) == [], (out, anomalies(nav)))
nav = navigator(make_grid(100, 100, walls=BOX), pose=(1.0, 1.0, 0.0))
out = nav.go_to((3.6, 4.0), 5.0)
check("a goal inside a wall's ring (lethal): refused, explained, nothing said", out["status"] == "refused" and anomalies(nav) == [], (out, anomalies(nav)))

nav = navigator(make_grid(100, 100), pose=(1.0, 2.5, 0.0))
t0 = time.monotonic()
out = nav.go_to((4.0, 2.5), 8.0)
r = anomalies(nav)
check("walking asked, the belief going nowhere for 3 s: the leg ends 'stuck', and the anomaly is said, major, with the window's numbers",
      out["status"] == "stalled" and out["why"].startswith("stuck") and [x["anomaly"] for x in r] == ["stuck"] and r[0]["severity"] == "major"
      and r[0]["values"]["moved_m"] < 0.05 and r[0]["values"]["seconds"] >= 2.7 and r[0]["margin"] > 0 and r[0]["duration_s"] >= 2.7
      and time.monotonic() - t0 < 6.0, (out, r))
stuck_row = next(x for x in rows(nav) if x.get("event") == "stuck")
check("... beside the stuck event with its decision, which is as before", stuck_row["decision"]["rule"] == "stuck")

# ---- the head, on the state stream -------------------------------------------------------------------------------------------------


def state(**by):
    angles = {n: SIM.anomalies.head_walk_pose.get(n, 0.0) for n in JOINTS}
    angles.update(by)
    return {"joints": [angles[n] for n in JOINTS]}


nav = navigator()
nav._head = anom.HeadWatch(POSE, OFF, 0.05)
nav._walking = True
nav._check_head(state())
time.sleep(0.1)
nav._check_head(state(head_pitch=POSE["head_pitch"] + 0.5))
time.sleep(0.1)
nav._check_head(state(head_pitch=POSE["head_pitch"] + 0.5))
nav._check_head(state(head_pitch=POSE["head_pitch"] + 0.5))
r = anomalies(nav)
check("head_off_walk: a head 0.5 rad off its walking pose for 0.1 s of walking: said once, minor, with the joint and the margin",
      [x["anomaly"] for x in r] == ["head_off_walk"] and r[0]["severity"] == "minor" and r[0]["values"]["joint"] == "head_pitch"
      and abs(r[0]["margin"] - (0.5 - OFF)) < 1e-6 and r[0]["values"]["margin_unit"] == "rad", r)
nav = navigator()
nav._head = anom.HeadWatch(POSE, OFF, 0.05)
nav._walking = False
for _ in range(3):
    nav._check_head(state(head_pitch=POSE["head_pitch"] + 0.5))
    time.sleep(0.07)
check("head_off_walk: the same head while the duck stands (a glance): nothing", anomalies(nav) == [])
nav._check_head({"joints": [0.0] * 14})
nav._check_head({})
check("head_off_walk: a state with another number of joints, or none: nothing, and no error", anomalies(nav) == [])

# ---- the streams' watchdog --------------------------------------------------------------------------------------------------------
nav = navigator()
nav._beat = {"state": anom.Staleness(0.15, time.monotonic()), "depth": anom.Staleness(0.15, time.monotonic())}
nav.range._thread = types.SimpleNamespace(is_alive=lambda: False)
run.WATCHDOG_S = 0.03
nav._start_watchdog()
t = nav._watchdog_thread
deadline = time.monotonic() + 0.6
while time.monotonic() < deadline:                     # four times the limit: the depth stream is said once, not at every look
    nav._beat["state"].seen(time.monotonic())          # the state stream keeps talking; the depth stream does not
    time.sleep(0.02)
nav._closing.set()
t.join(1.0)
r = anomalies(nav, "thread_failed")
check("thread_failed: the depth stream silent past its limit is said, once, major, with the silence, and whether its thread is alive",
      len(r) == 1 and r[0]["values"]["stream"] == "depth" and r[0]["severity"] == "major" and r[0]["values"]["thread_alive"] is False
      and r[0]["values"]["silent_s"] >= 0.15 and r[0]["margin"] > 0 and not t.is_alive(), (r, t.is_alive()))
check("... and the stream that kept talking was not said", all(x["values"]["stream"] != "state" for x in r))
run.WATCHDOG_S = 0.5

# ---- the camera and the relocaliser, through enable_objects -------------------------------------------------------------------------
from worldmodel.objects import load_kinds  # noqa: E402


class Camera:
    cfg = {"period_s": 0.02, "hfov_deg": 60.0, "range_m": 3.0}

    def __init__(self, error=None):
        self.error = error

    def detect(self):            # a CameraClient: no truth comes in (RFC-0021 step 6)
        if self.error:
            raise self.error
        return []


def watch_camera(camera, fixed=None, seconds=0.4):
    nav = navigator()
    nav.enable_objects(camera, load_kinds())
    if fixed is not None:
        nav.reloc = types.SimpleNamespace(observe=lambda found, pose, now: fixed)
    time.sleep(seconds)
    nav._closing.set()
    time.sleep(0.1)
    return nav


nav = watch_camera(Camera(RuntimeError("the camera is gone")))
r = anomalies(nav, "camera_failed")
check("camera_failed: the camera's look raising is said once (not every look), major, with the error",
      len(r) == 1 and r[0]["severity"] == "major" and "the camera is gone" in r[0]["summary"]
      and len([x for x in rows(nav) if x.get("event") == "camera_failed"]) == 1, r)
nav = watch_camera(Camera())
check("a camera that works says nothing", anomalies(nav) == [] and any(x.get("event") == "sighting" for x in rows(nav)))

refused = {"status": "refused", "why": "residuals disagree by 0.20 m (limit 0.12)", "n": 5, "median": [0.1, -0.2], "spread_m": 0.2, "landmarks": ["fridge_1"]}
nav = watch_camera(Camera(), refused, 0.1)
r = anomalies(nav, "reloc_refused")
check("reloc_refused: the landmark sightings disagreeing is said with the spread and the window; one for each refusal the relocaliser makes",
      len(r) >= 1 and r[0]["severity"] == "minor" and abs(r[0]["margin"] - 0.08) < 1e-9 and r[0]["values"]["n"] == 5 and r[0]["values"]["limit_m"] == 0.12
      and r[0]["values"]["window_s"] == 6.0 and len(r) == len([x for x in rows(nav) if x.get("event") == "relocalise"]), len(r))
nav = watch_camera(Camera(), {"status": "corrected", "dx": 0.1, "dy": 0.0, "n": 5, "median": [0.1, 0.0], "spread_m": 0.05, "landmarks": ["f"]}, 0.1)
check("a correction is not a refusal: nothing said", anomalies(nav) == [] and any(x.get("event") == "relocalise" for x in rows(nav)))

# ---- the explorer's refusal burst -------------------------------------------------------------------------------------------------------
log = []
fake = types.SimpleNamespace(anomaly=lambda kind, summary, severity=None, **f: log.append((kind, summary, f)), on_move=None)
ex = explore_run.Explorer(fake, None)
refused_leg = {"status": "refused", "why": "no room to turn (0.10 m to an obstacle, 1.0 m to a drop)"}
for k in range(5):
    ex.watch_burst(refused_leg, (1.0, 1.0 + 0.01 * k, 0.0), k + 1)
check("refusal_burst: refusals 1-5 at one pose: said once, at the third, with the reason and the count", len(log) == 1 and log[0][0] == "refusal_burst"
      and log[0][2]["values"]["refusals"] == 3 and "no room to turn" in log[0][1] and log[0][2]["margin"] == 0, log)
ex.watch_burst({"status": "reached"}, (1.0, 1.0, 0.0), 6)
for k in range(3):
    ex.watch_burst(refused_leg, (2.0, 1.0, 0.0), 7 + k)
check("a leg reached ends the streak: three more refusals say it again", len(log) == 2)
import inspect  # noqa: E402

check("the explorer's run loop hands each leg's outcome to the burst watch (a source check: the loop itself needs the simulator)",
      "self.watch_burst(out, pose, legs)" in inspect.getsource(explore_run.Explorer.run))
check("the navigator starts its watchdog when it is built (a source check: its constructor opens the sockets)",
      "self._start_watchdog()" in inspect.getsource(Navigator.__init__))
ex = explore_run.Explorer(fake, None)
log.clear()
for k in range(6):
    ex.watch_burst(refused_leg, (1.0 + 0.3 * k, 1.0, 0.0), k)
check("refusals each 0.3 m from the last (the duck moving between): never a burst", log == [], log)

# ---- the lease ---------------------------------------------------------------------------------------------------------------------------
nav = navigator()
nav.robot.fail = LeaseLost("robot.move: the lease ended", "lease_ended", "expired")
try:
    nav.move(Twist(0.2, 0.0))
    check("a command the gate refuses raises as before", False)
except LeaseLost:
    check("a command the gate refuses raises as before", True)
try:
    nav.move(Twist())
except LeaseLost:
    pass
r = anomalies(nav)
check("lease_lost: an expired lease is said once (the stop that follows is refused too, and not said again), major",
      [x["anomaly"] for x in r] == ["lease_lost"] and r[0]["severity"] == "major" and r[0]["values"]["reason"] == "expired", r)
nav = navigator()
nav.robot.fail = LeaseLost("robot.move: stopped", "lease_ended", "stopped_by_mobile")
try:
    nav.move(Twist(0.2, 0.0))
except LeaseLost:
    pass
r = anomalies(nav)
check("stop_latched: a STOP from someone (stopped_by ...) is its own anomaly, info, with who", [x["anomaly"] for x in r] == ["stop_latched"]
      and r[0]["severity"] == "info" and "stopped by mobile" in r[0]["summary"], r)
nav = navigator()
nav.lease_ended(LeaseLost("held", "held", None, "the app"))
check("another client holding the robot: the lease was lost (the code, the holder)", [(x["anomaly"], x["values"]["holder"]) for x in anomalies(nav)] == [("lease_lost", "the app")])


class Goal:
    """What GoalRun._work reads: a goal whose work ends in the gate's refusal."""
    kind, broken = "point", None
    cancelled = threading.Event()

    def __init__(self, exc):
        self.nav, self.finished, self.exc = types.SimpleNamespace(lease_ended=lambda e: self.said.append(e)), [], exc
        self.said = []

    def _do_point(self):
        raise self.exc

    def _finish(self, state, reason, result):
        self.finished.append((state, reason))


g = Goal(LeaseLost("x", "lease_ended", "taken_over_by_mobile"))
server.GoalRun._work(g)
check("the navigator server: a lease lost mid-goal reaches the navigator (once said there), and the goal ends 'interrupted' as before",
      len(g.said) == 1 and g.said[0].reason == "taken_over_by_mobile" and g.finished[0][0] == "interrupted", (g.said, g.finished))

# ---- additions only: the navigator's own rows are the same with an anomaly in the middle ----------------------------------------------------
a, b = navigator(), navigator()
for nav, say in ((a, False), (b, True)):
    nav.record(event="plan", pose=[1.0, 2.5, 0.0])
    if say:
        nav.anomaly("stuck", "x")
    nav.record(event="reached", pose=[1.0, 2.5, 0.0])
strip = lambda nav: [{k: v for k, v in r.items() if k not in ("t", "wall_ns")} for r in rows(nav) if r.get("event") != "anomaly"]  # noqa: E731
check("an anomaly between two rows leaves them as they were", strip(a) == strip(b) and len(rows(b)) == len(rows(a)) + 1)

# ---- every limit is the profile's (the operator, 2026-11-19: accepted as they are, and configurable) -----------------------------------
an = SIM.anomalies
check("the duck's profile holds the accepted limits",
      (an.refusal_burst_n, an.refusal_burst_moved_m, an.same_place_moved_m, an.same_place_gap_s, an.room_disagrees_window_s,
       an.room_disagrees_look_deg, an.room_disagrees_near_m, an.room_disagrees_see_m, an.room_disagrees_agree_m,
       an.room_disagrees_floor_slack_m, an.head_off_walk_rad, an.head_off_walk_s, an.unexplained_clear_m, an.state_stale_s, an.depth_stale_s)
      == (3, 0.10, 0.10, 5.0, 4.0, 20.0, 0.6, 1.5, 0.08, 0.02, 0.30, 1.0, 0.30, 3.0, 3.0))
lim = types.SimpleNamespace(refusal_burst_n=5, refusal_burst_moved_m=0.2, same_place_moved_m=0.5, same_place_gap_s=9.0)
ex5 = explore_run.Explorer(types.SimpleNamespace(anomaly=lambda *a, **f: None, on_move=None, anomalies=lim), None)
check("the explorer's burst takes its limits from the profile", (ex5.burst.n, ex5.burst.moved_m) == (5, 0.2), (ex5.burst.n, ex5.burst.moved_m))
b.__dict__.pop("_gates", None)
b.anomalies = lim
b._once_here("room_disagrees", (0.0, 0.0, 0.0))
g = b._gates["room_disagrees"]
check("the once-per-place rule takes its limits from the profile", (g.moved_m, g.gap_s) == (0.5, 9.0), (g.moved_m, g.gap_s))

print("ANOMALY", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
