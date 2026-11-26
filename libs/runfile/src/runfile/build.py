"""A run's build identity, one string and its parts, written into every run (the eval harness's `--build-ref`):

    brain@<robotics-lab commit 12>[-dirty]+ctrl@<local controller>+walker@<8 of the walking policy's sha256, or unknown>
    +sim@<simulator commit 8, or real>+tof@<depth impairment preset, or off>-s<seed>

`dirty` marks a tracked file changed since the commit; an untracked file does not. A dirty tree is recorded, never refused: the
eval side refuses it. A part that cannot be read is `unknown`, never a guess. Standard library only: the runner and the navigator
both write it."""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

CONTROLLER = "rules@1"          # the local controller of a profile that names none (RFC-0025 section 3.7)
PRESET = "nvidia"               # the impairment numbers in robots/duck/profile.json: NVIDIA's priors for their Microduck task
UNKNOWN, REAL, OFF = "unknown", "real", "off"
DIRTY = "-dirty"


def _git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def commit(repo, n: int) -> str | None:
    """The first `n` characters of the repository's HEAD, or None when `repo` is not a checkout."""
    head = _git(Path(repo), "rev-parse", "HEAD")
    return head.strip()[:n] if head and head.strip() else None


def dirty(repo) -> bool | None:
    """Whether a tracked file of the checkout differs from HEAD; None when git cannot say."""
    out = _git(Path(repo), "status", "--porcelain", "--untracked-files=no")
    return None if out is None else bool(out.strip())


def sha8(path) -> str:
    """The first 8 characters of a file's SHA-256, or `unknown` when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()[:8]
    except OSError:
        return UNKNOWN


def walker(host) -> str:
    """The walking policy the running simulator loads: the file robotd's config names (`[policy] walk`, written by duck-sim at
    its start), hashed. `unknown` when the host has no such config or it names no readable file."""
    try:
        cfg = tomllib.loads((Path(host.state) / f"robotd-{host.robot}.toml").read_text())
        return sha8(Path(cfg["policy"]["walk"]).expanduser())
    except (OSError, KeyError, TypeError, AttributeError, tomllib.TOMLDecodeError):
        return UNKNOWN


def tof(setting: dict | None) -> tuple:
    """(preset, seed) of the depth impairment `setting` ({"enabled", "seed"}): `off` when it is not enabled."""
    s = setting or {}
    return (PRESET if s.get("enabled") else OFF), int(s.get("seed", 0))


def identity(brain: str, ctrl: str, walker_: str, sim: str, preset: str, seed: int) -> dict:
    """The string, and each part of it as the string writes it. `brain` is the commit with its `-dirty`, if any."""
    parts = {"brain": brain, "ctrl": ctrl, "walker": walker_, "sim": sim, "tof": preset, "seed": int(seed)}
    parts["dirty"] = brain.endswith(DIRTY)
    parts["id"] = f"brain@{brain}+ctrl@{ctrl}+walker@{walker_}+sim@{sim}+tof@{preset}-s{int(seed)}"
    return parts


def of(repo, host, variant: str, impairment: dict | None, ctrl: str = CONTROLLER) -> dict:
    """The build a run on `host` records, read now: the brain from `repo`'s git, the simulator and the walking policy from the
    host (`variant` "sim"; any other is a real robot: no simulator, a policy this machine cannot reach)."""
    sha = commit(repo, 12)
    brain = (sha or UNKNOWN) + (DIRTY if sha and dirty(repo) else "")
    sim = walk = None
    if variant == "sim":
        rl = getattr(host, "microduck_rl", None)
        sim, walk = (rl and commit(rl, 8)) or UNKNOWN, walker(host)
    preset, seed = tof(impairment)
    return identity(brain, ctrl, walk or UNKNOWN, sim or REAL, preset, seed)
