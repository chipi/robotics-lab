# ADR-0010 — The API, version 2

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3, [ADR-0005](ADR-0005-miniview-api-live-from-the-start.md),
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) findings 2, 8, 13

## Context

A ten-second window of phase1-run18 is 404 KB because it carries every plan and map; serializing
the whole run takes 130 ms while holding the lock the follower needs; a bad query parameter drops
the connection with a traceback; `HEAD` on a live stream streams forever; nothing is compressed;
the live stream's `since` works but `Last-Event-ID` is ignored.

## Decision

- **Runs by key** (ADR-0006): `/api/v1/runs/<robot>/<scene>/<run>`, with `/frames`, `/state`,
  `/events`, `/presence`, `/live` under it. `/api/v1/runs?robot=&scene=&status=` lists them from
  the index.
- **Windows carry their own:** `frames?from=&to=` returns the ticks in the window and only the
  plans and maps those ticks refer to, keyed by index (`plans: {"5": …}`).
- **Snapshots outside the lock:** an answer takes the lengths of the run's append-only lists under
  the lock and serializes the slices after releasing it. Stream counts are kept as records arrive.
- **Errors are JSON:** 400 for bad input (a number that is not one, `from > to`, a key with other
  characters), 404, 409 (no ticks yet), 500 with an id that is also in the log. No traceback reaches
  the client, no connection is dropped.
- **Live by record, with resume:** `live` takes `since` or `Last-Event-ID`; each record is an event
  named by its kind with the record as data and its seq as id; then `status`. A heartbeat every
  15 s. `HEAD` answers with the headers only.
- **gzip** for JSON over 1 KB when the client accepts it; static files carry an ETag, vendored
  libraries and fonts are cached for a day.
- Request sockets have a timeout (30 s), except live streams.

**Not goals:** a thread per connection is unbounded (the service is for one operator on loopback; a
stalled live client is dropped after 60 s, an idle request after 30 s); the pages carry a same-origin
Content-Security-Policy and answers say `nosniff`, but there is no authentication (loopback only).

## Consequences

- **Positive:** a window costs its own size; the follower is never blocked by a reader for long;
  clients see why a request failed; live pages resume where they left off.
- **Negative:** run URLs change (the pages and the commands follow).

## Alternatives considered

- **A web framework.** Validation and errors for free, but a dependency, and it fixes none of the
  costs above.
- **WebSocket for live.** Needed only when the page sends to the service; SSE stays.
