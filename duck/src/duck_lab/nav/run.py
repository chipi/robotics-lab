"""Drive the duck to goals: the navigator's loop around the pure functions (RFC-0002 §3.8).

    uv run duck-go 1.5 0.5            # one goal in map coordinates, simulator sockets
    uv run duck-go 1.5 0.5 --log run.jsonl

Loop at 10 Hz: pose = map ← odom (frames.py) on the latest odometry; twist from follow.step; robot.move
with every tick (the deadman wants one every 100 ms); replan on a fresh map.grid every few seconds.
Reflex on each depth frame: something closer than STOP_MM ahead while walking forward → stop, survey
(the stop puts the obstacle in the map), replan. Every stop ends with an explicit zero move: robotd
keeps the last request after its deadman trips, and mapd then never sees a stop (PHASE0-SPIKE.md §3).
"""

import argparse
import json
import math
import socket
import threading
import time
from pathlib import Path

from duck_lab.nav.cliff import drop_points, obstacle_points
from duck_lab.nav.client import SIM, Rpc, StateStream, odom_pose
from duck_lab.nav.follow import FollowState, Twist, step
from duck_lab.nav.frames import Localizer
from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, LETHAL_COST, LETHAL_M, MARGIN_COST, CostGrid, EmptyMap, clearance, keep_current, path_length, plan, thin

TICK_S = 0.1
REPLAN_S = 3.0
# A leg whose planned path has not got PROGRESS_M shorter in NO_PROGRESS_S ends as "stalled": trial 6
# spent three 60 s timeouts following an unseen wall in search of a door that was not there. Path
# length, not straight-line distance, so a detour that first leads away is still progress.
PROGRESS_M = 0.10
NO_PROGRESS_S = 15.0
FOLLOW_SPACING_M = 0.10
STOP_MM = 250            # depth reflex distance, central columns
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
SURVEY_TIMEOUT_S = 8.0
VALID_STATUS = {5, 9}    # ST's "range valid" statuses


class TofStream:
    """tof.stream in a thread; keeps the nearest valid distance in the central columns."""

    def __init__(self, path: Path):
        self.nearest_mm = None
        self.frames = 0
        self.last = None
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
        return r["trunk"][0], r["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


CALIBRATION = Path(__file__).resolve().parents[3] / "calibration"


def load_scale(robot: str | None) -> float:
    """The robot's odometry scale (calibration/<robot>.json), 1.0 when none is given."""
    if not robot:
        return 1.0
    return float(json.loads((CALIBRATION / f"{robot}.json").read_text())["odom_scale"])


class Navigator:
    def __init__(self, sim_dir: Path = SIM, truth: bool = True, log: Path | None = None,
                 calibration: str | None = "sim"):
        # Odometry, mapd's poses and mapd's grid all come from robotd's odometry; one scale corrects
        # all three, so the map and the pose stay in the same (true) metres. The map's origin is its
        # first stop, so scaling about it keeps the duck where it is.
        self.scale = load_scale(calibration)
        self.loc = Localizer()
        self.robot = Rpc(sim_dir / "duck-a.sock")
        self.mapd = Rpc(sim_dir / "duck-a-map.sock")
        self.state = StateStream(sim_dir / "duck-a.sock", hz=20,
                                 on_state=lambda s: self.loc.on_odom(s["t_ns"], self._scaled(odom_pose(s))))
        self.tof = TofStream(sim_dir / "duck-a-tof.sock")
        self.body = Body() if truth else None
        self._log = open(log, "a") if log else None
        self._t0 = time.monotonic()
        self.blocked = []    # what the depth sensor saw as obstacles, in map metres
        self._seen = set()   # the memory's points, on a LAYER_SPACING_M grid (no duplicates)
        self._drop_streak = 0
        self._drop_frame = None
        self.drops = []      # where the cliff check found no floor, in map metres
        self.abort = None    # set by a watchdog (a test's truth guard): stop now, with this reason

    def _scaled(self, pose: tuple) -> tuple:
        return pose[0] * self.scale, pose[1] * self.scale, pose[2]

    def move(self, tw: Twist) -> None:
        self.robot.call("robot.move", {"vx": tw.vx, "vy": 0.0, "vyaw": tw.vyaw})

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
        return CostGrid.from_map_grid(g)

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

    def forget_blocked_near(self, pose: tuple, radius_m: float) -> int:
        """Nav2's "clear around the robot" recovery, for the obstacle memory only: mapd's map stays, and
        drops are never forgotten (trial 3 fell when drop memory was switched off)."""
        keep = [b for b in self.blocked if math.dist(b, pose[:2]) >= radius_m]
        gone = len(self.blocked) - len(keep)
        self.blocked = keep
        self._seen = {(round(b[0] / LAYER_SPACING_M), round(b[1] / LAYER_SPACING_M)) for b in keep}
        return gone

    def record(self, **row) -> None:
        if self._log:
            row["t"] = round(time.monotonic() - self._t0, 3)
            if self.body:
                row["truth"] = [round(v, 4) for v in self.body.pose()]
                row["truth_z"] = round(self.body.height, 4)
            self._log.write(json.dumps(row) + "\n")
            self._log.flush()

    def go_to(self, goal: tuple, timeout_s: float = 90.0) -> dict:
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
                self.record(event="aborted", why=self.abort)
                return {"status": "aborted", "why": self.abort}
            now = time.monotonic()
            pose = self.loc.pose()
            if path is None or now - planned_at > REPLAN_S:
                try:
                    grid = self.grid()
                except EmptyMap:
                    self.survey()
                    continue
                grid = grid.covering([pose[:2], goal] + self.blocked + self.drops).with_blocked(self.blocked)
                grid = grid.with_blocked(self.drops, DROP_LETHAL_M, DROP_INFLATE_M)
                raw = plan(grid, pose[:2], goal)
                if raw is None:
                    self.move(Twist())
                    start_cost, goal_cost = grid.at(*grid.cell(*pose[:2])), grid.at(*grid.cell(*goal))
                    self.record(event="refused", goal=goal, pose=pose,
                                start_cost=start_cost, goal_cost=goal_cost,
                                drops=[[round(v, 2) for v in d] for d in self.drops],
                                blocked=[[round(v, 2) for v in b] for b in self.blocked])
                    boxed = start_cost >= LETHAL_COST and goal_cost < LETHAL_COST
                    why = "start boxed in" if boxed else "no path on the map"
                    return {"status": "refused", "why": why, "time_s": round(now - start, 1)}
                ahead = following[st.target_index:] if following else []
                if keep_current(grid, ahead, pose, raw):
                    path = ahead
                    self.record(event="plan_kept", pose=pose, goal=goal)
                else:
                    # 10 cm waypoints: at the old 30 cm the lookahead landed 0.3-0.6 m ahead and cut bends.
                    path = thin(raw, FOLLOW_SPACING_M)
                    self.record(event="plan", pose=pose, goal=goal, path=[[round(v, 2) for v in q] for q in path[:24:3]])
                following, planned_at, costs = path, now, grid
                left = path_length([pose[:2]] + path)
                if left < best_left - PROGRESS_M:
                    best_left, best_at = left, now
                elif now - best_at > NO_PROGRESS_S:
                    self.move(Twist())
                    self.record(event="stalled", goal=goal, pose=pose, path_left_m=round(left, 2),
                                best_left_m=round(best_left, 2))
                    return {"status": "stalled", "why": f"{NO_PROGRESS_S:.0f} s without getting closer",
                            "time_s": round(now - start, 1), "reflex_stops": reflex_stops}
                st.target_index = 0
            near = costs.inside(*costs.cell(*pose[:2])) and costs.at(*costs.cell(*pose[:2])) >= MARGIN_COST
            nearest_drop = min((math.dist(pose[:2], d) for d in self.drops), default=math.inf)
            room = clearance(costs, pose[:2], PIVOT_OBSTACLE_M)
            pivot_ok = room >= PIVOT_OBSTACLE_M and nearest_drop >= PIVOT_DROP_M
            tw, done = step(path, pose, now, st, near=near, pivot_ok=pivot_ok)
            if done:
                self.move(Twist())
                self.record(event="reached", goal=goal, pose=pose)
                return {"status": "reached", "time_s": round(now - start, 1), "reflex_stops": reflex_stops,

                        "pose": [round(v, 3) for v in pose]}
            pts = []
            if self.tof.last is not None and self.state.latest is not None:
                pts = drop_points(self.tof.last, self.state.latest)
                if self.tof.last is not self._drop_frame:      # count frames, not ticks
                    self._drop_frame = self.tof.last
                    self._drop_streak = self._drop_streak + 1 if pts else 0
                if self._drop_streak < DROP_FRAMES:
                    pts = []
                seen = obstacle_points(self.tof.last, self.state.latest, within_m=LAYER_M)
                new = self._remember(seen, pose)
                ahead = path[st.target_index:] if path else []
                if new and any(math.dist(q, w) < LETHAL_M + 0.05 for q in new for w in ahead):
                    self.record(event="replan_new_obstacle", points=len(new), pose=pose)
                    path = None
                    continue
            if tw.vx > 0 and pts and min(p[2] for p in pts) < CLIFF_STOP_M:
                self.move(Twist())
                c, s_ = math.cos(pose[2]), math.sin(pose[2])
                for ax, ay, h in pts:
                    for extra in (0.0,) + BEYOND_M:
                        k = (h + extra) / h if h > 0 else 1.0
                        self.drops.append((pose[0] + k * (c * ax - s_ * ay), pose[1] + k * (s_ * ax + c * ay)))
                self.record(event="cliff_stop", drop_m=round(min(p[2] for p in pts), 3), zones=len(pts), pose=pose,
                            drops=[[round(v, 2) for v in d] for d in self.drops])
                self.survey()
                path = None
                continue
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose) and \
                    room >= TIGHT_PIVOT_M and nearest_drop >= PIVOT_DROP_M:
                # Nav2's spin recovery with a collision check, by the tick: in a squeeze (exploration
                # trial 7, wedged by a cabinet) pivot anyway while the room stays above TIGHT_PIVOT_M.
                tw, done = step(path, pose, now, st, near=near, pivot_ok=True)
                if not tight:
                    tight = True
                    self.record(event="tight_pivot", pose=pose, room_m=round(room, 3), nearest_mm=self.tof.nearest_mm)
            if st.turning and tw.vx > 0 and not self._arc_clear(costs, pose):
                self.move(Twist())
                self.record(event="refused", why="no room to turn", pose=pose, room_m=round(room, 3),
                            nearest_drop_m=round(nearest_drop, 3), nearest_mm=self.tof.nearest_mm,
                            blocked=[[round(v, 2) for v in b] for b in self.blocked if math.dist(b, pose[:2]) < 0.5],
                            drops=[[round(v, 2) for v in d] for d in self.drops],
                            path=[[round(v, 2) for v in q] for q in (path or [])[:8]])
                return {"status": "refused", "why": f"no room to turn ({room:.2f} m to an obstacle, "
                        f"{nearest_drop:.2f} m to a drop)", "time_s": round(now - start, 1)}
            near = self.tof.nearest_mm
            if tw.vx > 0 and near is not None and near < STOP_MM:
                reflex_stops += 1
                self.move(Twist())
                seen = obstacle_points(self.tof.last, self.state.latest) if self.state.latest else []
                self._remember(seen, pose)
                if not seen:   # no geometry (no state yet): the nearest return straight ahead
                    ahead = near / 1000.0
                    self.blocked.append((pose[0] + ahead * math.cos(pose[2]), pose[1] + ahead * math.sin(pose[2])))
                self.record(event="reflex_stop", nearest_mm=near, pose=pose)
                self.survey()
                path = None
                continue
            self.move(tw)
            self.record(pose=[round(v, 4) for v in pose], vx=tw.vx, vyaw=round(tw.vyaw, 3), nearest_mm=near,
                        turning=st.turning)
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
    args = ap.parse_args()
    nav = Navigator(log=args.log)
    try:
        print(json.dumps(nav.go_to((args.x, args.y), args.timeout)))
    finally:
        nav.close()


if __name__ == "__main__":
    main()
