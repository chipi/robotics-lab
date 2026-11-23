# The navigator contract

**Version 1.2.** What a navigator answers to its runner and to Mission Control: the duck's payload
(`duck_lab.payload`, the courses' navigator) and its navigator API (`duck_lab.nav.server`, Mission
Control's, behind `lab-nav-server`) both keep it, and another robot's navigator can. The names are in
code once, in `runfile.navcontract`; the contract test (`robots/duck/tests/test_contract.py`) runs
the same checks against both.

Newline-framed JSON-RPC 2.0, one request per line, on a unix socket (or TCP on loopback for the
navigator API). The navigator never reads the simulator's truth or this machine's installation file:
it is given the robot's sockets (the camera's only when its runner has a truth), a folder for its
own run, its profile version (`--profile`, always) and its profile variant (`--variant`).

## Methods

Every navigator answers the goal methods:

| Method | Answer |
| --- | --- |
| `hello {client?}` | `{name, version, contract, kinds, camera}`: `contract` is this file's version; `kinds` the goal kinds it takes; `camera` whether it was given one |
| `goal.start {kind, params, budget, conditions, ...}` | `{run_key, ...}` at once, or `{error: {code, message}}` when it will not start one |
| `goal.status` | `{state, reason, result, broken, ...}` |
| `goal.cancel {reason?}` | `{ok}`: the navigator stops the robot, the goal ends `cancelled` |
| `goal.break {name, detail}` | `{ok}`: a guardrail its runner checks by the truth broke; the goal ends `stopped_by_guardrail` |

Then each kind of navigator answers its own, and nothing else (an unknown method is a JSON-RPC
error):

- **The payload** (one process per course run, its navigator kept from one goal to the next):
  `localise` -> `{pose}` (its pose in its own map: a fix, else a survey), `stop` -> `{ok}` (its run
  is closed, the process ends). `goal.status` adds `pose`.
- **The navigator API** (one navigator per goal run): `map` (mapd's grid), and while a goal runs
  `state`, `objects`, `inventory` (RFC-0016). `goal.start` takes `seed`, `goal_run` and `scene`,
  and answers `profile {checksum, version, source}`; `goal.status` adds `progress`, `decisions`,
  `anomalies` (1.1) and
  `objects` (`apps/mission-control/CONTRACT.md`). Its runner adds `runner.status`.

A side that reads `hello` refuses a navigator whose `contract` has another major version than its
own, saying both (`runfile.navcontract.check_hello`); a minor version adds and never changes.

## A goal

`{kind, params, budget {minutes}, conditions {done_when {within_s}, guardrails}}`:

- `point`: `params {x, y}`, in the navigator's map (the payload's) or the site's frame (the
  navigator API's); its time limit is `conditions.done_when.within_s`.
- `explore`: `budget.minutes`; `params` are the navigator's own options (the duck's payload:
  `objects`, `find`, `site`, `object_costs`, `relocalise`; its navigator API: `area`).
- The navigator API's other kinds (`go_to_object`, `go_to_area`, `inventory`) are in
  `apps/mission-control/CONTRACT.md`.

One goal at a time: a `goal.start` while one runs answers `{error: {code: "busy"}}`.

## A goal's states

`idle` before the first goal, `running`, then one end, which is kept until the next `goal.start`.
`reason` says why for every end that is not a success.

| End | Meaning |
| --- | --- |
| `reached` | a goal with a place (`point`, `go_to_area`, `go_to_object`) ended there, by the navigator's belief (its runner judges it by the truth) |
| `done` | a goal without a place (`explore`, `inventory`) ended as it should: nothing left to explore, or its budget spent |
| `refused` | the navigator would not start or go on, and says why: no path on the map, no room to turn, no pose, no such area |
| `not_found` | what the goal looks for was not found |
| `timeout` | the goal's time limit was spent before it was reached |
| `stalled` | the robot stopped getting closer, or walked without moving |
| `stopped_by_guardrail` | a guardrail broke: the navigator's own, or its runner's (`goal.break`); `broken` is `{name, detail}` |
| `cancelled` | `goal.cancel`, or a STOP |
| `interrupted` | the robot was taken from the navigator: a takeover, the lease ended, the robot stopped answering |
| `failed` | anything else: an error, the robot trapped, an object found but not got to |

`reached` and `done` are the successes. A side that reads `goal.status` takes a state the contract
does not have as the navigator's failure, saying which (`runfile.navcontract.check_state`).

A stop asked from outside is named in the navigator's own run as well: its stop event, and the run's
verdict when the stop ends the run, is `stopped_by_guardrail` or `cancelled` (the duck's
`Navigator.stop_goal`).

## 1.2

`goal.start` takes `not_enforced`, a list of guardrail names its runner could not check (a runner on
a host with no truth cannot check `contact`, `fall`, `drop_clearance` or `no_go_area`). The navigator
records one anomaly of the harness for each, `guardrail_unenforced` (severity `minor`, the name in
`values.guardrail`), at the goal's start. A 1.1 navigator ignores the field and raises none; a runner
speaking 1.2 to a 1.1 navigator works as before, without the alarm.

## 1.1

The navigator API's `goal.status` takes `anomalies_since` and adds `anomalies` (the run's anomalies
since then, each RFC-0019's record with its `t` and its number `n`) and `anomalies_n`. A reader of
1.0 ignores them; a 1.0 navigator answers none, which a reader takes as none raised.

## Before 1.0

The payload answered `start`/`status`/`cancel` with `goal: [x, y]` and `time_s`, and its ends were
`reached`, `refused`, `timeout`, `stalled`, `aborted` and `failed`; the navigator API answered `ping`
with no version, and put a timeout and a stall under `failed`. The payload's `aborted` was only
ever its runner's own stop (the truth guard, a broken invariant): `goal.break` now, ending
`stopped_by_guardrail`. The navigator's own stop event was `aborted` too, for any stop, and a run
it ended had the verdict `aborted`. A run recorded then is read with its stop named now, by the
stop's recorded reason (`runfile.navcontract.stop_before`): a reason that says "cancelled ..." is
`cancelled`, every other `stopped_by_guardrail` (the 9 `aborted` events in the Observatory's index on
2026-11-22: 6 falls by an invariant, 2 truth guards at the staircase, 1 contact guardrail). The
reading is in `runfile.wire`, `runfile.store` and `runfile.adapters.duck` (and the duck's
`world.py` and the explore score, which read navigator logs themselves); the file is not changed.
