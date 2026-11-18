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
  Each tick keeps its source time as `t_src`. A segment whose source clock restarted keeps that
  clock: its zero is placed 1 s after the previous record (the gap between goals is not in the
  log), so the time a new navigator spends before its first record stays in the run (phase 1:
  about 12 s a goal; dropping it shortened phase1-run18 from about 588 s to 341 s, 2026-11-16).
- **Standard shapes where they exist**, as protobuf messages (message encoding `protobuf`, the
  schema a
  `FileDescriptorSet` from the `foxglove-schemas-protobuf` package; changed from JSON on 2026-11-15
  by the
  operator after the check below):
  `/belief/pose` and `/truth/pose` as `foxglove.PoseInFrame`, the map → world transform on `/tf`
  as `foxglove.FrameTransform`, the map grid on `/map` as `foxglove.Grid`, depth returns on
  `/depth` as `foxglove.PointCloud` (with the return kind as a field). Our own kinds use
  `miniview.*` schemas: `run`, `segment`, `event`, `plan`, `command`, `tilt`, `memory` (obstacles
  and drops), `end` (and, added by [ADR-0018](ADR-0018-semantic-map-records.md), `objects` and
  `look`: single messages like `plan`).
- **Nothing dropped.** A tick's fields that have no channel of their own go in `miniview.tick_extra`
  (`raw`); an import copies the source log to `source/` beside the run and records its SHA-256.
- **Closed when done.** The writer writes `end` (the verdict) and compacts the file into `run.mcap`
  (zstd chunks, message indexes, summary), then removes `run.live.mcap` and the lock. A writer that
  died leaves the live file; `miniview repair <run>` compacts it with the verdict `stopped`, and
  `miniview compact <run>` closes a finished run (it has its `end`) whose writer did not. Compaction
  streams the file record by record (memory does not grow with the file) and runs wherever the file
  is, so a small robot computer never compacts.
- Format 1 files are not read any more; the three existing runs are imported again.

## The tick protocol

A tick is written by these rules, which the recorder enforces (`begin_tick`, `tick_truth`,
`tick_depth`, `tick_command`, `tick_tilt`, `end_tick`, or `add(t, "tick", ...)` in one call) and the
reader checks:

1. The first message of a tick is `/belief/pose`.
2. Then at most one each of `/truth/pose`, `/depth`, `/miniview/command`, `/miniview/tilt`, in that
   order.
3. The last message of a tick is `/miniview/tick_extra` (always written, even with nothing in `raw`).
4. Nothing else is written between the first and the last message of a tick.
5. A world is `/map` then `/miniview/memory`, with nothing between them.
6. The writer flushes once per tick (and once per world or other record): a crash loses at most the
   tick being written.
7. (Added by [ADR-0013](ADR-0013-nxt-runs-in-format-2.md), proposed 2026-11-16.) A **signals tick**,
   a tick of a robot's named values with no pose, is the robot's `/<robot>/signals` message (a
   protobuf message built from the signals the run record declares) then `/miniview/tick_extra`,
   nothing between (`begin_signals`, `end_tick`). A robot with a pose and signals writes both at the
   same `t`.
8. (Added by [ADR-0014](ADR-0014-replay-logging.md), proposed 2026-11-16.) A **depth frame**, the
   sensor's raw 8 x 8 distances and statuses with their times, the state they were paired with and what
   was derived, is a record of its own: `/depth/raw`, `/depth/status`, `/miniview/depth_frame` (last),
   nothing between, one flush. It is not part of a tick and may be written between two. An event may
   carry a `decision` (`{rule, reason, values}`).

A reader emits a tick only when its last message has arrived. A tick or world that another message
interrupts is dropped and counted as a reject with its reason. Frames are checked: `/belief/pose`,
`/depth` and `/map` are in `map`, `/truth/pose` in `world`, and `/tf` is `world` ← `map` (parent
`world`, child `map`); anything else is rejected.

## Clocks and kinds

- `t` (the run's time, `log_time - started_at_ns`) only grows. `t_src` is the source's own clock for
  that record, in seconds: the navigator's monotonic clock or the simulator's, whichever stamped it.
  It can restart (a new navigator for the next goal) or differ between sources; it is kept for
  provenance and as the messages' `publish_time`, never used to order records.
- Depth kinds are one ASCII character each: `f` floor, `o` obstacle, `v` overhead, `b` below the
  floor (a hole). A kind that is not one of these is written and read as it is, and drawn as `o`.

## Remote robots

A robot's computer does not write the run file over a network file system: the lock is a local PID,
the inode semantics and `flush` are local, and a half-synced file would look like a crash. The decided
design is **a receiver process on the workstation** that owns the file: the robot streams its records
to it (the tick protocol is the unit of the stream) and the receiver writes the file with the recorder,
flushes per tick and compacts at the end, on the workstation. The lock then names a process on the
workstation. Until a receiver exists, a robot that writes elsewhere leaves a lock from another host,
which the service treats as unknown: the file's growth decides whether the run is live (ADR-0009), and
`repair` and `compact` refuse a file that grew in the last two minutes.

## Consequences

- **Positive:** two writers cannot corrupt a run; crashes lose at most one tick; time is real;
  goals are explicit; finished files are compressed and indexed.
- **Negative:** more to write and read; the reader maps Foxglove messages back to our records;
  three runs must be imported again.

**As checked (2026-11-15, explore9 in format 2):**

- **Rerun 0.43.2, with the Foxglove channels as protobuf:** `rerun mcap check` passes every channel
  and
  `rerun rrd verify` passes the converted file. `rerun mcap convert -d protobuf --disable-raw-fallback`
  decodes the entities `/belief/pose` (116 rows), `/truth/pose` (116), `/depth` (116 point clouds),
  `/map`
  (16 grids) and `/tf` (1 transform): the counts of the run. `-d foxglove` alone decodes nothing in
  this
  Rerun, with JSON or with protobuf; the `protobuf` decoder is the one that reads these channels.
  (Before the change, with JSON messages, no decoder showed them.)
- **Lichtblick loads them** with the right start time, the transforms, and `/belief/pose`,
  `/truth/pose`, `/depth` and `/map` classed as pose, point cloud and grid in its 3D panel. It
  rejected three of our own schemas at first (an array without an item type, an array of arrays);
  points are now `{x, y}` objects and a test keeps the schemas inside what Lichtblick reads. That
  the poses, map and depth draw in its 3D panel is not verified: switching the topics on was not
  scripted successfully.
- **A channel is written with its first message** (2026-11-16). With every channel declared at the
  start, a run without raw depth frames had an empty `/depth/raw`: the Image panel of Lichtblick's
  default layout (there with or without one) took it as its topic, and the compatibility check's 3D
  panel no longer listed its four topics (why is not established). A file has a channel only for a
  topic it holds; `compact` adds the `end` channel itself when it closes a stopped run. Runs written
  before keep their empty channels; the duck and NXT runs in the data folder open in Lichtblick with
  only the transform-topics note.

## Compatibility

A run opens fully in **Rerun, in Foxglove/Lichtblick and in miniview**, and stays so: we may drop one
of them later, not now.

**Rerun and miniview are tested; Lichtblick's checks are skipped** (the operator, 2026-11-16).
Driving Lichtblick's UI in CI failed runs for reasons in its UI, not in our files (its transforms
note did not show in 2 of 5 runs), and its failures must not become ours. The checks are kept, to
fix later: `COMPAT_LICHTBLICK=1 make test-run-compat` runs them (they passed so on 2026-11-16).
`make test-run-compat` (in `make ci`, and a CI job) imports the explore9 fixture and an NXT run
and checks Rerun (`mcap check`, `mcap convert -d protobuf` decoding the poses, the transform, the
map and the depth with the run's counts, `rrd verify`, a signal plotted from a blueprint) and the
service (loads and serves it). A change to the file that breaks one of them fails that test.

What Lichtblick did read was checked on 2026-11-16 with the image `make viewers` pins by digest in
`scripts/viewers.sh` (`ghcr.io/lichtblick-suite/lichtblick@sha256:25333a8f…`): it loaded the file
with no alert but the transforms note, the run's real start date and its topics, which drew when
switched on. That is a record of that day; CI does not run it. The schema rules Lichtblick's
reader imposes (no untyped arrays, no arrays of arrays) stay a unit test of our own schemas
(`test_mcapio.py`), which runs no Lichtblick.

## Alternatives considered

- **Chunked while live.** A reader sees a chunk only when it closes, so live latency would depend
  on chunk size. Writing unchunked while live and compacting at the end gives both.
- **Foxglove JSON schemas instead of protobuf.** No dependency, but Rerun decodes none of it and the
  messages are larger. Used first (checked 2026-11-15), then replaced by protobuf; every writer,
  including the robot, needs the `protobuf` and `foxglove-schemas-protobuf` packages.
- **Keep format 1 and fix only the reader.** A migration later, with hundreds of runs.
