# ADR-0004 — Runs: MCAP the record of truth; a SQLite index and prepared frames derived from it

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0009](../rfc/RFC-0009-miniview.md) §2 and §7,
[ADR-0001](ADR-0001-ros-aligned-foxglove.md), [ADR-0002](ADR-0002-viewers-rerun-and-lichtblick.md)

## Context

The operator asked for storage that is friendly to time series. Runs are bounded bundles — poses,
sensor frames, map snapshots, plans, decisions and events at 10–20 Hz for 1–15 minutes, a few MB
compressed each — and the challenge course will make hundreds. Uses: the page loads a run and
scrubs it; an agent asks for the state at t, events, and questions across runs ("which runs in this
scene broke this invariant"); a navigator appends while it runs and may be killed; Rerun, Lichtblick
and eval-harness should open runs; one format for every robot.

ADR-0002 already decided that **MCAP is the record format and every robot writes it**. The duck's
navigator does not: it writes JSON lines (`ticks.jsonl`). That is a gap against ADR-0002, not a new
choice. A comparison of MCAP, DuckDB over Parquet, Parquet/Arrow files, SQLite, time-series
databases and JSON lines was made on 2026-11-15 (versions checked on PyPI, npm and the projects'
pages that day).

## Decision

1. **Each run is one MCAP file, the record of truth.** One channel per kind of record (poses,
   truth, sensor, world, plan, decisions, events). Foxglove's protobuf schemas where a standard
   shape exists (pose in frame, transforms, grids), which Rerun decodes; JSON schemas for our own
   kinds. A small chunk size, so a killed run loses seconds, not the run. The navigator writes it
   natively (RFC-0008 step 1); until then an adapter converts `ticks.jsonl`, never editing it.
2. **Derived, rebuildable, deletable:**
   - `index.sqlite` across runs (Python's standard library): one row per run (scene, robot, verdict,
     numbers), events, invariant breaks — the agent's questions across runs are one SQL line;
     `index.json` for the page is exported from it.
   - Prepared frames per run, next to its MCAP: what the page loads whole and scrubs in memory.
   Both are rebuilt by `miniview index` and `miniview prepare`, with a staleness check.
3. **Scenes** are files of their own, referred to by name from each run's metadata.
4. **Where: one lab data folder outside the code checkout**, `/work/robotics-lab/data/` (operator,
   2026-11-15), for every robot and tool; not in git (runs grow to gigabytes). Later the logbook
   (RFC-0007) copies it to the homelab for backup.

   ```text
   data/
     scenes/<scene>/scene.json
     runs/<robot>/<scene>/<run-id>/run.mcap      the record (truth)
                                   frames.json    prepared for the page (derived)
     index.sqlite                                 the database across runs (derived)
   ```

5. **The database is SQLite** (the operator asked which): one file, in Python's standard library,
   no server.
6. **No time-series server.** A run is a bounded, nested bundle, not a metrics stream; a service would
   break "files in, files out", and nothing downstream reads it.

## Consequences

- **Positive:** keeps ADR-0002's decision and closes the duck's gap; append and crash safety are
  native; Foxglove, Lichtblick and Rerun (via protobuf) open runs directly; no new Python dependency
  (`mcap` is already in both projects); the page needs no database in the browser.
- **Negative:** two derived artifacts to keep fresh; a new question over raw records across runs
  means a re-scan (or adding DuckDB later as a reader of the derived exports).
- **Neutral:** the browser can read a growing MCAP directly later (`@mcap/browser`) for a live view.

## Alternatives considered

- **MCAP only** — one format, but every question across runs opens hundreds of files, and the page
  would decode and decompress the log on every scrub.
- **DuckDB over Parquet as the core** — the best ad-hoc analytics; but two new heavy dependencies, a
  second place for truth or a conversion step, no append for a live run, and nothing that Rerun or
  Lichtblick open. It can be added later as a reader.
- **SQLite as the record** — good queries and append; no viewer reads it, and nested records fit it
  poorly.
- **A time-series database** (TimescaleDB, QuestDB, InfluxDB) — a service for bounded bundles.
- **JSON lines** (today) — simple, but no schema, no index, largest, and against ADR-0002.
