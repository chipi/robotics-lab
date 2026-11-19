"""Turn to HEADING (deg) at 1.2 rad/s, then walk VX m/s for SECONDS; report travel and posture."""
import json
import math
import os
import socket
import sys
import time

heading, vx, seconds = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
body = socket.create_connection(("127.0.0.1", 7801)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()


def read():
    body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
    w, x, y, z = r["imu"]["quat"]
    return r["trunk"], math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


s = socket.socket(socket.AF_UNIX)
s.connect(os.path.expanduser("~/.cache/duck-sim/duck-a.sock"))
f = s.makefile("rw")
n = 0


def move(vx_, vyaw):
    global n
    n += 1
    f.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": "robot.move",
                        "params": {"vx": vx_, "vy": 0.0, "vyaw": vyaw}}) + "\n"); f.flush(); f.readline()


t0 = time.monotonic()
while time.monotonic() - t0 < 20:
    _, h = read()
    err = (heading - h + 180) % 360 - 180
    if abs(err) < 8:
        break
    move(0.0, 1.2 if err > 0 else -1.2)
    time.sleep(0.1)
(trunk0, h0) = read()
print(f"turned to {h0:+.0f} deg (asked {heading:+.0f}) in {time.monotonic() - t0:.1f} s, at ({trunk0[0]:.2f}, {trunk0[1]:.2f})")
lowest = 1.0
for _ in range(int(seconds * 10)):
    move(vx, 0.0)
    time.sleep(0.1)
    trunk, _ = read()
    lowest = min(lowest, trunk[2])
trunk1, h1 = read()
d = math.dist(trunk0[:2], trunk1[:2])
print(f"walked {d * 100:.0f} cm in {seconds:.0f} s ({d / seconds:.3f} m/s of {vx:.2f}), now at "
      f"({trunk1[0]:.2f}, {trunk1[1]:.2f}) heading {h1:+.0f}; lowest trunk {lowest:.3f} m")
