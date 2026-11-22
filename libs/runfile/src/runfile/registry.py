"""The robots registered on this machine (RFC-0022) and which profile file each runs here (phase 5 step 1). Each robot's package
registers one small module in the entry-point group `robotics_lab.robots`: NAME, PROFILE (its own profile's path), PAYLOAD and
NAVIGATOR_API (commands), SIM (its simulator's files). The runner (labrunner.robots) and Mission Control both find a robot by name
here and never import its navigator. Standard library and runfile only."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

GROUP = "robotics_lab.robots"


class ProfileSourceError(ValueError):
    """The installation names a profile for a robot that does not exist: the robot is refused, never run on another one."""


def names() -> list:
    """The robots registered on this machine."""
    return sorted(ep.name for ep in entry_points(group=GROUP))


def module(name: str):
    """A registered robot's module; LookupError naming the registered ones when there is none by that name."""
    found = [ep for ep in entry_points(group=GROUP) if ep.name == name]
    if not found:
        raise LookupError(f"no robot {name!r} registered here (group {GROUP}); registered: {', '.join(names()) or 'none'}")
    return found[0].load()


def profile_source(name: str, inst=False) -> Path | None:
    """The profile this machine runs the robot on: the installation's `robots.<name>.profile` (a version's file, or the version
    store's folder for the robot: its current version, read again at the start of every run), or None when the installation names
    none (the robot's own file then, recorded as source: repository).

    A named profile that does not exist, or a store that cannot say its current version, raises ProfileSourceError: no silent
    fallback to the robot's own file, which would run other numbers than the operator chose while the run says nothing wrong.
    `inst`: an Installation, None for none, or False to read this machine's (runfile.installation, not required)."""
    from runfile import installation
    from runfile.profilestore import Store, StoreError
    if inst is False:
        inst = installation.load(required=False)
    r = inst.robot(name) if inst is not None else None
    if r is None or r.profile is None:
        return None
    p = r.profile
    where = f"{inst.source}: robots.{name}.profile"
    if p.is_dir():
        try:
            n = Store(p.parent).current(p.name)
        except StoreError as e:
            raise ProfileSourceError(f"{where} is the version store {p}, which cannot say its current version ({e}): refused") from None
        if n is None:
            raise ProfileSourceError(f"{where} is the version store {p}, which has no version yet: refused (seed it first)")
        return p
    if not p.is_file():
        raise ProfileSourceError(f"{where} is {p}, which does not exist: refused (no fallback to the robot's own profile)")
    return p


def profile_file(name: str, inst=False) -> Path:
    """The one profile file the robot runs now: the installation's (a store folder's current version), else the robot's own."""
    from runfile.profilestore import resolve
    src = profile_source(name, inst)
    return resolve(src) if src is not None else Path(module(name).PROFILE)
