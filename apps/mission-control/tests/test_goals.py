"""Which robot may take which goal (RFC-0014 §3.3.2), and the executor's own check that a goal never loosens a site's or a robot's guardrails
(§3.4.8, RFC-0030 section 4.1: `merge` lives in the library missions, whose tests pin its rules, and Mission Control calls it on the safety
path). The goal schemas and the guardrail vocabulary are tested in libs/missions. Pure rules, no robot.
Run: cd apps/mission-control && uv run python tests/test_goals.py"""

import copy

from common import FAKE_FILE, check, finish

from mission_control import goals, planning

CAPS = FAKE_FILE["capabilities"]

merged = planning.merge({
    "robot": [{"name": "max_speed", "mps": 0.4}, {"name": "contact"}],
    "site": [{"name": "no_go_area", "area": "stairwell"}, {"name": "max_speed", "mps": 0.3}],
    "goal": [{"name": "max_speed", "mps": 0.9}, {"name": "time_limit", "seconds": 30.0}, {"name": "contact"}],
})
by_name = {(g["name"], g.get("area")): g for g in merged}
check("a goal cannot loosen a site's or a robot's speed cap: the strictest wins", by_name[("max_speed", None)]["mps"] == 0.3, by_name[("max_speed", None)])
check("each entry says which levels name it", by_name[("max_speed", None)]["from"] == ["robot", "site", "goal"]
      and by_name[("contact", None)]["from"] == ["robot", "goal"] and by_name[("time_limit", None)]["from"] == ["goal"])
check("the site's no-go area is in the merge", ("no_go_area", "stairwell") in by_name)


# --- which robot may take which goal (§3.3.2) -----------------------------------------------------
def goal(k, **params):
    return planning.validate({"name": "g", "kind": k, "params": params})


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
