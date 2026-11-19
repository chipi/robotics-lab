"""The robot file's format (RFC-0014 §3.3.1, docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md): a `factsheet` with VDA 5050 3.0.0's names, our own
blocks beside it, and the load-time checks. The shipped files (the fake, the simulated duck, the NXT) are loaded as they are.
Run: cd apps/mission-control && uv run python tests/test_robotfile.py"""

import copy
import json
from pathlib import Path

from common import FAKE_FILE, check, finish, robot_file

from mission_control.robots import ConfigError, RobotConfig, load_robot_files

CONTROL = Path(__file__).resolve().parents[1]


def refused(**over):
    try:
        RobotConfig(robot_file(**over))
    except ConfigError as exc:
        return str(exc)
    return None


# --- the shipped files load, as they are ------------------------------------------------------------------------------------
for folder, rid, kinematics in (("robots.example", "fake-1", "DIFFERENTIAL"), ("robots.sim", "duck-sim", "LEGGED"), ("robots.nxt", "nxt-1", "DIFFERENTIAL")):
    cfgs = load_robot_files(CONTROL / folder)
    cfg = cfgs[0]
    check(f"{folder}/{rid}.json loads", len(cfgs) == 1 and cfg.id == rid)
    check(f"{rid}: the factsheet has VDA's names for the type: {kinematics}", cfg.factsheet["typeSpecification"]["mobileRobotKinematics"] == kinematics, cfg.factsheet)
    check(f"{rid}: no field of the first format is left (drive, lease_s, takeover at the top)", "drive" not in cfg.capabilities)
duck = load_robot_files(CONTROL / "robots.sim")[0]
check("the duck: LEGGED, 0.3 m/s and 1.5 rad/s, from the factsheet", duck.factsheet["physicalParameters"] == {"maximumSpeed": 0.3, "maximumAngularSpeed": 1.5})
nxt = load_robot_files(CONTROL / "robots.nxt")[0]
check("the NXT: speeds are not measured, so the factsheet has none; its fire action says it cannot be undone",
      "physicalParameters" not in nxt.factsheet and nxt.factsheet["protocolFeatures"]["mobileRobotActions"][0]["irreversible"] is True)
check("the control block is read: deadman, lease and takeover", nxt.control == {"deadman_s": 0.6, "lease_s": 20.0, "takeover": []} and nxt.lease_s == 20.0 and nxt.takeover == [])

# --- defaults and the control block ----------------------------------------------------------------------------------------
bare = RobotConfig({"id": "bare", "kind": "x", "adapter": {"type": "fake"}})
check("a file with no factsheet and no control block loads with the defaults (deadman 0.5 s, lease 20 s, nobody may take over)",
      bare.factsheet == {} and bare.control == {"deadman_s": 0.5, "lease_s": 20.0, "takeover": []})
for name, over, want in (
    ("a lease of 5 s", {"control": {"lease_s": 5}}, "control.lease_s is 10 to 30"),
    ("a deadman of 0", {"control": {"deadman_s": 0}}, "control.deadman_s must be a number above 0"),
    ("a takeover that is not names", {"control": {"takeover": [1]}}, "control.takeover is a list of client names"),
    ("an unknown control field", {"control": {"lease": 20}}, "control: unknown fields ['lease']"),
):
    err = refused(**over)
    check(f"{name} is refused, saying where", err is not None and want in err, err)

# --- the first format says where each field went ----------------------------------------------------------------------------
check("lease_s at the top is refused with its new place", "lease_s moved to control.lease_s" in (refused(lease_s=20.0) or ""))
check("takeover at the top is refused with its new place", "takeover moved to control.takeover" in (refused(takeover=["x"]) or ""))
err = refused(capabilities={"drive": {"max_vx": 0.3}})
check("capabilities.drive is refused with its new place", err is not None and "maximumSpeed" in err and "control.deadman_s" in err, err)

# --- the factsheet ----------------------------------------------------------------------------------------------------------
fs = lambda **blocks: copy.deepcopy({**FAKE_FILE["factsheet"], **blocks})  # noqa: E731
for name, factsheet, want in (
    ("a field VDA has not got in typeSpecification", fs(typeSpecification={"seriesNmae": "x"}), "unknown fields ['seriesNmae']"),
    ("a block that is not VDA's", fs(wheels={}), "factsheet: unknown fields ['wheels']"),
    ("a kinematics that is not in the list", fs(typeSpecification={"mobileRobotKinematics": "WINGED"}), "mobileRobotKinematics must be one of"),
    ("a speed of 0", fs(physicalParameters={"maximumSpeed": 0}), "maximumSpeed must be a number above 0"),
    ("a speed that is a string", fs(physicalParameters={"maximumSpeed": "fast"}), "maximumSpeed must be a number above 0"),
    ("a localisation that is not VDA's", fs(typeSpecification={"localizationTypes": ["GPS"]}), "localizationTypes"),
    ("an action with no name", fs(protocolFeatures={"mobileRobotActions": [{"actionScopes": ["INSTANT"]}]}), "actionType is a name"),
    ("an action scope that is not VDA's", fs(protocolFeatures={"mobileRobotActions": [{"actionType": "a", "actionScopes": ["ALL"]}]}), "actionScopes"),
    ("a blocking type that is not VDA's", fs(protocolFeatures={"mobileRobotActions": [{"actionType": "a", "blockingTypes": ["MAYBE"]}]}), "blockingTypes"),
    ("an action listed twice", fs(protocolFeatures={"mobileRobotActions": [{"actionType": "a"}, {"actionType": "a"}]}), "listed twice"),
    ("a pause flag that is not true or false", fs(protocolFeatures={"mobileRobotActions": [{"actionType": "a", "pauseAllowed": "yes"}]}), "pauseAllowed must be true or false"),
):
    err = refused(factsheet=factsheet)
    check(f"{name} is refused, naming the field", err is not None and want in err, err)
ok = RobotConfig(robot_file(factsheet=fs(typeSpecification={"seriesName": "Walker", "mobileRobotKinematics": "LEGGED", "localizationTypes": ["NATURAL", "GRID"],
                                                             "navigationTypes": ["FREELY_NAVIGATING", "ANYTHING_VDA_ADDS"]},
                                          physicalParameters={"maximumSpeed": 1, "maximumAngularSpeed": 2, "maximumAcceleration": 1, "maximumDeceleration": 1,
                                                              "width": 0.2, "length": 0.3})))
check("a full factsheet loads: LEGGED, VDA's localisation types, an open list of navigation types, acceleration, size", ok.factsheet["physicalParameters"]["length"] == 0.3)

# --- max_speed may not be above what the robot can do ---------------------------------------------------------------------------
check("a max_speed guardrail above maximumSpeed is refused at load, with both numbers",
      all(s in (refused(guardrails=[{"name": "max_speed", "mps": 0.6}]) or "") for s in ("0.6 m/s", "maximumSpeed 0.5 m/s")))
check("at the ability is fine", refused(guardrails=[{"name": "max_speed", "mps": 0.5}]) is None)
check("below it is fine", refused(guardrails=[{"name": "max_speed", "mps": 0.1}]) is None)
no_ability = RobotConfig({"id": "x", "kind": "x", "adapter": {"type": "fake"}, "capabilities": {"guardrails": ["max_speed"]},
                          "guardrails": [{"name": "max_speed", "mps": 9.0}]})
check("with no maximumSpeed in the factsheet there is nothing to check it against", no_ability.guardrails[0]["mps"] == 9.0)

# --- the NXT adapter needs a scale ------------------------------------------------------------------------------------------------
try:
    from mission_control.robots import make_adapter
    raw = json.loads((CONTROL / "robots.nxt" / "nxt-1.json").read_text())
    del raw["adapter"]["full_speed_mps"]
    make_adapter(RobotConfig(raw), None)
    check("an NXT file with no scale for a track command is refused", False)
except ConfigError as exc:
    check("an NXT file with no scale (neither adapter.full_speed_mps nor a factsheet speed) is refused, saying what to set", "full_speed_mps" in str(exc), str(exc))
raw["adapter"].pop("full_turn_rps")
raw["factsheet"]["physicalParameters"] = {"maximumSpeed": 0.2, "maximumAngularSpeed": 1.0}
adapter = make_adapter(RobotConfig(raw), None)
check("with a factsheet speed the scale comes from it", (adapter.max_vx, adapter.max_vyaw) == (0.2, 1.0))

# --- the validator is the run format library's (RFC-0020 step 1): this module re-exports it, one set of rules ---------------------
import runfile.profile as profile_rules  # noqa: E402
from mission_control import robotfile  # noqa: E402

check("robotfile re-exports runfile.profile's parsers and error, they are the same objects",
      robotfile.parse_factsheet is profile_rules.parse_factsheet and robotfile.parse_control is profile_rules.parse_control
      and robotfile.check_max_speed is profile_rules.check_max_speed and robotfile.FormatError is profile_rules.FormatError)

finish("test_robotfile")
