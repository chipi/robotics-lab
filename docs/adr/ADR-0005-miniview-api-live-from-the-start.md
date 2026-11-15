# ADR-0005 — miniview: one API over the run store, live from the start

**Status:** Accepted (2026-11-15, by the operator); in part superseded by [RFC-0010](../rfc/RFC-0010-run-store-v2.md)
**Date:** 2026-11-15
**Context documents:** [RFC-0009](../rfc/RFC-0009-miniview.md) §2,
[ADR-0004](ADR-0004-runs-in-mcap-with-derived-index.md) (MCAP the record, SQLite the index),
[ADR-0001](ADR-0001-ros-aligned-foxglove.md) (Foxglove's protocol and schemas),
[UXS-001](../uxs/UXS-001-miniview.md) (the whole page)

> **What RFC-0010 supersedes (2026-11-15).** The API is **version 2**
> ([ADR-0010](ADR-0010-api-2.md)): runs are addressed by
> key (`/api/v1/runs/<robot>/<scene>/<run>`), a frames window carries only the plans and maps its
> ticks refer to, errors are JSON,
> and the live stream takes `since` or `Last-Event-ID` (not `from`), sends each record as an event
> named by its kind with its
> seq as id, and answers `HEAD` with headers only. "The ticks table answers the Moment" is withdrawn
> ([ADR-0009](ADR-0009-index-and-lifecycle.md)). "The page caches windows" became the page's run store
> ([ADR-0011](ADR-0011-loading-into-the-ui.md)): a window around the playhead, then the rest, then
> live by record. One API over
> one database, and live from the start, stand.

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

4. **The database** is the service's `index.sqlite` ([ADR-0009](ADR-0009-index-and-lifecycle.md)),
   with these tables: scenes,
   runs, streams, events and segments. It answers the run list, the scenes page and questions across
   runs; the inspector's
   Moment and the timeline's rows come from the run loaded in memory (there is no per-tick table).
   Records (poses, depth
   points, grids, plans) stay in the run's MCAP and are read by time range.
5. **Endpoints** (read-only, JSON):

   | Endpoint | For |
   | --- | --- |
   | `GET scenes`, `GET scenes/{id}` | the scene picker, the scene drawing |
   | `GET runs?robot=&scene=&status=` | the run picker |
   | `GET runs/{robot}/{scene}/{run}` | the outliner: streams, epochs, status |
   | `GET runs/{key}/state?t=` | the inspector's Moment |
   | `GET runs/{key}/presence` | the timeline's data rows |
   | `GET runs/{key}/events?kinds=` | the markers, the event list |
   | `GET runs/{key}/frames?from=&to=` | drawing data for a time window, with only the plans and maps its ticks refer to |
   | `GET runs/{key}/live?since=` | the live stream (below), or `Last-Event-ID` |

   The schemas are written in `viewer/CONTRACT.md`; the version is in the path.
6. **Live from the start: a live run is a run that has not ended.**
   - The robot side (the navigator, the simulator, later a bridge for a real robot) **appends to the
     run's live file** (`run.live.mcap`, unchunked, flushed after each tick's records, [ADR-0007](ADR-0007-run-file-format-2.md))
     under a writer lock, and compacts it into `run.mcap` when done. It does not need the service to
     be running.
   - The service **follows the growing file**, reading each complete record, updates the index
     (counts, events, t1) and sends new data to the pages as **Server-Sent Events** from
     `runs/{key}/live`: one event per record, named by its kind (`tick`, `plan`, `world`, `event`,
     `epoch`, `segment`,
     `end`), its seq as the event id, and `status` (live, ended, stopped, with the verdict).
     Server-Sent Events go one way (service to page), are native in the
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
