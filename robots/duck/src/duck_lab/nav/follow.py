"""Following a path (RFC-0002 §3.8, step 3), as one function: state in, twist out.

What the simulator taught (docs/wip/PHASE0-SPIKE.md): the duck moves at about half of what it is
asked, does not walk below about 0.2 m/s, and from a stand does not start turning on the spot below
about 1.1 rad/s. So: turns start with a kick, forward speed stays above the floor, and everything is
steered from the measured pose, never from the commanded speed.

The numbers are the robot's, from its profile's `locomotion` block (robots/duck/profile.json), passed as `loco`:
  cruise_mps, slowest_mps   the walk, and the slowest walk there is: near an obstacle or a drop the duck turns while walking
                            at the slowest speed instead of turning on the spot (upstream's brain creeps forward rather than pivot
                            by a wall); a turn this hard (slow_yaw_rad_s) within an obstacle's margin, or with an obstacle within
                            slow_clearance_m, walks at the slowest speed (RFC-0012's caution pace; the apartment's goals 11 and 12 cut
                            the office cabinet's corner at cruise speed, 7 cm from it)
  yaw_max_rad_s, yaw_gain   the steering
  pivot_first_deg           heading further off than this: turn on the spot first; pivot_done_deg: walk again once within this
  kick_rad_s, kick_s        starts stepping from a stand; hold_rad_s holds a turn once stepping
  restep_rad                a pivot that gains less than this in a second kicks again (phase 1 run 13, goal 9: 0.16 rad in the kick,
                            then 14 s at 0.8 rad/s without turning)
  lookahead_m               the lookahead; lookahead_near_m within an obstacle's margin, so a bend is followed instead of cut
                            (regulated pure pursuit's other half: phase 1 runs 9 and 10 cut the office doorway's bend inside)
  goal_tol_m                reached within this
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


def step(path: list, pose: tuple, now: float, st: FollowState, loco, near: bool = False, pivot_ok: bool = True,
         pivot_vx: float = 0.0, close: bool = False) -> tuple:
    """One control step. pose = (x, y, yaw) in the path's frame; loco = the profile's locomotion block; near = the duck is within an
    obstacle's margin (shorter lookahead); close = an obstacle is within slow_clearance_m (a hard turn slows); pivot_ok = there is
    room to turn on the spot (else a turn is an arc at the slowest speed, which the caller must check has clear floor ahead);
    pivot_vx = the forward speed a turn on the spot is sent with, against the robot's own creep (profile locomotion.pivot.vx_mps).
    Returns (Twist, done)."""
    x, y, yaw = pose
    if math.dist(path[-1], (x, y)) <= loco.goal_tol_m:
        st.turning, st.turn_started = False, None
        return Twist(), True
    st.target_index, target = lookahead(path, pose, st.target_index, loco.lookahead_near_m if near else loco.lookahead_m)
    err = wrap(math.atan2(target[1] - y, target[0] - x) - yaw)

    if st.turning and abs(err) <= math.radians(loco.pivot_done_deg):
        st.turning, st.turn_started = False, None
    elif not st.turning and abs(err) > math.radians(loco.pivot_first_deg):
        st.turning, st.turn_started, st.check_t = True, now, None

    if st.turning:
        if not pivot_ok:     # too close to something to turn on the spot: turn while walking, slowly
            return Twist(loco.slowest_mps, math.copysign(loco.yaw_max_rad_s, err)), False
        # A kick does not always start the stepping: a pivot that gains under restep_rad in a second kicks again.
        if st.check_t is None or now - st.check_t >= 1.0:
            if st.check_t is not None and now - st.turn_started >= loco.kick_s and abs(wrap(yaw - st.check_yaw)) < loco.restep_rad:
                st.turn_started = now
            st.check_t, st.check_yaw = now, yaw
        kicking = now - st.turn_started < loco.kick_s
        # The kick stands still: stepping back while the gait starts sometimes left the turn unstarted (old
        # challenge 6 seed 3: 13 deg in 15 s; sim/probes/pivot_start.py, 1 slow start in 5 at -0.06, none at 0).
        return Twist(0.0 if kicking else pivot_vx, math.copysign(loco.kick_rad_s if kicking else loco.hold_rad_s, err)), False
    vyaw = max(-loco.yaw_max_rad_s, min(loco.yaw_max_rad_s, loco.yaw_gain * err))
    return Twist(loco.slowest_mps if (near or close) and abs(vyaw) >= loco.slow_yaw_rad_s else loco.cruise_mps, vyaw), False
