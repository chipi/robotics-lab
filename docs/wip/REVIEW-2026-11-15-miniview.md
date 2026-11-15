# Review of miniview, 2026-11-15

A second-opinion review by the advisor (Fable 5.1, read-only) of miniview at commit `bc8bbf4`,
before RFC-0008 step 1. Findings 1–9 were reproduced by the advisor's probe scripts against
temporary data folders or measured; 10–11 are judgement on named evidence. The operator decided
(2026-11-15): fix all of them, and use them to strengthen how runs are stored, loaded and brought
into the UI — [RFC-0010](../rfc/RFC-0010-run-store-v2.md) and ADR-0006 to ADR-0012.

## Findings

| # | Finding | Evidence | Disposition |
| --- | --- | --- | --- |
| 1 | One malformed file or record takes the service down or freezes all live following | a garbage `run.mcap` makes `make_server` raise (crash loop in Docker); an `epoch` without `map_to_world` kills the follower thread, later runs never appear; `"belief": null` raises in `scan` | RFC-0010 |
| 2 | The live path does not scale | the page ignores SSE payloads and re-fetches the run each second (5.3 MB for phase1-run18); a window ships every plan and world (404 KB for 10 s); serialization (130 ms) holds the run's lock; `streams()` recomputed per batch | RFC-0010 |
| 3 | Everything loaded stays in memory; crashed runs reload and are polled forever; a cold index loads every run | about 14 KB per tick in RAM; footer-less files re-followed each boot; the `ticks`, `epochs`, `events`, `streams` tables are never read | RFC-0010 |
| 4 | Identity and staleness | run id is the folder name (collides across robots and scenes); a record id different from its folder is listed but 404s; a replaced file is stale until restart; a second writer truncates silently and the follower resyncs mid-record | RFC-0010 |
| 5 | Time | no wall-clock anchor (Foxglove shows 1970); goals stitched by a time heuristic (non-monotonic ticks possible, not triggered in 19 phase-1 logs); the import drops fields; no flush per record (a crash loses up to 8 KB) | RFC-0010 |
| 6 | The index loses a live run's first epoch and early events | the delete runs while ticks are 0 but epochs and events were already counted | RFC-0010 |
| 7 | The agent's interface substitutes another run; scripted time is overridden while following | `load()` falls back to the first run; follow resets `t` every second; `state()` has no run, status or seq; tests read `internals` | RFC-0010 |
| 8 | HTTP and page robustness | `live?since=abc` drops the connection with a traceback (confirmed by the lead: HTTP 000, `ValueError` in the container log); `from=nan` misbehaves; event kinds go unescaped into a RegExp; fonts from Google on every load | RFC-0010 |
| 9 | Docker mounts the data read-write only for the index; host CLI and container share one SQLite file without WAL; `miniview index` empties it under a running service | `compose.yml`, `catalog.py` | RFC-0010 |
| 10 | The decisions: JSON-only unchunked MCAP will hurt with Foxglove/Rerun and size; SSE right; stdlib server acceptable with gzip, timeouts and JSON errors; two renderers duplicate about 1,100 lines | judgement | RFC-0010 (ADR-0007, ADR-0010); the renderer question is the operator's, discussed separately |
| 11 | Tests prove the shapes on synthetic data only; no bad-input, collision, replace, stopped, DB-consistency or memory tests; three timing-sensitive checks | `test_server.py` latency with a missed-notify window; fixed sleeps in `test_live_page.py`; RAF-dependent play checks | RFC-0010 |
| 12 | Docs contradict the code | ADR-0005 `live?from=` and event names; "the ticks table answers the Moment"; PRD-001 non-goals; RFC-0009 `prepare`; ADR-0004 "loses at most one record" | RFC-0010 §4 step 7 |
| 13 | Small things | `RunData.since` linear; `HEAD /live` streams forever; bad `from` becomes "no bound"; hard-coded data path; vendor JS served `no-store` | RFC-0010 |

The CI workflow was judged runnable on ubuntu-latest by reading (uv 0.12.10 exists, Playwright's
Chromium under `CI=true`, Docker available); not verified by a run. The nbc toolchain pins a
Debian package revision (low risk).
