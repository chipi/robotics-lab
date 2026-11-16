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
from duck_lab.nav.cliff import blocking_ahead, depth_points, drop_points, extend_edge, obstacle_points
from duck_lab.nav.client import SIM, Rpc, StateStream, odom_pose
from duck_lab.nav.follow import FollowState, Twist, step
from duck_lab.nav.frames import Localizer
from duck_lab.nav.runlog import JOINTS, RunLog, add_args, open_from_args
from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, LETHAL_COST, LETHAL_M, MARGIN_COST, CostGrid, EmptyMap, clearance, keep_current, path_length, plan, thin

TICK_S = 0.1
REPLAN_S = 3.0
# A leg whose planned path has not got PROGRESS_M shorter in NO_PROGRESS_S ends as "stalled": trial 6
# spent three 60 s timeouts following an unseen wall in search of a door that was not there. Path
# length, not straight-line distance, so a detour that first leads away is still progress.
PROGRESS_M = 0.10
NO_PROGRESS_S = 15.0
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
# No room for either: a pivot is still allowed while the clearance stays above this, rechecked every tick
# - 2.5 cm more than the 8.3 cm footprint radius. Below it the duck stands and the leg is refused.
TIGHT_PIVOT_M = 0.11
BEYOND_M = (0.1, 0.2, 0.3, 0.4)   # a drop's hole continues behind its edge
EDGE_EXTEND_M = 0.15
FLOOR_CELL_M = 0.05
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

    def pose(self) -> tuple:
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
                 calibration: str | None = "sim", runlog: RunLog | None = None):
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
        self.robot = Rpc(sim_dir / "duck-a.sock")
        self.mapd = Rpc(sim_dir / "duck-a-map.sock")
        self.state = StateStream(sim_dir / "duck-a.sock", hz=20, on_state=self._on_state)
        self.tof = TofStream(sim_dir / "duck-a-tof.sock")
        self.body = Body() if truth else None
        self._log = open(log, "a") if log else None
        self.blocked = []    # what the depth sensor saw as obstacles, in map metres
        self._seen = set()   # the memory's points, on a LAYER_SPACING_M grid (no duplicates)
        self._drop_streak = 0
        self._drop_frame = None
        self._depth = None       # the newest depth frame's returns in map metres, for the next tick record
        self._block = None       # how far ahead an obstacle sits in the duck's corridor (newest frame)
        # Floor the depth sensor itself has seen, as FLOOR_CELL_M cells: mapd draws a stairwell as free
        # floor (upstream #599), and exploration trial 10 took a target inside one.
        self.floor_seen = set()
        self._map_raw = None     # mapd's last grid (scaled), for the world record
        self._world_key = None
        self.tof.on_frame = self._on_frame
        self.drops = []      # where the cliff check found no floor, in map metres
        self.abort = None    # set by a watchdog (a test's truth guard): stop now, with this reason
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
        return self._remember(obstacle_points(fv.frame, fv.state, within_m=LAYER_M), fv.pose or tick_pose)

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
            for ax, ay, _, kind in fv.rel:
                if kind == "floor":
                    x, y = pose[0] + c * ax - s_ * ay, pose[1] + s_ * ax + c * ay
                    self.floor_seen.add((round(x / FLOOR_CELL_M), round(y / FLOOR_CELL_M)))
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

    def floor_seen_near(self, xy: tuple, radius_m: float = FLOOR_NEAR_M) -> bool:
        """Has the depth sensor seen floor within radius_m of xy?"""
        cx, cy = round(xy[0] / FLOOR_CELL_M), round(xy[1] / FLOOR_CELL_M)
        r = math.ceil(radius_m / FLOOR_CELL_M)
        return any((cx + dx, cy + dy) in self.floor_seen for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                   if math.hypot(dx, dy) * FLOOR_CELL_M <= radius_m)

    def _arc_clear(self, costs: CostGrid, pose: tuple) -> bool:
        """Clear floor for a slow turn while walking: the depth sensor, the grid and the drop memory."""
        near = self.tof.nearest_mm
        if near is None or near < ARC_CLEAR_MM:
            return False
        ahead = (pose[0] + ARC_AHEAD_M * math.cos(pose[2]), pose[1] + ARC_AHEAD_M * math.sin(pose[2]))
        c = costs.cell(*ahead)
        if costs.inside(*c) and costs.at(*c) >= LETHAL_COST:
            return False
        for d in self.drops:
            dist = math.dist(pose[:2], d)
            bearing = math.atan2(d[1] - pose[1], d[0] - pose[0]) - pose[2]
            if dist < CLIFF_STOP_M and math.cos(bearing) > math.cos(math.radians(60)):
                return False
        return True

    def _record_world(self) -> None:
        """The world model as the planner saw it, for the viewer (duck-world): mapd's grid and the
        remembered obstacles and drops, whenever any of them changed."""
        g = self._map_raw
        if not g:
            return
        key = (hash(g["cells"]), g["width"], g["height"], len(self.blocked), len(self.drops))
        if key == self._world_key:
            return
        self._world_key = key
        self.record(event="world", grid={k: g[k] for k in ("res_m", "origin", "width", "height", "cells")},
                    blocked=[[round(v, 3) for v in b] for b in self.blocked],
                    drops=[[round(v, 3) for v in d] for d in self.drops])

    def forget_blocked_near(self, pose: tuple, radius_m: float) -> int:
        """Nav2's "clear around the robot" recovery, for the obstacle memory only: mapd's map stays, and
        drops are never forgotten (trial 3 fell when drop memory was switched off)."""
        keep = [b for b in self.blocked if math.dist(b, pose[:2]) >= radius_m]
        gone = len(self.blocked) - len(keep)
        self.blocked = keep
        self._seen = {(round(b[0] / LAYER_SPACING_M), round(b[1] / LAYER_SPACING_M)) for b in keep}
        return gone

    def record(self, **row) -> None:
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
        following = None     # the path being followed; a replan keeps it unless it is blocked or much longer
        tight = False        # a tight pivot was logged this leg
        reflex_stops = 0
        best_left, best_at = math.inf, start
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
                grid = grid.covering([pose[:2], goal] + self.blocked + self.drops).with_points(self.blocked)
                grid = grid.with_blocked(self.drops, DROP_LETHAL_M, DROP_INFLATE_M)
                raw = plan(grid, pose[:2], goal)
                if raw is None:
                    self.move(Twist())
                    start_cost, goal_cost = grid.at(*grid.cell(*pose[:2])), grid.at(*grid.cell(*goal))
                    boxed = start_cost >= LETHAL_COST and goal_cost < LETHAL_COST
                    why = "start boxed in" if boxed else "no path on the map"
                    self.record(event="refused", goal=goal, pose=pose,
                                start_cost=start_cost, goal_cost=goal_cost,
                                drops=[[round(v, 2) for v in d] for d in self.drops],
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
                if left < best_left - PROGRESS_M:
                    best_left, best_at = left, now
                elif now - best_at > NO_PROGRESS_S:
                    self.move(Twist())
                    self.record(event="stalled", goal=goal, pose=pose, path_left_m=round(left, 2),
                                best_left_m=round(best_left, 2),
                                decision=decision("stalled", f"{NO_PROGRESS_S:.0f} s without getting closer",
                                                  path_left_m=round(left, 2), best_left_m=round(best_left, 2),
                                                  progress_m=PROGRESS_M, no_progress_s=NO_PROGRESS_S))
                    return {"status": "stalled", "why": f"{NO_PROGRESS_S:.0f} s without getting closer",
                            "time_s": round(now - start, 1), "reflex_stops": reflex_stops}
                st.target_index = 0
            near = costs.inside(*costs.cell(*pose[:2])) and costs.at(*costs.cell(*pose[:2])) >= MARGIN_COST
            nearest_drop = min((math.dist(pose[:2], d) for d in self.drops), default=math.inf)
            room = clearance(costs, pose[:2], PIVOT_OBSTACLE_M)
            pivot_ok = room >= PIVOT_OBSTACLE_M and nearest_drop >= PIVOT_DROP_M
            tw, done = step(path, pose, now, st, near=near, pivot_ok=pivot_ok, pivot_vx=self.pivot_vx)
            self.sense = {"room_m": round(room, 3), "turning": int(st.turning)}
            if done:
                self.move(Twist())
                self.record(event="reached", goal=goal, pose=pose)
                return {"status": "reached", "time_s": round(now - start, 1), "reflex_stops": reflex_stops,

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
                self.drops.extend(extend_edge(edge, EDGE_EXTEND_M))
                self.record(event="cliff_stop", drop_m=round(min(p[2] for p in pts), 3), zones=len(pts), pose=pose,
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            decision=decision("cliff_stop", f"a drop ahead seen in {self._drop_streak} frames in a row",
                                              drop_m=round(min(p[2] for p in pts), 3), stop_m=CLIFF_STOP_M, zones=len(pts),
                                              streak=self._drop_streak, frames_needed=DROP_FRAMES, vx=tw.vx))
                self.survey()
                path = None
                continue
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose) and \
                    room >= TIGHT_PIVOT_M and nearest_drop >= PIVOT_DROP_M:
                # Nav2's spin recovery with a collision check, by the tick: in a squeeze (exploration
                # trial 7, wedged by a cabinet) pivot anyway while the room stays above TIGHT_PIVOT_M.
                tw, done = step(path, pose, now, st, near=near, pivot_ok=True, pivot_vx=self.pivot_vx)
                if not tight:
                    tight = True
                    self.record(event="tight_pivot", pose=pose, room_m=round(room, 3), nearest_mm=self.tof.nearest_mm,
                                decision=decision("tight_pivot", "no clear floor for an arc; pivoting while the room lasts",
                                                  room_m=round(room, 3), min_room_m=TIGHT_PIVOT_M,
                                                  nearest_drop_m=round(nearest_drop, 3), drop_clear_m=PIVOT_DROP_M,
                                                  nearest_mm=self.tof.nearest_mm, arc_clear_mm=ARC_CLEAR_MM))
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose):
                self.move(Twist())
                self.record(event="refused", why="no room to turn", pose=pose, room_m=round(room, 3),
                            nearest_drop_m=round(nearest_drop, 3), nearest_mm=self.tof.nearest_mm,
                            blocked=[[round(v, 2) for v in b] for b in self.blocked if math.dist(b, pose[:2]) < 0.5],
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            path=[[round(v, 2) for v in q] for q in (path or [])[:8]],
                            decision=decision("refused", "no room to turn", room_m=round(room, 3), min_room_m=TIGHT_PIVOT_M,
                                              nearest_drop_m=round(nearest_drop, 3), drop_clear_m=PIVOT_DROP_M,
                                              nearest_mm=self.tof.nearest_mm, arc_clear_mm=ARC_CLEAR_MM))
                return {"status": "refused", "why": f"no room to turn ({room:.2f} m to an obstacle, "
                        f"{nearest_drop:.2f} m to a drop)", "time_s": round(now - start, 1)}
            near = self.tof.nearest_mm
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
                path = None
                continue
            self.move(tw, nearest_mm=near, turning=st.turning)
            if int(now / 1.0) != int((now - TICK_S) / 1.0):
                self.fix()
            time.sleep(max(0.0, TICK_S - (time.monotonic() - now)))
        self.move(Twist())
        return {"status": "timeout", "time_s": timeout_s, "reflex_stops": reflex_stops,
                "pose": [round(v, 3) for v in self.loc.pose()]}

    def close(self) -> None:
        self.move(Twist())
        self.state.close()
        self.tof.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("x", type=float)
    ap.add_argument("y", type=float)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--timeout", type=float, default=90.0)
    add_args(ap)
    args = ap.parse_args()
    stamp = time.strftime("go-%Y%m%d-%H%M%S")
    runlog = open_from_args(args, args.log.stem if args.log else stamp, "go-to", args.log.parent if args.log else None)
    nav = Navigator(log=args.log, runlog=runlog)
    try:
        print(json.dumps(nav.go_to((args.x, args.y), args.timeout)))
    finally:
        nav.close()
        if runlog:
            runlog.finish()


if __name__ == "__main__":
    main()
