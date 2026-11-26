# RFC-0031: Learning in the lab, training as a run on another kind of resource

**Status:** Accepted (the operator, 2026-11-26: all eight questions as recommended), revision 2
(2026-11-26), after the advisor's
[review](../wip/RFC-0031-REVIEW-2026-11-26.md). Nothing here is built yet.
The operator approved writing it with option A of section 5 as the recommendation; that is a
recommendation, not a decision. One rule is decided and recorded in section 7.2 (the promotion
rule, 2026-11-26). Findings are cited as (review C1) and so on.
**Date:** 2026-11-26
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (Mission Control: goals, runs, the lease and
STOP), [RFC-0024](RFC-0024-one-platform.md) (one platform, one origin),
[RFC-0025](RFC-0025-mvp1-to-mvp2.md) (MVP 2; the local-controller seam of section 3.7; its
step 10 safety review), [RFC-0030](RFC-0030-missions.md) (approval modes, plan checksums, the
`missions` module), [ADR-0007](../adr/ADR-0007-run-file-format-2.md) (the run file).
**Related, not built on:** [RFC-0005](RFC-0005-missions.md) (build identity, flotilla's autonomy
ladder).
**Asked by the operator, 2026-11-26:** "expand MVP v2 with a better support of these things somehow
through the UI. So we can track the runs, we can see how robots are doing... a learning interface,
how we can drive this learning and somehow integrate with the results... maybe training is a new
type of goal, and then instead of us running the robot, we are training the robot... another type
of app that lives in the ecosystem, some another source within the control app, or how to think
here?"
**Evidence:** every `file:line` and file name below was read on 2026-11-26 in the `mission-control`
worktree (at 0a7c783, with the uncommitted `pool` command in the working tree), and in
`/work/microduck-nav`, `/work/robotics-evals` and `/work/agentic-ai-homelab`. The line citations
were re-read against the code for revision 2. What I did not verify is in section 13.

## Changes in revision 2

The review's verdict: accept option A, with changes to the data path, the promotion rule and the
first slice. The first version is now named for what it is: **a request ledger plus an artefact
import, not an adapter**. Where each finding went:

| Finding | Addressed in |
| --- | --- |
| C1, no data path for the read-only slice | 6.2 (the data path: files the Observatory imports, rows Mission Control holds, a derived model record, the eval result as an imported summary file); 6.3; 6.5; 11, Q2; 12 |
| M1, promotion identity has no source | 7.1 (a promotion record with token identity, tokens on, the MCP `use_profile_version` case); 11, Q5 |
| M2, the promotion rule is unsatisfiable on `avoidance_v1` | 7.2 (the operator's decision of 2026-11-26: `avoidance_v2`, a safety regression on `avoidance_v1`); 11, Q5 |
| M3, the sim-only refusal is not in the profile save | 7.3 (the real-variant refusal in the save path, with a contract test); 11, Q5 |
| M4, an eval goal kind has no executor | 6.1 (no `eval` goal kind; the eval spec is a document the skill fills); 6.2; 11, Q3 |
| M5, the run states are not shared | 6.1 (a `training_requests` table with its own states); 7.4 (STOP and STOP ALL do not reach the trainer; no STOP control); 11, Q7 |
| M6, the "twice" premise is not shown on disk | 2 (the premise restated); 10.1 (the record of today's manual runs, before any code) |
| M7, the model record lacks what promotion must check | 6.3 (the compatibility fields); 7.1 (promotion refuses a disagreeing robot) |
| m1, no index column to join replay runs by build | 6.3 (the join); 6.6 (an additive `build` column in the run index) |
| m2, the checker's entries | 6.6 (the list) |
| m3, `pool` exists | 2 (the scenario row); 4 (stage 1); 6.3 (the pool manifest's sha256); 13 |
| m4, the `learned.py` citation | 6.3 (the id row now cites `:200-201`) |
| m5, the window's end includes the swap back | 7.5 (the windows) |
| m6, the build key without the seed | 6.3 (the key) |
| m7, `learning.js` as its own module | 6.4; 10.2 (the dependency on RFC-0025 step 8 is weakened) |

The reviewer's answers to the eight questions are shown under each in section 11; the questions
stay the operator's.

## 1. Problem

The lab now trains a robot's controller. It does so by hand, through a chain of tools and
messages, and the chain has no home in the platform:

- The operator cannot see in Mission Control or the Observatory that a model exists, what trained
  it, how it scored or which robot runs it. The facts sit in a local logs folder, in
  `robotics-evals` and in a profile.
- Nothing connects the three records of one model: the training run (a commit, a task, curves,
  checkpoints), its evaluation (scores with intervals, on frozen scenarios) and its use (a robot's
  `local_controller`, a run's build identity). A person joins them from memory.
- The loop is operated by messages to the homelab session and by skills run in a terminal. It works.
  It is also the part of the lab that is least visible and most repeated.

This RFC asks how learning should appear in the platform: as a new kind of run on a new kind of
resource inside the apps we have, or as an app of its own, or as a tool we adopt. It also asks
what stays outside whatever we choose: the safety rules, and the homelab's ownership of the DGX.

## 2. Where it stands: the manual loop

Training has run by hand on 2026-11-26: a smoke test, M1, and a series (M2a, M2b) in progress at
writing. Section 10.1 holds the record of each run. What exists, by piece:

| Piece | What it does | Where |
| --- | --- | --- |
| M1 | The first DGX run: `Mjlab-Nav-OneWall-MicroDuck`, 4096 envs, 200 iterations, 15 min 42 s. Replay: 13 of 16 environments (81 %) stopped before the wall. Met, narrowly | `docs/training/running-and-results.md`, the M1 table; logs in `/work/microduck-nav-runs/m1/` |
| M2a, M2b | The full task two ways: `Mjlab-Nav-MicroDuck` (NVIDIA's recipe, 50 Hz) and `Mjlab-Nav-Deploy-MicroDuck` (10 Hz, no lateral residual, matched to our navigator). In progress at writing; the operator kept the DGX in robotics mode for the whole series | `/work/microduck-nav/docs/M2.md`; section 10.1 |
| The homelab's side | The homelab session runs `gpu-mode-swap.sh`, the stack's `.env` and `prepare.sh`. We send the commit, task, `--env.scene.num-envs`, trainer args and a maximum runtime; it answers when the trainer is up and when production is back. The homelab ran every swap of today's runs | `/work/agentic-ai-homelab/docs/recipes/robotics-training.md`; `.claude/skills/dgx-training-run/SKILL.md` |
| The preflight | Checks the commit is clean and pushed, the lock, the walker's SHA-256, `--agent.save-interval` and `--agent.logger tensorboard`, the runtime syntax and the window; prints the request block | `.claude/skills/dgx-training-run/scripts/preflight.py` |
| The checkpoint report | Reads curves from the copied-back logs, checks the ONNX shape `(1, 1343) -> (1, 3)`, and says INCONCLUSIVE under 8 points | `.claude/skills/dgx-training-run/scripts/checkpoint_report.py` |
| The learned controller | `learned@<sha8>`: an ONNX residual on the follower's command, simulator only; a failing model brakes. Since 0a7c783 it runs at the rate the model was trained for (from the ONNX metadata, else a `<model>.onnx.json` sidecar, else `--model-rate 50\|10`) and refuses a model with none | `robots/duck/src/duck_lab/plugins/learned.py` (`model_spec`); RFC-0025 section 3.7 |
| The build identity | One string written into every run: `brain@<commit>+ctrl@<controller>+walker@<sha8>+sim@<commit8>+tof@<preset>-s<seed>`; `ctrl` is `rules@1` or `learned@<8 of the model's sha256>` | `libs/runfile/src/runfile/build.py:3, :83` |
| Scenario sets | `lab-scenarios export` freezes challenge scenarios as one JSON each plus a manifest; `lab-scenarios mine` turns failed runs into training scenarios (failure mining, R7c), excluding an evaluation set by manifest; `lab-scenarios pool` writes a training pool (one item per line) and its manifest, excluding evaluation sets. `pool` is in progress and uncommitted | `libs/runner/src/labrunner/scenarios.py:117, :277, :331-366` |
| `robotics-evals` | A private evh project on eval-harness 0.8.1: the frozen set `avoidance_v1` (30 scenarios), the run ledger (one line per run with its build and file hashes), `evh import-run` and `evh comparison-show` | `/work/robotics-evals/README.md`, `docs/EVAL-HARNESS-0.8.1.md` |
| The challenge batch | Freeze a set, one batch per arm on the same seeds, score, import, compare; at least 10 scenarios per arm; success is the primary metric, collisions a safety limit | `.claude/skills/challenge-batch/SKILL.md` |

The loop a person runs today:

```text
 scenario pool --> train goal --> checkpoints --> replay as sim runs --> eval batch --> comparison --> promotion
      ^            (a DGX window)   (model_N.pt,     (a normal run,       (robotics-evals,   (with       (the robot's profile
      |                              model_N.onnx)    ctrl@learned@sha8)   intervals)        intervals)   names the model)
      |                                                                                                       |
      +------------------------------- failure mining (lab-scenarios mine, R7c) <-----------------------------+
```

Every arrow is a person or an agent with a terminal. The decision rule at the end is the training
guide's (`docs/training/running-and-results.md`, "Then R5, in robotics-evals"): a learned arm that
does not beat the rules does not ship, and the training reward is not consulted. Section 7.2
restates it for the data we have: the first draft's wording ("beats the rules on `success`") cannot
fire on `avoidance_v1`, where the rules arm scored `success` 1.0 (review M2).

The principle for what to build is the project's own: automate what we have done twice. The
review (M6) found that the premise "twice" was not shown by evidence on disk: at 16:40Z only
`m1/` and `r5/rules_v1` were in `/work/microduck-nav-runs/`. Section 10.1 therefore records the
runs first, and the build starts after M2a and M2b are recorded.

## 3. The idea: training is a run on another kind of resource

A goal run today is a goal on a robot, under a lease, with STOP always winning. The operator's
suggestion is that training is the same shape with a different resource: instead of running the
robot, we train it. The mapping holds for the **record** (a request, states, artefacts, a verdict)
and breaks for **control**: Mission Control can neither start, stop nor observe the trainer
(review, verdict). So the first version is a request ledger plus an artefact import, not an
adapter.

| Robots today | Learning |
| --- | --- |
| goal | a training request (a spec, and a ledger row); an eval spec, a document |
| robot adapter | none in the first version: the homelab runs the DGX and Mission Control records. A trainer adapter is a later, separate piece (6.2) |
| lease and STOP | a GPU window the operator gives; STOP does not reach it (7.4) |
| run file plus replay | a training run (curves, checkpoints, as imported files), each checkpoint replayed as a normal sim run |
| judge verdict | an eval result from `robotics-evals`, imported as a summary file, with intervals |
| profile writes, operator only (the MCP's R7) | a promotion record for a model, operator only, by a token identity (7.1) |
| mission approval modes (RFC-0030) | a training plan approved once, with a GPU-hours budget (later; Q4) |

"The MCP's R7" is the rule in `docs/wip/MCP-COVERAGE.md` and `mcp_server.py`: an agent cannot write
a profile, because a profile carries the robot's limits. It is not the research plan's R7 (our own
variant of the controller, parts R7a to R7e). Both names are in use; this RFC writes "the MCP's
R7" for the first.

Where the mapping holds and where it does not, read from the code:

- **A goal is robot-shaped.** The kinds are `point`, `go_to_object`, `go_to_area`, `explore` and
  `inventory` (`libs/missions/src/missions/goals.py:11`); a goal run names a robot, a `target` of
  `sim` or `real` and optionally a site (the `goal_runs` table in
  `apps/mission-control/src/mission_control/store.py:45-50`, with `robot TEXT NOT NULL` and `target
  TEXT NOT NULL`; `core._start_run`, `core.py:293`). A training run has no robot, no site, no
  start pose and no target in that sense. So "training is a goal kind" is true in the library the
  operator sees (a named, validated, versioned spec) and false in the table. Section 6.1 proposes
  the split.
- **`RobotAdapter` does not fit.** The Protocol (`robots.py:278`) asks for `call`,
  `make_navigator`, `map`, `map_version` and `sighting`, and refuses the ones a robot lacks. A
  trainer would refuse all of them. A trainer adapter, when there is one, is a sibling Protocol,
  not a robot with missing parts.
- **The run states do not carry over.** `ACTIVE` is `("queued", "running")`
  (`apps/mission-control/src/mission_control/goals.py:11`) and `TERMINAL` is `navcontract.ENDS`
  (`libs/runfile/src/runfile/navcontract.py:14`), the navigator's vocabulary. A training request
  has other states (6.1), so the first draft's "shares the run states" is withdrawn (review M5).
- **STOP is different.** A robot's STOP is immediate and Mission Control may send it. A training
  run's stop is "after the next save": rsl_rl saves nothing when stopped, so a run stopped between
  saves loses everything since the last one (`dgx-training-run` skill, "Always set
  `--agent.save-interval`"). Mission Control cannot perform it: the homelab's swap does, and its
  `timeout` is the bound (7.4). `core.stop_all` iterates robots only (`core.py:171-183`) and keeps
  doing so.

## 4. The lifecycle, and where it feeds back

Seven stages. Each names its record and its owner.

| Stage | Record | Owner |
| --- | --- | --- |
| 1. Scenario pool | A manifest of scenarios (`lab-scenarios pool`, export or mine), with evaluation items excluded by manifest; the manifest's sha256 is the pool's identity | `lab-scenarios`, in `libs/runner` |
| 2. Train | A training request: commit, task, args, pool hash, walker hash, window, state | The request is recorded in Mission Control; the homelab runs |
| 3. Checkpoints | `model_N.pt` and `model_N.onnx` with SHA-256, saved at the interval | The trainer; copied back, then imported into the Observatory's `training/` folder |
| 4. Sim replay | Each chosen checkpoint run as a normal simulator run: its build has `ctrl@learned@<sha8>` | The runner under the simulator lock, as `sim-run` does |
| 5. Eval batch | Per arm, a scores file, imported into `robotics-evals` under the build identity | `challenge-batch`; `evh` |
| 6. Comparison | `evh comparison-show`: delta, p, wins and losses, a 95 % interval, collisions; imported as a summary file | `robotics-evals`, then the Observatory's import |
| 7. Promotion | A promotion record in Mission Control and a profile version whose `plugins.local_controller` names the model by file and SHA-256 | The operator, by a token identity |

Failure mining (R7c) closes the loop: failed runs of any arm, found by the judge's verdict or a
stop, become scenarios in the next pool, with start poses just before the failure. The pool's
manifest then lists which evaluation items it excluded, so the evaluation stays unseen.

## 5. Options

**A. Extend Mission Control and the Observatory (recommended).** Mission Control gains a request
ledger and a promotion record; the Observatory imports the training artefacts as files and gains
a Learning view and a model page with lineage. A small library (section 6.3) holds the record
types and the pure functions that derive a model's record from the sources: code commit, pool
hash, training run, walker, eval results, promotion.

- For: no new app, container, token or origin (RFC-0024's reasoning applies as it did for
  planning). The operator already goes to Mission Control to operate and to the Observatory to
  understand (RFC-0023, decision D1), so learning lands where each job already lives. The
  Observatory's replay of a checkpoint as a normal run is the one it has. The safety rules (the
  operator-only promotion, the sim-only learned controller) are enforced by code that already
  enforces their neighbours.
- Against: Mission Control grows by a record that is not a robot, and the run store is
  robot-shaped (section 3). A Learning view is more shell code, though the shell is already
  modular by panel (`apps/observatory/web/shell/*.js`; 6.4). The trainer is run by a person at the
  homelab, so the first version is a ledger with a human inside it, which the robot adapters do
  not have. If learning grows (sweeps, many models, a GPU fleet), it will want its own place;
  section 8 says when.

**B. A third app, a Lab Bench.** A new app and origin for learning: train, evaluate, compare,
promote, with its own store and UI.

- For: a clean failure domain (a stuck trainer cannot touch the lock), a release pace of its
  own, and room to grow without arguing with the robot code. It would hold a GPU-shaped
  workload that does not suit Mission Control's small container.
- Against: it pays the split's costs before any trigger fires: a second token that can start
  things (or a second place that can ask for a GPU window), a second origin or proxy rule, a
  second set of contract tests, a second UI to keep consistent with the first, and a join to
  Mission Control anyway, because promotion writes a robot's profile and replay runs are robot
  runs. RFC-0024 rejected two origins for the same reason, and RFC-0030 section 8(b) rejected a
  separate planner app before its triggers. Nothing here is big enough yet to need it.

**C. Adopt MLflow, or TensorBoard plus a registry.** Use a tool that already tracks runs, metrics,
artefacts and model versions.

- For: it exists, it is known, and its experiment comparison and model registry are mature. We
  already write TensorBoard events (`--agent.logger tensorboard`), so curves cost nothing.
- Against: it tracks a model's training, not the platform's facts. Our identity is the build
  string, the frozen scenario set and `robotics-evals`'s ledger, and our decision is by
  intervals on frozen scenarios, not by a training metric. MLflow would hold a second copy of a
  model's record that disagrees with the first the day someone forgets to log. It adds a service
  and a dependency (a new dependency needs the operator's approval). It does not know about the
  lease, the operator-only promotion or a robot's profile. Its promotion stages would need
  enforcement in our code anyway.
- Kept regardless: TensorBoard stays the tool for raw curves. The training run page shows
  headline curves extracted to JSON at import (6.4) and does not redraw the rest. How a link to
  the full events would be served is open (section 13).

The comparison, in one table:

| | A: extend | B: Lab Bench | C: MLflow or TensorBoard plus registry |
| --- | --- | --- | --- |
| New app or service | No | Yes | Yes (MLflow); no for TensorBoard alone |
| Knows the lease, promotion rule, profile | Yes | Through a join | No |
| Cost now | One library, one table, one import, one view | A whole app | A service and a second record |
| Reversible | Yes: records are files and rows | Harder once it has users | Harder once logged |
| Fits the "twice" principle | Yes: built after M2 is recorded | No: built before | Partly |

The session's own for-and-against were not kept as text; the above is written afresh from the
code and RFCs read for this draft.

## 6. Proposal: option A

### 6.1 Specs, and the request table

Two specs, both documents in the learning library (6.3), not goal kinds. The first draft added
`train` and `eval` goal kinds to Mission Control; the review found that a goal run goes through
`rt.navigator.goal_start(spec)` (`core.py:500-506`) and that an eval has no executor there (M4).

- **A train spec** is a document: the training project and the full commit, the task, the number
  of environments, the trainer arguments, a maximum runtime, the pool (a manifest hash), the
  walker's SHA-256, and a GPU-hours ceiling. It is validated before a window is asked for, with
  the preflight's checks as rules (clean and pushed commit, `--agent.save-interval` present, the
  logger, the runtime syntax, a window clear of the nightly).
- **An eval spec** is a document: a frozen scenario set (a manifest hash), the arms (each a local
  controller and, for a learned one, a model's files with checksums), the seeds, the sensor
  setting and the primary metric. It is the `challenge-batch` flow as data. The skill fills it
  and runs the batch, as today; Mission Control does not run it (Q3).
- **The table.** Reusing `goal_runs` would make `robot` and `target` meaningless for a third of
  its rows, and its readers are goal-shaped (`core.py:641-657, 681-683, 546-549`). Training
  requests get a table of their own, `training_requests`, in a migration from schema 4 to 5
  (`SCHEMA_VERSION = 4`, `store.py:10`), with **its own states**. A vocabulary lives in
  `libs/learning`; the set is proposed, not fixed: `requested`, `window_given`, `up`, `running`,
  `done`, `stopped_with_checkpoint`, `failed`, `cancelled`. `stopped_with_checkpoint` is distinct
  from `failed`: a run stopped after a save kept a checkpoint and is not a failure. Mission
  Control's list shows training requests in a list of their own; `goal_runs`, the lease and the
  robot adapters do not change. In the first version the states are set by hand by the operator
  from the homelab's messages (a ledger form), because nothing observes the trainer.

### 6.2 The data path: a request ledger plus an artefact import

The review's critical finding (C1): the first draft put the registry in Mission Control's store
(Q2 A), the views in the Observatory, and connected them with nothing. The Observatory's shell
never calls Mission Control (the proxy forwards only:
`apps/observatory/src/observatory/server.py:28-29,
:464-472`); Mission Control's compose mounts `/config/robots` (read only) and `/state` only
(`apps/mission-control/compose.yml:22-29`), and the boundary checker bars it from the data folder
(`FORBIDDEN_MODULES`, `scripts/check_boundaries.py:74-76`); no container mounts
`/work/robotics-evals` or `/work/microduck-nav-runs`. The data path therefore mirrors goal runs:

- **Mission Control holds the operational rows:** the request (`training_requests`), its
  approval, and the promotion record (7.1).
- **The Observatory imports and serves the artefacts as files.** A `training/` folder beside the
  runs holds, per training run: `request.json`, `params/`, the ONNX files with their SHA-256, the
  headline curves extracted to JSON at import (the importer runs in microduck-nav's venv; the
  Observatory reads no tfevents), and the `.pt` files under a retention rule. An import CLI in
  `libs/learning` writes it, with a contract test and M1's folder as the fixture.
- **The eval result enters as an imported summary file:** the `evh comparison-show` output with
  the evh run ids and the `robotics-evals` commit. `robotics-evals`' data folder is still changed
  only through `evh`; the Observatory reads the summary, not the ledger.
- **The model record is derived**, not stored: pure functions in `libs/learning` assemble it from
  the training artefact (Observatory), the replay and eval runs by build, the eval summary
  (imported file) and the promotions (Mission Control). If a stored document is wanted later, a
  CLI writes it into the Observatory's data folder with a contract test: never two writers.

**The trainer adapter is a later piece.** It would be a sibling to `RobotAdapter`, with calls shaped
for a window rather than a body:

```text
request(spec) -> request record     # the preflight's request block, recorded; nothing is sent to the DGX
status(request_id) -> state         # the states of 6.1, read from the copied-back logs
stop_after_save(request_id)         # asks; the homelab's swap does it; not built before the homelab offers an interface
fetch(request_id) -> files          # logs, checkpoints, ONNX files with their SHA-256
```

**Nothing here touches the DGX.** The homelab session runs the swaps, the stack's `.env` and
`prepare.sh`; nobody else logs in, runs docker, runs `gpu-mode-swap.sh` or touches the Mac mini's
production socket (the homelab recipe; the `dgx-training-run` skill, "The split"). In the first
version Mission Control records the request and the operator relays the message to the homelab
session exactly as today. I found no machine interface to the homelab for swaps, so a call from
Mission Control to the homelab is a thing to ask the homelab for, not to build around; the
request form waits for that answer or is a ledger form with hand-set states.

Later adapters are the CPU (the C7 check runs 8 envs x 50 iterations on CPU) and a rented GPU. The
policy about windows differs.

### 6.3 The `learning` library and the model record

A small standard-library package, `libs/learning`, in the style of `libs/missions`: data in, data
out, no network, no robot. It holds the record types, their validation, the training-request
vocabulary, the two specs and the pure functions that derive a model's record. It may import
`runfile` for build parsing only (6.6).

A **model** record is the first-class object, derived (6.2):

| Field | What | Source |
| --- | --- | --- |
| id | The ONNX file's SHA-256, whole; the first 8 are the `ctrl` part of the build identity | `learned.py:200-201`, `runfile/build.py` |
| code | The training project and full commit | The training request |
| pool | The scenario pool manifest's sha256, and which evaluation manifests it excluded | `lab-scenarios pool` manifests (`scenarios.py:331-366`) |
| training run | The request, window, args, seed, actual iterations, seconds per iteration, the checkpoint it came from | The imported training artefact |
| body | The robot kind, the walker's SHA-256 (`ce894d30...` for Pollen's v10), `obs_layout`, `policy_step_s`, `lateral_limit` | The ONNX metadata or sidecar, as `model_spec` reads them |
| sidecar | The checksum of the `<model>.onnx.json` sidecar, when one is used | The imported training artefact |
| replay runs | Run keys of the sim replays, joined by build | The run index (6.6) |
| eval results | `robotics-evals` run ids per arm, the comparison's delta, interval and collisions | The imported eval summary |
| promotions | Which robot's profile version names it, by which token identity, when, with the comparison shown | Mission Control's promotion records |

The compatibility fields (review M7) are there because `learned.py` refuses a model whose
`policy_step_s`, `lateral_limit` or `obs_layout` disagree with the robot's, and (since 0a7c783) a
model with no rate at all. Promotion refuses a robot whose profile or walker disagrees with the
record's `body` (7.1), so the check happens before a goal start, not at it.

**The key.** A model is keyed by its files and checksums, never by "the newest run" and never by
a raw checkpoint (RFC-0025 section 3.7). Replay and eval runs are joined by the build identity
without its `-s<seed>` tail, which is how `robotics-evals` imports it (review m6): the record
keys on `brain@...+ctrl@learned@<sha8>+walker@...+sim@...+tof@...`, one record for every seed.
The library does not become a second ledger; `robotics-evals` remains where evaluation results
live and the record holds their ids.

The name has a clash: "model" already means a language model in RFC-0005's build identity
(`model@<alias>`) and RFC-0030's LLM planner. Question 1 asks.

### 6.4 The Observatory's Learning view

Read-only, in the Observatory, because it explains and Mission Control operates (RFC-0023, D1).
The unit is the training run, not the model (review, first UI slice):

- **Learning:** a list of training runs and models: state, task, commit, GPU time, the headline eval
  result, and where each model is promoted.
- **A training run page:** the headline curves (reward, episode length, the terminations) from the
  JSON extracted at import, and the three agreement signals of the skill: curves, replay and the
  ONNX shape.
- **A model page, with lineage,** once the first learned arm has a comparison: the chain of
  section 4 for one model: the pool it was trained on, the training run, the checkpoint, the
  replay runs (each a link to the ordinary run page, where the steering signals show when the
  controller overrode the follower), the eval comparison with its interval, and the promotions.
- **The results join:** the model page reads the imported eval summary and the replay runs by
  `ctrl@learned@<sha8>`; it does not write to `robotics-evals`.

The view is a `learning.js` module of its own beside the other panels in
`apps/observatory/web/shell/` (review m7), additive to `shell.js`.

Mission Control carries the operating side: a list of training requests, a request form (a ledger
form with hand-set states until the homelab offers an interface), and the promotion, for the
operator only. It shows **no STOP control** on a training request (7.4).

### 6.5 What goes where, one line each

- `libs/learning` holds the types, the vocabulary, the two specs, the derivation and the import CLI.
- Mission Control holds the `training_requests` table, the request form, the promotion record and
  the operator's actions.
- The Observatory imports the training folder and the eval summary, and holds the views.
- `robotics-evals` holds the evaluation; the skill and `evh` run it.
- `libs/runner` holds the scenario tools and the runner.
- The homelab holds the DGX.
- TensorBoard holds the raw curves.

### 6.6 The checker, the library's wiring and the run index

`libs/learning` needs these entries (review m2), as `libs/missions` has:

- `MODULES["learning"]` and `ALLOWED["learning"]` in `scripts/check_boundaries.py` (`MODULES` at
  `:26`, `ALLOWED` at `:47`; `ALLOWED[unit]` is indexed directly at `:164`, so a missing entry is
  an error, not a pass). `learning` may import `runfile` for build parsing, with a
  `FORBIDDEN_MODULES` row (`:72`) barring `runfile.catalog`, `runfile.index`, `runfile.store` and
  `runfile.mcapio`.
- `learning` in `ALLOWED["mission_control"]` (`:55`) and, if the Observatory imports through the
  library, in `ALLOWED["observatory"]` (`:54`).
- The Observatory's Dockerfile copying `libs/learning`.
- `libs-sync` and `LIBS_TESTS` in the `Makefile` (`:80-84`).
- **An additive `build` column in the run index** (review m1): `RUN_COLS`
  (`libs/runfile/src/runfile/index.py:48-49`) has no `build`, so replay runs cannot be joined by
  `ctrl@learned@<sha8>` without opening each run file. Whether the index can gain a column
  without a rebuild rule is not verified (section 13).

## 7. Safety

These are the rules the proposal must not weaken. None is new; each already holds in the code or the
decisions cited, and the proposal adds the places where it would otherwise be skipped. The review
found three of them not enforceable as the first draft wrote them (7.1, 7.2, 7.3).

### 7.1 Promotion is operator only, by a token identity

The first draft said an agent "has no profile writes". True of saving a profile; not of switching
one. The review (M1) read the code:

- `profilestore.Store.save` records no identity (`libs/runfile/src/runfile/profilestore.py:87-100`).
- `Ctx.client()` takes the caller's word when there is no token (`api.py:76-82`), and
  `require_tokens` defaults to `False` (`api.py:661`).
- The MCP allow-list carries `("PUT", "/robots/{id}/profile/current")` (`mcp_server.py:57`), and
  the tool `use_profile_version` (`:185-189`) is guarded by `sim_robot` only: an agent may choose
  among the versions the operator saved.

So: **a promotion is a Mission Control record**: the model's sha256, the robot, the profile
version, the token identity and the comparison shown. It is made only from a token identity the
operator names, as RFC-0030 4.5 does for approvals, and **tokens are on** for it. Promotion refuses
a robot whose profile or walker disagrees with the model record's `body` (6.3). An agent may
propose a promotion as a record the operator reads; it cannot perform one.

**The MCP case, to decide:** `use_profile_version` can make a version current whose
`plugins.local_controller` differs from today's, which would put a model on a robot with no
promotion record. This RFC **recommends refusing a version switch that changes
`plugins.local_controller`** through the MCP (the switch then needs the operator's own token). The
alternative is to allow it and record it as a switch, not a promotion, which leaves a model on a
robot that no comparison was shown for. The recommendation is Q5's.

### 7.2 The promotion rule (decided by the operator, 2026-11-26)

The first draft's rule (the learned arm "beats the rules on `success`") cannot fire on
`avoidance_v1`: the rules arm scored `success` 1.0 and collisions 0.0 there (review M2). The
operator has decided a harder frozen set, **`avoidance_v2`**, being built now, and a rule on both
sets. Its pre-registration lives in `robotics-evals`, `docs/R5-PREREGISTRATION.md`; this section
states the rule as the operator gave it, and the pre-registration is the text that governs if the
two ever differ.

- **Primary, on `avoidance_v2`:** `success`; the learned arm must beat the rules.
- **Safety, on `avoidance_v1`:** no regression: 30 of 30 scenarios and 0 collisions.
- As before: at least 10 scenarios per arm; the comparison is `evh comparison-show` with its
  interval and its collision count; the training reward is not consulted.

The set and the rule are pre-registered before the first learned arm is evaluated, so the metric
is not chosen after the result. A set is frozen when its file hashes are in the dataset; it is
never edited, a change is `_v3`.

### 7.3 A learned controller is sim only until R8, in the save path

`lab-challenge` refuses `--local-controller learned` on a host whose variant is not `sim`
(`libs/runner/src/labrunner/challenge.py:174-175`), and the plugin refuses at construction
(`robots/duck/src/duck_lab/plugins/learned.py:196-197`). Neither is the profile save, which is
where promotion happens: a `real`-variant profile naming `learned` saves, and fails at the next
goal start (review M3; `apps/mission-control/src/mission_control/profiles.py:68-77`). So
`validate_profile` (or `_fits`) **refuses a merged `real` variant that names a learned controller**,
at save and at promotion, with a contract test. The refusal is lifted by R8's safety review
(RFC-0025 section 3.7; RESEARCH-LEARNED-AVOIDANCE R8) and the operator, as a rule in code and not
a convention, the same shape as RFC-0030's mode 3.

### 7.4 STOP does not reach the trainer

The first draft let the trainer share the run states and "stop after the next save". It cannot.
STOP and STOP ALL (`core.stop_all` iterates robots only, `core.py:171-183`) **do not reach the
trainer**, and the UI **shows no STOP control** on a training request, because a control that does
nothing reads as one that works. A run's stop is the homelab's: its `timeout`
(`ROBOTICS_MAX_RUNTIME`)
is the enforcement, and the operator may ask the homelab session for a stop after the next save.
The ledger records what happened (`stopped_with_checkpoint`), set by hand until a machine interface
exists.

### 7.5 The rest, unchanged

- **Guards stay above the model.** The reflex, the drop stop, the guardrails' caps, the lease, the
  deadman and STOP sit outside the controller's interface and above it. A model that fails brakes.
  The seam clamps translation to the follower's request. Training the guards into the reward (R7b)
  makes the model careful; it does not remove one.
- **Nothing touches the DGX directly.** The homelab runs the swaps
  (`/work/agentic-ai-homelab/docs/recipes/robotics-training.md`). We send the commit, task, args and
  a window and wait for the answer. No Mission Control code logs in to the DGX, runs docker there,
  edits the stack's `.env` or touches the production socket.
- **The windows.** The nightly runs at 00:00Z and infra keeps 23:45Z to 03:00Z clear. Production
  must be back by 23:20Z, the operator's margin for the skill; the homelab's recipe says 23:30Z, and
  the earlier time holds. **The window's end includes the swap back**, which took 6 min 18 s when
  measured (review m5; I did not re-measure): a request is valid only if
  `start + max_runtime + swap_back <= 23:20Z`. A request that overlaps the nightly or fails that
  sum is refused by validation, before anything is sent. The operator gives each window; the
  homelab checks that production is idle. Every swap is announced beforehand
  (RESEARCH-LEARNED-AVOIDANCE, decided 2026-11-26). A series of runs in one window (the operator
  kept the DGX in robotics mode for M2a and M2b) pays the swap back once, at the end of the
  series.
- **Evidence before a word.** "It learned" requires the three signals to agree: curves, replay and
  the ONNX shape. "It is better" requires the comparison with its interval and its collision count,
  on at least 10 scenarios per arm and a frozen set the training never saw (7.2). The training
  reward is not consulted.
- **An eval is a simulator job.** It runs under the simulator lock, as `sim-run` and
  `challenge-batch` do, and never on a real robot.
- **No second writer for evaluation.** `robotics-evals`' data folder is changed only through `evh`.
  The Observatory reads the imported summary.

## 8. When to split into a Lab Bench

Option B is deferred, not rejected. The split triggers are the ones already written for the
pieces of this platform: RFC-0024's review, section 2 ("What should split out, and when",
`docs/wip/RFC-0024-REVIEW-2026-11-26.md`), with RFC-0018 section 5.1's "Ready to split when" and
RFC-0030 section 5. Read for learning, a Lab Bench becomes a separate app when one of these holds,
not before:

| Trigger | From | Reading here |
| --- | --- | --- |
| A second user of the Observatory's API, or a release pace unlike Mission Control's | RFC-0024 review, the Observatory row | The Learning view changes weekly while the robot views are stable |
| A second program imports the library | RFC-0018 5.1; the review's `libs/runfile` row | A second repository or app reads `libs/learning` |
| Long-running or heavy work that would take a core from Mission Control's container | RFC-0030 section 5 | Sweeps, many parallel evaluations, anything beyond a single request at a time; or the eval batch, which would be a new runner process with an API, not a goal kind (Q3) |
| Fleet scheduling with a clock of its own | RFC-0030 section 5 | A queue of training runs scheduled across windows, machines or a rented GPU |
| Its own UI that is not a panel of an existing page | RFC-0030 section 5 | The Learning view needs navigation, search and comparison of its own |
| A different owner or safety review cadence | RFC-0030 section 5 | Learning changes weekly; the executor changes with a safety review |
| A model or workload that needs a GPU or a host unlike Mission Control's | RFC-0030 section 5 | The orchestration itself needs a GPU, which today the homelab holds |

These are adapted triggers: the review's table is about the Observatory and the run format, and
RFC-0030's list is about planning. I applied them to learning; the operator may want different ones.
When a trigger fires, the split is a transport change: the library's records become an HTTP
contract, and Mission Control stays the only process that can write a robot's profile or take a
lease.

## 9. The flotilla link

Deferred. `docs/wip/IDEAS.md`, "With flotilla", item 5, records the operator's "maybe": flotilla as
an outer approver of auto-mode missions, to be discussed after MVP 2. Training would be one more
thing it could approve (a GPU window as an action that policy decides to run, ask or refuse), and
its autonomy ladder would map as it does for missions. Nothing here depends on flotilla, and nothing
here forecloses it. The record shapes (a request, a checksum, an approval with who and when) are the
ones RFC-0030 already defines for the join.

## 10. Placement in MVP 2

MVP 2's path (RFC-0025 steps 0 to 10: the interface, profile v2, the navigator split, hosts, the
Burger in Gazebo, the NXT's navigator, Nav2, scans, courses, the real Burger) does not wait for
this, and this does not block it.

### 10.1 The manual runs, recorded before any code

The review (M6) asked for the record first. It is the model record's shape, filled by hand, and
it is the evidence for what the record needs. What I know on 2026-11-26, from the operator's
brief for this revision; a blank is a fact not in my sources, to be filled from the homelab's
messages and the logs folders, not guessed:

| Run | Task | Envs x iterations | `save_interval` | Window start (Z) | Result |
| --- | --- | --- | --- | --- | --- |
| Smoke | not stated here | 64 x 20 | not stated here | not stated here | Ran |
| M1 | `Mjlab-Nav-OneWall-MicroDuck` | 4096 x 200 | not stated here | 15:55:47 | **Passed.** Progress 0.20 to 0.35, collisions 0.74 to 0.16, replay 13 of 16 environments (15 min 42 s) |
| M2a | `Mjlab-Nav-MicroDuck` | 4096 x 1500 | 100 | 16:15:00 | **In progress at writing.** About 4.75 s per iteration |
| M2b | `Mjlab-Nav-Deploy-MicroDuck` | 4096 x 400, chosen so its simulated time is about M2a's | 50 | after M2a | **In progress at writing** (planned after M2a) |

At 4.75 s per iteration, M2a's 1500 iterations take about 7,100 s of training (1500 x 4.75 s),
about 2 hours; that is arithmetic on a rate, not an observation of a finish. The operator kept the
DGX in robotics mode for the whole series, so there is one swap back, after M2b; the homelab ran
every swap. The record per run also needs: the commit, the seed, the pool, the walker's SHA-256,
the window's end and the swap-back time. Those are not in my sources; the first step of 10.2
is to fill them.

### 10.2 The steps

The principle: automate what we have done twice, and show it with the record of 10.1. This is not
scheduled against RFC-0025's steps. In the review's order:

1. **Now, no code:** the record of 10.1 for the smoke, M1, M2a and M2b, by hand (a file, a table
   in the training guide). M1's table already is one.
2. **`libs/learning`: the schemas and the import CLI,** with M1's folder as the fixture, and the
   checker entries of 6.6.
3. **The Observatory imports the folder and shows a training run page** (headline curves from the
   JSON extracted at import).
4. **The model page,** when the first learned arm has a comparison (7.2).
5. **Mission Control's request form and `training_requests`,** after the homelab's answer on a
   machine interface, or as a ledger form with hand-set states; then the promotion record with
   the tokens on (7.1) and the profile-save refusal (7.3).
6. **Later:** the GPU budget approval (Q4), failure mining as a button, a trainer adapter, other
   trainers, an eval runner process.

The slice starts when M2a and M2b are recorded. The Learning view is a module of its own
(`learning.js`, 6.4), so it no longer waits for RFC-0025 step 8's panel split; it is additive to
`shell.js`, which RFC-0024's review ranks as the part of MVP 2 that will hurt. Whether the whole is
in or after MVP 2 is question 6.

## 11. Questions for the operator

Each with options and a recommendation. The answer to any can be "none of these". Under each,
"Reviewer:" is the advisor's answer (the review, "The reviewer's answers to the questions"); the
question stays the operator's.

1. **The name.** The library, the view and the record.
   - A: library `models`, view "Learning".
   - B: library `learning`, view "Learning", record "model".
   - C: a product name, "Lab Bench", for the view and the library.
   - **Recommendation: B.** "Model" already means a language model in RFC-0005 and in RFC-0030's
     planner, and a library called `models` would invite the clash into imports. `learning` matches
     the view. "Lab Bench" names the app of option B, which is not the proposal.
   - **Reviewer:** B, agree; the record type `Controller` or `ControllerModel`.
   - **Decided (the operator, 2026-11-26): B.**
2. **Where the model registry lives.**
   - A: in the platform: operational rows (request, approval, promotion) in Mission Control, the
     training artefacts and the eval summary as files the Observatory imports, the model record
     derived by `libs/learning`; evaluation results stay in `robotics-evals` and the record holds
     their ids. There is no registry store.
   - B: in `robotics-evals`: the model is an evh system and its data folder is the registry.
   - C: MLflow's registry.
   - **Recommendation: A.** Promotion, the lease and the profile are Mission Control's, and the
     derived record sits next to them. B would make a private evaluation repository the home of a
     fact the robots need, and `data/` is changed only through `evh`. C is option C's argument.
   - **Reviewer:** A with C1's correction (the data path of 6.2; drop "store").
   - **Decided (the operator, 2026-11-26): A**, with C1's correction.
3. **Do eval goals run in Mission Control or in `robotics-evals`?**
   - A: Mission Control starts the batch, under the simulator lock, and hands scores to `evh`.
   - B: the batch stays the `challenge-batch` flow; Mission Control and the Observatory read the
     results and show a "requested evaluation" record.
   - C: both, in stages: B now, A when the batch has been run by hand three times. "A" is then a
     new runner process with an API, not a goal kind.
   - **Recommendation: C.** The batch needs the lock, `lab-challenge`, scoring and `evh`; those
     live in the skill and in `robotics-evals`. Mission Control may import `robotgate`, `runfile`
     and `missions` only (`check_boundaries.py:55`) and has no executor for it. Until then eval
     stays with the skill and `robotics-evals`, and the eval spec is a document the skill fills.
   - **Reviewer:** C, agree (M4).
   - **Decided (the operator, 2026-11-26): C.**
4. **How a GPU budget is approved.**
   - A: each window by the operator, as today.
   - B: a training plan approved once with a GPU-hours budget, as RFC-0030's mode 3 is for a
     mission; each swap still announced.
   - C: autonomous within a budget, no announcement.
   - **Recommendation: A for the first runs, then B after three windows have run through the
     ledger without a manual correction.** C is not recommended while the nightly window is
     someone else's. B must keep the 2026-11-26 decision that each swap is announced.
   - **Reviewer:** A then B; B needs tokens on; the homelab's `timeout` is the enforcement.
   - **Decided (the operator, 2026-11-26): A, then B** after three windows without a manual
     correction.
5. **Promotion rules.**
   - A: operator only, by a named token identity (7.1), after a comparison with an interval under
     the rule of 7.2 (success on `avoidance_v2`, no regression on `avoidance_v1`: 30 of 30, 0
     collisions), at least 10 scenarios per arm, on a set training never saw; the real-variant
     refusal of 7.3; the compatibility checks of 6.3. Sim only until R8.
   - B: automatic when the numbers pass.
   - C: A, plus a second reviewer's note on the record.
   - **Recommendation: A**, with a version switch through the MCP refused when it changes
     `plugins.local_controller` (7.1). It is today's rule written as code. B hands a robot's limits
     to a metric. C adds a reviewer the lab does not have; it can be added when there is a second
     person.
   - **Reviewer:** A with M2's rule, M3's refusal and M7's checks; C when there is a second person.
   - **Decided (the operator, 2026-11-26): A**, with the MCP version switch refused when it changes
     `plugins.local_controller`.
6. **Inside MVP 2, or after it?**
   - A: after M2a and M2b are recorded, as a side lane during MVP 2 (the read-only slice only).
   - B: after MVP 2, with RFC-0030's auto mode.
   - C: inside MVP 2, before the navigator split.
   - **Recommendation: A for the read-only slice, B for the request ledger's form and any
     adapter.** The read-only slice costs the critical path attention and no code on its steps.
   - **Reviewer:** A for the read-only slice, B for the adapter; the slice starts when M2a and M2b
     are recorded.
   - **Decided (the operator, 2026-11-26): A for the read-only slice, B for the adapter.**
7. **Does a training run share `goal_runs` or have its own table?**
   - A: its own table, `training_requests`, with its own states (6.1); the lists are separate.
   - B: `goal_runs` gets a `resource` column; `robot` and `target` become nullable.
   - **Recommendation: A.** `goal_runs` is read by the lease, the rehearsal and the group code, all
     robot-shaped, and the run states are the navigator's (`navcontract.ENDS`), not a trainer's.
   - **Reviewer:** A with M5: its own vocabulary, with `stopped_with_checkpoint` distinct from
     `failed`.
   - **Decided (the operator, 2026-11-26): A.**
8. **The first UI slice.**
   - A: the training run page and the Learning list, read-only, in the Observatory, from imported
     folders; the model page when the first learned arm has a comparison.
   - B: the request form in Mission Control, with the request block.
   - C: the eval comparison first, on `avoidance_v1`.
   - **Recommendation: A.** It shows what exists, shapes the record before anything operates a GPU,
     and risks nothing. C is moot: on `avoidance_v1` the rules arm scores 1.0 (7.2), and a learned
     arm does not exist yet (R5 is the first eval).
   - **Reviewer:** A as modified above: the unit is the training run, not the model.
   - **Decided (the operator, 2026-11-26): A**, the unit the training run.

## 12. Consequences

- A library `libs/learning` and the checker, Dockerfile, `libs-sync` and `LIBS_TESTS` entries of
  6.6, as `libs/missions` has.
- Mission Control gains a `training_requests` table (schema 4 to 5), a request form and a promotion
  record. It gains no goal kind and no trainer adapter in the first version. `goal_runs`, the
  lease, STOP and the robot adapters do not change.
- The Observatory gains an import of a `training/` folder and of an eval summary file, a
  `learning.js` module and a training run page; later a model page. It writes nothing to
  `robotics-evals`.
- The run index gains a `build` column, additively.
- The profile gains no field: `plugins.local_controller` and its model block are RFC-0025's. The
  profile save gains one refusal (a `real` variant naming a learned controller). Promotion is a
  record of Mission Control plus the existing save of a profile version, by a token identity the
  operator names; the MCP's version switch is refused when it changes `plugins.local_controller`
  (if Q5 A).
- Tokens are on for promotion.
- A model record is a derived document with a contract test, like the plan document of RFC-0030.
- Documentation: the training guide's M1 table becomes the first model record's example, and
  section 10.1 of this RFC is the record of the manual runs.

## 13. Not covered

Not built, and not run: nothing here was executed; the line citations were read on 2026-11-26.

- **Not verified, from the brief.** The homelab's messages (the request and the "up" and "done"
  replies) are the session's, and I did not read them; I used the recipe and the skill that
  describe them. The session's for-and-against on the options were not available as text and are
  rewritten here. M2a and M2b's progress, timings and results are as the operator's brief gave
  them; I read no log of either. The 6 min 18 s swap back is the review's measurement; I did not
  repeat it. `docs/R5-PREREGISTRATION.md` in `robotics-evals` and `avoidance_v2` were not on disk
  when I looked (`/work/robotics-evals/docs/` held `DATASET-SPEC.md` and
  `EVAL-HARNESS-0.8.1.md`); section 7.2 states the rule as the operator gave it, and I could not
  check it against the file.
- **Not verified, from the code.** That the homelab offers a machine interface to request a swap
  (I found none; the recipe is run by its session). That a Mission Control process can read the
  homelab's logs folder where it is today (`/work/microduck-nav-runs/` on the workstation, copied
  back by hand): by 6.2 it does not, and the Observatory imports instead. How the Observatory's
  importer would be wired: I read the run store's header
  (`apps/observatory/web/shell/runstore.js`) and RFC-0023, not the server's importer or routes.
  That `libs/learning` importing `libs/runfile` for build parsing causes no cycle. Whether the run
  index can gain a `build` column without a rebuild rule. The size of an M2 artefact folder, and
  so the retention rule for the `.pt` files. How a link to a run's full TensorBoard events would be
  served: a local server, a copy, or the homelab's. The review also read none of: `api.py` beyond
  auth and profile routes, `profiles.py` beyond `_fits` and `save`, `shell.js`, the Observatory
  importer, the skill scripts, the homelab swap script, eval-harness comparison code, and
  microduck-nav's source; neither did I.
- **Not measured.** The cost of any GPU hour here is the R6 plan's estimate, 6.5 to 10.5 hours for
  the whole ladder; the measured runs are the smoke and M1, and M2a's rate (about 4.75 s per
  iteration). No M2 result exists at writing.
- **Not decided.** The model record's exact fields and its checksum rule (a model's whole record
  edited later would need a new version, as RFC-0030's plan does); the exact states of 6.1; how a
  training run is retained and for how long; who may cancel a request after the homelab has
  answered; whether a held-out family (R7a) is a field of the pool or of the eval spec; the record
  type's name (Q1).
- **Not covered.** Training on the real robot or from real-home data (RFC-0025 section 5's privacy
  rules apply before any real-home run enters a pool); retraining Pollen's walker, which would
  invalidate every trained controller; recovery skills; higher-level learning from a camera;
  the sim-to-real work of R8, whose safety review comes first; a rented GPU's cost model and
  credentials; the legal reading of NVIDIA's licences for a published comparison (the research
  plan's section 8); a fleet view of several trainers; any approval by flotilla; the trainer
  adapter's calls, which stay a sketch until the homelab offers an interface.
- **Out of scope.** Changing the lease, STOP, the real-run key or the guardrails; the
  homelab's stack; the evaluation method (`robotics-evals`' decision).
