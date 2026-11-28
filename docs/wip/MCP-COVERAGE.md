# MCP coverage: every HTTP route against the MCP tools

Step 3 of the MVP 1 wrap-up ([PHASE5-NEXT-PLAN](PHASE5-NEXT-PLAN.md)), part 1 and 2, 2026-11-24.
Every route of Mission Control's API (`apps/mission-control/src/mission_control/api.py`,
`apps/mission-control/CONTRACT.md`) and of the Observatory's server
(`apps/observatory/src/observatory/server.py`, `apps/observatory/CONTRACT.md`) against the MCP
tools. Mission Control's MCP is `apps/mission-control/src/mission_control/mcp_server.py`; the
Observatory's (read-only) is
`apps/observatory/src/observatory/mcp_server.py`.

The decision column is one of:

- **covered**: a tool already called the route before this step.
- **added**: a tool this step added, through the allow-list `Api`.
- **excluded**: not a tool and not an allowed route, with the rule that says so.
- **Observatory MCP**: a tool of the Observatory's read-only server, named in the row.

The rules, from `mcp_server.py`'s docstring: R1 no firing (O21, RFC-0014 §3.8); R2 no takeover
(RFC-0017 §3.5.7); R3 areas, sites, import and a robot's site are the operator's (RFC-0014 §3.5.3);
R4 a real robot only with `MC_MCP_ALLOW_REAL=1` (RFC-0014 §3.8, RFC-0002 §3.5); R5 STOP is never
refused; R6 tokens are the operator's (RFC-0014 §3.9); R7 a profile is the robot's limits and only
the operator writes one; R8 no opting a goal out of its rehearsal (sim-first). A rule written here
that RFC-0014 does not state in so many words (R6 to R8, and the reasons given for the profile,
calibration, goal-edit, plan and stream rows) is this
step's decision and is open to the operator's change. **R6, R7 and R8 were confirmed by the operator
on 2026-11-26** as written: tokens stay the operator's, a profile is written only by the operator,
and no
goal opts out of its rehearsal.

## Mission Control

| Method | Path | What it does | Tool | Decision |
| --- | --- | --- | --- | --- |
| GET | `/health` | whether it answers, how many robots | `get_health` | added |
| GET | `/robots` | the robots, online, lock holder | `list_robots` | covered |
| GET | `/robots/{id}` | one robot: capabilities, status, alarms, profile brief | `get_robot` | covered |
| GET | `/robots/{id}/facts` | what the robot is and runs (RFC-0032 §3.1); `refresh=1` re-reads | `get_robot_facts` | covered |
| GET | `/robots/{id}/actions` | the action catalogue, read only (RFC-0032 §3.3) | `get_robot_actions` | covered |
| POST | `/robots/{id}/drive` | drive under the lease | `drive` | covered |
| POST | `/robots/{id}/lock` | take the lock | `acquire_lock` | covered |
| POST | `/robots/{id}/lock/renew` | keep the lease | `renew_lock` | covered |
| DELETE | `/robots/{id}/lock` | release the lock | `release_lock` | covered |
| POST | `/robots/{id}/lock/takeover` | take a robot another client holds | none | excluded (R2) |
| POST | `/robots/{id}/stop` | STOP one robot | `stop_robot` | covered |
| POST | `/stop` | STOP every robot | `stop_all` | covered |
| GET | `/robots/{id}/map` | the occupancy grid | `get_robot_map` | covered |
| GET | `/robots/{id}/sighting` | the latest camera record | `get_sighting` | covered |
| GET | `/robots/{id}/description` | the robot's body for the page | `get_robot_description` | added |
| GET | `/robots/{id}/meshes/{file}` | one mesh, binary STL | none | excluded (binary file; the tools answer JSON; the page's asset) |
| GET | `/robots/{id}/profile` | the profile versions and the running profile | `get_profile` | added |
| POST | `/robots/{id}/profile` | save a whole profile as the next version | none | excluded (R7) |
| PUT | `/robots/{id}/profile/current` | make a saved version current | `use_profile_version` | added (real robot: R4) |
| GET | `/robots/{id}/profile/export` | one version whole, with its checksum | `get_profile_version` | added |
| POST | `/robots/{id}/profile/import` | import a version from another machine | none | excluded (R7) |
| GET | `/robots/{id}/profile/diff` | two versions compared leaf by leaf | `diff_profile_versions` | added |
| GET | `/robots/{id}/calibration` | procedures and the latest run | `get_calibration` | added |
| POST | `/robots/{id}/calibration` | start a run; the robot walks | `start_calibration` | added (real robot: R4) |
| POST | `/robots/{id}/calibration/cancel` | end the run, the robot stands | `cancel_calibration` | added |
| POST | `/robots/{id}/calibration/reference` | the operator's tape distance, where the runner has no truth | none | excluded (the tape is the operator's measurement; an agent would invent it) |
| POST | `/robots/{id}/calibration/keep` | keep the measured value as the next profile version | `keep_calibration` | added (real robot: R4; the bounds still apply) |
| DELETE | `/robots/{id}/calibration` | forget the run | none | excluded (not needed: the next start replaces a finished run) |
| PUT | `/robots/{id}/site` | assign a robot to a site | none | excluded (R3) |
| GET | `/goals` | the library | `list_goals` | covered |
| POST | `/goals` | define a goal | `create_goal` | covered (`sim_first: false` refused, R8) |
| GET | `/goals/{id}` | one goal | `get_goal` | covered |
| PUT | `/goals/{id}` | change a goal | none | excluded (the operator's library: an edit drops the rehearsal of a goal; `create_goal` and `save_run` make new ones) |
| DELETE | `/goals/{id}` | retire a goal | none | excluded (same) |
| POST | `/goals/{id}/runs` | run a library goal | `run_goal` | covered; `start_pose` added; target by R4 |
| POST | `/goal-runs` | run a goal that is not saved | `run_adhoc_goal` | covered; `start_pose` added; target by R4; R8 |
| GET | `/goal-runs` | the runs | `list_runs` | covered |
| GET | `/goal-runs/{id}` | one run: state, decisions, `conditions.rehearsal` | `get_run` | covered |
| POST | `/goal-runs/{id}/cancel` | cancel a run | `cancel_run` | covered |
| POST | `/goal-runs/{id}/save` | put the run's goal in the library | `save_run` | covered |
| POST | `/plan` | words in, goals out, nothing run | none | excluded (the agent is the planner; the phrase matcher and the LLM planner are the page's; a test has always held it out) |
| GET | `/sites` | the sites | `list_sites` | covered |
| POST | `/sites` | make a site | none | excluded (R3) |
| GET | `/sites/{s}` | one site, with its dock pose | `get_site` | covered |
| PUT | `/sites/{s}` | rename or retype a site | none | excluded (R3) |
| DELETE | `/sites/{s}` | delete a site | none | excluded (R3) |
| POST | `/sites/{s}/export` | the site as one document (read only) | `export_site` | covered |
| POST | `/sites/{s}/import` | merge a site file in | none | excluded (R3) |
| GET | `/sites/{s}/areas` | the areas | `list_areas` | covered |
| POST | `/sites/{s}/areas` | draw an area | none | excluded (R3) |
| GET | `/sites/{s}/areas/at` | the area holding a point | `area_at` | covered |
| GET | `/sites/{s}/areas/{a}` | one area | `get_area` | added (the route was allowed, no tool called it) |
| PUT | `/sites/{s}/areas/{a}` | change an area | none | excluded (R3) |
| DELETE | `/sites/{s}/areas/{a}` | delete an area | none | excluded (R3) |
| POST | `/sites/{s}/areas/{a}/merge` | merge two areas | none | excluded (R3) |
| POST | `/sites/{s}/areas/{a}/split` | split an area | none | excluded (R3) |
| GET | `/sites/{s}/objects` | the objects | `list_objects` | covered |
| POST | `/sites/{s}/objects/{o}/label` | name an object | `label_object` | covered (RFC-0014 §3.5.2) |
| GET | `/sites/{s}/inventory` | the confirmed objects by area | `get_inventory` | covered |
| GET | `/sites/{s}/guardrails` | the site's guardrails | `get_site_guardrails` | covered |
| PUT | `/sites/{s}/guardrails` | set the site's guardrails | none | excluded (R3; a guardrail is a limit) |
| GET | `/tokens` | the tokens, whether they are required | none | excluded (R6) |
| POST | `/tokens` | make a token | none | excluded (R6) |
| DELETE | `/tokens/{id}` | revoke a token | none | excluded (R6) |
| GET | `/events` | the live stream, server-sent events | none | excluded (a stream does not fit a call and its answer; the agent follows with `get_run` and `get_robot`) |
| GET | `/`, `/web/*`, `/lib/*` | the page's files | none | excluded (not the API) |

`get_alarms` (the `alarms` of `GET /robots/{id}`) is a view of a covered route,
not a route of its own.

### What the plan asked for that the API does not have

These were named in the plan as gaps to close; each is a gap in the API, not in the MCP, and none
is built here (a new route is a change to the contract, not to the tool list).

| Asked | State |
| --- | --- |
| acknowledge an alarm | no route and no acknowledge in the API: an alarm ages out of the one-minute window; `get_alarms` reads the feed |
| telemetry status | no route: telemetry is the process's own exporter (`mission-control serve`), not served; its check is `make telemetry-send-check` |
| the simulator-first state of a goal | no route of its own: it is `conditions.rehearsal` on a real run (`get_run`), and a never-rehearsed real run is a `refused` run naming the robot to rehearse on; the rehearsal is found with `list_runs(goal_id)` |
| set the dock | no route: the first start pose a site sees is its dock, shown by `get_site` |

## Observatory

The Observatory answers `GET` and `HEAD` and one `POST`; everything else is a 405. Its MCP is
read-only, so a route that writes or starts work is excluded. The plan also names anomalies,
compare and the archive's dry run for that MCP: they are commands and queries of the Observatory
(`anomalies.py`, `query.py`, the CLI), not HTTP routes, so they are not in this table.

| Method | Path | What it does | Decision |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | runs, data folder, cache | Observatory MCP (`get_health`) |
| GET | `/api/v1/scenes` | the scenes with their runs | Observatory MCP (`list_scenes`) |
| GET | `/api/v1/scenes/{id}` | one scene, what is really there | Observatory MCP (`get_scene`) |
| GET | `/api/v1/runs` | the runs, filtered | Observatory MCP (`list_runs`) |
| GET | `/api/v1/runs/{robot}/{scene}/{run}` | one run's summary | Observatory MCP (`get_run`, `compare_runs`) |
| GET | `/api/v1/runs/.../frames` | the ticks in a window | excluded (a heavy window; not exposed yet) |
| GET | `/api/v1/runs/.../signals` | the signals in a window | excluded (a heavy window; not exposed yet) |
| GET | `/api/v1/runs/.../sensor` | the raw depth frame at a time | excluded (a heavy window; not exposed yet) |
| GET | `/api/v1/runs/.../state` | belief, truth, the last event at a time | Observatory MCP (`get_run_state`) |
| GET | `/api/v1/runs/.../events` | what happened, when | Observatory MCP (`get_run_events`) |
| GET | `/api/v1/runs/.../semantic` | the semantic map in a window | Observatory MCP (`get_run_semantic`) |
| GET | `/api/v1/runs/.../presence` | per stream, where there is data | Observatory MCP (`get_run_presence`) |
| GET | `/api/v1/runs/.../live` | server-sent events of a run being written | excluded (a stream; the MCP reads windows with `events` and `state`) |
| GET | `/api/v1/robots` | the robots with a description | Observatory MCP (`list_robots`) |
| GET | `/api/v1/robots/{robot}` | one robot's description | Observatory MCP (`get_robot`) |
| GET | `/api/v1/robots/{robot}/meshes/{file}` | a mesh, binary STL | excluded (binary file) |
| GET | `/api/v1/render` | the render service's engines | excluded (the render service is the video path, not exposed) |
| POST | `/api/v1/runs/.../video` | start a render job | excluded (it starts work on a shared service: not read-only) |
| GET | `/api/v1/videos/{id}` | a render job's state | excluded (the render service is the video path, not exposed) |
| GET | `/api/v1/videos/{id}/file` | the finished video, binary | excluded (binary file) |
| GET | `/watch/{robot}/{scene}/{run}` | the watch page, HTML | excluded (a page) |
| GET | `/`, `/web/*`, `/lib/*` | the pages' files | excluded (not the API) |
| any | `/control/*` | a proxy to Mission Control behind this origin | excluded (it would carry any call to Mission Control past its allow-list; its MCP is its own) |

## Counts

| | Rows | covered | added | excluded | Observatory MCP |
| --- | --- | --- | --- | --- | --- |
| Mission Control | 64 (63 routes and the page's files) | 28 | 11 | 25 | n/a |
| Observatory | 23 (20 API routes, the watch page, the files, the proxy) | n/a | n/a | 12 | 11 |

Mission Control's tools: 28 before this step, 40 now (12 new: `get_health`,
`get_robot_description`, `get_alarms`, `get_area`, `get_profile`, `get_profile_version`,
`diff_profile_versions`, `use_profile_version`, `get_calibration`, `start_calibration`,
`cancel_calibration`, `keep_calibration`); the allow-list 29 routes before, 39 now. `run_goal`
and `run_adhoc_goal` also take `start_pose`.

## What this step did not check

- The Observatory MCP was driven against test Observatories only
  (`apps/observatory/tests/test_mcp.py`), not the deployed one. Anomalies and the archive dry
  run are CLI only and not tools.
- The tools were driven against the fake robot and the duck behind the fake adapter (a simulated
  duck and a duck whose variant is real): no real robot, no simulator host.
- `use_profile_version`, `start_calibration` and `keep_calibration` decide "real" from the
  robot's profile variant (`profile.variant` of `GET /robots/{id}`). A robot whose file holds the
  robot itself has no variant and is treated as not real; for it the API has no profile or
  calibration at all.
- `drive` is not gated by the variant on the MCP side (it never was): the robot file's
  `allow_real_runs` refuses it at the API.
