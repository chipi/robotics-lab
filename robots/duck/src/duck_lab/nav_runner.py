"""duck-nav-server: the runner in front of Mission Control's navigator API (RFC-0021 step 6).

    duck-nav-server --data /work/robotics-lab/data --out state/nav      # the host file's sockets, its gate's for the robot

Mission Control talks to this as it talked to the navigator API (the same methods, on the same TCP address), and every
call passes through unchanged to the navigator API (duck_lab.nav.server), which this starts as its own process with only
the robot's sockets and the camera's. What the navigator does not get stays here:

- **The truth:** the host's body server, sampled while a goal runs (simhost.truth).
- **The camera:** served on the host file's camera socket (duck_lab.camera_server), from the truth.
- **The truth guardrails** (`contact`, `fall`, `drop_clearance`, the robot inside a `no_go_area`): checked against the
  truth (guardrails.TruthGuard); a broken one stops the run through the API's `goal.break`, and the run ends
  `stopped_by_guardrail` as one the navigator broke itself.
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
from duck_lab.camera_server import CameraServer
from duck_lab.challenge.runner import truth_connections
from duck_lab.nav.client import Rpc
from duck_lab.nav.guardrails import TruthGuard
from runfile import keys
from runfile.catalog import default_data
from runfile.truthcopy import TruthCopy, TruthLog
from simhost.truth import Sampler

TERMINAL = ("reached", "done", "refused", "failed", "stopped_by_guardrail", "not_found", "cancelled", "interrupted")
STARTED_S = 60.0         # the navigator API answers within this, or the runner gives up
WATCH_S = 0.2            # how often a goal's run is copied and its state asked
ROUTE_EVERY = 40         # truth samples between two looks at the navigator's connections (2 s at 20 Hz)


class GoalWatch:
    """One goal run: its truth sampled, its truth guardrails checked, its run copied into the official one."""

    def __init__(self, runner: "NavRunner", key: str, guardrails: list):
        self.runner, self.key = runner, key
        _, _, name = keys.split_key(key)
        self.dir = runner.out / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.truth_log = TruthLog(self.dir / "truth.jsonl")
        self.copy = TruthCopy(keys.run_dir(runner.payload_data, key), keys.run_dir(runner.data, key), key, self.truth_log.nearest)
        self.guard = TruthGuard(guardrails)
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
                print(f"duck-nav-server: goal.break {b[0]} failed: {type(e).__name__}: {e}", flush=True)
                self.broken = None

    def _watch(self) -> None:
        while not self._done.wait(WATCH_S):
            self.pump()
            try:
                st = self.runner.api("goal.status", {"decisions_since": 10 ** 9, "objects_since": self._objects_v})
                self._objects_v = st.get("objects_v", -1)
            except Exception:           # noqa: BLE001 - the navigator API gone: the run ends here with what was copied
                st = {"state": "failed"}
            if st.get("state") in TERMINAL or st.get("state") == "idle":
                self.state = st.get("state")
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
                print(f"duck-nav-server: the run {self.key} could not be copied: {e}", flush=True)
        self.truth_log.close()
        summary = self.summary()
        (self.dir / "runner.json").write_text(json.dumps(summary, indent=1))
        print(f"duck-nav-server: {self.key} {self.state}: {json.dumps(summary)}", flush=True)

    def summary(self) -> dict:
        return {"key": self.key, "state": self.state, "broken": self.broken, "truth_checked": self.guard.checked,
                "truth_samples": self.sampler.samples, "truth_error": self.sampler.error, "truth_copy": self.copy.stats(),
                "truth_connections": dict(self.route)}


class NavRunner:
    def __init__(self, host, data: Path, out: Path, scene: str = "apartment", client: str = "duck-nav-server",
                 robot_socket: Path | None = None):
        if host.truth_port is None:
            raise ValueError(f"{host.source}: this host has no truth (truth_port is null): Mission Control talks to the "
                             f"navigator API itself there (python -m duck_lab.nav.server)")
        self.host, self.data, self.out = host, Path(data), Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.payload_data = self.out / "payload-data"           # the navigator's own runs: not the Observatory's data folder
        self.dir = Path(tempfile.mkdtemp(prefix="nr-"))         # short: a unix socket path is limited to ~100 bytes
        self.sock = self.dir / "api.sock"
        self.goal: GoalWatch | None = None
        self.goals = 0
        self.route = {"checks": 0, "max": None}
        self.camera = CameraServer(host, host.sockets["camera"]).start()
        robot = robot_socket or host.sockets["gate"]
        cmd = [sys.executable, "-m", "duck_lab.nav.server", "--robot", str(robot), "--depth", str(host.sockets["depth"]),
               "--map", str(host.sockets["map"]), "--camera", str(self.camera.path), "--listen", str(self.sock),
               "--client", client, "--data", str(self.payload_data), "--out", str(self.out), "--scene", scene]
        env = {k: v for k, v in os.environ.items() if k != "ROBOTICS_LAB_HOST"}     # nothing of the host but its sockets
        self.log = open(self.out / "navigator.log", "a")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        self._rpc_lock = threading.Lock()
        self.rpc = None
        try:
            self._connect()
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

    def call(self, method: str, p: dict):
        if method == "runner.status":
            last = self.goal.summary() if self.goal else None
            return {"navigator_pid": self.proc.pid, "truth_connections": dict(self.route), "goals": self.goals, "last_goal": last}
        if method != "goal.start":
            return self.api(method, p)
        if self.goal is not None:
            self.goal.finish()          # (the navigator API refuses a second goal while one runs: this one is over)
            self._merge(self.goal.route)
        reply = self.api("goal.start", p)
        if isinstance(reply, dict) and reply.get("run_key"):
            guardrails = (p.get("conditions") or {}).get("guardrails") or []
            self.goal = GoalWatch(self, reply["run_key"], guardrails).start()
            self.goals += 1
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
    ap.add_argument("--robot-socket", type=Path, help="the robot's socket: a gate's (default: the host file's gate socket)")
    ap.add_argument("--client", default="duck-nav-server", help="the name the navigator takes the lease under")
    ap.add_argument("--data", type=Path, default=default_data(),
                    help="the Observatory's data folder: each goal run is written there as a run (env OBSERVATORY_DATA)")
    ap.add_argument("--out", type=Path, default=Path("state/nav"), help="the navigator's own output folders, one per goal run")
    ap.add_argument("--scene", default="apartment", help="the Observatory scene of the runs")
    args = ap.parse_args()
    if args.data is None:
        sys.exit("duck-nav-server: --data (or OBSERVATORY_DATA): where the runs are written")
    host = simhost.load(args.host)
    runner = NavRunner(host, args.data, args.out, args.scene, args.client, args.robot_socket)
    listen, _, port = args.listen.rpartition(":")
    srv = Server((listen or "127.0.0.1", int(port)), runner)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # a terminate stops the navigator API too (runner.close)
    print(f"duck-nav-server: {args.listen}, the navigator API pid {runner.proc.pid}, robot "
          f"{args.robot_socket or host.sockets['gate']}, camera {runner.camera.path}, runs in {args.data}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.close()


if __name__ == "__main__":
    main()
