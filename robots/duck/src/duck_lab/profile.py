"""The duck's profile (RFC-0020): robots/duck/profile.json, validated by runfile.profile and read for the environment a run is in.

    from duck_lab.profile import load
    p = load("sim")                       # the simulator; "real" is the duck itself
    p = load("sim", path)                 # another version of it: the one the runner hands the navigator (phase 5 step 1)
    p.locomotion.cruise_mps
    p.meta                                # where it came from: {source, path, checksum, version}

The navigator reads every number of its robot from here, not from constants in its modules."""

import json
from pathlib import Path

from runfile.profile import Profile, checksum, merge_variant, validate_profile

PROFILE = Path(__file__).resolve().parents[2] / "profile.json"
SIM, REAL = "sim", "real"


def version_of(path: Path):
    """A stored version's number from its file name (`profiles/<robot>/<n>.json`), else None."""
    return int(path.stem) if path.stem.isdigit() else None


def load(variant: str | None = SIM, path=None) -> Profile:
    """The duck's profile in one environment, from the repository's file or the one given. None is the real duck: what a navigator
    built with no calibration file was. `meta` says which file, its checksum (its identity) and its stored version, if any."""
    p = Path(path) if path else PROFILE
    raw = validate_profile(json.loads(p.read_text()))
    profile = Profile(merge_variant(raw, variant or REAL), variant or REAL)
    profile.meta = {"source": "given" if path else "repository", "path": str(p), "checksum": checksum(raw),
                    "version": version_of(p) if path else None}
    return profile
