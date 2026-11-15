# ADR-0009 — The index, run states and a bounded cache

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3,
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) findings 3, 6, 9

## Context

Every run once opened stays in memory (about 14 KB per tick: some 12 GB for 300 runs). A run whose
writer crashed is reloaded at every start and polled four times a second forever. A cold index
loads every run. The index sits in the data folder, so Docker mounts the data read-write; the
service and the commands share it without WAL; `miniview index` empties it under a running
service; the per-tick, epoch, event and stream tables are written but never read, and a live run's
first epoch and events are lost from them.

## Decision

- **The index is the service's own**: `index.sqlite` outside the data folder (`MINIVIEW_INDEX`;
  default `/work/robotics-lab/state/miniview/`), WAL with a busy timeout. The commands read it;
  `miniview index` (rebuild) refuses while a service holds its lock.
- **It is read.** Tables: `runs` (key, uuid, robot, scene, kind, status, verdict, started_at, t0,
  t1, ticks, events, rejects, error, file size, mtime, inode), `streams`, `events`, `segments`. The
  listing and the scenes page come from it; so do questions across runs (`miniview events --all
  --kind cliff_stop`). The per-tick table is dropped: the moment comes from the loaded run.
- **Written in one transaction per change**, with its counters reset together (the lost-epoch bug
  cannot recur).
- **States:** `live` (a lock whose PID is alive, or a file that grew in the last 120 s), `ended`
  (an `end` record), `stopped` (a live file with no live writer and no growth for 120 s), `broken`
  (ADR-0008). `ended`, `stopped` and `broken` are final until the file changes.
- **Start-up reads the index**; only runs whose file changed (size, mtime, inode) are opened, to
  summarize them without keeping them.
- **A cache bounded by memory** holds loaded runs (`MINIVIEW_CACHE_MB`, default 1024), least
  recently used out first; live runs and runs with an open live stream are pinned.

## Consequences

- **Positive:** memory stays bounded; start-up is fast with hundreds of runs; crashed runs cost
  nothing; the data can be mounted read only; questions across runs are one query.
- **Negative:** a run evicted and asked for again is loaded again (about 60 ms per MB).

## Alternatives considered

- **Keep the per-tick table and answer the moment from it.** Saves loading for one question, costs
  a row per tick per run; the pages need the loaded run anyway.
- **No cache, load per request.** Simple, slow for scrubbing.
