# ADR-0019 — The semantic map in a run: `objects` and `sighting` records, and what the pages and the video draw of them

**Status:** Accepted (the operator, 2026-11-18)
**Date:** 2026-11-18
**Context documents:** [ADR-0007](ADR-0007-run-file-format-2.md) (the run file, our own kinds),
[ADR-0014](ADR-0014-replay-logging.md) (decisions as events), [ADR-0017](ADR-0017-video-export.md)
(the video export), RFC-0016 (objects and a semantic map; on the `explore` branch until it merges)

## Context

The duck now recognises objects with a camera and keeps a semantic map (RFC-0016). The navigator
writes three rows for it: `semantic` (the objects it knows, when they change), `room` (the room it
believes it is in, with the votes), and `sighting` (every camera sighting, at 2 Hz: where the camera
was, its field of view, what it recognised, relative to the robot; the navigator's row was called
`look` until
2026-11-18, see below). The operator wants to see how
identifying objects works and what the duck really sees: in the 3D scene, in the eye view, in the
thinking panel and in the video, "so a video with all panels is super clear".

Until now `semantic` and `room` rows became events: `raw` held everything, and the viewer dropped
the not-notable ones, so no page could draw an object.

## Decision

### Two record kinds, one event given fields

Format 2's records gain two kinds (ADR-0007's list of our own kinds; the reader of an older run
sees none of them and is unchanged):

- **`objects`** `{objects, changes, t_src, raw}`: a `semantic` row. `objects` are the summaries
  (`id`, `kind`, `x`, `y` in the robot's **map** frame, `n`, `confirmed`, `landmark`,
  `permanence`, `first_t`, `last_t`, `confidence`, `sources`, `evidence`, and `parts`: boxes in
  plan `[x, y, hx, hy, yaw, z0, z1]`, map frame, each with a bottom and a top above the floor).
  `changes` are `["new" | "confirmed", id]`. Each record is the whole map at that time, so a
  reader needs only the one in force.
- **`sighting`** `{pose, hfov_deg, range_m, seen, t_src, raw}`: a `sighting` row. `pose` is the robot's
  **belief** `[x, y, yaw]` in the map frame; each `seen` entry is `{kind, x, y, radius, z0, z1,
  range_m, confidence, source}` with `x` ahead and `y` left, in metres, **relative to the robot**,
  as the recogniser reported it. **Renamed from `look` (the operator, 2026-11-18):** `look` already
  meant the
  head's glance (RFC-0012) and "looks before stepping", and a record of what a camera saw is a
  sighting. The
  reader of a recording made before the rename still reads its `look` rows, and of a file written
  with the
  topic `/miniview/look`, as `sighting` records; nothing writes `look` any more.
- **`room`** stays an `event`; its `room` (a name, or null) and `votes` are now plain fields of
  the event (and `text` says `room kitchen`), not only in `raw`. It is not notable (it never
  decides a verdict), but a viewer's reading keeps it, as it keeps a glance.

On the wire both kinds are `miniview.objects` and `miniview.sighting`, JSON, one message each
(`/miniview/objects`, `/miniview/sighting`), written whole with a flush as a plan is. **There is no
Foxglove schema for them**, so they are not mapped to one: Rerun and Lichtblick open the file and
show the channels as JSON, as they do for `plan` and `event`. The schemas keep to what
Lichtblick's reader takes (ADR-0007): a part is an object `{x, y, hx, hy, yaw, z0, z1}` and a
change `{change, id}` on the wire (lists again in the record). The writer refuses a record that
lacks its fields; the reader checks every one (ADR-0008) and skips and counts a bad one.

### In miniview

- **The service** keeps both lists apart from the ticks (they are small: a sighting is a few hundred
  bytes at 2 Hz) and serves them whole, `GET .../semantic?from=&to=`, once when a page opens a run;
  later records arrive on the live stream like any other. Two streams, `semantic.objects` and
  `semantic.sighting` (group "Semantic map", under Mind), switch the layers and have timeline rows.
  A run without them lists both as missing.
- **The 3D scene**, in the map frame like everything of the robot's (moved by the run's epoch in the
  world frame): each part a box from its bottom to its top; a confirmed object solid-ish with its
  kind as a label, an unconfirmed one faint, a landmark (`landmark >= 0.7`, the operator,
  2026-11-18: the
  duck's fridge, bed, toilet and bathtub at 0.9, the sofa and vanity at 0.8 and the markers at 1.0
  are landmarks) in its own colour. The
  current sighting: its field of view as a wedge on the floor from the belief pose, and what it saw,
  placed from that pose, as boxes with a label. A sighting is **current for one second**.
- **The Eye's panel** adds SEES (the current sighting's detections with range and confidence), ROOM
  (the room and its votes) and OBJECTS (confirmed and not yet). The room is not what the robot
  is *doing*: the panel's DOING line skips room events.

- **The agent's query.** `GET .../state?t=` and the page's `state()` carry the semantic map at `t` as
  `semantic` (a run with none has no such key): the snapshot of objects in force (`kind`, `id`, map
  `x`, `y`, `confirmed`, `landmark`, `confidence`), the current sighting (`kind`, `range_m`,
  `confidence` of each detection; current for one second as in the pages, else null) and the last
  room with its votes. `miniview objects <run> --at t` prints the same; `state`'s `last_event` skips
  `room` events as the Eye's DOING line does. The shape is in `viewer/CONTRACT.md`.

### In the video (ADR-0017)

The engine renders the **world**; objects are in the **map**, so the track moves each by the epoch
in force at its own time (a run with no truth is drawn in the map frame, no epoch). The HUD gains
the same three lines. The top inset draws each object's footprint (confirmed solid, the others
faint, landmarks in their colour) with its kind, and the camera's wedge from the belief pose, so
both stay in the map frame together; belief drift shows as an offset from the furniture the scene
draws. The eye inset draws each current detection as a labelled box, projected with a pinhole
through the head camera's pose and field of view (`cam_fovy` of the model; the inset is rendered
with it too), the detection placed from the **trunk's pose at that frame** (the truth's, the pose
the simulated camera saw it from) plus its relative `x`, `y`. The head camera is taken as it is in
the model at that frame; the detection's height band is its `z0`..`z1`.

**A defect found on the way, fixed here:** the duck's `head_camera` does not look along MuJoCo's
`-z`: at the STAND keyframe with the trunk at the identity its `-z` is world `-x`, behind the
robot, so the eye inset of ADR-0017 showed what was behind the duck. `robots.json` now says which
axis a robot's camera looks along (`eye_axis`, default `-z`; the duck `+z`).

## Consequences

- **Positive:** an object's life (new, confirmed, landmark), what the camera saw and the room it
  led to are in the run, in the 3D scene, in the eye panel and in the video, from one record each.
- **Negative:** `objects` records repeat the whole map (77 KB of JSON for the 32 snapshots of the
  find-fridge-2 recording, a dozen objects each); a robot with hundreds of objects would want a
  delta form.
- **Neutral:** older runs have neither kind and read as before; a recording made before `sighting`
  rows (then `look`) has objects and rooms but no camera view.

## Not decided here

- Detections from a real camera carry `evidence` (a frame's time and a box in the image); no
  page shows the picture yet.

## Alternatives considered

- **Keep `semantic` as an event.** Its `raw` already holds everything, but the viewer's reading
  drops events that are not notable, and a page would have to dig a map out of an event list.
- **Per-tick indexes like plans and worlds (ADR-0011).** A sighting is not a tick's state and the
  lists are small; one fetch is simpler and loses nothing at these sizes. A window parameter is
  there for when they are not.
- **A Foxglove `SceneUpdate` for the objects.** It would show them in Lichtblick's 3D panel;
  deferred: our pages draw them and the schema carries no confirmed / landmark / evidence.
