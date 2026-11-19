# RFC-0009 — miniview (now the Observatory): one run format, two faces, any robot

> Now the Observatory (RFC-0018, built 2026-11-19): the product, package and command were renamed;
> this text keeps the names of its time.

**Status:** Proposed (2026-11-15) — for the operator's review.
**Product and UX:** [PRD-001](../prd/PRD-001-miniview.md), [UXS-001](../uxs/UXS-001-miniview.md).
**Builds on:** [RFC-0007](RFC-0007-platform.md) (the platform), [ADR-0002](../adr/ADR-0002-viewers-rerun-and-lichtblick.md)
(Rerun and Lichtblick stay); serves [RFC-0008](RFC-0008-challenge-course.md) (the challenge course).

## 1. Motivation

The first `miniview` (`duck_lab/miniview.py`) proved the idea in an afternoon: pictures an agent can
read settled two wrong diagnoses. It is also duck-shaped (it reads the navigator's tick log
directly), one file, and has no page for the operator. The challenge course is about to produce runs
by the hundred; the viewer should be shaped before the logs that feed it.

## 2. Architecture

```text
 robot logs ──► adapter ──► run (format v1) ──► scene builder ──► agent renderer ──► PNG / JSON
 (duck ticks,               files on disk       layers → shapes  │                   (commands)
  NXT MCAP, …)                                  in the world     └► page renderer ──► one HTML file
                                                frame at t                             (operator)
```

1. **The run's content (v1)** — what is stored, whatever stores it (the storage itself is an open
   decision, §7): per run, its metadata (robot, footprint radius and height, scene, start, frames:
   which is truth, which is belief) and time-stamped records. Kinds: `pose` (belief, truth, tilt), `world`
   (grid with origin and resolution; obstacles; hazards as edges and points), `sensor` (returns with
   kind; the raw frame and its state's time), `plan` (path), `decision` (rule, reason, values),
   `event`. Units SI, frames named, everything in the run's map frame with one map→world transform
   per map epoch. Versioned; readers ignore what they do not know.
2. **Adapters** write the format: `duck` (the navigator's `ticks.jsonl` today; the navigator writes
   the format natively once step 1 of RFC-0008 lands), `mcap` (nxt-web's recordings) next. A new
   robot needs an adapter and nothing else.
3. **The scene builder** turns a run at t, with layers, into shapes — lines, polygons, points,
   labels — independent of how they are drawn, in a chosen frame: the world (truth beside belief) or
   the robot's own (the data view: no truth, no world transform). The coordinate system (axes, metre
   grid, labels) is a layer like any other. Views are cameras on the same shapes: orthographic from
   the top or any side, the three-view as three cameras, perspective. Today's `scene()` is its seed.
4. **The agent renderer** projects shapes (top or perspective, painter-sorted) to SVG and rasterizes
   with the system's Chromium; the state and summaries are JSON from the same builder.
5. **The viewer page**: one HTML page and a small script, served by `make viewers` (a browser does
   not let a page opened from disk read other files, and choosing runs needs that). It reads
   `index.json` (the scenes and their runs, written by `miniview index`) and, for the chosen run,
   the run's frames — loaded from the service by window, then by record
   ([ADR-0011](../adr/ADR-0011-loading-into-the-ui.md)) —
   and draws them with the same cameras as the agent renderer, so the page and the commands cannot
   disagree. There is no `prepare` step: nothing is written next to a run but the run itself. The
   drawing library for 2D
   and 3D is an open decision (§7). *Since ADR-0005:* the pages read the service's API (`/api/v1`),
   not
   files; `viewer/CONTRACT.md` lists it.
6. **Scenes** (operator, 2026-11-15): the thing that is loaded. A scene is a place with what is
   really there — geometry, hazards, origin and frame — and, for a challenge, its mission and
   invariants; scenes are written once (the simulator's layout, a challenge's generator, later a
   recorded map) and runs refer to theirs by name. A run without a known scene is shown as its data
   alone.

7. **One API over one database, two pages** (operator, 2026-11-15): the three.js and deck.gl pages
   read the same API, and the API reads one database (the index of ADR-0004 over the runs). The
   pages hold no data logic of their own. This replaces the "files in, files out, no server"
   principle below. **Streaming is supported from the start** (operator, 2026-11-15): a live run is
   a run that has not ended; the robot appends to its MCAP, the service follows the file and sends new
   data to the pages as Server-Sent Events. The data model, the endpoints and the live design are
   [ADR-0005](../adr/ADR-0005-miniview-api-live-from-the-start.md).

## 3. Where it lives

**Decided (operator, 2026-11-15):** its own package at the repository root, `viewer/` (Python, `uv`,
CLI `miniview`), not inside the duck
— the duck and the NXT both depend on it for their adapters; it depends on neither. Playwright stays
a development dependency of the viewer, for checking the page the way a person sees it.

### Running in Docker (plan; operator, 2026-11-15)

The service (ADR-0005) runs in a container, so it starts the same way on the workstation and later
on the homelab, and needs nothing installed on the host but Docker.

- **One image, `miniview`:** the viewer package and its two pages; the command is `miniview serve`
  on `0.0.0.0`, the port from `MINIVIEW_PORT`. A health route, `GET /api/v1/health`, for Docker's
  health check.
- **The data stays on the host:** `/work/robotics-lab/data/` (ADR-0004) is mounted into the
  container. The robot or the simulator writes runs there from outside, and the service follows the
  growing files (ADR-0005), by polling every quarter second rather than file events, which are
  unreliable across mounts. The index (`index.sqlite`) is written by the service, so the mount is
  read-write.
- **Pictures for the agent stay outside the image:** they need Chromium and Playwright, which would
  make the image several times larger. The `miniview` commands keep running from the viewer's own
  environment on the host; they read the same data folder.
- **Started by** a compose file in `viewer/` and `make viewer-up` / `make viewer-down`; `make
  viewers` starts it with Rerun and Lichtblick.
- **Later, on the homelab:** the same image behind the tailnet, so the page opens on a phone; it
  follows the homelab's rules for its Docker engine.

**Decided (operator, 2026-11-15):** the base image is `python:3.12-slim` with `uv` copied in (the
smallest); the port is **8070**, published on `127.0.0.1` only like the repo's other containers
(8000 is nxt-web, 8090 Lichtblick, 9090 Rerun, 8765 the docs).

## 4. Versions

- **v0.1 — what RFC-0008's steps 1–2 need, and the operator's page** (operator, 2026-11-15): the
  format v1 and the `duck` adapter; `events`, `frame`, `film`, `state`, `sensor`, `index`, `repair`
  (there is no `prepare`, RFC-0010);
  the viewer page with the runs list and picker, the timebar every panel follows, 2D views (top by
  default, any side, all three) and 3D, the coordinate system in every view, the data view (the
  robot's own data in its own frame), layers, the moment panel; scenes and their runs, several
  runs drawn together; out of the duck package; tests on
  synthetic runs, Playwright checks of the page.
- **v0.2**: the filmstrip and charts on the page, runs aligned at an event.
- **v0.3** — the `mcap` adapter (NXT), dark theme, live tailing of a running log.

## 5. Principles

- One builder, two renderers: a view exists in both faces or in neither.
- ~~Files in, files out: no server~~ — replaced by one API over one database (§2, item 7).
- Stable outputs: the same run and command give the same bytes (agents diff them).
- Truth is optional: a real robot's run has none, and every view still works.

## 6. Alternatives considered

- **Rerun alone, driven by Playwright.** Works for screenshots (done today), but its canvas offers
  nothing to ask or read back, and selecting a recording means clicking pixels. Kept for free
  exploration (ADR-0002).
- **Rerun's own data API for the agent, Rerun for the operator.** Two pictures that can disagree;
  and no truth-against-belief numbers without a builder of our own anyway.
- **Matplotlib for pictures.** A new dependency and a second drawing path from the page's.
- **A web app with a server.** More to run and secure, for no answer the files do not give.

## 7. Open decisions, to be chosen with care (operator, 2026-11-15)

Both get a written comparison and an ADR before v0.1 builds on them.

- **The drawing library for 2D and 3D** — **a framework from the start** (operator, 2026-11-15: no
  hand-drawn canvas); which one is this decision. On the page, and whether the agent's pictures
  come from the same library rendered headless (preferred: one drawing path). Candidates to compare:
  three.js, Babylon.js, deck.gl, react-three-fiber, and how Rerun and Foxglove draw. Criteria: the
  views of UXS-001 (sides, three-view, 3D orbit, the coordinate system), point counts per frame,
  scrubbing without lag, phone browsers, headless rendering for the agent, size and licence, how long
  it will be maintained.
- **The storage of runs**, time-series friendly. Candidates: MCAP (indexed by time, chunked,
  already ours for `nxt-web`, read by Foxglove, Lichtblick and Rerun), DuckDB over Parquet or Arrow,
  SQLite, a time-series database, JSON lines (today's). Criteria: queries by time window and by kind,
  appending while a run is live, size, reading from the browser page and from Python, other tools
  opening it, one format for every robot.

## 8. Open questions

- The raw frame's size in the log (64 numbers per frame at 15 Hz is fine; a camera later is not).
- Whether the page needs 3D orbit in v0.2 or a fixed set of cameras is enough at first.
- How long runs are kept, and where (the logbook, RFC-0007).
