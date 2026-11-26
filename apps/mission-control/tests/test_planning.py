"""The one door to the library missions (RFC-0030 section 4.1, review M6): the library's PlanError becomes the ApiError it has always been
(422 with the library's code; 502 for planner_failed), and nothing else in Mission Control imports the library, so no PlanError can reach
the API's handler, which answers 500 to anything that is not an ApiError.
Run: cd apps/mission-control && uv run python tests/test_planning.py"""

import ast
from pathlib import Path

from common import check, finish

from mission_control import planning
from mission_control.errors import ApiError


def refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ApiError as exc:
        return exc
    except Exception as exc:
        return exc
    return None


bad = refusal(planning.validate, {"name": "x", "kind": "point", "params": {"x": 0}})
check("a bad goal is a 422 bad_goal ApiError", isinstance(bad, ApiError) and bad.status == 422 and bad.code == "bad_goal", repr(bad))
bad = refusal(planning.validate, {"name": "x", "kind": "fetch"})
check("an unknown kind is a 422 unknown_kind", isinstance(bad, ApiError) and (bad.status, bad.code) == (422, "unknown_kind"), repr(bad))
bad = refusal(planning.normalise, "teleport")
check("an unknown guardrail is a 422 bad_guardrail", isinstance(bad, ApiError) and (bad.status, bad.code) == (422, "bad_guardrail"), repr(bad))
bad = refusal(planning.normalise_list, "contact")
check("a must_not that is no list is a 422 bad_guardrail", isinstance(bad, ApiError) and (bad.status, bad.code) == (422, "bad_guardrail"), repr(bad))
bad = refusal(planning.normalise_folder, "../x")
check("a folder that climbs is a 422 bad_goal", isinstance(bad, ApiError) and (bad.status, bad.code) == (422, "bad_goal"), repr(bad))
bad = refusal(planning.plan, "  ", planning.Context())
check("an empty request is a 422 invalid", isinstance(bad, ApiError) and (bad.status, bad.code) == (422, "invalid"), repr(bad))
bad = refusal(planning.plan, "do a dance", planning.Context(), planning.LlmPlanner("http://127.0.0.1:9/v1", "m", None, timeout_s=2.0))
check("a model that cannot be reached is a 502 planner_failed", isinstance(bad, ApiError) and (bad.status, bad.code) == (502, "planner_failed"), repr(bad))
check("a good goal passes through", planning.validate({"name": "x", "kind": "inventory"})["params"] == {"areas": []})

src = Path(planning.__file__).parent
importers = sorted(f.name for f in src.rglob("*.py") if any(
    (isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").split(".")[0] == "missions")
    or (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "missions" for a in n.names))
    for n in ast.walk(ast.parse(f.read_text()))))
check("only planning.py imports the library missions", importers == ["planning.py"], importers)

finish("test_planning")
