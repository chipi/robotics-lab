"""The link check (phase 5 item 4e unit E9): the one question lab-link and Mission Control both ask a socket, `runfile.linkcheck.check_socket`.
A live end answers (a JSON-RPC error counts), and each way to be dead names itself, in the words of a forward (ssh) or of the gate (a process
here). Real Unix sockets, no ssh, no robot. Run: cd libs/runfile && uv run python tests/test_linkcheck.py"""

import contextlib
import json
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

from runfile import linkcheck

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:300]}]" if detail else ""))
    if not cond:
        failures.append(name)


class Peer:
    """A Unix-socket server: `answer` (a result), `error` (a JSON-RPC error), `close` (accept and hang up), `silent`, `garbage` (not JSON)."""

    def __init__(self, path: Path, mode: str = "answer"):
        self.path, self.mode, self.asked = path, mode, []
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
                       "garbage": "not json", "list": [1]}[self.mode]
                f.write((out if isinstance(out, str) else json.dumps(out)) + "\n")
                f.flush()
        except (OSError, ValueError):
            pass

    def close(self):
        with contextlib.suppress(OSError):
            self.server.shutdown(socket.SHUT_RDWR)
        self.server.close()


tmp = Path(tempfile.mkdtemp(prefix="linkcheck-"))
ask = linkcheck.check_socket

p = Peer(tmp / "a.sock")
ok, why, ms = ask(tmp / "a.sock", "robot.health", 1.0)
check("a socket that answers is alive, says so, was asked the method, and the answer took a measured time",
      ok and why == "answered" and p.asked == ["robot.health"] and ms is not None and ms >= 0, (ok, why, ms, p.asked))
p.close()
ok, why, ms = ask(tmp / "a.sock", "robot.health", 1.0)
check("must fail: a stale file (the listener gone, the file left) is dead: 'nothing listens', ssh named, no time", not ok and "nothing listens" in why
      and "ssh is gone" in why and ms is None, (ok, why, ms))
check("... and for the gate the same file says the gate exited, not ssh", "the gate has exited" in ask(tmp / "a.sock", "gate.who", 1.0, gate=True)[1]
      and "ssh" not in ask(tmp / "a.sock", "gate.who", 1.0, gate=True)[1])

p = Peer(tmp / "e.sock", "error")
check("a JSON-RPC error is still a live end", ask(tmp / "e.sock", "map.status", 1.0)[0])
p.close()
p = Peer(tmp / "c.sock", "close")
ok, why, _ = ask(tmp / "c.sock", "map.status", 1.0)
check("must fail: connect works but the end hangs up: dead, 'closed', the robot's end gone", not ok and "closed on map.status" in why and "robot's end is gone" in why, why)
check("... the gate's words: 'the gate hung up'", "the gate hung up" in ask(tmp / "c.sock", "gate.who", 1.0, gate=True)[1])
p.close()
p = Peer(tmp / "s.sock", "silent")
t0 = time.monotonic()
ok, why, _ = ask(tmp / "s.sock", "tof.stream", 0.3)
check("must fail: a socket that never answers is dead, 'silent', after the timeout and no longer", not ok and "silent" in why and time.monotonic() - t0 < 2.0, (why, time.monotonic() - t0))
p.close()
p = Peer(tmp / "g.sock", "garbage")
check("must fail: an answer that is not JSON is dead", "not JSON" in ask(tmp / "g.sock", "robot.health", 1.0)[1] and not ask(tmp / "g.sock", "robot.health", 1.0)[0])
p.close()
p = Peer(tmp / "l.sock", "list")
check("must fail: JSON that is not an object is dead: not JSON-RPC", "not JSON-RPC" in ask(tmp / "l.sock", "robot.health", 1.0)[1])
p.close()
ok, why, _ = ask(tmp / "nope.sock", "robot.health", 1.0)
check("must fail: no socket file: 'the forward is not up'; the gate's: 'the gate is not running'", not ok and "no socket file" in why and "the forward is not up" in why
      and "the gate is not running" in ask(tmp / "nope.sock", "gate.who", 1.0, gate=True)[1], why)
(tmp / "plain").write_text("x")
check("must fail: a regular file where a socket should be is dead", "not a socket" in ask(tmp / "plain", "robot.health", 1.0)[1])

shutil.rmtree(tmp, ignore_errors=True)
print()
print("LINKCHECK", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
