"""The duck's profile (RFC-0020): robots/duck/profile.json, validated by runfile.profile and read for the environment a run is in.

    from duck_lab.profile import load
    p = load("sim")                       # the simulator; "real" is the duck itself
    p = load("sim", path)                 # another version: a file, or a store folder (its current version), as the runner hands it
    p.locomotion.cruise_mps
    p.meta                                # where it came from: {source, path, checksum, version}

The navigator reads every number of its robot from here, not from constants in its modules."""

import json
from pathlib import Path

from runfile.profile import Profile, checksum, merge_variant, validate_profile
from runfile.profilestore import resolve, version_of  # noqa: F401 - version_of: the duck's name for it

PROFILE = Path(__file__).resolve().parents[2] / "profile.json"
SIM, REAL = "sim", "real"


def load(variant: str | None = SIM, path=None) -> Profile:
    """The duck's profile in one environment, from the repository's file or the one given. None is the real duck: what a navigator
    built with no calibration file was. `meta` says which file, its checksum (its identity) and its stored version, if any."""
    p = resolve(Path(path)) if path else PROFILE         # a store folder: its current version, read now (each run reads it again)
    raw = validate_profile(json.loads(p.read_text()))
    profile = Profile(merge_variant(raw, variant or REAL), variant or REAL)
    profile.meta = {"source": "given" if path else "repository", "path": str(p), "checksum": checksum(raw),
                    "version": version_of(p) if path else None, "profile_version": raw["profile_version"]}
    return profile
