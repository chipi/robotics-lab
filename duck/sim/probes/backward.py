"""Can the duck walk backwards? Send vx < 0 (id'd robot.move every 0.1 s) for a few seconds, then
explicit zeros; report the truth displacement along and across the starting heading, and the yaw change.
Run: .venv/bin/python sim/probes/backward.py -0.15 4"""
import json
import math
import os
import socket
import sys
import time

vx, seconds = float(sys.argv[1]), float(sys.argv[2])
body = socket.create_connection(("127.0.0.1", 7801)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()


def pose():
    body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
    w, x, y, z = r["imu"]["quat"]
    return r["trunk"][0], r["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)), r["trunk"][2]


s = socket.socket(socket.AF_UNIX)
s.connect(os.path.expanduser("~/.cache/duck-sim/duck-a.sock"))
f = s.makefile("rw")


def move(v):
    f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "robot.move",
                        "params": {"vx": v, "vy": 0.0, "vyaw": 0.0}}) + "\n"); f.flush()
    return json.loads(f.readline())


x0, y0, yaw0, z0 = pose()
first = move(vx)
t = time.monotonic()
while time.monotonic() - t < seconds:
    move(vx)
    time.sleep(0.1)
for _ in range(15):          # robotd keeps the last twist after its deadman: stop explicitly
    move(0.0)
    time.sleep(0.1)
x1, y1, yaw1, z1 = pose()
dx, dy = x1 - x0, y1 - y0
along = dx * math.cos(yaw0) + dy * math.sin(yaw0)
across = -dx * math.sin(yaw0) + dy * math.cos(yaw0)
dyaw = math.degrees(math.atan2(math.sin(yaw1 - yaw0), math.cos(yaw1 - yaw0)))
print(f"first reply: {first}")
print(f"vx {vx:+.2f} m/s for {seconds:.0f} s: along heading {along * 100:+.1f} cm, across {across * 100:+.1f} cm, "
      f"yaw {dyaw:+.1f} deg, trunk height {z0:.3f} -> {z1:.3f} m")
