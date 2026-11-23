"""A robot's profile versions through Mission Control (phase 5 step 1, RFC-0023 D10): Mission Control is the one writer of this
machine's version store (runfile.profilestore, under the installation's `state` folder); the runner and the navigator only read it.
A change is saved as the next version and runs from the next goal; going back makes an older version current again; a version is
carried to another machine as an export and imported there (its checksum checked); two versions are compared leaf by leaf.

Only a robot whose robot file points at its profile (`robot`, robots.py) has versions here. Writing needs the installation to run
what is written: its `state` folder, and `robots.<robot>.profile` naming that store's folder for the robot. A save that would not
run (the installation names another file, or none) is refused saying what to change, never written to be ignored."""

from __future__ import annotations

import json
from pathlib import Path

from runfile import installation, registry
from runfile.profile import FormatError, checksum, validate_profile
from runfile.profilestore import Store, StoreError, diff, version_of

from .errors import ApiError, conflict, invalid
from .robots import ConfigError, RobotConfig, profile_of


def _robot(rt):
    if rt.cfg.robot is None:
        raise ApiError(404, "no_profile", f"{rt.cfg.id}'s robot file holds the robot itself: it has no profile versions "
                       f"(a robot file with \"robot\" points at a profile)")
    return rt.cfg.robot


def _where():
    try:
        inst = installation.load(required=False)
    except installation.InstallationError as exc:
        raise conflict("installation", str(exc)) from None
    return inst


def _store(robot: str):
    """The store and why it may not be written (None when it may)."""
    inst = _where()
    if inst is None or inst.state is None:
        where = inst.source if inst is not None else installation.where()
        return None, f"no state folder: name `state` in {where} (the version store is its profiles/ folder)"
    store = Store(inst.state / "profiles")
    folder = store.folder(robot)
    named = inst.robot(robot).profile if inst.robot(robot) is not None else None
    if named is None or named.resolve() != folder.resolve():
        return store, (f"robots.{robot}.profile in {inst.source} is {named or 'not set'}, not the store's folder {folder}: a saved "
                       f"version would not run; set it to {folder}")
    return store, None


def _writable(robot: str) -> Store:
    store, why = _store(robot)
    if why:
        raise conflict("profile_not_writable", why)
    return store


def _call(fn, *a):
    try:
        return fn(*a)
    except StoreError as exc:
        raise invalid(str(exc), code="profile") from None


def _fits(rt, raw) -> None:
    """A version is checked as Mission Control's robot before it is written: a valid profile Mission Control could not load (a
    guardrail its capabilities do not list, a state rate above the robot's limit) is refused, nothing written."""
    try:
        validate_profile(raw)
    except FormatError as exc:
        raise invalid(f"not a valid profile: {exc}", code="profile") from None
    try:
        RobotConfig(rt.cfg.file, profile=profile_of(raw, rt.cfg.variant, {"checksum": checksum(raw), "version": None}))
    except ConfigError as exc:
        raise invalid(f"not a robot Mission Control can run: {exc}", code="profile") from None


def _reload(rt) -> None:
    """Mission Control's view of the robot follows the version it made current; the poses' scale follows at the next goal (the
    navigator reads the version at a goal's start)."""
    with rt.mutex:
        rt.cfg.reload()


def view(rt) -> dict:
    """The robot's profile here: which file runs now (its checksum and version), the store's versions, and whether it is written."""
    robot = _robot(rt)
    store, why = _store(robot)
    try:
        running = registry.profile_file(robot)
        raw = json.loads(running.read_text())
    except (LookupError, registry.ProfileSourceError, StoreError, OSError, ValueError) as exc:
        raise conflict("profile", f"robot {robot!r}: {exc}") from None
    versions, current = [], None
    if store is not None:
        current = _call(store.current, robot)
        versions = [{"version": n, "checksum": checksum(_call(store.read, robot, n)), "current": n == current}
                    for n in store.versions(robot)]
    return {"robot": robot, "variant": rt.cfg.variant, "running": {"path": str(running), "checksum": checksum(raw)},
            "current": current, "versions": versions, "writable": why is None, "why_not": why, "profile": raw}


def start_from(rt) -> tuple:
    """(the profile a change starts from, whole, and its version or None): what a goal would run now; with the installation's store still
    empty, the robot's own file, which the first save seeds it with."""
    robot = _robot(rt)
    try:
        path = registry.profile_file(robot)
    except (StoreError, registry.ProfileSourceError):        # the store folder not made yet, or made and empty: a save seeds it
        path = Path(registry.module(robot).PROFILE)
    return json.loads(path.read_text()), version_of(path)


def save(rt, raw) -> dict:
    """A changed profile as the next version, made current (the store seeded from the robot's own file first, if empty)."""
    robot = _robot(rt)
    if not isinstance(raw, dict):
        raise invalid("profile: the whole profile, a JSON object")
    store = _writable(robot)
    _fits(rt, raw)
    if store.current(robot) is None:
        _call(store.seed, robot, registry.module(robot).PROFILE)
    n = _call(store.save, robot, raw)
    _reload(rt)
    return {"robot": robot, "version": n, "checksum": checksum(raw), "applies": "from the next goal"}


def use(rt, n) -> dict:
    robot = _robot(rt)
    if isinstance(n, bool) or not isinstance(n, int):
        raise invalid("version: a version's number")
    store = _writable(robot)
    _fits(rt, _call(store.read, robot, n))
    _call(store.use, robot, n)
    _reload(rt)
    return {"robot": robot, "current": n, "applies": "from the next goal"}


def export(rt, n=None) -> dict:
    robot = _robot(rt)
    store, _ = _store(robot)
    if store is None:
        raise conflict("no_store", "this machine has no version store (no installation state folder)")
    return _call(store.export, robot, n)


def import_(rt, exported) -> dict:
    robot = _robot(rt)
    store = _writable(robot)
    if isinstance(exported, dict) and isinstance(exported.get("profile"), dict):
        _fits(rt, exported["profile"])
    if store.current(robot) is None:
        _call(store.seed, robot, registry.module(robot).PROFILE)
    n = _call(store.import_, robot, exported)
    _reload(rt)
    return {"robot": robot, "version": n, "current": store.current(robot)}


def compare(rt, a: int, b: int, notes: bool = False) -> dict:
    robot = _robot(rt)
    store, _ = _store(robot)
    if store is None:
        raise conflict("no_store", "this machine has no version store (no installation state folder)")
    ra, rb = _call(store.read, robot, a), _call(store.read, robot, b)
    rows = diff(ra, rb, notes)
    values, all_rows = diff(ra, rb, False), diff(ra, rb, True)
    # two versions that differ only in their notes (measured, why) have two checksums: said, so an empty list does not read "same"
    return {"robot": robot, "a": a, "b": b, "changes": [{"path": p, "a": x, "b": y} for p, x, y in rows],
            "notes_changed": len(all_rows) - len(values), "only_notes": not values and len(all_rows) > 0}
