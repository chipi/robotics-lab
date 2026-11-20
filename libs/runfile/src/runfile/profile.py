"""A robot's profile (RFC-0020 §3, docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md): one JSON file per robot, `robots/<robot>/profile.json`, with
the robot file's `factsheet` and `control` (VDA 5050 3.0.0's names, ours beside them) and the blocks the navigator, the judge and the
views read: `footprint`, `locomotion`, `sensors`, `looking`, `localisation`, `error_budget`, `judge`, `anomalies`. A `variants` block holds what
differs between environments (`sim`, `real`): a variant is merged on the base and the result is validated again.

    profile = load_profile("robots/duck/profile.json", "sim")      # a Profile: profile.footprint.radius_m
    validate_profile(raw)                                          # every variant, or ProfileError naming the path and what is wrong

Rules the validator holds (RFC-0020 PHASE3-PREP §A2):
  - unknown fields are errors, at every level;
  - `plugins` names every interface the blocks need (`locomotion`, `range_sensing`, `localisation`, `looking`) as `name@version`;
  - a number that differs between variants sits in a block that carries `measured` and `why` (how it was measured, and what it fixed);
  - cruise <= the factsheet's maximum speed, slowest <= cruise, the turn limits <= the maximum angular speed,
    radius <= lethal <= inflate, the `max_speed` guardrail <= the maximum speed.

The factsheet and control parsers are Mission Control's (its robotfile.py re-exports them from here): the robot file and the profile share
them, and the run format's library is where the navigator, Mission Control and the Observatory can all read them."""

import copy
import json
import re
from numbers import Real
from pathlib import Path

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


ProfileError = FormatError


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


# ---- the profile -------------------------------------------------------------------------------------------------------------

PROFILE_VERSION = 1
ENVIRONMENTS = ("sim", "real")
INTERFACES = ("locomotion", "range_sensing", "localisation", "looking")
# the blocks that need an interface's plugin: a profile with the block names the plugin
NEEDS = {"locomotion": "locomotion", "sensors": "range_sensing", "localisation": "localisation", "looking": "looking"}
PLUGIN = re.compile(r"^[a-z][a-z0-9_-]*@[1-9][0-9]*$")
META = ("measured", "why")

# A field's kind: "pos" (a number above 0), "num" (any number), "nonneg", "int" (an integer above 0), "str", "bool", "strs", "ints",
# "pos_map" (an object of numbers above 0: a leaf, as a table of values), "num_map", or a nested dict. Every dict may also carry
# `measured` and `why`.
SCHEMA = {
    "body": {"description": "str", "urdf": "str"},
    "footprint": {"shape": "str", "radius_m": "pos", "height_m": "pos", "overhead_clear_m": "pos", "lethal_m": "pos", "inflate_m": "pos",
                  "standoff_m": "pos", "goal_clearance_m": "pos"},
    "locomotion": {
        "cruise_mps": "pos", "slowest_mps": "pos", "yaw_max_rad_s": "pos", "yaw_gain": "pos", "kick_rad_s": "pos", "kick_s": "pos",
        "hold_rad_s": "pos", "restep_rad": "pos", "pivot_first_deg": "pos", "pivot_done_deg": "pos", "slow_yaw_rad_s": "pos",
        "slow_clearance_m": "pos", "lookahead_m": "pos", "lookahead_near_m": "pos", "goal_tol_m": "pos", "step_over_m": "pos",
        "steer": {"deadband_rad": "pos"},
        "pace": {"caution_mps": "pos", "look_m": "pos", "unknown_reach_m": "pos"},
        "pivot": {"vx_mps": "num", "drop_clear_m": "pos", "edge_clear_m": "pos", "obstacle_margin_m": "pos", "tight_m": "pos",
                  "tight_spot_m": "pos", "tight_gap_s": "pos"},
        "arc": {"clear_mm": "pos", "ahead_m": "pos", "reach_m": "pos", "outer_deg": "pos", "inner_deg": "pos"},
        "stuck": {"window_s": "pos", "moved_max_m": "pos"},
    },
    "sensors": {
        "tof8x8": {"fov_deg": "pos", "rows": "int", "cols": "int", "valid_status": "ints", "no_target_status": "int", "range_m": "pos",
                   "look_m": "pos", "extra_m": "pos", "min_zones": "int", "floor_margin_m": "pos", "floor_margin_per_m": "nonneg",
                   "low_margin_m": "pos", "low_margin_per_m": "nonneg", "emergency_mm": "pos", "reflex_ahead_m": "pos",
                   "reflex_margin_m": "nonneg",
                   "mount": {"pitch_offset_deg": "num", "range_kind": "str"},
                   "floor_view": {"from_m": "pos", "to_m": "pos", "half_width_m": "pos"},
                   "side_drops": {"below_slope": "nonneg", "suspect_frames": "int", "suspect_ratio": "pos",
                                  "clear_m": "pos"}},
        "camera": {"hfov_deg": "pos", "range_m": "pos", "p_detect": "pos", "range_noise": "nonneg", "bearing_noise_deg": "nonneg",
                   "period_s": "pos"},
    },
    "looking": {"head_joints": "strs", "walk_command": "num_map", "floor_z_m": "num", "settle_frames": "int", "yaw_tol_deg": "pos",
                "max_s": "pos", "collect_s": "pos", "back_s": "pos", "along_m": "pos", "continue_m": "pos", "survey_steps": "int",
                "survey_step_deg": "pos"},
    "localisation": {
        "source": "str", "maps_only_at_stops": "bool", "grid_res_m": "pos",
        "odometry": {"scale": "pos", "at_speed_mps": "pos", "by_speed": "pos_map", "straight_rad_s": "pos"},
        "fix": {"jump_m": "pos", "jump_rad": "pos", "record_m": "pos", "loop_credit_s": "pos", "hold_n": "int", "hold_agree_m": "pos",
                "hold_agree_rad": "pos", "offset_max_m": "pos", "offset_half_s": "pos", "move_m": "pos", "move_rad": "pos",
                "parted_m": "pos", "parted_rad": "pos"},
        "landmarks": {"match_m": "pos", "range_m": "pos", "anchor_range_m": "pos", "anchor_n": "int", "anchor_spread_m": "pos",
                      "window_s": "pos", "min_n": "int", "spread_m": "pos", "deadband_m": "pos", "gain": "pos", "max_step_m": "pos"},
    },
    "error_budget": {"cliff_stop_m": "pos", "corridor_m": "pos", "drop_lethal_m": "pos", "drop_inflate_m": "pos", "edge_lethal_m": "pos",
                     "edge_inflate_m": "pos", "confirm_m": "pos", "glanced_m": "pos", "absorb_m": "pos", "hold_off_m": "pos",
                     "hold_detour": "pos", "beyond_m": "nums", "assoc_m": "pos", "unique_m": "pos"},
    "judge": {"fall_z_m": "pos", "drop_margin_m": "pos", "reached_m": "pos", "bounds_margin_m": "pos"},
    "anomalies": {"head_walk_pose": "num_map", "head_off_walk_rad": "pos", "head_off_walk_s": "pos", "state_stale_s": "pos",
                  "depth_stale_s": "pos", "room_disagrees_clear_mm": "pos", "unexplained_clear_m": "pos",
                  "refusal_burst_n": "int", "refusal_burst_moved_m": "pos", "same_place_moved_m": "pos", "same_place_gap_s": "pos"},
    "capabilities": "any",
    "guardrails": "any",
    "rates": {"state_hz": "pos", "map_hz": "pos", "max_state_hz": "pos"},
    "adapter": {"type": "str", "gate_socket": "str", "navigator": "str", "mapd_socket": "str", "observatory": "str"},
}
TOP = {"profile_version", "id", "label", "kind", "factsheet", "control", "plugins", "variants", *SCHEMA}
REQUIRED = ("profile_version", "id", "label", "kind", "factsheet", "footprint", "locomotion", "plugins", "control")


def _is_number(v) -> bool:
    return isinstance(v, Real) and not isinstance(v, bool)


def _leaf(v, kind: str, where: str) -> None:
    if kind == "str":
        ok = isinstance(v, str) and bool(v)
    elif kind == "bool":
        ok = isinstance(v, bool)
    elif kind == "int":
        ok = isinstance(v, int) and not isinstance(v, bool) and v > 0
    elif kind == "pos":
        ok = _is_number(v) and v > 0
    elif kind == "nonneg":
        ok = _is_number(v) and v >= 0
    elif kind == "num":
        ok = _is_number(v)
    elif kind == "strs":
        ok = isinstance(v, list) and bool(v) and all(isinstance(s, str) and s for s in v)
    elif kind == "ints":
        ok = isinstance(v, list) and bool(v) and all(isinstance(s, int) and not isinstance(s, bool) for s in v)
    elif kind == "nums":
        ok = isinstance(v, list) and bool(v) and all(_is_number(s) and s > 0 for s in v)
    elif kind in ("pos_map", "num_map"):
        ok = isinstance(v, dict) and bool(v) and all(isinstance(k, str) and _is_number(x) and (kind == "num_map" or x > 0)
                                                     for k, x in v.items())
    else:
        raise AssertionError(f"{where}: kind {kind!r}")
    if not ok:
        want = {"str": "a non-empty string", "bool": "true or false", "int": "a whole number above 0", "pos": "a number above 0",
                "nonneg": "a number, 0 or more", "num": "a number", "strs": "a list of strings", "ints": "a list of whole numbers",
                "nums": "a list of numbers above 0", "pos_map": "an object of numbers above 0",
                "num_map": "an object of numbers"}[kind]
        raise FormatError(f"{where} must be {want}, not {v!r}")


def _check(raw, schema, where: str) -> None:
    if schema == "any":
        return
    if not isinstance(raw, dict):
        raise FormatError(f"{where} must be an object")
    extra = set(raw) - set(schema) - set(META)
    if extra:
        raise FormatError(f"{where}: unknown fields {sorted(extra)} (the fields are {sorted(schema)})")
    for k in META:
        if k in raw and not (isinstance(raw[k], str) and raw[k]):
            raise FormatError(f"{where}.{k} must be a non-empty string")
    for k, v in raw.items():
        if k in META:
            continue
        kind = schema[k]
        if isinstance(kind, dict):
            _check(v, kind, f"{where}.{k}")
        else:
            _leaf(v, kind, f"{where}.{k}")


def _numeric(v) -> bool:
    return _is_number(v) or (isinstance(v, list) and any(_is_number(x) for x in v)) or (
        isinstance(v, dict) and any(_is_number(x) for x in v.values()))


def _merge(base, over, schema, where: str, report: list) -> dict:
    """base with `over` laid on it, key by key; every number the variant changes (or adds) is reported with its block's path, for
    the `measured` and `why` rule."""
    out = copy.deepcopy(base)
    changed = False
    for k, v in over.items():
        sub = schema.get(k) if isinstance(schema, dict) else None
        if k in META:
            out[k] = v
        elif isinstance(sub, dict):
            out[k] = _merge(out.get(k, {}), v, sub, f"{where}.{k}", report) if isinstance(v, dict) else v
        else:
            if _numeric(v) and out.get(k) != v:
                changed = True
            out[k] = v
    if changed and not all(isinstance(over.get(m), str) and over.get(m) for m in META):
        report.append(where)
    return out


def merge_variant(raw: dict, variant: str) -> dict:
    """The profile as it is in one environment: the base with variants[variant] laid on it. Not validated here."""
    over = (raw.get("variants") or {}).get(variant)
    if over is None:
        raise FormatError(f"variants.{variant}: no such variant (the profile has {sorted(raw.get('variants') or {})})")
    base = {k: v for k, v in raw.items() if k != "variants"}
    unmeasured = []
    out = base
    for k, v in over.items():
        sub = SCHEMA.get(k)
        if isinstance(sub, dict) and isinstance(v, dict):
            out = {**out, k: _merge(out.get(k, {}), v, sub, f"variants.{variant}.{k}", unmeasured)}
        else:
            out = {**out, k: v}
    if unmeasured:
        raise FormatError(f"{unmeasured[0]}: a number that differs between variants needs `measured` and `why` in its block "
                          f"(how it was measured, and what it fixed)")
    return out


def _check_odometry(odo: dict, where: str) -> None:
    """The odometry scale by speed (K8): the table's speeds are numbers (m/s, as strings: JSON keys), and `scale`, the one the map
    and mapd's pose are metred by, is the table's value at `at_speed_mps` (within 1 %): a table that disagrees with the scale
    it sits beside would put the belief and the map in different metres."""
    table = odo.get("by_speed")
    if table is None:
        return
    speeds = {}
    for k, v in table.items():
        try:
            speeds[float(k)] = v
        except ValueError:
            raise FormatError(f"{where}.by_speed: the speed {k!r} is not a number (m/s)") from None
        if float(k) <= 0:
            raise FormatError(f"{where}.by_speed: the speed {k!r} must be above 0 m/s")
    at = odo.get("at_speed_mps")
    if at is None:
        raise FormatError(f"{where}.at_speed_mps is required with by_speed (the speed `scale` was measured at)")
    if at not in speeds:
        raise FormatError(f"{where}.at_speed_mps {at:g} is not a speed of by_speed ({sorted(speeds)})")
    if "scale" in odo and abs(odo["scale"] - speeds[at]) > 0.01 * speeds[at]:
        raise FormatError(f"{where}.scale {odo['scale']:g} is not by_speed's {speeds[at]:g} at {at:g} m/s (within 1 %)")


def _check_numbers(p: dict, where: str) -> None:
    fs = parse_factsheet(p["factsheet"])
    pp = fs.get("physicalParameters") or {}
    loco = p["locomotion"]
    top, ang = pp.get("maximumSpeed"), pp.get("maximumAngularSpeed")
    cruise, slowest = loco.get("cruise_mps"), loco.get("slowest_mps")
    if top is not None and cruise is not None and cruise > top:
        raise FormatError(f"{where}.locomotion.cruise_mps {cruise:g} is above factsheet.physicalParameters.maximumSpeed {top:g}")
    if cruise is not None and slowest is not None and slowest > cruise:
        raise FormatError(f"{where}.locomotion.slowest_mps {slowest:g} is above locomotion.cruise_mps {cruise:g}")
    caution = (loco.get("pace") or {}).get("caution_mps")
    if caution is not None:
        if slowest is not None and caution < slowest:
            raise FormatError(f"{where}.locomotion.pace.caution_mps {caution:g} is below locomotion.slowest_mps {slowest:g}: the robot "
                              f"cannot walk that slowly")
        if cruise is not None and caution > cruise:
            raise FormatError(f"{where}.locomotion.pace.caution_mps {caution:g} is above locomotion.cruise_mps {cruise:g}")
    if ang is not None:
        for k in ("yaw_max_rad_s", "kick_rad_s", "hold_rad_s"):
            if k in loco and loco[k] > ang:
                raise FormatError(f"{where}.locomotion.{k} {loco[k]:g} is above factsheet.physicalParameters.maximumAngularSpeed {ang:g}")
    fp = p["footprint"]
    if "lethal_m" in fp and "radius_m" in fp and fp["radius_m"] > fp["lethal_m"]:
        raise FormatError(f"{where}.footprint.radius_m {fp['radius_m']:g} is above footprint.lethal_m {fp['lethal_m']:g}")
    if "inflate_m" in fp and "lethal_m" in fp and fp["lethal_m"] > fp["inflate_m"]:
        raise FormatError(f"{where}.footprint.lethal_m {fp['lethal_m']:g} is above footprint.inflate_m {fp['inflate_m']:g}")
    _check_odometry((p.get("localisation") or {}).get("odometry") or {}, f"{where}.localisation.odometry")
    try:
        check_max_speed(p.get("guardrails") or [], fs)
    except FormatError as exc:
        raise FormatError(f"{where}.guardrails: {exc}") from None


def _check_one(p: dict, where: str) -> None:
    extra = set(p) - TOP
    if extra:
        raise FormatError(f"{where}: unknown fields {sorted(extra)} (the fields are {sorted(TOP)})")
    for k in REQUIRED:
        if k not in p:
            raise FormatError(f"{where}: {k} is required")
    if p["profile_version"] != PROFILE_VERSION:
        raise FormatError(f"{where}.profile_version is {p['profile_version']!r}; this reader knows version {PROFILE_VERSION}")
    for k in ("id", "label", "kind"):
        if not (isinstance(p[k], str) and p[k]):
            raise FormatError(f"{where}.{k} must be a non-empty string")
    parse_factsheet(p["factsheet"])
    if not isinstance(p["control"], dict):
        raise FormatError(f"{where}.control must be an object")
    parse_control(p["control"])
    for k, schema in SCHEMA.items():
        if k in p:
            _check(p[k], schema, f"{where}.{k}")
    plugins = p["plugins"]
    if not isinstance(plugins, dict):
        raise FormatError(f"{where}.plugins must be an object of interface: name@version")
    extra = set(plugins) - set(INTERFACES)
    if extra:
        raise FormatError(f"{where}.plugins: unknown interfaces {sorted(extra)} (the interfaces are {list(INTERFACES)})")
    for k, v in plugins.items():
        if not (isinstance(v, str) and PLUGIN.match(v)):
            raise FormatError(f"{where}.plugins.{k} must be name@version (for example duck-walk@1), not {v!r}")
    for block, interface in NEEDS.items():
        if block in p and interface not in plugins:
            raise FormatError(f"{where}.plugins: the {block} block needs a {interface} plugin")
    _check_numbers(p, where)


def validate_profile(raw) -> dict:
    """The profile, validated: the base, then every variant merged on it and validated again. Returns raw. ProfileError names the
    path and what is wrong."""
    if not isinstance(raw, dict):
        raise FormatError("the profile must be an object")
    variants = raw.get("variants", {})
    if not isinstance(variants, dict) or set(variants) - set(ENVIRONMENTS):
        raise FormatError(f"variants: must be an object with {list(ENVIRONMENTS)} as its keys, not {variants!r}")
    for k, v in variants.items():
        if not isinstance(v, dict):
            raise FormatError(f"variants.{k} must be an object")
        for sub in v:
            if sub not in SCHEMA and sub not in ("factsheet", "control", "plugins"):
                raise FormatError(f"variants.{k}: {sub} is not a block a variant may change")
    _check_one({k: v for k, v in raw.items() if k != "variants"}, "profile")
    for name in variants:
        _check_one(merge_variant(raw, name), f"variants.{name} merged")
    return raw


class Profile:
    """A validated profile in one environment, read by attribute: `profile.footprint.radius_m`. A block is a Profile, a leaf its value
    (a table of numbers, `by_speed`, stays a plain dict). `data` is the merged dict."""

    def __init__(self, data: dict, variant: str | None = None):
        self.data, self.variant = data, variant

    def __getattr__(self, name: str):
        d = self.__dict__.get("data")
        if d is None or name not in d:
            raise AttributeError(name)
        v = d[name]
        return Profile(v, self.variant) if isinstance(v, dict) and name not in ("by_speed", "walk_command", "head_walk_pose") else v

    def get(self, path: str, default=None):
        """A value by its dotted path, for example "locomotion.cruise_mps"."""
        v = self.data
        for part in path.split("."):
            if not isinstance(v, dict) or part not in v:
                return default
            v = v[part]
        return v


def numbers(data: dict, prefix: str = ""):
    """(dotted path, value) of every number in a profile dict, lists and tables of numbers by index or key, `measured`/`why` skipped."""
    for k, v in data.items():
        path = f"{prefix}{k}"
        if k in META or k in ("variants",):
            continue
        if isinstance(v, dict):
            yield from numbers(v, f"{path}.")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if _is_number(x):
                    yield f"{path}[{i}]", x
        elif _is_number(v):
            yield path, v


def load_profile(path, variant: str) -> Profile:
    """The profile file at path, validated, in the named environment (`sim` or `real`)."""
    raw = validate_profile(json.loads(Path(path).read_text()))
    return Profile(merge_variant(raw, variant), variant)
