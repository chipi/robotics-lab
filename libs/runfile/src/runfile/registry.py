"""The robots registered on this machine (RFC-0022) and which profile file each runs here (phase 5 step 1). A robot is registered
by a registration file the installation names (`robots.<name>.registration`, the operator's decision a: nothing is installed into
Mission Control or the runner to add a robot), else by its package's module in the entry-point group `robotics_lab.robots` (the
fallback for a packaged robot). Either way a robot reads as NAME, PROFILE (its own profile's path), PAYLOAD and NAVIGATOR_API
(commands), SIM (its simulator's files, or None). The runner (labrunner.robots) and Mission Control both find a robot by name here
and never import its navigator. Standard library and runfile only.

A registration file:

    {"registration": 1, "name": "duck", "profile": "profile.json",
     "payload": [".venv/bin/python", "-m", "duck_lab.payload"],
     "navigator_api": [".venv/bin/python", "-m", "duck_lab.nav.server"],
     "sim": "sim"}

Paths (the profile, sim, and a command's program when it is a relative path with a `/`) are relative to the file's folder.
`payload` and `navigator_api` are optional: a robot with no navigator (the NXT) leaves both out and reads as None. `placements` is where
the robot's software can run (RFC-0025 §3.8: "workstation" now; the Pi module adds more); omitted, it reads as an empty list."""

from __future__ import annotations

import json
import types
from importlib.metadata import entry_points
from pathlib import Path

GROUP = "robotics_lab.robots"
REGISTRATION = 1
REG_KEYS = {"registration", "name", "profile", "payload", "navigator_api", "sim", "placements"}


class ProfileSourceError(ValueError):
    """The installation names a profile for a robot that does not exist: the robot is refused, never run on another one."""


class RegistrationError(LookupError):
    """A registration file that is missing or does not describe the robot the installation names it for."""


def _inst(inst):
    if inst is False:
        from runfile import installation
        return installation.load(required=False)
    return inst


def _registered(inst) -> dict:
    """name -> registration file, for the robots the installation registers by file."""
    if inst is None:
        return {}
    return {name: r.registration for name, r in inst.robots.items() if r.registration is not None}


def load_registration(path: Path, name: str):
    """A registration file read as a robot (NAME, PROFILE, PAYLOAD, NAVIGATOR_API, SIM); RegistrationError naming the file and
    what is wrong, including a file that registers another name than the one it is named for."""
    path = Path(path)

    def bad(why: str) -> RegistrationError:
        return RegistrationError(f"{path}: {why}")

    try:
        d = json.loads(path.read_text())
    except FileNotFoundError:
        raise bad(f"no registration file (the installation names it for robot {name!r})") from None
    except json.JSONDecodeError as e:
        raise bad(f"not JSON ({e})") from None
    if not isinstance(d, dict):
        raise bad("not a JSON object")
    extra = set(d) - REG_KEYS
    if extra:
        raise bad(f"unknown keys {sorted(extra)} (known: {sorted(REG_KEYS)})")
    if d.get("registration") != REGISTRATION:
        raise bad(f"'registration' is {d.get('registration')!r}, this reader knows version {REGISTRATION}")
    if d.get("name") != name:
        raise bad(f"registers {d.get('name')!r}, but the installation names it for {name!r}")
    here = path.parent

    def rel(v) -> Path:
        p = Path(v).expanduser()
        return p if p.is_absolute() else here / p

    if not (isinstance(d.get("profile"), str) and d["profile"]):
        raise bad("'profile' must be the path of the robot's profile")
    profile = rel(d["profile"])
    if not profile.is_file():
        raise bad(f"its profile {profile} does not exist")
    commands = {}
    for k in ("payload", "navigator_api"):
        c = d.get(k)
        if k not in d:
            commands[k] = None
            continue
        if not (isinstance(c, list) and c and all(isinstance(x, str) and x for x in c)):
            raise bad(f"'{k}' must be a command: a list of non-empty strings")
        prog = c[0]
        commands[k] = [str(rel(prog)) if "/" in prog else prog] + c[1:]
    sim = d.get("sim")
    if sim is not None and not (isinstance(sim, str) and sim):
        raise bad("'sim' must be the path of the robot's simulator files")
    placements = d.get("placements", [])
    if not (isinstance(placements, list) and all(isinstance(x, str) and x for x in placements)):
        raise bad("'placements' must be a list of non-empty names, like workstation")
    return types.SimpleNamespace(NAME=name, PROFILE=profile, PAYLOAD=commands["payload"], NAVIGATOR_API=commands["navigator_api"],
                                 SIM=rel(sim) if sim else None, PLACEMENTS=placements, REGISTRATION=path)


def names(inst=False) -> list:
    """The robots registered on this machine: by the installation's registration files, and by entry point."""
    return sorted({ep.name for ep in entry_points(group=GROUP)} | set(_registered(_inst(inst))))


def module(name: str, inst=False):
    """A registered robot: its registration file when the installation names one (it wins over an entry point of the same name),
    else its package's module; LookupError naming the registered ones when there is none by that name."""
    inst = _inst(inst)
    reg = _registered(inst).get(name)
    if reg is not None:
        return load_registration(reg, name)
    found = [ep for ep in entry_points(group=GROUP) if ep.name == name]
    if not found:
        raise LookupError(f"no robot {name!r} registered here (group {GROUP}, or robots.{name}.registration in the installation); "
                          f"registered: {', '.join(names(inst)) or 'none'}")
    return found[0].load()


def profile_source(name: str, inst=False) -> Path:
    """The profile this machine runs the robot on: the installation's `robots.<name>.profile` (a version's file, or the version
    store's folder for the robot: its current version, read again at the start of every run), or when the installation names none
    the robot's own (its registration's `profile`). Always a path, so a runner always hands its navigator `--profile`: the navigator
    reads the file its referee reads, never a default of its own that may part from it. LookupError when the robot is not registered.

    A named profile that does not exist, or a store that cannot say its current version, raises ProfileSourceError: no silent
    fallback to the robot's own file, which would run other numbers than the operator chose while the run says nothing wrong.
    `inst`: an Installation, None for none, or False to read this machine's (runfile.installation, not required)."""
    from runfile.profilestore import Store, StoreError
    inst = _inst(inst)
    r = inst.robot(name) if inst is not None else None
    if r is None or r.profile is None:
        return Path(module(name, inst).PROFILE)
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


def variant(name: str, default: str, inst=False) -> str:
    """The profile variant this machine runs the robot in, from the one place it is named: the installation's
    `robots.<name>.variant`, else `default` (the reader knows its own: the runner, whether its host has a truth; Mission
    Control, its adapter)."""
    inst = _inst(inst)
    r = inst.robot(name) if inst is not None else None
    return r.variant if r is not None and r.variant is not None else default


def profile_file(name: str, inst=False) -> Path:
    """The one profile file the robot runs now: the installation's (a store folder's current version), else the robot's own."""
    from runfile.profilestore import resolve
    inst = _inst(inst)
    return resolve(profile_source(name, inst))
