"""The judge's geometry and numbers (RFC-0022, from the evaluation): the robot's footprint and thresholds (its profile's,
variant sim), the simulator layout's files, and the distances the judge, the scores and the truth guard measure with.

The robot is the one the runner runs (labrunner.robots): read once, when this module is imported. With one robot
registered that is it; a second one needs its --robot read before the course's modules are imported (not built yet)."""

import math

from labrunner import robots

ROBOT = robots.get()
LAYOUT = robots.sim_dir() / "apartment_layout.json"
GOALS = robots.sim_dir() / "phase1_goals.json"
# The duck as the simulator models it (robots/duck/sim/measure_duck.py, STAND pose): 27.2 cm tall, every
# collision part within 8.3 cm of the trunk's centre in plan view. Pollen publishes ~25 cm tall,
# 14 cm wide, under 800 g; the model's extra 2 cm is the head in the standing pose.
# The harness judges the simulated duck: the numbers are its profile's (robots/duck/profile.json, variant sim).
PROFILE = robots.profile("sim")
DUCK_HEIGHT_M = PROFILE.footprint.height_m
FOOTPRINT_M = PROFILE.footprint.radius_m       # the trunk centre closer than this to an obstacle's outline: a part can touch
FALLEN_Z_M = PROFILE.judge.fall_z_m         # trunk height below this (standing: 0.116) is a fall; so is leaving the flat
OVERHEAD_CLEAR_M = PROFILE.footprint.overhead_clear_m   # obstacles whose underside is higher than this pass over the duck's head
GOAL_CLEARANCE_M = PROFILE.footprint.goal_clearance_m
REACHED_M = PROFILE.judge.reached_m          # truth within this of the goal counts as reached


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


def obstacles(layout: dict, landmarks: bool = True) -> list:
    """Colliding geoms the duck can walk into: not the floors, not the stairs' treads (the hole is the
    cliff check's business, not a contact). With landmarks, also the per-room lm_* markers: visual only
    in the simulator, but the depth sensor sees them, so in this world they are things the duck would hit
    (RFC-0016; b7 ended three runs 3 cm from lm_office, uncounted)."""
    out = []
    for g in layout["geoms"]:
        name = g["name"]
        marker = landmarks and name.startswith("lm_")
        if (not g["collides"] and not marker) or g["type"] == "plane" or name.startswith("floor") or \
                name.startswith("stair"):
            continue
        if underside(g) > OVERHEAD_CLEAR_M:
            continue    # above the duck's head (a table top, a high shelf): it walks under it
        out.append(g)
    return out


def clearance(p: tuple, obs: list) -> tuple:
    best = min(obs, key=lambda g: footprint_distance(p, g))
    return footprint_distance(p, best), best["name"]

