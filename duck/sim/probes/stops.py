"""Walk, stop, look: N times (walk WALK s at VX with a slight turn, then stand STOP s), printing the map status after each stop."""
import json
import os
import socket
import subprocess
import sys
import time

n_stops, vx, walk_s, stop_s = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
ctl = "/work/pollen/microduck/target/debug/robotctl"
map_sock = os.path.expanduser("~/.cache/duck-sim/duck-a-map.sock")
s = socket.socket(socket.AF_UNIX)
s.connect(os.path.expanduser("~/.cache/duck-sim/duck-a.sock"))
f = s.makefile("rw")
i = 0


def move(vx_, vyaw):
    global i
    i += 1
    f.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.move",
                        "params": {"vx": vx_, "vy": 0.0, "vyaw": vyaw}}) + "\n"); f.flush(); f.readline()


for k in range(n_stops):
    for _ in range(int(walk_s * 10)):
        move(vx, 0.3)
        time.sleep(0.1)
    move(0.0, 0.0)  # an explicit zero: robotd keeps the last request after its deadman trips
    time.sleep(stop_s)
    out = subprocess.run([ctl, "map", "--map-socket", map_sock, "status"], capture_output=True, text=True).stdout
    print(f"--- after stop {k + 1}\n{out.strip()}", flush=True)
