# 4. Rewards in depth

!!! abstract "By the end of this page"
    You can read any reward curve and say which behaviour it is paying for. You know the ways the
    duck could cheat and which term stops each, and you have a procedure for changing a weight
    without guessing.

The reward is the only way we tell the duck what we want. The network is never shown an obstacle
and told "avoid that". It gets a number per step and works out the rest. So the reward is the
specification of the product, and a wrong specification is learned as faithfully as a right one.

## The eight terms

The weights are in `env_cfg.py:46-55`, the terms registered at `:175-188`, the maths in
`nav_math.py`, and the stateful terms in `rewards.py`. NVIDIA's weights; each term is tested against
NVIDIA's own functions (`CHECKS.md:212-220`).

| Term | Weight | Kind | In one line |
| --- | --- | --- | --- |
| `progress` | +5 | continuous | Move along the request, but only as fast as is safe |
| `goal_arrival` | +30 | once | Reach the destination safely; revoked if you then crash |
| `barrier_bypass` | +5 | once | Get past the obstacle that blocked the way |
| `yaw_tracking` | +4 | continuous | Turn as asked, when the way ahead is clear |
| `command_tracking` | +1 | continuous | Move as asked, when the way ahead is clear |
| `approach` | -4 | continuous | Do not close on an obstacle faster than you could stop |
| `command_rate` | -5 | continuous | Do not change the command abruptly |
| `failure` | -30 | once | You fell, hit something or broke the physics |

### Reading the units

mjlab multiplies every step's reward by the step length, 0.02 s (`mjlab reward_manager.py:39`). So
a continuous term's weight is **per second**: progress at +5 pays at most 5 per second, 100 over a
20 s episode. The one-off terms divide by the step length first (`rewards.py:4-5`, `:79`, `:105`,
`:187`), so goal arrival pays exactly +30 once and the failure costs exactly -30.

The TensorBoard curve `Episode_Reward/<term>` is that term's episode total divided by 20 s
(`reward_manager.py:106-110`), so it reads as an average per-second rate. A `goal_arrival` curve at
1.5 would mean every episode arrived (30 / 20 s).

Only ratios between weights matter, not their absolute size, because the advantages are normalised
before each update ([page 2](ppo.md)).

## Each term

### progress: +5, the engine

```text
raw    = (actual body velocity . request) / |request|^2      clamped to [-1, 1]; 0 if |request| < 0.05
reward = raw * (1 - risk)   if raw > 0,   else raw           (nav_math.py:79-84, :122-123)
```

What it measures: how much of the request the duck is actually achieving, along the request's
direction. 1 means going exactly as fast as asked; 0 means not moving or moving sideways; negative
means going backwards.

What it encourages: move. What it discourages: standing, and rushing, because the progress credit
is multiplied by `1 - risk` (the approach risk below): charging at an obstacle earns nothing. The
gate uses the base risk only, without the extra commanded term (`rewards.py:49-51`).

A number to keep in mind: the walker delivers about 46 % of the asked speed ([page 3](the-task.md)),
and the request is the thing `raw` is measured against, so even a perfect controller sees `raw` of
about 0.46 and earns about 5 x 0.46 = 2.3 per second (my arithmetic). The reward's ceiling is the
walker's.

### goal_arrival: +30, the prize

```text
paid once, when the duck is within 0.2 m of the destination, safe, and was safe the whole way
revoked (-30 net) if it later fails: a collision, a fall, or leaving the field     (rewards.py:82-105)
```

What it measures: success. What it prevents: touching the goal and then crashing, or arriving by
bulldozing something. It is rare at the beginning and zero in M1, where the goal is out of reach.
It is a sparse reward: nothing until the duck gets there. This is why the other terms exist, to give
a trail to follow.

### barrier_bypass: +5, the shaped step

```text
paid once, when the duck passes the first obstacle that blocked the initial request line,
staying entirely on one side of it, and safe          (rewards.py:108-221)
```

The code picks the nearest obstacle that the initial request would hit, tracks whether the duck
stays wholly left or right of its expanded footprint (footprint plus 0.12 m) while crossing its
length, and pays when it is past the far end. It exists because arrival is far away: a duck that has
gone around the box, though not yet at the goal, gets credit. It is what separates "stopping in
front
of the box" from "going around it". Of all eight, I would call this the term that most directly
teaches
steering.

### yaw_tracking: +4 and command_tracking: +1, follow the request when it is safe

```text
yaw_tracking     = exp( -(request yaw - actual yaw rate)^2 / 0.35^2 )  * gate
command_tracking = exp( -|request xy - actual xy velocity|^2 / 0.15^2 ) * gate
gate = clamp(clearance ahead / 0.25, 0, 1) * clamp(progress, 0, 1)
       (gate = 1 if |request| < 0.05)                                  (nav_math.py:126-153)
```

The exponential is a bump: 1 when actual equals requested, falling off as they differ (a width of
0.35 rad/s for yaw and 0.15 m/s for translation). The gate is the interesting part. The "clearance
ahead" is the distance from the robot to the nearest obstacle along the next 0.5 m of the requested
path (`nav_math.py:41-72`). When something is within 0.25 m of that path the gate closes, so the
duck is not paid to follow the request, and it is not punished for leaving it either. This is what
frees the controller to deviate. Following the request is rewarded when it is safe, and only then.

A caveat. The gate also multiplies in the progress: tracking is paid only if the duck is also
making progress. Standing earns zero here.

Numbers (my arithmetic from [page 3](the-task.md)'s table): with a request of 0.30 m/s and the
walker's 0.14, the translation error is 0.16 m/s so the bump is exp(-(0.16 / 0.15)^2) = 0.32. And
the
gate has `progress` of about 0.47 in it. So `command_tracking` stays near 0.15 per second, with
weight 1. It is the faintest term here; and `yaw_tracking` at weight 4 is four times stronger, which
makes sense, because turning toward the goal is what steering is.

### approach: -4, the safety sense

This is the term that makes the duck careful. It does not penalise being close to an obstacle. It
penalises closing in on one too fast for the room that is left.

```text
c         = distance to the nearest obstacle's surface, minus the robot radius 0.12 m
closing   = how fast c is shrinking, predicted 0.1 s ahead, taking the worse of two predictions:
            (a) from the duck's actual velocity,  (b) from the command it was given
remaining = max(c - 0.2, 0)              0.2 m is the safety margin
risk      = clamp( (closing - remaining / 2) / 0.20, 0, 1 )^2        zero if not closing
reward    = -4 * (risk + 1.0 * risk_commanded_only)                (nav_math.py:87-119; env_cfg.py:181-185)
```

In words: you may approach an obstacle at any speed that would use up the free distance beyond a
0.2 m margin in no less than 2 seconds (`time_horizon` = 2). Faster than that is risky, and 0.2 m/s
faster than that is the maximum risk, 1. It is squared, so small excesses cost little and big ones a
lot.

A worked example (my arithmetic). The duck is 0.30 m from an obstacle (c = 0.30), so `remaining` is
0.10 m and the allowed closing speed is 0.05 m/s. The command is 0.30 m/s straight at it and the
walker delivers 0.14. The worse of the two predictions is the command's: ((0.30 - 0.05) / 0.2) is
1.25, clamped to 1, so `risk` = 1. The extra commanded term is also 1. Total 2, a penalty of -8 per
second, the most this term can charge. At the same speed from 1 m away, `remaining` is 0.8 and the
allowed speed 0.4: no risk at all.

Two details:

- **The commanded part.** The base `risk` already takes the worse of "what the duck is doing" and
  "what it was told to do". With `commanded_risk_weight` = 1.0 (`env_cfg.py:184`), a second term,
  the commanded-only risk, is added on top, so a rushing command is charged twice. Without this, the
  policy could ask for a high speed and let the walker's slowness protect it. With it, the policy is
  penalised for the intention. The progress gate uses the base `risk` only (`rewards.py:49-51`).
- **Not a proximity penalty.** A separate `clearance_risk` (penalty for simply being close) exists
  in
  the code but is not in the reward table (`rewards.py:68-70`, not registered). The duck may stand
  next to a wall for free. What it may not do is arrive there in a hurry.

### command_rate: -5, no jitter

```text
reward = -5 * mean over the 3 axes of ( (command - previous command) / limits )^2     (nav_math.py:160-161)
```

It penalises changes of the command from one step to the next, relative to the limits. By itself the
term is small: at the slew limit's maximum change per step (0.02, 0.02, 0.06) against the limits
(0.35, 0.12, 0.75), the mean squared ratio is about 0.0125, so the penalty is about -0.06 per second
(my arithmetic). Because the slew limit already keeps the command smooth, this term is a gentle
tie-breaker against dithering, not a force. The exception is the stale stop, which bypasses the slew
and can drop the command in one step.

### failure: -30, the wall

```text
reward = -30 on the step the episode terminates (collision, fall, NaN); nothing for a time-out
         (rewards.py:78-79)
```

It is a plain, large, once-only penalty. Think of it in the currency of the others: -30 is the
progress
a perfect duck earns in 6 s (at 5 per second), or about 13 s at the walker's realistic 2.3 per
second.
One collision costs more than a dozen seconds of good walking, which is about the right order for
"avoid collisions, but do not stop moving".

## Reward hacking: how the duck can cheat

A trained policy is an optimiser that finds the loopholes in your reward. For each plausible one,
here is the term that closes it.

| The cheat | Why it tempts | What stops it |
| --- | --- | --- |
| **Stand still.** Never move, never collide | The score is exactly 0, better than a collision's -30 | Nothing penalises standing. It earns 0 from progress, tracking, arrival and bypass, so it only loses the possible gains |
| **Spin on the spot** to farm yaw tracking | Turning matches a yaw request | The tracking gate contains `progress`, which is 0 when not translating, so the reward is 0 |
| **Rush the obstacle**, collect progress, hope to stop | Progress pays | `progress` is multiplied by `1 - risk`; `approach` charges for the speed at the obstacle |
| **Command a rush, let the slow walker protect you** | The walker delivers 46 % anyway | `approach` also counts the commanded closing speed (weight 1.0) |
| **Touch the goal, then crash** | Arrival pays +30 once | The credit is revoked on a later failure (`rewards.py:100-104`) |
| **Dither**: flip the command every step | It might average out to the right speed | The slew limit, `command_rate` |
| **Walk off the field** to end the episode | The 5 m boundary is a truncation: no -30 | Moving away from the destination has negative `progress`. Possible in principle; not seen |

Standing still deserves a closer look, because it is the real danger. In the first iterations
collisions are common. Under that pressure, the cheapest way to raise the average reward is to stop
moving, because standing scores 0 and a collision scores -30. The positive terms are the only
counterweight: a safe 20 s walk earns something like 2 to 4 per second, around +40 to +80 per
episode (my estimate; not measured). A policy that stands is
stable, because from standing there is no gradient leading to walking unless random exploration
finds a safe way to progress.

Two consequences:

- **Milestone M1 asks for the stop.** In the one-wall task the goal is out of reach in 20 s at the
  walker's speed, and the wall blocks the way, so stopping in front of it *is* the best policy
  available (`M1.md:122-123`). That is what the milestone checks: that the whole chain learned
  anything. It is a proof of plumbing, not of steering. M2 and M3 are where "does it go around?"
  gets answered.
- **How to tell a stander from a navigator on the curves.** A standing policy has episode length
  1000 (all time-outs), collisions near 0, `Episode_Reward/progress` near 0 and no arrival. A
  navigator has progress clearly above 0 and arrivals, bypasses, or both.

One more point about honest measurement. The reward is a proxy. The reward punishes any contact over
0.1 N and uses the true geometry, which the policy cannot fully see (behind it, outside the
sensor's field of view). The product is judged differently: success, collisions, minimum clearance,
time, stops, falls, on frozen scenarios (R5). A policy can score a high reward and still fail the
product's test. R5, not the reward curve, is the verdict.

## How to tune

A rule first: **do not change a weight without having looked at the per-term curves.** The total
reward hides which term moved.

| Symptom (from the curves) | Likely cause | First thing to try |
| --- | --- | --- |
| Episode length 1000, `progress` near 0, few collisions: it stands | Penalties outweigh the gains | Lower `approach` or `failure`; raise `progress` or `barrier_bypass`; check that requests are at least 0.2 m/s |
| `obstacle_collision` stays high and the reward is flat | The task is too hard too early | A curriculum (fewer obstacles first, then more); a gentler sensor impairment; a larger `failure` or `approach` |
| Collisions down, but the duck brakes far from everything | `approach` too strong relative to `progress` | Lower `approach`, or the `safety_distance` (0.2 m) |
| Passes close, scrapes | `approach` too weak | Raise `approach`, or the safety distance to 0.3 m |
| Never turns toward the goal | Little reward for steering | Raise `yaw_tracking` or `barrier_bypass` |
| The command twitches | The policy's noise is large | Check the action std first; then raise `command_rate` |

Process:

1. Change one thing at a time. With about two hours per full run, there is time for few experiments
   (the R6 plan budgets up to two tuning reruns, 2 to 4 GPU hours).
2. Compare runs by a fixed evaluation (the replay, then R5's scenarios), not by their mean reward.
   Reward values from different weights are not comparable.
3. Keep every variant as its own task id, so that a model's file names its weights. The weights are
   a dict (`env_cfg.py:46-55`); a variant needs a new `NavOptions` or its own registration in
   `tasks.py`. Name it in the run's record ([page 5](running-and-results.md)).
4. Record why. A reward change is a design decision, and in three weeks the "why" is gone.

Next: [running it and reading results](running-and-results.md).
