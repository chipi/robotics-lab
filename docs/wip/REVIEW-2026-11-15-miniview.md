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

## Resolution (RFC-0010 built, 2026-11-15)

| # | Fixed by | Shown by |
| --- | --- | --- |
| 1 | ADR-0008: records validated, a bad run isolated as broken, the follower never stops | `test_reading.py` (garbage file, bad records, key mismatch, a failing run, a failing round); `test_server.py` (broken run: 409 with the reason) |
| 2 | ADR-0010 and ADR-0011: windows with their own plans, snapshots outside the lock, counts kept as records arrive, a page store that loads by window then by record | `test_server.py` (a window is 19% of the run's bytes, counts equal a recount); `test_live_page.py` and `test_store_page.py` (no frames request while the run grows; one setRun, appends); `make perf-viewer` (lock held 0.75 ms at most) |
| 3 | ADR-0009: a cache bounded by memory, stopped runs final, start-up from the index, the index read | `test_index.py` (eviction under 4.5 MB, a restart opens only what changed, the stopped run is neither reloaded nor followed, the estimate within 25% of tracemalloc) |
| 4 | ADR-0006 and ADR-0007: the key `robot/scene/run`, one writer under a lock, a replaced file read again | `test_server.py` (same name under two robots), `test_mcapio.py` (second writer refused), `test_reading.py` (key mismatch, replaced file) |
| 5 | ADR-0007: absolute time, segments at goal-ending events, nothing dropped, flushed per record | `test_mcapio.py` (log_time, publish_time, segments, every source field, a tick on disk when `add` returns) |
| 6 | ADR-0009: one transaction per change, counters reset together | `test_index.py` (the index equals memory after a live run, first epoch and early events included) |
| 7 | ADR-0011: `load()` rejects, `state()` names the run, Follow live a mode, `config()` replaces what tests read | `test_store_page.py`, `test_live_page.py` |
| 8 | ADR-0010 and ADR-0011: JSON errors, event kinds as text, fonts served by the service | `test_server.py` (bad query input is 400), `test_store_page.py` (a kind with pattern characters), `test_ui.py` (no request leaves the machine) |
| 9 | ADR-0009 and ADR-0012: the index outside the data with WAL, the rebuild refuses under a service, the data mounted read only | `test_index.py`, `make test-viewer-image` |
| 10 | ADR-0007 and ADR-0010: Foxglove schemas, zstd chunks and indexes, gzip, timeouts, JSON errors. The renderer question stays the operator's | `test_mcapio.py`, `test_server.py` |
| 11 | RFC-0010 section 5: a real run as a fixture, a fault test per finding, no fixed waits | `viewer/tests/`, `viewer/tests/fixtures/explore9/` |
| 12 | RFC-0010 step 7 | ADR-0004, ADR-0005, PRD-001, RFC-0009, `viewer/CONTRACT.md` |
| 13 | ADR-0010: `HEAD` without a stream, a bad `from` is a 400, the data path from the environment, vendored files cached | `test_server.py` |
