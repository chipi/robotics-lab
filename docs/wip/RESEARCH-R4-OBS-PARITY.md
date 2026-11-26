# Research R4: the learned controller's observation against what microduck-nav trains on

**Status:** checked 2026-11-26. Activity R4 of `RESEARCH-LEARNED-AVOIDANCE.md`: until the vector the
navigator builds is the one the model trained on, a model of ours (R6) means nothing there. The
training code is the reference. No simulator and no DGX were run; the training side ran on one
CPU environment (about 10 s).

**Sources.** Training: `chipi/microduck-nav` at `6d39ceb` (`observations.py`, `action.py`,
`commands.py`, `tof_sensor.py`, `tof_geometry.py`, `impairments.py`, `env_cfg.py`, `rl_cfg.py`,
`residual_action.py`), with Pollen's terms it takes from the registered task
(`mjlab_microduck/tasks/microduck_velocity_env_cfg.py`, `mdp.py`) and mjlab 1.3.0's observation
manager and circular buffer. Deployment: `robots/duck/src/duck_lab/plugins/learned.py`, fed by
`nav/run.py`'s range buffer and `plugins/tof8x8.py`.

**The proof.** `microduck-nav/tests/fixtures/obs_parity.json` holds five constructed states and the
1343 numbers the training code builds from each, written by `scripts/export_obs_parity.py` from the
task's own observation functions on a one-environment CPU env (`obs_parity.py`). Its test rebuilds
them and fails if the training code drifts. A copy is in `robots/duck/tests/fixtures/`;
`test_local_controller.py` feeds the same states through `learned.observation` for both profiles
(the simulator's radial ranges and the real duck's axial ones) and asserts every slot within 1e-6.

## The actor's 1343

The actor reads two groups in this order (`rl_cfg.py`: `obs_groups actor = (policy, tof)`): `policy`
53, `tof` 1290. The model normalises its own inputs (`obs_normalization=True`, inside the ONNX), so
the deployment feeds raw values: no clipping or scaling is applied anywhere in the observation
(every term has `clip=None`, `scale=None`; checked on the built env).

| Slots | Training source | Deploy source | Match |
| --- | --- | --- | --- |
| 0-2 | `base_ang_vel`: trunk angular velocity in the body frame, rad/s (`root_link_ang_vel_b`, rotated by a per-env IMU misalignment of up to 6 degrees) | `body.imu.gyro` as is | Yes, for a gyro in the body frame; the frame of robotd's gyro is not checked here |
| 3-5 | `projected_gravity`: (0, 0, -1) rotated into the body frame (`quat_apply_inverse(root quat wxyz, g_w)`): upright is (0, 0, -1), a nose-down pitch of 10 degrees gives +0.174 on x | `rotate(conj(q), (0, 0, -1))`, q = `body.imu.quat` as w, x, y, z | Yes (the tilted and walking fixture states; the unit-length quaternion is assumed) |
| 6-19 | `joint_pos`: encoder reading (servo plus its backlash hinge, plus a per-env bias) less the default pose, rad, 14 servo joints | `body.joints` less `DEFAULT`, 15 joints of robotd less the mouth | Yes: same 14 and order (hip_yaw, hip_roll, hip_pitch, knee, ankle left; neck_pitch, head_pitch, head_yaw, head_roll; the same five right), same default pose to 1e-6 (asserted against the env) |
| 20-33 | `joint_vel`: servo plus hinge velocity, rad/s, read one control step late (lag 1, noise +-0.25) | `joint_velocity`: the previous tick's `body.velocities` less the mouth | Yes in value and order; the lag is one tick (0.1 s), not one step (0.02 s): see the rate |
| 34-36 | `actions`: `env.action_manager.action`, the three residuals the policy last sent, clipped to [-1, 1] | `previous_action`: the model's last output, clipped | Yes; zeros after a tick the model did not run on (training has no such tick) |
| 37-39 | `command`: the request (vx, 0, wz) from `NavigationCommand` (vy is always 0) | `(requested.vx, 0, requested.vyaw)` | Yes |
| 40-49 | `head_command` (4) and `body_command` (6): zeros | zeros | Yes |
| 50-52 | `applied_command`: the command after the residual, limits and slew (`residual.previous`), including the lateral | `(applied.vx, 0, applied.vyaw)`: the command sent last tick, after the guards | Partly: the lateral is always 0 here, see below |
| 53-1332 | `tof/ranges_and_validity`, history 10: oldest first, one entry per control step, each 64 depths then 64 valid flags (term-major: all ten of these, then all ten ages) | ten entries oldest first, each 64 then 64 | Yes, after the two fixes below |
| 53-1332, a depth | the delivered frame: optical-axis depth in metres (`radial * direction.x`), 0 where invalid; zones row-major, row 0 the top, column 0 the sensor's left, Pollen's equal-angle grid (or NVIDIA's pinhole, drawn per episode) | `distance_mm / 1000 * axial factor`; zones row-major in the same order (checked against `zone_directions("equal_angle")`: elevation falls and azimuth falls with the index, to 1e-6) | Yes, after the fix: the simulator's `range_kind` is radial |
| 53-1332, a flag | `isfinite & 0.12 <= depth <= 4.0` of the delivered depth | the status is a valid one and `0.12 <= depth <= 4.0` of the axial depth | Yes; the status test is extra and only removes returns the training never delivers |
| 1333-1342 | `tof/age`, history 10, oldest first: `env_time - delivered_time`, seconds; before the first frame, 1 s plus the time since the reset | per step: the frame's age now less the step's offset; 1 s for a step with no frame | Yes, except the 1 s of a step with no frame is exact only at the reset (up to 0.06 s short in the first steps) |

Not an observation but part of the contract, checked in the same pass (the table in
`RESEARCH-R1-R2.md` section 1.1 and `residual_action.py` against `learned.ResidualCommand`): the
limits (0.35, 0.12, 0.75), the clamp order, the speed cap by the request, the slew (1, 1, 3) per
second, the lateral ratio 0.35, the zero on a zero request, a missing frame or a frame older than
0.25 s: the same, line for line.

## Where it differed, and the fix

1. **Radial against axial ranges (slots 53-1332).** Training sees optical-axis depth; the
   simulator's sensor reports the distance along each beam (the profile's `range_kind: radial`),
   and `learned.py` fed it as it came: a zone at the edge of the 45 degree view read up to 13 % too
   far, and the 0.12 and 4 m bounds were applied to the wrong number. Fixed: `axial_factors`
   multiplies each zone by its beam's forward component when the sensor is radial, and leaves the
   real duck's axial ranges alone; the bounds are judged on the axial depth, as training does.
2. **The history's spacing (slots 53-1342).** `learned.py` spaced the ten entries by the navigator's
   tick (0.1 s), so the model saw one second of the sensor where it trained on 0.2 s (ten steps of
   0.02 s), and the ages ran in the wrong steps. Fixed: the entries are spaced by `MODEL_STEP_S`
   (0.02 s, the env's `step_dt`, asserted equal to it), each taking the newest frame that had
   arrived that long ago and its age then.
3. **The joint velocities across a pause (slots 20-33).** They were kept only on the ticks the model
   ran on, so the first tick after a stop read velocities from before it. Fixed: kept every tick.

Before the fixes, the parity test failed in 4 of the 5 states for each profile (for example the
worst slot of the walking state read 1.64 against 0.0, a depth taken from the wrong history entry);
after, all 10 pass, the worst slot off by 1.2e-7.

## What does not match, and what R4 must account for

- **The control rate.** The model was trained at a 50 Hz policy step (`step_dt` 0.02: decimation 4
  of 5 ms), and the walker beneath it runs on every step. The navigator ticks at 10 Hz
  (`run.TICK_S`, `Learned.tick_s` 0.1). So the model is asked 5 times less often, and everything
  per step in training is five times as long here: its action is held for 0.1 s, the previous
  action and the applied command it reads are 0.1 s old, the joint velocity is 0.1 s late instead
  of 0.02 s, and the ten history entries are rebuilt at 0.02 s from the frames kept (the sensor is
  15 Hz, so three or four entries share a frame, as in training). The slew is not affected: the
  residual limits a command to 1, 1 and 3 per second, and `ResidualCommand(dt = tick_s)` moves 0.1
  of that per tick where training moves 0.02, the same rate over time. The 10 Hz is not fixable in
  the observation. R4 must either run the learned controller on its own 50 Hz loop, or accept that
  the policy meets a slower loop than it learned in and check the avoidance does not degrade (the
  R4 comparison itself: rules against learned at the same 10 Hz).
- **No lateral command.** The duck's `Twist` is (vx, vyaw). The model's lateral residual
  (limit 0.12 m/s) is computed and dropped, and the applied command's lateral, which training feeds
  back (slots 51), is 0 here. A model that learned to sidestep loses it; one that learned to brake
  and turn does not.
- **Age is arrival, not capture.** Training's age counts from the frame's capture, including 0 or 1
  frames of transport delay (up to 67 ms). The navigator stamps a frame on arrival
  (`time.monotonic()` in `run.py`), so its ages are shorter by that delay.
- **The start of an episode.** Training's age before the first frame is 1 s plus the time since
  the reset, 1.02 to 1.06 in the first steps; the navigator uses 1.0.
- **No training noise, delay or misalignment.** The training adds noise to the IMU, joints and
  velocities, a lag of 0 or 1 step to the gyro and gravity, a per-env IMU mounting rotation of up
  to 6 degrees and an encoder bias of +-0.015 rad. The fixture switches them off (a deployed
  sensor brings its own); the model is trained to tolerate them. The real board's systematic
  pitch offset of about 5 degrees is corrected in robotd's runtime, outside this repository (R8).
- **A skipped tick's action.** When the model is not run (stale frame, zero request), the previous
  action is zeros; training always has an action.

## Outcome, 2026-11-26: each model at the rate it trained at

microduck-nav now trains two models (its `docs/M2.md`): M2a `Mjlab-Nav-MicroDuck` (50 Hz
policy step, lateral limit 0.12) and M2b `Mjlab-Nav-Deploy-MicroDuck` (10 Hz, five walker
steps per action, lateral 0). `learned.py` runs either:

- **The rate and the lateral limit come with the model.** Order: the ONNX `metadata_props`
(`task`, `policy_step_s`, `lateral_limit`,
  `obs_layout`; microduck-nav writes them at export since `57de640`), then a sidecar
  `<model>.onnx.json`, then `--model-rate 50|10` (`model_rate` in the run's setting). The first
  that exists decides; a flag that disagrees with it is refused; a model with none is refused,
  naming the three. Metadata or a sidecar with only one of the two numbers is refused, not
  completed from a lower source.  The checkpoints trained before the export wrote metadata
  need the sidecar or the flag; the sidecar for M2a is `{"task": "Mjlab-Nav-MicroDuck",
  "policy_step_s": 0.02, "lateral_limit": 0.12, "obs_layout": "nav-1343-v1"}` and for M2b
  `{"task": "Mjlab-Nav-Deploy-MicroDuck", "policy_step_s": 0.1, "lateral_limit": 0.0,
  "obs_layout": "nav-1343-v1"}`.
- **The history is spaced by the model's own `policy_step_s`** (0.02 s or 0.1 s), and
`ResidualCommand` takes its lateral bound from the
  model. `tests/fixtures/obs_parity_deploy.json` (the 10 Hz task's five states) is checked in
  `test_local_controller.py` beside the 50 Hz one, both profiles, all 1343 slots within 1e-6.
- **The run records it**: the calibration event's `local_controller.model` carries `task`,
`policy_step_s`, `lateral_limit`,
  `obs_layout` and `spec_source` (metadata, sidecar or flag) beside the sha256 and the IO. The
  build identity stays `ctrl@learned@<sha8>`: the sha8 already names the file, and the rate
  is the file's.
- **A float32 fix the 10 Hz fixture found.** A radial zone whose axial depth is exactly 4.0
m came back as 4.0000000000000004 after the
  millimetre round trip and was judged out of range (slot 610 of the long-history state,
  0 against 4.0). The bounds are now judged on the float32 depth, as training does.

The 10 Hz mismatch listed above ("The control rate") is therefore gone for an M2b model:
the navigator's 0.1 s tick is its policy step.  For M2a it is unchanged. Not covered: no
trained M2a or M2b model has run at the navigator; `--model-rate` is not yet plumbed through
`labrunner`'s own copy of the options (`labrunner.remote`).

## Not covered

- The ONNX itself: no trained model exists yet, so the parity is of the input; the network, the
  Beta head and the normaliser are not exercised. The fixture checks 1343 numbers, not 3 outputs.
- The sensor's frame and the IMU's frame on the simulated duck: the fixture sets the IMU values and
  the quaternion directly; that robotd's gyro is in the body frame and its quaternion rotates body
  to world is assumed from `tof8x8.py`'s own use of it, not measured.
- The equal-angle grid only: a model trained on `grid: mixed` also sees NVIDIA's pinhole grid on half
  its episodes (edge zones at 19.9 degrees, not 19.69), which the simulated duck never emits.
- Frames the training never delivers (a nonzero range with an invalid status), and a non-unit
  quaternion: the deployment drops the first and does not normalise the second.
- The real duck: `learned.py` refuses it until R8, and its sensor's `range_kind` is not measured.
- Any behaviour: this is the vector in, not the duck's walk.

## Regenerating

In `microduck-nav`: `uv run python scripts/export_obs_parity.py` writes
`tests/fixtures/obs_parity.json`; copy it to `robots/duck/tests/fixtures/`. The states and the
frames' ages are in `obs_parity.py`; add a state there, not by hand in the JSON.
