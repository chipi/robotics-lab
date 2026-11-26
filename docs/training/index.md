# Training the duck's local controller: a guide

This guide teaches how our robot learns to steer around obstacles, from first principles, using our
own code and our own numbers. It was written on 2026-11-26 at the operator's request, so that the
learning can be picked up again later without a re-explanation. It assumes you are a strong
software engineer and have never trained a reinforcement learning (RL) agent.

Read the pages in order the first time. Each one starts with what you will know by the end.

| # | Page | You will understand |
| --- | --- | --- |
| 0 | This page | What the local controller is, where it sits, what "done" means |
| 1 | [Reinforcement learning from zero](reinforcement-learning.md) | Agent, reward, return, discount, value, advantage; why simulation; sim-to-real |
| 2 | [PPO, step by step](ppo.md) | How the policy is actually updated, and every knob in our config |
| 3 | [Our task](the-task.md) | What the network sees (1343 numbers), what it outputs, the world it trains in |
| 4 | [Rewards](rewards.md) | Each reward term, reward hacking, how to tune |
| 5 | [Running it and reading results](running-and-results.md) | M1, M2, M3, the DGX flow, TensorBoard, the replay check |
| 6 | [Opportunities](opportunities.md) | R7, R8, a better walker, recovery skills, higher-level learning |
| 7 | [Glossary and where to continue](glossary-and-next.md) | Terms in one line; open questions |

## How to read the citations

- `microduck-nav file:line`, or a bare `file.py:line`, is the public repository
  [chipi/microduck-nav](https://github.com/chipi/microduck-nav), commit `b5a9fa9`, read on
  2026-11-26. The training code lives there, not in this repository.
- `rsl_rl ppo.py:line` is the PPO implementation `rsl_rl_lib` 5.0.1 that microduck-nav installs.
- `robotics-lab file:line` is this repository at commit `4e13c2e`. `learned.py` changes often, so it
  is cited by function, not by line.
- "Not verified" means I did not confirm it in code or by running it. It is a claim to check, not a
  fact.

## 1. The product view

### What the local controller is

The duck's navigator works in layers. A planner decides where to go. A follower turns the path into
a velocity command. The **local controller** sits between the follower and the safety guards, and
may adjust that command based on what the depth sensor sees right now.

```text
   goal
    |
    v
 planner (explore, rooms, pace)         "go to the kitchen"
    |  a path on the map
    v
 follower (nav/follow.py)               "walk 0.30 m/s, turn 0.2 rad/s"   10 Hz
    |  requested command (vx, vyaw)
    v
 LOCAL CONTROLLER  rules@1 | learned@<sha8>        <-- this guide
    |  adjusted command
    v
 guards: cliff stop, pace, depth reflex, stuck stop     they read it, never ask it
    |
    v
 speed cap (Navigator.move)             from the guardrails' max_speed
    |  applied command
    v
 locomotion plugin --> robotd --> Pollen's walker --> 14 motors
```

The code: the controller is called as `self._control(tw)` at `robotics-lab nav/run.py:1242`
(and `:1287`), right after the follower's `step` and before the cliff stop (`:1263`), the reflex
(`:1337`) and the stuck stop (`:1361`). The cap and the send are in `Navigator.move`
(`nav/run.py:359-372`). The seam is specified in
[RFC-0025, section 3.7](../rfc/RFC-0025-mvp1-to-mvp2.md) ("The local-controller seam").

### What it is, and what it is not

- **It does not walk.** Pollen's walking policy turns a velocity command into joint angles. The
  controller only edits the velocity command. It never sees a motor.
- **It never goes faster than asked.** It can slow down, stop, and steer. The forward speed it
  outputs is capped at the follower's request (`residual_action.py:47-49`). Learning to be
  careful cannot turn into learning to be reckless.
- **The guards stay above it.** The reflex, cliff stop, stuck stop, speed cap, STOP and the lease
  are unchanged and see the controller's command as they saw the follower's. A learned model never
  has the last word on safety.
- **It has no map and no plan.** It knows the request, the last 10 depth frames, and the body's
  own state. It reacts; it does not explore. That is a different problem (page 6).

Today's local layer, the rules, stops: a return in the corridor within 0.30 m, or any return within
150 mm, sends a zero command (profile `sensors.tof8x8`). It never steers. A learned controller's
job is to steer around and slow before the stop is needed.

### Where it is today

| Question | Answer |
| --- | --- |
| Default | `rules@1`: returns the follower's command unchanged (`plugins/rules.py:19-20`) |
| Learned | `learned@<sha8>`: an ONNX model, `plugins/learned.py`; named by the first 8 hex digits of its file's SHA-256 |
| Where it may run | The simulator only. Its constructor refuses any robot whose variant is not `sim`, until R8 |
| Does a trained model exist? | No result yet. M1 (a short run) has a smoke run only; see [page 5](running-and-results.md) |
| The real duck | Refused. R8, after a safety review, decides |
| The trainer | `microduck-nav`, a separate public repository, trained on the DGX |

### What "done" looks like, as a product

A learned controller that steers around obstacles, judged against the rules on frozen scenarios,
by evidence, not by a demo. In the research plan's terms (R5,
[RESEARCH-LEARNED-AVOIDANCE.md](../wip/RESEARCH-LEARNED-AVOIDANCE.md), section 4):

- Three arms: the rules alone, the learned controller, and the learned controller with the rules
  as the guard.
- The same scenarios with seeds, at least 10 per arm.
- Scores: success, collisions, minimum clearance, time, stops, falls.
- The comparison lives in `robotics-evals`, built on eval-harness 0.8.1.

If the learned arm does not beat the rules on that table, it does not ship, however good it looks
in a video. Training is a means to a number in that table.

## 2. The training in one picture

```text
  Pollen's walker (frozen)  ---------------------------+
                                                       v
 obstacle world --> 8x8 depth + body state --> [ policy: 1343 -> 3 ] --> residual command
 (4096 copies)             ^                                        |
                           |                                        v
                      reward: progress, arrival, safety   walker --> joint targets --> physics
                           ^                                        |
                           +----------------------------------------+
                                   (PPO changes the policy's weights)
```

Everything on this page happens in a simulator called MuJoCo Warp, on the GPU, 4096 ducks at once.
The only thing learned is the small 1343-to-3 network. Pollen's walker is inside the loop and is
not changed.

## 3. Where to go next

Go to [reinforcement learning from zero](reinforcement-learning.md). If you already know the
vocabulary, skim its summary box and go to [PPO](ppo.md).
