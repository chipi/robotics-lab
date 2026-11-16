"""Dead reckoning with fixes (RFC-0002 §3.7): odometry is smooth and drifts, mapd's pose is a fix.

The navigator keeps one transform, map ← odom: at each mapd pose, the map pose composed with the
inverse of the odometry pose at the same t_ns. Between fixes, the pose on the map is that transform
applied to the latest odometry. Poses are (x, y, yaw).
"""

import math


def compose(a: tuple, b: tuple) -> tuple:
    """a ∘ b: b expressed in a's parent frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], math.atan2(math.sin(a[2] + b[2]),
                                                                              math.cos(a[2] + b[2]))


def inverse(a: tuple) -> tuple:
    c, s = math.cos(a[2]), math.sin(a[2])
    return -c * a[0] - s * a[1], s * a[0] - c * a[1], -a[2]


class Localizer:
    def __init__(self, history: int = 200):
        self.map_from_odom = None
        self._odom = []          # (t_ns, pose), newest last
        self._history = history

    def on_odom(self, t_ns: int, pose: tuple) -> None:
        self._odom.append((t_ns, pose))
        del self._odom[:-self._history]

    def on_fix(self, t_ns: int, map_pose: tuple) -> bool:
        """A mapd pose. Returns False when no odometry near that time is held."""
        near = min(self._odom, key=lambda e: abs(e[0] - t_ns), default=None)
        if near is None or abs(near[0] - t_ns) > 100_000_000:
            return False
        self.map_from_odom = compose(map_pose, inverse(near[1]))
        return True

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose on the map (None before the first fix): the pose at the odometry's own instant, not the latest."""
        return None if self.map_from_odom is None else compose(self.map_from_odom, odom_pose)

    def pose(self) -> tuple | None:
        """The latest pose on the map, or None before the first fix."""
        if self.map_from_odom is None or not self._odom:
            return None
        return compose(self.map_from_odom, self._odom[-1][1])
