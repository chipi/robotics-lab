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

from duck_lab.nav.cliff import drop_points
from duck_lab.nav.client import SIM, Rpc, StateStream, odom_pose
from duck_lab.nav.follow import FollowState, Twist, step
from duck_lab.nav.frames import Localizer
from duck_lab.nav.grid import CostGrid, EmptyMap, plan, thin

TICK_S = 0.1
REPLAN_S = 3.0
STOP_MM = 250            # depth reflex distance, central columns
CLIFF_STOP_M = 0.45      # a drop this close ahead (horizontal) stops the duck
# A turn on the spot shifts the duck about 8 cm (phase 0: 8 cm over a full turn at 1.2 rad/s), and the
# duck does not walk backwards reliably (-0.3 m/s: no motion; -0.4: 87 cm with a 51 deg swing). So no
# turn on the spot with a remembered drop closer than this; refuse instead. (Run 3's fall was not a
# turn: the duck walked onto the opening along a route 3 cm from its edge, with no cliff check.)
TURN_CLEAR_M = 0.2
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
        self.blocked = []    # what the depth reflex saw, in map metres
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
        g = self.mapd.call("map.grid", {"res_m": 0.1})
        if g.get("res_m"):
            g["res_m"] *= self.scale
            g["origin"] = [v * self.scale for v in g["origin"]]
        return CostGrid.from_map_grid(g)

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
        reflex_stops = 0
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
                grid = grid.covering([pose[:2], goal] + self.blocked + self.drops).with_blocked(self.blocked + self.drops)
                raw = plan(grid, pose[:2], goal)
                if raw is None:
                    self.move(Twist())
                    self.record(event="refused", goal=goal, pose=pose)
                    return {"status": "refused", "why": "no path on the map", "time_s": round(now - start, 1)}
                path, planned_at = thin(raw), now
                st.target_index = 0
            tw, done = step(path, pose, now, st)
            if done:
                self.move(Twist())
                self.record(event="reached", goal=goal, pose=pose)
                return {"status": "reached", "time_s": round(now - start, 1), "reflex_stops": reflex_stops,

                        "pose": [round(v, 3) for v in pose]}
            pts = []
            if self.tof.last is not None and self.state.latest is not None:
                pts = drop_points(self.tof.last, self.state.latest)
            if tw.vx > 0 and pts and min(p[2] for p in pts) < CLIFF_STOP_M:
                self.move(Twist())
                c, s_ = math.cos(pose[2]), math.sin(pose[2])
                for ax, ay, h in pts:
                    for extra in (0.0,) + BEYOND_M:
                        k = (h + extra) / h if h > 0 else 1.0
                        self.drops.append((pose[0] + k * (c * ax - s_ * ay), pose[1] + k * (s_ * ax + c * ay)))
                self.record(event="cliff_stop", drop_m=round(min(p[2] for p in pts), 3), zones=len(pts), pose=pose)
                self.survey()
                path = None
                continue
            nearest_drop = min((math.dist(pose[:2], d) for d in self.drops), default=math.inf)
            if st.turning and nearest_drop < TURN_CLEAR_M:
                self.move(Twist())
                self.record(event="refused", why="a turn would be too close to a drop", pose=pose)
                return {"status": "refused", "why": f"a turn {nearest_drop:.2f} m from a drop",
                        "time_s": round(now - start, 1)}
            near = self.tof.nearest_mm
            if tw.vx > 0 and near is not None and near < STOP_MM:
                reflex_stops += 1
                self.move(Twist())
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
