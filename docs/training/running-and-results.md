# 5. Running it and reading the results

!!! abstract "By the end of this page"
    You know the ladder of runs (smoke, M1, M2, M3), what each proves and costs, how a run reaches
    the DGX, how to read its TensorBoard curves, and how a checkpoint becomes a model in the
    navigator and then a number in `robotics-evals`.

Two runs are measured: the smoke test and M1 (2026-11-26; M1 met its milestone, results below).
The numbers marked "plan" are estimates from the R6 plan. M2a (NVIDIA's recipe) and M2b (the same,
matched to our navigator: 10 Hz policy, no sidestep) follow the same day.

## The ladder

Each rung proves something the one before cannot, and costs more.

| Run | Task | Envs x iterations | What it proves | Cost (plan) |
| --- | --- | --- | --- | --- |
| Smoke | one wall | 64 x 20 | The command starts and the first checkpoint lands | Seconds. Measured: 0.64 s per iteration |
| CPU check C7 | full | 8 x 50 | 50 iterations run finite, checkpoint and ONNX are valid | 2.6 s per iteration on CPU (`CHECKS.md:241-253`) |
| **M1** | `Mjlab-Nav-OneWall-MicroDuck` | 4096 x 200 | The whole chain learns something: progress up, collisions down, the policy stops before the wall | 0.2 to 0.3 h training; about 0.5 h of DGX window with the swaps |
| **M2** | `Mjlab-Nav-MicroDuck` (all layouts, impairments) | 4096 x 1500 | It steers: success and collision rate in R5's scenarios | 1.3 to 1.9 h; about 2.1 h window |
| **M3** | the same | 4096 x 3000 | NVIDIA's second recipe; picks the recipe | 2.7 to 3.8 h; about 4 h window |
| Tuning | the same | up to two reruns | Reward weights, the speed floor, the walker pairing | 2 to 4 h |

Total in the plan: 6.5 to 10.5 GPU hours, five or six swaps, 8 to 12 hours of the DGX's production
mode being down (R6 plan, section 4). Every row after the smoke is an estimate. They rest on a guess
of 3.2 to 4.5 s per iteration at 4096 envs, which is not measured. The only measured comparison is
Pollen's walking task: 2.78 s per iteration at 4096 envs, 5.1 GB of GPU memory (homelab recipe,
"Measured").

Each iteration is 4096 x 24 = 98,304 steps, 33 robot-minutes at 50 Hz. In total:

| Run | Steps | Robot time |
| --- | --- | --- |
| M1 | 19.7 million | 4.5 days |
| M2 | 147 million | 34 days |
| M3 | 295 million | 68 days |

(My arithmetic.) These are the days the real duck would have to walk into walls. M1 is cheap
because it is short: 200 iterations.

M1's definition of done (`M1.md:101-123`): all three of

1. `Episode_Reward/progress` rises over the run;
2. `Episode_Termination/obstacle_collision` falls;
3. the replayed policy stops before the wall (below).

Arrival is not part of M1, because the goal is 2.6 m ahead, behind a wall, and the walker is too
slow to get there in 20 s: `goal_arrival` stays 0.

## The DGX flow

The DGX is shared and runs the operator's production models, so a training run is a "GPU mode": the
production models go down and the trainer comes up. The homelab runs the swap. What we send, per the
operator's description of the split, is the commit, the task and the arguments. The homelab's recipe
is `agentic-ai-homelab/docs/recipes/robotics-training.md`; this page summarises its parts that
matter to us.

```text
 us:      microduck-nav commit, task id, args, a window     (a request, then wait for the go)
              |
 homelab: prepare.sh microduck-nav <REF>        checks out and pins the commit (required: no default pin)
          .env: ROBOTICS_PROJECT=microduck-nav
                ROBOTICS_TASK=Mjlab-Nav-OneWall-MicroDuck
                ROBOTICS_TRAIN_ARGS="--agent.max-iterations 200 --agent.save-interval 50"
                MICRODUCK_WALKER_ONNX=/cache/assets/walker-seed-v10/velstand.onnx
          gpu-mode-swap.sh robotics         production models down, container `robotics-train` up
              |
 trainer: uv run train <task> --env.scene.num-envs 4096 ...    logger: tensorboard
          logs/rsl_rl/microduck_nav_one_wall/<timestamp>/    checkpoints, ONNX files, TensorBoard events
              |
 homelab: gpu-mode-swap.sh prod             trainer stopped, production back (about 6 min)
```

Facts from the recipe that shape a request:

- **A window.** Production serves the Close Listening pipeline. The nightly runs at 00:00Z and
  23:45Z to 03:00Z is kept clear; production must be back by 23:30Z. Swapping in takes about 1
  minute; swapping back, 6 min 18 s. The operator grants each window.
- **Always set `--agent.save-interval`.** `rsl_rl` does not save when a run is stopped; the first
  Pollen run kept only `model_0`. Stop only just after a save.
- **Always `--agent.logger tensorboard`.** The default is Weights & Biases, which stops at once
  without a key. The stack passes it (`ROBOTICS_LOGGER`), and `M1.md:93` repeats it.
- **The walker file.** The task refuses to start without it (`action.py:59-62`). Its SHA-256 should
  begin `ce894d30`; the run's record should say which file it was.
- **The run is bounded** by `ROBOTICS_MAX_RUNTIME` (GNU `timeout` syntax: `210m`, not `3h30m`).

The exact words the operator and the homelab use for this hand-off were not specified to me. The
three-item message above is my suggestion, not an agreed format.

The recipe's example spells a flag `--agent.max_iterations` and `M1.md` spells it
`--agent.max-iterations`. I did not check that the trainer's argument parser accepts both. Use
`M1.md`'s spelling, which was tested on CPU (`tests/test_m1_dry_run.py`).

## Reading TensorBoard

Open the `events` file in the run's folder with TensorBoard (`microduck-nav` installs it). The names
below are the ones the code writes (`rsl_rl utils/logger.py:157-208`, mjlab's managers).

| Tag | What it is | Healthy |
| --- | --- | --- |
| `Train/mean_reward` | Mean total reward of recently finished episodes | Starts very negative, then rises |
| `Train/mean_episode_length` | Mean length of finished episodes, in steps (1000 = 20 s) | Rises as collisions fall |
| `Episode_Reward/progress` and the 7 other terms | That term's per-second rate, averaged over recently reset envs ([page 4](rewards.md)) | `progress` up; `approach` less negative |
| `Episode_Termination/<term>` | Count of envs that ended by this cause, per reset batch | `obstacle_collision` down |
| `Policy/mean_std` | Mean spread of the action distribution | Slowly down from about 0.48 |
| `Loss/value` | The critic's error | High and falling; spikes when behaviour changes |
| `Loss/surrogate` | The clipped policy loss | Hovers near 0; advantages are normalised |
| `Loss/entropy` | Policy entropy (not optimised here: coefficient 0) | Slowly down |
| `Loss/learning_rate` | Learning rate | Flat at 3e-4 (fixed schedule) |
| `Perf/total_fps`, `Perf/collection_time`, `Perf/learning_time` | Speed | Steady. Collection dominates (C7: 2.53 s of 2.63 s on CPU) |

The meaning of the key curves:

- **Reward** is the headline but the least informative. It moves for many reasons.
- **Episode length** is a cheap and honest curve: if collisions fall, it rises toward 1000. Alone it
  cannot tell a duck that walks safely from one that stands (both reach 1000).
- **Terminations**: `obstacle_collision` should fall; `fell_over` should stay near 0 (the
  controller should not make the walker fall); `time_out` is the good ending; `field_boundary` and
  `nan_state` should be about 0. These are counts per reset batch, not shares
  (`termination_manager.py:94-97`), so only trends are safe to read.
- **Action std** (`Policy/mean_std`) is how random the policy still is. It should decrease as the
  policy gains confidence. Too quick a fall to near 0 while reward is flat means it committed to
  a poor behaviour; a std that grows means instability.
- **Value loss** measures how well the critic predicts. A critic that is far off makes the actor's
  updates noisy.

### What an unhealthy run looks like

This is general RL practice applied to our curves; none of it has been seen on our runs yet.

| What you see | What it probably is |
| --- | --- |
| Reward flat from iteration 0 for hundreds of iterations | The task is too hard, a weight is off, or the walker floor is violated (requests below 0.2 m/s) |
| Episode length 1000, `progress` near 0 | A standing policy ([page 4](rewards.md)) |
| Reward rises then collapses | Learning rate too high, or the policy found a hole in the reward |
| `Policy/mean_std` falls to near 0 quickly | Premature convergence; no more exploration |
| `Loss/value` explodes, or any value becomes NaN | Stop. The C7 check requires every logged scalar to be finite |
| `fell_over` climbing | The controller's commands destabilise the walker; look at the slew and the residual limits |
| `Perf/total_fps` falls mid-run | Another process on the GPU, or contacts exploding (`nconmax`, `env_cfg.py:148-149`) |

### The smoke run, annotated

The numbers the operator reported for 64 envs x 20 iterations (iteration 19). I did not find the
log; they come from the operator's message.

| Number | Value | What it says |
| --- | --- | --- |
| `Train/mean_reward` | -37.26 | A random policy. Half the episodes ended in a -30 penalty and the rest is mostly approach risk |
| `Train/mean_episode_length` | 257.85 | 5.2 s on average: most episodes ended early |
| `Policy/mean_std` | 0.41 | Close to the initial spread of about 0.48 ([page 2](ppo.md)) |
| `time_out` | 0.50 | See the note below |
| `obstacle_collision` | 0.50 | A count, not a share |
| `fell_over` | 0 | The walker is stable under the residual |
| Time per iteration | 0.64 s | 64 x 24 = 1,536 steps in 0.64 s, about 2,400 steps per second. CPU (C7) was 75 |

A note on `time_out` = 0.50. An episode times out after 1000 steps, and in 20 iterations of 24 steps
an environment takes only 480. I cannot explain a time-out count of 0.50 by that logic. Possible
explanations, none checked: the smoke ran a different build or episode length, or the logged
numbers are not what I read them to be. **Ask what task and commit the smoke used and read the
raw event file.**

Twenty iterations of 64 environments is 30,720 steps. It says the pipeline runs; it says nothing
about whether it learns.

### To be filled in: M1's actual numbers

!!! warning "Not measured yet"
    Nothing in the table below has been measured. Fill it when the M1 run (4096 envs x 200
    iterations) is done, and say where its logs are.

| Item | Value |
| --- | --- |
| Date and window | 2026-11-26, 15:55:47Z to about 16:12Z on the DGX (GB10); the homelab ran the swap |
| `microduck-nav` commit | `b5a9fa9` (CUDA torch on aarch64; mjviser 0.0.14, so no second mujoco) |
| Task and arguments | `Mjlab-Nav-OneWall-MicroDuck`, 4096 envs, `--agent.max-iterations 200 --agent.save-interval 50 --agent.logger tensorboard` |
| Walker file SHA-256 | `ce894d30b3343036...63e0a` (checked by the homelab on copy) |
| Seconds per iteration, GPU memory | 4.76 s at the end (the plan guessed 3.2 to 4.5); 200 iterations in 15 min 42 s; memory not recorded |
| `Train/mean_reward`, first and last | 0.09, then 4.94 |
| `Train/mean_episode_length`, first and last | 11.06, then 982.75 steps (of 1000: the ducks stopped falling into the wall and ran to the time limit) |
| `Episode_Reward/progress`, first and last | mean 0.20 in the first quarter, 0.35 in the last (rose) |
| `Episode_Termination/obstacle_collision`, first and last | mean 0.74 in the first quarter, 0.16 in the last (fell) |
| `Policy/mean_std`, first and last | 0.48, then 0.33 (the policy grew more certain) |
| Replay: environments stopped before the wall, of 16 | 13 (81 %), 0 collisions, 0 falls, mean final clearance 0.24 m |
| Checkpoint and ONNX SHA-256 | `model_199.pt` `391a28403735ecee...`, `model_199.onnx` `3ff681e268384f31...` |
| Where the logs are | `/work/microduck-nav-runs/m1/2026-11-26_15-55-36/` (checkpoints, events, params) and `m1-2026-11-26T1555Z.log`, on the workstation |
| Conclusion | Met, narrowly: both curves moved the right way, the ONNX has the right shape, 81 % stopped in replay. `goal_arrival` stayed 0, as expected (the 2.6 m goal is out of reach in an episode) |

## Checkpoints and the ONNX

`save_interval` is 100 in the default config (`rl_cfg.py:43`) and `M1.md` sets 50. Each save writes
`model_N.pt` (weights, optimiser state) and, beside it, `model_N.onnx`
(`rl_cfg.py:51-59`):

- the actor only, as a function from `(1, 1343)` to `(1, 3)`;
- the observation normaliser baked inside, so the navigator sends raw numbers;
- the deterministic output: the Beta mean, with the brake guard ([page 2](ppo.md));
- tested equal to the torch model to 1.75e-7 on random inputs (`CHECKS.md:138-143`).

If the export fails, training goes on with a warning (`rl_cfg.py:58-59`): check that every
checkpoint you want has its `.onnx`.

## The replay check

```bash
uv run python -m microduck_nav.replay logs/rsl_rl/microduck_nav_one_wall/<timestamp>/model_199.pt \
    --num-envs 16 --steps 600
```

The replay loads the ONNX, the file that deploys, and runs it in the task's play config: 16 envs,
the duck facing +x, no pushes. An environment counts as "stopped before the wall" if
(`M1.md:116-120`,
`replay.py` constants):

- no obstacle contact over 0.1 N and no fall;
- it closed at least 0.25 m of its initial gap to the wall;
- its speed over the last 2 s is below 0.03 m/s.

M1 is met when at least 80 % do; the exit code is 0 and the last line is a JSON summary. These
thresholds are this repository's choice, not NVIDIA's or the plan's. The replay is deterministic
(the Beta mean), unlike the training rollouts, so a policy can look better in the replay than in the
training curves.

## Into the navigator, through the slot

A checkpoint's `.onnx` is the model file for `learned@<sha8>`. In the navigator it is selected by a
run option, `local_controller={"name": "learned", "model": <path>}` (`nav/run.py:206-209, :236-237`;
`plugins/__init__.py:38-45`). I did not trace the command-line or profile route to set it.

What happens next, in code:

1. The plugin loads the file, computes its SHA-256 and names itself `learned@<first 8 hex>`
   (`plugins/learned.py`). It checks that the model takes one 1343-wide input and gives one
   3-wide output.
2. Each navigator tick it builds the 1343 numbers from what the navigator holds (state, the last
   depth frames with their ages, the request, the applied command), runs the ONNX, and applies the
   residual with the same limits, speed cap, slew and stale stop as training.
3. It returns the adjusted command, and the guards and the cap act on it as on any command.
4. The run's start record names the controller and its model file; each tick records the
   requested, the controller's and the applied command (`nav/run.py:303, :359-372`).
5. A non-finite input or output gives the brake. The plugin refuses any robot that is not the
   simulator.

The inputs are built differently from training, because the navigator runs at 10 Hz and the model
was trained at 50 Hz. That gap is the first open question ([page 7](glossary-and-next.md)).

## Then R5, in robotics-evals

A model is not good until the comparison says so. `/work/robotics-evals` is the private
repository for that, on eval-harness 0.8.1.

- **Frozen scenarios.** `avoidance_v1` is the first scenario set: 30 scenarios, 6 obstacle families
  x seeds 1 to 5 (`robotics-evals` commit `b043443`). Each is one canonical JSON file with start,
  goal, obstacles, limits and the sensor impairment's seed. The set never changes once frozen.
- **Arms.** The rules alone; the learned controller; the learned controller with the rules as
  guard. Each run names its build in one string: `brain@<commit>+ctrl@<local controller>+
  walker@<policy sha 8>+sim@<simulator commit 8>+tof@<impairment preset>-s<seed>`
  (`robotics-evals docs/EVAL-HARNESS-0.8.1.md`, "Our build identity"). The `ctrl` part is
  `learned@<8 of the model's sha256>`, so a result names the exact model.
- **Scores.** One row per scenario per arm: success, collisions, minimum clearance, time, stops,
  falls. They go in with `evh import-run`.
- **The comparison.** `evh comparison-show` pairs the arms by scenario: a paired test, a difference,
  a 95 % interval (none at 5 items or fewer, exact p up to 30 items). The primary metric is
  `success`; collisions is a safety limit; the rest is descriptive.
- **The verdict.** If the learned arm does not beat the rules on `success` without more collisions,
  it does not ship. The training reward is not consulted.

The state at the time of writing: the scenario set `avoidance_v1` is frozen, no learned arm has run
(no
model exists yet), and the ledger holds the existing navigator runs. The first evaluation is R5.

Next: [opportunities](opportunities.md).
