"""A robot's log into the lab's data folder as a format 2 run (ADR-0007), once or while it is being
written (ADR-0005: live). Until the navigator writes MCAP itself (RFC-0008 step 1), this is how a run
becomes live: `miniview import --follow` reads the growing log and appends to the run's live file.

The source log is copied beside the run (`source/`) and its SHA-256 recorded; every field of it is in
a record (`raw`), so the copy is for provenance, not for rescuing what the import left out.
"""

import hashlib
import shutil
import time
import uuid
from pathlib import Path

from miniview import keys
from miniview.adapters.duck import DuckLog
from miniview.mcapio import FINAL, Recorder, WriterBusy, new_run

SOURCE_FILES = ("ticks.jsonl", "start.json", "results.json", "map_grid.json")
UUID_NAMESPACE = uuid.UUID("6f6c6e6a-5b0c-4c0a-9f6e-6d696e697669")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def import_duck(log_dir: Path, scene: str, data: Path, follow: bool = False, idle_s: float = 60.0,
                poll_s: float = 0.1, say=print, started_at_ns: int | None = None, robot: str = "duck") -> Path:
    log_dir = Path(log_dir)
    ticks = log_dir / "ticks.jsonl"
    if follow:
        waited = 0.0
        while not ticks.exists():
            if waited > idle_s:
                raise SystemExit(f"no {ticks} after {idle_s:.0f} s")
            time.sleep(poll_s)
            waited += poll_s
    elif not ticks.exists():
        raise SystemExit(f"no {ticks}")
    try:
        key = keys.make_key(robot, scene, log_dir.name)
    except ValueError as e:
        raise SystemExit(f"cannot import {log_dir}: {e}") from None
    out_dir = keys.run_dir(data, key)
    log = DuckLog(log_dir, scene)
    sha = None if follow else sha256_of(ticks)
    if started_at_ns is not None:
        started, started_src = started_at_ns, "given"
    elif follow:
        started, started_src = time.time_ns(), "importer_clock"
    else:
        started, started_src = ticks.stat().st_mtime_ns, "file_mtime"
    run = new_run(key, dict(log.robot, name=robot), scene, log.kind, started, started_src, {"name": "ticks.jsonl", "sha256": sha},
                  str(uuid.uuid5(UUID_NAMESPACE, f"{key}:{sha}")) if sha else None)
    try:
        rec = Recorder(out_dir, run)
    except WriterBusy as e:
        raise SystemExit(f"cannot import {log_dir}: {e}") from None
    for r in log.header:
        rec.add(*r)
    n = 0
    with open(ticks) as fh:
        partial, quiet_since = "", time.monotonic()
        while True:
            chunk = fh.readline()
            if chunk:
                partial += chunk
                if not partial.endswith("\n") and follow:
                    continue                            # a line still being written
                for r in log.feed(partial):
                    rec.add(*r)
                    n += 1
                partial = ""
                quiet_since = time.monotonic()
                continue
            if not follow:
                break
            if log.ended() or time.monotonic() - quiet_since > idle_s:
                break
            time.sleep(poll_s)
    if partial:
        for r in log.feed(partial):
            rec.add(*r)
            n += 1
    (out_dir / "source").mkdir(exist_ok=True)
    for name in SOURCE_FILES:
        if (log_dir / name).exists():
            shutil.copyfile(log_dir / name, out_dir / "source" / name)
    final_sha = sha256_of(out_dir / "source" / "ticks.jsonl")
    for t, kind, p in log.finish():
        rec.add(t, kind, dict(p, source_sha256=final_sha) if kind == "end" else p)
    rec.close()
    say(f"{key}: {log.ticks} ticks, {len(log.events)} events, {n} records -> {out_dir / FINAL}")
    return out_dir / FINAL
