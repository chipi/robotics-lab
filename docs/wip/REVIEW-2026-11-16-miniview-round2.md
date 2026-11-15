# Review of miniview, round 2, 2026-11-16

A second review (the advisor, Fable 5.1, read-only) of miniview at `22be841` plus the lead's catalog
fix
`dbcbc86`, with probe scripts that reproduce most findings. The operator decided (2026-11-16): fix all
of them, and close the RFC-0008 gaps before RFC-0008 step 1. Each finding below gets a test that fails
before its fix; the Disposition column says what was done and which test shows it.

## Findings

| # | Finding | Disposition |
| --- | --- | --- |
| A1 | A live stream across a rewritten file splices the new content onto the old (no `rewritten` event when the new seq is not below the client's) | Fixed: `RunData.generation` (bumped by `reset`), `rewritten` sent when it changes, `generation` in the summary and every status event, the page reloads on a change; Last-Event-ID wins over `since`. `test_review2.py` A1 (failed before: no `rewritten`) |
| A2 | A lock from another host counts as a live writer for ever: a crashed run in Docker never becomes `stopped`; a stopped file that grows again is not followed | Fixed: a lock from another host is unknown, the growth rule decides; a stopped file that grows again resumes (live, rewritten 0). `test_review2.py` A2 (failed before: `live` for a day-old foreign lock) |
| A3 | A file cut and rewritten longer than the follower's offset (same inode) stalls: nothing read, no `rewritten`, no `stopped` | Fixed: bytes at the offset that are not a record start the file over. `test_review2.py` A3 (failed before: 5 of 23 ticks, no rewrite) |
| A4 | `scan` and `get` can open the same new run at once: two `Loaded`, a stream on the one the cache dropped never sees new ticks | Fixed: `_scan_one` keeps the `Loaded` a request stored. `test_review2.py` A4 (failed before) |
| A5 | A normal compaction is counted as a rewrite (`rewritten` 1 after `end`, poll, close, scan) | Fixed: a poll that changed `done` takes the signature, LIVE to FINAL is compaction. `test_review2.py` A5 (failed before: rewritten 1) |
| B1 | `started_at_ns` of 2**63 or more passes validation and fails in SQLite: the run is missing from the index and a request answers 500 | Fixed: `started_at_ns` below 2**63 in validation; an index failure marks the run broken. `test_review2.py` B1 (failed before: 500) |
| B2 | A `/map` inside a tick drops the tick silently (`follower.partials` is not surfaced) | Fixed: an interrupted tick is a reject, 'tick at t=1.1: interrupted by /map'. `test_review2.py` B2 (failed before: another message) |
| B3 | Two indexes: the commands scan and write the host's index while the service's is on a Docker volume | Fixed: compose bind-mounts the host state folder; the commands read the index and write nothing while a service holds it; ADR-0012 says what changed. `test_review2.py` B3 and `make test-viewer-image` (written with the fix; not run against the old code) |
| C1 | No timeout on a live stream: a client that stops reading pins a thread and its run | Fixed: 60 s write timeout on a live stream. `test_review2.py` C1 (a client that never reads is dropped, the run unpinned; written with the fix, not run against the old code) |
| C2 | One write and flush per record on a live stream | Fixed: one write per wake-up. Covered by `test_server.py` (burst) and the live tests; no separate before-test |
| C3 | A follower round recomputes `streams` and notifies for every finished run in the cache | Fixed: `finish_batch` only on change or the done transition. `test_review2.py` C3 (failed before: 10 recomputations) |
| C4 | `scan` reads the index one row per run | Fixed: one query for all rows. `test_review2.py` C4 (failed before: 12 row queries) |
| C5 | The follower, `_read_final` and `compact` read whole files into memory | Fixed: block reads, streamed final and compaction. `test_review2.py` C5 (peaks 2 MB and 4 MB for an 18 MB file; the before-peaks were not measured) |
| C6 | Every request for an unknown key rescans the data folder | Fixed: a missing key rescans once a second. `test_review2.py` C6 (failed before: 30 rescans) |
| D1 | Static files: a directory outside `web/` answers a 301 before the root check | Fixed: the web-root check comes first. `test_review2.py` D1 (failed before: 301) |
| D3 | The server names itself (version strings), no `nosniff`, no CSP, `not allowed` keeps the connection; unbounded threads are not written down | Fixed: server name, nosniff, a same-origin CSP, close on 405; unbounded threads written in ADR-0010. `test_review2.py` D3 (failed before) |
| D4 | A scene whose id differs from its folder is indexed | Fixed: logged and not indexed. `test_review2.py` D4 (failed before) |
| E2a | The compat test pulls `lichtblick:latest`, clicks fixed pixels, and asserts that Rerun's `-d foxglove` decodes nothing | Fixed: Lichtblick pinned by digest in `viewers.sh` and the test, how to bump it in ADR-0007; the click is a fraction of the timeline's box; the `-d foxglove` assertion is removed. `make test-run-compat` |
| F1 | `cli.py` docstring names a default data path the code no longer has | Fixed: the docstring in `cli.py` |
| F2 | Docs differ from the code: ADR-0006 `started_at_source` values, ADR-0011 plans/maps wording, CONTRACT frames of a tickless run, ADR-0007 flush per tick | Fixed: ADR-0006 (`started_at_source` values), ADR-0011 (plans and maps inside the window), CONTRACT (a tickless run's frames), ADR-0007 (flush per tick, now in the code) |
| F3 | Test hygiene: a tautology in `test_live_page`, latency margins in `test_server`, play checks in `test_ui` that depend on the frame clock | Fixed: the tautology is gone, latency margins are three follower rounds, `test_ui` waits for conditions (pause, stop at the end) |

## RFC-0008 gaps, closed before step 1

| # | Gap | Disposition |
| --- | --- | --- |
| G1 | The tick protocol is implicit: no numbered rule, the recorder does not enforce it | Closed: the numbered rule in ADR-0007 and CONTRACT; `Recorder.begin_tick`/`tick_*`/`end_tick`; the reader drops an interrupted tick. `test_review2.py` G1 |
| G2 | Remote robots: no decision where the file is written | Closed: ADR-0007 'Remote robots': a receiver on the workstation writes the file; the foreign-host lock handling is the safety net |
| G3 | Compaction reads the whole file and only runs where the writer runs | Closed: compaction streams (C5) and `miniview compact <key>` runs it on the workstation. `test_review2.py` G3 |
| G4 | The recorder flushes per record, not per tick | Closed: one flush per tick. `test_review2.py` G4 |
| G5 | No depth kind registry; `/tf` frame ids are not validated | Closed: the depth kind registry in CONTRACT and ADR-0007; `/tf` must be world <- map, frames are checked. `test_review2.py` G5 |
| G6 | `t_src` is not documented as a clock | Closed: `t_src` is the source's own clock, in ADR-0007 and CONTRACT |
