"""The robots this runner can run (RFC-0022): each robot is registered by a registration file the installation names
(`robots.<name>.registration`), else by its package's module in the entry-point group `robotics_lab.robots`; either names its
profile, its navigator's commands and its simulator files. The runner finds a robot by name and never imports its navigator.
The registry itself is runfile.registry, which Mission Control reads too.

    robots.select("duck")       # a command's --robot; with one robot registered it is the default
    r = robots.get()            # r.NAME, r.PROFILE, r.PAYLOAD, r.NAVIGATOR_API, r.SIM (robots.sim_dir(): None refused)
    robots.profile("sim")       # its profile in an environment: the version this machine runs (profile_file), with .meta

A robot's module: NAME (str), PROFILE (the profile's path), PAYLOAD and NAVIGATOR_API (commands, lists), SIM (the folder of
its simulator's files: the apartment's layout, objects and phase 1's goals for the duck)."""

from __future__ import annotations

from pathlib import Path

from runfile import registry
from runfile.profile import load_profile
from runfile.profilestore import describe
from runfile.registry import GROUP, ProfileSourceError, names, profile_source  # noqa: F401 - the runner's names for them

_selected: str | None = None
_resolved: dict = {}


def select(name: str | None) -> None:
    """The robot the commands of this process run (their --robot)."""
    global _selected
    if name is not None and name not in names():
        raise SystemExit(f"no robot {name!r} registered here (group {GROUP}); registered: {', '.join(names()) or 'none'}")
    _selected = name


def navigator_command(kind: str, name: str | None = None) -> list:
    """The robot's navigator command, `kind` NAVIGATOR_API or PAYLOAD. A robot registered with none (the NXT: it is driven by hand and
    its registration names no navigator) is refused here, in one line naming it, instead of failing later on `list(None)`."""
    r = get(name)
    command = getattr(r, kind)
    if command is None:
        raise SystemExit(f"robot {r.NAME!r} has no navigator API (its registration names no {kind.lower()}): this command runs a "
                         f"navigator, and this robot is driven by hand")
    return list(command)


def get(name: str | None = None):
    """A robot's module: the one named, else the one selected, else the only one registered."""
    name = name or _selected
    if name is None:
        known = names()
        if len(known) != 1:
            raise SystemExit(f"which robot? give --robot (registered: {', '.join(known) or 'none'})")
        name = known[0]
    try:
        return registry.module(name)
    except LookupError as e:
        raise SystemExit(str(e)) from None


def sim_dir(name: str | None = None) -> Path:
    """The robot's simulator files (the apartment's layout and objects, phase 1's goals); a robot registered with none cannot run
    the runner's courses, which are in the simulator: said, naming the robot."""
    r = get(name)
    if r.SIM is None:
        raise SystemExit(f"robot {r.NAME!r} has no simulator files (its registration names no sim): the runner's courses run in "
                         f"the simulator")
    return Path(r.SIM)


def gate_socket(host, name: str | None = None) -> Path:
    """The robot's gate socket, from one source (the second review's finding 5): the installation's `robots.<name>.gate` when it
    names one, which is where Mission Control reads it, else the host file's. lab-gate listens there and lab-nav-server drives through
    it, so the gate, the runner and Mission Control meet at one path; a stale second copy can no longer send a STOP elsewhere."""
    from runfile import installation
    inst = installation.load(required=False)
    r = inst.robot(get(name).NAME) if inst is not None else None
    return r.gate if r is not None and r.gate is not None else Path(host.sockets["gate"])


def variant(host, name: str | None = None) -> str:
    """The profile variant this machine runs the robot in, for its navigator and its referee alike: the installation's
    `robots.<name>.variant`, else `sim` on a host with a truth and `real`, the base profile, on one with none."""
    return registry.variant(get(name).NAME, "sim" if host.truth_port is not None else "real")


def _resolve(name: str | None) -> tuple:
    """(the installation's source or None, the file) for a robot, resolved once in this process."""
    name = get(name).NAME
    if name not in _resolved:
        _resolved[name] = (registry.profile_source(name), registry.profile_file(name))
    return _resolved[name]


def profile_file(name: str | None = None) -> Path:
    """The one profile file this process judges the robot by and hands its navigator (phase 5 step 1, the operator's decision e):
    the installation's (a store folder's current version) else the robot's own, resolved at the first call and the same after,
    so a course's referee and its navigator read one version. lab-nav-server, which runs many goals, reads it again per goal."""
    return _resolve(name)[1]


def given_profile(name: str | None = None) -> Path:
    """The file to hand the robot's navigator as --profile: profile_file, the installation's or the registration's, so the navigator
    never reads a default of its own that may part from the referee's."""
    return _resolve(name)[1]


def read_profile(path, variant: str | None = "sim"):
    """A profile file in one environment, with `meta` {path, checksum, version}: what a run records the referee judged by."""
    p = load_profile(path, variant or "real")
    p.meta = describe(path)
    return p


def profile(variant: str | None = "sim", name: str | None = None):
    """A robot's profile in one environment ("sim", or "real" / None for the robot itself), from profile_file."""
    return read_profile(profile_file(name), variant)


def add_robot_arg(ap) -> None:
    ap.add_argument("--robot", help="the robot to run, by its registered name (default: the only one registered)")
