"""The link to a robot whose sockets are on another computer (phase 5 item 4b unit B5; RFC-0002 section 3.3): one ssh session carries the
robot's Unix sockets to this workstation, a check asks each socket a question that only a live robot answers, and a supervisor
restarts the session with back-off when it dies. Nothing here is the duck's: a forward is a named socket on a host (a local path,
the remote path, the method that proves it alive); `duck_forwards` is the duck's three.

    lab-link up --host microduck@duck              # open the forwards, check them, reconnect with back-off until stopped
    lab-link check --host microduck@duck           # one pass: exit 0 if every socket answers, else 1 and why
    lab-link up --host microduck@duck --dry-run    # print the ssh command; run nothing
    lab-link up --host microduck@duck --gate G.sock --restart-gate    # also run lab-gate on the forwarded robot socket (see below)

Why a check asks, not only connects: when the robot's end of an ssh forward is gone, the local socket file stays and a connect still
succeeds; the connection is closed a moment later. Only a request that gets an answer (or an end of stream) tells a live socket from a
dead one. The probes are read-only (`robot.health`, `map.status`, `tof.stream`); the gate's own socket is asked `gate.who`.

The ssh window the robot's face button opens lasts 30 minutes (RFC-0002 section 3.3), so ssh exiting is an expected event, not a
fault: the supervisor retries with growing waits until the window is open again. It never resends a command. `lab-gate` closes its
upstream when the forward dies and exits (it does not reconnect), so with `--restart-gate` (or `--gate-cmd`) the supervisor starts it
once the forwards answer and again after each reconnect, never while the link is down; without either option it does not touch the gate.
The gate's lease dies with the old gate: after a reconnect the robot stays stopped until a client acquires again.

Standard library and runfile only; `ssh` is an external command, run only by `up`, never by a test."""

from __future__ import annotations

import argparse
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from runfile import linkcheck
from runfile.linkcheck import CHECK_TIMEOUT_S

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
    """Ask one socket one question (runfile.linkcheck, the one Mission Control asks too)."""
    ok, why, ms = linkcheck.check_socket(path, method, timeout_s)
    return Check(name, ok, why, ms)


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
                 report=None, backoff: Backoff | None = None, gate_argv=None, spawn_gate=None, poll_s: float = POLL_S, fails_to_drop: int = FAILS_TO_DROP,
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
        self.gate_argv = list(gate_argv) if gate_argv else None      # run while the link is up; None: the gate is the operator's
        self._spawn_gate = spawn_gate or (lambda argv: subprocess.Popen(argv, stdin=subprocess.DEVNULL))
        self.gates = 0                      # gates started
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

    def _start_gate(self):
        """Only called with the link up: a gate started on a dead forward would exit at once."""
        try:
            gate = self._spawn_gate(self.gate_argv)
        except OSError as exc:
            self.report(f"cannot run the gate: {exc}")
            return None
        self.gates += 1
        self.report(f"gate started (pid {getattr(gate, 'pid', '?')}); the old lease is gone, clients must acquire again")
        return gate

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
                    gate = self._start_gate() if self.gate_argv else None
                    why = self._watch(proc)
                    if gate is not None:
                        self._end(gate)         # it exits itself when the forward dies; this covers a stop or a half-dead tunnel
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
    ap.add_argument("--restart-gate", action="store_true", help="up: run lab-gate (needs --gate for its socket; upstream: the robot forward) once the "
                    "forwards answer, and again after each reconnect; never while the link is down")
    ap.add_argument("--gate-cmd", help="up: the command to run as the gate instead of lab-gate's default (implies --restart-gate), split like a shell line")
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
    gate_argv = None
    if args.gate_cmd:
        gate_argv = shlex.split(args.gate_cmd)
    elif args.restart_gate:
        robot = next((f for f in forwards if f.name == "robot"), None)
        if args.gate is None or robot is None:
            ap.error("--restart-gate needs --gate (the gate's socket) and a forward named robot; or give --gate-cmd")
        gate_argv = [sys.executable, "-m", "labrunner.gate", "--listen", str(args.gate.expanduser()), "--upstream", str(robot.local)]
    link = Link(args.host, forwards, local_only=local_only, ssh=args.ssh, options=args.options, gate_argv=gate_argv)
    if args.dry_run:
        print(" ".join(link.argv))
        if gate_argv:
            print("gate (after the forwards answer): " + " ".join(shlex.quote(a) for a in gate_argv))
        return 0
    signal.signal(signal.SIGTERM, lambda *_: link.stop.set())
    signal.signal(signal.SIGINT, lambda *_: link.stop.set())
    link.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
