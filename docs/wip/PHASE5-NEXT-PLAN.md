# Phase 5: the plan after step 1

**Status:** written 2026-11-22, at the end of phase 5 step 1 (parts 1 to 10, last commit `11cad9d`),
for the next session to start from. The order is [RFC-0023 §7.1](../rfc/RFC-0023-the-views.md) items
3 to 6 and the [architecture review](ARCHITECTURE-REVIEW-2026-11-22.md)'s "during phase 5" list.
Nothing below is started.

## Where things stand

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

**Decide first (the operator):** the end states' names (a proposal: reached, done, refused,
not_found, timeout, stalled, stopped_by_guardrail, cancelled, interrupted, failed, each with one
meaning written down; `aborted` folded into `stopped_by_guardrail` or `interrupted`); whether old
runs' end states are mapped when read (the Observatory shows recorded runs).

**Proof.** A contract test, the same file run against the duck's payload and its navigator API;
must-fail cases (an unknown end state, a major version the runner does not know, a payload answering
a method outside the contract); `make ci-fast`; `make sim-duck`; one challenge batch (challenges 1
to 11, seed 1) whose verdicts match the last batch's.

**Size:** one part-sized commit.

### 2. The apartment out of the runner

**The problem.** The runner library holds one scene: the apartment's bounds (`geometry.py`
`APARTMENT`), its rooms (`rooms.py` `ROOMS`), its stairwell twice (`rooms.py` and `guard.py`
`STAIRS`, and the guard adds it as a drop to any layout that has none: the review's finding), and
`geometry.py` and `sim_camera.py` read the robot when they are imported, so a second robot needs
`--robot` read before they load.

**The build.**

- The scene's bounds, rooms and drops in the scene's own files (beside `scene.json` in the data
  folder, or the robot's `sim/` folder: to choose with the operator), read by the runner for the
  scene it runs.
- The guard takes the layout's drops only; a layout with none has none.
- The course modules read the robot and the scene when a command starts, not at import (no
  module-level `robots.get()`).

**Proof.** Unit tests of the scene reader (a second, small scene with no stairwell: no drop added);
the challenge batch as in item 1, verdicts matching; `make sim-duck`; the explore score of one
apartment run equal before and after (`explore_score.py` reads the rooms).

**Size:** one to two parts; it touches every course.

### 3. RFC-0023 steps 2 and 3, side by side

- **Step 2, the run keeps the body:** per joint the commanded angle, velocity and current (an empty
  list is "not reported", never zero), and robotd's health. First a check of what the simulator's
  bridge carries (`duck-control/src/sim.rs`) and what reaches our state stream.
- **Step 3, one alarm feed:** the anomalies of every source in RFC-0019's shape (the navigator's,
  the runner's truth guardrails, the subsystems, the joints with limits from the profile), served
  live by Mission Control, kept in the run, and marked on the Observatory's timeline and map.

### 4. Before step 6

- **A runner that works without the truth:** no sampler, no truth guardrails, no camera, the
  official run copied without truth, so a real robot has a path through `lab-nav-server` and Mission
  Control always goes through it.
- **The gate protocol's version**, with step 4's "who holds the robot" on the robot page.

### 5. Step 6 (telemetry): needs the operator before it starts

New dependencies (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`), test sends into
the operator's Victoria stack, the robotics-lab Grafana folder's token and tailnet access from the
homelab session. Step 7 (retention) when convenient, with its N decided by the operator.

## Working rules for the next session

- The work is in the `mission-control` worktree (`/work/robotics-lab/mission-control`, branch
  `mission-control`), pushed to `main` at each checkpoint after green local gates, the secrets scan
  and a rebase; CI watched to its verdict.
- Simulator jobs under `flock -w 7200 /tmp/claude-1000/-work-robotics-lab-main/sim.lock` with
  `TMPDIR=$HOME/.cache/robotics-lab-tests`; `make sim-duck` takes about 10 minutes and resets the
  simulator.
- Kept test folders in `~/.cache/robotics-lab-tests` (`mc-sim-duck-*`, `k46-run-*.log`) are not
  deleted without the operator's go.
- Each item: a failing test first, the fix, a mutation check, the gates, the docs, a commit with its
  numbers.
