"""A robot's log into the lab's data folder as MCAP (ADR-0004), once or while it is being written
(ADR-0005: live). Until the navigator writes MCAP itself (RFC-0008 step 1), this is how a run becomes
live: `miniview import --follow` reads the growing log and appends to the run's file."""

import time
from pathlib import Path

from miniview.adapters.duck import DuckLog
from miniview.catalog import run_dir
from miniview.mcapio import Recorder


def import_duck(log_dir: Path, scene: str, data: Path, follow: bool = False, idle_s: float = 60.0,
                poll_s: float = 0.1, say=print) -> Path:
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
    out = run_dir(data, "duck", scene, log_dir.name) / "run.mcap"
    log = DuckLog(log_dir, scene)
    rec = Recorder(out)
    for r in log.header:
        rec.add(*r)
    rec.flush()
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
            rec.flush()
            if log.ended() or time.monotonic() - quiet_since > idle_s:
                break
            time.sleep(poll_s)
    if partial:
        for r in log.feed(partial):
            rec.add(*r)
            n += 1
    rec.add(*log.end())
    rec.close()
    say(f"{log_dir.name}: {log.ticks} ticks, {len(log.events)} events, {n} records -> {out}")
    return out
