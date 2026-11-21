"""Where the duck is, and the apartment's walls near it (from the scene file)."""
import json
import math
import re
import socket
from pathlib import Path

import simhost  # noqa: E402

HOST = simhost.load()      # the host's truth port and sockets (RFC-0021)

body = socket.create_connection(("127.0.0.1", HOST.truth_port)).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()
body.write('{"op":"read"}\n'); body.flush(); r = json.loads(body.readline())
w, x, y, z = r["imu"]["quat"]
yaw = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
tx, ty = r["trunk"][:2]
print(f"duck at ({tx:.2f}, {ty:.2f}) m, heading {yaw:+.0f} deg, trunk z {r['trunk'][2]:.3f}")
print("contacts:", {k: v for k, v in r.items() if "contact" in k.lower()} or "(none reported)")

apt = Path("/work/pollen/microduck_rl/src/mjlab_microduck/robot/microduck/apartment.xml").read_text()
near = []
for m in re.finditer(r'<geom[^>]*name="([^"]+)"[^>]*>', apt):
    g = m.group(0)
    pos = re.search(r'pos="([^"]+)"', g)
    size = re.search(r'size="([^"]+)"', g)
    if not pos or not size:
        continue
    px, py, *_ = (float(v) for v in pos.group(1).split())
    sx, sy, *_ = [float(v) for v in size.group(1).split()] + [0, 0]
    d = math.hypot(max(abs(tx - px) - sx, 0), max(abs(ty - py) - sy, 0))
    near.append((d, m.group(1), px, py, sx, sy))
for d, name, px, py, sx, sy in sorted(near)[:8]:
    print(f"  {d:.2f} m  {name}  centre ({px:.2f},{py:.2f}) half-size ({sx:.2f},{sy:.2f})")
