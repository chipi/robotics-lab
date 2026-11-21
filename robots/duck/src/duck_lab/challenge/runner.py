"""The runner's side of the payload (RFC-0021 §3, step 2): the navigator started as its own process with only the robot's
connections (duck_lab.payload), driven over its contract, and its run copied into the official one with the truth put in
(runfile.truthcopy) while it runs. The runner keeps what the payload never gets: the host file, the truth, the judge.

    with Remote(host, run_out, scene_id, name, data, key, truth_log) as nav:     # nav.go_to, nav.loc.pose(), nav.record
        ...
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from duck_lab.nav.client import Rpc
from runfile import keys
from runfile.truthcopy import TruthCopy

STARTED_S = 60.0         # the payload process answers within this, or it is stopped
POLL_S = 0.1             # how often a goal's status is asked
COPY_S = 0.2             # how often the payload's run is copied into the official one (the live view's lag)
STOP_S = 10.0            # the payload ends this long after `stop`, else SIGTERM, then SIGKILL


class PayloadError(RuntimeError):
    """The payload process did not start, died, or answered with an error."""


def event(kind: str, text: str, /, **raw) -> dict:          # positional: a row's own fields may be named `kind` (a goal's)
    """The runner's own event, in the shape a navigator row's event has in a run (runfile.adapters.duck)."""
    return {"kind": kind, "text": text, "notable": True, "t_src": None, "raw": raw}


PROC = Path("/proc")       # where a process's sockets are read, when the host has it (a test points it elsewhere)


def truth_connections(pid: int, port: int) -> int | None:
    """The TCP connections process `pid` holds to `port` on this host: its own sockets (/proc/<pid>/fd) matched by inode in
    the kernel's TCP tables; where there is no /proc (macOS), `lsof` on the process. None when the process is gone or
    neither can say: not measured, never 0."""
    if PROC.exists():
        try:
            fds = list((PROC / str(pid) / "fd").iterdir())
        except FileNotFoundError:
            return None
        inodes = set()
        for fd in fds:
            try:
                link = os.readlink(fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
        n = 0
        for table in ("net/tcp", "net/tcp6"):
            try:
                lines = (PROC / table).read_text().splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                f = line.split()
                if len(f) > 9 and f[9] in inodes and int(f[2].rsplit(":", 1)[1], 16) == port:
                    n += 1
        return n
    try:
        os.kill(pid, 0)               # lsof says nothing for a process that is gone: that is not 0
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    try:
        out = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-Fn"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # -Fn: one `n<local>-><remote>` line per connection; lsof exits 1 when the process has none at all
    return sum(1 for line in out.stdout.splitlines() if line.startswith("n") and "->" in line
               and line.rsplit("->", 1)[1].rsplit(":", 1)[-1] == str(port))


class _Loc:
    def __init__(self, remote: "Remote"):
        self.remote = remote

    def pose(self):
        p = self.remote.call("status").get("pose")
        return tuple(p) if p else None


class Remote:
    """The payload as a navigator for the course code (go_to, loc.pose(), record, scale), across a process boundary."""

    def __init__(self, host, run_out: Path, scene: str, name: str, data: Path, key: str, truth_log, variant: str = "sim",
                 copy: TruthCopy | None = None, run: dict | None = None, payload: list | None = None,
                 camera: Path | None = None, extra: list | None = None):
        """`copy`: an official run already being written (an evaluation's earlier goals), which this payload's run is copied
        on into (TruthCopy.next_source), else a new one; `run`: its run record's fields that are the runner's (`kind`);
        `camera`: the camera's socket the runner serves (duck_lab.camera_server), handed to the payload as one of the robot's;
        `extra`: more of the payload's own options (a navigator's test switches)."""
        self.host, self.run_out = host, Path(run_out)
        self.dir = Path(tempfile.mkdtemp(prefix="pl-"))           # short: a unix socket path is limited to ~100 bytes
        self.sock = self.dir / "payload.sock"
        self.payload_data = self.run_out / "payload-data"         # the payload's own run: not the Observatory's data folder
        src = keys.run_dir(self.payload_data, keys.make_key("duck", scene, name))
        if copy is None:
            self.copy = TruthCopy(src, keys.run_dir(Path(data), key), key, truth_log.nearest, run=run)
        else:
            self.copy = copy
            copy.next_source(src)
        self._lock = threading.Lock()                             # the copy is written by the pump and by the runner's events
        self._stop = threading.Event()
        cmd = list(payload or [sys.executable, "-m", "duck_lab.payload"]) + [      # any navigator that keeps the contract
               "--robot", str(host.sockets["robot"]), "--depth", str(host.sockets["depth"]), "--map", str(host.sockets["map"]),
               "--listen", str(self.sock), "--out", str(self.run_out), "--data", str(self.payload_data),
               "--scene", scene, "--name", name, "--variant", variant] + (["--camera", str(camera)] if camera else []) + list(extra or [])
        env = {k: v for k, v in os.environ.items() if k != "ROBOTICS_LAB_HOST"}    # nothing of the host but its sockets
        self.log = open(self.run_out / "payload.log", "a")       # an evaluation's payloads, one after another
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        self.rpc = None
        try:
            self._connect()
            hello = self.call("hello")
        except Exception:
            self.close()
            raise
        self.name, self.kinds, self.scale = hello["name"], hello["kinds"], hello.get("scale")
        self.loc = _Loc(self)
        self._pump = threading.Thread(target=self._pumping, name="truth-copy", daemon=True)
        self._pump.start()

    def _connect(self) -> None:
        end = time.monotonic() + STARTED_S
        while True:
            if self.proc.poll() is not None:
                raise PayloadError(f"the payload ended before it answered (exit {self.proc.returncode}): see {self.run_out / 'payload.log'}")
            try:
                self.rpc = Rpc(self.sock, timeout=300.0)
                return
            except OSError:
                if time.monotonic() > end:
                    raise PayloadError(f"the payload did not answer on {self.sock} within {STARTED_S:.0f} s") from None
                time.sleep(0.2)

    def call(self, method: str, params: dict | None = None) -> dict:
        if self.proc.poll() is not None:
            raise PayloadError(f"the payload died (exit {self.proc.returncode}): see {self.run_out / 'payload.log'}")
        try:
            return self.rpc.call(method, params)
        except (OSError, json.JSONDecodeError) as e:
            raise PayloadError(f"{method}: the payload stopped answering ({type(e).__name__}: {e})") from None

    def _pumping(self) -> None:
        while not self._stop.wait(COPY_S):
            self.pump()

    def pump(self) -> None:
        with self._lock:
            try:
                self.copy.pump()
            except FileNotFoundError:
                pass                       # the payload has not opened its run yet

    def record(self, **row) -> None:
        """A runner's event in the official run (the course's per-goal row, an invariant, the verdict), at the run's time."""
        ev = row.pop("event")
        text = row.get("why") or " ".join(f"{k} {v}" for k, v in row.items() if k in ("n", "status", "rule"))
        with self._lock:
            if self.copy.rec is not None:
                self.copy.add(self.copy.last_t, "event", event(ev, f"{ev} {text}".strip(), **row))

    def localise(self) -> tuple | None:
        try:
            return tuple(self.call("localise")["pose"])
        except RuntimeError:
            return None

    def _goal(self, params: dict) -> dict:
        self.call("start", params)
        while True:
            st = self.call("status")
            if st["state"] not in ("running", "idle"):
                return st
            time.sleep(POLL_S)

    def go_to(self, goal, timeout_s: float) -> dict:
        """As Navigator.go_to: {status, why, ...}, the goal in the payload's map."""
        st = self._goal({"kind": "point", "goal": [float(goal[0]), float(goal[1])], "time_s": float(timeout_s)})
        out = dict(st.get("result") or {})
        out["status"], out["why"] = st["state"], st.get("why")
        return out

    def explore(self, minutes: float, **opts) -> dict:
        """`opts`: the explore goal's options (objects, find, site, object_costs, relocalise: duck_lab.payload)."""
        st = self._goal({"kind": "explore", "minutes": float(minutes), **opts})
        if st["state"] == "failed":
            raise PayloadError(f"explore failed in the payload: {st.get('why')}")
        return st["result"]

    @property
    def abort(self):
        return None

    @abort.setter
    def abort(self, reason) -> None:
        if reason:
            try:
                self.call("cancel", {"reason": reason})
            except PayloadError:
                pass

    def close(self, verdict: str | None = None, finish: bool = True):
        """The payload stopped (asked, then signalled); the robot stopped by the runner itself as well; the run copied whole.
        `finish`: the official run ends here (False: an evaluation's next goal copies on into it)."""
        self._stop.set()
        try:
            if self.rpc is not None and self.proc.poll() is None:
                self.call("stop")
        except (PayloadError, RuntimeError):
            pass
        try:
            self.proc.wait(STOP_S)
        except subprocess.TimeoutExpired:
            for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
                try:
                    os.killpg(self.proc.pid, sig)
                    self.proc.wait(wait)
                    break
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    continue
        self._zero_move()
        if self.rpc is not None:
            self.rpc.close()
        self.log.close()
        self.sock.unlink(missing_ok=True)
        try:
            self.dir.rmdir()
        except OSError:
            pass
        with self._lock:
            if not finish:
                self.copy.pump()        # all of this payload's run, before the next one's
                return None
            return self.copy.finish(verdict) if self.copy.rec is not None or self.copy.follower.dir.exists() else None

    def truth_connections(self, port: int) -> int | None:
        """How many TCP connections the payload's process holds to `port` now (the truth's): its own sockets (/proc/<pid>/fd)
        matched by inode against the kernel's TCP tables, or where there is no /proc (macOS) `lsof`; None when neither can
        tell (not measured, not zero). The body server's port also takes joint targets (op `write`), so a connection would
        be an actuation path too."""
        return truth_connections(self.proc.pid, port)

    def _zero_move(self) -> None:
        """robotd keeps the last command it was given: a payload that died mid-goal leaves the duck walking."""
        try:
            r = Rpc(self.host.sockets["robot"], timeout=2.0)
            try:
                r.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
            finally:
                r.close()
        except (OSError, RuntimeError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
