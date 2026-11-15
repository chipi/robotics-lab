"""The navigator's log has a pose row for every command it sends, not only while following a path:
explore12 logged none during surveys, survey turns and the waits after a stop, so 0-27 s, two
3-second gaps and the last 3.7 s before "trapped" had events but no poses. No simulator.
Run: cd duck && uv run python tests/test_record.py"""

import io
import json
import sys
import time

from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class Calls:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        return {}


class Pose:
    def __init__(self, pose):
        self.p = pose

    def pose(self):
        return self.p


class Latest:
    latest = None


def navigator(pose):
    """A Navigator with its sockets replaced: commands are collected, the log is in memory."""
    nav = Navigator.__new__(Navigator)
    nav.robot, nav.loc, nav.state, nav.body = Calls(), Pose(pose), Latest(), None
    nav._log, nav._t0, nav._depth = io.StringIO(), time.monotonic(), None
    return nav


def rows(nav):
    return [json.loads(line) for line in nav._log.getvalue().splitlines()]


nav = navigator((1.0, 2.0, 0.5))
nav.move(Twist())                       # what survey() sends every tick
nav.move(Twist(0.0, 0.8))               # what a survey turn sends
r = rows(nav)
check("a command outside path following still logs a pose row", len(r) == 2 and all("pose" in x for x in r), r)
check("the row carries the pose and the command", r and r[-1]["pose"] == [1.0, 2.0, 0.5] and r[-1]["vyaw"] == 0.8, r[-1:])
check("the command still reaches the robot", nav.robot.calls[-1] == ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.8}))

blind = navigator(None)
blind.move(Twist())
check("no pose yet (before the first fix): the command is sent, no pose row is invented",
      rows(blind) == [] and len(blind.robot.calls) == 1, rows(blind))

follow = navigator((0.0, 0.0, 0.0))
follow.move(Twist(0.2, 0.0), nearest_mm=400, turning=False)
r = rows(follow)
check("path following adds its own fields to the same row, one row per command",
      len(r) == 1 and r[0]["nearest_mm"] == 400 and r[0]["turning"] is False and r[0]["vx"] == 0.2, r)

print("RECORD", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
