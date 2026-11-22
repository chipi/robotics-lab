"""A scene's description (phase 5 item 2, the operator's decision of 2026-11-22): what the world is, not a robot's or a machine's,
so it is versioned in the repository at scenes/<id>/scene.json. The Observatory's scene shape (`id`, `name`, `kind`, `frame`,
`bounds`, `boxes`, `hazards`) plus `rooms`. The runner's judge, guard and scores read it for the scene they run; the Observatory's
data folder holds a copy (`observatory scene <id>`). A run records `describe()` beside `judge_profile`, so the referee's map is as
traceable as its limits, and `changed_since` says when the file has changed after the run.

    sc = scenefile.load("apartment")       # SceneError when there is none, or it is not a scene
    sc.room_of((x, y)), sc.room_area("corridor"), sc.drop_geoms(), sc.bounds

A drop is the scene's own (`hazards` of kind `drop`): a scene with none has none, nothing is added."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[4] / "scenes"     # libs/runfile/src/runfile -> the repository's scenes/
HAZARD_KINDS = ("drop",)
FIELDS = ("id", "name", "kind", "frame", "bounds", "boxes", "hazards", "rooms")


class SceneError(ValueError):
    """No scene file, or one that is not a scene: said with its path."""


@dataclass(frozen=True)
class Room:
    name: str
    x0: float
    x1: float
    y0: float
    y1: float

    def holds(self, p, inset: float = 0.0) -> bool:
        return self.x0 + inset <= p[0] <= self.x1 - inset and self.y0 + inset <= p[1] <= self.y1 - inset


@dataclass(frozen=True)
class Scene:
    raw: dict
    path: Path | None
    bounds: tuple
    rooms: tuple
    drops: tuple

    @property
    def id(self) -> str:
        return self.raw["id"]

    def room_of(self, p, inset: float = 0.0) -> str | None:
        """The first room holding p (rooms share their walls: the file's order decides there), at least `inset` in from its walls."""
        return next((r.name for r in self.rooms if r.holds(p, inset)), None)

    def room_area(self, name: str) -> float:
        """A room's floor: its rectangle less the part of every drop inside it."""
        r = next(r for r in self.rooms if r.name == name)
        area = (r.x1 - r.x0) * (r.y1 - r.y0)
        for d in self.drops:
            w = min(r.x1, d["x1"]) - max(r.x0, d["x0"])
            h = min(r.y1, d["y1"]) - max(r.y0, d["y0"])
            if w > 0 and h > 0:
                if d.get("yaw", 0.0):
                    raise SceneError(f"{self.path}: the drop {d['name']} is turned; a room's area takes a drop along its axes")
                area -= w * h
        return area

    def drop_geoms(self) -> list:
        """The drops as box geoms (the simulator layout's shape, no height): what the guard and the judge measure distance to."""
        return [{"name": d["name"], "type": "box", "pos": [(d["x0"] + d["x1"]) / 2, (d["y0"] + d["y1"]) / 2, 0.0],
                 "size": [(d["x1"] - d["x0"]) / 2, (d["y1"] - d["y0"]) / 2, 0.0], "yaw": d.get("yaw", 0.0)} for d in self.drops]


def checksum(raw: dict) -> str:
    """A scene's identity: sha256 of its JSON with sorted keys and no spacing."""
    return "sha256:" + hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _rect(where: str, d: dict) -> tuple:
    try:
        x0, x1, y0, y1 = (float(d[k]) for k in ("x0", "x1", "y0", "y1"))
    except (KeyError, TypeError, ValueError):
        raise SceneError(f"{where}: needs numbers x0, x1, y0, y1") from None
    if not (x0 < x1 and y0 < y1):
        raise SceneError(f"{where}: x0 < x1 and y0 < y1, not {x0, x1, y0, y1}")
    return x0, x1, y0, y1


def from_dict(raw: dict, path: Path | None = None) -> Scene:
    """A scene description, checked: every field there, the bounds the right way round, each room inside them and named once, each
    hazard of a known kind (a drop with its depth)."""
    where = str(path) if path else f"scene {raw.get('id')!r}"
    missing = [k for k in FIELDS if k not in raw]
    if missing:
        raise SceneError(f"{where}: no {', '.join(missing)}")
    b = raw["bounds"]
    if not (isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b) and b[0] < b[1] and b[2] < b[3]):
        raise SceneError(f"{where}: bounds are [x0, x1, y0, y1] with x0 < x1 and y0 < y1, not {b}")
    rooms, seen = [], set()
    for r in raw["rooms"]:
        x0, x1, y0, y1 = _rect(f"{where}: room {r.get('name')!r}", r)
        if r["name"] in seen:
            raise SceneError(f"{where}: the room {r['name']!r} is named twice")
        if x0 < b[0] or x1 > b[1] or y0 < b[2] or y1 > b[3]:
            raise SceneError(f"{where}: the room {r['name']!r} reaches outside the bounds {b}")
        seen.add(r["name"])
        rooms.append(Room(r["name"], x0, x1, y0, y1))
    drops = []
    for h in raw["hazards"]:
        if h.get("kind") not in HAZARD_KINDS:
            raise SceneError(f"{where}: the hazard {h.get('name')!r} has kind {h.get('kind')!r}; the kinds: {', '.join(HAZARD_KINDS)}")
        _rect(f"{where}: hazard {h.get('name')!r}", h)
        if not isinstance(h.get("depth"), (int, float)) or h["depth"] <= 0:
            raise SceneError(f"{where}: the drop {h.get('name')!r} needs a depth above 0")
        drops.append(h)
    return Scene(raw, path, tuple(b), tuple(rooms), tuple(drops))


def read(path: Path) -> Scene:
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise SceneError(f"no scene file {path}") from None
    except (OSError, json.JSONDecodeError) as e:
        raise SceneError(f"{path}: {e}") from None
    scene = from_dict(raw, path)
    if scene.id != path.parent.name:
        raise SceneError(f"{path}: its id {scene.id!r} is not its folder's ({path.parent.name!r})")
    return scene


def load(scene_id: str, root: Path = REPOSITORY) -> Scene:
    """scenes/<id>/scene.json under `root` (default: the repository's)."""
    path = Path(root) / scene_id / "scene.json"
    if not path.exists():
        raise SceneError(f"no scene file for {scene_id!r} at {path}")
    return read(path)


def describe(path: Path) -> dict:
    """Which scene file a run was judged by: {id, path, checksum}. Any scene file, a challenge's too (it has no rooms: not checked)."""
    raw = json.loads(Path(path).read_text())
    return {"id": raw.get("id"), "path": str(path), "checksum": checksum(raw)}


def changed_since(recorded: dict | None, path: Path) -> bool | None:
    """Whether the scene file at `path` differs from the one a run recorded (`describe`); None when the run recorded none or there is
    no readable file: not known."""
    if not recorded or not recorded.get("checksum"):
        return None
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return checksum(raw) != recorded["checksum"]


def boxes_from_layout(layout: dict) -> list:
    """A simulator layout's colliding boxes and cylinders as a scene's boxes (a cylinder as its square), floors left out: how the
    apartment's boxes are made from robots/duck/sim/apartment_layout.json."""
    boxes = []
    for g in layout["geoms"]:
        if not g.get("collides") or str(g.get("name", "")).startswith("floor") or g.get("type") not in ("box", "cylinder"):
            continue
        hx, hy = (g["size"][0], g["size"][1]) if g["type"] == "box" else (g["size"][0], g["size"][0])
        hz = g["size"][2] if g["type"] == "box" else g["size"][1]
        boxes.append({"name": g.get("name", ""), "cx": g["pos"][0], "cy": g["pos"][1],
                      "z0": round(g["pos"][2] - hz, 4), "z1": round(g["pos"][2] + hz, 4),
                      "hx": hx, "hy": hy, "yaw": g.get("yaw", 0.0)})
    return boxes
