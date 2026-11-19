"""Record a session for maploc's replay bench (Pollen's `cargo run -p maploc --release --example replay -- <dir>`) from the
live simulator: state.jsonl (robot.state) and tof.jsonl (tof.frame), each line {"arrival_ns", "params"}, the robot's own
t_ns inside; and truth.jsonl, the simulator's trunk pose beside each 5th state (t_ns, x, y, z, quat), to score the grid
the bench builds against the apartment's layout (map_range.py). The duck walks and stops N times (as stops.py does: the
mapper builds a keyframe at a stop), with an explicit zero at each stop because robotd keeps the last twist after its
deadman.

    uv run python sim/probes/record_session.py OUT_DIR [N_STOPS VX VYAW WALK_S STOP_S]      # defaults 6 0.2 0.25 6 4

Run it on a freshly reset simulator (sim/reset_sim.py), under the simulator lock.
"""

import json
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path

SIM = Path(os.path.expanduser("~/.cache/duck-sim"))


def stream(sock: Path, request: dict, method: str, out, stop: threading.Event, every: int = 1, extra=None) -> None:
    s = socket.socket(socket.AF_UNIX)
    s.connect(str(sock))
    s.settimeout(1.0)
    f = s.makefile("rw")
    f.write(json.dumps(request) + "\n")
    f.flush()
    n = 0
    while not stop.is_set():
        try:
            line = f.readline()
        except (TimeoutError, socket.timeout):
            continue
        if not line:
            break
        msg = json.loads(line)
        if msg.get("method") != method:
            continue
        n += 1
        out.write(json.dumps({"arrival_ns": time.time_ns(), "params": msg["params"]}) + "\n")
        if extra is not None and n % every == 0:
            extra(msg["params"])


def main() -> None:
    out_dir = Path(sys.argv[1])
    n_stops, vx, vyaw, walk_s, stop_s = (int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]),
                                         float(sys.argv[6])) if len(sys.argv) > 6 else (6, 0.2, 0.25, 6.0, 4.0)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = socket.create_connection(("127.0.0.1", 7801)).makefile("rw")
    body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n")
    body.flush()
    body.readline()
    truth = open(out_dir / "truth.jsonl", "w")
    body_lock = threading.Lock()

    def sample_truth(state: dict) -> None:
        with body_lock:
            body.write('{"op":"read"}\n')
            body.flush()
            r = json.loads(body.readline())
        truth.write(json.dumps({"t_ns": state["t_ns"], "trunk": r["trunk"], "quat": r["imu"]["quat"]}) + "\n")

    stop = threading.Event()
    state_f, tof_f = open(out_dir / "state.jsonl", "w"), open(out_dir / "tof.jsonl", "w")
    threads = [
        threading.Thread(target=stream, args=(SIM / "duck-a.sock", {"jsonrpc": "2.0", "id": 1, "method": "robot.subscribe",
                                                                      "params": {"hz": 50}}, "robot.state", state_f, stop, 5,
                                              sample_truth)),
        threading.Thread(target=stream, args=(SIM / "duck-a-tof.sock", {"jsonrpc": "2.0", "id": 1, "method": "tof.stream"},
                                              "tof.frame", tof_f, stop)),
    ]
    for t in threads:
        t.start()
    time.sleep(1.0)
    s = socket.socket(socket.AF_UNIX)
    s.connect(str(SIM / "duck-a.sock"))
    f = s.makefile("rw")
    i = 0

    def move(v: float, w: float) -> None:
        nonlocal i
        i += 1
        f.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": "robot.move", "params": {"vx": v, "vy": 0.0, "vyaw": w}}) + "\n")
        f.flush()
        f.readline()

    for k in range(n_stops):
        for _ in range(int(walk_s * 10)):
            move(vx, vyaw)
            time.sleep(0.1)
        move(0.0, 0.0)
        time.sleep(stop_s)
        print(f"stop {k + 1} of {n_stops}", flush=True)
    stop.set()
    for t in threads:
        t.join()
    for fh in (state_f, tof_f, truth):
        fh.close()
    print(f"recorded to {out_dir}: " + ", ".join(f"{n} {sum(1 for _ in open(out_dir / n))} lines" for n in ("state.jsonl", "tof.jsonl", "truth.jsonl")))


if __name__ == "__main__":
    main()
