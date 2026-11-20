"""The duck's localisation and map (RFC-0020 §4, `mapd@1`): where it is, the grid, and how sure, from Pollen's mapping service.

mapd builds a map and a pose from the duck's depth sensor and odometry, and maps only at stops (`localisation.maps_only_at_stops`):
the navigator stands still to let it (`settle`). Its pose is a fix, not a stream: odometry is smooth and drifts, mapd's pose corrects
it (RFC-0002 §3.7, nav/frames.py's Localizer, which this plugin owns as the robot's belief). Odometry, mapd's poses and mapd's grid
all come from robotd's odometry; one scale corrects all three (`localisation.odometry.scale`, the simulator's reads about 10 % long),
so the map and the pose stay in the same (true) metres. The map's origin is its first stop, so scaling about it keeps the duck where
it is. That one scale (`odometry.scale`, the table's value at `at_speed_mps`) is the map's and mapd's pose's: mapd builds both from
robotd's odometry, and the grid cannot be re-metred per step. The navigator's own dead reckoning between fixes does better: each
odometry step is scaled by the table's scale at the speed commanded while it was walked (`odometry.by_speed`, K8); a fix at a stop
then puts the belief back on mapd's pose.

Numbers: the profile's `localisation` block (`fix`: the gate's thresholds, `loop_credit_s`, `record_m`; `odometry.scale`;
`grid_res_m`).

What it says about itself it says through `record` (the navigator's recorder), each with its decision: a `fix` event when a fix is held
or moves the belief far (the next jump shows its source: mapd's raw pose and its t_ns, and the odometry it was paired with) and a
`mapd_status` event when mapd's own account of itself changes.
"""

import math
import time

from duck_lab.nav.decision import decision
from duck_lab.nav.frames import Localizer, move_grid


class Mapd:
    name = "mapd"
    version = 1
    STRAIGHT_MIN_MPS = 0.05          # forward slower than this is a stand or a pivot's creep, not a walk

    def __init__(self, profile):
        loc = profile.localisation
        self.fixcfg = loc.fix
        self.belief = Localizer(loc.fix, max_jump_m=loc.fix.jump_m, hold_n=None)
        self.scale = float(loc.odometry.scale)
        self.by_speed = sorted((float(k), float(v)) for k, v in (loc.get("odometry.by_speed") or {}).items())
        self.straight_rad_s = float(loc.get("odometry.straight_rad_s") or math.inf)
        self._speed = None           # the straight walk's speed last commanded (None: not walking straight), which picks the scale
        self._last = None            # the previous odometry sample (robotd's) and its corrected pose, for the next step
        self._corrected = {}         # raw odometry pose -> corrected pose, the newest ones: to_map is asked with a raw pose
        self.grid_res_m = loc.grid_res_m
        self.stops_to_map = loc.maps_only_at_stops
        self.rpc = None
        self.seen = None             # mapd's last account of itself (lost, loops, relocalizations, islands)
        self._loop_credit = None     # until when a large fix is taken to be the loop closure mapd believed (time.monotonic)

    def bind(self, rpc) -> None:
        """The channel mapd answers on (a robot RPC with `call(method, params)`)."""
        self.rpc = rpc

    def scaled(self, pose: tuple) -> tuple:
        return pose[0] * self.scale, pose[1] * self.scale, pose[2]

    def scale_at(self, speed: float) -> float:
        """The odometry scale at a forward speed (m/s): the table's, interpolated between its speeds and held beyond the
        ends; `odometry.scale` where the profile has no table."""
        if not self.by_speed:
            return self.scale
        v = abs(speed)
        if v <= self.by_speed[0][0]:
            return self.by_speed[0][1]
        for (v0, s0), (v1, s1) in zip(self.by_speed, self.by_speed[1:]):
            if v <= v1:
                return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
        return self.by_speed[-1][1]

    def commanded(self, vx: float, vyaw: float = 0.0) -> None:
        """The motion now commanded. The odometry steps that follow are corrected by the scale at this forward speed when the
        duck walks straight (a turn under `odometry.straight_rad_s`, forward faster than a creep); a turn on the spot or an arc
        is corrected by `odometry.scale`, the one measured in navigation (over 8 m of arcs at 0.2 m/s the belief walked 0.986
        of the truth with it, where the straight walk's table would put 0.2 m/s at 1.06)."""
        straight = vx > self.STRAIGHT_MIN_MPS and abs(vyaw) < self.straight_rad_s
        self._speed = vx if straight else None

    def corrected(self, odom_pose: tuple) -> tuple:
        """Robotd's odometry pose, corrected: its steps scaled by the scale at the speed commanded while they were walked, so
        a slow walk and a fast one are each in true metres (one scale was right at one speed only). The first sample is
        scaled about the odometry's origin, as the single scale did."""
        if not self.by_speed:
            return self.scaled(odom_pose)
        if self._last is None:
            c = self.scaled(odom_pose)
        else:
            raw0, c0 = self._last
            s = self.scale if self._speed is None else self.scale_at(self._speed)
            c = (c0[0] + (odom_pose[0] - raw0[0]) * s, c0[1] + (odom_pose[1] - raw0[1]) * s, odom_pose[2])
        self._last = (odom_pose, c)
        self._corrected[odom_pose] = c
        if len(self._corrected) > 400:
            self._corrected.pop(next(iter(self._corrected)))
        return c

    def on_odom(self, t_ns: int, odom_pose: tuple) -> None:
        """Every odometry sample (robotd's, unscaled)."""
        self.belief.on_odom(t_ns, self.corrected(odom_pose))

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose (robotd's, unscaled) on the map: the pose at the odometry's own instant, not the latest."""
        return self.belief.to_map(self._corrected.get(odom_pose) or self.scaled(odom_pose))

    def pose(self) -> tuple | None:
        return self.belief.pose()

    def frame_delta(self) -> tuple | None:
        return self.belief.delta()

    def nudge(self, dx: float, dy: float) -> tuple:
        return self.belief.nudge(dx, dy)

    def needs_stationary(self) -> bool:
        return self.stops_to_map

    def settle(self, hold, survey_timeout_s: float, tick_s: float) -> bool:
        """Stand still with explicit zeros (`hold()`) until mapd is collecting this stop, then a little longer. True when it was."""
        t = time.monotonic()
        collecting_since = None
        while time.monotonic() - t < survey_timeout_s:
            hold()
            st = self.rpc.call("map.status")
            if (st.get("state") or {}).get("collecting"):
                collecting_since = collecting_since or time.monotonic()
                if time.monotonic() - collecting_since > 2.0:
                    break
            time.sleep(tick_s)
        return collecting_since is not None

    def fix(self, record, frames_on: bool = True, fault: tuple | None = None, t0: float = 0.0) -> bool:
        """Ask mapd for its pose and apply it to the belief (the gate holds a jump too large to believe). False when mapd had no
        pose or no odometry was near its time. fault: (t_s, dx, dy), a test of the fix gate and the landmarks: from t_s after t0 on,
        mapd's raw pose is shifted by (dx, dy)."""
        st = self.rpc.call("map.status")
        pose = (st.get("state") or {}).get("pose")
        t_ns = (st.get("state") or {}).get("t_ns")
        closure = self._watch(st, record) if frames_on else None
        raw = self.scaled((pose["x"], pose["y"], pose["yaw"])) if pose else None
        if raw and fault and time.monotonic() - t0 >= fault[0]:
            raw = (raw[0] + fault[1], raw[1] + fault[2], raw[2])
        if not (pose and t_ns and self.belief.on_fix(t_ns, raw, closure=closure)):
            return False
        f = self.belief.last_fix
        if f.get("closure") and closure:
            self._loop_credit = None          # one large fix per loop closure
        rejected = self.belief.rejected
        if (f["status"] != "taken" and (rejected <= 3 or rejected % 20 == 0)) or (f["status"] == "taken"
                                                                                 and f["moved_m"] > self.fixcfg.record_m):
            jump_m = self.fixcfg.jump_m
            held = (f"a {f['closure']} mapd believed would move the belief {f['moved_m']:.2f} m: held until the landmarks agree with it"
                    if f.get("closure") else
                    f"a fix that would move the belief {f['moved_m']:.2f} m is held, not taken (limit {jump_m})")
            record(event="fix", **f, rejected=rejected, mapd=self.seen,
                   decision=decision("fix", {"held": held,
                                             "late": f"a jump of {f['moved_m']:.2f} m taken: held fixes agreed",
                                             "taken": f"a fix moved the belief {f['moved_m']:.2f} m"}[f["status"]],
                                     moved_m=f["moved_m"], limit_m=jump_m))
        return True

    def grid(self, frames_on: bool = True, fault: tuple | None = None, fault_grid: bool = False, t0: float = 0.0) -> dict:
        """mapd's grid as the navigator uses it: its finest resolution (doorways stay open), scaled like the odometry, and in
        the belief's frame (frames.move_grid): the pose, the memory and the grid are then one frame, whatever the belief
        took from mapd. Before, only the scale was applied, and after a held jump or a landmarks' nudge the walls sat
        displaced against the duck."""
        g = dict(self.rpc.call("map.grid", {"res_m": self.grid_res_m}))
        if g.get("res_m"):
            g["res_m"] *= self.scale
            g["origin"] = [v * self.scale for v in g["origin"]]
            if fault_grid and fault and time.monotonic() - t0 >= fault[0]:
                g["origin"] = [g["origin"][0] + fault[1], g["origin"][1] + fault[2]]
            if frames_on:
                g = move_grid(g, self.belief.delta())
        return g

    def _watch(self, st: dict, record) -> str | None:
        """mapd's own account of itself (its `map.status`): why it is lost (`boot`, `carried`, `bumped`, `sat`, `fell`,
        `contradiction`; absent while it knows), and its loop closures, relocalizations and island stops since it started.
        Recorded when any of them changes, so a jump in the belief can be read against what mapd did at that moment
        (RFC-0019: the first robot-tagged anomalies; b10a r1's 0.9 m jump had none of this).
        Returns "loop closure" when a large fix now is mapd's loop closure: the loops counter stepped within loop_credit_s, mapd
        is not lost and no relocalization stepped (mapd believed a loop closure after two agreeing stops, mapping-design §3).
        The gate holds it for the landmarks (Localizer.on_fix, K26); None otherwise, a large fix is held as ever."""
        now = {"lost": (st.get("state") or {}).get("lost"), "loops": st.get("loops"),
               "relocalizations": st.get("relocalizations"), "islands": st.get("island_keyframes")}
        before = self.seen
        stepped = {k: before is not None and (now[k] or 0) > (before.get(k) or 0) for k in ("loops", "relocalizations")}
        t = time.monotonic()
        if now["lost"] or stepped["relocalizations"]:
            self._loop_credit = None
        elif stepped["loops"]:
            self._loop_credit = t + self.fixcfg.loop_credit_s
        trust = "loop closure" if not now["lost"] and (self._loop_credit or 0) > t else None
        if now == before:
            return trust
        self.seen = now
        if before is None and not now["lost"] and not now["loops"] and not now["relocalizations"]:
            return trust         # the first look, nothing unusual yet
        what = [k for k in now if before is None or now[k] != before.get(k)]
        record(event="mapd_status", **now, changed=what, pose=self.pose(),
               decision=decision("mapd_status", f"mapd: {', '.join(f'{k} {now[k]}' for k in what)}", **now))
        return trust
