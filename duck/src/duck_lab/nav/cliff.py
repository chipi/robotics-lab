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

FOV_DEG = 45.0
ROWS = COLS = 8
PITCH_OFFSET_RAD = math.radians(3.0)
VALID = {5, 9}
LOOK_M = 0.7           # only floor expected within this horizontal distance is checked
EXTRA_M = 0.06         # a return this much further than the floor (along the beam's drop) is a drop
MIN_ZONES = 2          # zones that must agree, in the central columns
CENTRAL = range(2, 6)


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


# Higher than mapd's 3 cm: over flat floor with the head turned, returns read up to 6.5 cm above the
# predicted floor at 0.4 m (pose error); real obstacles (walls, the cabinet) read a median 14 cm.
FLOOR_MARGIN_M = 0.08      # a return lower than this (+3 cm per metre of range) is floor
FLOOR_MARGIN_PER_M = 0.03
OVERHEAD_M = 0.30          # above the duck's head (27.2 cm): passes over it


def obstacle_points(frame: dict, state: dict, within_m: float = 0.8) -> list:
    """(ahead, left) of every valid return that is an obstacle — above the floor, below the duck's
    head, within within_m — relative to the sensor and turned to the trunk's heading. The reflex's
    memory takes all of them, not one point: a wall seen once is a wall, not a dot."""
    height, q = sensor_pose(state)
    w, x, y, z = state["imu"]["quat"]
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    out = []
    for i, beam in enumerate(BEAMS):
        if frame["status"][i] not in VALID or frame["distance_mm"][i] <= 0:
            continue
        r = frame["distance_mm"][i] / 1000.0 / beam[0]
        d = rotate(q, beam)
        hx, hy = r * d[0], r * d[1]
        h = math.hypot(hx, hy)
        z = height + r * d[2]
        if h > within_m or z < FLOOR_MARGIN_M + FLOOR_MARGIN_PER_M * h or z > OVERHEAD_M:
            continue
        out.append((c * hx - s_ * hy, s_ * hx + c * hy))
    return out


def depth_points(frame: dict, state: dict) -> list:
    """Every valid return as (ahead, left, height above the floor, kind), relative to the sensor and
    turned to the trunk's heading, with the same geometry and thresholds as obstacle_points: kind is
    "floor", "obstacle" or "overhead". For the viewer: what the sensor saw, not only what was kept."""
    height, q = sensor_pose(state)
    w, x, y, z = state["imu"]["quat"]
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    out = []
    for i, beam in enumerate(BEAMS):
        if frame["status"][i] not in VALID or frame["distance_mm"][i] <= 0:
            continue
        r = frame["distance_mm"][i] / 1000.0 / beam[0]
        d = rotate(q, beam)
        hx, hy = r * d[0], r * d[1]
        h = math.hypot(hx, hy)
        zz = height + r * d[2]
        kind = ("floor" if zz < FLOOR_MARGIN_M + FLOOR_MARGIN_PER_M * h else
                "overhead" if zz > OVERHEAD_M else "obstacle")
        out.append((c * hx - s_ * hy, s_ * hx + c * hy, zz, kind))
    return out


def drop_ahead(frame: dict, state: dict) -> float | None:
    """Horizontal distance to the nearest place ahead where the floor should be and is not."""
    pts = drop_points(frame, state)
    return min(p[2] for p in pts) if pts else None


def drop_points(frame: dict, state: dict) -> list:
    """(ahead, left, horizontal distance) of each beam's expected floor point where there was no
    floor, relative to the sensor and turned to the trunk's heading; empty under MIN_ZONES."""
    height, q = sensor_pose(state)
    if height <= 0.02:
        return []
    yaw_q = state["imu"]["quat"]
    w, x, y, z = yaw_q
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    c, s_ = math.cos(-yaw), math.sin(-yaw)
    drops = []
    for i, beam in enumerate(BEAMS):
        if i % COLS not in CENTRAL:
            continue
        d = rotate(q, beam)
        if d[2] > -0.15:
            continue        # a beam that never reaches the floor nearby says nothing about it
        t_floor = -height / d[2]                       # slant range to the floor along this beam
        h_floor = t_floor * math.hypot(d[0], d[1])     # horizontal distance to that floor point
        if h_floor > LOOK_M:
            continue
        valid = frame["status"][i] in VALID and frame["distance_mm"][i] > 0
        if valid:
            r = frame["distance_mm"][i] / 1000.0 / beam[0]   # axial reading -> along the beam
            if r * -d[2] < height + EXTRA_M:
                continue    # it reached the floor (or something on it): no drop here
        wx, wy = t_floor * d[0], t_floor * d[1]          # level frame, world-aligned yaw
        drops.append((c * wx - s_ * wy, s_ * wx + c * wy, h_floor))
    return drops if len(drops) >= MIN_ZONES else []
