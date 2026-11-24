"""Goals (RFC-0014 §3.4): a kind, what it is about, how it is done, what it must not do. A kind is a
name plus a validated schema; an unknown kind or field is refused (RFC-0004 §2.1)."""

import hashlib
import json
import math

from runfile import navcontract

from . import guardrails
from .errors import invalid

KINDS = ("point", "go_to_object", "go_to_area", "explore", "inventory")

# §3.4.3: a run's states. The first two are live; the rest end it, by the navigator contract's names (libs/runner/CONTRACT.md).
ACTIVE = ("queued", "running")
TERMINAL = navcontract.ENDS
STATES = ACTIVE + TERMINAL
# reach goals end `reached`; the ones with no target to reach end `done` (§3.4.3)
SUCCESS = navcontract.SUCCESS

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

# An anomaly of these kinds means a run's own measures are not to be trusted (a simulator slower than real time): the run ends with the state
# the navigator gave it and no verdict (`as_expected` null, the run's `no_verdict` says why). The runner raises it (navigator contract 1.6).
NO_VERDICT_ANOMALIES = ("rtf_low",)

# The simulator-first flag (RFC-0014 §3.4.2, phase 5 item 4b unit B8; on by default since 4e E1, `sim_first: false` opts a goal out): a goal
# runs on a real robot only after a passing simulator run of the same goal, within this long. A day: the room, the site's areas and the robot's profile are what they were when it was rehearsed,
# more or less; longer than that the rehearsal says too little about today.
REHEARSAL_MAX_AGE_S = 24 * 3600.0
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


def capability_refusal(caps: dict, goal: dict, merged: list, *, has_site: bool) -> str | None:
    """Why this robot cannot take the goal, or None (RFC-0014 §3.3.2 and §3.4.8). The reason is a
    field a client can show."""
    nav = caps.get("navigator")
    if not nav:
        return "this robot has no navigator"
    if goal["kind"] not in nav.get("goal_kinds", []):
        return f"this robot's navigator does not list the goal kind {goal['kind']}"
    kind = goal["kind"]
    names_a_place = kind in ("go_to_object", "go_to_area") or (kind == "explore" and "area" in goal["params"]) \
        or (kind == "inventory" and bool(goal["params"]["areas"]))
    if names_a_place:
        localised = (caps.get("localisation") or {}).get("frame") == "site"
        if not caps.get("recognisers") and not localised:
            return "no recogniser and not localised in the site frame"
    if kind == "inventory" and not caps.get("recognisers"):
        return "inventory needs a recogniser"
    if kind == "explore" and not caps.get("map"):
        return "explore needs a robot with a map"
    if (names_a_place or kind in ("explore", "inventory")) and not has_site:
        return "this goal is about a site and the run has none: assign the robot a site or name one"
    can = set(caps.get("guardrails", []))
    for g in merged:
        if g["name"] not in can:
            return f"this robot cannot enforce the guardrail {g['name']}"
    return None


def not_checkable(caps: dict, goal: dict) -> list:
    """The goal's done_when conditions this robot's navigator cannot check (§3.4.1: a run says which
    conditions were and were not checkable)."""
    can = set((caps.get("navigator") or {}).get("conditions", []))
    return sorted(k for k in goal["done_when"] if k not in can)


def start_pose(raw) -> dict | None:
    """The operator's word for where the robot stands on the map when a run starts (navigator contract 1.5, phase 5 item 4b unit B7):
    `{x, y, yaw}` in the site frame, metres and radians, or None for a robot that starts where its map does. It belongs to the run, not
    the goal: the same goal is run from another place tomorrow. Raises a 422 for anything else."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"x", "y", "yaw", "frame"} or not {"x", "y", "yaw"} <= set(raw) \
            or raw.get("frame", "site") != "site":
        raise invalid("start_pose is {x, y, yaw}: metres in the site frame and radians", "bad_start_pose")
    for k in ("x", "y", "yaw"):
        if isinstance(raw[k], bool) or not isinstance(raw[k], (int, float)) or not math.isfinite(raw[k]):
            raise invalid(f"start_pose's {k} must be a number, got {raw[k]!r}", "bad_start_pose")
    yaw = float(raw["yaw"])
    return {"x": float(raw["x"]), "y": float(raw["y"]), "yaw": math.atan2(math.sin(yaw), math.cos(yaw))}
