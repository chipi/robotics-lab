"""The cliff check on frames built from geometry, and on recorded frames from the simulator.
Run: cd duck && uv run python tests/test_cliff.py"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav.cliff import BEAMS, COLS, drop_ahead, drop_points, rotate, sensor_pose

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


def side_hole(st, left_from_m, drop_m=0.3):
    """Flat floor, except a hole to the left: where the floor point lies more than left_from_m left."""
    height, q = sensor_pose(st)
    dist, status = [], []
    for beam in BEAMS:
        d = rotate(q, beam)
        if d[2] >= -0.01:
            dist.append(2000), status.append(5)
            continue
        t = -height / d[2]
        if t * d[1] > left_from_m:
            t = -(height + drop_m) / d[2]
        dist.append(int(t * beam[0] * 1000)), status.append(5)
    return {"distance_mm": dist, "status": status}


# Exploration trial 10: the duck walked diagonally past the stairwell's corner, the hole to its left,
# and the central columns saw only floor. Columns whose floor point falls in the duck's corridor and
# the bend beside it count too.
sh = drop_points(side_hole(st, 0.12), st)
check("a hole 12 cm to the left of the line: a drop, on the left", sh and all(p[1] > 0 for p in sh), sh[:2])
check("a hole beyond the corridor (30 cm left): not a stop", drop_points(side_hole(st, 0.30), st) == [])

# The head pitched 3 deg higher than the duck believes (contact, gait): shallow beams meet the floor
# further out than predicted. That is not a drop (trial 12's false stop by the office cabinet).
believed, actual = state(pitch_deg=25.0), state(pitch_deg=22.0)
check("flat floor seen with the head 3 deg higher than believed: no drop",
      drop_points(frame_for(actual), believed) == [], len(drop_points(frame_for(actual), believed)))

from duck_lab.nav.cliff import depth_points as _dp  # noqa: E402

hole_pts = _dp(side_hole(st, 0.12), st)
check("returns from inside a hole are 'below', never 'floor' (the explorer trusts only floor)",
      any(p[3] == "below" for p in hole_pts) and not any(p[3] == "floor" and p[1] > 0.14 for p in hole_pts),
      sorted({p[3] for p in hole_pts}))

# A drop with no return at all (challenge 12: a table edge over a floor out of range). Where a beam that should meet the
# floor within the sensor's range returns nothing, there is no floor that near: the floor is at least as far down as the
# beam's lowest point in range. depth_points gives that as a "below" point where the floor should have been, so a glance
# traces the edge and the forward sensor suspects it (challenge 12 seed 1: every glance read "floor", and the duck
# walked the edge for 60 s instead of refusing).
from duck_lab.nav.cliff import EXTRA_M, NO_TARGET_RANGE_M  # noqa: E402

none_beyond = frame_for(st)
h0, q0 = sensor_pose(st)
for i, beam in enumerate(BEAMS):
    dd = rotate(q0, beam)
    if dd[2] < -0.01 and (-h0 / dd[2]) * math.hypot(dd[0], dd[1]) > 0.45:
        none_beyond["distance_mm"][i], none_beyond["status"][i] = 0, 255
nb = _dp(none_beyond, st)
below_nb = [p for p in nb if p[3] == "below"]
check("no return where the floor should be: 'below' points, placed where the floor should have been (beyond 0.45 m)",
      below_nb and all(math.hypot(p[0] - 0.08, p[1]) > 0.42 for p in below_nb), [tuple(round(v, 2) for v in p[:3]) for p in below_nb[:3]])
check("... at least as far down as the beam's lowest point in range, past cliff.EXTRA_M",
      all(p[2] < -EXTRA_M for p in below_nb), sorted(round(p[2], 2) for p in below_nb)[-3:])
check("... and the floor before the edge is still floor", any(p[3] == "floor" for p in nb))
up = {"distance_mm": [0] * 64, "status": [255] * 64}
level_up = state(pitch_deg=-30.0)                  # the head pitched up: no beam meets the floor in range
check("no return from beams that never meet the floor in range says nothing (not a drop)",
      not any(p[3] == "below" for p in _dp(up, level_up)), sorted({p[3] for p in _dp(up, level_up)}))
check("the range used is the simulated sensor's", NO_TARGET_RANGE_M == 4.0)

from duck_lab.nav.cliff import extend_edge  # noqa: E402

seen = [(0.0, -0.7), (0.1, -0.71), (0.2, -0.7)]          # 20 cm of a stairwell's edge, along x
ext = extend_edge(seen, 0.15)
check("an edge seen for 20 cm is remembered 15 cm further each way, along it",
      len(ext) == 6 and min(p[0] for p in ext) < -0.14 and max(p[0] for p in ext) > 0.34
      and all(abs(p[1] + 0.703) < 0.02 for p in ext), [tuple(round(v, 2) for v in p) for p in ext])
check("one point is no edge", extend_edge([(0.0, 0.0)], 0.15) == [])

# Recorded in the simulator standing on flat floor, each frame with robotd's state at that moment
# (duck/sim/probes/tof_rows.py). Skipped where the recordings are absent (they live in runs/).
for path in sorted((Path(__file__).resolve().parents[1] / "runs").glob("tof-flat-*.json")):
    frames = json.loads(path.read_text())["frames"]
    hits = [drop_ahead(f, f["state"]) for f in frames]
    check(f"recorded flat floor ({path.name}, {len(frames)} frames): no drop",
          all(h is None for h in hits), [h for h in hits if h is not None][:5])

# Obstacle points for the reflex's memory, on the same recordings: floor is not an obstacle; the
# doorway walls and the cabinet are (tof-flat-0 faces them from the dock, tof-flat-180 faces open
# corridor floor).
from duck_lab.nav.cliff import obstacle_points  # noqa: E402

runs = Path(__file__).resolve().parents[1] / "runs"
if (runs / "tof-flat-180.json").exists():
    frames = json.loads((runs / "tof-flat-180.json").read_text())["frames"]
    n = sum(len(obstacle_points(f, f["state"])) for f in frames)
    check("open corridor floor: no obstacle points", n == 0, n)
if (runs / "tof-flat-0.json").exists():
    frames = json.loads((runs / "tof-flat-0.json").read_text())["frames"]
    pts = [p for f in frames for p in obstacle_points(f, f["state"])]
    ahead = sorted(p[0] for p in pts)
    check("facing the doorway and the cabinet: obstacles 0.3-0.7 m ahead",
          len(pts) > 100 and 0.3 <= ahead[len(ahead) // 2] <= 0.7, (len(pts), ahead[len(ahead) // 2] if ahead else None))

# Points are relative to the trunk, not the sensor: the sensor sits 8.5 cm ahead of the trunk and 2 cm
# left (frames.tof.pos), and leaving that out put every remembered obstacle 8.5 cm nearer the duck
# (explore9: "0.12 m of room" at a door frame 0.2 m away by truth).
if (runs / "tof-flat-0.json").exists():
    import copy  # noqa: E402

    f = json.loads((runs / "tof-flat-0.json").read_text())["frames"][0]
    at_trunk = copy.deepcopy(f)
    at_trunk["state"]["frames"]["tof"]["pos"] = [0.0, 0.0, f["state"]["frames"]["tof"]["pos"][2]]
    a, b = obstacle_points(f, f["state"]), obstacle_points(at_trunk, at_trunk["state"])
    from duck_lab.nav.cliff import sensor_offset  # noqa: E402

    (ax_, ay_), (bx_, by_) = sensor_offset(f["state"]), sensor_offset(at_trunk["state"])
    ex, ey = ax_ - bx_, ay_ - by_
    check("the sensor is ~8.5 cm ahead, ~2 cm left of the trunk", 0.07 < ax_ < 0.10 and 0.0 < ay_ < 0.04,
          (round(ax_, 3), round(ay_, 3)))
    shifted = len(a) == len(b) and len(a) > 0 and all(abs(p[0] - r[0] - ex) < 1e-6 and abs(p[1] - r[1] - ey) < 1e-6
                                                      for p, r in zip(a, b))
    check("obstacle points include the sensor's offset from the trunk (8.5 cm ahead)", shifted,
          (round(ex, 3), round(ey, 3), len(a), len(b)))

# The reflex's corridor: only what the duck would walk into counts.
from duck_lab.nav.cliff import blocking_ahead  # noqa: E402

pts = [(0.25, 0.30, 0.2, "obstacle"),     # a door frame to the side: passed, not hit
       (0.40, 0.05, 0.2, "obstacle"),     # straight ahead, further on
       (0.20, 0.00, 0.01, "floor"),       # floor is not an obstacle
       (-0.1, 0.00, 0.2, "obstacle")]     # behind
check("blocking_ahead: the nearest obstacle in the corridor, not the nearest in view",
      blocking_ahead(pts, 0.12) == 0.40 and blocking_ahead(pts[:1], 0.12) is None, blocking_ahead(pts, 0.12))

# The viewer's depth points: every valid return, classified as the obstacle layer classifies them.
from duck_lab.nav.cliff import depth_points  # noqa: E402

for name in ("tof-flat-0.json", "tof-flat-180.json"):
    if (runs / name).exists():
        frames = json.loads((runs / name).read_text())["frames"]
        agree = all(
            sorted((round(p[0], 6), round(p[1], 6)) for p in depth_points(f, f["state"])
                   if p[3] == "obstacle" and math.hypot(p[0], p[1]) <= 0.8)
            == sorted((round(p[0], 6), round(p[1], 6)) for p in obstacle_points(f, f["state"]))
            for f in frames)
        check(f"{name}: depth_points' obstacles are obstacle_points' points", agree)

# The sensor as mounted (calibration "tof"). The simulator's looks 2.5 deg further down than its servo angles say and reads
# along each ray; read with the real duck's values (3 deg, axial) its flat floor looked further away when the head looked near
# level, and the duck stopped for drops that were not there (the challenge course, 2026-11-16).
from duck_lab.nav import cliff  # noqa: E402

SIM_TOF = json.loads((Path(__file__).resolve().parents[1] / "calibration" / "sim.json").read_text())["tof"]
SIM_MOUNT = (SIM_TOF["pitch_offset_deg"], SIM_TOF["range"])


def sim_frame(st, floor_until_m=None, drop_m=0.3):
    """What the simulator's sensor reports: mounted as calibration/sim.json says, the distance along each zone's ray."""
    cliff.configure(*SIM_MOUNT)
    height, q = sensor_pose(st)
    dist = []
    for beam in BEAMS:
        d = rotate(q, beam)
        if d[2] >= -0.01:
            dist.append(2000)
            continue
        t = -height / d[2]
        if floor_until_m is not None and t * math.hypot(d[0], d[1]) > floor_until_m:
            t = -(height + drop_m) / d[2]
        dist.append(int(t * 1000))
    return {"distance_mm": dist, "status": [5] * 64}


try:
    cliff.configure(0.0, "slant")
    check("configure: an unknown range kind is refused", False)
except ValueError:
    check("configure: an unknown range kind is refused", True)
beam = BEAMS[0]
cliff.configure()
axial = cliff.along_beam(500, beam)
cliff.configure(0.0, "radial")
check("along_beam: axial readings are divided by the beam's axial part, radial ones are not",
      abs(axial - 0.5 / beam[0]) < 1e-12 and cliff.along_beam(500, beam) == 0.5, (axial, beam[0]))

def first_stop(frames, stop_m, needed):
    """The navigator's cliff stop: `needed` frames in a row with a drop, the last one's nearest within stop_m."""
    streak = 0
    for f in frames:
        pts = drop_points(f, f["state"])
        streak = streak + 1 if pts else 0
        if streak >= needed and min(p[2] for p in pts) < stop_m:
            return f["t"]
    return None


# The recorded false stops (sim/probes/false_drop_fixture.py): flat floor, the real duck's mounting stopped in each.
fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "flat_false_stops.json").read_text())
stops = {}
for mount in ((3.0, "axial"), SIM_MOUNT):
    cliff.configure(*mount)
    stops[mount] = [first_stop(r["frames"], fx["stop_m"], fx["frames_needed"]) for r in fx["runs"]]
check(f"recorded flat floor ({len(fx['runs'])} runs): the real duck's mounting stops for a drop in every run, as it did",
      len(fx["runs"]) == 8 and all(s is not None and abs(s - r["stop_t"]) < 1e-6 for s, r in zip(stops[(3.0, "axial")], fx["runs"])),
      stops[(3.0, "axial")])
check("recorded flat floor: the simulator's own mounting stops in none", not any(stops[SIM_MOUNT]), stops[SIM_MOUNT])

# The simulator's mounting keeps the check's reach: an 8 cm drop is seen; with no pitch offset the floor sits too high and
# a drop that shallow is not (0 deg removed the false stops too, by blinding the check).
st = state()
edge = drop_points(sim_frame(st, floor_until_m=0.45), st)
check("the simulator's floor ending 0.45 m ahead: a drop, at about 0.45 m",
      edge and 0.4 <= min(p[2] for p in edge) <= 0.55, min((p[2] for p in edge), default=None))
shallow = sim_frame(st, floor_until_m=0.45, drop_m=0.08)
cliff.configure(*SIM_MOUNT)
seen = len(drop_points(shallow, st))
cliff.configure(0.0, "radial")
blind = len(drop_points(shallow, st))
check("an 8 cm drop 0.45 m ahead: seen with the simulator's mounting, not with no pitch offset", seen > 0 and blind == 0, (seen, blind))
cliff.configure()

print("CLIFF", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
