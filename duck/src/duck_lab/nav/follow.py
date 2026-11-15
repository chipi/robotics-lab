"""Following a path (RFC-0002 §3.8, step 3), as one function: state in, twist out.

What the simulator taught (docs/wip/PHASE0-SPIKE.md): the duck moves at about half of what it is
asked, does not walk below about 0.2 m/s, and from a stand does not start turning on the spot below
about 1.1 rad/s. So: turns start with a kick, forward speed stays above the floor, and everything is
steered from the measured pose, never from the commanded speed.
"""

import math
from dataclasses import dataclass, field

LOOKAHEAD_M = 0.30
# Regulated pure pursuit's other half (the duck cannot walk slower): within an obstacle's margin the
# lookahead shrinks, so a bend is followed instead of cut. Phase 1 runs 9 and 10 cut the office doorway's
# bend inside, 7-8 cm from the cabinet; a 90 deg corner is cut by about L(1 - 1/sqrt 2): 9 cm at 0.30 m.
LOOKAHEAD_NEAR_M = 0.15
GOAL_TOL_M = 0.15
TURN_FIRST_RAD = math.radians(45)    # heading further off than this: turn on the spot first
TURN_DONE_RAD = math.radians(15)     # and walk again once within this
KICK_RAD_S = 1.2                     # starts stepping from a stand
KICK_S = 1.0
RESTEP_RAD = 0.05
TURN_RAD_S = 0.8                     # holds a turn once stepping (about 26 deg/s in the simulator)
WALK_MPS = 0.3
# A turn on the spot moves the duck in the simulator (upstream #597: 26 cm over 4.3 rad in exploration
# trial 5, a contact in phase 1 run 12). Close to an obstacle or a drop the duck turns while walking at
# the slowest speed it walks at instead, as upstream's brain creeps forward rather than pivot by a wall.
ARC_MPS = 0.2
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
    check_t: float | None = None     # pivot progress check: when, and the yaw then
    check_yaw: float = 0.0
    log: list = field(default_factory=list)


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def lookahead(path: list, pose: tuple, start_index: int, dist_m: float = LOOKAHEAD_M) -> tuple:
    """The first path point at least dist_m from the pose, searching forward from the closest
    point at or after start_index; the last point when none is that far."""
    x, y = pose[0], pose[1]
    closest = min(range(start_index, len(path)), key=lambda i: math.dist(path[i], (x, y)))
    for i in range(closest, len(path)):
        if math.dist(path[i], (x, y)) >= dist_m:
            return i, path[i]
    return len(path) - 1, path[-1]


def step(path: list, pose: tuple, now: float, st: FollowState, near: bool = False, pivot_ok: bool = True) -> tuple:
    """One control step. pose = (x, y, yaw) in the path's frame; near = the duck is within an obstacle's
    margin (shorter lookahead); pivot_ok = there is room to turn on the spot (else a turn is an arc at
    ARC_MPS, which the caller must check has clear floor ahead). Returns (Twist, done)."""
    x, y, yaw = pose
    if math.dist(path[-1], (x, y)) <= GOAL_TOL_M:
        st.turning, st.turn_started = False, None
        return Twist(), True
    st.target_index, target = lookahead(path, pose, st.target_index, LOOKAHEAD_NEAR_M if near else LOOKAHEAD_M)
    err = wrap(math.atan2(target[1] - y, target[0] - x) - yaw)

    if st.turning and abs(err) <= TURN_DONE_RAD:
        st.turning, st.turn_started = False, None
    elif not st.turning and abs(err) > TURN_FIRST_RAD:
        st.turning, st.turn_started, st.check_t = True, now, None

    if st.turning:
        if not pivot_ok:     # too close to something to turn on the spot: turn while walking, slowly
            return Twist(ARC_MPS, math.copysign(MAX_YAW_RAD_S, err)), False
        # A kick does not always start the stepping (phase 1 run 13, goal 9: 0.16 rad in the kick, then
        # 14 s at 0.8 rad/s without turning). A pivot that gains under RESTEP_RAD in a second kicks again.
        if st.check_t is None or now - st.check_t >= 1.0:
            if st.check_t is not None and now - st.turn_started >= KICK_S and abs(wrap(yaw - st.check_yaw)) < RESTEP_RAD:
                st.turn_started = now
            st.check_t, st.check_yaw = now, yaw
        rate = KICK_RAD_S if now - st.turn_started < KICK_S else TURN_RAD_S
        return Twist(0.0, math.copysign(rate, err)), False
    vyaw = max(-MAX_YAW_RAD_S, min(MAX_YAW_RAD_S, YAW_GAIN * err))
    return Twist(WALK_MPS, vyaw), False
