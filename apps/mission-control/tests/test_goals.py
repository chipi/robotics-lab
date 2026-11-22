"""Goal kinds and their schemas, guardrails at three levels and their merge, and which robot may take which
goal (RFC-0014 §3.3.2, §3.4.1, §3.4.8). Pure rules, no robot.
Run: cd apps/mission-control && uv run python tests/test_goals.py"""

import copy

from common import FAKE_FILE, check, finish

from mission_control import goals, guardrails
from mission_control.errors import ApiError

CAPS = FAKE_FILE["capabilities"]


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ApiError as exc:
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

# --- which robot may take which goal (§3.3.2) -----------------------------------------------------
def goal(k, **params):
    return goals.validate({"name": "g", "kind": k, "params": params})


def caps(**over):
    c = copy.deepcopy(CAPS)
    c.update(over)
    return c


check("the fake takes a point", goals.capability_refusal(CAPS, goal("point", x=0, y=0), [], has_site=False) is None)
check("a robot with no navigator refuses every goal",
      goals.capability_refusal(caps(navigator=None), goal("point", x=0, y=0), [], has_site=False) == "this robot has no navigator")
check("a goal kind the navigator does not list is refused",
      "does not list" in goals.capability_refusal(caps(navigator={"goal_kinds": ["point"], "conditions": []}),
                                                  goal("go_to_object", kind="fridge"), [], has_site=True))
r = goals.capability_refusal(caps(recognisers=[], localisation={"frame": "run", "how": "dock"}),
                             goal("go_to_object", kind="fridge"), [], has_site=True)
check("no recogniser and not localised in the site frame: refused with the RFC's reason",
      r == "no recogniser and not localised in the site frame", r)
check("localised in the site frame is enough for an object goal without a recogniser",
      goals.capability_refusal(caps(recognisers=[]), goal("go_to_object", kind="fridge"), [], has_site=True) is None)
check("a recogniser is enough without the site frame",
      goals.capability_refusal(caps(localisation={"frame": "run", "how": "dock"}), goal("go_to_object", kind="fridge"), [], has_site=True) is None)
check("inventory needs a recogniser", goals.capability_refusal(caps(recognisers=[]), goal("inventory", areas=[]), [], has_site=True)
      == "inventory needs a recogniser")
check("explore needs a map", goals.capability_refusal(caps(map=None), goal("explore", site=True), [], has_site=True) == "explore needs a robot with a map")
check("a goal about a site needs one", "site" in goals.capability_refusal(CAPS, goal("go_to_object", kind="fridge"), [], has_site=False))
check("a guardrail the robot cannot enforce refuses the goal, naming it",
      goals.capability_refusal(caps(guardrails=["contact"]), goal("point", x=0, y=0), [{"name": "max_speed", "mps": 1.0}], has_site=False)
      == "this robot cannot enforce the guardrail max_speed")
check("a condition the navigator cannot check is listed, not hidden",
      goals.not_checkable(caps(navigator={"goal_kinds": ["go_to_object"], "conditions": ["within_m", "within_s"]}),
                          goal("go_to_object", kind="fridge")) == ["facing_deg"])

# a run's ends are the navigator contract's, here and on the page (its own copy: the page has them before any request)
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from runfile import navcontract  # noqa: E402

page = (Path(goals.__file__).parent / "web" / "app.js").read_text()
listed = re.search(r"^const TERMINAL = \[([^\]]*)\]", page, re.M)
on_page = re.findall(r'"([a-z_]+)"', listed.group(1)) if listed else []
check("a run's ends are the navigator contract's", goals.TERMINAL == navcontract.ENDS and goals.SUCCESS == navcontract.SUCCESS)
check("the page's list of ends is the contract's", sorted(on_page) == sorted(navcontract.ENDS),
      sorted(set(on_page) ^ set(navcontract.ENDS)))

finish("test_goals")
