"""Guardrails (RFC-0014 §3.4.8): what a goal must not do, at three levels (the robot's, the site's,
the goal's), merged into every goal run. A goal can add guardrails and can never remove or loosen
a site's or a robot's: the merge is a union in which the stricter limit of two wins.

An entry is a bare name for the ones with no limit ("contact") or an object with its limit
({"name": "max_speed", "mps": 0.2}). `no_go_area` names an area of the site ({"name": "no_go_area",
"area": "stairwell"}); Mission Control resolves it to the outline before the navigator sees it."""

import math

from .errors import invalid

# The names are the capability list of RFC-0014 §3.3.2. §3.4.1's example writes "drop" and "stall":
# they are accepted and stored as "fall" and "stuck".
ALIASES = {"drop": "fall", "stall": "stuck"}
LEVELS = ("robot", "site", "goal")

# name -> (the limit's field, which way is stricter) ; None: the guardrail has no limit
_LIMITS = {
    "contact": None,
    "fall": None,
    "stuck": None,
    "time_limit": ("seconds", min),
    "max_speed": ("mps", min),
    "drop_clearance": ("m", max),
    "no_go_area": None,
}
NAMES = tuple(_LIMITS)


def normalise(entry) -> dict:
    """One guardrail as {"name", ...limit}, or a 422."""
    if isinstance(entry, str):
        entry = {"name": entry}
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise invalid(f"a guardrail is a name or an object with a name, got {entry!r}", "bad_guardrail")
    name = ALIASES.get(entry["name"], entry["name"])
    if name not in _LIMITS:
        raise invalid(f"unknown guardrail {entry['name']!r}; known: {', '.join(NAMES)}", "bad_guardrail")
    rest = {k: v for k, v in entry.items() if k != "name"}
    if name == "no_go_area":
        if set(rest) != {"area"} or not isinstance(rest["area"], str) or not rest["area"]:
            raise invalid("no_go_area needs the area (an id or a name of the site)", "bad_guardrail")
        return {"name": name, "area": rest["area"]}
    limit = _LIMITS[name]
    if limit is None:
        if rest:
            raise invalid(f"{name} has no limit, got {sorted(rest)}", "bad_guardrail")
        return {"name": name}
    field = limit[0]
    value = rest.get(field)
    if set(rest) != {field} or isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value <= 0:
        raise invalid(f"{name} needs {field}, a number above 0", "bad_guardrail")
    return {"name": name, field: float(value)}


def normalise_list(entries) -> list:
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise invalid("must_not is a list of guardrails", "bad_guardrail")
    out = []
    for e in entries:
        n = normalise(e)
        if n not in out:
            out.append(n)
    return out


def merge(levels: dict) -> list:
    """`levels` maps "robot", "site", "goal" to normalised lists. Each merged entry says which
    levels name it ("from"). Two entries of one name keep the stricter limit."""
    merged: dict = {}
    for level in LEVELS:
        for entry in levels.get(level, []):
            name = entry["name"]
            key = (name, entry["area"]) if name == "no_go_area" else (name,)
            if key not in merged:
                merged[key] = {**entry, "from": [level]}
                continue
            have = merged[key]
            limit = _LIMITS[name]
            if limit is not None:
                field, stricter = limit
                have[field] = stricter(have[field], entry[field])
            if level not in have["from"]:
                have["from"].append(level)
    return list(merged.values())
