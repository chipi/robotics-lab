# ADR-0002 — Viewers: Rerun first, Lichtblick kept usable, MCAP the record

**Status:** Accepted (operator, 2026-11-14): "I like Rerun more for now, but let's keep making sure
I can use both."
**Date:** 2026-11-14
**Context from:** [RFC-0007](../rfc/RFC-0007-platform.md) §4 (the viewer spike),
[VIEWER-SPIKE.md](../wip/VIEWER-SPIKE.md); amends [ADR-0001](ADR-0001-ros-aligned-foxglove.md)
decision 3.

## Context

RFC-0007 needs a viewer for "see": live and recorded robots, maps, paths, plots, the command log,
runs compared. The spike opened one simulated duck run and one NXT run (simulated brick) in Rerun
0.43.2 and in Lichtblick (latest image), both served from the workstation and looked at by the
operator over an ssh tunnel.

| | Rerun | Lichtblick |
| --- | --- | --- |
| Reads our MCAP (JSON + JSON Schema) | Imports it, but keeps JSON as opaque blobs | Directly |
| Needs from us | A converter to `.rrd` (`duck-to-rerun`) | Coordinate frames (`/tf`) in the file |
| First view | Laid itself out: 3D with paths as trails, a plot per number | Empty until frame, topics and panels are set by hand |
| Paths | Drawn as lines | Current axes only |
| Plots against the timeline | Yes | Yes |
| Browsers | Ran in the operator's browser | Warns: Chrome 76+ only |
| Operator's choice | **Preferred for now** | Kept usable |

## Decision

1. **MCAP stays the record format.** Every robot writes MCAP (RFC-0007); nothing is recorded only
   for one viewer.
2. **Rerun is the first viewer.** Our runs reach it through `duck-to-rerun` (MCAP → `.rrd`, Rerun's
   own types: 3D transforms and paths, scalars, text logs).
3. **Lichtblick stays usable.** Recordings carry what it needs (`foxglove.PoseInFrame`,
   `foxglove.FrameTransform`), and the spike checks both.
4. **Both start with one command** on the workstation, on loopback, reached over ssh
   (`make viewers`, `make viewers-down`).
5. **Our own panels** (mission timeline, the brain's decisions, rehearsal against the real run) are
   built inside a viewer, not as a viewer of our own — the effort is in
   [VIEWER-SPIKE.md](../wip/VIEWER-SPIKE.md).

## Consequences

- Positive: the operator sees runs today, in the viewer they prefer, without depending on either
  project's choices for our recordings.
- Negative: a converter to keep up with Rerun's Python API as Rerun releases; two viewers to keep
  working.
- Open: if Rerun reads MCAP's protobuf well, recording Foxglove's protobuf schemas instead of JSON
  would let both viewers read one file with no converter — to test, not decided.

## Alternatives considered

- **Lichtblick only:** reads our files as they are, but needs setup for every view and draws no
  trails; the operator preferred Rerun.
- **Rerun only:** would let the recordings drift toward Rerun's format; MCAP keeps them open.
- **Our own viewer:** large; see the effort table in [VIEWER-SPIKE.md](../wip/VIEWER-SPIKE.md).
