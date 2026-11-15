# The API — what every miniview page reads (ADR-0005)

`miniview serve` (or `make viewer-up`, in Docker) serves the pages and the API over the lab's data
folder (ADR-0004: `MINIVIEW_DATA`, default `/work/robotics-lab/data`). Runs are stored as MCAP
(`runs/<robot>/<scene>/<run>/run.mcap`, one channel per record kind: `/miniview/run`, `epoch`,
`tick`, `plan`, `world`, `event`, `end`; JSON messages; log time = the run's t in nanoseconds);
`index.sqlite` beside them is derived. The pages read only the API below. Units SI (metres, radians,
seconds). Frames: **world** (the scene's, where truth is) and **map** (the robot's own). A pose is
`[x, y, yaw]`.

| Endpoint | Answers |
| --- | --- |
| `GET /api/v1/health` | `{"ok": true, "runs": n, "data": path}` |
| `GET /api/v1/scenes` | the scenes with their runs (below) |
| `GET /api/v1/scenes/{id}` | a scene (below) |
| `GET /api/v1/runs?scene=` | a scene's runs |
| `GET /api/v1/runs/{id}` | the run (below), with `status` (`live`, `ended`, `stopped`) and `seq` |
| `GET /api/v1/runs/{id}/frames?from=&to=` | the frames (below) for a time window; `i0` is the first tick's index |
| `GET /api/v1/runs/{id}/state?t=` | belief, truth, distance, depth returns, the last event at t |
| `GET /api/v1/runs/{id}/events?kinds=` | what happened, when |
| `GET /api/v1/runs/{id}/presence` | per stream, the spans or times it has data (the timeline's rows) |
| `GET /api/v1/runs/{id}/live?since=SEQ` | Server-Sent Events, below |

**Live.** A live run is a run whose file has not ended; it grows while a page watches. `live` sends
`tick`, `plan`, `world`, `event`, `epoch` and `end` events (data: the record with its `t`), then
`status` (`{"status", "seq", "t1"}`, with `"done": true` last); it resumes after `since`. `stopped`
is a live file that has not grown for 120 s (its writer is gone).

## `GET /api/v1/scenes`

```json
{"format": 1, "scenes": [{"id": "apartment", "name": "The simulated apartment", "kind": "apartment",
  "runs": [{"id": "explore12", "robot": "duck", "kind": "exploration", "status": "ended",
            "length_s": 58.5, "verdict": "trapped", "events": 23}]}]}
```

## `GET /api/v1/scenes/{id}` — what is really there (world frame)

```json
{"id": "apartment", "frame": "world", "bounds": [-4.0, 4.0, -3.0, 3.0],
 "boxes": [{"name": "off_cabinet", "cx": 0.85, "cy": 0.0, "z0": 0.0, "z1": 0.6,
            "hx": 0.18, "hy": 0.18, "yaw": 0.0}],
 "hazards": [{"name": "stairs", "kind": "drop", "x0": -0.4, "x1": 0.0, "y0": -1.4, "y1": -0.7,
              "depth": 0.3}]}
```

`boxes` are oriented boxes (centre, half sizes in x and y, bottom and top z, yaw). Cylinders are given
as boxes with equal half sizes.

## `GET /api/v1/runs/{id}` — the run's summary

```json
{"id": "explore12", "scene": "apartment", "robot": {"name": "duck", "radius": 0.083, "height": 0.272},
 "kind": "exploration", "status": "ended", "seq": 516,
 "t0": 24.962, "t1": 83.44, "ticks": 464, "verdict": "trapped",
 "epochs": [{"from_t": 0.0, "map_to_world": [-0.018, 0.0, 0.0]}],
 "events": [{"t": 44.613, "kind": "cliff_stop", "text": "cliff_stop drop_m 0.589"}]}
```

- `t0`, `t1`: the span of every record (poses, plans, maps, events), not only the poses: events can
  come before the first pose or after the last. While a run is live, `verdict` is `live`.

- `epochs`: the map → world transform from a time on (a reset simulator starts a new map; phase-1
  evaluations have one epoch per goal). To draw map-frame data in the world, use the epoch in force
  at that tick. The data view ignores epochs and draws the map frame as it is.
- `events`: the notable ones only (stops, refusals, recoveries, ends); routine records are left out.
- `streams` (v0.2): what the run holds, for the streams tree and its badges — one entry per stream,
  in tree order:

  ```json
  [{"id": "belief.pose", "group": "Robot (belief)", "name": "pose", "frame": "map", "count": 464,
    "rate_hz": 8.8, "missing": false, "time_modes": ["at", "window", "upto"], "default_mode": "at"},
   {"id": "sensors.depth.below", "group": "Sensors", "parent": "sensors.depth", "name": "below the floor",
    "frame": "map", "count": 737, "missing": false},
   {"id": "sensors.tilt", "group": "Sensors", "name": "tilt", "frame": "robot", "count": 0,
    "missing": true, "why": "not in this run"}]
  ```

  Ids: `scene.boxes`, `scene.hazards`, `belief.pose`, `belief.track`, `truth.pose`, `truth.track`,
  `sensors.depth` with children `sensors.depth.floor|obstacle|overhead|below`, `sensors.tilt`,
  `world.grid`, `world.obstacles`, `world.drops`, `plan.path`, `events`. Time modes: `at` (the value
  at t, or the latest before it), `window` (the last N seconds before t), `upto` (everything up to t).

## The page's script API (v0.2) — what the `miniview` commands call, headless

Every page exposes `window.miniview` and sets `window.__ready = true` after its first draw, and again
after each call below once it has drawn (set it to `false` before calling, then wait for `true`):

```text
load(scene, run)            setTime(t)                  setView("top|front|back|left|right|three|3d")
setFrame("world|map")       setVisible(streamId, bool)  setTimeMode(streamId, "at|window|upto", seconds)
setRelation("belief_truth|depth_pose", bool)            setViewVisible(view, streamId, bool)
select({kind, index})        state() -> {t, belief, truth, distance, last_event, selection}
```

`select` takes a depth return (`{kind: "depth", index}`, the point's place in the file), a robot
(`{kind: "robot", index: 0 belief | 1 truth}`; `belief` and `truth` with any index also work and mean
the robot at the current tick) or a map cell (`{kind: "cell", index, world}`); `select(null)` clears.
`state()` adds `tick`, `frame`, `view`, `belief_map`, `t_range` and `hidden` (the streams not shown).
`setVisible` takes a stream id or a group (`g.sensors`, `Sensors`, ...).

The view area is the element `#stage`; commands crop to it for the filmstrip. The two pages are one
workbench (`web/shell/`: top bar, outliner, properties, inspector, timeline, themes) with a renderer
adapter each (`web/three/app.js`, `web/deck/app.js`); the status chip `#runinfo` reads "robot ·
kind · verdict · length · N ticks", and `#follow` (with `#follow-on`) shows only while the run is
live.

The page shows ticks 1-based, "tick 457 of 464" (the time-tick field and the inspector);
`state().tick` stays the 0-based index, and `miniview.internals.M.fr` is indexed the same way.
Display > Point size (depth returns, map obstacles and drops) and Line width (tracks, plan), per
stream in pixels, are held in `miniview.internals.M.size` (stream id -> px; unset means the
default) and apply in both renderers. A 1 m scale bar (`#scale`, `data-m`, `data-px`) sits at the
bottom-left of the viewport in the orthographic views (the top pane in Three), and the cursor
readout (`#readout`) names the axes of the view under the pointer (front and back: y z; left and
right: x z; top: x y; 3D: x y of the floor, z = 0, or "—" off it). In the timeline, hatched bands
(`#dlanes .gap`) mark where the run has ticks but no depth frames (between the depth spans of
`/presence`). `viewer/tests/test_ui.py` drives all of this on a synthetic run, both pages.

### Renderer adapters (what `web/shell/shell.js` calls; `web/three/app.js`, `web/deck/app.js`)

A page gives the shell an adapter that draws into `#stage`:

```text
init(stage, shell)      setScene(scene)         setRun(run, frames)     setLayout(view, frame)
draw(sync)              settled() -> Promise    resize()                fit()               theme(palette)
describe(sel)           cursor(clientX, clientY) -> {axes, v, note?} | null
gizmo() -> {x, y, z}    camera-space axes (3D only)
scale() -> px per metre of the first orthographic pane, or null (3D)
fillsDrawn(pane) -> bool   whether the faint box faces are drawn in the pane named so (top and 3d yes; front, back, left, right outlines only)
project([x, y, z]) -> [clientX, clientY] | null   where a world point falls in the first pane (tests probe pixels there)
```

The shell gives the adapter `M` (the model), `shown(id, view)`, `cfg(id)`, `size(id)` (point
diameter or line width in px), `pick(sel)`, `viewChanged()`, `tickAt(t)` and `palette()` (the
theme's drawing colours, including `box-fill`). The 3D views of both pages start from the same
camera (45 degrees, from (-6.4, -8.8, 7.6) at the origin); `test_ui.py` checks that six world
points land on the same pixels.

## `GET /api/v1/runs/{id}/frames` — everything, by tick

```json
{"t": [0.1, 0.2],
 "belief": [[x, y, yaw], ...],            "map frame (the robot's own)"
 "truth": [[x, y, yaw] | null, ...],      "world frame; null on a real robot"
 "tilt": [[pitch_deg, roll_deg] | null, ...],
 "cmd": [[vx, vyaw], ...],
 "depth": [[[x, y, z, "f|o|v|b"], ...] | null, ...],   "map frame; null = no new frame that tick"
 "plan_at": [i, ...],                     "per tick: index into plans, or -1"
 "world_at": [i, ...],                    "per tick: index into worlds, or -1"
 "plans": [{"t": 1.0, "path": [[x, y], ...]}],         "map frame"
 "worlds": [{"t": 1.0, "grid": {"res": 0.0455, "origin": [x, y], "w": 82, "h": 92, "cells": "?.#..."},
             "obstacles": [[x, y], ...], "drops": [[x, y], ...]}]}   "map frame"
```

- `t` is the run's time, increasing (evaluation runs are laid end to end).
- Depth kinds: `f` floor, `o` obstacle, `v` overhead, `b` below the floor (a hole).
- Grid cells are row-major from the lowest y: `?` unknown, `.` free, `#` occupied; cell (i, j) has its
  centre at `origin + ((i + 0.5) res, (j + 0.5) res)`.

## Colours (UXS-001)

belief `#4682ff`, truth `#28b45a`, plan `#e6b400`, obstacles `#ff9600`, hazards and drops `#e600e6`,
depth f `#3cc85a`, o `#e63228`, v `#3c78e6`, b `#e600e6`, occupied `#505050`, free `#cdeccd`,
axes x `#e03030` y `#30b030` z `#3060e0`, scene boxes `#8a8a96`.
