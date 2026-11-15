"""A run's key is its place: `robot/scene/run` (ADR-0006)."""

import re
from pathlib import Path

PART = re.compile(r"^[a-z0-9_-]+$")


def check_part(name: str, what: str = "part") -> str:
    if not isinstance(name, str) or not PART.match(name):
        raise ValueError(f"{what} {name!r}: lower case letters, digits, - and _ only")
    return name


def make_key(robot: str, scene: str, run: str) -> str:
    return "/".join(check_part(p, w) for p, w in ((robot, "robot"), (scene, "scene"), (run, "run")))


def split_key(key: str) -> tuple:
    parts = key.split("/") if isinstance(key, str) else []
    if len(parts) != 3:
        raise ValueError(f"run key {key!r}: expected robot/scene/run")
    make_key(*parts)
    return tuple(parts)


def run_dir(data: Path, key: str) -> Path:
    robot, scene, run = split_key(key)
    return Path(data) / "runs" / robot / scene / run


def key_of(data: Path, run_dir: Path) -> str:
    """The key a folder under data/runs stands for (ValueError when it is not three valid parts deep)."""
    return make_key(*Path(run_dir).relative_to(Path(data) / "runs").parts)
