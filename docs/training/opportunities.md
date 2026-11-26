# 6. Opportunities

!!! abstract "By the end of this page"
    You know what each next step is, why it matters, what it needs, what it costs, and what must
    come
    before it. The operator's words on 2026-11-26: "we'll definitely be doing all of these". This
    page
    is the map, not a schedule: no item here has a date. R1 to R3, R4's input check and R6's CPU
    checks are done; no training run has finished.

## The map

```text
 M1 (plumbing) --> M2 (steers) --> R5 (beats the rules? in simulation)
                                     |
          +--------------------------+------------------------+
          v                          v                        v
   tuning, curriculum,        R7a-e: our own variant     R8: the real duck, with measured
   more envs, longer runs     (our families, guards in   sensor faults, under a safety review
                               the loop, failure mining,         ^
                               Pollen's apartment, t-s)        |
                                                                |
 retraining the walker  ---- (invalidates the trained controller: train it again)
 recovery skills            -- independent track, on Pollen's training code
 higher-level learning      -- independent track, supervised and vision, not RL
```

| Opportunity | Cost (rough) | Needs first |
| --- | --- | --- |
| Curriculum, more envs, longer runs | M3 2.7 to 3.8 GPU h; more for more envs | M2's curves |
| R7a-e, our own variant | Ports of our families, a guards-in-the-loop reward, failure mining; M2-size runs of 1.3 to 1.9 h each | M2 (M2b's code) and R5's failure list; decided to run before MVP 2 |
| R8, sim-to-real | Hardware sessions with the operator; one retrain | The real duck, a safety review, R5's evidence |
| Retraining the walker | About 3 h per run on the DGX (Pollen's walking task) | Pollen's `microduck_rl`; then retrain the controller |
| Recovery skills | Unknown; the reference is about 3 h per run | Fall handling in the navigator; Pollen's tasks |
| Higher-level learning | Unknown; no design yet | A camera, recorded data, the semantic map |

## R7: our own variant

**What.** A controller trained on our world instead of NVIDIA's. On 2026-11-26 the operator split R7
into five parts and decided that all five run before MVP 2
(`RESEARCH-LEARNED-AVOIDANCE.md`, section 4). Our edge, the plan says, is owning the whole loop:
navigator, guards, challenge course, judges and the evaluation, not compute. Each part is
judged against "M2b" (the plan's name for NVIDIA's recipe, deploy-matched; not defined elsewhere in
the docs I read) on `avoidance_v1`, which training never sees.

| Part | What | In training terms |
| --- | --- | --- |
| R7a | Our challenge families as the training distribution. `lab-scenarios` writes a training pool (seeds disjoint from evaluation), microduck-nav loads it by file, one family is held out to test generalisation | New layouts: replaces or joins `layouts.py`'s ten families ([page 3](the-task.md)) |
| R7b | Our guards in the loop. The reflex and the cliff stop run inside training, and each intervention costs reward, so the controller steers before a guard must fire | A new reward term, and the guards' logic in the environment: the controller learns to be careful because the safety layer above it is part of its world |
| R7c | Failure mining. Failed runs (judge verdicts, stops, anomalies) become training scenarios, plus start poses just before the failure; evaluation items are excluded by manifest | The training distribution is aimed at what the rules and earlier models got wrong |
| R7d | Train in an apartment: Pollen's simulated 6-room apartment as a static training scene, start and goal pairs through its doorways | The survey (done): about 1 to 2 weeks |
| R7e | Teacher and student: a teacher with the true obstacle map, a student with the 64 zones only, trained to imitate | Not PPO on the student: the student is trained by imitation (supervised), a different method from this guide's |

Two things from earlier pages meet here:

- R7b is the answer to a design tension. The controller never has the last word on safety (guards
  above it), but a guard that fires is a hard stop that wastes the duck's time. If a guard's firing
  costs reward during training, the controller learns to steer early so that the guard is rarely
  needed. It is also the reason the guards' behaviour must exist in the training environment, not
  only in the navigator.
- The weights and layouts are the ones in this guide: `REWARD_WEIGHTS` (`env_cfg.py:46-55`), the
  slots (`obstacles.py:47-54`, eight) and the weights (`layouts.py:31-41`). Changing a weight is a
  line; a new term is a function in `rewards.py` plus a test; a new shape is a new slot.

The operator's note also mentioned **the camera**. It is not among R7a-e. The duck has a head
camera, and a controller that sees colour and shape could tell a chair leg from a wall or a rug from
a drop, which an 8x8 depth grid cannot. It would be the largest change: a visual network is far
bigger than a 128 x 128 one, and rendering images for 4096 envs on the GPU is a cost and a
capability I have not verified for mjlab. Treat it as research.

**Why.** NVIDIA's recipe is a recipe for their world. R5 measures whether it is enough for ours; R7
is
how we improve where it is not.

**Needs.** M2 working (M2b's code is R7a's dependency). R5's failure list. A frozen scenario set for
evaluation (`avoidance_v1` exists; 30 scenarios).

**Cost.** Code: ports in the style of the C6 work (the whole original port was about 2,240 lines;
layouts 450 and rewards 400 of them: R6 plan section 1.2, an estimate). GPU: M2-size runs, 1.3 to
1.9 h each, and the R6 plan budgets only two tuning reruns, 2 to 4 h, which five parts will exceed:
the budget has to be reopened.

**Dependency.** M2b, R5. The plan's section 6 still says "After MVP 2: R7, if R5 and R6 justify it";
the operator's later decision (section 4) says all five before MVP 2. The decision is the newer.

## R8: sim-to-real, with measured sensor faults

**What.** Put the controller on the real duck, and replace NVIDIA's guesses about the sensor with
our
own measurements.

1. **Measure.** Record the real ToF over our floors and over a real edge: its noise, bias, invalid
   rate, floor blanking, delay. The scripts for measuring on the real duck are in
   [REAL-DUCK-MEASURE.md](../wip/REAL-DUCK-MEASURE.md).
2. **Put the numbers in.** The impairments are one dataclass, `ToFRandomization`
   (`impairments.py:20-57`); each field is a range or a probability. Replace NVIDIA's priors by the
   measured ones. There is also a decision pending on floor zones: failed floor zones keep counting
   as a drop on the real sensor, because a real edge also gives no valid return; R8's record decides
   whether a drop needs several failed zones or frames (`RESEARCH-LEARNED-AVOIDANCE.md`, section 1).
3. **Retrain.** An M2-size run on the measured sensor.
4. **Test on the robot.** The rules first, then the learned controller under the guards, at a capped
   speed, with the operator present, after a safety review like the one the first real run needs
   ([REAL-DUCK-SAFETY-REVIEW.md](../wip/REAL-DUCK-SAFETY-REVIEW.md)). The plugin lifts its
   "simulator only" refusal only then.

**Why.** A policy that has only seen simulated faults can fail on real ones: the whole point of
domain randomisation ([page 1](reinforcement-learning.md)) is a bet that the real sensor is inside
the training spread. R8 turns the bet into a measurement.

**Needs.** The real duck (expected in one to two months from 2026-11-26; research plan, section 6).
The operator in the room. The first rungs of the real-duck backlog
([REAL-DUCK-BACKLOG.md](../wip/REAL-DUCK-BACKLOG.md)).

**Cost.** Hardware sessions, and one retrain (1.3 to 1.9 GPU hours at the plan's estimate).

**Dependency.** The duck's arrival; R5 showing a learned controller worth the risk. Also the walker:
the real duck may not track speed the way the simulator's walker does (the simulator reproduces the
published 44 to 48 %; the real figure is unmeasured here).

## Retraining Pollen's walker

**What.** Train a better walking policy than the one the duck runs: one that walks below 0.2 m/s and
tracks the asked speed more closely than 46 %.

**Why.** Everything the controller does passes through the walker, and the walker is the ceiling:

- The controller can never make the duck faster than the walker delivers, and the walker delivers
  46 % ([page 3](the-task.md)).
- Below 0.2 m/s the walker mostly does not move (0.15 asked, 0.034 got with noise, 0.007 without;
  `CHECKS.md:110-122`), so the controller's slow-down range is only 0.2 to 0.35 and its brake works
  more as a stop.
- Reaching a 2.6 m goal in 20 s needs a request of about 0.28 m/s. A walker that tracked would
  make all the speed range useful, give richer rewards, and make the real duck's slow, careful
  approach to obstacles possible.

**What is known about the cause.** Nothing established. The walker's own training samples forward
commands of at least 0.3 for some share of environments (`CHECKS.md:124-126`); this is code and has
not been shown to be the cause. Pollen documents the 44 % shortfall and lists it as open
(`docs/wip/MICRODUCK.md:105-108`).

**Needs.** Pollen's `microduck_rl` (Apache-2.0; its meshes CC BY-NC-SA 4.0), the DGX in robotics
mode, and a check that measures the result: `scripts/walker_speed_table.py` in microduck-nav does
exactly the asked-versus-got table above. And a way to put the new policy on the robot.

**Cost.** The one measured reference is Pollen's walking task: 2.78 s per iteration at 4096 envs,
about 3 h for 4,000 iterations on the DGX (homelab recipe).

**Dependency, and a trap.** A new walker invalidates every controller trained against the old one.
The controller learned how this walker responds. So walker-first is cheaper than controller-first:
changing the walker later throws away M2 and M3. That has to be set against the fact that the
walker is Pollen's, and the published set is the one the real duck runs.

## Recovery skills

**What.** The duck getting itself back to work after trouble: standing up after a fall, and getting
over thresholds and steps. Our challenge course has the steps: challenge 17 (things on the floor: a
cable, a rug's edge, a book), 18 (a step up and a step down), 19 (a short flight, up) and 20
(a short flight, down) (`RFC-0008-challenge-course.md`, rows 17 to 20). Today they are "parked" (the
note [Walking over and up](../wip/STEPS.md)).

**Why.** An apartment has thresholds and rugs. A robot that stops dead at a door sill, or falls and
stays down, is not a product.

**What exists.** Pollen's training code already has task families for fall recovery, stand-up and
more (13 families; `docs/wip/MICRODUCK.md:11`), and the duck's policies are "swappable at runtime
(walk / recover / trick)" (`:24`). So part of this may be integration, not training: detect a fall
from the tilt, switch to the recovery policy, switch back. I have not checked that those policies
are
installed in our simulator or what the navigator would need to hand over control. A new skill, if
needed, would be a new environment and reward in `microduck_rl` (`:62-64`).

**Needs.** Fall detection and a hand-over in the navigator (today the judge's fall rule ends a
run); the skill policy; scenes with thresholds and steps for the simulator; perception of a step's
height, which an 8x8 depth grid is poor at ([the step-height note to
Pollen](../wip/UPSTREAM-STEP-HEIGHT-DRAFT.md)).
These are not training questions only.

**Cost.** Unknown. For scale, one walking-policy run is about 3 h on the DGX.

**Dependency.** Independent of the local controller, but the controller's training must stay valid:
a walker that can climb is a different walker (see above).

## Higher-level learning

**What.** The layers above the local controller: which place to explore next, and recognising areas
(rooms) and objects. The operator's stated direction. This is **supervised learning or vision
models, not reinforcement learning.**

**Why not RL.** Page 1's loop needs a cheap simulator and a reward you can write down per step. The
local controller has both: a few seconds of physics and "did you touch it". "Explore the apartment
well" has a horizon of minutes and a reward nobody has defined; no simulator has the rooms it would
explore; and
mistakes cost real time. Recognising a kitchen or a chair, meanwhile, is a labelled-examples problem
with well-understood methods.

**How it ties in.**

- **Photogrammetry.** The separate photogrammetry project (RFC-0025 section 5) builds 3D models of
  rooms from images. Those give geometry for scenes and, with labels, data for recognition.
- **The semantic map.** Objects and areas land in the semantic map
  ([RFC-0016](../rfc/RFC-0016-objects-and-semantic-map.md)); the code is `libs/worldmodel`.
- **Missions.** Instructions in words such as "go to the kitchen" need areas and objects to mean
  something ([RFC-0030](../rfc/RFC-0030-missions.md),
  [RFC-0004](../rfc/RFC-0004-perception-and-planning.md)).
- **Exploration choice.** Today exploring is rule-based (`nav/explore.py`, not read for this guide).
  A learned
  chooser would be trained from recorded runs and judged in `robotics-evals`, like everything else.

**Needs.** Camera data from our robot, labels, recorded runs (the ledger holds 85 so far), and an
evaluation design. I have not read a design for any of it; this section records the direction and
the reasoning, not a plan.

**Cost.** Unknown.

**Dependency.** The camera pipeline and the photogrammetry project; the real duck for real data.

## Curriculum, more envs, longer runs

Three ways to spend more compute or be smarter with it, all on the existing task.

- **Curriculum.** Start with easy worlds and make them harder as the policy improves. We have the
  knobs: `layout_weights` (`env_cfg.py:63`), the speed range, the impairments on or off
  (`NavOptions`, `env_cfg.py:58-69`). The task has its inherited curriculum switched off
  (`env_cfg.py:141`). A natural first: start in `open` and `barrier`, add `scattered` and the
  impairments later. It targets the "stands still" trap ([page 4](rewards.md)), because early on
  fewer collisions leave room to find the reward for moving.
- **More environments.** NVIDIA's article trained 16,384 envs x 1,500 iterations (from the article,
  not their code). More envs give a less noisy gradient per iteration, not necessarily a better
  final policy. If the cost scaled linearly (not known) it would be about 5 to 7.5 h at the plan's
  estimate of 3.2 to 4.5 s per iteration at 4096. GPU memory was 5.1 GB for Pollen's task at 4096
  and the GB10 has about 121 GiB shared with the CPU; whether the nav task fits at 16,384 is
  unmeasured.
- **Longer runs.** M3 (3,000 iterations) exists for this. The decision rule is simple: if M2's
  reward
  and `progress` are still rising at iteration 1500, longer runs pay; if flat, change something
  else.

**Cost.** M3: 2.7 to 3.8 GPU hours. **Dependency.** M2's curves, which say which of the three is
worth it.

## In what order

My suggestion, to be checked against the operator's priorities:

1. M1, then M2, then R5. Nothing else matters if the chain does not learn.
2. Decide about the walker before the expensive nav runs, because it invalidates them.
3. Curriculum, longer runs, tuning from M2's evidence.
4. R7a to R7e, which the operator decided to run before MVP 2, aimed first at where R5 shows the
   NVIDIA recipe losing.
5. R8 when the duck arrives.
6. Recovery skills and higher-level learning as their own tracks, in parallel, since they do not
   share a bottleneck with the controller.

Next: [glossary and where to continue](glossary-and-next.md).
