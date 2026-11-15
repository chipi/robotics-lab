# RFC-0010 — Runs, version 2: how they are stored, read, served and loaded

**Status:** Accepted (2026-11-15, by the operator), with ADR-0006 to ADR-0012. Built (steps 1 to 7)
on 2026-11-15.
**Builds on:** [RFC-0009](RFC-0009-miniview.md) (miniview), [ADR-0004](../adr/ADR-0004-runs-in-mcap-with-derived-index.md)
(MCAP the record), [ADR-0005](../adr/ADR-0005-miniview-api-live-from-the-start.md) (one API, live).
**Serves:** [RFC-0008](RFC-0008-challenge-course.md) (runs by the hundred; the navigator writing MCAP).
**Evidence:** [the miniview review](../wip/REVIEW-2026-11-15-miniview.md) (13 findings).

## 1. Why

The review of miniview found that one bad file stops the service and one bad record freezes every
live run; that a live page downloads the whole run again every second; that every run once
opened stays in memory and crashed runs are polled forever; that run ids collide across robots;
that a run's time has no wall-clock anchor and an evaluation's goals are joined by a guess; that
the index is written but never read; and that the agent's interface can quietly show the wrong run.
The operator decided (2026-11-15) to fix all of them, and to use the fixes to strengthen how runs
are stored, loaded and brought into the UI — now, before the navigator writes runs itself
(RFC-0008 step 1) and before hundreds exist, when changing the layout is still cheap.

## 2. The shape

```text
 writer (navigator, importer)      the data folder (read only for the service)
   one writer, a lock,  ─────────►  runs/<robot>/<scene>/<run>/run.live.mcap → run.mcap
   flushed per tick                                          source/ (the original log)
                                    scenes/<scene>/scene.json
          service ◄──── follows, validates, isolates (a bad run is "broken", never fatal)
          │   index (outside the data, the service's own): runs, streams, events, segments
          │   cache of loaded runs, bounded by memory; live runs pinned
          ▼
   /api/v1 — windows, records, errors as JSON, gzip, live by record with resume
          ▼
   the page's run store — the window around the playhead first, the rest after;
   live records applied as they arrive; renderers take appends
```

## 3. The decisions

| ADR | Decides | Review findings |
| --- | --- | --- |
| [ADR-0006](../adr/ADR-0006-run-identity.md) | a run is `robot/scene/run`; the `run` record: format, uuid, wall-clock start, origin | 4 |
| [ADR-0007](../adr/ADR-0007-run-file-format-2.md) | the file: one writer and a lock, flushed per tick, absolute time, segments, Foxglove shapes, nothing dropped, compacted at the end | 4, 5, 10 |
| [ADR-0008](../adr/ADR-0008-reading-runs.md) | reading: every record validated, a bad run isolated as broken, rewrites detected | 1, 4 |
| [ADR-0009](../adr/ADR-0009-index-and-lifecycle.md) | the index outside the data, owned by the service, read; run states; a memory-bounded cache | 3, 6, 9 |
| [ADR-0010](../adr/ADR-0010-api-2.md) | the API: windows with their own plans and maps, snapshots outside the lock, JSON errors, live by record with resume, gzip | 2, 8, 13 |
| [ADR-0011](../adr/ADR-0011-loading-into-the-ui.md) | the page: a run store loaded by window then by record; appends; follow as a mode; the agent's interface | 2, 7, 8 |
| [ADR-0012](../adr/ADR-0012-docker-read-only-data.md) | Docker: the data read only, the index on its own volume, imports on the host | 9 |

The two renderers stay as they are until the operator's renderer decision (separate).

## 4. Build order

Each step lands with its tests and keeps the gate green.

1. **Identity and format 2** (ADR-0006, ADR-0007): the writer (lock, flush, absolute time,
   segments, Foxglove shapes, compaction), the importer keeping everything, `miniview repair`.
   The three existing runs are imported again into format 2 (replacing their files needs the
   operator's go, path by path).
2. **Reading** (ADR-0008): validation, broken runs, rewrite detection; the follower never stops.
3. **Index and lifecycle** (ADR-0009): the index moved and read; states; the cache.
4. **API** (ADR-0010).
5. **Loading into the UI** (ADR-0011), both pages.
6. **Docker** (ADR-0012).
7. **Docs** brought in line: ADR-0004 and ADR-0005 (superseded parts), PRD-001's non-goals,
   RFC-0009 §4, CONTRACT.md.

## 5. Tests

- A real run as a fixture: explore9, imported from its log and committed (small).
- A fault test for each finding: a garbage file, a bad record, a key mismatch, the same run name
  under two robots, a replaced file, a second writer, a crashed writer (stopped, not reloaded),
  the index equal to memory after a live run, a resume by `Last-Event-ID`, two viewers, eviction,
  bad query input, an event kind with pattern characters.
- No fixed sleeps: every wait is for a condition, with a timeout.
- `make perf-viewer` (not in CI): phase1-run18 replayed at 20 Hz through the writer with two pages
  open; it reports the follower's latency, the bytes each page receives per second and the time
  the run's lock is held.

## 6. Not decided here

- Which renderer stays (the operator's renderer discussion).
- When the navigator writes format 2 itself: that is RFC-0008 step 1, which follows ADR-0007.
- Retention and backup of runs (RFC-0007's logbook).
