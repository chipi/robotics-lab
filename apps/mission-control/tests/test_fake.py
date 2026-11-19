"""The fake robot (RFC-0014 §3.7): it moves a point, answers status, honours STOP and the deadman, drops
offline when told, carries a fake site; and the gate of RFC-0017 in front of it applies the real rules
(RFC-0017 §5 step 2). A fake clock; no sockets, no simulator.
Run: cd apps/mission-control && uv run python tests/test_fake.py"""

import math

from common import Clock, check, finish

from robotgate import Gate, GateError
from mission_control.fake import FakeRobot

clock = Clock()
robot = FakeRobot(clock=clock)


def state():
    return robot("robot.state")


check("it starts at the dock, in the site frame", state()["pose"] == {"x": 0.0, "y": 0.0, "yaw": 0.0, "frame": "site"}, state()["pose"])
check("health says link and battery", robot("robot.health") == {"ok": True, "battery_pct": 100.0, "link": "fake"})

robot("robot.move", {"vx": 0.4, "vy": 0.0, "vyaw": 0.0})
clock.advance(0.4)
check("a move moves the point by speed times time", abs(state()["pose"]["x"] - 0.16) < 0.005, state()["pose"])
check("while moving the mode says so", state()["mode"] == "moving" and state()["velocity"]["vx"] == 0.4)

# the deadman (RFC-0003 §2.3): a command lasts 0.5 s
robot("robot.move", {"vx": 0.4, "vy": 0.0, "vyaw": 0.0})
clock.advance(5.0)
s = state()
check("the deadman stops it 0.5 s after the last command, not at the next call", abs(s["pose"]["x"] - (0.16 + 0.2)) < 0.01, s["pose"])
check("and it reads idle", s["mode"] == "idle" and s["velocity"] == {"vx": 0.0, "vyaw": 0.0})

robot("robot.move", {"vx": 5.0, "vy": 0.0, "vyaw": 9.0})
check("a command above the robot's limits is clamped to them", state()["velocity"] == {"vx": 0.5, "vyaw": 1.5}, state()["velocity"])
robot("robot.stop")
x_stop = state()["pose"]["x"]
clock.advance(1.0)
check("STOP is immediate and the robot stays", state()["pose"]["x"] == x_stop and state()["mode"] == "idle")

robot("robot.move", {"vx": 0.5, "vy": 0.0, "vyaw": 0.0})
for _ in range(100):
    clock.advance(0.1)
    robot("robot.move", {"vx": 0.5, "vy": 0.0, "vyaw": 0.0})
check("the world has walls: it stays inside the bounds", state()["pose"]["x"] <= 4.0 + 1e-9, state()["pose"])
check("driving costs battery", state()["battery_pct"] < 100.0, state()["battery_pct"])
robot("robot.stop")

# turning in place
yaw0 = state()["pose"]["yaw"]
for _ in range(10):
    robot("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 1.0})
    clock.advance(0.1)
check("turning in place changes the heading, not the position", abs(state()["pose"]["yaw"] - yaw0) > 0.5)
robot("robot.stop")

# failures
robot.set_offline(True)
try:
    robot("robot.state")
    check("an offline robot raises", False)
except ConnectionError:
    check("an offline robot raises", True)
robot.set_offline(False)
check("and answers again when it is back", "pose" in state())
robot.inject("contact", True)
check("a fault is in the state's flags", state()["flags"]["contact"] is True)
robot.inject("contact", False)
try:
    robot.inject("gremlins")
    check("an unknown fault raises", False)
except KeyError:
    check("an unknown fault raises", True)
try:
    robot("robot.dance")
    check("an unknown method raises", False)
except ValueError:
    check("an unknown method raises", True)

# the fake site, its camera and its map
fresh = FakeRobot(clock=clock)
check("nothing is seen at the dock", fresh.sight() == [])
fresh.x, fresh.y = 2.6, 1.4
seen = fresh.sight()
check("the camera recognises the fridge within its range", [o["kind"] for o in seen] == ["fridge"] and seen[0]["unique"], seen)
snap = fresh.sighting()
check("the sighting is a camera record: pose, field of view, detections ahead and left of the robot",
      snap["hfov_deg"] == 120.0 and snap["pose"][:2] == [2.6, 1.4] and all("range_m" in d for d in snap["seen"]), snap)
fresh.yaw = math.atan2(1.5 - 1.4, 3.0 - 2.6)
snap = fresh.sighting()
check("facing the fridge it is ahead (x > 0), almost dead ahead", snap["seen"] and snap["seen"][0]["x"] > 0.3 and abs(snap["seen"][0]["y"]) < 0.1, snap)
m = fresh.map()
check("the map has unknown cells, and the fridge's cells are occupied once seen",
      m["kind"] == "occupancy_grid" and -1 in m["data"] and 100 in m["data"] and m["frame"] == "site" and m["width"] * m["height"] == len(m["data"]))
v0 = fresh.map_version
fresh("robot.move", {"vx": 0.5, "vy": 0.0, "vyaw": 0.0})
clock.advance(0.4)
fresh("robot.state")
check("exploring changes the map's version", fresh.map_version > v0)
locked = FakeRobot(clock=clock)
locked.wheels_locked = True
locked("robot.move", {"vx": 0.5, "vy": 0.0, "vyaw": 0.0})
clock.advance(0.4)
check("locked wheels: told to move, it does not", locked("robot.state")["pose"]["x"] == 0.0)

# --- the gate in front of the fake (RFC-0017 §5 step 2) --------------------------------------------
clock2 = Clock()
fake = FakeRobot(clock=clock2)
gate = Gate(fake, clock=clock2, wall=clock2, lease_s=20.0, takeover_names={"operator-laptop"})
a = gate.open("mission-control")
b = gate.open("script")
try:
    gate.handle(a, "robot.move", {"vx": 0.3, "vy": 0, "vyaw": 0})
    check("no lease, no motion", False)
except GateError as exc:
    check("no lease, no motion", exc.code == "no_lease")
gate.handle(a, "gate.acquire")
gate.handle(a, "robot.move", {"vx": 0.3, "vy": 0, "vyaw": 0})
clock2.advance(0.3)
x1 = gate.handle(a, "robot.state")["pose"]["x"]
check("the holder drives the fake through the gate", x1 > 0.05, x1)
try:
    gate.handle(b, "robot.move", {"vx": -0.3, "vy": 0, "vyaw": 0})
    check("a second client's move is refused with who holds it", False)
except GateError as exc:
    check("a second client's move is refused with who holds it", exc.code == "held" and "mission-control" in str(exc))
check("and never reached the fake", fake("robot.state")["velocity"]["vx"] == 0.3)
gate.handle(b, "robot.stop")
check("STOP from anyone stops the fake", fake("robot.state")["velocity"]["vx"] == 0.0 and fake("robot.state")["mode"] == "idle")
try:
    gate.handle(a, "robot.move", {"vx": 0.3, "vy": 0, "vyaw": 0})
    check("a STOP latches: the holder's next move is refused", False)
except GateError as exc:
    check("a STOP latches: the holder's next move is refused", exc.code == "lease_ended" and "stopped_by script" in str(exc))
check("the fake stays stopped", fake("robot.state")["mode"] == "idle")
gate.handle(a, "gate.acquire")
gate.handle(a, "robot.move", {"vx": 0.3, "vy": 0, "vyaw": 0})
clock2.advance(25.0)
gate.tick()
check("a silent holder's lease expires and the fake is stopped and free",
      gate.who()["holder"] is None and fake("robot.state")["mode"] == "idle")
gate.handle(b, "gate.acquire")
gate.close(b)
check("a dropped connection frees it at once", gate.who()["holder"] is None)

finish("test_fake")
