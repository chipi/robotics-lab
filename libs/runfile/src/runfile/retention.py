"""Retention (phase 5 step 7, docs/wip/TELEMETRY-RETENTION-DESIGN.md): which runs of the data folder are old enough to leave it, and
moving them out whole. A run folder data/runs/<robot>/<scene>/<run> is renamed (os.rename, so atomic and free) to
<data>-archive/runs/<robot>/<scene>/<run>; nothing is deleted, one line per move is appended to <archive>/archive-log.jsonl, and
restoring is a `mv` back. `plan` only looks; `apply` moves. The index is never opened: the Observatory drops a key whose folder is gone.

It keeps: an official run (its record says `official: true`, the marker the runner's truth copy writes; an older record without the field: it has judge_truth or judge_profile; else its kind is challenge, go-to evaluation or goal-run; `official: false` wins), a run younger than
the age (by the mtime of run.mcap), a run still being written (run.live.mcap, writer.lock), anything it cannot read. It refuses when the
archive is the data folder or inside it (or holds it), when a run's target exists, and when the two are on different filesystems.
Standard library at import; reading a run's record imports the run format's MCAP reader."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from runfile import keys

RUN_TOPIC = "/miniview/run"
LOG = "archive-log.jsonl"
OFFICIAL_FIELDS = ("judge_truth", "judge_profile")      # the rule for runs written before the marker `official: true`
OFFICIAL_KINDS = ("challenge", "go-to evaluation", "goal-run")      # the run record's kinds the runner judges; same rule, by kind
FINAL, LIVE, LOCK = "run.mcap", "run.live.mcap", "writer.lock"      # mcapio's names; not imported, so this stays light
DAY_S = 86400.0


@dataclass(frozen=True)
class Item:
    key: str
    path: Path
    age_days: float | None
    official: bool | None        # None: not known (live, or the record cannot be read)
    size: int
    action: str                  # "archive" | "keep" | "refuse"
    reason: str


def default_archive(data: Path) -> Path:
    data = Path(data)
    return data.parent / f"{data.name}-archive"


def read_record(run_dir: Path) -> dict:
    """The run's own record (its first message, on /miniview/run) from run.mcap. Raises on anything unreadable."""
    from mcap.reader import make_reader

    with open(Path(run_dir) / FINAL, "rb") as fh:
        for _, _, msg in make_reader(fh).iter_messages(topics=[RUN_TOPIC]):
            rec = json.loads(msg.data)
            if not isinstance(rec, dict):
                raise ValueError("the run record is not an object")
            return rec
    raise ValueError("no run record")


def is_official(rec: dict) -> tuple[bool, str]:
    """(official, how): the record's own `official` wins when it is a bool; else the rule for runs older than the marker."""
    mark = rec.get("official")
    if isinstance(mark, bool):
        return mark, "marker"
    if any(f in rec for f in OFFICIAL_FIELDS):
        return True, "rule"
    if rec.get("kind") in OFFICIAL_KINDS:
        return True, f"kind {rec['kind']}"
    return False, "rule"


def refusal(data: Path, archive: Path) -> str | None:
    """Why the archive cannot be used for this data folder, else None."""
    d, a = Path(data).resolve(), Path(archive).resolve()
    if a == d or d in a.parents:
        return f"the archive {a} is inside the data folder {d}"
    if a in d.parents:
        return f"the data folder {d} is inside the archive {a}"
    if not (d / "runs").is_dir():
        return f"{d} has no runs folder"
    probe = a
    while not probe.exists():
        probe = probe.parent
    if os.stat(d / "runs").st_dev != os.stat(probe).st_dev:
        return f"the archive {a} is on another filesystem than the data folder {d}: a rename cannot move a run there"
    return None


def _size(d: Path) -> int:
    total = 0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _is_run_folder(p: Path) -> bool:
    return any((p / n).exists() for n in (FINAL, LIVE, LOCK))


def plan(data: Path, archive: Path, days: float, robot: str | None = None, now: float | None = None, record=read_record) -> list[Item]:
    """Every run under data/runs (of one robot with `robot`) and what to do with it, in key order. Reads, never writes."""
    data, archive = Path(data), Path(archive)
    now = time.time() if now is None else now
    out = []
    for p in sorted((data / "runs").glob(f"{robot or '*'}/*/*")):
        if not (p.is_dir() and _is_run_folder(p)):
            continue
        try:
            key = keys.key_of(data, p)
        except ValueError:
            continue
        size = _size(p)

        def item(action, reason, age=None, official=None):
            return Item(key, p, age, official, size, action, reason)

        if (p / LIVE).exists() or (p / LOCK).exists():
            out.append(item("keep", "still being written"))
            continue
        try:
            age = (now - (p / FINAL).stat().st_mtime) / DAY_S
        except OSError as e:
            out.append(item("keep", f"cannot read {FINAL}: {e.strerror or e}"))
            continue
        try:
            rec = record(p)
            official, basis = is_official(rec)
        except Exception as e:
            out.append(item("keep", f"cannot read the run record: {type(e).__name__}", age))
            continue
        if official:
            out.append(item("keep", f"official run ({basis})", age, True))
        elif age < days:
            out.append(item("keep", f"younger than {days:g} days", age, False))
        elif (archive / "runs" / key).exists():
            out.append(item("refuse", f"the target exists: {archive / 'runs' / key}", age, False))
        else:
            out.append(item("archive", f"older than {days:g} days, not official", age, False))
    return out


def apply(items: list[Item], data: Path, archive: Path, days: float, now: float | None = None) -> tuple[list[dict], list[tuple]]:
    """Move each item with action "archive"; returns (the log lines written, [(key, why not)] for those that did not move)."""
    why = refusal(data, archive)
    if why:
        raise ValueError(why)
    archive = Path(archive)
    moved, failed = [], []
    for it in items:
        if it.action != "archive":
            continue
        dest = archive / "runs" / it.key
        if (it.path / LIVE).exists() or (it.path / LOCK).exists():
            failed.append((it.key, "a writer started on it"))
            continue
        if dest.exists():
            failed.append((it.key, f"the target exists: {dest}"))
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(it.path, dest)
        except OSError as e:
            failed.append((it.key, f"rename failed: {e.strerror or e}"))
            continue
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "key": it.key, "from": str(it.path), "to": str(dest),
                "age_days": round(it.age_days or 0.0, 2), "size": it.size, "official": False, "archive_after_days": days}
        with open(archive / LOG, "a") as fh:
            fh.write(json.dumps(line) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        moved.append(line)
    return moved, failed
