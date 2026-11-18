# The contract: Mission Control's API (version 1, RFC-0014 §3.2)

`mission-control serve` (or `make control-run`; the image of `control/Dockerfile`) serves the API on
`--host`/`MC_HOST` (default `127.0.0.1`) and `--port`/`MC_PORT` (default 8060). The robot files are
read from `--robots`/`MC_ROBOTS`, the SQLite store and the gates' logs are kept in
`--state`/`MC_STATE`. There is no login: the tailnet is the authentication in v1 (RFC-0014 §3.9).
`tests/test_api.py` checks this file against a running server. Units SI (metres, radians, seconds).
Every response that carries a position names its `frame`; the one frame so far is `site`.

## Replies and errors

Every reply is JSON. Success is `{"ok": true, ...}` with the resource under a named key. A failure
is `{"ok": false, "error": {"code", "message", ...data}}` with an honest status code:

| Status | Codes |
| --- | --- |
| 400 | `bad_json` |
| 403 | `not_allowed` (takeover by a name not on the robot's list) |
| 404 | `not_found` (`what`, `id`), `no_route`, `no_map`, `no_recogniser` |
| 405 | `method_not_allowed` |
| 409 | `held` (`holder`, `since`), `lease_ended` (`reason`), `no_lease`, `not_holder`, `robot_busy`, `run_ended`, `goal_running`, `name_taken`, `label_taken`, `site_in_use`, `area_in_use` |
| 413 | `too_large` |
| 422 | `invalid`, `bad_goal`, `unknown_kind`, `bad_guardrail`, `bad_outline`, `bad_bundle` |
| 501 | `not_built` (teams, RFC-0014 step 5), `no_planner` |
| 503 | `robot_offline` |

A command to an offline robot is an error and nothing is queued. A goal that a robot cannot take is
**not** an error: it is a run in the state `refused` with the reason in `reason` (below).

## Robots

| Call | Meaning |
| --- | --- |
| `GET /api/v1/robots` | `[{id, label, kind, online, lock, last_seen_age_s}]` |
| `GET /api/v1/robots/{id}` | the same, plus `capabilities`, `status` (the last state: `pose`, `velocity`, `mode`, `battery_pct`, `link`, `flags`), `guardrails` (the robot's own), `rates`, `site`, `goal_run` |
| `PUT /api/v1/robots/{id}/site` | `{site}` (an id, or null): a robot is at one site at a time; refused while a goal run holds it |
| `GET /api/v1/robots/{id}/map` | the robot's map, `{kind: "occupancy_grid", resolution_m, origin, width, height, data, frame, version}` with data -1 unknown, 0 free, 100 occupied; `404 no_map` when its capabilities have none |
| `GET /api/v1/robots/{id}/sighting` | the latest camera record (ADR-0019): `pose`, `hfov_deg`, `range_m`, `seen[]` with x ahead and y left of the robot; `404 no_recogniser` |
| `POST /api/v1/robots/{id}/drive` | `{vx, vyaw?, session}`; needs the lease; a command lasts the robot's deadman time, so a driver repeats it |
| `POST /api/v1/robots/{id}/stop` | `{client?}`: accepted always, needs no lock; ends the holder's lease and latches. Returns `{robot, confirmed, online}`; `confirmed` is true when the robot answered `robot.stop` |
| `POST /api/v1/stop` | every robot at once, each reported, a silent one after 3 s: `{robots: [...], all_confirmed}` |

**`online`** is a measured fact: the last answer from the robot was within the robot file's
`online_after_s`. It is never a flag the adapter sets. A robot that has not answered since start-up
is offline.

**The client's name** for STOP is `client` in the body, else the `X-Client` header, else `api`; it is
logged and on the event stream.

### The lock

The exclusive control lock of RFC-0014 §3.3.3 and RFC-0017 is the gate of `duck_lab.gate` in front
of every robot. HTTP has no connection to tie a lease to, so a lease is tied to a **session**: a
random id that `acquire` returns and the holder sends with each drive, as nxt-web's `/api/lock`
does. The robot's `lock` field is the gate's `who`: `{holder, since, lease_id, expires_in_s}`, or
`{holder: null, lease_id}`. Mission Control keeps no second copy.

| Call | Meaning |
| --- | --- |
| `POST /robots/{id}/lock` | `{client}`: acquire, `{session, lease_id, expires_in_s}`; `409 held` names the holder and when |
| `POST /robots/{id}/lock/renew` | `{session}` |
| `DELETE /robots/{id}/lock` | `{session}`: release; the robot is stopped, then free |
| `POST /robots/{id}/lock/takeover` | `{client}`: only for the client names in the robot file's `takeover`; the robot is stopped, the old holder's next call is `lease_ended` with `taken_over_by <name>` |

The lease lasts `lease_s` (10 to 30 s, default 20) without a command or a renew. It also ends on
release, STOP and takeover. After any end the session is dead (`lease_ended`, with the reason) and
the holder must acquire again, which works only if the robot is free. A goal run holds the robot
through its navigator, in the name of that navigator (the fake's is `fake-navigator`).

## Goals

A goal: `{name, folder, kind, params, done_when, must_not, expect, budget?, scene?}`. A `GET` returns
it with `id`, `created_at`, `updated_at`, and a `PUT` accepts that back. An unknown field or kind is
a 422.

| `kind` | `params` | `done_when` defaults | `budget` |
| --- | --- | --- | --- |
| `point` | `{x, y, frame?: "site" \| "map"}` | `within_m` 0.25, `within_s` 60 | none |
| `go_to_object` | exactly one of `kind`, `id`, `label`; `area?` | `within_m` 0.35, `facing_deg` 45, `within_s` 300 | `{minutes}`, default 5: the exploring |
| `go_to_area` | `{area}` (an id or a name) | `within_s` 300 | none |
| `explore` | `{area}` or `{site: true}` | none | `{minutes}`, default 5 |
| `inventory` | `{areas?: [...]}` (none: the whole site) | none | `{minutes}`, default 5 |

`expect` is `reach` (default) or `refuse`. `folder` is a path such as `tests/course`.

| Call | Meaning |
| --- | --- |
| `GET /goals?folder=` | the library; a folder lists itself and its subfolders |
| `POST /goals` | define one: 201; a name is unique in its folder |
| `GET`, `PUT`, `DELETE /goals/{id}` | read, change, retire; neither change nor retire while a run of it is active |
| `POST /goals/{id}/runs` | `{robots: [id], target?: "sim" \| "real", site?}`: 201, a goal run |
| `POST /goal-runs` | `{goal, robots, target?, site?}`: a goal that is not in the library; saves none |
| `POST /goal-runs/{id}/save` | `{name, folder?}`: the run's goal goes in the library and the run links to it |
| `GET /goal-runs?robot=&state=&goal=` | runs, newest first |
| `GET /goal-runs/{id}` | one run, with its `decisions` |
| `POST /goal-runs/{id}/cancel` | the navigator stops, the robot is stopped |
| `POST /plan` | `501 no_planner`: no planner is configured |

`robots` names one robot; two or more, or `team`, is `501 not_built` (RFC-0014 step 5). `site`
defaults to the robot's site. A `target` of `real` is refused for the fake robot.

### A goal run

`{id, goal_id, goal (a copy), robot, site, target, state, reason, progress, result, broken,
guardrails, conditions, run_key, watch, expect, as_expected, created_at, started_at, ended_at}`.

States: `queued`, `running`, then one of `reached`, `done`, `refused`, `failed`,
`stopped_by_guardrail`, `not_found`, `cancelled`, `interrupted`. `reason` says why for every end that
is not `reached` or `done`.

- `reached` and `done` are the successes: `done` is for `explore` and `inventory`, which have no
  target to reach and end `done` whether no frontier is left or the budget is spent.
- `refused`: the run could not start (a capability the robot lacks, the robot is held, no path, an
  area that is not there). It is an ended run.
- `failed`: the robot tried and a condition broke (the time limit of `done_when`).
- `stopped_by_guardrail`: a guardrail broke; `broken` is `{name, detail}`. Not the same as `failed`.
- `not_found`: an object goal whose exploring ended without finding it.
- `cancelled`: `cancel`, or a STOP (the latch). `interrupted`: a takeover, or the robot stopped answering.
- `as_expected` is null while running, then true when the end matches `expect` (`reach`: `reached` or
  `done`; `refuse`: `refused`).
- `progress`: `elapsed_s`, `pose`, `area` (the area it believes it is in, by the operator's outlines,
  or null), `guardrails_ok`, `distance_left_m`, and for exploring `waypoints_visited`,
  `cells_explored`. Written at most once a second.
- `result` by kind: `go_to_object` `{object: {id, kind, x, y, label, frame}, stand: {x, y, yaw, frame}}`
  (the id is the site's stable one); `inventory` `{areas: [{area, name, objects}], none_defined,
  cells_explored, objects_found, ended_by}`; `explore` `{cells_explored, objects_found, ended_by}`
  where `ended_by` is `no_frontier_left` or `budget`; `point` and `go_to_area` none.
- `conditions`: `{done_when, not_checkable}`; `not_checkable` lists the `done_when` keys the robot's
  navigator cannot check.
- `run_key` and `watch` are null for the fake robot: it writes no Observatory run.

### Guardrails

A goal's `must_not` is a list of names or `{name, limit}` objects. At every run the robot's own
(its file), the site's and the goal's are merged: a goal can add and never remove or loosen, and of
two limits of one name the stricter wins. The run's `guardrails` is the merged list, each entry with
`from` (the levels that name it). The robot's navigator checks them while it runs.

| Name | Limit | Stricter |
| --- | --- | --- |
| `contact`, `fall`, `stuck` | none | |
| `time_limit` | `seconds` | smaller |
| `max_speed` | `mps` | smaller |
| `drop_clearance` | `m` | larger |
| `no_go_area` | `area` (an area of the site) | |

`drop` is accepted as `fall` and `stall` as `stuck` (RFC-0014 §3.4.1's example). A goal that needs a
guardrail the robot's `capabilities.guardrails` does not list is `refused`, naming it.

## Sites, areas and objects

Several sites, any kind of place (`kind` is free text). Ids are slugs of the name and do not change
when it does. **Only the operator's calls create, change or delete an area;** a goal run never does.

| Call | Meaning |
| --- | --- |
| `GET`, `POST /sites` | list, create `{name, kind}` |
| `GET`, `PUT`, `DELETE /sites/{s}` | read, change `{name?, kind?}`, retire (refused while a robot is at it) |
| `GET`, `POST /sites/{s}/areas` | list (with the object ids in each), create `{name, type?, outline}` |
| `GET`, `PUT`, `DELETE /sites/{s}/areas/{a}` | read, change `{name?, type?, outline?}`, delete |
| `POST /sites/{s}/areas/{a}/merge` | `{other, name?, type?, outline?}`: `other` is folded in; the outline is the convex hull of both unless given |
| `POST /sites/{s}/areas/{a}/split` | `{line: [[x, y], [x, y]], name, name_kept?}`: the area keeps the left of the directed line, a new area `name` takes the right |
| `GET /sites/{s}/areas/at?x=&y=` | which area holds the point (of nested areas the smallest), or `area: null` and `message: "none defined"` |
| `GET /sites/{s}/objects` | `[{id, kind, label, x, y, frame, parts, confirmed, landmark, confidence, n, unique, first_seen, last_seen, seen_by, evidence, area}]` |
| `POST /sites/{s}/objects/{id}/label` | `{label}` (null clears); unique in the site, case-insensitively |
| `GET /sites/{s}/inventory` | the confirmed objects by area, and `none_defined` |
| `POST /sites/{s}/export` | the site, the operator's areas, its labelled objects and its guardrails as one JSON document: `{bundle}` with `format: "mission-control-site"`, `version: 1`, `site`, `areas`, `objects`, `guardrails` (no-go areas by name). Objects nobody named are not in it |
| `POST /sites/{s}/import` | `{bundle}` (or the bundle as the body), merged into this site, all or nothing. An area of the same name has its type and outline replaced; a labelled object joins an unnamed object of its kind within the association gate and names it, else becomes a new confirmed object; a label another object here has is skipped and reported; the guardrails are added. Returns `{imported: {areas: {created, updated}, objects: {created, labelled, skipped}, guardrails}}`; a file that is not a site file is `422 bad_bundle` |
| `GET`, `PUT /sites/{s}/guardrails` | `{guardrails: [...]}`, including `no_go_area`; an area that a guardrail names is not deleted, merged away or split |

An **outline** is a list of at least three `[x, y]` in the site frame, simple (no crossing), with an
area above zero; it is stored counter-clockwise. A split line must cross the outline in exactly two
places and miss every corner. An object's `area` is the outline that holds its position, by geometry,
or null.

Objects get Mission Control's own stable ids (`obj-1`, ...). A run's objects are merged into the site's:
the same kind within 0.5 m (1.5 m for a kind the navigator calls unique) is the same object, and a
label is never touched by a merge.

## The event stream

`GET /api/v1/events` is server-sent events. Each event is `id: <seq>`, `event: <kind>` and `data:` the
JSON `{seq, t, kind, robot, ...}`. Query:

- `since=<seq>`: replay what the ring (the latest 5000) still holds after it, then go live.
  Without it the stream starts from the `Last-Event-ID` header (a browser's EventSource sends it
  when it reconnects), else from now. When the ring no longer holds all of it, an
  `event: gap` comes first.
- `robots=a,b`, `goal_run=<id>`: filters.
- `state_hz=<n>`: lowers the state rate of this subscription. It cannot raise it above the robot's.

| Kind | When |
| --- | --- |
| `state` | each robot's status at its `rates.state_hz` (default 2) |
| `map` | when a robot's map changes, at most `rates.map_hz` (default 1) |
| `robot-online`, `robot-offline` | a change, with the error |
| `lock` | the gate's log: `event` is `acquired`, `refused`, `released`, `expired`, `taken_over`, `lease_ended`, `stop`, `stop_failed` |
| `stop`, `stop-all` | every STOP, with the client's name |
| `goal-run` | a state change or progress, with `goal_run` |
| `decision` | the navigator's decisions with their reasons, with `goal_run` |
| `objects` | objects merged into a site (`changes`) |
| `object-named` | an operator's label |

A comment line `: keepalive` comes every 15 s.

## The page

`GET /` is the page: `web/index.html`, `web/app.js` and `web/style.css` under `/web/`, plain files with
no build step, served by the same server. It is a client of this API and the event stream and has no
call of its own. It shows the robots (online, status, lock holder), the selected robot's map with the
objects and areas layers, a point goal by tapping the map and the other goal kinds by form, the
library, the goal runs with their progress and decisions, area drawing, renaming and deleting, site
export and import, STOP for the selected robot and STOP ALL (always on screen), and a Watch link that
is disabled while a run's `watch` is null. It uses the Observatory's colour tokens, in light and dark,
and fits a 390 px phone. `window.__mc` is a hook for the page test.

## Robot files

JSON, one per robot, `<id>.json`. The format is provisional (RFC-0014 §5 question 21: the VDA 5050
and Open-RMF specs are not read yet). Fields: `id`, `label`, `kind`, `adapter {type, call_timeout_s?}`,
`capabilities {drive, sensors, recognisers, localisation, map, navigator, guardrails, skills,
description}`, `guardrails` (the robot's own, each of them in `capabilities.guardrails`),
`rates {state_hz, map_hz, max_state_hz}`, `lease_s`, `online_after_s`, `takeover [client names]`.
`state_hz` may not exceed `max_state_hz`, which is what the robot's interface allows. A call that
does not answer within `adapter.call_timeout_s` is abandoned on its own thread and counts as an error;
a late answer may still arrive, and the robot's deadman covers it.
