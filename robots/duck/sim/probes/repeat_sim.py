"""Where do two runs of the simulator first differ? (K13: the commands of two repeats of a challenge first differ 8 to 15 s in and the truth
differs by 0.9 mm at the first command.) The body server (microduck_rl sim/body_server.py) steps MuJoCo in real time, 20 ms of physics
a pass paced by time.sleep, while robotd writes the joint targets from its own wall-clock loop and tofd asks for a depth frame at 15 Hz
from a generator seeded once per body; so what is compared here is what each of them leaves.

    uv run python sim/probes/repeat_sim.py record OUT.json idle|walk|steered SECONDS     # on a freshly reset simulator (sim/reset_sim.py)
    uv run python sim/probes/repeat_sim.py compare A.json B.json

`record` reads the body server's truth (trunk pose, sim_time) as fast as it answers and keeps every distinct sim_time, and every depth
frame tofd publishes; in `walk` mode, after 4 s, it sends robot.move vx 0.2 every 0.1 s of wall time; in `steered` mode it sends robot.head
(the walking policy's zero command) every 0.1 s from the start, which keeps robotd's idle head behaviour (robotd/src/idle_head.rs: random
glances seeded from the clock, after 2 s with nothing asked) from starting. `compare` takes the sim_times both runs have, and says where the
trunk poses first differ (over 1e-9 m, over 1 mm), how much at the end, and where the depth frames (in order) first differ and by how much.
What it found is in docs/wip/KNOWN-ISSUES.md, K13: the trunk is already 0.6 to 5 mm apart at the first sim time read (6.6 s after a reset),
before any command.
"""

import json
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path

import simhost  # noqa: E402

HOST = simhost.load()      # the host's truth port and sockets (RFC-0021)



def record(out: Path, mode: str, seconds: float) -> None:
    body = socket.create_connection(("127.0.0.1", HOST.truth_port)).makefile("rw")
    body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n")
    body.flush()
    body.readline()
    frames, stop = [], threading.Event()

    def tof() -> None:
        s = socket.socket(socket.AF_UNIX)
        s.connect(str(HOST.sockets["depth"]))
        s.settimeout(1.0)
        f = s.makefile("rw")
        f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
        f.flush()
        while not stop.is_set():
            try:
                line = f.readline()
            except (TimeoutError, socket.timeout):
                continue
            if not line:
                break
            msg = json.loads(line)
            if msg.get("method") == "tof.frame":
                frames.append(msg["params"]["distance_mm"])

    t = threading.Thread(target=tof)
    t.start()
    rob = socket.socket(socket.AF_UNIX)
    rob.connect(str(HOST.sockets["robot"]))
    rf = rob.makefile("rw")
    i = 0
    poses, start, last_move = {}, time.monotonic(), 0.0
    while time.monotonic() - start < seconds:
        body.write('{"op":"read"}\n')
        body.flush()
        r = json.loads(body.readline())
        poses[r["sim_time"]] = [r["trunk"][0], r["trunk"][1], r["trunk"][2], *r["imu"]["quat"]]
        now = time.monotonic() - start
        if mode == "steered" and now - last_move >= 0.1:
            i += 1
            last_move = now
            rf.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.head", "params": {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}}) + "\n")
            rf.flush()
            rf.readline()
        if mode == "walk" and now > 4.0 and now - last_move >= 0.1:
            i += 1
            last_move = now
            rf.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.move", "params": {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}}) + "\n")
            rf.flush()
            rf.readline()
    if mode == "walk":
        for _ in range(10):
            i += 1
            rf.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.move", "params": {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}}) + "\n")
            rf.flush()
            rf.readline()
            time.sleep(0.1)
    stop.set()
    t.join()
    out.write_text(json.dumps({"mode": mode, "poses": poses, "frames": frames}))
    print(f"{out}: {len(poses)} sim times ({min(map(float, poses)):.2f} .. {max(map(float, poses)):.2f} s), {len(frames)} depth frames")


def compare(pa: Path, pb: Path) -> None:
    a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
    common = sorted(set(a["poses"]) & set(b["poses"]), key=float)
    first = {1e-9: None, 1e-3: None}
    worst = 0.0
    for k in common:
        d = math.dist(a["poses"][k][:3], b["poses"][k][:3])
        worst = max(worst, d)
        for thr in first:
            if first[thr] is None and d > thr:
                first[thr] = (float(k), d)
    last = common[-1]
    print(f"{a['mode']}: {len(common)} common sim times of {len(a['poses'])} and {len(b['poses'])} "
          f"({float(common[0]):.2f} .. {float(last):.2f} s)")
    print(f"  trunk position: first over 1e-9 m at " + (f"sim {first[1e-9][0]:.2f} s ({first[1e-9][1] * 1000:.4f} mm)" if first[1e-9] else "never")
          + "; first over 1 mm at " + (f"sim {first[1e-3][0]:.2f} s ({first[1e-3][1] * 1000:.2f} mm)" if first[1e-3] else "never")
          + f"; worst {worst * 1000:.3f} mm; at the last common time {math.dist(a['poses'][last][:3], b['poses'][last][:3]) * 1000:.3f} mm")
    n = min(len(a["frames"]), len(b["frames"]))
    diff = [k for k in range(n) if a["frames"][k] != b["frames"][k]]
    mx = max((max(abs(x - y) for x, y in zip(a["frames"][k], b["frames"][k])) for k in diff), default=0)
    print(f"  depth frames: {n} in common, {len(diff)} differ" + (f", first at frame {diff[0]}, up to {mx} mm" if diff else ""))


if __name__ == "__main__":
    if sys.argv[1] == "record":
        record(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]))
    else:
        compare(Path(sys.argv[2]), Path(sys.argv[3]))
