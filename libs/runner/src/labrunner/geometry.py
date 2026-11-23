"""The judge's geometry and numbers (RFC-0022, from the evaluation): the robot's footprint and thresholds (its profile's,
variant sim), the simulator layout's files, and the distances the judge, the scores and the truth guard measure with.

The robot is the one the runner runs (labrunner.robots), read when asked (`profile()`, `layout_path()`, `goals_path()`), not
when this module is imported: a command reads it after its --robot (phase 5 item 2).

The numbers a course judges by are the profile's (robots/duck/profile.json, variant sim, for the duck): `footprint.radius_m`
(the trunk centre closer than this to an obstacle's outline: a part can touch), `judge.fall_z_m` (trunk height below this is a
fall), `footprint.overhead_clear_m` (obstacles whose underside is higher pass over the robot's head), `footprint.goal_clearance_m`,
`judge.reached_m` (truth within this of the goal counts as reached). The duck as the simulator models it
(robots/duck/sim/measure_duck.py, STAND pose): 27.2 cm tall, every collision part within 8.3 cm of the trunk's centre in plan
view."""

import math
from pathlib import Path

from labrunner import robots


def profile():
    """The robot's profile in the simulator, the version this machine runs (labrunner.robots.profile_file)."""
    return robots.profile("sim")


def layout_path() -> Path:
    """The robot's simulator layout (what the robot can walk into in the apartment)."""
    return robots.sim_dir() / "apartment_layout.json"


def goals_path() -> Path:
    """Phase 1's fixed goals in the apartment."""
    return robots.sim_dir() / "phase1_goals.json"


def footprint_distance(p: tuple, g: dict) -> float:
    """2D distance from point p to a geom's footprint (box with yaw, or cylinder/sphere/capsule)."""
    dx, dy = p[0] - g["pos"][0], p[1] - g["pos"][1]
    if g["type"] == "box":
        c, s = math.cos(-g["yaw"]), math.sin(-g["yaw"])
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return math.hypot(max(abs(lx) - g["size"][0], 0.0), max(abs(ly) - g["size"][1], 0.0))
    return max(math.hypot(dx, dy) - g["size"][0], 0.0)


def underside(g: dict) -> float:
    """Height of a geom's lowest point (boxes and cylinders by half-height, capsules and spheres by
    radius plus half-length)."""
    z = g["pos"][2]
    if g["type"] == "box":
        return z - g["size"][2]
    if g["type"] == "cylinder":
        return z - g["size"][1]
    if g["type"] == "capsule":
        return z - g["size"][1] - g["size"][0]
    return z - g["size"][0]


def obstacles(layout: dict, landmarks: bool = True, overhead_clear_m: float | None = None) -> list:
    """Colliding geoms the duck can walk into: not the floors, not the stairs' treads (the hole is the
    cliff check's business, not a contact). With landmarks, also the per-room lm_* markers: visual only
    in the simulator, but the depth sensor sees them, so in this world they are things the duck would hit
    (RFC-0016; b7 ended three runs 3 cm from lm_office, uncounted). `overhead_clear_m`: the profile's when not given."""
    clear = profile().footprint.overhead_clear_m if overhead_clear_m is None else overhead_clear_m
    out = []
    for g in layout["geoms"]:
        name = g["name"]
        marker = landmarks and name.startswith("lm_")
        if (not g["collides"] and not marker) or g["type"] == "plane" or name.startswith("floor") or \
                name.startswith("stair"):
            continue
        if underside(g) > clear:
            continue    # above the duck's head (a table top, a high shelf): it walks under it
        out.append(g)
    return out


def clearance(p: tuple, obs: list) -> tuple:
    best = min(obs, key=lambda g: footprint_distance(p, g))
    return footprint_distance(p, best), best["name"]

