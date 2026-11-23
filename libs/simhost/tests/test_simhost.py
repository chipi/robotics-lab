"""The host file and the host's reset (RFC-0021 §5 step 1): a host file read, refused when wrong, never defaulted to this
workstation; the sockets it names; `simhost init` and `show`; the reset's refusal of a duck-sim that asks sudo. No
simulator. Run: cd robots/duck && uv run python tests/test_simhost.py"""

import atexit
import contextlib
import io
import json
import os
import shutil
import socket
import tempfile
from pathlib import Path

import simhost
from simhost import cli
from simhost.host import HostError

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="simhost-"))
atexit.register(shutil.rmtree, tmp, True)
GOOD = {"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a",
        "pollen": {"microduck": str(tmp / "microduck"), "microduck_rl": str(tmp / "rl")},
        "state": str(tmp / "state"), "truth_port": 7801, "cargo_bin": "~/.cargo/bin"}


def write(d, name="host.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps(d))
    return p


def refused(d) -> str:
    try:
        simhost.load(write(d, "bad.json"))
    except HostError as e:
        return str(e)
    return ""


h = simhost.load(write(GOOD))
check("the sockets are duck-sim's, in the state folder, by the robot's name",
      h.sockets == {"robot": tmp / "state/duck-a.sock", "depth": tmp / "state/duck-a-tof.sock",
                    "map": tmp / "state/duck-a-map.sock", "gate": tmp / "state/duck-a-gate.sock",
                    "camera": tmp / "state/duck-a-camera.sock"}, h.sockets)
check("the scenarios and Pollen's scene folder come from the host",
      h.scenarios == tmp / "state/scenarios" and h.scene_dir == tmp / "rl/src/mjlab_microduck/robot/microduck")
check("~ in a path is this user's home", h.cargo_bin == Path(os.path.expanduser("~/.cargo/bin")), h.cargo_bin)
named = simhost.load(write({**GOOD, "sockets": {"robot": "/fwd/duck.sock"}, "truth_port": None}, "named.json"))
check("a socket the file names is used, the others stay duck-sim's",
      named.sockets["robot"] == Path("/fwd/duck.sock") and named.sockets["map"] == tmp / "state/duck-a-map.sock")
check("a host with no truth says so (null port)", named.truth_port is None)
check("as_json reads back as the same host", simhost.parse(h.as_json(), h.source) == h)

for why, d, says in [("an unknown key", {**GOOD, "data": "/x"}, "unknown keys"),
                     ("another version", {**GOOD, "host": 2}, "version 1"),
                     ("another kind", {**GOOD, "kind": "gazebo"}, "kind"),
                     ("a robot with a path in it", {**GOOD, "robot": "../x"}, "robot"),
                     ("one Pollen checkout missing", {**GOOD, "pollen": {"microduck": "/a"}}, "pollen"),
                     ("a port out of range", {**GOOD, "truth_port": 70000}, "truth_port"),
                     ("a port that is a bool", {**GOOD, "truth_port": True}, "truth_port"),
                     ("a socket key not known", {**GOOD, "sockets": {"lidar": "/c"}}, "sockets")]:
    msg = refused(d)
    check(f"refused: {why}, the reason named with the file", says in msg and "bad.json" in msg, msg)

os.environ.pop(simhost.ENV, None)
missing = tmp / "none" / "host.json"
try:
    simhost.load(missing)
    msg = ""
except HostError as e:
    msg = str(e)
check("a missing host file is an error that names the file and `simhost init` (no fallback)",
      str(missing) in msg and "simhost init" in msg, msg)
os.environ[simhost.ENV] = str(write(GOOD, "from-env.json"))
check("$ROBOTICS_LAB_HOST is read when no file is given", simhost.where() == tmp / "from-env.json")
check("a file given wins over $ROBOTICS_LAB_HOST", simhost.where(tmp / "host.json") == tmp / "host.json")
os.environ.pop(simhost.ENV)
check("else the default under ~/.config", simhost.where() == Path(os.path.expanduser("~/.config/robotics-lab/host.json")))

out = tmp / "init" / "host.json"
with contextlib.redirect_stdout(io.StringIO()):
    code = cli.main(["--host", str(out), "init", "--microduck", "/p/microduck", "--microduck-rl", "/p/rl"])
check("simhost init writes a host file that loads", code == 0 and simhost.load(out).microduck == Path("/p/microduck"))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    code = cli.main(["--host", str(out), "init", "--microduck", "/q", "--microduck-rl", "/q"])
check("simhost init does not replace a host file without --force",
      code == 1 and simhost.load(out).microduck == Path("/p/microduck"), err.getvalue())
with contextlib.redirect_stdout(io.StringIO()):
    code = cli.main(["--host", str(out), "init", "--microduck", "/q", "--microduck-rl", "/q", "--truth-port", "0", "--force"])
check("--force replaces it; --truth-port 0 is a host with no truth",
      code == 0 and simhost.load(out).microduck == Path("/q") and simhost.load(out).truth_port is None)
shown = io.StringIO()
with contextlib.redirect_stdout(shown):
    code = cli.main(["--host", str(out), "show"])
check("simhost show prints the file read and its sockets", code == 0 and str(out) in shown.getvalue()
      and "duck-a-map.sock" in shown.getvalue(), shown.getvalue()[:200])
err = io.StringIO()
with contextlib.redirect_stderr(err):
    code = cli.main(["--host", str(missing), "show"])
check("a command with no host file exits 2 and says why", code == 2 and "no host file" in err.getvalue(), err.getvalue())

# The host's reset never calls a duck-sim that asks sudo with no terminal (docs/wip/DUCK-SIM-FOR-AGENTS.md).
(tmp / "microduck" / "scripts").mkdir(parents=True)
sim_script = tmp / "microduck" / "scripts" / "duck-sim"
sim_script.write_text('        if sudo systemctl is-active --quiet "$name" 2>/dev/null; then\n')
try:
    simhost.duck_sim(h)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("an unpatched duck-sim (sudo on every down) is refused, the patch named", "duck-sim-sudo-free-down.patch" in msg, msg)
sim_script.write_text('        if systemctl is-active --quiet "$name" 2>/dev/null; then\n')
check("a patched duck-sim is used, from the host's microduck checkout", simhost.duck_sim(h) == str(sim_script))

# Stopping mapd: the pid file's process is stopped only when it is mapd, and it is known on a host with no /proc (macOS: on
# the MacBook on 2026-11-21 mapd was left running and its pid file deleted, as the check read /proc only).
import subprocess  # noqa: E402
import sys  # noqa: E402

from simhost import simulator  # noqa: E402

(tmp / "state").mkdir(exist_ok=True)
for proc_root, where in ((Path("/proc"), "with /proc"), (tmp / "no-proc", "with no /proc (ps, as on macOS)")):
    simulator.PROC = proc_root
    stand_in = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "mapd", "--config", "x"])
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "not-the-map"])
    try:
        (tmp / "state" / "mapd.pid").write_text(str(other.pid))
        simulator.stop_mapd(h)
        check(f"{where}: a process that is not mapd is not stopped", other.poll() is None)
        (tmp / "state" / "mapd.pid").write_text(str(stand_in.pid))
        simulator.stop_mapd(h)
        stand_in.wait(5)
        check(f"{where}: mapd is stopped, and its pid file goes with it",
              stand_in.returncode is not None and not (tmp / "state" / "mapd.pid").exists(), stand_in.returncode)
    finally:
        for p in (stand_in, other):
            if p.poll() is None:
                p.kill()
                p.wait()
simulator.PROC = Path("/proc")

# ---- the truth sampler (RFC-0021 step 2): the runner's own reader of the body server ---------------------------------------
import math  # noqa: E402
import socketserver  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from simhost.truth import Sampler  # noqa: E402


class FakeBody(socketserver.ThreadingTCPServer):
    """The body server's two ops a sampler uses; the trunk at x = sim_time (it moves 1 m per simulated second), its
    simulated time running at `rtf` of the wall clock. Counts its connections."""
    allow_reuse_address = daemon_threads = True

    def __init__(self, rtf: float):
        self.rtf, self.t0, self.connections = rtf, time.monotonic(), 0
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.server.connections += 1
        for line in self.rfile:
            req = json.loads(line)
            if req["op"] == "hello":
                out = {"ok": True}
            else:
                st = (time.monotonic() - self.server.t0) * self.server.rtf
                yaw = 0.5
                out = {"trunk": [st, -1.0, 0.116], "sim_time": st,
                       "imu": {"quat": [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]}}
            self.wfile.write((json.dumps(out) + "\n").encode())


body = FakeBody(rtf=0.5)
threading.Thread(target=body.serve_forever, daemon=True).start()
seen = []
port_host = simhost.parse({**GOOD, "truth_port": body.server_address[1]}, tmp / "fake.json")
sampler = Sampler(port_host, on_sample=seen.append, hz=50).start()
first = sampler.latest
time.sleep(0.6)
sampler.stop()
check("start() returns with a sample in hand: the trunk's x, y, yaw, its height and orientation",
      first is not None and first.pose[1] == -1.0 and abs(first.pose[2] - 0.5) < 1e-9 and first.z == 0.116
      and len(first.quat) == 4, first)
check("samples come on their own thread, at about the rate asked (50 Hz for 0.6 s)", 20 <= len(seen) <= 40, len(seen))
check("each sample carries the host's wall clock (what a navigator row is paired by) and the runner's own t, in order",
      all(abs(s.wall_ns - time.time_ns()) < 5e9 for s in seen) and [s.t for s in seen] == sorted(s.t for s in seen))
check("the real-time factor is the simulated time against the wall clock (0.5 here)", abs(sampler.rtf() - 0.5) < 0.05,
      sampler.rtf())
check("one connection to the body server", body.connections == 1, body.connections)
try:
    Sampler(simhost.parse({**GOOD, "truth_port": None}, tmp / "none.json"))
    msg = ""
except ValueError as e:
    msg = str(e)
check("a host with no truth has no sampler, and says so", "no truth" in msg, msg)
body2 = FakeBody(rtf=1.0)
threading.Thread(target=body2.serve_forever, daemon=True).start()
gone = Sampler(simhost.parse({**GOOD, "truth_port": body2.server_address[1]}, tmp / "gone.json"), hz=50).start()
body2.shutdown()
body2.server_close()
gone._body._sock.shutdown(2)          # the body server gone: the next read fails
time.sleep(0.3)
check("a body server that goes away stops the sampler with the error said (a judge with no truth must know)",
      gone.error is not None, gone.error)
gone.stop()
body.shutdown()

# ---- the host kind nxt-kinematic-sim (RFC-0025 §3.4, NXT-D0): nxt-web --sim; no Pollen keys; a restart; a truth over HTTP -------
import stat  # noqa: E402
import urllib.error  # noqa: E402

from simhost import nxt  # noqa: E402

NXT = {"host": 1, "kind": "nxt-kinematic-sim", "robot": "nxt-1", "state": str(tmp / "nxt-state"),
       "nxt_web": {"url": "http://127.0.0.1:8123", "project": str(tmp / "nxt-web")}, "scene": str(tmp / "scene.json"),
       "start": [0.5, -1, 1.5], "params": None}
nh = simhost.load(write(NXT, "nxt.json"))
check("an nxt host file loads as an NxtHost, the kind kept", isinstance(nh, simhost.NxtHost) and nh.kind == "nxt-kinematic-sim"
      and nh.start == (0.5, -1.0, 1.5) and nh.scene == tmp / "scene.json" and nh.params is None, nh)
check("its truth port is nxt-web's, and it names one connection", nh.truth_port == 8123
      and nh.connections() == {"nxt-web": "http://127.0.0.1:8123"})
check("an nxt host reads back from its own json", simhost.parse(nh.as_json(), nh.source) == nh)
check("an nxt host has no Pollen fields: a duck field is an AttributeError at once",
      not any(hasattr(nh, a) for a in ("microduck", "sockets", "cargo_bin", "scenarios", "scene_dir")))
check("the duck's host is the same class and fields as before", isinstance(h, simhost.Host) and h.kind == "pollen-duck-sim")
check("the table has both kinds, each with the sensor kinds it simulates",
      list(simhost.KINDS) == ["pollen-duck-sim", "nxt-kinematic-sim"] and simhost.KINDS["nxt-kinematic-sim"].simulates == ("range",)
      and "tof8x8" in simhost.KINDS["pollen-duck-sim"].simulates)
for why, d, says in [("a Pollen key on the nxt kind (a duck file copied over)", {**NXT, "pollen": {"microduck": "/a", "microduck_rl": "/b"}}, "unknown keys"),
                     ("cargo_bin on the nxt kind", {**NXT, "cargo_bin": "~/.cargo/bin"}, "unknown keys"),
                     ("sockets on the nxt kind", {**NXT, "sockets": {}}, "unknown keys"),
                     ("a truth_port on the nxt kind (it is nxt-web's port)", {**NXT, "truth_port": 7801}, "unknown keys"),
                     ("a url with no port", {**NXT, "nxt_web": {**NXT["nxt_web"], "url": "http://127.0.0.1"}}, "nxt_web.url"),
                     ("a url that is not http", {**NXT, "nxt_web": {**NXT["nxt_web"], "url": "ftp://x:21"}}, "nxt_web.url"),
                     ("nxt_web without its project", {**NXT, "nxt_web": {"url": "http://127.0.0.1:8123"}}, "nxt_web"),
                     ("no scene", {k: v for k, v in NXT.items() if k != "scene"}, "scene"),
                     ("a start of two numbers", {**NXT, "start": [0, 0]}, "start"),
                     ("a start with a string in it", {**NXT, "start": [0, 0, "x"]}, "start"),
                     ("a robot with a path in it", {**NXT, "robot": "a/b"}, "robot"),
                     ("a duck key missing is not asked of the nxt kind, but a wrong version is", {**NXT, "host": 2}, "version 1")]:
    msg = refused(d)
    check(f"refused: {why}, the reason named with the file", says in msg and "bad.json" in msg, msg)



from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


def stand_in(pose, connected=True, truth=True):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/api/status":
                body, code = {"connected": connected}, 200
            elif self.path == "/api/sim/truth" and truth:
                body, code = {"wall_ns": time.time_ns(), "pose": list(pose)}, 200
            else:
                body, code = {"ok": False}, 404
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


web = stand_in((1.0, 2.0, 0.5))
live = simhost.parse({**NXT, "nxt_web": {**NXT["nxt_web"], "url": f"http://127.0.0.1:{web.server_address[1]}"}}, tmp / "live.json")
wall, pose = nxt.read_truth(live)
check("the truth reader gives (wall_ns, pose) from nxt-web's own port", abs(wall - time.time_ns()) < 5e9 and pose == (1.0, 2.0, 0.5), (wall, pose))
got = []
nsampler = Sampler(live, on_sample=got.append, hz=50).start()
first = nsampler.latest
time.sleep(0.2)
nsampler.stop()
check("a Sampler works on an nxt host: z is 0, the quaternion is the yaw alone, there is no sim_time and so no rtf",
      first.pose == (1.0, 2.0, 0.5) and first.z == 0.0 and first.sim_time is None and nsampler.rtf() is None
      and abs(first.quat[0] - math.cos(0.25)) < 1e-12 and abs(first.quat[3] - math.sin(0.25)) < 1e-12 and first.quat[1] == first.quat[2] == 0.0
      and len(got) >= 3, first)
web.shutdown()
web.server_close()
web = stand_in((0, 0, 0), truth=False)
live404 = simhost.parse({**NXT, "nxt_web": {**NXT["nxt_web"], "url": f"http://127.0.0.1:{web.server_address[1]}"}}, tmp / "live.json")
try:
    nxt.read_truth(live404)
    code = None
except urllib.error.HTTPError as e:
    code = e.code
check("outside --sim the truth is a 404, never a made-up pose", code == 404, code)
web.shutdown()
web.server_close()

# The reset: a stand-in nxt-web (a script of that name serving the two routes at --start) is started, answered, and found settled.
proj = tmp / "nxt-web"
(proj / ".venv" / "bin").mkdir(parents=True)
exe = proj / ".venv" / "bin" / "nxt-web"
exe.write_text(f"""#!{sys.executable}
import json, math, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
a = sys.argv
port, start = int(a[a.index("--port") + 1]), [float(v) for v in a[a.index("--start") + 1:a.index("--start") + 4]]
mode = open("{tmp}/mode").read().strip()
if mode == "die":
    sys.exit(3)
pose = [start[0], start[1], math.radians(start[2]) + (0.5 if mode == "drift" else 0.0)]
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        body = {{"connected": True}} if self.path == "/api/status" else {{"wall_ns": time.time_ns(), "pose": pose}}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
print(" ".join(a[1:]), flush=True)
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
""")
exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
probe = socket.socket()
probe.bind(("127.0.0.1", 0))
free = probe.getsockname()[1]
probe.close()
rh = simhost.parse({**NXT, "nxt_web": {"url": f"http://127.0.0.1:{free}", "project": str(proj)}}, tmp / "reset.json")
nxt.SETTLE_S = 3.0
(tmp / "mode").write_text("ok")
simhost.reset(rh)
log = (rh.state / "nxt-web.log").read_text()
check("reset starts nxt-web --sim with the host's scene, port and start pose (yaw in degrees), and returns settled at it",
      f"--sim --world {tmp / 'scene.json'}" in log and f"--port {free}" in log and "--start 0.5 -1.0 85.9" in log
      and nxt._at_start(rh) and (rh.state / "nxt-web.pid").exists(), log)
first_pid = int((rh.state / "nxt-web.pid").read_text())
simhost.reset(rh, str(tmp / "other.json"))
second_pid = int((rh.state / "nxt-web.pid").read_text())
check("a second reset stops the first process, starts another, and takes the scene given instead of the host's",
      not nxt.command_of(first_pid) and second_pid != first_pid and f"--world {tmp / 'other.json'}" in (rh.state / "nxt-web.log").read_text())
squatter = stand_in((0, 0, 0))
squat = simhost.parse({**NXT, "state": str(tmp / "squat-state"), "nxt_web": {"url": f"http://127.0.0.1:{squatter.server_address[1]}", "project": str(proj)}}, tmp / "squat.json")
try:
    simhost.reset(squat)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("something already answering at the address that this reset did not start is an error, not a pass", "did not start" in msg, msg)
squatter.shutdown()
squatter.server_close()
simhost.down(rh)
check("down stops it and removes the pid file", not nxt.command_of(second_pid) and not (rh.state / "nxt-web.pid").exists())
(tmp / "mode").write_text("drift")
try:
    simhost.reset(rh)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("a start pose the truth does not read is not settled: the reset raises after its timeout", "did not settle" in msg, msg)
(tmp / "mode").write_text("die")
try:
    simhost.reset(rh)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("an nxt-web that exits on start is an error carrying its log", "exited (3)" in msg, msg)
(proj / ".venv" / "bin" / "nxt-web").unlink()
try:
    simhost.reset(rh)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("no nxt-web installed in the project says which folder to `uv sync`", "uv sync" in msg and str(proj) in msg, msg)
shown = io.StringIO()
with contextlib.redirect_stdout(shown):
    code = cli.main(["--host", str(write(NXT, "nxt.json")), "show"])
check("simhost show prints an nxt host", code == 0 and '"nxt_web"' in shown.getvalue(), shown.getvalue()[:200])

print()
print("FAIL: " + ", ".join(failures) if failures else "all passed")
raise SystemExit(1 if failures else 0)
