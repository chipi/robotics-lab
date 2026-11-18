"""The world model (RFC-0016): objects, the semantic map, the simulated camera, and the judge's view of landmarks."""

import json
import math
import sys

from duck_lab.nav.evaluate import LAYOUT, obstacles
from duck_lab.world_model.objects import Part, load_kinds, part_from_geom
from duck_lab.world_model.semantic_map import CONFIRM_N, Detection, SemanticMap
from duck_lab.nav.sim_camera import SimCamera

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


kinds = load_kinds()
geoms = {g["name"]: g for g in json.loads(LAYOUT.read_text())["geoms"]}

# ---- objects: parts and how the duck may pass them ------------------------------------------------------------------
check("a rug is walked over", part_from_geom(geoms["rug_living"]).traversal == "over", part_from_geom(geoms["rug_living"]))
check("a desk top is passed under", part_from_geom(geoms["off_desk"]).traversal == "under", part_from_geom(geoms["off_desk"]))
check("a desk leg is gone round", part_from_geom(geoms["off_desk_l1"]).traversal == "around")
lm = part_from_geom(geoms["lm_office"])
check("lm_office, a standing capsule: about 4-66 cm high, gone round", abs(lm.z0 - 0.04) < 0.01 and abs(lm.z1 - 0.66) < 0.01
      and lm.traversal == "around", (lm.z0, lm.z1))
box = Part(1.0, 0.0, 0.1, 0.2, 0.0, 0.0, 0.5)
check("distance to a part's outline", abs(box.distance((1.3, 0.0)) - 0.2) < 1e-9 and box.distance((1.0, 0.1)) == 0.0)
check("an outline's points lie on it", all(box.distance(p) < 1e-9 for p in box.outline(0.03)), len(box.outline(0.03)))
turned = Part(1.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.5).moved((2.0, 0.0, math.pi / 2))
check("a part moved by a pose", abs(turned.x - 2.0) < 1e-9 and abs(turned.y - 1.0) < 1e-9, turned)

# ---- the semantic map ------------------------------------------------------------------------------------------------
def det(kind, x, y, radius=0.3, z1=1.8):
    return Detection(kind, x, y, radius, 0.0, z1, math.hypot(x, y))


up = (2.0, 0.0, math.pi / 2)                       # the duck at (2, 0) facing +y
m = SemanticMap(kinds)
ch = m.integrate([det("fridge", 1.0, 0.0)], up, 1.0)
o = m.objects[0]
check("a detection is placed with the duck's pose (map frame)", ch and ch[0][0] == "new" and abs(o.x - 2.0) < 1e-9
      and abs(o.y - 1.0) < 1e-9, (o.x, o.y))
for k in range(CONFIRM_N - 1):
    ch = m.integrate([det("fridge", 1.05, 0.0)], up, 2.0 + k)
check(f"the same fridge seen {CONFIRM_N} times: one object, confirmed", len(m.objects) == 1 and o.confirmed
      and ch and ch[0][0] == "confirmed", (len(m.objects), o.n))
m.integrate([det("sofa", 1.0, 0.0)], up)
check("another kind at the same place is another object", len(m.objects) == 2)
m.integrate([det("fridge", 1.0, 0.0)], (2.8, 0.0, math.pi / 2))
check("a unique kind (fridge) seen 0.8 m off, as after drift: the same fridge", len([x for x in m.objects if x.kind == "fridge"]) == 1)
check("... and it follows the newer sighting (RECENT)", o.x > 2.1, o.x)
m.integrate([det("stool", 1.0, 0.0, 0.15, 0.6)], up)
m.integrate([det("stool", 1.0, -1.0, 0.15, 0.6)], up)
check("two stools 1 m apart (not unique): two objects", len([x for x in m.objects if x.kind == "stool"]) == 2)
check("find: the confirmed fridge", m.find("fridge", (0.0, 0.0, 0.0)) is o and m.find("bed") is None)

# the room: objects near and in sight vote; None when none; a new room only after ROOM_TICKS looks in a row
k = SemanticMap(kinds)
for _ in range(CONFIRM_N):
    k.integrate([det("fridge", 0.8, 0.0)], (0.0, 0.0, 0.0))
room, votes = k.room_at((0.0, 0.0, 0.0))
check("a confirmed fridge 0.8 m away: this is the kitchen", room == "kitchen", votes)
check("an unconfirmed sofa does not vote", "living" not in m.votes((2.0, 0.5, 0.0)), m.votes((2.0, 0.5, 0.0)))
check("nothing confirmed near: no room", SemanticMap(kinds).room_at((20.0, 20.0, 0.0))[0] is None)
wall = {"res_m": 0.05, "origin": [-1.0, -1.0], "width": 40, "height": 40,
        "cells": "".join("#" if x == 28 else "." for y in range(40) for x in range(40))}   # a wall at x 0.4
check("a fridge behind a wall of the duck's own map does not vote", k.votes((0.0, 0.0, 0.0), wall) == {},
      k.votes((0.0, 0.0, 0.0), wall))
empty = {"res_m": 0.0, "origin": [0.0, 0.0], "width": 0, "height": 0, "cells": ""}   # mapd before its first stop
try:
    on_empty = k.votes((0.0, 0.0, 0.0), empty)
except ZeroDivisionError as e:
    on_empty = f"crashed: {e}"
check("mapd's empty first grid: nothing in the way, no crash (find-fridge-1's camera thread died on it)",
      on_empty == k.votes((0.0, 0.0, 0.0)), on_empty)
for _ in range(CONFIRM_N):
    k.integrate([det("sofa", -0.5, 0.0, 0.3, 0.8)], (0.0, 0.0, 0.0))      # a sofa at -0.5: nearer than the fridge
said = [k.room_at((-0.2, 0.0, 0.0))[0] for _ in range(3)]
check("a new room leads: the old one held for ROOM_TICKS - 1 looks, then the new", said == ["kitchen", "kitchen", "living"], said)

check("the cost layer's points lie on the fridge's outline", len(m.blocking_points()) > 0
      and all(abs(math.dist(p, (o.x, o.y)) - 0.3) < 0.13 for p in m.blocking_points()))
# a fridge against a wall above it: where to stand is in front of it, facing it
a = m.approach(o, (2.0, -1.0, 0.0), free=lambda p: p[1] < o.y + 0.3)
check("approach: on the free side, STAND_M from the outline, facing the fridge",
      a is not None and a[1] < o.y - 0.3 and math.cos(a[2] - math.atan2(o.y - a[1], o.x - a[0])) > 0.99, a)
check("approach: nowhere free, None", m.approach(o, (2.0, -1.0, 0.0), free=lambda p: False) is None)
back = SemanticMap.from_json(json.loads(json.dumps(m.to_json())), kinds)
check("the map round-trips through JSON", [x.summary() for x in back.objects] == [x.summary() for x in m.objects])

# ---- the simulated camera -------------------------------------------------------------------------------------------
cam = SimCamera(config={"p_detect": 1.0, "range_noise": 0.0, "bearing_noise_deg": 0.0}, seed=1)
seen = {d.kind for d in cam.detect((2.5, -0.6, math.pi))}
check("from inside the office facing west: the green capsule (lm_office) is seen", "green_capsule" in seen, seen)
behind = {d.kind for d in cam.detect((2.5, -0.6, 0.0))}
check("facing east, it is not", "green_capsule" not in behind, behind)
kitchen = {d.kind for d in cam.detect((-2.0, 2.0, 0.0))}
check("from the kitchen facing east, nothing of the bedroom or the office (walls)",
      not kitchen & {"bed", "nightstand", "wardrobe", "desk", "green_capsule"}, kitchen)
m2 = SemanticMap(kinds)
truth = (2.5, -0.6, math.pi)
caps = [d for d in cam.detect(truth) if d.kind == "green_capsule"]
m2.integrate(caps, truth)
check("with no noise and the belief = the truth, the capsule lands where it is",
      abs(m2.objects[0].x - 0.95) < 1e-6 and abs(m2.objects[0].y + 0.6) < 1e-6, (m2.objects[0].x, m2.objects[0].y))
check("the leak test: a detection carries a kind, a disc relative to the duck, a height band, a range, a confidence,"
      " its recogniser and (from a real camera) evidence; nothing else",
      set(vars(caps[0])) == {"kind", "x", "y", "radius", "z0", "z1", "range_m", "confidence", "source", "evidence"}
      and caps[0].source == "sim_camera" and caps[0].evidence is None
      and (round(caps[0].x, 3), round(caps[0].y, 3)) != (0.95, -0.6), vars(caps[0]))
inv_map = SemanticMap(kinds)
for _ in range(CONFIRM_N):
    inv_map.integrate([Detection("fridge", 1.0, 0.0, 0.3, 0.0, 1.8, 1.0, 0.7, "video_detector",
                                 {"frame_t": 12.5, "box": [10, 20, 80, 160]})], (0.0, 0.0, 0.0))
inv_map.integrate([det("bed", 5.0, 5.0)], (0.0, 0.0, 0.0))                  # seen once: not in the inventory
inv = inv_map.inventory()
check("the inventory: confirmed objects by room, with sightings, confidence, recogniser and evidence",
      inv["objects"] == 1 and inv["rooms"]["kitchen"][0]["kind"] == "fridge"
      and inv["rooms"]["kitchen"][0]["sightings"] == CONFIRM_N and inv["rooms"]["kitchen"][0]["confidence"] == 0.7
      and inv["rooms"]["kitchen"][0]["sources"] == ["video_detector"]
      and inv["rooms"]["kitchen"][0]["evidence"][-1]["frame_t"] == 12.5, inv)
check("its disc covers the capsule (radius 0.09 + its half diagonal)", 0.09 <= caps[0].radius <= 0.14, caps[0].radius)
check("out of range (3 m): not seen", not [d for d in cam.detect((4.5, -0.6, math.pi)) if d.kind == "green_capsule"])
check("out of the field of view (60 deg): not seen",
      not [d for d in cam.detect((2.5, 0.6, math.pi)) if d.kind == "green_capsule"])
check("p_detect 0: nothing", SimCamera(config={"p_detect": 0.0}).detect(truth) == [])
noisy = SimCamera(seed=2)
n = sum(1 for _ in range(200) for d in noisy.detect(truth) if d.kind == "green_capsule")
check("with the default detection probability, seen in some looks but not all", 0 < n < 200, n)

# ---- no-camera and costs-off invariance: every grid the brain builds is the one it built before objects ------------
import threading  # noqa: E402

from duck_lab.nav.run import Navigator  # noqa: E402

nav = Navigator.__new__(Navigator)
nav.semantic, nav._sem_lock = None, threading.Lock()
check("no semantic map: no points for the cost map", nav.semantic_points() == [])
nav.semantic = m
check("a semantic map with confirmed objects, costs off (the default): still none", nav.semantic_points() == [])
nav.object_costs = True
check("costs on: the confirmed objects' outlines", len(nav.semantic_points()) == len(m.blocking_points()) > 0)

# ---- the judge: the landmarks the depth sensor sees are obstacles ---------------------------------------------------
names = {g["name"] for g in obstacles(json.loads(LAYOUT.read_text()))}
check("the judge counts the six lm_* landmarks as obstacles", {f"lm_{r}" for r in
      ("kitchen", "living", "corridor", "bedroom", "office", "bath")} <= names, sorted(n for n in names if n.startswith("lm")))

print("WORLD-MODEL", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
