"""The robot file's `factsheet` and `control` blocks (RFC-0014 §3.3.1, docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md, decided 2026-11-18).

The validator lives with the run format, in libs/runfile (runfile.profile, RFC-0020 step 1: the robot's profile is the robot file's
format extended, and the navigator, Mission Control and the Observatory all read it); this module re-exports it, so the robot file and
the profile share one set of rules.

`factsheet` is a subset of VDA 5050 3.0.0's factsheet with VDA's names verbatim (camelCase, SI units: metres, seconds, radians), so a
real VDA robot's factsheet can fill it by copying. Everything VDA has no field for stays ours, in snake_case, beside it (`control`,
`capabilities`, `rates`, `guardrails`, `adapter`). Two values are ours inside the factsheet and say so there: the kinematics
`LEGGED` (VDA's enum is extensible, and has no legs) and an action's `irreversible`."""

from runfile.profile import (ACTION_FIELDS, ACTION_SCOPES, BLOCKING_TYPES, CONTROL_FIELDS, DEFAULT_DEADMAN_S, DEFAULT_LEASE_S, KINEMATICS,
                             LOCALIZATION_TYPES, PHYSICAL_FIELDS, TYPE_FIELDS, FormatError, ProfileError, check_max_speed, load_profile,
                             parse_control, parse_factsheet, validate_profile)

__all__ = ["ACTION_FIELDS", "ACTION_SCOPES", "BLOCKING_TYPES", "CONTROL_FIELDS", "DEFAULT_DEADMAN_S", "DEFAULT_LEASE_S", "KINEMATICS",
           "LOCALIZATION_TYPES", "PHYSICAL_FIELDS", "TYPE_FIELDS", "FormatError", "ProfileError", "check_max_speed", "load_profile",
           "parse_control", "parse_factsheet", "validate_profile"]
