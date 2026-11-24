"""The real duck's adapter (phase 5 item 4b unit B6) against stand-ins for everything behind it: a robotd, a tofd and a mapd on Unix sockets in
a folder of the test's own (the folder lab-link forwards into, on the real duck), the real gate proxy (labrunner.gate) in front of the
robotd, and a navigator API. No ssh, no simulator, no robot. What is tested: the robot offline with the link's reason (never an error) while
sockets are missing, online when they answer, offline again when one drops and when the gate goes, with STOP still reaching the robot;
the link check (runfile.linkcheck, one function for lab-link and Mission Control) on the same dead ends; a real run refused unless the robot file
says allow_real_runs, a goal and a calibration both, the navigator never asked; simulator-first still on top of it; and that the
addresses are the real duck's and never the simulator's.
Run: cd apps/mission-control && uv run python tests/test_duck_real.py"""

import atexit
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import check, finish, installation_file

from labrunner import link as lab_link
from labrunner.gate import Proxy
from mission_control import duck_real
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import ConfigError, RobotConfig, make_adapter
from runfile import linkcheck
from runfile import installation


def wait_for(cond, timeout=15.0, every=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(every)
    return None


class Daemon:
    """A Unix-socket JSON-RPC server: `answer(method, params)` is a result, `serve` the loop of one connection."""

    def __init__(self, path: Path):
        self.path, self.calls = Path(path), []
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(8)
        self.stopped = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(sock,), daemon=True).start()

    def serve(self, sock):
        for line in sock.makefile("r"):
            req = json.loads(line)
            self.calls.append((req["method"], req.get("params") or {}))
            sock.sendall((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": self.answer(req["method"], req.get("params") or {})}) + "\n").encode())

    def answer(self, method, params):
        return {}

    def stop(self, unlink: bool = True):
        """The robot's end goes: the listener closes; the file stays (a stale socket, what a dead ssh leaves) unless `unlink`."""
        self.stopped = True
        try:
            self.server.shutdown(socket.SHUT_RDWR)       # a thread blocked in accept() keeps a closed listener alive until it returns
        except OSError:
            pass
        self.server.close()
        if unlink:
            self.path.unlink(missing_ok=True)


class StubRobotd(Daemon):
    def __init__(self, path):
        self.x = 0.0
        super().__init__(path)

    def serve(self, sock):
        send_lock = threading.Lock()

        def send(msg):
            with send_lock:
                sock.sendall((json.dumps(msg) + "\n").encode())

        def stream():
            while True:
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state",
                          "params": {"odom": {"position": [self.x, 0.0, 0.117], "yaw": 0.0}, "move": {"applied": [0.0, 0.0, 0.0]},
                                     "safety": {"fallen": False, "picked_up": False, "limp": False}, "policy": "walk", "joints": []}})
                except OSError:
                    return
                time.sleep(0.1)

        for line in sock.makefile("r"):
            req = json.loads(line)
            m = req["method"]
            self.calls.append((m, req.get("params") or {}))
            if m == "robot.subscribe":
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"policy": "walk"}})
                threading.Thread(target=stream, daemon=True).start()
            else:
                send({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True, "battery": {"percent": 63.0}}})


class StubNav:
    """The navigator API as far as a goal and a calibration need it, scripted through its attributes."""

    def __init__(self):
        self.started, self.cal_calls, self.state = [], [], "running"
        self.server = __import__("socketserver").ThreadingTCPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self):
        stub = self

        class H(__import__("socketserver").StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    req = json.loads(line)
                    m, p = req["method"], req.get("params") or {}
                    if m == "hello":
                        result = {"name": "stub-nav", "version": "0", "contract": "1.3", "kinds": ["point"], "camera": False}
                    elif m == "goal.start":
                        stub.started.append(p)
                        result = {"run_key": "duck/apartment/mc-real-1", "profile": None}
                    elif m == "goal.status":
                        result = {"state": stub.state, "reason": None, "progress": None, "result": None, "broken": None, "run_key": "duck/apartment/mc-real-1",
                                  "decisions": [], "decisions_n": 0, "anomalies": [], "anomalies_n": 0, "objects": None, "objects_v": -1}
                    elif m == "map":
                        result = {"res_m": 0.05, "origin": [0.0, 0.0], "width": 2, "height": 1, "cells": "?."}
                    elif m == "calibration.start":
                        stub.cal_calls.append((m, p))
                        result = {"params": {"speed_mps": 0.3, "seconds": 2.0}}
                    elif m == "calibration.status":
                        stub.cal_calls.append((m, p))
                        result = {"state": "running"}
                    else:
                        result = {}
                    self.wfile.write((json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n").encode())

        return H


tmp = Path(tempfile.mkdtemp(prefix="mc-duck-real-"))
atexit.register(shutil.rmtree, tmp, True)
BARE = installation_file(tmp / "bare-installation.json")
os.environ[installation.ENV] = str(BARE)

# --- the link check says what lab-link says ---------------------------------------------------------------------------------------------
par = tmp / "parity"
par.mkdir()
cases = {}
cases["missing"] = par / "missing.sock"
(par / "file").write_text("not a socket")
cases["a file"] = par / "file"
gone = Daemon(par / "stale.sock")
gone.stop(unlink=False)
cases["stale"] = par / "stale.sock"


class Hangup(Daemon):
    def serve(self, sock):
        sock.close()


class Silent(Daemon):
    def serve(self, sock):
        time.sleep(3)


class Talks(Daemon):
    pass


class Garbage(Daemon):
    def serve(self, sock):
        sock.recv(100)
        sock.sendall(b"not json\n")


hang, silent, talks, garbage = Hangup(par / "hang.sock"), Silent(par / "silent.sock"), Talks(par / "ok.sock"), Garbage(par / "garbage.sock")
cases.update({"a hang-up": hang.path, "silent": silent.path, "answering": talks.path, "garbage": garbage.path})
for name, path in cases.items():
    theirs = lab_link.check_socket("x", path, "robot.health", 0.4)
    mine = linkcheck.check_socket(path, "robot.health", 0.4)
    check(f"the link check on {name}: lab-link's wrapper says the same verdict and words: {mine[1][:70]}", mine[:2] == (theirs.ok, theirs.why), (mine, theirs))
check("the answering one is alive and each dead end is dead", [linkcheck.check_socket(p, "robot.health", 0.4)[0] for p in cases.values()]
      == [False, False, False, False, False, True, False])
check("the gate's dead ends say gate, not ssh (a gate is a process here)",
      "the gate is not running" in linkcheck.check_socket(cases["missing"], "gate.who", gate=True)[1]
      and "ssh" not in linkcheck.check_socket(cases["stale"], "gate.who", gate=True)[1])
check("the probes are lab-link's own: the names, the files and the questions of the duck's three forwards",
      [(n, f.format(robot="duck"), m) for n, f, m in duck_real.FORWARDS]
      == [(f.name, f.local.name, f.method) for f in lab_link.duck_forwards(Path("/x"))])
for d in (hang, silent, talks, garbage):
    d.stop()

# --- the addresses are the real duck's, never the simulator's ------------------------------------------------------------------------------
HOME = Path("~/.cache/duck-real").expanduser()
sim_entry = {"duck": {"gate": str(tmp / "SIM-gate.sock"), "navigator": "127.0.0.1:8061"}}


def adapter_with(entry, raw=None):
    os.environ[installation.ENV] = str(installation_file(tmp / f"inst-{abs(hash(json.dumps(entry, sort_keys=True)))}.json", entry))
    try:
        return make_adapter(RobotConfig({"id": "d", "robot": "duck", "adapter": {"type": "duck-real", **(raw or {})}}), time.monotonic)
    finally:
        os.environ[installation.ENV] = str(BARE)


a = adapter_with(sim_entry)
check("must fail: an installation that names the simulator's gate and navigator (no variant) is not the real duck's: the real folder's gate and "
      "navigator port 8062 are used", a.gate_socket == HOME / "duck-gate.sock" and a.nav_address == "127.0.0.1:8062", (a.gate_socket, a.nav_address))
a = adapter_with({"duck": {**sim_entry["duck"], "variant": "real"}})
check("an installation entry that says its variant is real is read: its gate and navigator",
      a.gate_socket == tmp / "SIM-gate.sock" and a.nav_address == "127.0.0.1:8061", (a.gate_socket, a.nav_address))
a = adapter_with(sim_entry, {"gate_socket": str(tmp / "mine.sock"), "navigator": "10.0.0.2:9000", "link_dir": str(tmp / "elsewhere")})
check("the robot file's adapter block names its own: gate, navigator and the folder lab-link forwards into",
      a.gate_socket == tmp / "mine.sock" and a.nav_address == "10.0.0.2:9000" and a.link_dir == tmp / "elsewhere"
      and [p[1] for p in a.watch.probes][:3] == [tmp / "elsewhere" / n for n in ("duck.sock", "duck-tof.sock", "duck-map.sock")], a.watch.probes)
try:
    adapter_with({"duck": {"variant": "sim"}})
    sim_refused = None
except ConfigError as exc:
    sim_refused = str(exc)
check("must fail: a duck-real file on a machine that runs the duck as the simulator is refused, naming the installation's key",
      sim_refused and "robots.duck.variant" in sim_refused and "'sim'" in sim_refused, sim_refused)

# --- Mission Control with no link and no gate: offline, with the reason, not an error ----------------------------------------------------------
LINK = tmp / "real"
LINK.mkdir()
nav = StubNav()
ADAPTER = {"type": "duck-real", "link_dir": str(LINK), "navigator": nav.address, "observatory": "http://127.0.0.1:8070"}
mc = MissionControl([RobotConfig({"id": "duck-real", "robot": "duck", "adapter": ADAPTER}),
                     RobotConfig({"id": "duck-real-go", "robot": "duck", "adapter": {**ADAPTER, "allow_real_runs": True}}),
                     RobotConfig({"id": "duck-twin", "robot": "duck", "adapter": {"type": "fake"}})], state_dir=tmp / "state")
mc.robot("duck-twin").cfg.variant = "sim"
for rid in ("duck-real", "duck-real-go"):
    mc.robots[rid].adapter.watch.every_s, mc.robots[rid].adapter.watch.timeout_s = 0.3, 0.5
check("the real duck's variant is real (the adapter's default), and allow_real_runs is read from its file",
      [(mc.robots[r].cfg.variant, mc.robots[r].cfg.allow_real_runs) for r in ("duck-real", "duck-real-go")] == [("real", False), ("real", True)])
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}/api/v1"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def robot(rid="duck-real-go"):
    return call("GET", f"/robots/{rid}")[1]["robot"]


def run_of(rid):
    return call("GET", f"/goal-runs/{rid}")[1]["run"]


why = wait_for(lambda: robot().get("offline_reason"), 10)
check("Mission Control started with no socket at all, and the robot is offline with the link's reason",
      robot()["online"] is False and why and "link is down" in why and "lab-link check: FAIL" in why, why)
check("the reason names every socket and what is wrong with it, and where the recipe is",
      all(f"{n}: no socket file" in why for n in ("robot", "depth", "map", "gate")) and "REAL-DUCK-LINK.md" in why, why)
check("it is not an error: no `error` event on the bus for the robot (the loop caught nothing)",
      not [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "error"], [e for e in mc.bus.since(0, 100000)[0] if e["kind"] == "error"][:2])
check("a robot-offline event carries the same reason", any(e["kind"] == "robot-offline" and e["robot"] == "duck-real-go" and "no socket file" in (e["error"] or "")
                                                          for e in mc.bus.since(0, 100000)[0]))
st, b = call("POST", "/goal-runs", {"goal": {"kind": "point", "params": {"x": 1.0, "y": 0.0}}, "robots": ["duck-real-go"], "target": "real"})
check("a run on the offline robot is not queued: 503 robot_offline", st == 503 and b["error"]["code"] == "robot_offline", b)

# --- the stand-ins come up: the robot comes online ---------------------------------------------------------------------------------------------
robotd = StubRobotd(LINK / "duck.sock")
tofd, mapd = Daemon(LINK / "duck-tof.sock"), Daemon(LINK / "duck-map.sock")
proxy = Proxy(LINK / "duck-gate.sock", LINK / "duck.sock", takeover_names={"operator-laptop"}, log=tmp / "gate.jsonl", lease_s=10.0)
proxy.start()
check("with the three forwards and the gate answering, the robot is online with no reason",
      wait_for(lambda: robot()["online"], 20) and "offline_reason" not in robot(), robot())
check("its state is the gate's subscription, in the page's shape, link duck-gate",
      wait_for(lambda: (robot().get("status") or {}).get("pose")) and robot()["status"]["link"] == "duck-gate" and robot()["status"]["pose"]["frame"] == "site",
      robot().get("status"))
check("the gate was started after Mission Control and is its lock all the same: who answers, nobody holds", robot()["lock"]["holder"] is None
      and "unreachable" not in robot()["lock"], robot()["lock"])
check("the robot's own connection to the gate was made when the gate came (the notice 'someone else drives' has somewhere to arrive)",
      wait_for(lambda: mc.robots["duck-real-go"].gate._wires.get(mc.robots["duck-real-go"].gate._own) is not None
               and mc.robots["duck-real-go"].gate._wires[mc.robots["duck-real-go"].gate._own].alive))
check("the map is the navigator API's, in the site frame", call("GET", "/robots/duck-real-go/map")[1]["map"]["data"] == [-1, 0])
check("the checks asked read-only questions of each daemon and nothing else",
      {m for m, _ in tofd.calls} == {"tof.stream"} and {m for m, _ in mapd.calls} == {"map.status"}
      and {m for m, _ in robotd.calls} <= {"robot.health", "robot.subscribe"}, ({m for m, _ in robotd.calls}, tofd.calls[:1], mapd.calls[:1]))
check("nothing has moved the robot: no robot.move reached robotd", not [c for c in robotd.calls if c[0] in ("robot.move", "robot.stop")])

# --- a real run is refused unless the robot file allows it ---------------------------------------------------------------------------------------
mc.sites.create("Home", "apartment")
for rid in ("duck-real", "duck-real-go", "duck-twin"):
    call("PUT", f"/robots/{rid}/site", {"site": "home"})
check("the held robot is online too (a robot offline would be refused for being offline, not for the key)",
      wait_for(lambda: robot("duck-real")["online"], 20), robot("duck-real"))
POINT = {"kind": "point", "params": {"x": 1.0, "y": 0.0}}
for target in ("real", "sim"):
    st, b = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-real"], "target": target})
    r = b["run"]
    check(f"must fail: a goal run on the real duck whose file does not allow real runs is refused (target {target}), naming the key and the safety review",
          st in (200, 201) and r["state"] == "refused" and "allow_real_runs" in r["reason"] and "REAL-DUCK-SAFETY-REVIEW.md" in r["reason"], r)
check("... and the navigator was never asked, and nothing moved or was leased", nav.started == [] and not [c for c in robotd.calls if c[0] in ("robot.move", "gate.acquire")]
      and robot("duck-real")["goal_run"] is None, (nav.started, robot("duck-real")["lock"]))
st, b = call("POST", "/robots/duck-real/calibration", {"procedure": "odometry_scale", "params": {"seconds": 2}})
check("must fail: a calibration walk is refused the same way (it walks blind): 409 real_runs_not_allowed naming the key",
      st == 409 and b["error"]["code"] == "real_runs_not_allowed" and "allow_real_runs" in b["error"]["message"], b)
check("... and the navigator was never asked to calibrate", not [c for c in nav.cal_calls if c[0] == "calibration.start"], nav.cal_calls)
check("the refusal is a recorded refused run, as a goal not as expected is (the page lists it)",
      call("GET", "/goal-runs")[1]["runs"][0]["state"] == "refused")
st, b = call("POST", "/robots/duck-real/drive", {"session": "any", "vx": 0.1, "vyaw": 0.0})
check("must fail: hand drive on a real robot whose file does not allow real runs is refused too: 409 real_runs_not_allowed naming the key (E5)",
      st == 409 and b["error"]["code"] == "real_runs_not_allowed" and "allow_real_runs" in b["error"]["message"], (st, b))
check("... and no robot.move reached robotd", not [c for c in robotd.calls if c[0] == "robot.move"])
st, b = call("POST", "/robots/duck-real-go/drive", {"session": "any", "vx": 0.1, "vyaw": 0.0})
check("a robot whose file allows real runs is not refused for the key: its drive gets as far as the lease (409 no_lease for an unknown session)",
      st == 409 and b["error"]["code"] == "no_lease", (st, b))
floor = mc.robots["duck-real-go"].cfg.profile.get("locomotion.stand_turn.min_rad_s")
check("the duck's profile has a stand-turn floor (E10: the walking network starts no turn from a stand below it)", isinstance(floor, float) and floor > 0, floor)
for label, body in (("a left turn", {"vx": 0.0, "vyaw": floor / 2}), ("a right turn", {"vx": 0.0, "vyaw": -floor / 2}), ("a turn just under it", {"vx": 0.0, "vyaw": floor - 0.01})):
    st, b = call("POST", "/robots/duck-real-go/drive", {"session": "any", **body})
    check(f"must fail: {label} on the spot below the floor does not start from a stand: 422 naming the floor", st == 422 and b["error"]["code"] == "stand_turn_below_floor"
          and f"{floor:g} rad/s" in b["error"]["message"] and "does not start from a stand" in b["error"]["message"], (st, b))
for label, body in (("at the floor", {"vx": 0.0, "vyaw": floor}), ("above it", {"vx": 0.0, "vyaw": 2 * floor}), ("walking while turning slowly", {"vx": 0.2, "vyaw": 0.5}),
                    ("no turn at all", {"vx": 0.0, "vyaw": 0.0}), ("a plain walk", {"vx": 0.1})):
    st, b = call("POST", "/robots/duck-real-go/drive", {"session": "any", **body})
    check(f"{label} is not held to the floor: it gets as far as the lease (409 no_lease)", st == 409 and b["error"]["code"] == "no_lease", (st, b))
st, b = call("POST", "/robots/duck-real/stop", {"client": "page"})
check("STOP is never refused for the key: the held robot's STOP goes through the gate to robotd and is confirmed",
      st == 200 and b["stop"]["confirmed"] is True and ("robot.stop", {}) in robotd.calls, (st, b))

# the robot file that allows it: the run goes to the navigator
nav.state = "running"
st, b = call("POST", "/goal-runs", {"goal": {**POINT, "sim_first": False}, "robots": ["duck-real-go"], "target": "real"})
r = b["run"]
check("a robot whose file allows real runs starts the goal: the navigator got it, the run is running with its run key and Watch link",
      r["state"] == "running" and len(nav.started) == 1 and r["run_key"] == "duck/apartment/mc-real-1"
      and r["watch"] == "http://127.0.0.1:8070/watch/duck/apartment/mc-real-1", r)
check("the real run records that it was not rehearsed (B8) beside the permission", r["conditions"]["rehearsal"]["state"] == "not_rehearsed"
      and r["conditions"]["rehearsal"]["flagged"] is False, r["conditions"])
nav.state = "reached"
end = wait_for(lambda: run_of(r["id"])["state"] == "reached" and run_of(r["id"]), 10)
check("and ends as the navigator says", end and end["as_expected"] is True, end)
st, b = call("POST", "/robots/duck-real-go/calibration", {"procedure": "odometry_scale", "params": {"seconds": 2}})
check("a calibration on the allowed robot starts: the navigator was asked", st == 201 and any(c[0] == "calibration.start" for c in nav.cal_calls), (st, b))

# --- simulator-first is on top of the permission ---------------------------------------------------------------------------------------------------
FLAGGED = {**POINT, "name": "to the door", "sim_first": True}
nav.state = "running"
n0 = len(nav.started)
st, b = call("POST", "/goal-runs", {"goal": FLAGGED, "robots": ["duck-real-go"], "target": "real"})
check("must fail: a simulator-first goal on a robot that is allowed is still refused with no rehearsal, naming the twin; the navigator not asked",
      b["run"]["state"] == "refused" and "simulator-first" in b["run"]["reason"] and "duck-twin" in b["run"]["reason"] and len(nav.started) == n0, b["run"])
call("POST", "/robots/duck-real-go/calibration/cancel")
st, b = call("POST", "/goal-runs", {"goal": FLAGGED, "robots": ["duck-twin"], "target": "sim"})
twin = wait_for(lambda: run_of(b["run"]["id"])["state"] == "reached" and run_of(b["run"]["id"]), 60)
check("the twin (the simulated duck's place, here a fake) rehearses it", twin and twin["as_expected"] is True, twin)
st, b = call("POST", "/goal-runs", {"goal": FLAGGED, "robots": ["duck-real-go"], "target": "real"})
check("after the rehearsal the allowed robot takes it, and the run names what rehearsed it",
      b["run"]["state"] == "running" and b["run"]["conditions"]["rehearsal"]["state"] == "rehearsed" and b["run"]["conditions"]["rehearsal"]["run"] == twin["id"]
      and len(nav.started) == n0 + 1, b["run"])
st, b2 = call("POST", "/goal-runs", {"goal": FLAGGED, "robots": ["duck-real"], "target": "real"})
check("must fail: the rehearsal is not the permission: the robot whose file does not allow is refused for the key",
      b2["run"]["state"] == "refused" and "allow_real_runs" in b2["run"]["reason"], b2["run"])
nav.state = "reached"
wait_for(lambda: robot()["goal_run"] is None, 10)

# --- the link drops, the gate goes, and STOP still gets through ---------------------------------------------------------------------------------------
tofd.stop()
why = wait_for(lambda: robot().get("offline_reason") if not robot()["online"] else None, 10)
check("a forward that drops (the depth socket gone) takes the robot offline, saying which and why", why and "depth: no socket file" in why
      and "robot:" not in why, why)
st, b = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-real-go"], "target": "real"})
check("must fail: no run starts on a robot whose link is down", st == 503 and b["error"]["code"] == "robot_offline", b)
st, b = call("POST", "/robots/duck-real-go/stop", {"client": "page"})
check("STOP is not held up by the link check: it goes through the gate to robotd and is confirmed",
      st == 200 and b["stop"]["confirmed"] is True and ("robot.stop", {}) in robotd.calls, b)
tofd = Daemon(LINK / "duck-tof.sock")
check("the forward back, the robot is online again with no reason", wait_for(lambda: robot()["online"] and "offline_reason" not in robot(), 15), robot())
proxy.stop()
why = wait_for(lambda: robot().get("offline_reason") if not robot()["online"] else None, 10)
check("the gate gone (it exits when its upstream closes): offline, and the gate is named", why and "gate:" in why and "depth:" not in why, why)
proxy = Proxy(LINK / "duck-gate.sock", LINK / "duck.sock", takeover_names={"operator-laptop"}, log=tmp / "gate.jsonl", lease_s=10.0)
proxy.start()
check("started again, the robot is online and Mission Control's own connection to it is made again",
      wait_for(lambda: robot()["online"], 20) and wait_for(lambda: mc.robots["duck-real-go"].gate._wires.get(mc.robots["duck-real-go"].gate._own) is not None
                                                          and mc.robots["duck-real-go"].gate._wires[mc.robots["duck-real-go"].gate._own].alive), robot())
wait_for(lambda: robot("duck-real")["online"], 20)        # the held robot's link check follows the gate's return on its own beat: offline is a 503, not a refusal
st, b = call("POST", "/goal-runs", {"goal": POINT, "robots": ["duck-real"], "target": "sim"})
check("a refusal still holds after all that", "run" in b and b["run"]["state"] == "refused" and "allow_real_runs" in b["run"]["reason"], b)

mc._stopping.set()
proxy.stop()
finish("test_duck_real")
