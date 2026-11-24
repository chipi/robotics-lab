"""A profile's schema rules that phase 5 added (step 1, the architecture review of 2026-11-22): the checksum (its identity across
machines), the schema-version policy (older versions migrated, never refused; newer refused), the `joints` and `subsystems`
blocks, and the profile holding no machine's addresses. A small profile of its own, no robot's package.
Run: cd libs/runfile && uv run python tests/test_profile_schema.py"""

import copy
import hashlib
import json

from helpers import Checks
from runfile import profile as P
from runfile.profile import FormatError, canonical, checksum, upgrade, validate_profile

check = Checks("PROFILE SCHEMA")

BASE = {
    "profile_version": 1, "id": "rover", "label": "A test rover", "kind": "rover",
    "factsheet": {"typeSpecification": {"seriesName": "Rover", "mobileRobotKinematics": "DIFFERENTIAL"},
                  "physicalParameters": {"maximumSpeed": 0.5, "maximumAngularSpeed": 2.0}},
    "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": []},
    "footprint": {"radius_m": 0.1, "height_m": 0.2},
    "locomotion": {"cruise_mps": 0.3},
    "plugins": {"locomotion": "wheels@1"},
    "joints": {"names": ["left_wheel", "right_wheel"]},
    "subsystems": [{"name": "base", "what": "the motor board", "check": {"kind": "socket", "socket": "robot"}},
                   {"name": "camera", "check": {"kind": "none"}}],
    "variants": {"sim": {}, "real": {}},
}


def refused(raw, why):
    try:
        validate_profile(raw)
    except FormatError as e:
        return why in str(e), str(e)
    return False, "accepted"


check("the small profile validates", validate_profile(copy.deepcopy(BASE)) is not None)

# the checksum
a = checksum(copy.deepcopy(BASE))
reordered = json.loads(json.dumps(BASE, sort_keys=True))
check("the checksum is the canonical JSON's sha256, written sha256:<hex>", a.startswith("sha256:") and len(a) == 71, a)
check("key order and spacing do not change it", checksum(reordered) == a)
same_number = copy.deepcopy(BASE)
same_number["locomotion"]["cruise_mps"] = 0.30
check("0.30 and 0.3 are one number: one checksum", checksum(same_number) == a)
changed = copy.deepcopy(BASE)
changed["locomotion"]["cruise_mps"] = 0.31
check("any changed value changes it", checksum(changed) != a)
check("the canonical text has no spaces and sorted keys", ", " not in canonical(BASE) and canonical(BASE).startswith('{"control"'))
for name, edit in (("label", lambda p: p.__setitem__("label", "Another rover")),
                   ("measured", lambda p: p["locomotion"].update(cruise_mps=0.3, measured="2026-11-22, a tape")),
                   ("why", lambda p: p["locomotion"].update(why="the walk's own"))):
    noted = copy.deepcopy(BASE)
    edit(noted)
    check(f"a changed {name} changes it too (a note is part of the identity)", checksum(noted) != a)

# schema versions
newer = copy.deepcopy(BASE)
newer["profile_version"] = P.PROFILE_VERSION + 1
ok, why = refused(newer, "and older")
check("a profile newer than the reader is refused, saying which it knows", ok, why)
for bad in (0, "1", True, None, 1.0):
    b = copy.deepcopy(BASE)
    b["profile_version"] = bad
    ok, why = refused(b, "whole number from 1")
    check(f"profile_version {bad!r} is refused", ok, why)

# an older one is migrated, never refused: pretend this reader is at version 2 with a migration from 1
saved_version, saved_migrations = P.PROFILE_VERSION, dict(P.MIGRATIONS)
try:
    P.PROFILE_VERSION = 2

    def one_to_two(p):
        p["profile_version"] = 2
        p["label"] = p["label"] + " (migrated)"
        return p
    P.MIGRATIONS[1] = one_to_two
    old = copy.deepcopy(BASE)
    up = validate_profile(old)
    check("a version-1 profile read by a version-2 reader is migrated, not refused", up["profile_version"] == 2
          and up["label"].endswith("(migrated)"), up["label"])
    check("the migration works on a copy: the stored profile is untouched", old["profile_version"] == 1 and "migrated" not in old["label"])
    as_stored = "sha256:" + hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    check("must fail: the checksum is the file as stored (version 1), not as migrated: a newer reader keeps its identity "
          "(the operator's decision b)", checksum(copy.deepcopy(old)) == as_stored == a, (checksum(old), as_stored, a))
    P.MIGRATIONS.clear()
    ok, why = refused(copy.deepcopy(BASE), "no migration from it")
    check("an older version with no migration registered is an error that says so", ok, why)

    def wrong(p):
        return p                                  # forgot to raise the version
    P.MIGRATIONS[1] = wrong
    ok, why = refused(copy.deepcopy(BASE), "the migration from version 1 left")
    check("a migration that does not raise the version is caught", ok, why)
finally:
    P.PROFILE_VERSION = saved_version
    P.MIGRATIONS.clear()
    P.MIGRATIONS.update(saved_migrations)
check("upgrade() of a current profile returns it as it is", upgrade(BASE) is BASE)

# the new blocks
for mutate, why, name in (
        (lambda p: p.__setitem__("subsystems", {"name": "x"}), "must be a list", "subsystems not a list"),
        (lambda p: p["subsystems"].append({"name": "base", "check": {"kind": "none"}}), "listed twice", "a part listed twice"),
        (lambda p: p["subsystems"][0].__setitem__("check", {"kind": "ping"}), "kind is one of", "an unknown check"),
        (lambda p: p["subsystems"][0].__setitem__("check", {"kind": "socket"}), "must name one of the machine's sockets", "a socket check with no socket"),
        (lambda p: p["subsystems"][0].__setitem__("host", "x"), "unknown fields", "an unknown field in a part"),
        (lambda p: p["joints"].__setitem__("names", "left_wheel"), "joints.names", "joint names not a list"),
        (lambda p: p.__setitem__("adapter", {"type": "x", "observatory": "http://127.0.0.1:8070"}), "unknown fields", "a machine's adapter in the profile")):
    p = copy.deepcopy(BASE)
    mutate(p)
    ok, why_ = refused(p, why)
    check(f"refused: {name}", ok, why_)

# the rules Mission Control's robot file had alone, now the profile's too (one set: a valid profile is a robot Mission Control runs)
CAPS = {"guardrails": ["max_speed"], "description": "a rover"}
for name, extra, why in (
        ("a state rate above the robot's limit", {"rates": {"state_hz": 20.0, "max_state_hz": 10.0}}, "above the robot's limit"),
        ("a rate that is not above 0", {"rates": {"map_hz": 0}}, "rates.map_hz must be a number above 0"),
        ("a capability key that is not one", {"capabilities": {**CAPS, "teleport": True}}, "capabilities keys are"),
        ("a guardrail of its own it cannot check", {"capabilities": {**CAPS, "guardrails": []},
                                                    "guardrails": [{"name": "max_speed", "mps": 0.2}]}, "not in capabilities.guardrails")):
    ok, why_ = refused({**copy.deepcopy(BASE), **extra}, why)
    check(f"refused: {name}", ok, why_)
check("rates and capabilities within the rules validate", validate_profile({**copy.deepcopy(BASE), "capabilities": CAPS,
                                                                            "guardrails": [{"name": "max_speed", "mps": 0.2}],
                                                                            "rates": {"state_hz": 5.0}}) is not None)

# --- the sensors block describes every robot (phase 5 E4): an id per sensor, a kind, a source; the duck's two named blocks unchanged ---
TOF = {"fov_deg": 45.0, "rows": 8, "cols": 8, "range_m": 3.0, "mount": {"pitch_offset_deg": 0.0, "range_kind": "perpendicular"}}
NXT = {"ultrasonic": {"kind": "range", "port": "4", "source": "nxt-web", "range_m": 2.55}, "colour": {"kind": "colour", "port": "3", "source": "nxt-web"}}
TURTLE = {"lidar": {"kind": "scan2d", "source": "ros:/scan", "frame": "base_scan", "rate_hz": 5.0, "range_m": 3.5, "fov_deg": 360.0, "samples": 360,
                    "mount": {"x_m": -0.032, "y_m": 0.0, "z_m": 0.172, "yaw_deg": 0.0}, "noise": {"range_m": 0.01}},
          "imu": {"kind": "imu", "source": "ros:/imu", "frame": "imu_link", "rate_hz": 200.0, "noise": {"gyro_rad_s": 0.001, "accel_mps2": 0.02}},
          "odom": {"kind": "odometry", "source": "ros:/odom", "rate_hz": 30.0},
          "camera": {"kind": "image", "source": "ros:/camera/image_raw", "rate_hz": 15.0, "width_px": 640, "height_px": 480, "hfov_deg": 62.0,
                     "mount": {"x_m": 0.07, "z_m": 0.1, "pitch_deg": 0.0}}}


def with_sensors(sensors, plugin="range@1", variants=None):
    p = copy.deepcopy(BASE)
    p.update(sensors=copy.deepcopy(sensors), plugins={**p["plugins"], "range_sensing": plugin})
    if variants is not None:
        p["variants"] = variants
    return p


check("the duck's shape is unchanged: tof8x8 by its own name, no kind, validates", validate_profile(with_sensors({"tof8x8": TOF})) is not None)
check("must fail: the NXT's two sensors (a range, a colour) are a sensors block, each with its id, kind, port and source",
      validate_profile(with_sensors(NXT, "nxt-ultrasonic@1"))["sensors"]["ultrasonic"]["range_m"] == 2.55)
check("must fail: a TurtleBot's lidar, IMU, odometry and camera fit with no rename: ids of the robot's own, kinds the schema names",
      sorted(validate_profile(with_sensors(TURTLE, "scan2d@1"))["sensors"]) == ["camera", "imu", "lidar", "odom"])
check("one block holds the duck's named sensor beside declared ones", validate_profile(with_sensors({"tof8x8": TOF, **NXT})) is not None)
check("must fail: a kind the schema does not know is refused, naming it", refused(with_sensors({"x": {"kind": "sonar9"}}), "sonar9")[0])
check("must fail: a field the kind does not have is refused (a scan has no `rows`)", refused(with_sensors({"lidar": {"kind": "scan2d", "rows": 8}}), "unknown fields")[0])
check("must fail: a sensor with no kind whose id is not a kind is refused", refused(with_sensors({"lidar": {"source": "ros:/scan"}}), "kind")[0])
check("must fail: a number of a sensor must be a number above 0", refused(with_sensors({"lidar": {"kind": "scan2d", "range_m": -1}}), "range_m")[0])
check("must fail: the block still needs a range_sensing plugin", refused({**with_sensors(NXT), "plugins": {"locomotion": "wheels@1"}}, "range_sensing")[0])
check("must fail: a sensor's mount is checked", refused(with_sensors({"lidar": {"kind": "scan2d", "mount": {"x_m": "left"}}}), "mount")[0])
noisy = {"sim": {"sensors": {"lidar": {"noise": {"range_m": 0.0}}}}, "real": {}}
check("must fail: a noise that differs between variants needs measured and why in the sensor's block",
      refused(with_sensors(TURTLE, "scan2d@1", noisy), "measured")[0])
noisy["sim"]["sensors"]["lidar"].update(measured="spike 2026-11", why="the Gazebo plugin's own noise is off")
check("... and with them it validates, and the merged sim lidar has the variant's noise",
      P.merge_variant(validate_profile(with_sensors(TURTLE, "scan2d@1", noisy)), "sim")["sensors"]["lidar"]["noise"] == {"range_m": 0.0})
gone = {"sim": {"sensors": {"colour": None}}, "real": {}}
v = validate_profile(with_sensors(NXT, "nxt-ultrasonic@1", gone))
check("must fail: a variant says a sensor does not exist there with null: the sim has no colour sensor, the real one has both",
      sorted(P.merge_variant(v, "sim")["sensors"]) == ["ultrasonic"] and sorted(P.merge_variant(v, "real")["sensors"]) == ["colour", "ultrasonic"])
check("must fail: null is for a variant only: the base cannot say a sensor is null", refused(with_sensors({"colour": None}), "colour")[0])
check("the sensors read by attribute as ever: profile.sensors.tof8x8.fov_deg, and a declared one by its id",
      P.Profile(P.merge_variant(validate_profile(with_sensors({"tof8x8": TOF, **NXT})), "real")).sensors.ultrasonic.port == "4")

check.done()
