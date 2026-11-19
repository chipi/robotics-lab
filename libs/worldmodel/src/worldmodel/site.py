"""A site and its semantic map kept between runs (RFC-0016 revision 3; the operator, 2026-11-18: "B yes", sites and
areas, not homes).

A site is a named place robots work in (its kind: apartment, office, ...), with a site frame. In the simulator every run
starts at the dock, so a run's map frame is the site frame and a run's objects can be merged into the site's stored map
directly; at a real site the robot must first recognise where it is (later). Until Mission Control stores sites
(RFC-0014), a site is a folder: site.json (id, name, kind) and semantic_map.json.

Merging a run's map into the site's: each run object is matched to a stored object of the same kind by the semantic
map's association rule (its limits.assoc_m, unique_m for unique kinds); a match keeps the stored id, label and pins and takes the
run's position and sightings; no match is a new object with the next stable id. Stored objects not seen in the run
stay, unless the run forgot them (an object expected in view and not seen for a while: SemanticMap.forget): those are
marked gone, kept in the site's history, and an object the operator named is only flagged missing. A gone stored
object seen again is back. An object the operator named is never merged into another.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from worldmodel.objects import DUCK_LIMITS, Limits
from worldmodel.semantic_map import CONFIRM_N, SemanticMap


def inside(xy: tuple, polygon: list) -> bool:
    """Point in polygon (even-odd ray casting); the polygon's vertices in order, not closed."""
    x, y = xy
    hit = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


@dataclass
class Area:
    """A named region of a site that the operator defines (the operator, 2026-11-18: "the goal is that he can detect in
    which area he is … I definitely don't want a robot to create areas"): a name, an outline on the site map (site
    frame) and, optionally, an area type (kitchen, bedroom, office…). The robot never creates or suggests one."""
    aid: str
    name: str
    polygon: list
    type: str | None = None

    def to_json(self) -> dict:
        return {"id": self.aid, "name": self.name, "type": self.type, "polygon": [[round(v, 3) for v in p]
                                                                                for p in self.polygon]}


@dataclass
class Site:
    sid: str
    name: str
    kind: str
    folder: Path
    semantic: SemanticMap = field(default=None)
    areas: list = field(default_factory=list)

    def area_at(self, xy: tuple):
        """The operator's area the point is in (site frame), None outside all of them: geometry, not a guess."""
        return next((a for a in self.areas if inside(xy, a.polygon)), None)

    def add_area(self, name: str, polygon: list, type_: str | None = None) -> Area:
        if len(polygon) < 3:
            raise ValueError("an area's outline needs at least 3 points")
        if any(a.name.lower() == name.lower() for a in self.areas):
            raise ValueError(f"an area named {name!r} exists at site {self.sid}")
        aid = f"area_{len(self.areas) + 1}"
        while any(a.aid == aid for a in self.areas):
            aid += "x"
        area = Area(aid, name, [tuple(p) for p in polygon], type_)
        self.areas.append(area)
        return area

    @classmethod
    def create(cls, root: Path, sid: str, name: str, kind: str, kinds: dict, limits: Limits = DUCK_LIMITS) -> "Site":
        folder = Path(root) / sid
        if (folder / "site.json").exists():
            raise FileExistsError(f"site {sid} exists: {folder}")
        site = cls(sid, name, kind, folder, SemanticMap(kinds, site_kind=kind, limits=limits))
        site.save()
        return site

    @classmethod
    def load(cls, root: Path, sid: str, kinds: dict, limits: Limits = DUCK_LIMITS) -> "Site":
        folder = Path(root) / sid
        meta = json.loads((folder / "site.json").read_text())
        sem = folder / "semantic_map.json"
        semantic = (SemanticMap.from_json(json.loads(sem.read_text()), kinds, site_kind=meta["kind"], limits=limits) if sem.exists()
                    else SemanticMap(kinds, site_kind=meta["kind"], limits=limits))
        areas = [Area(a["id"], a["name"], [tuple(p) for p in a["polygon"]], a.get("type")) for a in meta.get("areas", [])]
        return cls(meta["id"], meta["name"], meta["kind"], folder, semantic, areas)

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "site.json").write_text(json.dumps({"id": self.sid, "name": self.name, "kind": self.kind,
                                                           "areas": [a.to_json() for a in self.areas]}, indent=1))
        (self.folder / "semantic_map.json").write_text(json.dumps(self.semantic.to_json(), indent=1))

    def merge(self, run: SemanticMap) -> dict:
        """Merge a run's confirmed objects into the site's map (the module's doc). Returns {"matched", "added"}."""
        matched, added, forgotten = 0, 0, 0
        taken = set()
        for o in run.objects:
            if not o.gone or o.n < CONFIRM_N:
                continue
            # the run forgot it (expected in view, not seen): the stored one goes too, kept in the history; one the
            # operator named is only flagged
            gate = self.semantic.limits.unique_m if self.semantic.kinds.get(o.kind, {}).get("unique") else self.semantic.limits.assoc_m
            same = [s for s in self.semantic.objects if s.kind == o.kind and not s.gone
                    and math.dist((s.x, s.y), (o.x, o.y)) <= gate]
            if same:
                s = min(same, key=lambda s: math.dist((s.x, s.y), (o.x, o.y)))
                if s.pinned:
                    s.missing = True
                else:
                    s.gone, s.gone_t = True, o.gone_t
                    forgotten += 1
        for o in run.confirmed():
            gate = self.semantic.limits.unique_m if self.semantic.kinds.get(o.kind, {}).get("unique") else self.semantic.limits.assoc_m
            same = [s for s in self.semantic.objects if s.kind == o.kind and s.oid not in taken
                    and math.dist((s.x, s.y), (o.x, o.y)) <= gate]
            if same:
                s = min(same, key=lambda s: math.dist((s.x, s.y), (o.x, o.y)))
                taken.add(s.oid)
                s.parts = [q.shifted(o.x - s.x, o.y - s.y) for q in s.parts]
                s.x, s.y, s.n = o.x, o.y, s.n + o.n
                s.gone, s.gone_t, s.misses, s.missing = False, None, o.misses, o.missing    # seen again: it is back
                s.last_t, s.confidence = o.last_t, max(s.confidence, o.confidence)
                s.sources = sorted(set(s.sources) | set(o.sources))
                s.evidence = (s.evidence + o.evidence)[-3:]
                matched += 1
            else:
                o.oid = self.semantic.new_id(o.kind)
                o.label, o.named_by, o.pinned = None, None, False
                self.semantic.objects.append(o)
                taken.add(o.oid)
                added += 1
        return {"matched": matched, "added": added, "forgotten": forgotten}

    def name_object(self, oid: str, label: str, by: str = "operator") -> None:
        """The operator names an object ("my desk"): the label, who named it, and a pin (never merged away)."""
        o = next((x for x in self.semantic.objects if x.oid == oid), None)
        if o is None:
            raise KeyError(f"no object {oid} at site {self.sid}")
        o.label, o.named_by, o.pinned = label, by, True
