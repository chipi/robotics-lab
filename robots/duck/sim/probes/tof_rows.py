"""What the depth sensor sees, row by row: N frames from tof.stream, each saved with robotd's state at
that moment (the head moves between frames), then per row the median distance of valid zones.

    robots/duck/.venv/bin/python robots/duck/sim/probes/tof_rows.py [frames] [--json out.json]
"""
import json
import os
import socket
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from duck_lab.nav.client import StateStream  # noqa: E402
import simhost  # noqa: E402

host = simhost.load()

n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 20
out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
state = StateStream(host.sockets["robot"], hz=50)
time.sleep(0.5)
s = socket.socket(socket.AF_UNIX)
s.connect(str(host.sockets["depth"]))
f = s.makefile("rw")
f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
f.flush()
frames = []
while len(frames) < n:
    msg = json.loads(f.readline())
    if msg.get("method") == "tof.frame":
        fr = msg["params"]
        fr["state"] = {k: state.latest[k] for k in ("imu", "odom", "frames", "t_ns")}
        frames.append(fr)
state.close()
rows, cols = frames[0]["rows"], frames[0]["cols"]
print(f"{n} frames, {rows}x{cols}; statuses seen: {sorted({st for fr in frames for st in fr['status']})}")
for r in range(rows):
    vals = [fr["distance_mm"][r * cols + c] for fr in frames for c in range(cols)
            if fr["status"][r * cols + c] in (5, 9) and fr["distance_mm"][r * cols + c] > 0]
    print(f"row {r}: median {statistics.median(vals) if vals else '-':>6} mm, valid {len(vals) / (n * cols):.0%}")
if out:
    json.dump({"frames": frames}, open(out, "w"))
