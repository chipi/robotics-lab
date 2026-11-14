"""How still is the standing duck? Simulator truth over 0.5 s windows for 6 s, no commands sent."""
import json
import math
import socket
import time

body = socket.create_connection(("127.0.0.1", 7801)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()


def read():
    body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
    w, x, y, z = r["imu"]["quat"]
    return r["trunk"][:2], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


time.sleep(2)
p0, y0 = read()
for _ in range(12):
    time.sleep(0.5)
    p1, y1 = read()
    v = math.dist(p0, p1) / 0.5
    w = abs(math.atan2(math.sin(y1 - y0), math.cos(y1 - y0))) / 0.5
    print(f"speed {v:.3f} m/s  turn {w:.3f} rad/s  {'STILL' if v < 0.03 and w < 0.08 else 'moving'}")
    p0, y0 = p1, y1
