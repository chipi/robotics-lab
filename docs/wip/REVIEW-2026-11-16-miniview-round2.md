# Review of miniview, round 2, 2026-11-16

A second review (the advisor, Fable 5.1, read-only) of miniview at `22be841` plus the lead's catalog
fix
`dbcbc86`, with probe scripts that reproduce most findings. The operator decided (2026-11-16): fix all
of them, and close the RFC-0008 gaps before RFC-0008 step 1. Each finding below gets a test that fails
before its fix; the Disposition column says what was done and which test shows it.

## Findings

| # | Finding | Disposition |
| --- | --- | --- |
| A1 | A live stream across a rewritten file splices the new content onto the old (no `rewritten` event when the new seq is not below the client's) | open |
| A2 | A lock from another host counts as a live writer for ever: a crashed run in Docker never becomes `stopped`; a stopped file that grows again is not followed | open |
| A3 | A file cut and rewritten longer than the follower's offset (same inode) stalls: nothing read, no `rewritten`, no `stopped` | open |
| A4 | `scan` and `get` can open the same new run at once: two `Loaded`, a stream on the one the cache dropped never sees new ticks | open |
| A5 | A normal compaction is counted as a rewrite (`rewritten` 1 after `end`, poll, close, scan) | open |
| B1 | `started_at_ns` of 2**63 or more passes validation and fails in SQLite: the run is missing from the index and a request answers 500 | open |
| B2 | A `/map` inside a tick drops the tick silently (`follower.partials` is not surfaced) | open |
| B3 | Two indexes: the commands scan and write the host's index while the service's is on a Docker volume | open |
| C1 | No timeout on a live stream: a client that stops reading pins a thread and its run | open |
| C2 | One write and flush per record on a live stream | open |
| C3 | A follower round recomputes `streams` and notifies for every finished run in the cache | open |
| C4 | `scan` reads the index one row per run | open |
| C5 | The follower, `_read_final` and `compact` read whole files into memory | open |
| C6 | Every request for an unknown key rescans the data folder | open |
| D1 | Static files: a directory outside `web/` answers a 301 before the root check | open |
| D3 | The server names itself (version strings), no `nosniff`, no CSP, `not allowed` keeps the connection; unbounded threads are not written down | open |
| D4 | A scene whose id differs from its folder is indexed | open |
| E2a | The compat test pulls `lichtblick:latest`, clicks fixed pixels, and asserts that Rerun's `-d foxglove` decodes nothing | open |
| F1 | `cli.py` docstring names a default data path the code no longer has | open |
| F2 | Docs differ from the code: ADR-0006 `started_at_source` values, ADR-0011 plans/maps wording, CONTRACT frames of a tickless run, ADR-0007 flush per tick | open |
| F3 | Test hygiene: a tautology in `test_live_page`, latency margins in `test_server`, play checks in `test_ui` that depend on the frame clock | open |

## RFC-0008 gaps, closed before step 1

| # | Gap | Disposition |
| --- | --- | --- |
| G1 | The tick protocol is implicit: no numbered rule, the recorder does not enforce it | open |
| G2 | Remote robots: no decision where the file is written | open |
| G3 | Compaction reads the whole file and only runs where the writer runs | open |
| G4 | The recorder flushes per record, not per tick | open |
| G5 | No depth kind registry; `/tf` frame ids are not validated | open |
| G6 | `t_src` is not documented as a clock | open |
