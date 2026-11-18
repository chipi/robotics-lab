"""The semantic map (RFC-0016): the objects the duck has seen, in the map frame, over the occupancy grid.

A detection (from a camera: a kind, a range and bearing, a size and a height band, relative to the duck) is placed
with the duck's belief and associated with a tracked object of the same kind nearby — within ASSOC_M, or UNIQUE_M for
a kind a home has one of (kinds.json "unique": a fridge seen again after the belief drifted is the same fridge) —
else it starts a new one. An object's position follows its recent detections (the belief drifts; the object should
drift with it, not anchor the old frame), and it is confirmed after CONFIRM_N detections (one per camera look). From
the confirmed objects: the room the duck is in (objects near and in sight vote for their kinds' rooms; the room
changes only after it wins ROOM_TICKS looks in a row), an object by kind, and where to stand to reach one.
"""

import math
from dataclasses import dataclass, field

from duck_lab.world_model.objects import Part, blocking, distance

ASSOC_M = 0.5              # a detection this close to a tracked object of its kind is that object
UNIQUE_M = 1.5             # ... for a kind the home has one of: drift between two sightings of the fridge
RECENT = 0.3               # the newest detection's weight at least (the position follows the drifting belief)
CONFIRM_N = 3              # detections (one per look) before an object is trusted
ROOM_RADIUS_M = 1.2        # objects within this vote for the room the duck is in (the corridor is 1.5 m wide)
ROOM_TICKS = 3             # looks a new room must win in a row before the duck says it is there
STAND_M = 0.25             # where to stand to reach an object: this far from its outline (lethal 0.12 + room)


@dataclass
class Detection:
    """What a camera reports, nothing else: a kind; the object as a disc relative to the duck (x ahead, y left), its
    radius and height band; the range it was seen at. No name and no world coordinate (the sim camera's leak test)."""
    kind: str
    x: float
    y: float
    radius: float
    z0: float
    z1: float
    range_m: float

    def part(self) -> Part:
        return Part(self.x, self.y, self.radius, self.radius, 0.0, self.z0, self.z1)


@dataclass
class Tracked:
    oid: str
    kind: str
    x: float
    y: float
    parts: list                    # in the map frame
    n: int = 1
    first_t: float = 0.0
    last_t: float = 0.0
    props: dict = field(default_factory=dict)

    @property
    def confirmed(self) -> bool:
        return self.n >= CONFIRM_N

    def summary(self) -> dict:
        return {"id": self.oid, "kind": self.kind, "x": round(self.x, 3), "y": round(self.y, 3), "n": self.n,
                "confirmed": self.confirmed, "landmark": self.props.get("landmark", 0.0),
                "permanence": self.props.get("permanence"), "first_t": round(self.first_t, 1),
                "last_t": round(self.last_t, 1),
                "parts": [[round(v, 3) for v in (q.x, q.y, q.hx, q.hy, q.yaw, q.z0, q.z1)] for q in self.parts]}


def centre(parts) -> tuple:
    w = [max(q.hx * q.hy, 1e-6) for q in parts]
    return (sum(q.x * a for q, a in zip(parts, w)) / sum(w), sum(q.y * a for q, a in zip(parts, w)) / sum(w))


def wall_between(grid: dict, a: tuple, b: tuple) -> bool:
    """Whether mapd's grid (map.grid, scaled) has a wall cell on the line a-b: the brain's own sight line, no truth."""
    if not grid or grid.get("res_m", 0) <= 0 or not grid.get("cells"):     # mapd before its first stop: no walls yet
        return False
    res, (ox, oy), w, h, cells = grid["res_m"], grid["origin"], grid["width"], grid["height"], grid["cells"]
    n = max(1, int(math.dist(a, b) / (res / 2)))
    for i in range(1, n):
        x, y = a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n
        cx, cy = math.floor((x - ox) / res), math.floor((y - oy) / res)
        if 0 <= cx < w and 0 <= cy < h and cells[cy * w + cx] == "#":
            return True
    return False


class SemanticMap:
    def __init__(self, kinds: dict):
        self.kinds = kinds
        self.objects: list = []
        self._next = {}
        self._room, self._lead, self._lead_n = None, None, 0

    def integrate(self, detections: list, pose: tuple, t: float = 0.0) -> list:
        """Place each detection with the duck's pose (map frame) and track it. Returns the changes, as
        ("new" | "confirmed", object) pairs."""
        changes = []
        for d in detections:
            part = d.part().moved(pose)
            cx, cy = part.x, part.y
            gate = UNIQUE_M if self.kinds.get(d.kind, {}).get("unique") else ASSOC_M
            same = [o for o in self.objects if o.kind == d.kind and math.dist((o.x, o.y), (cx, cy)) <= gate]
            if same:
                o = min(same, key=lambda o: math.dist((o.x, o.y), (cx, cy)))
                a = max(1.0 / (o.n + 1), RECENT)
                nx, ny = o.x + a * (cx - o.x), o.y + a * (cy - o.y)
                was = o.confirmed
                o.parts = [q.shifted(nx - o.x, ny - o.y) for q in o.parts]
                o.x, o.y, o.n, o.last_t = nx, ny, o.n + 1, t
                if o.confirmed and not was:
                    changes.append(("confirmed", o))
            else:
                k = self._next.get(d.kind, 0) + 1
                self._next[d.kind] = k
                o = Tracked(f"{d.kind}_{k}", d.kind, cx, cy, [part], 1, t, t, self.kinds.get(d.kind, {}))
                self.objects.append(o)
                changes.append(("new", o))
        return changes

    def confirmed(self) -> list:
        return [o for o in self.objects if o.confirmed]

    def find(self, kind: str, pose: tuple = None):
        """The confirmed object of this kind nearest the pose (else the most recently seen), None when none is known."""
        of = [o for o in self.confirmed() if o.kind == kind]
        if not of:
            return None
        if pose is None:
            return max(of, key=lambda o: o.last_t)
        return min(of, key=lambda o: math.dist((o.x, o.y), pose[:2]))

    def votes(self, pose: tuple, grid: dict = None, radius_m: float = ROOM_RADIUS_M) -> dict:
        """Each confirmed object within radius_m and not behind a wall of the brain's map votes its kind's room hints,
        weighted 1 / (1 + d)^2."""
        votes = {}
        for o in self.confirmed():
            d = math.dist((o.x, o.y), pose[:2])
            if d > radius_m or wall_between(grid, pose[:2], (o.x, o.y)):
                continue
            for room, w in o.props.get("rooms", {}).items():
                votes[room] = votes.get(room, 0.0) + w / (1.0 + d) ** 2
        return {k: round(v, 3) for k, v in sorted(votes.items(), key=lambda kv: -kv[1])}

    def room_at(self, pose: tuple, grid: dict = None):
        """(room, votes): the room the duck says it is in. None while no object near says anything; a different room
        only after it has led ROOM_TICKS looks in a row (no flapping in doorways). Call once per look."""
        votes = self.votes(pose, grid)
        lead = next(iter(votes), None)
        if lead is None:
            self._room, self._lead, self._lead_n = None, None, 0
        elif lead == self._room:
            self._lead, self._lead_n = None, 0
        else:
            self._lead_n = self._lead_n + 1 if lead == self._lead else 1
            self._lead = lead
            if self._room is None or self._lead_n >= ROOM_TICKS:
                self._room, self._lead, self._lead_n = lead, None, 0
        return self._room, votes

    def blocking_points(self, spacing: float = 0.03) -> list:
        """Outline points of the confirmed objects' parts the duck must go around (the semantic cost layer, off by
        default: RFC-0016 §5)."""
        return [p for o in self.confirmed() for q in blocking(o.parts) for p in q.outline(spacing)]

    def approach(self, o: Tracked, pose: tuple, free=lambda p: True, stand_m: float = STAND_M, step_deg: int = 10):
        """Where to stand to reach object o: on a ring stand_m from its outline, a point free() accepts (the caller's
        cost map, with room to turn), the nearest to the duck; with the heading that faces the object. None when no
        point on the ring is free."""
        parts = blocking(o.parts) or o.parts
        best = None
        for k in range(0, 360, step_deg):
            a = math.radians(k)
            r, p = 0.0, None
            while r < 3.0:
                p = (o.x + r * math.cos(a), o.y + r * math.sin(a))
                if distance(parts, p) >= stand_m:
                    break
                r += 0.02
            if r >= 3.0 or not free(p):
                continue
            if best is None or math.dist(p, pose[:2]) < math.dist(best, pose[:2]):
                best = p
        if best is None:
            return None
        return best[0], best[1], math.atan2(o.y - best[1], o.x - best[0])

    def to_json(self) -> dict:
        return {"objects": [o.summary() for o in self.objects]}

    @classmethod
    def from_json(cls, data: dict, kinds: dict) -> "SemanticMap":
        m = cls(kinds)
        for s in data["objects"]:
            parts = [Part(*p) for p in s["parts"]]
            o = Tracked(s["id"], s["kind"], s["x"], s["y"], parts, s["n"], s.get("first_t", 0.0), s.get("last_t", 0.0),
                        kinds.get(s["kind"], {}))
            m.objects.append(o)
            k = int(s["id"].rsplit("_", 1)[1])
            m._next[s["kind"]] = max(m._next.get(s["kind"], 0), k)
        return m
