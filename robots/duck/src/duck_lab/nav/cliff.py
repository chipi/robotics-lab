"""The cliff check (RFC-0002 §3.6, "the floor disappears ahead → stop").

The depth sensor's downward beams should meet the floor at a distance its pose predicts. Where they
read much further, the floor is not there — a staircase, a step down. Where the sensor is, and where
its beams point, are robotd's numbers (robot.state: odometry height, IMU orientation, frames.tof); the
beam geometry is Pollen's (kinematics/src/tof.rs) and mapd's settings (maploc/src/project.rs:
ranges along the optical axis, the sensor ~3° further down than the head's kinematics say).

Pure: drop_ahead(frame, state) -> distance in metres to the nearest missing floor, or None;
drop_points(frame, state) -> where the floor should have been, in the trunk's level frame (x ahead, y
left), for the beams that found none.
"""

import math

from worldmodel.objects import DUCK_LIMITS

FOV_DEG = 45.0
ROWS = COLS = 8
# The sensor as mounted on this robot (configure(), from calibration/<robot>.json): how much further down it looks than the
# head's kinematics say, and whether its readings run along the optical axis or along each zone's ray. The defaults are the
# real duck's (mapd's: 3°, axial). The simulator's reads along the ray and looks 2.5° down (calibration/sim.json); with the
# real duck's values its floor sat up to 2 cm too low, and the cliff check stopped for drops that were not there (the
# challenge course, 2026-11-16: 131 frames, 8 stops in 40 runs on flat floor).
PITCH_OFFSET_RAD = math.radians(3.0)
OVERHEAD_M = DUCK_LIMITS.overhead_m      # a return higher than this passes over the robot's head (footprint.overhead_clear_m; configure())
RANGE = "axial"


def configure(pitch_offset_deg: float = 3.0, range_kind: str = "axial", overhead_m: float = DUCK_LIMITS.overhead_m) -> None:
    global PITCH_OFFSET_RAD, RANGE, OVERHEAD_M
    if range_kind not in ("axial", "radial"):
        raise ValueError(f"range {range_kind!r}: axial or radial")
    PITCH_OFFSET_RAD, RANGE, OVERHEAD_M = math.radians(pitch_offset_deg), range_kind, overhead_m


def along_beam(mm: float, beam: tuple) -> float:
    """A zone's reading (mm) as the distance along its beam (m)."""
    return mm / 1000.0 if RANGE == "radial" else mm / 1000.0 / beam[0]
VALID = {5, 9}
NO_TARGET = 255           # the sensor's "nothing out there" status (VL53L5CX; the simulator's too)
NO_TARGET_RANGE_M = 4.0   # its range: no target means nothing nearer along the beam (microduck_rl sim/tof.py MAX_RANGE)
LOOK_M = 0.7           # only floor expected within this horizontal distance is checked
EXTRA_M = 0.06         # a return this much further than the floor (along the beam's drop) is a drop
MIN_ZONES = 2          # zones that must agree, in the central columns
# Which beams the cliff check reads: every column whose expected floor point lies within this of the
# duck's line, ahead (its corridor and the bend beside it). It used to read the central columns only,
# and exploration trial 10 walked diagonally past the stairwell's corner with the hole to its left,
# outside them, until the truth guard stopped it 5 cm from the edge.
CORRIDOR_DROP_M = 0.25


def _beams() -> list:
    half = math.radians(FOV_DEG / 2 - FOV_DEG / COLS / 2)
    step = 2 * half / (COLS - 1)
    out = []
    for i in range(ROWS * COLS):
        el = half - (i // COLS) * step
        az = half - (i % COLS) * step
        out.append((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    return out


BEAMS = _beams()


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def rotate(q, v):
    w, x, y, z = q
    p = qmul(qmul(q, (0.0, *v)), (w, -x, -y, -z))
    return p[1], p[2], p[3]


def sensor_pose(state: dict) -> tuple:
    """The depth sensor's height above the floor and orientation in a level frame (yaw kept).
    Height: trunk height from odometry plus the sensor's offset rotated by the trunk's tilt."""
    trunk_q = tuple(state["imu"]["quat"])
    tof = state["frames"]["tof"]
    offset = rotate(trunk_q, tof["pos"])
    height = state["odom"]["position"][2] + offset[2]
    q = qmul(qmul(trunk_q, tuple(tof["quat"])),
             (math.cos(PITCH_OFFSET_RAD / 2), 0.0, math.sin(PITCH_OFFSET_RAD / 2), 0.0))
    return height, q


def sensor_offset(state: dict) -> tuple:
    """Where the sensor is relative to the trunk, level and turned to the trunk's heading (ahead, left):
    about 8.5 cm ahead and 2 cm left. Points are returned relative to the trunk, where the navigator's
    pose is; without this every remembered obstacle and drop sat 8.5 cm nearer the duck (explore9)."""
    q = tuple(state["imu"]["quat"])
    off = rotate(q, state["frames"]["tof"]["pos"])
    w, x, y, z = q
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    return c * off[0] - s_ * off[1], s_ * off[0] + c * off[1]


# Higher than mapd's 3 cm: over flat floor with the head turned, returns read up to 6.5 cm above the
# predicted floor at 0.4 m (pose error); real obstacles (walls, the cabinet) read a median 14 cm.
FLOOR_MARGIN_M = 0.08      # a return lower than this (+3 cm per metre of range) is floor
FLOOR_MARGIN_PER_M = 0.03
# Below the floor margin, above this: the low band, things a few cm tall that the floor margin reads as floor (a 6.6 cm
# box, challenge 15 seed 1). One return there is noise as often as not, so the navigator keeps a low cell only once
# several frames saw it. Flat floor since the head fix (27 runs, 20 min, sim/probes/low_persistence.py): 0 cells/min
# seen in 3 frames at 3.5 cm + 2 cm/m, 8 of 10 low boxes caught (5 at the floor margin alone).
LOW_MARGIN_M = 0.035
LOW_MARGIN_PER_M = 0.02


def obstacle_points(frame: dict, state: dict, within_m: float = 0.8, low: bool = False) -> list:
    """(ahead, left) of every valid return that is an obstacle — above the floor, below the duck's
    head, within within_m of the sensor — relative to the trunk and turned to its heading. The
    reflex's memory takes all of them, not one point: a wall seen once is a wall, not a dot.
    low: the returns in the low band instead (above LOW_MARGIN_M, below the floor margin)."""
    height, q = sensor_pose(state)
    sx, sy = sensor_offset(state)
    w, x, y, z = state["imu"]["quat"]
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    out = []
    for i, beam in enumerate(BEAMS):
        if frame["status"][i] not in VALID or frame["distance_mm"][i] <= 0:
            continue
        r = along_beam(frame["distance_mm"][i], beam)
        d = rotate(q, beam)
        hx, hy = r * d[0], r * d[1]
        h = math.hypot(hx, hy)
        z = height + r * d[2]
        floor_top = FLOOR_MARGIN_M + FLOOR_MARGIN_PER_M * h
        if h > within_m or z > OVERHEAD_M:
            continue
        if (low and not LOW_MARGIN_M + LOW_MARGIN_PER_M * h <= z < floor_top) or (not low and z < floor_top):
            continue
        out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy))
    return out


def low_points(frame: dict, state: dict, within_m: float = 0.8) -> list:
    """obstacle_points' low band: returns a few cm above the floor that the floor margin takes for floor."""
    return obstacle_points(frame, state, within_m, low=True)


def depth_points(frame: dict, state: dict) -> list:
    """Every valid return as (ahead, left, height above the floor, kind), relative to the trunk and
    turned to its heading, with the same geometry and thresholds as obstacle_points: kind is
    "below" (under the floor by more than EXTRA_M: a hole), "floor", "obstacle" or "overhead". For
    the viewer, and for the floor the explorer trusts: what the sensor saw, not only what was kept."""
    height, q = sensor_pose(state)
    sx, sy = sensor_offset(state)
    w, x, y, z = state["imu"]["quat"]
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    out = []
    for i, beam in enumerate(BEAMS):
        d = rotate(q, beam)
        if frame["status"][i] not in VALID or frame["distance_mm"][i] <= 0:
            # no return where the beam meets the floor within range: no floor that near (challenge 12, a table edge
            # over a floor out of range). The floor is at least as far down as the beam's lowest point in range; the
            # point is put where the floor should have been, the near side of the hole.
            if frame["status"][i] == NO_TARGET and d[2] < 0 and -height / d[2] <= NO_TARGET_RANGE_M and \
                    height + NO_TARGET_RANGE_M * d[2] < -EXTRA_M:
                t = -height / d[2]
                hx, hy = t * d[0], t * d[1]
                out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy, height + NO_TARGET_RANGE_M * d[2], "below"))
            continue
        r = along_beam(frame["distance_mm"][i], beam)
        hx, hy = r * d[0], r * d[1]
        h = math.hypot(hx, hy)
        zz = height + r * d[2]
        kind = ("below" if zz < -EXTRA_M else "floor" if zz < FLOOR_MARGIN_M + FLOOR_MARGIN_PER_M * h else
                "overhead" if zz > OVERHEAD_M else "obstacle")
        out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy, zz, kind))
    return out


def blocking_ahead(points: list, half_width_m: float) -> float | None:
    """How far ahead (m, from the trunk) the nearest obstacle return lies inside the corridor the duck
    sweeps walking straight on — |left| within half_width_m; None when there is none. points are
    depth_points. The reflex stops on this, not on the nearest return anywhere in view: phase 1 run
    16 stopped eight times for a door frame it was passing with room to spare."""
    ahead = [p[0] for p in points if p[3] == "obstacle" and p[0] > 0 and abs(p[1]) <= half_width_m]
    return min(ahead) if ahead else None


def extend_edge(points: list, extend_m: float, step_m: float = 0.05) -> list:
    """A drop's edge, beyond what was seen: points every step_m along the line through `points`
    (x, y), extend_m past each end. A stop sees a short stretch of an edge; the hole goes on to the
    sides (trial 8 reached a target 0.3 m from a stairwell corner it had not seen)."""
    if len(points) < 2:
        return []
    mx = sum(p[0] for p in points) / len(points)
    my = sum(p[1] for p in points) / len(points)
    sxx = sum((p[0] - mx) ** 2 for p in points)
    syy = sum((p[1] - my) ** 2 for p in points)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    a = 0.5 * math.atan2(2 * sxy, sxx - syy)            # the edge's direction (principal axis)
    ux, uy = math.cos(a), math.sin(a)
    ts = [(p[0] - mx) * ux + (p[1] - my) * uy for p in points]
    out = []
    for lo, hi, sign in ((max(ts), max(ts) + extend_m, 1), (min(ts) - extend_m, min(ts), -1)):
        t = lo + step_m if sign > 0 else hi - step_m
        while (t <= hi + 1e-9) if sign > 0 else (t >= lo - 1e-9):
            out.append((mx + t * ux, my + t * uy))
            t += sign * step_m
    return out


def drop_ahead(frame: dict, state: dict) -> float | None:
    """Horizontal distance to the nearest place ahead where the floor should be and is not."""
    pts = drop_points(frame, state)
    return min(p[2] for p in pts) if pts else None


def drop_points(frame: dict, state: dict) -> list:
    """(ahead, left, horizontal distance) of each beam's expected floor point where there was no
    floor: ahead and left relative to the trunk, turned to its heading; the distance from the sensor
    (what the cliff check stops on: the nearer, so the more careful). Empty under MIN_ZONES."""
    height, q = sensor_pose(state)
    sx, sy = sensor_offset(state)
    if height <= 0.02:
        return []
    yaw_q = state["imu"]["quat"]
    w, x, y, z = yaw_q
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    drops = []
    for i, beam in enumerate(BEAMS):
        d = rotate(q, beam)
        if d[2] > -0.15:
            continue        # a beam that never reaches the floor nearby says nothing about it
        t_floor = -height / d[2]                       # slant range to the floor along this beam
        h_floor = t_floor * math.hypot(d[0], d[1])     # horizontal distance to that floor point
        if h_floor > LOOK_M:
            continue
        valid = frame["status"][i] in VALID and frame["distance_mm"][i] > 0
        if valid:
            r = along_beam(frame["distance_mm"][i], beam)
            if r * -d[2] < height + EXTRA_M:
                continue    # it reached the floor (or something on it): no drop here
        wx, wy = t_floor * d[0], t_floor * d[1]          # level frame, world-aligned yaw
        ahead, left = sx + c * wx - s_ * wy, sy + s_ * wx + c * wy
        if abs(left) > CORRIDOR_DROP_M:
            continue        # beside the duck's way, not on it
        drops.append((ahead, left, h_floor))
    return drops if len(drops) >= MIN_ZONES else []
