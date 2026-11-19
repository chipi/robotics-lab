"""Drive the duck to goals: the navigator's loop around the pure functions (RFC-0002 §3.8).

    uv run duck-go 1.5 0.5            # one goal in map coordinates, simulator sockets
    uv run duck-go 1.5 0.5 --log run.jsonl
    uv run duck-go 1.5 0.5 --miniview-data /work/robotics-lab/data   # also written as a live Observatory run (ADR-0014)

With an Observatory data folder (--miniview-data or OBSERVATORY_DATA) the run is also written in format 2, while it runs: that run
is the record, with every depth frame and the IMU (`duck-replay` checks it is complete); ticks.jsonl is kept during the
transition, for the importer and the older tools.

Loop at 10 Hz: pose = map ← odom (frames.py) on the latest odometry; twist from follow.step; robot.move
with every tick (the deadman wants one every 100 ms); replan on a fresh map.grid every few seconds.
Reflex on each depth frame: an obstacle in the duck's corridor within the sensor's reflex_ahead_m while walking → stop, survey
(the stop puts the obstacle in the map), replan. Every stop ends with an explicit zero move: robotd
keeps the last request after its deadman trips, and mapd then never sees a stop (PHASE0-SPIKE.md §3).

The robot's numbers are its profile's (robots/duck/profile.json, RFC-0020), read by Navigator.configure and kept as attributes;
what is left in this module is the navigator's own policy: the tick, the replan and stall periods, the obstacle memory's
spacing, the survey's wait. The comments on the numbers below say why each has the value the duck's profile gives it.
"""

import argparse
import collections
import json
import math
import socket
import sys
import threading
import time
from pathlib import Path

from duck_lab.nav.client import SIM, LeaseLost, Rpc, StateStream, odom_pose
from duck_lab import plugins
from duck_lab.plugins.tof8x8 import FrameView     # (the depth frame as derived: re-exported for the tools that read it)
from duck_lab.nav.follow import FollowState, Twist, step, wrap
from duck_lab.nav import anomaly as anom, recovery
from duck_lab.nav.decision import decision
from duck_lab.nav.frames import move_xy
from duck_lab.nav.runlog import JOINTS, RunLog, add_args, open_from_args
from duck_lab.nav.stuck import StuckWatch
from duck_lab.nav.side_drops import (SuspectMemory, continuation, continues, edge_from_glance, head_settled, in_the_way,
                                     look_targets)
from duck_lab.profile import load as load_profile
from worldmodel.objects import Limits
from worldmodel.relocalise import Relocaliser
from worldmodel.semantic_map import SemanticMap
from duck_lab.nav.grid import FREE_COST, LETHAL_COST, CostGrid, EmptyMap, clearance, keep_current, nearest_free, path_length, plan, thin

TICK_S = 0.1
REPLAN_S = 3.0
# A leg whose planned path has not got PROGRESS_M shorter in NO_PROGRESS_S ends as "stalled": trial 6
# spent three 60 s timeouts following an unseen wall in search of a door that was not there. Path
# length, not straight-line distance, so a detour that first leads away is still progress.
PROGRESS_M = 0.10
NO_PROGRESS_S = 15.0


class Progress:
    """The stall rule's bookkeeping. `known` counts what the map remembers of drops: when it grows, the best path length so
    far was measured on a map without them and progress counts again from the path as it is (challenge 11 seed 5: a pit
    found ahead made the way 4.15 m against a 2.54 m best, and the leg stalled while walking round it)."""

    def __init__(self, start: float):
        self.best, self.at, self.known = math.inf, start, None

    def update(self, left: float, now: float, known: int) -> bool:
        """True: stalled."""
        if known != self.known and self.known is not None:
            self.best, self.at = left, now
        elif left < self.best - PROGRESS_M:
            self.best, self.at = left, now
        elif now - self.at > NO_PROGRESS_S:
            return True
        self.known = known
        return False

    def pause(self, seconds: float) -> None:
        """Time spent standing to look is not time without progress (exploring b3 r1 leg 4: four looks before stepping,
        all floor, ~3 s each, and the leg stalled 0.2 m from its target)."""
        self.at += seconds


FOLLOW_SPACING_M = 0.10
# The depth reflex: an obstacle return inside the corridor the duck sweeps (its 8.3 cm radius and 4 cm)
# within REFLEX_AHEAD_M of the trunk stops it; so does any return at all within EMERGENCY_MM of the
# sensor. It used to stop for the nearest return in the central columns within 250 mm, wherever it was:
# phase 1 run 16 stopped eight times for a door frame it was passing with room to spare.
# (profile sensors.tof8x8: reflex_ahead_m 0.30, emergency_mm 150, and reflex_margin_m 0.04 beyond footprint.radius_m 0.083)
# A drop this close ahead (horizontal) stops the duck. 0.60, not 0.45: the duck then has to turn round
# where it stopped, and a turn on the spot drifts (exploration trial 5: 26 cm over 4.3 rad).
# (profile error_budget.cliff_stop_m)
# ... once seen in this many consecutive depth frames (15 Hz): a single frame read against a state a
# few tens of ms apart, mid-turn, put a "drop" on flat corridor floor (run 7, goal 15). A staircase
# does not vanish between frames; 3 frames is 0.2 s, ~6 cm of walking against the 45 cm stop distance.
DROP_FRAMES = 3
# (profile localisation.fix: jump_m 0.3, a mapd fix that would move the belief more than this is held (frames.Localizer); the 33
# recorded exploring runs hold one such jump (explore-b10a-r1: 0.9 m in one tick, belief error 0.2 -> 0.7 m); record_m 0.1, every
# fix that moves the belief more than this is recorded with its raw pose and paired odometry; loop_credit_s 3.0, a loop closure
# mapd believed (its counter stepped, it is not lost) lets a large fix through for this long)
PARTED_REPORT_M = 0.25   # a "frames_parted" is said again when the frames part this much further
SNAPSHOT_S, SNAPSHOT_MOVED_M = 2.0, 0.05    # the objects re-recorded every 2 s while any moved more than 5 cm
LOW_FRAMES, LOW_CELL_M = 3, 0.05    # a low-band cell is an obstacle once this many frames saw it (sim/probes/low_persistence.py)
# After a cliff stop the duck looks along the edge, looking.along_m past each end of what it saw (side_drops.look_targets);
# where the drop goes on there, or the look saw nothing, the hole is taken to go on looking.continue_m past the seen end.
# The obstacle layer: what the depth sensor sees this close, every tick, joins the memory, and a new
# point near the remaining path replans at once. mapd maps only at stops, so a face first seen while
# walking (the cabinet's side, passed while turning into the office: run 6's touches) was not on the map.
LAYER_M = 0.6
LAYER_SPACING_M = 0.03
# A turn on the spot shifts the duck (phase 0: 8 cm over a full turn; exploration trial 5: 26 cm over
# 4.3 rad, toward the stairs; phase 1 run 12: a contact beside the office cabinet), and the duck does
# not walk backwards (-0.15 and -0.3 m/s: no motion; -0.4: 87 cm with a 51 deg swing). So it turns on
# the spot only with room for that drift: locomotion.pivot.drop_clear_m (0.30) from any remembered drop and pivot_obstacle_m (the
# lethal ring plus obstacle_margin_m: the 12 cm lethal zone and 5 cm) from any obstacle. Otherwise it turns while walking slowly
# (an arc), and only onto clear floor: locomotion.arc.clear_mm by the depth sensor (300: a 0.2 m radius arc, 0.2 m/s at 1 rad/s,
# reaches ~0.2 m ahead, + the 8.3 cm footprint), no lethal cell arc.ahead_m (0.25) ahead and no remembered drop within
# cliff_stop_m in front. No room for either: the leg is refused.
# The floor a turn while walking sweeps, for drops: the arc's reach (arc.reach_m 0.45: arc.ahead_m and the footprint's 0.083 m and
# the following's error, rounded up) from just outside the heading (arc.outer_deg 20) to well round the side it turns to
# (arc.inner_deg 120).
# No room for either: a pivot is still allowed while the clearance stays above pivot.tight_m (0.15; was 0.11 (footprint + 2.5 cm);
# + the creep a pivot leaves (b7 r2, the operator 2026-11-18)), rechecked every tick, once per spot (pivot.tight_spot_m 0.10,
# tight_gap_s 0.5: Navigator._tight_allowed). Below it the duck stands and the leg is refused.
# error_budget.beyond_m: a drop's hole continues behind its edge.
FLOOR_CELL_M = 0.05
# Drop rings by what is known of the drop (docs/wip/SIDE-DROPS.md; the advisor's split, the operator's choice 2026-11-17).
# Each is the turn gate of its kind plus the following's (~3 cm) and the belief's (~2.5 cm) error, so the duck can turn
# on the spot wherever the planner may put it; each gate less the pivot's drift (max 7.9 cm over 87 pivots on 2026-11-17,
# sim/probes/turn_drift.py) keeps the judge's 0.15 m and the belief. A cliff stop's rough points: error_budget.drop_lethal_m (0.35)
# and pivot.drop_clear_m (0.30). A drop edge a glance measured (-14/+6.4 cm aside, -18/+3 cm ahead, 54 glances): pivot.edge_clear_m
# 0.26 and edge_lethal_m 0.32 round it, which also keeps a path held at it out of the cliff check's 0.25 m corridor (0.305 with the
# errors). 0.22 put such a path inside that corridor: the duck was stopped for the edge it had measured, and stood where
# it was not allowed to turn. A suspected drop (side_drops.SuspectMemory) costs what it becomes when a glance confirms it
# (a smaller ring, 0.25, let the duck walk where the confirmed ring then put it inside, unable to turn: challenge 11 seed
# 1); one within error_budget.confirm_m (0.9) triggers that glance, and a false one that closes the way is looked at, not refused for.
# The suspect rings are the edge's (edge_lethal_m, edge_inflate_m).
# a goal inside a drop's ring is held off at the nearest place out of it this near (error_budget.hold_off_m 0.20); farther, it is
# across the drop (challenges 8 and 9: refused). Under the judge's reached_m 0.25 with room for the following.
# hold_detour 1.25: and only on this side of the drop: the way there no longer than this times the straight line, + 0.3 m
# glanced_m 0.4: a suspicion this near one already looked at is not looked at again
# A suspicion this near a measured edge (absorb_m 0.15) is that drop going on, confirmed without a look (challenge 10 seed 1
# looked 7 times walking along one ledge); new suspicions join one by one as the duck walks, so the drop grows along its length.
# looking.floor_z_m -0.116: the floor in the trunk frame (stand height), where the glance aims; settle_frames 5 and yaw_tol_deg
# 3.0: the sensor's yaw held this still over this many frames: the head is there; max_s, collect_s, back_s; walk_command:
# robotd's default head command: how the duck walks when nothing moves the head.
FLOOR_NEAR_M = 0.10      # an explorer's target needs floor seen by the depth sensor this close   # and along it, past what one stop saw (longer would close the gaps beside the stairs)
SURVEY_TIMEOUT_S = 8.0
STATE_KEEP = 40          # robot states held to pair depth frames with: two seconds at 20 Hz (autod holds the last second)
WATCHDOG_S = 0.5         # how often the streams' watchdog looks (the limits are the profile's anomalies.state_stale_s, depth_stale_s)




class Body:
    """The simulator's ground truth (the body server); absent on a real duck."""

    def __init__(self, port: int = 7801):
        self._f = socket.create_connection(("127.0.0.1", port)).makefile("rw")
        self._f.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n")
        self._f.flush()
        self._f.readline()
        # one request and its reply at a time: the record (main thread), an exploring run's truth guard and the
        # simulated camera (RFC-0016) all read the truth from their own threads over this one socket
        self._lock = threading.Lock()

    def pose(self) -> tuple:
        with self._lock:
            self._f.write('{"op":"read"}\n')
            self._f.flush()
            r = json.loads(self._f.readline())
        w, x, y, z = r["imu"]["quat"]
        self.height = r["trunk"][2]
        self.quat = (w, x, y, z)          # the trunk's whole orientation, for the run's full truth pose (ADR-0016)
        return r["trunk"][0], r["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def load_scale(variant: str | None) -> float:
    """The robot's odometry scale in an environment (the profile's localisation.odometry.scale), 1.0 for the real duck (None)."""
    return float(load_profile(variant).localisation.odometry.scale)


def load_tof(variant: str | None) -> dict:
    """The robot's depth sensor as mounted in an environment (the profile's sensors.tof8x8.mount): {pitch_offset_deg, range_kind};
    mapd's (3 degrees, along the optical axis) for the real duck (None)."""
    mount = load_profile(variant).sensors.tof8x8.mount
    return {"pitch_offset_deg": float(mount.pitch_offset_deg), "range_kind": mount.range_kind}


def load_pivot_vx(variant: str | None) -> float:
    """The forward speed a turn on the spot is sent with in an environment (the profile's locomotion.pivot.vx_mps); 0 for the
    real duck (None). The simulator's pivot creeps forward, the real duck's backward by upstream (RFC-0008 §4)."""
    return float(load_profile(variant).locomotion.pivot.vx_mps)


class Navigator:
    runlog = None            # a RunLog (ADR-0014) when the run is also written as an Observatory run
    watch = None             # a test's truth check (ADR-0015): called with each row that has truth; a row it returns is recorded
    speed_cap = None         # a goal's guardrails (RFC-0014 §3.4.8): see __init__; class defaults for a navigator built without it
    keepout = ()
    on_decision = None
    frames_on = True         # (class defaults: a test builds a navigator without __init__)
    fault_grid = False
    on_move = None
    _parted_at = None
    _walking = False         # the last command asked for a forward walk (the head watch reads it on the state thread)
    _lease_said = False
    anomalies = _head = _beat = None      # the profile's anomalies block, the head watch and the streams' watchdog state (configure)

    def __init__(self, sim_dir: Path = SIM, truth: bool = True, log: Path | None = None,
                 calibration: str | None = "sim", runlog: RunLog | None = None,
                 robot_sock: Path | None = None, client: str | None = None, profile=None):
        # `calibration` names the environment ("sim", or None for the real duck); the profile is the duck's, in that environment
        # (robots/duck/profile.json), unless one is given.
        # The robot's socket is a setting (RFC-0017 §5 step 3): robotd's own, or a gate's (duck-gate). With a `client` name
        # this navigator speaks to a gate: hello {client}, then it takes the lease before anything else, and a gate that
        # holds the robot for another client refuses it here (LeaseLost), before a run, a thread or a map exists.
        self.client = client
        self.robot_sock = Path(robot_sock) if robot_sock else sim_dir / "duck-a.sock"
        self.robot = Rpc(self.robot_sock, client=client)
        if client:
            try:
                self.robot.call("gate.acquire")
            except Exception:
                self.robot.close()
                raise
        # Odometry, mapd's poses and mapd's grid all come from robotd's odometry; one scale corrects
        # all three, so the map and the pose stay in the same (true) metres. The map's origin is its
        # first stop, so scaling about it keeps the duck where it is.
        self.configure(profile if profile is not None else load_profile(calibration))
        self._t0 = time.monotonic()
        self.runlog = runlog
        self._sid = runlog.new_session() if runlog else None
        self._states = collections.deque(maxlen=STATE_KEEP)     # (t_ns, robot state), newest last: what a frame is paired with
        self._fv = None          # the newest depth frame, paired and derived (FrameView)
        self.sense = {}          # what go_to decides on this tick (room_m, turning), for the signals; empty outside go_to
        self._logging_failed = False

        self.mapd = Rpc(sim_dir / "duck-a-map.sock")
        self.localisation.bind(self.mapd)
        self.state = StateStream(self.robot_sock, hz=20, on_state=self._on_state, client=client)

        self.body = Body() if truth else None
        self._log = open(log, "a") if log else None
        self.blocked = []    # what the depth sensor saw as obstacles, in map metres
        self._seen = set()   # the memory's points, on a LAYER_SPACING_M grid (no duplicates)
        self._low = {}       # low-band cells (LOW_CELL_M) -> the frames that saw them, until LOW_FRAMES remember them
        self._drop_streak = 0
        self._drop_frame = None
        self._depth = None       # the newest depth frame's returns in map metres, for the next tick record
        self._block = None       # how far ahead an obstacle sits in the duck's corridor (newest frame)
        # Floor the depth sensor itself has seen, as FLOOR_CELL_M cells: mapd draws a stairwell as free
        # floor (upstream #599), and exploration trial 10 took a target inside one.
        self.floor_seen = set()
        # Drops beside the way (docs/wip/SIDE-DROPS.md): suspected from the forward sensor's below-floor returns, then
        # confirmed (into drops) or cleared by a glance; the places already looked at.
        sd = self.profile.sensors.tof8x8.side_drops
        self.suspects = SuspectMemory(sd.suspect_frames, sd.suspect_ratio, sd.clear_m)
        self.glanced = []
        self.step_looked = []    # spots looked at before stepping on them (step_check), not looked at again
        self._map_raw = None     # mapd's last grid (scaled), for the world record
        self.fix_fault = None    # (t_s, dx, dy): from t_s on, mapd's raw pose is shifted by (dx, dy) — a test of the fix gate and the landmarks
        self.fault_grid = False  # ... and its grid too: mapd's frame jumped as a whole, as its pose and grid come from one graph
        self.frames_on = True    # mapd's grid is read in the belief's frame and the memory moves with it (off: the run before, a test)
        self._moves = []         # the frame changes the memory has been moved by, in order (a leg's goal follows them)
        self.on_move = None      # called with each: the explorer's own lists
        self._parted_at = None   # the frames' delta when "frames_parted" was last said, None while they are together
        self._world_key = None
        self.range.on_frame = self._on_frame
        self.range.open(sim_dir / "duck-a-tof.sock")
        self.drops = []      # where the cliff check found no floor, in map metres
        self.edges = []      # drop edges a glance measured (and the hole beyond them), in map metres: a smaller ring
        self.abort = None    # set by a watchdog (a test's truth guard): stop now, with this reason
        # a goal's guardrails (RFC-0014 §3.4.8), set by whoever runs the goal: a forward speed cap (m/s), the points of the
        # no-go areas (map metres: obstacles for the planner, so a path never enters), and a listener for every decision
        self.speed_cap = None
        self.keepout = []
        self.on_decision = None
        # objects (RFC-0016): off unless a camera is given (enable_objects); the challenge course runs without
        self.semantic = None
        self.room = None         # the area type the objects suggest (a guess; was "room")
        self.area, self.area_agrees = None, None    # the operator's area the pose is in, and whether the guess agrees
        self._sem_lock = threading.Lock()
        self._closing = threading.Event()
        self._start_watchdog()
        # the sensor's mounting as this run used it, so a replay applies the same (duck-replay reads it)
        self.record(event="calibration", tof=self.tof_cal, odom_scale=self.scale, pivot_vx_mps=self.locomotion.pivot_vx,
                    profile={"id": self.profile.id, "variant": self.profile.variant, "plugins": dict(self.profile.plugins.data)})

    def configure(self, profile) -> None:
        """The robot's numbers, from its profile (RFC-0020): everything the navigator decides with that is the robot's and not its
        own policy. Derived values are computed the way the constants were, so they are the same to the last bit."""
        self.profile = profile
        loco, fp, eb, look = profile.locomotion, profile.footprint, profile.error_budget, profile.looking
        tof, fix = profile.sensors.tof8x8, profile.localisation.fix
        self.loco, self.fp = loco, fp
        self.tof_cal = {"pitch_offset_deg": float(tof.mount.pitch_offset_deg), "range_kind": tof.mount.range_kind}
        self.cliff_stop_m = eb.cliff_stop_m
        self.plugins = plugins.load(profile)
        self.locomotion = lw = self.plugins["locomotion"]
        self.range = rs = self.plugins["range_sensing"]
        self.localisation = mp = self.plugins["localisation"]
        self.looking = self.plugins["looking"]
        lw.bind(getattr(self, "robot", None))
        self.looking.bind(getattr(self, "robot", None))
        self.loc = mp.belief          # the belief the localisation plugin owns: the frames logic below is shared
        self.scale = mp.scale
        self.reflex_ahead_m, self.reflex_half_w_m, self.emergency_mm = rs.reflex_ahead_m, rs.reflex_half_w_m, rs.emergency_mm
        # what the navigator itself decides with, and records, of the locomotion plugin's gates
        self.pivot_drop_m, self.pivot_edge_m, self.pivot_obstacle_m = lw.pivot_drop_m, lw.pivot_edge_m, lw.pivot_obstacle_m
        self.tight_pivot_m, self.arc_clear_mm = lw.tight_pivot_m, lw.arc.clear_mm
        self.drop_lethal_m, self.drop_inflate_m = eb.drop_lethal_m, eb.drop_inflate_m
        self.edge_lethal_m, self.edge_inflate_m = eb.edge_lethal_m, eb.edge_inflate_m
        self.confirm_m, self.hold_off_m, self.hold_detour = eb.confirm_m, eb.hold_off_m, eb.hold_detour
        self.glanced_m, self.absorb_m, self.beyond_m = eb.glanced_m, eb.absorb_m, tuple(eb.beyond_m)
        self.look_along_m, self.continue_m = look.along_m, look.continue_m
        self.limits = Limits(walk_over_m=loco.step_over_m, overhead_m=fp.overhead_clear_m, stand_m=fp.standoff_m,
                             assoc_m=eb.assoc_m, unique_m=eb.unique_m)
        # the robot-tagged anomalies' numbers (RFC-0019 step 1); a profile without the block raises none that need them
        an = profile.get("anomalies")
        self.anomalies = profile.anomalies if an else None
        if an:
            self._head = anom.HeadWatch(an["head_walk_pose"], an["head_off_walk_rad"], an["head_off_walk_s"])
            now = time.monotonic()
            self._beat = {"state": anom.Staleness(an["state_stale_s"], now), "depth": anom.Staleness(an["depth_stale_s"], now)}

    def _scaled(self, pose: tuple) -> tuple:
        return pose[0] * self.scale, pose[1] * self.scale, pose[2]

    def move(self, tw: Twist, **extra) -> None:
        """Send a command and log it with the pose: every command, so surveys, survey turns and the
        waits after a stop are in the log too (explore12 had events there but no poses)."""
        self.sync_memory()
        vx =tw.vx if self.speed_cap is None else max(-self.speed_cap, min(self.speed_cap, tw.vx))
        self._walking = tw.vx > 0.05
        try:
            self.locomotion.command(vx, tw.vyaw)
        except LeaseLost as exc:
            self.lease_ended(exc)
            raise
        pose = self.localisation.pose()
        if pose is None:
            return
        self.record(pose=[round(v, 4) for v in pose], vx=tw.vx, vyaw=round(tw.vyaw, 3), tilt=self._tilt(),
                    **extra, **({"depth": self._depth} if self._depth else {}))
        self._depth = None

    def fix(self) -> bool:
        """A fix from the localisation source, applied to the belief; then the memory follows the belief's frame."""
        if not self.localisation.fix(self.record, self.frames_on, self.fix_fault, self._t0):
            return False
        self.sync_memory()
        self._watch_frames()
        self._watch_fix()
        return True

    def sync_memory(self) -> None:
        """The belief's frame moved (a fix taken after a jump, a landmarks' nudge): everything the navigator placed with the
        belief moves with it (move_memory). Called from the navigator's own thread, before it uses the memory."""
        if not self.frames_on:
            return
        d = self.loc.memory_delta()
        if d is not None:
            self.move_memory(d)

    def move_memory(self, d: tuple) -> None:
        """Re-place the navigator's memory by the frame change d (x, y, yaw; new <- old): the obstacle points, the low-band
        cells, the drops and the measured edges, what was glanced at, the floor the sensor saw, the suspected drops, the
        objects, the tight-pivot spots, and the explorer's frontier lists (on_move). A rigid move of all of it: the memory
        has no age (a loop closure's true correction is smaller for what was placed long ago)."""
        def mv(p):
            return move_xy(d, p)
        self.blocked = [mv(p) for p in self.blocked]
        self._seen = {(round(q[0] / LAYER_SPACING_M), round(q[1] / LAYER_SPACING_M)) for q in self.blocked}
        low = {}
        for (cx, cy), frames in list(self._low.items()):
            q = mv((cx * LOW_CELL_M, cy * LOW_CELL_M))
            low.setdefault((round(q[0] / LOW_CELL_M), round(q[1] / LOW_CELL_M)), set()).update(frames)
        self._low = low
        self.drops = [mv(p) for p in self.drops]
        self.edges = [mv(p) for p in self.edges]
        self.glanced = [mv(p) for p in self.glanced]
        self.step_looked = [mv(p) for p in self.step_looked]
        for spot in self.locomotion.tight_spots:
            spot[0] = mv(spot[0])
        self.floor_seen = {(round(q[0] / FLOOR_CELL_M), round(q[1] / FLOOR_CELL_M))
                           for q in (mv((cx * FLOOR_CELL_M, cy * FLOOR_CELL_M)) for cx, cy in list(self.floor_seen))}
        self.suspects.move(d)
        if self.semantic is not None:
            with self._sem_lock:
                self.semantic.move(d)
        self._moves.append(d)
        if self.on_move is not None:
            self.on_move(d)
        self.record(event="memory_moved", delta=[round(d[0], 4), round(d[1], 4), round(d[2], 4)], blocked=len(self.blocked),
                    drops=len(self.drops) + len(self.edges), floor_cells=len(self.floor_seen),
                    objects=len(self.semantic.objects) if self.semantic is not None else 0, pose=self.localisation.pose(),
                    decision=decision("memory_moved", f"the belief's frame moved {math.hypot(d[0], d[1]):.2f} m, "
                                      f"{math.degrees(d[2]):.1f} deg: the memory moved with it", moves=len(self._moves)))

    def _watch_frames(self) -> None:
        """The belief's frame against mapd's (RFC-0019's frames_parted): said when they part (a held jump, a landmarks'
        offset), again when they part further, and when they are together again."""
        d = self.localisation.frame_delta()
        if d is None:
            return
        shown = [round(d[0], 4), round(d[1], 4), round(d[2], 4)]
        if self.loc.parted():
            last = self._parted_at
            if last is None or math.dist(last[:2], d[:2]) > PARTED_REPORT_M:
                self._parted_at = d
                self.record(event="frames_parted", delta=shown, mapd=self.localisation.seen,
                            fix=(self.loc.last_fix or {}).get("status"), offset=[round(v, 3) for v in self.loc.offset],
                            decision=decision("frames_parted", f"the belief's frame is {math.hypot(d[0], d[1]):.2f} m, "
                                              f"{math.degrees(d[2]):.1f} deg from mapd's", delta=shown))
                held = (self.loc.last_fix or {}).get("status") == "held"
                fx = self.profile.localisation.fix
                margin, unit = anom.over(math.hypot(d[0], d[1]), fx.parted_m, abs(d[2]), fx.parted_rad)
                self.anomaly("frames_parted", f"the belief's frame is {math.hypot(d[0], d[1]):.2f} m, {math.degrees(d[2]):.1f} deg from "
                             f"mapd's" + ("; a held fix" if held else ""), "major" if held else None, margin=margin,
                             values={"delta": shown, "offset": [round(v, 3) for v in self.loc.offset], "fix": (self.loc.last_fix or {}).get("status"),
                                     "parted_m": fx.parted_m, "parted_rad": fx.parted_rad, "margin_unit": unit})
        elif self._parted_at is not None:
            self._parted_at = None
            self.record(event="frames_joined", delta=shown,
                        decision=decision("frames_joined", "the belief's frame and mapd's are together again", delta=shown))

    # ---- anomalies (RFC-0019 §3.1: what the navigator itself notices; nav/anomaly.py has the record and the stateful rules) -------

    def anomaly(self, kind: str, summary: str, severity: str | None = None, **fields) -> None:
        """One robot-tagged anomaly, as an event of the run (source "robot"), with the belief's place when there is one: the
        simulator's truth is added by `record`, as to every row. It writes a row and changes nothing else (no decision, no state);
        a failure to write it is said on stderr and never stops the navigation."""
        try:
            loc = getattr(self, "localisation", None)
            self.record(**anom.record(kind, summary, severity, belief=loc.pose() if loc else None, **fields))
        except Exception as e:  # noqa: BLE001 - an observer must not stop the navigation
            print(f"anomaly {kind} not recorded: {type(e).__name__}: {e}", file=sys.stderr)

    def _once_here(self, kind: str, pose: tuple) -> bool:
        """False for an anomaly already said for this place (anomaly.PlaceGate): a refusal repeats for every target tried at one pose."""
        gates = self.__dict__.setdefault("_gates", {})
        return gates.setdefault(kind, anom.PlaceGate()).allow(time.monotonic(), pose)

    def _watch_fix(self) -> None:
        """fix_jump_held: every fix the gate held, none throttled (the `fix` event is: only the first few and every twentieth)."""
        f = self.loc.last_fix
        if not f or f["status"] != "held":
            return
        fx = self.profile.localisation.fix
        turn = abs(wrap(f["after"][2] - f["before"][2])) if f.get("before") else 0.0
        margin, unit = anom.over(f["moved_m"], fx.jump_m, turn, fx.jump_rad)
        seen = self.localisation.seen or {}
        self.anomaly("fix_jump_held", f"mapd's fix would move the belief {f['moved_m']:.2f} m and turn it {math.degrees(turn):.0f} deg; held",
                     margin=margin, mapd=f["raw"][:2],
                     values={"jump_m": f["moved_m"], "turn_deg": round(math.degrees(turn), 1), "limit_m": fx.jump_m, "limit_rad": fx.jump_rad,
                             "held_in_a_row": len(self.loc._held), "held_total": self.loc.rejected, "mapd_lost": seen.get("lost"),
                             "relocalizations": seen.get("relocalizations"), "margin_unit": unit},
                     evidence={"fix_t_ns": f["t_ns"], "odom_t_ns": f["odom_t_ns"], "raw": f["raw"], "before": f.get("before"), "after": f["after"]})

    def _check_room(self, room: float, nearest_drop: float) -> None:
        """room_disagrees: the map says there is no room to turn while the depth sensor sees `room_disagrees_clear_mm` or more clear
        ahead. Half of the refusals for no room to turn in the recordings are such (profile anomalies.measured): it is a note beside
        them, not a verdict on which of the two was right."""
        if self.anomalies is None:
            return
        near, pose = self.range.nearest_mm(), self.localisation.pose()
        limit = self.anomalies.room_disagrees_clear_mm
        if near is None or near < limit or not self._once_here("room_disagrees", pose):
            return
        self.anomaly("room_disagrees", f"the map has {room:.2f} m of room to turn, the depth sensor sees {near:.0f} mm clear ahead",
                     margin=near - limit, values={"room_m": round(room, 3), "nearest_mm": near, "limit_mm": limit,
                                                  "nearest_drop_m": round(nearest_drop, 3), "margin_unit": "mm"})

    def _check_unexplained(self, grid: CostGrid, pose: tuple, goal: tuple, why: str, start_cost: float, goal_cost: float) -> None:
        """refused_unexplained: the planner found no way, the start is not boxed in, the goal is not lethal, and nothing the robot's
        own map holds (walls, remembered obstacles, drops, edges, suspected drops) lies within `unexplained_clear_m` of the pose."""
        if self.anomalies is None or start_cost >= LETHAL_COST or goal_cost >= LETHAL_COST:
            return
        limit = self.anomalies.unexplained_clear_m
        if clearance(grid, pose[:2], limit) < limit or not self._once_here("refused_unexplained", pose):
            return
        self.anomaly("refused_unexplained", f"{why}, with nothing in the map within {limit} m of the pose and the goal not lethal",
                     values={"why": why, "start_cost": start_cost, "goal_cost": goal_cost, "clear_m": limit, "goal": [round(v, 3) for v in goal]})

    def _check_head(self, s: dict) -> None:
        """head_off_walk, on the state stream: the head joints against the walking pose while the last command was a walk."""
        joints = s.get("joints") or []
        if self._head is None or len(joints) != len(JOINTS):
            return
        try:
            ev = self._head.update(time.monotonic() - self._t0, self._walking, dict(zip(JOINTS, joints)))
        except Exception as e:  # noqa: BLE001 - an observer must not stop the state stream
            self._head = None
            print(f"head watch stopped: {type(e).__name__}: {e}", file=sys.stderr)
            return
        if ev:
            self.anomaly("head_off_walk", f"{ev['joint']} is {math.degrees(ev['deviation_rad']):.0f} deg from its walking pose after "
                         f"{ev['walking_s']:.1f} s of walking", margin=ev["deviation_rad"] - self.anomalies.head_off_walk_rad,
                         values={**ev, "limit_rad": self.anomalies.head_off_walk_rad, "margin_unit": "rad"}, duration_s=ev["walking_s"])

    def _start_watchdog(self) -> None:
        if not self._beat:
            return
        for beat in self._beat.values():
            beat.last = time.monotonic()         # the clock starts when the streams are open, not when the profile was read
        self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self._watchdog_thread.start()

    def _watchdog(self) -> None:
        """thread_failed: the state and depth streams run in threads that end silently (an exception in a callback leaves a line on
        stderr and nothing in the run), so each is said when it has been quiet past its limit (the profile's anomalies.state_stale_s,
        depth_stale_s) and has not spoken since."""
        while not self._closing.wait(WATCHDOG_S):
            now = time.monotonic()
            for name, stream in (("state", self.state), ("depth", self.range)):
                age = self._beat[name].check(now)
                if age is None:
                    continue
                limit = self._beat[name].limit_s
                thread = getattr(stream, "_thread", None)
                self.anomaly("thread_failed", f"the {name} stream has been silent for {age:.1f} s", margin=age - limit,
                             values={"stream": name, "silent_s": round(age, 2), "limit_s": limit,
                                     "thread_alive": None if thread is None else thread.is_alive(), "margin_unit": "s"})

    def lease_ended(self, exc: LeaseLost) -> None:
        """stop_latched or lease_lost, once: the gate refused a command because this client has no lease. `stopped_by <who>` is a STOP
        from someone; an expired lease, a takeover or any other end is the lease lost mid-goal."""
        if self._lease_said:
            return
        self._lease_said = True
        reason = exc.reason or exc.code
        stopped = (exc.reason or "").startswith("stopped_by")
        self.anomaly("stop_latched" if stopped else "lease_lost",
                     f"the gate stopped the robot: {reason.replace('_', ' ')}" if stopped else f"the lease ended: {reason.replace('_', ' ')}",
                     values={"code": exc.code, "reason": exc.reason, "holder": exc.holder})

    def hazards(self) -> list:
        """The remembered drops: a cliff stop's points, measured edges, suspected cells."""
        return self.drops + self.edges + self.suspects.points()

    def costs_here(self, pose: tuple) -> CostGrid:
        """The cost map as the leg's plan sees it round pose: mapd's grid (the belief's frame), the memory's obstacle points
        and the objects', the remembered drops and edges."""
        seen = self.blocked + self.semantic_points()
        costs = self.grid().covering([pose[:2]] + seen + self.drops + self.edges).with_points(seen)
        return costs.with_blocked(self.drops, self.drop_lethal_m, self.drop_inflate_m).with_blocked(self.edges, self.edge_lethal_m, self.edge_inflate_m)

    def recover(self, attempt: int) -> dict:
        """One recovery at the pose (nav/recovery.py): a creep forward, or an arc away from the nearest hazard, as
        recovery.choose says for this attempt from what the depth sensor shows now; then a survey, so mapd maps the new stop.
        A creep only where the room ahead is a turn's room and more than the room here (recovery.creep_gains_room), from the
        same cost map the refusal came from. The event says what was done and how far it moved the duck."""
        pose = self.localisation.pose()
        haz = recovery.hazard(pose, self.hazards(), self.blocked)
        front = recovery.drop_ahead(pose, self.hazards())
        try:
            costs = self.costs_here(pose)
            ahead = (pose[0] + recovery.CREEP_M * math.cos(pose[2]), pose[1] + recovery.CREEP_M * math.sin(pose[2]))
            room_now, room_ahead = clearance(costs, pose[:2], 0.5), clearance(costs, ahead, 0.5)
        except EmptyMap:
            room_now, room_ahead = recovery.projected_room(pose, self.blocked, recovery.CREEP_M)
        nearest_mm = self.range.nearest_mm()
        kind = recovery.choose(attempt, nearest_mm, front, haz, recovery.creep_gains_room(room_now, room_ahead, self.pivot_obstacle_m))
        why = None
        if kind == "creep":
            why = self._walk(0.0, recovery.CREEP_M, self.loco.slowest_mps, 0.0)
        elif kind == "arc":
            why = self._walk(0.7, 0.0, self.loco.slowest_mps, recovery.turn_away(pose, haz[0]) * self.loco.yaw_max_rad_s)
        collecting = self.survey()
        after = self.localisation.pose()
        moved = math.dist(pose[:2], after[:2])
        turned = abs(wrap(after[2] - pose[2]))
        self.record(event="recovery", attempt=attempt, action=kind, stopped=why, pose=pose, after=after, moved_m=round(moved, 3),
                    turned_deg=round(math.degrees(turned), 1), nearest_mm=nearest_mm, drop_ahead=front,
                    room_m=round(room_now, 3), room_ahead_m=round(room_ahead, 3),
                    hazard=[[round(v, 3) for v in haz[0]], haz[1]] if haz else None, surveyed=collecting,
                    decision=decision("recovery", f"a refusal at this pose: {kind}" + (f" ({haz[1]} at {math.dist(pose[:2], haz[0]):.2f} m)"
                                                                                       if kind == "arc" else "") + ", then a survey",
                                      attempt=attempt, action=kind, moved_m=round(moved, 3), nearest_mm=nearest_mm,
                                      room_m=round(room_now, 3), room_ahead_m=round(room_ahead, 3)))
        return {"action": kind, "moved_m": moved, "turned_rad": turned}

    def _walk(self, turned_rad: float, dist_m: float, vx: float, vyaw: float, timeout_s: float = 3.0) -> str | None:
        """Walk at (vx, vyaw) until it has gone dist_m (a creep) or turned turned_rad (an arc), or something stops it: the depth
        sensor shows too little ahead (a creep: the footprint and the margin, recovery.CREEP_FLOOR_MM, and what is left to go; an
        arc: recovery.ARC_CLEAR_MM), the same for an obstacle in the corridor, a drop in the frame within the cliff-stop
        distance, the remembered obstacles nearer than at the start (by 1 cm), the abort, the time. Returns why it stopped early,
        None when it got where it was asked. Ends with a stop."""
        start = self.localisation.pose()
        room0 = min((math.dist(start[:2], b[:2]) for b in self.blocked), default=math.inf)
        t0 = time.monotonic()
        why = "time"
        while time.monotonic() - t0 < timeout_s:
            if self.abort:
                why = "abort"
                break
            pose = self.localisation.pose()
            gone = math.dist(start[:2], pose[:2])
            if (dist_m and gone >= dist_m) or (turned_rad and abs(wrap(pose[2] - start[2])) >= turned_rad):
                why = None
                break
            need_mm = recovery.CREEP_FLOOR_MM + max(0.0, dist_m - gone) * 1000 if dist_m else recovery.ARC_CLEAR_MM
            near, fv = self.range.nearest_mm(), self._fv
            if near is None or near < need_mm:
                why = "no room ahead"
                break
            if fv is not None and fv.ok:
                if fv.block is not None and fv.block < need_mm / 1000.0:
                    why = "obstacle"
                    break
                if fv.drops and min(p[2] for p in fv.drops) < self.cliff_stop_m:
                    why = "drop"
                    break
            if min((math.dist(pose[:2], b[:2]) for b in self.blocked), default=math.inf) < room0 - 0.01:
                why = "closer to something"
                break
            self.move(Twist(vx, vyaw))
            time.sleep(TICK_S)
        self.move(Twist())
        return why

    def survey(self) -> bool:
        """Stand still with explicit zeros until the source is mapping this stop, then a little longer (a source that maps only at
        stops: mapd); then a fix. A source that maps on the move has nothing to wait for."""
        collecting = True
        if self.localisation.needs_stationary():
            collecting = self.localisation.settle(lambda: self.move(Twist()), SURVEY_TIMEOUT_S, TICK_S)
        self.fix()
        return collecting

    def glance_at(self, target: tuple, pose: tuple) -> dict:
        """Stand and look at the floor at target (map metres) with the head, to confirm or clear a suspected drop there
        (docs/wip/SIDE-DROPS.md). The looking plugin aims the head and returns the frames it saw once the sensor's own yaw held
        still. What the navigator makes of them: floor joins floor_seen and clears the suspicions it covers; a floor boundary with
        below-floor returns beyond it (side_drops.edge_from_glance) is a drop, remembered with its edge extended. The head
        then gets back the command it had (robot.head keeps a command until told otherwise). A robot that cannot look leaves the
        spot unseen: not blocked."""
        if not self.looking.capable:
            self.record(event="glance", decision=decision("glance", "this robot cannot look: the spot stays unseen",
                                                          target=list(target)))
            return {"status": "unseen"}
        hold = lambda: self.move(Twist())          # noqa: E731
        view = lambda: self._fv                    # noqa: E731
        self.glanced.append(tuple(target))
        look = self.looking.look_at(target, pose, hold, view, TICK_S)
        if "failed" in look:
            self.record(event="glance", decision=decision("glance", f"robot.look failed: {look['failed']}", target=list(target)))
            return {"status": "failed"}
        t0, frames, bearing, rel, dist = look["t0"], look["frames"], look["bearing"], look["rel"], look["dist"]
        rim, below, floor = edge_from_glance(frames, tuple(pose[:2]), bearing)
        for x, y in floor:
            self.floor_seen.add((round(x / FLOOR_CELL_M), round(y / FLOOR_CELL_M)))
        cleared = self.suspects.clear(floor)
        if rim:
            cells = {(round(x / FLOOR_CELL_M), round(y / FLOOR_CELL_M)) for x, y in rim + below}
            self.edges.extend((cx * FLOOR_CELL_M, cy * FLOOR_CELL_M) for cx, cy in sorted(cells))
            # what the look saw, not extended past it: a line fitted through a rim ran diagonally where the rim held the
            # pit's far wall (challenge 10 seed 1) or went round a corner (challenge 11 seed 2), and its extension put the
            # goal or the passage inside the ring. Rims are too noisy to tell a corner from a line (rms 3-4 cm round a
            # corner, 8-10 cm along a straight ledge).
        edge_m = min((math.dist(p, pose[:2]) for p in rim), default=None)
        self.looking.restore(hold, view, TICK_S)
        # no frames: the head never settled, so nothing was seen; not floor (challenge 11 seed 5 recorded such a look as floor)
        out = {"status": "drop" if rim else ("floor" if frames else "unseen"), "frames": len(frames), "rim": len(rim), "below": len(below),
               "cleared": cleared, "edge_m": round(edge_m, 3) if edge_m is not None else None,
               "time_s": round(time.monotonic() - t0, 2)}
        self.record(event="glance", target=[round(v, 3) for v in target], pose=pose, **out,
                    rim_points=[[round(v, 3) for v in p] for p in rim],      # what the edge was traced from, to trace it back
                    decision=decision("glance", "a suspected drop near the way: looked at it with the head"
                                      + (" and saw its edge" if rim else (" and saw floor" if floor else ", nothing seen")),
                                      bearing_deg=round(math.degrees(rel)), distance_m=round(dist, 3), **out))
        return {**out, "rim_points": rim}

    def look_along(self, edge: list, heading: float, pose: tuple) -> list:
        """After a cliff stop: look along the edge it saw, looking.along_m past each end (side_drops.look_targets). Where the
        look's rim reaches its target, or the look saw nothing, the hole is taken to go on looking.continue_m past the seen end
        (challenge 9's drop spans the room: the duck must still refuse); where it saw floor there, the hole ends before
        it (challenge 11's pit: the way beside it stays open). The glances' own edges join self.edges. Returns, per side,
        whether the hole was taken to go on."""
        if not edge:
            return []
        out = []
        for side, target in zip((-1, 1), look_targets(edge, heading, self.look_along_m)):
            g = self.glance_at(target, pose)
            goes_on = g.get("status") in ("failed", "unseen") or continues(g.get("rim_points") or [], target)
            if goes_on:
                self.drops.extend(continuation(edge, heading, side, self.continue_m))
            out.append(goes_on)
        self.record(event="edge_ends", pose=pose, goes_on=out,
                    decision=decision("edge_ends", "looked along the edge of the drop it stopped at",
                                      goes_on=out, look_along_m=self.look_along_m,
                                      continue_m=self.continue_m))
        return out

    def mapd_grid(self) -> dict:
        """The localisation source's grid as the navigator uses it: scaled like the odometry, and in the belief's frame (the
        pose, the memory and the grid are then one frame, whatever the belief took from the source: after a held jump or a
        landmarks' nudge the walls sat displaced against the duck)."""
        self.sync_memory()
        return self.localisation.grid(self.frames_on, self.fix_fault, self.fault_grid, self._t0)

    def grid(self) -> CostGrid:
        g = self._map_raw = self.mapd_grid()
        return CostGrid.from_map_grid(g, explained_by=self.blocked, lethal_m=self.fp.lethal_m, inflate_m=self.fp.inflate_m)   # the clearance model: exact points over whole cells

    def _remember(self, pts: list, pose: tuple) -> list:
        """Add obstacle points (relative to the sensor, trunk-heading frame) to the memory, a few cm
        apart; return the ones that were new, in map metres."""
        c, s_ = math.cos(pose[2]), math.sin(pose[2])
        new = []
        for ax, ay in pts:
            q = (pose[0] + c * ax - s_ * ay, pose[1] + s_ * ax + c * ay)
            key = (round(q[0] / LAYER_SPACING_M), round(q[1] / LAYER_SPACING_M))
            if key not in self._seen:
                self._seen.add(key)
                self.blocked.append(q)
                new.append(q)
        return new

    def _remember_frame(self, fv, tick_pose: tuple) -> list:
        """Remember a frame's obstacle points within LAYER_M, placed with the pose of the state the frame was paired with
        (fv.pose), the tick's only when the frame has none: frames come at 15 Hz and ticks at 10 Hz, and during a pivot at
        0.8 rad/s the tick's pose is up to 0.08 rad off, a point at 0.6 m some 5 cm (the review of 2026-11-16)."""
        pose = fv.pose or tick_pose
        return self._remember(self.range.obstacle_points(fv.frame, fv.state, within_m=LAYER_M), pose) + \
            self._remember_low(self.range.low_points(fv.frame, fv.state, within_m=LAYER_M), pose,
                               (fv.frame.get("seq"), fv.frame.get("t_ns")))

    def _remember_low(self, pts: list, pose: tuple, frame_key) -> list:
        """Low-band points (cliff.low_points) join the memory once LOW_FRAMES different frames saw their LOW_CELL_M
        cell: one frame's low return is floor noise as often as not, a low box is there in every frame. frame_key tells
        frames apart (go_to calls this every tick, with the newest frame, often the same one)."""
        c, s_ = math.cos(pose[2]), math.sin(pose[2])
        keep = []
        for ax, ay in pts:
            q = (pose[0] + c * ax - s_ * ay, pose[1] + s_ * ax + c * ay)
            frames = self._low.setdefault((round(q[0] / LOW_CELL_M), round(q[1] / LOW_CELL_M)), set())
            frames.add(frame_key)
            if len(frames) >= LOW_FRAMES:
                keep.append((ax, ay))
        return self._remember(keep, pose)

    def _on_state(self, s: dict) -> None:
        """Every robot state (the state stream's thread): odometry to the localizer, the state to the pairing history, the IMU and
        the navigator's values to the run's signals."""
        self.localisation.on_odom(s["t_ns"], odom_pose(s))
        self._states.append((s["t_ns"], s))
        if self._beat:
            self._beat["state"].seen(time.monotonic())
            self._check_head(s)
        if self.runlog and not self._logging_failed:
            try:
                self.runlog.signals(self._sid, time.monotonic() - self._t0, self._signal_values(s))
            except Exception as e:  # noqa: BLE001 - an observer must not stop the state stream
                self._logging_failed = True
                print(f"signals not logged: {type(e).__name__}: {e}", file=sys.stderr)

    def _signal_values(self, s: dict) -> dict:
        v = {}
        imu = s.get("imu")
        if imu:
            w, x, y, z = imu["quat"]
            v.update(pitch_deg=math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))),
                     roll_deg=math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))),
                     pitch_rate_dps=math.degrees(imu["gyro"][1]), qw=w, qx=x, qy=y, qz=z)
        joints = s.get("joints") or []           # the measured angles robotd reports, in its JOINT_NAMES order (ADR-0016)
        if len(joints) == len(JOINTS):
            v.update({f"joint_{n}": a for n, a in zip(JOINTS, joints)})
        fv = self._fv
        v.update(nearest_mm=self.range.nearest_mm() if self.range else None, block_m=fv.block if fv else None, **self.sense)
        return {k: x for k, x in v.items() if x is not None and math.isfinite(x)}

    def _pair(self, t_ns: int) -> tuple:
        """(state, state time minus frame time in ms): the state nearest the frame's capture among those received, as Pollen's
        autod pairs them; the newest state, with no time difference, for a frame that carries no time."""
        states = self._states.copy()
        if not states:
            return None, None
        if not t_ns:
            return states[-1][1], None
        t, st = min(states, key=lambda e: abs(e[0] - t_ns))
        return st, (t - t_ns) / 1e6

    def _on_frame(self, frame: dict) -> None:
        """Every depth frame, whatever the duck is doing (surveys and turns too: trial 11 surveyed
        first and found no frontier with seen floor): paired with a state and derived once (FrameView), logged, and the
        floor it shows joins floor_seen."""
        arrived = time.monotonic() - self._t0
        if self._beat:
            self._beat["depth"].seen(time.monotonic())
        state, dt_ms = self._pair(frame.get("t_ns") or 0)
        pose = None
        if state is not None:
            try:
                pose = self.localisation.to_map(odom_pose(state))
            except (KeyError, TypeError, ValueError):
                pass
        fv = self._fv = self.range.derive(frame, state, dt_ms, pose)
        # not while the memory still sits in the frame before the belief's last move: these points would be moved twice
        if fv.ok and pose is not None and not (self.frames_on and self.loc.memory_pending()):
            c, s_ = math.cos(pose[2]), math.sin(pose[2])
            seen = []
            for ax, ay, h, kind in fv.rel:
                if kind == "floor" or (kind == "below" and self.range.below_counts(h, math.hypot(ax, ay))):
                    x, y = pose[0] + c * ax - s_ * ay, pose[1] + s_ * ax + c * ay
                    seen.append((x, y, kind))
                    if kind == "floor":
                        self.floor_seen.add((round(x / FLOOR_CELL_M), round(y / FLOOR_CELL_M)))
            self.suspects.add_frame(seen)
        if self.runlog and not self._logging_failed:
            try:
                self.runlog.frame(self._sid, arrived, fv.payload())
            except Exception as e:  # noqa: BLE001 - an observer must not stop the depth stream
                self._logging_failed = True
                print(f"depth frames not logged: {type(e).__name__}: {e}", file=sys.stderr)

    def _tilt(self) -> list | None:
        """The trunk's pitch and roll (deg) by the IMU: trial 12's false drop needs a 5 deg pitch
        error, and the log did not say whether the duck was tilted."""
        st = self.state.latest
        if not st or "imu" not in st:
            return None
        w, x, y, z = st["imu"]["quat"]
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
        roll = math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))
        return [round(pitch, 1), round(roll, 1)]

    def floor_seen_at(self, xy: tuple) -> bool:
        """Has the depth sensor seen floor in xy's own FLOOR_CELL_M cell? Exact, not near: at a drop's edge a few cm of
        tolerance is the whole margin (the step_check replay of b2 r2: with one cell of tolerance the floor seen at the
        stairwell's south edge passed spots inside the opening)."""
        return (round(xy[0] / FLOOR_CELL_M), round(xy[1] / FLOOR_CELL_M)) in self.floor_seen

    def floor_seen_near(self, xy: tuple, radius_m: float = FLOOR_NEAR_M) -> bool:
        """Has the depth sensor seen floor within radius_m of xy?"""
        cx, cy = round(xy[0] / FLOOR_CELL_M), round(xy[1] / FLOOR_CELL_M)
        r = math.ceil(radius_m / FLOOR_CELL_M)
        return any((cx + dx, cy + dy) in self.floor_seen for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                   if math.hypot(dx, dy) * FLOOR_CELL_M <= radius_m)

    def _arc_clear(self, costs: CostGrid, pose: tuple, turn: float) -> bool:
        """Clear floor for a slow turn while walking (the locomotion plugin judges it against the sensor and the hazard memory)."""
        return self.locomotion.arc_clear(costs, pose, turn, self.range.nearest_mm(), self.drops, self.edges, self.suspects.points())

    def _record_world(self) -> None:
        """The world model as the planner saw it, for the viewer (duck-world): mapd's grid and the
        remembered obstacles and drops, whenever any of them changed."""
        g = self._map_raw
        if not g:
            return
        d = self.localisation.frame_delta()
        shown = [round(v, 4) for v in d] if d is not None else None
        key = (hash(g["cells"]), g["width"], g["height"], len(self.blocked), len(self.drops), len(self.edges), tuple(shown or ()),
               len(self._moves))
        if key == self._world_key:
            return
        self._world_key = key
        # frames: the belief's frame against mapd's (translation, yaw) and how often the memory has moved with it; the grid
        # here is in the belief's frame already, as the blocked points and drops are
        self.record(event="world", grid={k: g[k] for k in ("res_m", "origin", "width", "height", "cells")},
                    blocked=[[round(v, 3) for v in b] for b in self.blocked],
                    drops=[[round(v, 3) for v in d] for d in self.drops + self.edges],
                    frames={"belief_from_mapd": shown, "parted": self.loc.parted(), "memory_moves": len(self._moves)})

    def forget_blocked_near(self, pose: tuple, radius_m: float) -> int:
        """Nav2's "clear around the robot" recovery, for the obstacle memory only: mapd's map stays, and
        drops are never forgotten (trial 3 fell when drop memory was switched off)."""
        keep = [b for b in self.blocked if math.dist(b, pose[:2]) >= radius_m]
        gone = len(self.blocked) - len(keep)
        self.blocked = keep
        self._seen = {(round(b[0] / LAYER_SPACING_M), round(b[1] / LAYER_SPACING_M)) for b in keep}
        self._low = {k: v for k, v in self._low.items()
                     if math.dist((k[0] * LOW_CELL_M, k[1] * LOW_CELL_M), pose[:2]) >= radius_m}
        return gone

    _rec_lock = threading.RLock()   # rows come from the main loop and the camera thread (RFC-0016); re-entered by watch

    def record(self, **row) -> None:
        with self._rec_lock:
            self._record(**row)

    def _record(self, **row) -> None:
        if self.on_decision is not None and row.get("decision"):
            try:
                self.on_decision(row)
            except Exception:       # noqa: BLE001 - a listener must not stop the navigation
                pass
        if self._log or self.runlog:
            row["t"] = round(time.monotonic() - self._t0, 3)
            if self.body:
                row["truth"] = [round(v, 4) for v in self.body.pose()]
                row["truth_z"] = round(self.body.height, 4)
                row["truth_quat"] = [round(v, 6) for v in self.body.quat]
            if self._log:
                self._log.write(json.dumps(row) + "\n")
                self._log.flush()
            if self.runlog:
                self.runlog.row(self._sid, row)
            if self.watch and "truth" in row and "event" not in row:
                said = self.watch(row)
                if said:
                    self.record(**said)

    def go_to(self, goal: tuple, timeout_s: float = 90.0) -> dict:
        try:
            return self._go_to(goal, timeout_s)
        finally:
            self.sense = {}

    def _go_to(self, goal: tuple, timeout_s: float) -> dict:
        start = time.monotonic()
        if self.localisation.pose() is None and not self.fix():
            self.survey()
        if self.localisation.pose() is None:
            return {"status": "refused", "why": "no pose on the map yet"}
        path, planned_at, st = None, 0.0, FollowState()
        stuck = StuckWatch(self.loco.stuck.window_s, self.loco.stuck.moved_max_m)
        following = None     # the path being followed; a replan keeps it unless it is blocked or much longer
        tight = False        # a tight pivot was logged this leg
        reflex_stops = 0
        progress = Progress(start)
        held_at = None       # where a goal inside a drop's ring is held off at (nearest_free), once aimed at
        moves_seen = len(self._moves)
        while time.monotonic() - start < timeout_s:
            if self.abort:
                self.move(Twist())
                self.record(event="aborted", why=self.abort, decision=decision("aborted", self.abort))
                return {"status": "aborted", "why": self.abort}
            if len(self._moves) > moves_seen:
                # the memory moved with the belief's frame: the goal, a place in the world, and the path to it move too
                for d in self._moves[moves_seen:]:
                    goal = move_xy(d, goal)[:2]
                    held_at = move_xy(d, held_at)[:2] if held_at else None
                moves_seen = len(self._moves)
                path = following = None
            now = time.monotonic()
            pose = self.localisation.pose()
            if path is None or now - planned_at > REPLAN_S:
                fv = self._fv
                if fv is not None and fv.ok:
                    # what the sensor sees now is in the memory before the plan and the pivot gate use it: a
                    # duck that has not moved yet had none (challenge 7: the room read from whole cells alone)
                    self._remember_frame(fv, pose)
                try:
                    grid = self.grid()
                except EmptyMap:
                    self.survey()
                    continue
                seen = self.blocked + self.semantic_points()     # the depth sensor's points and the objects' (RFC-0016)
                grid = grid.covering([pose[:2], goal] + seen + self.drops + self.edges).with_points(seen)
                grid = grid.with_blocked(self.drops, self.drop_lethal_m, self.drop_inflate_m)
                grid = grid.with_blocked(self.edges, self.edge_lethal_m, self.edge_inflate_m)   # edges a glance measured
                suspected = self.suspects.points()        # suspected drops: a smaller ring until a glance confirms them
                unsuspected = grid
                # a goal inside a known drop's ring: aim at the nearest place out of it, within HOLD_OFF_M (the
                # operator, 2026-11-17: go as close as is safe and say so); farther, it is across the drop: refused
                gc = unsuspected.cell(*goal)
                inside = unsuspected.inside(*gc) and unsuspected.at(*gc) >= LETHAL_COST
                aim = (nearest_free(unsuspected, goal, self.hold_off_m, room_m=self.pivot_obstacle_m) or goal) if inside else goal
                if aim != goal and aim != held_at:
                    held_at = aim
                    self.record(event="held_off", goal=goal, aim=[round(v, 3) for v in aim],
                                decision=decision("held_off", "the goal is inside a drop's ring: going as close as is safe",
                                                  held_off_m=round(math.dist(aim, goal), 3), hold_off_max_m=self.hold_off_m))
                if suspected:
                    grid = grid.covering(suspected).with_blocked(suspected, self.edge_lethal_m, self.edge_inflate_m)
                raw = plan(grid, pose[:2], aim)
                if raw and aim != goal and path_length([pose[:2]] + raw) > self.hold_detour * math.dist(pose[:2], aim) + 0.3:
                    # the way to the held-off place goes round the drop: that place is across it, not this side of it
                    # (challenges 8 and 9: 13 of 20 refusals would have walked 2.4-7 m round the drop instead)
                    raw = None
                if raw is None and suspected:
                    # no way with the suspicions, one without them: the ones in that way not looked at yet are to be
                    # looked at, not a reason to refuse (challenge 11 seed 3: a false one 0.15 m from the goal). Within
                    # CONFIRM_M, now; farther, walk on that way and the trigger looks when near enough to see (challenge
                    # 10 seed 5: a look from 1.4 m saw floor but cleared none of them, and the leg was refused).
                    free = plan(unsuspected, pose[:2], goal)
                    look = [p for p in in_the_way(free or [], suspected, self.edge_lethal_m)
                            if all(math.dist(p, g) > self.glanced_m for g in self.glanced)]
                    near_ = [p for p in look if math.dist(p, pose[:2]) <= self.confirm_m]
                    if near_:
                        self.move(Twist())
                        self.glance_at(min(near_, key=lambda p: math.dist(p, pose[:2])), pose)
                        path = None
                        continue
                    if look:
                        raw = free
                if raw is None:
                    self.move(Twist())
                    start_cost, goal_cost = grid.at(*grid.cell(*pose[:2])), grid.at(*grid.cell(*goal))
                    boxed = start_cost >= LETHAL_COST and goal_cost < LETHAL_COST
                    why = "start boxed in" if boxed else "no path on the map"
                    self.record(event="refused", goal=goal, pose=pose,
                                start_cost=start_cost, goal_cost=goal_cost,
                                drops=[[round(v, 2) for v in d] for d in self.drops],
                                edges=[[round(v, 2) for v in d] for d in self.edges],
                                suspected=[[round(v, 2) for v in d] for d in suspected],
                                blocked=[[round(v, 2) for v in b] for b in self.blocked],
                                decision=decision("refused", why, start_cost=start_cost, goal_cost=goal_cost,
                                                  lethal_cost=LETHAL_COST))
                    self._check_unexplained(grid, pose, goal, why, start_cost, goal_cost)
                    return {"status": "refused", "why": why, "time_s": round(now - start, 1),
                            "start_lethal": start_cost >= LETHAL_COST}
                ahead = following[st.target_index:] if following else []
                if keep_current(grid, ahead, pose, raw):
                    path = ahead
                    self.record(event="plan_kept", pose=pose, goal=goal)
                else:
                    # 10 cm waypoints: at the old 30 cm the lookahead landed 0.3-0.6 m ahead and cut bends.
                    path = thin(raw, FOLLOW_SPACING_M)
                    self.record(event="plan", pose=pose, goal=goal, path=[[round(v, 3) for v in q] for q in path])
                following, planned_at, costs = path, now, grid
                self._record_world()
                left = path_length([pose[:2]] + path)
                if progress.update(left, now, len(self.drops) + len(self.edges)):
                    self.move(Twist())
                    self.record(event="stalled", goal=goal, pose=pose, path_left_m=round(left, 2),
                                best_left_m=round(progress.best, 2),
                                decision=decision("stalled", f"{NO_PROGRESS_S:.0f} s without getting closer",
                                                  path_left_m=round(left, 2), best_left_m=round(progress.best, 2),
                                                  progress_m=PROGRESS_M, no_progress_s=NO_PROGRESS_S))
                    return {"status": "stalled", "why": f"{NO_PROGRESS_S:.0f} s without getting closer",
                            "time_s": round(now - start, 1), "reflex_stops": reflex_stops}
                st.target_index = 0
            if self.edges and self.suspects.suspected:
                self.edges.extend(self.suspects.confirm_near(self.edges, self.absorb_m))
            if not st.turning:
                # RFC-0012's first trigger: a suspected drop near the way, not yet looked at: stop and look at it
                look = [p for p in self.suspects.near(pose[:2], self.confirm_m)
                        if all(math.dist(p, g) > self.glanced_m for g in self.glanced)]
                if look:
                    self.move(Twist())
                    self.glance_at(min(look, key=lambda p: math.dist(p, pose[:2])), pose)
                    path = None
                    continue
            near = costs.inside(*costs.cell(*pose[:2])) and costs.at(*costs.cell(*pose[:2])) > FREE_COST    # in a margin ring, unknown or shadow
            nearest_drop = min((math.dist(pose[:2], d) for d in self.drops + self.edges), default=math.inf)
            room = clearance(costs, pose[:2], max(self.pivot_obstacle_m, self.loco.slow_clearance_m))
            pivot_ok = self.locomotion.can_pivot(room, pose[:2], self.drops, self.edges)
            tw, done = step(path, pose, now, st, self.loco, self.locomotion, near=near, pivot_ok=pivot_ok,
                            close=room < self.loco.slow_clearance_m)
            self.sense = {"room_m": round(room, 3), "turning": int(st.turning)}
            if done:
                self.move(Twist())
                held = round(math.dist(held_at, goal), 3) if held_at else None
                self.record(event="reached", goal=goal, pose=pose, held_off_m=held)
                return {"status": "reached", "time_s": round(now - start, 1), "reflex_stops": reflex_stops,
                        **({"held_off_m": held, "why": "held off: the goal is inside a drop's ring"} if held else {}),

                        "pose": [round(v, 3) for v in pose]}
            pts = []
            fv = self._fv       # the newest frame with the state it was paired with, derived once (FrameView)
            if fv is not None and fv.ok:
                pts = fv.drops
                if fv is not self._drop_frame:      # count frames, not ticks
                    self._drop_frame = fv
                    self._block = fv.block
                    self._depth = fv.points
                    self._drop_streak = self._drop_streak + 1 if pts else 0
                if self._drop_streak < DROP_FRAMES:
                    pts = []
                new = self._remember_frame(fv, pose)
                ahead = path[st.target_index:] if path else []
                if new and any(math.dist(q, w) < self.fp.lethal_m + 0.05 for q in new for w in ahead):
                    self.record(event="replan_new_obstacle", points=len(new), pose=pose,
                                decision=decision("replan_new_obstacle", "new obstacle points on the path ahead",
                                                  points=len(new), margin_m=self.fp.lethal_m + 0.05))
                    path = None
                    continue
            if tw.vx > 0 and pts and min(p[2] for p in pts) < self.cliff_stop_m:
                self.move(Twist())
                at = fv.pose or pose        # the drops were seen in that frame: placed with its state's pose
                c, s_ = math.cos(at[2]), math.sin(at[2])
                edge = [(at[0] + c * ax - s_ * ay, at[1] + s_ * ax + c * ay) for ax, ay, _ in pts]
                for ax, ay, h in pts:
                    for extra in (0.0,) + self.beyond_m:
                        k = (h + extra) / h if h > 0 else 1.0
                        self.drops.append((at[0] + k * (c * ax - s_ * ay), at[1] + k * (s_ * ax + c * ay)))
                self.record(event="cliff_stop", drop_m=round(min(p[2] for p in pts), 3), zones=len(pts), pose=pose,
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            decision=decision("cliff_stop", f"a drop ahead seen in {self._drop_streak} frames in a row",
                                              drop_m=round(min(p[2] for p in pts), 3), stop_m=self.cliff_stop_m, zones=len(pts),
                                              streak=self._drop_streak, frames_needed=DROP_FRAMES, vx=tw.vx))
                self.look_along(edge, at[2], pose)
                self.survey()
                path = None
                continue
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose, tw.vyaw) and \
                    self.locomotion.tight_pivot_ok(room, pose[:2], self.drops, self.edges, now):
                # Nav2's spin recovery with a collision check, by the tick: in a squeeze (exploration
                # trial 7, wedged by a cabinet) pivot anyway while the room stays above TIGHT_PIVOT_M.
                tw, done = step(path, pose, now, st, self.loco, self.locomotion, near=near, pivot_ok=True,
                                close=room < self.loco.slow_clearance_m)
                if not tight:
                    tight = True
                    self.record(event="tight_pivot", pose=pose, room_m=round(room, 3), nearest_mm=self.range.nearest_mm(),
                                decision=decision("tight_pivot", "no clear floor for an arc; pivoting while the room lasts",
                                                  room_m=round(room, 3), min_room_m=self.tight_pivot_m,
                                                  nearest_drop_m=round(nearest_drop, 3), drop_clear_m=self.pivot_drop_m, edge_clear_m=self.pivot_edge_m,
                                                  nearest_mm=self.range.nearest_mm(), arc_clear_mm=self.arc_clear_mm))
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose, tw.vyaw):
                self.move(Twist())
                self.record(event="refused", why="no room to turn", pose=pose, room_m=round(room, 3),
                            nearest_drop_m=round(nearest_drop, 3), nearest_mm=self.range.nearest_mm(),
                            blocked=[[round(v, 2) for v in b] for b in self.blocked if math.dist(b, pose[:2]) < 0.5],
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            path=[[round(v, 2) for v in q] for q in (path or [])[:8]],
                            decision=decision("refused", "no room to turn", room_m=round(room, 3), min_room_m=self.tight_pivot_m,
                                              nearest_drop_m=round(nearest_drop, 3), drop_clear_m=self.pivot_drop_m, edge_clear_m=self.pivot_edge_m,
                                              nearest_mm=self.range.nearest_mm(), arc_clear_mm=self.arc_clear_mm))
                self._check_room(room, nearest_drop)
                return {"status": "refused", "why": f"no room to turn ({room:.2f} m to an obstacle, "
                        f"{nearest_drop:.2f} m to a drop)", "time_s": round(now - start, 1)}
            near = self.range.nearest_mm()
            if tw.vx > 0 and path:
                spot = self.range.unseen_ahead(path[st.target_index:], pose, self.floor_seen_at, skip=self.step_looked)
                if spot is not None:
                    # Look before you step (step_check.py): floor about to be walked on that the depth sensor never saw
                    # as floor (exploring b2 r2 cut a stairwell corner it had never had in view).
                    self.move(Twist())
                    self.step_looked.append(spot)
                    self.record(event="step_look", spot=[round(v, 3) for v in spot], pose=pose,
                                decision=decision("step_look", "floor about to be walked on was never seen: look first",
                                                  spot=[round(v, 3) for v in spot]))
                    looked_at = time.monotonic()
                    seen = self.glance_at(spot, pose)
                    progress.pause(time.monotonic() - looked_at)
                    if seen.get("status") != "drop" and not self.floor_seen_at(spot):
                        self.blocked.append(tuple(spot))    # still not seen as floor: not walked on (an obstacle point)
                    path = None
                    continue
            blocked_ahead = self._block is not None and self._block < self.reflex_ahead_m
            if tw.vx > 0 and (blocked_ahead or (near is not None and near < self.emergency_mm)):
                reflex_stops += 1
                self.move(Twist())
                seen = self.range.obstacle_points(fv.frame, fv.state) if fv is not None and fv.ok else []
                self._remember(seen, (fv.pose or pose) if fv is not None else pose)    # placed with the frame's pose
                if not seen:   # no geometry (no state yet): the nearest return straight ahead
                    ahead = near / 1000.0
                    self.blocked.append((pose[0] + ahead * math.cos(pose[2]), pose[1] + ahead * math.sin(pose[2])))
                emergency = near is not None and near < self.emergency_mm
                self.record(event="reflex_stop", nearest_mm=near, block_m=self._block, pose=pose,
                            decision=decision("reflex_stop", f"a return within {self.emergency_mm} mm" if emergency and not blocked_ahead
                                              else f"an obstacle in the corridor within {self.reflex_ahead_m} m",
                                              block_m=self._block, ahead_limit_m=self.reflex_ahead_m, nearest_mm=near,
                                              emergency_mm=self.emergency_mm, corridor_half_m=self.reflex_half_w_m))
                self.survey()
                # Face the path before walking again: the reflex watches straight ahead, the path may bend past what
                # stopped it (exploring b3 r2: the cabinet's corner 0.11 m to the side of the heading, the path clear
                # past it, plan kept and reflex stop again 28 times). With the plan kept, the follower turns on the spot
                # to the lookahead first (follow.step's turn, within TURN_DONE_RAD) and the reflex then looks the way
                # the duck will walk; a path really blocked is replanned as before.
                st.turning, st.turn_started, st.check_t = True, time.monotonic(), None
                path = None
                continue
            seen = stuck.update(now, tw.vx > 0.05, pose[:2])
            if seen:
                # walking asked, the belief going nowhere (nav/stuck.py; challenge 16's first build stalled 15 s at a bar
                # before the stall rule spoke): stop, and remember something just ahead, so the next plan goes elsewhere
                self.move(Twist())
                ahead = 0.20     # beyond the lethal ring, so the duck's own cell stays out of the point's lethal ring
                self.blocked.append((pose[0] + ahead * math.cos(pose[2]), pose[1] + ahead * math.sin(pose[2])))
                self.record(event="stuck", pose=pose, **seen,
                            decision=decision("stuck", "walking without getting anywhere", **seen,
                                              window_s=self.loco.stuck.window_s, moved_max_m=self.loco.stuck.moved_max_m))
                self.anomaly("stuck", f"walking for {seen['seconds']:.1f} s, the belief moved {seen['moved_m']:.3f} m",
                             margin=self.loco.stuck.moved_max_m - seen["moved_m"], duration_s=seen["seconds"],
                             values={**seen, "window_s": self.loco.stuck.window_s, "moved_max_m": self.loco.stuck.moved_max_m})
                return {"status": "stalled", "why": "stuck: walking without moving", "time_s": round(now - start, 1),
                        **seen}
            self.move(tw, nearest_mm=near, turning=st.turning)
            if int(now / 1.0) != int((now - TICK_S) / 1.0):
                self.fix()
            time.sleep(max(0.0, TICK_S - (time.monotonic() - now)))
        self.move(Twist())
        return {"status": "timeout", "time_s": timeout_s, "reflex_stops": reflex_stops,
                "pose": [round(v, 3) for v in self.localisation.pose()]}

    def enable_objects(self, camera, kinds: dict, costs: bool = False, semantic: SemanticMap | None = None,
                       area_at=None, relocalise: bool = True) -> None:
        """Objects (RFC-0016): every camera period, what the camera recognises joins the semantic map, placed with the
        belief taken right after the camera's truth (50 ms apart at most: 1.5 cm walking, under the camera's noise); a
        "semantic" event when an object is new or confirmed, a "room" event when the room the objects say the duck is in
        changes (mapd's last grid decides what is in sight). costs: the confirmed objects' parts join the cost map too
        (semantic_points) — off by default: the depth sensor already sees them, and a drifted copy beside the fresh
        points closed passages and fed "no room to turn" (the advisor's review; RFC-0016 §5, to be measured)."""
        self.semantic = semantic if semantic is not None else SemanticMap(kinds, limits=self.limits)     # a site's map, or a fresh one
        self.object_costs = costs
        self.semantic.limits = self.limits       # a site's map was built before this navigator knew its robot
        self.reloc = Relocaliser(self.semantic, numbers=self.profile.localisation.landmarks)
        if semantic is not None:
            self.semantic.anchor_landmarks()      # a site's landmarks, where they were kept: the run's belief is checked against them
        period = camera.cfg["period_s"]

        def watch():
            said = set()
            while not self._closing.wait(period):
                try:
                    look()
                except Exception as e:  # noqa: BLE001 - the camera must not stop the run, nor stop looking; each failure said once
                    why = f"{type(e).__name__}: {e}"
                    if why not in said:
                        said.add(why)
                        self.record(event="camera_failed", why=why)
                        self.anomaly("camera_failed", f"the camera's look failed: {why}", values={"why": why, "period_s": period})

        recorded = {"t": 0.0, "at": {}}       # the last objects snapshot: when, and where each object was then

        def look():
            pose = self.localisation.pose()
            if pose is None or self.body is None or (self.frames_on and self.loc.memory_pending()):
                return           # (pending: the memory is not yet in the belief's frame, the navigator's thread moves it)
            found = camera.detect(self.body.pose())
            # every look, what it recognised, relative to the duck: a "sighting" (RFC-0016 rev. 3; the Observatory's eye
            # view and video, ADR-0019), with each recogniser's evidence when it has any (a real camera's frame and box)
            self.record(event="sighting", pose=[round(v, 4) for v in pose], hfov_deg=camera.cfg["hfov_deg"],
                        range_m=camera.cfg["range_m"],
                        seen=[{"kind": d.kind, "x": round(d.x, 3), "y": round(d.y, 3), "radius": d.radius,
                               "z0": round(d.z0, 3), "z1": round(d.z1, 3), "range_m": round(d.range_m, 3),
                               "confidence": d.confidence, "source": d.source,
                               **({"evidence": d.evidence} if d.evidence else {})} for d in found])
            now = time.monotonic() - self._t0
            fixed = self.reloc.observe(found, pose, now) if relocalise else None
            if fixed and fixed["status"] == "corrected":
                step = self.localisation.nudge(fixed["dx"], fixed["dy"])
                fixed["step"] = [round(v, 3) for v in step]
                fixed["offset"] = [round(v, 3) for v in self.loc.offset]
                pose = self.localisation.pose() or pose
            if fixed:
                self.record(event="relocalise", **fixed, pose=[round(v, 4) for v in pose],
                            decision=decision("relocalise", fixed.get("why") or
                                              f"landmarks {fixed['landmarks']} place the duck {fixed['median']} m off: "
                                              f"belief moved {fixed.get('step')}", **{k: v for k, v in fixed.items()
                                                                                      if k in ("n", "median", "spread_m")}))
                if fixed["status"] == "refused":
                    lm = self.profile.localisation.landmarks
                    self.anomaly("reloc_refused", f"{fixed['n']} landmark sightings in {lm.window_s:g} s disagree by {fixed['spread_m']:.2f} m "
                                 f"(limit {lm.spread_m}); no correction", margin=fixed["spread_m"] - lm.spread_m,
                                 values={"n": fixed["n"], "spread_m": fixed["spread_m"], "median": fixed["median"], "landmarks": fixed["landmarks"],
                                         "limit_m": lm.spread_m, "window_s": lm.window_s, "min_n": lm.min_n})
            if self.frames_on and fixed and fixed["status"] == "corrected":
                return           # the objects are in the old frame until the navigator's thread moves them: this look is not placed
            with self._sem_lock:
                changes = self.semantic.integrate(found, pose, now)
                forgot = self.semantic.forget(pose, camera.cfg["hfov_deg"], camera.cfg["range_m"], self._map_raw, now)
                changes += forgot
                guess, votes = self.semantic.area_type_at(pose, self._map_raw)
                moved = any(math.dist((o.x, o.y), recorded["at"].get(o.oid, (math.inf, math.inf))) > SNAPSHOT_MOVED_M
                            for o in self.semantic.objects)
                due = changes or (moved and now - recorded["t"] >= SNAPSHOT_S)
                objects = [o.summary() for o in self.semantic.objects] if due else None
                if due:
                    recorded["t"], recorded["at"] = now, {o.oid: (o.x, o.y) for o in self.semantic.objects}
            if due:
                # the whole map when an object is new or confirmed, and every SNAPSHOT_S while any moved (they follow
                # the belief's drift): the Observatory then draws where they are, not where they were first seen
                self.record(event="semantic", changes=[[c, o.oid] for c, o in changes], objects=objects)
            for c, o in forgot:
                self.record(event="forget", id=o.oid, kind=o.kind, change=c, misses=o.misses, pinned=o.pinned,
                            decision=decision("forget", f"{o.kind} {o.oid} {c}: expected in view and not seen "
                                              f"{o.misses} looks in a row", pose=[round(v, 3) for v in pose]))
            if guess != self.room:
                # the area type the objects near suggest: information, never an area (the operator's, site.Area)
                self.room = guess
                self.record(event="area_type", type=guess, votes=votes,
                            decision=decision("area_type", f"the objects near look like: {guess}", votes=votes))
            if area_at is not None:
                # which of the operator's areas the duck is in: its pose inside an outline (geometry), and whether the
                # objects' guess agrees — a disagreement says the pose is likely wrong (RFC-0016 rev. 3)
                area = area_at(pose[:2])
                aid = area.aid if area else None
                agrees = None if area is None or area.type is None or guess is None else area.type == guess
                if aid != self.area or agrees != self.area_agrees:
                    self.area, self.area_agrees = aid, agrees
                    self.record(event="area", id=aid, name=area.name if area else None, type=area.type if area else None,
                                guess=guess, agrees=agrees,
                                decision=decision("area", f"in {area.name if area else 'no area'}"
                                                  + ("" if agrees is not False else f", but the objects look {guess}"),
                                                  agrees=agrees))

        threading.Thread(target=watch, daemon=True).start()

    object_costs = False

    def semantic_points(self) -> list:
        """The semantic cost layer's points; none unless enable_objects(costs=True): every grid the brain builds is
        then the one it built before objects existed."""
        if self.semantic is None or not self.object_costs:
            return list(self.keepout)
        seen = list(self.blocked)
        with self._sem_lock:
            return list(self.keepout) + self.semantic.blocking_points(seen=seen)     # only where the depth sensor has no points

    def close(self) -> None:
        self._closing.set()
        try:
            self.move(Twist())
        except LeaseLost:
            pass                  # the gate stopped the robot when the lease ended
        if self.client:
            try:
                self.robot.call("gate.release")
            except (LeaseLost, RuntimeError, OSError):
                pass
        self.state.close()
        self.range.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("x", type=float)
    ap.add_argument("y", type=float)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--robot-socket", type=Path, help="the robot's socket: robotd's own (the default) or a gate's (duck-gate)")
    ap.add_argument("--client", help="the name to speak to a gate as (hello, then gate.acquire): needed with a gate's socket")
    add_args(ap)
    args = ap.parse_args()
    stamp = time.strftime("go-%Y%m%d-%H%M%S")
    runlog = open_from_args(args, args.log.stem if args.log else stamp, "go-to", args.log.parent if args.log else None)
    try:
        nav = Navigator(log=args.log, runlog=runlog, robot_sock=args.robot_socket, client=args.client)
    except LeaseLost as exc:
        print(json.dumps({"status": "refused", "why": str(exc), "gate": exc.code, "holder": exc.holder}))
        if runlog:
            runlog.finish()
        sys.exit(3)
    try:
        print(json.dumps(nav.go_to((args.x, args.y), args.timeout)))
    except LeaseLost as exc:
        print(json.dumps({"status": "interrupted", "why": str(exc), "gate": exc.code, "reason": exc.reason}))
        sys.exit(4)
    finally:
        nav.close()
        if runlog:
            runlog.finish()


if __name__ == "__main__":
    main()
