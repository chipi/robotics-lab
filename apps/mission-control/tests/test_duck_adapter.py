"""The simulated duck's adapter (RFC-0014 step 2) against stand-ins for the processes behind it: a robotd, the real gate
proxy in front of it (labrunner.gate), and a navigator server that speaks the navigator API (its map included). No simulator:
what is tested is Mission Control's side: the remote gate (lock, STOP, takeover are the gate's own), the state it builds from
robotd's stream, the map, the navigator client (start, poll, decisions, objects, refusals, a server that goes away), the run key
and the Watch link; and (phase 5 step 1) the robot file as a pointer to the profile, the addresses from the installation file,
the profile read again at each goal's start. The real navigator in the real simulator is sim_duck.py.
Run: cd apps/mission-control && uv run python tests/test_duck_adapter.py"""

import json
import math
import os
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

from common import check, finish, installation_file

from labrunner.gate import Proxy
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import ConfigError, RobotConfig
from runfile import installation
from runfile.navcontract import CONTRACT
from runfile.profile import checksum
from runfile.profilestore import Store


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
        self.stop_error = False              # robot.stop answers with an error (the zero move still works)
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
                "safety": {"fallen": False, "picked_up": False, "limp": False}, "policy": "walk",
                "joints": [round(0.01 * k, 2) for k in range(15)]}

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
            elif m == "robot.stop" and self.stop_error:
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": "stop failed"}})
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


class StubNav:
    """duck-nav-server's API, scripted by the test through its attributes."""

    def __init__(self):
        self.started: list = []
        self.cancelled = 0
        self.mode = "ok"                     # ok, held, silent
        self.state = "running"
        self.decisions: list = []
        self.anomalies: list = []            # contract 1.1: the run's anomalies, served since a number
        self.objects: list | None = None     # delivered once, with the next status
        self.result = None
        self.reason = None
        self.key = "duck/apartment/mc1-20261118-120000"
        self.profile = None                  # what goal.start says the goal runs (the navigator's calibration event)
        self.contract = "1.0"                # the navigator contract hello names
        self.map_calls = 0
        self.placed = None                   # contract 1.5: what goal.start answers a start pose with (none: a navigator that did not hear it)
        self.site = True                     # contract 1.8: answers `site_pose` and a `map` in true metres (False: a 1.7 navigator, which answers neither)
        self.scale, self.frame, self.site_calls = 0.9, None, []      # the odometry scale it runs, the frame the latest goal's start pose set (mapd's metres), site_pose's calls
        self.cal_calls, self.cal_answer = [], {}     # contract 1.3's calibration.* calls received, and what each is answered with
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
                    if m == "hello":
                        result = {"name": "stub-nav", "version": "0", "contract": stub.contract, "kinds": ["point", "go_to_object"],
                                  "camera": True}
                    elif m == "goal.start":
                        stub.started.append(p)
                        stub.frame = stub.placed["frame"] if stub.placed and p.get("start_pose") else None
                        result = {"error": {"code": "held", "message": "driven by script since 12:00", "holder": "script"}} \
                            if stub.mode == "held" else {"run_key": stub.key, "profile": stub.profile,
                                                         **({"placed": stub.placed} if stub.placed and p.get("start_pose") else {})}
                    elif m == "map":
                        stub.map_calls += 1
                        result = {"res_m": 0.05, "origin": [-0.1, -0.2], "width": 3, "height": 2, "cells": "?.#" + ".?#"}
                        if stub.site and p.get("units") == "site":
                            result = {**result, "res_m": result["res_m"] * stub.scale, "origin": [v * stub.scale for v in result["origin"]], "units": "site"}
                    elif m == "site_pose" and stub.site:
                        stub.site_calls.append(p)
                        o, f, k = p["odom"], stub.frame, stub.scale
                        f = (f["x"] * k, f["y"] * k, f["yaw"]) if f else (0.0, 0.0, 0.0)
                        c, sn = math.cos(f[2]), math.sin(f[2])
                        result = {"x": f[0] + c * o["x"] * k - sn * o["y"] * k, "y": f[1] + sn * o["x"] * k + c * o["y"] * k,
                                  "yaw": math.atan2(math.sin(f[2] + o["yaw"]), math.cos(f[2] + o["yaw"])), "frame": "site", "placed": stub.frame is not None}
                    elif m == "goal.status":
                        objs = stub.objects
                        stub.objects = None
                        result = {"state": stub.state, "reason": stub.reason, "progress": {"elapsed_s": 1.0, "pose": {"x": 1, "y": 0, "yaw": 0}},
                                  "result": stub.result, "broken": None, "run_key": stub.key,
                                  "decisions": stub.decisions[p.get("decisions_since", 0):], "decisions_n": len(stub.decisions),
                                  "anomalies": stub.anomalies[p.get("anomalies_since", 0):], "anomalies_n": len(stub.anomalies),
                                  "objects": objs, "objects_v": 7 if objs else -1}
                    elif m == "goal.cancel":
                        stub.cancelled += 1
                        stub.state, stub.reason = "cancelled", "cancelled by Mission Control"
                        result = {"ok": True}
                    elif m.startswith("calibration."):
                        stub.cal_calls.append((m, p))
                        result = stub.cal_answer.get(m, {"ok": True})
                    else:
                        result = {}
                    self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n").encode())

        return H

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


tmp = Path(tempfile.mkdtemp(prefix="mc-duck-"))
atexit.register(shutil.rmtree, tmp, True)
# the test's own installation, the duck registered by its file and nothing else: this machine's would point Mission Control at the
# real gate, and the duck's package is not installed beside Mission Control
BARE = installation_file(tmp / "bare-installation.json")
os.environ[installation.ENV] = str(BARE)
robotd = StubRobotd(tmp / "robotd.sock")
proxy = Proxy(tmp / "gate.sock", tmp / "robotd.sock", takeover_names={"operator-laptop"}, log=tmp / "gate.jsonl", lease_s=10.0)
proxy.start()
nav = StubNav()

FILE = {"id": "duck-sim", "label": "Simulated duck", "robot": "duck", "variant": "sim",
        "adapter": {"type": "duck-sim", "gate_socket": str(tmp / "gate.sock"),
                    "navigator": nav.address,
                    "observatory": "http://127.0.0.1:8070"}}
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
joint_names = json.loads((Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json").read_text())["joints"]["names"]
check("must fail: its joint angles are in its state by the profile's joint names, in robotd's order (the body page poses from them)",
      st.get("joints") == {n: round(0.01 * k, 2) for k, n in enumerate(joint_names)} and len(st["joints"]) == 15, st.get("joints"))
check("the lock is the gate's own: free", robot()["lock"]["holder"] is None)
m = call("GET", "/robots/duck-sim/map")["map"]
check("the map is the navigator API's (mapd's grid), in the site frame: unknown -1, free 0, occupied 100", m["data"] == [-1, 0, 100, 0, -1, 100] and m["width"] == 3 and m["frame"] == "site", m)
check("must fail: its resolution and origin are the navigator's, in true metres: Mission Control scales nothing",
      abs(m["resolution_m"] - 0.05 * nav.scale) < 1e-9 and [round(v, 6) for v in m["origin"]] == [round(-0.1 * nav.scale, 6), round(-0.2 * nav.scale, 6)], m)
n0, t0 = nav.map_calls, time.monotonic()
time.sleep(3.0)
rate = (nav.map_calls - n0) / (time.monotonic() - t0)
check(f"the map is asked for at the robot's map_hz ({mc.robots['duck-sim'].cfg.rates['map_hz']:g} Hz), not every tick, while it does not "
      f"change: {rate:.1f} requests/s",
      rate <= 2.5 * mc.robots["duck-sim"].cfg.rates["map_hz"], rate)

# the state stream's rate (the operator's decision h): a whole number, ceil(state_hz), at most max_state_hz
from mission_control.duck import _Stream, stream_hz  # noqa: E402
rates_ = mc.robots["duck-sim"].cfg.rates
asked = [p.get("hz") for m_, p in robotd.calls if m_ == "robot.subscribe"]
check(f"Mission Control subscribes at the profile's state_hz as a whole number ({rates_['state_hz']:g} -> {stream_hz(rates_)})",
      asked and asked[-1] == stream_hz(rates_) == 2 and isinstance(asked[-1], int), asked)
check("stream_hz: ceil of state_hz, capped at max_state_hz, never 0",
      [stream_hz(r) for r in ({"state_hz": 2.0}, {"state_hz": 2.2}, {"state_hz": 0.4}, {"state_hz": 9.5, "max_state_hz": 9.7},
                              {"state_hz": 5.0, "max_state_hz": 10.0})] == [2, 3, 1, 9, 5])
t0 = time.monotonic()
s = _Stream(tmp / "gate.sock", "rate-probe", hz=2.5)
check("must fail: a subscription the gate refuses is read and said, not dropped (no states, the gate's own words)",
      wait_for(lambda: s.refused is not None, 3.0) and "whole number" in s.refused and s.latest is None
      and time.monotonic() - t0 < 2.0, (s.refused, s.latest))
s.close()

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
# through the real remote path (RemoteGate -> the gate proxy -> robotd), `confirmed` is whether robotd answered robot.stop: a wire
# call that returned is not that
events = lambda: [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "stop"]      # noqa: E731
robotd.stop_error = True
robotd.calls.clear()
stop = call("POST", "/robots/duck-sim/stop", {"client": "page"})["stop"]
check("STOP when robotd fails robot.stop: accepted, confirmed False, on the reply and the bus, and the zero move still sent",
      stop["confirmed"] is False and events()[-1]["confirmed"] is False
      and ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}) in robotd.calls, (stop, events()[-1:], robotd.calls))
c = call("POST", "/robots/duck-sim/lock", {"client": "script"})["lock"]
stop = call("POST", "/robots/duck-sim/stop", {"client": "page"})["stop"]
check("... and with a holder too: the lease ended, confirmed False", stop["confirmed"] is False and robot()["lock"]["holder"] is None, stop)
robotd.stop_error = False
stop = call("POST", "/robots/duck-sim/stop", {"client": "page"})["stop"]
check("STOP when robotd answers again: confirmed True, on the bus too", stop["confirmed"] is True and events()[-1]["confirmed"] is True, (stop, events()[-1:]))
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
A1 = {"n": 1, "t": 3.5, "anomaly": "joint_overload", "source": "robot", "module": "body", "severity": "major", "detector": "joint_current",
      "summary": "left_knee at 130 mA, at or over 120 mA for 1.0 s", "values": {"joint": "left_knee"}, "margin": 10, "where": {"frame": "map"}}
nav.anomalies = [A1]
check("must fail: the navigator's anomalies are kept with the goal run (contract 1.1)",
      wait_for(lambda: [a["anomaly"] for a in run_of(run["id"]).get("anomalies", [])] == ["joint_overload"]), run_of(run["id"]).get("anomalies"))
nav.anomalies = [A1, {**A1, "n": 2, "t": 5.0, "anomaly": "robot_unhealthy", "severity": "minor", "summary": "robotd says it is degraded"}]
check("must fail: each is relayed once, the next one after it", wait_for(lambda: [a["anomaly"] for a in run_of(run["id"])["anomalies"]]
                                                                         == ["joint_overload", "robot_unhealthy"]), run_of(run["id"])["anomalies"])
bus_an = [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "anomaly"]
check("must fail: on the event stream, with the robot, the goal run and the Observatory's page at its moment",
      [(e["robot"], e["goal_run"], e["anomaly"]["anomaly"], e["watch"]) for e in bus_an]
      == [("duck-sim", run["id"], "joint_overload", f"http://127.0.0.1:8070/watch/{nav.key}#t=3.5"),
          ("duck-sim", run["id"], "robot_unhealthy", f"http://127.0.0.1:8070/watch/{nav.key}#t=5.0")], bus_an)
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
# a start pose without a truth (phase 5 B7, contract 1.5): refused by a navigator that would ignore it, shown in the frame it sets
START = {"x": 2.0, "y": 1.0, "yaw": math.pi / 2}
POINT = {"kind": "point", "params": {"x": 2.0, "y": 0.0}}
nav.state, nav.reason = "running", None
n_started = len(nav.started)
r = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-sim"], "start_pose": START})["run"]
check("must fail: a navigator below contract 1.5 would ignore a start pose and run the goal in the wrong frame: refused before goal.start, saying why",
      r["state"] == "refused" and "takes no start pose" in r["reason"] and "1.0" in r["reason"] and len(nav.started) == n_started, r)
r = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-sim"]})["run"]
check("... and the same goal with no start pose still starts on it (an older navigator keeps working)", r["state"] == "running" and "start_pose" not in nav.started[-1], r)
call("POST", f"/goal-runs/{r['id']}/cancel")
nav.contract, nav.state, nav.reason = CONTRACT, "running", None
cancelled_before = nav.cancelled
r = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-sim"], "start_pose": START})["run"]
check("must fail: a 1.5 navigator that answers no `placed` did not hear the pose: the goal is cancelled and refused",
      r["state"] == "refused" and "no `placed`" in r["reason"] and nav.cancelled == cancelled_before + 1, r)
nav.placed = {"pose": {**START, "frame": "site"}, "frame": {"x": 0.5, "y": -1.0, "yaw": math.pi / 2}}
nav.state, nav.reason = "running", None
r = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-sim"], "start_pose": {**START, "yaw": START["yaw"] + 2 * math.pi}})["run"]
check("a 1.5 navigator gets goal.start with the start pose (yaw wrapped), and the run keeps it among its conditions",
      r["state"] == "running" and abs(nav.started[-1]["start_pose"]["yaw"] - START["yaw"]) < 1e-9 and nav.started[-1]["start_pose"]["x"] == 2.0
      and r["conditions"]["start_pose"]["y"] == 1.0, (r["state"], nav.started[-1].get("start_pose")))
adapter = mc.robot("duck-sim").adapter
check("must fail: Mission Control keeps no frame and no scale of its own: the navigator owns both (contract 1.8)",
      not hasattr(adapter, "placed") and not hasattr(adapter, "scale"), (hasattr(adapter, "placed"), hasattr(adapter, "scale")))


def shown_pose():
    s = (robot().get("status") or {}).get("pose") or {}
    return s.get("x"), s.get("y"), s.get("yaw")


# odometry (x, 0, yaw) is placed by the frame (0.5, -1.0, pi/2) and scaled by the navigator's scale (0.9, not 1: a missed scaling shows): the navigator
# answers the pose in the site frame, Mission Control shows it as it is: x' = 0.5 s (y is 0), y' = (-1.0 + x) s
want = lambda: (round(0.5 * nav.scale, 4), round((-1.0 + robotd.x) * nav.scale, 4))      # noqa: E731
check("must fail: the robot's pose on the page is the navigator's, in the frame the start pose set and in true metres",
      wait_for(lambda: shown_pose()[:2] == want() or None, 5.0) and robot()["status"]["pose"]["frame"] == "site", (shown_pose(), want()))
check("must fail: Mission Control sent robotd's raw odometry, unscaled and unplaced, to the navigator",
      nav.site_calls and abs(nav.site_calls[-1]["odom"]["x"] - robotd.x) < 1e-9 and nav.site_calls[-1]["odom"]["y"] == 0.0 and nav.site_calls[-1]["odom"]["yaw"] == 0.0, nav.site_calls[-1:])
call("POST", f"/goal-runs/{r['id']}/cancel")
nav.state, nav.reason = "running", None
r = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-sim"]})["run"]
check("a goal with no start pose leaves the placed frame: the pose is odometry, scaled by the navigator",
      wait_for(lambda: shown_pose()[:2] == (round(robotd.x * nav.scale, 4), 0.0) or None, 5.0), shown_pose())
call("POST", f"/goal-runs/{r['id']}/cancel")
nav.site = False
check("must fail: a navigator below 1.8 answers no site_pose: no pose is shown (Mission Control has no scale to make one), the reason is, and the robot stays online",
      wait_for(lambda: "pose" not in robot()["status"] and "site_pose" in (robot()["status"].get("pose_error") or "") or None, 5.0) and robot()["online"], robot()["status"])
check("... and its map in mapd's metres is not shown as the site's: no map", call("GET", "/robots/duck-sim/map").get("error") is not None, call("GET", "/robots/duck-sim/map"))
nav.site = True
check("a navigator at 1.8 again: the pose is back", wait_for(lambda: shown_pose()[0] is not None or None, 5.0) and "pose_error" not in robot()["status"], robot()["status"])
nav.placed = None

# the navigator contract (libs/runner/CONTRACT.md): what Mission Control refuses of a navigator
nav.state, nav.reason, nav.contract = "running", None, "2.0"
n_started = len(nav.started)
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
check("must fail: a navigator speaking another major version of the contract is refused before a goal starts, both versions said",
      r["state"] == "refused" and "2.0" in r["reason"] and CONTRACT in r["reason"] and len(nav.started) == n_started, r)
nav.contract = "1.0"
r = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 2.0, "y": 0.0}}, "robots": ["duck-sim"]})["run"]
nav.state = "aborted"
end = wait_for(lambda: run_of(r["id"])["state"] != "running" and run_of(r["id"]), 10)
check("must fail: a state the contract does not have ends the run failed, saying which state", end and end["state"] == "failed"
      and "'aborted'" in end["reason"], end and (end["state"], end["reason"]))
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

# Phase 5 step 1: the robot file is a pointer to the robot's profile; the addresses come from the installation file.
from mission_control.duck import DuckAdapter  # noqa: E402

REPO_PROFILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
repo = json.loads(REPO_PROFILE.read_text())
cfg = RobotConfig({"id": "d", "robot": "duck", "variant": "sim", "adapter": {"type": "duck-sim"}})
check("a pointer file's factsheet, capabilities and rates are the profile's (the robot's own file, no installation)",
      cfg.kind == "duck" and cfg.factsheet == repo["factsheet"] and cfg.capabilities == repo["capabilities"]
      and cfg.rates == repo["rates"] and cfg.label == repo["label"] and cfg.profile.meta["checksum"] == checksum(repo),
      (cfg.kind, cfg.rates, cfg.profile.meta))


def refused(raw, why):
    try:
        RobotConfig(raw)
    except ConfigError as exc:
        return why in str(exc), str(exc)
    return False, "not refused"


ok, why = refused({"id": "d", "robot": "duck", "variant": "sim", "adapter": {"type": "duck-sim"}, "rates": {"state_hz": 9.0}},
                  "come from the profile")
check("must fail: a pointer file that repeats a block of the profile is refused (one copy of the robot)", ok, why)
ok, why = refused({"id": "d", "robot": "goose", "adapter": {"type": "duck-sim"}}, "no robot 'goose' registered")
check("a pointer to a robot not registered here is refused, naming the registered ones", ok, why)

# the variant has one source: the installation's robots.<robot>.variant, else the adapter's default (duck-sim runs on a host with a
# truth: sim; any other: real); a robot file that names one is checked against it, never obeyed
def variant_of(installed, adapter, named=None):
    f = installation_file(tmp / f"variant-{installed}.json", {"duck": {"variant": installed}} if installed else {})
    os.environ[installation.ENV] = str(f)
    try:
        raw = {"id": "d", "robot": "duck", "adapter": {"type": adapter}, **({"variant": named} if named else {})}
        return RobotConfig(raw).variant
    except ConfigError as exc:
        return str(exc)
    finally:
        os.environ[installation.ENV] = str(BARE)


check("must fail: no variant named anywhere: sim for the duck-sim adapter", variant_of(None, "duck-sim") == "sim", variant_of(None, "duck-sim"))
check("no variant named anywhere: real for any other adapter", variant_of(None, "fake") == "real", variant_of(None, "fake"))
check("must fail: the installation's robots.duck.variant is the robot's, whatever the adapter", variant_of("sim", "fake") == "sim"
      and variant_of("real", "duck-sim") == "real", (variant_of("sim", "fake"), variant_of("real", "duck-sim")))
check("a robot file naming the installation's variant is accepted", variant_of("real", "duck-sim", "real") == "real"
      and variant_of(None, "duck-sim", "sim") == "sim")
mismatch = variant_of("sim", "duck-sim", "real")
check("must fail: a robot file naming another variant than the installation's is refused, saying why",
      "names variant 'real'" in mismatch and "robots.duck.variant" in mismatch and "sim" in mismatch, mismatch)
mismatch = variant_of(None, "duck-sim", "real")
check("must fail: and than the adapter's default when the installation names none", "names variant 'real'" in mismatch, mismatch)
check("an installation naming a variant the profile does not have is refused", "no variant 'moon'" in variant_of("moon", "duck-sim"),
      variant_of("moon", "duck-sim"))
try:
    DuckAdapter(RobotConfig({"id": "d", "kind": "duck", "adapter": {"type": "duck-sim", "gate_socket": "/x/g.sock"}}))
    said = "accepted"
except ConfigError as exc:
    said = str(exc)
check("a duck-sim robot file that is not a pointer to the profile is refused", "points at its robot's profile" in said, said)
try:
    DuckAdapter(cfg)
    said = "accepted"
except ConfigError as exc:
    said = str(exc)
check("must fail: a gate named nowhere (not in the installation, no gate_socket) is an error saying where to name it",
      "robots.duck.gate" in said and "bare-installation.json" in said, said)

store = Store(tmp / "inst-state" / "profiles")
store.seed("duck", REPO_PROFILE)
# the gate's protocol (RFC-0018 §5.3): this side's gate is read, a gate from the future is refused
from mission_control.duck import _Wire  # noqa: E402
from robotgate import ProtocolError  # noqa: E402


def wire_to(hello_result):
    path = tmp / f"fake-gate-{len(list(tmp.glob('fake-gate-*')))}.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        for line in conn.makefile("r"):
            conn.sendall((json.dumps({"jsonrpc": "2.0", "id": json.loads(line)["id"], "result": hello_result}) + "\n").encode())
    threading.Thread(target=serve, daemon=True).start()
    try:
        _Wire(path, "mission-control").sock.close()
        return None
    except ProtocolError as exc:
        return exc
    finally:
        srv.close()


check("a gate of this protocol is connected to", wire_to({"gate": True, "client": "mission-control", "protocol": 1}) is None)
check("must fail: a gate that speaks a newer protocol is refused, both numbers said",
      "2" in str(wire_to({"gate": True, "client": "mission-control", "protocol": 2})) and "1" in str(wire_to({"protocol": 2})))
check("a gate that names none (before the number) is accepted", wire_to({"gate": True, "client": "mission-control"}) is None)

# calibration (contract 1.3): asked of a navigator only when its hello says it speaks 1.3
from mission_control.duck import DuckNavigatorClient  # noqa: E402
from runfile.navcontract import ContractError  # noqa: E402

cnav = StubNav()      # (the one above is stopped)
cal = DuckNavigatorClient(cnav.address)
cnav.contract, cnav.cal_calls = "1.2", []
check("a navigator that speaks 1.2 lists no procedures, and is not asked for any", cal.calibration_list() == [] and cnav.cal_calls == [], cnav.cal_calls)
cnav.contract = "1.3"
cnav.cal_answer = {"calibration.list": {"procedures": [{"id": "odometry_scale", "params": {"speed_mps": 0.3}}]},
                   "calibration.start": {"ok": True, "procedure": "odometry_scale", "params": {"speed_mps": 0.3, "seconds": 8.0}},
                   "calibration.status": {"state": "running", "step": "walk"}}
check("one that speaks 1.3 lists them", cal.calibration_list() == [{"id": "odometry_scale", "params": {"speed_mps": 0.3}}])
check("a start, a status and a cancel are the contract's methods with the procedure and its parameters",
      cal.calibration_start("odometry_scale", {"seconds": 8}) == cnav.cal_answer["calibration.start"] and cal.calibration_status()["state"] == "running"
      and cal.calibration_cancel() is None
      and [m for m, _ in cnav.cal_calls][1:] == ["calibration.start", "calibration.status", "calibration.cancel"]
      and cnav.cal_calls[1][1] == {"procedure": "odometry_scale", "params": {"seconds": 8}}, cnav.cal_calls)
cnav.cal_answer["calibration.status"] = {"state": "walking"}
try:
    cal.calibration_status()
    outside = False
except ContractError:
    outside = True
check("a calibration state outside the contract is refused, as a goal's is", outside)
cnav.stop()

inst_file = installation_file(tmp / "installation.json", {"duck": {"navigator": "127.0.0.1:9", "gate": str(tmp / "inst-gate.sock"),
                                                                    "profile": str(tmp / "inst-state" / "profiles" / "duck")}},
                              observatory="http://obs.example:8070/", state=str(tmp / "inst-state"))
os.environ[installation.ENV] = str(inst_file)
a = DuckAdapter(RobotConfig({"id": "d", "robot": "duck", "variant": "sim", "adapter": {"type": "duck-sim"}}))
check("with an installation file: the gate, the navigator and the Observatory are its",
      str(a.gate_socket) == str(tmp / "inst-gate.sock") and a.nav_address == "127.0.0.1:9" and a.observatory == "http://obs.example:8070",
      (a.gate_socket, a.nav_address, a.observatory))
b = DuckAdapter(RobotConfig({"id": "d", "robot": "duck", "variant": "sim",
                             "adapter": {"type": "duck-sim", "gate_socket": "/x/g.sock", "navigator": "127.0.0.1:7"}}))
check("... and a robot file that names an address keeps its own", str(b.gate_socket) == "/x/g.sock" and b.nav_address == "127.0.0.1:7",
      (b.gate_socket, b.nav_address))
check("the profile is the installation's: the store's current version (1)", a.profile.meta["version"] == 1, a.profile.meta)

v2 = json.loads(REPO_PROFILE.read_text())
odo = v2["variants"]["sim"]["localisation"]["odometry"]
odo["scale"], odo["by_speed"]["0.3"] = 0.95, 0.951          # (the validator holds the scale to by_speed at cruise)
store.save("duck", v2)
check("a version saved after start is not read until a goal starts", a.profile.meta["version"] == 1)
note = a._goal_started({"run_key": "k", "profile": {"checksum": checksum(v2), "version": 2, "source": "given"}})
check("at a goal's start the profile is read again: version 2 is the one this adapter reads from this run",
      a.profile.meta["version"] == 2 and note is None, (a.profile.meta, note))
note = a._goal_started({"run_key": "k", "profile": {"checksum": checksum(repo), "version": 1, "source": "given"}})
check("must fail: a navigator that runs another version than Mission Control reads is said, with both versions",
      note is not None and "version 1" in note and "version 2" in note, note)
(tmp / "inst-state" / "profiles" / "duck" / "current").write_text("9\n")
note = a._goal_started({"run_key": "k", "profile": None})
check("a store that breaks between goals is said, and the last version read stays", note is not None and "could not read" in note
      and a.profile.meta["version"] == 2, note)
os.environ[installation.ENV] = str(BARE)
finish("test_duck_adapter")
