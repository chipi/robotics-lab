"""The link tooling (phase 5 item 4b unit B5): the checks tell a live socket from each way of a dead one, the ssh command is the one the
design says, the back-off grows and resets, and the supervisor tears a dead tunnel down and brings it up again. No ssh runs and no
robot is reached: a stand-in for ssh serves real Unix sockets, and a scripted one runs on a fake clock.
Run: cd libs/runner && uv run python tests/test_link.py"""

import contextlib
import io
import json
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

from labrunner import link
from labrunner.link import Backoff, Forward, Link, check_socket, duck_forwards, ssh_command

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Peer:
    """A Unix-socket server that behaves as `mode` says: answer (a result), error (a JSON-RPC error, still a live end), close (accept and
    hang up: an ssh forward whose robot end is gone), silent (accept, never answer), garbage (not JSON)."""

    def __init__(self, path: Path, mode: str = "answer"):
        self.path, self.mode = path, mode
        self.asked: list = []
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(8)
        self._conns: list = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.server.accept()
            except OSError:
                return
            self._conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        if self.mode == "close":
            c.close()
            return
        f = c.makefile("rw")
        try:
            for line in f:
                req = json.loads(line)
                self.asked.append(req["method"])
                if self.mode == "silent":
                    continue
                out = {"answer": {"jsonrpc": "2.0", "id": req["id"], "result": {}},
                       "error": {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "no such method"}},
                       "garbage": "not json"}[self.mode]
                f.write((out if isinstance(out, str) else json.dumps(out)) + "\n")
                f.flush()
        except (OSError, ValueError):
            pass

    def close(self, leave_file: bool = True):
        """The listener goes; the file stays (what a killed ssh leaves) unless asked."""
        with contextlib.suppress(OSError):
            self.server.shutdown(socket.SHUT_RDWR)          # close() alone does not end a blocked accept: the listener would live on
        self.server.close()
        for c in self._conns:
            with contextlib.suppress(OSError):
                c.close()
        if not leave_file:
            self.path.unlink(missing_ok=True)


tmp = Path(tempfile.mkdtemp(prefix="lablink-"))

# ---- the checks: a live end, and each way to be dead names itself ----
p = Peer(tmp / "a.sock")
c = check_socket("robot", tmp / "a.sock", "robot.health", 1.0)
check("a socket that answers is ok, and was asked the method", c.ok and p.asked == ["robot.health"], c)
p.close()
c = check_socket("robot", tmp / "a.sock", "robot.health", 1.0)
check("must fail: a stale file (the listener is gone, the file stays) is dead, 'nothing listens'", not c.ok and "nothing listens" in c.why, c)

p = Peer(tmp / "e.sock", "error")
c = check_socket("map", tmp / "e.sock", "map.status", 1.0)
check("a JSON-RPC error is still a live end", c.ok, c)
p.close()

p = Peer(tmp / "c.sock", "close")
c = check_socket("map", tmp / "c.sock", "map.status", 1.0)
check("must fail: connect works but the end hangs up (the dead forward's shape) is dead, 'closed'", not c.ok and "closed" in c.why, c)
p.close()

p = Peer(tmp / "s.sock", "silent")
t0 = time.monotonic()
c = check_socket("depth", tmp / "s.sock", "tof.stream", 0.3)
check("must fail: a socket that never answers is dead, 'silent', after the timeout and no longer",
      not c.ok and "silent" in c.why and time.monotonic() - t0 < 2.0, (c, time.monotonic() - t0))
p.close()

p = Peer(tmp / "g.sock", "garbage")
c = check_socket("robot", tmp / "g.sock", "robot.health", 1.0)
check("must fail: an answer that is not JSON is dead", not c.ok and "not JSON" in c.why, c)
p.close()

c = check_socket("robot", tmp / "nope.sock", "robot.health", 1.0)
check("must fail: no socket file is dead, 'the forward is not up'", not c.ok and "not up" in c.why, c)
(tmp / "plain").write_text("x")
c = check_socket("robot", tmp / "plain", "robot.health", 1.0)
check("must fail: a regular file where a socket should be is dead", not c.ok and "not a socket" in c.why, c)

# ---- the duck's forwards and the ssh command ----
fw = duck_forwards(tmp / "real", "duck")
check("the duck's forwards: robotd, tofd, mapd, named as the host file names them",
      [(f.name, f.local.name, f.remote) for f in fw] == [("robot", "duck.sock", "/run/robotd.sock"),
                                                         ("depth", "duck-tof.sock", "/run/tofd/tof.sock"),
                                                         ("map", "duck-map.sock", "/run/mapd/map.sock")], fw)
argv = ssh_command("microduck@duck", fw, options=["Port=2222"])
check("ssh: no shell, no tty, the host last", argv[0] == "ssh" and "-N" in argv and "-T" in argv and argv[-1] == "microduck@duck", argv)
check("ssh: a forward that cannot bind ends it, a stale file does not block it, a silent drop ends it, no password prompt",
      all(o in argv for o in ("ExitOnForwardFailure=yes", "StreamLocalBindUnlink=yes", "ServerAliveInterval=5", "BatchMode=yes")), argv)
check("ssh: one -L local:remote per forward, and the caller's own -o",
      [argv[i + 1] for i, a in enumerate(argv) if a == "-L"] == [f"{f.local}:{f.remote}" for f in fw] and "Port=2222" in argv, argv)

# ---- the back-off ----
b = Backoff()
seq = [b.delay() for _ in range(8)]
check("back-off doubles from 1 s and stops at 30 s", seq == [1, 2, 4, 8, 16, 30, 30, 30], seq)
b.reset()
check("back-off starts again after reset", b.delay() == 1.0)


# ---- the supervisor on a fake clock: ssh exits (the 30-minute window), the delays grow, a long-lived link resets them ----
class FakeClock:
    def __init__(self):
        self.t = 0.0


class FakeStop:
    """Threading.Event's is_set and wait, on the fake clock: wait advances time and returns at once."""

    def __init__(self, clock):
        self.clock, self.flag = clock, False

    def is_set(self):
        return self.flag

    def set(self):
        self.flag = True

    def wait(self, t):
        self.clock.t += t
        return self.flag


class FakeProc:
    def __init__(self, clock, up_after, lifetime):
        self.clock, self.born, self.up_after, self.lifetime = clock, clock.t, up_after, lifetime
        self.ended = False
        self.terminated = False

    def poll(self):
        return None if (not self.ended and self.clock.t < self.born + self.lifetime) else 255

    def is_up(self):
        return self.poll() is None and self.clock.t >= self.born + self.up_after

    def terminate(self):
        self.ended = self.terminated = True

    def kill(self):
        self.ended = True

    def wait(self, t=None):
        return 0


clock = FakeClock()
stop = FakeStop(clock)
# (up_after, lifetime): ssh dies at once twice (the window is shut); one that lives 100 s; one that dies at once; one that is up 5 s
plan = [(99, 0), (99, 0), (1, 100), (99, 0), (1, 5)]
procs: list = []


def spawn(argv):
    if len(procs) >= len(plan):
        if len(procs) > len(plan):
            stop.set()
        procs.append(procs[-1])
        raise OSError("ssh: not found")
    proc = FakeProc(clock, *plan[len(procs)])
    procs.append(proc)
    return proc


def scripted_check():
    up = procs[-1].is_up()
    return [link.Check(f.name, up, "answered" if up else "closed on x (the forward is up but the robot's end is gone)") for f in fw]


said: list = []
lk = Link("microduck@duck", fw, spawn=spawn, check=scripted_check, stop=stop, clock=lambda: clock.t, report=said.append,
          poll_s=2.0, fails_to_drop=3, up_timeout_s=20.0, stable_s=30.0)
lk.run()
delays = [float(m.split("retrying in ")[1].split(" s")[0]) for m in said if "retrying in" in m]
check("the supervisor retries after ssh exits, waiting 1, 2, then 1 again after a link that lasted, then 2, 4 for a flapping one",
      delays == [1, 2, 1, 2, 4, 8][:len(delays)] and delays[:5] == [1, 2, 1, 2, 4], (delays, said))
check("the supervisor says why each session ended", any("ssh exited with 255 before the forwards were up" in m for m in said) and
      any("ssh exited with 255;" in m for m in said), said)
check("the supervisor says 'up' only when every forward answered", sum(m.startswith("up:") for m in said) == 2, said)
check("the supervisor cannot run ssh: says so, and does not crash", any("cannot run ssh" in m for m in said), said)
check("the supervisor ends stopped", lk.state == "down" and said[-1] == "stopped", (lk.state, said[-1]))

# ---- stop while up: ssh is terminated, not left behind ----
clock2 = FakeClock()
stop2 = FakeStop(clock2)
holder: list = []
n_polls = [0]


def spawn2(argv):
    holder.append(FakeProc(clock2, 0, 1000))
    return holder[-1]


def check2():
    n_polls[0] += 1
    if n_polls[0] > 4:
        stop2.set()
    return [link.Check(f.name, True) for f in fw]


Link("h", fw, spawn=spawn2, check=check2, stop=stop2, clock=lambda: clock2.t, report=lambda m: None).run()
check("stopping an up link terminates ssh", len(holder) == 1 and holder[0].terminated, holder)

# ---- the dead socket and the reconnect, on real sockets: a stand-in for ssh serves the three local paths ----
real = duck_forwards(tmp / "real", "duck")


class FakeSsh:
    """What ssh does for the link: binds the local socket files (unlinking a stale one, StreamLocalBindUnlink) and serves them while it
    lives; a kill stops the listeners and leaves the files, as a killed ssh can."""

    def __init__(self, argv):
        self.argv, self.peers, self.rc = argv, {}, None
        for f in real:
            f.local.unlink(missing_ok=True)
            self.peers[f.name] = Peer(f.local)

    def poll(self):
        return self.rc

    def terminate(self):
        self.rc = -15
        for p in self.peers.values():
            p.close()

    kill = terminate

    def wait(self, t=None):
        return self.rc

    def break_remote(self, name):
        """The robot's end of one forward goes: ssh keeps the local socket and hangs up on every connection."""
        path = self.peers[name].path
        self.peers[name].close(leave_file=False)
        self.peers[name] = Peer(path, "close")


sessions: list = []


def spawn_real(argv):
    sessions.append(FakeSsh(argv))
    return sessions[-1]


said2: list = []
stop3 = threading.Event()
lk = Link("microduck@duck", real, spawn=spawn_real, stop=stop3, report=said2.append, poll_s=0.05, fails_to_drop=3,
          up_timeout_s=5.0, backoff=Backoff(0.05, 2, 0.2))
t = threading.Thread(target=lk.run, daemon=True)
t.start()
check("the link comes up: all three real sockets answer their method", wait_for(lambda: lk.state == "up"), said2)
check("... and the ssh command it ran carries all three forwards", sum(a == "-L" for a in sessions[0].argv) == 3, sessions[0].argv)
sessions[0].break_remote("map")
dead = check_socket("map", real[2].local, "map.status", 1.0)
check("must fail: the broken forward is dead by the check, 'closed'", not dead.ok and "closed" in dead.why, dead)
check("the supervisor tears the dead session down and starts another", wait_for(lambda: lk.sessions >= 2) and sessions[0].rc == -15, said2)
check("... and the new session comes up with every socket answering",
      wait_for(lambda: lk.state == "up") and all(check_socket(f.name, f.local, f.method, 1.0).ok for f in real), said2)
check("... and said why it dropped the first", any(m.startswith("down:") and "closed" in m for m in said2), said2)
stop3.set()
t.join(timeout=5)
check("stopping ends the run and the last ssh", not t.is_alive() and sessions[-1].rc == -15, said2)

# ---- the gate's own socket is checked, reported, and never restarts ssh ----
gate = Peer(tmp / "gate.sock", "close")
res = link.check_all(real, [("gate", tmp / "gate.sock", "gate.who")])
check("check_all asks the forwards and the gate's socket, and names the gate", [c.name for c in res][-1] == "gate" and not res[-1].ok, res)
gate.close()

# ---- the command line: check prints one line per socket and PASS or FAIL, exit 0 or 1; --dry-run runs nothing ----
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = link.main(["check", "--host", "h", "--dir", str(tmp / "empty"), "--robot", "duck"])
check("lab-link check with nothing up: FAIL, exit 1, one line per socket",
      rc == 1 and out.getvalue().count("DEAD") == 3 and out.getvalue().strip().endswith("link FAIL"), out.getvalue())
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = link.main(["up", "--host", "microduck@duck", "--dir", str(tmp / "dry"), "--dry-run"])
check("lab-link up --dry-run prints the ssh command and runs nothing", rc == 0 and out.getvalue().startswith("ssh -N") and
      out.getvalue().strip().endswith("microduck@duck") and not (tmp / "dry").exists(), out.getvalue())
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = link.main(["check", "--host", "h", "--forward", f"x={tmp / 'x.sock'}=/run/x.sock=x.ping"])
check("--forward replaces the duck's three with a named socket (a robot other than the duck)",
      rc == 1 and out.getvalue().count("DEAD") == 1 and "DEAD x:" in out.getvalue(), out.getvalue())

if failures:
    print(f"\nFAIL {len(failures)}: {failures}")
    raise SystemExit(1)
shutil.rmtree(tmp, ignore_errors=True)
print("\nPASS test_link")
