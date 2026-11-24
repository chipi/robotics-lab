"""The installation file (phase 5 step 1, RFC-0023 D9): what one machine of the lab holds that is not a robot's and not a
simulator's. The robot's profile holds only the robot; the host file (libs/simhost) holds only the simulator; this holds where this
machine keeps its runs, its state and its services, and, per robot it runs, where that robot's navigator and profile are.

    {"installation": 1,
     "data": "/work/robotics-lab/data", "index": "/work/robotics-lab/state/observatory/index.sqlite",
     "observatory": "http://127.0.0.1:8070", "state": "~/.local/state/robotics-lab",
     "robots": {"duck": {"navigator": "127.0.0.1:8061", "gate": "~/.cache/duck-sim/duck-a-gate.sock",
                         "profile": "~/.local/state/robotics-lab/profiles/duck",
                         "registration": "/work/robotics-lab/main/robots/duck/registration.json", "variant": "sim"}}}

A robot whose software runs beside a connector over its own link (the NXT behind nxt-web) also names `placement` (where this machine
runs it: one of its registration's `placements`) and `connections`, the address of each connector ("nxt-web": a URL), so Mission
Control never assumes a localhost; a sensor in the robot's profile names the connection it comes from.

`telemetry` (absent: off) names the `environment` and the OTLP/HTTP URL of each signal; `runs.archive_after_days` (default 30) is
`observatory archive`'s age (docs/wip/TELEMETRY-RETENTION-DESIGN.md).

Robots are keyed by their registered name: a `registration` file named here (runfile.registry; the operator's decision a), else
the entry point `robotics_lab.robots` of a package installed beside the reader. Every key but `installation` is
optional; a machine running no robot has `robots: {}`. Read from `--installation` where a command takes one, else
$ROBOTICS_LAB_INSTALLATION, else ~/.config/robotics-lab/installation.json. A missing or wrong file is an error naming the file and
what is wrong; unknown keys are errors. Standard library only: every part of the lab may read it."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
ENV = "ROBOTICS_LAB_INSTALLATION"
DEFAULT = Path("~/.config/robotics-lab/installation.json")
KEYS = {"installation", "data", "index", "observatory", "state", "robots", "telemetry", "runs"}
TELEMETRY_KEYS = {"environment", "traces", "metrics", "logs", "metrics_interval_s"}
SIGNALS = ("traces", "metrics", "logs")
RUNS_KEYS = {"archive_after_days"}
ARCHIVE_AFTER_DAYS = 30
METRICS_INTERVAL_S = 15
ROBOT_KEYS = {"navigator", "gate", "profile", "registration", "variant", "placement", "connections"}


class InstallationError(ValueError):
    """The installation file is missing or does not describe an installation."""


class NotNamed(LookupError):
    """A folder or file this machine must name (by a variable or in the installation file) and names nowhere; the message says where
    to name it. A library raises it; a command turns it into its exit message."""


def _path(v) -> Path:
    return Path(os.path.expanduser(str(v)))


@dataclass(frozen=True)
class Robot:
    name: str
    navigator: str | None = None          # host:port of the robot's navigator API (Mission Control's address for it)
    gate: Path | None = None              # the socket of the robot's gate (RFC-0017): Mission Control's way to the robot
    profile: Path | None = None           # the profile version this machine runs; None: the robot's own (repository) profile
    registration: Path | None = None      # the robot's registration file (runfile.registry); None: its package's entry point
    variant: str | None = None            # the profile variant this machine runs it in (sim, real); None: sim with a truth, else real
    placement: str | None = None          # where this machine runs the robot's software (one of its registration's placements)
    connections: dict = field(default_factory=dict)   # connection name -> URL of the robot's connector here (nxt-web); sensors name theirs


@dataclass(frozen=True)
class Telemetry:
    environment: str                      # deployment.environment.name: dev, prod, check
    traces: str | None = None             # each signal's OTLP/HTTP (protobuf) URL, used as given; None: that signal is off
    metrics: str | None = None
    logs: str | None = None
    metrics_interval_s: int = METRICS_INTERVAL_S


@dataclass(frozen=True)
class Installation:
    source: Path
    data: Path | None = None
    index: Path | None = None
    observatory: str | None = None
    state: Path | None = None
    robots: dict = field(default_factory=dict)          # name -> Robot
    telemetry: Telemetry | None = None                  # None: telemetry is off
    archive_after_days: int = ARCHIVE_AFTER_DAYS        # `observatory archive`: runs younger than this stay

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
        reg = r.get("registration")
        if reg is not None and not (isinstance(reg, str) and reg):
            raise bad(f"robots.{name}.registration must be the path of the robot's registration file")
        variant = r.get("variant")
        if variant is not None and not (isinstance(variant, str) and variant):
            raise bad(f"robots.{name}.variant must be the name of a profile variant, like sim or real")
        placement = r.get("placement")
        if placement is not None and not (isinstance(placement, str) and placement):
            raise bad(f"robots.{name}.placement must be a name, like workstation")
        conns = r.get("connections", {})
        if not isinstance(conns, dict):
            raise bad(f"robots.{name}.connections must be an object of connection name: URL")
        for cname, url in conns.items():
            if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                raise bad(f"robots.{name}.connections.{cname} must be an http(s) URL, not {url!r}")
        robots[name] = Robot(name, nav, _path(gate) if gate else None, _path(prof) if prof else None,
                             _path(reg) if reg else None, variant, placement, dict(conns))
    telemetry = _telemetry(d["telemetry"], bad) if "telemetry" in d else None
    after = ARCHIVE_AFTER_DAYS
    if "runs" in d:
        runs = d["runs"]
        if not isinstance(runs, dict):
            raise bad("'runs' must be an object")
        extra = set(runs) - RUNS_KEYS
        if extra:
            raise bad(f"runs: unknown keys {sorted(extra)} (known: {sorted(RUNS_KEYS)})")
        after = runs.get("archive_after_days", after)
        if not (isinstance(after, int) and not isinstance(after, bool) and after >= 1):
            raise bad(f"runs.archive_after_days must be an integer of 1 or more, not {after!r}")
    return Installation(source, _path(d["data"]) if "data" in d else None, _path(d["index"]) if "index" in d else None,
                        d.get("observatory"), _path(d["state"]) if "state" in d else None, robots, telemetry, after)


def _telemetry(t, bad) -> Telemetry:
    if not isinstance(t, dict):
        raise bad("'telemetry' must be an object")
    extra = set(t) - TELEMETRY_KEYS
    if extra:
        raise bad(f"telemetry: unknown keys {sorted(extra)} (known: {sorted(TELEMETRY_KEYS)})")
    if "environment" not in t:
        raise bad("telemetry: needs 'environment' (like dev) and at least one of 'traces', 'metrics', 'logs'; leave the block out to keep telemetry off")
    env = t["environment"]
    if not (isinstance(env, str) and re.fullmatch(r"[a-z0-9_-]+", env)):
        raise bad(f"telemetry.environment must match ^[a-z0-9_-]+$, not {env!r}")
    for k in SIGNALS:
        if k in t and not (isinstance(t[k], str) and re.match(r"https?://[^/\s]+", t[k])):
            raise bad(f"telemetry.{k} must be an http(s) URL, not {t[k]!r}")
    if not any(k in t for k in SIGNALS):
        raise bad("telemetry: needs at least one of 'traces', 'metrics', 'logs'")
    n = t.get("metrics_interval_s", METRICS_INTERVAL_S)
    if not (isinstance(n, int) and not isinstance(n, bool) and 5 <= n <= 300):
        raise bad(f"telemetry.metrics_interval_s must be an integer from 5 to 300, not {n!r}")
    return Telemetry(env, t.get("traces"), t.get("metrics"), t.get("logs"), n)


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
