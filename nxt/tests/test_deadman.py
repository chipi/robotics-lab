"""robotd-lite's protocol and the simulated program's behaviour (no hardware).
Run: make test-unit, or python nxt/tests/test_deadman.py from the repo."""

import sys
import time

from nxt_lab import deadman
from nxt_lab.config import Config
from nxt_lab.robot import deadman_ports_problem, deadman_powers

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


# The fixed-width commands robotd.nxc parses: D seq(4) left+100(3) right+100(3) fwd(1).
check("drive encodes", deadman.drive(7, -100, 100, False) == b"D00070002000", deadman.drive(7, -100, 100, False))
check("drive is 12 bytes", len(deadman.drive(12345, 50, 50, True)) == 12)
check("seq wraps at 10000", deadman.drive(10003, 0, 0, False)[:5] == b"D0003")
check("stop encodes", deadman.stop(3) == b"S0003")
check("query encodes", deadman.query(42) == b"Q0042")
s = deadman.parse_state(b"12,50,-50,34,3,9000\x00")
check("state parses", (s["seq"], s["left"], s["right"], s["dist"], s["ms"]) == (12, 50, -50, 34, 9000), s)
check("state flags", s["deadman_stop"] and s["obstacle_stop"] and not s["bad_command"], s)

check("ports C/B are what robotd drives", deadman_ports_problem(Config()) is None)
check("other ports are refused", "drives left C" in (deadman_ports_problem(Config(left="A", right="B", shooter="C")) or ""))
check("inversion applied, forward from the robot's view",
      deadman_powers(Config(invert_left=True), 40, 40) == (-40, 40, True), deadman_powers(Config(invert_left=True), 40, 40))
check("backing up is not forward", deadman_powers(Config(), -30, -30)[2] is False)
check("powers clamped", deadman_powers(Config(), 500, -500)[:2] == (100, -100))

b = deadman.FakeDeadman()
b.dist = 80
b.receive(deadman.drive(1, 50, 50, True))
check("drive moves", (b.left, b.right) == (50, 50) and deadman.parse_state(b.reply)["seq"] == 1)
time.sleep(0.3)
b.receive(deadman.query(2))
check("a query answers without stopping", (b.left, b.right) == (50, 50) and not deadman.parse_state(b.reply)["deadman_stop"])
time.sleep(0.35)
b.tick()
check("deadman: no drive for 0.5 s stops it, queries do not feed it", (b.left, b.right) == (0, 0) and b.flags & deadman.FLAG_DEADMAN)
b.receive(deadman.drive(3, 40, 40, True))
check("a new drive clears the deadman flag", (b.left, b.right) == (40, 40) and b.flags == 0)
b.dist = 10
b.tick()
check("obstacle closer than 15 cm stops forward motion", (b.left, b.right) == (0, 0) and b.flags & deadman.FLAG_OBSTACLE)
b.receive(deadman.drive(4, -40, -40, False))
check("backing away from an obstacle is allowed", (b.left, b.right) == (-40, -40))
b.receive(deadman.stop(5))
check("stop", (b.left, b.right) == (0, 0) and b.flags == 0)
b.receive(b"X0006")
check("unknown command stops and is flagged", (b.left, b.right) == (0, 0) and deadman.parse_state(b.reply)["bad_command"])

# The real robot's exchange with a stub brick: a late answer to an earlier command is dropped.
import threading  # noqa: E402

import nxt.error  # noqa: E402

from nxt_lab.robot import NxtRobot  # noqa: E402


class StubBrick:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def message_write(self, inbox, message):
        self.sent.append((inbox, message))

    def message_read(self, remote_inbox, local_inbox, remove):
        if not self.replies:
            raise nxt.error.EmptyMailboxError()
        return 0, self.replies.pop(0)


robot = object.__new__(NxtRobot)
robot._lock = threading.RLock()
robot._brick = StubBrick([b"6,0,0,40,0,100\x00", b"7,20,20,40,0,120\x00"])
state = robot._exchange(deadman.drive(7, 20, 20, True))
check("exchange writes to mailbox 1", robot._brick.sent == [(0, b"D00071201201")], robot._brick.sent)
check("exchange drops a late answer and returns its own", state and state["seq"] == 7, state)
robot._brick = StubBrick([])
check("no answer -> None, not an error", robot._exchange(deadman.query(8)) is None)

print("DEADMAN", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
