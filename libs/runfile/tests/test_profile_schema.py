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

check.done()
