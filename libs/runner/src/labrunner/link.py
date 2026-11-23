"""The link to a robot whose sockets are on another computer (phase 5 item 4b unit B5; RFC-0002 section 3.3): one ssh session carries the
robot's Unix sockets to this workstation, a check asks each socket a question that only a live robot answers, and a supervisor
restarts the session with back-off when it dies. Nothing here is the duck's: a forward is a named socket on a host (a local path,
the remote path, the method that proves it alive); `duck_forwards` is the duck's three.

    lab-link up --host microduck@duck              # open the forwards, check them, reconnect with back-off until stopped
    lab-link check --host microduck@duck           # one pass: exit 0 if every socket answers, else 1 and why
    lab-link up --host microduck@duck --dry-run    # print the ssh command; run nothing

Why a check asks, not only connects: when the robot's end of an ssh forward is gone, the local socket file stays and a connect still
succeeds; the connection is closed a moment later. Only a request that gets an answer (or an end of stream) tells a live socket from a
dead one. The probes are read-only (`robot.health`, `map.status`, `tof.stream`); the gate's own socket is asked `gate.who`.

The ssh window the robot's face button opens lasts 30 minutes (RFC-0002 section 3.3), so ssh exiting is an expected event, not a
fault: the supervisor retries with growing waits until the window is open again. It never resends a command and never touches the
gate: `lab-gate` closes its upstream when the forward dies and exits (it does not reconnect); restart it after the link is back.

Standard library only; `ssh` is an external command, run only by `up`, never by a test."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

CHECK_TIMEOUT_S = 2.0        # one question to one socket
POLL_S = 2.0                 # between checks of a link that is up
FAILS_TO_DROP = 3            # consecutive failed checks before an up link is torn down (one lost answer is not a dead tunnel)
UP_TIMEOUT_S = 20.0          # a started ssh has this long to bring every forward up
BACKOFF_FIRST_S, BACKOFF_FACTOR, BACKOFF_CAP_S = 1.0, 2.0, 30.0
STABLE_S = 30.0              # a link up this long when it fails starts the back-off again; a flapping one keeps growing it
KILL_WAIT_S = 3.0


@dataclass(frozen=True)
class Forward:
    """A named socket on a robot's computer, brought to a local path. `method` is a read-only JSON-RPC call that a live end answers."""
    name: str
    local: Path
    remote: str
    method: str


def duck_forwards(directory: Path, robot: str = "duck") -> list:
    """The duck's three sockets (RFC-0002 section 3.3), named as the host file names them (`<robot>.sock`, `-tof`, `-map`: simhost)."""
    d = Path(directory)
    return [Forward("robot", d / f"{robot}.sock", "/run/robotd.sock", "robot.health"),
            Forward("depth", d / f"{robot}-tof.sock", "/run/tofd/tof.sock", "tof.stream"),
            Forward("map", d / f"{robot}-map.sock", "/run/mapd/map.sock", "map.status")]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    why: str = "answered"
    ms: float | None = None

    def line(self) -> str:
        return f"{'ok  ' if self.ok else 'DEAD'} {self.name}: {self.why}" + (f" ({self.ms:.0f} ms)" if self.ms is not None else "")


def check_socket(name: str, path: Path, method: str, timeout_s: float = CHECK_TIMEOUT_S) -> Check:
    """Ask one socket one question. Any JSON line back (a result or an error) is a live end; each way to be dead names itself."""
    p = Path(path)
    try:
        mode = p.stat().st_mode
    except FileNotFoundError:
        return Check(name, False, f"no socket file {p} (the forward is not up)")
    except OSError as exc:
        return Check(name, False, f"{p}: {exc}")
    if not stat.S_ISSOCK(mode):
        return Check(name, False, f"{p} is not a socket")
    t0 = time.monotonic()
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout_s)
    try:
        s.connect(str(p))
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}) + "\n").encode())
        line = s.makefile("r").readline()
    except (ConnectionRefusedError, FileNotFoundError):
        return Check(name, False, "nothing listens (a stale socket file: ssh is gone)")
    except (ConnectionResetError, BrokenPipeError):         # the hang-up can land before or after the request: both are the same dead end
        return Check(name, False, f"closed on {method} (the forward is up but the robot's end is gone)")
    except (socket.timeout, TimeoutError):
        return Check(name, False, f"no answer to {method} in {timeout_s:g} s (the link is silent)")
    except OSError as exc:
        return Check(name, False, f"{type(exc).__name__}: {exc}")
    finally:
        s.close()
    if not line:
        return Check(name, False, f"closed on {method} (the forward is up but the robot's end is gone)")
    try:
        msg = json.loads(line)
    except ValueError:
        return Check(name, False, f"answered {method} with something that is not JSON")
    if not isinstance(msg, dict):
        return Check(name, False, f"answered {method} with something that is not JSON-RPC")
    return Check(name, True, ms=(time.monotonic() - t0) * 1000)


def check_all(forwards, local_only=()) -> list:
    """`local_only`: (name, path, method) of sockets that are not forwarded (the gate): checked and reported, never a reason to restart ssh."""
    return [check_socket(f.name, f.local, f.method) for f in forwards] + [check_socket(n, p, m) for n, p, m in local_only]


def ssh_command(host: str, forwards, ssh: str = "ssh", options=()) -> list:
    """The one ssh session. ExitOnForwardFailure: a forward that cannot bind ends ssh, so the supervisor sees it rather than a half link.
    StreamLocalBindUnlink: a socket file left by a dead ssh does not block the next one. ServerAlive*: a silent Wi-Fi drop ends ssh in
    about 15 s instead of hanging. BatchMode: never wait for a password nobody sees."""
    argv = [ssh, "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "StreamLocalBindUnlink=yes",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=10"]
    for o in options:
        argv += ["-o", o]
    for f in forwards:
        argv += ["-L", f"{f.local}:{f.remote}"]
    return argv + [host]


class Backoff:
    """1, 2, 4 ... capped; no jitter: one workstation, one robot."""

    def __init__(self, first: float = BACKOFF_FIRST_S, factor: float = BACKOFF_FACTOR, cap: float = BACKOFF_CAP_S):
        self.first, self.factor, self.cap = first, factor, cap
        self._next = first

    def delay(self) -> float:
        d = self._next
        self._next = min(self.cap, self._next * self.factor)
        return d

    def reset(self) -> None:
        self._next = self.first


class Link:
    """Keeps one ssh session up. `spawn(argv)` returns a Popen-like (poll, terminate, kill, wait); `stop` is a threading.Event-like
    (is_set, wait). Both, `check` and `clock` are arguments so a test runs it with no ssh and no real time."""

    def __init__(self, host: str, forwards, *, local_only=(), spawn=None, check=None, stop=None, clock=time.monotonic,
                 report=None, backoff: Backoff | None = None, poll_s: float = POLL_S, fails_to_drop: int = FAILS_TO_DROP,
                 up_timeout_s: float = UP_TIMEOUT_S, stable_s: float = STABLE_S, ssh: str = "ssh", options=()):
        self.host, self.forwards, self.local_only = host, list(forwards), list(local_only)
        self._spawn = spawn or (lambda argv: subprocess.Popen(argv, stdin=subprocess.DEVNULL))
        self._check = check or (lambda: check_all(self.forwards, self.local_only))
        self.stop = stop or threading.Event()
        self._clock = clock
        self.report = report or (lambda msg: print(f"lab-link: {msg}", flush=True))
        self.backoff = backoff or Backoff()
        self.poll_s, self.fails_to_drop, self.up_timeout_s, self.stable_s = poll_s, fails_to_drop, up_timeout_s, stable_s
        self.argv = ssh_command(host, self.forwards, ssh, options)
        self.state = "down"                 # down | connecting | up
        self.sessions = 0                   # ssh sessions started

    def _forwarded_dead(self, results) -> list:
        names = {f.name for f in self.forwards}
        return [c for c in results if c.name in names and not c.ok]

    def _wait_up(self, proc) -> str | None:
        """None: every forward answers; else why this session failed."""
        end = self._clock() + self.up_timeout_s
        last = []
        while not self.stop.is_set():
            rc = proc.poll()
            if rc is not None:
                return f"ssh exited with {rc} before the forwards were up"
            last = self._forwarded_dead(self._check())
            if not last:
                return None
            if self._clock() >= end:
                return "not up in %g s: %s" % (self.up_timeout_s, "; ".join(c.line() for c in last))
            self.stop.wait(0.5)
        return "stopped"

    def _watch(self, proc) -> str:
        """While up: why the session ended."""
        fails, local_was = 0, True
        while not self.stop.wait(self.poll_s):
            rc = proc.poll()
            if rc is not None:
                return f"ssh exited with {rc}"
            results = self._check()
            dead = self._forwarded_dead(results)
            fails = fails + 1 if dead else 0
            local = [c for c in results if c.name not in {f.name for f in self.forwards}]
            if all(c.ok for c in local) != local_was:      # the gate is not ours to restart; say when it goes and comes back
                local_was = not local_was
                self.report("; ".join(c.line() for c in local))
            if fails >= self.fails_to_drop:
                return "; ".join(c.line() for c in dead)
        return "stopped"

    def _end(self, proc) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(KILL_WAIT_S)
            except Exception:                                   # noqa: BLE001 - TimeoutExpired of whatever Popen this is
                proc.kill()
                proc.wait(KILL_WAIT_S)

    def run(self) -> None:
        for f in self.forwards:
            f.local.parent.mkdir(parents=True, exist_ok=True)
        while not self.stop.is_set():
            self.state = "connecting"
            self.sessions += 1
            self.report(f"connecting to {self.host} (session {self.sessions})")
            try:
                proc = self._spawn(self.argv)
            except OSError as exc:
                why, up_at = f"cannot run ssh: {exc}", None
            else:
                why = self._wait_up(proc)
                up_at = None
                if why is None:
                    up_at = self._clock()
                    self.state = "up"
                    self.report("up: " + ", ".join(f.name for f in self.forwards))
                    why = self._watch(proc)
                self._end(proc)
            self.state = "down"
            if self.stop.is_set():
                break
            if up_at is not None and self._clock() - up_at >= self.stable_s:
                self.backoff.reset()
            delay = self.backoff.delay()
            self.report(f"down: {why}; retrying in {delay:g} s")
            self.stop.wait(delay)
        self.state = "down"
        self.report("stopped")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["up", "check"], help="up: open and keep the link; check: ask each socket once")
    ap.add_argument("--host", required=True, help="the robot's ssh address, like microduck@duck")
    ap.add_argument("--robot", default="duck", help="the robot's name: the local socket files are <robot>.sock, -tof.sock, -map.sock")
    ap.add_argument("--dir", type=Path, default=Path("~/.cache/duck-real"), help="where the local socket files go "
                    "(default ~/.cache/duck-real: apart from the simulator's ~/.cache/duck-sim, so one never answers for the other)")
    ap.add_argument("--forward", action="append", default=[], metavar="NAME=LOCAL=REMOTE=METHOD",
                    help="a forward in place of the duck's three (repeat); METHOD is a read-only JSON-RPC call that proves it alive")
    ap.add_argument("--gate", type=Path, help="the gate's socket, also checked (never a reason to restart ssh)")
    ap.add_argument("--ssh", default="ssh", help="the ssh command")
    ap.add_argument("-o", dest="options", action="append", default=[], help="an ssh -o option (a port, a key); repeat")
    ap.add_argument("--dry-run", action="store_true", help="up: print the ssh command and exit")
    args = ap.parse_args(argv)
    directory = args.dir.expanduser()
    if args.forward:
        forwards = []
        for spec in args.forward:
            parts = spec.split("=")
            if len(parts) != 4 or not all(parts):
                ap.error(f"--forward {spec!r}: want NAME=LOCAL=REMOTE=METHOD")
            forwards.append(Forward(parts[0], Path(parts[1]).expanduser(), parts[2], parts[3]))
    else:
        forwards = duck_forwards(directory, args.robot)
    local_only = [("gate", args.gate.expanduser(), "gate.who")] if args.gate else []
    if args.command == "check":
        results = check_all(forwards, local_only)
        for c in results:
            print(c.line())
        print("link " + ("PASS" if all(c.ok for c in results) else "FAIL"))
        return 0 if all(c.ok for c in results) else 1
    link = Link(args.host, forwards, local_only=local_only, ssh=args.ssh, options=args.options)
    if args.dry_run:
        print(" ".join(link.argv))
        return 0
    signal.signal(signal.SIGTERM, lambda *_: link.stop.set())
    signal.signal(signal.SIGINT, lambda *_: link.stop.set())
    link.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
