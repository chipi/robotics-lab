"""Sites, areas and the site's objects (RFC-0014 §3.5): the library, the operator's areas (create, rename,
redraw, merge, split, which area holds a point), objects with stable ids merged from runs, naming by
hand, the inventory, and that all of it survives a restart (SQLite).
Run: cd apps/mission-control && uv run python tests/test_sites.py"""

import tempfile
from pathlib import Path

from common import Clock, check, finish

from mission_control.errors import ApiError
from mission_control.sites import Sites
from mission_control.store import Store

clock = Clock()


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ApiError as exc:
        return exc
    return None


store = Store(None)
sites = Sites(store, clock)

# --- the site library -----------------------------------------------------------------------------
home = sites.create("Home", "apartment")
check("a site has an id, a name, a kind and the site frame", home["id"] == "home" and home["name"] == "Home"
      and home["kind"] == "apartment" and home["frame"] == "site", home)
check("a kind is free text: nothing is fixed to a home", sites.create("Course", "the simulated challenge course")["kind"].startswith("the simulated"))
check("a second site with the same name is refused", refusal(sites.create, "home", "office").code == "name_taken")
check("several sites live side by side", [s["id"] for s in sites.list()] == ["home", "course"])
check("rename and change the kind, the id stays", sites.update("home", name="My flat", kind="flat")["id"] == "home"
      and sites.get("home")["name"] == "My flat")
check("an empty name is refused", refusal(sites.create, " ", "x").code == "invalid")
check("an unknown site is a 404", refusal(sites.get, "nope").status == 404)
sites.assign_robot("fake-1", "home")
check("a site with a robot at it is not retired", refusal(sites.retire, "home").code == "site_in_use")
sites.assign_robot("fake-1", None)
sites.retire("course")
check("a retired site leaves the list and its name is free again", [s["id"] for s in sites.list()] == ["home"]
      and sites.create("Course", "garden")["id"] == "course-2")

# --- areas: the operator's ------------------------------------------------------------------------
KITCHEN = [[0, 0], [4, 0], [4, 4], [0, 4]]
kitchen = sites.create_area("home", "Kitchen", "kitchen", KITCHEN)
check("an area has a name, a type and an outline in the site frame", kitchen["id"] == "kitchen" and kitchen["type"] == "kitchen"
      and kitchen["frame"] == "site" and len(kitchen["outline"]) == 4)
check("an area name is unique in its site", refusal(sites.create_area, "home", "kitchen", None, KITCHEN).code == "name_taken")
check("a bad outline is refused with bad_outline", refusal(sites.create_area, "home", "Bad", None, [[0, 0], [1, 1]]).code == "bad_outline")
hall = sites.create_area("home", "Hall", None, [[4, 0], [6, 0], [6, 4], [4, 4]])
check("an area's type is optional", hall["type"] is None)
check("which area holds a point", sites.area_at("home", 1, 1)["id"] == "kitchen" and sites.area_at("home", 5, 1)["id"] == "hall")
check("none defined where no outline is", sites.area_at("home", 9, 9) is None)
nested = sites.create_area("home", "Pantry", None, [[0, 0], [1, 0], [1, 1], [0, 1]])
check("of nested areas the smallest holds the point", sites.area_at("home", 0.5, 0.5)["id"] == "pantry")
check("an area is found by name too", sites.area("home", "KITCHEN")["id"] == "kitchen")
check("rename, retype and redraw", sites.update_area("home", "pantry", {"name": "Larder", "type": "storage",
      "outline": [[0, 0], [2, 0], [2, 1], [0, 1]]})["name"] == "Larder")
check("the id stays when the name changes", sites.area("home", "pantry")["id"] == "pantry")
check("an area's id and site cannot be changed", refusal(sites.update_area, "home", "pantry", {"id": "x"}).code == "invalid")
check("a rename to a taken name is refused", refusal(sites.update_area, "home", "pantry", {"name": "Hall"}).code == "name_taken")

# merge and split
merged = sites.merge_areas("home", "kitchen", "hall", {"name": "Kitchen and hall"})
check("merging folds the other area in: the outline is the hull of both",
      merged["name"] == "Kitchen and hall" and sites.area_at("home", 5, 1)["id"] == "kitchen")
check("the merged-away area is gone", refusal(sites.area, "home", "hall").status == 404)
check("an area does not merge with itself", refusal(sites.merge_areas, "home", "kitchen", "kitchen").code == "invalid")
kept, new = sites.split_area("home", "kitchen", [[3, -1], [3, 5]], "Hall")
check("splitting by a line: the area keeps the left, a new area takes the right",
      kept["id"] == "kitchen" and new["name"] == "Hall" and sites.area_at("home", 1, 3)["id"] == "kitchen"
      and sites.area_at("home", 5, 1)["id"] == "hall", (kept, new))
check("a line that misses is refused", refusal(sites.split_area, "home", "kitchen", [[99, 0], [99, 9]], "X").code == "bad_outline")

# no-go areas in the site's guardrails
sites.set_guardrails("home", [{"name": "no_go_area", "area": "Hall"}, "contact"])
check("a no-go area is stored by id", sites.guardrails("home")[0] == {"name": "no_go_area", "area": "hall"})
check("a no-go area that does not exist is refused", refusal(sites.set_guardrails, "home", [{"name": "no_go_area", "area": "moon"}]).status == 404)
check("an area a guardrail names cannot be deleted", refusal(sites.delete_area, "home", "hall").code == "area_in_use")
check("nor merged away", refusal(sites.merge_areas, "home", "kitchen", "hall").code == "area_in_use")
check("nor split, the new half would escape it", refusal(sites.split_area, "home", "hall", [[5, -1], [5, 5]], "X").code == "area_in_use")
sites.set_guardrails("home", [])
check("free again, it can be deleted", sites.delete_area("home", "hall") is None and refusal(sites.area, "home", "hall").status == 404)

# --- objects: stable ids, merged from runs --------------------------------------------------------
def rep(nid, kind, x, y, n=1, confirmed=False, **extra):
    return {"id": nid, "kind": kind, "x": x, "y": y, "n": n, "confirmed": confirmed, "confidence": 0.6, **extra}


assoc: dict = {}
ch = sites.merge_run_objects("home", [rep("nav-0", "fridge", 3.0, 1.5, unique=True), rep("nav-1", "sofa", -2.5, -1.5)], "fake-1", assoc)
check("new objects get the site's own ids", [c for c, _ in ch] == ["new", "new"] and sorted(i for _, i in ch) == ["obj-1", "obj-2"], ch)
objs = {o["kind"]: o for o in sites.objects("home")}
check("an object carries kind, position, parts, confidence, sightings, who saw it, evidence",
      objs["fridge"]["n"] == 1 and objs["fridge"]["seen_by"] == ["fake-1"] and objs["fridge"]["parts"] and objs["fridge"]["frame"] == "site")
check("not confirmed yet", not objs["fridge"]["confirmed"])
ch = sites.merge_run_objects("home", [rep("nav-0", "fridge", 3.0, 1.5, n=2, confirmed=True, unique=True),
                                      rep("nav-1", "sofa", -2.5, -1.5, n=1)], "fake-1", assoc)
check("the same navigator object again is the same site object: counted by what is new, confirmed on the second sighting",
      ch == [("confirmed", "obj-1")] and sites.object("home", "obj-1")["n"] == 2 and sites.object("home", "obj-1")["confirmed"], ch)
check("resending the same map changes nothing", sites.merge_run_objects("home", [rep("nav-0", "fridge", 3.0, 1.5, n=2, confirmed=True)], "fake-1", assoc) == [])

# a later run has its own ids: the same kind nearby is the same object
assoc2: dict = {}
ch = sites.merge_run_objects("home", [rep("nav-7", "sofa", -2.3, -1.4, n=2, confirmed=True)], "fake-1", assoc2)
check("a later run's sofa 0.22 m away is the same sofa (the 0.5 m association gate)", ch[0][1] == "obj-2" and len(sites.objects("home")) == 2, ch)
ch = sites.merge_run_objects("home", [rep("nav-8", "sofa", -1.5, -1.5)], "fake-1", assoc2)
check("a sofa 1 m from the known one is a new object", ch == [("new", "obj-3")], ch)
ch = sites.merge_run_objects("home", [rep("nav-9", "fridge", 4.0, 2.2, unique=True)], "fake-1", {})
check("a fridge 1.2 m from the known one is the same fridge: a kind a site has one of has a 1.5 m gate (drift)",
      ch[0][1] == "obj-1" and len(sites.objects("home")) == 3, ch)
ch = sites.merge_run_objects("home", [rep("nav-9", "fridge", 3.0, 3.5, unique=True)], "fake-1", {})
check("but not 2 m away", ch == [("new", "obj-4")], ch)
ch = sites.merge_run_objects("home", [rep("nav-2", "desk", 0, 0)], "second-robot", {})
check("another robot's sighting adds it to seen_by", sites.object("home", ch[0][1])["seen_by"] == ["second-robot"])
sites.merge_run_objects("home", [rep("nav-2", "desk", 0, 0, n=2)], "fake-1", {"ids": {"nav-2": ch[0][1]}, "n": {"nav-2": 1}})
check("and so does a second robot's later sighting", sites.object("home", ch[0][1])["seen_by"] == ["second-robot", "fake-1"])

# naming by hand
named = sites.label("home", "obj-2", "My sofa")
check("the operator names an object", named["label"] == "My sofa")
check("a label is unique in the site, case-insensitively", refusal(sites.label, "home", "obj-3", "my SOFA").code == "label_taken")
sites.merge_run_objects("home", [rep("nav-70", "sofa", -2.4, -1.45, n=3, confirmed=True)], "fake-1", {})
check("a named object is never merged away: it keeps its id and label when seen again", sites.object("home", "obj-2")["label"] == "My sofa")
check("a label can be cleared", sites.label("home", "obj-2", None)["label"] is None)
sites.label("home", "obj-2", "My sofa")
check("an unknown object is a 404", refusal(sites.label, "home", "obj-99", "x").status == 404)

# objects are in areas by geometry; none until the operator draws one
check("an object outside every outline has no area: it lists under none defined", sites.object("home", "obj-2")["area"] is None)
sites.update_area("home", "kitchen", {"outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})
inv = sites.inventory("home")
sofa_area = sites.object("home", "obj-2")["area"]
check("after the operator draws an outline round it, the sofa is in it", sofa_area == "kitchen", sofa_area)
check("the inventory lists confirmed objects by area, with sightings and confidence",
      any(o["id"] == "obj-2" and o["n"] >= 1 and "confidence" in o for a in inv["areas"] for o in a["objects"]), inv)
check("an unconfirmed object is not in the inventory", all(o["id"] != "obj-4" for a in inv["areas"] for o in a["objects"] + inv["none_defined"]))
seed = sites.seed("home")
check("the seed for a navigator is the confirmed objects and the areas' outlines", seed["objects"] and all(o["confirmed"] for o in seed["objects"])
      and seed["areas"][0]["outline"])

# no area is created by anything but the operator's calls
before = len(sites.areas("home"))
sites.merge_run_objects("home", [rep("nav-50", "bed", 9, 9, n=5, confirmed=True)], "fake-1", {})
check("merging a run's objects creates no area", len(sites.areas("home")) == before)

# --- export and import ------------------------------------------------------------------------------
sites.update_area("home", "kitchen", {"name": "Kitchen"})
sites.delete_area("home", "pantry")
sites.set_guardrails("home", [{"name": "no_go_area", "area": "kitchen"}, "contact"])
bundle = sites.export_site("home")
check("an export is a document: format, version, the site, the operator's areas, the labelled objects, the guardrails",
      bundle["format"] == "mission-control-site" and bundle["version"] == 1 and bundle["site"]["name"] == "My flat"
      and [a["name"] for a in bundle["areas"]] == ["Kitchen"] and bundle["areas"][0]["outline"])
check("only the objects somebody named are in it: what a robot saw is the runs' to find again",
      [o["label"] for o in bundle["objects"]] == ["My sofa"] and len(sites.objects("home")) > 1, bundle["objects"])
check("a no-go area is by name, so the file does not depend on ids", bundle["guardrails"][0] == {"name": "no_go_area", "area": "Kitchen"})
import json as _json
check("it is plain JSON", _json.loads(_json.dumps(bundle)) == bundle)

other = sites.create("Copy", "flat")
rep1 = sites.import_site("copy", bundle)
check("an import into another site makes the areas, the named objects and the guardrails",
      [a["name"] for a in sites.areas("copy")] == ["Kitchen"] and [o["label"] for o in sites.objects("copy")] == ["My sofa"]
      and sites.guardrails("copy") == [{"name": "no_go_area", "area": "kitchen"}, {"name": "contact"}], rep1)
check("the report says what was created", rep1["areas"] == {"created": ["kitchen"], "updated": []} and rep1["objects"]["created"] == ["obj-1"]
      and rep1["guardrails"] == 2)
check("an imported named object is confirmed, in the site's own ids, seen by 'import'", sites.object("copy", "obj-1")["confirmed"]
      and sites.object("copy", "obj-1")["seen_by"] == ["import"])
rep2 = sites.import_site("copy", bundle)
check("importing again changes nothing: no duplicate area, object or guardrail",
      rep2["areas"] == {"created": [], "updated": ["kitchen"]} and rep2["objects"] == {"created": [], "labelled": ["obj-1"], "skipped": []}
      and len(sites.areas("copy")) == 1 and len(sites.objects("copy")) == 1 and len(sites.guardrails("copy")) == 2, rep2)
moved = _json.loads(_json.dumps(bundle))
moved["areas"][0]["outline"] = [[0, 0], [1, 0], [1, 1], [0, 1]]
moved["areas"][0]["type"] = "galley"
sites.import_site("copy", moved)
check("an area of the same name has its outline and type replaced", sites.area("copy", "kitchen")["type"] == "galley"
      and sites.area("copy", "kitchen")["outline"][2] == [1.0, 1.0])

sites.merge_run_objects("copy", [rep("nav-1", "sofa", -1.5, -1.5, n=2, confirmed=True)], "fake-1", {})
named = sites.import_site("copy", {**bundle, "objects": [{"kind": "sofa", "x": -1.5, "y": -1.4, "label": "Big sofa"}]})
check("a named object joins an unnamed one of its kind within the association gate and names it",
      named["objects"]["labelled"] == ["obj-2"] and sites.object("copy", "obj-2")["label"] == "Big sofa", named)
clash = sites.import_site("copy", {**bundle, "objects": [{"kind": "desk", "x": 5, "y": 5, "label": "my sofa"}]})
check("a label another object here already has is skipped and reported, not taken", clash["objects"]["skipped"][0]["label"] == "my sofa"
      and clash["objects"]["created"] == [] and sites.object("copy", "obj-1")["label"] == "My sofa", clash)

def bad(b):
    before = (len(sites.areas("copy")), len(sites.objects("copy")))
    e = refusal(sites.import_site, "copy", b)
    return e, before == (len(sites.areas("copy")), len(sites.objects("copy")))

e, same = bad({"format": "something-else"})
check("a file that is not a site file is refused", e.code == "bad_bundle" and same)
e, same = bad({**bundle, "version": 9})
check("a version this build does not read is refused", e.code == "bad_bundle" and same)
e, same = bad({**bundle, "areas": [{"name": "Good", "outline": [[0, 0], [9, 0], [9, 9]]}, {"name": "Bad", "outline": [[0, 0]]}]})
check("all or nothing: a bad area late in the file rolls the earlier ones back", e.code == "bad_outline" and same and refusal(sites.area, "copy", "good").status == 404)
e, same = bad({**bundle, "objects": [{"kind": "fridge", "x": 1, "y": 1}]})
check("an object with no label is refused", e.code == "bad_bundle" and same)
check("a no-go area the file's areas do not have is refused",
      refusal(sites.import_site, "copy", {**bundle, "guardrails": [{"name": "no_go_area", "area": "Nowhere"}]}).status == 404)
check("an import into a site that is not there is a 404", refusal(sites.import_site, "nope", bundle).status == 404)

# --- persistence ------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "db" / "mc.sqlite"
    s1 = Sites(Store(path), clock)
    s1.create("Office", "office")
    s1.create_area("office", "Lab", "lab", KITCHEN)
    s1.merge_run_objects("office", [rep("nav-0", "fridge", 1, 1, n=2, confirmed=True, unique=True)], "fake-1", {})
    s1.label("office", "obj-1", "Break room fridge")
    s1.set_guardrails("office", [{"name": "no_go_area", "area": "lab"}])
    s1.store.close()
    s2 = Sites(Store(path), clock)
    check("sites, areas, labelled objects and guardrails survive a restart",
          s2.get("office")["counts"] == {"areas": 1, "objects": 1, "labelled": 1} and s2.object("office", "obj-1")["label"] == "Break room fridge"
          and s2.guardrails("office") == [{"name": "no_go_area", "area": "lab"}])

finish("test_sites")
