"""A machine's profile versions (phase 5 step 1, RFC-0023 D10): every version a robot's profile has had on this installation, and
which one is current. Mission Control writes it (an operator's change is a new version, applied from the next run); the runner only
reads it. Under the installation's state folder:

    profiles/<robot>/1.json, 2.json, …        each a whole profile, as saved (its schema version inside it)
    profiles/<robot>/current                  the current version's number, as text

Keyed by the robot's registered name (labrunner.robots), not the profile's id: two robots of one kind on one machine keep two chains.
A version's number is this store's label; its checksum (runfile.profile.checksum) is its identity across machines, and import matches
on it. Standard library and runfile.profile only."""

from __future__ import annotations

import json
import os
from pathlib import Path

from runfile.profile import FormatError, META, checksum, validate_profile

EXPORT = 1


class StoreError(ValueError):
    """A version that cannot be read, saved or imported, with the reason."""


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)          # <state>/profiles

    def folder(self, robot: str) -> Path:
        if not robot or "/" in robot or robot.startswith("."):
            raise StoreError(f"robot name {robot!r} must be a registered robot's name, like duck")
        return self.root / robot

    def versions(self, robot: str) -> list:
        f = self.folder(robot)
        return sorted(int(p.stem) for p in f.glob("*.json") if p.stem.isdigit()) if f.is_dir() else []

    def current(self, robot: str) -> int | None:
        p = self.folder(robot) / "current"
        if not p.exists():
            return None
        text = p.read_text().strip()
        if not text.isdigit():
            raise StoreError(f"{p}: holds {text!r}, not a version number")
        n = int(text)
        if not self.path(robot, n).exists():
            raise StoreError(f"{p}: names version {n}, and {self.path(robot, n)} does not exist")
        return n

    def path(self, robot: str, n: int) -> Path:
        return self.folder(robot) / f"{n}.json"

    def read(self, robot: str, n: int | None = None) -> dict:
        n = self.current(robot) if n is None else n
        if n is None:
            raise StoreError(f"{self.folder(robot)}: no version yet (seed it from the robot's own profile)")
        p = self.path(robot, n)
        try:
            return json.loads(p.read_text())
        except FileNotFoundError:
            raise StoreError(f"{p}: no such version") from None
        except json.JSONDecodeError as e:
            raise StoreError(f"{p}: not JSON ({e})") from None

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text)
        os.replace(tmp, path)                 # whole or not at all: a reader never sees half a version

    def seed(self, robot: str, profile_path: Path) -> int:
        """Version 1 from the robot's own profile file, when the store has none for it yet; the current version otherwise."""
        cur = self.current(robot)
        if cur is not None:
            return cur
        raw = json.loads(Path(profile_path).read_text())
        try:
            validate_profile(raw)
        except FormatError as e:
            raise StoreError(f"{profile_path}: {e}") from None
        self._write(self.path(robot, 1), json.dumps(raw, indent=1, ensure_ascii=False))
        self._write(self.folder(robot) / "current", "1\n")
        return 1

    def save(self, robot: str, raw: dict) -> int:
        """A changed profile as the next version, made current. Validated first; the same content as the current version is
        refused (no version that changes nothing)."""
        try:
            new_sum = checksum(raw)
        except FormatError as e:
            raise StoreError(f"not a valid profile: {e}") from None
        cur = self.current(robot)
        if cur is not None and checksum(self.read(robot, cur)) == new_sum:
            raise StoreError(f"the same as version {cur} (checksum {new_sum}): nothing to save")
        n = max(self.versions(robot), default=0) + 1
        self._write(self.path(robot, n), json.dumps(raw, indent=1, ensure_ascii=False))
        self._write(self.folder(robot) / "current", f"{n}\n")
        return n

    def use(self, robot: str, n: int) -> None:
        """Make an existing version current again (going back)."""
        if not self.path(robot, n).exists():
            raise StoreError(f"{self.path(robot, n)}: no such version")
        self._write(self.folder(robot) / "current", f"{n}\n")

    def export(self, robot: str, n: int | None = None) -> dict:
        """One version as one file to carry to another machine: the profile, its version here and its checksum."""
        n = self.current(robot) if n is None else n
        raw = self.read(robot, n)
        return {"export": EXPORT, "robot": robot, "version": n, "checksum": checksum(raw), "profile": raw}

    def import_(self, robot: str, exported: dict) -> int:
        """An exported version saved here as the next version: its checksum checked against its profile first (a file changed on
        the way is refused, nothing written), made current. Returns the new version's number, or the existing one's (made
        current, nothing saved twice) when this store already has a version with that checksum."""
        if not isinstance(exported, dict) or exported.get("export") != EXPORT or not isinstance(exported.get("profile"), dict):
            raise StoreError(f"not a profile export (export {EXPORT}, with a profile)")
        try:
            actual = checksum(exported["profile"])
        except FormatError as e:
            raise StoreError(f"the exported profile is not valid: {e}") from None
        if actual != exported.get("checksum"):
            raise StoreError(f"the export's checksum {exported.get('checksum')} does not match its profile ({actual}): refused")
        for n in self.versions(robot):
            if checksum(self.read(robot, n)) == actual:
                self.use(robot, n)
                return n
        return self.save(robot, exported["profile"])


def resolve(path: Path) -> Path:
    """A profile path as a runner hands it on: a version's file as it is, or a robot's folder in a store: its current version's
    file, read now (so a run that starts after a save runs the saved version)."""
    path = Path(path)
    if not path.is_dir():
        return path
    store = Store(path.parent)
    n = store.current(path.name)
    if n is None:
        raise StoreError(f"{path}: no version yet (seed it from the robot's own profile)")
    return store.path(path.name, n)


def leaves(data, prefix: str = ""):
    """(path, value) of every leaf of a profile: objects by `a.b`, lists of objects by `a[i]`, a list of plain values as one
    leaf; `measured` and `why` included as text."""
    if isinstance(data, dict):
        for k, v in data.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(data, list) and any(isinstance(x, (dict, list)) for x in data):
        for i, x in enumerate(data):
            yield from leaves(x, f"{prefix}[{i}]")
    else:
        yield prefix, data


def diff(a: dict, b: dict, notes: bool = False) -> list:
    """What differs between two profiles, leaf by leaf: [(path, in a, in b)], None where a side has no such leaf. `measured`
    and `why` are left out unless `notes`."""
    la, lb = dict(leaves(a)), dict(leaves(b))
    out = []
    for path in sorted(set(la) | set(lb)):
        if not notes and path.rsplit(".", 1)[-1] in META:
            continue
        if la.get(path) != lb.get(path):
            out.append((path, la.get(path), lb.get(path)))
    return out
