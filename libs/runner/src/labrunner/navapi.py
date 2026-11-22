"""lab-nav-server: the runner in front of Mission Control's navigator API (RFC-0021 step 6, RFC-0022).

    lab-nav-server --data /work/robotics-lab/data --out state/nav      # the host file's sockets, its gate's for the robot

Mission Control talks to this as it talked to the navigator API (the same methods, on the same TCP address), and every
call passes through unchanged to the navigator API (the robot's registered NAVIGATOR_API: duck_lab.nav.server for the
duck), which this starts as its own process with only the robot's sockets and the camera's. What the navigator does not
get stays here:

- **The truth:** the host's body server, sampled while a goal runs (simhost.truth).
- **The camera:** served on the host file's camera socket (labrunner.camera), from the truth.
- **The truth guardrails** (`contact`, `fall`, `drop_clearance`, the robot inside a `no_go_area`): checked against the
  truth (labrunner.guard.TruthGuard); a broken one stops the run through the API's `goal.break`, and the run ends
  `stopped_by_guardrail` as one the navigator broke itself. Judged by the profile version read at each `goal.start`,
  the one the navigator reads; a navigator answering another one has its goal cancelled.
- **The official recording:** each goal run's run is the navigator's (written to `--out`/payload-data) copied into the
  Observatory's data folder with the truth put in (runfile.truthcopy), under the key `goal.start` answered with.

One more method, the runner's own: `runner.status` -> {navigator_pid, truth_connections {checks, max}, goals, last_goal}:
how many TCP connections the navigator's process held to the truth's port, looked at every 2 s while a goal ran."""

from __future__ import annotations

import argparse
import json
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
from labrunner.remote import navigator_env, truth_connections
from labrunner.rpc import Rpc
from labrunner.guard import TruthGuard
from runfile import keys, registry, scenefile
from runfile.catalog import default_data
from runfile.navcontract import ContractError, ENDS, check_hello, check_state
from runfile.truthcopy import TruthCopy, TruthLog
from simhost.truth import Sampler

STARTED_S = 60.0         # the navigator API answers within this, or the runner gives up
WATCH_S = 0.2            # how often a goal's run is copied and its state asked
ROUTE_EVERY = 40         # truth samples between two looks at the navigator's connections (2 s at 20 Hz)
READS = ("map", "state", "objects", "inventory")   # what the navigator sees: answered on a connection of their own


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
        self.truth_log = TruthLog(self.dir / "truth.jsonl")
        self.copy = TruthCopy(keys.run_dir(runner.payload_data, key), keys.run_dir(runner.data, key), key, self.truth_log.nearest,
                              run={"judge_profile": self.judge, "judge_scene": runner.judge_scene})
        self.guard = TruthGuard(guardrails, profile=judge, scene=runner.scene)
        self.broken = None
        self.state = None
        self._objects_v = -1          # the objects version last seen: asked again, the API leaves them out
        self.route = {"checks": 0, "max": None}
        self._lock = threading.Lock()          # the copy: the pump and the finish
        self._done = threading.Event()
        self.sampler = Sampler(runner.host, on_sample=self._sample)

    def start(self) -> "GoalWatch":
        self.sampler.start()
        threading.Thread(target=self._watch, name=f"goal-watch-{self.key}", daemon=True).start()
        return self

    def _sample(self, s) -> None:
        self.truth_log.add(s.wall_ns, s.pose, s.z, s.quat)
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

    def pump(self) -> None:
        with self._lock:
            try:
                self.copy.pump()
            except FileNotFoundError:
                pass                    # the navigator has not opened its run yet

    def finish(self) -> None:
        if self._done.is_set():
            return
        self._done.set()
        self.sampler.stop()
        with self._lock:
            try:
                self.copy.finish()
            except (FileNotFoundError, ValueError) as e:
                print(f"lab-nav-server: the run {self.key} could not be copied: {e}", flush=True)
        self.truth_log.close()
        summary = self.summary()
        (self.dir / "runner.json").write_text(json.dumps(summary, indent=1))
        print(f"lab-nav-server: {self.key} {self.state}: {json.dumps(summary)}", flush=True)

    def summary(self) -> dict:
        return {"key": self.key, "state": self.state, "broken": self.broken, "truth_checked": self.guard.checked,
                "truth_samples": self.sampler.samples, "truth_error": self.sampler.error, "truth_copy": self.copy.stats(),
                "truth_connections": dict(self.route), "judge_profile": self.judge, "navigator_profile": self.navigator_profile,
                "judge_scene": self.runner.judge_scene}


class NavRunner:
    def __init__(self, host, data: Path, out: Path, scene: str = "apartment", client: str = "lab-nav-server",
                 robot_socket: Path | None = None):
        self.robot_name = robots.get().NAME                     # read once, at start: robots.get() exits on a bad name, a server must not
        profile = robots.profile_source(self.robot_name)        # resolved first: a named version that does not exist refuses here
        self.scene = scenefile.load(scene)                      # the scene's drops, for the truth guard: none, the server does not start
        self.judge_scene = scenefile.describe(self.scene.path)
        if host.truth_port is None:
            raise ValueError(f"{host.source}: this host has no truth (truth_port is null): Mission Control talks to the "
                             f"navigator API itself there (the robot's NAVIGATOR_API)")
        self.host, self.data, self.out = host, Path(data), Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.payload_data = self.out / "payload-data"           # the navigator's own runs: not the Observatory's data folder
        self.dir = Path(tempfile.mkdtemp(prefix="nr-"))         # short: a unix socket path is limited to ~100 bytes
        self.sock = self.dir / "api.sock"
        self.goal: GoalWatch | None = None
        self.goals = 0
        self.route = {"checks": 0, "max": None}
        self.camera = CameraServer(host, host.sockets["camera"]).start()
        robot = self.robot_socket = robot_socket or robots.gate_socket(host)     # the installation's gate, where Mission Control's is
        cmd = list(robots.get().NAVIGATOR_API) + ["--robot", str(robot), "--depth", str(host.sockets["depth"]),
               "--map", str(host.sockets["map"]), "--camera", str(self.camera.path), "--listen", str(self.sock),
               "--client", client, "--data", str(self.payload_data), "--out", str(self.out), "--scene", scene] + \
            (["--profile", str(profile)] if profile else [])
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
        if method != "goal.start":
            return self.api(method, p)
        if self.goal is not None:
            self.goal.finish()          # (the navigator API refuses a second goal while one runs: this one is over)
            self._merge(self.goal.route)
        # the referee reads the profile again at each goal, from the one source the navigator reads it from (the installation's
        # version, or the robot's own): a version chosen since applies to both from this goal (the operator's decision e)
        judge = robots.read_profile(registry.profile_file(self.robot_name), "sim")   # errors are the caller's answer, never an exit
        reply = self.api("goal.start", p)
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

    def _merge(self, route: dict) -> None:
        self.route["checks"] += route["checks"]
        if route["max"] is not None:
            self.route["max"] = max(self.route["max"] or 0, route["max"])

    def close(self) -> None:
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
    ap.add_argument("--client", default="lab-nav-server", help="the name the navigator takes the lease under")
    ap.add_argument("--data", type=Path, default=default_data(),
                    help="the Observatory's data folder: each goal run is written there as a run (env OBSERVATORY_DATA)")
    ap.add_argument("--out", type=Path, default=Path("state/nav"), help="the navigator's own output folders, one per goal run")
    ap.add_argument("--scene", default="apartment", help="the Observatory scene of the runs")
    ap.add_argument("--robot", help="the robot, by its registered name (default: the only one registered)")
    args = ap.parse_args()
    robots.select(args.robot)
    if args.data is None:
        sys.exit("lab-nav-server: --data (or OBSERVATORY_DATA): where the runs are written")
    host = simhost.load(args.host)
    runner = NavRunner(host, args.data, args.out, args.scene, args.client, args.robot_socket)
    listen, _, port = args.listen.rpartition(":")
    srv = Server((listen or "127.0.0.1", int(port)), runner)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # a terminate stops the navigator API too (runner.close)
    print(f"lab-nav-server: {args.listen}, the navigator API pid {runner.proc.pid}, robot "
          f"{runner.robot_socket}, camera {runner.camera.path}, runs in {args.data}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.close()


if __name__ == "__main__":
    main()
