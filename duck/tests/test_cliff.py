"""The cliff check on frames built from geometry, and on recorded frames from the simulator.
Run: cd duck && uv run python tests/test_cliff.py"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav.cliff import BEAMS, COLS, drop_ahead, rotate, sensor_pose

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def state(pitch_deg=25.0, height=0.118):
    """A level trunk; the sensor at the head's height, pitched down by pitch_deg."""
    p = math.radians(pitch_deg) / 2
    return {"imu": {"quat": [1.0, 0.0, 0.0, 0.0]},
            "odom": {"position": [0.0, 0.0, height], "yaw": 0.0},
            "frames": {"tof": {"pos": [0.08, 0.0, 0.11], "quat": [math.cos(p), 0.0, math.sin(p), 0.0]}}}


def frame_for(st, floor_until_m=None, drop_m=0.3):
    """The frame the sensor would see over flat floor; beyond floor_until_m (horizontal) the floor
    drops by drop_m. Axial ranges, as the sensor reports them."""
    height, q = sensor_pose(st)
    dist, status = [], []
    for beam in BEAMS:
        d = rotate(q, beam)
        if d[2] >= -0.01:
            dist.append(2000), status.append(5)
            continue
        t = -height / d[2]
        if floor_until_m is not None and t * math.hypot(d[0], d[1]) > floor_until_m:
            t = -(height + drop_m) / d[2]
        dist.append(int(t * beam[0] * 1000)), status.append(5)
    return {"distance_mm": dist, "status": status}


st = state()
check("flat floor: no drop", drop_ahead(frame_for(st), st) is None)
d = drop_ahead(frame_for(st, floor_until_m=0.45), st)
check("floor ends 0.45 m ahead: a drop at about 0.45 m", d is not None and 0.4 <= d <= 0.55, d)
check("floor ends 1.5 m ahead: beyond the look distance, no drop", drop_ahead(frame_for(st, 1.5), st) is None)
nothing = {"distance_mm": [0] * 64, "status": [255] * 64}
check("no returns where the floor should be: a drop", drop_ahead(nothing, st) is not None)
box = frame_for(st)
for i in range(64):
    if i % COLS in range(2, 6):
        box["distance_mm"][i] = min(box["distance_mm"][i], 250)
check("something on the floor (shorter returns): not a drop", drop_ahead(box, st) is None)
level = state(pitch_deg=0.0)
check("head level: the lower rows still see the floor", drop_ahead(frame_for(level), level) is None)

# Recorded in the simulator standing on flat floor, each frame with robotd's state at that moment
# (duck/sim/probes/tof_rows.py). Skipped where the recordings are absent (they live in runs/).
for path in sorted((Path(__file__).resolve().parents[1] / "runs").glob("tof-flat-*.json")):
    frames = json.loads(path.read_text())["frames"]
    hits = [drop_ahead(f, f["state"]) for f in frames]
    check(f"recorded flat floor ({path.name}, {len(frames)} frames): no drop",
          all(h is None for h in hits), [h for h in hits if h is not None][:5])

print("CLIFF", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
