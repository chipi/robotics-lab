"""lab-nav-server: the runner in front of Mission Control's navigator API (RFC-0021 step 6, RFC-0022).

    lab-nav-server --data /work/robotics-lab/data --out state/nav      # the host file's sockets, its gate's for the robot

Mission Control talks to this as it talked to the navigator API (the same methods, on the same TCP address), and every
call passes through unchanged to the navigator API (the robot's registered NAVIGATOR_API: duck_lab.nav.server for the
duck), which this starts as its own process with only the robot's sockets and the camera's. What the navigator does not
get stays here:

- **The truth:** the host's body server, sampled while a goal runs (simhost.truth). A host file with `truth_port: null` has none:
  there is no sampler, no camera server, no truth guardrails and no `truth_connections` check, and the official copy is made with
  no tick paired (a real robot's way through the runner).
- **The camera:** served on the host file's camera socket (labrunner.camera), from the truth.
- **The truth guardrails** (`contact`, `fall`, `drop_clearance`, the robot inside a `no_go_area`): checked against the
  truth (labrunner.guard.TruthGuard); a broken one stops the run through the API's `goal.break`, and the run ends
  `stopped_by_guardrail` as one the navigator broke itself. Judged by the profile version read at each `goal.start`,
  the one the navigator reads; a navigator answering another one has its goal cancelled.
- **The clock:** the simulator's time beside the wall clock's, in each truth sample (`truth.jsonl`) and as `clock {sim_s, wall_s,
  rtf}` in the run's `runner.json`. A real-time factor under `--rtf-low` (default simhost.truth.RTF_LOW) after a few seconds is the
  anomaly `rtf_low`, told to the navigator with `goal.anomaly` (contract 1.6), and the run has no verdict (Mission Control reads the
  anomaly). A host with no simulated time (the NXT's) has no clock and no check.
- **The official recording:** each goal run's run is the navigator's (written to `--out`/payload-data) copied into the
  Observatory's data folder with the truth put in (runfile.truthcopy), under the key `goal.start` answered with.

One more method, the runner's own: `runner.status` -> {navigator_pid, truth_connections {checks, max}, goals, last_goal}:
how many TCP connections the navigator's process held to the truth's port, looked at every 2 s while a goal ran."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import simhost
from labrunner import robots
from labrunner.camera import CameraServer
from labrunner.remote import REPO, add_impairment_arg, impairment_in_force, judge_truth, navigator_env, truth_connections
from labrunner.rpc import Rpc
from labrunner.guard import TRUTH, TruthGuard
from runfile import build as runbuild
from runfile import keys, registry, scenefile
from runfile.catalog import default_data
from runfile.navcontract import CALIBRATION_ENDS, ContractError, ENDS, check_hello, check_state, speaks
from runfile.truthcopy import TruthCopy, TruthLog
from simhost.truth import RTF_LOW, Sampler

def no_truth(wall_ns, max_gap_ns):
    return None


def unchecked(has_truth: bool, guardrails: list) -> list:
    """The truth guardrails a goal asked for that no one checks (a host with no truth), each once, in the order asked."""
    return [] if has_truth else list(dict.fromkeys(g["name"] for g in guardrails if g["name"] in TRUTH))


STARTED_S = 60.0         # the navigator API answers within this, or the runner gives up
WATCH_S = 0.2            # how often a goal's run is copied and its state asked
ROUTE_EVERY = 40         # truth samples between two looks at the navigator's connections (2 s at 20 Hz)
READS = ("map", "state", "objects", "inventory", "site_pose")   # what the navigator sees: answered on a connection of their own


class GoalWatch:
    """One goal run: its truth sampled, its truth guardrails checked, its run copied into the official one."""

    def __init__(self, runner: "NavRunner", key: str, guardrails: list, judge, navigator_profile: dict | None = None):
        """`judge`: the profile this goal is judged by (labrunner.robots.read_profile, read at its goal.start), recorded in the
        official run and runner.json beside what the navigator said it runs (`navigator_profile`)."""
        self.runner, self.key = runner, key
        self.judge, self.navigator_profile = judge.meta, navigator_profile
        _, _, name = keys.split_key(key)
        self.dir = runner.out / name
        self.dir.mkdir(parents=True, exist_ok=True)
        # asked for and checked by no one: the goal runs, and says so (here, and in the run's judge_truth)
        self.not_enforced = unchecked(runner.has_truth, guardrails)
        self.judge_truth = judge_truth(runner.host, self.not_enforced)
        self.build = runbuild.of(REPO, runner.host, runner.variant, impairment_in_force(runner.variant, getattr(runner, "depth_impairment", None), judge))
        self.truth_log = TruthLog(self.dir / "truth.jsonl") if runner.has_truth else None
        self.copy = TruthCopy(keys.run_dir(runner.payload_data, key), keys.run_dir(runner.data, key), key,
                              self.truth_log.nearest if self.truth_log else no_truth,
                              run={"judge_profile": self.judge, "judge_scene": runner.judge_scene,
                                   "judge_truth": self.judge_truth, "build": self.build})
        self.guard = TruthGuard(guardrails, profile=judge, scene=runner.scene) if runner.has_truth else None
        self.broken = None
        self.state = None
        self.rtf_low = None           # the clock when its factor first read below the threshold: the run has no verdict
        self._objects_v = -1          # the objects version last seen: asked again, the API leaves them out
        self.route = {"checks": 0, "max": None}
        self._lock = threading.Lock()          # the copy: the pump and the finish
        self._done = threading.Event()
        self.sampler = Sampler(runner.host, on_sample=self._sample) if runner.has_truth else None

    def start(self) -> "GoalWatch":
        if self.sampler:
            self.sampler.start()
        threading.Thread(target=self._watch, name=f"goal-watch-{self.key}", daemon=True).start()
        return self

    def _sample(self, s) -> None:
        self.truth_log.add(s.wall_ns, s.pose, s.z, s.quat, s.sim_time)
        if self.sampler.samples % ROUTE_EVERY == 1:
            n = truth_connections(self.runner.proc.pid, self.runner.host.truth_port)
            if n is not None:
                self.route["checks"] += 1
                self.route["max"] = max(self.route["max"] or 0, n)
        if self.broken is not None or self._done.is_set():
            return
        b = self.guard.check(s.pose, s.z)
        if b:
            self.broken = b
            try:
                self.runner.api("goal.break", {"name": b[0], "detail": b[1]})
            except Exception as e:      # noqa: BLE001 - said where the operator reads the runner, and the next sample tries again
                print(f"lab-nav-server: goal.break {b[0]} failed: {type(e).__name__}: {e}", flush=True)
                self.broken = None

    def _watch(self) -> None:
        while not self._done.wait(WATCH_S):
            self.pump()
            self.check_clock()
            try:
                st = self.runner.api("goal.status", {"decisions_since": 10 ** 9, "objects_since": self._objects_v})
                self._objects_v = st.get("objects_v", -1)
                state = check_state(st.get("state"))
            except ContractError as e:  # a state the contract does not have: the navigator's failure, said
                print(f"lab-nav-server: {self.key}: {e}", flush=True)
                state = "failed"
            except Exception:           # noqa: BLE001 - the navigator API gone: the run ends here with what was copied
                state = "failed"
            if state in ENDS or state == "idle":
                self.state = state
                self.finish()

    def check_clock(self) -> None:
        """The real-time factor against the threshold: the first time it is under, the navigator is told (once, kept in its run)."""
        if self.sampler is None or self.rtf_low is not None or self._done.is_set():
            return
        low = self.sampler.rtf_low(self.runner.rtf_low)
        if low is None:
            return
        self.rtf_low = low
        if not speaks(self.runner.hello, "1.6"):
            return          # a 1.5 navigator cannot record it: runner.json still says so
        try:
            self.runner.api("goal.anomaly", {"kind": "rtf_low", "values": {**low, "below": self.runner.rtf_low},
                            "summary": f"the simulator ran at {low['rtf']:.2f} of real time ({low['sim_s']:.1f} s of simulated time in "
                                       f"{low['wall_s']:.1f} s), under {self.runner.rtf_low}: the run has no verdict"})
        except Exception as e:      # noqa: BLE001 - said, and the run goes on; runner.json carries it
            print(f"lab-nav-server: goal.anomaly rtf_low failed: {type(e).__name__}: {e}", flush=True)

    def pump(self) -> None:
        with self._lock:
            try:
                self.copy.pump()
            except FileNotFoundError:
                pass                    # the navigator has not opened its run yet

    def finish(self) -> None:
        if self._done.is_set():
            return
        self.check_clock()
        self._done.set()
        if self.sampler:
            self.sampler.stop()
        with self._lock:
            try:
                self.copy.finish()
            except (FileNotFoundError, ValueError) as e:
                print(f"lab-nav-server: the run {self.key} could not be copied: {e}", flush=True)
        if self.truth_log:
            self.truth_log.close()
        summary = self.summary()
        (self.dir / "runner.json").write_text(json.dumps(summary, indent=1))
        print(f"lab-nav-server: {self.key} {self.state}: {json.dumps(summary)}", flush=True)

    def summary(self) -> dict:
        return {"key": self.key, "state": self.state, "broken": self.broken, "truth_checked": self.guard.checked if self.guard else [], "not_enforced": self.not_enforced,
                "clock": self.sampler.clock() if self.sampler else None,
                "no_verdict": f"rtf_low: {self.rtf_low['rtf']} under {self.runner.rtf_low}" if self.rtf_low else None,
                "truth_samples": self.sampler.samples if self.sampler else 0, "truth_error": self.sampler.error if self.sampler else None, "truth_copy": self.copy.stats(),
                "truth_connections": dict(self.route), "judge_profile": self.judge, "navigator_profile": self.navigator_profile,
                "judge_scene": self.runner.judge_scene, "judge_truth": self.judge_truth, "build": self.build}


class CalibrationWatch:
    """The truth over one calibration (contract 1.3): sampled from the call that starts it, read at the marks the navigator names when
    it is done. The reference a procedure is judged by: how far the robot went between its first mark and its last, by the host's truth."""

    def __init__(self, host):
        self.log = TruthLog()
        self.sampler = Sampler(host, on_sample=lambda s: self.log.add(s.wall_ns, s.pose, s.z, s.quat)).start()
        self.reference, self.stopped = None, False     # the reference kept once worked out: a second poll of the same end answers the same

    def reference_of(self, marks: list) -> dict | None:
        if self.reference is None:
            a, b = (self.log.nearest(marks[0]["wall_ns"]), self.log.nearest(marks[-1]["wall_ns"])) if len(marks) >= 2 else (None, None)
            if a is None or b is None:
                return None
            self.reference = {"by": "truth", "distance_m": round(math.dist(a["pose"][:2], b["pose"][:2]), 4), "from": a["pose"][:2],
                              "to": b["pose"][:2]}
        return self.reference

    def stop(self) -> None:
        if not self.stopped:
            self.stopped = True
            self.sampler.stop()


class NavRunner:
    def __init__(self, host, data: Path, out: Path, scene: str = "apartment", client: str = "lab-nav-server",
                 robot_socket: Path | None = None, rtf_low: float = RTF_LOW, depth_impairment: int | None = None):
        self.rtf_low = rtf_low                                  # the real-time factor under which a run has no verdict (--rtf-low)
        self.robot_name = robots.get().NAME                     # read once, at start: robots.get() exits on a bad name, a server must not
        api_cmd = robots.navigator_command("NAVIGATOR_API")     # a robot with no navigator (the NXT) is refused here, before anything starts
        profile = robots.profile_source(self.robot_name)        # resolved first: a named version that does not exist refuses here
        self.scene = scenefile.load(scene)                      # the scene's drops, for the truth guard: none, the server does not start
        self.judge_scene = scenefile.describe(self.scene.path)
        self.has_truth = host.truth_port is not None            # the host file's one signal: none, no sampler, no camera, no truth guardrails
        self.variant = robots.variant(host, self.robot_name)    # the navigator's and the referee's: one
        if depth_impairment is not None and self.variant != "sim":
            raise ValueError(f"--depth-impairment is the simulator's: the {self.variant!r} robot's depth frames are not impaired")
        self.depth_impairment = depth_impairment                # every goal's navigator runs with it (its seed), and every run records it
        self.host, self.data, self.out = host, Path(data), Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.payload_data = self.out / "payload-data"           # the navigator's own runs: not the Observatory's data folder
        self.dir = Path(tempfile.mkdtemp(prefix="nr-"))         # short: a unix socket path is limited to ~100 bytes
        self.sock = self.dir / "api.sock"
        self.goal: GoalWatch | None = None
        self.calibration: CalibrationWatch | None = None
        self.goals = 0
        self.route = {"checks": 0, "max": None}
        self.camera = CameraServer(host, host.sockets["camera"]).start() if self.has_truth else None
        robot = self.robot_socket = robot_socket or robots.gate_socket(host)     # the installation's gate, where Mission Control's is
        cmd = api_cmd + ["--robot", str(robot), "--depth", str(host.sockets["depth"]),
               "--map", str(host.sockets["map"]), "--listen", str(self.sock),
               "--client", client, "--data", str(self.payload_data), "--out", str(self.out), "--scene", scene,
               "--variant", self.variant] + \
            (["--camera", str(self.camera.path)] if self.camera else []) + \
            ["--profile", str(profile)] + (["--depth-impairment", str(depth_impairment)] if depth_impairment is not None else [])
        env = navigator_env()                                   # nothing of the host but its sockets, nothing of the installation
        self.log = open(self.out / "navigator.log", "a")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        self._rpc_lock = threading.Lock()
        self.rpc = None
        try:
            self._connect()
            self.hello = check_hello(self.api("hello"))    # another major version of the contract: refused before it serves
        except BaseException:
            self.close()
            raise

    def _connect(self) -> None:
        end = time.monotonic() + STARTED_S
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"the navigator API ended before it answered (exit {self.proc.returncode}): "
                                   f"see {self.out / 'navigator.log'}")
            try:
                self.rpc = Rpc(self.sock, timeout=300.0)
                return
            except OSError:
                if time.monotonic() > end:
                    raise RuntimeError(f"the navigator API did not answer on {self.sock} within {STARTED_S:.0f} s") from None
                time.sleep(0.2)

    def api(self, method: str, params: dict | None = None) -> dict:
        if self.proc.poll() is not None:
            raise RuntimeError(f"the navigator API died (exit {self.proc.returncode}): see {self.out / 'navigator.log'}")
        return self.rpc.call(method, params)

    def read(self, method: str, params: dict | None = None) -> dict:
        """A read (the map, what the navigator sees) on a connection of its own: the navigator API serves each connection on its
        own thread, so a slow read (mapd restarting) never holds a goal.start or a cancel queued behind it."""
        if self.proc.poll() is not None:
            raise RuntimeError(f"the navigator API died (exit {self.proc.returncode}): see {self.out / 'navigator.log'}")
        rpc = Rpc(self.sock, timeout=30.0)
        try:
            return rpc.call(method, params)
        finally:
            rpc.close()

    def call(self, method: str, p: dict):
        if method == "runner.status":
            last = self.goal.summary() if self.goal else None
            return {"navigator_pid": self.proc.pid, "truth_connections": dict(self.route), "goals": self.goals, "last_goal": last}
        if method in READS:
            return self.read(method, p)
        if method == "goal.status" and self.goal is not None:
            self.goal.check_clock()         # before the answer: a client that reads the run's end has read its rtf_low too
        if method.startswith("calibration."):
            return self._calibrate(method, p)
        if method != "goal.start":
            return self.api(method, p)
        if self.goal is not None:
            self.goal.finish()          # (the navigator API refuses a second goal while one runs: this one is over)
            self._merge(self.goal.route)
        # the referee reads the profile again at each goal, from the one source the navigator reads it from (the installation's
        # version, or the robot's own): a version chosen since applies to both from this goal (the operator's decision e)
        judge = robots.read_profile(registry.profile_file(self.robot_name), self.variant)   # errors are the caller's answer, never an exit
        asked = unchecked(self.has_truth, (p.get("conditions") or {}).get("guardrails") or [])
        # told to the navigator (contract 1.2), which raises one anomaly each; a 1.1 navigator ignores the field and raises none
        reply = self.api("goal.start", {**p, "not_enforced": asked} if asked else p)
        if isinstance(reply, dict) and reply.get("run_key"):
            guardrails = (p.get("conditions") or {}).get("guardrails") or []
            theirs = reply.get("profile")
            self.goal = GoalWatch(self, reply["run_key"], guardrails, judge, theirs).start()
            self.goals += 1
            if theirs and theirs.get("checksum") and theirs["checksum"] != judge.meta["checksum"]:
                # a version chosen between the two reads: never judged by other numbers than it runs; the run is cancelled
                self.api("goal.cancel")
                raise RuntimeError(f"the navigator started {reply['run_key']} on profile {theirs['checksum'][:15]}… (version "
                                   f"{theirs.get('version')}), the runner read {judge.meta['checksum'][:15]}… (version "
                                   f"{judge.meta['version']}): the profile changed while the goal started; it is cancelled, "
                                   f"start it again")
        return reply

    def _calibrate(self, method: str, p: dict) -> dict:
        """The navigator's calibration methods, with the truth put in (contract 1.3): `calibration.status` of a procedure that is done
        adds `reference`, the distance the host's truth says the robot went between its marks, or null when this host has no truth (a real
        robot's: the operator's tape is the reference then). The navigator never sees it."""
        reply = self.api(method, p)
        if method == "calibration.start" and isinstance(reply, dict) and reply.get("ok"):
            self._calibration_stop()
            if self.has_truth:
                self.calibration = CalibrationWatch(self.host)
        elif method == "calibration.status" and isinstance(reply, dict) and reply.get("state") in CALIBRATION_ENDS:
            if reply["state"] == "done":
                reply = {**reply, "reference": self.calibration.reference_of(reply.get("marks") or []) if self.calibration else None}
            self._calibration_stop()
        return reply

    def _calibration_stop(self) -> None:
        if self.calibration is not None:
            self.calibration.stop()

    def _merge(self, route: dict) -> None:
        self.route["checks"] += route["checks"]
        if route["max"] is not None:
            self.route["max"] = max(self.route["max"] or 0, route["max"])

    def close(self) -> None:
        self._calibration_stop()
        if self.goal is not None and not self.goal._done.is_set():
            # a goal still running: cancelled, so the navigator stops the robot and gives the lease back before it ends
            try:
                self.api("goal.cancel")
                end = time.monotonic() + 15.0
                while time.monotonic() < end and not self.goal._done.wait(0.2):
                    pass
            except Exception:           # noqa: BLE001 - the navigator API already gone: the gate stops the robot
                pass
        if self.goal is not None:
            self.goal.finish()
            self._merge(self.goal.route)
        if self.rpc is not None:
            self.rpc.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        if self.camera:
            self.camera.stop()
        self.log.close()
        self.sock.unlink(missing_ok=True)
        try:
            self.dir.rmdir()
        except OSError:
            pass


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            try:
                req = json.loads(line)
                reply = {"jsonrpc": "2.0", "id": req.get("id"), "result": self.server.runner.call(req["method"], req.get("params") or {})}
            except Exception as exc:                                # noqa: BLE001 - every error is the caller's answer
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
            try:
                self.wfile.write((json.dumps(reply) + "\n").encode())
                self.wfile.flush()
            except OSError:
                return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, runner: NavRunner):
        super().__init__(addr, Handler)
        self.runner = runner


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--listen", default="127.0.0.1:8061", help="host:port (loopback by default: the API has no login)")
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    ap.add_argument("--robot-socket", type=Path, help="the robot's socket: a gate's (default: the installation's robots.<robot>.gate, where Mission Control reads it, "
                    "else the host file's gate socket)")
    ap.add_argument("--rtf-low", type=float, default=RTF_LOW, help="the real-time factor under which a run has no verdict (the anomaly rtf_low); "
                    "a test raises it to prove the check on a simulator that is not slow")
    ap.add_argument("--client", default="lab-nav-server", help="the name the navigator takes the lease under")
    ap.add_argument("--data", type=Path, default=default_data(),
                    help="the Observatory's data folder: each goal run is written there as a run (env OBSERVATORY_DATA)")
    ap.add_argument("--out", type=Path, default=Path("state/nav"), help="the navigator's own output folders, one per goal run")
    ap.add_argument("--scene", default="apartment", help="the Observatory scene of the runs")
    add_impairment_arg(ap)
    ap.add_argument("--robot", help="the robot, by its registered name (default: the only one registered)")
    args = ap.parse_args()
    robots.select(args.robot)
    if args.data is None:
        sys.exit("lab-nav-server: --data (or OBSERVATORY_DATA): where the runs are written")
    host = simhost.load(args.host)
    runner = NavRunner(host, args.data, args.out, args.scene, args.client, args.robot_socket, args.rtf_low, args.depth_impairment)
    listen, _, port = args.listen.rpartition(":")
    srv = Server((listen or "127.0.0.1", int(port)), runner)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # a terminate stops the navigator API too (runner.close)
    print(f"lab-nav-server: {args.listen}, the navigator API pid {runner.proc.pid}, robot "
          f"{runner.robot_socket}, camera {runner.camera.path if runner.camera else 'none (no truth)'}, runs in {args.data}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.close()


if __name__ == "__main__":
    main()
