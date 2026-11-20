"""The duck's locomotion (RFC-0020 §4, `duck-walk@1`): what a wanted motion has to be for this walk, and where it may turn.

What the simulator taught (docs/wip/PHASE0-SPIKE.md): the duck moves at about half of what it is asked, does not walk below
about 0.2 m/s, and from a stand does not start turning on the spot below about 1.1 rad/s. So turns start with a kick, forward
speed stays above the floor, and a turn on the spot shifts the duck (phase 0: 8 cm over a full turn; exploration trial 5: 26 cm
over 4.3 rad, toward the stairs; phase 1 run 12: a contact beside the office cabinet) and the duck does not walk backwards
(-0.15 and -0.3 m/s: no motion; -0.4: 87 cm with a 51 deg swing). So it turns on the spot only with room for that drift:
`pivot.drop_clear_m` from any remembered drop and the lethal ring plus `pivot.obstacle_margin_m` from any obstacle. Otherwise it
turns while walking slowly (an arc), and only onto clear floor: `arc.clear_mm` by the depth sensor, no lethal cell `arc.ahead_m`
ahead and no remembered drop where the arc sweeps. No room for either: a pivot is still allowed while the clearance stays above
`pivot.tight_m`, rechecked every tick, once per spot. Below it the duck stands and the leg is refused.

Numbers: the profile's `locomotion` block and the footprint's lethal ring (robots/duck/profile.json). The path-following geometry
(the lookahead, the heading error) is shared and lives in nav/follow.py; this is the part of following that is the robot's own.
"""

import math

from duck_lab.nav.follow import Twist, wrap
from duck_lab.nav.grid import LETHAL_COST


class DuckWalk:
    name = "duck-walk"
    version = 1

    def __init__(self, profile, pivot_vx: float | None = None):
        loco = self.loco = profile.locomotion
        self.pivot_vx = float(loco.pivot.vx_mps) if pivot_vx is None else pivot_vx
        self.lethal_m = profile.footprint.lethal_m
        self.pivot_obstacle_m = self.lethal_m + loco.pivot.obstacle_margin_m
        self.pivot_drop_m, self.pivot_edge_m = loco.pivot.drop_clear_m, loco.pivot.edge_clear_m
        self.tight_pivot_m, self.tight_spot_m, self.tight_gap_s = loco.pivot.tight_m, loco.pivot.tight_spot_m, loco.pivot.tight_gap_s
        self.arc = loco.arc
        self.deadband = float(loco.get("steer.deadband_rad") or 0.0)
        self.drop_lethal_m = profile.error_budget.drop_lethal_m
        self.tight_spots = []        # [(x, y), last tick] of each tight pivot: one per spot (tight_pivot_ok)
        self.robot = None

    def bind(self, robot) -> None:
        self.robot = robot

    def command(self, vx: float, vyaw: float) -> None:
        self.robot.call("robot.move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})

    def stop(self) -> None:
        self.command(0.0, 0.0)

    def drive(self, err: float, yaw: float, now: float, st, near: bool, pivot_ok: bool, close: bool) -> Twist:
        """The follower's state in, one motion out. st.turning: turn on the spot first when the heading is further off than
        pivot_first_deg, and walk again once within pivot_done_deg. Turning, with no room to pivot: an arc at the slowest speed
        (the caller checks it has clear floor ahead). Turning on the spot: a kick (kick_rad_s for kick_s, standing still: stepping
        back while the gait starts sometimes left the turn unstarted, old challenge 6 seed 3: 13 deg in 15 s;
        sim/probes/pivot_start.py), then hold_rad_s, and a pivot that gains under restep_rad in a second kicks again (phase 1 run
        13, goal 9: 0.16 rad in the kick, then 14 s at 0.8 rad/s without turning). Walking: the steering by yaw_gain, at the
        slowest speed when the turn is hard (slow_yaw_rad_s) and an obstacle is near (RFC-0012's caution pace)."""
        loco = self.loco
        if st.turning and abs(err) <= math.radians(loco.pivot_done_deg):
            st.turning, st.turn_started = False, None
        elif not st.turning and abs(err) > math.radians(loco.pivot_first_deg):
            st.turning, st.turn_started, st.check_t = True, now, None

        if st.turning:
            if not pivot_ok:     # too close to something to turn on the spot: turn while walking, slowly
                return Twist(loco.slowest_mps, math.copysign(loco.yaw_max_rad_s, err))
            if st.check_t is None or now - st.check_t >= 1.0:
                if st.check_t is not None and now - st.turn_started >= loco.kick_s and abs(wrap(yaw - st.check_yaw)) < loco.restep_rad:
                    st.turn_started = now
                st.check_t, st.check_yaw = now, yaw
            kicking = now - st.turn_started < loco.kick_s
            return Twist(0.0 if kicking else self.pivot_vx, math.copysign(loco.kick_rad_s if kicking else loco.hold_rad_s, err))
        vyaw = max(-loco.yaw_max_rad_s, min(loco.yaw_max_rad_s, loco.yaw_gain * err))
        if self.deadband and not close:
            # not in a squeeze: no turn while the heading is within the band, a correction once past it (K1: a turn commanded while the
            # feet meet a 0.5-1 cm edge stops the step-over; the walk's own drift, 0.07 rad/s, does not)
            if abs(err) >= self.deadband:
                st.steering = True
            elif abs(err) <= self.deadband / 2:
                st.steering = False
            if not st.steering:
                vyaw = 0.0
        else:
            st.steering = False
        return Twist(loco.slowest_mps if (near or close) and abs(vyaw) >= loco.slow_yaw_rad_s else loco.cruise_mps, vyaw)

    def pivot_clear_of_drops(self, xy: tuple, drops: list, edges: list) -> bool:
        """Room to turn on the spot, as far as drops go: pivot.drop_clear_m from a cliff stop's points, pivot.edge_clear_m from a
        measured edge (each its ring less the following's and belief's error, so the duck can turn wherever the planner may
        put it)."""
        return all(math.dist(xy, d) >= self.pivot_drop_m for d in drops) and \
            all(math.dist(xy, d) >= self.pivot_edge_m for d in edges)

    def can_pivot(self, room_m: float, xy: tuple, drops: list, edges: list) -> bool:
        return room_m >= self.pivot_obstacle_m and self.pivot_clear_of_drops(xy, drops, edges)

    def _tight_allowed(self, xy: tuple, now: float) -> bool:
        """One tight pivot per spot (the operator, 2026-11-18): a turn on the spot creeps 3-4 cm the odometry does not see,
        so the belief's room is no longer the room after one (b7 r2: four tight pivots beside lm_office took it from
        0.206 to 0.034 m while it believed 0.16). A pivot going on (a tick within tight_gap_s of the last) continues;
        a new one within tight_spot_m of an earlier one is refused, and the leg then is "no room to turn"."""
        for spot in self.tight_spots:
            if math.dist(spot[0], xy) <= self.tight_spot_m:
                if now - spot[1] <= self.tight_gap_s:
                    spot[1] = now
                    return True
                return False
        self.tight_spots.append([tuple(xy), now])
        return True

    def tight_pivot_ok(self, room_m: float, xy: tuple, drops: list, edges: list, now: float) -> bool:
        return room_m >= self.tight_pivot_m and self.pivot_clear_of_drops(xy, drops, edges) and self._tight_allowed(xy, now)

    def arc_clear(self, costs, pose: tuple, turn: float, nearest_mm, drops: list, edges: list, suspected: list) -> bool:
        """Clear floor for a slow turn while walking, turn > 0 to the left: the depth sensor, the grid ahead (for walls:
        a cell lethal only for a drop's ring is left to the drop check) and the drop memory, where the arc sweeps: within
        arc.reach_m, from arc.outer_deg on the outer side to arc.inner_deg on the inner side. A drop anywhere ahead vetoed
        every turn before (challenge 11 seed 1: a turn away from a pit at the side was refused)."""
        near = nearest_mm
        if near is None or near < self.arc.clear_mm:
            return False
        hazards = drops + edges + suspected
        ahead = (pose[0] + self.arc.ahead_m * math.cos(pose[2]), pose[1] + self.arc.ahead_m * math.sin(pose[2]))
        c = costs.cell(*ahead)
        if costs.inside(*c) and costs.at(*c) >= LETHAL_COST and \
                all(math.dist(ahead, d) > self.drop_lethal_m for d in hazards):
            return False
        side = 1.0 if turn >= 0 else -1.0
        for d in hazards:
            if math.dist(pose[:2], d) >= self.arc.reach_m:
                continue
            b = math.degrees(wrap(math.atan2(d[1] - pose[1], d[0] - pose[0]) - pose[2])) * side
            if -self.arc.outer_deg <= b <= self.arc.inner_deg:
                return False
        return True
