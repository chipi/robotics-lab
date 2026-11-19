"""The duck's looking (RFC-0020 §4, `duck-head@1`): aim the head at a floor spot the depth sensor cannot see from where the duck
stands, and give the head back its walking command (docs/wip/SIDE-DROPS.md).

The head is aimed with robot.look and held by resending; frames are used once the sensor's own yaw has held still (the old glance
read short from frames taken while the head was still turning), for `looking.collect_s`. A look returns the frames it saw, classified
(floor, and below-floor returns that count by their range); what to make of them (a drop's edge, floor seen, a suspicion cleared) is
the navigator's, with its hazard memory: a plugin never remembers a hazard.

robot.head is a command to the walking policy, not a joint target: under robotd's default command (`looking.walk_command`, zeros) the
head walks at neck ~13°, pitch ~20°, so sending the measured angles back pitched it further down at every glance (challenge 11,
2026-11-18: neck 44°, pitch 83° after three, the odometry 10-14 % short). So the head is given back that command, held until the sensor
faces as it did.

Numbers: the profile's `looking` block (`floor_z_m`, where the glance aims in the trunk frame: the stand height; `settle_frames` and
`yaw_tol_deg`: the sensor's yaw held this still over this many frames means the head is there; `max_s`, `collect_s`, `back_s`).
"""

import math
import time

from duck_lab.nav.client import LeaseLost
from duck_lab.nav.follow import wrap
from duck_lab.nav.side_drops import head_settled


class DuckHead:
    name = "duck-head"
    version = 1
    capable = True

    def __init__(self, profile):
        look = profile.looking
        self.floor_z_m = look.floor_z_m
        self.settle_frames, self.yaw_tol_deg = look.settle_frames, look.yaw_tol_deg
        self.max_s, self.collect_s, self.back_s = look.max_s, look.collect_s, look.back_s
        self.walk_command = dict(look.walk_command)
        self.robot = None
        self._steady = False
        self._yaw0 = 0.0

    def bind(self, robot) -> None:
        self.robot = robot

    @staticmethod
    def sensor_yaw(state: dict) -> float:
        """The depth sensor's yaw against the trunk (deg), from the state the frame was paired with."""
        w, x, y, z = state["frames"]["tof"]["quat"]
        return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

    @classmethod
    def sensor_dir(cls, state: dict) -> tuple:
        """The depth sensor's (yaw, pitch) against the trunk (deg)."""
        w, x, y, z = state["frames"]["tof"]["quat"]
        return cls.sensor_yaw(state), math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))

    def settled(self) -> bool:
        return self._steady

    def look_at(self, target: tuple, pose: tuple, hold, view, tick_s: float = 0.1) -> dict:
        """Aim at the floor at target (map metres) from pose and collect what the sensor then sees, holding the duck still with
        hold() each tick; view() is the newest frame as a perception. Returns {"failed": why} when robot.look failed, else
        {"frames": the classified frames (lists of (x, y, kind) in the map frame, floor and below-floor returns that count by
        their range), "bearing", "rel", "dist" (to the target, in the map and relative to the heading), "t0"}. A below-floor
        return counts by the same range-dependent threshold as every other frame (the sensor's below_counts): far floor reads a
        few cm low, and a glance into an open room counted it (challenge 7 seed 1: floor 1.7-2.5 m away read 6-9 cm low, the
        glance said "drop", the start was fenced in; sim/probes/glance_distance.py)."""
        t0 = time.monotonic()
        bearing = math.atan2(target[1] - pose[1], target[0] - pose[0])
        rel = wrap(bearing - pose[2])
        dist = math.dist(target, pose[:2])
        fv0 = view()
        self._yaw0 = self.sensor_yaw(fv0.state) if fv0 is not None and fv0.ok else 0.0   # where the sensor faced before
        self._steady = False
        try:
            ans = self.robot.call("robot.look", {"x": dist * math.cos(rel), "y": dist * math.sin(rel),
                                                 "z": self.floor_z_m, "neck_pitch": 0.0}) or {}
        except LeaseLost:
            raise                  # the gate ended this navigator's lease: not a failed look, the end of the run
        except (RuntimeError, OSError) as e:
            return {"failed": str(e)}
        head = ans.get("head")
        frames, seen, dirs, settled = [], None, [], None
        while time.monotonic() - t0 < self.max_s and (settled is None or time.monotonic() - settled < self.collect_s):
            if head:
                self.robot.call("robot.head", head)
            hold()
            fv = view()
            if fv is not None and fv is not seen and fv.ok and fv.pose is not None:
                seen = fv
                dirs.append(self.sensor_dir(fv.state))
                if settled is None and head_settled(dirs, self.settle_frames, self.yaw_tol_deg):
                    settled = time.monotonic()
                if settled is not None:
                    c, s_ = math.cos(fv.pose[2]), math.sin(fv.pose[2])
                    frames.append([(fv.pose[0] + c * ax - s_ * ay, fv.pose[1] + s_ * ax + c * ay, kind)
                                   for ax, ay, h, kind in fv.rel
                                   if kind == "floor" or (kind == "below" and fv.sensor.below_counts(h, math.hypot(ax, ay)))])
            time.sleep(tick_s)
        self._steady = settled is not None
        return {"frames": frames, "bearing": bearing, "rel": rel, "dist": dist, "t0": t0}

    def restore(self, hold, view, tick_s: float = 0.1) -> None:
        """Back to the walking command, held until the sensor faces as it did before the look."""
        back = time.monotonic()
        while time.monotonic() - back < self.back_s:
            self.robot.call("robot.head", self.walk_command)
            hold()
            fv = view()
            if fv is not None and fv.ok and abs(self.sensor_yaw(fv.state) - self._yaw0) < self.yaw_tol_deg:
                break
            time.sleep(tick_s)
