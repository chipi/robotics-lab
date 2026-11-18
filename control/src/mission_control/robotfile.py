"""The robot file's `factsheet` and `control` blocks (RFC-0014 §3.3.1, docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md, decided 2026-11-18).

`factsheet` is a subset of VDA 5050 3.0.0's factsheet with VDA's names verbatim (camelCase, SI units: metres, seconds, radians), so a
real VDA robot's factsheet can fill it by copying. Everything VDA has no field for stays ours, in snake_case, beside it (`control`,
`capabilities`, `rates`, `guardrails`, `adapter`). Two values are ours inside the factsheet and say so here: the kinematics
`LEGGED` (VDA's enum is extensible, and has no legs) and an action's `irreversible`."""

from numbers import Real

KINEMATICS = {"DIFFERENTIAL", "OMNIDIRECTIONAL", "THREE_WHEEL", "LEGGED"}   # LEGGED is ours: the duck
LOCALIZATION_TYPES = {"NATURAL", "REFLECTOR", "RFID", "DMC", "SPOT", "GRID"}
ACTION_SCOPES = {"INSTANT", "NODE", "EDGE"}
BLOCKING_TYPES = {"NONE", "SOFT", "HARD"}
TYPE_FIELDS = {"seriesName", "seriesDescription", "mobileRobotKinematics", "localizationTypes", "navigationTypes"}
PHYSICAL_FIELDS = {"maximumSpeed", "maximumAngularSpeed", "maximumAcceleration", "maximumDeceleration", "width", "length"}
ACTION_FIELDS = {"actionType", "actionScopes", "blockingTypes", "pauseAllowed", "cancelAllowed", "irreversible"}   # irreversible: ours
CONTROL_FIELDS = {"deadman_s", "lease_s", "takeover"}
DEFAULT_DEADMAN_S = 0.5
DEFAULT_LEASE_S = 20.0


class FormatError(ValueError):
    pass


def _number(v, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, Real) or v <= 0:
        raise FormatError(f"{where} must be a number above 0")
    return float(v)


def _strings(v, where: str, allowed: set | None = None) -> list:
    if not isinstance(v, list) or not all(isinstance(s, str) and s for s in v):
        raise FormatError(f"{where} must be a list of strings")
    if allowed is not None and set(v) - allowed:
        raise FormatError(f"{where}: {sorted(set(v) - allowed)} are not among {sorted(allowed)}")
    return v


def _block(raw, where: str, fields: set) -> dict:
    if not isinstance(raw, dict):
        raise FormatError(f"{where} must be an object")
    extra = set(raw) - fields
    if extra:
        raise FormatError(f"{where}: unknown fields {sorted(extra)} (the fields are {sorted(fields)})")
    return raw


def parse_factsheet(raw) -> dict:
    """The validated factsheet (an empty one when the file has none): the fields of the three blocks Mission Control reads."""
    if raw is None:
        return {}
    fs = _block(raw, "factsheet", {"typeSpecification", "physicalParameters", "protocolFeatures"})
    if "typeSpecification" in fs:
        ts = _block(fs["typeSpecification"], "factsheet.typeSpecification", TYPE_FIELDS)
        for k in ("seriesName", "seriesDescription"):
            if k in ts and not isinstance(ts[k], str):
                raise FormatError(f"factsheet.typeSpecification.{k} must be a string")
        if "mobileRobotKinematics" in ts and ts["mobileRobotKinematics"] not in KINEMATICS:
            raise FormatError(f"factsheet.typeSpecification.mobileRobotKinematics must be one of {sorted(KINEMATICS)} (LEGGED is ours, not VDA's)")
        if "localizationTypes" in ts:
            _strings(ts["localizationTypes"], "factsheet.typeSpecification.localizationTypes", LOCALIZATION_TYPES)
        if "navigationTypes" in ts:
            _strings(ts["navigationTypes"], "factsheet.typeSpecification.navigationTypes")
    if "physicalParameters" in fs:
        pp = _block(fs["physicalParameters"], "factsheet.physicalParameters", PHYSICAL_FIELDS)
        for k, v in pp.items():
            _number(v, f"factsheet.physicalParameters.{k}")
    if "protocolFeatures" in fs:
        pf = _block(fs["protocolFeatures"], "factsheet.protocolFeatures", {"mobileRobotActions"})
        actions = pf.get("mobileRobotActions", [])
        if not isinstance(actions, list):
            raise FormatError("factsheet.protocolFeatures.mobileRobotActions must be a list")
        seen = set()
        for i, a in enumerate(actions):
            where = f"factsheet.protocolFeatures.mobileRobotActions[{i}]"
            a = _block(a, where, ACTION_FIELDS)
            if not isinstance(a.get("actionType"), str) or not a["actionType"]:
                raise FormatError(f"{where}.actionType is a name")
            if a["actionType"] in seen:
                raise FormatError(f"{where}: the action {a['actionType']} is listed twice")
            seen.add(a["actionType"])
            if "actionScopes" in a:
                _strings(a["actionScopes"], f"{where}.actionScopes", ACTION_SCOPES)
            if "blockingTypes" in a:
                _strings(a["blockingTypes"], f"{where}.blockingTypes", BLOCKING_TYPES)
            for k in ("pauseAllowed", "cancelAllowed", "irreversible"):
                if k in a and not isinstance(a[k], bool):
                    raise FormatError(f"{where}.{k} must be true or false")
    return fs


def parse_control(raw) -> dict:
    """{deadman_s, lease_s, takeover}: the lock is ours (RFC-0017), VDA has no control lock."""
    ctl = _block({} if raw is None else raw, "control", CONTROL_FIELDS)
    deadman = _number(ctl.get("deadman_s", DEFAULT_DEADMAN_S), "control.deadman_s")
    lease = ctl.get("lease_s", DEFAULT_LEASE_S)
    if isinstance(lease, bool) or not isinstance(lease, Real) or not 10.0 <= lease <= 30.0:
        raise FormatError("control.lease_s is 10 to 30 s (RFC-0017 §3.3)")
    takeover = ctl.get("takeover", [])
    if not isinstance(takeover, list) or not all(isinstance(n, str) for n in takeover):
        raise FormatError("control.takeover is a list of client names")
    return {"deadman_s": deadman, "lease_s": float(lease), "takeover": list(takeover)}


def check_max_speed(guardrails: list, factsheet: dict) -> None:
    """A max_speed guardrail is the limit applied; `maximumSpeed` is what the robot can do: the limit may not be above the ability."""
    ability = (factsheet.get("physicalParameters") or {}).get("maximumSpeed")
    if ability is None:
        return
    for g in guardrails:
        if g["name"] == "max_speed" and g["mps"] > ability:
            raise FormatError(f"the max_speed guardrail {g['mps']:g} m/s is above factsheet.physicalParameters.maximumSpeed {ability:g} m/s")
