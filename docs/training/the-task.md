# 3. Our task: what the network sees, does, and trains in

!!! abstract "By the end of this page"
    You know the 1343 inputs and the 3 outputs, what Pollen's walker does between them and the
    motors, what worlds the duck is dropped into, and how an episode ends.

The task is called `Mjlab-Nav-MicroDuck` (all layouts and sensor impairments) and
`Mjlab-Nav-OneWall-MicroDuck` (the M1 version: one wall, no impairments); see `tasks.py:11-21`. It
is NVIDIA's Microduck obstacle-avoidance task, ported from their Isaac Lab to mjlab so that it
trains against Pollen's walker. What follows NVIDIA's design is listed at the top of
`env_cfg.py:1-7`: the scene, observation groups, action, command, rewards and weights,
terminations, 20 s episode and 14 m spacing.

## What an episode is

1. The duck is reset near the origin (within +-0.15 m), facing a random direction
   (`env_cfg.py:156`).
2. Obstacles are placed, in the duck's own frame, so that "ahead" is where it faces.
3. A **destination** is fixed 2.6 m away (`layouts.py:56`, `commands.py:110`), usually in the
   direction of the obstacle in front, so that the straight line is blocked and going around is the
   job. For a passage, the destination is the midpoint of the gap.
4. A **requested speed** is drawn once from U(0.2, 0.35) m/s (`commands.py:35`, `:111-112`).
5. Every control step, the **request** is computed as a joystick-like command that steers to the
   destination:

   ```text
   vx    = speed * max(cos(heading error), 0) * min(distance / 0.5, 1)
   vy    = 0
   vyaw  = clamp(1.5 * heading error, -0.75, 0.75)       (commands.py:123-125)
   all zero once within 0.2 m of the destination (commands.py:122, 126)
   ```

6. The policy sees that request and the sensor, and outputs a **residual** on it. The result goes
   to the walker. The request has no idea about obstacles; the policy's job is to bend it.
7. The episode ends at 20 s, or earlier on a collision, a fall or leaving the field.

The request is a stand-in for what our own follower sends ("walk 0.30 m/s, turn 0.2 rad/s"). In
training it is a clean, smooth function of the destination. The real follower's command is not.
That is one of the input differences listed on [page 7](glossary-and-next.md).

## The observation: 1343 numbers

The actor's input is two groups joined, `policy` (53 numbers) and `tof` (1290), `env_cfg.py:77-106`.
The order, from the deployment side (`learned.py`'s `observation`, and R1 section 1.2):

| Index | Width | What | Why the network gets it |
| --- | --- | --- | --- |
| 0-2 | 3 | Gyro: body angular velocity | How fast it is turning or toppling |
| 3-5 | 3 | Projected gravity: the down direction in the body frame | Tilt |
| 6-19 | 14 | Joint positions minus the default pose | The body's own posture |
| 20-33 | 14 | Joint velocities | Motion; the deployment reads them one tick late, as in training |
| 34-36 | 3 | The previous action (the last three residuals) | What it just did |
| 37-39 | 3 | The request: vx, vy, vyaw | The goal of the moment |
| 40-49 | 10 | Zeros (4 head pose, 6 body pose commands) | Walker inputs held at zero (`env_cfg.py:82-83`) |
| 50-52 | 3 | The applied command: what was actually sent last step, after limits | The residual's own output, after the slew |
| 53-1332 | 1280 | Ten time steps, oldest first, each 64 depths then 64 valid flags | What the sensor saw, with a flag for which returns are real |
| 1333-1342 | 10 | The age of each of the ten frames, in seconds | How stale each frame is |

Check on the arithmetic (`env_cfg.py:77-84`): 34 body numbers + 3 + 3 + 4 + 6 + 3 = 53 for `policy`;
10 x (64 + 64 + 1) = 1290 for `tof`; 53 + 1290 = 1343. The ordering of the history was checked in
mjlab: it is flattened term by term, oldest first (`mjlab observation_manager.py:351-356`,
`utils/buffers/circular_buffer.py:162-168`).

### Why history matters

The network is a feed-forward MLP. It has no memory of its own. The observation is its whole past,
and the history is the only memory it has. There are four reasons it needs it.

- **One depth frame is a still photograph.** To tell an obstacle that is getting closer from one
  that is standing still, the network needs two frames and the time between them.
- **The sensor is slow and the control is fast.** The ToF runs at about 15 Hz and the control at
  50 Hz, so about three control steps in a row see the same frame. The ages say which numbers are
  fresh. NVIDIA's comment: 200 ms "covers about three distinct 15 Hz frames at the 50 Hz control
  rate" (R1 section 1.2).
- **Sensors lie.** A zone that is invalid in one frame may be fine in the next. A short history
  lets the network average noise and drop-outs.
- **It must know its own motion.** The previous action, the applied command and the joint
  velocities say how the duck itself has been moving, so it can separate its own motion from the
  world's.

The consequence, which I infer from the architecture and have not tested: anything that left the
sensor's view more than 0.2 s ago is forgotten. The sensor's field of view is 45 degrees. A box the
duck has just passed, at its side, is invisible and not remembered. A learned controller that is
clean about what is ahead can still clip a corner behind it. This is where a map-aware layer (our
planner and its occupancy grid) does what this network cannot.

### The critic's extra view

The critic additionally gets the true clearance to every obstacle and noise-free state
(`env_cfg.py:86-90`, `observations.py:35`). It is a training aid, not part of the model on the
robot ([page 2](ppo.md)).

## The action: a residual on the request

The network outputs three numbers in [-1, 1]: forward, sideways, turn. They are **residuals**: a
correction added to the request, not a command on their own. A residual of zero means "do what the
follower said". This is one of the best things about the design: a freshly initialised network
(residual near 0) already behaves like the rules and learning only has to improve on that.

The function that turns the residual into the command is `ResidualCommand.process`
(`residual_action.py:36-58`). Step by step, with the numbers from `action.py:45-48`:

```text
1. cmd = request + clip(action, -1, 1) * (0.35, 0.12, 0.75)       limits: m/s, m/s, rad/s
2. forward  clamped to [0, 0.35]      no reversing
   sideways clamped to [-0.12, 0.12]
   yaw      clamped to [-0.75, 0.75]
3. if the translation (vx, vy) is longer than the request's, scale it down to the request's length
                                                      never faster than asked
4. slew: the command may change at most (1.0, 1.0, 3.0) per second from the last one;
   at 50 Hz that is (0.02, 0.02, 0.06) per step
5. sideways clamped to 0.35 x forward                 a duck does not walk sideways at a standstill
6. STOP, ignoring the slew, if the request is all zero, or no frame has ever arrived,
   or the newest frame is older than 0.25 s           the stale stop
```

A worked example (my arithmetic). The request is (0.30, 0, 0.20), the previous command (0.30, 0,
0.20) and the network says (-0.5, +0.2, +0.1):

- Step 1: forward 0.30 - 0.175 = 0.125; sideways 0.024; yaw 0.20 + 0.075 = 0.275.
- Step 3: the translation (0.127 m/s) is below the request's 0.30, so nothing to scale.
- Step 4: forward may fall only 0.02 this step, so 0.28; sideways rises to 0.02; yaw to 0.26.
- Result: (0.28, 0.02, 0.26). The brake is applied gradually: to slow from 0.30 to 0 takes 15
  steps, 0.3 s.

What each limit buys:

- **Limits (0.35, 0.12, 0.75).** The residual can bend the request a lot in yaw (0.75 rad/s is
  also the whole range of the request's yaw) and little sideways: the duck is not built to
  side-step.
- **Never faster than asked.** The network can brake and steer, but cannot speed up; the worst
  an untrained or broken network can do is slow down.
- **Slew.** Without it, a policy that outputs noisy residuals would send the walker jittering
  commands. The `command_rate` reward penalises this too ([page 4](rewards.md)).
- **Stale stop.** If the sensor dies, a learned controller does not keep steering on frozen data;
  the command goes to zero within a step.

One known quirk (`CHECKS.md:175-177`): the speed cap acts before the slew, so after a request
drops (0.3 to 0.1), the command can still be above the new request for a few ticks (0.28 on the
first). The same order is in NVIDIA's code and in the deployment script.

## Pollen's walker, inside the action term

The command is not the end. It goes into **Pollen's walker**, a frozen neural network that turns
"walk at this velocity" into joint angles. Without the walker the controller would have to learn
to walk; this way it learns only to steer.

```text
 request + residual --> ResidualCommand --> command (3)
                                              |
 walker input (61) = [ body proprioception (34), the walker's own last output (14),
                       command (3), zeros (10) ]            (action.py:92-93)
                                              |
 walker network: 61 -> 512 -> 256 -> 128 -> 14, ELU activations        (CHECKS.md:96-97)
                                              |
 14 joint offsets, added to the default pose, as joint position targets
```

The walker is fixed: its weights have `requires_grad` off (`walker.py:27-28`), and it is the exact
file the real duck runs (`velstand.onnx`, SHA-256 beginning `ce894d30`, policies v10). Because the
original ONNX takes a batch of one, we rebuild it as a torch module that works on 4096 envs at once;
the rebuilt module matches the ONNX to 5e-5 (`CHECKS.md:12`).

**The walker has limits, and they become the controller's limits.** The check on CPU, mjlab physics
(`CHECKS.md:110-117`):

| Asked (m/s) | Got (m/s) | Got / asked |
| --- | --- | --- |
| 0.10 | 0.005 | 5 % |
| 0.15 | 0.034 | 23 % |
| 0.20 | 0.092 | 46 % |
| 0.30 | 0.142 | 47 % |
| 0.40 | 0.193 | 48 % |

- Above 0.2 m/s the walker delivers about 46 to 48 % of the asked speed. Below 0.2 it mostly does
  not walk. (One seed, flat floor, 10 s runs.) Pollen's own figures agree: about 44 %, and no
  walking below about 0.2 m/s (`docs/wip/MICRODUCK.md:105-108`).
- This is why the request's minimum is 0.2 m/s (`commands.py:35`; NVIDIA's is 0.15). Our walker
  does not walk at 0.15, so a residual has no effect there.
- To reach a 2.6 m goal inside 20 s the duck needs about 0.14 m/s of actual speed, so about 0.28 m/s
  requested or more (2.6 / (0.46 x 20)). Perhaps half of the draws from U(0.2, 0.35) can arrive at
  all (my arithmetic, not measured). This is why the one-wall milestone M1 does not ask for arrival.
- Since the residual cannot exceed the request, the policy cannot make up for the walker's 46 %. The
  speed ceiling belongs to the walker. Retraining it is [an opportunity](opportunities.md).

## Layouts: the worlds

There are ten families of obstacle layout (`layouts.py:29`). Each episode in the full task draws
one at random using these weights (`layouts.py:31-41`, NVIDIA's mix):

| Layout | Weight | What it is (from the sampling code; I have not drawn them) |
| --- | --- | --- |
| `scattered` | 0.65 | A cluttered room: six props in two rows of three, plus two far walls |
| `open` | 0.10 | Nothing in the way: a check that it simply walks |
| `barrier` | 0.10 | One obstacle ahead on the straight line to the goal |
| `passage` | 0.05 | Two walls with a gap to pass through; in half of them the walls stand wider apart and an obstacle sits in the way |
| `thin_low` | 0.05 | A thin post and a low block, close together |
| `corner` | 0.03 | A front obstacle with one wall beside it |
| `blocked` | 0.02 | A front obstacle with a wall on each side: a pocket |
| `ring`, `slalom` | 0 | Written, but off in the mix |
| `one_wall` | not in the mix | Only for M1: one 1.8 m wall across the approach, 0.6 to 1.0 m ahead |

Eight obstacle "slots" exist in every environment: `obstacle` (a post 0.11 m radius), `crate`,
`tall_box`, `low_block`, `cylinder`, `thin_post`, `wall_left`, `wall_right` (`obstacles.py:47-54`).
Each layout places some of them and parks the rest 5 m under the floor. The robot's own
radius for clearance maths is 0.12 m (`nav_math.py:19`).

Caveats from the checks (`CHECKS.md:228-231`): the footprints of the props are NVIDIA's exact ones;
the heights of `crate`, `low_block` and `cylinder` are assumed (0.40, 0.35, 0.55 m); `cylinder` is
a box; a hand or foot touching a prop also counts as a collision.

Our own obstacles (door frames, chair legs, rugs) are not in this list. Adding them is
[opportunity R7](opportunities.md).

## Terminations: how an episode ends

Five conditions end an episode (`env_cfg.py:190-199`, `terminations.py`):

| Termination | Meaning | Counts as |
| --- | --- | --- |
| `time_out` | 20 s passed (1000 steps) | Truncation: the duck was fine. The critic's value is credited ([page 2](ppo.md)) |
| `fell_over` | Pollen's fall rule | Failure: -30 |
| `nan_state` | Physics produced a NaN | Failure: -30 |
| `obstacle_collision` | Any part of the robot touched any obstacle with more than 0.1 N in any physics step of the control step (`terminations.py:16-29`) | Failure: -30 |
| `field_boundary` | The duck is more than 5 m from the origin (`terminations.py:32-34`) | Truncation, not a collision. Unpenalised |

The difference between failure and truncation is important. A failure ends the future: the value
after it is zero. A truncation does not: the value is estimated and credited. And the
`failure` reward term (-30) fires only on failures (`rewards.py:78-79`).

A collision threshold of 0.1 N is very tight: touching a box with a toe, hardly pressing, ends the
episode. The policy learns that any contact is catastrophic. That is the safe choice. It is
plausibly also part of why the early iterations look so bad (not verified): the smoke run reported a
collision share
of 0.50 at iteration 19.

## What to remember

- The request is joystick-like and ignorant of obstacles. The policy outputs three residuals.
- The residual is bounded, never faster than the request, slew-limited, and stops when the sensor
  is stale.
- Pollen's walker turns the command into joints. It delivers 46 % of the asked speed and does not
  walk under 0.2 m/s.
- The observation is 1343 numbers, mostly ten frames of depth with validity and ages; there is no
  memory beyond 0.2 s.
- Layouts are NVIDIA's mix; collisions end the episode at 0.1 N.

Next: [rewards](rewards.md).
