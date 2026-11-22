"""The installation file (phase 5 step 1, RFC-0023 D9): what one machine of the lab holds that is not a robot's and not a
simulator's. The robot's profile holds only the robot; the host file (libs/simhost) holds only the simulator; this holds where this
machine keeps its runs, its state and its services, and, per robot it runs, where that robot's navigator and profile are.

    {"installation": 1,
     "data": "/work/robotics-lab/data", "index": "/work/robotics-lab/state/observatory/index.sqlite",
     "observatory": "http://127.0.0.1:8070", "state": "~/.local/state/robotics-lab",
     "robots": {"duck": {"navigator": "127.0.0.1:8061", "gate": "~/.cache/duck-sim/duck-a-gate.sock",
                         "map": "~/.cache/duck-sim/duck-a-map.sock",
                         "profile": "~/.local/state/robotics-lab/profiles/duck"}}}

Robots are keyed by their registered name (the entry point `robotics_lab.robots`, labrunner.robots). Every key but `installation` is
optional; a machine running no robot has `robots: {}`. Read from `--installation` where a command takes one, else
$ROBOTICS_LAB_INSTALLATION, else ~/.config/robotics-lab/installation.json. A missing or wrong file is an error naming the file and
what is wrong; unknown keys are errors. Standard library only: every part of the lab may read it."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
ENV = "ROBOTICS_LAB_INSTALLATION"
DEFAULT = Path("~/.config/robotics-lab/installation.json")
KEYS = {"installation", "data", "index", "observatory", "state", "robots"}
ROBOT_KEYS = {"navigator", "gate", "map", "profile"}


class InstallationError(ValueError):
    """The installation file is missing or does not describe an installation."""


def _path(v) -> Path:
    return Path(os.path.expanduser(str(v)))


@dataclass(frozen=True)
class Robot:
    name: str
    navigator: str | None = None          # host:port of the robot's navigator API (Mission Control's address for it)
    gate: Path | None = None              # the socket of the robot's gate (RFC-0017): Mission Control's way to the robot
    profile: Path | None = None           # the profile version this machine runs; None: the robot's own (repository) profile
    map: Path | None = None               # the socket of the robot's map (mapd), read by Mission Control itself; None: via the navigator API


@dataclass(frozen=True)
class Installation:
    source: Path
    data: Path | None = None
    index: Path | None = None
    observatory: str | None = None
    state: Path | None = None
    robots: dict = field(default_factory=dict)          # name -> Robot

    def robot(self, name: str) -> Robot | None:
        return self.robots.get(name)


def where(path: str | Path | None = None) -> Path:
    """The installation file this process reads: the one given, else $ROBOTICS_LAB_INSTALLATION, else the default."""
    if path:
        return _path(path)
    return _path(os.environ.get(ENV) or DEFAULT)


def parse(d, source: Path) -> Installation:
    def bad(why: str) -> InstallationError:
        return InstallationError(f"{source}: {why}")

    if not isinstance(d, dict):
        raise bad("not a JSON object")
    extra = set(d) - KEYS
    if extra:
        raise bad(f"unknown keys {sorted(extra)} (known: {sorted(KEYS)})")
    if d.get("installation") != VERSION:
        raise bad(f"'installation' is {d.get('installation')!r}, this reader knows version {VERSION}")
    for k in ("data", "index", "state", "observatory"):
        if k in d and not (isinstance(d[k], str) and d[k]):
            raise bad(f"'{k}' must be a non-empty string")
    if "observatory" in d and not d["observatory"].startswith(("http://", "https://")):
        raise bad(f"'observatory' must be an http(s) URL, not {d['observatory']!r}")
    robots_raw = d.get("robots", {})
    if not isinstance(robots_raw, dict):
        raise bad("'robots' must be an object of robot name: settings")
    robots = {}
    for name, r in robots_raw.items():
        if not (isinstance(name, str) and name and "/" not in name):
            raise bad(f"robot name {name!r} must be a registered robot's name, like duck")
        if not isinstance(r, dict):
            raise bad(f"robots.{name} must be an object")
        extra = set(r) - ROBOT_KEYS
        if extra:
            raise bad(f"robots.{name}: unknown keys {sorted(extra)} (known: {sorted(ROBOT_KEYS)})")
        nav = r.get("navigator")
        if nav is not None and not (isinstance(nav, str) and nav.rpartition(":")[2].isdigit()):
            raise bad(f"robots.{name}.navigator must be host:port, not {nav!r}")
        gate = r.get("gate")
        if gate is not None and not (isinstance(gate, str) and gate):
            raise bad(f"robots.{name}.gate must be the path of the gate's socket")
        prof = r.get("profile")
        if prof is not None and not (isinstance(prof, str) and prof):
            raise bad(f"robots.{name}.profile must be a path")
        mapd = r.get("map")
        if mapd is not None and not (isinstance(mapd, str) and mapd):
            raise bad(f"robots.{name}.map must be the path of the map's socket (mapd)")
        robots[name] = Robot(name, nav, _path(gate) if gate else None, _path(prof) if prof else None,
                             map=_path(mapd) if mapd else None)
    return Installation(source, _path(d["data"]) if "data" in d else None, _path(d["index"]) if "index" in d else None,
                        d.get("observatory"), _path(d["state"]) if "state" in d else None, robots)


def load(path: str | Path | None = None, required: bool = True) -> Installation | None:
    """The installation this process runs in (see `where`). A missing file raises InstallationError, or, with required=False,
    returns None (a machine not set up yet keeps today's defaults)."""
    p = where(path)
    try:
        text = p.read_text()
    except FileNotFoundError:
        if not required:
            return None
        raise InstallationError(f"{p}: no installation file. Write one for this machine (docs/wip/PHASE5-STEP1-DESIGN.md), "
                                f"or point ${ENV} at one") from None
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise InstallationError(f"{p}: not JSON ({e})") from None
    return parse(d, p)
