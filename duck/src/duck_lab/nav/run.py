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

from duck_lab.nav.client import SIM, Rpc, StateStream, odom_pose
from duck_lab.nav.follow import FollowState, Twist, step
from duck_lab.nav.frames import Localizer
from duck_lab.nav.grid import CostGrid, EmptyMap, plan, thin

TICK_S = 0.1
REPLAN_S = 3.0
STOP_MM = 250            # depth reflex distance, central columns
SURVEY_TIMEOUT_S = 8.0
VALID_STATUS = {5, 9}    # ST's "range valid" statuses


class TofStream:
    """tof.stream in a thread; keeps the nearest valid distance in the central columns."""

    def __init__(self, path: Path):
        self.nearest_mm = None
        self.frames = 0
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
        return r["trunk"][0], r["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


class Navigator:
    def __init__(self, sim_dir: Path = SIM, truth: bool = True, log: Path | None = None):
        self.loc = Localizer()
        self.robot = Rpc(sim_dir / "duck-a.sock")
        self.mapd = Rpc(sim_dir / "duck-a-map.sock")
        self.state = StateStream(sim_dir / "duck-a.sock", hz=20,
                                 on_state=lambda s: self.loc.on_odom(s["t_ns"], odom_pose(s)))
        self.tof = TofStream(sim_dir / "duck-a-tof.sock")
        self.body = Body() if truth else None
        self._log = open(log, "a") if log else None
        self._t0 = time.monotonic()

    def move(self, tw: Twist) -> None:
        self.robot.call("robot.move", {"vx": tw.vx, "vy": 0.0, "vyaw": tw.vyaw})

    def fix(self) -> bool:
        st = self.mapd.call("map.status")
        pose = (st.get("state") or {}).get("pose")
        t_ns = (st.get("state") or {}).get("t_ns")
        return bool(pose and t_ns and self.loc.on_fix(t_ns, (pose["x"], pose["y"], pose["yaw"])))

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
        return CostGrid.from_map_grid(self.mapd.call("map.grid", {"res_m": 0.1}))

    def record(self, **row) -> None:
        if self._log:
            row["t"] = round(time.monotonic() - self._t0, 3)
            if self.body:
                row["truth"] = [round(v, 4) for v in self.body.pose()]
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
            now = time.monotonic()
            pose = self.loc.pose()
            if path is None or now - planned_at > REPLAN_S:
                try:
                    grid = self.grid()
                except EmptyMap:
                    self.survey()
                    continue
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
            near = self.tof.nearest_mm
            if tw.vx > 0 and near is not None and near < STOP_MM:
                reflex_stops += 1
                self.move(Twist())
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
