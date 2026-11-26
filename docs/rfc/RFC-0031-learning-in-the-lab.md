# RFC-0031: Learning in the lab, training as a run on another kind of resource

**Status:** Proposed, draft 1 (2026-11-26). For the operator's decision. Nothing here is built. The
operator approved writing it with option A of section 5 as the recommendation; that is a
recommendation, not a decision.
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
worktree, and in `/work/microduck-nav`, `/work/robotics-evals` and
`/work/agentic-ai-homelab`. What I did not verify is in section 13.

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

Training has run once end to end, by hand, on 2026-11-26. What exists, by piece:

| Piece | What it does | Where |
| --- | --- | --- |
| M1 | The first DGX run: `Mjlab-Nav-OneWall-MicroDuck`, 4096 envs, 200 iterations, 15 min 42 s. Replay: 13 of 16 environments (81 %) stopped before the wall. Met, narrowly | `docs/training/running-and-results.md`, the M1 table; logs in `/work/microduck-nav-runs/m1/` |
| M2a, M2b | The full task two ways: `Mjlab-Nav-MicroDuck` (NVIDIA's recipe, 50 Hz) and `Mjlab-Nav-Deploy-MicroDuck` (10 Hz, no lateral residual, matched to our navigator). The two commands are written | `/work/microduck-nav/docs/M2.md`. I found no run of either |
| The homelab's side | The homelab session runs `gpu-mode-swap.sh`, the stack's `.env` and `prepare.sh`. We send the commit, task, `--env.scene.num-envs`, trainer args and a maximum runtime; it answers when the trainer is up and when production is back | `/work/agentic-ai-homelab/docs/recipes/robotics-training.md`; `.claude/skills/dgx-training-run/SKILL.md` |
| The preflight | Checks the commit is clean and pushed, the lock, the walker's SHA-256, `--agent.save-interval` and `--agent.logger tensorboard`, the runtime syntax and the window; prints the request block | `.claude/skills/dgx-training-run/scripts/preflight.py` |
| The checkpoint report | Reads curves from the copied-back logs, checks the ONNX shape `(1, 1343) -> (1, 3)`, and says INCONCLUSIVE under 8 points | `.claude/skills/dgx-training-run/scripts/checkpoint_report.py` |
| The learned controller | `learned@<sha8>`: an ONNX residual on the follower's command, simulator only; a failing model brakes | `robots/duck/src/duck_lab/plugins/learned.py`; RFC-0025 section 3.7 |
| The build identity | One string written into every run: `brain@<commit>+ctrl@<controller>+walker@<sha8>+sim@<commit8>+tof@<preset>-s<seed>`; `ctrl` is `rules@1` or `learned@<8 of the model's sha256>` | `libs/runfile/src/runfile/build.py` |
| Scenario sets | `lab-scenarios export` freezes challenge scenarios as one JSON each plus a manifest; `lab-scenarios mine` turns failed runs into training scenarios (failure mining, R7c), excluding an evaluation set by manifest | `libs/runner/src/labrunner/scenarios.py` |
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

Every arrow is a person or an agent with a terminal. The decision rule at the end already exists in
the training guide: a learned arm that does not beat the rules on `success` without more
collisions does not ship, and the training reward is not consulted
(`docs/training/running-and-results.md`, "Then R5, in robotics-evals").

The principle for what to build is the project's own: automate what we have done twice. The
loop has run once (M1, and a smoke test before it). M2a and M2b are the second and third. Section 10
places the build after them.

## 3. The idea: training is a run on another kind of resource

A goal run today is a goal on a robot, under a lease, with STOP always winning. The operator's
suggestion is that training is the same shape with a different resource: instead of running the
robot, we train it. The mapping:

| Robots today | Learning |
| --- | --- |
| goal | train goal or eval goal |
| robot adapter | trainer adapter: the DGX through the homelab's contract (commit, task, num-envs, args, maximum runtime); later the CPU or a rented GPU |
| lease and STOP | a GPU window; stop after the next save |
| run file plus replay | a training run (curves, checkpoints), each checkpoint replayed as a normal sim run |
| judge verdict | an eval result from `robotics-evals`, with intervals |
| profile writes, operator only (the MCP's R7) | promotion of a model to a robot's `local_controller`, operator only |
| mission approval modes (RFC-0030) | a training plan approved once, with a GPU-hours budget |

"The MCP's R7" is the rule in `docs/wip/MCP-COVERAGE.md` and `mcp_server.py`: an agent cannot write
a profile, because a profile carries the robot's limits. It is not the research plan's R7 (our own
variant of the controller, parts R7a to R7e). Both names are in use; this RFC writes "the MCP's
R7" for the first.

Where the mapping holds and where it does not, read from the code:

- **A goal is robot-shaped.** The kinds are `point`, `go_to_object`, `go_to_area`, `explore` and
  `inventory` (`libs/missions/src/missions/goals.py:11`); a goal run names a robot, a `target` of
  `sim` or `real` and optionally a site (the `goal_runs` table in
  `apps/mission-control/src/mission_control/store.py`, with `robot TEXT NOT NULL`;
  `core._start_run`, `core.py:293`). A training run has no robot, no site, no start pose and no
  target in that sense. So "training is a goal kind" is true in the library the operator sees (a
  named, validated, versioned spec you can run from a list) and false in the table. Section 6.1
  proposes the split.
- **`RobotAdapter` does not fit.** The Protocol (`robots.py:278`) asks for `call`,
  `make_navigator`, `map`, `map_version` and `sighting`, and refuses the ones a robot lacks. A
  trainer would refuse all of them. A trainer adapter is a sibling Protocol, not a robot with
  missing parts.
- **STOP is different.** A robot's STOP is immediate and Mission Control may send it. A training
  run's stop is "after the next save": rsl_rl saves nothing when stopped, so a run stopped between
  saves loses everything since the last one (`dgx-training-run` skill, "Always set
  `--agent.save-interval`"). The adapter can request a stop; the homelab's swap performs it.

## 4. The lifecycle, and where it feeds back

Seven stages. Each names its record and its owner.

| Stage | Record | Owner |
| --- | --- | --- |
| 1. Scenario pool | A manifest of scenarios (export, mine, or a pool), with evaluation items excluded by manifest | `lab-scenarios`, in `libs/runner` |
| 2. Train | A training run: commit, task, args, pool hash, walker hash, window, state | The trainer adapter asks; the homelab runs |
| 3. Checkpoints | `model_N.pt` and `model_N.onnx` with SHA-256, saved at the interval | The trainer; copied back |
| 4. Sim replay | Each chosen checkpoint run as a normal simulator run: its build has `ctrl@learned@<sha8>` | The runner under the simulator lock, as `sim-run` does |
| 5. Eval batch | Per arm, a scores file, imported into `robotics-evals` under the build identity | `challenge-batch`; `evh` |
| 6. Comparison | `evh comparison-show`: delta, p, wins and losses, a 95 % interval, collisions | `robotics-evals` |
| 7. Promotion | A profile version whose `plugins.local_controller` names the model by file and SHA-256 | The operator |

Failure mining (R7c) closes the loop: failed runs of any arm, found by the judge's verdict or a
stop, become scenarios in the next pool, with start poses just before the failure. The pool's
manifest then lists which evaluation items it excluded, so the evaluation stays unseen.

## 5. Options

**A. Extend Mission Control and the Observatory (recommended).** Mission Control gains goal kinds
for training and evaluation and a trainer adapter. The Observatory gains a Learning view and a
model page with lineage. A small library (section 6.3) holds the model as a first-class object:
code commit, pool hash, training run, walker, eval results, promotion.

- For: no new app, container, token or origin (RFC-0024's reasoning applies as it did for
  planning). The operator already goes to Mission Control to operate and to the Observatory to
  understand (RFC-0023, decision D1), so learning lands where each job already lives. Training
  runs and robot runs can share the run list, the run states and the Observatory's replay of a
  checkpoint as a normal run. The safety rules (the operator-only promotion, the sim-only learned
  controller) are enforced by code that already enforces their neighbours.
- Against: Mission Control grows by a resource kind that is not a robot, and the run store is
  robot-shaped (section 3). The Observatory's `shell.js` is already one large file
  (RFC-0024 review: 1,872 lines), and a Learning view is more of it. A trainer adapter that
  waits on a person at the homelab is an adapter with a human inside it, which the robot adapters
  do not have. If learning grows (sweeps, many models, a GPU fleet), it will want its own place;
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
- Kept regardless: TensorBoard stays the tool for raw curves. The Learning view links to a run's
  TensorBoard events and does not redraw them. How that link is served is open (section 13).

The comparison, in one table:

| | A: extend | B: Lab Bench | C: MLflow or TensorBoard plus registry |
| --- | --- | --- | --- |
| New app or service | No | Yes | Yes (MLflow); no for TensorBoard alone |
| Knows the lease, promotion rule, profile | Yes | Through a join | No |
| Cost now | One library, two goal kinds, one view | A whole app | A service and a second record |
| Reversible | Yes: records are files and rows | Harder once it has users | Harder once logged |
| Fits the "twice" principle | Yes: built after M2 | No: built before | Partly |

The session's own for-and-against were not kept as text; the above is written afresh from the
code and RFCs read for this draft.

## 6. Proposal: option A

### 6.1 Goal kinds for learning, in their own library

Add two goal kinds: **train** and **eval**. They live in the learning library (6.3), not in
`libs/missions`. RFC-0030 made that library the home of robot-shaped planning and put a wall
around it (data in, data out, no robot); a train goal has no robot to plan for.

- **A train goal** is a spec: the training project and the full commit, the task, the number of
  environments, the trainer arguments, a maximum runtime, the pool (a manifest hash), the walker's
  SHA-256, and a GPU-hours ceiling. It is validated before a window is asked for, with the
  preflight's checks as rules (clean and pushed commit, `--agent.save-interval` present, the
  logger, the runtime syntax, a window clear of the nightly).
- **An eval goal** is a spec: a frozen scenario set (a manifest hash), the arms (each a local
  controller and, for a learned one, a model's files with checksums), the seeds, the sensor
  setting and the primary metric. It is the `challenge-batch` flow as data.
- **The store.** Reusing `goal_runs` would make `robot` nullable and `target` meaningless for a
  third of its rows. The proposal is a separate table for training runs that shares the run states
  of RFC-0030 and RFC-0014 (active and terminal states, the same words), so the run list can show
  both, and leaves `goal_runs` as it is. This is open question 7 in section 11 if the operator
  prefers the other way.

### 6.2 The trainer adapter

A sibling to `RobotAdapter`, with calls shaped for a window rather than a body:

```text
request(spec) -> request record     # the preflight's request block, recorded; nothing is sent to the DGX
status(request_id) -> state         # waiting, up, running, saved N, done, stopped, failed
stop_after_save(request_id)         # asks; the homelab's swap does it
fetch(request_id) -> files          # logs, checkpoints, ONNX files with their SHA-256
```

**The adapter never touches the DGX.** The homelab session runs the swaps, the stack's `.env` and
`prepare.sh`; nobody else logs in, runs docker, runs `gpu-mode-swap.sh` or touches the Mac mini's
production socket (the homelab recipe; the `dgx-training-run` skill, "The split"). In the first
version the adapter produces the request, records it, and reads what comes back (the copied logs
folder). The message to the homelab session is relayed by the operator or an agent exactly as
today; the adapter makes it a record. I found no machine interface to the homelab for swaps, so a
call from Mission Control to the homelab is a thing to ask the homelab for, not to build around.

Later adapters are the CPU (the C7 check runs 8 envs x 50 iterations on CPU) and a rented GPU. The
Protocol is the same; the policy about windows differs.

### 6.3 The `learning` library and the model as an object

A small standard-library package, `libs/learning`, in the style of `libs/missions`: data in, data
out, no network, no robot. It holds the record types and their validation, and nothing that runs.

A **model** record is the first-class object:

| Field | What | Source |
| --- | --- | --- |
| id | The ONNX file's SHA-256, whole; the first 8 are the `ctrl` part of the build identity | `learned.py:150`, `runfile/build.py` |
| code | The training project and full commit | The training run's request |
| pool | The scenario pool's manifest hash, and which evaluation manifests it excluded | `lab-scenarios` manifests |
| training run | The request, window, args, seconds per iteration, the checkpoint it came from | The trainer adapter |
| walker | The walking policy's SHA-256 (`ce894d30...` for Pollen's v10) | The task refuses to start without it |
| replay runs | Run keys of the sim replays | Run files |
| eval results | `robotics-evals` run ids per arm, the comparison's delta, interval and collisions | `evh` |
| promotions | Which robot's profile version names it, who, when | Mission Control's profile store |

The record names a model by its files and checksums, never by "the newest run" and never by a raw
checkpoint (RFC-0025 section 3.7). The records are read from, and cross-checked against, the sources
in the right-hand column; the library does not become a second ledger. `robotics-evals` remains
where evaluation results live; the model record holds their ids.

The name has a clash: "model" already means a language model in RFC-0005's build identity
(`model@<alias>`) and RFC-0030's LLM planner. Question 1 asks.

### 6.4 The Observatory's Learning view

Read-only, in the Observatory, because it explains and Mission Control operates (RFC-0023, D1):

- **Learning:** a list of training runs and models: state, task, commit, GPU time, the headline eval
  result, and where each model is promoted.
- **A model page, with lineage:** the chain of section 4 for one model: the pool it was trained on,
  the training run, the checkpoint, the replay runs (each a link to the ordinary run page, where the
  steering signals show when the controller overrode the follower), the eval comparison with its
  interval, and the promotions.
- **A training run page:** the headline curves (reward, episode length, the terminations), a link to
  the run's TensorBoard events for the rest, and the three agreement signals of the skill: curves,
  replay and the ONNX shape.
- **The results join:** `robotics-evals`' ledger already keys a run by its build identity. The model
  page reads the ledger and the comparison by `ctrl@learned@<sha8>`; it does not write there.

Mission Control carries the operating side: the goal library gets train and eval entries, a run
list shows training runs, a request is made and a stop-after-save is asked, and promotion is a
button for the operator only.

### 6.5 What goes where, one line each

- `libs/learning` holds the types and rules.
- Mission Control holds the goal kinds' forms, the trainer adapter, the training run store and the
  operator's actions.
- The Observatory holds the views.
- `robotics-evals` holds the evaluation.
- `libs/runner` holds the scenario tools and the runner.
- The homelab holds the DGX.
- TensorBoard holds the raw curves.

## 7. Safety

These are the rules the proposal must not weaken. None is new; each already holds in the code or the
decisions cited, and the proposal adds the places where it would otherwise be skipped.

- **Promotion is operator only.** Promoting a model means writing a profile version whose
  `plugins.local_controller` names it. An agent has no profile writes (`mcp_server.py`, "No profile
  writes"; `docs/wip/MCP-COVERAGE.md`, the MCP's R7), and the allow-list of the MCP does not carry
  the save or import routes. An agent may propose a promotion, as a record the operator reads. It
  cannot perform one. The record stores who promoted and the evidence it was shown.
- **A learned controller is sim only until R8.** `lab-challenge` refuses `--local-controller
  learned` on a host whose variant is not `sim` (`libs/runner/src/labrunner/challenge.py:173-175`),
  and the plugin's own docstring says the real duck is R8's decision. Promotion to a robot whose
  profile variant is `real` is refused in code until the real duck's safety review (RFC-0025
  section 3.7; RESEARCH-LEARNED-AVOIDANCE R8) has been done and the operator lifts the refusal. This
  is the same shape as RFC-0030's mode 3, which is a rule in code and not a convention.
- **Guards stay above the model.** The reflex, the drop stop, the guardrails' caps, the lease, the
  deadman and STOP sit outside the controller's interface and above it. A model that fails brakes.
  The seam clamps translation to the follower's request. Training the guards into the reward (R7b)
  makes the model careful; it does not remove one.
- **A trainer adapter never touches the DGX directly.** The homelab runs the swaps
  (`/work/agentic-ai-homelab/docs/recipes/robotics-training.md`). We send the commit, task, args and
  a window and wait for the answer. No Mission Control code logs in to the DGX, runs docker there,
  edits the stack's `.env` or touches the production socket.
- **The windows.** The nightly runs at 00:00Z and infra keeps 23:45Z to 03:00Z clear. Production
  must be back by 23:20Z, the operator's margin for the skill; the homelab's recipe says 23:30Z, and
  the earlier time holds. A request that overlaps the nightly or ends after 23:20Z is refused
  by validation, before anything is sent. The operator gives each window; the homelab checks that
  production is idle. Every swap is announced beforehand (RESEARCH-LEARNED-AVOIDANCE, decided
  2026-11-26).
- **Evidence before a word.** "It learned" requires the three signals to agree: curves, replay and
  the
  ONNX shape. "It is better" requires the comparison with its interval and its collision count,
  on at least 10 scenarios per arm and a frozen set the training never saw. The training reward is
  not consulted.
- **An eval is a simulator job.** It runs under the simulator lock, as `sim-run` and
  `challenge-batch` do, and never on a real robot.
- **No second writer for evaluation.** `robotics-evals`' data folder is changed only through `evh`.
  The Learning view reads it.

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
| Long-running or heavy work that would take a core from Mission Control's container | RFC-0030 section 5 | Sweeps, many parallel evaluations, anything beyond a single request at a time |
| Fleet scheduling with a clock of its own | RFC-0030 section 5 | A queue of training runs scheduled across windows, machines or a rented GPU |
| Its own UI that is not a panel of an existing page | RFC-0030 section 5 | The Learning view needs navigation, search and comparison of its own |
| A different owner or safety review cadence | RFC-0030 section 5 | Learning changes weekly; the executor changes with a safety review |
| A model or workload that needs a GPU or a host unlike Mission Control's | RFC-0030 section 5 | The orchestration itself needs a GPU, which today the homelab holds |

These are adapted triggers: the review's table is about the Observatory and the run format, and
RFC-0030's list is about planning. I applied them to learning; the operator may want different ones.
When a trigger fires, the split is a transport change: the library's records become an HTTP
contract, the trainer adapter moves with the app, and Mission Control stays the only process that
can write a robot's profile or take a lease.

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
this, and this does not block it. One step is proposed, after the trainer adapter is proven on the
manual runs:

1. **Now, no code:** record each manual run in the model record's shape, by hand (a file, a table in
   the training guide). M1's table already is one. M2a and M2b are the second and third; their
   results are the evidence for what the record needs.
2. **After M2a and M2b, the read-only slice:** `libs/learning` with the record types, the model
   page and the Learning list in the Observatory, fed by the records of 1. Nothing operates the DGX.
3. **After that, the trainer adapter:** the request and the record, then the status read from the
   copied-back logs. Train and eval goal kinds in Mission Control's library.
4. **Later:** the GPU budget approval (question 4), failure mining as a button, other trainers.

The principle: automate what we have done twice. This is not scheduled against RFC-0025's steps. It
touches the Observatory's `shell.js`, which RFC-0024's review ranks as the part of MVP 2 that will
hurt, so the view's step should follow RFC-0025 step 8's panel split rather than precede it.
Whether it is in or after MVP 2 is question 6.

## 11. Questions for the operator

Each with options and a recommendation. The answer to any can be "none of these".

1. **The name.** The library, the view and the record.
   - A: library `models`, view "Learning".
   - B: library `learning`, view "Learning", record "model".
   - C: a product name, "Lab Bench", for the view and the library.
   - **Recommendation: B.** "Model" already means a language model in RFC-0005 and in RFC-0030's
     planner, and a library called `models` would invite the clash into imports. `learning` matches
     the view. "Lab Bench" names the app of option B, which is not the proposal.
2. **Where the model registry lives.**
   - A: in the platform: records in Mission Control's store, types in `libs/learning`; evaluation
     results stay in `robotics-evals` and the record holds their ids.
   - B: in `robotics-evals`: the model is an evh system and its data folder is the registry.
   - C: MLflow's registry.
   - **Recommendation: A.** Promotion, the lease and the profile are Mission Control's; the model's
     record must sit next to them. B would make a private evaluation repository the home of a fact
     the robots need, and `data/` is changed only through `evh`. C is option C's argument.
3. **Do eval goals run in Mission Control or in `robotics-evals`?**
   - A: Mission Control starts the batch (a goal kind `eval`), under the simulator lock, and hands
     scores to `evh`.
   - B: the batch stays the `challenge-batch` flow; Mission Control and the Observatory read the
     results and show a "requested evaluation" record.
   - C: both, in stages: B now, A when the batch has been run by hand three times.
   - **Recommendation: C.** The batch needs the lock, `lab-challenge`, scoring and `evh`; those
     live in the skill and in `robotics-evals`. A goal kind that wraps them before M2's batches have
     run is automating something done once.
4. **How a GPU budget is approved.**
   - A: each window by the operator, as today.
   - B: a training plan approved once with a GPU-hours budget, as RFC-0030's mode 3 is for a
     mission; each swap still announced.
   - C: autonomous within a budget, no announcement.
   - **Recommendation: A for the first runs, then B after three windows have run through the
     adapter without a manual correction.** C is not recommended while the nightly window is
     someone else's. B must keep the 2026-11-26 decision that each swap is announced.
5. **Promotion rules.**
   - A: operator only, by a named identity, after a comparison with an interval: the learned arm
     beats the rules on `success` without more collisions, at least 10 scenarios per arm, on a set
     training never saw. Sim only until R8.
   - B: automatic when the numbers pass.
   - C: A, plus a second reviewer's note on the record.
   - **Recommendation: A.** It is today's rule written as code. B hands a robot's limits to a
     metric. C adds a reviewer the lab does not have; it can be added when there is a second
     person.
6. **Inside MVP 2, or after it?**
   - A: after M2a and M2b, as a side lane during MVP 2 (the read-only slice only).
   - B: after MVP 2, with RFC-0030's auto mode.
   - C: inside MVP 2, before the navigator split.
   - **Recommendation: A for the read-only slice, B for the trainer adapter.** The read-only slice
     costs the critical path attention and no code on its steps. The adapter needs the second
     and third manual runs and RFC-0025 step 8's panel split.
7. **Does a training run share `goal_runs` or have its own table?**
   - A: its own table, sharing the run states; the run list reads both.
   - B: `goal_runs` gets a `resource` column; `robot` and `target` become nullable.
   - **Recommendation: A.** `goal_runs` is read by the lease, the rehearsal and the group code, all
     robot-shaped. A nullable robot makes every reader check.
8. **The first UI slice.**
   - A: the Learning list and the model page, read-only, in the Observatory, fed by hand-made
     records.
   - B: the train goal's form in Mission Control, with the request block.
   - C: the eval comparison first, on `avoidance_v1`.
   - **Recommendation: A.** It shows what exists, shapes the record before anything operates a GPU,
     and risks nothing. C needs a learned arm that does not exist yet (R5 is the first eval).

## 12. Consequences

- A library `libs/learning` and a row in the boundary checker's tables, as `libs/missions` has;
  `libs-sync` and `LIBS_TESTS` gain it.
- Mission Control gains a trainer adapter Protocol, a training run store and goal kinds `train` and
  `eval`. `goal_runs`, the lease and the robot adapters do not change.
- The Observatory gains a Learning view and a model page. It reads `robotics-evals`'ledger and
  writes
  nothing to it.
- The profile gains no field: `plugins.local_controller` and its model block are RFC-0025's.
  Promotion is the existing save of a profile version, by the operator.
- A model record is a new document with a contract test, like the plan document of RFC-0030.
- Documentation: the training guide's M1 table becomes the first model record's example.

## 13. Not covered

Not built, and not run: nothing here was executed; every reference was read on 2026-11-26.

- **Not verified, from the brief.** The homelab's messages (the request and the "up" and "done"
  replies) are the session's, and I did not read them; I used the recipe and the skill that
  describe them. The session's for-and-against on the options were not available as text and are
  rewritten here. `lab-scenarios pool` is named in the brief and in the research plan's R7a ("writes
  a training pool"); `libs/runner/.../scenarios.py` has `export` and `mine` and no `pool`, so the
  pool is
  today an `export` or a `mine` output, and a `pool` command is planned, not built.
- **Not verified, from the code.** That the homelab offers a machine interface to request a swap
  (I found none; the recipe is run by its session). That a Mission Control process can read the
  homelab's logs folder where it is today (`/work/microduck-nav-runs/` on the workstation, copied
  back by hand). How a TensorBoard link would be served to the operator: a local server, a copy, or
  the homelab's. How the Observatory's server would read a model record: I read the run store's
  header (`apps/observatory/web/shell/runstore.js`) and RFC-0023, not the server's routes. That
  `libs/missions`' wall allows a sibling library to share the run-state vocabulary without an
  import cycle. Whether `libs/learning` should depend on `libs/runfile` for the build identity.
- **Not measured.** The cost of any GPU hour here is the R6 plan's estimate, 6.5 to 10.5 hours for
  the
  whole ladder; the only measured runs are the smoke and M1. M2a and M2b: I found their commands
  (`/work/microduck-nav/docs/M2.md`) and no results; `/work/microduck-nav-runs/` holds M1 and the
  smoke only.
- **Not decided.** The model record's exact fields and its checksum rule (a model's whole record
  edited later would need a new version, as RFC-0030's plan does); how a training run is
  retained and for how long; what a run is called when it is stopped after a save (a `stopped`
  that kept a checkpoint is not a failure); who may cancel a request after the homelab has
  answered; whether a held-out family (R7a) is a field of the pool or of the eval goal.
- **Not covered.** Training on the real robot or from real-home data (RFC-0025 section 5's privacy
  rules apply before any real-home run enters a pool); retraining Pollen's walker, which would
  invalidate every trained controller; recovery skills; higher-level learning from a camera;
  the sim-to-real work of R8, whose safety review comes first; a rented GPU's cost model and
  credentials; the legal reading of NVIDIA's licences for a published comparison (the research
  plan's section 8); a fleet view of several trainers; any approval by flotilla.
- **Out of scope.** Changing the lease, STOP, the real-run key or the guardrails; the
  homelab's stack; the evaluation method (`robotics-evals`' decision).
