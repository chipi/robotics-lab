"""The host file (RFC-0021 §3): what one machine that runs Pollen's simulator provides, so nothing of this machine is a
default in the navigator. One JSON file per machine, written once (`simhost init`, or the setup script):

    {"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a",
     "pollen": {"microduck": "/work/pollen/microduck", "microduck_rl": "/work/pollen/microduck_rl"},
     "state": "~/.cache/duck-sim", "truth_port": 7801, "cargo_bin": "~/.cargo/bin"}

`state` is duck-sim's own folder: the robot's sockets are `<robot>.sock`, `<robot>-tof.sock`, `<robot>-map.sock`,
the gate's `<robot>-gate.sock` and the camera's `<robot>-camera.sock` there, unless `sockets` names one (keys robot, depth,
map, gate, camera; the camera is served by the runner, RFC-0021 step 6). `truth_port` is the
body server's (the judge's only); null on a host with no truth (the real duck behind its forwarded sockets).

The host file above is the duck's (`pollen-duck-sim`). Its `kind` picks the reader (kinds.KINDS); the other kind,
`nxt-kinematic-sim` (nxt-web --sim, no Pollen keys), is read into an NxtHost (docs/wip/NXT-D0.md):

    {"host": 1, "kind": "nxt-kinematic-sim", "robot": "nxt-1", "state": "~/.cache/nxt-sim",
     "nxt_web": {"url": "http://127.0.0.1:8000", "project": "/work/robotics-lab/apps/nxt-web"},
     "scene": "scenes/apartment/scene.json", "start": [0, 0, 0], "params": null}

`start` is x, y in metres and yaw in radians (the truth's unit); `project` is where `.venv/bin/nxt-web` is. The optional
`takeover_names` is a file of client names (one per line) that may take the control lock from its holder, passed to nxt-web as
`--takeover-names`; absent or null: nobody may.

Where it is read from: `--host` where a command takes one, else $ROBOTICS_LAB_HOST, else
~/.config/robotics-lab/host.json. A missing or wrong file is an error that says which file and why; there is no
fallback to this workstation's paths."""

from __future__ import annotations

import json
import math
import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
ENV = "ROBOTICS_LAB_HOST"
DEFAULT = Path("~/.config/robotics-lab/host.json")
SOCKETS = {"robot": "{robot}.sock", "depth": "{robot}-tof.sock", "map": "{robot}-map.sock", "gate": "{robot}-gate.sock",
           "camera": "{robot}-camera.sock"}
KEYS = {"host", "kind", "robot", "pollen", "state", "truth_port", "cargo_bin", "sockets"}
NXT_KEYS = {"host", "kind", "robot", "state", "nxt_web", "scene", "start", "params", "takeover_names"}


class HostError(ValueError):
    """The host file is missing or does not describe a host."""


def _path(v) -> Path:
    return Path(os.path.expanduser(str(v)))


@dataclass(frozen=True)
class Host:
    source: Path
    kind: str
    robot: str
    microduck: Path
    microduck_rl: Path
    state: Path
    truth_port: int | None
    cargo_bin: Path
    sockets: dict = field(default_factory=dict)     # robot, depth, map, gate, camera -> Path

    @property
    def scenarios(self) -> Path:
        """Where challenge scenes are written for the simulator to load."""
        return self.state / "scenarios"

    @property
    def scene_dir(self) -> Path:
        """Pollen's robot folder: the scene files a challenge scene is built from."""
        return self.microduck_rl / "src" / "mjlab_microduck" / "robot" / "microduck"

    def as_json(self) -> dict:
        return {"host": VERSION, "kind": self.kind, "robot": self.robot,
                "pollen": {"microduck": str(self.microduck), "microduck_rl": str(self.microduck_rl)},
                "state": str(self.state), "truth_port": self.truth_port, "cargo_bin": str(self.cargo_bin),
                "sockets": {k: str(v) for k, v in self.sockets.items()}}


@dataclass(frozen=True)
class NxtHost:
    """The host of `nxt-kinematic-sim`: nxt-web run with --sim (apps/nxt-web), nothing of Pollen's. A caller that reaches for
    a duck field (microduck, sockets, scenarios) gets an AttributeError at once, not a wrong path."""
    source: Path
    kind: str
    robot: str
    state: Path             # where our restart keeps nxt-web's pid file and log
    url: str                # nxt-web's own address: its API, and the truth (/api/sim/truth)
    project: Path           # apps/nxt-web: <project>/.venv/bin/nxt-web is what is started
    scene: Path             # scene.json for --world
    start: tuple            # x, y, yaw: metres, metres, radians (the unit of the truth's pose)
    params: Path | None     # JSON overriding nxt_lab.world.WorldParams, or None
    takeover_names: Path | None = None      # nxt-web's --takeover-names file, or None: nobody may take the lock

    @property
    def truth_port(self) -> int:
        """nxt-web's port: its truth is served there. Never None: this kind has no host without a truth."""
        return urllib.parse.urlsplit(self.url).port

    def connections(self) -> dict:
        return {"nxt-web": self.url}

    def as_json(self) -> dict:
        return {"host": VERSION, "kind": self.kind, "robot": self.robot, "state": str(self.state),
                "nxt_web": {"url": self.url, "project": str(self.project)}, "scene": str(self.scene),
                "start": list(self.start), "params": None if self.params is None else str(self.params),
                "takeover_names": None if self.takeover_names is None else str(self.takeover_names)}


def where(path: str | Path | None = None) -> Path:
    """The host file this process reads: the one given, else $ROBOTICS_LAB_HOST, else the default."""
    if path:
        return _path(path)
    return _path(os.environ.get(ENV) or DEFAULT)


def parse(d: dict, source: Path):
    """The host a file describes: its `kind` picks the reader (kinds.KINDS), which knows that kind's keys."""
    from simhost.kinds import KINDS     # kinds imports this module: the table is read when a file is, not at import

    if not isinstance(d, dict):
        raise HostError(f"{source}: not a JSON object")
    if d.get("host") != VERSION:
        raise HostError(f"{source}: 'host' is {d.get('host')!r}, this reader knows version {VERSION}")
    if d.get("kind") not in KINDS:
        raise HostError(f"{source}: 'kind' is {d.get('kind')!r}, known: {list(KINDS)}")
    return KINDS[d["kind"]].parse(d, source)


def _robot(d: dict, bad) -> str:
    robot = d.get("robot")
    if not isinstance(robot, str) or not robot or "/" in robot:
        raise bad(f"'robot' must be a name like duck-a, not {robot!r}")
    return robot


def parse_nxt(d: dict, source: Path) -> NxtHost:
    def bad(why: str) -> HostError:
        return HostError(f"{source}: {why}")

    extra = set(d) - NXT_KEYS
    if extra:
        raise bad(f"unknown keys {sorted(extra)} for kind {d['kind']!r} (known: {sorted(NXT_KEYS)})")
    robot = _robot(d, bad)
    if not isinstance(d.get("state"), str) or not d["state"]:
        raise bad("'state' must be a path")
    web = d.get("nxt_web")
    if not isinstance(web, dict) or set(web) != {"url", "project"} or not all(isinstance(v, str) and v for v in web.values()):
        raise bad("'nxt_web' must be {\"url\": nxt-web's address, \"project\": the apps/nxt-web checkout}")
    try:
        url = urllib.parse.urlsplit(web["url"])
        port = url.port
    except ValueError:
        url, port = None, None
    if url is None or url.scheme != "http" or not url.hostname or not port or url.path not in ("", "/"):
        raise bad(f"'nxt_web.url' must be like http://127.0.0.1:8000, not {web['url']!r}")
    if not isinstance(d.get("scene"), str) or not d["scene"]:
        raise bad("'scene' must be the path of the scene.json nxt-web drives in")
    start = d.get("start")
    if not isinstance(start, list) or len(start) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in start):
        raise bad(f"'start' must be [x, y, yaw] in metres and radians, not {start!r}")
    params = d.get("params")
    if params is not None and (not isinstance(params, str) or not params):
        raise bad("'params' must be a path or null")
    names = d.get("takeover_names")
    if names is not None and (not isinstance(names, str) or not names):
        raise bad("'takeover_names' must be a path or null")
    return NxtHost(source, d["kind"], robot, _path(d["state"]), f"http://{url.hostname}:{port}", _path(web["project"]),
                   _path(d["scene"]), tuple(float(v) for v in start), None if params is None else _path(params),
                   None if names is None else _path(names))


def parse_duck(d: dict, source: Path) -> Host:
    def bad(why: str) -> HostError:
        return HostError(f"{source}: {why}")

    extra = set(d) - KEYS
    if extra:
        raise bad(f"unknown keys {sorted(extra)} (known: {sorted(KEYS)})")
    robot = _robot(d, bad)
    pollen = d.get("pollen")
    if not isinstance(pollen, dict) or set(pollen) != {"microduck", "microduck_rl"} or \
            not all(isinstance(v, str) and v for v in pollen.values()):
        raise bad("'pollen' must name the two checkouts: {\"microduck\": path, \"microduck_rl\": path}")
    for k in ("state", "cargo_bin"):
        if not isinstance(d.get(k), str) or not d[k]:
            raise bad(f"'{k}' must be a path")
    port = d.get("truth_port")
    if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536):
        raise bad(f"'truth_port' must be a port number or null, not {port!r}")
    named = d.get("sockets") or {}
    if not isinstance(named, dict) or set(named) - set(SOCKETS) or not all(isinstance(v, str) and v for v in named.values()):
        raise bad(f"'sockets' may name only {sorted(SOCKETS)}, each a path")
    state = _path(d["state"])
    sockets = {k: _path(named[k]) if k in named else state / pattern.format(robot=robot) for k, pattern in SOCKETS.items()}
    return Host(source, d["kind"], robot, _path(pollen["microduck"]), _path(pollen["microduck_rl"]), state, port,
                _path(d["cargo_bin"]), sockets)


def load(path: str | Path | None = None):
    """The host this process runs on (see `where`). Raises HostError when the file is missing or wrong."""
    p = where(path)
    try:
        text = p.read_text()
    except FileNotFoundError:
        raise HostError(f"{p}: no host file. Write one for this machine: simhost init (RFC-0021 §4), "
                        f"or point ${ENV} at one") from None
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise HostError(f"{p}: not JSON ({e})") from None
    return parse(d, p)
