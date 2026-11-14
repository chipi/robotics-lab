"""Following a path (RFC-0002 §3.8, step 3), as one function: state in, twist out.

What the simulator taught (docs/wip/PHASE0-SPIKE.md): the duck moves at about half of what it is
asked, does not walk below about 0.2 m/s, and from a stand does not start turning on the spot below
about 1.1 rad/s. So: turns start with a kick, forward speed stays above the floor, and everything is
steered from the measured pose, never from the commanded speed.
"""

import math
from dataclasses import dataclass, field

LOOKAHEAD_M = 0.30
GOAL_TOL_M = 0.15
TURN_FIRST_RAD = math.radians(45)    # heading further off than this: turn on the spot first
TURN_DONE_RAD = math.radians(15)     # and walk again once within this
KICK_RAD_S = 1.2                     # starts stepping from a stand
KICK_S = 1.0
TURN_RAD_S = 0.8                     # holds a turn once stepping (about 26 deg/s in the simulator)
WALK_MPS = 0.3
MAX_YAW_RAD_S = 1.0
YAW_GAIN = 1.5


@dataclass
class Twist:
    vx: float = 0.0
    vyaw: float = 0.0


@dataclass
class FollowState:
    turning: bool = False
    turn_started: float | None = None
    target_index: int = 0
    log: list = field(default_factory=list)


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def lookahead(path: list, pose: tuple, start_index: int) -> tuple:
    """The first path point at least LOOKAHEAD_M from the pose, searching forward from the closest
    point at or after start_index; the last point when none is that far."""
    x, y = pose[0], pose[1]
    closest = min(range(start_index, len(path)), key=lambda i: math.dist(path[i], (x, y)))
    for i in range(closest, len(path)):
        if math.dist(path[i], (x, y)) >= LOOKAHEAD_M:
            return i, path[i]
    return len(path) - 1, path[-1]


def step(path: list, pose: tuple, now: float, st: FollowState) -> tuple:
    """One control step. pose = (x, y, yaw) in the path's frame. Returns (Twist, done)."""
    x, y, yaw = pose
    if math.dist(path[-1], (x, y)) <= GOAL_TOL_M:
        st.turning, st.turn_started = False, None
        return Twist(), True
    st.target_index, target = lookahead(path, pose, st.target_index)
    err = wrap(math.atan2(target[1] - y, target[0] - x) - yaw)

    if st.turning and abs(err) <= TURN_DONE_RAD:
        st.turning, st.turn_started = False, None
    elif not st.turning and abs(err) > TURN_FIRST_RAD:
        st.turning, st.turn_started = True, now

    if st.turning:
        rate = KICK_RAD_S if now - st.turn_started < KICK_S else TURN_RAD_S
        return Twist(0.0, math.copysign(rate, err)), False
    vyaw = max(-MAX_YAW_RAD_S, min(MAX_YAW_RAD_S, YAW_GAIN * err))
    return Twist(WALK_MPS, vyaw), False
