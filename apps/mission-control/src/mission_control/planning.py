"""The one door to the library missions (RFC-0030, section 4.1): the library raises PlanError(code, message) and knows no status, and
every call that can raise one passes through here and comes out as the ApiError it has always been, so each answer, status and code of
the API and the MCP tools is what it was. A test pins that nothing else in this package imports the library."""

import functools

from missions import goals as _goals
from missions import guardrails as _guardrails
from missions import planner as _planner
from missions.errors import PlanError
from missions.goals import version
from missions.guardrails import LEVELS, NAMES, merge
from missions.planner import Context, LlmPlanner, load_planner, match, read_back

from .errors import ApiError

STATUS = {"planner_failed": 502}


def _wrapped(fn):
    @functools.wraps(fn)
    def call(*args, **kw):
        try:
            return fn(*args, **kw)
        except PlanError as exc:
            raise ApiError(STATUS.get(exc.code, 422), exc.code, str(exc)) from None
    return call


validate = _wrapped(_goals.validate)
normalise_folder = _wrapped(_goals.normalise_folder)
normalise = _wrapped(_guardrails.normalise)
normalise_list = _wrapped(_guardrails.normalise_list)
plan = _wrapped(_planner.plan)

__all__ = ["Context", "LEVELS", "LlmPlanner", "NAMES", "load_planner", "match", "merge", "normalise", "normalise_folder", "normalise_list", "plan",
           "read_back", "validate", "version"]
