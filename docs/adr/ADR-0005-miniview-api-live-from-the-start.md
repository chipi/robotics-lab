# ADR-0005 — miniview: one API over the run store, live from the start

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0009](../rfc/RFC-0009-miniview.md) §2,
[ADR-0004](ADR-0004-runs-in-mcap-with-derived-index.md) (MCAP the record, SQLite the index),
[ADR-0001](ADR-0001-ros-aligned-foxglove.md) (Foxglove's protocol and schemas),
[UXS-001](../uxs/UXS-001-miniview.md) (the whole page)

## Context

The operator decided on 2026-11-15:

- the two pages (three.js and deck.gl) use **one API**, and the API uses **one database**;
- **streaming is supported from the start**: a run can be watched while it happens, not only after
  its files are prepared.

Until now everything was files: a run ends, `miniview prepare` writes `frames.json`, a page loads it
whole. That breaks in three places: a run cannot be watched while it runs (a near-fall seen after
the fact), the challenge course's batches cannot be followed or stopped early, and long runs are
large as one file (phase1-run18's `frames.json` is 5.3 MB, explore12's 0.9 MB).

ADR-0004 stays: MCAP is the record of truth, `index.sqlite` and prepared frames are derived. Its
sentence "a service would break files in, files out" referred to a time-series database server; it is
superseded only in that the pages now read through a small API process instead of the files.

## Decision

1. **One service, `miniview serve`**, Python's standard library (`http.server`, threaded), no new
   dependency. It serves both pages and the API under `/api/v1`. The pages hold no data logic: no
   epoch transforms, no "state at t", no presence computation; they draw what the API returns.
2. **One query layer, three faces.** The API, the `miniview` commands and a later MCP server call the
   same Python functions (`query.py` grows into it). The commands do not need the service running.
3. **The data model**, the same for every robot (adapters map a robot's log onto it):

   | Thing | Fields |
   | --- | --- |
   | Scene | id, name, frame, bounds, boxes, hazards |
   | Run | id, scene, robot (name, radius, height), kind, status `live` or `ended`, t0, t1, verdict |
   | Stream | id, group, name, kind (`pose`, `points`, `grid`, `path`, `event`, `layout`, `scalar`), frame (`world`, `map`, `robot`), count, rate, t span, missing and why |
   | Epoch | from t, the map → world transform |
   | Event | t, kind, text, values |
   | Record | stream, t, payload by the stream's kind |

4. **The database** is ADR-0004's `index.sqlite`, with these tables: scenes, runs, streams, epochs,
   events, and `ticks` — one row per tick per run (t, belief, truth, command, tilt). The ticks table
   answers the inspector's Moment and the timeline's rows without opening MCAP. Bulk records (depth
   points, grids, plans) stay in the run's MCAP and are read by time range.
5. **Endpoints** (read-only, JSON):

   | Endpoint | For |
   | --- | --- |
   | `GET scenes`, `GET scenes/{id}` | the scene picker, the scene drawing |
   | `GET runs?scene=` | the run picker |
   | `GET runs/{id}` | the outliner: streams, epochs, status |
   | `GET runs/{id}/state?t=` | the inspector's Moment |
   | `GET runs/{id}/presence` | the timeline's data rows |
   | `GET runs/{id}/events?kinds=` | the markers, the event list |
   | `GET runs/{id}/frames?from=&to=` | drawing data for a time window; the page caches windows |
   | `GET runs/{id}/live?from=` | the live stream (below) |

   The schemas are written in `viewer/CONTRACT.md`; the version is in the path.
6. **Live from the start: a live run is a run that has not ended.**
   - The robot side (the navigator, the simulator, later a bridge for a real robot) **appends to the
     run's MCAP with small chunks** (ADR-0004) and marks the run `live` in the index. It does not
     need the service to be running.
   - The service **follows the growing file**, reading each completed chunk, updates the index
     (ticks, events, t1) and sends new data to the pages as **Server-Sent Events** from
     `runs/{id}/live`: `tick` (a ticks row), `record` (a stream's record), `event`, and `status`
     (ended, with the verdict). Server-Sent Events go one way (service to page), are native in the
     browser (`EventSource`, which reconnects by itself) and need nothing beyond the standard
     library.
   - The page: the timeline grows; a **Follow live** switch pins the playhead to the newest tick;
     scrubbing back works as on a finished run. When the run ends, nothing changes for the page
     except the status.
   - Latency is the chunk size: about a quarter of a second, enough for watching a 10–20 Hz robot.
   - A real robot over the network later: a bridge on the lab machine receives its data (the
     Foxglove WebSocket protocol, ADR-0001) and writes the same MCAP, so the service sees the same
     thing.
7. **Not in the viewer:** sending commands to a robot (RFC-0003's interface).

## Consequences

- **Positive:** one place computes everything both pages show, so they cannot disagree; the file
  stays the truth, so a crash of the service loses nothing and a robot runs without it; live and
  finished runs use the same reads; windows make long runs cheap; the endpoints map one to one to
  future MCP tools.
- **Negative:** a process to run (`make viewers` starts it); following a growing MCAP needs care
  (read only completed chunks); two derived things to keep fresh (the index, the frame cache).
- **Neutral:** the agent keeps using the commands, which do not need the service.

## Alternatives considered

- **The robot publishes to the service, which writes the MCAP** (one writer). Lower latency, but the
  record depends on the service being up, and a robot cannot run alone.
- **The page reads the MCAP itself** (`@mcap/browser`). No service, but every page would repeat the
  data logic, against "two UIs, one API".
- **WebSocket instead of Server-Sent Events.** Needed only when the page sends to the service while
  live; nothing does yet. Can be added beside it.
- **FastAPI.** A generated schema and validation, but new dependencies for a dozen read-only
  endpoints; the schemas live in CONTRACT.md instead.
- **The Foxglove WebSocket protocol to the page.** Lets Foxglove and Lichtblick watch live too; our
  pages would need its client and still compute the inspector's values themselves. Kept for the
  robot-to-lab bridge.
- **Polling the files.** Simple, but a page would re-read growing files and repeat the work.
