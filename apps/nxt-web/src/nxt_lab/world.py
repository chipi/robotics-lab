"""A small 2D world for the simulated NXT (SimRobot): differential kinematics from the two track powers, collision with
the scene's boxes, and an ultrasonic cone cast. Pure Python, no third-party code.

Truth is this model's ideal pose. Odometry (the recorder's tacho-based belief) never reads it, so the two differ the way
they would on the floor: the sim turns at turn_slip of the commanded rate, the tachos count the commanded motion.

Every number in WorldParams is an assumption until D1 measures it on the brick (NXT-MVP1.md); none is a measurement."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from runfile import scenefile


@dataclass
class WorldParams:
    # K16's assumed full speeds (KNOWN-ISSUES.md), the same two numbers robots.nxt/nxt-1.json carries.
    speed_m_s: float = 0.3            # both tracks at +100
    turn_rad_s: float = 1.5           # the tracks at +100 and -100
    turn_slip: float = 0.9            # share of the commanded turn the tracks achieve; a guess, nothing measured it
    # The footprint the run format draws (runfile adapters/nxt.py FOOTPRINT). A circle: turning never penetrates.
    body_radius_m: float = 0.10
    body_height_m: float = 0.12
    # The ultrasonic. UNVERIFIED: cone, range and resolution are from memory of the sensor's data sheet, not checked
    # against the brick; its height and angle are for D1 to measure.
    us_forward_m: float = 0.10        # from the body's centre along its heading
    us_height_m: float = 0.08
    us_cone_deg: float = 30.0         # full angle
    us_max_cm: int = 255              # what the sensor reads with nothing in range
    us_resolution_cm: int = 1
    us_rays: int = 9                  # rays across the cone; thin things can fall between them
    # About what an NXT motor does unloaded; the same number FakeRobot uses.
    tacho_deg_s_per_power: float = 9.0
    step_s: float = 0.02              # integration step: the obstacle stop is tested at this grain

    def validate(self) -> None:
        for name in ("speed_m_s", "turn_rad_s", "body_radius_m", "body_height_m", "us_max_cm", "us_resolution_cm",
                     "tacho_deg_s_per_power", "step_s", "us_cone_deg"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be above 0")
        if not 0 < self.turn_slip <= 1:
            raise ValueError("turn_slip must be above 0 and at most 1")
        if not 0 < self.us_cone_deg < 180:
            raise ValueError("us_cone_deg must be between 0 and 180")
        if self.us_rays < 1:
            raise ValueError("us_rays must be at least 1")

    @classmethod
    def from_dict(cls, data: dict) -> "WorldParams":
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown world parameter(s): {sorted(unknown)}")
        params = cls(**data)
        params.validate()
        return params

    def to_dict(self) -> dict:
        return asdict(self)

    def track_geometry(self) -> tuple:
        """(sprocket diameter, track width) in metres that read this model's own tachos back as its commanded motion: the wheel
        geometry of a sim run when the config has none. Not a measurement of the brick; the sim's slip is what the belief misses."""
        m_per_deg = self.speed_m_s / (100.0 * self.tacho_deg_s_per_power)
        return m_per_deg * 360.0 / math.pi, 2.0 * self.speed_m_s / self.turn_rad_s


@dataclass
class Box:
    """A scene.json box: a rotated rectangle `hx` by `hy` around (cx, cy), between heights z0 and z1."""

    name: str
    cx: float
    cy: float
    z0: float
    z1: float
    hx: float
    hy: float
    yaw: float = 0.0

    def local(self, x: float, y: float) -> tuple:
        c, s = math.cos(-self.yaw), math.sin(-self.yaw)
        px, py = x - self.cx, y - self.cy
        return c * px - s * py, s * px + c * py

    def gap(self, x: float, y: float) -> float:
        """Distance from a point to the box's footprint, 0 inside it."""
        lx, ly = self.local(x, y)
        return math.hypot(max(abs(lx) - self.hx, 0.0), max(abs(ly) - self.hy, 0.0))


def ray_box_distance(ox: float, oy: float, angle: float, box: Box, max_m: float) -> float | None:
    """Distance along a ray from (ox, oy) to a box's footprint, None when it is missed or farther than max_m. The slab test
    of labrunner's `_segment_hits_box` (sim_camera.py), in its distance form: it keeps the entry parameter t0 that the hit
    test throws away. A copy, because nxt-web's environment does not carry the runner."""
    lx, ly = box.local(ox, oy)
    c, s = math.cos(angle - box.yaw), math.sin(angle - box.yaw)   # the ray's direction in the box's frame
    t0, t1 = 0.0, max_m
    for p, d, h in ((lx, c, box.hx), (ly, s, box.hy)):
        if abs(d) < 1e-12:
            if abs(p) > h:
                return None
            continue
        u, v = (-h - p) / d, (h - p) / d
        t0, t1 = max(t0, min(u, v)), min(t1, max(u, v))
        if t0 > t1:
            return None
    return t0


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class World:
    def __init__(self, boxes: list, bounds: list | None, params: WorldParams | None = None,
                 start: tuple = (0.0, 0.0, 0.0), scene_id: str = "", scene_sha256: str = "",
                 scene_path: str = "", scene_checksum: str = ""):
        self.params = params or WorldParams()
        self.params.validate()
        self.scene_id, self.scene_sha256 = scene_id, scene_sha256
        # the file's path and runfile's checksum of it (scenefile.describe), taken when the world was: what a run records it was in
        self.scene_path, self.scene_checksum = scene_path, scene_checksum
        self.bounds = bounds
        # Boxes wholly below the floor (the stairwell's steps) cannot be hit; a table top above the body's height cannot either.
        self.blockers = [b for b in boxes if b.z1 > 0.0 and b.z0 < self.params.body_height_m]
        self.echoes = [b for b in boxes if b.z0 <= self.params.us_height_m <= b.z1]
        self.start = start
        self.contact = False
        self.reset(start)

    @classmethod
    def from_scene(cls, path, params: WorldParams | None = None, start: tuple = (0.0, 0.0, 0.0)) -> "World":
        raw = Path(path).read_bytes()
        scene = json.loads(raw)
        boxes = [Box(**{k: b[k] for k in ("name", "cx", "cy", "z0", "z1", "hx", "hy")}, yaw=b.get("yaw", 0.0))
                 for b in scene["boxes"]]
        return cls(boxes, scene.get("bounds"), params, start, scene.get("id", ""), hashlib.sha256(raw).hexdigest(),
                   str(Path(path).resolve()), scenefile.checksum(scene))

    def reset(self, start: tuple | None = None) -> None:
        """Back to the start pose; the model is settled the moment it returns (no simulator to wait for)."""
        if start is not None:
            self.start = start
        x, y, yaw = self.start
        if not self._free(x, y):
            raise ValueError(f"the start pose ({x}, {y}) is inside a box or outside the bounds")
        self.x, self.y, self.yaw = x, y, _wrap(yaw)
        self.contact = False

    def pose(self) -> tuple:
        return (self.x, self.y, self.yaw)

    def _free(self, x: float, y: float) -> bool:
        r = self.params.body_radius_m - 1e-9
        if self.bounds is not None:
            x0, x1, y0, y1 = self.bounds
            if x - r < x0 or x + r > x1 or y - r < y0 or y + r > y1:
                return False
        return all(b.gap(x, y) >= r for b in self.blockers)

    def step(self, left: int, right: int, dt: float) -> None:
        """Advance dt seconds on track powers (-100..100, forward as the robot sees it). A move that would penetrate a box
        goes as far as contact and no further; the turn goes on, so a stuck robot can still turn away."""
        p = self.params
        v = (left + right) / 200.0 * p.speed_m_s
        w = (right - left) / 200.0 * p.turn_rad_s * p.turn_slip
        heading = self.yaw + w * dt / 2.0
        dx, dy = v * dt * math.cos(heading), v * dt * math.sin(heading)
        self.contact = False
        if self._free(self.x + dx, self.y + dy):
            self.x, self.y = self.x + dx, self.y + dy
        elif dx or dy:
            lo, hi = 0.0, 1.0
            for _ in range(12):
                f = (lo + hi) / 2.0
                lo, hi = (f, hi) if self._free(self.x + f * dx, self.y + f * dy) else (lo, f)
            self.x, self.y = self.x + lo * dx, self.y + lo * dy
            self.contact = True
        self.yaw = _wrap(self.yaw + w * dt)

    def range_cm(self) -> int:
        """What the ultrasonic reads from the current pose: the nearest echo across the cone, in whole resolution steps."""
        p = self.params
        ox = self.x + p.us_forward_m * math.cos(self.yaw)
        oy = self.y + p.us_forward_m * math.sin(self.yaw)
        half = math.radians(p.us_cone_deg) / 2.0
        best = p.us_max_cm / 100.0
        for k in range(p.us_rays):
            offset = 0.0 if p.us_rays == 1 else -half + k * 2.0 * half / (p.us_rays - 1)
            for box in self.echoes:
                t = ray_box_distance(ox, oy, self.yaw + offset, box, best)
                if t is not None and t < best:
                    best = t
        steps = round(best * 100.0 / p.us_resolution_cm)
        return min(p.us_max_cm, int(steps * p.us_resolution_cm))
