"""A run's states, the rehearsal rule's constants, and which robot may take which goal (RFC-0014 §3.3.2, §3.4.3, §3.4.8). The goal schemas, their
validation and the guardrail vocabulary are the library missions' (RFC-0030), reached through planning.py. Pure rules, no robot."""

import math

from runfile import navcontract

from .errors import invalid

# §3.4.3: a run's states. The first two are live; the rest end it, by the navigator contract's names (libs/runner/CONTRACT.md).
ACTIVE = ("queued", "running")
TERMINAL = navcontract.ENDS
STATES = ACTIVE + TERMINAL
# reach goals end `reached`; the ones with no target to reach end `done` (§3.4.3)
SUCCESS = navcontract.SUCCESS

# An anomaly of these kinds means a run's own measures are not to be trusted (a simulator slower than real time): the run ends with the state
# the navigator gave it and no verdict (`as_expected` null, the run's `no_verdict` says why). The runner raises it (navigator contract 1.6).
NO_VERDICT_ANOMALIES = ("rtf_low",)

# The simulator-first flag (RFC-0014 §3.4.2, phase 5 item 4b unit B8; on by default since 4e E1, `sim_first: false` opts a goal out): a goal
# runs on a real robot only after a passing simulator run of the same goal, within this long. A day: the room, the site's areas and the robot's profile are what they were when it was rehearsed,
# more or less; longer than that the rehearsal says too little about today.
REHEARSAL_MAX_AGE_S = 24 * 3600.0


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
