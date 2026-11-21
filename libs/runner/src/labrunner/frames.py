"""Poses in the plane for the judge and the course: the navigator's own `compose` and `inverse` (duck_lab.nav.frames), the
yaw wrapped, kept here so the runner imports no robot's package and a move changes no number (RFC-0022; runfile.se2
does not wrap the yaw)."""

import math


def compose(a: tuple, b: tuple) -> tuple:
    """a ∘ b: b expressed in a's parent frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], math.atan2(math.sin(a[2] + b[2]),
                                                                              math.cos(a[2] + b[2]))


def inverse(a: tuple) -> tuple:
    c, s = math.cos(a[2]), math.sin(a[2])
    return -c * a[0] - s * a[1], s * a[0] - c * a[1], -a[2]
