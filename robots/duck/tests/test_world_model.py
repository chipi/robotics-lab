"""The world model (RFC-0016): objects, the semantic map, the simulated camera, and the judge's view of landmarks."""

import json
import math
import sys

from duck_lab.nav.evaluate import LAYOUT, obstacles
from worldmodel.objects import Part, load_kinds, part_from_geom
from worldmodel.semantic_map import CONFIRM_N, Detection, SemanticMap
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

fridge_outline = m.blocking_points()
depth_on_fridge = [(o.x + 0.31, o.y)]            # the depth sensor saw the fridge's east face
check("the cost layer fills only what the depth sensor missed: a part with a depth point near it adds nothing",
      m.blocking_points(seen=depth_on_fridge) != fridge_outline
      and not [p for p in m.blocking_points(seen=depth_on_fridge) if math.dist(p, (o.x, o.y)) < 0.45],
      len(m.blocking_points(seen=depth_on_fridge)))
check("... and a depth point far from it changes nothing", m.blocking_points(seen=[(50.0, 50.0)]) == fridge_outline)
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
nav.semantic, nav._sem_lock, nav.blocked = None, threading.Lock(), []
check("no semantic map: no points for the cost map", nav.semantic_points() == [])
nav.semantic = m
check("a semantic map with confirmed objects, costs off (the default): still none", nav.semantic_points() == [])
nav.object_costs = True
check("costs on: the confirmed objects' outlines", len(nav.semantic_points()) == len(m.blocking_points()) > 0)

# ---- the judge: the landmarks the depth sensor sees are obstacles ---------------------------------------------------
names = {g["name"] for g in obstacles(json.loads(LAYOUT.read_text()))}
check("the judge counts the six lm_* landmarks as obstacles", {f"lm_{r}" for r in
      ("kitchen", "living", "corridor", "bedroom", "office", "bath")} <= names, sorted(n for n in names if n.startswith("lm")))

# ---- forgetting what is expected in view and not seen (RFC-0016 §4) ------------------------------------------------
from worldmodel.semantic_map import FORGET_N  # noqa: E402

ORIGIN = (0.0, 0.0, 0.0)


def confirmed_stool(pinned=False):
    fm = SemanticMap(kinds)
    for k in range(CONFIRM_N):
        fm.integrate([det("stool", 1.5, 0.0, 0.15, 0.6)], ORIGIN, float(k))
    fm.objects[0].pinned = pinned
    return fm


def looks(fm, n, pose=ORIGIN, found=(), grid=None):
    out = []
    for k in range(n):
        fm.integrate(list(found), pose, 10.0 + k)
        out += fm.forget(pose, 60.0, 3.0, grid, 10.0 + k)
    return out


fm = confirmed_stool()
st = fm.objects[0]
c0 = st.confidence
looks(fm, FORGET_N - 1)
check(f"expected in view, not seen {FORGET_N - 1} looks: still there, less sure", not st.gone and st.misses == FORGET_N - 1
      and st.confidence < c0, (st.misses, st.confidence))
fm.integrate([det("stool", 1.5, 0.0, 0.15, 0.6)], ORIGIN, 30.0)
fm.forget(ORIGIN, 60.0, 3.0, None, 30.0)
check("a sighting resets the count", st.misses == 0 and not st.gone, st.misses)
ch = looks(fm, FORGET_N)
check(f"{FORGET_N} looks in a row: gone, kept in the map, out of find and the confirmed", ch == [("gone", st)] and st.gone
      and st in fm.objects and st not in fm.confirmed() and fm.find("stool") is None, [(c, o.oid) for c, o in ch])
check("gone survives a save and a load", SemanticMap.from_json(fm.to_json(), kinds).objects[0].gone)
ch = fm.integrate([det("stool", 1.5, 0.0, 0.15, 0.6)], ORIGIN, 50.0)
check("a gone object seen again is back, the same object", ch and ch[0] == ("back", st) and not st.gone and st.confirmed
      and len(fm.objects) == 1, [(c, o.oid) for c, o in ch])

for name, pose in (("behind the duck", (3.0, 0.0, 0.0)), ("out of the field's angle", (0.0, 0.0, math.pi / 2)),
                   ("beyond the range", (-3.0, 0.0, 0.0)), ("too close", (1.4, 0.0, 0.0))):
    fm = confirmed_stool()
    looks(fm, FORGET_N + 2, pose)
    check(f"not expected in view ({name}): never counts a miss", fm.objects[0].misses == 0 and not fm.objects[0].gone,
          fm.objects[0].misses)
wall = {"res_m": 0.1, "origin": (0.0, 0.0), "width": 40, "height": 10, "cells": [" "] * 400}
for y in range(10):
    wall["cells"][y * 40 + 7] = "#"                    # a wall at x = 0.7 between the duck at 0 and the stool at 1.5
fm = confirmed_stool()
looks(fm, FORGET_N + 2, grid=wall)
check("behind a wall of mapd's grid: not expected in view, not forgotten", fm.objects[0].misses == 0 and not fm.objects[0].gone)

fm = confirmed_stool(pinned=True)
ch = looks(fm, FORGET_N * 2)
check("an object the operator named is flagged missing, never forgotten", fm.objects[0].missing and not fm.objects[0].gone
      and [c for c, _ in ch] == ["missing"], [(c, o.oid) for c, o in ch])
fm.integrate([det("stool", 1.5, 0.0, 0.15, 0.6)], ORIGIN, 99.0)
check("... and seen again, the flag clears", not fm.objects[0].missing and fm.objects[0].misses == 0)

# ---- landmark relocalisation (RFC-0016 §4) ---------------------------------------------------------------------------
from worldmodel.relocalise import DUCK_LANDMARKS, Relocaliser  # noqa: E402

MAX_STEP_M = DUCK_LANDMARKS.max_step_m


def fridge_site():
    """A site map whose fridge (a landmark, unique) was kept at (1.0, 0.5), and a relocaliser over it."""
    sm = SemanticMap(kinds, "apartment")
    for k in range(CONFIRM_N):
        sm.integrate([det("fridge", 1.0, 0.5, 0.3, 1.8)], ORIGIN, float(k))
    check("a fridge is a landmark, a stool is not", sm.is_landmark("fridge") and not sm.is_landmark("stool")
          and not sm.is_landmark("bed_that_does_not_exist"))
    return sm, Relocaliser(sm)


def look_at_fridge(rel, err, n=6, rng=1.1, t0=10.0, noise=0.0):
    """n sightings of the fridge from the true pose (0, 0, 0), the belief off by err (x, y); returns what observe said."""
    said = []
    for k in range(n):
        d = det("fridge", 1.0 + (noise if k % 2 else -noise), 0.5, 0.3, 1.8)
        d.range_m = rng
        pose = (err[0], err[1], 0.0)
        said.append(rel.observe([d], pose, t0 + 0.5 * k))
    return [s for s in said if s]


sm, rel = fridge_site()
check("no anchors until the site's landmarks are anchored", sm.anchors == {} and look_at_fridge(rel, (0.3, -0.2)) == [])
sm, rel = fridge_site()
sm.anchor_landmarks()
check("a site's confirmed landmarks become anchors", list(sm.anchors) == ["fridge_1"], sm.anchors)
said = look_at_fridge(rel, (0.3, -0.2))
check("the belief 0.36 m off: corrected back, toward the anchor, within MAX_STEP_M", said and said[0]["status"] == "corrected"
      and said[0]["dx"] < 0 < said[0]["dy"] and math.hypot(said[0]["dx"], said[0]["dy"]) <= MAX_STEP_M + 1e-9
      and said[0]["landmarks"] == ["fridge_1"], said)
sm, rel = fridge_site()
sm.anchor_landmarks()
check("a belief 5 cm off is noise: no correction", look_at_fridge(rel, (0.05, 0.0)) == [])
sm, rel = fridge_site()
sm.anchor_landmarks()
said = look_at_fridge(rel, (0.3, -0.2), noise=0.2)
check("residuals that disagree (a noisy placement): refused, with why", said and said[0]["status"] == "refused"
      and "disagree" in said[0]["why"], said)
sm, rel = fridge_site()
sm.anchor_landmarks()
check("a landmark 1.5 m from where the belief puts it is no match: nothing", look_at_fridge(rel, (1.5, 0.0)) == [])
check("seen from beyond RANGE_M: not used", look_at_fridge(rel, (0.3, -0.2), rng=2.5) == [])
sm.objects[0].gone = True
check("a forgotten landmark is not an anchor", look_at_fridge(rel, (0.3, -0.2), t0=100.0) == [])

# closed loop: the belief's error shrinks as the corrections are taken
sm, rel = fridge_site()
sm.anchor_landmarks()
err = [0.6, -0.4]
for k in range(40):
    d = det("fridge", 1.0, 0.5, 0.3, 1.8)
    d.range_m = 1.1
    out = rel.observe([d], (err[0], err[1], 0.0), 10.0 + 0.5 * k)
    if out and out["status"] == "corrected":
        err[0], err[1] = err[0] + out["dx"], err[1] + out["dy"]
check("closed loop: a 0.72 m error is under 0.15 m after the corrections", math.hypot(*err) < 0.15, err)

# a run without a site: an anchor is made from close sightings that agree, and does not follow the belief
sm = SemanticMap(kinds)
for k in range(CONFIRM_N):
    sm.integrate([det("fridge", 1.0, 0.5, 0.3, 1.8)], ORIGIN, float(k))
rel = Relocaliser(sm)
look_at_fridge(rel, (0.0, 0.0), n=3)
check("three close sightings are not yet an anchor", sm.anchors == {})
look_at_fridge(rel, (0.0, 0.0), n=2, t0=20.0)
anchor = sm.anchors.get("fridge_1")
check("four close sightings that agree make the anchor, at where they placed it", anchor is not None
      and math.dist(anchor, (1.0, 0.5)) < 1e-9, anchor)
for k in range(10):                  # the belief drifts 0.4 m; the object follows it, the anchor does not
    sm.integrate([det("fridge", 1.0, 0.5, 0.3, 1.8)], (0.4, 0.0, 0.0), 30.0 + k)
check("the object follows the belief's drift, its anchor stays", sm.objects[0].x > 1.2 and sm.anchors["fridge_1"] == anchor,
      (sm.objects[0].x, sm.anchors))
sm2 = SemanticMap(kinds)
for k in range(CONFIRM_N):
    sm2.integrate([det("fridge", 1.0, 0.5, 0.3, 1.8)], ORIGIN, float(k))
rel2 = Relocaliser(sm2)
look_at_fridge(rel2, (0.0, 0.0), n=1)
look_at_fridge(rel2, (0.3, 0.0), n=3, t0=20.0)
check("sightings that disagree make no anchor", sm2.anchors == {})

# a hypothesis (a held loop closure's frame, K26): do the sightings sit on their anchors at a pose that is only a guess?
AGREE_M = 0.2


def probe_fridge(rel, pose, n=6, rng=1.1, t0=10.0, noise=0.0, window=None):
    """n sightings of the fridge placed from `pose` (as the hypothesis would place the duck), 0.5 s apart; the window and the verdict."""
    window = window or []
    for k in range(n):
        d = det("fridge", 1.0 + (noise if k % 2 else -noise), 0.5, 0.3, 1.8)
        d.range_m = rng
        window = rel.probe([d], pose, t0 + 0.5 * k, window)
    return window, rel.agreement(window, AGREE_M)


sm, rel = fridge_site()
sm.anchor_landmarks()
w, v = probe_fridge(rel, (0.05, 0.0, 0.0))
check("a pose that puts the fridge on its anchor: agrees", v and v["status"] == "agrees" and v["n"] == 6 and v["landmarks"] == ["fridge_1"], v)
w, v = probe_fridge(rel, (0.3, -0.2, 0.0))
check("a pose 0.36 m off the anchor: disagrees, with the median that says how far", v and v["status"] == "disagrees"
      and math.dist(v["median"], (-0.3, 0.2)) < 1e-9, v)
w, v = probe_fridge(rel, (0.05, 0.0, 0.0), noise=0.2)
check("residuals that disagree with each other: refused", v and v["status"] == "refused", v)
w, v = probe_fridge(rel, (0.05, 0.0, 0.0), n=3)
check("fewer than min_n residuals: no verdict yet", v is None and len(w) == 3, v)
w, v = probe_fridge(rel, (1.5, 0.0, 0.0))
check("a pose 1.5 m off is no match to any anchor: nothing to judge by", v is None and w == [], (w, v))
w, v = probe_fridge(rel, (0.05, 0.0, 0.0), n=4, t0=10.0)
w2, v2 = probe_fridge(rel, (0.05, 0.0, 0.0), n=1, t0=30.0, window=w)
check("residuals older than window_s drop out", len(w2) == 1 and v2 is None, w2)
check("a probe changes nothing of the relocaliser's: its own window and the anchors", rel.window == [] and list(sm.anchors) == ["fridge_1"])
sm = SemanticMap(kinds)
for k in range(CONFIRM_N):
    sm.integrate([det("fridge", 1.0, 0.5, 0.3, 1.8)], ORIGIN, float(k))
rel = Relocaliser(sm)
w, v = probe_fridge(rel, (0.0, 0.0, 0.0), n=8)
check("a run without anchors: a probe makes none, and has nothing to judge by", sm.anchors == {} and rel.pending == {} and v is None, (sm.anchors, v))

print("WORLD-MODEL", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
