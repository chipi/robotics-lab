# The lab from the command line

**Status: provisional.** Written on 2026-11-26 against commit 57633bd. Every command's flags were
read from its `--help`; the commands that need the simulator were not run for this page, so their
output blocks come from earlier runs on disk and say so.

## What this is for

The three web apps (Mission Control, the Observatory, nxt-web) are how you drive a robot and look
at a run. Everything that *produces* a run in bulk, judges a navigator, builds a scenario set or
checks the repository is a command. This page is for the person who wants to experiment from a
terminal:

- start the simulated duck and send it somewhere, once;
- run a numbered challenge on a seed and read the verdict;
- run a batch and score it;
- write the scenario sets that training and evaluation use;
- run the repository's own checks.

You need nothing from this page to use the web apps. You need all of it to repeat an experiment.

## Before you start

- Run commands from the repository root. The runner's commands (`lab-*`) and `simhost` are
  installed into the duck's environment: `make duck-sync` once, then `uv run lab-go ...` from
  `robots/duck`, or call the binary in `robots/duck/.venv/bin/`.
- A run is written under a **data folder** that an installation file names. Do not point
  experiments at your real one. Make a scratch file and set it:

```json
{"installation": 1, "data": "~/scratch/lab/data", "index": "~/scratch/lab/state/index.sqlite",
 "state": "~/scratch/lab/state",
 "robots": {"duck": {"navigator": "127.0.0.1:8061", "gate": "~/.cache/duck-sim/duck-a-gate.sock",
                      "registration": "<repo>/robots/duck/registration.json"}}}
```

```bash
export ROBOTICS_LAB_INSTALLATION=~/scratch/lab/installation.json
```

Unknown keys in that file are errors. Open the same data folder in the Observatory (section 6) to
look at what you made.

## 1. The simulator

**Purpose.** The duck's simulator is Pollen's `duck-sim` (MuJoCo). The lab does not own it: it
borrows it through a *host file*, and `simhost` is the small tool that reads that file and resets or
stops the simulator. Every challenge and navigation run goes through it.

**When you use it.** Once per machine to set up; then only to check the host, or to reset or stop
the simulator by hand. The challenge commands reset it themselves (about 40 s per run).

| Command | What it does |
| --- | --- |
| `scripts/host-setup [--dry-run] [--pollen-dir DIR]` | Make this machine a host: Pollen's two checkouts at the pinned commits, `mapd`, our patch to `duck-sim`, our environments, the host file. Run once; safe to repeat. `--dry-run` prints each step and changes nothing. |
| `scripts/host-check [--host FILE]` | Read-only. One PASS/FAIL line per requirement, then `HOST-CHECK PASS` or `FAIL`. |
| `simhost show` | Print the host file and the sockets it names. |
| `simhost reset [scene]` | The duck at its dock with an empty map (default scene `apartment_backlash`). |
| `simhost down` | Stop the simulator and `mapd`. |

`host-check` on a machine that is set up, run from a fresh checkout that has not been synced yet
(so the last two FAILs are expected, and `make duck-sync` and `make observatory-sync` clear them):

```text
PASS     the host file  — /home/marko/.config/robotics-lab/host.json
PASS     microduck at the pinned commit  — /work/pollen/microduck 094d4bb4
PASS     duck-sim is patched (no sudo on down)
PASS     the simulator environment imports (mujoco, onnxruntime, mjlab_microduck)  — mujoco 3.10.0
FAIL     our environment robots/duck  — no .../robots/duck/.venv/bin/python: make duck-sync
NOT RUN  the simulator's real-time factor  — needs the simulator up; measured by a course run
HOST-CHECK FAIL (15 pass, 2 fail, 1 not run)
```

(Four of the 18 lines are shown.) The real-time factor is checked afterwards: a run whose
`clock.rtf` is under 0.95 has no verdict.

### The sim lock

**One simulator job at a time on a machine, yours or anyone's.** Every reset restarts the simulator,
so a second job would wreck the first. `scripts/sim-lock` is the lock: it runs a command while
holding an exclusive `flock` on one file, waits if someone else holds it, and says who.

```bash
scripts/sim-lock -- make sim-duck ARGS="--only point"
scripts/sim-lock --timeout 600 -- uv run lab-challenge 1 --runs 3
scripts/sim-lock --path          # the lock file's path, and nothing else
```

It exits 75 when the lock was not free within `--timeout` (default 7200 s) and your command did not
run. There is no separate status command. The read-only way to ask "is it free?" is the `sim-run`
preflight, which reads `/proc/locks` and takes nothing:

```text
$ .claude/skills/sim-run/scripts/preflight.py
FAIL  lock  /run/user/1000/robotics-lab-sim.lock is HELD by pid 3424263 (...): its record:
      pid 3424263 lab-challenge 24 --runs 3 --seed 201 ...: wait for it, do not start a second job
PASS  host file  /home/marko/.config/robotics-lab/host.json: kind pollen-duck-sim, robot duck-a, truth_port 7801
PASS  duck-sim sudo patch  applied (the unpatched sudo check is absent)
INFO  simulator  UP: body server listening on 7801; ...
WARN  installation  ROBOTICS_LAB_INSTALLATION is not set: a run reads the operator's own file ...
SIM-PREFLIGHT BUSY
```

That output is from the day this page was written, while another job held the lock. It exits 0
(READY), 1 (NOT READY) or 3 (BUSY). Rules that follow from the lock: never delete the lock file,
never wrap a `make sim-*` target in `flock` (they take the lock themselves), and from a script use
only `duck-sim up, down, drive, status, ctl, stand`. The other `duck-sim` commands ask for sudo,
and with no terminal that locks sudo out (the story is in `docs/wip/DUCK-SIM-FOR-AGENTS.md`).

## 2. Running a navigator once

**Purpose.** The navigator is the robot's own program; the *runner* (`labrunner`) starts it as a
payload, gives it the robot's sockets, watches the simulator's ground truth, and writes the official
run with that truth in it. The navigator never sees the truth; the runner judges by it.

**When you use it.** To see one thing happen: a goal reached, a room explored, one challenge on one
seed. Take the sim lock first, set your scratch installation, and run in the foreground.

| Command | One run of |
| --- | --- |
| `lab-go X Y` | one goal, in the navigator's map, `X Y` metres |
| `lab-explore --minutes N` | the apartment's exploration; `--find KIND` explores until an object (say `fridge`) is found, then goes to it; `--inventory` lists what is where |
| `lab-challenge N --runs 1 --seed S` | challenge `N` on seed `S`, judged |

Common to all three: `--miniview-data DIR` (the data folder the run is written to while it runs;
default `$OBSERVATORY_DATA`), `--out DIR` (the navigator's own files), `--run NAME`, `--robot NAME`,
`--host FILE`. `lab-go` and `lab-explore` start from where the simulator's duck stands: run
`simhost reset` first. `lab-challenge` resets for you and stops the simulator at the end
(`--keep-up` leaves it).

```bash
scripts/sim-lock -- uv run lab-challenge 14 --runs 1 --seed 1 --depth-impairment 1 \
    --miniview-data ~/scratch/lab/data --out ~/scratch/lab/out
```

**Sensor impairments.** By default the simulated depth sensor is perfect. `--depth-impairment SEED`
(on `lab-challenge` and `lab-explore`) gives it the real sensor's imperfections, using the robot
profile's numbers and the seed to draw them; in a batch, run `i` uses `SEED + i`. The run's build id
records it as `tof@nvidia-s1`. A real robot refuses the flag. There is no list of presets to pick
from on the command line.

**The local controller.** The navigator's local controller (the part that steers around what the
sensor sees) is the profile's rules by default. `--local-controller learned --model PATH.onnx`
swaps in a trained network, for the simulator only; `--model` without `learned`, or `learned`
without a model, is a usage error. Change that one setting and keep the seeds and sensor the same
if you want to compare the two.

**Where the run lands.** In `<data>/runs/<robot>/<scene>/<run>/` for the data folder you gave
(for a challenge: `duck/ch14-s1/run-20261126-171049`), and in your `--out` folder as `ticks.jsonl`,
`truth.jsonl` and `result.json`. A challenge ends with a line such as
`CHALLENGE 14: <ok> of <n> passed (<rate>) in <minutes> min`.

Output of an earlier run of that exact command (a batch on 2026-11-26, read from disk, not rerun
for this page): its `result.json`, abridged:

```json
{"challenge": "14", "seed": 1, "scene": "ch14-s1", "right": "reach", "goal": [2.4044, 0.2708],
 "pass": true, "status": "reached", "error_m": 0.146, "min_clearance_m": 0.258, "nearest": "leg3",
 "clock": {"sim_s": 44.06, "wall_s": 44.052, "rtf": 1.0},
 "build": {"ctrl": "rules@1", "tof": "nvidia", "seed": 1, "dirty": false,
           "id": "brain@54defc130582+ctrl@rules@1+walker@ce894d30+sim@0daab160+tof@nvidia-s1"}}
```

The duck walked to within 0.146 m of the goal and never came closer than 0.258 m to a leg of the
chair. The `build.id` names everything that made the run: navigator commit, controller, walking
policy, simulator commit, sensor and seed. A `dirty` build cannot be imported into an evaluation.

## 3. The challenge course

**Purpose.** A challenge is a function from a seed to a generated scene (a room, obstacles, a
goal), in its own frame with the duck at the origin facing +x. The same number and seed always give
the same scene, so a result can be repeated and two navigators can be compared on identical
ground. Numbers are never reused or changed: datasets and runs name them.

**When you use it.** To ask "does this navigator get through narrow doors?" with a pass rate
rather than one anecdote. Run a challenge N times with `--runs`; run `i` uses seed `--seed + i`.

Challenges are in `libs/runner/src/labrunner/challenges.py`. "Right" is what the duck must do:
*reach* the goal, or *refuse* to go (a drop is not a goal).

| No. | Family | Right |
| --- | --- | --- |
| 1 | Straight corridor | reach |
| 2 | Doorway (80, 50 or 42 cm by seed) | reach |
| 3 | A box corner just inside a doorway | reach |
| 4 | A box in the open, its back unseen | reach |
| 5 | U-turn in a 60 cm corridor | reach |
| 6 | Dead-end corridor | reach |
| 7 | Start wedged in a corner | reach |
| 8, 9 | Step down, head-on / approached diagonally | refuse |
| 10 | Walking along a ledge | reach |
| 11 | A narrow passage beside a hole | reach |
| 12 | A table edge with no return | refuse |
| 13 | A low overhang (walk under or go round, by seed) | reach |
| 14 | A thin pole, a chair's legs | reach |
| 15 | A field of small boxes | reach |
| 16 | A threshold to step over | reach |
| 17 | A cable, a rug or a book on the floor | reach |
| 18 | A step up and a step down | reach |
| 19, 20 | A short flight of small steps, up / down | reach |
| 21 | Ten goals in a row, one reset | each within 0.25 m |
| 22 | One room, explored, a drop by the start (5 min) | explore |
| 23 | Two rooms through a door, explored (8 min) | explore |
| 24 | Narrow doorway, off-axis | reach |
| 25 | A dense field of small boxes | reach |
| 26 | A cluster of chairs, their legs | reach |
| 27 | A slalom of posts | reach |
| 28 | A box just behind a doorway | reach |

Challenges 24 to 28 are the harder families added for `avoidance_v2` (section 4).

**Scoring.** Each run is judged against the simulator's truth, not the navigator's belief. The
judge fails a run for a `fall`, a `drop_margin` (too near a drop's edge), `bounds` (outside the
scene) or a `collision`; otherwise the status says why it did not pass (`stalled`, `refused`,
`trapped`, `time`, `missed_goal`). A run whose simulator ran slower than real time (`rtf` under
0.95) has `pass: null` and is not a result.

**A batch.** One `lab-challenge N --runs R --seed S` per challenge, all with the same seeds and
sensor, is a batch; `--out` per arm. To turn a folder of runs into rows you can compare, use the
scorer from the `challenge-batch` skill, which reads only:

```text
$ .claude/skills/challenge-batch/scripts/batch_scores.py /work/microduck-nav-runs/r5/rules_v1 --arm rules --out rules.jsonl
30 scenarios from 30 result.json; success 30/30, collisions 0, falls 0
NOTE  no --dataset: item ids are the scene ids, so the scenario set is NOT frozen; import needs a frozen dataset
wrote 30 rows to rules.jsonl
BATCH-SCORES PASS
```

(From the earlier R5 rules-controller batch on disk.) A pass rate over fewer than about ten scenarios
is a rate, not a comparison; the skill's "Never" list is the rule for what you may claim.

## 4. Scenario sets

**Purpose.** A scenario set is a list of challenge scenes written as plain files: one canonical
JSON per scenario (start, goal, obstacles, limits, sensor seed) and a `manifest.json` with each
file's sha256, the commit it was made from and the command. It lets another program (a trainer, an
evaluator) use our scenes without our simulator. `lab-scenarios` needs no simulator.

**When you use it.** To freeze an evaluation set, to build a training pool, or to turn failures
into new scenarios.

| Command | Makes |
| --- | --- |
| `lab-scenarios export --challenges 4,14 --seeds 1-5 [--depth-impairment SEED\|off] --out DIR` | one file per challenge and seed, and the manifest |
| `lab-scenarios pool --challenges 1,2,3,4,14,15 --seeds 1000-5999 [--exclude-dataset MANIFEST] --out FILE.jsonl` | the training distribution: the same items, one line each, plus `FILE.manifest.json` |
| `lab-scenarios mine --runs DIR --out DIR [--variants N] [--exclude-dataset MANIFEST]` | each failed run becomes the scenario it failed in, with variant starts just before the failure |

```text
$ lab-scenarios export --challenges 14 --seeds 1 --depth-impairment 1 --out scratch/ex
EXPORT: 1 items into scratch/ex
$ ls scratch/ex
manifest.json  thin_legs-s1.json
$ cat scratch/ex/manifest.json
{"command": "lab-scenarios export --challenges 14 ...", "format": "robotics-scenario-set/1",
 "items": [{"challenge": 14, "file": "thin_legs-s1.json", "item_id": "thin_legs-s1", "seed": 1,
            "sha256": "9675d869f71ad..."}], "robotics_lab": {"commit": "57633bd87cfd", "dirty": false}}
```

Floors, drops and steps are not exported, so a challenge with a drop or a step (8 to 12, 16 to 20),
or one that is not a single goal (21 to 23), is refused by `pool`. `--exclude-dataset` keeps an
evaluation set's scenes out of anything used for training; it is applied before anything else.

**The evaluation sets.** They are frozen, which means their file hashes are in the dataset and
nobody edits one (a change is a new set):

- `avoidance_v1`: 30 scenarios, six obstacle families by seeds 1 to 5. The rules controller scores
  30 of 30 on it, so it cannot show a gain; it is kept as a **safety** check (no regression).
- `avoidance_v2`: 40 scenarios, challenges 24 to 28 by seeds 1 to 8. The harder set and the
  **primary** one; the rules controller passed 23 of 40.
- `avoidance_val`: 33 scenarios, used to **select** a checkpoint, never to report.

The datasets, the run ledger and the comparisons live in a private evaluation repository, which
this page does not link. What you can do without it is export a scenario set of your own and score a
batch as in section 3.

## 5. Training

Training a controller does not happen in this repository. [Training the controller](../training/index.md)
teaches the task, the rewards and the DGX flow from zero; the code is in the public
[chipi/microduck-nav](https://github.com/chipi/microduck-nav). What this repository gives it is
the scenario pool (`lab-scenarios pool`), the failures to learn from (`mine`), and the way to try
the result: `--local-controller learned --model PATH.onnx` on a challenge. The `dgx-training-run`
skill is the checklist for asking for a training run.

## 6. Reading a run

**For a person:** open the data folder in the Observatory and pick the run. It shows the duck's
body in 3D, what the robot believed against what was true, and the timeline of every stream.

```bash
make observatory-up OBSERVATORY_DATA=~/scratch/lab/data OBSERVATORY_STATE=~/scratch/lab/state
# http://127.0.0.1:8070/
```

**For an agent**, the repository carries four skills in `.claude/skills/`, each with a preflight, a
list of signals that must agree, and a "Never" list:

| Skill | Use it to | Starts the simulator? |
| --- | --- | --- |
| `robotics-run-read` | say what happened in one run: verdict, build, stops, guards, belief against truth | no |
| `sim-run` | run one job on the simulator under the lock, with the sudo rule and the success checks | yes |
| `challenge-batch` | freeze a set, run one batch per arm, score and compare | yes (via `sim-run`) |
| `dgx-training-run` | ask for a training run and check it afterwards | no |

`robotics-run-read` is also a plain script. On the run from section 2:

```text
$ .claude/skills/robotics-run-read/scripts/run_summary.py /work/microduck-nav-runs/r5/rules_v1/ch14-s1/run-20261126-171049
VERDICT  {"challenge": "14", "scene": "ch14-s1", "seed": 1, "pass": true, "status": "reached", "error_m": 0.146, "min_clearance_m": 0.258, ...}
BUILD    brain@54defc130582+ctrl@rules@1+walker@ce894d30+sim@0daab160+tof@nvidia-s1
TICKS    {"count": 449, ... "requested_applied": {"ticks_with_both": 449, "differ": 0, "max_applied_vx": 0.3}}
STOPS    none recorded
GUARDS   none fired (stopped_by_guardrail, robot_guard absent)
BELIEF   {"samples": 449, "mean_m": 0.017, "max_m": 0.061, ...}
```

(Earlier run, read from disk. `JUDGE` and `EVENTS` lines are omitted.) Read it as: it passed, it was
never told to stop, and its belief of where it was stayed within 6 cm of the truth.

## 7. The checks

`make help` lists every target with a one-line description; it is the default target.

| Target | What it checks | Needs |
| --- | --- | --- |
| `make ci-fast` | lint, the sim-lock and deploy self-tests, the libraries, the NXT, the duck, the Observatory and Mission Control unit tests | no simulator, no robot |
| `make ci` | `ci-fast` plus the pages in headless Chromium, run compatibility, the images, `docs-lint` and `docs-build` | Docker, Chromium |
| `make test-libs`, `test-duck`, `test-observatory`, `test-control` | one project each | its `*-sync` first |
| `make docs-validate` | markdownlint and the strict docs build | `make docs-install` |
| `make sim-duck`, `sim-nxt` | Mission Control on the real simulator (about 10 min and 1 min) | the sim lock; they reset the simulator |

Run `make <target>; echo "MAKE_EXIT=$?"` so an unattended run ends with an exit line. The `sim-*`
targets are not in CI and take the lock themselves.

## What this page does not cover

The NXT and the LEGO robots; the real duck and any hardware; Mission Control's and the Observatory's
own use; `lab-gate`, `lab-nav-server`, the `lab-measure-*` tools and the `duck-*` tools; the
`evh` import and comparison flow (it needs the private evaluation repository); and
the fault-injection test flags of `lab-explore`. The simulator-dependent output blocks here were
not produced by this page's author running them.
