"""Drive the duck to goals: the navigator's loop around the pure functions (RFC-0002 §3.8).

    uv run duck-go 1.5 0.5            # one goal in map coordinates, simulator sockets
    uv run duck-go 1.5 0.5 --log run.jsonl
    uv run duck-go 1.5 0.5 --miniview-data /work/robotics-lab/data   # also written as a live miniview run (ADR-0014)

With a miniview data folder (--miniview-data or MINIVIEW_DATA) the run is also written in format 2, while it runs: that run
is the record, with every depth frame and the IMU (`duck-replay` checks it is complete); ticks.jsonl is kept during the
transition, for the importer and the older tools.

Loop at 10 Hz: pose = map ← odom (frames.py) on the latest odometry; twist from follow.step; robot.move
with every tick (the deadman wants one every 100 ms); replan on a fresh map.grid every few seconds.
Reflex on each depth frame: an obstacle in the duck's corridor within REFLEX_AHEAD_M while walking → stop, survey
(the stop puts the obstacle in the map), replan. Every stop ends with an explicit zero move: robotd
keeps the last request after its deadman trips, and mapd then never sees a stop (PHASE0-SPIKE.md §3).
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

from duck_lab.nav import cliff
from duck_lab.nav.cliff import blocking_ahead, depth_points, drop_points, low_points, obstacle_points
from duck_lab.nav.client import SIM, LeaseLost, Rpc, StateStream, odom_pose
from duck_lab.nav.follow import SLOW_CLEAR_M, FollowState, Twist, step, wrap
from duck_lab.nav.frames import Localizer
from duck_lab.nav.runlog import JOINTS, RunLog, add_args, open_from_args
from duck_lab.nav.step_check import unseen_ahead
from duck_lab.nav.stuck import MOVED_MAX_M as STUCK_MOVED_M, WINDOW_S as STUCK_WINDOW_S, StuckWatch
from duck_lab.nav.side_drops import (SuspectMemory, below_counts, continuation, continues, edge_from_glance, head_settled, in_the_way,
                                     look_targets)
from duck_lab.world_model.semantic_map import SemanticMap
from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, FREE_COST, LETHAL_COST, LETHAL_M, CostGrid, EmptyMap, clearance, keep_current, nearest_free, path_length, plan, thin

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
REFLEX_AHEAD_M = 0.30
REFLEX_HALF_W_M = 0.083 + 0.04
EMERGENCY_MM = 150
# A drop this close ahead (horizontal) stops the duck. 0.60, not 0.45: the duck then has to turn round
# where it stopped, and a turn on the spot drifts (exploration trial 5: 26 cm over 4.3 rad).
CLIFF_STOP_M = 0.60
# ... once seen in this many consecutive depth frames (15 Hz): a single frame read against a state a
# few tens of ms apart, mid-turn, put a "drop" on flat corridor floor (run 7, goal 15). A staircase
# does not vanish between frames; 3 frames is 0.2 s, ~6 cm of walking against the 45 cm stop distance.
DROP_FRAMES = 3
SNAPSHOT_S, SNAPSHOT_MOVED_M = 2.0, 0.05    # the objects re-recorded every 2 s while any moved more than 5 cm
LOW_FRAMES, LOW_CELL_M = 3, 0.05    # a low-band cell is an obstacle once this many frames saw it (sim/probes/low_persistence.py)
# After a cliff stop the duck looks along the edge, LOOK_ALONG_M past each end of what it saw (side_drops.look_targets);
# where the drop goes on there, or the look saw nothing, the hole is taken to go on CONTINUE_M past the seen end.
LOOK_ALONG_M = 0.4
CONTINUE_M = 1.0
# The obstacle layer: what the depth sensor sees this close, every tick, joins the memory, and a new
# point near the remaining path replans at once. mapd maps only at stops, so a face first seen while
# walking (the cabinet's side, passed while turning into the office: run 6's touches) was not on the map.
LAYER_M = 0.6
LAYER_SPACING_M = 0.03
# A turn on the spot shifts the duck (phase 0: 8 cm over a full turn; exploration trial 5: 26 cm over
# 4.3 rad, toward the stairs; phase 1 run 12: a contact beside the office cabinet), and the duck does
# not walk backwards (-0.15 and -0.3 m/s: no motion; -0.4: 87 cm with a 51 deg swing). So it turns on
# the spot only with room for that drift: PIVOT_DROP_M from any remembered drop and PIVOT_OBSTACLE_M
# from any obstacle (the 12 cm lethal zone and 5 cm). Otherwise it turns while walking slowly (an arc),
# and only onto clear floor: ARC_CLEAR_MM by the depth sensor, no lethal cell ARC_AHEAD_M ahead and no
# remembered drop within CLIFF_STOP_M in front. No room for either: the leg is refused.
PIVOT_DROP_M = 0.30
PIVOT_OBSTACLE_M = LETHAL_M + 0.05
ARC_CLEAR_MM = 300      # a 0.2 m radius arc (0.2 m/s at 1 rad/s) reaches ~0.2 m ahead, + the 8.3 cm footprint
ARC_AHEAD_M = 0.25
# The floor a turn while walking sweeps, for drops: the arc's reach (ARC_AHEAD_M and the footprint's 0.083 m and the
# following's error, rounded up) from just outside the heading to well round the side it turns to.
ARC_REACH_M = 0.45
ARC_OUTER_DEG, ARC_INNER_DEG = 20.0, 120.0
# No room for either: a pivot is still allowed while the clearance stays above this, rechecked every tick, once per
# spot. Below it the duck stands and the leg is refused.
TIGHT_PIVOT_M = 0.15     # was 0.11 (footprint + 2.5 cm); + the creep a pivot leaves (b7 r2, the operator 2026-11-18)
TIGHT_SPOT_M, TIGHT_GAP_S = 0.10, 0.5    # one tight pivot per spot (Navigator._tight_allowed)
BEYOND_M = (0.1, 0.2, 0.3, 0.4)   # a drop's hole continues behind its edge
FLOOR_CELL_M = 0.05
# Drop rings by what is known of the drop (docs/wip/SIDE-DROPS.md; the advisor's split, the operator's choice 2026-11-17).
# Each is the turn gate of its kind plus the following's (~3 cm) and the belief's (~2.5 cm) error, so the duck can turn
# on the spot wherever the planner may put it; each gate less the pivot's drift (max 7.9 cm over 87 pivots on 2026-11-17,
# sim/probes/turn_drift.py) keeps the judge's 0.15 m and the belief. A cliff stop's rough points: grid.DROP_LETHAL_M (0.35)
# and PIVOT_DROP_M (0.30). A drop edge a glance measured (-14/+6.4 cm aside, -18/+3 cm ahead, 54 glances): PIVOT_EDGE_M
# 0.26 and 0.32 round it, which also keeps a path held at it out of the cliff check's 0.25 m corridor (0.305 with the
# errors). 0.22 put such a path inside that corridor: the duck was stopped for the edge it had measured, and stood where
# it was not allowed to turn. A suspected drop (side_drops.SuspectMemory) costs what it becomes when a glance confirms it
# (a smaller ring, 0.25, let the duck walk where the confirmed ring then put it inside, unable to turn: challenge 11 seed
# 1); one within CONFIRM_M triggers that glance, and a false one that closes the way is looked at, not refused for.
PIVOT_EDGE_M = 0.26
EDGE_LETHAL_M = 0.32
EDGE_INFLATE_M = 0.50
SUSPECT_LETHAL_M = EDGE_LETHAL_M
SUSPECT_INFLATE_M = EDGE_INFLATE_M
CONFIRM_M = 0.9
# a goal inside a drop's ring is held off at the nearest place out of it this near; farther, it is across the drop
# (challenges 8 and 9: refused). Under the judge's REACHED_M 0.25 with room for the following.
HOLD_OFF_M = 0.20
HOLD_DETOUR = 1.25         # and only on this side of the drop: the way there no longer than this times the straight line, + 0.3 m
GLANCED_M = 0.4              # a suspicion this near one already looked at is not looked at again
# A suspicion this near a measured edge is that drop going on, confirmed without a look (challenge 10 seed 1 looked 7
# times walking along one ledge); new suspicions join one by one as the duck walks, so the drop grows along its length.
ABSORB_M = 0.15
LOOK_FLOOR_Z_M = -0.116      # the floor in the trunk frame (stand height), where the glance aims
LOOK_SETTLE_FRAMES, LOOK_YAW_TOL_DEG = 5, 3.0   # the sensor's yaw held this still over this many frames: the head is there
LOOK_MAX_S, LOOK_COLLECT_S, HEAD_BACK_S = 3.0, 1.0, 2.0
HEAD_JOINTS = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
HEAD_WALK_CMD = dict.fromkeys(HEAD_JOINTS, 0.0)    # robotd's default head command: how the duck walks when nothing moves the head
FLOOR_NEAR_M = 0.10      # an explorer's target needs floor seen by the depth sensor this close   # and along it, past what one stop saw (longer would close the gaps beside the stairs)
SURVEY_TIMEOUT_S = 8.0
VALID_STATUS = {5, 9}    # ST's "range valid" statuses
STATE_KEEP = 40          # robot states held to pair depth frames with: two seconds at 20 Hz (autod holds the last second)


def decision(rule: str, reason: str, **values) -> dict:
    """A rule that fired, for the log (ADR-0014): which rule, why, and the numbers it compared with its thresholds."""
    return {"rule": rule, "reason": reason, "values": values}


class FrameView:
    """One depth frame, the robot state it was paired with and what the navigator makes of it, derived once: the points
    (map metres, for the viewer and the floor memory), the drop points, the blocking distance. Everything that reads the
    frame (the cliff check, the reflex, the obstacle memory, the log) reads this, so what is logged is what was used."""

    def __init__(self, frame: dict, state: dict | None, dt_ms: float | None, pose: tuple | None):
        self.frame, self.state, self.dt_ms, self.pose = frame, state, dt_ms, pose
        self.rel = self.drops = self.block = self.points = None
        self.ok = False
        if state is None:
            return
        try:
            self.rel = depth_points(frame, state)
            self.drops = drop_points(frame, state)
        except (KeyError, TypeError, ValueError):
            return
        self.ok = True
        self.block = blocking_ahead(self.rel, REFLEX_HALF_W_M)
        if pose is not None:
            c, s_ = math.cos(pose[2]), math.sin(pose[2])
            self.points = [[round(pose[0] + c * ax - s_ * ay, 3), round(pose[1] + s_ * ax + c * ay, 3), round(z, 3), kind[0]]
                           for ax, ay, z, kind in self.rel]

    def payload(self) -> dict:
        """The depth_frame record (miniview.wire): the raw frame, its times, the paired state's replay fields, the pose and
        what was derived."""
        fr = self.frame
        p = {"rows": fr["rows"], "cols": fr["cols"], "distance_mm": list(fr["distance_mm"]), "status": list(fr["status"]),
             "frame_t_ns": int(fr.get("t_ns") or 0), "seq": fr.get("seq")}
        if self.state is not None and "t_ns" in self.state:
            p["state_t_ns"] = int(self.state["t_ns"])
            if self.dt_ms is not None:
                p["pair_dt_ms"] = round(self.dt_ms, 3)
        if self.ok:
            st = self.state
            p["state"] = {"quat": list(st["imu"]["quat"]), "odom_z": st["odom"]["position"][2],
                          "tof": {"pos": list(st["frames"]["tof"]["pos"]), "quat": list(st["frames"]["tof"]["quat"])}}
            if self.pose is not None:
                p["pose"] = list(self.pose[:3])          # as it was used, not rounded: a replay places the points with it
                p["derived"] = {"points": self.points, "drop_points": [list(d) for d in self.drops]}
                if self.block is not None:
                    p["derived"]["block_m"] = self.block
        return p


class TofStream:
    """tof.stream in a thread; keeps the nearest valid distance in the central columns."""

    def __init__(self, path: Path):
        self.nearest_mm = None
        self.frames = 0
        self.last = None
        self.on_frame = None     # called with each frame (the navigator's seen-floor memory)
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.connect(str(path))
        self._sock.settimeout(1.0)
        self._f = self._sock.makefile("rw")
        self._f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
        self._f.flush()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                line = self._f.readline()
            except (TimeoutError, socket.timeout):
                continue
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") != "tof.frame":
                continue
            fr = msg["params"]
            self.last = fr
            rows, cols = fr["rows"], fr["cols"]
            central = range(cols // 2 - 2, cols // 2 + 2)
            near = [fr["distance_mm"][r * cols + c] for r in range(rows) for c in central
                    if fr["status"][r * cols + c] in VALID_STATUS and fr["distance_mm"][r * cols + c] > 0]
            self.nearest_mm = min(near) if near else None
            self.frames += 1
            if self.on_frame:
                self.on_frame(fr)

    def close(self):
        self._stop.set()
        self._sock.close()


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


CALIBRATION = Path(__file__).resolve().parents[3] / "calibration"


def load_scale(robot: str | None) -> float:
    """The robot's odometry scale (calibration/<robot>.json), 1.0 when none is given."""
    if not robot:
        return 1.0
    return float(json.loads((CALIBRATION / f"{robot}.json").read_text())["odom_scale"])


def load_tof(robot: str | None) -> dict:
    """The robot's depth sensor as mounted (calibration/<robot>.json "tof"): {pitch_offset_deg, range}; the real duck's
    defaults (cliff.py's) when the robot or its file says nothing."""
    tof = json.loads((CALIBRATION / f"{robot}.json").read_text()).get("tof", {}) if robot else {}
    return {"pitch_offset_deg": float(tof.get("pitch_offset_deg", 3.0)), "range_kind": tof.get("range", "axial")}


def load_pivot_vx(robot: str | None) -> float:
    """The forward speed a turn on the spot is sent with (calibration/<robot>.json "pivot" "vx_mps"); 0 when the robot or
    its file says nothing. The simulator's pivot creeps forward, the real duck's backward by upstream (RFC-0008 §4)."""
    pivot = json.loads((CALIBRATION / f"{robot}.json").read_text()).get("pivot", {}) if robot else {}
    return float(pivot.get("vx_mps", 0.0))


class Navigator:
    runlog = None            # a RunLog (ADR-0014) when the run is also written as a miniview run
    watch = None             # a test's truth check (ADR-0015): called with each row that has truth; a row it returns is recorded

    def __init__(self, sim_dir: Path = SIM, truth: bool = True, log: Path | None = None,
                 calibration: str | None = "sim", runlog: RunLog | None = None,
                 robot_sock: Path | None = None, client: str | None = None):
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
        self.scale = load_scale(calibration)
        self.tof_cal = load_tof(calibration)
        cliff.configure(**self.tof_cal)
        self.pivot_vx = load_pivot_vx(calibration)
        self.loc = Localizer()
        self._t0 = time.monotonic()
        self.runlog = runlog
        self._sid = runlog.new_session() if runlog else None
        self._states = collections.deque(maxlen=STATE_KEEP)     # (t_ns, robot state), newest last: what a frame is paired with
        self._fv = None          # the newest depth frame, paired and derived (FrameView)
        self.sense = {}          # what go_to decides on this tick (room_m, turning), for the signals; empty outside go_to
        self._logging_failed = False
        self.tof = None
        self.mapd = Rpc(sim_dir / "duck-a-map.sock")
        self.state = StateStream(self.robot_sock, hz=20, on_state=self._on_state, client=client)
        self.tof = TofStream(sim_dir / "duck-a-tof.sock")
        self.body = Body() if truth else None
        self._log = open(log, "a") if log else None
        self.blocked = []    # what the depth sensor saw as obstacles, in map metres
        self._seen = set()   # the memory's points, on a LAYER_SPACING_M grid (no duplicates)
        self._low = {}       # low-band cells (LOW_CELL_M) -> the frames that saw them, until LOW_FRAMES remember them
        self._tight_spots = []   # [(x, y), last tick] of each tight pivot: one per spot (_tight_allowed)
        self._drop_streak = 0
        self._drop_frame = None
        self._depth = None       # the newest depth frame's returns in map metres, for the next tick record
        self._block = None       # how far ahead an obstacle sits in the duck's corridor (newest frame)
        # Floor the depth sensor itself has seen, as FLOOR_CELL_M cells: mapd draws a stairwell as free
        # floor (upstream #599), and exploration trial 10 took a target inside one.
        self.floor_seen = set()
        # Drops beside the way (docs/wip/SIDE-DROPS.md): suspected from the forward sensor's below-floor returns, then
        # confirmed (into drops) or cleared by a glance; the places already looked at.
        self.suspects = SuspectMemory()
        self.glanced = []
        self.step_looked = []    # spots looked at before stepping on them (step_check), not looked at again
        self._map_raw = None     # mapd's last grid (scaled), for the world record
        self._world_key = None
        self.tof.on_frame = self._on_frame
        self.drops = []      # where the cliff check found no floor, in map metres
        self.edges = []      # drop edges a glance measured (and the hole beyond them), in map metres: a smaller ring
        self.abort = None    # set by a watchdog (a test's truth guard): stop now, with this reason
        # objects (RFC-0016): off unless a camera is given (enable_objects); the challenge course runs without
        self.semantic = None
        self.room = None         # the area type the objects suggest (a guess; was "room")
        self.area, self.area_agrees = None, None    # the operator's area the pose is in, and whether the guess agrees
        self._sem_lock = threading.Lock()
        self._closing = threading.Event()
        # the sensor's mounting as this run used it, so a replay applies the same (duck-replay reads it)
        self.record(event="calibration", tof=self.tof_cal, odom_scale=self.scale, pivot_vx_mps=self.pivot_vx)

    def _scaled(self, pose: tuple) -> tuple:
        return pose[0] * self.scale, pose[1] * self.scale, pose[2]

    def move(self, tw: Twist, **extra) -> None:
        """Send a command and log it with the pose: every command, so surveys, survey turns and the
        waits after a stop are in the log too (explore12 had events there but no poses)."""
        self.robot.call("robot.move", {"vx": tw.vx, "vy": 0.0, "vyaw": tw.vyaw})
        pose = self.loc.pose()
        if pose is None:
            return
        self.record(pose=[round(v, 4) for v in pose], vx=tw.vx, vyaw=round(tw.vyaw, 3), tilt=self._tilt(),
                    **extra, **({"depth": self._depth} if self._depth else {}))
        self._depth = None

    def fix(self) -> bool:
        st = self.mapd.call("map.status")
        pose = (st.get("state") or {}).get("pose")
        t_ns = (st.get("state") or {}).get("t_ns")
        return bool(pose and t_ns and self.loc.on_fix(t_ns, self._scaled((pose["x"], pose["y"], pose["yaw"]))))

    def survey(self) -> bool:
        """Stand still with explicit zeros until mapd is collecting this stop, then a little longer."""
        t = time.monotonic()
        collecting_since = None
        while time.monotonic() - t < SURVEY_TIMEOUT_S:
            self.move(Twist())
            st = self.mapd.call("map.status")
            if (st.get("state") or {}).get("collecting"):
                collecting_since = collecting_since or time.monotonic()
                if time.monotonic() - collecting_since > 2.0:
                    break
            time.sleep(TICK_S)
        self.fix()
        return collecting_since is not None

    @staticmethod
    def _sensor_yaw(state: dict) -> float:
        """The depth sensor's yaw against the trunk (deg), from the state the frame was paired with."""
        w, x, y, z = state["frames"]["tof"]["quat"]
        return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

    @staticmethod
    def _sensor_dir(state: dict) -> tuple:
        """The depth sensor's (yaw, pitch) against the trunk (deg)."""
        w, x, y, z = state["frames"]["tof"]["quat"]
        return Navigator._sensor_yaw(state), math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))

    def glance_at(self, target: tuple, pose: tuple) -> dict:
        """Stand and look at the floor at target (map metres) with the head, to confirm or clear a suspected drop there
        (docs/wip/SIDE-DROPS.md). The head is aimed with robot.look and held by resending; frames are used once the
        sensor's own yaw has held still (the old glance read short from frames taken while the head was still turning),
        for LOOK_COLLECT_S. What it saw: floor joins floor_seen and clears the suspicions it covers; a floor boundary with
        below-floor returns beyond it (side_drops.edge_from_glance) is a drop, remembered with its edge extended. The head
        then gets back the command it had (robot.head keeps a command until told otherwise)."""
        t0 = time.monotonic()
        bearing = math.atan2(target[1] - pose[1], target[0] - pose[0])
        rel = wrap(bearing - pose[2])
        dist = math.dist(target, pose[:2])
        # robot.head is a command to the walking policy, not a joint target: under robotd's default command (zeros) the
        # head walks at neck ~13°, pitch ~20°, so sending the measured angles back pitched it further down at every
        # glance (challenge 11, 2026-11-18: neck 44°, pitch 83° after three, the odometry 10-14 % short)
        home = HEAD_WALK_CMD
        fv0 = self._fv
        yaw0 = self._sensor_yaw(fv0.state) if fv0 is not None and fv0.ok else 0.0   # where the sensor faced before
        self.glanced.append(tuple(target))
        try:
            ans = self.robot.call("robot.look", {"x": dist * math.cos(rel), "y": dist * math.sin(rel),
                                                 "z": LOOK_FLOOR_Z_M, "neck_pitch": 0.0}) or {}
        except (RuntimeError, OSError) as e:
            self.record(event="glance", decision=decision("glance", f"robot.look failed: {e}", target=list(target)))
            return {"status": "failed"}
        head = ans.get("head")
        frames, seen, dirs, settled = [], None, [], None
        while time.monotonic() - t0 < LOOK_MAX_S and (settled is None or time.monotonic() - settled < LOOK_COLLECT_S):
            if head:
                self.robot.call("robot.head", head)
            self.move(Twist())
            fv = self._fv
            if fv is not None and fv is not seen and fv.ok and fv.pose is not None:
                seen = fv
                dirs.append(self._sensor_dir(fv.state))
                if settled is None and head_settled(dirs, LOOK_SETTLE_FRAMES, LOOK_YAW_TOL_DEG):
                    settled = time.monotonic()
                if settled is not None:
                    c, s_ = math.cos(fv.pose[2]), math.sin(fv.pose[2])
                    # below-floor returns by the same range-dependent threshold as every other frame (_on_frame,
                    # side_drops.below_counts): far floor reads a few cm low, and a glance into an open room counted it
                    # (challenge 7 seed 1: floor 1.7-2.5 m away read 6-9 cm low, the glance said "drop", the start was
                    # fenced in; sim/probes/glance_distance.py)
                    frames.append([(fv.pose[0] + c * ax - s_ * ay, fv.pose[1] + s_ * ax + c * ay, kind)
                                   for ax, ay, h, kind in fv.rel
                                   if kind == "floor" or (kind == "below" and below_counts(h, math.hypot(ax, ay)))])
            time.sleep(TICK_S)
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
        # back to the walking command, held until the sensor faces as it did
        back = time.monotonic()
        while time.monotonic() - back < HEAD_BACK_S:
            self.robot.call("robot.head", home)
            self.move(Twist())
            fv = self._fv
            if fv is not None and fv.ok and abs(self._sensor_yaw(fv.state) - yaw0) < LOOK_YAW_TOL_DEG:
                break
            time.sleep(TICK_S)
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
        """After a cliff stop: look along the edge it saw, LOOK_ALONG_M past each end (side_drops.look_targets). Where the
        look's rim reaches its target, or the look saw nothing, the hole is taken to go on CONTINUE_M past the seen end
        (challenge 9's drop spans the room: the duck must still refuse); where it saw floor there, the hole ends before
        it (challenge 11's pit: the way beside it stays open). The glances' own edges join self.edges. Returns, per side,
        whether the hole was taken to go on."""
        if not edge:
            return []
        out = []
        for side, target in zip((-1, 1), look_targets(edge, heading, LOOK_ALONG_M)):
            g = self.glance_at(target, pose)
            goes_on = g.get("status") in ("failed", "unseen") or continues(g.get("rim_points") or [], target)
            if goes_on:
                self.drops.extend(continuation(edge, heading, side, CONTINUE_M))
            out.append(goes_on)
        self.record(event="edge_ends", pose=pose, goes_on=out,
                    decision=decision("edge_ends", "looked along the edge of the drop it stopped at",
                                      goes_on=out, look_along_m=LOOK_ALONG_M,
                                      continue_m=CONTINUE_M))
        return out

    def grid(self) -> CostGrid:
        g = self.mapd.call("map.grid", {"res_m": 0.05})   # mapd's finest: doorways stay open
        if g.get("res_m"):
            g["res_m"] *= self.scale
            g["origin"] = [v * self.scale for v in g["origin"]]
        self._map_raw = g
        return CostGrid.from_map_grid(g, explained_by=self.blocked)       # the clearance model: exact points over whole cells

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
        return self._remember(obstacle_points(fv.frame, fv.state, within_m=LAYER_M), pose) + \
            self._remember_low(low_points(fv.frame, fv.state, within_m=LAYER_M), pose,
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
        self.loc.on_odom(s["t_ns"], self._scaled(odom_pose(s)))
        self._states.append((s["t_ns"], s))
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
        v.update(nearest_mm=self.tof.nearest_mm if self.tof else None, block_m=fv.block if fv else None, **self.sense)
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
        state, dt_ms = self._pair(frame.get("t_ns") or 0)
        pose = None
        if state is not None:
            try:
                pose = self.loc.to_map(self._scaled(odom_pose(state)))
            except (KeyError, TypeError, ValueError):
                pass
        fv = self._fv = FrameView(frame, state, dt_ms, pose)
        if fv.ok and pose is not None:
            c, s_ = math.cos(pose[2]), math.sin(pose[2])
            seen = []
            for ax, ay, h, kind in fv.rel:
                if kind == "floor" or (kind == "below" and below_counts(h, math.hypot(ax, ay))):
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

    def _tight_allowed(self, pose: tuple, now: float) -> bool:
        """One tight pivot per spot (the operator, 2026-11-18): a turn on the spot creeps 3-4 cm the odometry does not see,
        so the belief's room is no longer the room after one (b7 r2: four tight pivots beside lm_office took it from
        0.206 to 0.034 m while it believed 0.16). A pivot going on (a tick within TIGHT_GAP_S of the last) continues;
        a new one within TIGHT_SPOT_M of an earlier one is refused, and the leg then is "no room to turn"."""
        for spot in self._tight_spots:
            if math.dist(spot[0], pose[:2]) <= TIGHT_SPOT_M:
                if now - spot[1] <= TIGHT_GAP_S:
                    spot[1] = now
                    return True
                return False
        self._tight_spots.append([tuple(pose[:2]), now])
        return True

    def _pivot_clear_of_drops(self, pose: tuple) -> bool:
        """Room to turn on the spot, as far as drops go: PIVOT_DROP_M from a cliff stop's points, PIVOT_EDGE_M from a
        measured edge (each its ring less the following's and belief's error, so the duck can turn wherever the planner
        may put it)."""
        xy = pose[:2]
        return all(math.dist(xy, d) >= PIVOT_DROP_M for d in self.drops) and \
            all(math.dist(xy, d) >= PIVOT_EDGE_M for d in self.edges)

    def _arc_clear(self, costs: CostGrid, pose: tuple, turn: float) -> bool:
        """Clear floor for a slow turn while walking, turn > 0 to the left: the depth sensor, the grid ahead (for walls:
        a cell lethal only for a drop's ring is left to the drop check) and the drop memory, where the arc sweeps: within
        ARC_REACH_M, from ARC_OUTER_DEG on the outer side to ARC_INNER_DEG on the inner side. A drop anywhere ahead vetoed
        every turn before (challenge 11 seed 1: a turn away from a pit at the side was refused)."""
        near = self.tof.nearest_mm
        if near is None or near < ARC_CLEAR_MM:
            return False
        drops = self.drops + self.edges + self.suspects.points()
        ahead = (pose[0] + ARC_AHEAD_M * math.cos(pose[2]), pose[1] + ARC_AHEAD_M * math.sin(pose[2]))
        c = costs.cell(*ahead)
        if costs.inside(*c) and costs.at(*c) >= LETHAL_COST and \
                all(math.dist(ahead, d) > DROP_LETHAL_M for d in drops):
            return False
        side = 1.0 if turn >= 0 else -1.0
        for d in drops:
            if math.dist(pose[:2], d) >= ARC_REACH_M:
                continue
            b = math.degrees(wrap(math.atan2(d[1] - pose[1], d[0] - pose[0]) - pose[2])) * side
            if -ARC_OUTER_DEG <= b <= ARC_INNER_DEG:
                return False
        return True

    def _record_world(self) -> None:
        """The world model as the planner saw it, for the viewer (duck-world): mapd's grid and the
        remembered obstacles and drops, whenever any of them changed."""
        g = self._map_raw
        if not g:
            return
        key = (hash(g["cells"]), g["width"], g["height"], len(self.blocked), len(self.drops), len(self.edges))
        if key == self._world_key:
            return
        self._world_key = key
        self.record(event="world", grid={k: g[k] for k in ("res_m", "origin", "width", "height", "cells")},
                    blocked=[[round(v, 3) for v in b] for b in self.blocked],
                    drops=[[round(v, 3) for v in d] for d in self.drops + self.edges])

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
        if self.loc.pose() is None and not self.fix():
            self.survey()
        if self.loc.pose() is None:
            return {"status": "refused", "why": "no pose on the map yet"}
        path, planned_at, st = None, 0.0, FollowState()
        stuck = StuckWatch()
        following = None     # the path being followed; a replan keeps it unless it is blocked or much longer
        tight = False        # a tight pivot was logged this leg
        reflex_stops = 0
        progress = Progress(start)
        held_at = None       # where a goal inside a drop's ring is held off at (nearest_free), once aimed at
        while time.monotonic() - start < timeout_s:
            if self.abort:
                self.move(Twist())
                self.record(event="aborted", why=self.abort, decision=decision("aborted", self.abort))
                return {"status": "aborted", "why": self.abort}
            now = time.monotonic()
            pose = self.loc.pose()
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
                grid = grid.with_blocked(self.drops, DROP_LETHAL_M, DROP_INFLATE_M)
                grid = grid.with_blocked(self.edges, EDGE_LETHAL_M, EDGE_INFLATE_M)   # edges a glance measured
                suspected = self.suspects.points()        # suspected drops: a smaller ring until a glance confirms them
                unsuspected = grid
                # a goal inside a known drop's ring: aim at the nearest place out of it, within HOLD_OFF_M (the
                # operator, 2026-11-17: go as close as is safe and say so); farther, it is across the drop: refused
                gc = unsuspected.cell(*goal)
                inside = unsuspected.inside(*gc) and unsuspected.at(*gc) >= LETHAL_COST
                aim = (nearest_free(unsuspected, goal, HOLD_OFF_M, room_m=PIVOT_OBSTACLE_M) or goal) if inside else goal
                if aim != goal and aim != held_at:
                    held_at = aim
                    self.record(event="held_off", goal=goal, aim=[round(v, 3) for v in aim],
                                decision=decision("held_off", "the goal is inside a drop's ring: going as close as is safe",
                                                  held_off_m=round(math.dist(aim, goal), 3), hold_off_max_m=HOLD_OFF_M))
                if suspected:
                    grid = grid.covering(suspected).with_blocked(suspected, SUSPECT_LETHAL_M, SUSPECT_INFLATE_M)
                raw = plan(grid, pose[:2], aim)
                if raw and aim != goal and path_length([pose[:2]] + raw) > HOLD_DETOUR * math.dist(pose[:2], aim) + 0.3:
                    # the way to the held-off place goes round the drop: that place is across it, not this side of it
                    # (challenges 8 and 9: 13 of 20 refusals would have walked 2.4-7 m round the drop instead)
                    raw = None
                if raw is None and suspected:
                    # no way with the suspicions, one without them: the ones in that way not looked at yet are to be
                    # looked at, not a reason to refuse (challenge 11 seed 3: a false one 0.15 m from the goal). Within
                    # CONFIRM_M, now; farther, walk on that way and the trigger looks when near enough to see (challenge
                    # 10 seed 5: a look from 1.4 m saw floor but cleared none of them, and the leg was refused).
                    free = plan(unsuspected, pose[:2], goal)
                    look = [p for p in in_the_way(free or [], suspected, SUSPECT_LETHAL_M)
                            if all(math.dist(p, g) > GLANCED_M for g in self.glanced)]
                    near_ = [p for p in look if math.dist(p, pose[:2]) <= CONFIRM_M]
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
                    return {"status": "refused", "why": why, "time_s": round(now - start, 1)}
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
                self.edges.extend(self.suspects.confirm_near(self.edges, ABSORB_M))
            if not st.turning:
                # RFC-0012's first trigger: a suspected drop near the way, not yet looked at: stop and look at it
                look = [p for p in self.suspects.near(pose[:2], CONFIRM_M)
                        if all(math.dist(p, g) > GLANCED_M for g in self.glanced)]
                if look:
                    self.move(Twist())
                    self.glance_at(min(look, key=lambda p: math.dist(p, pose[:2])), pose)
                    path = None
                    continue
            near = costs.inside(*costs.cell(*pose[:2])) and costs.at(*costs.cell(*pose[:2])) > FREE_COST    # in a margin ring, unknown or shadow
            nearest_drop = min((math.dist(pose[:2], d) for d in self.drops + self.edges), default=math.inf)
            room = clearance(costs, pose[:2], max(PIVOT_OBSTACLE_M, SLOW_CLEAR_M))
            pivot_ok = room >= PIVOT_OBSTACLE_M and self._pivot_clear_of_drops(pose)
            tw, done = step(path, pose, now, st, near=near, pivot_ok=pivot_ok, pivot_vx=self.pivot_vx,
                            close=room < SLOW_CLEAR_M)
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
                if new and any(math.dist(q, w) < LETHAL_M + 0.05 for q in new for w in ahead):
                    self.record(event="replan_new_obstacle", points=len(new), pose=pose,
                                decision=decision("replan_new_obstacle", "new obstacle points on the path ahead",
                                                  points=len(new), margin_m=LETHAL_M + 0.05))
                    path = None
                    continue
            if tw.vx > 0 and pts and min(p[2] for p in pts) < CLIFF_STOP_M:
                self.move(Twist())
                at = fv.pose or pose        # the drops were seen in that frame: placed with its state's pose
                c, s_ = math.cos(at[2]), math.sin(at[2])
                edge = [(at[0] + c * ax - s_ * ay, at[1] + s_ * ax + c * ay) for ax, ay, _ in pts]
                for ax, ay, h in pts:
                    for extra in (0.0,) + BEYOND_M:
                        k = (h + extra) / h if h > 0 else 1.0
                        self.drops.append((at[0] + k * (c * ax - s_ * ay), at[1] + k * (s_ * ax + c * ay)))
                self.record(event="cliff_stop", drop_m=round(min(p[2] for p in pts), 3), zones=len(pts), pose=pose,
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            decision=decision("cliff_stop", f"a drop ahead seen in {self._drop_streak} frames in a row",
                                              drop_m=round(min(p[2] for p in pts), 3), stop_m=CLIFF_STOP_M, zones=len(pts),
                                              streak=self._drop_streak, frames_needed=DROP_FRAMES, vx=tw.vx))
                self.look_along(edge, at[2], pose)
                self.survey()
                path = None
                continue
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose, tw.vyaw) and \
                    room >= TIGHT_PIVOT_M and self._pivot_clear_of_drops(pose) and self._tight_allowed(pose, now):
                # Nav2's spin recovery with a collision check, by the tick: in a squeeze (exploration
                # trial 7, wedged by a cabinet) pivot anyway while the room stays above TIGHT_PIVOT_M.
                tw, done = step(path, pose, now, st, near=near, pivot_ok=True, pivot_vx=self.pivot_vx,
                                close=room < SLOW_CLEAR_M)
                if not tight:
                    tight = True
                    self.record(event="tight_pivot", pose=pose, room_m=round(room, 3), nearest_mm=self.tof.nearest_mm,
                                decision=decision("tight_pivot", "no clear floor for an arc; pivoting while the room lasts",
                                                  room_m=round(room, 3), min_room_m=TIGHT_PIVOT_M,
                                                  nearest_drop_m=round(nearest_drop, 3), drop_clear_m=PIVOT_DROP_M, edge_clear_m=PIVOT_EDGE_M,
                                                  nearest_mm=self.tof.nearest_mm, arc_clear_mm=ARC_CLEAR_MM))
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose, tw.vyaw):
                self.move(Twist())
                self.record(event="refused", why="no room to turn", pose=pose, room_m=round(room, 3),
                            nearest_drop_m=round(nearest_drop, 3), nearest_mm=self.tof.nearest_mm,
                            blocked=[[round(v, 2) for v in b] for b in self.blocked if math.dist(b, pose[:2]) < 0.5],
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            path=[[round(v, 2) for v in q] for q in (path or [])[:8]],
                            decision=decision("refused", "no room to turn", room_m=round(room, 3), min_room_m=TIGHT_PIVOT_M,
                                              nearest_drop_m=round(nearest_drop, 3), drop_clear_m=PIVOT_DROP_M, edge_clear_m=PIVOT_EDGE_M,
                                              nearest_mm=self.tof.nearest_mm, arc_clear_mm=ARC_CLEAR_MM))
                return {"status": "refused", "why": f"no room to turn ({room:.2f} m to an obstacle, "
                        f"{nearest_drop:.2f} m to a drop)", "time_s": round(now - start, 1)}
            near = self.tof.nearest_mm
            if tw.vx > 0 and path:
                spot = unseen_ahead(path[st.target_index:], pose, self.floor_seen_at, skip=self.step_looked)
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
            blocked_ahead = self._block is not None and self._block < REFLEX_AHEAD_M
            if tw.vx > 0 and (blocked_ahead or (near is not None and near < EMERGENCY_MM)):
                reflex_stops += 1
                self.move(Twist())
                seen = obstacle_points(fv.frame, fv.state) if fv is not None and fv.ok else []
                self._remember(seen, (fv.pose or pose) if fv is not None else pose)    # placed with the frame's pose
                if not seen:   # no geometry (no state yet): the nearest return straight ahead
                    ahead = near / 1000.0
                    self.blocked.append((pose[0] + ahead * math.cos(pose[2]), pose[1] + ahead * math.sin(pose[2])))
                emergency = near is not None and near < EMERGENCY_MM
                self.record(event="reflex_stop", nearest_mm=near, block_m=self._block, pose=pose,
                            decision=decision("reflex_stop", f"a return within {EMERGENCY_MM} mm" if emergency and not blocked_ahead
                                              else f"an obstacle in the corridor within {REFLEX_AHEAD_M} m",
                                              block_m=self._block, ahead_limit_m=REFLEX_AHEAD_M, nearest_mm=near,
                                              emergency_mm=EMERGENCY_MM, corridor_half_m=REFLEX_HALF_W_M))
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
                ahead = 0.20     # beyond LETHAL_M, so the duck's own cell stays out of the point's lethal ring
                self.blocked.append((pose[0] + ahead * math.cos(pose[2]), pose[1] + ahead * math.sin(pose[2])))
                self.record(event="stuck", pose=pose, **seen,
                            decision=decision("stuck", "walking without getting anywhere", **seen,
                                              window_s=STUCK_WINDOW_S, moved_max_m=STUCK_MOVED_M))
                return {"status": "stalled", "why": "stuck: walking without moving", "time_s": round(now - start, 1),
                        **seen}
            self.move(tw, nearest_mm=near, turning=st.turning)
            if int(now / 1.0) != int((now - TICK_S) / 1.0):
                self.fix()
            time.sleep(max(0.0, TICK_S - (time.monotonic() - now)))
        self.move(Twist())
        return {"status": "timeout", "time_s": timeout_s, "reflex_stops": reflex_stops,
                "pose": [round(v, 3) for v in self.loc.pose()]}

    def enable_objects(self, camera, kinds: dict, costs: bool = False, semantic: SemanticMap | None = None,
                       area_at=None) -> None:
        """Objects (RFC-0016): every camera period, what the camera recognises joins the semantic map, placed with the
        belief taken right after the camera's truth (50 ms apart at most: 1.5 cm walking, under the camera's noise); a
        "semantic" event when an object is new or confirmed, a "room" event when the room the objects say the duck is in
        changes (mapd's last grid decides what is in sight). costs: the confirmed objects' parts join the cost map too
        (semantic_points) — off by default: the depth sensor already sees them, and a drifted copy beside the fresh
        points closed passages and fed "no room to turn" (the advisor's review; RFC-0016 §5, to be measured)."""
        self.semantic = semantic if semantic is not None else SemanticMap(kinds)     # a site's map, or a fresh one
        self.object_costs = costs
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

        recorded = {"t": 0.0, "at": {}}       # the last objects snapshot: when, and where each object was then

        def look():
            pose = self.loc.pose()
            if pose is None or self.body is None:
                return
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
            with self._sem_lock:
                changes = self.semantic.integrate(found, pose, now)
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
            return []
        seen = list(self.blocked)
        with self._sem_lock:
            return self.semantic.blocking_points(seen=seen)     # only where the depth sensor has no points

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
        self.tof.close()


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
