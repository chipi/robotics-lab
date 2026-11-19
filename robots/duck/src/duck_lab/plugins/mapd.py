"""The duck's localisation and map (RFC-0020 §4, `mapd@1`): where it is, the grid, and how sure, from Pollen's mapping service.

mapd builds a map and a pose from the duck's depth sensor and odometry, and maps only at stops (`localisation.maps_only_at_stops`):
the navigator stands still to let it (`settle`). Its pose is a fix, not a stream: odometry is smooth and drifts, mapd's pose corrects
it (RFC-0002 §3.7, nav/frames.py's Localizer, which this plugin owns as the robot's belief). Odometry, mapd's poses and mapd's grid
all come from robotd's odometry; one scale corrects all three (`localisation.odometry.scale`, the simulator's reads about 10 % long),
so the map and the pose stay in the same (true) metres. The map's origin is its first stop, so scaling about it keeps the duck where
it is.

Numbers: the profile's `localisation` block (`fix`: the gate's thresholds, `loop_credit_s`, `record_m`; `odometry.scale`;
`grid_res_m`).

What it says about itself it says through `record` (the navigator's recorder), each with its decision: a `fix` event when a fix is held
or moves the belief far (the next jump shows its source: mapd's raw pose and its t_ns, and the odometry it was paired with) and a
`mapd_status` event when mapd's own account of itself changes.
"""

import time

from duck_lab.nav.decision import decision
from duck_lab.nav.frames import Localizer, move_grid


class Mapd:
    name = "mapd"
    version = 1

    def __init__(self, profile):
        loc = profile.localisation
        self.fixcfg = loc.fix
        self.belief = Localizer(loc.fix, max_jump_m=loc.fix.jump_m, hold_n=None)
        self.scale = float(loc.odometry.scale)
        self.grid_res_m = loc.grid_res_m
        self.stops_to_map = loc.maps_only_at_stops
        self.rpc = None
        self.seen = None             # mapd's last account of itself (lost, loops, relocalizations, islands)
        self._loop_credit = None     # until when a loop closure mapd believed lets a large fix through (time.monotonic)

    def bind(self, rpc) -> None:
        """The channel mapd answers on (a robot RPC with `call(method, params)`)."""
        self.rpc = rpc

    def scaled(self, pose: tuple) -> tuple:
        return pose[0] * self.scale, pose[1] * self.scale, pose[2]

    def on_odom(self, t_ns: int, odom_pose: tuple) -> None:
        """Every odometry sample (robotd's, unscaled)."""
        self.belief.on_odom(t_ns, self.scaled(odom_pose))

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose (robotd's, unscaled) on the map: the pose at the odometry's own instant, not the latest."""
        return self.belief.to_map(self.scaled(odom_pose))

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
        trust = self._watch(st, record) if frames_on else None
        raw = self.scaled((pose["x"], pose["y"], pose["yaw"])) if pose else None
        if raw and fault and time.monotonic() - t0 >= fault[0]:
            raw = (raw[0] + fault[1], raw[1] + fault[2], raw[2])
        if not (pose and t_ns and self.belief.on_fix(t_ns, raw, trust=trust)):
            return False
        f = self.belief.last_fix
        if f.get("trusted"):
            self._loop_credit = None          # one large fix per loop closure
        rejected = self.belief.rejected
        if (f["status"] != "taken" and (rejected <= 3 or rejected % 20 == 0)) or (f["status"] == "taken"
                                                                                 and f["moved_m"] > self.fixcfg.record_m):
            jump_m = self.fixcfg.jump_m
            record(event="fix", **f, rejected=rejected, mapd=self.seen,
                   decision=decision("fix", {"held": "a fix that would move the belief "
                                             f"{f['moved_m']:.2f} m is held, not taken (limit {jump_m})",
                                             "late": f"a jump of {f['moved_m']:.2f} m taken: held fixes agreed",
                                             "taken": (f"a {f['trusted']} mapd believed moved the belief {f['moved_m']:.2f} m: taken"
                                                       if f.get("trusted") else
                                                       f"a fix moved the belief {f['moved_m']:.2f} m")}[f["status"]],
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
        Returns "loop closure" when a large fix may be taken now: the loops counter stepped within loop_credit_s, mapd is not
        lost and no relocalization stepped (mapd believed a loop closure after two agreeing stops, mapping-design §3); None
        otherwise, and the gate holds a large fix as it always did."""
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
