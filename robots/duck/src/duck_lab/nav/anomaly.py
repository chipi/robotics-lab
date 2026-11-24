"""The navigator's own anomalies (RFC-0019 §3.1, PHASE3-PREP B1): something it noticed, while running, that should not have happened.

One record, RFC-0019 §2.1's, written as an event of the run (`event: "anomaly"`, source "robot") by `Navigator.anomaly`; the
analysis side (`observatory anomalies`) writes the same record with source "analysis". The row carries no `decision`: a decision is
a rule that fired and feeds Mission Control's listeners and guardrails, and an anomaly is a note on the timeline that must not
change what the navigator does. The simulator's truth pose comes from the run's own row (`Navigator._record` adds it to every row);
`where` carries what the robot knew, the belief, in the map frame.

Here: the record's builder, and the rules that need state across ticks, pure and testable without a simulator. The raise points
are in run.py (the fix gate, the relocaliser, stuck, the frames, the turn rules, the planner's refusals, the state handler, the
camera, the streams' watchdog, the lease), explore_run.py (the refusal burst) and server.py (the lease). The numbers that are the
duck's are its profile's `anomalies` block (with their measurement); the policy numbers are here, each with where it came from.
"""

import collections
import math
import threading

SEVERITIES = ("info", "minor", "major", "critical")
SOURCE = {"guardrail_broken": "harness", "guardrail_unenforced": "harness", "rtf_low": "harness"}      # the kinds the navigator records for another source; the rest are "robot"
VERSION = 1

# anomaly -> (module, detector, the severity it is raised at unless the raise point says otherwise). Proposed from the runs (RFC-0019 §6
# question 1); the operator reviews them. info: worth seeing; minor: cost time; major: put the run at risk.
KINDS = {
    "fix_jump_held": ("localizer", "fix_gate", "major"),
    "reloc_refused": ("relocaliser", "landmark_window", "minor"),
    "stuck": ("navigator", "stuck_watch", "major"),
    "frames_parted": ("localizer", "frame_watch", "minor"),
    "refusal_burst": ("explorer", "refusal_burst", "major"),
    "room_disagrees": ("navigator", "turn_room", "info"),
    "head_off_walk": ("navigator", "head_watch", "minor"),
    "refused_unexplained": ("planner", "planner_refusal", "minor"),
    "camera_failed": ("camera", "camera_watch", "major"),
    "thread_failed": ("navigator", "stream_watchdog", "major"),
    "stop_latched": ("gate", "lease_watch", "info"),
    "lease_lost": ("gate", "lease_watch", "major"),
    # the body's (body.BodyWatch, at the profile's joints.limits): a joint held past its current or tracking limit, the hottest servo,
    # the control loop, robotd's own verdict (minor when it says degraded)
    "joint_overload": ("body", "joint_current", "major"),
    "joint_tracking": ("body", "joint_tracking", "major"),
    "motor_hot": ("body", "motor_temperature", "major"),
    "loop_slow": ("body", "control_loop", "minor"),
    "robot_unhealthy": ("body", "robot_health", "major"),
    # the harness's (RFC-0019 §2.1's third source): the runner's guardrails only the simulator's truth can check (a contact, a fall,
    # a drop margin broken), told to the navigator by `goal.break`; recorded by it, with source "harness"
    "guardrail_broken": ("runner", "truth_guard", "critical"),
    # a guardrail the goal asked for and its runner has no truth to check (a real robot): said once at the goal's start (`not_enforced`)
    "guardrail_unenforced": ("runner", "truth_guard", "minor"),
    # the robot's own sensors broke a guardrail (guardrails.RobotSide): critical when it stops the goal (no truth, the robot is the only
    # judge), minor when a truth exists and the robot only records what it would have done (the runner's referee judges, and its own
    # guardrail_broken is the critical one); contract 1.7. `values.enforced` says which
    "robot_guard": ("navigator", "robot_side_guard", "critical"),
    # the simulator ran slower than the wall clock (the runner's sampler: simhost.truth RTF_LOW): timing, timeouts and the truth pairing
    # of the run are not what they say, so the run has no verdict; minor, not major: the robot is not unfit (Mission Control makes a robot
    # unfit for a major one), the simulator is slow; told to the navigator by `goal.anomaly` (contract 1.6)
    "rtf_low": ("runner", "real_time_factor", "minor"),
}

# A refusal at one pose repeats for every target the explorer tries (b11 r5: six "no room to turn" in 1 s at one pose, 0.283-0.290
# m ahead each time): said again for a place only once the duck has moved this far from where it was last said, or this long after.
PLACE_MOVED_M = 0.10
PLACE_GAP_S = 5.0

# The refusal burst (explorer): refusals in a row at one pose with no motion between. The refused legs of the 66 apartment recordings,
# grouped by pose (each within 0.10 m of the group's first), came in groups of 1: 81, 2: 18, 3: 16, 4: 3, 5: 3, 6 or more: 35 (the
# explorer calls 6 in a row "trapped"). Three targets refused at one pose is the pose's trouble more than the targets': the limit is
# the first count past the 1 and 2 that are one bad target or two, and it says so three legs before "trapped" does.
BURST_N = 3
BURST_MOVED_M = 0.10


def record(kind: str, summary: str, severity: str | None = None, *, belief=None, mapd=None, values: dict | None = None, margin=None,
           duration_s: float = 0.0, evidence: dict | None = None, related: list | None = None) -> dict:
    """The event row for one anomaly: RFC-0019 §2.1's fields, `t` (and the truth) added by the navigator's record. `margin`: how far
    past its threshold it was, in the unit `values["margin_unit"]` says (metres unless it says otherwise). `duration_s`: how long
    it lasted when the raise point knows (the analysis side's `t_end` is `t` plus this)."""
    module, detector, default = KINDS[kind]
    severity = severity or default
    if severity not in SEVERITIES:
        raise ValueError(f"severity {severity!r}: one of {', '.join(SEVERITIES)}")
    where = {"frame": "map"}
    if belief is not None:
        where["belief"] = [round(float(belief[0]), 3), round(float(belief[1]), 3)]
    if mapd is not None:
        where["mapd"] = [round(float(mapd[0]), 3), round(float(mapd[1]), 3)]
    return {"event": "anomaly", "anomaly": kind, "source": SOURCE.get(kind, "robot"), "module": module, "severity": severity,
            "detector": detector,
            "version": VERSION, "summary": summary, "values": values or {}, "margin": None if margin is None else round(float(margin), 4),
            "where": where, "evidence": evidence or {}, "related": related or [], "duration_s": round(float(duration_s), 3)}


def over(dist_m: float, limit_m: float, turn_rad: float, limit_rad: float) -> tuple:
    """(margin, unit) of something a distance or a turn limits: metres past the distance limit when it is past, else radians past
    the turn limit."""
    if dist_m > limit_m:
        return dist_m - limit_m, "m"
    return turn_rad - limit_rad, "rad"


class PlaceGate:
    """Said once for a place: `allow` is True the first time, and again when the pose is `moved_m` from the last place it was allowed
    at, or `gap_s` has passed."""

    def __init__(self, moved_m: float = PLACE_MOVED_M, gap_s: float = PLACE_GAP_S):
        self.moved_m, self.gap_s = moved_m, gap_s
        self.last = None            # (t, xy)

    def allow(self, t: float, xy: tuple) -> bool:
        xy = tuple(xy[:2])
        if self.last is not None and t - self.last[0] < self.gap_s and math.dist(self.last[1], xy) <= self.moved_m:
            return False
        self.last = (t, xy)
        return True


class RefusalBurst:
    """Refusals in a row at one pose, with no motion between. `refused(xy)` is called with the belief's position for each refused
    leg; it returns the count when the streak reaches `n` (once for a streak), else None. A streak starts again when a refusal is
    more than `moved_m` from its first; `reset()` when a leg was not refused."""

    def __init__(self, n: int = BURST_N, moved_m: float = BURST_MOVED_M):
        self.n, self.moved_m = n, moved_m
        self.reset()

    def reset(self) -> None:
        self.first, self.count, self.said = None, 0, False

    def refused(self, xy: tuple) -> int | None:
        if self.first is None or math.dist(self.first, xy[:2]) > self.moved_m:
            self.first, self.count, self.said = tuple(xy[:2]), 1, False
        else:
            self.count += 1
        if self.count >= self.n and not self.said:
            self.said = True
            return self.count
        return None


# The most frames Returns holds, whatever the window: 240 is 4 s of a 60 Hz sensor, four times the tof8x8's 15 Hz, and at 64 returns
# a frame (8x8) under 16 000 small tuples. The window prunes first; this is the bound if frames ever come faster.
RETURNS_MAX_FRAMES = 240


class Returns:
    """The depth returns of the last `window_s` seconds, one entry per frame (time, then (x, y, kind) in map metres, kind the first
    letter the sensor's FrameView gives: o obstacle or overhead, f floor, b below), newest last. Bounded in time (older frames go at each `add`)
    and in size (RETURNS_MAX_FRAMES). Written from the depth stream's thread, read from the navigator's: under a lock."""

    def __init__(self, window_s: float):
        self.window_s = window_s
        self._frames = collections.deque(maxlen=RETURNS_MAX_FRAMES)
        self._lock = threading.Lock()

    def add(self, t: float, points) -> None:
        """A frame's points, [x, y, z, kind] each (FrameView.points), at time t (seconds, one clock for add and `last`)."""
        kept = tuple((p[0], p[1], p[3]) for p in points)
        with self._lock:
            self._frames.append((t, kept))
            while self._frames[0][0] < t - self.window_s:
                self._frames.popleft()

    def move(self, mv) -> None:
        """The frame change the memory moved by (`mv` maps (x, y) to the new (x, y)): the returns are placed with the belief too."""
        with self._lock:
            self._frames = collections.deque(((t, tuple(mv((x, y)) + (k,) for x, y, k in pts)) for t, pts in self._frames),
                                             maxlen=RETURNS_MAX_FRAMES)

    def last(self, t: float) -> list:
        """The returns of the frames in [t - window_s, t], flattened."""
        with self._lock:
            frames = list(self._frames)
        return [q for ft, pts in frames if t - self.window_s <= ft <= t for q in pts]


def nearest_obstacle(pose: tuple, grid: dict | None, points, near_m: float) -> tuple | None:
    """(distance, (x, y)) of the map's nearest obstacle within `near_m` of the pose: the centres of mapd's occupied cells (`grid` as
    the navigator reads it: res_m, origin, width, height, cells with "#" for a wall) and the remembered points; None when none is."""
    best = (math.inf, None)
    if grid:
        res, (ox, oy), w, h, cells = grid["res_m"], grid["origin"], grid["width"], grid["height"], grid["cells"]
        r = int(near_m / res) + 1
        cx0, cy0 = math.floor((pose[0] - ox) / res), math.floor((pose[1] - oy) / res)
        for cy in range(max(0, cy0 - r), min(h, cy0 + r + 1)):
            for cx in range(max(0, cx0 - r), min(w, cx0 + r + 1)):
                if cells[cy * w + cx] == "#":
                    q = (ox + (cx + .5) * res, oy + (cy + .5) * res)
                    d = math.hypot(q[0] - pose[0], q[1] - pose[1])
                    if d < best[0]:
                        best = (d, q)
    for q in points:
        d = math.hypot(q[0] - pose[0], q[1] - pose[1])
        if d < best[0]:
            best = (d, (q[0], q[1]))
    return best if best[0] <= near_m else None


def room_verdict(pose: tuple, grid: dict | None, points, returns: Returns, t: float, *, look_deg: float, near_m: float, see_m: float,
                 agree_m: float, floor_slack_m: float) -> dict | None:
    """Which of the map and the depth sensor a refusal for no room to turn can be believed (K36; the rule is
    sim/probes/room_rule.py's, measured on the apartment recordings). The map's nearest obstacle (nearest_obstacle) gives a bearing and
    a distance; the returns of the last window within `look_deg` of that bearing and `see_m` of the pose are what the sensor saw
    that way. "agrees": an obstacle return at or nearer than the map's distance plus `agree_m`; "disagrees": none, and a floor return
    at or beyond the map's distance less `floor_slack_m`; "unclear": returns, but neither; "unseen": no return that way. None when
    the map has no obstacle within `near_m`. `obstacle_m`: the nearest obstacle return that way; `floor_beyond_m`: the nearest floor
    return at or beyond the map's distance (less the slack)."""
    near = nearest_obstacle(pose, grid, points, near_m)
    if near is None:
        return None
    dm, (qx, qy) = near
    bearing = math.atan2(qy - pose[1], qx - pose[0])
    looked, obstacle, floor = 0, None, None
    for x, y, kind in returns.last(t):
        dx, dy = x - pose[0], y - pose[1]
        d = math.hypot(dx, dy)
        if d > see_m or d < 0.02:
            continue
        if abs(math.degrees((math.atan2(dy, dx) - bearing + math.pi) % (2 * math.pi) - math.pi)) > look_deg:
            continue
        looked += 1
        if kind == "o" and (obstacle is None or d < obstacle):
            obstacle = d
        if kind == "f" and d >= dm - floor_slack_m and (floor is None or d < floor):
            floor = d
    near_obstacle = obstacle is not None and obstacle <= dm + agree_m
    verdict = "unseen" if not looked else "agrees" if near_obstacle else "disagrees" if floor is not None else "unclear"
    return {"verdict": verdict, "bearing_rad": bearing, "map_m": dm, "obstacle_m": obstacle, "floor_beyond_m": floor, "returns": looked}


class HeadWatch:
    """The head away from its walking pose while the duck walks (the glance that left the head pitched and tilted the odometry,
    EXPLORE-PROGRESS.md). `pose`: the head joints' walking angles (the profile's anomalies.head_walk_pose); a joint more than `off_rad`
    from its angle, for `hold_s` of unbroken walking, is one anomaly, said once until the head is back within `off_rad`. Standing
    (a glance, a survey) clears the timer but not the episode: the head is meant to be off then, and the episode ends when it is
    back. update() returns the evidence when it fires."""

    def __init__(self, pose: dict, off_rad: float, hold_s: float):
        self.pose, self.off_rad, self.hold_s = dict(pose), off_rad, hold_s
        self.since, self.said = None, False

    def update(self, t: float, walking: bool, joints: dict) -> dict | None:
        devs = {j: abs(joints[j] - a) for j, a in self.pose.items() if j in joints}
        if not devs:
            return None
        joint = max(devs, key=devs.get)
        if devs[joint] <= self.off_rad:
            self.since, self.said = None, False
            return None
        if not walking:
            self.since = None
            return None
        if self.since is None:
            self.since = t
        if self.said or t - self.since < self.hold_s:
            return None
        self.said = True
        return {"joint": joint, "deviation_rad": round(devs[joint], 3), "angle_rad": round(joints[joint], 3),
                "walking_pose_rad": self.pose[joint], "walking_s": round(t - self.since, 2)}


class Staleness:
    """A stream that stops: `seen(t)` on each message, `check(t)` from a watchdog; check returns the silence in seconds once, when it
    passes `limit_s` (and again only after the stream has spoken in between)."""

    def __init__(self, limit_s: float, start: float):
        self.limit_s, self.last, self.said = limit_s, start, False

    def seen(self, t: float) -> None:
        self.last, self.said = t, False

    def check(self, t: float) -> float | None:
        age = t - self.last
        if age <= self.limit_s or self.said:
            return None
        self.said = True
        return age
