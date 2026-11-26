# Technical review, 2026-11-26 (review round 4 and step 4.9)

The operator asked for a full technical review by the advisor (Fable 5) as part of review
round 4 and step 4.9. It was read-only, at main 9962cd0, with the web layer read at HEAD while
U26 was in flux. The reviewer ran no test suite; one scratch script proved finding 1.1. Each
finding is marked VERIFIED (the reviewer read the code path) or SUSPECTED. The triage column is
ours.

## Findings and triage

| # | Severity | Finding | Where | Triage |
| --- | --- | --- | --- | --- |
| 1.1 | HIGH, VERIFIED | A STOP through lab-gate was reported `confirmed` when robotd did not answer | `robotgate/__init__.py` `_stop_from`, `_gate_stop`; `robots.py` `RobotRuntime.stop` | Fixed in 3c478c3 (noted in 819f7cf), tests red first |
| 1.4 | LOW, VERIFIED | A `ProtocolError` on STOP escaped as a 500 | `robots.py` `stop` | Fixed with 1.1; the NXT's 409 too |
| 5.a | MEDIUM, VERIFIED | No test of STOP through the proxy with a failing robotd | `test_gate.py`, `test_duck_adapter.py` | Added with 1.1 |
| 1.2 | MEDIUM, VERIFIED | `allow_real_runs` misses a real robot whose file holds the robot itself (`robots.nxt/nxt-1.json`): hand driving the real NXT never asks | `robots.py:161-174` | Decided by the operator 2026-11-26; fixed in fb884b2 |
| 1.3 | MEDIUM, VERIFIED | The gate holds its lock across robot I/O (up to 10 s per STOP on a hung robotd); `_after_stop` and `cancel_run` hold the robot's mutex through settling | `robotgate` `handle`; `core.py:187-196, 681-696` | Planned: with MVP 2 step 1's gate changes |
| 2.a | MEDIUM, VERIFIED | Three implementations of the lease rules | `robotgate.Gate`, `nxt_lab/lock.py`, `NxtGate` | Planned: MVP 2 step 1, behind the contract test |
| 2.b | MEDIUM, VERIFIED | Frames and scale computed in three places | navigator `_place`/`move_grid`, `progress.pose`, MC `DuckAdapter._placed` | Planned: before MVP 2 (one frame owner) |
| 3.a | MEDIUM, VERIFIED | Adapter programming errors look like link loss (caught, shown as offline, no stderr line) | `robots.py:329-360`, `core.py:98-104` | Fixed in fb884b2 |
| 5.b | MEDIUM, VERIFIED | No cross-adapter contract test of the adapter surface | `mission_control.robots` | Planned: before MVP 2 (step 1 asks for it) |
| 8.a | MEDIUM, VERIFIED | The Observatory ignores hash-only navigation (no `hashchange`) | `shell.js` | Fixed in 349f083 |
| 8.b | MEDIUM, VERIFIED | `createShell` is one 1,540-line closure over a mutable `M` | `shell.js:201-1740` | Planned: split during MVP 2 |
| 6.a | LOW-MEDIUM, VERIFIED | `?token=` reaches logs on unexpected 500s | `api.py:625`, Observatory `server.py:316` | Fixed in fb884b2 |
| 4.a | LOW, VERIFIED | `int(Content-Length)` gives a 500, not a 400; MC has no request timeout | `api.py:519, 572` | Fixed in fb884b2 |
| 4.b | LOW, SUSPECTED | Profile import only partly validated before the store | `profiles.py:157-165` | Checked: already validated in profilestore; no change (fb884b2) |
| 2.c | LOW, VERIFIED | RFC-0018 §10 says an import exception is in force; the checker has none | RFC-0018, `check_boundaries.py:79` | Fixed in fb884b2 (the exception retired) |
| 3.b | LOW, VERIFIED | A worker thread per timed-out call; a TCP connection per navigator call at 5 Hz; the full grid fetched to learn its version | `robots.py:237-255`, `duck.py:500-510` | Noted |
| 3.c | LOW, VERIFIED | The nav server maps any `KeyError` to "no method" | `duck_lab/nav/server.py:664` | Fixed in fb884b2 |
| 8.c | LOW, VERIFIED | `/state` and `/presence` copy the whole run's tick lists per request | Observatory `server.py:552-553` | Noted; measure with perf-observatory |
| 6.b | LOW, VERIFIED | Mission Control has no access log; the two servers log errors differently | `api.py` | Noted |

## Readiness for MVP 2 (the reviewer's verdict)

Ready to start after four small refactors, none a rewrite, each guarded by `make ci-fast`:

1. The gate's STOP reply carries the robot's answer, with the proxy test (done: 1.1).
2. The adapter surface written as a `Protocol` in `mission_control.robots`, with one contract
   test over fake, duck and NXT (step 1 asks for exactly this).
3. One frame and scale owner: the navigator API answers poses in the site frame, already
   scaled; Mission Control stops re-scaling (otherwise step 5a's ROS connector adds a fourth
   copy).
4. `allow_real_runs` settled for robot files that hold the robot itself (1.2), before step 6.

During MVP 2, as planned: gate method names from the contract (step 1), profile v2 (step 2),
the navigator split (step 3), host kinds (step 4); retire `nxt_lab/lock.py`'s copy in step 1
behind the contract test; the lock-scope fixes (1.3) ride with step 1's gate changes.

Repository: keep one repository, uv projects with path sources, the boundary checker as the law.

RFC-0024, who fronts whom: keep the Observatory as the one origin, as built. Its process is
stateless toward the robot and must stay up when the robot stack is down; its proxy holds no
token and makes no decision; fronting with Mission Control would put the lock-holding process on
the path of every large run read and tie the Observatory's availability to it. Confidence
moderate: the proxy's latency on the event stream was not measured.

## What the review found correct (verified)

STOP is open without a token; every lease end stops first; disconnect and expiry stop; a second
driver ends the lease with an alarm; the navigator refuses a goal while the robot is held and
takes the lease before anything moves; closing zero-moves then releases; the real duck's link
watch degrades to offline; calibration and goal runs ask for the real-run key; path traversal
is refused in both servers; the event bus signals gaps; the telemetry hook never raises; the
exposure model is as documented (loopback, tokens and `tailscale serve` at the cut-over).

## Not covered

The reviewer ran no test suite, simulator, Docker or deployed stack; 1.3, 3.x and 8.x are read
from code, not measured. Not read: `fake.py`, parts of `nxt.py`, `calibration.py`, `sites.py`,
`goals.py`, `guardrails.py`, `planner.py`, both MCP servers, most of `runfile`, `simhost`, most of
`labrunner`, most of `duck_lab/nav/run.py`, `apps/nxt-web` beyond greps, the Observatory's CLI,
video and query code, `docs.yml`. RFC-0024, RFC-0025, the deployment notes, the safety review
and both contracts were read in part; the look-and-feel plan and the ADR bodies were not. The web
JavaScript was read by grep only, and the U26 changes not at all. Nothing on hardware, the X3
staging stack, telemetry delivery or run-format compatibility with Rerun and Lichtblick.
