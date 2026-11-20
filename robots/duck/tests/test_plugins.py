"""The four interfaces and the duck's plugins (RFC-0020 §4, step 3; no simulator). Run: cd robots/duck && uv run python tests/test_plugins.py

The profile names the plugins, they are loaded by name and held to their interface; the sensor's mount is instance state (two sensors
mounted differently in one process); the localisation plugin owns the belief, the scale and mapd's account of itself; a robot that
cannot look leaves a spot unseen, not blocked; the looking plugin returns the frames and hands the head back.
"""

import math
import sys

from duck_lab import plugins
from duck_lab.nav.follow import FollowState, Twist
from duck_lab.nav.run import Navigator
from duck_lab.plugins.duck_head import DuckHead
from duck_lab.plugins.duck_walk import DuckWalk
from duck_lab.plugins.interfaces import Localisation, Locomotion, Looking, RangeSensing
from duck_lab.plugins.mapd import Mapd
from duck_lab.plugins.tof8x8 import Tof8x8
from duck_lab.profile import load
from runfile.profile import Profile

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


P = load("sim")
REAL = load("real")

# ---- the profile names them, they are loaded by name ----------------------------------------------------------------------
loaded = plugins.load(P)
check("the profile's four interfaces each get a plugin", set(loaded) == {"locomotion", "range_sensing", "localisation", "looking"}, set(loaded))
check("each is the interface it is named for (a runtime-checkable Protocol)",
      isinstance(loaded["locomotion"], Locomotion) and isinstance(loaded["range_sensing"], RangeSensing)
      and isinstance(loaded["localisation"], Localisation) and isinstance(loaded["looking"], Looking))
check("and the class named in the profile: name@version",
      {i: f"{p.name}@{p.version}" for i, p in loaded.items()} == P.plugins.data, {i: f"{p.name}@{p.version}" for i, p in loaded.items()})
check("the duck's classes are those", (type(loaded["locomotion"]), type(loaded["range_sensing"]), type(loaded["localisation"]),
                                     type(loaded["looking"])) == (DuckWalk, Tof8x8, Mapd, DuckHead))
other = Profile({**P.data, "plugins": {**P.data["plugins"], "locomotion": "duck-walk@2"}}, "sim")
try:
    plugins.load(other)
    check("a version this package does not have is refused", False)
except LookupError as exc:
    check("a version this package does not have is refused, naming it and what there is", "duck-walk@2" in str(exc) and "duck-walk@1" in str(exc), str(exc))
swapped = Profile({**P.data, "plugins": {**P.data["plugins"], "locomotion": "tof8x8@1"}}, "sim")
try:
    plugins.load(swapped)
    check("a plugin named for the wrong interface is refused", False)
except TypeError as exc:
    check("a plugin named for the wrong interface is refused, saying which", "locomotion" in str(exc) and "Locomotion" in str(exc), str(exc))
check("two loads are two sets of plugins: no state is shared", plugins.load(P)["locomotion"] is not loaded["locomotion"])

# ---- locomotion ----------------------------------------------------------------------------------------------------------------


class Robot:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        return {}


robot = Robot()
walk = DuckWalk(P)
walk.bind(robot)
walk.command(0.3, 0.1)
walk.stop()
check("command sends robot.move with the speed and the turn, stop sends zeros",
      robot.calls == [("robot.move", {"vx": 0.3, "vy": 0.0, "vyaw": 0.1}), ("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})], robot.calls)
check("the creep a pivot is sent with is the profile's, per environment: the simulator's steps back, the real duck's stands",
      (DuckWalk(P).pivot_vx, DuckWalk(REAL).pivot_vx) == (-0.06, 0.0))
st = FollowState()
kick = DuckWalk(P, pivot_vx=0.0).drive(math.radians(120), 0.0, 10.0, st, near=False, pivot_ok=True, close=False)
check("drive: 120 degrees off turns on the spot with the kick (1.2 rad/s, standing still)", st.turning and kick == Twist(0.0, 1.2), kick)
st = FollowState()
arc = DuckWalk(P).drive(math.radians(120), 0.0, 10.0, st, near=False, pivot_ok=False, close=False)
check("drive: no room to pivot is an arc at the slowest walk", st.turning and arc == Twist(0.2, 1.0), arc)
check("the gates are the profile's: a 0.17 m room turns on the spot, 0.16 does not; a drop at 0.29 m forbids it, 0.31 m allows it",
      walk.can_pivot(0.171, (0.0, 0.0), [], []) and not walk.can_pivot(0.16, (0.0, 0.0), [], [])
      and not walk.can_pivot(0.3, (0.0, 0.0), [(0.29, 0.0)], []) and walk.can_pivot(0.3, (0.0, 0.0), [(0.31, 0.0)], []))
two = DuckWalk(P)
two.tight_pivot_ok(0.2, (1.0, 1.0), [], [], 10.0)
check("one tight pivot per spot is that plugin's own state: a second plugin has not seen the spot",
      not two.tight_pivot_ok(0.2, (1.0, 1.0), [], [], 14.0) and DuckWalk(P).tight_pivot_ok(0.2, (1.0, 1.0), [], [], 14.0))

# ---- range sensing: the mount is instance state ---------------------------------------------------------------------------------
state = {"t_ns": 1, "odom": {"position": [0.0, 0.0, 0.116], "yaw": 0.0}, "imu": {"quat": [1.0, 0.0, 0.0, 0.0], "gyro": [0.0, 0.0, 0.0]},
         "frames": {"tof": {"pos": [0.08, 0.0, 0.11], "quat": [math.cos(0.1), 0.0, math.sin(0.1), 0.0]}}}
frame = {"rows": 8, "cols": 8, "distance_mm": [400 + 5 * i for i in range(64)], "status": [5] * 64}
sim_sensor, real_sensor = Tof8x8(P), Tof8x8(REAL)
a, b = sim_sensor.depth_points(frame, state), real_sensor.depth_points(frame, state)
check("two sensors mounted differently (the simulator's 2.5 deg radial, the real duck's 3 deg axial) read the same frame differently, "
      "side by side in one process", a != b and len(a) == len(b) == 64)
check("... and each keeps its own mount: nothing module-wide changed",
      sim_sensor.depth_points(frame, state) == a and real_sensor.depth_points(frame, state) == b)
try:
    Tof8x8(P, mount={"pitch_offset_deg": 0.0, "range_kind": "slant"})
    check("a range kind that is neither axial nor radial is refused", False)
except ValueError:
    check("a range kind that is neither axial nor radial is refused", True)
check("nearest_mm is a method, None before any frame", sim_sensor.nearest_mm() is None)
perception = sim_sensor.derive(frame, state, 5.0, (0.0, 0.0, 0.0))
check("derive: the frame as the navigator makes of it, with the sensor that derived it", perception.ok and perception.sensor is sim_sensor
      and len(perception.points) == 64 and perception.payload()["pair_dt_ms"] == 5.0)


# ---- localisation: the belief, the scale, mapd's account ------------------------------------------------------------------------
class Mapd_RPC:
    def __init__(self):
        self.status = {"state": {"pose": {"x": 1.0, "y": 2.0, "yaw": 0.5}, "t_ns": 1_000_000_000, "collecting": False}, "loops": 0,
                       "relocalizations": 0, "island_keyframes": 0}
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "map.status":
            return self.status
        if method == "map.grid":
            return {"res_m": 0.05, "origin": [1.0, 2.0], "width": 2, "height": 1, "cells": ".."}
        raise AssertionError(method)


mp = Mapd(P)
rpc = Mapd_RPC()
mp.bind(rpc)
rows = []
record = lambda **kw: rows.append(kw)          # noqa: E731
check("no pose before the first fix; mapd maps only at stops, so the navigator stops to let it",
      mp.pose() is None and mp.needs_stationary() is True)
mp.on_odom(1_000_000_000, (1.0, 2.0, 0.5))
check("a fix is applied to the belief (scaled by the profile's 0.91 like the odometry), and the pose is there",
      mp.fix(record) is True and mp.pose() is not None and abs(mp.pose()[0] - 0.91) < 1e-9 and abs(mp.pose()[1] - 1.82) < 1e-9, mp.pose())
check("... and mapd's first quiet account says nothing", rows == [], rows)
g = mp.grid()
check("the grid is read at 0.05 m and scaled like the odometry (resolution and origin by 0.91)",
      rpc.calls[-1] == ("map.grid", {"res_m": 0.05}) and abs(g["res_m"] - 0.05 * 0.91) < 1e-12 and abs(g["origin"][0] - 0.91) < 1e-12, g)
check("the real duck's localisation applies no scale", Mapd(REAL).scale == 1.0 and mp.scale == 0.91)
rpc.status = {"state": {"pose": {"x": 5.0, "y": 2.0, "yaw": 0.5}, "t_ns": 1_000_000_000, "lost": "bumped"}, "loops": 0,
              "relocalizations": 0, "island_keyframes": 0}
mp.fix(record)
check("mapd lost: said once, with what changed and where the belief was", len(rows) >= 1 and rows[0]["event"] == "mapd_status"
      and rows[0]["lost"] == "bumped" and rows[0]["changed"] == ["lost"], rows)
check("a fix that would jump the belief 4 m is held by the gate (the belief stays)", mp.belief.last_fix["status"] == "held"
      and abs(mp.pose()[0] - 0.91) < 1e-9, mp.belief.last_fix)
check("the fix event says so: held, with its source", any(r.get("event") == "fix" and r["status"] == "held" and r["mapd"] is not None for r in rows), rows)
stands = []
rpc2 = Mapd_RPC()
rpc2.status = {"state": {"collecting": False}}
m2 = Mapd(P)
m2.bind(rpc2)
check("settle with mapd never collecting: it gives up after the timeout and says no (timeout 0.2 s here)",
      m2.settle(lambda: stands.append(1), 0.2, 0.05) is False and len(stands) >= 3, len(stands))
stands.clear()
rpc2.status = {"state": {"collecting": True}}
import time as _time  # noqa: E402
_real_sleep = _time.sleep
t_start = _time.monotonic()
check("... and when it is collecting, true (after 2 s more)", m2.settle(lambda: stands.append(1), 5.0, 0.2) is True
      and 1.9 < _time.monotonic() - t_start < 3.0, _time.monotonic() - t_start)

ms = Mapd(P)
check("the odometry scale by speed: the table's at its speeds, between them on a line, held beyond them",
      [round(ms.scale_at(v), 4) for v in (0.0, 0.2, 0.25, 0.3, 0.4, 0.5)] == [0.849, 0.849, 0.88, 0.911, 0.93, 0.93],
      [ms.scale_at(v) for v in (0.0, 0.2, 0.25, 0.3, 0.4, 0.5)])
rpc3 = Mapd_RPC()
rpc3.status = {"state": {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "t_ns": 1_000_000_000}, "loops": 0, "relocalizations": 0,
               "island_keyframes": 0}
ms.bind(rpc3)
ms.on_odom(1_000_000_000, (0.0, 0.0, 0.0))
ms.commanded(0.2)
ms.on_odom(2_000_000_000, (1.0, 0.0, 0.0))
ms.commanded(0.3)
ms.on_odom(3_000_000_000, (2.0, 0.0, 0.0))
ms.commanded(0.2, 0.6)
ms.on_odom(4_000_000_000, (3.0, 0.0, 0.0))
ms.fix(lambda **kw: None)
check("odometry steps are scaled by the speed commanded while they were walked (1 m at 0.2, 1 m at 0.3: 0.849 + 0.911)",
      abs(ms.to_map((2.0, 0.0, 0.0))[0] - 1.760) < 1e-9 and abs(ms.to_map((1.0, 0.0, 0.0))[0] - 0.849) < 1e-9,
      (ms.to_map((2.0, 0.0, 0.0)), ms.to_map((1.0, 0.0, 0.0))))
check("... an arc (a turn over straight_rad_s) is corrected by `scale`, the one measured in navigation (0.91)",
      abs(ms.pose()[0] - (0.849 + 0.911 + 0.91)) < 1e-9, ms.pose())
mr = Mapd(REAL)
mr.on_odom(1_000_000_000, (0.0, 0.0, 0.0))
mr.commanded(0.2)
mr.on_odom(2_000_000_000, (1.0, 0.0, 0.0))
mr.bind(rpc3)
mr.fix(lambda **kw: None)
check("a profile without a table keeps its one scale at every speed (the real duck's 1.0)", abs(mr.pose()[0] - 1.0) < 1e-9, mr.pose())

# ---- the walk's steering deadband (off in the profile: K1) ----------------------------------------------------------------------
import copy  # noqa: E402
from duck_lab.nav.follow import FollowState  # noqa: E402

check("the profile has no deadband: steering is proportional, as it was", DuckWalk(P).deadband == 0.0)
data = copy.deepcopy(P.data)
data["locomotion"]["steer"] = {"deadband_rad": 0.3}
dw = DuckWalk(Profile(data, "sim"))
st = FollowState()


def vyaw_at(err, close=False):
    return dw.drive(err, 0.0, 0.0, st, False, True, close).vyaw


check("with a deadband: no turn inside the band, a correction once past it, kept until inside half of it",
      vyaw_at(0.2) == 0.0 and vyaw_at(0.35) > 0 and vyaw_at(0.2) > 0 and vyaw_at(0.12) == 0.0, st.steering)
check("... and never in a squeeze (an obstacle within slow_clearance_m): proportional there",
      vyaw_at(0.2, close=True) == dw.loco.yaw_gain * 0.2 and st.steering is False)

# ---- looking --------------------------------------------------------------------------------------------------------------------


class FailingRobot:
    def __init__(self, exc):
        self.exc = exc

    def call(self, method, params=None):
        raise self.exc


head = DuckHead(P)
head.bind(FailingRobot(RuntimeError("no head")))
check("robot.look failing is a failed look, not an error", head.look_at((1.0, 0.0), (0.0, 0.0, 0.0), lambda: None, lambda: None)
      == {"failed": "no head"})
check("the duck can look", head.capable is True and head.settled() is False)

# a robot that cannot look: the navigator leaves the spot unseen, not blocked
nv = Navigator.__new__(Navigator)
nv.configure(P)
rows2 = []
nv.record = lambda **kw: rows2.append(kw)


class CannotLook:
    name, version, capable = "stub", 1, False

    def look_at(self, *a, **k):
        raise AssertionError("a robot that cannot look is not asked to")


nv.looking = CannotLook()
nv.glanced, nv.blocked = [], []
out = nv.glance_at((1.0, 0.0), (0.0, 0.0, 0.0))
check("a robot that cannot look: the glance is 'unseen', the spot is not blocked, no look was asked of it",
      out == {"status": "unseen"} and nv.blocked == [] and nv.glanced == [], out)
check("... and it says so", rows2 and rows2[-1]["event"] == "glance" and "cannot look" in rows2[-1]["decision"]["reason"], rows2)

print("PLUGINS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
