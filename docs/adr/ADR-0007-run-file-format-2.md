# ADR-0007 — The run file, format 2

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3, [ADR-0004](ADR-0004-runs-in-mcap-with-derived-index.md),
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) findings 4, 5, 10

## Context

Format 1 (ADR-0004 "as built") has JSON records of our own, no chunks, run-relative time, and no
lock. A second writer truncates a file silently; the writer does not flush per record (a crash
loses up to 8 KB); log time starts at 1970; an evaluation's goals are joined by a guess on clock
jumps; the import drops fields; Foxglove and Lichtblick open the files but show nothing. The
navigator is about to write runs itself (RFC-0008 step 1) and will copy whatever layout exists.

## Decision

- **One writer.** While written, a run is `run.live.mcap` beside `writer.lock` (PID, host, start
  time). The writer creates both exclusively and refuses a run that exists. It flushes after each
  tick's records: a crash loses at most the tick being written.
- **Absolute time.** `log_time = started_at_ns + t` (ADR-0006); `publish_time` is the source's own
  clock. Run time `t` only grows.
- **Segments instead of stitching.** An evaluation's goals are `segment` records (index, goal,
  the source clock's origin). A new segment starts at the event that ended the last goal
  (`reached`, `refused`, `timeout`, `stalled`, `aborted` with a `goal`), never at a clock jump.
  Each tick keeps its source time as `t_src`.
- **Standard shapes where they exist**, as JSON messages with Foxglove's JSON schemas:
  `/belief/pose` and `/truth/pose` as `foxglove.PoseInFrame`, the map → world transform on `/tf`
  as `foxglove.FrameTransform`, the map grid on `/map` as `foxglove.Grid`, depth returns on
  `/depth` as `foxglove.PointCloud` (with the return kind as a field). Our own kinds use
  `miniview.*` schemas: `run`, `segment`, `event`, `plan`, `command`, `tilt`, `memory` (obstacles
  and drops), `end`.
- **Nothing dropped.** A tick's fields that have no channel of their own go in `miniview.tick_extra`
  (`raw`); an import copies the source log to `source/` beside the run and records its SHA-256.
- **Closed when done.** The writer writes `end` (the verdict) and compacts the file into `run.mcap`
  (zstd chunks, message indexes, summary), then removes `run.live.mcap` and the lock. A writer that
  died leaves the live file; `miniview repair <run>` compacts it with the verdict `stopped`.
- Format 1 files are not read any more; the three existing runs are imported again.

## Consequences

- **Positive:** two writers cannot corrupt a run; crashes lose at most one tick; time is real;
  goals are explicit; Foxglove, Lichtblick and Rerun's MCAP reader show poses, the map and depth;
  finished files are compressed and indexed.
- **Negative:** more to write and read; the reader maps Foxglove messages back to our records;
  three runs must be imported again.

## Alternatives considered

- **Chunked while live.** A reader sees a chunk only when it closes, so live latency would depend
  on chunk size. Writing unchunked while live and compacting at the end gives both.
- **Foxglove protobuf instead of JSON.** Smaller, and Rerun decodes it natively; it needs a
  protobuf dependency on every writer, including the robot. JSON with Foxglove's schemas first.
- **Keep format 1 and fix only the reader.** A migration later, with hundreds of runs.
