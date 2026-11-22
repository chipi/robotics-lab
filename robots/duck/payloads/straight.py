"""A second payload (RFC-0021 step 5): the smallest navigator that keeps the payload's contract, to show the contract is not
ours alone. Straight to the goal on the robot's own odometry; it stops, and says so, when the depth sensor sees something
nearer than STOP_MM ahead. No map, no planner, nothing of duck_lab: the standard library, the robot's three sockets, and
the run format (runfile) for its own run, which the runner copies with the truth put in.

    python straight.py --robot R.sock --depth T.sock --map M.sock --listen P.sock --out DIR --data DATA --scene S --name N

It keeps the navigator contract as a payload (libs/runner/CONTRACT.md, as duck_lab.payload does): hello, goal.start {kind:
point, params {x, y}, conditions.done_when.within_s}, goal.status, goal.cancel, goal.break, localise, stop."""

import argparse
import json
import math
import socket
import socketserver
import sys
import threading
import time
import uuid
from pathlib import Path

from runfile import keys
from runfile.mcapio import Recorder, new_run
from runfile.navcontract import CONTRACT

STOP_MM = 300            # nearer than this ahead (the sensor's central columns): stop, refused
VALID = (5, 9)           # the depth sensor's statuses that are a measurement
REACHED_M = 0.15
TICK_S = 0.1             # 10 Hz commands: well inside robotd's deadman
CRUISE, TURN = 0.25, 0.8
ROBOT = {"name": "duck", "radius": 0.083, "height": 0.272}


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


class Lines:
    """One newline-JSON-RPC stream on a unix socket, read on a thread: the latest notification of `method` kept."""

    def __init__(self, path: Path, request: dict, method: str):
        self.latest, self.method = None, method
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.connect(str(path))
        self._f = self._sock.makefile("rw")
        self._f.write(json.dumps(request) + "\n")
        self._f.flush()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        for line in self._f:
            msg = json.loads(line)
            if msg.get("method") == self.method:
                self.latest = msg["params"]

    def close(self):
        self._sock.close()


class Straight:
    def __init__(self, a):
        self.robot = socket.socket(socket.AF_UNIX)
        self.robot.connect(str(a.robot))
        self._rf = self.robot.makefile("rw")
        self._id = 0
        self.state = Lines(a.robot, {"jsonrpc": "2.0", "id": 1, "method": "robot.subscribe", "params": {"hz": 20}}, "robot.state")
        self.depth = Lines(a.depth, {"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}, "tof.frame")
        key = keys.make_key("duck", a.scene, a.name)
        self.rec = Recorder(keys.run_dir(a.data, key), new_run(key, dict(ROBOT), a.scene, "challenge", time.time_ns(), "writer",
                                                               writer={"program": "straight", "version": "0.1.0"},
                                                               run_uuid=str(uuid.uuid4())))
        self.key = key
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.status, self.stopped = {"state": "idle", "reason": None, "result": None, "broken": None}, threading.Event()
        self.broken = self.cancelled = None

    def _now(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def move(self, vx: float, vyaw: float) -> None:
        with self.lock:
            self._id += 1
            self._rf.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": "robot.move",
                                       "params": {"vx": vx, "vy": 0.0, "vyaw": vyaw}}) + "\n")
            self._rf.flush()
            while True:
                msg = json.loads(self._rf.readline())
                if msg.get("id") == self._id:
                    return

    def pose(self):
        st = self.state.latest
        if not st or "odom" not in st:
            return None
        o = st["odom"]
        return o["position"][0], o["position"][1], o["yaw"]

    def nearest_mm(self):
        fr = self.depth.latest
        if not fr:
            return None
        rows, cols = fr["rows"], fr["cols"]
        near = [fr["distance_mm"][r * cols + c] for r in range(rows) for c in range(cols // 2 - 2, cols // 2 + 2)
                if fr["status"][r * cols + c] in VALID and fr["distance_mm"][r * cols + c] > 0]
        return min(near) if near else None

    def event(self, kind: str, text: str, **raw) -> None:
        self.rec.add(max(self._now(), self.rec.last_t), "event",
                     {"kind": kind, "text": text, "notable": True, "t_src": self._now(), "raw": raw})

    def go(self, goal, time_s: float) -> tuple:
        end = time.monotonic() + time_s
        while True:
            if self.broken:
                return "stopped_by_guardrail", self.broken["detail"]
            if self.cancelled:
                return "cancelled", self.cancelled
            p = self.pose()
            if p is None:
                time.sleep(TICK_S)
                continue
            dx, dy = goal[0] - p[0], goal[1] - p[1]
            dist = math.hypot(dx, dy)
            if dist < REACHED_M:
                return "reached", None
            if time.monotonic() > end:
                return "timeout", f"not there within {time_s:.0f} s"
            err = wrap(math.atan2(dy, dx) - p[2])
            vx, vyaw = (0.0, max(-TURN, min(TURN, 1.5 * err))) if abs(err) > 0.35 else (min(CRUISE, dist), err)
            near = self.nearest_mm()
            if vx > 0 and near is not None and near < STOP_MM:
                return "refused", f"something {near} mm ahead (under {STOP_MM} mm)"
            self.move(vx, vyaw)
            t = self._now()
            self.rec.add(max(t, self.rec.last_t), "tick", {"belief": [round(v, 4) for v in p], "truth": None, "tilt": None,
                                                           "cmd": [round(vx, 3), round(vyaw, 3)], "depth": None, "t_src": t,
                                                           "raw": {"wall_ns": time.time_ns(), "nearest_mm": near}})
            time.sleep(TICK_S)

    def run_point(self, goal, time_s: float) -> None:
        try:
            state, why = self.go(goal, time_s)
        except Exception as e:      # noqa: BLE001 - its failure is its outcome, said
            state, why = "failed", f"{type(e).__name__}: {e}"
        self.move(0.0, 0.0)
        self.event(state, f"{state} {why or ''}".strip(), goal=list(goal), why=why)
        self.status = {"state": state, "reason": why, "result": {"status": state, "why": why}, "broken": self.broken}

    METHODS = ("hello", "goal.start", "goal.status", "goal.cancel", "goal.break", "localise", "stop")

    def call(self, method: str, p: dict):
        if method not in self.METHODS:
            raise KeyError(f"no method {method!r}")
        if method == "hello":
            return {"name": "straight", "version": "0.2.0", "contract": CONTRACT, "kinds": ["point"], "camera": False,
                    "scale": 1.0}
        if method == "localise":
            for _ in range(50):
                if self.pose() is not None:
                    return {"pose": list(self.pose())}
                time.sleep(0.1)
            raise ValueError("no odometry from the robot")
        if method == "goal.start":
            if self.status["state"] == "running":
                return {"error": {"code": "busy", "message": "a goal is running"}}
            if p.get("kind") != "point":
                return {"error": {"code": "unknown_kind", "message": f"kind {p.get('kind')!r}: this payload takes ['point']"}}
            q = p.get("params") or {}
            within = float(((p.get("conditions") or {}).get("done_when") or {}).get("within_s") or 60.0)
            self.broken = self.cancelled = None
            self.status = {"state": "running", "reason": None, "result": None, "broken": None}
            threading.Thread(target=self.run_point, args=((float(q["x"]), float(q["y"])), within), daemon=True).start()
            return {"run_key": self.key}
        if method == "goal.status":
            p_ = self.pose()
            return {**self.status, "pose": list(p_) if p_ else None}
        if method == "goal.cancel":
            self.cancelled = str(p.get("reason") or "cancelled")
            return {"ok": True}
        if method == "goal.break":
            self.broken = {"name": str(p.get("name") or "guardrail"), "detail": str(p.get("detail") or "broken, says the runner")}
            return {"ok": True}
        self.close()                # stop
        return {"ok": True}

    def close(self) -> None:
        if self.stopped.is_set():
            return
        self.stopped.set()
        try:
            self.move(0.0, 0.0)
        except OSError:
            pass
        for s in (self.state, self.depth):
            s.close()
        self.rec.close()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            req = json.loads(line)
            try:
                out = {"jsonrpc": "2.0", "id": req.get("id"), "result": self.server.nav.call(req.get("method"), req.get("params") or {})}
            except Exception as e:      # noqa: BLE001
                out = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}}
            self.wfile.write((json.dumps(out) + "\n").encode())
            self.wfile.flush()
            if self.server.nav.stopped.is_set():
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for k in ("robot", "depth", "map", "listen", "out", "data"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--variant", default="sim")
    a = ap.parse_args()
    nav = Straight(a)
    a.listen.unlink(missing_ok=True)
    srv = socketserver.ThreadingUnixStreamServer(str(a.listen), Handler)
    srv.daemon_threads = True
    srv.nav = nav
    print(f"straight: listening on {a.listen}", flush=True)
    try:
        srv.serve_forever()
    finally:
        nav.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
