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

## MVP 1 and MVP 2

**The operator, 2026-11-23:** "By the time we get to Gazebo and Burger, we're going to be MVP
version 1. And then we are evolving architecture to fit MVP version 2." Things work well so far;
MVP 2 is "stepping up the game", by a proper architectural evolution, not by bolting a robot on.

- **MVP 1:** everything the operator needs with the Microduck and the Lego (NXT) in the current
  ecosystem. Items 4a, 4b and 4c, then 5 (telemetry) and step 7 (retention), below. **The Lego
  NXT too (the operator, 2026-11-23):** it is the robot the operator has working today, so MVP 1
  closes its gaps: what is missing to fully integrate and operate it, and a way to drive it in a
  simulator, on the simulator setup we have now. Item 4d below, scoped by a survey first.
- **Between MVP 1 and MVP 2, a close-out (the operator, 2026-11-23):** fix the documentation and
  the README, take screenshots, and make the GitHub repository a first-class one; decide on a new
  name for the repository and on the project's branding; and review, with MVP 2's architecture in
  mind, whether bringing Mission Control and the Observatory together (RFC-0024) was right for
  the long term.
- **MVP 2:** the TurtleBot3 Burger (arriving about a week after 2026-11-23) with more sensors,
  starting in a simulator (Gazebo), on an architecture that supports every approach as a peer
  (robotd, ROS 2, the NXT's, more later). Its direction: the operator's vision note on depth
  cameras, SLAM and 3D mapping, and [ADR-0020](../adr/ADR-0020-robots-behind-our-own-interfaces.md)
  (proposed, for reflection). Its first step is an architecture reflection on paper, then RFCs;
  nothing for it is built before those are agreed. Item 6 below is its old shape (stubs) and is
  revised by that work.

### What RFC-0025 (accepted 2026-11-23) changes in MVP 1

The operator agreed the order on 2026-11-23: A3 first, then two streams side by side, the duck
(B3, B7, B8, then B5, B6, then 4c) and the NXT (4d). Items needing the operator are parked in
[PARKED-FOR-OPERATOR.md](PARKED-FOR-OPERATOR.md). RFC-0025's decisions reach MVP 1 here:

1. **D10, the NXT over Bluetooth:** the deadman is a last-hop watchdog on the computer wired to
   the motors (RFC-0025 §3.3). Over USB nxt-web's deadman on the workstation is that computer;
   over Bluetooth it is not, so the brick must stop by itself when commands stop. D10 checks the
   brick-side program for that timeout, and adds one if it is missing, before any drive over
   Bluetooth.
2. **D0 and D3:** the host kind follows RFC-0025's rules: minimal per-kind dispatch in `simhost`
   (RFC-0028 starts from it), truth as `(wall_ns, pose)`, and a reset that returns only when the
   simulator is settled (§3.4).
3. **D4:** the NXT's stand-in profile takes profile v2's shapes where they are decided: a source
   per sensor (§3.10), the supported placements in the registration and nxt-web's address in the
   installation (question 18).
4. **D5 and D6:** the NXT adapter grows only within the existing `robot.*` methods; our robot
   interface becomes a written contract in RFC-0025 step 1.
5. **Step 7, retention:** acts on whole run folders, companion files included (ADR-0020
   decision 5), though MVP 1 records none.
6. **Step 6, telemetry:** robot-neutral labels (robot id, robot kind, host kind).
7. **B8:** check whether the duck's simulated runs record the simulator's time and the
   real-time factor (question 7); if not, add it, with the `rtf_low` alarm below 0.95 (the
   threshold a guess).
8. **B6:** a real run refused unless the robot file allows it covers a calibration walk too: A3's
   `odometry_scale` walks blind, with no wall, cliff or contact check.

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
     5 of 5 mutants killed, `make ci-fast` PASS. Live (2026-11-23): challenge 1 seed 1 under a test
     installation whose profile puts `judge.fall_z_m` at 0.5 m (above the trunk) raised one
     `guardrail_broken`, critical, source `harness` ("fall: trunk 0.116 m above its floor, below
     0.5 m"). Not covered: no real challenge breaks the truth guard on purpose.
  3. **The live feed: done (2026-11-23).** The navigator contract is 1.1: the navigator API's
     `goal.status` takes `anomalies_since` and answers `anomalies` (numbered, with `t`); a 1.0
     navigator answers none. Mission Control relays each once, keeps it with the goal run (store
     version 4, an `anomalies` table; `GET /goal-runs/{id}` has them), puts it on the event stream
     (`anomaly`, with the Observatory's page at `#t=`), and the page shows a header badge (the last
     minute's count and the worst), the list and an inspector (what, where, since when, by how
     much; STOP, the run, the Observatory at that moment). Proof: the contract, body and adapter
     tests and the page in Chromium at phone width, 5 of 5 mutants killed, `make ci-fast` PASS.
     Live (2026-11-23): `tests/sim_duck.py --only point --profile <a test profile>` on the real
     simulator: the goal run kept `joint_overload` and `joint_tracking`, and the event stream carried
     9 `anomaly` events, each with its `#t=` link (`PASS sim_duck`). `--profile` seeds Mission
     Control's profile store with a test profile; `make sim-duck` runs without it. (Corrected in
     part 4: the Observatory's pages already seek to `#t=`.)
  4. **The Observatory's marks** (the operator, 2026-11-23: (a) now, (b) later).
     **(a) The tagged ones: done (2026-11-23).** A run's `anomaly` events keep the navigator's record
     (`runfile.store.anomaly_of`; `wire` keeps an anomaly event's `raw`); an `anomalies` stream;
     the shell's Alarms lane (one mark per anomaly, coloured by severity, the harness's a diamond,
     a click seeks), the inspector's rows, and pins on the map in both renderers (the belief's place
     by the epoch in force, the truth's ring joined to it). `#t=` opening at a moment was already
     there; it is tested now. Proof: `libs/runfile/tests/test_store_anomaly.py`,
     `apps/observatory/tests/test_anomaly_pages.py` (three, deck, the watch page; 390 px; light),
     7 of 7 mutants killed, `make ci-fast` and `make test-observatory-pages` PASS. A live run's
     pins: `apps/observatory/tests/test_live_page.py` writes an anomaly into a growing run while
     both pages follow it; the lane's mark and the pin appear (`LIVE PAGE PASS`). The index was
     rebuilt and the Observatory redeployed (2026-11-23, the operator's go; 219 scenes, 1629 runs).
     **(b) The analysis's found anomalies** on the same track: needs RFC-0019's derived index
     (later).

### 4. Before step 6

- **A runner that works without the truth:** no sampler, no truth guardrails, no camera, the
  official run copied without truth, so a real robot has a path through `lab-nav-server` and Mission
  Control always goes through it.
- **The gate protocol's version**, with step 4's "who holds the robot" on the robot page.

**Decided (the operator, 2026-11-23):**

- **The truth signal** is the host file's `truth_port: null`, as it already is for the sampler
  and the camera. There is no second flag.
- **The variant** comes from the installation: `robots.<name>.variant`. The default is `sim` when
  the host has truth and the base (real) profile when it has none. The judge and the navigator are
  given the same variant: `navapi.py`'s hard-coded `"sim"` goes, and `--variant` is passed.
- **The truth guardrails** (`contact`, `fall`, `drop_clearance`, `no_go_area`) on a truth-less
  host: the goal runs; the run records them as `not_enforced`; one harness `warning` anomaly per
  guardrail is raised at goal start.
- **Who holds the robot:** the gate protocol's version (`protocol: 1` in every gate reply; a
  missing number is read as 0 and accepted), plus a minimal holder line from `gate.who` on
  Mission Control's robot view. The rest of the robot page stays for RFC-0023 step 4.
- **The profile finding is fixed here.** Today the runner passes `--profile` only when the
  installation names one, so the navigator reads its own default while the judge reads the
  registration's. Fix: `profile_source` falls back to the registration's profile. Fix
  `remote.py` the same way. A failing test comes first.

**Done (2026-11-23), all seven parts.** The navigator contract is now 1.2: `goal.start` takes
`not_enforced`, and the navigator raises `guardrail_unenforced` (harness, minor). There is one
variant source, the installation's; a Mission Control robot file naming a different one is
refused. The gate protocol is 1: `protocol` is in every gate reply, a missing number is read as 0
with a warning, and a newer one is refused. Mission Control's robot card has the holder line.

Proof:

- `make ci-fast` PASS; `make test-control-page` PASS; 29 of 29 mutants killed.
- Live on the simulator, `tests/sim_duck.py --only point,profile,drop`: `PASS sim_duck`.
- `tests/sim_duck.py --no-truth` (the runner given the host file with `truth_port: null`):
  `PASS sim_duck`. A goal asking `drop_clearance 3.0`, `contact` and `fall` ran and was reached.
  Three `guardrail_unenforced` alarms arrived live. `judge_truth` reads "not available" in the
  runner's record and the Observatory's. No camera was served, and none of the 187 ticks was
  paired.

Not covered:

- No real robot.
- With no variant named, the runner's default follows the host's truth while Mission Control's
  follows the adapter type. The installation must name the variant when the two would differ.

**Parts, in order:**

1. `lab-nav-server` starts without truth. On a truth-less host there is no camera server and no
   `--camera`, no sampler, no `TruthLog`, no `TruthGuard` and no `truth_connections`. The official
   copy is made unpaired.
2. The unenforced guardrails, recorded and warned.
3. The run record's `judge_truth`.
4. The profile fallback.
5. The variant.
6. The gate protocol's version.
7. The holder line.

This replaces the earlier rule in `navapi.py` that "Mission Control talks to the navigator API
itself" on a truth-less host: Mission Control always goes through `lab-nav-server`.

**After item 4 and before 4a (the operator, 2026-11-23): a review by the advisor (Fable 5.1).**
It covers where phase 5 stands, and whether items 4a and 4b are planned well: their scope, order,
gaps and risks. Its findings go to the operator before 4a starts.

### 4a. RFC-0023 steps 4 and 5, before telemetry

**The operator, 2026-11-23:** these are built before telemetry. This plan had left them out; the
RFC's §7.1 order was "steps 2 and 3 side by side; then 4, 5".

- **Step 4: Mission Control's robot page.** Its sections: Overview, Parts (including who holds
  the robot), Modules, Settings, Calibration, and Body.
- **Step 5: the realistic body.** The duck's own meshes, coloured by each joint's worst state. It
  appears on the watch page and live in Mission Control.

### 4b. Ready for the real duck (the first goal), before telemetry

**The operator, 2026-11-23:** the first goal is to work with the real duck when it arrives.
**Initial scope (the operator, 2026-11-23):**

1. **The real duck's adapter, deadman and safety review** (RFC-0014 step 8).
2. **The real duck's gate** (RFC-0017 §3.8). It runs on the computer that runs the navigator,
   not on the duck (RFC-0017:139). It includes the watch for the duck's other doors:
   `move.source` and `autonomous`, and `someone_else_drives`. (Corrected 2026-11-23: an earlier
   version said "on the duck's own computer", which the RFC does not say.)
3. **Relocalisation at a real site from landmarks** (RFC-0014 step 10, the relocalisation half).
   Without the simulator's truth, the duck's position comes only from what it sees.
4. **A real camera recogniser** in the robot's capabilities (RFC-0014 step 11). Without it, every
   object goal is refused as `no_camera`.
5. **Calibration probes as step guides** run by the runner (RFC-0023 step 4's Calibration
   section). These measure the real duck's limits, whose hold times are only proposed today.

**Added after the sweep (the operator, 2026-11-23, all seven):**

1. **Robot-side guardrails**, which replace the truth-only ones. A fall comes from the IMU's tilt;
   contact from mapd's `bumped` and `carried`; a drop from the cliff checks. They are enforced,
   not just recorded.
2. **Stopping on its own health.** The navigator stops the duck on `motor_hot`, low battery, an
   unhealthy verdict, or a stale state or depth stream.
3. **Link tooling.** It opens and checks the ssh-forwarded sockets and reconnects with back-off. A
   test covers a dead tunnel.
4. **A start pose in a real room**, set and checked without truth.
5. **A simulator-first flag:** a goal is rehearsed in the simulator before the real duck runs it
    (RFC-0014 step 5).
6. **mapd's CPU cost on the board and a score sheet comparing simulator and real** (RFC-0002).
    These need the robot; the tooling comes first.
7. **The depth sensor's model** (K34): radial or axial. It is measured on the robot first
    (REAL-DUCK.md §2); the tooling comes first.

The sweep's table, with its evidence, is in
[the real duck's readiness](PHASE5-REAL-DUCK-READINESS.md).

### The build package for 4a and 4b (the advisor's review, 2026-11-23)

The operator asked for this before a flight: "create a good package ... that 4a and 4b
implements", built unattended. Decisions are made by the recommended default and logged in
[the pending decisions](PHASE5-DECISIONS-PENDING.md).

**The review's findings:**

- 4a's two steps are each too big for one unit.
- The Calibration section in 4a and 4b's calibration item are the same work. 4a builds the frame
  with one procedure the simulator can measure; 4b adds the real duck's procedures.
- **Order matters for the drop guardrail.** Enforcing the robot-side drop guardrail before
  challenge 22's blind spot is fixed would turn a known hole into a safety claim. So B1 precedes
  B3. The blind spot: a frontier target on an unmapped rim, approached from the side.
- Relocalisation and a real recogniser need the robot or a real camera. They go last.

#### 4a units

| Unit | What | Proof | Size | Builds here |
| --- | --- | --- | --- | --- |
| A1 | Robot page shell, Overview ("fit to go, and why not"), Parts (the subsystems, the holder line) | `test_page.py`, Chromium, phone and desktop | M | yes |
| A2 | Modules (the plugins), Settings (versions, edit a copy, diff, export, import; the API exists) | page test: edit, save, diff | M | yes |
| A3 | Calibration frame, plus one simulator procedure (odometry scale), through a navigator-API method (contract 1.3, the operator's choice) | runner unit test, page test, one simulator run | L | done (2026-11-23): contract 1.3's `calibration.*`, the runner's truth reference, Mission Control's calibration API, and the Calibration tab's card and side drawer; `odometry_scale` in the simulator read 0.911 by the truth and 0.902 by a tape entry (profile 0.91), kept as a version the next goal runs; the real duck's tape entry is built and proven only against the simulator's truth read as a tape |
| A4 | RFC-0024 steps 1 and 2 (accepted 2026-11-23): the shared `libs/web` (tokens, three.js, the body from `robotbody.js`), then the body in Mission Control, live, beside the watch page's | page tests in both apps | L | done, `aea6d23` |
| A5 | The body with the duck's real meshes in Chromium: every link drawn, a joint coloured by an alarm. A page test that skips when the meshes are not built | screenshots, phone and desktop | S | done (2026-11-23): 15 of 15 links, 70 of 70 visuals, a hip red on `joint_overload` |
| A6 | The robot view carries the last minute's alarms (the worst per joint, the worst overall), so the body's colours and Overview's fit verdict are right when the page opens | page test: opened after an alarm, the joint is already coloured and the robot unfit | S | done (2026-11-23): `GET /robots/{id}` carries the minute's worst alarms |

#### 4b units

| Unit | What | Proof | Size | Builds here |
| --- | --- | --- | --- | --- |
| B1 | Challenge 22's blind spot: a target on an unmapped rim, approached from the side | the `lab-challenge --start/--goal` probe, then 10 runs; a unit test on a synthetic rim | M-L | partly done (2026-11-23): the hazard set fixed; the rim share recorded, not enforced; the path-grazing case open ([CH22-RIM.md](CH22-RIM.md)) |
| B2 | Stopping on its own health (`motor_hot`, battery, unhealthy, a stale stream) | contract test with a stub health; `sim_duck --profile` | M | done (2026-11-23): `stopped_by_guardrail` naming motor_hot, battery_low, robot_unhealthy or stale_stream |
| B3 | Robot-side guardrails enforced without truth (fall from tilt, contact from `bumped` and `carried`, drop from the cliff check) | contract test; `sim_duck --no-truth` | M | done (2026-11-23): contract 1.4; with `not_enforced` the navigator API checks `fall` (tilt 45 deg for 0.5 s, or mapd `fell`), `contact` (mapd newly `bumped` or `carried`) and `drop_clearance` (seen drops and edges), ending `stopped_by_guardrail`; the simulator proves only the drop (an exploration stopped 0.64 m from the rim at 1 m asked); a rim not yet seen is not covered |
| B4 | The other-doors watch (`autonomous`, `move.source`, `someone_else_drives`) | gate tests with a fake state source | S-M | done (2026-11-23): `Gate.observe_state` in the gate, the proxy (`--own-source`) and Mission Control's in-process gate; a sign stops the robot, ends the lease, and raises a critical `someone_else_drives` alarm. The simulator's robotd fills none of the three fields, so `sim_duck` proves only that nothing false-fires (`not_watched` logged once per proxy). Open: robotd's real `move.source` name for the proxy, and the "holder sent zero, robot moves" case |
| B5 | Link tooling: the ssh forwards, checks, reconnect with back-off | dead-socket and reconnect tests; no ssh in tests | M | done (2026-11-23): `lab-link up/check` (`labrunner.link`): the duck's three forwards (robotd, tofd, mapd) in one ssh session, a read-only question per socket (a stale file, a hang-up and a silent socket each named), restart with 1 to 30 s back-off that resets after a link that lasted 30 s; proven on stand-ins only, no ssh run; the gate does not reconnect and the real robotd's second connection is not verified ([the recipe](REAL-DUCK-LINK.md)) |
| B6 | The real duck's adapter (`duck-real`); a real run refused unless the robot file allows it | adapter test; `sim_duck --no-truth` | M | done (2026-11-24, code only): `duck-real` (`mission_control/duck_real.py`) over `lab-link`'s sockets, offline with the link's reason when one is dead, never an error; a goal run or a calibration on a robot whose variant is real is refused unless its file says `allow_real_runs: true` (default false), naming the key and [the review](REAL-DUCK-SAFETY-REVIEW.md); proven on stand-in sockets and `sim_duck --no-truth`, nothing on the real duck; the safety review is the operator's |
| B7 | A start pose without truth (`goal.start`'s `start_pose`, placed on the map) | contract and page tests | M | done (2026-11-23): contract 1.5; a run takes `start_pose {x, y, yaw}` (site frame), the navigator API sets its belief and grid in that frame by mapd's pose then, answers `placed`, and refuses only a non-pose or a no-go area; a navigator below 1.5 is refused the run, not run in the wrong frame; the page has "Start from a pose I place on the map". The simulator proves it with and without a truth (the duck ended 0.10 to 0.13 m from the goal the placement means, 0.58 to 0.62 m from the unplaced one). The frame is per goal; no truth can tell a wrong pose; a rotated placement is proven only in unit tests |
| B8 | The simulator-first flag (rehearse in the simulator, then real) | API test; `sim_duck` | M | done (2026-11-23): see [the decisions](PHASE5-DECISIONS-PENDING.md), B8 |
| B9 | Measurement tooling: CPU cost, score sheet, radial or axial | scripts | S each | done (2026-11-23): four scripts in `libs/runner`, run on the robot later ([the recipe](REAL-DUCK-MEASURE.md)): `lab-measure-cpu` (a standalone file for the board: mapd, robotd, tofd, machine), `lab-measure-range` (radial or axial by a fit to a flat board, read-only), `lab-measure-walk` (speed gain and odometry scale by tape; moves the robot, so gate, lease and `--real`) and `lab-score-sheet` (simulator and real runs side by side, the speed gain first); proven on the simulator and stand-ins, none on the real duck; the radial verdict is proven on recorded simulator frames, not a live wall |
| B10, B11 | Relocalisation from landmarks; a real recogniser | last: a stub recogniser at most | L | no |

### 4c. One platform, deployed (after 4a and 4b, before telemetry)

**The operator, 2026-11-23:** "note these as 4c". The two apps were first deployed together on
2026-11-23 (`make stack-up` from main at `36670fb`; the proof is P3 in
[the pending decisions](PHASE5-DECISIONS-PENDING.md)). They run side by side, not yet as one
platform.

| Unit | What | Proof | Size | Builds here |
| --- | --- | --- | --- | --- |
| C1 | One origin (RFC-0024 step 3): the Observatory proxies Mission Control's API; the token is needed for actions only (Q3, Q4); Mission Control reads runs only through the Observatory's API (Q5) | API tests through the proxy; both apps' pages from one address in Chromium | M-L | done (2026-11-24; the real deploy is pending the operator): the Observatory forwards `/control/...` to Mission Control with the standard library (any method, the stream a chunk at a time, `Authorization` across, no cookie); Mission Control's page is relative so it works at `/` and `/control/`; `--require-tokens actions` makes reads open and actions need a token (STOP always open); `check_boundaries` forbids Mission Control's source the run readers and its container gets no data folder. Proven on a test stack (`test_control_proxy`, `test_one_origin_page`, `test_tokens`). Not built: the shared "Robots / Runs" navigation and the phone watch page (RFC-0024 question 6); POST routes that only read need the token too |
| C2 | Mission Control's container drives the sim duck. It mounts the gate's and the navigator's sockets, the installation file, the robot's folder (description, meshes) and the profile store, at the paths the installation names, under the same UID | `make stack-up`, then a goal run from the deployed page against `sim_duck` | M | done (2026-11-24; the real deploy is pending the operator): the deploy overlay gives Mission Control's container the installation file, the gate's folder, the robot's folder and the profile store at the paths the installation names, under the same UID, and no data folder. The navigator is TCP on the host's loopback, not a socket, so both containers run on the host's network (loopback only; RFC-0024 section 9). Proven by `make sim-deployed` on a test stack: a point goal started from the page at `/control/` ended `reached`, the run is in the Observatory. The real installation's gate socket shares a folder with robotd's, so it is mounted only when it exists, and Mission Control restarts after the gate does |
| C3 | The deploy scripts: deploy from a named commit, not whatever the main checkout holds; one target that replaces the solo Observatory project; a smoke after it (health, `/lib/`, the pages in Chromium) | the smoke's output after a deploy | S-M | done (2026-11-24; the real deploy is pending the operator): `scripts/deploy.py` (`make deploy COMMIT=<sha>`, `deploy-dry`, `deploy-rollback`, `deploy-smoke`; [the recipe](DEPLOY.md)): `git archive` of the named commit, images tagged by it, the solo project taken down after the build, the deployed sha recorded for the rollback, the smoke ends the deploy. Proven on a test stack: a deploy, a redeploy, a rollback (also to a commit before the proxy), the solo project replaced |

The robot page's look follows the mock-up the operator approved on 2026-11-23 ("mockup is
good"): tabs, collapsible sections, Settings as a block list with a compact read view, a
side-drawer edit and a History drawer. A1 and A2 are rebuilt to it inside 4a.

### 4d. The NXT in MVP 1 (after 4c, before telemetry)

**The operator, 2026-11-23:** "for MVP1, we do have to go back to Lego NXT and actually see what
else is missing there to fully integrate that and see how to operate it… The gap we have is how to
drive Lego in simulator." The survey and the operator's answers (2026-11-23) are in
[NXT-MVP1.md](NXT-MVP1.md). Chosen: a kinematic NXT sim as nxt-web's `SimRobot` backend, started
by a new host kind `nxt-kinematic-sim` in `simhost`; the apartment scene; a stand-in profile; every
Mission Control drive session recorded; the shooter left out. The link is USB first, then
Bluetooth (D10); a Pi-based sensor module on the robot follows in MVP 2, and D0 keeps room for it.

| Unit | What | Size | Needs the robot |
| --- | --- | --- | --- |
| D0 | Design note: the second host kind, the NXT sim's sensors, the profile route. **Done 2026-11-23** ([NXT-D0.md](NXT-D0.md), defaults for the operator's review) | S | no |
| D1 | Hardware check at the brick: `hw_*` scripts, K15, K16 measured, the 15 cm stop | S | yes |
| D2 | A world for nxt-web: kinematic pose, collisions, ultrasonic cone cast. **Done 2026-11-23** (`nxt-web --sim --world`, `apps/nxt-web/tests/test_sim.py`; D1's checklist: [NXT-D1-CHECKLIST.md](NXT-D1-CHECKLIST.md)) | M | no |
| D3 | Host kind `nxt-kinematic-sim` in `simhost`: dispatch, reset, truth. **Done 2026-11-23** (`simhost.KINDS`, `NxtHost`, `libs/simhost/src/simhost/nxt.py`, nxt-web's `GET /api/sim/truth`; `libs/simhost/tests/test_simhost.py`) | M | no |
| D4 | The NXT registered like the duck: profile, variants `sim`/`real`, description. **Done 2026-11-23** (`robots/nxt-shooterbot/registration.json` and `profile.json`; registration `placements`, installation `placement` and `connections`; `robots.nxt-registered/nxt-1.json`; `apps/mission-control/tests/test_nxt_registered.py`, `test_nxt_page.py`) | M | no |
| D5 | Mission Control shows its sensors, stops and alarms. **Done 2026-11-23** (`nxt.py` `NxtWatcher` and the state's `sensors`, `battery_pct`, `flags`; nxt-web's `/api/status` gains `sensors`, `sensors_age_s` and `stops`; the robot page's facts line; the page's "Not fit" at idle was nxt-web's running program reported as a status flag; `test_nxt_adapter.py`, `test_nxt_page.py`, `test_sim.py`) | M | no |
| D6 | A drive session from Mission Control records a format 2 run. **Done 2026-11-23** (`NxtGate` starts nxt-web's recorder with the first session that holds the robot and stops it with the last, never one someone else started; in `--sim` nxt-web's recorder writes the run itself as `nxt/<scene>/<run>` with the scene's id and sha256 in `judge_scene`, the truth beside the belief in every tick and the map <- world epoch; `test_recorder_sim.py`, `test_nxt_adapter.py`) | M | no |
| D7 | `make sim-nxt`: the scenario end to end, PASS in the foreground. **Done 2026-11-23** (`apps/mission-control/tests/sim_nxt.py`: simhost starts nxt-web `--sim`, a client drives it by hand through Mission Control's API, the obstacle stop, STOP, takeover, deadman, and the run opened in the Observatory's API with truth; `lab-go`/`lab-nav-server --robot nxt-shooterbot` now refuse with "no navigator API"; [NXT-SIM.md](NXT-SIM.md)) | M | no |
| D8 | Docs: stale `nxt/` paths, ROADMAP, ADR-0013 names, a sim recipe. **Done 2026-11-23** (the paths, ROADMAP, ADR-0013 and the recipe [NXT-SIM.md](NXT-SIM.md)) | S | no |
| D9 | Measured numbers into the sim; one real and one sim run compared | S | yes |
| D10 | Bluetooth: the same nxt-web over BT; latency and drops measured; deadman timeout set | S | yes |

Order: D0, then D2 with D1 alongside (this week, the operator's answer), D3 to D8, D9 after D1,
D10 last.

### 4e. Follow-ups from the operator's decisions (2026-11-24)

The operator decided the parked items on 2026-11-24 ([PARKED-FOR-OPERATOR.md](PARKED-FOR-OPERATOR.md),
"The operator's answers"). The work they create, before telemetry:

| Unit | What | Size |
| --- | --- | --- |
| E1 | Simulator-first on by default for goals on a real robot, opt out per goal (B8). **Done 2026-11-24** (a goal with no `sim_first` is held on a real robot; `sim_first: false` is kept and opts out; the page's box is ticked and always sends it; `core._rehearsal`, `goals.validate`; `tests/test_sim_first.py`, `test_page.py`, `test_duck_real.py`; CONTRACT.md) | S |
| E2 | Robot-side guardrails also run with a truth, recording only; a critical `robot_guard` alarm on a robot-side stop (B3). **Done 2026-11-24** (`Guard`'s `shadow` `RobotSide` records a minor `robot_guard` once per name beside a truth and stops nothing; a robot-side stop raises it critical; contract 1.7; `robots/duck/tests/test_guardrails.py`, `test_contract.py`; [libs/runner/CONTRACT.md](../../libs/runner/CONTRACT.md)) | M |
| E3 | The site page says when the dock was set from the first placed start (B7). **Done 2026-11-24** (the site's `dock_pose` records `set_from`, `placed_start` or `robot_pose`; the map card's dock line says which; `tests/test_core.py`, `test_page.py`; CONTRACT.md) | S |
| E4 | The profile's `sensors` block generalised for both robots; the NXT's sensors move out of `capabilities.sensors` (D0). **Done 2026-11-24** (`sensors` is a table by id with a `kind` per entry: the duck's `tof8x8` and `camera` unchanged, plus `range`, `colour`, `scan2d`, `imu`, `odometry`, `image`, `depth_image`, each with `source`, `frame`, `mount`, `rate_hz`, `noise`; a variant's `null` drops a sensor; no new profile version; the NXT's profile holds its two, Mission Control lists them as `capabilities.sensors` as before; `libs/runfile/tests/test_profile_schema.py`, `test_nxt_registered.py`; [NXT-D0.md](NXT-D0.md) §5) | M |
| E5 | Hand drive on a real robot behind `allow_real_runs`; STOP never (B6). **Done 2026-11-24** (`RobotRuntime.drive` refuses a robot whose file lacks `allow_real_runs`: 409 `real_runs_not_allowed`; STOP is never refused; also, K48: 422 `stand_turn_below_floor` for vx 0 and a turn under the profile's `locomotion.stand_turn.min_rad_s`; `tests/test_duck_real.py`, `test_api.py`; CONTRACT.md) | S |
| E6 | `lab-link up --gate` restarts the gate once the forwards are back (B5). **Done 2026-11-24** (`--restart-gate`, or `--gate-cmd` for another command: the gate starts once the forwards answer, again after each reconnect, never while the link is down, ended with the session; the lease goes with the old gate; `libs/runner/tests/test_link.py`; [REAL-DUCK-LINK.md](REAL-DUCK-LINK.md)) | S |
| E7 | A `takeover_names` key in the NXT host file; `make sim-nxt` drops its own nxt-web (D7). **Done 2026-11-24** (`NxtHost.takeover_names`, passed to nxt-web as `--takeover-names`; `sim_nxt.py`'s takeover scenario runs on simhost's nxt-web; `libs/simhost/tests/test_simhost.py`; [NXT-SIM.md](NXT-SIM.md)) | S |
| E8 | A `sim-lock` helper in the repo that every simulator job takes the same way. **Done 2026-11-24** (`scripts/sim-lock`, `fcntl.flock` on `$ROBOTICS_LAB_SIM_LOCK` or `${XDG_RUNTIME_DIR:-/tmp}/robotics-lab-sim.lock`, 7200 s wait; `make sim-duck`, `sim-nxt`, `sim-gate-scenarios` and `sim-deployed` run under it; `make test-sim-lock`; [DUCK-SIM-FOR-AGENTS.md](DUCK-SIM-FOR-AGENTS.md)) | S |
| E9 | The socket check moved into `libs/runfile`, used by `lab-link` and Mission Control (B6). **Done 2026-11-24** (`runfile.linkcheck.check_socket`, one function with the forward and gate wordings; `labrunner.link.check_socket` wraps it, Mission Control's copy in `duck_real.py` is deleted; `libs/runfile/tests/test_linkcheck.py`, `test_link.py`, `test_duck_real.py`) | S |
| E10 | Investigate the duck's motion in the simulator: turning in place, the two speed figures (0.36 and 0.55 of commanded), the placed-start stall; fix what is ours. **Done 2026-11-24** (turning: the walking network starts no turn below ~1.0-1.1 rad/s from a stand, not ours; the profile's `locomotion.stand_turn.min_rad_s` and a refusal of a kick under it; Mission Control's drive refusal is left to an owner of `robots.py`, K48. Speed: B9's 0.36 was a wall 0.55 m ahead in the default scene, the sheet's 0.55 summed sway, the walk is ~0.47 over the ground; `lab-measure-walk` marks a blocked leg, `lab-score-sheet` takes net displacement, K49. Placed-start: the test told the duck faced 0, K50; fixed) | M |

### 5. Step 6 (telemetry): needs the operator before it starts

**Approved (the operator, 2026-11-22):** the new dependencies (`opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`), test sends into the operator's Victoria stack, and asking
the homelab session for the robotics-lab Grafana folder's token and the tailnet access.

Step 7 (retention) when convenient. **Decided:** N is configurable, `runs.archive_after_days` in the
installation file, default 30 days; official runs are always kept.

**Status, 2026-11-24** (design: [TELEMETRY-RETENTION-DESIGN.md](TELEMETRY-RETENTION-DESIGN.md); how
to use it: [TELEMETRY.md](TELEMETRY.md)):

- **Built:** the `telemetry` and `runs` blocks (U1); `runfile.telemetry` and the stub receiver
  (U2); Mission Control's hook and wiring (U3); `make telemetry-send-check`, run against the real
  stack (U4); the dashboard file, `make grafana-dry` and `make grafana-import` (U5);
  `observatory archive`, a dry run unless `--apply` (U6); these docs (U7).
- **Not done:** the dashboard is not imported into Grafana, and its datasource types and panel
  queries are untested there (the operator imports it); `observatory archive --apply` has not
  been run on the real data folder, and which runs count as official is still to confirm with the
  operator against the dry run's table.

### 6. Next integration goal: a second robot and a second simulator

**The operator, 2026-11-23:** after the planned work (steps 6 and 7), the next robot is a
TurtleBot3 Burger (ROS 2), with Gazebo Sim as a second simulator engine beside MuJoCo, and the
two must be fully compatible with what is here. Until then, every change is weighed against it.

The exercise comes first: a **stub** TurtleBot3 (a registration, a profile, a payload and
navigator that speak the contracts) and a **stub** Gazebo engine (a host serving the same
sockets: depth, map, camera, truth). Neither does real work. The stubs prove that the seams hold:
the registration, the profile schema, the navigator contract, the gate, the host file, the
Observatory's data, and Mission Control.

Known couplings to the duck and MuJoCo that the exercise must face:

- `geometry.layout_path` and `SimCamera` read the duck's MuJoCo layout.
- `robots.sim_dir()`.
- The profile's `joints` block (a wheeled robot has two wheels, not legs).
- `ROBOT_KINDS` in the Observatory.

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
