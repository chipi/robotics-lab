"""The navigator's log has a pose row for every command it sends, not only while following a path:
explore12 logged none during surveys, survey turns and the waits after a stop, so 0-27 s, two
3-second gaps and the last 3.7 s before "trapped" had events but no poses. No simulator.
Run: cd robots/duck && uv run python tests/test_record.py"""

import io
import json
import sys
import time

from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator
from duck_lab.plugins.duck_walk import DuckWalk
from duck_lab.profile import load

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

    def memory_delta(self):
        return None

    def commanded(self, vx, vyaw=0.0):
        pass


class Latest:
    latest = None


def navigator(pose):
    """A Navigator with its sockets replaced: commands are collected, the log is in memory."""
    nav = Navigator.__new__(Navigator)
    nav.robot, nav.loc, nav.state, nav.body = Calls(), Pose(pose), Latest(), None
    nav.localisation = nav.loc
    nav.locomotion = DuckWalk(load("sim"))
    nav.locomotion.bind(nav.robot)
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

# The measured joint angles (ADR-0016): robotd's 15, in its order, become the run's joint_* signals; a state with another
# count says nothing about them (a joint guessed into the wrong name is worse than none).
from duck_lab.nav.runlog import JOINTS, SIGNALS  # noqa: E402

nav = Navigator.__new__(Navigator)
nav._fv, nav.range, nav.sense = None, None, {}
angles = [round(0.01 * i, 2) for i in range(15)]
v = nav._signal_values({"joints": angles})
check("robotd's 15 measured joint angles become joint_<name> signals, in its order",
      [v.get(f"joint_{n}") for n in JOINTS] == angles and v["joint_left_hip_yaw"] == 0.0 and v["joint_right_ankle"] == 0.14, v)
check("a state with another number of joints gives no joint signals", not any(k.startswith("joint_") for k in nav._signal_values({"joints": angles[:14]})))
check("the run declares the 15 joint signals, in radians", [s["name"] for s in SIGNALS if s["name"].startswith("joint_")] == [f"joint_{n}" for n in JOINTS]
      and all(s.get("unit") == "rad" for s in SIGNALS if s["name"].startswith("joint_")))

print("RECORD", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
