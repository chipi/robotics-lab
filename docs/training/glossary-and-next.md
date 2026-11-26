# 7. Glossary and where to continue

## Glossary

Terms in the order you would meet them. The page that explains each in full is in brackets.

### Reinforcement learning ([page 1](reinforcement-learning.md))

| Term | One line |
| --- | --- |
| Agent | The decision maker: here the 1343-to-3 network |
| Environment | The world that answers: here the simulated duck, obstacles and physics |
| Observation | What the agent is told at one step (1343 numbers) |
| Action | What it outputs (3 residuals in [-1, 1]) |
| Reward | One number per step, the weighted sum of eight terms |
| Step | One control tick: 0.02 s, 50 Hz |
| Episode | One attempt: up to 20 s, 1000 steps |
| Policy | The map from observation to a distribution over actions |
| Return | The discounted sum of future rewards |
| Discount (gamma) | How much a reward counts per step of distance: 0.998, a horizon of about 500 steps (10 s) |
| Value | The return expected from a state |
| Advantage | How much better an action was than the value predicted |
| Termination | An episode that ends in failure: the future is lost |
| Truncation (time-out) | An episode that is cut: the future is credited from the critic |
| Domain randomisation | Making the simulator vary on purpose so the policy does not depend on one version of it |
| Sim-to-real gap | The difference between the simulator and the real robot |
| Impairment | A deliberate fault in the simulated sensor (noise, dropout, delay, mount) |
| Reward hacking | A policy finding a high score by a route you did not intend |
| Curriculum | Training on easy cases first, then harder ones |

### PPO ([page 2](ppo.md))

| Term | One line |
| --- | --- |
| Policy gradient | Nudge weights to make good actions likelier |
| Actor | The policy network; the only part deployed |
| Critic | The value network; used only in training |
| Asymmetric actor-critic | A critic that sees more than the actor (the true obstacle clearances) |
| TD error | `r + gamma V(next) - V(now)`: the one-step surprise |
| GAE (lambda) | A blend of one-step and full-return advantages; lambda 0.95 looks about 19 steps ahead |
| Rollout | The experience collected between updates: 24 steps from each of 4096 envs |
| Iteration | One rollout plus one update (5 epochs x 4 minibatches) |
| Epoch, minibatch | A pass over the batch; a slice of the batch for one gradient step |
| Ratio | New policy's probability of an action over the old one's |
| Clip (eps = 0.2) | The limit on how far one update may move the ratio |
| Entropy | A measure of the policy's randomness; its bonus is 0 here |
| KL divergence | A measure of how far two distributions are apart; inert in our config |
| Observation normalisation | Rescaling each input by running mean and std, inside the model |
| Beta distribution | A distribution on (0, 1); ours is mapped to [-1, 1] so actions cannot leave range |
| Softplus | A smooth positive function; with +1 it keeps alpha and beta at or above 1 |
| Brake guard | The exported model's rule: a collapsed forward head or any non-finite logit gives a stop |

### Our task and the stack ([page 3](the-task.md), [page 5](running-and-results.md))

| Term | One line |
| --- | --- |
| Local controller | The layer between the follower and the guards that may steer around obstacles |
| `rules@1` | The default controller: returns the follower's command unchanged |
| `learned@<sha8>` | The ONNX controller, named by the first 8 hex digits of its file's SHA-256 |
| The seam | The local-controller slot in the navigator ([RFC-0025](../rfc/RFC-0025-mvp1-to-mvp2.md) section 3.7) |
| Guards | Cliff stop, pace, reflex, stuck stop, cap, STOP: they sit above the controller |
| Request | The follower's command (or, in training, the joystick-like command to the destination) |
| Residual | A correction added to the request, in [-1, 1] times the limits (0.35, 0.12, 0.75) |
| Slew | The cap on how fast the command may change: (1, 1, 3) per second |
| Stale stop | The command goes to zero if the newest depth frame is older than 0.25 s |
| Walker | Pollen's frozen policy turning a velocity command into joint targets (61 to 14) |
| ToF | Time-of-flight depth sensor: 8x8 = 64 zones, 45 degrees, 0.12 to 4 m, about 15 Hz |
| Zone | One of the 64 depth cells |
| Layout | A family of obstacle arrangements; ten exist, `scattered` is 65 % of the mix |
| mjlab | The training framework on MuJoCo Warp that runs the environment |
| MuJoCo Warp | The GPU version of the MuJoCo physics engine |
| `rsl_rl` | The library with the PPO implementation |
| Checkpoint | A saved set of weights, `model_N.pt` |
| ONNX | The portable model file; `model_N.onnx` is the actor, `(1, 1343)` to `(1, 3)` |
| TensorBoard | The viewer for a run's curves |
| Replay | A check that runs the exported ONNX in the task and tests whether it stops before the wall |

### Work items

| Item | Meaning |
| --- | --- |
| R1 to R8 | The research plan's activities, [RESEARCH-LEARNED-AVOIDANCE.md](../wip/RESEARCH-LEARNED-AVOIDANCE.md) |
| R5 | The first evaluation: rules, learned, learned under the rules' guard on frozen scenarios |
| R6 | Training the controller ourselves; [the plan](../wip/RESEARCH-R6-PLAN.md) |
| R7a to R7e | Our own variant, in five parts ([page 6](opportunities.md)) |
| R8 | The real duck |
| C1 to C7 | The CPU checks of the training code, `microduck-nav docs/CHECKS.md` |
| M1, M2, M3 | The GPU milestones: one wall, the full task, NVIDIA's second recipe |
| S1 to S5, E1 to E5 | Agent skills research; evaluation infrastructure (same plan) |

## Open questions

Each is stated with what is known and what it would take to close. None is settled here.

### 1. Is the navigator's input the training input?

Largely yes, after the 2026-11-26 parity work: five constructed states give the same 1343 numbers
from the training code and from `learned.py`, to 1e-6
([RESEARCH-R4-OBS-PARITY.md](../wip/RESEARCH-R4-OBS-PARITY.md)). That note found and fixed three
mismatches (radial against axial ranges, the history spacing, joint velocities across a pause).

What the note says still does not match:

- **No lateral command.** The duck's command is (vx, vyaw). The model's sideways residual is
  computed and dropped, and the applied lateral it reads is 0. A model that learned to side-step
  loses that skill.
- **Age is arrival, not capture**, so the navigator's ages are shorter by the sensor's transport
  delay (up to 67 ms in training).
- **No training noise** in the deployment's inputs beyond what the real or simulated sensor brings:
  the model was trained to tolerate it.
- **The zone grid.** A model trained on `mixed` also saw NVIDIA's pinhole grid on half its
  episodes, which our simulated duck never emits.

And one I add, from the code: the training request is a clean, smooth function of the destination
(`commands.py:121-126`), and our follower's command is not. Whether that matters is untested.

### 2. 50 Hz or 10 Hz?

The model was trained at a 50 Hz step. The navigator ticks at 10 Hz (`run.TICK_S`, 0.1 s;
`nav/run.py:43`). So the model is asked five times less often, its action is held five times longer,
and the previous action and applied command it reads are 0.1 s old. The history is rebuilt at
0.02 s from the frames the navigator keeps, and the slew works at the same rate over time. The
parity note's options: run the learned controller on its own 50 Hz loop, or accept the slower loop
and check, in R4 and R5, that avoidance does not degrade. Which is open; a third option is to
train at a rate that matches (not discussed in the sources; my suggestion).

### 3. A model failure: brake, or the follower's command?

The sources disagree.

- RFC-0025 section 3.7 says a failing model "returns the follower's command, and the run records it
  as an anomaly. Whether to stop instead is for the first learned arm's evidence (R5)".
- The code, `Learned.command` in `plugins/learned.py`, catches any exception and returns the
  **brake**: the residual (-1, 0, 0) through the limits and slew, or a plain stop when the inputs
  themselves are not numbers. Its docstring says the same ("the answer is the brake").

The code is the safer of the two and matches the exported model's own guard. But the RFC calls the
other behaviour the design, so one of them is wrong. Which to keep is the operator's call; I have
not changed either.

### 4. What did the smoke run actually run?

The smoke's `time_out` of 0.50 cannot come from the 20 s limit in 20 iterations of 24 steps
(480 steps). Either it was a different build, or the counter does not mean what I read
([page 5](running-and-results.md)). The raw event file will say. Also: `microduck-nav`'s README and
`M1.md` still say that nothing has run on a GPU; the smoke has.

### 5. Does 0.28 m/s of request matter?

The goal at 2.6 m arrives in 20 s only for requests of about 0.28 m/s or more, perhaps half of the
draws. Is that the right training range for M2, or should the goal distance, the episode length or
the speed range change? `M1.md:122-123` says 20 s covers "about 1 to 2 m"; by the walker table
(46 % of 0.2 to 0.35 m/s) it is about 1.8 to 3.2 m. My arithmetic, not measured on a GPU run.

### 6. The mount and the grid

Pollen's `tof` site looks level at 0.249 m; NVIDIA's looks 20 degrees down from 0.22 m
(`CHECKS.md:226-227`). The nominal pitch is a config field, not tuned. A level sensor sees the floor
only far out; a down-looking one sees the floor near the duck and the drops. Which the real duck
has,
and what the training should assume, is open. Also open: the `mixed` grid default
(`CHECKS.md:66-69`).

### 7. The walker's cause

Why does Pollen's walker give 46 % and not walk below 0.2? Unknown
([opportunities](opportunities.md)).

### 8. Prop heights and the missing memory

The heights of three props are assumed; the policy has no memory beyond 0.2 s. Both could matter for
R5's door frames and chair legs; neither has been tested.

## Where to continue

In this order, if you are picking this up again:

1. Get M1 running and fill in the table on [page 5](running-and-results.md). Everything else rests
   on
   the chain learning anything.
2. Read the per-term curves of that run next to [page 4](rewards.md). Ask: is it standing, or
   steering?
3. Settle open questions 2 and 3 above before M2, because both change what is trained or what is
   compared.
4. Decide about the walker ([opportunities](opportunities.md)) before spending on M2 and M3.
5. Build R5's comparison in `robotics-evals` (`avoidance_v1`, three arms) so that the first learned
   model has somewhere to be judged.

### Sources, by topic

- The plan: [RESEARCH-LEARNED-AVOIDANCE.md](../wip/RESEARCH-LEARNED-AVOIDANCE.md) (R and S and E
  tracks), [RESEARCH-R1-R2.md](../wip/RESEARCH-R1-R2.md) (NVIDIA's controller and our sensor),
  [RESEARCH-R6-PLAN.md](../wip/RESEARCH-R6-PLAN.md) (M1, M2, M3, GPU hours),
  [RESEARCH-R4-OBS-PARITY.md](../wip/RESEARCH-R4-OBS-PARITY.md) (the input check),
  [RESEARCH-S1-S4.md](../wip/RESEARCH-S1-S4.md).
- The seam: [RFC-0025](../rfc/RFC-0025-mvp1-to-mvp2.md) section 3.7, "The local-controller seam".
- Pollen's walker and the DGX: [MICRODUCK.md](../wip/MICRODUCK.md).
- The challenge course: [RFC-0008](../rfc/RFC-0008-challenge-course.md).
- The code: [chipi/microduck-nav](https://github.com/chipi/microduck-nav) (`README.md`,
  `docs/CHECKS.md`, `docs/M1.md`, `src/microduck_nav/`), and
  [robots/duck/src/duck_lab/plugins](https://github.com/chipi/robotics-lab/tree/main/robots/duck/src/duck_lab/plugins)
  (`learned.py`, `rules.py`).
- The DGX recipe: `agentic-ai-homelab/docs/recipes/robotics-training.md`, in the homelab repository.
- Evaluation: `robotics-evals` (private): `README.md`, `docs/EVAL-HARNESS-0.8.1.md`,
  `docs/DATASET-SPEC.md`.
