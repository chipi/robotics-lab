"""Before "trapped" (the advisor's R1; docs/wip/EXPLORE-PROGRESS.md, b11): the pure choices.

b11 ended four of five runs "trapped" in under four minutes: six refusals at one pose within half a second ("no room to turn"
asked of six different targets, one pose), nothing tried between them. A refusal at a pose says the pose is tight, not that the
target is out of reach. So a refusal first costs a recovery at that pose: a creep forward when the depth sensor shows room
ahead, else an arc away from the nearest hazard, then a stand for mapd (a survey); only when MAX_ATTEMPTS of those have not
freed the duck does a refusal count toward "trapped".

choose(): which motion an attempt makes. away_target(): a first leg that leaves a drop the run started beside.
"""

import math

CREEP_FLOOR_MM = 150      # the sensor's reading at the end of a creep: the footprint 83 mm + the following's error and the judge's margin 70 mm
CREEP_M = 0.10            # a creep of 0.1-0.2 m; the advisor's derivation (2026-11-19): short, to where a pivot is allowed, not a nudge
CREEP_CLEAR_MM = CREEP_FLOOR_MM + round(CREEP_M * 1000)    # what the sensor must show to begin one: 250 mm
ARC_CLEAR_MM = 300        # an arc needs more: it reaches 0.2 m ahead plus the footprint (run.ARC_CLEAR_MM, the same number)
MAX_ATTEMPTS = 3          # recoveries in a row (no leg reached between) before a refusal counts
HAZARD_DROP_M = 1.0       # a remembered drop this near is what an arc turns away from; else the nearest obstacle point ...
HAZARD_OBSTACLE_M = 0.4   # ... this near
DROP_AHEAD_M = 0.6        # a remembered drop within this (cliff.CLIFF_STOP_M) in front of the duck forbids a creep
DROP_AHEAD_DEG = 35.0     # ... in this cone either side of the heading
START_MARGIN_M = 0.45     # a run that starts with a drop this near leaves it first (run.ARC_REACH_M: what a turn sweeps)
AWAY_M = (0.5, 0.4, 0.6)  # how far the first leg goes, in order of preference
AWAY_SPREAD_DEG = (0, 30, -30, 60, -60)


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def drop_ahead(pose: tuple, drops: list) -> bool:
    """A remembered drop within DROP_AHEAD_M and DROP_AHEAD_DEG of the heading."""
    return any(math.dist(pose[:2], d) <= DROP_AHEAD_M
               and abs(math.degrees(_wrap(math.atan2(d[1] - pose[1], d[0] - pose[0]) - pose[2]))) <= DROP_AHEAD_DEG
               for d in drops)


def hazard(pose: tuple, drops: list, obstacles: list) -> tuple | None:
    """What an arc turns away from: (point, "drop" | "obstacle"), the nearest drop within HAZARD_DROP_M, else the nearest
    obstacle point within HAZARD_OBSTACLE_M; None when there is none."""
    d = min(drops, key=lambda p: math.dist(p[:2], pose[:2]), default=None)
    if d is not None and math.dist(d[:2], pose[:2]) <= HAZARD_DROP_M:
        return tuple(d[:2]), "drop"
    o = min(obstacles, key=lambda p: math.dist(p[:2], pose[:2]), default=None)
    if o is not None and math.dist(o[:2], pose[:2]) <= HAZARD_OBSTACLE_M:
        return tuple(o[:2]), "obstacle"
    return None


def creep_gains_room(room_now: float, room_ahead: float, min_room_m: float) -> bool:
    """A creep is a move to where a pivot is allowed, not a nudge (the advisor, 2026-11-19): the room (clearance to the
    remembered obstacles) CREEP_M ahead must be a turn's room and more than the room now. b11 r5: 0.136 m here, 0.178 m ahead
    (a creep frees it); r3: 0.114 m of room, 0.088 ahead (a creep walks into the memory: not a recovery)."""
    return room_ahead >= min_room_m and room_ahead >= room_now


def projected_room(pose: tuple, points: list, ahead_m: float) -> tuple:
    """(room now, room ahead_m along the heading): the distance from the pose, and from the point ahead of it, to the nearest of
    points (the remembered obstacle points); inf when there are none."""
    ahead = (pose[0] + ahead_m * math.cos(pose[2]), pose[1] + ahead_m * math.sin(pose[2]))
    return (min((math.dist(pose[:2], p[:2]) for p in points), default=math.inf),
            min((math.dist(ahead, p[:2]) for p in points), default=math.inf))


def choose(attempt: int, clear_mm: float | None, drop_in_front: bool, haz: tuple | None, creep_ok: bool = True) -> str:
    """The motion of recovery attempt number `attempt` (0, 1, 2 ...): "creep" (odd attempts try the other motion first when
    both are possible, so a creep that did not free the duck is followed by an arc, and the reverse), "arc", or "stand" (the
    survey alone). Creep: the sensor shows CREEP_CLEAR_MM ahead, no remembered drop is in front and creep_ok (the room ahead
    is a turn's room: creep_gains_room). Arc: there is a hazard to turn away from and the sensor shows ARC_CLEAR_MM."""
    can_creep = clear_mm is not None and clear_mm >= CREEP_CLEAR_MM and not drop_in_front and creep_ok
    can_arc = clear_mm is not None and clear_mm >= ARC_CLEAR_MM and haz is not None
    order = ("creep", "arc") if attempt % 2 == 0 else ("arc", "creep")
    for kind in order:
        if (kind == "creep" and can_creep) or (kind == "arc" and can_arc):
            return kind
    return "stand"


def turn_away(pose: tuple, point: tuple) -> float:
    """The sign of a turn that takes the heading away from `point`: +1 left, -1 right (the point to the left is turned from to
    the right); +1 when it is straight ahead or behind."""
    b = _wrap(math.atan2(point[1] - pose[1], point[0] - pose[0]) - pose[2])
    return -1.0 if 0.0 < b < math.pi - 1e-6 else 1.0


def away_target(pose: tuple, drops: list, ok) -> tuple | None:
    """A place to go first when the run starts within START_MARGIN_M of a remembered drop: from the pose, directly away from the
    nearest one (and AWAY_SPREAD_DEG either side), AWAY_M out, the first that ok(point) accepts (seen floor, not lethal, room
    to turn: the explorer's test). None when nothing is within the margin, or nothing is accepted."""
    near = min(drops, key=lambda p: math.dist(p[:2], pose[:2]), default=None)
    if near is None or math.dist(near[:2], pose[:2]) > START_MARGIN_M:
        return None
    away = math.atan2(pose[1] - near[1], pose[0] - near[0])
    for dist in AWAY_M:
        for spread in AWAY_SPREAD_DEG:
            a = away + math.radians(spread)
            p = (pose[0] + dist * math.cos(a), pose[1] + dist * math.sin(a))
            if ok(p):
                return p
    return None
