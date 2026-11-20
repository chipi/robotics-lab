"""The duck's navigator as a payload (RFC-0021 §3): its own process, given only the robot's connections, a socket to answer
the runner on, and a folder for its own run. It names no host path, no port and never reads the simulator's truth; the
runner, which has the truth, judges it and writes the official run (runfile.truthcopy).

    duck-payload --robot R.sock --depth T.sock --map M.sock --listen P.sock --out DIR --data DATA --scene S --name N

The contract (newline JSON-RPC 2.0 on --listen; another navigator can implement the same):
  hello                         -> {name, version, kinds, scale}
  localise                      -> {pose}: its pose in its own map once it has one (a fix, else a survey), or an error
  start {kind, ...}             -> {ok}: point {goal: [x, y] in its map, time_s}; explore {minutes}
  status                        -> {state, why, pose, result}: running, then reached, refused, timeout, stalled, aborted or
                                   failed (`result`: the explorer's for explore)
  cancel {reason}               -> {ok}: the navigator stops, and its run says why
  stop                          -> {ok}: its run is closed and the process ends
One goal at a time; the navigator (its map and its memory) is kept from one start to the next."""

import argparse
import json
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.explore_score import ENDS
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import RunLog

NAME, VERSION = "duck-lab", "0.1.0"
KINDS = ("point", "explore")
TERMINAL = ("reached", "refused", "timeout", "stalled", "aborted", "failed")


class Payload:
    def __init__(self, sockets: dict, out: Path, data: Path, scene: str, name: str, variant: str | None):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.runlog = RunLog(Path(data), scene, name, "challenge", self.out)
        self.nav = Navigator(sockets, body=None, log=self.out / "ticks.jsonl", runlog=self.runlog, calibration=variant)
        self.state, self.why, self.result = "idle", None, None
        self._lock = threading.Lock()
        self.stopped = threading.Event()

    def call(self, method: str, p: dict):
        if method == "hello":
            return {"name": NAME, "version": VERSION, "kinds": list(KINDS), "scale": self.nav.scale}
        if method == "localise":
            nav = self.nav
            if nav.loc.pose() is None and not nav.fix():
                nav.survey()
            pose = nav.loc.pose()
            if pose is None:
                raise ValueError("no pose on the map after the survey")
            return {"pose": list(pose)}
        if method == "start":
            with self._lock:
                if self.state == "running":
                    raise ValueError("a goal is running")
                kind = p.get("kind")
                if kind not in KINDS:
                    raise ValueError(f"kind {kind!r}: this payload takes {list(KINDS)}")
                self.nav.abort = None
                self.state, self.why, self.result = "running", None, None
            threading.Thread(target=self._work, args=(kind, p), name=f"goal-{kind}", daemon=True).start()
            return {"ok": True}
        if method == "status":
            pose = self.nav.loc.pose()
            return {"state": self.state, "why": self.why, "result": self.result, "pose": list(pose) if pose else None}
        if method == "cancel":
            self.nav.abort = str(p.get("reason") or "cancelled by the runner")
            return {"ok": True}
        if method == "stop":
            self.close()
            return {"ok": True}
        raise KeyError(f"no method {method!r}")

    def _work(self, kind: str, p: dict) -> None:
        try:
            if kind == "point":
                out = self.nav.go_to(tuple(p["goal"][:2]), float(p["time_s"]))
                state, why, result = out.get("status", "failed"), out.get("why"), out
            else:
                ex = Explorer(self.nav, self.out)
                res = ex.run(float(p["minutes"]))
                ended = [e for e in ex.events if e.get("event") in ENDS]
                result = {**res, "end": ended[-1]["event"] if ended else "time", "end_s": ended[-1]["t"] if ended else None,
                          "why": ended[-1].get("why") if ended else None}
                state, why = "reached", None
        except Exception as e:      # noqa: BLE001 - a goal's failure is its outcome, said to the runner
            state, why, result = "failed", f"{type(e).__name__}: {e}", None
        with self._lock:
            self.result, self.why = result, why
            self.state = state if state in TERMINAL else "failed"     # last: a poll that sees it terminal sees the rest

    def close(self) -> None:
        if self.stopped.is_set():
            return
        self.stopped.set()
        try:
            self.nav.close()
        finally:
            self.runlog.finish()


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                out = {"jsonrpc": "2.0", "id": req.get("id"), "result": self.server.payload.call(req.get("method"), req.get("params") or {})}
            except Exception as e:      # noqa: BLE001 - every error is the caller's answer
                out = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}}
            self.wfile.write((json.dumps(out) + "\n").encode())
            self.wfile.flush()
            if self.server.payload.stopped.is_set():
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for k in ("robot", "depth", "map"):
        ap.add_argument(f"--{k}", type=Path, required=True, help=f"the robot's {k} socket")
    ap.add_argument("--listen", type=Path, required=True, help="the socket the runner calls")
    ap.add_argument("--out", type=Path, required=True, help="the navigator's own files (ticks.jsonl, the explorer's map)")
    ap.add_argument("--data", type=Path, required=True, help="where its own run is written (not the Observatory's data folder)")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--variant", default="sim", help="the robot profile's variant (sim, or real)")
    a = ap.parse_args()
    payload = Payload({"robot": a.robot, "depth": a.depth, "map": a.map}, a.out, a.data, a.scene, a.name,
                      None if a.variant == "real" else a.variant)
    a.listen.unlink(missing_ok=True)
    srv = Server(str(a.listen), Handler)
    srv.payload = payload
    print(f"duck-payload: listening on {a.listen}", flush=True)
    try:
        srv.serve_forever()
    finally:
        payload.close()
        a.listen.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
