"""Turn on the spot: KICK rad/s for 2 s to start stepping, then HOLD rad/s for 8 s, measured."""
import json
import math
import os
import socket
import sys
import time

import simhost  # noqa: E402

HOST = simhost.load()      # the host's truth port and sockets (RFC-0021)

kick, hold = float(sys.argv[1]), float(sys.argv[2])
body = socket.create_connection(("127.0.0.1", HOST.truth_port)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()


def yaw():
    body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
    w, x, y, z = r["imu"]["quat"]
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


s = socket.socket(socket.AF_UNIX)
s.connect(str(HOST.sockets["robot"]))
f = s.makefile("rw")


def move(i, w):
    f.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.move",
                        "params": {"vx": 0.0, "vy": 0.0, "vyaw": w}}) + "\n"); f.flush(); f.readline()


for i in range(20):
    move(i, kick); time.sleep(0.1)
prev, turned = yaw(), 0.0
for i in range(80):
    move(100 + i, hold); time.sleep(0.1)
    y = yaw(); turned += math.atan2(math.sin(y - prev), math.cos(y - prev)); prev = y
print(f"kick {kick} then hold {hold}: {math.degrees(turned) / 8:+.1f} deg/s of {math.degrees(hold):+.0f} asked")
