"""The duck's range sensing (RFC-0020 §4, `tof8x8@1`): the 8x8 depth sensor (a VL53L5CX in its head, 45 degrees square), what a
frame of it says about obstacles, floor and drops, and how the navigator reads its stream.

The cliff check (RFC-0002 §3.6, "the floor disappears ahead → stop"): the sensor's downward beams should meet the floor at a distance
its pose predicts. Where they read much further, the floor is not there — a staircase, a step down. Where the sensor is, and where
its beams point, are robotd's numbers (robot.state: odometry height, IMU orientation, frames.tof); the beam geometry is Pollen's
(kinematics/src/tof.rs) and mapd's settings (maploc/src/project.rs: ranges along the optical axis, the sensor ~3° further down than
the head's kinematics say).

The sensor as mounted on this robot is the profile's `sensors.tof8x8.mount`: how much further down it looks than the head's
kinematics say, and whether its readings run along the optical axis or along each zone's ray. The real duck's are mapd's (3°,
axial). The simulator's reads along the ray and looks 2.5° down; with the real duck's values its floor sat up to 2 cm too low, and
the cliff check stopped for drops that were not there (the challenge course, 2026-11-16: 131 frames, 8 stops in 40 runs on flat
floor). That mount is instance state here, not a module's: two sensors can be mounted differently in one process.

The numbers are the profile's (robots/duck/profile.json `sensors.tof8x8`, with `footprint.overhead_clear_m` and
`error_budget.corridor_m`): `fov_deg`, `rows`, `cols`; `valid_status` and `no_target_status` (VL53L5CX: "range valid", "nothing out
there", the simulator's too) and `range_m` (its range: no target means nothing nearer along the beam); `look_m` (only floor expected
within this horizontal distance is checked); `extra_m` (a return this much further than the floor is a drop); `min_zones` (zones that
must agree); `corridor_m` (every column whose expected floor point lies within this of the duck's line, ahead: its corridor and the
bend beside it; exploration trial 10 walked diagonally past the stairwell's corner with the hole to its left, outside the central
columns, until the truth guard stopped it 5 cm from the edge); `floor_margin_m` + `floor_margin_per_m` per metre of range (higher than
mapd's 3 cm: over flat floor with the head turned, returns read up to 6.5 cm above the predicted floor at 0.4 m, pose error; real
obstacles read a median 14 cm); `low_margin_m` + `low_margin_per_m` (the low band, things a few cm tall that the floor margin reads as
floor: a 6.6 cm box, challenge 15 seed 1); `reflex_ahead_m`, `reflex_margin_m` and `emergency_mm` (the depth reflex: an obstacle
return inside the corridor the duck sweeps, its radius and the margin, within reflex_ahead_m stops it; so does any return at all within
emergency_mm of the sensor; phase 1 run 16 stopped eight times for a door frame it was passing with room to spare);
`side_drops.below_slope` (how much more below the floor a far return must read to count as a hole: the trunk's sway pitches a far floor
return a few cm low); `floor_view` (look before you step, stream A 2026-11-17: the duck walks only over floor its depth sensor has seen;
exploring batch b2 run 2 cut the staircase opening's corner, which was never in the 45 deg wedge, first beside the duck, then a few cm
left of the wedge's edge, the corner itself in the blind zone under the head: the strip from_m to to_m of walking ahead, half_width_m
either side, is checked against the floor the sensor has seen).
"""

import json
import math
import socket
import threading

STEP_M = 0.05       # the floor-view probe spacing, along and across: the floor cells are 5 cm (run.FLOOR_CELL_M)


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def rotate(q, v):
    w, x, y, z = q
    p = qmul(qmul(q, (0.0, *v)), (w, -x, -y, -z))
    return p[1], p[2], p[3]


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


class FrameView:
    """One depth frame, the robot state it was paired with and what the navigator makes of it, derived once: the points
    (map metres, for the viewer and the floor memory), the drop points, the blocking distance. Everything that reads the
    frame (the cliff check, the reflex, the obstacle memory, the log) reads this, so what is logged is what was used.
    The sensor that derived it says what the corridor the duck sweeps is (its radius and the reflex margin)."""

    def __init__(self, sensor: "Tof8x8", frame: dict, state: dict | None, dt_ms: float | None, pose: tuple | None):
        self.sensor, self.frame, self.state, self.dt_ms, self.pose = sensor, frame, state, dt_ms, pose
        self.rel = self.drops = self.block = self.points = None
        self.ok = False
        if state is None:
            return
        try:
            self.rel = sensor.depth_points(frame, state)
            self.drops = sensor.drop_points(frame, state)
        except (KeyError, TypeError, ValueError):
            return
        self.ok = True
        self.block = sensor.blocking_ahead(self.rel, sensor.reflex_half_w_m)
        if pose is not None:
            c, s_ = math.cos(pose[2]), math.sin(pose[2])
            self.points = [[round(pose[0] + c * ax - s_ * ay, 3), round(pose[1] + s_ * ax + c * ay, 3), round(z, 3), kind[0]]
                           for ax, ay, z, kind in self.rel]

    def payload(self) -> dict:
        """The depth_frame record (runfile.wire): the raw frame, its times, the paired state's replay fields, the pose and
        what was derived."""
        fr = self.frame
        p = {"rows": fr["rows"], "cols": fr["cols"], "distance_mm": list(fr["distance_mm"]), "status": list(fr["status"]),
             "frame_t_ns": int(fr.get("t_ns") or 0), "seq": fr.get("seq")}
        if self.state is not None and "t_ns" in self.state:
            p["state_t_ns"] = int(self.state["t_ns"])
            if self.dt_ms is not None:
                p["pair_dt_ms"] = round(self.dt_ms, 3)
        if self.ok:
            st = self.state
            p["state"] = {"quat": list(st["imu"]["quat"]), "odom_z": st["odom"]["position"][2],
                          "tof": {"pos": list(st["frames"]["tof"]["pos"]), "quat": list(st["frames"]["tof"]["quat"])}}
            if self.pose is not None:
                p["pose"] = list(self.pose[:3])          # as it was used, not rounded: a replay places the points with it
                p["derived"] = {"points": self.points, "drop_points": [list(d) for d in self.drops]}
                if self.block is not None:
                    p["derived"]["block_m"] = self.block
        return p


class Tof8x8:
    name = "tof8x8"
    version = 1

    def __init__(self, profile, mount: dict | None = None):
        """mount: {pitch_offset_deg, range_kind} to read the sensor by instead of the profile's (a replay of a run recorded with another
        mounting)."""
        t = profile.sensors.tof8x8
        self.fov_deg, self.rows, self.cols = t.fov_deg, t.rows, t.cols
        self.valid = set(t.valid_status)
        self.no_target, self.range_m, self.look_m, self.extra_m, self.min_zones = t.no_target_status, t.range_m, t.look_m, t.extra_m, t.min_zones
        self.corridor_m = profile.error_budget.corridor_m
        self.overhead_m = profile.footprint.overhead_clear_m
        self.floor_margin_m, self.floor_margin_per_m = t.floor_margin_m, t.floor_margin_per_m
        self.low_margin_m, self.low_margin_per_m = t.low_margin_m, t.low_margin_per_m
        mount = mount or {"pitch_offset_deg": t.mount.pitch_offset_deg, "range_kind": t.mount.range_kind}
        self.pitch_offset_rad, self.range_kind = math.radians(mount["pitch_offset_deg"]), mount["range_kind"]
        if self.range_kind not in ("axial", "radial"):
            raise ValueError(f"range {self.range_kind!r}: axial or radial")
        self.reflex_ahead_m, self.emergency_mm = t.reflex_ahead_m, t.emergency_mm
        self.reflex_half_w_m = profile.footprint.radius_m + t.reflex_margin_m
        self.below_slope = t.side_drops.below_slope
        self.view = t.floor_view
        self.beams = self._beams()
        self.on_frame = None             # called with each frame (the navigator derives, logs and remembers it)
        self.last, self.frames = None, 0
        self._nearest_mm = None
        self._sock = self._f = None
        self._stop = threading.Event()

    # ---- the stream ------------------------------------------------------------------------------------------------------
    def open(self, path) -> None:
        """tof.stream in a thread; keeps the nearest valid distance in the central columns."""
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.connect(str(path))
        self._sock.settimeout(1.0)
        self._f = self._sock.makefile("rw")
        self._f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
        self._f.flush()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                line = self._f.readline()
            except (TimeoutError, socket.timeout):
                continue
            if not line:
                return
            msg = json.loads(line)
            if msg.get("method") != "tof.frame":
                continue
            fr = msg["params"]
            self.last = fr
            rows, cols = fr["rows"], fr["cols"]
            central = range(cols // 2 - 2, cols // 2 + 2)
            near = [fr["distance_mm"][r * cols + c] for r in range(rows) for c in central
                    if fr["status"][r * cols + c] in self.valid and fr["distance_mm"][r * cols + c] > 0]
            self._nearest_mm = min(near) if near else None
            self.frames += 1
            if self.on_frame:
                self.on_frame(fr)

    def nearest_mm(self) -> float | None:
        return self._nearest_mm

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()

    def derive(self, frame: dict, state: dict | None, dt_ms: float | None, pose: tuple | None) -> FrameView:
        return FrameView(self, frame, state, dt_ms, pose)

    # ---- the geometry ----------------------------------------------------------------------------------------------------
    def _beams(self) -> list:
        half = math.radians(self.fov_deg / 2 - self.fov_deg / self.cols / 2)
        step = 2 * half / (self.cols - 1)
        out = []
        for i in range(self.rows * self.cols):
            el = half - (i // self.cols) * step
            az = half - (i % self.cols) * step
            out.append((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
        return out

    def along_beam(self, mm: float, beam: tuple) -> float:
        """A zone's reading (mm) as the distance along its beam (m)."""
        return mm / 1000.0 if self.range_kind == "radial" else mm / 1000.0 / beam[0]

    def sensor_pose(self, state: dict) -> tuple:
        """The depth sensor's height above the floor and orientation in a level frame (yaw kept).
        Height: trunk height from odometry plus the sensor's offset rotated by the trunk's tilt."""
        trunk_q = tuple(state["imu"]["quat"])
        tof = state["frames"]["tof"]
        offset = rotate(trunk_q, tof["pos"])
        height = state["odom"]["position"][2] + offset[2]
        q = qmul(qmul(trunk_q, tuple(tof["quat"])),
                 (math.cos(self.pitch_offset_rad / 2), 0.0, math.sin(self.pitch_offset_rad / 2), 0.0))
        return height, q

    @staticmethod
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

    def obstacle_points(self, frame: dict, state: dict, within_m: float = 0.8, low: bool = False) -> list:
        """(ahead, left) of every valid return that is an obstacle — above the floor, below the duck's
        head, within within_m of the sensor — relative to the trunk and turned to its heading. The
        reflex's memory takes all of them, not one point: a wall seen once is a wall, not a dot.
        low: the returns in the low band instead (above the low margin, below the floor margin)."""
        height, q = self.sensor_pose(state)
        sx, sy = self.sensor_offset(state)
        w, x, y, z = state["imu"]["quat"]
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        c, s_ = math.cos(-yaw), math.sin(-yaw)
        out = []
        for i, beam in enumerate(self.beams):
            if frame["status"][i] not in self.valid or frame["distance_mm"][i] <= 0:
                continue
            r = self.along_beam(frame["distance_mm"][i], beam)
            d = rotate(q, beam)
            hx, hy = r * d[0], r * d[1]
            h = math.hypot(hx, hy)
            z = height + r * d[2]
            floor_top = self.floor_margin_m + self.floor_margin_per_m * h
            if h > within_m or z > self.overhead_m:
                continue
            if (low and not self.low_margin_m + self.low_margin_per_m * h <= z < floor_top) or (not low and z < floor_top):
                continue
            out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy))
        return out

    def low_points(self, frame: dict, state: dict, within_m: float = 0.8) -> list:
        """obstacle_points' low band: returns a few cm above the floor that the floor margin takes for floor."""
        return self.obstacle_points(frame, state, within_m, low=True)

    def depth_points(self, frame: dict, state: dict) -> list:
        """Every valid return as (ahead, left, height above the floor, kind), relative to the trunk and
        turned to its heading, with the same geometry and thresholds as obstacle_points: kind is
        "below" (under the floor by more than extra_m: a hole), "floor", "obstacle" or "overhead". For
        the viewer, and for the floor the explorer trusts: what the sensor saw, not only what was kept."""
        height, q = self.sensor_pose(state)
        sx, sy = self.sensor_offset(state)
        w, x, y, z = state["imu"]["quat"]
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        c, s_ = math.cos(-yaw), math.sin(-yaw)
        out = []
        for i, beam in enumerate(self.beams):
            d = rotate(q, beam)
            if frame["status"][i] not in self.valid or frame["distance_mm"][i] <= 0:
                # no return where the beam meets the floor within range: no floor that near (challenge 12, a table edge
                # over a floor out of range). The floor is at least as far down as the beam's lowest point in range; the
                # point is put where the floor should have been, the near side of the hole.
                if frame["status"][i] == self.no_target and d[2] < 0 and -height / d[2] <= self.range_m and \
                        height + self.range_m * d[2] < -self.extra_m:
                    t = -height / d[2]
                    hx, hy = t * d[0], t * d[1]
                    out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy, height + self.range_m * d[2], "below"))
                continue
            r = self.along_beam(frame["distance_mm"][i], beam)
            hx, hy = r * d[0], r * d[1]
            h = math.hypot(hx, hy)
            zz = height + r * d[2]
            kind = ("below" if zz < -self.extra_m else "floor" if zz < self.floor_margin_m + self.floor_margin_per_m * h else
                    "overhead" if zz > self.overhead_m else "obstacle")
            out.append((sx + c * hx - s_ * hy, sy + s_ * hx + c * hy, zz, kind))
        return out

    @staticmethod
    def blocking_ahead(points: list, half_width_m: float) -> float | None:
        """How far ahead (m, from the trunk) the nearest obstacle return lies inside the corridor the duck
        sweeps walking straight on — |left| within half_width_m; None when there is none. points are
        depth_points. The reflex stops on this, not on the nearest return anywhere in view: phase 1 run
        16 stopped eight times for a door frame it was passing with room to spare."""
        ahead = [p[0] for p in points if p[3] == "obstacle" and p[0] > 0 and abs(p[1]) <= half_width_m]
        return min(ahead) if ahead else None

    def drop_ahead(self, frame: dict, state: dict) -> float | None:
        """Horizontal distance to the nearest place ahead where the floor should be and is not."""
        pts = self.drop_points(frame, state)
        return min(p[2] for p in pts) if pts else None

    def drop_points(self, frame: dict, state: dict) -> list:
        """(ahead, left, horizontal distance) of each beam's expected floor point where there was no
        floor: ahead and left relative to the trunk, turned to its heading; the distance from the sensor
        (what the cliff check stops on: the nearer, so the more careful). Empty under min_zones."""
        height, q = self.sensor_pose(state)
        sx, sy = self.sensor_offset(state)
        if height <= 0.02:
            return []
        yaw_q = state["imu"]["quat"]
        w, x, y, z = yaw_q
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        c, s_ = math.cos(-yaw), math.sin(-yaw)
        drops = []
        for i, beam in enumerate(self.beams):
            d = rotate(q, beam)
            if d[2] > -0.15:
                continue        # a beam that never reaches the floor nearby says nothing about it
            t_floor = -height / d[2]                       # slant range to the floor along this beam
            h_floor = t_floor * math.hypot(d[0], d[1])     # horizontal distance to that floor point
            if h_floor > self.look_m:
                continue
            valid = frame["status"][i] in self.valid and frame["distance_mm"][i] > 0
            if valid:
                r = self.along_beam(frame["distance_mm"][i], beam)
                if r * -d[2] < height + self.extra_m:
                    continue    # it reached the floor (or something on it): no drop here
            wx, wy = t_floor * d[0], t_floor * d[1]          # level frame, world-aligned yaw
            ahead, left = sx + c * wx - s_ * wy, sy + s_ * wx + c * wy
            if abs(left) > self.corridor_m:
                continue        # beside the duck's way, not on it
            drops.append((ahead, left, h_floor))
        return drops if len(drops) >= self.min_zones else []

    def below_counts(self, height_m: float, range_m: float) -> bool:
        """A below-floor return (height above the floor, negative) deep enough for its range to count toward a suspicion:
        extra_m at the duck, below_slope more a metre. A far floor return read just past extra_m is the trunk's pitch
        (walking sway), not a hole: 3 deg at 1.5 m is 8 cm (the false suspicions that closed challenge 10's goal sat 6.6-7.9
        cm below, 1.1-2.4 m away)."""
        return height_m <= -(self.extra_m + self.below_slope * range_m)

    # ---- look before you step ------------------------------------------------------------------------------------------
    def strip(self, path_ahead: list, pose: tuple, from_m: float | None = None, to_m: float | None = None,
              half_width_m: float | None = None, step_m: float = STEP_M) -> list:
        """Probe points covering the part of the path between from_m and to_m of walking from the pose, across the duck's
        width, nearest first. The path is followed from the pose through path_ahead's points. Nearer than from_m the sensor cannot
        see the floor (under the head): seen on the way, or not checked; to_m is about a second and a half of walking."""
        from_m = self.view.from_m if from_m is None else from_m
        to_m = self.view.to_m if to_m is None else to_m
        half_width_m = self.view.half_width_m if half_width_m is None else half_width_m
        pts = [tuple(pose[:2])] + [tuple(q[:2]) for q in path_ahead]
        out, walked = [], 0.0
        for a, b in zip(pts, pts[1:]):
            seg = math.dist(a, b)
            if seg == 0:
                continue
            ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
            s = 0.0
            while s <= seg:
                d = walked + s
                if d > to_m:
                    return out
                if d >= from_m:
                    cx, cy = a[0] + ux * s, a[1] + uy * s
                    n = round(half_width_m / step_m)
                    for k in sorted(range(-n, n + 1), key=abs):
                        out.append((cx - uy * k * step_m, cy + ux * k * step_m))
                s += step_m
            walked += seg
        return out

    def unseen_ahead(self, path_ahead: list, pose: tuple, seen, skip=(), **kw) -> tuple | None:
        """The nearest probe point of the strip ahead where seen(point) is false, or None when the sensor has seen floor
        under all of it. skip: points already looked at and found walkable or settled otherwise (within STEP_M)."""
        for p in self.strip(path_ahead, pose, **kw):
            if seen(p):
                continue
            if any(math.dist(p, q) <= STEP_M for q in skip):
                continue
            return p
        return None
