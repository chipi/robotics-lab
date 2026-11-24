"""The measurement tooling (phase 5 item 4b unit B9): the pure parts of the four scripts, and each script's refusals and its read-only or
gated behaviour against stand-ins. CPU cost: /proc's lines, the windows, a real read of this process. Range model: a synthetic flat wall,
radial and axial, is recovered and told apart; a bent wall is "inconclusive"; the depth socket is only asked tof.stream. Score sheet: legs,
gains, a fix is not a step, an arm with no truth prints '-'. Walk: the speed cap, the refusal of a robot that is not the simulator before
any connection, the gain and the tape's scale, the stop at the end, and a whole run through a stand-in gate (hello, who, acquire, move,
release). No simulator, no robot.
Run: cd libs/runner && uv run python tests/test_measure.py"""

import contextlib
import io
import json
import math
import os
import random
import socket
import tempfile
import threading
import time
from pathlib import Path

import simhost
from robotgate import PROTOCOL

from labrunner import measure_cpu, measure_range, measure_score, measure_walk

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


# ---- CPU cost ----
line = "4242 (tmux: server (x)) S 1 4242 4242 0 -1 4194560 100 0 0 0 150 50 0 0 20 0 7 0 99 1000 300 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 2 0 0 0 0 0"
ticks, threads, pages = measure_cpu.parse_proc_stat(line)
check("a /proc stat line whose name holds spaces and brackets reads utime + stime, threads and resident pages",
      (ticks, threads, pages) == (200, 7, 300), (ticks, threads, pages))
busy, total = measure_cpu.parse_cpu_line("cpu  100 0 50 800 40 5 5 0 0 0")
check("the machine's busy time leaves out idle and iowait", (busy, total) == (160, 1000), (busy, total))

samples = [{"t": float(i), "busy": 50 * i, "total": 400 * i, "procs": {"mapd": (50 * i, 5, 2560), "ghost": None}, "temp_c": 50.0 + i}
           for i in range(1, 6)]
res = measure_cpu.summarise(samples, 100, 4096, 4)
check("half a core of ticks per second is 50 % of one core, and its resident size is pages x page size",
      res["processes"]["mapd"]["cpu_pct_mean"] == 50.0 and res["processes"]["mapd"]["rss_mb_max"] == 10.0, res["processes"]["mapd"])
check("a process that is never there is None, not a zero cost", res["processes"]["ghost"] is None)
check("the machine's busy share is of all cores and its hottest zone is kept",
      res["machine"]["busy_pct_mean"] == 12.5 and res["machine"]["temp_c_max"] == 55.0, res["machine"])

proc = Path(tempfile.mkdtemp(prefix="labcpu-"))
for pid, comm in ((10, "mapd"), (20, "robotd"), (30, "mapd")):
    (proc / str(pid)).mkdir()
    (proc / str(pid) / "comm").write_text(comm + "\n")
(proc / "self").mkdir()
check("pids by comm name: the lowest pid of each, others ignored", measure_cpu.pids_by_name(("mapd", "tofd"), proc) == {"mapd": 10})

end = time.monotonic() + 1.3
t = threading.Thread(target=lambda: [None for _ in iter(lambda: time.monotonic() < end, False)], daemon=True)
t.start()
live = measure_cpu.measure(("self",), 1.2, 0.3, "test", pids={"self": os.getpid()})
t.join()
check("a real read of this process under a busy thread shows CPU and a resident size",
      live["processes"]["self"]["cpu_pct_mean"] > 20 and live["processes"]["self"]["rss_mb_max"] > 5, live["processes"]["self"])
check("the table names every process and says when one is missing",
      "not running" in measure_cpu.table({**live, "processes": {**live["processes"], "tofd": None}}))

# ---- range model ----
bs = measure_range.beams()
half = math.radians(45 / 2 - 45 / 8 / 2)
check("64 unit beams; the top-left zone looks up and to the left by half the 8x8's outermost step",
      len(bs) == 64 and all(abs(math.hypot(*b) - 1) < 1e-9 for b in bs)
      and abs(bs[0][2] - math.sin(half)) < 1e-9 and abs(bs[0][1] - math.cos(half) * math.sin(half)) < 1e-9, bs[0])
rng = random.Random(7)


def frames_of(kind, d, pitch, yaw, noise=2.0, n=20, bump=None):
    base = measure_range.wall_ranges(kind, d, pitch, yaw, bs)
    if bump:
        base = [v + (bump if i % 8 >= 4 else 0) for i, v in enumerate(base)]
    return [{"distance_mm": [round(v + rng.gauss(0, noise)) for v in base], "status": [5] * 64} for _ in range(n)]


for kind in ("radial", "axial"):
    for d, pitch, yaw in ((0.25, 2.5, 4.0), (0.5, 3.0, 0.0), (0.75, 5.0, -3.0)):
        r = measure_range.analyse(frames_of(kind, d, pitch, yaw), tape_m=d)
        check(f"a {kind} wall at {d} m, pitch {pitch}, yaw {yaw} is told {kind}, and its distance and pitch are recovered",
              r["verdict"] == kind and abs(r[kind]["d_m"] - d) < 0.005 and abs(r[kind]["pitch_deg"] - pitch) < 0.3
              and abs(r[kind]["d_minus_tape_mm"]) < 5, (r["verdict"], r[kind]))
bent = measure_range.analyse(frames_of("radial", 0.5, 3.0, 0.0, bump=120))
check("must fail: a wall with half of it 12 cm farther (a step, not a plane) is inconclusive, and says so",
      bent["verdict"] == "inconclusive" and "flat" in bent["why"], (bent["verdict"], bent["why"]))
part = measure_range.analyse(frames_of("radial", 0.5, 3.0, 0.0), rows=(0, 1), cols=(0, 3))
check("a window of 8 zones is too few to part the models: inconclusive", part["verdict"] == "inconclusive" and part["zones_used"] == 8, part["why"])
holes = frames_of("radial", 0.5, 3.0, 0.0)
for f in holes:
    f["status"][:20] = [255] * 20
check("zones with no valid return are left out of the fit", measure_range.analyse(holes)["zones_used"] == 44)
check("rows and columns are read as spans", measure_range._span("2-5") == (2, 5) and measure_range._span("3") == (3, 3))
out = measure_range.table(measure_range.analyse(frames_of("axial", 0.5, 3.0, 0.0)), frames_of("axial", 0.5, 3.0, 0.0))
check("the table has the verdict and the two residual maps", "verdict: axial" in out and "residual per zone" in out)


class DepthPeer:
    """A depth socket: answers tof.stream with frames, and records every method it was asked (the script must ask only that)."""

    def __init__(self, path, frames):
        self.asked, self.frames = [], frames
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(2)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            c, _ = self.server.accept()
        except OSError:
            return
        f = c.makefile("rw")
        try:
            for line in f:
                req = json.loads(line)
                self.asked.append(req["method"])
                f.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}) + "\n")
                for fr in self.frames:
                    f.write(json.dumps({"jsonrpc": "2.0", "method": "tof.frame", "params": fr}) + "\n")
                f.flush()
        except (OSError, ValueError):
            pass


tmp = Path(tempfile.mkdtemp(prefix="labmeasure-"))
src = frames_of("radial", 0.5, 3.0, 0.0, n=12)
peer = DepthPeer(tmp / "tof.sock", src)
got = measure_range.read_frames(tmp / "tof.sock", 12)
check("read_frames takes the frames of a tof.stream and asks nothing else (read-only)", len(got) == 12 and peer.asked == ["tof.stream"], peer.asked)
saved = tmp / "frames.json"
saved.write_text(json.dumps({"frames": src}))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    code = measure_range.main(["--frames-file", str(saved), "--json", "--tape-m", "0.5"])
check("main from a saved frame set prints JSON with the verdict and exits 0", code == 0 and json.loads(buf.getvalue())["verdict"] == "radial", buf.getvalue()[:200])

# ---- score sheet ----
def tick(t, cmd, x, truth_x=None, jump=0.0):
    p = {"belief": [x, 0.0, 0.0], "cmd": list(cmd), "tilt": [1.0, -2.0]}
    if truth_x is not None:
        p["truth"] = [truth_x, 0.0, 0.0]
    return t, p


# 5 s of 0.3 m/s asked, walked at 0.15 (belief) and 0.12 (truth), ticks every 0.1 s; a 1 m fix in the middle is not a step
walk_ticks = [tick(i / 10, (0.3, 0.0), 0.15 * i / 10 + (1.0 if i >= 30 else 0.0), 0.12 * i / 10) for i in range(51)]
lg = measure_score.legs(walk_ticks)
check("a straight leg: asked 0.3, belief 0.15 m/s, truth 0.12 m/s; the fix's jump is not a step and its first second is the ramp",
      len(lg) == 1 and lg[0][0] == 0.3 and abs(lg[0][1] - 0.15) < 0.01 and abs(lg[0][2] - 0.12) < 0.01, lg)
check("a turning stretch is not a speed", measure_score.legs([tick(i / 10, (0.3, 0.8), 0.1 * i) for i in range(40)]) == [])
check("a leg of under a second after the ramp is not a speed", measure_score.legs([tick(i / 10, (0.3, 0.0), 0.1 * i) for i in range(15)]) == [])
cut = [tick(i / 10, (0.3 if i < 30 else 0.2, 0.0), 0.1 * i) for i in range(60)]
check("a change of the asked speed cuts a leg in two, each its own speed", sorted(x[0] for x in measure_score.legs(cut)) == [0.2, 0.3],
      measure_score.legs(cut))
# phase 5 item 4e unit E10: the pose sways about 2 cm across the walk at 10 Hz, and summed steps count every sway as walking (a belief
# walked at 0.15 m/s read as 0.2): a speed is the stretch's net displacement over its time
sway = [(i / 10, {"belief": [0.15 * i / 10, 0.02 * (i % 2), 0.0], "truth": [0.12 * i / 10, 0.02 * (i % 2), 0.0], "cmd": [0.3, 0.0]}) for i in range(51)]
lg = measure_score.legs(sway)
check("a sway across the walk is not walking: the speed is the net displacement (belief 0.15, truth 0.12), not the summed steps",
      len(lg) == 1 and abs(lg[0][1] - 0.15) < 0.01 and abs(lg[0][2] - 0.12) < 0.01, lg)
no_truth = measure_score.legs([tick(i / 10, (0.3, 0.0), 0.15 * i / 10) for i in range(51)])
check("without a truth the leg's truth speed is None", no_truth[0][2] is None, no_truth)

records = [(0.0, "run", {})] + [(t, "tick", p) for t, p in walk_ticks] + [(0.0, "segment", {"t_start": 0.0, "t_end": 5.0, "outcome": "reached"}),
                                                                            (1.0, "event", {"kind": "stuck"})]
one = measure_score.summarise_run(records)
sim = measure_score.arm_stats([one, one])
real = measure_score.arm_stats([{**one, "legs": [(0.3, 0.12, None)]}])
check("an arm's score: reached share, the gain by belief and by truth, the trouble per run",
      sim["reached_share"] == 1.0 and abs(sim["gain"]["0.30"]["belief_p50"] - 0.5) < 0.05 and abs(sim["gain"]["0.30"]["truth_p50"] - 0.4) < 0.05
      and sim["trouble_per_run"] == {"stuck": 1.0} and sim["tilt_deg_max"] == 2.0, sim)
check("an arm with no truth has no truth gain", real["gain"]["0.30"]["truth_p50"] is None)
sheet = measure_score.table(sim, real)
check("the sheet puts the speed gain first, with '-' where the real arm has nothing, and the ratio where both have",
      sheet.splitlines()[1].startswith("speed gain at 0.30 m/s, by belief") and "0.40" in sheet.splitlines()[1] and
      sheet.splitlines()[2].split()[-1] == "-", sheet)
check("a sheet of one arm prints without the other", "-" in measure_score.table(sim, None) and "real/sim" in measure_score.table(None, real))
run_a = tmp / "runs" / "x" / "run-1"
run_a.mkdir(parents=True)
(run_a / "run.mcap").write_bytes(b"")
check("run folders are found by their run.mcap, and a run folder given itself is one", measure_score.run_dirs([tmp / "runs"]) == [run_a]
      and measure_score.run_dirs([run_a]) == [run_a])
said = []
check("an unreadable recording is said and left out, not a stop", measure_score.load_arm([tmp / "runs"], warn=said.append) == [] and said, said)

# ---- walk: refusals, the numbers, the stop ----
for bad in ("0.5", "0", "-0.1", "abc,0.3"):
    try:
        measure_walk.parse_speeds(bad)
        refused = False
    except (measure_walk.Refused, ValueError):
        refused = True
    check(f"must fail: --speeds {bad} is refused", refused)
check("speeds parse", measure_walk.parse_speeds("0.2, 0.3") == [0.2, 0.3])

sim_host = type("H", (), {"truth_port": 7801, "sockets": {"gate": Path("/g/sim-gate.sock"), "robot": Path("/g/sim.sock")}})()
check("the simulator is a host with a truth whose sockets name this gate",
      measure_walk.is_simulator(Path("/g/sim-gate.sock"), sim_host) and not measure_walk.is_simulator(Path("/g/other.sock"), sim_host))
check("no host file: nothing is the simulator", not measure_walk.is_simulator(Path("/g/sim-gate.sock"), None))
check("a host with no truth is not a simulator", not measure_walk.is_simulator(Path("/g/sim-gate.sock"), type("H", (), {"truth_port": None, "sockets": {"gate": Path("/g/sim-gate.sock")}})()))


class FakeRobot:
    """Walks at `gain` of the asked speed and keeps a clock; the odometry reads `scale` of what was walked."""

    def __init__(self, gain=0.5, scale=0.9):
        self.gain, self.scale, self.vx, self.t, self.x, self.moves, self.fail_at = gain, scale, 0.0, 0.0, 0.0, [], None

    def move(self, vx):
        if self.fail_at is not None and len(self.moves) >= self.fail_at:
            raise measure_walk.LeaseLost("lease ended", "lease_ended", "stopped_by someone")
        self.moves.append(vx)
        self.vx = vx

    def sleep(self, dt):
        self.t += dt
        self.x += self.vx * self.gain * dt

    def sample(self):
        return {"odom": [self.x * self.scale, 0.0], "odom_t": self.t, "truth": [self.x, 0.0], "truth_t": self.t}


fake = FakeRobot()
legs = measure_walk.walk(fake.move, fake.sample, fake.sleep, [0.2, 0.3], 4.0, 1.5, tell=lambda m: None)
check("a leg's gain is the odometry's speed over the asked speed (0.5 walked at 0.9 scale: 0.45), and truth's 0.5",
      len(legs) == 2 and abs(legs[1]["odom_gain"] - 0.45) < 0.01 and abs(legs[1]["truth_gain"] - 0.5) < 0.01, legs[1])
check("the leg's truth over its odometry distance is the odometry scale (1/0.9)", abs(legs[1]["odom_scale_by_truth"] - 1 / 0.9) < 0.01, legs[1])
check("the last command is a zero move, and the robot walked only the asked speeds", fake.moves[-1] == 0.0 and set(fake.moves) == {0.0, 0.2, 0.3})
answers = iter(["", "0.40"])
asked_prompts = []
fake = FakeRobot()
legs = measure_walk.walk(fake.move, fake.sample, fake.sleep, [0.3], 4.0, 1.5, ask=lambda p: (asked_prompts.append(p), next(answers))[1], tell=lambda m: None)
check("--interactive waits before the leg, asks the tape after it, and the scale is tape over believed distance",
      len(asked_prompts) == 2 and "start mark" in asked_prompts[0] and legs[0]["tape_leg_m"] == 0.4
      and abs(legs[0]["odom_scale_by_tape"] - legs[0]["tape_leg_m"] / legs[0]["odom_leg_m"]) < 0.01, legs[0])
class WalledRobot(FakeRobot):
    """Stops where a wall is: the simulator's default scene has one 0.55 m ahead of the duck's start, which is B9's 0.108 m/s (E10)."""

    def __init__(self, wall_m=None):
        super().__init__()
        self.wall_m = wall_m

    def sleep(self, dt):
        super().sleep(dt)
        if self.wall_m is not None:
            self.x = min(self.x, self.wall_m)


def walk_in(robot):
    return measure_walk.walk(robot.move, robot.sample, robot.sleep, [0.3], 4.0, 1.5, tell=lambda m: None)


free, walled = walk_in(WalledRobot()), walk_in(WalledRobot(0.35))
check("a leg that kept its speed to the end is not marked blocked", not free[0].get("blocked"), free[0])
check("a leg that slowed to a stop before the end (a wall) is marked blocked: its speed is not the walk's", walled[0].get("blocked") is True, walled[0])
table_of = lambda legs: measure_walk.table({"variant": "simulator", "seconds": 4.0, "ramp_s": 1.5, "legs": legs})    # noqa: E731
check("the table says so under the blocked leg, and not under a free one", "blocked" in table_of(walled) and "blocked" not in table_of(free), table_of(walled))
fake = FakeRobot()
fake.fail_at = 30
try:
    measure_walk.walk(fake.move, fake.sample, fake.sleep, [0.3], 4.0, 1.5, tell=lambda m: None)
    lost = False
except measure_walk.LeaseLost:
    lost = True
check("a lost lease ends the walk with the lease error, after one more try at a zero move", lost)
fake = FakeRobot()
calls = []


def boom(vx):
    calls.append(vx)
    if len(calls) == 15:
        raise KeyboardInterrupt
    fake.move(vx)


try:
    measure_walk.walk(boom, fake.sample, fake.sleep, [0.3], 4.0, 1.5, tell=lambda m: None)
except KeyboardInterrupt:
    pass
check("Ctrl-C mid-leg still sends the stop", calls[-1] == 0.0 and len(calls) == 16, calls[-3:])


class FakeGate:
    """A stand-in gate on a Unix socket: hello, gate.who, gate.acquire, robot.move, robot.subscribe (streams odometry integrated from
    the moves), gate.release. Records each connection's methods; `holder` makes the robot look held."""

    def __init__(self, path, holder=None):
        self.path, self.holder, self.log, self.connections = path, holder, [], 0
        self.vx, self.x, self.t = 0.0, 0.0, 0.0
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        f = c.makefile("rw")
        lock = threading.Lock()

        def send(msg):
            with lock:
                f.write(json.dumps(msg) + "\n")
                f.flush()

        def stream():
            while True:
                self.t += 0.05
                self.x += self.vx * 0.4 * 0.05
                try:
                    send({"jsonrpc": "2.0", "method": "robot.state", "params": {"t_ns": int(self.t * 1e9), "odom": {"position": [self.x, 0.0, 0.2]}}})
                except (OSError, ValueError):
                    return
                time.sleep(0.05)

        try:
            for line in f:
                req = json.loads(line)
                m = req["method"]
                self.log.append(m)
                result = {"protocol": PROTOCOL}
                if m == "gate.who":
                    result["holder"] = self.holder
                if m == "robot.move":
                    self.vx = req["params"]["vx"]
                if m == "robot.subscribe":
                    threading.Thread(target=stream, daemon=True).start()
                send({"jsonrpc": "2.0", "id": req["id"], "result": result})
        except (OSError, ValueError):
            pass


def run_main(argv, host=None):
    real_load = simhost.load
    simhost.load = (lambda *a, **k: host) if host is not None else (lambda *a, **k: (_ for _ in ()).throw(simhost.HostError("no host file")))
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                return measure_walk.main(argv), out.getvalue(), err.getvalue()
            except SystemExit as exc:
                return exc.code, out.getvalue(), err.getvalue()
    finally:
        simhost.load = real_load


gate = FakeGate(tmp / "duck-gate.sock")
code, out, err = run_main(["--gate", str(tmp / "duck-gate.sock"), "--speeds", "0.3"])
check("must fail: a gate the host file does not name is refused without --real, and no connection was made (the robot was never spoken to)",
      isinstance(code, str) and "--real" in code and gate.connections == 0 and gate.log == [], (code, gate.connections, gate.log))
code, out, err = run_main(["--gate", str(tmp / "duck-gate.sock"), "--speeds", "0.9", "--real"])
check("must fail: 0.9 m/s is refused even with --real, before any connection", isinstance(code, str) and "0.4" in code and gate.connections == 0, code)
held = FakeGate(tmp / "held.sock", holder="operator-laptop")
code, out, err = run_main(["--gate", str(tmp / "held.sock"), "--speeds", "0.3", "--real"])
check("must fail: a robot someone else holds is not taken: it never acquires and never moves",
      isinstance(code, str) and "operator-laptop" in code and "gate.acquire" not in held.log and "robot.move" not in held.log, (code, held.log))
measure_walk.SETTLE_S = measure_walk.STOP_S = 0.2
code, out, err = run_main(["--gate", str(tmp / "duck-gate.sock"), "--real", "--speeds", "0.3", "--seconds", "0.6", "--ramp-s", "0.3", "--json"])
res = json.loads(out) if code == 0 else {}
log = gate.log
check("--real walks through the gate: hello, who, subscribe, acquire, moves, release in that order, the last move a zero",
      code == 0 and log.index("gate.who") < log.index("gate.acquire") < log.index("robot.move") and log[-1] == "gate.release"
      and gate.vx == 0.0 and res["variant"] == "real", (code, err[-200:], log[:6], log[-3:]))
check("the leg's gain is the stand-in's 0.4 of the asked speed, the real variant has no truth column",
      abs(res["legs"][0]["odom_gain"] - 0.4) < 0.1 and "truth_gain" not in res["legs"][0], res.get("legs"))
gate2 = FakeGate(tmp / "sim-gate.sock")
sim_like = type("H", (), {"truth_port": None, "sockets": {"gate": tmp / "sim-gate.sock"}})()
code, out, err = run_main(["--gate", str(tmp / "sim-gate.sock"), "--speeds", "0.3"], host=sim_like)
check("must fail: a host with no truth is not the simulator, so its own gate is refused without --real", isinstance(code, str) and "--real" in code, code)

print()
if failures:
    print(f"FAIL: {len(failures)} check(s): " + "; ".join(failures))
    raise SystemExit(1)
print("PASS: every measurement check passed")
