"""What the simulated duck does with a constant command from a stand, from the truth (phase 5 item 4e unit E10): turn rate for a
vyaw with vx 0, and walk speed for a vx, by the second. A fresh simulator (the host's default scene) for each case; takes it down
at the end. Run under the simulator lock.

    uv run python sim/probes/drive_response.py turn 0.5 0.8 1.0 1.2        # vyaw, vx 0
    uv run python sim/probes/drive_response.py walk 0.3 --tick 0.1 --seconds 8
    uv run python sim/probes/drive_response.py walk 0.2 0.3 0.4 --tick 0.05

Per case: the turn (degrees) and the distance (m) in each second, then the whole run and the last half's rate.
"""

import argparse
import json
import math
import socket
import time

import simhost

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["turn", "walk"])
ap.add_argument("values", nargs="+", type=float)
ap.add_argument("--seconds", type=float, default=8.0)
ap.add_argument("--tick", type=float, default=0.1, help="seconds between robot.move commands")
ap.add_argument("--stand", type=float, default=3.0, help="seconds of zero commands before the case")
ap.add_argument("--vx", type=float, default=0.0, help="forward speed beside the turn (turn mode)")
ap.add_argument("--scene", default=None, help="a scenario id (ch1-s1) under the host's scenarios; default: the simulator's own scene")
args = ap.parse_args()
host = simhost.load()


def run(value: float) -> None:
    simhost.reset(host, *([str(host.scenarios / args.scene / "scene.xml")] if args.scene else []))
    body = socket.create_connection(("127.0.0.1", host.truth_port)).makefile("rw")
    body.write(json.dumps({"op": "hello", "protocol": 1, "joints": 15}) + "\n"); body.flush(); body.readline()

    def pose():
        body.write('{"op":"read"}\n'); body.flush()
        r = json.loads(body.readline())
        w, x, y, z = r["imu"]["quat"]
        return r["trunk"][0], r["trunk"][1], math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

    s = socket.socket(socket.AF_UNIX); s.connect(str(host.sockets["robot"])); f = s.makefile("rw")
    n = [0]

    def move(vx: float, vyaw: float) -> None:
        n[0] += 1
        f.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": "robot.move",
                            "params": {"vx": vx, "vy": 0.0, "vyaw": vyaw}}) + "\n"); f.flush(); f.readline()

    t_end = time.monotonic() + args.stand
    while time.monotonic() < t_end:
        move(0.0, 0.0); time.sleep(0.1)
    cmd = (args.vx, value) if args.mode == "turn" else (value, 0.0)
    x0, y0, a0 = pose()
    last, turned, rows = (x0, y0, a0), 0.0, []
    t0 = time.monotonic()
    sec_turn = sec_dist = 0.0
    sec, at = 1, []
    while time.monotonic() - t0 < args.seconds:
        move(*cmd); time.sleep(args.tick)
        x, y, a = pose()
        turned += math.atan2(math.sin(a - last[2]), math.cos(a - last[2]))
        sec_turn += math.atan2(math.sin(a - last[2]), math.cos(a - last[2]))
        sec_dist += math.dist((x, y), last[:2])
        last = (x, y, a)
        if time.monotonic() - t0 >= sec:
            rows.append((sec_turn, sec_dist)); at.append((round(x - x0, 2), round(y - y0, 2))); sec_turn = sec_dist = 0.0; sec += 1
    move(0.0, 0.0)
    x, y, _ = pose()
    half = rows[len(rows) // 2:]
    label = f"{args.mode} {value:g} (tick {args.tick:g}, vx {cmd[0]:g}, vyaw {cmd[1]:g})"
    per_s = " ".join(f"{math.degrees(t):+4.0f}/{d:.2f}" for t, d in rows)
    print(f"{label}: per second deg/m: {per_s}", flush=True)
    print(f"    offset from the start each second (m): {at}", flush=True)
    print(f"    whole run: turned {math.degrees(turned):+.0f} deg, net {math.hypot(x - x0, y - y0):.3f} m; last half: "
          f"{math.degrees(sum(t for t, _ in half)) / len(half):+.1f} deg/s, {sum(d for _, d in half) / len(half):.3f} m/s "
          f"(asked {cmd[1]:g} rad/s = {math.degrees(cmd[1]):.0f} deg/s, {cmd[0]:g} m/s)", flush=True)


try:
    for v in args.values:
        run(v)
finally:
    simhost.down(host)
