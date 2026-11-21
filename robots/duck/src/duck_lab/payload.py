"""The duck's navigator as a payload (RFC-0021 §3): its own process, given only the robot's connections, a socket to answer
the runner on, and a folder for its own run. It names no host path, no port and never reads the simulator's truth; the
runner, which has the truth, judges it and writes the official run (runfile.truthcopy).

    duck-payload --robot R.sock --depth T.sock --map M.sock [--camera C.sock] --listen P.sock --out DIR --data DATA --scene S --name N

The contract (newline JSON-RPC 2.0 on --listen; another navigator can implement the same):
  hello                         -> {name, version, kinds, scale, camera}
  localise                      -> {pose}: its pose in its own map once it has one (a fix, else a survey), or an error
  start {kind, ...}             -> {ok}: point {goal: [x, y] in its map, time_s}; explore {minutes, and with a camera:
                                   objects, find (a kind), site (an id in --sites), object_costs, relocalise}
  status                        -> {state, why, pose, result}: running, then reached, refused, timeout, stalled, aborted or
                                   failed (`result`: the explorer's for explore)
  cancel {reason}               -> {ok}: the navigator stops, and its run says why
  stop                          -> {ok}: its run is closed and the process ends
One goal at a time; the navigator (its map and its memory) is kept from one start to the next. An explore with objects
writes the semantic map and the inventory into --out, records the inventory in its run, and saves a site back."""

import argparse
import json
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from duck_lab.nav.camera import CameraClient
from duck_lab.nav.decision import decision
from duck_lab.nav.explore_run import Explorer
from duck_lab.nav.explore_run import ENDS
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import RunLog
from duck_lab.robot import SITES
from worldmodel.objects import load_kinds
from worldmodel.site import Site

NAME, VERSION = "duck-lab", "0.1.0"
KINDS = ("point", "explore")
TERMINAL = ("reached", "refused", "timeout", "stalled", "aborted", "failed")


class Payload:
    def __init__(self, sockets: dict, out: Path, data: Path, scene: str, name: str, variant: str | None,
                 camera: Path | None = None, sites: Path = SITES, faults: dict | None = None, client: str | None = None):
        """`faults`: the navigator's test switches, set before it localises (duck-explore's --no-fix-gate, --no-frames,
        --fix-fault, --frame-fault)."""
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.sites = Path(sites)
        self.runlog = RunLog(Path(data), scene, name, "challenge", self.out)
        self.nav = Navigator(sockets, log=self.out / "ticks.jsonl", runlog=self.runlog, calibration=variant, client=client)
        f = faults or {}
        if f.get("no_fix_gate"):
            self.nav.loc.max_jump_m = None
        if f.get("fault"):
            self.nav.fix_fault = tuple(f["fault"])
            self.nav.fault_grid = bool(f.get("fault_grid"))
        self.nav.frames_on = not f.get("no_frames")
        self.camera = CameraClient(camera) if camera else None
        self.objects_on = False
        self.site = None
        self.state, self.why, self.result = "idle", None, None
        self._lock = threading.Lock()
        self.stopped = threading.Event()

    def call(self, method: str, p: dict):
        if method == "hello":
            return {"name": NAME, "version": VERSION, "kinds": list(KINDS), "scale": self.nav.scale,
                    "camera": self.camera is not None}
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
                if kind == "explore" and (p.get("objects") or p.get("find")) and self.camera is None:
                    raise ValueError("objects need a camera: this payload was started without --camera")
                if p.get("find") and p["find"] not in load_kinds():
                    raise ValueError(f"no kind {p['find']!r}")
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
                if p.get("objects") or p.get("find"):
                    self._objects(p)
                ex = Explorer(self.nav, self.out)
                ex.find = p.get("find")
                try:
                    res = ex.run(float(p["minutes"]))
                finally:
                    kept = self._keep_objects()
                ended = [e for e in ex.events if e.get("event") in ENDS]
                reached = (res.get("found") or {}).get("status") == "reached"     # a find ends when it stands at the object
                result = {**res, "end": ended[-1]["event"] if ended else ("found" if reached else "time"),
                          "end_s": ended[-1]["t"] if ended else None,
                          "why": ended[-1].get("why") if ended else None, **kept}
                state, why = "reached", None
        except Exception as e:      # noqa: BLE001 - a goal's failure is its outcome, said to the runner
            state, why, result = "failed", f"{type(e).__name__}: {e}", None
        with self._lock:
            self.result, self.why = result, why
            self.state = state if state in TERMINAL else "failed"     # last: a poll that sees it terminal sees the rest

    def _objects(self, p: dict) -> None:
        """The camera and the semantic map on (once: the navigator is kept between starts), from a site's map when one
        is named (its objects are known before they are seen again; the run starts at the dock, the site's frame)."""
        if self.objects_on:
            return
        if p.get("site"):
            self.site = Site.load(self.sites, p["site"], load_kinds())
            s = self.site
            self.nav.record(event="site", id=s.sid, name=s.name, kind=s.kind, objects=len(s.semantic.objects),
                            areas=[a.to_json() for a in s.areas])
        s = self.site
        self.nav.enable_objects(self.camera, load_kinds(), costs=bool(p.get("object_costs")),
                                semantic=s.semantic if s else None, area_at=s.area_at if s and s.areas else None,
                                relocalise=p.get("relocalise", True))
        self.objects_on = True

    def _keep_objects(self) -> dict:
        """The semantic map and the inventory written (files and the run: the Observatory and Mission Control read runs),
        the site saved back; what the runner reports."""
        nav = self.nav
        if nav.semantic is None:
            return {}
        with nav._sem_lock:
            (self.out / "semantic_map.json").write_text(json.dumps(nav.semantic.to_json(), indent=1))
            inventory = nav.semantic.inventory(nav._map_raw)
        (self.out / "inventory.json").write_text(json.dumps(inventory, indent=1))
        nav.record(event="inventory", objects=inventory["objects"], rooms=inventory["rooms"],
                   decision=decision("inventory", f"{inventory['objects']} objects found", objects=inventory["objects"]))
        kept = {"inventory": {"objects": inventory["objects"],
                              "rooms": {room: [o["kind"] for o in objs] for room, objs in inventory["rooms"].items()}}}
        if self.site is not None:
            with nav._sem_lock:
                self.site.save()          # the run worked on the site's own map: its ids stay, the new objects join
            kept["site"] = {"id": self.site.sid, "objects": len(self.site.semantic.objects), "folder": str(self.site.folder)}
        return kept

    def close(self) -> None:
        if self.stopped.is_set():
            return
        self.stopped.set()
        try:
            self.nav.close()
        finally:
            if self.camera is not None:
                self.camera.close()
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
    ap.add_argument("--client", help="the name to speak to a gate as, when --robot is a gate's socket")
    ap.add_argument("--camera", type=Path, help="the camera's socket (a recogniser: the host's, RFC-0021 step 6); none: no objects")
    ap.add_argument("--sites", type=Path, default=SITES, help=f"the sites' folder (default {SITES})")
    ap.add_argument("--no-fix-gate", action="store_true", help="every mapd fix is taken (a test)")
    ap.add_argument("--no-frames", action="store_true", help="the grid stays in mapd's frame (a test)")
    ap.add_argument("--fix-fault", help="T,DX,DY: from T s on, mapd's pose is shifted by (DX, DY) m (a test)")
    ap.add_argument("--frame-fault", help="T,DX,DY: as --fix-fault, and mapd's grid shifts with its pose (a test)")
    a = ap.parse_args()
    if a.fix_fault and a.frame_fault:
        ap.error("--fix-fault and --frame-fault are one fault: give one")
    fault = a.fix_fault or a.frame_fault
    faults = {"no_fix_gate": a.no_fix_gate, "no_frames": a.no_frames, "fault_grid": bool(a.frame_fault),
              "fault": [float(v) for v in fault.split(",")] if fault else None}
    payload = Payload({"robot": a.robot, "depth": a.depth, "map": a.map}, a.out, a.data, a.scene, a.name,
                      None if a.variant == "real" else a.variant, camera=a.camera, sites=a.sites, faults=faults, client=a.client)
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
