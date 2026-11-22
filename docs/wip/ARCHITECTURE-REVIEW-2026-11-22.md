# Architecture review, 2026-11-22

The operator asked the advisor (Fable) to review everything built so far and the architecture as
written down (the architecture page and its diagrams, the README, RFC-0014/0017-0023, the plan),
before phase 5 builds on it, and to judge whether phase 5's step 1 is the right next step. The
lead checked each finding below against the code before taking it (file and line given). The
operator, after reading it: "love the feedback, let's adjust approach and follow your
recommendation as next step, and then do another round of review".

## The verdict

The shape is right, and for the one robot that exists it is enforced, not only described: the
navigator never sees the truth (a process boundary with a live check, `labrunner/remote.py`), the
runner is the one referee and the one writer of the official run, the run format is the one record,
and the import table is checked on every `make lint`. What is not yet true is the platform's claim
about itself:

- **The simulator kind is a string, not a seam.** `simhost/host.py:25` knows one kind; the `Host`
  record has Pollen's checkouts as fields and refuses a file without them; the truth reader speaks
  Pollen's body server; the reset is `duck-sim` and `mapd`. RFC-0021 §3.1's four parts are four
  functions in one Pollen library, and the scene writer is in the runner.
- **The runner is shaped by the duck** in three places: the payload's connections are the duck's
  three sockets as fixed flags (`remote.py`, `navapi.py`), the apartment's stairwell, rooms and
  bounds live in the runner library (`geometry.py`, `guard.py`, `rooms.py`), and `geometry.py` reads
  the robot when it is imported.
- **The runner is all or nothing on the truth.** `navapi.py`, `camera.py`, `explore_run.py` and
  `truth.py` refuse a host with no truth port, and a host file cannot be written for a machine
  without Pollen's simulator: on the EV3 there is no runner, no official run, nothing between
  Mission Control and the navigator.

## Findings, checked

| Finding | Evidence |
| --- | --- |
| Mission Control imports the duck's navigator and the host library | `mission_control/duck.py:21-22`, `:261` |
| Mission Control opens mapd's socket directly for the map, past the gate and the navigator API | `duck.py:254-266`, `:332-344`; the API serves `map` (`nav/server.py`) |
| Mission Control reads the robot's factsheet and capabilities from its own robot file, a second copy of the profile | `mission_control/robots.py:60-68`; `robots.sim/duck-sim.json` beside `robots/duck/profile.json` |
| Mission Control reads the odometry scale once, at start | `duck.py:269` |
| No library has tests of its own; the runner, the host library and the run format are tested through the duck | no `libs/*/tests`; `robots/duck/tests` imports `labrunner` in 8 files |
| The profile reader refuses any other schema version, so stored versions become unreadable at the next schema | `runfile/profile.py:371-372` |
| Two navigator contracts: the payload's (courses) and the navigator API's (Mission Control), with different end states and goal shapes | `duck_lab/payload.py`, `nav/server.py` |
| The payload contract is written only in a docstring; RFC-0022 said "written down in `libs/runner`" | `ls libs/runner`: no contract document |
| The gate protocol has no version; RFC-0018 §5.3 promised one | no `protocol` or `version` in `libs/gate`, `labrunner/gate.py` |
| The guard adds the apartment's stairwell as a drop to any layout that has none | `labrunner/guard.py:34-37` |
| The robot's radius and height are written in several places | `profile.json`, `runfile/adapters/duck.py:20`, `payloads/straight.py`, each run record |

## Docs that misdescribe the code (fixed with this review)

1. `architecture.md`, the real robot: a host file with `truth_port: null` cannot be written today.
2. `architecture.md`, the camera seam: "on the real duck it would be its detector" is designed, not
   built.
3. `architecture.md`, "the runner imports no robot's package": true of `import` statements; the
   entry point loads the robot's registration when the runner starts, which the check cannot see.
4. RFC-0021 §3.1, "nothing outside the kind names Pollen, MuJoCo": the goal, not the state.
5. RFC-0022 §3.2, the payload contract "written down in `libs/runner`": not done.
6. RFC-0018 §10 and `check_boundaries.py`, Mission Control's exception "retired by RFC-0020's
   plugins": not retired; phase 5 step 1 retires it.
7. RFC-0018 §5.3, the gate protocol's version: not given.
8. RFC-0014 §3.7, "state today": historical.

## What changes, and when (the lead's recommendation, the operator's go)

**Inside phase 5 step 1:**

1. Mission Control's robot file becomes a pointer (`robot: duck`, its label, the adapter's type);
   the factsheet, control, capabilities, guardrails and rates come from the robot's profile version.
2. Mission Control stops importing the duck's navigator and the host library: the map through the
   navigator API, the scale per run, the addresses from the installation file.
3. A policy for profile schema versions before the store holds anything (older schema versions
   read and migrated, never refused), and the profile blocks phase 5 needs added now: the
   robot's subsystems (step 4's Parts), joint limits (steps 3 and 5).
4. The libraries get tests of their own (`libs/*/tests`, a `test-libs` target), the library
   tests moved out of the duck's.

**During phase 5:** one navigator contract (the payload's a subset of the navigator API's, one
vocabulary of end states, a version in `hello` and `ping`, written down in `libs/runner`), before
step 3; a runner that works without the truth (no sampler, no truth guardrails, the official run
copied without it, no camera), so Mission Control always goes through `lab-nav-server` and a real
robot has a path, before step 6; the apartment out of the runner library (into the scene's own
files; the robot read after `--robot`), before step 3; a protocol version for the gate, with the
robot page's "who holds the robot".

**Later, when it arrives:** a module per simulator kind (at the second kind); the navigator out of
the duck's package and its four interfaces cut again on the second robot's vocabulary (at the
second robot); the official run built from what the runner observes, the payload's own run optional,
and Pollen's model licence settled (at the arena).

**The build order:** steps 2 and 3 can run side by side; step 7 (retention) leaves the sequence and
is done when convenient.

Not verified in the code by the review: the stairwell fallback on the challenge path; whether a run
record takes an added `profile` key of about 12 KB; the navigator API's direct path from Mission
Control on a host with no truth (no test exists).
