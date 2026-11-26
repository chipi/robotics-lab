# 2. PPO, step by step

!!! abstract "By the end of this page"
    You can explain, in your own words, why PPO is built the way it is: policy gradient, then the
    variance problem, then a critic as a baseline, then GAE, then small clipped updates. You can
    read every line of our PPO config and say what changes if it is wrong.

PPO is Proximal Policy Optimisation. It is the algorithm in `rsl_rl`, the library that trains our
controller (`rsl_rl ppo.py`). We will build it one problem at a time. Each step exists because the
previous one has a flaw.

## Step 1. The policy gradient: make good actions more likely

The policy is a network with weights `theta`. It maps an observation to the parameters of a
distribution over actions, and `pi_theta(a | o)` is the probability of action `a`. We want weights
that make the expected return `J(theta)` large.

The policy gradient theorem says the direction that increases `J` is:

```text
grad J  =  E [ grad log pi_theta(a | o)  *  G ]
```

In words: for each action the duck took, nudge the weights so that the same action is more likely
next time in that situation, and scale the nudge by how good the outcome (`G`, the return) was. A
good outcome pushes the action's probability up; a bad outcome pushes it down.

That is the whole idea of "learning from the score". Everything below makes it work in practice.

A tiny illustration from our task, with made-up returns. The duck sees a wall at 0.5 m. In one
environment it picks a forward residual of -1 (brake) and the episode goes on without contact: a
high return, say +40. In another it picks 0 (follow the request), hits the wall and gets -30 and
less. The gradient makes braking more likely when a wall is at 0.5 m and following the request less
likely. After many such experiences the weights encode "wall close: slow down".

## Step 2. The variance problem

The recipe above is correct on average and useless in practice, because the return `G` is a very
noisy teacher.

Our episode has 1000 steps. The return after step 300 includes the effect of 700 further random
actions, the sensor's random faults, random pushes and a random obstacle layout. Whether one
particular action at step 300 was good is a tiny signal inside that noise. If the duck had a good
episode anyway, every action in it, including bad ones, gets pushed up. It is like judging one
line of code by the revenue of the whole company that month.

Two things follow:

- With raw returns we would need an enormous number of samples to average the noise away.
- A uniformly good state gives every action a positive score. Only differences between actions
  matter.

## Step 3. A baseline: the critic and the advantage

Subtract from the return what we would have expected anyway, `V(o)`:

```text
A  =  G  -  V(o)
```

This is the **advantage** from [page 1](reinforcement-learning.md). It is positive when the action
did better than the typical outcome from that state and negative when worse. Subtracting a
baseline that depends only on the state does not change the expected gradient, but it greatly
reduces the noise: a state that is good anyway now gives scores near zero and only the genuinely
better or worse actions stand out.

`V` is not known; we learn it with a second network, the **critic**, trained to predict returns by
plain regression (squared error). So training has two coupled networks:

- the **actor** (the policy): chooses actions;
- the **critic** (the value function): judges states, so that the actor's updates are less noisy.

The critic is used only during training. The file that goes on the robot is the actor alone.

## Step 4. GAE: how far to look before trusting the critic

We still need an estimate of the advantage per step. Two extremes:

- **Use the real return**: unbiased but noisy (step 2).
- **Use one step and then trust the critic**: calm, but only as good as the critic, which is bad
  at the start. This is the **TD error**:

```text
delta_t  =  r_t  +  gamma * V(o_{t+1})  -  V(o_t)
```

In words: what I got now, plus what I think the next state is worth, minus what I thought this
state was worth. If `delta` is positive, things went better than the critic expected.

**GAE** (generalised advantage estimation) blends the whole range with one number, `lambda`:

```text
A_t  =  delta_t  +  (gamma * lambda) * delta_{t+1}  +  (gamma * lambda)^2 * delta_{t+2}  +  ...
```

Our `lambda` is 0.95 (`rl_cfg.py:35`), so `gamma * lambda` = 0.998 x 0.95 = 0.948. The advantage
effectively looks ahead about `1 / (1 - 0.948)` = 19 steps, 0.39 s, and trusts the critic beyond
that. Compare with the return's own horizon of 500 steps. This is the bias and variance trade:

- `lambda` near 0: short-sighted advantage, low noise, biased by whatever the critic gets wrong.
- `lambda` near 1: close to the real return, unbiased, noisy.

The code is a short backwards loop (`rsl_rl ppo.py:187-206`). Two details that matter to us:

- At the end of the 24-step rollout, the critic's value of the last observation stands in for the
  rest of the episode (`ppo.py:191-196`). A rollout is much shorter than an episode, so the critic
  is used constantly.
- When an episode ends by time-out and not by failure, the code adds `gamma * V` to the last
  reward (`ppo.py:175-179`; mjlab supplies the flag, `mjlab rl/vecenv_wrapper.py:83`). A time-out is
  not a bad outcome; the duck would have kept going, so
  its future value is credited. A collision or fall gets no such credit. This is why our config
  marks `field_boundary` as a time-out (`env_cfg.py:198`) and collisions as not.

Finally the advantages of the whole batch are normalised to mean 0 and standard deviation 1
(`ppo.py:208-209`). This makes the learning rate mean the same thing whatever the reward's scale.

## Step 5. Why updates must be small

We now have a batch of 98,304 steps with advantages. The obvious move is to take many gradient
steps on it until the policy has fully exploited it. That fails.

The batch was collected by the **old** policy. The advantage says "this action was good when the old
policy took it in that situation". If the policy changes a lot, those numbers no longer describe the
new policy. A big step on stale data can walk the policy off a cliff: it becomes worse, the
next batch is collected by this worse policy, and training collapses. In RL, unlike in supervised
learning, a bad update corrupts your own future training data.

So the update needs a leash: change the policy, but not by much.

## Step 6. The clipped objective

PPO measures how far the new policy has moved on each sample, with the **ratio**:

```text
r  =  pi_new(a | o) / pi_old(a | o)
```

`r` = 1 means unchanged for this action; `r` = 1.3 means the action is now 30 % more likely.

The objective it maximises:

```text
L  =  mean over samples of  min(  r * A ,  clip(r, 1 - eps, 1 + eps) * A  )        eps = 0.2
```

(Code: `rsl_rl ppo.py:297-302`; it minimises the negative.) Read it as two cases:

- **A > 0, the action was good.** We want `r` to go up. Once `r` exceeds 1.2 the clipped term
  stops growing, the gradient is zero, and we stop pushing: this action is already 20 % more likely.
- **A < 0, the action was bad.** We want `r` to go down. Once `r` is below 0.8, no more push.

Past the clip, a sample simply stops contributing. If a step went the wrong way (the action's
probability rose though it was bad), the `min` keeps the full gradient so it gets corrected. The
policy can still move, but each sample's pull has a limit, and the batch is reused for only 5
passes.

That is PPO. It does not guarantee the policy stays near the old one, but in practice it is a very
robust way to approximate "take the biggest safe step".

## The whole loop, in our numbers

```text
repeat for 1500 iterations (max_iterations):
    collect:  4096 envs x 24 steps each          = 98,304 steps       (0.48 s of robot time each)
    compute:  returns and advantages (GAE) from the critic's values
    update:   5 epochs x 4 minibatches           = 20 gradient steps
              each on 24,576 steps (98,304 / 4), actor and critic together
    log, and every 100 iterations: save a checkpoint (and its ONNX)
```

The loss that each gradient step minimises (`ppo.py:313`):

```text
loss = surrogate_loss  +  1.0 * value_loss  -  0.0 * entropy
```

- **surrogate** is the clipped objective above;
- **value loss** is the critic's squared error against the returns, itself clipped by the same
  `eps` so the critic cannot lurch either (`ppo.py:304-311`);
- **entropy** is a bonus for being random; ours is off.

Gradients are clipped to a norm of 1.0 (`ppo.py:374-375`) as a guard against one bad batch, and the
optimiser is Adam (the default, `ppo.py:49`).

## Our settings, one by one

All from `rl_cfg.py:21-48`, which follows NVIDIA's recipe (docstring at `:1-6`).

| Setting | Ours | What it does | Too high | Too low |
| --- | --- | --- | --- | --- |
| `learning_rate` | 3e-4, `schedule="fixed"` | Size of each weight update | Reward oscillates or collapses; losses spike | Learning is slow; nothing visible in hundreds of iterations |
| `clip_param` (eps) | 0.2 | How far one sample may move the policy per update | Updates too bold; unstable | Almost no learning per batch |
| `num_learning_epochs` | 5 | Passes over the same batch | Overfits stale data; ratio leaves the trust region | Wastes expensive simulation data |
| `num_mini_batches` | 4 | Splits the batch into 4 for 4 gradient steps per epoch | Few samples per step: noisy | One huge step: fewer updates per batch |
| `num_steps_per_env` | 24 | Rollout length per env per iteration | Slower iterations, staler data, but longer credit assignment | Advantage leans heavily on the critic; noisier gradient per env |
| `gamma` | 0.998 | The horizon, about 10 s | Noisy, slow learning | A duck that brakes only at the last second |
| `lam` | 0.95 | The GAE blend (about 19 steps) | Noisy advantages | Biased towards the critic's errors |
| `entropy_coef` | 0.0 | Bonus for randomness | The policy stays random; never commits | The policy may become certain too early and stop exploring |
| `value_loss_coef` | 1.0 | Weight of the critic's error in the loss | Critic dominates the shared updates | A poor baseline: noisy actor updates |
| `max_grad_norm` | 1.0 | Clips the gradient size | Little protection | Throttles learning |
| `desired_kl` | 0.01 | Used only by an adaptive learning rate, which we do not use | n/a | n/a |
| `obs_normalization` | True | Rescales every input to mean 0, std 1 using running statistics | n/a | Inputs of different scales (metres, flags, seconds) fight each other |
| `clip_actions` | 1.0 | Clips the actor's action to [-1, 1] | n/a | n/a |
| `num_envs` | 4096 (`env_cfg.py:143`) | Parallel ducks | More memory | A noisier gradient |
| `max_iterations` | 1500 | Training length | Longer, more cost | Underfitted |

Notes on the table:

- `desired_kl` is inert here: `ppo.py:269` only uses it when `schedule == "adaptive"`. NVIDIA's own
  config sets it to `None` (R1 section 1.8). Ours sets 0.01, which is harmless. Not an issue, but
  do not read it as a KL target in effect.
- `entropy_coef` 0 is NVIDIA's choice (R1 section 1.8). With a Beta head and no entropy bonus,
  exploration depends on the head's spread, which PPO tends to narrow as the policy improves. The
  signal to watch is the action std on TensorBoard ([page 5](running-and-results.md)).
- Left out on purpose: NVIDIA's mirror loss (coefficient 0.1), which rewards left-right symmetric
  behaviour (`rl_cfg.py:3-4`). Add it only if the trained duck turns out lopsided.
- "Too high / too low" columns are standard RL experience, not measured on our runs. We have no
  tuning history yet.

## The networks

```text
actor:   1343 --normalise--> 128 --tanh--> 128 --tanh--> 6 logits --> 3 Beta distributions
critic:  its own observation --normalise--> 128 --tanh--> 128 --tanh--> 1 value
```

- Both are small multi-layer perceptrons, 128 x 128, tanh (`rl_cfg.py:23-24`). The actor has about
  189 thousand weights by my arithmetic (1343 x 128 + 128 x 128 + 128 x 6 plus biases; not read off
  a
  model).
- The 1343 inputs are first **normalised** with running means and standard deviations learned
  during training, stored inside the exported ONNX (`CHECKS.md:138-139`). The robot sends raw
  numbers, and the model rescales.
- **What the critic sees extra.** The actor reads groups `policy` and `tof`. The critic reads
  groups `critic` and `tof` (`rl_cfg.py:39`). The `critic` group is Pollen's walker critic terms
  (not read: contents unverified), plus the last action, zero head and body commands, and the
  **true distance to each of the 8 obstacle slots** (`env_cfg.py:86-90`, `observations.py:35`). It
  is also noise-free (`enable_corruption=False`, `env_cfg.py:105`). The actor must act from noisy
  sensor readings, but the critic may see the truth, because it is only a training aid. This is
  called an **asymmetric actor-critic**: a better baseline, with nothing leaking into the deployed
  model.

## The Beta distribution head

The actor does not output an action; it outputs the parameters of a distribution, and the
environment gets a sample.

For each of the three actions the network emits two logits `a` and `b`. They become:

```text
alpha = softplus(a) + 1          beta = softplus(b) + 1          (beta_head.py:29-32)
sample x ~ Beta(alpha, beta), in (0, 1)         action = -1 + 2 x      (beta_head.py:42-43)
mean of the action = 2 * alpha / (alpha + beta) - 1
```

`softplus` is a smooth positive function, so `alpha` and `beta` are always at least 1. The Beta
distribution lives only between 0 and 1, so the action is mapped onto [-1, 1] and can never leave
it.

Why Beta and not the usual Gaussian? The commonly cited reason (not stated in our code): the
residual is bounded, [-1, 1]. A Gaussian sample can fall outside and has to be clipped, so many
samples pile up at the ends and the probability the network is trained on no longer matches what the
robot did. A Beta has no mass outside its range, so the sample, the probability and the action are
one and the same. Having `alpha, beta >= 1` also keeps the density single-peaked: never "either
full brake or full forward".

Some useful numbers:

- When `alpha = beta`, the mean is 0: the residual is 0 and the command equals the request. A
  freshly
  initialised network is therefore close to "do what the follower says", plus noise.
- For `alpha = beta = a`, the spread of the action (its std) is `1 / sqrt(2a + 1)`. With logits near
  0,
  `a` = 1.69 and the std is about 0.48. The smoke run's `Policy/mean_std` of 0.41 at iteration 19
  corresponds to `a` of about 2.5: slightly more confident. This is my arithmetic assuming
  symmetric heads, and the std is the mean over the three actions.
- A residual std of 0.48 of the limits is a lot of noise in the command: 0.17 m/s forward (limit
  0.35),
  0.06 m/s sideways, 0.36 rad/s turn. Since the command can never exceed the request, the forward
  noise mostly shows up as random slowing.

### The brake guard

At deployment we do not sample. We take the mean, and the exported ONNX contains two safety nets
(`beta_head.py:88-105`):

- If the forward head's `alpha` and `beta` both round to exactly 1.0 (a numerically collapsed head:
  the logits so negative that `softplus` underflows) the forward output is forced to -1.
- If any logit or the denominator is not finite, the whole output is the brake, (-1, 0, 0).

A forward residual of -1 gives `request - 0.35`, clamped at zero by the action: the command stops
(through the slew limit, so within a fraction of a second). So "the model is broken" means "brake",
not "freeze with the last command".

Two limits found in the checks (`CHECKS.md:148-157`), both of which the navigator-side plugin
has to cover:

- A collapsed forward head alone gives (-1, lateral mean, yaw mean), not a full brake. Only a
  non-finite logit gives (-1, 0, 0).
- An infinite input does not brake: `tanh` saturates and the logits stay finite. Only NaN reaches
  the brake. So `plugins/learned.py` checks inputs and outputs for non-finite values itself.

## What to remember

- Policy gradient: raise the probability of actions that scored above expectation.
- A critic subtracts the expected score; GAE (lambda 0.95, about 19 steps) balances noise and bias.
- PPO's clipping (0.2) limits how far one batch can move the policy; 5 epochs x 4 minibatches is
  20 gradient steps per iteration on 98,304 samples.
- The Beta head keeps actions inside [-1, 1]; zero residual is the starting point; the brake guard
  turns a broken model into a stop.

Next: [our task](the-task.md).
