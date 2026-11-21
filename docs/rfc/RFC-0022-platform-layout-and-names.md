# RFC-0022 — The platform's layout and names: what is the duck's, and what is everyone's

**Status:** Proposed (2026-11-21), for the operator's decision; nothing has moved. The operator,
2026-11-21: "do we have to use duck in names still since now all is generic and we keep robot
profiles?" The answer given then: partly; some of it is rightly the duck's, some is the platform's
and only lives in the duck's package, and the navigator is not yet proven generic. The operator
agreed to "not a rename sweep, but a move", written as a proposal before anything moves. **Builds
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
| `payload.py`'s contract (the methods and their shapes) | the payload contract any navigator keeps | written down in `libs/runner` (the duck's server of it stays the duck's) |
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

## 7. Open questions for the operator

1. **The option:** A, B or C?
2. **The prefix:** `lab-` (the repository's name), or another?
3. **When:** right after this RFC is decided, before phase 5's build (phase 5's design round can
   start meanwhile: it does not depend on where the runner lives); or after phase 5?
