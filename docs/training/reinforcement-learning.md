# 1. Reinforcement learning from zero

!!! abstract "By the end of this page"
    You can say what every word in an RL training log means, and you know the five numbers that
    define our problem: 50 Hz, 20 s, 1000 steps, discount 0.998, 4096 parallel ducks.

## The idea

Supervised learning needs a teacher who knows the right answer for each input. Here nobody knows
the right command for a given depth frame. What we can do cheaply is **score** a whole attempt:
the duck reached the goal without touching anything, or it hit a wall.

Reinforcement learning is learning from that score. Try something, see what happened, make the
things that led to good scores more likely. Repeat millions of times. There is no dataset of
correct answers; the data is the agent's own experience.

## The loop and its vocabulary

```text
        action a_t  (3 numbers)
   +---------------------------+
   |                           v
 AGENT                    ENVIRONMENT
 (the policy)             (simulated duck, obstacles, physics)
   ^                           |
   +---------------------------+
     observation o_{t+1}  (1343 numbers),  reward r_{t+1}  (1 number)
```

| Word | Meaning | In our code |
| --- | --- | --- |
| **Environment** | The world that responds to actions | mjlab on MuJoCo Warp; `env_cfg.py` builds it |
| **Agent** | The thing that decides | A small neural network, 1343 inputs to 3 outputs |
| **Observation** | What the agent is told about the world at one step | The 1343 numbers: body state, the request, ten depth frames, their ages ([page 3](the-task.md)) |
| **Action** | What the agent outputs | Three residuals in [-1, 1]: forward, sideways, turn |
| **Reward** | One number per step saying how well it is going | A weighted sum of 8 terms ([page 4](rewards.md)) |
| **Step** | One tick of the loop | 0.02 s: physics at 5 ms, 4 physics steps per control step (50 Hz) |
| **Episode** | One attempt, from reset to end | 20 s = 1000 steps (`env_cfg.py:140`), or sooner on a failure |
| **Policy** | The rule mapping observation to action | The actor network. Written as pi(a given o) |
| **Return** | The total discounted reward from now to the end | See below |
| **Value** | The return you expect from a state | Estimated by a second network, the critic |
| **Advantage** | How much better an action was than usual | See below |

Two subtleties of the word "observation":

- The agent does not see the true state of the world. It sees what its sensors report: a noisy
  8x8 depth image, its own joints, its own tilt. It cannot see behind it or the exact distance to a
  wall. Because of that, its history is part of the observation (page 3).
- Our policy is **stochastic** during training. It outputs a probability distribution over
  actions and the environment gets a sample from it. Randomness is how it tries new things. At
  deployment we use the mean of the distribution instead, so the robot behaves the same way twice.

## Return and the discount

A single step's reward is not what we want to maximise. A step that gets close to the wall might
pay a little progress now and cost -30 two seconds later. So the agent maximises the **return**:
the sum of future rewards, each one counted a little less the further away it is.

```text
G_t  =  r_t  +  gamma * r_{t+1}  +  gamma^2 * r_{t+2}  +  ...
```

In words: this step's reward counts fully; the next counts gamma of itself; the one after counts
gamma squared; and so on. `gamma` is the **discount**. It is 0.998 in our config
(`rl_cfg.py:34`).

What does 0.998 mean in time? The control step is 0.02 s. A reward `n` steps away is worth
`0.998^n`:

| Distance | Steps | Weight | Reads as |
| --- | --- | --- | --- |
| 0.4 s | 20 | 0.96 | almost fully counted |
| 5 s | 250 | 0.61 | still counted over half |
| 6.9 s | 346 | 0.50 | **half-life** |
| 10 s | 500 | 0.37 | the usual rule of thumb: horizon `1 / (1 - gamma)` = 500 steps = 10 s |
| 20 s | 1000 | 0.135 | the end of an episode counts about an eighth |

Two consequences for us:

- The agent plans over roughly 10 seconds. That is the right order of magnitude: from the first
  sight of a wall (about 1 m ahead at 0.14 m/s actual speed, 7 s away) to the goal, the whole
  manoeuvre is inside the horizon.
- A collision's -30 penalty reaches back. A step that starts a doomed approach 5 s before the
  crash is penalised by 0.61 x 30, about 18 in the return, so the agent is told that approach was
  bad long before the contact.

A discount also keeps the sum finite and makes learning stabler. A high gamma (closer to 1)
gives farsighted behaviour but noisier learning. A low gamma gives a short-sighted agent that
would brake only at the last moment.

## Value and advantage

The **value function** `V(s)` answers: from this situation, what return do I expect, if I keep
behaving as I do now? A duck facing an open floor has a high value; a duck 8 cm from a wall,
walking at it, has a low one. We train a second network, the **critic**, to predict it.

The **advantage** answers a narrower question about a single action:

```text
A(s, a)  =  (return actually obtained after taking a in s)  -  V(s)
```

In words: how much better than expected did this action turn out? Positive means better than
average from that state, negative means worse. The advantage is what the policy learns from: it
says which of the actions taken in a state to make more likely and which less.

The advantage is the subtraction of a baseline. Without it, a state that is good anyway would
reward every action taken in it. [Page 2](ppo.md) shows why this matters.

## Why trial and error, and why in simulation

The policy starts knowing nothing. In the first iterations the duck bumps walls constantly. The
smoke run's iteration 19 is typical: mean reward -37.26, half the finished episodes ending in an
obstacle collision. It needs those failures to learn where the penalty is.

On the real duck, each failure costs time (reset by hand), battery, wear on gears, and risks a
fall onto something. And it needs a lot of them. Do the arithmetic from our config:

```text
4096 envs  x  24 steps per env  =  98,304 steps per iteration
x 1500 iterations (the config's default)  =  147 million steps
147,456,000 steps / 50 steps per second   =  2.9 million robot-seconds  =  34 robot-days
```

A real duck would need more than a month of continuous, unattended walking into walls. The
simulator does the same in an estimated 1.3 to 1.9 GPU hours (the R6 plan's estimate for M2; not
yet measured, see [page 5](running-and-results.md)).

## Why thousands of parallel ducks

Two reasons, one practical and one statistical.

- **Practical.** A GPU is very good at doing the same arithmetic on a large batch. MuJoCo Warp
  steps 4096 independent worlds in one call, and `rays` casts all 64 depth rays of all 4096 ducks
  in one call (R6 plan section 1.1). One duck at a time would waste almost all of it.
- **Statistical.** Each learning step needs a batch of experience. With 4096 environments each
  taking 24 steps, one iteration gathers 98,304 steps from 4096 different situations: different
  obstacle layouts, different headings, different sensor faults, different pushes. A big and
  varied batch gives a stable estimate of "which actions were good" (less noise, see the variance
  problem on [page 2](ppo.md)).

Each environment sits 14 m from the next (`env_cfg.py:37`) so the ducks do not see each other's
obstacles.

The smoke run used 64 environments, and the scale-up is 4096. The per-iteration time does not
scale linearly, so the smoke's 0.64 s per iteration says little about the big run (see
[page 5](running-and-results.md)).

## Sim-to-real

A policy trained in simulation is judged in the real world. The difference between the two is the
**sim-to-real gap**. Everything the simulator simplifies, the policy can exploit: a perfectly
clean depth sensor, exactly known friction, no delay. A policy that learned in such a world fails
on a real duck whose sensor reports garbage 3 % of the time.

The standard defence is **domain randomisation**: make the simulator wrong in many different ways,
a different way each episode, so that the policy cannot rely on any one of them. It has to work
across the whole spread, and the real world is hoped to fall inside that spread.

We randomise two kinds of things.

**The body (Pollen's own randomisation, kept)**: foot friction, centre of mass, mass and inertia,
joint friction, armature, encoder bias, and random pushes every 5 to 10 s of up to 0.1 m/s
(`env_cfg.py:40-44`, `:159-160`). These make the walker's job vary; the controller must work with
whatever the walker then does.

**The sensor (NVIDIA's impairments, called "priors": a guess at the real thing)**. Our depth sensor
is a time-of-flight (ToF) chip, 8x8 = 64 zones, 45 degree field of view, 0.12 to 4 m, at about
15 Hz. The training sensor is made worse in these ways (`impairments.py:20-57`):

| Impairment | Draw per episode | Why it exists |
| --- | --- | --- |
| Range gate | A return under 0.12 m or over 4 m is invalid | The chip cannot report them |
| Distance bias | U(-0.02, +0.02) m, same for all zones | Calibration error |
| Distance scale | U(0.98, 1.02) | Calibration error |
| Zone bias | U(-0.01, +0.01) m, per zone | Per-zone calibration |
| Noise | std U(0.003, 0.01) m, plus 0.8 % of the depth | Measurement noise |
| Invalid zones | 3 % of zones each frame report nothing | The chip drops zones |
| Floor blanking | Floor returns beyond about 0.556 m are dropped with a rising probability | The chip fails on floor at grazing angles |
| Edge column | In half the episodes, one edge column of near floor is mostly dropped | A quirk NVIDIA saw |
| Latency | 0 or 1 frames | Transport delay |
| Frame dropout | 2 % of frames never arrive | Packet loss |
| Mount | Pitch +-10 degrees, height +-2 cm | The head is not mounted identically |
| Zone grid | `mixed`: each episode draws Pollen's equal-angle grid or NVIDIA's pinhole grid | We do not know which the real chip's data resembles (`CHECKS.md:66-69`) |

A key honest point: these numbers are **NVIDIA's guesses**, from their own duck. They are not
measured on ours. Measuring our own sensor's faults, and retraining on them, is
[opportunity R8](opportunities.md).

One more piece of the observation protects against a simulator trap: a missing return is not
"free space". Each depth number comes with a separate valid flag, so the network can tell "0 m
because the chip failed" from "far away" (`observations.py:14-19`).

## What to remember

- The policy maps observation to a distribution over actions; we train it to maximise the
  expected return.
- gamma 0.998 means a horizon of about 500 steps, 10 s; the half-life is 6.9 s.
- Value is expected return from a state; advantage is how much better an action was than that.
- Simulation gives 34 robot-days of experience in about two hours, and domain randomisation is how
  the simulator's lies are kept from being learned.

Next: [PPO, step by step](ppo.md).
