# RFC-0022 — The platform's layout and names: what is the duck's, and what is everyone's

**Status:** Accepted (2026-11-21, the operator: "1A, 2 choose best name, 3 before phase 5"):
option A; the prefix `lab-` (chosen by the lead, §7); done before phase 5. Built 2026-11-21 (§9);
§8 is the plan as refined by the code, with what changed from §3–§6 and why. Proposed the same
day. The operator, 2026-11-21: "do we have to use duck in names still since now all is generic and
we keep robot profiles?" The answer given then: partly; some of it is rightly the duck's, some is
the platform's and only lives in the duck's package, and the navigator is not yet proven generic.
The operator agreed to "not a rename sweep, but a move", written as a proposal before anything
moves. **Builds
on:** [RFC-0018](RFC-0018-lab-projects-and-seams.md) (the three kinds of folder and the boundary
check), [RFC-0020](RFC-0020-robot-profiles-and-plugins.md) (profiles and plugins),
[RFC-0021](RFC-0021-sim-host-and-payload.md) (the host, the payload and the runner). The map of
the pieces: [How the platform fits together](../architecture.md).

## 1. Problem

The platform's pieces were built on the duck first, in the duck's package (`robots/duck`,
`duck_lab`), and its commands are all named `duck-*`. Since RFC-0020 and RFC-0021 a robot is a
profile and plugins, a simulator is a kind, and the navigator is a payload behind a runner. A second
robot (the EV3 in phase 6, the TurtleBot3 after the plan) would today have to import its runner,
its judge and its gate proxy from the duck's package, and its operator would type `duck-challenge`
to test a robot that is not a duck.

## 2. Goals and non-goals

**Goals:** every piece lives where its kind of code lives (RFC-0018: `apps/`, `libs/`, `robots/`);
a command's name says what it does and takes the robot as an argument; the boundary check keeps a
robot's package from being imported by the platform; the old names keep working for one release.

**Non-goals:** renaming the navigator (it is the duck's until a second robot runs it, §3.3);
renaming the run keys (`duck/apartment/...` names the robot that ran, and stays); any change of
behaviour (a move, proven by the same tests and runs before and after).

## 3. What is whose

### 3.1 The duck's, and stays so

The profile (`robots/duck/profile.json`), its plugins (`duck_walk`, `duck_head`, `tof8x8`,
`mapd`), its description and meshes, its simulator scenes, patches and probes
(`robots/duck/sim/`), the robot's name in run keys.

### 3.2 The platform's, living in the duck's package

| Today | What it is | Proposed home |
| --- | --- | --- |
| `challenge/runner.py` (`Remote`), `nav_runner.py` (`duck-nav-server`), the runner half of `nav/explore_run.py`, `nav/evaluate.py` and `nav/run.py` (their `main`s) | the runner: starts a payload, drives it, reads the truth, copies the run | `libs/runner` |
| `challenge/judge.py`, `challenges.py`, `sequence.py`, `floor.py`, `explore.py`, `nav/explore_score.py`, `nav/rooms.py`, `nav/guardrails.TruthGuard` | the judge, the course and the scores (their thresholds are the profile's `judge` section) | `libs/runner` |
| `challenge/scene.py` (the MuJoCo scene writer) | a simulator kind's scene writer (RFC-0021 §3.1, 4) | `libs/simhost`, under the kind |
| `camera_server.py` | the simulated camera a host serves | `libs/runner` (it needs the world model and the scene's layout, which `simhost`, standard library only, does not take) |
| `payload.py`'s contract (the methods and their shapes) | the payload contract any navigator keeps | written down in `libs/runner` (the duck's server of it stays the duck's); not done in §9's build: phase 5 writes it, as one contract with the navigator API's |
| `gate_proxy.py` (`duck-gate`) | the gate in front of any robot that speaks RFC-0003 on a unix socket | `libs/gate` (`robotgate.proxy`) |
| `record.py`, `replay.py`, `to_rerun.py`, `world.py`, `miniview.py` (`duck-pic`) | tools over runs | `apps/observatory` (or `libs/runfile` for the ones with no viewer) |
| `site_cli.py` (`duck-site`) | the operator's sites, the world model's | `libs/worldmodel` |

### 3.3 The navigator: the duck's until a second robot runs it

`nav/*` (but the `main`s above), `payload.py`'s server and `nav/server.py` (the navigator API) stay
in `robots/duck`. The navigator takes its numbers from the profile, but it has run only on the duck,
with the duck's plugins. When the EV3 or the TurtleBot3 runs it, what proves generic moves to a
library then, by the same rule.

## 4. Names

One prefix for the platform's commands, the robot an argument, the profile naming its navigator:

| Today | Proposed |
| --- | --- |
| `duck-challenge 1 --runs 3` | `lab-challenge 1 --robot duck --runs 3` |
| `duck-eval`, `duck-explore`, `duck-go` | `lab-eval`, `lab-explore`, `lab-go` (`--robot duck`) |
| `duck-nav-server` | `lab-nav-server --robot duck` |
| `duck-gate` | `lab-gate` |
| `duck-site`, `duck-record`, `duck-replay`, `duck-rooms`, `duck-world`, `duck-to-rerun`, `duck-pic` | `lab-site`, `lab-record`, `lab-replay`, `lab-rooms`, `lab-world`, `lab-to-rerun`, `lab-pic` |
| `duck-payload` | stays: it is the duck's navigator |

The runner finds a robot's navigator in its profile: a new `navigator {command}` field
(`["duck-payload"]` for the duck), so `--robot duck` is all the runner needs, and `--payload` still
overrides it (a second navigator, `payloads/straight.py`).

**Compatibility:** every `duck-*` command keeps working for one release as an alias that says its new
name, as the `miniview` names did for the Observatory (K30).

## 5. Options

- **A. Move (recommended):** §3.2 and §4 as above. Cost: about half a day; every import of the moved
  modules, the boundary table (RFC-0018 §10), the tests, the make targets, the docs. Proof: the
  same as step 6's, before and after: `make ci`, `make sim-duck`, challenges 1–5 seed 1, a
  5-minute exploration, 0 truth connections throughout.
- **B. Rename only:** new command names, the code stays in `duck_lab`. Cheap; the second robot still
  imports the duck's package.
- **C. Wait for the second robot:** move nothing until the EV3 runs. No cost now; phase 5's views and
  docs are written against names that then change.

## 6. Steps (option A)

1. `libs/runner` with the runner, judge, course, scores, camera server and the payload contract;
   `duck_lab` imports nothing back from it but the contract's names.
2. The scene writer under `simhost`'s kind; the gate proxy into `libs/gate`; the run tools and the
   site tool to their homes.
3. The profile's `navigator {command}`; `--robot` on every runner command.
4. The `lab-*` commands, the `duck-*` aliases, the make targets.
5. The boundary table: `libs/runner` may import `simhost`, `runfile`, `worldmodel`, `robotgate`,
   never a robot's package; a robot's package never imports `libs/runner`.
6. The proof above, then the docs (the architecture page, the READMEs, `DUCK-SIM-FOR-AGENTS.md`).

## 7. Answered (2026-11-21)

1. ~~The option~~ **A**.
2. ~~The prefix~~ **`lab-`**, chosen by the lead as the operator asked: short, the repository's
   own name, says "the lab's tool" and not any robot's, and no command of ours starts with it.
3. ~~When~~ **Before phase 5.**

## 8. The plan, refined by the code (2026-11-21)

Reading the imports before moving anything changed four things in §3–§6:

- **A robot is found by name through a Python entry point, not a profile field.** The profile
  describes the robot, not code. A robot package registers itself in the group
  `robotics_lab.robots` (the duck: `duck = "duck_lab.robot"`, a small module that names its
  profile, its navigator's command and its simulator files); `labrunner.robots` finds it for
  `--robot duck`. With one robot registered, it is the default. *Since phase 5 step 1 (the
  operator's decision, 2026-11-22):* a robot is registered first by a registration file the
  installation names (`robots.<name>.registration`; the duck's is `robots/duck/registration.json`),
  so nothing is installed into Mission Control or the runner to add a robot; the entry point stays
  the fallback for a packaged robot, and a file wins over an entry point of the same name.
- **The boundary is the navigator, not the whole duck package.** `duck_lab.nav`,
  `duck_lab.payload`, `duck_lab.plugins` and `duck_lab.profile` (the navigator) never import
  `labrunner` or `simhost`; the duck's operator tools may, as a runner does.
- **The tools tied to the simulated apartment stay the duck's for now** (`duck-record`,
  `duck-replay`, `duck-world`, `duck-pic`, `duck-site`, `duck-to-rerun`): `duck-replay` replays the
  duck's own perception; `world`, `pic` and `site` read the apartment's layout and rooms. They keep
  their names; moving them is a follow-up when a second robot needs them. `duck-rooms` moves with
  the scores it is part of.
- **The apartment's files stay in `robots/duck/sim/`** (its layout, objects, phase 1's goals): they
  are the scene built for the duck's simulator; the duck's registration names the folder and the
  runner reads them from there. A second simulator kind brings its own scenes (RFC-0021 §3.1).

| Today (`robots/duck/src/duck_lab/`) | Moves to |
| --- | --- |
| `challenge/runner.py` | `labrunner/remote.py` |
| `challenge/run.py` (`duck-challenge`) | `labrunner/challenge.py` (`lab-challenge`) |
| `challenge/judge.py`, `challenges.py`, `scene.py`, `sequence.py`, `explore.py`, `floor.py` | `labrunner/`; the scene writer's MuJoCo part (`mjcf`) stays in `labrunner/scene.py` for now: it takes the runner's `Scene`, and `simhost` (the standard library only) cannot import the runner. It moves to the kind when a second kind brings its own writer |
| `nav_runner.py` (`duck-nav-server`) | `labrunner/navapi.py` (`lab-nav-server`) |
| `camera_server.py`, `nav/sim_camera.py` | `labrunner/camera.py`, `labrunner/sim_camera.py` |
| `nav/evaluate.py` (`duck-eval`) | `labrunner/geometry.py` (the footprint and the layout) and `labrunner/evaluate.py` (`lab-eval`) |
| `nav/explore_score.py`, `nav/rooms.py` (`duck-rooms`) | `labrunner/explore_score.py`, `labrunner/rooms.py` (`lab-rooms`) |
| `nav/guardrails.py`'s `TruthGuard`, `nav/explore_run.py`'s staircase guard | `labrunner/guard.py` |
| `nav/explore_run.py`'s `main` (`duck-explore`), `nav/run.py`'s `main` (`duck-go`) | `labrunner/explore.py` (`lab-explore`), `labrunner/go.py` (`lab-go`) |
| `gate_proxy.py` (`duck-gate`) | `labrunner/gate.py` (`lab-gate`): not `libs/gate`, which is pure rules and the standard library only (the proxy does socket I/O and reads the host file) |

The runner keeps its own `compose` and `inverse` (the navigator's wrap the angle, `runfile.se2`'s do
not; a move changes no number). Every `duck-*` command that moves keeps working for one release
and says its new name. The proof is §5's: before and after, the same tests and runs.

## 9. Built (2026-11-21)

`libs/runner` (`labrunner`) holds the moved modules of §8's table plus what the move needed:
`robots.py` (a robot by name, the entry-point group `robotics_lab.robots`), `geometry.py` (the
judge's footprint, thresholds and layout, from the evaluation), `guard.py` (the truth guard and the
staircase guard), `explore_run.py` and `go.py` (the runners of `lab-explore` and `lab-go`), `cli.py`,
`frames.py` and `rpc.py` (the runner's own copies, so it imports no robot), and `aliases.py` (the
`duck-*` names for one release). The duck registers itself (`duck_lab/robot.py`: its profile, its
payload's and navigator API's commands, its simulator files, its sites folder). Taken out of the
navigator: `explore_run`'s and `run`'s `main`s, the staircase guard, `TruthGuard`; dead code
removed: the challenges' in-process exploration (`explore.run`, no caller). The run keys name the
robot (`robots.get().NAME`), and `lab-nav-server` takes the lease as `lab-nav-server`.

The boundary check (`scripts/check_boundaries.py`) has two new units: `labrunner` (may import the
libraries, never a robot's package) and `duck_nav` (the navigator: `duck_lab.nav`, the payload,
the plugins, the profile, the registration; may import neither `labrunner` nor `simhost`). Its own
test has cases for both, and a mutation (the navigator importing `labrunner.remote`) fails the
check. `test_payload.py`: importing the payload or the navigator API loads no `labrunner` and no
`simhost`; the explorer's end events and the runner's are the same names.

**The proof (§5), after the move:**

- `make ci-fast` PASS (lint, the boundaries and their test, every project's unit tests); the docs
  PASS.
- `lab-challenge` 1–5, seed 1: 5 of 5 passed (errors 0.11–0.18 m); `duck-challenge 1` seed 2 (the
  old name): passed, and said its new name. Every run: all ticks paired, 0 truth connections.
- `lab-explore`, 5 minutes with the inventory: 601 sightings from 601 looks (119.5 a minute, as
  before), no camera failure, 11 objects in 3 rooms (the run before the move: 18 in 4; one run
  each, explorations differ by where they go); the official run 3083 of 3083 ticks with the truth;
  0 truth connections in 150 checks.
- `lab-go 1.5 0.5`: reached; 351 of 351 ticks with the truth.
- `make sim-duck`: first run, 21 checks passed, then the test itself crashed in the inventory
  scenario (it read a missing result: an inventory that did not end `done`; the run's files went
  with its temporary folder, so why it did not is not known). The inventory scenario alone: passed.
  The test now reports such a run instead of crashing. The second full run: 44 passed, 0 failed
  (`PASS sim_duck`), the inventory `done`, drop clearance broken by the runner's check, 0 truth
  connections in 308 checks over 15 goals. One failure in two full runs, of a scenario that starts
  where the one before left the robot: not explained, not repeated.
