"""robotd's odometry against the simulator's truth on a straight walk: the measurement for an upstream
report, using only duck-sim's own pieces (robot.move, robot.subscribe, the body server's read).

    python duck/sim/probes/odom_vs_truth.py [vx] [seconds] [runs]

Each run: settle, record odometry and truth, walk straight at vx for the given seconds (a move every
100 ms), stop with an explicit zero, settle, record again. Reports straight-line distance by each.
"""
import json
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from duck_lab.nav.client import SIM, StateStream  # noqa: E402

vx = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
runs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
sim = os.path.expanduser("~/.cache/duck-sim")

body = socket.create_connection(("127.0.0.1", int(os.environ.get("DUCK_SIM_PORT", "7801")))).makefile("rw")
body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()
rpc = socket.socket(socket.AF_UNIX); rpc.connect(f"{sim}/duck-a.sock"); rf = rpc.makefile("rw")
state = StateStream(SIM / "duck-a.sock", hz=50)   # a reader thread: always the latest state
time.sleep(0.5)
n = [0]


def truth():
    body.write('{"op":"read"}\n'); body.flush()
    return json.loads(body.readline())["trunk"][:2]


def odom():
    return state.latest["odom"]["position"][:2]


def move(v):
    n[0] += 1
    rf.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": "robot.move",
                         "params": {"vx": v, "vy": 0.0, "vyaw": 0.0}}) + "\n"); rf.flush(); rf.readline()


rows = []
for k in range(runs):
    for _ in range(20):
        move(0.0); time.sleep(0.1)
    o0, t0 = odom(), truth()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        move(vx); time.sleep(0.1)
    for _ in range(20):
        move(0.0); time.sleep(0.1)
    o1, t1 = odom(), truth()
    do, dt = math.dist(o0, o1), math.dist(t0, t1)
    rows.append((do, dt))
    print(f"run {k + 1}: odometry {do:.3f} m, truth {dt:.3f} m, truth/odometry {dt / do:.3f}", flush=True)
ratio = sum(t for _, t in rows) / sum(o for o, _ in rows)
print(f"pooled truth/odometry {ratio:.3f} over {sum(t for _, t in rows):.2f} m (vx {vx}, {seconds:.0f} s x {runs})")
