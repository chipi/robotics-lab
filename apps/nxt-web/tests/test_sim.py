"""SimRobot and its world (nxt_lab.world): no hardware, no sleeping except in the one HTTP smoke at the end.
Run: make test-unit, or python apps/nxt-web/tests/test_sim.py from the repo.

The robot and its brick program run on an injected clock, so a 10 s drive takes milliseconds and every number below is
exact. The world's numbers are the model's assumptions (WorldParams), not measurements of the brick."""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from runfile.adapters import nxt as nxt_run

from nxt_lab import deadman
from nxt_lab.config import Config
from nxt_lab.robot import FakeRobot, SimRobot
from nxt_lab.world import Box, World, WorldParams

failures = []
REPO = Path(__file__).resolve().parents[3]
NXT_DIR = Path(__file__).resolve().parents[1]
APARTMENT = REPO / "scenes" / "apartment" / "scene.json"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def run(self, robot, seconds, left=None, right=None, every=0.1):
        """Let `seconds` pass in `every`-second slices, re-sending the drive command each slice when one is given (as the
        page does every 200 ms); None sends nothing."""
        for _ in range(round(seconds / every)):
            if left is not None:
                robot.drive(left, right)
            self.t += every
            robot._advance()


def wall_world(distance_m, **params):
    """A single wall whose face is at x = distance_m, the robot at the origin facing it."""
    wall = Box("wall", distance_m + 0.05, 0.0, 0.0, 1.0, 0.05, 5.0)
    return World([wall], None, WorldParams(**params), (0.0, 0.0, 0.0))


def sim(world, clock, **config):
    robot = SimRobot(Config(**config), world=world, clock=clock)
    robot.set_deadman(config.get("drive_mode", "deadman") == "deadman")
    return robot


# ---- drive into a wall and stop (direct mode: only the world holds the robot) -------------------------------------
clock = Clock()
world = wall_world(1.0)
robot = sim(world, clock, drive_mode="direct")
clock.run(robot, 10.0, 100, 100)
r = world.params.body_radius_m
check("direct drive into a wall stops at its face, body radius off", abs(world.x - (1.0 - r)) < 1e-6 and world.contact, world.pose())
check("it did not penetrate", world.x <= 1.0 - r + 1e-9)
check("the wall does not move the heading or the sideways position", abs(world.y) < 1e-9 and abs(world.yaw) < 1e-9)
tachos = robot.read_tachos()
check("tachos kept counting against the wall: the belief is wrong, as on a real wall",
      tachos["C"] > 9 * 100 * 9, tachos)
clock.run(robot, 1.0, -100, -100)
check("backing out of contact works", world.x < 1.0 - r - 0.2 and not world.contact, world.pose())

# ---- the ultrasonic reads the wall's distance ---------------------------------------------------------------------
for metres in (0.4, 1.2345, 2.0):
    w = wall_world(metres + 0.10)   # the sensor sits 0.10 m ahead of the body's centre
    check(f"ultrasonic reads {metres} m within 1 cm", abs(w.range_cm() - metres * 100) <= 1, w.range_cm())
check("nothing in range reads 255", wall_world(5.0).range_cm() == 255)
check("the range is an integer in whole centimetres", isinstance(wall_world(1.2345).range_cm(), int))
tilted = Box("wall", 1.0, 0.0, 0.0, 1.0, 0.05, 5.0, yaw=math.radians(20))
centre = World([tilted], None, WorldParams(us_rays=1), (0.0, 0.0, 0.0)).range_cm()
cone = World([tilted], None, WorldParams(us_cone_deg=20.0), (0.0, 0.0, 0.0)).range_cm()
check("a wall at 20 degrees: the centre ray reads its face (by hand 84.66 cm), the cone reads the nearest echo, which is nearer", centre == 85 and cone < centre, (centre, cone))
low = World([Box("shin_high", 0.5, 0.0, 0.2, 1.0, 0.05, 5.0)], None, WorldParams(), (0.0, 0.0, 0.0))
check("a box above the sensor's height is not an echo and not an obstacle", low.range_cm() == 255 and low._free(0.4, 0.0))
beyond = World([Box("far", 3.5, 0.0, 0.0, 1.0, 0.05, 5.0)], None, WorldParams(), (0.0, 0.0, 0.0))
check("max range is a parameter: 3.35 m of wall reads 255 at 255 cm", beyond.range_cm() == 255)
beyond = World([Box("far", 3.5, 0.0, 0.0, 1.0, 0.05, 5.0)], None, WorldParams(us_max_cm=400), (0.0, 0.0, 0.0))
check("and 335 cm at max 400", beyond.range_cm() == 335, beyond.range_cm())

apartment = World.from_scene(APARTMENT, start=(0.0, 2.0, math.pi / 2))
check("the apartment: the north wall's face at y = 2.94 reads 84 cm from (0, 2) facing north", abs(apartment.range_cm() - 84) <= 1, apartment.range_cm())
check("the apartment scene's checksum and id are kept", apartment.scene_id == "apartment" and len(apartment.scene_sha256) == 64)
check("the stairwell's steps (below the floor) are not obstacles",
      World.from_scene(APARTMENT, start=(-0.2, -1.0, 0.0)).pose()[:2] == (-0.2, -1.0))
try:
    World.from_scene(APARTMENT, start=(-2.5, 2.74, 0.0))
    check("a start inside a box is refused", False)
except ValueError as exc:
    check("a start inside a box is refused", "inside a box" in str(exc), exc)

# ---- turning in place ----------------------------------------------------------------------------------------------
clock = Clock()
world = wall_world(50.0)
robot = sim(world, clock, drive_mode="direct")
clock.run(robot, 1.0, -50, 50)
check("turning in place: no translation", abs(world.x) < 1e-9 and abs(world.y) < 1e-9, world.pose())
check("one second at -50/+50 is half the full turn rate times the slip",
      abs(world.yaw - 0.5 * 1.5 * 0.9) < 1e-6, world.yaw)
clock.run(robot, 1.0, 50, -50)
check("and back again", abs(world.yaw) < 1e-6, world.yaw)
w = World([], None, WorldParams(turn_slip=1.0), (0.0, 0.0, 0.0))
w.step(100, -100, 1.0)
check("full right turn at slip 1 is turn_rad_s, clockwise", abs(w.yaw + 1.5) < 1e-6, w.yaw)
w = World([], None, WorldParams(), (0.0, 0.0, 0.0))
for _ in range(50):
    w.step(100, 100, 0.02)
check("straight at 100 is speed_m_s", abs(w.x - 0.3) < 1e-9 and abs(w.y) < 1e-9, w.pose())

# ---- truth is not odometry ----------------------------------------------------------------------------------------
clock = Clock()
world = wall_world(50.0)
cfg = Config(drive_mode="direct", odom_sprocket_diameter_m=0.3 / 900 * 360 / math.pi, odom_track_width_m=2 * 0.3 / 1.5)
robot = sim(world, clock, drive_mode="direct", odom_sprocket_diameter_m=cfg.odom_sprocket_diameter_m, odom_track_width_m=cfg.odom_track_width_m)
odom = nxt_run.Odometry(nxt_run.geometry_from(cfg.to_dict(), "test"))
odom.step(robot.read_tachos())
for _ in range(20):
    clock.run(robot, 0.1, 40, -40)
    odom.step(robot.read_tachos())
truth_yaw = world.yaw
belief_yaw = -0.4 * 1.5 * 2.0       # 40 / -40 for 2 s is 0.4 of the full rate
check("with geometry matching the speeds, the belief turns by the commanded angle", abs(odom.pose()[2] - belief_yaw) < 0.02, odom.pose())
check("truth turned slip times what odometry believes, so the two differ", abs(truth_yaw - 0.9 * belief_yaw) < 1e-3 and abs(truth_yaw - odom.pose()[2]) > 0.05, (truth_yaw, odom.pose()))
t_ns, pose = robot.truth()
check("truth() is (wall_ns, (x, y, yaw)) and is the model's pose", isinstance(t_ns, int) and pose == world.pose(), (t_ns, pose))

# ---- the obstacle stop (deadman mode: robotd-lite's 15 cm rule on the real simulated distance) --------------------
clock = Clock()
world = wall_world(1.0)
robot = sim(world, clock)
clock.run(robot, 10.0, 100, 100)
state = robot.deadman_query()
stop_x = 1.0 - 0.15 - world.params.us_forward_m
check("the obstacle stop fires at 15 cm from the wall, before any contact",
      state["obstacle_stop"] and not world.contact and stop_x - 0.01 < world.x <= stop_x + 0.01 and world.x < 1.0 - r, (state, world.pose()))
check("it read the real distance", 14 <= state["dist"] <= 15, state)
check("the server's own command is untouched, as on the brick", (robot.left, robot.right) == (100, 100))
clock.run(robot, 1.0, -40, -40)
check("backing away from the obstacle is allowed", world.x < stop_x - 0.1, world.pose())
check("and the flag clears with the new command", not robot.deadman_query()["obstacle_stop"])
sensors = robot.read_sensors()
check("read_sensors gives the simulated distance on the ultrasonic's port", sensors["4"]["value"] == world.range_cm() or abs(sensors["4"]["value"] - world.range_cm()) <= 1, sensors)
check("colour is not modelled: it reads empty, not a made-up value", sensors["3"] == {"value": None, "label": None}, sensors)

# ---- STOP and the deadman still hold --------------------------------------------------------------------------------
clock = Clock()
world = wall_world(50.0)
robot = sim(world, clock)
clock.run(robot, 1.0, 100, 100)
robot.stop()
x_stopped = world.x
clock.run(robot, 2.0)
check("STOP holds: the robot does not move afterwards", world.x == x_stopped and (robot.left, robot.right) == (0, 0), world.pose())

clock = Clock()
world = wall_world(50.0)
robot = sim(world, clock)
robot.drive(100, 100)
clock.run(robot, 3.0)
state = robot.deadman_query()
check("the deadman stops the tracks 0.5 s after the last command", state["deadman_stop"] and (state["left"], state["right"]) == (0, 0), state)
check("and the robot travelled only those 0.5 s", abs(world.x - 0.5 * 0.3) < 0.02, world.pose())
robot.drive(100, 100)
clock.run(robot, 0.2)
check("a new command moves it again", world.x > 0.15 + 0.03, world.pose())

# direct mode has no brick program: the server's own watchdog is what stops it (web.py), and the world holds the line at walls
clock = Clock()
robot = sim(wall_world(50.0), clock, drive_mode="direct")
robot.drive(60, 60)
robot.stop()
clock.run(robot, 1.0)
check("direct mode: stop is stop", robot.world.x == 0.0 or abs(robot.world.x) < 1e-9, robot.world.pose())

# ---- the same interface as FakeRobot -------------------------------------------------------------------------------
fake_api = {n for n in dir(FakeRobot) if not n.startswith("__")}
check("SimRobot has everything FakeRobot has", fake_api <= {n for n in dir(SimRobot)}, fake_api - set(dir(SimRobot)))
check("it is a fake as far as the web layer is concerned and names its link", SimRobot.fake and SimRobot.link == "sim")

# inverted tracks: the commanded forward is still forward in the world, and the tachos count the way the motors turn
clock = Clock()
world = wall_world(50.0)
robot = sim(world, clock, invert_left=True, invert_right=True)
clock.run(robot, 1.0, 100, 100)
check("inverted ports: forward is forward", abs(world.x - 0.3) < 0.02, world.pose())
check("and the tachos run backwards", robot.read_tachos()["C"] < -800, robot.read_tachos())

# reset: back to the start, tachos zero, motors stopped
robot.reset_world()
check("reset_world: start pose, tachos zero, motors stopped", world.pose() == (0.0, 0.0, 0.0) and robot.read_tachos()["C"] == 0 and (robot.left, robot.right) == (0, 0))

# ---- parameters ----------------------------------------------------------------------------------------------------
try:
    WorldParams.from_dict({"speed_m_s": 0.3, "warp": 9})
    check("an unknown parameter is refused", False)
except ValueError as exc:
    check("an unknown parameter is refused", "warp" in str(exc), exc)
try:
    WorldParams(turn_slip=1.5).validate()
    check("a slip above 1 is refused", False)
except ValueError:
    check("a slip above 1 is refused", True)
fast = World([], None, WorldParams.from_dict({"speed_m_s": 0.6}), (0.0, 0.0, 0.0))
fast.step(100, 100, 1.0)
check("the speed is a parameter, not a constant in the code", abs(fast.x - 0.6) < 1e-9, fast.pose())


# ---- the server: --sim over HTTP, once, in real time ----------------------------------------------------------------
def http(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))
tmp = Path(tempfile.mkdtemp())
env = dict(os.environ, NXT_LAB_DATA=str(tmp), OBSERVATORY_DATA=str(tmp / "obs"), MINIVIEW_DATA=str(tmp / "obs"))
bad = subprocess.run([NXT_WEB, "--sim"], capture_output=True, text=True, env=env)
check("--sim without --world is refused", bad.returncode == 2 and "--world" in bad.stderr, bad.stderr[-120:])
bad = subprocess.run([NXT_WEB, "--sim", "--fake", "--world", str(APARTMENT)], capture_output=True, text=True, env=env)
check("--sim with --fake is refused", bad.returncode == 2, bad.stderr[-120:])

(tmp / "config.json").write_text(json.dumps(Config().to_dict()))
port = 8767
proc = subprocess.Popen([NXT_WEB, "--sim", "--world", str(APARTMENT), "--start", "0", "2", "90", "--port", str(port), "--config", str(tmp / "config.json")],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
try:
    print("server:", proc.stdout.readline().strip())
    base = f"http://127.0.0.1:{port}"
    status = http(base, "/api/status")[1]
    check("status: connected, a fake, link sim, the deadman running",
          status["connected"] and status["fake"] and status["link"] == "sim" and status["deadman"]["running"], status)
    code, truth = http(base, "/api/sim/truth")
    check("GET /api/sim/truth: the model's pose and the wall clock, open without the lock (simhost's truth reader)",
          code == 200 and abs(truth["pose"][1] - 2.0) < 1e-6 and abs(truth["pose"][2] - math.pi / 2) < 1e-6
          and abs(truth["wall_ns"] - time.time_ns()) < 5e9, truth)
    session = http(base, "/api/lock", {"action": "acquire", "client": "sim-test"})[1]["session"]
    deadline = time.monotonic() + 8.0
    flag = None
    while time.monotonic() < deadline and not flag:
        http(base, "/api/drive", {"left": 100, "right": 100, "session": session})
        time.sleep(0.2)
        flag = (http(base, "/api/status")[1]["deadman"]["state"] or {}).get("obstacle_stop")
    status = http(base, "/api/status")[1]
    check("driving north at the wall over HTTP: the obstacle stop fires, from the world's distance", flag, status["deadman"]["state"])
    samples = http(base, "/api/live?since=0")[1]["samples"]
    check("the ultrasonic in the live samples is the world's, not the sine", samples and samples[-1]["sensors"]["4"]["value"] is not None
          and samples[-1]["sensors"]["4"]["value"] <= 15, samples[-1]["sensors"] if samples else None)
    http(base, "/api/stop", {"session": session})
    fake = subprocess.Popen([NXT_WEB, "--fake", "--port", str(port + 1), "--config", str(tmp / "config.json")],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        fake.stdout.readline()
        check("outside --sim there is no truth: /api/sim/truth is a 404", http(f"http://127.0.0.1:{port + 1}", "/api/sim/truth")[0] == 404)
    finally:
        fake.terminate()
        fake.wait(timeout=5)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(tmp, ignore_errors=True)

print("SIM", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
