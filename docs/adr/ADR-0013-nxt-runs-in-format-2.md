# ADR-0013 — NXT runs in format 2

**Status:** Proposed (2026-11-16) — for the operator's review
**Date:** 2026-11-16
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md),
[RFC-0009](../rfc/RFC-0009-miniview.md) ("a run without a known scene"),
[ADR-0006](ADR-0006-run-identity.md), [ADR-0007](ADR-0007-run-file-format-2.md),
[ADR-0011](ADR-0011-loading-into-the-ui.md), [ADR-0012](ADR-0012-docker-read-only-data.md)

## Context

nxt-web records the LEGO NXT to a CSV (`run-YYYYMMDD-HHMMSS.csv`: time, motor powers, tacho counts,
sensor readings, the running program) and, until now, to an ad-hoc MCAP of its own (`mcap_log.py`:
JSON on `/nxt/state` and `/nxt/events`, no run record, no real start time) that Rerun and
Lichtblick could open and miniview could not. The NXT has no pose of its own and no scene: format 2
([ADR-0007](ADR-0007-run-file-format-2.md)) was written around a duck with a belief pose, a
truth and a map.

## Decision

### Identity

- A run's key is `nxt/unmapped/<run-name>`, for example `nxt/unmapped/run-20261114-145402`
  ([ADR-0006](ADR-0006-run-identity.md)). The scene `unmapped` has no `scenes/unmapped/scene.json`:
  no layout exists. The catalog lists its runs (the scene's `kind` is `no layout`); the pages draw
  none of a scene (`scene.boxes` and `scene.hazards` are missing, "no scene"); `GET
  /api/v1/scenes/unmapped` is a 404.

### Signals

- A new record kind, `signals`: the robot's named values at a time: `{values: {name: number | text}}`.
  The run record declares them (`signals`: name, kind `number` or `text`, optional unit), so every
  reader knows the set before the first sample. nxt-web's every CSV column but `t` is a signal
  (`power_left`, `power_right`, `tacho_A..C`, `s3_color`, `s3_color_name`, `s4_ultrasonic`,
  `program`); the colour name and the program are text. A value a sample did not have (an empty CSV
  cell) is absent, never zero.
- **The message.** A signals tick is one message on `/<robot>/signals` (`/nxt/signals`), **protobuf**
  with a message type our own, built at run time with `descriptor_pb2` (no `protoc`, no new
  dependency: `protobuf` is already the viewer's): `miniview.Signals`, **one optional field per
  declared signal** (a `double`, or a `string`), in the order declared. The channel's schema is the
  message's own `FileDescriptorSet`, so a reader that knows nothing of miniview decodes the values by
  name. The alternative, a generic `Signals { repeated Value values }` with a name and a `oneof`
  per value, has a constant schema and no per-run descriptor, and was measured against it:
  **Rerun 0.43.2** (`rerun mcap convert -d protobuf --disable-raw-fallback`) decodes both into one
  entity, but the generic one into a list of structs of `name` and a `oneof` struct, which a time
  series view cannot plot by name; the per-signal fields decode into one struct column per signal,
  `Struct("power_left": Float64, ..., "s3_color_name": Utf8, ...)`, nullable (an absent field is
  `null`), selectable by name in a Rerun time series. So the fixed-per-run shape was chosen, and the
  reader builds the same message from the run record (not from the channel, so a file whose schema
  and run record disagree is a reader error, not a guess).
- **The tick protocol, extended.** A tick is either a pose tick (as in ADR-0007) or a **signals
  tick**: the signals message, then `/miniview/tick_extra` last, nothing between
  (`Recorder.begin_signals(t, values)` then `end_tick()`, or `add(t, "signals", ...)`). A signals tick
  has no pose, so a robot with signals only has no ticks at all. A robot with both writes a pose tick
  and a signals tick for a sample at the same `t` (time only grows; equal is allowed). One flush per
  tick, as before. A signals message another record interrupts is dropped and counted, as a pose
  tick is.
- Events stay `miniview.event` (JSON): nxt-web's command log (drive, stop, safety stop, fire,
  program, connect, record start) with its detail in `raw`; all of them notable.

### Pose from the tracks (the operator's decision, 2026-11-16)

- Two settings in nxt-web's config, both unset by default: `odom_sprocket_diameter_m` (the diameter
  of the drive sprockets) and `odom_track_width_m` (the **effective** track width for turning: tracks
  slip, so it is calibrated, not measured off the parts). The motor mapping is already in the
  config (`left`, `right`, `invert_left`, `invert_right`). Tacho counts are motor degrees.
- Differential drive: each track's distance is `deg / 360 * pi * D`; per sample the robot moves the
  mean of the two and turns `(right - left) / W` (counter-clockwise positive), integrated on the
  midpoint heading. The pose starts at `[0, 0, 0]` at the first sample, x forward. It is the run's
  belief pose (`/belief/pose`, frame `map`, as in the tick protocol), with one identity epoch (the
  map frame is the world frame: there is no scene to place it in), so miniview draws the track and
  Rerun and Lichtblick show it. A sample with no count for a track holds the pose.
- **With either value unset there is no pose, and never a guess:** the pose streams are missing with
  the reason `no wheel geometry (set odom_sprocket_diameter_m and odom_track_width_m)`, recorded in
  the run record as `no_pose`. With geometry the run record carries `odometry`: the two values, the
  motor mapping, and where they came from (`config`, `config.json`, `command line`).
- The robot's drawn size (marker radius 0.10 m, height 0.12 m) is **nominal, for drawing only**, and
  says so in the run record: nxt-web does not know the robot's footprint.

### The pages

- The Signals group in the outliner has one row per signal, with an eye. The inspector's Moment
  shows each signal's value at the playhead (the sample at or before it), with the sample's number.
  The timeline has a data row per signal (the spans where it has values).
- A run with signals and **no pose** shows a **Signals view** in the viewport (in the shared shell,
  `web/shell/signals.js`, both pages): one chart per numeric signal (an SVG line, its range in the
  label), one labelled band per text signal, stacked on one time axis with the playhead; a click
  or a drag on a chart seeks. The layout and frame buttons are hidden, the streams the run lacks
  are hidden behind "Show them", and "tick" reads "sample". Both themes are respected. A run **with**
  a pose keeps today's spatial views; its signals are in the outliner, inspector and rows too.

### Importing a recording (`miniview import --robot nxt`)

- `miniview import --robot nxt <run>.csv` writes `runs/nxt/unmapped/<run>/` (scene given with
  `--scene`). The source is copied to `source/` and its SHA-256 recorded: the CSV, the old MCAP when
  there is one, else the command-log entries that were used.
- **Time.** The file name's `YYYYMMDD-HHMMSS` is local time on the machine that recorded
  (nxt-web uses `datetime.now()`), whole seconds. The import reads it as local time of the machine it
  runs on, or of the zone given with `--tz` (an IANA name), and converts to UTC. Better clocks win,
  in this order: the old MCAP's own clock (first state's log time minus its `t`,
  `started_at_source: source_clock`, to the nanosecond); the command log's `record start` event
  within 1.5 s of the file name's time (`record_start_event`, to the millisecond); the file name
  (`file_name`, up to a second early); the file's mtime (`file_mtime`). The two recordings of
  2026-11-14 were made on this workstation, so its zone is the right one. A time that falls in the
  hour a clock change repeats is read as its first occurrence.
- **Events:** the old MCAP's `/nxt/events` (with their log times), else the entries of `events.jsonl`
  and `events-fake.jsonl` beside the recordings whose time falls in the recording (2 s either way),
  by time.
- **Geometry:** `--sprocket-diameter` and `--track-width` (both or neither); else the recording's
  own MCAP config, else `config.json` beside the recordings' folder. The motor mapping is the
  recording's own when its MCAP has one.

### nxt-web writes format 2 itself

- Its recorder writes the run through miniview's `Recorder` (the same tick helpers, the live file and
  lock, compaction at the end) beside the CSV: a pose tick (with odometry) and a signals tick per
  sample at the same run time, the command log's entries as events, the CSV's SHA-256 in the `end`
  record. A recording is **live** in miniview from its first sample, and compacted when it stops
  (or when nxt-web is stopped: SIGTERM and Ctrl-C take the stop path). The receiver of ADR-0007
  ("Remote robots") is not needed: nxt-web runs on the workstation.
- **Where it writes (decided here):** the lab data folder `MINIVIEW_DATA`, or `--miniview-data`,
  else `miniview/` in nxt-web's own data folder (`NXT_LAB_DATA`, else the `nxt/` folder): a folder in
  miniview's layout (`runs/nxt/unmapped/<run>/`), so it can be served as it is. `make nxt-web` passes
  `--miniview-data $(MINIVIEW_DATA)` (the workstation's `/work/robotics-lab/data` that
  `make viewer-up` serves), so a real recording is live in the running service; `make nxt-web-fake`
  does not, so a simulated drive does not land in the lab data. The image writes to the mounted
  `MINIVIEW_DATA` (`make nxt-image-run`), else `/data/miniview` in its volume; as the container
  runs as root, runs written there are root's.
- A run's name is the CSV's (`run-YYYYMMDD-HHMMSS`, local time); a name taken by a CSV or by a run
  gets `-2`, `-3`, and so on. Run time is the monotonic clock since the recording began, never behind
  what was already written. `started_at` is the writer's clock.
- **A failure to write the run costs the run, never the recording.** The CSV is written first; an
  error in the miniview writer (a folder that cannot be written, say) is shown in the status
  (`recording.miniview.error`) and the recording goes on; a live file left behind is closed with
  `miniview repair`.
- The CSV stays (nxt-web's Plot view uses it); the `.mcap` link in the run list downloads the
  finished format 2 run. `mcap_log.py` (the old ad-hoc MCAP) is gone; `scripts/viewers.sh` gives
  Rerun (its protobuf decoder) and Lichtblick the finished format 2 runs of the data folder, and
  the duck's own `duck/runs/*.mcap` as before.
- nxt depends on the viewer package (`miniview`) by a path source
  (`[tool.uv.sources] miniview = { path = "../viewer", editable = true }`, the lock updated; protobuf
  and foxglove-schemas-protobuf come with it). pip does not read that table, so the NXT image is
  built from the repository root (`docker build -f nxt/Dockerfile .`) and installs `viewer/` before
  `nxt/`.

## Calibration (the operator's to run; the robot on the floor)

Both numbers belong to the robot, the floor and the speed: calibrate on the surface it will drive on,
at the power it will use, and again if the tracks or the surface change. Record with nxt-web's Record
button, read the tacho counts from the CSV (first and last rows) or from
`miniview state <run> --at t`.

1. **Sprocket diameter** `D`, from a straight run of a known length `L` (a taped line, 2 m or more).
   Drive straight along it, stop, and take the mean of the two tracks' counts, in degrees:
   `delta = (|tacho_B_end - tacho_B_start| + |tacho_C_end - tacho_C_start|) / 2`. Then
   `D = L / (delta / 360 * pi)`, in metres. Repeat three times and take the mean.
2. **Effective track width** `W`, from `N` spins in place (`N` at least 3, counted against a mark on
   the floor; drive left and right in opposite directions). With `a_L` and `a_R` the two tracks'
   counts over the spins, in degrees and as magnitudes:
   `W = ((a_L + a_R) / 360 * pi * D) / (N * 2 * pi)`, which is `(a_L + a_R) * D / (720 * N)`.
   Repeat and take the mean. `W` is not the distance between the tracks' centres: it is the
   number that makes a measured turn come out right.
3. Set `odom_sprocket_diameter_m` and `odom_track_width_m` in nxt-web's Setup (or `config.json`).
   Check: record a drive of a known shape (1 m straight, a quarter turn) and read the track in miniview;
   adjust `W` for a turn that is short or long, `D` for a distance that is.

## Consequences

- **Positive:** every NXT recording, old and new, is a run miniview, Rerun and Lichtblick open; a
  recording is live while it is made; one writer (miniview's) for every robot; the signals message
  is generic (any robot with named values can use it) and self-describing in the file.
- **Negative:** nxt-web now depends on the viewer package; the per-run descriptor means the signal
  set is fixed when a run starts (a sensor changed mid-run is a new run); a run of the old kind
  (`nxt/runs/*.mcap`) is not read by miniview, only imported from its CSV; the image's runs are
  root's.
- **Neutral:** the pose is dead reckoning from the tracks and drifts; the run says how it was made.

## Compatibility (checked 2026-11-16)

`make test-run-compat` (explore9 and an NXT run, with and without wheel geometry): Rerun 0.43.2
`mcap check` and `rrd verify` pass; `/nxt/signals` decodes into one row per sample, a struct with a
named Float64 or Utf8 column per signal (the first sample's values match the CSV); `/belief/pose` and
`/tf` decode for the run with odometry. Lichtblick (the pinned image) lists `/nxt/signals`
(`miniview.Signals`, 281 messages) with no alert but the transforms note, and its Raw Messages panel
decodes the message at the playhead by name, equal to what miniview reads for that sample. That a
Rerun time series view or a Lichtblick Plot panel draws a signal was **not** scripted.

## Alternatives considered

- **A generic `Signals { repeated Value }` message.** Constant schema, but Rerun cannot plot its
  values by name (above).
- **JSON for the signals,** as for our own kinds: no Rerun decoding at all of a custom schema
  (ADR-0007), so the values would be dark in Rerun.
- **One channel per signal.** Rerun would plot each as a scalar, but a sample is no longer one
  message, the tick protocol's atomic unit.
- **A pose guessed from the config's defaults.** Refused: the wheel geometry is the operator's
  to measure.
