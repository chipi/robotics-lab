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
  source?: {name, sha256}}`. A run whose record disagrees with its folder is broken.
- **Time**: `log_time = started_at_ns + t` (UTC nanoseconds; `t` is the run's time and only grows);
  `publish_time` is the source's own clock (each tick also keeps `t_src`).
- **Writer**: one, with `writer.lock` (`{pid, host, started_at_ns}`) created exclusively; it refuses
  a run that exists.
  Every record is flushed when it is written; a crash loses at most the tick being written. At the
  end: `end`
  (`{verdict}`), then `run.mcap`, then the live file and the lock are removed. `miniview repair
  <key>` closes a dead
  writer's run with the verdict `stopped`.
- **Messages**: the Foxglove channels (`/belief/pose`, `/truth/pose`, `/depth`, `/tf`, `/map`) are
  protobuf with a
  `FileDescriptorSet` schema (the `foxglove-schemas-protobuf` package); ours (`miniview.*`) are JSON
  with JSON schemas.
  Foxglove's published JSON schemas stay copied in `src/miniview/schemas/` as the reference tests
  check against:

  | Topic | Schema | Holds |
  | --- | --- | --- |
  | `/belief/pose` | `foxglove.PoseInFrame` (frame `map`) | a tick's belief; **first** message of a tick |
  | `/truth/pose` | `foxglove.PoseInFrame` (frame `world`) | the simulator's truth (if any) |
  | `/depth` | `foxglove.PointCloud` (frame `map`; fields x, y, z, `kind` = the ASCII of f/o/v/b) | the tick's depth returns |
  | `/miniview/command` | `miniview.command` | `{vx, vyaw}` |
  | `/miniview/tilt` | `miniview.tilt` | `{tilt}` |
  | `/miniview/tick_extra` | `miniview.tick_extra` | `{t_src, raw}`: every other source field; **last** message of a tick |
  | `/tf` | `foxglove.FrameTransform` (`world` <- `map`) | an epoch: the map to world transform from this time on |
  | `/map` + `/miniview/memory` | `foxglove.Grid` (cells as bytes) + `miniview.memory` (`{obstacles, drops, raw}`) | a map snapshot; `memory` last |
  | `/miniview/plan` | `miniview.plan` | `{path, t_src, raw}` |
  | `/miniview/event` | `miniview.event` | `{kind, text, notable, t_src, raw}`; routine events have `notable: false` |
  | `/miniview/segment` | `miniview.segment` | a goal's span: `{index, goal?, outcome?, origin_src, t_start, t_end}`, written when it ends (a goal-ending event with a goal) |
  | `/miniview/end` | `miniview.end` | `{verdict, source_sha256?}` |

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
| `.../state?t=` | belief, truth, distance, depth returns, the last event at t |
| `.../events?kinds=` | what happened, when |
| `.../presence` | per stream, the spans or times it has data |
| `.../live?since=SEQ` | Server-Sent Events, below |

- **Errors are JSON** (`{"error": ...}`): 400 (a number that is not one, `from` after `to`, a key
  with other
  characters, a negative `since`), 404, 405, 409 (no ticks yet; a broken run), 500 with an `id` that
  is also in the log.
  The connection is never dropped without an answer.
- **gzip** for JSON over 1 KB when the client accepts it; static files carry an ETag
  (`If-None-Match` answers 304),
  vendored libraries and fonts are cached for a day; request sockets time out after 30 s except live
  streams.
- **Live.** `live` sends one event per record, named by its kind (`tick`, `plan`, `world`, `event`,
  `epoch`, `segment`,
  `end`), the record (with its `t`) as data and its `seq` as the event id; then `status`
  (`{"status", "seq", "t1"}`, with `"done": true` last, and `error` for a broken run). It resumes
  after `since`, or
  after `Last-Event-ID` when `since` is absent. A heartbeat comment every 15 s. A run whose file was
  rewritten sends
  `rewritten` and ends: the client starts over. `HEAD` answers with the headers only.

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
as boxes with equal half sizes.

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

- `t0`, `t1`: the span of every record (poses, plans, maps, events), not only the poses. While a run
  is live,
  `verdict` is `live`. `status` is `live`, `ended`, `stopped` or `broken`.
- `epochs`: the map to world transform from a time on (a reset simulator starts a new map; phase-1
  evaluations have one
  epoch per goal). The data view ignores epochs and draws the map frame as it is.
- `events`: the notable ones only (stops, refusals, recoveries, ends); every event is in the file.
- `streams`: what the run holds, one entry per stream in tree order, counts kept as records arrive:

  ```json
  [{"id": "belief.pose", "group": "Robot (belief)", "name": "pose", "frame": "map", "count": 464,
    "rate_hz": 8.8, "missing": false, "time_modes": ["at", "window", "upto"], "default_mode": "at"},
   {"id": "sensors.tilt", "group": "Sensors", "name": "tilt", "frame": "robot", "count": 0,
    "missing": true, "why": "not in this run"}]
  ```

  Ids: `scene.boxes`, `scene.hazards`, `belief.pose`, `belief.track`, `truth.pose`, `truth.track`,
  `sensors.depth` with children `sensors.depth.floor|obstacle|overhead|below`, `sensors.tilt`,
  `world.grid`, `world.obstacles`, `world.drops`, `plan.path`, `events`. Time modes: `at`, `window`
  (the last N seconds
  before t), `upto` (everything up to t).

### `GET /api/v1/runs/{key}/frames` — a window, by tick

```json
{"t": [0.1, 0.2], "i0": 120, "ticks": 464,
 "belief": [[x, y, yaw], ...],            "map frame (the robot's own)"
 "truth": [[x, y, yaw] | null, ...],      "world frame; null on a real robot"
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
  run.
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
live. Fonts (Inter, JetBrains Mono; OFL, licences in `web/fonts/`) are served by the service: no
request leaves the machine.

**The run store** (`web/shell/runstore.js`, shared by both renderers): the run's summary; then the
ticks up to the
playhead + 30 s in windows of 60 s, so the page draws at once; then the rest in the background, one
window per turn;
plans and worlds by number as ticks refer to them; then the live stream, applied in order. `seq` is
checked: a gap
reconnects from the last seq held. The loaded part is always the first ticks without a hole, because
renderers take
appends only: a playhead deep in a run loads the first ticks up to it, then draws.

**Script API.** Every page exposes `window.miniview` and sets `window.__ready = true` after its
first draw, and again after
each call once it has drawn (set it to `false` before calling, then wait for `true`):

```text
load(scene, run)            setTime(t)                  setView("top|front|back|left|right|three|3d")
setFrame("world|map")       setVisible(streamId, bool)  setTimeMode(streamId, "at|window|upto", seconds)
setRelation("belief_truth|depth_pose", bool)            setViewVisible(view, streamId, bool)
select({kind, index})       scenes()
state()     -> {run, scene, status, seq, follow, loaded: {ticks, of, complete}, t, tick, tick_t, frame, view, belief,
                belief_map, truth, distance, last_event, selection, t_range, hidden}
config()    -> {modes, on, vv, size, kinds, play, rel, overlays, view, frame, theme, follow, scene, run}   plain data
whenLoaded() -> resolves with {ticks} when every tick of the open run is loaded
```

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
  "depth", index}`), a robot
  (`{kind: "robot", index: 0 belief | 1 truth}`) or a map cell (`{kind: "cell", index, world}`);
  `select(null)` clears.
  `setVisible` takes a stream id or a group (`g.sensors`, `Sensors`, ...).
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
```

`setRun(run, frames)` gives the run and the frames loaded so far (ticks `0..n-1` without a hole;
plans and worlds by
number, only those a loaded tick refers to). `append({i0, i1, plans: [k, ...], worlds: [k, ...]})`
says what was added:
the ticks `i0..i1-1` and the plan and world numbers that became available; nothing is rebuilt
(three.js packs into buffers
that double when full, deck.gl prepares only what was added). An epoch that arrives behind drawn
ticks makes the shell call
`setRun` again: what depends on the epoch is drawn again. The shell gives the adapter `M` (the
model), `shown(id, view)`,
`cfg(id)`, `size(id)`, `pick(sel)`, `viewChanged()`, `tickAt(t)` and `palette()`. The 3D views of
both pages start from
the same camera; `viewer/tests/test_ui.py` checks that six world points land on the same pixels.

## Commands (the agent's face)

`miniview scenes | runs <scene> | events <key|name> [--kinds a,b] | events --all --kind K | state
<run> --at t |
frame | film | import | repair <key> | index | serve`. A run is named by its key or by a name only
one run has;
otherwise the command lists the candidates. `--data` or `MINIVIEW_DATA` names the data folder.

## Colours (UXS-001)

belief `#4682ff`, truth `#28b45a`, plan `#e6b400`, obstacles `#ff9600`, hazards and drops `#e600e6`,
depth f `#3cc85a`, o `#e63228`, v `#3c78e6`, b `#e600e6`, occupied `#505050`, free `#cdeccd`,
axes x `#e03030` y `#30b030` z `#3060e0`, scene boxes `#8a8a96`.
