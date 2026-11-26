"""One contract, three adapters (RFC-0025 step 1, review 5.b): the fake, the duck behind its gate proxy, and the NXT behind nxt-web --fake
answer the same assertions about robots.RobotAdapter: structural conformance, the poll and the view, the map and sighting refusals, the
navigator, the lease and the drive, STOP (confirmed or not, never raised to the caller), and a robot that does not answer. What differs
by design (the NXT has no pose, no map, no navigator) is stated per adapter in EXPECT, so a difference that is not stated fails.
Stand-ins only, as test_duck_adapter.py and test_nxt_adapter.py use them: a robotd and a navigator server for the duck (the real gate
proxy between), nxt-web with a simulated brick. Never a real robot.
Run: make test-control (needs apps/nxt-web/.venv: make nxt-sync)"""

import atexit
import copy
import json
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from common import FAKE_FILE, Clock, check, finish, installation_file

from labrunner.gate import Proxy
from mission_control.core import MissionControl
from mission_control.errors import ApiError
from mission_control.robots import GatedAdapter, RobotAdapter, RobotConfig
from runfile import installation

ROOT = Path(__file__).resolve().parents[3]
NXT_WEB = os.environ.get("NXT_WEB", str(ROOT / "apps" / "nxt-web" / ".venv" / "bin" / "nxt-web"))
if not Path(NXT_WEB).exists():
    print(f"FAIL test_adapter_contract: {NXT_WEB} is missing (make nxt-sync)")
    sys.exit(1)

tmp = Path(tempfile.mkdtemp(prefix="mc-contract-"))
atexit.register(shutil.rmtree, tmp, True)
os.environ[installation.ENV] = str(installation_file(tmp / "bare-installation.json"))      # this machine's installation is never read


def wait(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class StubRobotd:
    """robotd as far as the gate and the adapter need it (as test_duck_adapter.py's): moves, stop, health and a state stream."""

    def __init__(self, path: Path, hangup: bool = False):
        self.hangup = hangup        # accepts the gate's connection and closes it: a robotd that is up and answers nothing
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock):
        if self.hangup:
            sock.close()
            return
        lock = threading.Lock()

        def send(msg):
            with lock:
                sock.sendall((json.dumps(msg) + "\n").encode())

        def stream():
            while True:
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": {
                        "odom": {"position": [0.0, 0.0, 0.117], "yaw": 0.0}, "move": {"applied": [0.0, 0.0, 0.0]},
                        "safety": {"fallen": False, "picked_up": False, "limp": False}, "policy": "walk",
                        "joints": [round(0.01 * k, 2) for k in range(15)]}})
                except OSError:
                    return
                time.sleep(0.1)

        for line in sock.makefile("r"):
            req = json.loads(line)
            m = req["method"]
            if m in ("robot.move", "robot.stop"):
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}})
            elif m == "robot.health":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"battery": {"percent": 63.0, "volts": 7.4}}})
            elif m == "robot.subscribe":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"policy": "walk"}})
                threading.Thread(target=stream, daemon=True).start()
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "no such method"}})


class StubNav:
    """duck-nav-server's API as far as the adapter reads it outside a goal: the map."""

    def __init__(self):
        class H(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    req = json.loads(line)
                    result = {"res_m": 0.05, "origin": [-0.1, -0.2], "width": 3, "height": 2, "cells": "?.#" + ".?#", "units": "site"} if req["method"] == "map" else (
                        {**req["params"]["odom"], "frame": "site", "placed": False} if req["method"] == "site_pose" else {})
                    self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n").encode())

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the three adapters, each with a robot that answers and one that does not ---------------------------------------------------------

def fake_mc(answers: bool) -> MissionControl:
    mc = MissionControl([RobotConfig(copy.deepcopy(FAKE_FILE))], clock=Clock(), wall=Clock())
    if not answers:
        mc.robots["fake-1"].adapter.robot.set_offline(True)
    return mc


robotd = StubRobotd(tmp / "robotd.sock")
proxy = Proxy(tmp / "gate.sock", tmp / "robotd.sock", takeover_names={"operator-laptop"}, log=tmp / "gate.jsonl", lease_s=10.0)
proxy.start()
deaf_robotd = StubRobotd(tmp / "deaf-robotd.sock", hangup=True)
deaf = Proxy(tmp / "deaf-gate.sock", tmp / "deaf-robotd.sock", log=tmp / "deaf-gate.jsonl", lease_s=10.0)
deaf.start()
nav = StubNav()


def duck_mc(answers: bool) -> MissionControl:
    gate = tmp / ("gate.sock" if answers else "deaf-gate.sock")
    return MissionControl([RobotConfig({"id": "duck-sim", "label": "Simulated duck", "robot": "duck", "variant": "sim",
                                        "adapter": {"type": "duck-sim", "gate_socket": str(gate), "navigator": nav.address}})])


NXT_PORT = free_port()
NXT_URL = f"http://127.0.0.1:{NXT_PORT}"
(tmp / "takeover.txt").write_text("operator-laptop  # may take the lock back\n")
proc = subprocess.Popen([NXT_WEB, "--fake", "--host", "127.0.0.1", "--port", str(NXT_PORT), "--config", str(tmp / "config.json"),
                         "--takeover-names", str(tmp / "takeover.txt")],
                        env=dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "miniview")), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def nxt_up() -> bool:
    try:
        with urllib.request.urlopen(NXT_URL + "/api/status", timeout=2) as r:
            return bool(json.loads(r.read()).get("connected"))
    except OSError:
        return False


def nxt_mc(answers: bool) -> MissionControl:
    raw = json.loads((ROOT / "apps" / "mission-control" / "robots.nxt" / "nxt-1.json").read_text())
    raw["adapter"]["url"] = NXT_URL if answers else f"http://127.0.0.1:{free_port()}"
    raw["adapter"]["allow_real_runs"] = True        # a file that holds the NXT itself is a real robot: a hand drive asks for the key (nxt-web is --fake)
    return MissionControl([RobotConfig(raw)])


# What differs by design, and nothing else: the pose, the map, the sighting, the navigator, the gate of its own, the Observatory's page, and what "online" measures
# when the robot behind a live gate is silent (the duck's link is its gate's answer; robotd down shows in the missing state and the unconfirmed STOP).
EXPECT = {
    "fake":  {"make": fake_mc, "id": "fake-1",   "gated": False, "pose": True,  "map": True,  "sighting": True,  "navigator": True,  "watch": False, "silent_online": False},
    "duck":  {"make": duck_mc, "id": "duck-sim", "gated": True,  "pose": True,  "map": True,  "sighting": False, "navigator": True,  "watch": True,  "silent_online": True},
    "nxt":   {"make": nxt_mc,  "id": "nxt-1",    "gated": True,  "pose": False, "map": False, "sighting": False, "navigator": False, "watch": True,  "silent_online": False},
}


def outcome(fn):
    """('ok', value) or ('api', status): an ApiError is a refusal the API shows; any other exception is a bug and propagates."""
    try:
        return "ok", fn()
    except ApiError as exc:
        return "api", exc.status


def refused(fn, status, code=None):
    try:
        fn()
    except ApiError as exc:
        return exc.status == status and (code is None or exc.code == code)
    return False


class Missing:
    call = None

    def make_navigator(self, gate, clock=None): ...
    def map(self): ...
    def sighting(self): ...


check("the protocol can say no: an object with no map_version is not a RobotAdapter", not isinstance(Missing(), RobotAdapter) and not isinstance(object(), RobotAdapter))

try:
    check("nxt-web --fake is up", wait(nxt_up, 20))
    for name, e in EXPECT.items():
        rid = e["id"]
        mc = e["make"](True)
        rt = mc.robots[rid]
        ad = rt.adapter

        check(f"{name}: the adapter is a RobotAdapter", isinstance(ad, RobotAdapter), type(ad).__name__)
        check(f"{name}: and a GatedAdapter exactly when it brings a gate of its own ({e['gated']})", isinstance(ad, GatedAdapter) == e["gated"] and hasattr(ad, "make_gate") == e["gated"])
        w = getattr(ad, "watch_url", None)
        check(f"{name}: watch_url is {'there and says None for no run' if e['watch'] else 'absent (the core reads it with getattr)'}",
              (w is not None and w(None) is None) if e["watch"] else w is None)

        # the poll and the view
        rt.poll(force=True)
        st = rt.status
        check(f"{name}: a poll is an answer: online, a status in the page's shape", rt.online() and isinstance(st, dict) and isinstance(st.get("mode"), str)
              and set(st["velocity"]) == {"vx", "vyaw"} and isinstance(st["flags"], dict) and "link" in st and "battery_pct" in st, st)
        check(f"{name}: pose {'in the site frame' if e['pose'] else 'absent'}", (st.get("pose") or {}).get("frame") == "site" if e["pose"] else "pose" not in st, st.get("pose"))
        view = mc.robot_view(rt)
        check(f"{name}: the robot view carries the robot's id, its online fact, the gate's lock, the status, and goes to JSON",
              view["id"] == rid and view["online"] is True and view["status"] == st and "holder" in view["lock"] and json.dumps(view), sorted(view))

        # the map, the sighting, the navigator: what the robot has, or the API's refusal
        check(f"{name}: map_version is an integer", isinstance(ad.map_version(), int) and not isinstance(ad.map_version(), bool))
        kind, got = outcome(ad.map)
        check(f"{name}: map is {'an occupancy grid in the site frame' if e['map'] else 'refused with a 404'}",
              (kind == "ok" and got["kind"] == "occupancy_grid" and got["frame"] == "site" and len(got["data"]) == got["width"] * got["height"]) if e["map"] else (kind, got) == ("api", 404), (kind, got))
        kind, got = outcome(ad.sighting)
        check(f"{name}: sighting is {'a dict' if e['sighting'] else 'refused with a 404'}", (kind == "ok" and isinstance(got, dict)) if e["sighting"] else (kind, got) == ("api", 404), (kind, got))
        check(f"{name}: the runtime made {'a navigator' if e['navigator'] else 'no navigator, and the adapter refuses one with a 501'}",
              (rt.navigator is not None) if e["navigator"] else (rt.navigator is None and refused(lambda: ad.make_navigator(rt.gate, mc.clock), 501)))

        # the lease and the drive
        a = rt.acquire("alice")
        check(f"{name}: acquire gives a session and the gate names the holder", isinstance(a["session"], str) and rt.gate.who()["holder"] == "alice", a)
        check(f"{name}: a second client is refused, naming the holder", refused(lambda: rt.acquire("bob"), 409, "held"))
        check(f"{name}: renew answers", isinstance(rt.renew(a["session"]), dict))
        check(f"{name}: a drive by the holder answers", isinstance(rt.drive(a["session"], 0.05, 0.0), dict))
        check(f"{name}: a session that is not ours is refused", refused(lambda: rt.drive("made-up", 0.05, 0.0), 409, "no_lease"))
        rt.release(a["session"])
        check(f"{name}: release frees it, and the released session drives no more", rt.gate.who()["holder"] is None and refused(lambda: rt.drive(a["session"], 0.05, 0.0), 409, "no_lease"))

        # STOP: from anyone, with no lease; it ends the lease and is confirmed
        a = rt.acquire("alice")
        rt.drive(a["session"], 0.05, 0.0)
        stop = rt.stop("bystander")
        check(f"{name}: STOP from anyone is confirmed, in the robot's own terms", stop == {"robot": rid, "confirmed": True, "online": True}, stop)
        check(f"{name}: it ended the lease, and the holder's next drive is refused with why", refused(lambda: rt.drive(a["session"], 0.05, 0.0), 409, "lease_ended") and rt.gate.who()["holder"] is None)
        events = [ev for ev in mc.bus.since(0, 100000)[0] if ev["kind"] == "stop"]
        check(f"{name}: and the bus has the stop with the same word", [ev["confirmed"] for ev in events] == [True], events)
        mc.close()

        # a robot that does not answer: a poll is not an error, STOP is accepted and cannot be confirmed, never raised
        mc = e["make"](False)
        rt = mc.robots[rid]
        rt.poll(force=True)
        check(f"{name}: a poll of a robot that does not answer raises nothing, and it has no state", rt.online() is e["silent_online"] and rt.status is None)
        raised = None
        try:
            stop = rt.stop("bystander")
        except Exception as exc:                                             # the contract says STOP never raises to its caller
            raised, stop = exc, None
        check(f"{name}: STOP to a robot that does not answer is accepted, not confirmed, and raises nothing", raised is None and stop == {"robot": rid, "confirmed": False, "online": e["silent_online"]}, raised or stop)
        check(f"{name}: the bus says not confirmed", [ev["confirmed"] for ev in mc.bus.since(0, 100000)[0] if ev["kind"] == "stop"] == [False])
        mc.close()
finally:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
finish("test_adapter_contract")
