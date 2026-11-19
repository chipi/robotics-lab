"""The simulated duck's adapter (RFC-0014 step 2) against stand-ins for the three processes behind it: a robotd, the real gate
proxy in front of it (duck_lab.gate_proxy), a mapd, and a navigator server that speaks the navigator API. No simulator:
what is tested is Mission Control's side: the remote gate (lock, STOP, takeover are the gate's own), the state it builds from
robotd's stream, the map, the navigator client (start, poll, decisions, objects, refusals, a server that goes away), the run key
and the Watch link. The real navigator in the real simulator is sim_duck.py.
Run: cd apps/mission-control && uv run python tests/test_duck_adapter.py"""

import json
import socket
import socketserver
import shutil
import atexit
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish

from duck_lab.gate_proxy import Proxy
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig


def wait_for(cond, timeout=10.0, every=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


class StubRobotd:
    """robotd as far as the gate and the adapter need it: robot.move, robot.stop, robot.health, and a state stream."""

    def __init__(self, path: Path):
        self.calls: list = []
        self.x = self.yaw = 0.0
        self.vx = self.vyaw = 0.0
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._physics, daemon=True).start()

    def _physics(self):
        while True:
            time.sleep(0.05)
            self.x += self.vx * 0.05
            self.yaw += self.vyaw * 0.05

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _state(self):
        return {"odom": {"position": [self.x, 0.0, 0.117], "yaw": self.yaw}, "move": {"applied": [self.vx, 0.0, self.vyaw]},
                "safety": {"fallen": False, "picked_up": False, "limp": False}, "policy": "walk"}

    def _serve(self, sock):
        send_lock = threading.Lock()

        def send(msg):
            with send_lock:
                sock.sendall((json.dumps(msg) + "\n").encode())

        def stream():
            while True:
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": self._state()})
                except OSError:
                    return
                time.sleep(0.1)

        for line in sock.makefile("r"):
            req = json.loads(line)
            m, p = req["method"], req.get("params") or {}
            self.calls.append((m, p))
            if m == "robot.move":
                self.vx, self.vyaw = p.get("vx", 0.0), p.get("vyaw", 0.0)
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}})
            elif m == "robot.stop":
                self.vx = self.vyaw = 0.0
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}})
            elif m == "robot.health":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"battery": {"percent": 63.0, "volts": 7.4}}})
            elif m == "robot.subscribe":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"policy": "walk"}})
                threading.Thread(target=stream, daemon=True).start()
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "no such method"}})


class StubMapd:
    def __init__(self, path: Path):
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        for line in sock.makefile("r"):
            req = json.loads(line)
            grid = {"res_m": 0.05, "origin": [-0.1, -0.2], "width": 3, "height": 2, "cells": "?.#" + ".?#"}
            sock.sendall((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": grid}) + "\n").encode())


class StubNav:
    """duck-nav-server's API, scripted by the test through its attributes."""

    def __init__(self):
        self.started: list = []
        self.cancelled = 0
        self.mode = "ok"                     # ok, held, silent
        self.state = "running"
        self.decisions: list = []
        self.objects: list | None = None     # delivered once, with the next status
        self.result = None
        self.reason = None
        self.key = "duck/apartment/mc1-20261118-120000"
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        stub = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    if stub.mode == "silent":
                        return
                    req = json.loads(line)
                    m, p = req["method"], req.get("params") or {}
                    if m == "goal.start":
                        stub.started.append(p)
                        result = {"error": {"code": "held", "message": "driven by script since 12:00", "holder": "script"}} \
                            if stub.mode == "held" else {"run_key": stub.key}
                    elif m == "goal.status":
                        objs = stub.objects
                        stub.objects = None
                        result = {"state": stub.state, "reason": stub.reason, "progress": {"elapsed_s": 1.0, "pose": {"x": 1, "y": 0, "yaw": 0}},
                                  "result": stub.result, "broken": None, "run_key": stub.key,
                                  "decisions": stub.decisions[p.get("decisions_since", 0):], "decisions_n": len(stub.decisions),
                                  "objects": objs, "objects_v": 7 if objs else -1}
                    elif m == "goal.cancel":
                        stub.cancelled += 1
                        stub.state, stub.reason = "cancelled", "cancelled by Mission Control"
                        result = {"ok": True}
                    else:
                        result = {}
                    self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n").encode())

        return H

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


tmp = Path(tempfile.mkdtemp(prefix="mc-duck-"))
atexit.register(shutil.rmtree, tmp, True)
robotd = StubRobotd(tmp / "robotd.sock")
mapd = StubMapd(tmp / "mapd.sock")
proxy = Proxy(tmp / "gate.sock", tmp / "robotd.sock", takeover_names={"operator-laptop"}, log=tmp / "gate.jsonl", lease_s=10.0)
proxy.start()
nav = StubNav()

FILE = {
    "id": "duck-sim", "label": "Simulated duck", "kind": "duck",
    "adapter": {"type": "duck-sim", "gate_socket": str(tmp / "gate.sock"), "navigator": nav.address, "mapd_socket": str(tmp / "mapd.sock"),
                "observatory": "http://127.0.0.1:8070"},
    "factsheet": {"typeSpecification": {"seriesName": "Microduck", "mobileRobotKinematics": "LEGGED"},
                  "physicalParameters": {"maximumSpeed": 0.3, "maximumAngularSpeed": 1.5}},
    "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": []},
    "capabilities": {
        "sensors": [],
        "recognisers": [{"name": "sim-camera", "kinds": ["fridge"], "frame": "site"}],
        "localisation": {"frame": "site", "how": "dock"}, "map": {"kind": "occupancy_grid", "resolution_m": 0.05},
        "navigator": {"goal_kinds": ["point", "go_to_object", "go_to_area", "explore", "inventory"], "conditions": ["within_s"]},
        "guardrails": ["time_limit"], "skills": [], "description": "the simulated duck"},
    "rates": {"state_hz": 5.0, "map_hz": 2.0, "max_state_hz": 10.0},
}
mc = MissionControl([RobotConfig(FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def robot():
    return call("GET", "/robots/duck-sim")["robot"]


def run_of(rid):
    return call("GET", f"/goal-runs/{rid}")["run"]


check("the duck is online: robotd's stream, through the gate, is its state", wait_for(lambda: robot()["online"]), robot())
# online is the first state; the pose follows the navigator's first fix, a moment later (CI's runner read between them)
check("the duck has a pose in its state (the bound is long: the machine is loaded by the simulator streams)", wait_for(lambda: (robot().get("status") or {}).get("pose") is not None, 40.0))
st = robot()["status"]
check("its state is in the page's shape: pose in the site frame, mode, flags, battery from robot.health",
      st["pose"]["frame"] == "site" and st["mode"] == "idle" and st["flags"]["fall"] is False and st["battery_pct"] == 63.0 and st["link"] == "duck-gate", st)
check("the lock is the gate's own: free", robot()["lock"]["holder"] is None)
m = call("GET", "/robots/duck-sim/map")["map"]
check("the map is mapd's grid, in the site frame: unknown -1, free 0, occupied 100", m["data"] == [-1, 0, 100, 0, -1, 100] and m["width"] == 3 and m["frame"] == "site", m)

# the lock, over the gate's socket
a = call("POST", "/robots/duck-sim/lock", {"client": "script"})["lock"]
check("acquire takes the gate's lease in the client's name", a["lease_id"] == 1 and robot()["lock"]["holder"] == "script", a)
second = call("POST", "/robots/duck-sim/lock", {"client": "other"})
check("a second client is refused with who holds it (the gate's refusal)", second["error"]["code"] == "held" and second["error"]["holder"] == "script", second)
call("POST", "/robots/duck-sim/drive", {"vx": 0.2, "vyaw": 0.0, "session": a["session"]})
check("a drive reaches robotd through the gate", ("robot.move", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}) in robotd.calls)
check("and the robot walks (state from the stream)", wait_for(lambda: robot()["status"]["pose"]["x"] > 0.05 and robot()["status"]["mode"] == "moving"), robot()["status"])
stop = call("POST", "/robots/duck-sim/stop", {"client": "page"})["stop"]
check("STOP: confirmed, robot.stop then a zero move upstream", stop["confirmed"] is True
      and robotd.calls[-2:] == [("robot.stop", {}), ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})], robotd.calls[-3:])
r = call("POST", "/robots/duck-sim/drive", {"vx": 0.2, "session": a["session"]})
check("it latched: the holder's next drive is refused with the gate's reason", r["error"]["code"] == "lease_ended" and "stopped_by page" in r["error"]["message"], r)
check("the robot is free", robot()["lock"]["holder"] is None)
b = call("POST", "/robots/duck-sim/lock", {"client": "script"})["lock"]
tk = call("POST", "/robots/duck-sim/lock/takeover", {"client": "operator-laptop"})
check("a takeover is the gate's: refused to a name on no list, done for one on it",
      call("POST", "/robots/duck-sim/lock/takeover", {"client": "intruder"})["error"]["code"] == "not_allowed" and tk["ok"]
      and robot()["lock"]["holder"] == "operator-laptop", tk)
check("the old holder is refused with why",
      "taken_over_by operator-laptop" in call("POST", "/robots/duck-sim/drive", {"vx": 0.1, "session": b["session"]})["error"]["message"])
call("DELETE", "/robots/duck-sim/lock", {"session": tk["lock"]["session"]})
check("the holder as it changes is on the stream", wait_for(lambda: any(e["kind"] == "lock" and e.get("event") == "holder" and e.get("holder") == "script"
                                                                          for e in mc.bus.since(0, 100000)[0])))

# a goal run on the navigator server
mc.sites.create("Home", "apartment")
call("PUT", "/robots/duck-sim/site", {"site": "home"})
run = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
check("a goal starts on the navigator server, with the run key at once, and the Watch link points at the Observatory",
      run["state"] == "running" and run["run_key"] == nav.key and run["watch"] == "http://127.0.0.1:8070/watch/" + nav.key, run)
spec = nav.started[0]
check("the server got the goal, its guardrails, the seed and the goal run's id and name (for the Observatory run's metadata)",
      spec["kind"] == "point" and spec["params"] == {"x": 1.0, "y": 0.0, "frame": "site"} and spec["goal_run"]["id"] == run["id"]
      and spec["goal_run"]["name"] == "ad-hoc point" and "seed" in spec and spec["conditions"]["done_when"]["within_s"] == 60.0, spec)
nav.decisions = [{"n": 1, "t": 1.0, "text": "planned a path of 1.2 m", "rule": "plan", "values": {"length_m": 1.2}},
                 {"n": 2, "t": 2.0, "text": "slowed for an obstacle", "rule": "slow", "values": {}}]
check("the navigator's decisions are relayed with their reasons, once each",
      wait_for(lambda: len([d for d in run_of(run["id"])["decisions"] if d["text"] in ("planned a path of 1.2 m", "slowed for an obstacle")]) == 2))
d1 = next(d for d in run_of(run["id"])["decisions"] if d["text"].startswith("planned"))
check("with the rule and its values", d1["rule"] == "plan" and d1["values"] == {"length_m": 1.2}, d1)
check("progress comes from the server", wait_for(lambda: (run_of(run["id"])["progress"] or {}).get("elapsed_s") == 1.0))
nav.state = "reached"
end = wait_for(lambda: run_of(run["id"])["state"] == "reached" and run_of(run["id"]))
check("a run the server ends reached is reached here, as expected", end and end["as_expected"] is True and end["run_key"] == nav.key, end)
check("the robot is free again", robot()["goal_run"] is None)

# objects the server was seeded with come back as themselves
mc.sites.merge_run_objects("home", [{"id": "n", "kind": "fridge", "x": 3.0, "y": 1.5, "n": 3, "confirmed": True, "unique": True,
                                      "parts": [[3.0, 1.5, 0.4, 0.35, 0.0, 0.0, 1.8]]}], "seed", {})
nav.state, nav.reason, nav.result = "running", None, None
b = call("POST", "/goal-runs", {"goal": {"kind": "go_to_object", "params": {"kind": "fridge"}}, "robots": ["duck-sim"]})
spec = nav.started[-1]
check("the site's confirmed objects are the seed, with their own ids", [o["id"] for o in spec["seed"]["objects"]] == ["obj-1"], spec["seed"])
nav.objects = [{"id": "fridge_1", "seed": "obj-1", "kind": "fridge", "x": 3.05, "y": 1.45, "n": 9, "confirmed": True, "landmark": 0.9, "unique": True,
                "parts": [[3.05, 1.45, 0.4, 0.35, 0.0, 0.0, 1.8]], "confidence": 0.9, "label": None},
               {"id": "sofa_1", "seed": None, "kind": "sofa", "x": -2.0, "y": -1.0, "n": 3, "confirmed": True, "landmark": 0.8, "unique": False,
                "parts": [[-2.0, -1.0, 0.9, 0.4, 0.0, 0.0, 0.8]], "confidence": 0.8, "label": None}]
check("the navigator's map is merged into the site: the seeded fridge stays obj-1, the sofa is new",
      wait_for(lambda: len(mc.sites.objects("home")) == 2) and mc.sites.object("home", "obj-1")["n"] >= 9
      and {o["kind"] for o in mc.sites.objects("home")} == {"fridge", "sofa"}, [(o["id"], o["kind"], o["n"]) for o in mc.sites.objects("home")])
nav.state, nav.result = "reached", {"object": {"id": "fridge_1", "seed": "obj-1", "kind": "fridge", "x": 3.05, "y": 1.45, "label": None, "frame": "site"},
                                    "stand": {"x": 2.6, "y": 1.4, "yaw": 0.0, "frame": "site"}}
rid = b["run"]["id"]
end = wait_for(lambda: run_of(rid)["state"] == "reached" and run_of(rid))
check("the run's result names the site's own object (navigator ids are mapped)", end and end["result"]["object"]["id"] == "obj-1", end and end["result"])

# refusals and failures of the server
nav.mode, nav.state = "held", "running"
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
check("a robot another client holds: the server's refusal is the run's reason, the run is refused", r["state"] == "refused" and "driven by script" in r["reason"], r)
nav.mode = "ok"
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
cancelled = call("POST", f"/goal-runs/{r['id']}/cancel")["run"]
check("cancel goes to the server and waits for it to end the run", nav.cancelled == 1 and cancelled["state"] == "cancelled", cancelled)
nav.state, nav.reason = "running", None
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
nav.mode = "silent"
end = wait_for(lambda: run_of(r["id"])["state"] != "running" and run_of(r["id"]), 15)
check("a navigator server that stops answering ends the run interrupted, with why", end and end["state"] == "interrupted" and "stopped answering" in end["reason"],
      end and (end["state"], end["reason"]))
nav.stop()
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
check("with the server down a goal is refused, saying so", r["state"] == "refused" and "did not answer" in r["reason"], r)

# the gate gone
proxy.stop()
check("with the gate gone the duck is offline, and STOP is accepted but cannot be confirmed",
      wait_for(lambda: not robot()["online"], 15) and call("POST", "/robots/duck-sim/stop")["stop"]["confirmed"] is False)

srv.shutdown()
srv.server_close()
mc.close()
finish("test_duck_adapter")
