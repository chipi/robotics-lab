"""The navigator API's answers that Mission Control reads without importing the navigator (phase 5 step 1): the robot's map between
goals (read from mapd by the navigator API, so no client opens mapd itself), and goal.start's answer naming the profile version the
goal runs. A stand-in mapd and a stand-in goal run; no simulator.
Run: cd robots/duck && uv run python tests/test_nav_server.py"""

import atexit
import json
import shutil
import socket
import tempfile
import threading
import types
from pathlib import Path

from duck_lab.nav import server

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="nav-server-"))
atexit.register(shutil.rmtree, tmp, True)
GRID = {"res_m": 0.05, "origin": [-0.1, -0.2], "width": 3, "height": 2, "cells": "?.#.?#"}
asked = []


def mapd(path: Path):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(4)

    def serve(c):
        for line in c.makefile("r"):
            req = json.loads(line)
            asked.append(req["method"])
            c.sendall((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": GRID}) + "\n").encode())

    def accept():
        while True:
            c, _ = s.accept()
            threading.Thread(target=serve, args=(c,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()


mapd(tmp / "map.sock")
nav = server.NavServer({"robot": tmp / "gate.sock", "depth": tmp / "depth.sock", "map": tmp / "map.sock"}, tmp / "data", tmp / "out")
check("between goals the navigator API answers `map` from mapd itself", nav.call("map", {}) == GRID and asked == ["map.grid"], asked)
check("state, objects and inventory still need a running goal",
      nav.call("state", {}) == {"error": "no goal is running"} and nav.call("objects", {}) == {"objects": []})

META = {"source": "given", "path": "/s/profiles/duck/2.json", "checksum": "sha256:abc", "version": 2}


class FakeRun:
    def __init__(self, srv, spec):
        self.state, self.nav, self.placed = "starting", None, None
        if spec.get("start_pose"):           # as GoalRun._place answers: the pose and the change from mapd's frame (metres, mapd's own)
            self.placed = {"pose": {**spec["start_pose"], "frame": "site"}, "frame": {"x": 0.5, "y": -0.25, "yaw": 0.0}}

    def start(self):
        self.nav = types.SimpleNamespace(profile=types.SimpleNamespace(meta=META))
        self.state = "running"
        return "duck/apartment/mc1-x"


server.GoalRun, nav._gate_holder = FakeRun, lambda: None
reply = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}})
check("goal.start's answer names the profile the goal runs: checksum, version and source, no machine path",
      reply == {"run_key": "duck/apartment/mc1-x", "profile": {"checksum": "sha256:abc", "version": 2, "source": "given"}}, reply)

# --- a start pose (contract 1.5) ---------------------------------------------------------------------------------------------------
nav.run.state = "reached"
POSE = {"x": 2.0, "y": 1.0, "yaw": 0.5}
reply = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}, "start_pose": POSE})
check("goal.start with a start pose answers `placed`: the pose taken and the frame change in mapd's metres",
      reply.get("placed") == {"pose": {**POSE, "frame": "site"}, "frame": {"x": 0.5, "y": -0.25, "yaw": 0.0}}, reply)
moved = nav.call("map", {})
check("`map` is then answered in the placed frame (the grid's origin moved by the change, the cells as they were)",
      moved["origin"] == [0.4, -0.45] and moved["cells"] == GRID["cells"] and moved["width"] == 3, moved)
nav.run.state = "reached"
reply = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}})
check("a goal with no start pose answers no `placed`, and `map` is mapd's own again (the frame is per goal)",
      "placed" not in reply and nav.call("map", {}) == GRID, (reply, nav.call("map", {})))
nav.run.state = "reached"
for label, bad in (("a pose without a yaw", {"x": 1.0, "y": 2.0}), ("a string for x", {"x": "1", "y": 2.0, "yaw": 0.0}),
                   ("a NaN", {"x": float("nan"), "y": 2.0, "yaw": 0.0}), ("a list", [1, 2, 0]), ("a boolean for yaw", {"x": 1, "y": 2, "yaw": True})):
    err = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}, "start_pose": bad}).get("error") or {}
    check(f"must fail: {label} is not a start pose: bad_start_pose, no goal started", err.get("code") == "bad_start_pose" and nav.run.state == "reached", err)
ROOM = [[0, 0], [2, 0], [2, 2], [0, 2]]
nogo = {"conditions": {"guardrails": [{"name": "no_go_area", "area": "cellar", "outline": ROOM}]}}
err = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}, "start_pose": {"x": 1.0, "y": 1.0, "yaw": 0.0}, **nogo}).get("error") or {}
check("must fail: a start pose inside a no-go area the goal carries is refused, naming the area", err.get("code") == "bad_start_pose" and "cellar" in err.get("message", ""), err)
reply = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}, "start_pose": {"x": 3.0, "y": 1.0, "yaw": 0.0}, **nogo})
check("... and one outside it is taken", "placed" in reply, reply)

# --- over the socket: only an unknown method is "no method"; a KeyError inside a handler is an internal error (review 3.c) ---
srv = server.Server(("127.0.0.1", 0), nav)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def rpc(method):
    with socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5) as s:
        s.sendall((json.dumps({"id": 1, "method": method, "params": {}}) + "\n").encode())
        return json.loads(s.makefile("r").readline())["error"]


real_start = nav.start
nav.start = lambda p: {}["missing"]
inside, unknown = rpc("goal.start"), rpc("no.such.method")
nav.start = real_start
srv.shutdown()
check("an unknown method is -32601 no method", unknown["code"] == -32601 and "no.such.method" in unknown["message"], unknown)
check("a KeyError raised inside a handler is -32603, reported as KeyError, not as a missing method",
      inside["code"] == -32603 and "KeyError" in inside["message"] and "no method" not in inside["message"], inside)

print()
print("NAV SERVER", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
