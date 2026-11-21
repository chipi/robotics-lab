"""The robots this runner can run (RFC-0022): each robot's package registers one small module in the entry-point group
`robotics_lab.robots`, which names its profile, its navigator's commands and its simulator files. The runner finds a robot
by name and never imports its navigator.

    robots.select("duck")       # a command's --robot; with one robot registered it is the default
    r = robots.get()            # r.NAME, r.PROFILE, r.PAYLOAD, r.NAVIGATOR_API, r.SIM
    robots.profile("sim")       # its profile in an environment (runfile.profile)

A robot's module: NAME (str), PROFILE (the profile's path), PAYLOAD and NAVIGATOR_API (commands, lists), SIM (the folder of
its simulator's files: the apartment's layout, objects and phase 1's goals for the duck)."""

from __future__ import annotations

from importlib.metadata import entry_points

from runfile.profile import load_profile

GROUP = "robotics_lab.robots"
_selected: str | None = None


def names() -> list:
    """The robots registered on this machine."""
    return sorted(ep.name for ep in entry_points(group=GROUP))


def select(name: str | None) -> None:
    """The robot the commands of this process run (their --robot)."""
    global _selected
    if name is not None and name not in names():
        raise SystemExit(f"no robot {name!r} registered here (group {GROUP}); registered: {', '.join(names()) or 'none'}")
    _selected = name


def get(name: str | None = None):
    """A robot's module: the one named, else the one selected, else the only one registered."""
    name = name or _selected
    if name is None:
        known = names()
        if len(known) != 1:
            raise SystemExit(f"which robot? give --robot (registered: {', '.join(known) or 'none'})")
        name = known[0]
    found = [ep for ep in entry_points(group=GROUP) if ep.name == name]
    if not found:
        raise SystemExit(f"no robot {name!r} registered here (group {GROUP}); registered: {', '.join(names()) or 'none'}")
    return found[0].load()


def profile(variant: str | None = "sim", name: str | None = None):
    """A robot's profile in one environment ("sim", or "real" / None for the robot itself)."""
    return load_profile(get(name).PROFILE, variant or "real")


def add_robot_arg(ap) -> None:
    ap.add_argument("--robot", help="the robot to run, by its registered name (default: the only one registered)")
