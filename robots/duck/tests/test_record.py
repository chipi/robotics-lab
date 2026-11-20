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

# Robotd's odometry as it came (K41), on every tick row, recorded only: what the navigator sends and what the row says otherwise are
# the same with the odometry as without.
STATE = {"t_ns": 7_000_000_000, "odom": {"position": [3.04, -1.25, 0.0], "yaw": 1.0}}
with_odom, without = navigator((1.0, 2.0, 0.5)), navigator((1.0, 2.0, 0.5))
with_odom.state.latest = STATE
for n in (with_odom, without):
    n.move(Twist(0.2, 0.0), nearest_mm=400)
    n.move(Twist(0.0, 0.8))
    n.record(event="reached", goal=1)
a, b = rows(with_odom), rows(without)
strip = lambda r: {k: v for k, v in r.items() if k not in ("odom_raw", "odom_raw_t_ns")}  # noqa: E731
check("every tick row carries robotd's odometry pose and its time, unscaled", [x["odom_raw"] for x in a[:2]] == [[3.04, -1.25, 1.0]] * 2
      and all(x["odom_raw_t_ns"] == 7_000_000_000 for x in a[:2]), a[:2])
check("... an event row does not", "odom_raw" not in a[2] and a[2]["event"] == "reached", a[2])
check("... a run without a state yet, or a state with no odometry, has none, and no row is lost",
      not any("odom_raw" in x for x in b) and len(a) == len(b) == 3)
check("the same commands reach the robot with and without it", with_odom.robot.calls == without.robot.calls and len(without.robot.calls) == 2,
      (with_odom.robot.calls, without.robot.calls))
check("... and the rows are the same but for those two fields (the pose, the command, the extras)",
      [strip(x) | {"t": 0, "wall_ns": 0} for x in a] == [x | {"t": 0, "wall_ns": 0} for x in b], (a, b))
# The host's wall clock on every row (RFC-0021 step 2): how the runner, another process, pairs its truth samples with the rows.
import time  # noqa: E402
check("every row, tick and event, carries the host's wall clock in ns, in order",
      all(isinstance(x["wall_ns"], int) and abs(x["wall_ns"] - time.time_ns()) < 60e9 for x in a)
      and [x["wall_ns"] for x in a] == sorted(x["wall_ns"] for x in a), [x.get("wall_ns") for x in a])
from pathlib import Path  # noqa: E402
from runfile.adapters.duck import DuckLog  # noqa: E402

log = DuckLog(Path("/nonexistent/duck-run"), "apartment")     # what the run recorder turns a row into
log.start, log.header, log.fresh = None, [], True
tick = next(p for _, k, p in log.feed_row(a[0]) if k == "tick")
check("the recorder keeps it in the tick's raw, the belief and the command where they were",
      tick["raw"]["odom_raw"] == [3.04, -1.25, 1.0] and tick["raw"]["odom_raw_t_ns"] == 7_000_000_000 and tick["belief"] == [1.0, 2.0, 0.5]
      and tick["cmd"] == [0.2, 0.0], tick)
check("... and the wall clock in the tick's raw too (unknown fields are kept: the runner reads it back)",
      tick["raw"].get("wall_ns") == a[0]["wall_ns"], tick["raw"])
partial = navigator((1.0, 2.0, 0.5))
partial.state.latest = {"t_ns": 1, "imu": {"quat": [1, 0, 0, 0], "gyro": [0, 0, 0]}}
partial.move(Twist())
check("a state with only an IMU adds no odometry", "odom_raw" not in rows(partial)[0] and len(rows(partial)) == 1)

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
