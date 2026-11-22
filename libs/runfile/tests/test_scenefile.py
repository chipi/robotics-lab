"""A scene's description (phase 5 item 2, runfile/scenefile.py): read and checked from scenes/<id>/scene.json, its rooms and drops
as the runner's judge, guard and scores read them (a scene with no drop has none: nothing is added), its checksum the same across
key order and spacing and changed by any value, a run's recorded scene compared with the file as it is now, the boxes taken from a
simulator's layout, and the repository's apartment read. No robot's package.
Run: cd libs/runfile && uv run python tests/test_scenefile.py"""

import atexit
import copy
import json
import shutil
import tempfile
from pathlib import Path

from helpers import Checks
from runfile import scenefile
from runfile.scenefile import SceneError

check = Checks("SCENE FILE")
tmp = Path(tempfile.mkdtemp(prefix="scenefile-"))
atexit.register(shutil.rmtree, tmp, True)

ROOM = {"id": "room", "name": "One room", "kind": "test", "frame": "world", "bounds": [-1.0, 1.0, -1.0, 1.0],
        "boxes": [{"name": "crate", "cx": 0.5, "cy": 0.5, "z0": 0.0, "z1": 0.3, "hx": 0.1, "hy": 0.1, "yaw": 0.0}],
        "hazards": [], "rooms": [{"name": "room", "x0": -1.0, "x1": 1.0, "y0": -1.0, "y1": 1.0}]}
PIT = {**ROOM, "id": "pit", "hazards": [{"name": "pit", "kind": "drop", "x0": 0.0, "x1": 0.4, "y0": -0.5, "y1": 0.2, "yaw": 0.0,
                                         "depth": 0.4}]}


def write(scene: dict, root: Path = tmp) -> Path:
    p = root / scene["id"] / "scene.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scene))
    return p


def raises(fn, why):
    try:
        fn()
    except SceneError as e:
        return why in str(e), str(e)
    return False, "no error"


write(ROOM)
write(PIT)
room, pit = scenefile.load("room", tmp), scenefile.load("pit", tmp)
check("a scene with no drop has none: nothing is added", room.drops == () and room.drop_geoms() == [])
check("a scene's drop is its own, as a box geom for the guard", [g["name"] for g in pit.drop_geoms()] == ["pit"]
      and pit.drop_geoms()[0]["pos"][:2] == [0.2, -0.15] and pit.drop_geoms()[0]["size"][:2] == [0.2, 0.35], pit.drop_geoms())
check("bounds", room.bounds == (-1.0, 1.0, -1.0, 1.0))
check("room_of: inside, on the inset, outside", room.room_of((0.0, 0.0)) == "room" and room.room_of((0.95, 0.0), 0.1) is None
      and room.room_of((1.5, 0.0)) is None)
check("a room's area less the drops inside it", room.room_area("room") == 4.0 and abs(pit.room_area("room") - (4.0 - 0.28)) < 1e-12,
      pit.room_area("room"))
check("a drop reaching out of the room counts only its part inside",
      abs(scenefile.from_dict({**PIT, "hazards": [{**PIT["hazards"][0], "x0": 0.8, "x1": 1.4}]}).room_area("room") - (4.0 - 0.14))
      < 1e-12)

check("the checksum ignores key order", scenefile.checksum(dict(reversed(list(ROOM.items())))) == scenefile.checksum(ROOM))
check("the checksum of a file is its content's, not its spacing's",
      scenefile.checksum(json.loads(json.dumps(ROOM, indent=3))) == scenefile.checksum(ROOM))
moved = copy.deepcopy(PIT)
moved["hazards"][0]["depth"] = 0.3
check("any value changes the checksum", scenefile.checksum(moved) != scenefile.checksum(PIT))
d = scenefile.describe(pit.path)
check("describe: what a run records", d == {"id": "pit", "path": str(tmp / "pit" / "scene.json"), "checksum": scenefile.checksum(PIT)}, d)
check("a run judged by the file as it is: not changed", scenefile.changed_since(d, tmp / "pit" / "scene.json") is False)
write(moved)
check("must fail: the file changed after the run: said", scenefile.changed_since(d, tmp / "pit" / "scene.json") is True)
check("a run with no scene recorded, or no file now: not known", scenefile.changed_since(None, tmp / "pit" / "scene.json") is None
      and scenefile.changed_since(d, tmp / "gone" / "scene.json") is None)

ok, why = raises(lambda: scenefile.load("nowhere", tmp), "no scene file")
check("must fail: a scene with no file, said with the path", ok and str(tmp / "nowhere") in why, why)
for name, bad, said in (
        ("an id that is not its folder's", {**ROOM, "id": "other"}, "its folder"),
        ("bounds the wrong way round", {**ROOM, "bounds": [1.0, -1.0, -1.0, 1.0]}, "bounds"),
        ("a room outside the bounds", {**ROOM, "rooms": [{"name": "room", "x0": -1.0, "x1": 2.0, "y0": -1.0, "y1": 1.0}]}, "outside"),
        ("two rooms of one name", {**ROOM, "rooms": ROOM["rooms"] * 2}, "twice"),
        ("a hazard of an unknown kind", {**PIT, "hazards": [{**PIT["hazards"][0], "kind": "lava"}]}, "kind"),
        ("a drop with no depth", {**PIT, "hazards": [{k: v for k, v in PIT["hazards"][0].items() if k != "depth"}]}, "depth"),
        ("no rooms field", {k: v for k, v in ROOM.items() if k != "rooms"}, "rooms")):
    bad = {**bad}
    folder = tmp / "bad" / "room"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scene.json").write_text(json.dumps(bad))
    ok, why = raises(lambda: scenefile.load("room", tmp / "bad"), said)
    check(f"must fail: {name}", ok, why)

layout = {"geoms": [
    {"name": "floor_a", "type": "box", "pos": [0, 0, -0.005], "size": [1, 1, 0.005], "yaw": 0.0, "collides": True},
    {"name": "wall", "type": "box", "pos": [1.0, 0.0, 0.25], "size": [0.05, 1.0, 0.25], "yaw": 0.0, "collides": True},
    {"name": "bin", "type": "cylinder", "pos": [0.2, 0.3, 0.15], "size": [0.1, 0.15], "yaw": 0.0, "collides": True},
    {"name": "rug", "type": "box", "pos": [0, 0, 0.001], "size": [0.5, 0.5, 0.001], "yaw": 0.0, "collides": False},
    {"name": "ball", "type": "sphere", "pos": [0, 0, 0.05], "size": [0.05], "collides": True}]}
boxes = scenefile.boxes_from_layout(layout)
check("a layout's boxes: no floor, nothing that does not collide, a cylinder as its square",
      [b["name"] for b in boxes] == ["wall", "bin"] and boxes[1] == {"name": "bin", "cx": 0.2, "cy": 0.3, "z0": 0.0, "z1": 0.3,
                                                                  "hx": 0.1, "hy": 0.1, "yaw": 0.0}, boxes)

apt = scenefile.load("apartment")
check("the repository's apartment: six rooms, one drop, its bounds", [r.name for r in apt.rooms] ==
      ["kitchen", "living", "office", "bedroom", "bath", "corridor"] and [h["name"] for h in apt.drops] == ["stairs"]
      and apt.bounds == (-4.0, 4.0, -3.0, 3.0), (apt.rooms, apt.drops))
check("the apartment's corridor less its stairwell", abs(apt.room_area("corridor") - (1.5 * 6.0 - 0.4 * 0.7)) < 1e-9,
      apt.room_area("corridor"))
check.done()
