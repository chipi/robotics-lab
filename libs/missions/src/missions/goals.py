"""Goals (RFC-0014 §3.4): a kind, what it is about, how it is done, what it must not do. A kind is a name plus a validated schema; an
unknown kind or field is refused (RFC-0004 §2.1). The planning half of what was Mission Control's goals.py: no run, no robot."""

import hashlib
import json
import math

from . import guardrails
from .errors import invalid

KINDS = ("point", "go_to_object", "go_to_area", "explore", "inventory")

EXPECTS = ("reach", "refuse")
FIELDS = {"name", "folder", "kind", "params", "done_when", "must_not", "expect", "budget", "scene", "sim_first"}
SERVER_FIELDS = {"id", "created_at", "updated_at"}

# ADR-0015's REACHED_M, RFC-0014 §3.4.1's table
DEFAULT_DONE_WHEN = {
    "point": {"within_m": 0.25, "within_s": 60.0},
    "go_to_object": {"within_m": 0.35, "facing_deg": 45.0, "within_s": 300.0},
    "go_to_area": {"within_s": 300.0},
    "explore": {},
    "inventory": {},
}
DEFAULT_BUDGET_MIN = 5.0

BUDGET_KINDS = ("explore", "inventory", "go_to_object")

def _num(value, what: str, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or (positive and value <= 0):
        raise invalid(f"{what} must be a number{' above 0' if positive else ''}, got {value!r}", "bad_goal")
    return float(value)


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid(f"{what} must be a non-empty string", "bad_goal")
    return value.strip()


def _params(kind: str, p) -> dict:
    if not isinstance(p, dict):
        raise invalid("params must be an object", "bad_goal")
    if kind == "point":
        extra = set(p) - {"x", "y", "frame"}
        if extra or "x" not in p or "y" not in p:
            raise invalid("point params are {x, y, frame?}", "bad_goal")
        frame = p.get("frame", "site")
        if frame not in ("site", "map"):
            raise invalid("a point's frame is 'site' or 'map'", "bad_goal")
        return {"x": _num(p["x"], "x", positive=False), "y": _num(p["y"], "y", positive=False), "frame": frame}
    if kind == "go_to_object":
        keys = [k for k in ("kind", "id", "label") if k in p]
        if len(keys) != 1 or set(p) - {"kind", "id", "label", "area"}:
            raise invalid("go_to_object params are exactly one of kind, id, label, and an optional area", "bad_goal")
        out = {keys[0]: _text(p[keys[0]], keys[0])}
        if "area" in p:
            out["area"] = _text(p["area"], "area")
        return out
    if kind == "go_to_area":
        if set(p) != {"area"}:
            raise invalid("go_to_area params are {area}", "bad_goal")
        return {"area": _text(p["area"], "area")}
    if kind == "explore":
        if set(p) not in ({"area"}, {"site"}):
            raise invalid("explore params are {area} or {site: true}", "bad_goal")
        if "site" in p:
            if p["site"] is not True:
                raise invalid("explore's site is true: the site of the run", "bad_goal")
            return {"site": True}
        return {"area": _text(p["area"], "area")}
    if kind == "inventory":
        if set(p) - {"areas"}:
            raise invalid("inventory params are {areas?}", "bad_goal")
        areas = p.get("areas", [])
        if not isinstance(areas, list):
            raise invalid("inventory areas is a list", "bad_goal")
        return {"areas": [_text(a, "an area") for a in areas]}
    raise invalid(f"unknown goal kind {kind!r}; known: {', '.join(KINDS)}", "unknown_kind")


def _done_when(kind: str, given) -> dict:
    allowed = {"within_m", "facing_deg", "within_s"}
    if given is None:
        given = {}
    if not isinstance(given, dict) or set(given) - allowed:
        raise invalid(f"done_when keys are {sorted(allowed)}", "bad_goal")
    out = dict(DEFAULT_DONE_WHEN[kind])
    for k, v in given.items():
        if k not in out:
            raise invalid(f"{k} does not apply to a {kind} goal", "bad_goal")
        out[k] = _num(v, k)
    return out


def validate(spec, *, require_name: bool = True) -> dict:
    """A goal as stored: every default filled in, every field checked."""
    if not isinstance(spec, dict):
        raise invalid("a goal is an object", "bad_goal")
    spec = {k: v for k, v in spec.items() if k not in SERVER_FIELDS}  # what GET returns can go back in a PUT
    extra = set(spec) - FIELDS
    if extra:
        raise invalid(f"unknown goal fields {sorted(extra)}", "bad_goal")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise invalid(f"unknown goal kind {kind!r}; known: {', '.join(KINDS)}", "unknown_kind")
    name = spec.get("name")
    if name is None and not require_name:
        name = f"ad-hoc {kind}"
    expect = spec.get("expect", "reach")
    if expect not in EXPECTS:
        raise invalid("expect is 'reach' or 'refuse'", "bad_goal")
    out = {
        "name": _text(name, "name"),
        "folder": normalise_folder(spec.get("folder", "")),
        "kind": kind,
        "params": _params(kind, spec.get("params", {})),
        "done_when": _done_when(kind, spec.get("done_when")),
        "must_not": guardrails.normalise_list(spec.get("must_not")),
        "expect": expect,
    }
    if kind in BUDGET_KINDS:
        budget = spec.get("budget") or {}
        if not isinstance(budget, dict) or set(budget) - {"minutes"}:
            raise invalid("budget is {minutes}", "bad_goal")
        out["budget"] = {"minutes": _num(budget.get("minutes", DEFAULT_BUDGET_MIN), "budget minutes")}
    elif spec.get("budget"):
        raise invalid(f"a {kind} goal has no budget", "bad_goal")
    if "scene" in spec:
        out["scene"] = _text(spec["scene"], "scene")
    if "sim_first" in spec:
        if not isinstance(spec["sim_first"], bool):
            raise invalid("sim_first is true or false", "bad_goal")
        out["sim_first"] = spec["sim_first"]        # false is kept: on a real robot absent means on, so false is the opt-out
    return out


def version(goal: dict) -> str:
    """What a rehearsal must have in common with the run it rehearses: the goal's content. Its name, its folder and the flag itself are
    not what the robot does, so renaming or flagging a goal keeps its rehearsal, and any edit to what it asks for drops it."""
    body = {k: v for k, v in goal.items() if k not in ("name", "folder", "sim_first")}
    return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def normalise_folder(folder) -> str:
    if not isinstance(folder, str):
        raise invalid("folder is a path like 'kitchen' or 'tests/course'", "bad_goal")
    parts = [p.strip() for p in folder.split("/") if p.strip()]
    if any(p in (".", "..") for p in parts):
        raise invalid("a folder path has no . or .. parts", "bad_goal")
    return "/".join(parts)
