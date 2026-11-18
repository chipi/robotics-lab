"""Dead reckoning with fixes (RFC-0002 §3.7): odometry is smooth and drifts, mapd's pose is a fix.

The navigator keeps one transform, map ← odom: at each mapd pose, the map pose composed with the
inverse of the odometry pose at the same t_ns. Between fixes, the pose on the map is that transform
applied to the latest odometry. Poses are (x, y, yaw).

Two things sit on top of that (RFC-0016 §4; the run explore-b10a-r1, where one fix moved the belief 0.9 m while the
duck pivoted and the duck later touched a landmark): a gate on a fix that would move the belief more than max_jump_m
(it is held, and taken only when HOLD_N fixes in a row agree with each other), and an offset, the landmarks' correction
(nudge), kept across fixes — each fix replaces the transform, so a correction made once would be gone in a second.
"""

import math

HOLD_N = 5               # fixes in a row that must agree before a jump is taken (at one fix a second: 5 s)
HOLD_AGREE_M = 0.15      # ... agreeing to within this and HOLD_AGREE_RAD
HOLD_AGREE_RAD = 0.1
OFFSET_MAX_M = 1.0       # the landmarks' total correction never exceeds this
OFFSET_HALF_S = 90.0     # ... and it halves in this time: mapd corrects itself too, and an old correction would then double it


def compose(a: tuple, b: tuple) -> tuple:
    """a ∘ b: b expressed in a's parent frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], math.atan2(math.sin(a[2] + b[2]),
                                                                              math.cos(a[2] + b[2]))


def inverse(a: tuple) -> tuple:
    c, s = math.cos(a[2]), math.sin(a[2])
    return -c * a[0] - s * a[1], s * a[0] - c * a[1], -a[2]


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


class Localizer:
    def __init__(self, history: int = 200, max_jump_m: float | None = None, hold_n: int | None = HOLD_N):
        self.map_from_odom = None
        self._odom = []          # (t_ns, pose), newest last
        self._history = history
        self.max_jump_m = max_jump_m      # None: every fix is taken
        self.hold_n = hold_n              # fixes in a row that must agree before a held jump is taken; None: never
        self.offset = (0.0, 0.0)          # the landmarks' correction, added to every fix's transform
        self._held = []                   # the transforms of the fixes held back, in a row
        self._fix_t_ns = None
        self.rejected = 0
        self.last_fix = None              # what the latest fix was, for the run's record

    def on_odom(self, t_ns: int, pose: tuple) -> None:
        self._odom.append((t_ns, pose))
        del self._odom[:-self._history]

    def on_fix(self, t_ns: int, map_pose: tuple) -> bool:
        """A mapd pose. Returns False when no odometry near that time is held. With max_jump_m, a fix that would move the
        belief further is held (last_fix["status"] "held"; the belief stays) until HOLD_N in a row agree ("late"); it still
        returns True. last_fix says what it was: the raw pose, its t_ns, the odometry paired with it, the belief before and
        after and how far it moved."""
        near = min(self._odom, key=lambda e: abs(e[0] - t_ns), default=None)
        if near is None or abs(near[0] - t_ns) > 100_000_000:
            return False
        if self._fix_t_ns is not None and t_ns > self._fix_t_ns:
            k = 0.5 ** ((t_ns - self._fix_t_ns) / 1e9 / OFFSET_HALF_S)
            self.offset = (self.offset[0] * k, self.offset[1] * k)
        self._fix_t_ns = t_ns
        new = compose(map_pose, inverse(near[1]))
        new = (new[0] + self.offset[0], new[1] + self.offset[1], new[2])
        before = None if self.map_from_odom is None else compose(self.map_from_odom, near[1])
        after = compose(new, near[1])
        jump = 0.0 if before is None else math.dist(before[:2], after[:2])
        status = "taken"
        if before is not None and self.max_jump_m is not None and (jump > self.max_jump_m
                                                                  or abs(_wrap(after[2] - before[2])) > 0.35):
            if self._held and (math.dist(self._held[-1][:2], new[:2]) > HOLD_AGREE_M
                               or abs(_wrap(self._held[-1][2] - new[2])) > HOLD_AGREE_RAD):
                self._held = []
            self._held = (self._held + [new])[-(self.hold_n or HOLD_N):]
            self.rejected += 1
            status = "late" if self.hold_n is not None and len(self._held) >= self.hold_n else "held"
        if status != "held":
            self.map_from_odom = new
            self._held = []
        self.last_fix = {"status": status, "t_ns": t_ns, "raw": [round(v, 4) for v in map_pose],
                         "odom_t_ns": near[0], "odom": [round(v, 4) for v in near[1]],
                         "before": None if before is None else [round(v, 4) for v in before],
                         "after": [round(v, 4) for v in after], "moved_m": round(jump, 3)}
        return True

    def nudge(self, dx: float, dy: float) -> tuple:
        """The landmarks' correction: move the belief by (dx, dy) on the map, kept across fixes; the total is capped at
        OFFSET_MAX_M. Returns the step taken."""
        ox, oy = self.offset[0] + dx, self.offset[1] + dy
        n = math.hypot(ox, oy)
        if n > OFFSET_MAX_M:
            ox, oy = ox * OFFSET_MAX_M / n, oy * OFFSET_MAX_M / n
        step = (ox - self.offset[0], oy - self.offset[1])
        self.offset = (ox, oy)
        if self.map_from_odom is not None:
            m = self.map_from_odom
            self.map_from_odom = (m[0] + step[0], m[1] + step[1], m[2])
        return step

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose on the map (None before the first fix): the pose at the odometry's own instant, not the latest."""
        return None if self.map_from_odom is None else compose(self.map_from_odom, odom_pose)

    def pose(self) -> tuple | None:
        """The latest pose on the map, or None before the first fix."""
        if self.map_from_odom is None or not self._odom:
            return None
        return compose(self.map_from_odom, self._odom[-1][1])
