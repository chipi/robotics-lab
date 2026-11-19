"""The duck's profile (RFC-0020 step 1, robots/duck/profile.json) and its validator (runfile.profile).

Two halves. The profile loaded in the simulator's variant is compared number by number with the constant it replaces in the code
(and, for the measured ones, with robots/duck/calibration/sim.json, `measured` and `why` verbatim): every number of the profile
must have an expected value here, and every expected value must be in the profile, so a number added to either side fails. Then the
validator's rules, each with the profile broken in one place and the error read for its path.
"""

import copy
import json
import math
import sys
from pathlib import Path

from duck_lab.nav import cliff, evaluate, explore_run, follow, frames, grid, run, side_drops, stuck
from duck_lab.nav.sim_camera import DEFAULTS as CAMERA_DEFAULTS
from duck_lab.challenge.judge import BOUNDS_MARGIN_M, DROP_MARGIN_M
from runfile.profile import FormatError, Profile, load_profile, merge_variant, numbers, validate_profile
from worldmodel import objects, relocalise, semantic_map

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


DUCK = Path(__file__).resolve().parents[1]
RAW = json.loads((DUCK / "profile.json").read_text())
SIM_JSON = json.loads((DUCK / "calibration" / "sim.json").read_text())
ROBOT_FILE = json.loads((DUCK.parents[1] / "apps" / "mission-control" / "robots.sim" / "duck-sim.json").read_text())
SIM = load_profile(DUCK / "profile.json", "sim")
REAL = load_profile(DUCK / "profile.json", "real")


def refused(raw) -> str | None:
    try:
        validate_profile(raw)
    except FormatError as exc:
        return str(exc)
    return None


def mutated(*path, to):
    """A copy of the profile with one value set (path through the dicts); to=KeyError removes it."""
    raw = copy.deepcopy(RAW)
    d = raw
    for k in path[:-1]:
        d = d[k]
    if to is KeyError:
        del d[path[-1]]
    else:
        d[path[-1]] = to
    return raw


# ---- the file loads, in both environments ----------------------------------------------------------------------------------
check("the shipped profile validates (the base and both variants)", refused(RAW) is None, refused(RAW))
check("sim and real are the two environments, named", SIM.variant == "sim" and REAL.variant == "real")
check("a profile read by attribute: footprint.radius_m", SIM.footprint.radius_m == 0.083)
check("a dotted path reads too, and a missing one is the default", SIM.get("locomotion.pivot.vx_mps") == -0.06 and SIM.get("no.such", 7) == 7)

# ---- every number against the constant it replaces ---------------------------------------------------------------------------
tof = SIM.sensors.tof8x8
OLD = {
    "profile_version": 1,
    "factsheet": ROBOT_FILE["factsheet"],
    "control": ROBOT_FILE["control"],
    "footprint": {"radius_m": evaluate.FOOTPRINT_M, "height_m": evaluate.DUCK_HEIGHT_M, "overhead_clear_m": evaluate.OVERHEAD_CLEAR_M,
                  "lethal_m": grid.LETHAL_M, "inflate_m": grid.INFLATE_M, "standoff_m": semantic_map.STAND_M,
                  "goal_clearance_m": evaluate.GOAL_CLEARANCE_M},
    "locomotion": {
        "cruise_mps": follow.WALK_MPS, "slowest_mps": follow.ARC_MPS, "yaw_max_rad_s": follow.MAX_YAW_RAD_S, "yaw_gain": follow.YAW_GAIN,
        "kick_rad_s": follow.KICK_RAD_S, "kick_s": follow.KICK_S, "hold_rad_s": follow.TURN_RAD_S, "restep_rad": follow.RESTEP_RAD,
        "pivot_first_deg": 45, "pivot_done_deg": 15, "slow_yaw_rad_s": follow.SLOW_YAW_RAD_S, "slow_clearance_m": follow.SLOW_CLEAR_M,
        "lookahead_m": follow.LOOKAHEAD_M, "lookahead_near_m": follow.LOOKAHEAD_NEAR_M, "goal_tol_m": follow.GOAL_TOL_M,
        "step_over_m": objects.WALK_OVER_M,
        "pivot": {"vx_mps": run.load_pivot_vx("sim"), "drop_clear_m": run.PIVOT_DROP_M, "edge_clear_m": run.PIVOT_EDGE_M,
                  "obstacle_margin_m": 0.05,       # run.PIVOT_OBSTACLE_M = grid.LETHAL_M + 0.05 (a literal there), checked below
                  "tight_m": run.TIGHT_PIVOT_M,
                  "tight_spot_m": run.TIGHT_SPOT_M, "tight_gap_s": run.TIGHT_GAP_S},
        "arc": {"clear_mm": run.ARC_CLEAR_MM, "ahead_m": run.ARC_AHEAD_M, "reach_m": run.ARC_REACH_M, "outer_deg": run.ARC_OUTER_DEG,
                "inner_deg": run.ARC_INNER_DEG},
        "stuck": {"window_s": stuck.WINDOW_S, "moved_max_m": stuck.MOVED_MAX_M},
    },
    "sensors": {
        "tof8x8": {
            "fov_deg": cliff.FOV_DEG, "rows": cliff.ROWS, "cols": cliff.COLS, "valid_status": sorted(cliff.VALID),
            "no_target_status": cliff.NO_TARGET, "range_m": cliff.NO_TARGET_RANGE_M, "look_m": cliff.LOOK_M, "extra_m": cliff.EXTRA_M,
            "min_zones": cliff.MIN_ZONES, "floor_margin_m": cliff.FLOOR_MARGIN_M, "floor_margin_per_m": cliff.FLOOR_MARGIN_PER_M,
            "low_margin_m": cliff.LOW_MARGIN_M, "low_margin_per_m": cliff.LOW_MARGIN_PER_M, "emergency_mm": run.EMERGENCY_MM,
            "reflex_ahead_m": run.REFLEX_AHEAD_M, "reflex_margin_m": 0.04,    # run.REFLEX_HALF_W_M = 0.083 + 0.04, checked below
            "mount": {"pitch_offset_deg": run.load_tof("sim")["pitch_offset_deg"]},
            "side_drops": {"cell_m": side_drops.CELL_M, "below_slope": side_drops.BELOW_SLOPE, "suspect_frames": side_drops.SUSPECT_FRAMES,
                           "suspect_ratio": side_drops.SUSPECT_RATIO, "clear_m": side_drops.CLEAR_M},
        },
        "camera": {k: v for k, v in CAMERA_DEFAULTS.items()},
    },
    "looking": {"walk_command": run.HEAD_WALK_CMD, "floor_z_m": run.LOOK_FLOOR_Z_M, "settle_frames": run.LOOK_SETTLE_FRAMES,
                "yaw_tol_deg": run.LOOK_YAW_TOL_DEG, "max_s": run.LOOK_MAX_S, "collect_s": run.LOOK_COLLECT_S, "back_s": run.HEAD_BACK_S,
                "along_m": run.LOOK_ALONG_M, "continue_m": run.CONTINUE_M, "survey_steps": explore_run.SURVEY_STEPS,
                "survey_step_deg": 90},
    "localisation": {
        "grid_res_m": ROBOT_FILE["capabilities"]["map"]["resolution_m"],      # run.mapd_grid asks mapd for 0.05 (a literal there)
        "odometry": {"scale": run.load_scale("sim"), "at_speed_mps": SIM_JSON["at_speed_mps"], "by_speed": SIM_JSON["by_speed"]},
        "fix": {"jump_m": run.FIX_JUMP_M, "jump_rad": 0.35, "record_m": run.FIX_RECORD_M, "loop_credit_s": run.LOOP_CREDIT_S,
                "hold_n": frames.HOLD_N, "hold_agree_m": frames.HOLD_AGREE_M, "hold_agree_rad": frames.HOLD_AGREE_RAD,
                "offset_max_m": frames.OFFSET_MAX_M, "offset_half_s": frames.OFFSET_HALF_S, "move_m": frames.MOVE_M,
                "move_rad": frames.MOVE_RAD, "parted_m": frames.PARTED_M, "parted_rad": frames.PARTED_RAD},
        "landmarks": {"match_m": relocalise.MATCH_M, "range_m": relocalise.RANGE_M, "anchor_range_m": relocalise.ANCHOR_RANGE_M,
                      "anchor_n": relocalise.ANCHOR_N, "anchor_spread_m": relocalise.ANCHOR_SPREAD_M, "window_s": relocalise.WINDOW_S,
                      "min_n": relocalise.MIN_N, "spread_m": relocalise.SPREAD_M, "deadband_m": relocalise.DEADBAND_M,
                      "gain": relocalise.GAIN, "max_step_m": relocalise.MAX_STEP_M},
    },
    "error_budget": {"cliff_stop_m": run.CLIFF_STOP_M, "corridor_m": cliff.CORRIDOR_DROP_M, "drop_lethal_m": grid.DROP_LETHAL_M,
                     "drop_inflate_m": grid.DROP_INFLATE_M, "edge_lethal_m": run.EDGE_LETHAL_M, "edge_inflate_m": run.EDGE_INFLATE_M,
                     "confirm_m": run.CONFIRM_M, "glanced_m": run.GLANCED_M, "absorb_m": run.ABSORB_M, "hold_off_m": run.HOLD_OFF_M,
                     "hold_detour": run.HOLD_DETOUR, "beyond_m": list(run.BEYOND_M), "assoc_m": semantic_map.ASSOC_M,
                     "unique_m": semantic_map.UNIQUE_M},
    "judge": {"fall_z_m": evaluate.FALLEN_Z_M, "drop_margin_m": DROP_MARGIN_M, "reached_m": evaluate.REACHED_M,
              "bounds_margin_m": BOUNDS_MARGIN_M},
    "rates": ROBOT_FILE["rates"],
    "capabilities": ROBOT_FILE["capabilities"],
}
have, want = dict(numbers(SIM.data)), dict(numbers(OLD))
check("every number of the profile has an expected old value, and the other way round", set(have) == set(want),
      f"only in the profile {sorted(set(have) - set(want))}; only expected {sorted(set(want) - set(have))}")
off = {p: (have[p], want[p]) for p in have if p in want and have[p] != want[p]}
check(f"all {len(have)} numbers equal the constant they replace, exactly", not off, off)

# the numbers that are not a constant of their own: derived the way the code derived them
check("the pivot's obstacle gate is the lethal ring plus the margin, to the last bit",
      grid.LETHAL_M + SIM.locomotion.pivot.obstacle_margin_m == run.PIVOT_OBSTACLE_M)
check("the reflex corridor is the radius plus the margin, to the last bit",
      SIM.footprint.radius_m + tof.reflex_margin_m == run.REFLEX_HALF_W_M)
check("the turn thresholds in degrees are the code's radians, to the last bit",
      math.radians(SIM.locomotion.pivot_first_deg) == follow.TURN_FIRST_RAD
      and math.radians(SIM.locomotion.pivot_done_deg) == follow.TURN_DONE_RAD
      and math.radians(SIM.looking.survey_step_deg) == explore_run.SURVEY_STEP_RAD)
check("the head joints and the sensor's valid statuses are the code's", tuple(SIM.looking.head_joints) == run.HEAD_JOINTS
      and set(tof.valid_status) == cliff.VALID == run.VALID_STATUS)
check("the sensor's mount in the simulator: radial ranges", tof.mount.range_kind == run.load_tof("sim")["range_kind"] == "radial")
check("the simulated camera is calibration/sim.json's", {k: v for k, v in SIM.sensors.camera.data.items() if k not in ("measured", "why")}
      == {k: v for k, v in SIM_JSON["camera"].items() if k != "about"} and SIM.sensors.camera.why == SIM_JSON["camera"]["about"])
check("the robot file's capabilities, adapter and guardrail names are the profile's",
      SIM.capabilities.data == ROBOT_FILE["capabilities"] and SIM.adapter.data == ROBOT_FILE["adapter"]
      and SIM.factsheet.data == ROBOT_FILE["factsheet"])

# measured and why, kept verbatim from the calibration file
check("odometry: measured and why are sim.json's own words",
      (SIM.localisation.odometry.measured, SIM.localisation.odometry.why) == (SIM_JSON["measured"], SIM_JSON["why"]))
check("pivot: measured and why are sim.json's own words",
      (SIM.locomotion.pivot.measured, SIM.locomotion.pivot.why) == (SIM_JSON["pivot"]["measured"], SIM_JSON["pivot"]["why"]))
check("the depth sensor's mount: measured and why are sim.json's own words",
      (tof.mount.measured, tof.mount.why) == (SIM_JSON["tof"]["measured"], SIM_JSON["tof"]["why"]))

# ---- the two environments --------------------------------------------------------------------------------------------------
check("real: the pivot is not sent a creep, the depth sensor is mapd's 3 deg axial, the odometry is taken as it is",
      REAL.locomotion.pivot.vx_mps == 0.0 and REAL.sensors.tof8x8.mount.pitch_offset_deg == 3.0
      and REAL.sensors.tof8x8.mount.range_kind == "axial" and REAL.localisation.odometry.scale == 1.0)
check("real: no simulated camera and no simulator adapter", REAL.get("sensors.camera") is None and REAL.get("adapter") is None)
check("sim: the creep, the 2.5 deg radial mount and the 0.91 scale",
      SIM.locomotion.pivot.vx_mps == -0.06 and tof.mount.pitch_offset_deg == 2.5 and SIM.localisation.odometry.scale == 0.91)
check("what the variants do not change is the same in both",
      REAL.footprint.data == SIM.footprint.data and REAL.locomotion.cruise_mps == SIM.locomotion.cruise_mps
      and REAL.error_budget.data == SIM.error_budget.data)
check("the plugins are named for every interface the blocks need",
      SIM.plugins.data == {"locomotion": "duck-walk@1", "range_sensing": "tof8x8@1", "localisation": "mapd@1", "looking": "duck-head@1"})

# ---- the validator's rules, each with the profile broken in one place ---------------------------------------------------------
def says(raw, *parts) -> bool:
    msg = refused(raw)
    return msg is not None and all(p in msg for p in parts)


check("a profile that is not an object is refused", says([], "must be an object"))
check("an unknown field at the top is an error, named", says({**RAW, "bogus": 1}, "profile: unknown fields ['bogus']"))
check("an unknown field in a block is an error with its path", says(mutated("footprint", "radius", to=0.1), "profile.footprint", "'radius'"))
check("an unknown field two levels down is an error with its path", says(mutated("locomotion", "arc", "reachh_m", to=1.0),
                                                                        "profile.locomotion.arc", "reachh_m"))
for need in ("profile_version", "id", "label", "kind", "factsheet", "footprint", "locomotion", "plugins", "control"):
    check(f"{need} is required", says(mutated(need, to=KeyError), need, "required"))
check("a profile version this reader does not know is refused", says(mutated("profile_version", to=2), "profile_version", "version 1"))
check("a number must be a number, with the path and the value", says(mutated("footprint", "radius_m", to="big"),
                                                                    "profile.footprint.radius_m", "a number above 0", "'big'"))
check("a number above 0 is not 0", says(mutated("locomotion", "cruise_mps", to=0), "profile.locomotion.cruise_mps"))
check("a whole number is not a fraction", says(mutated("sensors", "tof8x8", "rows", to=8.5), "profile.sensors.tof8x8.rows", "whole number"))
check("true is not a number", says(mutated("judge", "fall_z_m", to=True), "profile.judge.fall_z_m"))
check("measured must be text", says(mutated("locomotion", "pivot", "measured", to=3), "profile.locomotion.pivot.measured"))

plugins = lambda **kw: mutated("plugins", to={**RAW["plugins"], **kw})      # noqa: E731
for interface, block in (("locomotion", "locomotion"), ("range_sensing", "sensors"), ("localisation", "localisation"), ("looking", "looking")):
    raw = copy.deepcopy(RAW)
    del raw["plugins"][interface]
    check(f"the {block} block needs a {interface} plugin", says(raw, "plugins", f"the {block} block needs a {interface} plugin"))
check("a plugin is name@version", says(plugins(locomotion="duck-walk"), "plugins.locomotion", "name@version"))
check("a plugin's version is a whole number from 1", says(plugins(locomotion="duck-walk@0"), "plugins.locomotion"))
check("an interface the platform does not have is refused", says(plugins(flying="x@1"), "plugins", "flying"))

check("cruise above the factsheet's maximum speed is refused", says(mutated("locomotion", "cruise_mps", to=0.4), "cruise_mps 0.4",
                                                                    "maximumSpeed 0.3"))
check("slowest above cruise is refused", says(mutated("locomotion", "slowest_mps", to=0.31), "slowest_mps 0.31", "cruise_mps 0.3"))
check("a turn limit above the maximum angular speed is refused", says(mutated("locomotion", "kick_rad_s", to=1.6), "kick_rad_s 1.6",
                                                                      "maximumAngularSpeed 1.5"))
check("a radius above the lethal ring is refused", says(mutated("footprint", "radius_m", to=0.13), "radius_m 0.13", "lethal_m 0.12"))
check("a lethal ring above the inflation is refused", says(mutated("footprint", "lethal_m", to=0.3), "lethal_m 0.3", "inflate_m 0.28"))
check("a max_speed guardrail above the maximum speed is refused",
      says(mutated("guardrails", to=[{"name": "max_speed", "mps": 0.5}]), "guardrails", "0.5 m/s", "maximumSpeed 0.3"))
check("a max_speed guardrail at the maximum is fine", refused(mutated("guardrails", to=[{"name": "max_speed", "mps": 0.3}])) is None)
check("the factsheet is checked by Mission Control's rules (a kinematics that is not one)",
      says(mutated("factsheet", "typeSpecification", "mobileRobotKinematics", to="WINGED"), "mobileRobotKinematics"))
check("the control block is checked by Mission Control's rules (a lease of 5 s)", says(mutated("control", "lease_s", to=5.0), "lease_s"))

check("a variant that is not an environment is refused", says(mutated("variants", "lab", to={}), "variants", "lab"))
check("a variant may not change what is not a block", says(mutated("variants", "real", to={"id": "x"}), "variants.real", "id"))
raw = copy.deepcopy(RAW)
del raw["variants"]["sim"]["locomotion"]["pivot"]["why"]
check("a number that differs between variants needs its why (the variant's pivot without it)",
      says(raw, "variants.sim.locomotion.pivot", "`measured` and `why`"))
raw = copy.deepcopy(RAW)
del raw["variants"]["sim"]["sensors"]["tof8x8"]["mount"]["measured"]
check("... and its measured (the variant's depth sensor without it)", says(raw, "variants.sim.sensors.tof8x8.mount", "`measured` and `why`"))
raw = copy.deepcopy(RAW)
del raw["variants"]["sim"]["localisation"]["odometry"]["why"]
check("... for a table of numbers too (the odometry by speed)", says(raw, "variants.sim.localisation.odometry"))
raw = copy.deepcopy(RAW)
raw["variants"]["real"] = {"locomotion": {"pivot": {"vx_mps": 0.0}}}
check("a variant that restates the base's number needs no why", refused(raw) is None, refused(raw))
raw = copy.deepcopy(RAW)
raw["variants"]["real"] = {"locomotion": {"pivot": {"vx_mps": -0.02}}}
check("a variant that changes it does", says(raw, "variants.real.locomotion.pivot"))
raw = copy.deepcopy(RAW)
raw["variants"]["real"] = {"locomotion": {"cruise_mps": 0.5, "measured": "a test", "why": "a test"}}
check("a variant is merged and validated again (a cruise above the maximum, said of the merged profile)",
      says(raw, "variants.real merged", "cruise_mps 0.5"))
check("merge_variant lays the variant on the base and leaves the base alone",
      merge_variant(RAW, "sim")["locomotion"]["pivot"]["vx_mps"] == -0.06 and RAW["locomotion"]["pivot"]["vx_mps"] == 0.0)
try:
    merge_variant(RAW, "lab")
    check("merge_variant refuses an unknown variant", False)
except FormatError as exc:
    check("merge_variant refuses an unknown variant, naming the ones it has", "variants.lab" in str(exc) and "sim" in str(exc), str(exc))

check("Profile: an attribute that is not there is an AttributeError", not hasattr(SIM, "no_such_block"))
check("Profile: a table of numbers stays a plain dict", SIM.localisation.odometry.by_speed == {"0.2": 0.849, "0.3": 0.911, "0.4": 0.930})

print("PROFILE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
