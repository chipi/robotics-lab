# Phase 5: the plan after step 1

**Status:** written 2026-11-22, at the end of phase 5 step 1 (parts 1 to 10, last commit `11cad9d`),
for the next session to start from; updated the same day after item 1 (`0488ca3`, `642a82b`, both CI
green), and on 2026-11-23 after item 2 and item 3's step 2. The order is
[RFC-0023 §7.1](../rfc/RFC-0023-the-views.md) items 3 to 6 and the
[architecture review](ARCHITECTURE-REVIEW-2026-11-22.md)'s "during phase 5" list. **Items 1 and 2 are
done; item 3 step 2 is done** (the run keeps the body; the operator's decisions and the proof are in
[what the body data is today](PHASE5-ITEM3-BODY-DATA.md)). **Next: item 3 step 3**, the alarm feed.

## Where things stand

- **Item 1, one navigator contract, is done** (both commits, below). After it, on the operator's go
  (2026-11-22): the main checkout (`/work/robotics-lab/main`) was pulled to `642a82b` and the
  installation file (`~/.config/robotics-lab/installation.json`) registers the duck from it
  (`/work/robotics-lab/main/robots/duck/registration.json`, before: a test folder); the Observatory's
  index was rebuilt (219 scenes, 1629 runs; backup in
  `/work/robotics-lab/state/miniview/backup-20261122-before-stops/`; 0 `aborted` left, 9
  `stopped_by_guardrail` events, no data file changed) and the Observatory redeployed from main
  (`make observatory-up`, healthy, 1629 runs); the old `--keep` test folders were deleted.
- Phase 5 step 1 and the second review are done and pushed: the installation file and profile
  versions, robots registered by file (Mission Control and the runner have no robot's package), the
  checksum over the profile as stored, the referee judging by the version the navigator runs,
  whole-number state streams, the navigator never reading the installation, one gate socket, the
  forget rule (K45). What each is and how it was proven: [the step 1
  design](PHASE5-STEP1-DESIGN.md).
- Open: **K46**, inventory goals ending "the robot was trapped", 2 of 21 runs, none in the last 13,
  no trapped goal kept to read ([known issues](KNOWN-ISSUES.md)). Every `sim-duck` batch run with
  `--keep` is a chance to catch one.
- Not in reach without the operator: the NXT hardware checks (K15, K16).

## The order

### 1. One navigator contract (first: the smallest, and it unblocks 2 and 3)

**The problem.** Two contracts for one navigator: the payload's (courses: `duck_lab/payload.py`, its
docstring is its only written form) and the navigator API's (Mission Control:
`duck_lab/nav/server.py`). They differ in method names (`start`/`status`/`cancel` against
`goal.start`/`goal.status`/`goal.cancel`), goal shapes (`goal: [x, y]` in the navigator's map
against `params {x, y}`), end states, and versions (`hello` has a version; the navigator API has
`ping` without one).

| End states today | |
| --- | --- |
| payload `status` | running, reached, refused, timeout, stalled, aborted, failed |
| navigator API (`nav/server.py` `TERMINAL`) | reached, done, refused, failed, stopped_by_guardrail, not_found, cancelled, interrupted |

**The build.**

- The contract written down once: `libs/runner/CONTRACT.md` (RFC-0022 promised it there), one
  vocabulary of end states and one goal shape, the payload's methods a subset of the navigator
  API's.
- A version in `hello` and `ping`; the runner refuses a navigator whose major version it does not
  know, saying both versions.
- The duck's payload and API move to the one vocabulary; the runner (`labrunner/remote.py`,
  `navapi.py`), Mission Control's adapter (`mission_control/duck.py`) and the courses' judge read
  it.

**Decided (the operator, 2026-11-22):** the end states are reached, done, refused, not_found,
timeout, stalled, stopped_by_guardrail, cancelled, interrupted and failed, each with one meaning
written down; `aborted` folds into `stopped_by_guardrail` or `interrupted`. Old runs keep their
recorded end states, and the Observatory translates them to the new names when it shows them.

**Proof.** A contract test, the same file run against the duck's payload and its navigator API;
must-fail cases (an unknown end state, a major version the runner does not know, a payload answering
a method outside the contract); `make ci-fast`; `make sim-duck`; one challenge batch (challenges 1
to 11, seed 1) whose verdicts match the last batch's.

**Size:** one part-sized commit.

**Done 2026-11-22 (the contract, 1.0).** `libs/runner/CONTRACT.md`, its names in
`runfile.navcontract`; the payload (and `payloads/straight.py`) answers `goal.*` with the API's goal
shape, the API answers `hello` (no `ping`), a timeout and a stall are their own ends, the runner's
truth stops are `goal.break`; the runner, `lab-nav-server` and Mission Control refuse another major
version and take a state outside the contract as the navigator's failure. Proof:
`test_contract.py` 108 checks against both navigators; `test_remote_contract.py` (a stand-in
payload process) and Mission Control's `test_duck_adapter.py` with the must-fail cases; 5 mutants
killed (a guardrail end, a stall end, the state check, the runner's and Mission Control's hello
check); `make ci-fast` PASS; challenges 1-11, seed 1, the code before (`8237c25`) and after,
alternating: the same verdict in 11 of 11 (10 pass; challenge 7 refused "no room to turn" on both,
K40); `make sim-duck` PASS 48 FAIL 0. **And the stop's name (decided 2026-11-22, the second
commit):** the navigator's own stop event, and a run's verdict, is `stopped_by_guardrail` or
`cancelled` (`Navigator.stop_goal`) instead of `aborted`; an old run's `aborted` is read by its
recorded reason (`runfile.navcontract.stop_before`: the index's 9 are all guardrail stops, 6 falls,
2 truth guards, 1 contact). Proof: `test_stops_before.py` (a run file and a navigator log written
the old way, read back), the stop rule in `test_contract.py`, 5 mutants killed; `make sim-duck
--keep` PASS 48, its 34 runs: the time-limit and drop-clearance stops `stopped_by_guardrail`, the
cancel `cancelled`, events and verdicts, no `aborted`. The Observatory's index was rebuilt after it
(above): its 9 old rows now read `stopped_by_guardrail`. Not covered: the payload's `goal.break` path
is unit-tested only (no challenge in 1-11, seed 1, breaks an invariant).

### 2. The apartment out of the runner

**The problem.** The runner library holds one scene: the apartment's bounds (`geometry.py`
`APARTMENT`), its rooms (`rooms.py` `ROOMS`), its stairwell twice (`rooms.py` and `guard.py`
`STAIRS`, and the guard adds it as a drop to any layout that has none: the review's finding), and
`geometry.py` and `sim_camera.py` read the robot when they are imported, so a second robot needs
`--robot` read before they load.

**The build.**

- The scene's bounds, rooms and drops in one scene description per scene, read by the runner for
  the scene it runs, versioned in the repository at `scenes/<id>/scene.json`
  ([decided below](#decision-where-a-scene-lives)).
- The guard takes the layout's drops only; a layout with none has none.
- The course modules read the robot and the scene when a command starts, not at import (no
  module-level `robots.get()`).

**Proof.** Unit tests of the scene reader (a second, small scene with no stairwell: no drop added);
the challenge batch as in item 1, verdicts matching (the old code in a worktree at `642a82b`,
alternating runs, seed 1; challenge 7 is expected to fail on both, K40); `make sim-duck`; the
explore score of one apartment run equal before and after (`explore_score.py` reads the rooms); a
run records the scene's checksum beside `judge_profile`, and a run whose scene file changed says so.

**Start here.** Read `labrunner/geometry.py` (`APARTMENT`), `rooms.py` (`ROOMS`, `STAIRS`),
`guard.py` (`STAIRS`, the drop it adds), `sim_camera.py`, `challenge.py` (the `scene.json` it
writes), and the data folder's `data/scenes/apartment/scene.json`; compare the code's copy with the
file's before writing `scenes/apartment/scene.json`, and list every difference for the operator if
they disagree.

**Size:** one to two parts; it touches every course.

**Decided (the operator, 2026-11-23):** the scene's boxes are the simulator layout's 61 (the free
bodies too), with a test that fails when the two part; the stairwell is 0.4 m deep (the last
tread's top); the Observatory reads the repository's scene file (its own copy in `scenes.py` goes).

**Part 1 done 2026-11-23 (the scene file).** `scenes/apartment/scene.json`, read and checked by
`runfile.scenefile` (bounds, rooms in order, drops, boxes; `describe`, `changed_since`,
`boxes_from_layout`). The runner's rooms score, the explore score, the truth guard, `lab-explore`'s
drop guard, `lab-eval`'s bounds and `lab-nav-server` read it for their `--scene`; the guard takes
the scene's drops only (`STAIRS` and the added stairwell are gone from `rooms.py` and `guard.py`,
`geometry.APARTMENT` too). A run records `judge_scene` {id, path, checksum} beside `judge_profile`
(a challenge's: the scene file written for it); the Observatory keeps it and its run answer says
`scene_changed`. `observatory scene <id>` copies the repository's file (`observatory/scenes.py`
deleted). Proof: `test_scenefile` (23 checks, 9 must-fail), the duck's `test_scene_layout` (13: the
boxes are the layout's, the stairwell the treads' outline and depth, the rooms between the walls,
the guard stops at the stairs and adds no drop to a scene with none), `test_server` (4, the scene
changed after a run said), `test_profile_source` (the run records the scene); 7 mutants killed;
`make ci-fast` PASS; the explore score and `lab-rooms` of 8 recorded runs (b11 r1-r5, b13 r1-r3)
byte for byte the same before and after; challenges 1-11, seed 1, the main checkout (`bff565c`) and
this code alternating: the same verdict in 11 of 11 (9 pass; 6 and 7 fail on both, K40), and the
11 new runs record `judge_scene` matching their scene file. Challenge 6 failed differently on the
two sides, so it ran twice more on each: before refused, stalled, reached (1 of 3); after stalled,
refused, refused (0 of 3); both sides show both failures, too few runs to tell 1 of 3 from 0 of 3.
`make sim-duck` PASS 48 FAIL 0 (its `drop_clearance` stop names the scene's `stairs`). Not covered:
`lab-explore`'s drop guard and `lab-eval`'s bounds run only in a live exploration or evaluation (not
run); the stairwell copies in the duck's viewer and probes stay (K47). **Waiting for the operator
after the push:** `observatory scene apartment` replaces the data folder's 57-box file.

**Part 2 done 2026-11-23 (the robot read when a command starts).** No module-level `robots.get()`,
`robots.profile()` or `robots.sim_dir()` left in the runner: `geometry.py` has `profile()`,
`layout_path()`, `goals_path()` (its `ROBOT`, `LAYOUT`, `GOALS`, `PROFILE` and the numbers from it
are gone); `Judge(scene, profile=None)` keeps its numbers (fall height, footprint, margins, reach),
`sequence.run` takes `reached_m`, `floor.lattice`, the truth guard, `lab-eval` and the explore
score read the profile when called, `SimCamera` its files when made. The duck's probes and tests
read the same values at their top. Proof: `test_import` (in the runner's own environment, no robot
registered: every labrunner module imports, and the judge judges by the profile it is given), in
`make test-libs`; 5 mutants killed (a module-level profile or sim folder read, the judge ignoring
its profile or its reach, a sequence ignoring `reached_m`); `make ci-fast` PASS; the explore score
and `lab-rooms` of the 8 runs the same as before item 2; on the simulator challenges 1 and 8 pass,
21 and 22 pass on part 1's code (`cb1c1cf`) and on this; `make sim-duck` PASS 48 FAIL 0. Not
covered: `lab-eval` and `lab-explore` not run live (as part 1).

### 3. RFC-0023 steps 2 and 3, side by side

- **Step 2, the run keeps the body: done (2026-11-23).** Per joint the commanded angle, velocity and
  current as signals (an empty list is "not reported", never zero), the stream's loop, safety flags
  and limits every tick, `robot.health` polled every 10 s with an event when its verdict changes;
  decisions and proof in [what the body data is today](PHASE5-ITEM3-BODY-DATA.md).
- **Step 3, one alarm feed:** the anomalies of every source in RFC-0019's shape (the navigator's,
  the runner's truth guardrails, the subsystems, the joints with limits from the profile), served
  live by Mission Control, kept in the run, and marked on the Observatory's timeline and map. In
  four parts, each its own commit (the operator, 2026-11-23: all four, in this order; limits in the
  profile for both the simulator and the real duck):
  1. **The body's anomalies: done (2026-11-23).** `body.BodyWatch` at the profile's new
     `joints.limits`: `joint_overload`, `joint_tracking`, `loop_slow` from each state, `motor_hot`
     and `robot_unhealthy` from each health answer; a `body_watch` event says the limits in force
     and what is not checked. The real duck's limits are Pollen's (900 mA of the servo's 1000 mA
     current limit, hot at 60 C of the 70 C shutdown), its tracking limit null (not measured);
     the simulator's from `sim/probes/body_limits.py` over 18 runs (its current is a stand-in).
     Proof in [what the body data is today](PHASE5-ITEM3-BODY-DATA.md).
  2. **The runner's truth guardrails: done (2026-11-23).** At `goal.break` (both the payload and
     the navigator API) the navigator records a `guardrail_broken` anomaly, source `harness`,
     severity critical, naming the guardrail; its own guardrails (a time limit spent) are none. The
     Observatory reads `harness` beside `robot`. Proof: `tests/test_contract.py` on both navigators,
     5 of 5 mutants killed, `make ci-fast` PASS; not covered: no live break on the simulator (no
     challenge breaks the truth guard on purpose).
  3. **The live feed: done (2026-11-23).** The navigator contract is 1.1: the navigator API's
     `goal.status` takes `anomalies_since` and answers `anomalies` (numbered, with `t`); a 1.0
     navigator answers none. Mission Control relays each once, keeps it with the goal run (store
     version 4, an `anomalies` table; `GET /goal-runs/{id}` has them), puts it on the event stream
     (`anomaly`, with the Observatory's page at `#t=`), and the page shows a header badge (the last
     minute's count and the worst), the list and an inspector (what, where, since when, by how
     much; STOP, the run, the Observatory at that moment). Proof: the contract, body and adapter
     tests and the page in Chromium at phone width, 5 of 5 mutants killed, `make ci-fast` PASS.
     Not covered: no live run through Mission Control with this navigator (`make sim-duck` runs the
     registered one). (Corrected in part 4: the Observatory's pages already seek to `#t=`.)
  4. **The Observatory's marks** (the operator, 2026-11-23: (a) now, (b) later).
     **(a) The tagged ones: done (2026-11-23).** A run's `anomaly` events keep the navigator's record
     (`runfile.store.anomaly_of`; `wire` keeps an anomaly event's `raw`); an `anomalies` stream;
     the shell's Alarms lane (one mark per anomaly, coloured by severity, the harness's a diamond,
     a click seeks), the inspector's rows, and pins on the map in both renderers (the belief's place
     by the epoch in force, the truth's ring joined to it). `#t=` opening at a moment was already
     there; it is tested now. Proof: `libs/runfile/tests/test_store_anomaly.py`,
     `apps/observatory/tests/test_anomaly_pages.py` (three, deck, the watch page; 390 px; light),
     7 of 7 mutants killed, `make ci-fast` and `make test-observatory-pages` PASS. Not covered: a
     live run's pins (rebuilt on a live anomaly, untested); runs indexed before this lack the
     `anomalies` stream until the index is rebuilt (the operator's go).
     **(b) The analysis's found anomalies** on the same track: needs RFC-0019's derived index
     (later).

### 4. Before step 6

- **A runner that works without the truth:** no sampler, no truth guardrails, no camera, the
  official run copied without truth, so a real robot has a path through `lab-nav-server` and Mission
  Control always goes through it.
- **The gate protocol's version**, with step 4's "who holds the robot" on the robot page.

### 5. Step 6 (telemetry): needs the operator before it starts

**Approved (the operator, 2026-11-22):** the new dependencies (`opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`), test sends into the operator's Victoria stack, and asking
the homelab session for the robotics-lab Grafana folder's token and the tailnet access.

Step 7 (retention) when convenient. **Decided:** N is configurable, `runs.archive_after_days` in the
installation file, default 30 days; official runs are always kept.

## Decision: where a scene lives

For item 2; **decided (the operator accepted the recommendation, 2026-11-22).**

- **What exists today.** The apartment's `scene.json` (bounds, boxes, the stairwell as a `drop`
  hazard) is only in the data folder, `data/scenes/apartment/`, which is not in git; nothing in the
  repository writes it. The runner holds a second copy in code (`geometry.py` `APARTMENT`,
  `rooms.py` `ROOMS` and `STAIRS`, `guard.py` `STAIRS`). The simulator's files are in
  `robots/duck/sim/` (`apartment_layout.json`, `apartment_objects.json`). `labrunner/challenge.py`
  writes a challenge's `scene.json` into the data folder.
- **The decision.** A scene belongs to the world, not to a robot or a machine, so its
  description is versioned in the repository: `scenes/<id>/scene.json`, the existing shape (`id`,
  `name`, `kind`, `frame`, `bounds`, `boxes`, `hazards`) plus `rooms`. The runner's judge, guard and
  scores read it for the scene they run; it is copied into the data folder for the Observatory, as
  today. The robot's `sim/` keeps only what one simulator needs (the MuJoCo layout, the objects, the
  goals).
- **Not chosen.** The data folder alone: not versioned, one machine's copy, and a run could not
  say which scene description judged it. The robot's `sim/` folder: a second robot in the same
  apartment would copy it, and a real robot has no `sim/`.
- **What it adds.** A run records the scene's checksum beside `judge_profile`, so the referee's map
  is as traceable as its limits.

## Working rules for the next session

- The work is in the `mission-control` worktree (`/work/robotics-lab/mission-control`, branch
  `mission-control`), pushed to `main` at each checkpoint after green local gates, the secrets scan
  and a rebase; CI watched to its verdict.
- Simulator jobs under `flock -w 7200 /tmp/claude-1000/-work-robotics-lab-main/sim.lock` with
  `TMPDIR=$HOME/.cache/robotics-lab-tests`; `make sim-duck` takes about 10 minutes and resets the
  simulator.
- Test folders kept in `~/.cache/robotics-lab-tests` (`mc-sim-duck-*`, `k46-run-*.log`) are not
  deleted without the operator's go (the earlier ones were deleted with it, 2026-11-22). The
  installation file is not pointed at a test folder; it stays on the main checkout.
- After a push to main, pull the main checkout (`git -C /work/robotics-lab/main pull --ff-only`)
  so the installation's duck and the Observatory run the pushed code; rebuilding the Observatory's
  index or redeploying it (`observatory index`, `make observatory-up`) needs the operator's go.
- Not to be touched: Rerun (pid 735512), the `robotics-lichtblick` container, the NXT and EV3 (no
  scripts against them); never `uv sync --no-dev` in `robots/duck`; no new dependencies without
  approval (OpenTelemetry approved for step 6 only).
- Each item: a failing test first, the fix, a mutation check, the gates, the docs, a commit with its
  numbers.
