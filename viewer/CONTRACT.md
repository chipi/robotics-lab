# The contract — runs (format 2), the API (version 2) and the pages (RFC-0010)

`miniview serve` (or `make viewer-up`, in Docker) serves the pages and the API over the lab's data
folder (`MINIVIEW_DATA`, or `--data`; there is no default in the code, the workstation's
`/work/robotics-lab/data` is the default of the compose file and the Makefile only). The service's
own index is at `MINIVIEW_INDEX` (default `/work/robotics-lab/state/miniview/index.sqlite`), outside
the
data. The loaded-run cache is bounded by `MINIVIEW_CACHE_MB` (default 1024). Units SI (metres,
radians, seconds). Frames: **world** (the scene's, where truth is) and **map** (the robot's own). A
pose
is `[x, y, yaw]`.

## Runs on disk — format 2 (ADR-0006, ADR-0007)

```text
data/scenes/<scene>/scene.json
data/runs/<robot>/<scene>/<run>/run.live.mcap + writer.lock     while written
data/runs/<robot>/<scene>/<run>/run.mcap                        when done (zstd chunks, indexes, summary)
data/runs/<robot>/<scene>/<run>/source/                         an import's original log (ticks.jsonl, ...)
```

- **The key** of a run is its place, `robot/scene/run`; each part is lower case letters, digits, `-`
  and `_`.
- **The first message is `/miniview/run`**: `{format: 2, key, uuid, robot: {name, radius, height},
  scene, kind,
  started_at_ns, started_at_source ("writer", "file_mtime", "importer_clock", "given"), writer:
  {program, version},
  source?: {name, sha256}, signals?, odometry?, no_pose?}`. A run whose record disagrees with its
  folder is broken. `signals` declares a robot's named values (ADR-0013): `[{name, kind: "number" |
  "text", unit?}]`; `odometry` how a pose was computed (`{sprocket_diameter_m, track_width_m, left,
  right, invert_left, invert_right, source}`), `no_pose` why there is none ("no wheel geometry ...").
- **Time**: `log_time = started_at_ns + t` (UTC nanoseconds; `t` is the run's time and only grows);
  `publish_time` is the source's own clock (each tick also keeps `t_src`).
- **Writer**: one, with `writer.lock` (`{pid, host, started_at_ns}`) created exclusively; it refuses
  a run that exists.
  Every record is flushed when it is written; a crash loses at most the tick being written. At the
  end: `end`
  (`{verdict}`), then `run.mcap`, then the live file and the lock are removed. `miniview repair
  <key>` closes a dead
  writer's run with the verdict `stopped`.
- **Messages**: the Foxglove channels (`/belief/pose`, `/truth/pose`, `/depth`, `/depth/raw`,
  `/depth/status`, `/tf`, `/map`) are
  protobuf with a
  `FileDescriptorSet` schema (the `foxglove-schemas-protobuf` package); ours (`miniview.*`) are JSON
  with JSON schemas.
  Foxglove's published JSON schemas stay copied in `src/miniview/schemas/` as the reference tests
  check against.
  **The tick protocol** (the recorder enforces it, the reader checks it): (1) a tick's first message
  is
  `/belief/pose`; (2) then at most one each of `/truth/pose`, `/depth`, `/miniview/command`,
  `/miniview/tilt`, in that order; (3) its last message is `/miniview/tick_extra`; (4) nothing else
  between the first and the last; (5) a world is `/map` then `/miniview/memory`; (6) one flush per
  tick; (7) **a signals tick** (ADR-0013) is the robot's `/<robot>/signals` message, then
  `/miniview/tick_extra`, nothing between: a tick of named values with no pose
  (`begin_signals(t, values)`, `end_tick()`, or `add(t, "signals", {"values": {...}})`). A tick
  another message interrupts is dropped and counted as a reject. Frames: `/belief/pose`,
  `/depth`, `/map` in `map`; `/truth/pose` in `world`; `/tf` is `world` <- `map` (parent `world`,
  child `map`). The recorder: `begin_tick`, `tick_truth`, `tick_depth`, `tick_command`, `tick_tilt`,
  `end_tick`, or `add(t, "tick", ...)`. **Clocks:** `t` only grows; `t_src` is the source's own clock
  (monotonic or wall, whichever stamped the record), may restart between goals, and is kept for
  provenance (it is the messages' `publish_time`), never used to order records. **Depth kinds:** one
  ASCII character, `f` floor, `o` obstacle, `v` overhead, `b` below the floor; any other is written
  as it is and drawn as `o`. The messages:

  | Topic | Schema | Holds |
  | --- | --- | --- |
  | `/belief/pose` | `foxglove.PoseInFrame` (frame `map`) | a tick's belief; **first** message of a tick |
  | `/truth/pose` | `foxglove.PoseInFrame` (frame `world`) | the simulator's truth (if any) |
  | `/depth` | `foxglove.PointCloud` (frame `map`; fields x, y, z, `kind` = the ASCII of f/o/v/b) | the tick's depth returns |
  | `/miniview/command` | `miniview.command` | `{vx, vyaw}` |
  | `/miniview/tilt` | `miniview.tilt` | `{tilt}` |
  | `/<robot>/signals` | `miniview.Signals` (protobuf, built from the run's `signals`) | one optional field per declared signal (a double or a string); absent = no value; **first** message of a signals tick |
  | `/miniview/tick_extra` | `miniview.tick_extra` | `{t_src, raw}`: every other source field; **last** message of a tick |
  | `/tf` | `foxglove.FrameTransform` (`world` <- `map`) | an epoch: the map to world transform from this time on |
  | `/map` + `/miniview/memory` | `foxglove.Grid` (cells as bytes) + `miniview.memory` (`{obstacles, drops, raw}`) | a map snapshot; `memory` last |
  | `/miniview/plan` | `miniview.plan` | `{path, t_src, raw}` |
  | `/miniview/objects` | `miniview.objects` | the semantic map (ADR-0018): `{objects, changes, t_src, raw}`; an object `{id, kind, x, y, n, confirmed, landmark, permanence, first_t, last_t, confidence, sources, evidence, parts}` in the map frame, a part `{x, y, hx, hy, yaw, z0, z1}` (a list in the record), a change `{change: "new" or "confirmed", id}`; the whole map at that time. No Foxglove schema |
  | `/miniview/look` | `miniview.look` | a camera look (ADR-0018): `{pose, hfov_deg, range_m, seen, t_src, raw}`; `pose` the belief `[x, y, yaw]` in the map frame, `seen` `{kind, x, y, radius, z0, z1, range_m, confidence, source}` relative to the robot (x ahead, y left). No Foxglove schema |
  | `/depth/raw` | `foxglove.RawImage` (frame `tof`, `16UC1`, one row per sensor row) | **a depth frame** (ADR-0014): the sensor's raw distances in mm, the first message of the frame; a negative distance is kept as the int16's 16 bits |
  | `/depth/status` | `foxglove.RawImage` (frame `tof`, `mono8`) | the frame's per-zone statuses (5 and 9 are "range valid") |
  | `/miniview/depth_frame` | `miniview.depth_frame` | `{rows, cols, frame_t_ns, seq?, state_t_ns?, pair_dt_ms?, t_src?, state?, pose?, derived?}`: **last** message of a depth frame. `frame_t_ns` is the sensor's own clock (CLOCK_MONOTONIC), `state_t_ns` the robot state the frame was paired with (the nearest by time among those received, as Pollen's `autod` does) and `pair_dt_ms` that state's time minus the frame's; `state` is what a replay needs of it (`quat`, `odom_z`, `tof: {pos, quat}`), `pose` the robot's map pose the frame's points were placed with, `derived` what the robot made of the frame (`points` as `{x, y, z, k}` in the map frame, `drop_points` as `{ahead, left, h}`, `block_m`) |
  | `/miniview/event` | `miniview.event` | `{kind, text, notable, t_src, raw, decision?, room?, votes?}` (`room` and `votes` on a `room` event: the room the robot believes it is in, or null, and its votes, ADR-0018); routine events have `notable: false`; `decision` is `{rule, reason, values}`: the rule that fired and the values it compared (ADR-0014) |
  | `/miniview/segment` | `miniview.segment` | a goal's span: `{index, goal?, outcome?, origin_src, t_start, t_end}`, written when it ends (a goal-ending event with a goal) |
  | `/miniview/end` | `miniview.end` | `{verdict, source_sha256?}` |

  **A depth frame** (ADR-0014) is a record of its own, not a part of a tick: `/depth/raw`,
  `/depth/status`, `/miniview/depth_frame` in that order, nothing between, one flush; it may be
  written between two ticks (a robot that sees 15 frames a second and moves 10 times a second writes
  both as they come). The tick's `/depth` stays: the frame's derived points as the viewer draws them.
  A frame another record interrupts is dropped and counted as a reject. The reader's view of a frame
  is `{rows, cols, distance_mm, status, frame_t_ns, seq?, state_t_ns?, pair_dt_ms?, state?, pose?}`
  (`distance_mm` and `status` as lists, row-major); `state` (the paired state: `quat`, `odom_z`,
  `tof: {pos, quat}`) and `pose` (the map pose the frame's points were placed with) are kept for the
  robot's eye (RFC-0013: where the sensor was), `derived` and `t_src` are for a replay (a reader with
  `keep_raw`), not for the pages.

  `raw` holds every source field a message has no field of its own for; non-finite numbers in it are
  the strings
  `"inf"`, `"-inf"`, `"nan"`. A tick is read only when its last message has arrived.
- **Reading** (ADR-0008): every record is checked per kind (required fields, types, lengths, finite
  numbers, time that
  does not go back); a bad one is skipped and counted (`rejects`, `first_error`). A run is
  **broken** when its file is
  not MCAP, its run record is missing or invalid, or its key is not its folder's: listed with its
  `error`, not loaded.
  A file replaced or cut is read again from the start (`rewritten`).

## The index and run states (ADR-0009)

Tables `runs` (key, uuid, robot, scene, kind, status, verdict, started_at_ns, t0, t1, ticks, events,
rejects,
first_error, error, rewritten, epochs, size, mtime_ns, inode), `streams`, `events`, `segments`,
`scenes`. WAL with a busy
timeout; `miniview index` (the rebuild) refuses while a service holds the index. States: `live` (a
writer whose PID is
alive, or growth in the last 120 s), `ended`, `stopped` (no live writer, no growth for 120 s),
`broken`; the last three
are final until the file changes (size, mtime, inode). A restart opens only runs that changed.

## The API, version 2 (ADR-0010)

| Endpoint | Answers |
| --- | --- |
| `GET /api/v1/health` | `{"ok": true, "runs": n, "data": path, "cache_mb": n}` |
| `GET /api/v1/scenes` | `{"format": 2, "scenes": [...]}` the scenes with their runs, newest first |
| `GET /api/v1/scenes/{id}` | a scene (below) |
| `GET /api/v1/runs?robot=&scene=&status=` | the runs, from the index |
| `GET /api/v1/runs/{robot}/{scene}/{run}` | the run (below), with `status` and `seq` |
| `.../frames?from=&to=` | the ticks in the window and only the plans and worlds they refer to (below) |
| `.../signals?from=&to=` | the signals ticks in the window, columnar (below) |
| `.../sensor?t=` | the raw depth frame at or before t, with its number, the count, the pairing (`state_t_ns`, `pair_dt_ms`) and, when recorded, the paired `state` and the `pose` (404 when the run has none) |
| `GET /watch/{robot}/{scene}/{run}` and `.../latest` | the watch page (below), HTML; `latest` is the scene's newest run; 400 for a part that is not `[a-z0-9_-]+`, 404 for a run that does not exist or a scene with no run yet |
| `.../state?t=` | belief, truth, distance, depth returns, the last event at t |
| `.../events?kinds=` | what happened, when |
| `.../presence` | per stream, the spans or times it has data |
| `.../live?since=SEQ` | Server-Sent Events, below |
| `GET /api/v1/robots` | the robots with a description (`robots/<robot>/robot.urdf` under `MINIVIEW_ROBOTS`, default the repository's `robots/`): `[{"name", "label", "description": true, "links", "joints", "meshes", "meshes_missing", "simulator", "backend"}]` (RFC-0011 §3.4; the rest from `robot.json`) |
| `GET /api/v1/robots/{robot}` | its description: `{"name", "label", "root", "links": [{"name", "visuals": [{"mesh", "url", "origin": {"pos", "quat"}, "rgba"}]}], "joints": [{"name", "type", "parent", "child", "origin", "axis", "lower", "upper"}] (from the root out), "meshes_missing": [...], "stand_z": m \| null}` (`stand_z`: the root's height standing, from `robot.json`); 404 for an unknown robot |
| `GET /api/v1/robots/{robot}/meshes/{file}.stl` | a mesh of the description (`model/stl`, with an ETag); 404 for a missing mesh, a file that is not a mesh or a path out of the robot's folder |
| `GET /api/v1/render` | the render service's `GET /engines` (`{"engines": [{"name", "available", "why", "robots"}]}`), or `{"available": false, "why": "no render service configured" \| "render service not answering: ..."}` |
| `POST /api/v1/runs/{robot}/{scene}/{run}/video` | body `{"engine", "from"?, "to"?, "size"?: "1280x720"}`; 202 `{"id"}`; the render service's 400, 404, 409 (one job at a time) and 503 come through with its reason |
| `GET /api/v1/videos/{id}` | the job: `{"id", "run", "engine", "status": "queued" \| "running" \| "done" \| "failed", "error", "file"}` |
| `GET /api/v1/videos/{id}/file` | the finished video, `video/mp4`; 409 until the job is done |

- **Errors are JSON** (`{"error": ...}`): 400 (a number that is not one, `from` after `to`, a key
  with other
  characters, a negative `since`), 404, 405, 409 (no ticks yet; a broken run), 500 with an `id` that
  is also in the log.
  The connection is never dropped without an answer.
- **gzip** for JSON over 1 KB when the client accepts it; static files carry an ETag
  (`If-None-Match` answers 304),
  vendored libraries and fonts are cached for a day; request sockets time out after 30 s except live
  streams.
- **Live.** `live` sends one event per record, named by its kind (`tick`, `signals`, `plan`, `world`,
  `event`, `depth_frame`, `epoch`, `segment`, `end`), the record (with its `t`) as data and its `seq`
  as the event id; then
  `status` (`{"status", "seq", "t1", "generation"}`, with `"done": true` last, and `error` for a broken
  run). It resumes after `Last-Event-ID` (what a reconnecting client has just seen), or after `since`
  when there is no such header. A heartbeat comment every 15 s; a client that stops reading is dropped
  after 60 s. A run whose file was rewritten has a new `generation` (in its summary and in every
  status): the stream sends `rewritten` and ends, and the client starts over. `HEAD` answers with the
  headers only.

- **Video (ADR-0017).** The four routes above pass through to the render service
  (`miniview render-serve`, `GET /engines`, `POST /jobs`, `GET /jobs/{id}[/file]`) whose address is
  the environment variable `MINIVIEW_RENDER` (read at each request; unset: no render service).
  miniview writes nothing: the service reads the runs from the same data folder and keeps the videos
  in its own `<state>/videos/`. One job at a time. `from` and `to` are run times in seconds (the
  whole run when absent); `size` is `1280x720` or any `WIDTHxHEIGHT`.
- **A run of a scene with no `scene.json`** (the NXT's `unmapped`, ADR-0013) is listed under its scene
  (`kind` `no layout`); `GET /scenes/{id}` for it is a 404 and the pages draw none of a scene.
- **Signals.** `.../signals?from=&to=` (time window, both optional; 400 for `from` after `to`)
  answers `{"i0": 12, "n": 281, "t": [...], "v": {"power_left": [50.0, null, ...], ...}}`: the
  samples in the window, `i0` the first one's number in the run, `n` how many the run has, `null`
  where a sample had no value for that signal. `state` adds `signals` (`{t, index, n, values}`: the
  sample at or before `t`); a run with no pose answers `state` with `tick: null` and the signals;
  `presence` has `signals.<name>`
  spans; `frames` of a run with no pose is an empty window.

### `GET /api/v1/scenes/{id}` — what is really there (world frame)

```json
{"id": "apartment", "frame": "world", "bounds": [-4.0, 4.0, -3.0, 3.0],
 "boxes": [{"name": "off_cabinet", "cx": 0.85, "cy": 0.0, "z0": 0.0, "z1": 0.6,
            "hx": 0.18, "hy": 0.18, "yaw": 0.0}],
 "hazards": [{"name": "stairs", "kind": "drop", "x0": -0.4, "x1": 0.0, "y0": -1.4, "y1": -0.7,
              "depth": 0.3}]}
```

`boxes` are oriented boxes (centre, half sizes in x and y, bottom and top z, yaw). Cylinders are
given
as boxes with equal half sizes. A hazard is the rectangle `x0..x1` × `y0..y1`, turned by an optional
`yaw` (radians) about its centre: a challenge scene's drop is turned with the start's jitter
(ADR-0015).

### `GET /api/v1/runs/{key}` — the run's summary

```json
{"id": "explore12", "key": "<robot>/<scene>/<run>", "uuid": "<36 characters>", "scene": "apartment",
 "robot": {"name": "duck", "radius": 0.083, "height": 0.272}, "kind": "exploration", "status": "ended", "seq": 516,
 "started_at_ns": 1794737292087483947, "started_at_source": "file_mtime", "t0": 24.962, "t1": 83.44, "ticks": 464,
 "verdict": "trapped", "rejects": 0, "first_error": null, "error": null, "rewritten": 0,
 "epochs": [{"from_t": 0.0, "map_to_world": [-0.018, 0.0, 0.0]}],
 "events": [{"t": 44.613, "kind": "cliff_stop", "text": "cliff_stop drop_m 0.589"}],
 "segments": [{"index": 0, "goal": [0.5, 0.14], "outcome": "refused", "t_start": 24.96, "t_end": 32.5}],
 "streams": [...]}
```

- `samples` is the number of signals ticks (0 for a robot with none), `signals` the declared signals,
  `odometry` and `no_pose` as in the run record.
- `t0`, `t1`: the span of every record (poses, signals, plans, maps, events), not only the poses.
  While a run is live,
  `verdict` is `live`. `status` is `live`, `ended`, `stopped` or `broken`.
- `epochs`: the map to world transform from a time on (a reset simulator starts a new map; phase-1
  evaluations have one
  epoch per goal). The data view ignores epochs and draws the map frame as it is.
- `events`: the notable ones only (stops, refusals, recoveries, ends, the navigator's glances); every
  event is in the file. A recording that wrote a `glance` as not notable is read as notable all the
  same (`wire.ALWAYS_NOTABLE`).
- `streams`: what the run holds, one entry per stream in tree order, counts kept as records arrive:

  ```json
  [{"id": "belief.pose", "group": "Robot (belief)", "name": "pose", "frame": "map", "count": 464,
    "rate_hz": 8.8, "missing": false, "time_modes": ["at", "window", "upto"], "default_mode": "at"},
   {"id": "sensors.tilt", "group": "Sensors", "name": "tilt", "frame": "robot", "count": 0,
    "missing": true, "why": "not in this run"}]
  ```

  Ids: `scene.boxes`, `scene.hazards`, `belief.pose`, `belief.track`, `truth.pose`, `truth.track`,
  `sensors.depth` with children `sensors.depth.floor|obstacle|overhead|below`, `sensors.tilt`,
  `sensors.raw` (the raw depth frames: count, rate, spans; shown in the inspector, drawn in no view),
  `world.grid`, `world.obstacles`, `world.drops`, `world.gaps` (derived by the page, not recorded:
  the unknown cells of the map in force within 0.45 m of the plan in force; its count is the number
  of maps, 0 while the run has no plan), `plan.path`, `events`, and one per declared signal,
  `signals.<name>` (group `Signals`, frame `time`, with `kind` and `unit`, no time modes). A stream
  of a run with no pose says why in `why` (the run's `no_pose`). Time modes: `at`, `window` (the
  last N seconds before t), `upto` (everything up to t).

### `GET /api/v1/runs/{key}/frames` — a window, by tick

```json
{"t": [0.1, 0.2], "i0": 120, "ticks": 464,
 "belief": [[x, y, yaw], ...],            "map frame (the robot's own)"
 "truth": [[x, y, yaw] | null, ...],      "world frame; null on a real robot"
 "truth_3d": [{"z": m, "quat": [w, x, y, z]} | null, ...],   "the truth's height and whole orientation (ADR-0016); null when not recorded"
 "tilt": [[pitch_deg, roll_deg] | null, ...],
 "cmd": [[vx, vyaw], ...],
 "depth": [[[x, y, z, "f|o|v|b"], ...] | null, ...],   "map frame; null = no new frame that tick"
 "plan_at": [i, ...],                     "per tick: the number of the plan in force, or -1"
 "world_at": [i, ...],                    "per tick: the number of the map in force, or -1"
 "plans": {"5": {"t": 1.0, "path": [[x, y], ...]}},    "only the plans the window's ticks refer to, by number; map frame"
 "worlds": {"3": {"t": 1.0, "grid": {"res": 0.0455, "origin": [x, y], "w": 82, "h": 92, "cells": "?.#..."},
                  "obstacles": [[x, y], ...], "drops": [[x, y], ...]}}}  "the maps (world model snapshots), same way"
```

- `i0` is the first tick's index in the run, `ticks` the run's tick count at the time of the answer.
  `t` is the run's time,
  increasing (evaluation runs are laid end to end). Without `from` and `to` the window is the whole
  run. The frames of a run with no ticks yet are a
  200 with empty lists (`state` and `presence` are a 409).
- Depth kinds: `f` floor, `o` obstacle, `v` overhead, `b` below the floor (a hole).
- Grid cells are row-major from the lowest y: `?` unknown, `.` free, `#` occupied; cell (i, j) has
  its
  centre at `origin + ((i + 0.5) res, (j + 0.5) res)`.

## The pages (ADR-0011)

The two pages are one workbench (`web/shell/`: top bar, outliner, properties, inspector, timeline,
themes) with a
renderer adapter each (`web/three/app.js`, `web/deck/app.js`). The view area is the element
`#stage`; the status chip
`#runinfo` reads "robot · kind · verdict · length · N ticks"; `#follow` (with `#follow-on`) shows
only while the run is
live. `#exportBtn` ("Export video") is enabled when the render service lists an available engine
for the run's robot (its title says why when not); it opens a panel (engine, from, to, size, Start;
then the job's status, a `<video>` and a download link). Fonts (Inter, JetBrains Mono; OFL, licences
in `web/fonts/`) are served by the service: no request leaves the machine.

**The run store** (`web/shell/runstore.js`, shared by both renderers): the run's summary; then the
window of ticks
around the playhead, from 30 s before it to 30 s after, wherever in the run it is, so the page draws
at once; then the
rest in the background, in windows of 60 s outwards from what is loaded, nearest the playhead first;
plans and worlds
by number as ticks refer to them; then the live stream, applied in order. `seq` is checked: a gap
reconnects from the
last seq held. The frames the renderers read are indexed by the tick's number in the run and have
holes where a tick is
not loaded (`frames.ranges` lists what is, as sorted `[first, end)` pairs). A seek into a part that
is not loaded loads
the window around it first (`setTime` waits for it); the playhead shows the nearest loaded tick meanwhile.

**Script API.** Every page exposes `window.miniview` and sets `window.__ready = true` after its
first draw, and again after
each call once it has drawn (set it to `false` before calling, then wait for `true`):

```text
load(scene, run)            setTime(t)                  setView("top|front|back|left|right|three|3d|eye|chase|watch")
setFrame("world|map")       setVisible(streamId, bool)  setTimeMode(streamId, "at|window|upto", seconds)
setRelation("belief_truth|depth_pose", bool)            setViewVisible(view, streamId, bool)
setOverlay("coords|gizmo|legend|hazards_top", bool)
select({kind, index})       scenes()
setSection(id, open)        setAngles(bool)
explore(robot?)             explorePart(link|null)      explorePose("recorded|hand")
exploreJoint(name, radians) exploreHide(link, bool)     exploreIsolate(link|null)
state()     -> {tab, angles, robot, sections: [{id, name, open, streams}], run, scene, status, seq, follow,
                loaded: {ticks, of, complete, ranges}, t, tick, tick_t, frame, view, belief, belief_map, truth, distance,
                last_event, selection, t_range, hidden, eye, alerts, decided}
config()    -> {modes, on, vv, size, kinds, play, rel, overlays, view, frame, theme, follow, scene, run}   plain data
whenLoaded() -> resolves with {ticks} when every tick of the open run is loaded
exploreState() -> {robot, kind, pose, selected, hidden, isolated, why, links, drawn, values, poses}   (null before Explore opens)
exploreSnapshot() -> the body as a PNG data URL
```

- **The left panel by meaning** (UXS-001, 2026-11-16). The outliner's top level is five sections:
  World (`sec.world`: the scene's `g.scene`, the truth's `g.truth`), Body (`sec.body`: the robot's
  3D model `body.model`, its joints by chain `g.chain.<chain>`, from the robot's description, or
  `g.joints`), Senses (`sec.senses`: depth, the raw frame, `g.imu`), Mind (`sec.mind`: `g.belief`,
  `g.world` the world model, the plan, the events) and Other values (`sec.other`: the signals that
  belong to none). A joint is the signal `joint_<name>` (ADR-0016), shown by its name with its
  angle at the playhead in degrees (`[data-angle]`; `setAngles(false)` hides them). Sections are
  closed until a viewer opens them, except the one holding the selected stream; what a viewer
  opened and the angles switch are remembered in the browser (`localStorage` `miniview.left`).
  The timeline's rows and the Moment's signals follow the same order. `setVisible` and
  `setSection` take a node id or a name; the names before the sections still resolve (`Sensors`
  is Senses, `Robot` Body, `Signals` Other values).
- **The Robot layer** (RFC-0011 §3.2, the three.js page): the run's robot's body in the views
  (`body.model`, its eye in the Body section): in the world frame of a run with `truth_3d`, the
  root link (the trunk) at the truth's whole pose; otherwise at the belief's x, y and yaw in the
  frame looked at, tilted by `tilt`, at the registry's `stand_z`. The joints at the playhead.
- **The robot's eye, what it decided and the watch page** (RFC-0013, prototype; the three.js page
  only, `createShell(adapter, {eye: true, watch})`).
  - **Views `eye`, `chase`, `watch`** (`setView`, `#view=` of the URL hash; the layout switch has Eye
    and Chase buttons): perspective cameras in the **world frame** (choosing one sets the frame to
    world; `setFrame("map")` is refused while one is on). `eye` is the depth sensor's camera at the
    playhead: the pose comes from the depth frame at or before it (`/sensor?t=`, `state` + `pose`,
    through the epoch in force: the navigator's own geometry, `web/shell/eye.js`, with the 3 degree
    pitch offset of `duck_lab.nav.cliff`; `source: "recorded"`), else is **estimated** from the tick's
    trunk pose (`truth_3d` and truth, else belief and tilt) and a nominal mount
    (`eye.js` `NOMINAL_MOUNT`; `source: "estimated"`). While the frame is being asked for the camera
    stays where it was. The robot's own markers and body are not drawn in `eye`. Outside the sensor's
    45 degree square (`#eyecone`) the view is darkened. `chase` is 0.9 m behind and 0.55 m above the
    robot (truth, else belief). `watch` is the eye with the top view as an inset (`watch` layout).
  - **The HUD** (`#eyehud`, over `eye` and `watch`): `#hudtxt` (pace = the tick's `cmd`, the newest
    event with its rule and reason, the numbers of its `decision.values`, this frame's returns by
    kind, where the sensor pose came from) and `#hudcv` (the 8 x 8 distances, one pixel per zone).
    Recorded values and values computed from them only. Over them, an **alert** (`.alert` in
    `#hudtxt`, `state().alerts` `[{kind, phase, t, rule, html}]`, the two newest) for what the
    navigator did that RFC-0012 calls attention: a `cliff_stop` (STOPPED) and a `glance` (a look
    with the head at a suspected drop). An event is written when it ends, so a glance is LOOKING for
    its decision's `values.time_s` before its event (bearing and distance only, no result yet) and
    LOOKED after (what it saw and the edge); both are held 4 s after (`eye.js` `attentionAt`). Only
    recorded events, never what a rule would have done.
  - **Gaps** (`world.gaps`, in the World model group, drawn by the three.js page only): the map
    in force's unknown cells within `GAP_MARGIN_M` = 0.45 m (RFC-0012's drop margin,
    `web/shell/gaps.js`, which also holds the pure `gapCells(grid, path, margin)`) of the plan in
    force, tinted orange with a hatch; the other unknown cells as a faint fog. The adapter's
    `gaps()` says how many of each are drawn. **`setOverlay("hazards_top", true)`** (the Overlays
    popover, "Real hazards over the model"; off in the explorer, on in the watch page) draws the
    scene's hazards again as a dashed outline over the other layers.
  - **Decided** (`#tabDecided`, the right panel's fourth tab, `state().tab === "decided"`): the run's
    events (those not switched off in the Events popover) as `.dec` rows with `data-t` = the event's
    time: the rule (the decision's, else the kind), the reason, the values it compared; a stop is
    `.hot`, the judge's `invariant` and the final **verdict** row (a run that is not live) `.judge`;
    the last row at or before the playhead is `.now`; a click (or Enter) seeks to its time.
    `state().decided` is `{n, now}` (rows, and the time of the one at the playhead or null);
    `state().eye` is the eye camera as drawn `{source, frame_t, position, forward, up, fov}` while
    `eye` or `watch` is the view, else null.
  - **The watch page**: `GET /watch/<robot>/<scene>/<run>` or `.../latest` serves
    `web/three/watch.html` (the same `app.js`, which reads the run from the path; `<base>` keeps
    its files under `/web/three/`). Layout: the `watch` view (the eye, the top view inset, real
    hazards on), the Decided tab as the whole right panel, the timeline with the events marked (no
    data rows), buttons Eye, Above (top) and Both (watch); Follow live is on, as in the explorer, and
    a live run is followed. `latest` opens the scene's newest run (`/api/v1/runs?robot=&scene=`,
    newest first) and, once that run is not live, checks every 4 s for a newer one and opens it.
  - **Links at the same moment**: the explorer's `#watchLink` ("Watch") is
    `/watch/<robot>/<scene>/<run>#t=<playhead>`; the watch page's `#exploreLink` ("Explorer") is
    `/web/three/#scene=&run=&view=eye&frame=world&t=<playhead>`. A page opened with `#t=<seconds>` in
    its hash puts the playhead there once the run is open (Follow live turns off, as with any seek).
- **Explore** (RFC-0011 §3.3): the right panel's third tab (`#tabExplore`, `#explore`), a detail
  view whose first kind is a robot's body (the run's robot, or any of `GET /api/v1/robots`). The
  description's meshes placed by the pages' forward kinematics (`web/shell/robot.js`, the same as
  `miniview.kinematics`, checked against `robots/duck/fk_fixture.json`), posed **as recorded** (the
  joints' values at the playhead, following it) or **by hand** (a slider per joint by chain, within
  its limits; it starts from the recorded pose). A part is picked in the body or in the list of
  parts; its details: what moves it (joint, type, axis, angle, limits) or what it is fixed to, what
  it hangs from and carries, where it is from the root, its meshes (no mass: the description has
  none). Isolate, hide, show all, focus; "Expand" widens the right panel. three.js is loaded when
  Explore first opens (the deck.gl page has the same import map as the three.js page).
- **Signals** (ADR-0013). A run with `signals` has a row and an eye per signal in the outliner
  (in its section; a run with signals only selects the first, so its section is open), the values
  at the playhead in the inspector's Moment (the sample at or before it,
  with its number), and a data row per signal in the timeline. A run with signals and **no pose**
  has no spatial view: the viewport is the **Signals view** (`#sigview`, `web/shell/signals.js`): a
  chart per numeric signal and a band per text signal on one time axis with the playhead; a click
  or a drag on a chart (`.sg-p`) seeks; the layout and frame buttons are hidden, the streams the
  run lacks are hidden ("Show them"), "tick" reads "sample" and the status chip counts samples.
  The run store loads every
  sample when the run opens (`GET .../signals`, in windows) and takes the later ones by record.
  `state()` adds `signals` (`{i, n, t, values}` for the sample at or before the playhead) and
  `loaded.samples`; a run with no pose answers `tick: 0` and `belief: null`.
- `load(scene, run)`: `run` is the key, or a name only one run of that scene has. It **rejects** (an
  `Error`) for an unknown
  scene, an unknown run or an ambiguous name (listing the keys), and leaves the open run as it was.
  `load()` with no
  arguments shows the scenes page; `load(scene)` opens the scene's newest run.
- `state()` names the run (`run` is its key, null on the scenes page), its `status`, the `seq` the
  page has applied, and
  `follow`. `tick` is the 0-based index; the page shows it 1-based, "tick 457 of 464".
- **Follow live is a mode**: it pins the playhead to the newest tick of a live run. Any change of
  time (`setTime`, a click on
  the timeline or the transport, a key, playback) turns it off, and the switch shows it; the switch
  turns it on again.
- `setTime(t)` waits for the ticks up to `t` to be loaded. `select` takes a depth return (`{kind:
  "depth", index}`, the index being `tick * 100000` plus
  the point's place in its tick), a robot (`{kind: "robot", index: 0 belief | 1 truth}`) or a map cell
  (`{kind: "cell", index, world}`); `select(null)` clears.
  `setVisible` takes a stream id, a group or a section (`g.belief`, `Senses`, `sec.mind`, ...).
- `miniview.internals` (the model, the store and the renderer adapter) is **for this repository's
  tests only**; scripts use
  the functions above.
- Display > Point size and Line width, per stream in pixels, apply in both renderers
  (`config().size`). A 1 m scale bar
  (`#scale`, `data-m`, `data-px`) sits at the bottom-left of the viewport in the orthographic views;
  the cursor readout
  (`#readout`) names the axes of the view under the pointer. In the timeline, hatched bands
  (`#dlanes .gap`) mark where
  the run has ticks but no depth frames.
- Event kinds from a file are compared as text, never used as code or as a pattern.

### Renderer adapters (what `web/shell/shell.js` calls)

```text
init(stage, shell)      setScene(scene)         setRun(run, frames)     append(range)       setLayout(view, frame)
draw(sync)              settled() -> Promise    resize()                fit()               theme(palette)
describe(sel)           cursor(clientX, clientY) -> {axes, v, note?} | null
gizmo() -> {x, y, z}    camera-space axes (3D only)
scale() -> px per metre of the first orthographic pane, or null (3D)
fillsDrawn(pane) -> bool   whether the faint box faces are drawn in the pane named so
project([x, y, z]) -> [clientX, clientY] | null   where a world point falls in the first pane (tests probe pixels there)
eye() -> {source, frame_t, position, forward, up, fov} | null   the eye camera as drawn (three.js page; the shell gives it `shell.eyePose()` and
                           is called back with `shell.drawn()` after each draw)
eyeView() -> {fov, h} | null   the eye camera's field of view and its pane's height in pixels      gaps() -> {gap, fog, visible} | null
returns(i) -> {f, o, v, b: [[x, y, z]]} | null   tick i's returns as drawn, by class, in the world frame
```

`setRun(run, frames)` gives the run and the frames loaded so far (ticks by their number in the run,
holes where a tick
is not loaded, `frames.ranges` saying where; plans and worlds by number, only those a loaded tick
refers to; the frames
also carry `tickAt(t)`, `firstAt(t)` and `firstAfter(t)` over the loaded ticks).
`append({i0, i1, plans: [k, ...], worlds: [k, ...]})` says what was added: the ticks `i0..i1-1`,
**wherever they are in
the run** (a window in the middle of a long run, or the next tick of a live one), and the plan and
world numbers that
became available. Nothing is rebuilt: three.js packs ticks into buffers indexed by tick (a track's
segment exists once
both its ticks do) and depth returns per stretch of loaded ticks; deck.gl prepares only what was
added, one layer per
stretch. An epoch that arrives behind drawn ticks makes the shell call `setRun` again: what depends
on the epoch is drawn
again. The shell gives the adapter `M` (the model), `shown(id, view)`, `cfg(id)`, `size(id)`, `pick(sel)`,
`viewChanged()`, `tickAt(t)` and `palette()`. The 3D views of both pages start from the same camera;
`viewer/tests/test_ui.py` checks that six world points land on the same pixels.

## Commands (the agent's face)

`miniview scenes | runs <scene> | events <key|name> [--kinds a,b] | events --all --kind K | state
<run> --at t | sensor <run> --at t [--json] |
frame | film | import | repair <key> | compact <key> | index | serve`. `import --robot nxt <run>.csv
[--scene S] [--tz ZONE] [--sprocket-diameter M --track-width M] [--config PATH]` imports an nxt-web
recording (ADR-0013); `state` of a run with signals prints them. While a service holds the
index the
commands read it and write nothing (one index, ADR-0012); `compact` closes a finished run whose
writer did
not, `repair` a run whose writer died, both only for a file that has not grown in the last two
minutes. A run
is named by its key or by a name only one run has;
otherwise the command lists the candidates. `--data` or `MINIVIEW_DATA` names the data folder.

## Colours (UXS-001)

belief `#4682ff`, truth `#28b45a`, plan `#e6b400`, obstacles `#ff9600`, hazards and drops `#e600e6`,
depth f `#3cc85a`, o `#e63228`, v `#3c78e6`, b `#e600e6`, occupied `#505050`, free `#cdeccd`,
axes x `#e03030` y `#30b030` z `#3060e0`, scene boxes `#8a8a96`.
