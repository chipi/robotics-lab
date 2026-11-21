"""The duck's profile (RFC-0020, robots/duck/profile.json) and its validator (runfile.profile).

Two halves. The profile loaded in the simulator's variant is compared number by number with the value of the constant it replaced
(RFC-0020 step 1 compared it with the constants themselves; steps 2 and 3 took them out of the navigator and the plugins, so the
table below holds each constant's value as it was, with where it was), and, for the measured ones, with robots/duck/calibration/
sim.json, `measured` and `why` verbatim. The simulated camera's fidelity is also compared with sim_camera.DEFAULTS. Every number of
the profile must have an expected value here, and every expected value must be in the profile, so a number added to either side
fails. Then the validator's rules, each with the profile broken in one place and the error read for its path.
"""

import copy
import json
import math
import sys
from pathlib import Path

from duck_lab.nav import run
from labrunner.sim_camera import DEFAULTS as CAMERA_DEFAULTS
from runfile.profile import FormatError, Profile, load_profile, merge_variant, numbers, validate_profile
from worldmodel.objects import DUCK_LIMITS
from worldmodel.relocalise import DUCK_LANDMARKS

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
    # each value is what the constant was, and where (deleted in step 2)
    "footprint": {"radius_m": 0.083,            # evaluate.FOOTPRINT_M
                  "height_m": 0.272,            # evaluate.DUCK_HEIGHT_M
                  "overhead_clear_m": 0.30,     # evaluate.OVERHEAD_CLEAR_M, worldmodel.objects.OVERHEAD_M
                  "lethal_m": 0.12,             # grid.LETHAL_M
                  "inflate_m": 0.28,            # grid.INFLATE_M
                  "standoff_m": 0.25,           # semantic_map.STAND_M
                  "goal_clearance_m": 0.35},    # evaluate.GOAL_CLEARANCE_M
    "locomotion": {
        "cruise_mps": 0.3, "slowest_mps": 0.2,                  # follow.WALK_MPS, ARC_MPS
        "yaw_max_rad_s": 1.0, "yaw_gain": 1.5,                  # follow.MAX_YAW_RAD_S, YAW_GAIN
        "kick_rad_s": 1.2, "kick_s": 1.0, "hold_rad_s": 0.8,    # follow.KICK_RAD_S, KICK_S, TURN_RAD_S (explore_run had its own copies)
        "restep_rad": 0.05,                                     # follow.RESTEP_RAD
        "pivot_first_deg": 45, "pivot_done_deg": 15,            # follow.TURN_FIRST_RAD = math.radians(45), TURN_DONE_RAD = radians(15)
        "slow_yaw_rad_s": 0.4, "slow_clearance_m": 0.25,        # follow.SLOW_YAW_RAD_S, SLOW_CLEAR_M
        "lookahead_m": 0.30, "lookahead_near_m": 0.15,          # follow.LOOKAHEAD_M, LOOKAHEAD_NEAR_M
        "goal_tol_m": 0.15,                                     # follow.GOAL_TOL_M
        "step_over_m": 0.01,                                    # worldmodel.objects.WALK_OVER_M
        "pivot": {"vx_mps": SIM_JSON["pivot"]["vx_mps"],        # calibration/sim.json "pivot"
                  "drop_clear_m": 0.30,                         # run.PIVOT_DROP_M
                  "edge_clear_m": 0.26,                         # run.PIVOT_EDGE_M
                  "obstacle_margin_m": 0.05,                    # run.PIVOT_OBSTACLE_M = LETHAL_M + 0.05 (a literal there)
                  "tight_m": 0.15,                              # run.TIGHT_PIVOT_M
                  "tight_spot_m": 0.10, "tight_gap_s": 0.5},    # run.TIGHT_SPOT_M, TIGHT_GAP_S
        "arc": {"clear_mm": 300, "ahead_m": 0.25, "reach_m": 0.45,            # run.ARC_CLEAR_MM, ARC_AHEAD_M, ARC_REACH_M
                "outer_deg": 20.0, "inner_deg": 120.0},                       # run.ARC_OUTER_DEG, ARC_INNER_DEG
        "stuck": {"window_s": 3.0, "moved_max_m": 0.05},                      # stuck.WINDOW_S, MOVED_MAX_M
        "pace": {"caution_mps": 0.2, "look_m": 0.7, "unknown_reach_m": 0.4},  # RFC-0012 section 3, as the profile's measured says
    },
    "sensors": {
        "tof8x8": {
            "fov_deg": 45.0, "rows": 8, "cols": 8, "valid_status": [5, 9],                      # cliff.FOV_DEG, ROWS = COLS, VALID
            "no_target_status": 255, "range_m": 4.0,                                          # cliff.NO_TARGET, NO_TARGET_RANGE_M
            "look_m": 0.7, "extra_m": 0.06, "min_zones": 2,                                   # cliff.LOOK_M, EXTRA_M, MIN_ZONES
            "floor_margin_m": 0.08, "floor_margin_per_m": 0.03,                               # cliff.FLOOR_MARGIN_M, FLOOR_MARGIN_PER_M
            "low_margin_m": 0.035, "low_margin_per_m": 0.02,                                  # cliff.LOW_MARGIN_M, LOW_MARGIN_PER_M
            "emergency_mm": 150,                                       # run.EMERGENCY_MM
            "reflex_ahead_m": 0.30, "reflex_margin_m": 0.04,           # run.REFLEX_AHEAD_M; run.REFLEX_HALF_W_M = 0.083 + 0.04
            "mount": {"pitch_offset_deg": SIM_JSON["tof"]["pitch_offset_deg"]},
            "floor_view": {"from_m": 0.20, "to_m": 0.40, "half_width_m": 0.10},                # step_check.FROM_M, TO_M, HALF_WIDTH_M
            "side_drops": {"below_slope": 0.035, "suspect_frames": 5,                          # side_drops.BELOW_SLOPE, SUSPECT_FRAMES
                           "suspect_ratio": 3.0, "clear_m": 0.10},                                 # SUSPECT_RATIO, CLEAR_M
        },
        "camera": {k: v for k, v in CAMERA_DEFAULTS.items()},
    },
    "looking": {"walk_command": dict.fromkeys(("neck_pitch", "head_pitch", "head_yaw", "head_roll"), 0.0),    # run.HEAD_WALK_CMD
                "floor_z_m": -0.116,                              # run.LOOK_FLOOR_Z_M
                "settle_frames": 5, "yaw_tol_deg": 3.0,           # run.LOOK_SETTLE_FRAMES, LOOK_YAW_TOL_DEG
                "max_s": 3.0, "collect_s": 1.0, "back_s": 2.0,    # run.LOOK_MAX_S, LOOK_COLLECT_S, HEAD_BACK_S
                "along_m": 0.4, "continue_m": 1.0,                # run.LOOK_ALONG_M, CONTINUE_M
                "survey_steps": 4,                                # explore_run.SURVEY_STEPS
                "survey_step_deg": 90},                           # explore_run.SURVEY_STEP_RAD = math.pi / 2
    "localisation": {
        "grid_res_m": ROBOT_FILE["capabilities"]["map"]["resolution_m"],      # run.mapd_grid asks mapd for 0.05 (a literal there)
        "odometry": {"scale": SIM_JSON["odom_scale"], "at_speed_mps": SIM_JSON["at_speed_mps"], "by_speed": SIM_JSON["by_speed"],
                     "straight_rad_s": SIM_JSON["straight_rad_s"]},
        "fix": {"jump_m": 0.3, "jump_rad": 0.35,                                       # run.FIX_JUMP_M; the literal in frames.on_fix
                "record_m": 0.1, "loop_credit_s": 3.0,                                 # run.FIX_RECORD_M, LOOP_CREDIT_S
                "hold_n": 5, "hold_agree_m": 0.15, "hold_agree_rad": 0.1,              # frames.HOLD_N, HOLD_AGREE_M, HOLD_AGREE_RAD
                "offset_max_m": 1.0, "offset_half_s": 90.0,                            # frames.OFFSET_MAX_M, OFFSET_HALF_S
                "move_m": 0.05, "move_rad": 0.02,                                      # frames.MOVE_M, MOVE_RAD
                "parted_m": 0.25, "parted_rad": 0.1},                                  # frames.PARTED_M, PARTED_RAD
        # relocalise.MATCH_M ... MAX_STEP_M: the library keeps the duck's as its default numbers (DUCK_LANDMARKS)
        "landmarks": vars(DUCK_LANDMARKS),
        "closure": {"agree_m": 0.2},      # new with K26 (no constant before it); its `measured` says how it was chosen
    },
    "error_budget": {"cliff_stop_m": 0.60,                                             # run.CLIFF_STOP_M
                     "corridor_m": 0.25,                                               # cliff.CORRIDOR_DROP_M
                     "drop_lethal_m": 0.35, "drop_inflate_m": 0.55,                    # grid.DROP_LETHAL_M, DROP_INFLATE_M
                     "edge_lethal_m": 0.32, "edge_inflate_m": 0.50,                    # run.EDGE_LETHAL_M, EDGE_INFLATE_M
                     "confirm_m": 0.9, "glanced_m": 0.4, "absorb_m": 0.15,             # run.CONFIRM_M, GLANCED_M, ABSORB_M
                     "hold_off_m": 0.20, "hold_detour": 1.25,                          # run.HOLD_OFF_M, HOLD_DETOUR
                     "beyond_m": [0.1, 0.2, 0.3, 0.4],                                 # run.BEYOND_M
                     "assoc_m": DUCK_LIMITS.assoc_m, "unique_m": DUCK_LIMITS.unique_m},   # semantic_map.ASSOC_M, UNIQUE_M
    "judge": {"fall_z_m": 0.06,                       # evaluate.FALLEN_Z_M
              "drop_margin_m": 0.15,                  # challenge.judge.DROP_MARGIN_M
              "reached_m": 0.25,                      # evaluate.REACHED_M
              "bounds_margin_m": 0.05},               # challenge.judge.BOUNDS_MARGIN_M
    # new in RFC-0019 step 1 (no constant before it): the robot-tagged anomalies' numbers, each measured on the recordings, see the
    # block's own `measured` (the apartment's 66 runs): the walking head pose, how far off it counts and for how long, how long the
    # state and depth streams may be silent, the depth rule for room_disagrees (K36), the map's explaining distance
    "anomalies": {"head_walk_pose": {"neck_pitch": 0.239, "head_pitch": 0.358, "head_yaw": -0.078, "head_roll": -0.023},
                  "head_off_walk_rad": 0.30, "head_off_walk_s": 1.0, "state_stale_s": 3.0, "depth_stale_s": 3.0,
                  "room_disagrees_window_s": 4.0, "room_disagrees_look_deg": 20.0, "room_disagrees_near_m": 0.6,
                  "room_disagrees_see_m": 1.5, "room_disagrees_agree_m": 0.08, "room_disagrees_floor_slack_m": 0.02,
                  "unexplained_clear_m": 0.30,
                  # the refusal burst and the once-per-place rule, out of nav/anomaly.py (the operator: configurable)
                  "refusal_burst_n": 3, "refusal_burst_moved_m": 0.10, "same_place_moved_m": 0.10, "same_place_gap_s": 5.0},
    "rates": ROBOT_FILE["rates"],
    "capabilities": ROBOT_FILE["capabilities"],
}
have, want = dict(numbers(SIM.data)), dict(numbers(OLD))
check("every number of the profile has an expected old value, and the other way round", set(have) == set(want),
      f"only in the profile {sorted(set(have) - set(want))}; only expected {sorted(set(want) - set(have))}")
off = {p: (have[p], want[p]) for p in have if p in want and have[p] != want[p]}
check(f"all {len(have)} numbers equal the constant they replace, exactly", not off, off)

# the numbers that are not a constant of their own: derived the way the code derived them, to the last bit (0.12 + 0.05 is not 0.17)
check("the pivot's obstacle gate is the lethal ring plus the margin, to the last bit of what the constant was",
      SIM.footprint.lethal_m + SIM.locomotion.pivot.obstacle_margin_m == 0.12 + 0.05)
check("the reflex corridor is the radius plus the margin, to the last bit of what the constant was",
      SIM.footprint.radius_m + tof.reflex_margin_m == 0.083 + 0.04)
check("the turn thresholds in degrees are the radians the constants were, to the last bit",
      math.radians(SIM.locomotion.pivot_first_deg) == math.radians(45) and math.radians(SIM.locomotion.pivot_done_deg) == math.radians(15)
      and math.radians(SIM.looking.survey_step_deg) == math.pi / 2)
check("the head joints are the code's four, and the sensor's valid statuses are the code's",
      tuple(SIM.looking.head_joints) == ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
      and set(tof.valid_status) == {5, 9})
check("the world model library's duck limits are the profile's (until a second robot passes its own)",
      (SIM.locomotion.step_over_m, SIM.footprint.overhead_clear_m, SIM.footprint.standoff_m, SIM.error_budget.assoc_m,
       SIM.error_budget.unique_m) == (DUCK_LIMITS.walk_over_m, DUCK_LIMITS.overhead_m, DUCK_LIMITS.stand_m, DUCK_LIMITS.assoc_m,
                                      DUCK_LIMITS.unique_m))
check("the navigator reads the same numbers: its calibration loaders return the profile's",
      run.load_scale("sim") == 0.91 and run.load_tof("sim") == {"pitch_offset_deg": 2.5, "range_kind": "radial"}
      and run.load_pivot_vx("sim") == -0.06 and run.load_scale(None) == 1.0 and run.load_pivot_vx(None) == 0.0)
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
raw["locomotion"]["pace"]["caution_mps"] = 0.15
check("the caution pace may not be slower than the slowest walk", says(raw, "pace.caution_mps 0.15 is below locomotion.slowest_mps"))
raw = copy.deepcopy(RAW)
raw["locomotion"]["pace"]["caution_mps"] = 0.35
check("... nor faster than cruise", says(raw, "pace.caution_mps 0.35 is above locomotion.cruise_mps"))
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

raw = copy.deepcopy(RAW)
raw["variants"]["sim"]["localisation"]["odometry"]["by_speed"]["fast"] = 0.95
check("the odometry table's speeds are numbers", says(raw, "by_speed", "not a number"))
raw = copy.deepcopy(RAW)
del raw["variants"]["sim"]["localisation"]["odometry"]["at_speed_mps"]
check("a table needs the speed `scale` was measured at", says(raw, "at_speed_mps is required"))
raw = copy.deepcopy(RAW)
raw["variants"]["sim"]["localisation"]["odometry"]["at_speed_mps"] = 0.25
check("... which is one of the table's speeds", says(raw, "at_speed_mps 0.25 is not a speed of by_speed"))
raw = copy.deepcopy(RAW)
raw["variants"]["sim"]["localisation"]["odometry"]["scale"] = 0.85
check("... and `scale` is the table's value there (0.85 against 0.911 at 0.3 m/s)", says(raw, "scale 0.85 is not by_speed's 0.911"))

check("Profile: an attribute that is not there is an AttributeError", not hasattr(SIM, "no_such_block"))
check("Profile: a table of numbers stays a plain dict", SIM.localisation.odometry.by_speed == {"0.2": 0.849, "0.3": 0.911, "0.4": 0.930})

print("PROFILE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
