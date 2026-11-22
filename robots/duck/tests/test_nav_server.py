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
        self.state, self.nav = "starting", None

    def start(self):
        self.nav = types.SimpleNamespace(profile=types.SimpleNamespace(meta=META))
        self.state = "running"
        return "duck/apartment/mc1-x"


server.GoalRun, nav._gate_holder = FakeRun, lambda: None
reply = nav.call("goal.start", {"kind": "point", "params": {"x": 1, "y": 0}})
check("goal.start's answer names the profile the goal runs: checksum, version and source, no machine path",
      reply == {"run_key": "duck/apartment/mc1-x", "profile": {"checksum": "sha256:abc", "version": 2, "source": "given"}}, reply)

print()
print("NAV SERVER", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
