"""The duck's profile (RFC-0020): robots/duck/profile.json, validated by runfile.profile and read for the environment a run is in.

    from duck_lab.profile import load
    p = load("sim")                       # the simulator; "real" is the duck itself
    p.locomotion.cruise_mps

The navigator reads every number of its robot from here, not from constants in its modules."""

from pathlib import Path

from runfile.profile import Profile, load_profile

PROFILE = Path(__file__).resolve().parents[2] / "profile.json"
SIM, REAL = "sim", "real"


def load(variant: str | None = SIM) -> Profile:
    """The duck's profile in one environment. None is the real duck: what a navigator built with no calibration file was."""
    return load_profile(PROFILE, variant or REAL)
