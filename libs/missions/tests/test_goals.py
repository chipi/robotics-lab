"""Goal kinds and their schemas, and the guardrail vocabulary with its merge (RFC-0014 §3.4.1, §3.4.8; RFC-0030): pure rules, no robot. The
library raises PlanError with a code and no status.
Run: cd libs/missions && uv run python tests/test_goals.py"""

import sys

from missions import goals, guardrails
from missions.errors import PlanError

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except PlanError as exc:
        return exc
    return None


# --- guardrails ------------------------------------------------------------------------------------
check("a bare name", guardrails.normalise("contact") == {"name": "contact"})
check("RFC-0014 §3.4.1's example 'drop' is stored as fall", guardrails.normalise("drop") == {"name": "fall"})
check("and 'stall' as stuck", guardrails.normalise("stall") == {"name": "stuck"})
check("a limit", guardrails.normalise({"name": "max_speed", "mps": 0.2}) == {"name": "max_speed", "mps": 0.2})
check("an unknown guardrail is refused", refusal(guardrails.normalise, "teleport").code == "bad_guardrail")
check("a limit is needed where there is one", refusal(guardrails.normalise, "max_speed").code == "bad_guardrail")
check("a limit is a number above 0", refusal(guardrails.normalise, {"name": "max_speed", "mps": -1}).code == "bad_guardrail")
check("true is not a number", refusal(guardrails.normalise, {"name": "time_limit", "seconds": True}) is not None)
check("a limit where there is none is refused", refusal(guardrails.normalise, {"name": "contact", "mps": 1}) is not None)
check("a no-go area names its area", guardrails.normalise({"name": "no_go_area", "area": "stairwell"})["area"] == "stairwell")
check("a no-go area with no area is refused", refusal(guardrails.normalise, "no_go_area") is not None)
check("duplicates collapse", guardrails.normalise_list(["contact", "contact"]) == [{"name": "contact"}])
check("must_not is a list", refusal(guardrails.normalise_list, "contact") is not None)

merged = guardrails.merge({
    "robot": [{"name": "max_speed", "mps": 0.4}, {"name": "contact"}],
    "site": [{"name": "no_go_area", "area": "stairwell"}, {"name": "max_speed", "mps": 0.3}],
    "goal": [{"name": "max_speed", "mps": 0.9}, {"name": "time_limit", "seconds": 30.0}, {"name": "contact"}],
})
by_name = {(g["name"], g.get("area")): g for g in merged}
check("a goal cannot loosen a site's or a robot's speed cap: the strictest wins",
      by_name[("max_speed", None)]["mps"] == 0.3, by_name[("max_speed", None)])
check("each entry says which levels name it", by_name[("max_speed", None)]["from"] == ["robot", "site", "goal"]
      and by_name[("contact", None)]["from"] == ["robot", "goal"] and by_name[("time_limit", None)]["from"] == ["goal"])
check("a goal adds a guardrail", ("time_limit", None) in by_name and by_name[("time_limit", None)]["seconds"] == 30.0)
check("the site's no-go area is in the merge", ("no_go_area", "stairwell") in by_name)
tighter = guardrails.merge({"robot": [{"name": "time_limit", "seconds": 60.0}], "goal": [{"name": "time_limit", "seconds": 20.0}]})
check("a goal can tighten a limit", tighter[0]["seconds"] == 20.0)
clearance = guardrails.merge({"site": [{"name": "drop_clearance", "m": 0.3}], "goal": [{"name": "drop_clearance", "m": 0.1}]})
check("for a clearance the larger distance is the stricter", clearance[0]["m"] == 0.3)
check("two no-go areas both stay", len(guardrails.merge({"site": [{"name": "no_go_area", "area": "a"}],
                                                          "goal": [{"name": "no_go_area", "area": "b"}]})) == 2)

# --- goal kinds -------------------------------------------------------------------------------------
point = goals.validate({"name": "to the door", "kind": "point", "params": {"x": 1, "y": 2}})
check("a point goal gets its defaults (ADR-0015's 0.25 m, 60 s) and the site frame",
      point["done_when"] == {"within_m": 0.25, "within_s": 60.0} and point["params"]["frame"] == "site" and point["expect"] == "reach")
obj = goals.validate({"name": "fridge", "kind": "go_to_object", "params": {"kind": "fridge", "area": "kitchen"},
                      "must_not": ["contact", "drop"]})
check("go_to_object defaults: 0.35 m, 45 degrees", obj["done_when"]["within_m"] == 0.35 and obj["done_when"]["facing_deg"] == 45.0)
check("the example's 'drop' is stored as fall", obj["must_not"] == [{"name": "contact"}, {"name": "fall"}], obj["must_not"])
check("an object goal has a budget in minutes", obj["budget"] == {"minutes": 5.0})
check("go_to_area", goals.validate({"name": "a", "kind": "go_to_area", "params": {"area": "kitchen"}})["params"] == {"area": "kitchen"})
check("explore a site", goals.validate({"name": "e", "kind": "explore", "params": {"site": True}})["params"] == {"site": True})
check("explore an area with a budget", goals.validate({"name": "e", "kind": "explore", "params": {"area": "k"},
                                                        "budget": {"minutes": 2}})["budget"] == {"minutes": 2.0})
check("inventory with no areas is the whole site", goals.validate({"name": "i", "kind": "inventory"})["params"] == {"areas": []})

check("an unknown kind is refused", refusal(goals.validate, {"name": "x", "kind": "fetch", "params": {}}).code == "unknown_kind")
check("an unknown field is refused", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "colour": 1}) is not None)
check("a point needs both coordinates", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": 0}}) is not None)
check("a point's x is a number", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": "a", "y": 0}}) is not None)
check("a bad frame is refused", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": 0, "y": 0, "frame": "world"}}) is not None)
check("go_to_object takes exactly one of kind, id, label",
      refusal(goals.validate, {"name": "x", "kind": "go_to_object", "params": {"kind": "fridge", "label": "mine"}}) is not None
      and refusal(goals.validate, {"name": "x", "kind": "go_to_object", "params": {}}) is not None)
check("explore takes an area or the site, not both", refusal(goals.validate, {"name": "x", "kind": "explore", "params": {"area": "k", "site": True}}) is not None)
check("a point has no budget", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "budget": {"minutes": 1}}) is not None)
check("done_when keys must apply to the kind", refusal(goals.validate, {"name": "x", "kind": "go_to_area", "params": {"area": "k"},
                                                                         "done_when": {"within_m": 1}}) is not None)
check("expect is reach or refuse", refusal(goals.validate, {"name": "x", "kind": "point", "params": {"x": 0, "y": 0}, "expect": "maybe"}) is not None)
check("a library goal needs a name", refusal(goals.validate, {"kind": "point", "params": {"x": 0, "y": 0}}) is not None)
check("an ad-hoc goal does not", goals.validate({"kind": "point", "params": {"x": 0, "y": 0}}, require_name=False)["name"] == "ad-hoc point")
check("folders are normalised", goals.normalise_folder("/tests//course/") == "tests/course")
check("a folder cannot climb", refusal(goals.normalise_folder, "../x") is not None)

# --- the checksum of a goal's content, and what the library raises ------------------------------------
base = goals.validate({"name": "a", "kind": "point", "params": {"x": 1, "y": 2}})
check("a goal's version is 16 hex characters of a sha256", goals.version(base).startswith("sha256:") and len(goals.version(base)) == len("sha256:") + 16)
check("renaming, moving to a folder or flagging a goal keeps its version",
      goals.version({**base, "name": "b", "folder": "x", "sim_first": False}) == goals.version(base))
check("any edit to what it asks for changes it", goals.version({**base, "params": {**base["params"], "x": 2.0}}) != goals.version(base))
check("the version is the one recorded before the move", goals.version(base) == "sha256:577ba3a6d466ada3")
check("an error carries a code and a message, and no status", not hasattr(refusal(goals.validate, {"kind": "fetch"}), "status")
      and refusal(goals.validate, {"kind": "fetch"}).code == "unknown_kind")

if failures:
    print(f"FAIL test_goals: {len(failures)} failed: {failures}")
    sys.exit(1)
print("PASS test_goals")
