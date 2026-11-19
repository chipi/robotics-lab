"""Why did the cliff check see a drop? For every depth frame of a run whose recorded drop_points are not empty, each beam
that counted as a drop, and for what: no valid reading (its status) or a reading too far (how far past the floor), with
the sensor's height and pitch as the robot believed them. Replays cliff.drop_points' own geometry on the recorded
frame and its paired state (ADR-0014), so it says what the navigator saw, not a re-imagining of it.

    uv run python sim/probes/false_drops.py <data folder> <run key> [--all]
"""

import collections
import math
import sys
from pathlib import Path

from runfile import keys
from runfile.mcapio import Follower

from cliff_shim import cliff
from duck_lab.replay import state_of


def diagnose(frame: dict, state: dict) -> list:
    height, q = cliff.sensor_pose(state)
    out = []
    for i, beam in enumerate(cliff.BEAMS):
        d = cliff.rotate(q, beam)
        if d[2] > -0.15:
            continue
        t_floor = -height / d[2]
        h_floor = t_floor * math.hypot(d[0], d[1])
        if h_floor > cliff.LOOK_M:
            continue
        st, mm = frame["status"][i], frame["distance_mm"][i]
        valid = st in cliff.VALID and mm > 0
        if valid:
            r = mm / 1000.0 / beam[0]
            if r * -d[2] < height + cliff.EXTRA_M:
                continue
            why = f"too far: {r:.3f} m along the beam, floor at {t_floor:.3f} m ({(r - t_floor) * 100:+.1f} cm)"
        else:
            why = f"no valid reading (status {st}, {mm} mm)"
        out.append({"zone": (i // 8, i % 8), "h_floor": round(h_floor, 3), "why": why, "valid": valid})
    return out


def main() -> None:
    data, key = Path(sys.argv[1]), sys.argv[2]
    show_all = "--all" in sys.argv
    kinds = collections.Counter()
    n = 0
    for t, kind, p in Follower(keys.run_dir(data, key), keep_raw=True).poll():
        if kind != "depth_frame" or "state" not in p or not (p.get("derived") or {}).get("drop_points"):
            continue
        n += 1
        st = state_of(p)
        height, q = cliff.sensor_pose(st)
        w, x, y, z = st["imu"]["quat"]
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
        beams = diagnose({"distance_mm": p["distance_mm"], "status": p["status"]}, st)
        for b in beams:
            kinds["no valid reading" if not b["valid"] else "too far"] += 1
        if show_all or n <= 6:
            print(f"t {t:.3f}  sensor height {height:.3f} m, trunk pitch {pitch:+.1f} deg, odom_z {p['state']['odom_z']:.3f}")
            for b in beams:
                print(f"   zone {b['zone']}: floor expected {b['h_floor']:.2f} m ahead; {b['why']}")
    print(f"{n} frames with a drop; beams counted: {dict(kinds)}")


if __name__ == "__main__":
    main()
