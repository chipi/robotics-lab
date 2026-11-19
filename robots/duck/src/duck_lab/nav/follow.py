"""Following a path (RFC-0002 §3.8, step 3), as one function: state in, twist out.

What the simulator taught (docs/wip/PHASE0-SPIKE.md): everything is steered from the measured pose, never from the commanded
speed. This is the shared half of following: find the point on the path to head for (the lookahead) and how far off it the
robot's heading is. What a robot does about that error is its locomotion plugin's (`drive`: for the duck, plugins/duck_walk.py:
the kick, the slowest walk, the creep).

The numbers are the profile's `locomotion` block (robots/duck/profile.json), passed as `loco`:
  lookahead_m       the lookahead; lookahead_near_m within an obstacle's margin, so a bend is followed instead of cut
                    (regulated pure pursuit's other half: phase 1 runs 9 and 10 cut the office doorway's bend inside)
  goal_tol_m        reached within this
"""

import math
from dataclasses import dataclass, field


@dataclass
class Twist:
    vx: float = 0.0
    vyaw: float = 0.0


@dataclass
class FollowState:
    turning: bool = False
    turn_started: float | None = None
    target_index: int = 0
    check_t: float | None = None     # pivot progress check: when, and the yaw then
    check_yaw: float = 0.0
    log: list = field(default_factory=list)


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def lookahead(path: list, pose: tuple, start_index: int, dist_m: float) -> tuple:
    """The first path point at least dist_m from the pose, searching forward from the closest
    point at or after start_index; the last point when none is that far."""
    x, y = pose[0], pose[1]
    closest = min(range(start_index, len(path)), key=lambda i: math.dist(path[i], (x, y)))
    for i in range(closest, len(path)):
        if math.dist(path[i], (x, y)) >= dist_m:
            return i, path[i]
    return len(path) - 1, path[-1]


def step(path: list, pose: tuple, now: float, st: FollowState, loco, walker, near: bool = False, pivot_ok: bool = True,
         close: bool = False) -> tuple:
    """One control step. pose = (x, y, yaw) in the path's frame; loco = the profile's locomotion block; walker = the robot's
    locomotion plugin, which turns the heading error into a motion (Locomotion.drive); near = the robot is within an obstacle's
    margin (shorter lookahead); close = an obstacle is within slow_clearance_m (a hard turn slows); pivot_ok = there is room to
    turn on the spot (else a turn is an arc, which the caller must check has clear floor ahead). Returns (Twist, done)."""
    x, y, yaw = pose
    if math.dist(path[-1], (x, y)) <= loco.goal_tol_m:
        st.turning, st.turn_started = False, None
        return Twist(), True
    st.target_index, target = lookahead(path, pose, st.target_index, loco.lookahead_near_m if near else loco.lookahead_m)
    err = wrap(math.atan2(target[1] - y, target[0] - x) - yaw)
    return walker.drive(err, yaw, now, st, near, pivot_ok, close), False
