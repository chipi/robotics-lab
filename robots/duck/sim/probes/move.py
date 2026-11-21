"""Like duck-sim's drive, but each robot.move carries an id and its reply is read."""
import json
import math
import os
import socket
import sys
import time

import simhost  # noqa: E402

HOST = simhost.load()      # the host's truth port and sockets (RFC-0021)

vx, vyaw, with_id = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3] == "id"
port = HOST.truth_port
body = socket.create_connection(("127.0.0.1", port)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()


def pose():
    body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
    w, x, y, z = r["imu"]["quat"]
    return r["trunk"][:2], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


s = socket.socket(socket.AF_UNIX)
s.connect(str(HOST.sockets["robot"]))
f = s.makefile("rw")
(x0, yaw0), turned = pose(), 0.0
prev = yaw0
for i in range(80):
    req = {"jsonrpc": "2.0", "method": "robot.move", "params": {"vx": vx, "vy": 0.0, "vyaw": vyaw}}
    if with_id:
        req["id"] = i
    f.write(json.dumps(req) + "\n"); f.flush()
    if with_id:
        f.readline()
    time.sleep(0.1)
    _, yaw = pose()
    turned += math.atan2(math.sin(yaw - prev), math.cos(yaw - prev)); prev = yaw
x1, _ = pose()
moved = math.dist(x0, x1)
print(f"{'id' if with_id else 'notification'}: moved {moved * 100:.0f} cm ({moved / 8:.3f} m/s of {vx:.2f}), "
      f"turned {math.degrees(turned):+.0f} deg ({math.degrees(turned) / 8:+.1f} deg/s of {math.degrees(vyaw):+.0f})")
