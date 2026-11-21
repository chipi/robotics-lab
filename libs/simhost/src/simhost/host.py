"""The host file (RFC-0021 §3): what one machine that runs Pollen's simulator provides, so nothing of this machine is a
default in the navigator. One JSON file per machine, written once (`simhost init`, or the setup script):

    {"host": 1, "kind": "pollen-duck-sim", "robot": "duck-a",
     "pollen": {"microduck": "/work/pollen/microduck", "microduck_rl": "/work/pollen/microduck_rl"},
     "state": "~/.cache/duck-sim", "truth_port": 7801, "cargo_bin": "~/.cargo/bin"}

`state` is duck-sim's own folder: the robot's sockets are `<robot>.sock`, `<robot>-tof.sock`, `<robot>-map.sock`,
the gate's `<robot>-gate.sock` and the camera's `<robot>-camera.sock` there, unless `sockets` names one (keys robot, depth,
map, gate, camera; the camera is served by the runner, RFC-0021 step 6). `truth_port` is the
body server's (the judge's only); null on a host with no truth (the real duck behind its forwarded sockets).

Where it is read from: `--host` where a command takes one, else $ROBOTICS_LAB_HOST, else
~/.config/robotics-lab/host.json. A missing or wrong file is an error that says which file and why; there is no
fallback to this workstation's paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
KINDS = ("pollen-duck-sim",)
ENV = "ROBOTICS_LAB_HOST"
DEFAULT = Path("~/.config/robotics-lab/host.json")
SOCKETS = {"robot": "{robot}.sock", "depth": "{robot}-tof.sock", "map": "{robot}-map.sock", "gate": "{robot}-gate.sock",
           "camera": "{robot}-camera.sock"}
KEYS = {"host", "kind", "robot", "pollen", "state", "truth_port", "cargo_bin", "sockets"}


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


def where(path: str | Path | None = None) -> Path:
    """The host file this process reads: the one given, else $ROBOTICS_LAB_HOST, else the default."""
    if path:
        return _path(path)
    return _path(os.environ.get(ENV) or DEFAULT)


def parse(d: dict, source: Path) -> Host:
    def bad(why: str) -> HostError:
        return HostError(f"{source}: {why}")

    if not isinstance(d, dict):
        raise bad("not a JSON object")
    extra = set(d) - KEYS
    if extra:
        raise bad(f"unknown keys {sorted(extra)} (known: {sorted(KEYS)})")
    if d.get("host") != VERSION:
        raise bad(f"'host' is {d.get('host')!r}, this reader knows version {VERSION}")
    if d.get("kind") not in KINDS:
        raise bad(f"'kind' is {d.get('kind')!r}, known: {list(KINDS)}")
    robot = d.get("robot")
    if not isinstance(robot, str) or not robot or "/" in robot:
        raise bad(f"'robot' must be a name like duck-a, not {robot!r}")
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


def load(path: str | Path | None = None) -> Host:
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
