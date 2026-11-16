# ADR-0014 — The duck writes its runs itself, with what a replay needs

**Status:** Proposed (2026-11-16) — for the operator's review
**Date:** 2026-11-16
**Context documents:** [RFC-0008](../rfc/RFC-0008-challenge-course.md) §4 "Log for replay" and
§5 step 0, [the navigator review](../wip/REVIEW-2026-11-15-navigator.md) (the false drop could
not be replayed),
[ADR-0007](ADR-0007-run-file-format-2.md), [ADR-0013](ADR-0013-nxt-runs-in-format-2.md)

## Context

Every cause of the navigator's false drops took one trial to find, because the log had no sensor time,
no raw frame, no pitch rate: the depth points were in it, the readings they came from were not,
and the state a frame was read against was whichever the navigator held at that tick, not the one
nearest the frame in time (Pollen's `autod` pairs each frame with the sample nearest its capture). A
failure could only be diagnosed by running the robot again.

## Decision

### The navigator writes format 2 itself, live

- The duck's navigator (`duck-go`, `duck-explore`, `duck-eval`) writes its run through miniview's
  `Recorder` into the lab data folder (`MINIVIEW_DATA`, or `--miniview-data`), key
  `duck/<scene>/<run>` (`--scene`, default `apartment`; the run is the output folder's name, or
  `--run`). It is live in miniview from its first record and compacted when the run ends. The duck
  depends on the viewer package by a path source, as nxt-web does (ADR-0013).
- `ticks.jsonl` is **kept for now**, unchanged, because the importer and the older tools read it. The
  format 2 run is the record; `ticks.jsonl` goes when nothing reads it. The native writer turns the
  same rows into records with the same code as the importer (`miniview.adapters.duck.DuckLog`), so a
  run written live and the same log imported later are the same run: an evaluation's goals are
  segments with their own clocks (ADR-0007), and each goal's epoch comes from the truth and the map
  at its first pose.
- A failure to write the run costs the run, never the navigation: the error is said once on stderr and
  the navigator goes on.

### A depth frame is a record

- `depth_frame` (kind), written for **every** frame the sensor sends, whatever the duck is doing
  (surveys and turns too): `/depth/raw` (`foxglove.RawImage`, `16UC1`, the 8 x 8 distances in mm),
  `/depth/status` (`mono8`, the statuses), then `/miniview/depth_frame` (JSON) as the last message.
  Rerun and Lichtblick show the first two as images of the frame `tof`. A frame is not part of a tick
  (the sensor's 15 Hz and the navigator's 10 Hz do not line up); it has its own record, which a reader
  assembles when its last message arrives, as for a tick or a map.
- The metadata message holds the frame's own time (`frame_t_ns`, the sensor stream's `t_ns`), its `seq`,
  the time of the state it was paired with (`state_t_ns`) and the difference (`pair_dt_ms`), what a
  replay needs of that state (`state`: the trunk's orientation, its height from odometry, the sensor's
  pose in the trunk), the map pose the points were placed with (`pose`) and what the navigator derived
  (`derived`: `points`, `drop_points`, `block_m`). The tick's `/depth` stays as it was: the same points
  as the viewer draws them.
- **Pairing.** A frame is paired, when it arrives, with the state nearest its `t_ns` among those received
  so far (the last second), as `autod` does. This is also what the navigator **uses**: it derives a
  frame's points, drop points and blocking distance once, from that pair, and `go_to` reads them, where
  it read the newest state at the tick before. That is a change in what the navigator sees (a few tens
  of milliseconds of state, a few centimetres of pose), made so that what is logged is what was
  used; the rule that stops the duck for a drop (three frames in a row) is unchanged.
- A frame is large (about 1.5 KB with its derived values). The pages and the API hold only the frame
  and its pairing (`GET .../sensor?t=`); `state`, `pose` and `derived` are read only by a replay.

### Decisions are events with structured values

A rule that fires is an event (`cliff_stop`, `reflex_stop`, `refused`, `tight_pivot`,
`replan_new_obstacle`, `stalled`, `aborted`, `trapped`, ...): the event gets an optional `decision`,
`{rule, reason, values}`, with the numbers the rule compared and its thresholds. The alternative, a
`decision` kind beside the event, would put two records at the same instant for every stop, two
markers in the timeline and two places to look; the event is already the unit the pages, the index and
`miniview events` work with, so the decision rides on it. A row of `ticks.jsonl` carries the same
`decision` field, so an import has it too.

### The IMU and what the navigator decides on are signals

The run record declares signals (ADR-0013's generic kind, channel `/duck/signals`): `pitch_deg`,
`roll_deg`, `pitch_rate_dps` (the gyro's y axis in the trunk frame), `qw`, `qx`, `qy`, `qz` (the
trunk's orientation), written per state sample (20 Hz), and `nearest_mm`, `block_m`, `room_m` and
`turning` (1 or 0) as the navigator last had them, in the same sample, so the inspector's Moment shows
one coherent sample. A value that does not exist then (`block_m` with nothing ahead, `room_m` outside
`go_to`) is absent, never zero.

### The replay check

`duck-replay <run>` re-runs the duck's perception (`cliff.depth_points`, `drop_points`,
`blocking_ahead`) on every recorded raw frame and its paired state, places the points with the
recorded pose and compares them with what was recorded; it also checks that every tick's `/depth`
is a recorded frame's points, that frame times only grow and that every frame has a state. It is the
acceptance test that the log is complete for replay: a difference means something the navigator used
is not in the file.

## Consequences

- **Positive:** a failure can be replayed offline against any pairing or threshold; the run is
  live in the pages while the duck drives; one writer for every robot.
- **Negative:** the duck depends on the viewer package (`make duck-sync` pulls protobuf and the Foxglove
  schemas into its venv); a run is a few megabytes larger (the raw frames); the navigator's perception
  changed slightly (pairing).
- **Not decided here:** receiving the records from a duck over a network (ADR-0007 "Remote robots");
  removing `ticks.jsonl`.

## Alternatives considered

- **A `decision` record kind** (above).
- **Raw frames in `ticks.jsonl`.** Ten times its size, and a second format to keep complete.
- **Keep the navigator's pairing (the newest state at the tick) and log the nearest as well.** Two
  pairings in the log and a replay that does not reproduce what the navigator decided on.
- **IMU values in `tick_extra.raw`.** Invisible to Rerun and the signals machinery of the pages.
