# The contract: Mission Control's API (version 1, RFC-0014 §3.2)

`mission-control serve` (or `make control-run`; the image of `control/Dockerfile`) serves the API on
`--host`/`MC_HOST` (default `127.0.0.1`) and `--port`/`MC_PORT` (default 8060). The robot files are
read from `--robots`/`MC_ROBOTS`, the SQLite store and the gates' logs are kept in
`--state`/`MC_STATE`. By default there is no login: the tailnet is the authentication (RFC-0014 §3.9);
`--require-tokens` adds per-client tokens (below).
`tests/test_api.py` checks this file against a running server. Units SI (metres, radians, seconds).
Every response that carries a position names its `frame`; the one frame so far is `site`.

## Replies and errors

Every reply is JSON. Success is `{"ok": true, ...}` with the resource under a named key. A failure
is `{"ok": false, "error": {"code", "message", ...data}}` with an honest status code:

| Status | Codes |
| --- | --- |
| 400 | `bad_json` |
| 403 | `not_allowed` (takeover by a name not on the robot's list) |
| 401 | `unauthorized` (tokens are required and the call has none, or one that is not valid) |
| 404 | `not_found` (`what`, `id`), `no_route`, `no_map`, `no_recogniser` |
| 405 | `method_not_allowed` |
| 409 | `held` (`holder`, `since`), `lease_ended` (`reason`), `no_lease`, `not_holder`, `robot_busy`, `run_ended`, `goal_running`, `name_taken`, `label_taken`, `site_in_use`, `area_in_use` |
| 413 | `too_large` |
| 422 | `invalid`, `bad_goal`, `unknown_kind`, `bad_guardrail`, `bad_outline`, `bad_bundle` |
| 501 | `not_built` (`share: split`, RFC-0014 step 10) |
| 502 | `planner_failed` (the LLM planner did not answer, or not with goals) |
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

The exclusive control lock of RFC-0014 §3.3.3 and RFC-0017 is the gate of `robotgate` in front
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
| `GET /goal-runs?robot=&state=&goal=&parent=` | runs, newest first; the children of a group are listed on their own only with `robot` or `parent` |
| `GET /goal-runs/{id}` | one run, with its `decisions`; a group with its `children` |
| `POST /goal-runs/{id}/cancel` | the navigator stops, the robot is stopped; a group's children are all cancelled |
| `POST /plan` | `{text, robot?, site?}`: words in, goals out, nothing run (below) |

`robots` names one robot, or several, or `team` names a team (the robots whose files list it in
`teams`); `share` (below) applies to several. `site` defaults to the robot's site. A `target` of
`real` is refused for the fake robot.

### One goal on several robots

`share: "each"` (the default) has every robot do the whole goal, independently; `share: "any"` ends
the goal when the first robot reaches it and cancels and stops the others; `share: "split"` is
`501 not_built`. The reply is a **group run**: a parent with `share`, `robots` and `children`, one
child run per robot, each an ordinary goal run with `parent_id`. The children start in the order of
the robot ids.

- A robot that cannot take part (offline, busy, or refused by its capabilities) is left out: its child
  is a run in the state `refused` with the reason. If no robot can, the group is `refused`.
- If a robot is **held** by another client, the children already started are cancelled and the
  group is `refused`, naming the robot (RFC-0017 §3.5.3).
- The group ends when its children have. `each`: `reached` or `done` when every robot that took part
  did, one state for all when they ended alike, else `failed` with each robot's state in `reason`;
  `result` is `{robot: {state, reason, result, run}}`. `any`: the winner's state, `result` is
  `{winner, result, robots}`; when no robot reaches it, as for `each`.
- STOP of one robot ends its child `cancelled` and the group goes on with the others.

### Goals in words

`POST /plan` returns `{plan: {goals: [{goal, read_back}], dropped, source, llm_configured,
confirm_required, message, site}}`. The goals are proposals: each is a valid goal, read back in
words, and nothing runs until the operator starts it (`POST /goal-runs` with the goal). The
**phrase matcher** (no model, always there) understands "go to the kitchen" (an area), "go to my
desk" (a label), "go to the fridge" (a kind), "go to 1.5, 0.5", "explore" and "explore the
kitchen", "take an inventory" and "inventory of the study", with "without touching anything" adding
the guardrail `contact`. It matches against the site's own areas, labels and kinds and the kinds
the robots' recognisers know. Only when it finds nothing, and an **LLM planner is configured**, is
the model asked. The LLM is off unless `planner.json` sits beside the robot files:
`{"base_url", "model", "api_key_env" | "api_key_file", "timeout_s"}`, an OpenAI-compatible chat
completions endpoint. What the model says is validated like any goal: an unknown kind, field or
guardrail is dropped (listed in `dropped`), and a plan's guardrails only add to the site's and the
robot's. The planner module imports no robot code: it cannot drive, stop or fire.

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

## The MCP server

`mission-control mcp [--url http://127.0.0.1:8060]` (stdio; env `MC_URL`) is the way in for an outside
agent. It is a client of this API: every tool is one allowed call, and the server calls nothing else
(`ALLOWED` in `mcp_server.py`, 29 routes, checked by `tests/test_mcp.py`). It needs the `mcp` package,
which only this command imports.

| Tools | Calls |
| --- | --- |
| `list_robots`, `get_robot`, `get_robot_map`, `get_sighting` | the robot reads |
| `acquire_lock`, `renew_lock`, `release_lock`, `drive` | the lock and manual driving, as the client `mcp-agent` |
| `stop_robot`, `stop_all` | STOP: always accepted, never needs the lock |
| `list_goals`, `get_goal`, `create_goal`, `run_goal`, `run_adhoc_goal` | the library and runs |
| `list_runs`, `get_run`, `cancel_run`, `save_run` | goal runs |
| `list_sites`, `get_site`, `list_areas`, `area_at`, `list_objects`, `get_inventory`, `get_site_guardrails`, `export_site` | the sites, read only |
| `label_object` | name an object (RFC-0014 §3.5.2) |

An API error is a tool error whose text is `code: message`, so an agent can read why. What an agent
may not do, and how:

- **Fire** (O21, RFC-0014 §3.8): there is no tool for it and no allowed route could do it.
- **Take a robot another client holds** (RFC-0017 §3.5.7): there is no takeover tool; the client name
  is fixed by the operator (`--client` or `MC_MCP_CLIENT`, default `mcp-agent`) and no tool takes one.
  A held robot is refused to the agent, naming the holder.
- **Draw, change or delete areas, make or delete sites, import a site, set a site's guardrails,
  assign a robot to a site** (RFC-0014 §3.5.3: the operator's): not tools, not allowed routes.
- **Run on a real robot** (RFC-0014 §3.8, RFC-0002 §3.5): `target` is `sim` unless the operator
  started the server with `--allow-real` or `MC_MCP_ALLOW_REAL=1`; anything else is refused before the
  call leaves the process.
- **Refuse a STOP** or be refused one: not possible; the tools have no limit.

## Per-client tokens

`mission-control serve --require-tokens` (env `MC_REQUIRE_TOKENS=1`) makes every call carry a token
that names its client: `Authorization: Bearer mc_...`, or `?token=` on the event stream, which a browser
cannot give a header. It refuses to start while no token exists. Without the flag nothing changes: every
call works and a client names itself in the body.

- **Make, list, revoke**: `mission-control token create --client NAME` prints the token once; only its
  sha256 is kept. `token list` shows id, client and state, never the token. `token revoke ID` ends it.
  Over the API (with a token): `GET /tokens` (`required`, `tokens`), `POST /tokens {client}` (201, the
  token shown once) and `DELETE /tokens/{id}` (a second revoke is 409, an unknown id 404). The MCP
  server cannot reach these routes.
- **Always open, with no token or a wrong one**: STOP (`POST /robots/{id}/stop`, `POST /stop`),
  `GET /health` and the page's own files (it has to load to ask for a token). A STOP with a valid
  token is logged under the token's client, otherwise under the name it gave.
- **The token is the identity**: a lock, a takeover, a goal run and a STOP are recorded under the
  token's client, whatever `client` the body says. A takeover is therefore for the names on a robot's
  list only by token. The run carries `client`; so do the `goal-run` and `stop` events.
- **The MCP server** takes `--token` / `MC_TOKEN` and speaks as that client.
- **The page** shows a token box when a call is answered 401, keeps the token in `localStorage`
  (`mc-token`), and STOP and STOP ALL work before any token is entered.
- Tokens are not encryption: over plain HTTP a token is as visible as the tailnet lets it be.

## The page

`GET /` is the page: `web/index.html`, `web/app.js` and `web/style.css` under `/web/`, plain files with
no build step, served by the same server. It is a client of this API and the event stream and has no
call of its own. It shows the robots (online, status, lock holder), the selected robot's map with the
objects and areas layers, a point goal by tapping the map and the other goal kinds by form, the
library, the goal runs with their progress and decisions, area drawing, renaming and deleting, site
export and import, STOP for the selected robot and STOP ALL (always on screen), and a Watch link that
is disabled while a run's `watch` is null. It uses the Observatory's colour tokens, in light and dark,
and fits a 390 px phone. `window.__mc` is a hook for the page test.

## The simulated duck and the navigator API

The adapter type `duck-sim` (`duck.py`; example `robots.sim/duck-sim.json`) puts two processes
between Mission Control and the simulator, both from the duck package:

- **`duck-gate`** (RFC-0017): the one door to robotd. Mission Control is a client of it as
  `mission-control`; the lock, STOP and takeover of the API are the gate's own (the robot file's
  `lease_s` and `takeover` do not apply: they are the gate's flags). A robot's `lock` is the
  gate's `who`; `unreachable` appears in it when the gate does not answer, and the robot is then
  offline.
- **`duck-nav-server`** (O22, `duck_lab/nav/server.py`): the real navigator as its own process,
  JSON-RPC over TCP on loopback (newline framed, RFC-0003's shape). It takes the lease from the
  gate at `goal.start` and gives it back at the end, and writes each goal run as an Observatory
  run `duck/<scene>/mc<id>-<time>`.

Adapter options: `gate_socket`, `navigator` (host:port), `mapd_socket`, `observatory` (the base of
the Watch links), `calibration`. The state is built from robotd's `robot.subscribe` stream (robotd
has no `robot.state` request), the map is mapd's grid in the site frame, and
`GET /robots/{id}/sighting` is `404 no_sighting` (the camera runs with a goal, and its sightings
are in the Observatory run).

The navigator API, as the server speaks it:

| Method | Meaning |
| --- | --- |
| `goal.start {kind, params, budget, conditions {done_when, guardrails}, seed {objects, areas}, goal_run {id, name, kind}}` | `{run_key}` at once, or `{error: {code, message, holder?}}`: `held` (another client holds the robot: the gate's own refusal), `busy`, `unknown_kind` |
| `goal.status {decisions_since, objects_since}` | `{state, reason, progress, result, broken, run_key, decisions, decisions_n, objects, objects_v}`; `objects` is the navigator's whole map, only when it changed |
| `goal.cancel` | the navigator stops, ends the run, gives the lease back |
| `state`, `objects`, `inventory`, `map` | what the navigator sees now, while a run is active |

`seed.objects` are the site's confirmed objects (their ids Mission Control's; they come back as
`seed`); `seed.areas` are the operator's outlines `{id, name, type, outline}`. A goal run's
`run_key` is the Observatory run's key and `watch` is `<observatory>/watch/<run_key>`. The
Observatory run carries `goal_run {id, name, kind, robot}` in its record (`viewer/CONTRACT.md`).

The navigator takes a goal only where the robot's map knows a way: a point or an area in space the
robot has not seen is `refused` ("no path on the map"), as the navigator has always refused it;
exploring first is a goal of its own.

## The NXT

`adapter {"type": "nxt-web", "url": "http://127.0.0.1:8000", "full_speed_mps", "full_turn_rps"}`
(`robots.nxt/nxt-1.json`) is the NXT behind `nxt-web`, which is the only process on the brick's link,
so nxt-web is the robot's gate (RFC-0017): its lock, its STOP and its takeover list
(`--takeover-names`) are the robot's, and the file's `control.takeover` and `control.lease_s` do not
apply to it. Mission Control is a client: `POST /robots/{id}/lock` takes nxt-web's lock in the
client's name and returns the session of this API; drive is `/api/drive` with nxt-web's session, STOP
is `/api/stop`, who holds the lock is `/api/lock`, polled at the state rate (a lease that ended at
nxt-web, by its own page's STOP, expiry or takeover, ends the API's session with nxt-web's reason).
`vx` and `vyaw` become the tracks in percent: both tracks at 100 is `full_speed_mps`, the tracks 50
apart each way is `full_turn_rps`. Those two are the factsheet's `maximumSpeed` and
`maximumAngularSpeed` when the file has them; the NXT's speeds are not measured, so its factsheet
has none and the file sets the two as assumed values (0.3 and 1.5). The state has `mode`, `velocity`
(computed from the tracks), `tracks {left, right}`, `link`, `battery_mv`
and no `pose`; `battery_pct` is null (the voltage to percent curve of the cells is not known).
The NXT has no navigator, so a goal for it is a run in the state `refused` ("this robot has no
navigator"), and it has no map or recogniser. It is reached through nxt-web only, never through a
device; nxt-web offline is the robot offline, and STOP is then accepted and not confirmed.

## Robot files

JSON, one per robot, `<id>.json` (RFC-0014 §3.3.1; decided 2026-11-18 from
`docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md`, VDA 5050 3.0.0 and Open-RMF read). A `factsheet` that is a
subset of VDA's, with **VDA's names verbatim** (camelCase, SI units), and our own snake_case blocks
beside it. An unknown field anywhere is an error naming it; a file of the first format says where
the field went.

| Field | What |
| --- | --- |
| `id`, `label`, `kind` | ours. `id` is lower case, digits and dashes (no `manufacturer` or `serialNumber` until a VDA robot is added); `kind` keys `robots/<kind>/` |
| `adapter {type, call_timeout_s?, ...}` | ours: `fake`, `duck-sim`, `nxt-web`, and each one's options |
| `factsheet.typeSpecification` | VDA: `seriesName`, `seriesDescription`, `mobileRobotKinematics` (`DIFFERENTIAL`, `OMNIDIRECTIONAL`, `THREE_WHEEL`, and **`LEGGED`, which is ours** and not in VDA), `localizationTypes` (VDA's list), `navigationTypes` (open) |
| `factsheet.physicalParameters` | VDA: `maximumSpeed` [m/s], `maximumAngularSpeed` [rad/s], `maximumAcceleration`, `maximumDeceleration`, `width`, `length`, each a number above 0. Left out when not measured |
| `factsheet.protocolFeatures.mobileRobotActions[]` | VDA: `actionType`, `actionScopes` (`INSTANT`, `NODE`, `EDGE`), `blockingTypes` (`NONE`, `SOFT`, `HARD`), `pauseAllowed`, `cancelAllowed`; **`irreversible` is ours** (RFC-0003 §2.3) |
| `control {deadman_s, lease_s, takeover}` | ours: the deadman (default 0.5 s), the lease (10 to 30 s, default 20), the client names that may take a robot over (default none). VDA has no control lock |
| `capabilities {sensors, recognisers, localisation, map, navigator, guardrails, skills, description}` | ours: VDA has no field for them |
| `guardrails` | the robot's own, each of them in `capabilities.guardrails`. A `max_speed` of them may not be above `factsheet.physicalParameters.maximumSpeed`: the file does not load |
| `rates {state_hz, map_hz, max_state_hz}`, `online_after_s`, `teams [names]` | ours |

`GET /robots/{id}` returns `factsheet`, `control` and `capabilities`. The first format's
`capabilities.drive {max_vx, max_vyaw, deadman_s}` is now `factsheet.physicalParameters.maximumSpeed`
and `maximumAngularSpeed` and `control.deadman_s`; its top-level `lease_s` and `takeover` are
`control.lease_s` and `control.takeover`. There is no VDA adapter.

`state_hz` may not exceed `max_state_hz`, which is what the robot's interface allows. A call that
does not answer within `adapter.call_timeout_s` is abandoned on its own thread and counts as an error;
a late answer may still arrive, and the robot's deadman covers it.
