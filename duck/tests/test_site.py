"""Sites (RFC-0016 revision 3): a site's semantic map kept between runs, stable ids, objects named by the operator, kind
aliases and area hints by the site's kind."""

import json
import math
import sys
import tempfile
from pathlib import Path

from duck_lab.world_model.objects import load_kinds
from duck_lab.world_model.semantic_map import CONFIRM_N, Detection, SemanticMap
from duck_lab.world_model.site import Site

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


kinds = load_kinds()


def seen(m, kind, x, y, pose=(0.0, 0.0, 0.0), r=0.3):
    for _ in range(CONFIRM_N):
        m.integrate([Detection(kind, x, y, r, 0.0, 1.0, math.hypot(x, y))], pose)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    site = Site.create(root, "home", "Home", "apartment", kinds)
    check("a new site: site.json and an empty map", (root / "home" / "site.json").exists() and not site.semantic.objects)
    try:
        Site.create(root, "home", "Home", "apartment", kinds)
        made_twice = True
    except FileExistsError:
        made_twice = False
    check("a site is not created twice (no overwrite)", not made_twice)

    run1 = SemanticMap(kinds, "apartment")
    seen(run1, "fridge", 2.0, 0.0)
    seen(run1, "stool", 1.0, 1.0, r=0.15)
    out = site.merge(run1)
    site.save()
    fridge_id = next(o.oid for o in site.semantic.objects if o.kind == "fridge")
    check("the first run's objects join the site", out == {"matched": 0, "added": 2}, out)

    site.name_object(fridge_id, "the big fridge")
    site.save()
    again = Site.load(root, "home", kinds)
    named = next(o for o in again.semantic.objects if o.oid == fridge_id)
    check("a name the operator gave is kept, pinned, through a save and a load",
          named.label == "the big fridge" and named.named_by == "operator" and named.pinned)

    run2 = SemanticMap(kinds, "apartment")
    seen(run2, "fridge", 2.4, 0.3)            # the same fridge, seen 0.5 m off after drift (unique: 1.5 m)
    seen(run2, "stool", 3.5, 3.5, r=0.15)     # a second stool, far from the first
    out2 = again.merge(run2)
    check("the next run: the same fridge keeps its id and name, a far stool is new",
          out2 == {"matched": 1, "added": 1}
          and [o.oid for o in again.semantic.objects if o.kind == "fridge"] == [fridge_id]
          and next(o for o in again.semantic.objects if o.kind == "fridge").label == "the big fridge"
          and len({o.oid for o in again.semantic.objects}) == len(again.semantic.objects), out2)
    try:
        again.name_object("no_such_thing_9", "x")
        refused = False
    except KeyError:
        refused = True
    check("naming an object that does not exist is refused", refused)

    m = again.semantic
    check("find by the operator's name", m.find("The Big Fridge") is not None and m.find("the big fridge").oid == fridge_id)
    check("find by an alias (a detector's class)", m.find("refrigerator").oid == fridge_id)
    check("find by id", m.find(fridge_id).oid == fridge_id)
    check("an unknown name finds nothing", m.find("spaceship") is None)
    check("the inventory carries the name", any(o.get("label") == "the big fridge"
                                                for objs in m.inventory()["rooms"].values() for o in objs))

    office = SemanticMap(kinds, "office")
    seen(office, "fridge", 0.8, 0.0)
    check("a fridge at an office says break room (the site kind's hints)",
          next(iter(office.votes((0.0, 0.0, 0.0))), None) == "break_room", office.votes((0.0, 0.0, 0.0)))
    flat = SemanticMap(kinds, "apartment")
    seen(flat, "fridge", 0.8, 0.0)
    check("... and kitchen at an apartment (the general hints)",
          next(iter(flat.votes((0.0, 0.0, 0.0))), None) == "kitchen", flat.votes((0.0, 0.0, 0.0)))
    meta = json.loads((root / "home" / "site.json").read_text())
    check("site.json says what the site is", meta == {"id": "home", "name": "Home", "kind": "apartment", "areas": []},
          meta)

    # areas are the operator's: drawn, named, typed; "which area am I in" is geometry (the operator, 2026-11-18)
    kitchen = again.add_area("Kitchen", [(0, 0), (2, 0), (2, 1.5), (0, 1.5)], "kitchen")
    again.add_area("Marko's office", [(2, 0), (4, 0), (4, 1.5), (2, 1.5)], "office")
    check("a point inside an outline is in that area", again.area_at((1.0, 0.7)) is kitchen)
    check("a point in no outline is in no area", again.area_at((9.0, 9.0)) is None)
    check("an L-shaped outline: the notch is outside",
          Site("x", "x", "apartment", root / "x", areas=[]).add_area("L", [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)])
          is not None)
    l_site = Site("x", "x", "apartment", root / "x", areas=[])
    l_area = l_site.add_area("L", [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)])
    check("... inside the L yes, in its notch no", l_site.area_at((0.5, 1.5)) is l_area and l_site.area_at((1.5, 1.5)) is None)
    for bad, why in (((("Kitchen", [(0, 0), (1, 0), (1, 1)], None)), "a second area with the same name"),
                     ((("Hall", [(0, 0), (1, 0)], None)), "an outline of two points")):
        try:
            again.add_area(*bad)
            ok = False
        except ValueError:
            ok = True
        check(f"refused: {why}", ok)
    again.save()
    back = Site.load(root, "home", kinds)
    check("areas survive a save and a load", [(a.name, a.type, a.polygon) for a in back.areas]
          == [(a.name, a.type, a.polygon) for a in again.areas], [a.to_json() for a in back.areas])

    # the simulated apartment's six rooms as a site's areas (sim-areas): the dock's start puts them in the site frame
    start = root / "start.json"
    start.write_text(json.dumps({"map": [0.0, 0.0, 0.0], "truth": [0.05, 0.0, 0.0], "scale": 0.91}))
    import subprocess  # noqa: E402

    Site.create(root, "flat", "The simulated apartment", "apartment", kinds)
    out = subprocess.run([sys.executable, "-m", "duck_lab.world_model.site", "--sites", str(root), "sim-areas", "flat",
                          "--start", str(start)], capture_output=True, text=True)
    sim = Site.load(root, "flat", kinds)
    office = next((a for a in sim.areas if a.name == "office"), None)
    check("sim-areas: the six rooms drawn, typed by their names", {a.name for a in sim.areas} >= {"kitchen", "living",
          "office", "bedroom", "bath", "corridor"} and office is not None and office.type == "office", out.stdout + out.stderr)
    check("... in the site frame: the office's world (2.0, 0.0) is at (1.95, 0.0) on the site map",
          sim.area_at((1.95, 0.0)) is office and sim.area_at((2.06, 0.0)) is office)

print("SITE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
