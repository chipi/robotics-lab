# The navigator contract

**Version 1.8.** What a navigator answers to its runner and to Mission Control: the duck's payload
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
| `goal.start {kind, params, budget, conditions, start_pose?, ...}` | `{run_key, ...}` at once, or `{error: {code, message}}` when it will not start one |
| `goal.status` | `{state, reason, result, broken, ...}` |
| `goal.cancel {reason?}` | `{ok}`: the navigator stops the robot, the goal ends `cancelled` |
| `goal.break {name, detail}` | `{ok}`: a guardrail its runner checks by the truth broke; the goal ends `stopped_by_guardrail` |

Then each kind of navigator answers its own, and nothing else (an unknown method is a JSON-RPC
error):

- **The payload** (one process per course run, its navigator kept from one goal to the next):
  `localise` -> `{pose}` (its pose in its own map: a fix, else a survey), `stop` -> `{ok}` (its run
  is closed, the process ends). `goal.status` adds `pose`.
- **The navigator API** (one navigator per goal run): `goal.anomaly {kind, summary, values?}` (1.6,
  below), `map` (mapd's grid; in true metres with `units: "site"`, 1.8), `site_pose` (1.8), and
  while a goal runs `state`, `objects`, `inventory` (RFC-0016). `goal.start` takes `seed`,
  `goal_run` and `scene`,
  and answers `profile {checksum, version, source}`; `goal.status` adds `progress`, `decisions`,
  `anomalies` (1.1) and
  `objects` (`apps/mission-control/CONTRACT.md`). Its runner adds `runner.status`. It answers
  `calibration.list`, `calibration.start`, `calibration.status` and `calibration.cancel` (1.3,
  below); the payload does not.

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

## 1.8

The **navigator API** owns the conversion from robotd's odometry to the site frame, so a client
(Mission Control; a ROS connector later) holds no frame and no scale of its own (technical review
2.b). Both changes are additive; a navigator below 1.8 answers neither, and a client that asked
and reads no `frame: "site"` or `units: "site"` was not heard (as for `placed`, 1.5).

- `site_pose {odom: {x, y, yaw}}` -> `{x, y, yaw, frame: "site", placed}`: robotd's odometry pose
  (unscaled, in the odometry's frame) as the site frame has it, in metres and radians. With `k` the
  `localisation.odometry.scale` of the profile the latest goal ran, and `F` the `placed.frame` that
  goal's `goal.start` answered (its start pose's change from mapd's frame, rounded as answered):
  `(x, y) = (F.x k, F.y k) + R(F.yaw) (odom.x k, odom.y k)` and `yaw = wrap(F.yaw + odom.yaw)`.
  `placed` says whether `F` was set; a goal with no `start_pose`, and a navigator before any goal,
  have no frame (identity), and then `k` is the scale of the profile the navigator was given. It
  is the odometry through the one scale, as the page has always shown it, not the navigator's
  belief (`goal.status`'s `progress.pose`: fixes, the by-speed steps). `odom` that is not three
  finite numbers is `{error: {code: "bad_pose", message}}`. The runner answers it on a connection of
  its own, as `map`, so a `goal.start` in progress never holds it.
- `map {units: "site"}` answers the grid as `map` does (the latest goal's placed frame, the same
  cells) with `res_m` and `origin` in true metres (times `k`) and `units: "site"`. `map` with no
  `units` is unchanged: mapd's own metres.

## 1.7

The **navigator API** records a `robot_guard` anomaly (source `robot`, in `goal.status`'s
`anomalies` as any other; phase 5 item 4e E2) when its robot's own sensors (`guardrails.RobotSide`:
`fall`, `contact`, `drop_clearance`) break a guardrail, with `values {guardrail, detail,
enforced}`:

- **`enforced` true, severity `critical`:** the runner has no truth for that name (`not_enforced`,
  1.4), so the robot's sensors are the only judge: the goal ends `stopped_by_guardrail` and Mission
  Control's alarm feed shows the stop as critical.
- **`enforced` false, severity `minor`:** the runner has the truth for that name. The robot's check
  runs beside it and only records what it would have done (once per name per goal); the goal is not
  stopped by it, the runner's referee judges, and where the truth agrees its `guardrail_broken`
  is the critical alarm. Minor, so a run where the robot's sensors and the truth part is visible
  without raising a second critical alarm for one event.

The navigator's own rules (`time_limit`, `stuck`, `max_speed`, `no_go_area`) are not `robot_guard`.
A goal also records a `guardrails_robot_record` event naming the names it records only. No new
method and no new field: a runner that does not know the kind reads it as any anomaly.

## 1.6

The **navigator API** answers `goal.anomaly {kind, summary, values?}`: an anomaly its runner
measured and the navigator cannot see, recorded once per kind in the run (source `harness`) and
served in `goal.status`'s `anomalies` as any other (phase 5 item 4b unit B8). The only kind is
`rtf_low`: the simulator's real-time factor (its simulated seconds per wall second since the
goal's first truth sample) read under the runner's threshold (`simhost.truth.RTF_LOW`, 0.95, a
guess; `lab-nav-server --rtf-low`) after 5 s of wall time, with `values {sim_s, wall_s, rtf,
below}`. Severity `minor`: the robot is not unfit, the simulator is slow. The goal goes on; **the
run has no verdict**: the runner records `no_verdict` and the clock in the run's `runner.json`, and
Mission Control ends the run with `as_expected` null. Another kind is `{error: {code:
"bad_anomaly"}}`, and a goal that is not running ignores it. A runner tells a navigator only if its
`hello` names 1.6 or later; the payload answers none (`lab-challenge` withholds the verdict itself:
`pass` null and `no_verdict` in the row). A host with no simulated time (the NXT's) has no factor
and no check. The runner keeps the clock for every goal: `clock {sim_s, wall_s, rtf}` in
`runner.json`, and `sim_time` beside `wall_ns` in each line of the run's `truth.jsonl`.

## 1.5

`goal.start` of the **navigator API** takes `start_pose {x, y, yaw}`: where the operator says the
robot stands on the map when the goal starts (metres in the map's frame, which is the frame goals,
areas and objects are given in, and radians). A robot with no truth cannot read where it is placed,
so the word is taken and the frame is set by it (phase 5 item 4b unit B7):

- The navigator puts every pose and the grid of its localisation into that frame: the change is its
  localisation's pose now against `start_pose` (a localisation with no pose yet starts its map at
  the robot's first stop, which is here). It records a `placed` event, with a decision, in the run.
- The answer adds `placed {pose {x, y, yaw, frame}, frame {x, y, yaw}}`: the pose taken, and the
  change from mapd's frame to the map's, in mapd's own (unscaled) metres, as `map`'s grid is. A
  goal started with no `start_pose` is in mapd's frame, as before: the frame is per goal.
- `map` is answered in the frame of the latest goal's start pose (none: mapd's, as before).
- It checks only the word: `start_pose` must be three finite numbers, and not inside a `no_go_area`
  the goal carries (`outline`), else `{error: {code: "bad_start_pose", message}}`. It cannot tell a
  pose that is wrong; with a truth, the run's official copy is made as ever, and the truth shows
  where the robot stood (the run records both).
- A navigator below 1.5 ignores the field and answers no `placed`: a client sends `start_pose` only
  to one whose `hello` names 1.5 or later (`runfile.navcontract.speaks`) and refuses the goal for
  the others, since a goal run in the wrong frame is worse than none. The payload takes none.

## 1.4

A runner with no truth (a real robot's) lists `contact`, `fall` and `drop_clearance` in
`not_enforced`; from 1.4 the **navigator API** checks them by the robot's own sensors (phase 5
item 4b unit B3, `duck_lab.nav.guardrails.RobotSide`), and a break ends the goal
`stopped_by_guardrail` with `broken` naming the guardrail, as a truth break does:

- `fall`: the IMU's tilt (the larger of pitch and roll) at or over the profile's
  `robot_guards.fall_tilt_deg` for `fall_s`, or mapd lost as `fell`. It cannot see a fall under the
  angle, or an IMU that went quiet (the stale-stream stop is the backstop).
- `contact`: mapd newly lost as `bumped` or `carried` after the goal began (the first account is
  the baseline). It cannot see a touch mapd did not feel.
- `drop_clearance {m}`: the belief's distance to the drops the forward sensor has seen (cliff
  stops' points, a glance's edges), under `m`. It cannot see a drop it has not seen: an unmapped
  rim approached from the side ([CH22-RIM.md](../../docs/wip/CH22-RIM.md)) is not covered.

For these names it records no `guardrail_unenforced` anomaly. It records one
`guardrails_robot_side` event naming them, its `goal.status` `progress` carries
`guardrails_robot_side`, and a break's `guardrail` event says `side: robot`. Every other name in
`not_enforced` (`no_go_area`) is raised as before. They are weaker than the truth and not armed
where the runner has it. A navigator of 1.3 or below still raises the anomaly for all; the payload
(the courses' navigator) does not check them.

## 1.3

The navigator API answers four methods for **calibration**: a short scripted motion that measures
one number of the robot (phase 5 item 4a unit A3, RFC-0023 D11). Mission Control starts it, the
operator keeps or discards what it measured. The navigator drives and reports what the robot's own
sensors said; it never sees the truth, so the **reference** (what the floor says) is its runner's
(the host's truth) or an operator's tape. One calibration at a time, and never with a goal: either
answers `{error: {code: "busy"}}` to the other.

| Method | Answer |
| --- | --- |
| `calibration.list` | `{procedures: [{id, params}]}`: what it drives, each with its parameters' defaults (the profile version it runs: `odometry_scale` takes `speed_mps`, `seconds`; `max_speed_mps` says the most) |
| `calibration.start {procedure, params?}` | `{ok, procedure, params}` (the parameters it runs with) at once, or `{error: {code, message, holder?}}`: `busy`, `held` (another client holds the robot: the gate's refusal, nothing began), `unknown_procedure`, `bad_params`, `start_failed` |
| `calibration.status` | `{state, procedure, step, reason, params, measured, marks}`, and from a runner `reference` |
| `calibration.cancel` | `{ok}`: the robot stands, the run ends `cancelled` |

`state` is `idle` (before the first), `running`, then one end: `done`, `refused`, `cancelled`,
`interrupted` or `failed`, with the goal's meanings (`runfile.navcontract.CALIBRATION_STATES`). It
holds the robot's lease from the start to its end, and a takeover or a STOP ends it as it ends a
goal (`interrupted`, `cancelled`). `step` names where a running one is. A finished run's answer is
kept until the next start.

`odometry_scale` (the one procedure so far) stands still, walks straight at `speed_mps` for
`seconds` (2 to 30; no wall, cliff or guardrail is checked: it walks blind), and stands still. Its
`measured` is `{odom_m, speed_mps, seconds}`: how far robotd's own odometry, unscaled, says the
robot went. `marks` are its two instants, `[{name: "start" | "end", wall_ns, odom}]`: the host's
wall clock, the one a runner pairs its truth by.

**The reference** is added by the runner when a procedure is `done`: `reference` is `{by: "truth",
distance_m, from, to}`, the truth's distance between the marks (it samples the truth from the
start), or `null` when its host has no truth (a real robot's). With `null` the operator measures
with a tape and gives the distance to Mission Control. A navigator reached without a runner sends
no `reference`, which is read as `null`.

**What the numbers mean** is Mission Control's, not the navigator's (`mission_control.calibration`):
the procedure's step guide, the setting it sets, and how a measurement and a reference become its
value (`odometry_scale`: reference over `odom_m`, kept as `localisation.odometry.scale`, and the
`by_speed` entry at the speed walked, in the variant the robot runs).

A navigator of 1.2 or below answers none of this: a client asks only a navigator whose `hello`
names 1.3 or later (`runfile.navcontract.speaks`), and lists no procedures for the others.

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
