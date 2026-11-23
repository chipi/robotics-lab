# Viewer spike: Rerun or Lichtblick, and what our own would take

**Started:** 2026-11-14 ([RFC-0007](../rfc/RFC-0007-platform.md) §4, step 2). The operator approved
installing Rerun into `duck/`'s venv and running Lichtblick's Docker image, and asked what building
our own viewer would need.

## What exists now

| Piece | Where | Checked |
| --- | --- | --- |
| NXT runs as MCAP: `/nxt/state`, `/nxt/events` | `nxt_lab/mcap_log.py`, every recording | Read back in the smoke test |
| Duck runs as MCAP: `/duck/state`, `/duck/pose`, `/duck/truth` | `duck-record` (`duck/src/duck_lab/record.py`) | A 26 s walk in the apartment read back |
| Our MCAP → Rerun's `.rrd` | `duck-to-rerun` (`duck/src/duck_lab/to_rerun.py`) | `rerun rrd verify`: both files verified without error |
| Rerun 0.43.2 | `duck/.venv` (dev dependency) | Web viewer served on the workstation |
| Lichtblick (latest image, `sha256:25333a8f…`) | Docker, loopback port 8090, run files mounted | Serves the app and the files (range requests: 206) |

Not yet: a **real** NXT run (the brick is away today; the NXT file is from the simulated brick).

## What the files are, to each viewer

- **Lichtblick** reads JSON messages with JSON Schemas, as Foxglove does; `/duck/pose` and
  `/duck/truth` use the `foxglove.PoseInFrame` shape, so its 3D panel can draw them. **Not
  verified:** no browser here; the operator's look is the check.
- **Rerun** imports MCAP but keeps JSON messages as opaque blobs (`McapMessage:data` in
  `rerun rrd print`); as far as read here it decodes protobuf and ROS 2 messages. So for Rerun the
  runs go through `duck-to-rerun`: poses as 3D transforms and paths, numbers as scalar plots, the
  command log as text. Writing protobuf (Foxglove's schemas) instead would let both read one file
  — a format decision for after the spike.

## What the operator saw (2026-11-14)

- **Lichtblick:** read the files as recorded. Its 3D panel showed nothing until the files carried
  `foxglove.FrameTransform` messages, and a transform sent once was "missing" later in the run — so
  `duck-record` now sends `/tf` continuously. Then: four frames, odometry and truth a few
  centimetres apart; a Plot synced to the timeline (odometry x: standing, walking, the curve past
  north, standing). Setup by hand (frame, topics, panels); no trail of the path; a banner that only
  Chrome 76+ is supported.
- **Rerun:** laid itself out with no setup: 3D with both paths as trails, a plot per number. The
  first timeline spanned 0.2 s — `duck-to-rerun` had named its timeline `log_time`, Rerun's own,
  which Rerun stamps with the moment of conversion; renamed `recorded`.
- **Choice:** "I like Rerun more for now, but let's keep making sure I can use both" —
  [ADR-0002](../adr/ADR-0002-viewers-rerun-and-lichtblick.md).

## For the operator: how to look

`make viewers` (on the workstation) converts every run in `apps/nxt-web/runs/` and `duck/runs/` and
starts both, printing the links; `make viewers-down` stops them. From the Mac: `ssh -N -L
8090:127.0.0.1:8090 -L 9090:127.0.0.1:9090 -L 9876:127.0.0.1:9876 marko@100.92.54.65`, then the
printed links. In Rerun choose the timeline `recorded`; in Lichtblick's 3D panel the display frame
`world`.

What to compare (RFC-0007 §4): the duck's path in 3D (odometry against truth), plots over time
(NXT tachos and sensors, the duck's velocities), the command log on the timeline, two runs side by
side, how much setup each needs, and how each works on a phone.

## What our own viewer would take

The parts a robotics viewer is made of, what exists to build each from, and how hard each is. The
effort column is a judgement from what these parts involve, not a measurement.

| Part | What it does | Build from | Effort |
| --- | --- | --- | --- |
| Reading MCAP | Indexed, random-access reads of large files, in the browser | `@mcap/core` (the format's reference library for TypeScript) | Small |
| Decoding | JSON, protobuf, ROS 1/2, CDR; schema-driven | `protobufjs`, `@foxglove/rosmsg`; JSON native | Medium (one encoding: small) |
| Time and playback | One clock across topics, play, pause, scrub, speed, seek in big files | Our own | Medium: the core of every viewer |
| Plots | Many series, zoom, follow the playhead | uPlot or similar | Small to medium |
| 3D | Poses, paths, transform tree (map → odom → trunk), meshes, point clouds | three.js | Large: the transform tree and its timing are most of it |
| Maps | An occupancy grid under the 3D view | three.js texture | Small, once 3D exists |
| Camera | JPEG frames; H.264 if recorded as video | browser decoders, WebCodecs | Medium |
| Logs and events | A timeline of events, filtered | Our own | Small |
| Layouts | Panels the user arranges and saves | a layout library | Medium |
| Live data | Streaming from a robot, not only files | the Foxglove WebSocket protocol (open), or our own | Medium |
| Several runs | Two recordings on one timeline, aligned | Our own | Medium |
| Phone | Usable at phone width | design work across all of it | Medium |

In short: a single-purpose viewer for our own runs (a map, the duck's path, a few plots, the
command log, one run at a time) is a few of the small and medium parts. A general viewer that
approaches Lichtblick or Rerun is all of them, and is what those projects spent years on.

**Recommendation (for the operator's review after the look):** reuse a viewer and build **our own
panels inside it** — Lichtblick has an extension API for panels, Rerun has blueprints and a Python
SDK — for what only we need: the mission timeline, the brain's decisions, the mission spec, the
rehearsal-vs-real comparison. Build a viewer of our own only if neither can show those.
