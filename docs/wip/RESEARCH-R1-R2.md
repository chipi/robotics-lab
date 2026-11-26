# Research R1 and R2: NVIDIA's Microduck avoidance controller, and our ToF simulation against it

**Status:** research note, 2026-11-26, read-only. Activities R1 and R2 of
`RESEARCH-LEARNED-AVOIDANCE.md`. Nothing was installed or run; no simulator was started.

**Sources read.**

- `isaac-sim/IsaacLab`, branch `exp/microduck`, commit `802b8d5` ("Stream MicroDuck body state at
  the full 50 Hz in ToF navigation (#9107)"), shallow sparse clone at
  `$HOME/.cache/robotics-lab-tests/research/isaaclab`. Paths below are relative to that clone;
  `OBS` = `source/isaaclab_tasks/isaaclab_tasks/contrib/microduck_obstacle`,
  `WALK` = `source/isaaclab_tasks/isaaclab_tasks/contrib/microduck`,
  `DEP` = `scripts/deploy/microduck_tof_nav`.
- Our side: `/work/robotics-lab/mission-control/robots/duck/...` and Pollen's
  `/work/pollen/microduck_rl` at `0daab160` (verified with `git log -1`) and
  `/work/pollen/microduck`.
- Two web fetches, both through a summarising fetch tool: the Newton README and the NVIDIA article.
  Claims resting on them are marked "(fetch)".

Marks: VERIFIED means read in code with a citation; NOT VERIFIED means not established.

## R1. The contract

### 1.1 Layering (VERIFIED)

The navigation actor is a residual on top of the commanded velocity. The walking policy is frozen
and sits below it.

- The actor outputs three numbers in [-1, 1]. The command delivered to the walker is
  `requested + clamp(a, -1, 1) * (0.35, 0.12, 0.75)`, then forward clamped to [0, 0.35], lateral
  to +-0.12, yaw to +-0.75 (`OBS/mdp/actions.py:52-59`, limits at `:96`).
- Translation speed may not exceed the requested speed (`actions.py:60-63`): the actor can steer
  and brake, never speed up.
- The command is slew-limited to (1.0, 1.0, 3.0) per second (`actions.py:65-67`, `:99-101`), and
  lateral is held within 0.35 of forward (`:68-69`, `:97`).
- An all-zero request, a missing frame, or a frame older than 0.25 s zeroes the command and
  bypasses the slew limit (`actions.py:71-76`, `:95`).
- The same function exists on the deployment side, `command_from_action`
  (`DEP/nav_pad.py:104-116`), so training and deployment share the post-processing.

### 1.2 Observation vector: 1343 inputs (VERIFIED)

Deployment layout, `DEP/nav_pad.py:59-65`, built at `:193-206`:

| Index | Width | Field | Notes |
| --- | --- | --- | --- |
| 0-2 | 3 | gyro | IMU angular velocity; training noise 0.03 (`WALK/flat_env_cfg.py:159-162`) |
| 3-5 | 3 | projected gravity | training noise 0.01 |
| 6-19 | 14 | joint positions minus default | default pose `nav_pad.py:69-87`; mouth joint dropped (`:68`, `:145-150`); training noise +-0.001 |
| 20-33 | 14 | joint velocities, one tick late | `nav_pad.py:185-186`; training noise +-0.25 and lag 1 (`flat_env_cfg.py:173-183`) |
| 34-36 | 3 | previous navigation action | the three residuals, not the walker's 14 |
| 37-39 | 3 | requested velocity (the goal or the stick) | vx, vy, wz |
| 40-49 | 10 | zeros | head pose (4) and body pose (6) commands, held at zero in training (`obstacle_avoidance_env_cfg.py:393-394`) |
| 50-52 | 3 | previous applied command | what was actually sent after limits and brake (`nav_pad.py:460-461`) |
| 53-1332 | 1280 | ToF history | ten control ticks, oldest first; each 64 ranges (m) then 64 valid flags |
| 1333-1342 | 10 | ToF frame ages (s) | one per history tick |

- The training side: actor groups are `policy` and `tof` (`OBS/agents/rsl_rl_ppo_cfg.py:34`).
  `policy` = the 61-wide walker group (`flat_env_cfg.py:155-187`) plus `applied_command`
  (`obstacle_avoidance_env_cfg.py:246-248`). The `tof` group has `history_length = 10`
  (`:253`, comment: "200 ms covers about three distinct 15 Hz frames at the 50 Hz control rate").
- ToF preprocessing (`OBS/mdp/observations.py:18-28`): a return is valid when finite and in
  [0.12, 4.0] m; invalid ranges are written as 0 and the valid flag is a separate input. "Missing
  returns are not free space" is the stated reason. Age is `sample_age`, including transport delay
  and dropped frames (`observations.py:31-33`, `sensors.py:139-141`).
- Deployment fills the first ticks with empty frames aged 1 s, "as at a training reset"
  (`nav_pad.py:191-192`).
- Normalisation is inside the ONNX: `obs_normalization=True` in training
  (`rsl_rl_ppo_cfg.py:41`); `nav_pad.py:119-142` reads `obs_normalizer._mean` and `_std` (shape
  (1, 1343)) only to warn when live inputs are over 5 standard deviations away (`:210`, `:495`).
  The statistics themselves are not in the repository (no checkpoint is published).
- The ordering of the flattened history (term-major, oldest first) is asserted by `nav_pad.py`'s
  header; Isaac Lab's own history flattening is outside the sparse clone, so that part is
  NOT VERIFIED against the framework.

### 1.3 Action vector (VERIFIED)

- Three residuals [forward, lateral, yaw] in [-1, 1] (`actions.py:52-59`).
- Distribution: Beta with full [-1, 1] support (`OBS/agents/navigation_distribution.py:47-58`).
  The exported deterministic output is the Beta mean (`navigation_distribution.py:59-63`,
  `:18-30`); a numerically
  collapsed forward head, or a non-finite output, becomes a brake (-1 forward, 0, 0)
  (`navigation_distribution.py:24-30`).
- `forward_braking_only` is False by default (`rsl_rl_ppo_cfg.py:23`,
  `navigation_distribution.py:49-52`).

### 1.4 Rates (VERIFIED unless noted)

| Item | Value | Citation |
| --- | --- | --- |
| Physics step | 5 ms | `WALK/flat_env_cfg.py:493` |
| Control / navigation policy | 50 Hz (decimation 4) | `flat_env_cfg.py:491`; `nav_pad.py:59` |
| Walker period | 4 physics-step groups, same 50 Hz contract | `obstacle_avoidance_env_cfg.py:278,392` |
| ToF acquisition | 15 Hz average (deadline scheduler keeps the sub-tick remainder), captures quantised to 20 ms scene updates | `OBS/sensors.py:83-88,164-174`; `obstacle_avoidance_env_cfg.py:213` |
| Body state on the robot | every 50 Hz robotd tick (asking for "50" drops about a third) | `DEP/relay_on_duck.py:78` |
| Episode | 20 s | `obstacle_avoidance_env_cfg.py:389` |
| Request resampling | every 3-6 s | `obstacle_avoidance_env_cfg.py:313` |

### 1.5 Sensor model: exact parameters (VERIFIED)

Mount and geometry, `obstacle_avoidance_env_cfg.py`:

- Mount position `(-0.0176, 0.0, -0.083)` m in the head body, 0.22 m above flat ground at the
  default 0.125 m root height (`:57-58`); rotation 55 degrees about y, "optical axis 20 degrees
  down at the home neck/head pitch of +0.3491 rad" (`:60-61`).
- 45 degree square FOV, 8x8 pinhole pattern (`:63-69`, `:227-229`); max range 4.0 m (`:66`);
  FOV "not independently calibrated" (`:64`).
- The policy consumes optical-axis depth (`distance_to_image_plane`, `sensors.py:93`; comment
  at `obstacle_avoidance_env_cfg.py:210`). Ray hits use the finite visual floor mesh, not the
  collision plane (`:216-219`).
- Randomisation actually used (`:230-235`): mount pitch uniform in [-10, +10] degrees; mount
  height [-0.02, +0.02] m; floor-validity midpoint offset [0, 0.13] m; near-floor edge
  impairment probability 0.5. Everything else is the class default below.

Defaults, `OBS/sensors.py:27-78`:

| Impairment | Parameter | Value | Line |
| --- | --- | --- | --- |
| Range gate | minimum_distance, max_distance | 0.12 m, 4.0 m; checked before and after noise | 42, 282 |
| Episode bias, all zones | distance_bias | U(-0.02, +0.02) m | 44 |
| Per-zone bias, per episode | zone_bias | U(-0.01, +0.01) m | 46 |
| Scale | distance_scale | U(0.98, 1.02) | 48 |
| Noise, per acquisition | noise_std (episode base) + fraction of depth | U(0.003, 0.01) m + 0.008 x depth | 50-52, 278 |
| Invalid zone, non-floor | invalid_zone_probability | 0.03 per zone per acquisition ("uncalibrated generic prior") | 54-59 |
| Frame dropout | frame_dropout_probability | 0.02 per acquisition; last frame is retained and keeps ageing | 40-41, 253-264 |
| Latency | latency_frames | integer U{0, 1} acquired frames per episode (0 or about 67 ms) | 38-39, 206-209 |
| Floor validity (far) | sigmoid, midpoint 0.556 m + episode shift, width 0.015 m | floor hits at or under 0.55 m are valid; beyond, dropout = sigmoid; 16 % valid at 0.58 m, almost never beyond 0.65 m at zero shift | 70-78, 292-297 |
| Near-floor edge impairment | one outer column (left or right, uniform) is attenuated for the episode with probability 0.5; per-acquisition survival U(0.02, 0.55) | applies to floor hits between 0.12 and 0.55 m | 60-67, 214-219, 298-301 |
| Mount | pitch and height offsets re-drawn at each reset | see above | 223-240 |

Honesty notes from the code itself: the edge mixture and persistence "are not fitted hardware
frequencies or timing" (`sensors.py:62-65`), the floor sigmoid is "provisional" and "a sensor/
material prior" (`:68-78`), and the generic dropout is "an uncalibrated generic prior" (`:55`).
These are stress augmentations, not measurements.

Self-hits and the rest of the body: not described in the sensor adapter; NOT VERIFIED whether
the ray targets include the robot (the mesh list is floor plus the eight obstacles,
`obstacle_avoidance_env_cfg.py:215-226`, so the robot's own beak is not a ray target).

### 1.6 Obstacle generation (VERIFIED)

- Eight scene objects with fixed slots and footprints (`obstacle_avoidance_env_cfg.py:74-83`,
  cells `OBS/mdp/events.py:16-25`): a traffic cone scaled to 0.2286 x 0.2286 x 0.3048 m
  (`:150-156`), a cardboard box, a bin, a bedside table (SimReady assets), a thin post, a
  low box 0.4 x 0.3 x 0.12 m, and two 0.12 x 0.9 x 0.65 m walls. Six props are shuffled among
  poses each reset (`:408`).
- Nine layout families, weights (`obstacle_avoidance_env_cfg.py:291-301`): scattered 0.65, open
  0.10, barrier 0.10, passage 0.05, thin_low 0.05, corner 0.03, blocked 0.02, ring 0, slalom 0.
  Scattered course: six props in two rows at 0.8 m and 1.7 m forward, columns 1.15 m apart,
  lateral row offsets 0.15-0.35 m, half of courses aligned on the goal corridor, lateral walls
  at 2.2-2.5 m (`events.py:342-368`). Passage corridor half-gaps 0.20-0.55 m, or 1.0-1.15 m with
  one prop inside (`events.py:230-234,306-321`). Blocked: front wall 0.55-1.05 m ahead,
  half-gap 0.70-0.80 m (`:283-299`).
- Spawn: robot pose jitter +-0.15 m, yaw full circle (`obstacle_avoidance_env_cfg.py:395-400`);
  pushes every 5-10 s up to 0.1 m/s (`:401-402`).
- Command source: all episodes are "destination" episodes, a fixed world point 2.6 m ahead with
  0.2 m tolerance (`mdp/commands.py:244-255`); the stick-like request steers toward it with
  heading gain 1.5, speed U(0.15, 0.35), forward-only (`commands.py:149-171`,
  `obstacle_avoidance_env_cfg.py:310-322`). No routing around obstacles is given to the actor
  (`commands.py:97-98`).
- Field limit 5.0 m radius, truncating (not collision) (`env_cfg:410`, `terminations.py:28-30`).

### 1.7 Rewards and terminations (VERIFIED)

Weights, `obstacle_avoidance_env_cfg.py:326-350`:

| Term | Weight | What it does (`OBS/mdp/rewards.py`) |
| --- | --- | --- |
| progress (gated) | +5.0 | requested-direction progress in [-1, 1], times (1 - approach risk) when positive (`:199-210`) |
| goal_arrival | +30.0 | once on safe entry within 0.2 m, revoked on later failure (`:27-51`) |
| barrier_bypass | +5.0 | once for passing the first blocking obstacle on one side (`:54-196`) |
| yaw_tracking | +4.0 | exp tracking, std 0.35, gated by path clearance 0.25 m and progress (`:229-236`) |
| command_tracking | +1.0 | exp tracking, std 0.15, same gate (`:213-226`) |
| approach (risk) | -4.0 | closing speed vs. braking margin, safety distance 0.2 m, horizon 2 s, plus commanded risk weight 1.0 (`:245-292`) |
| command_rate | -5.0 | mean squared change of executed commands over limits (`:295-299`) |
| failure | -30.0 | on termination, exactly 30 (`terminated_penalty`) |
| ungated_progress, clearance, upright | 0.0 | present, switched off |

Terminations: walker-inherited ones (fall) plus `obstacle_collision`, contact force above 0.1 N
on the trunk filtered to obstacles (`OBS/mdp/terminations.py:18-24`), plus field boundary as a
timeout (`:28-30`). Robot footprint radius for clearance 0.12 m (`OBS/mdp/geometry.py:84-91`).

### 1.8 Training config (VERIFIED, plus article claims marked)

- Task id `IsaacContrib-ObstacleAvoidance-Flat-MicroDuck` (`OBS/__init__.py:15-19`); backlash
  robot via `presets=backlash`.
- PPO via RSL-RL: actor MLP [128, 128], tanh, observation normalisation, Beta distribution;
  critic gets privileged state plus per-obstacle clearance (`rsl_rl_ppo_cfg.py:38-43`,
  `obstacle_avoidance_env_cfg.py:258-259`). `max_iterations = 1500`, `save_interval = 100`
  (`:36-37`); entropy 0.0, learning rate 3e-4 fixed, `desired_kl=None`, gamma 0.998, mirror loss
  coefficient 0.1 without data augmentation (`:46-57`); other PPO values inherited from the
  walker (clip 0.2, 5 epochs, 4 minibatches, lambda 0.95: `WALK/agents/rsl_rl_ppo_cfg.py:36-47`).
- Defaults in code are 256 environments, spacing 14 m (`env_cfg:377,411`); the 16,384 environments
  figure comes from the command line in the article, not from the code (fetch). The article's
  second recipe (4,096 environments, 3,000 iterations, about 6 h on a DGX Spark) is likewise
  article-only (fetch); NOT VERIFIED in code.
- Physics: Newton with the MuJoCo Warp solver, `njmax=96`, `nconmax=16` for the walker, raised
  to 1024 and 200 here (`WALK/flat_env_cfg.py:463-480`, `env_cfg:390-391`); collision pipeline
  buffers raised for 16 k environments (`env_cfg:413-414`).
- Hosted assets: the robot USD and cone come from Isaac Lab's public Nucleus URLs; the other props
  are SimReady packages that must be downloaded to `assets/simready` first
  (`env_cfg:48-52,161-186`).

### 1.9 ONNX inputs and outputs

- Input: one float tensor, last dimension 1343, run as `obs[None, :]`, shape (1, 1343)
  (`nav_pad.py:67,158-161,211`). The input name is taken from the file at runtime
  (`:158`), so the name itself is NOT VERIFIED; no ONNX file is available to read.
- Output: exactly one tensor, last dimension 3 (`nav_pad.py:162-163`), shape (1, 3), the
  residuals.
- Initialisers `obs_normalizer._mean` (1, 1343) and `_std`, or a Sub/Div pair with a folded
  denominator, hold the normalisation (`nav_pad.py:119-142`).
- Runtime: CPU `onnxruntime`, one session on the laptop (`nav_pad.py:157`).

### 1.10 Deployment path (VERIFIED)

```text
 duck: tofd, robotd --(relay_on_duck.py, JSON lines over ssh)--> laptop nav_pad.py (ONNX, 50 Hz)
 gamepad daemon --> padproxy_on_duck.py --> /run/robotd.sock      <--(stdin "vx vy vyaw")-- laptop
```

- State relay: read-only; subscribes to `robotd` (`robot.subscribe`, `robot.state`) and `tofd`
  (`tof.stream`, `tof.frame`) and prints JSON lines (`DEP/relay_on_duck.py:18-19,55-79`). ToF
  frames are stamped with the robot's own monotonic clock on arrival so age needs no clock sync
  (`:56`).
- Commands: the laptop writes `vx vy vyaw` lines to the proxy's stdin; the proxy sends
  `robot.move` to robotd only while the policy is on and the stick asks for forward or turning
  motion (`DEP/padproxy_on_duck.py:80-85,240-247`). Everything else from the gamepad passes
  through unchanged (`:115-144`). This is a gamepad-emulation seam, not an API of the policy.
- Caps: laptop clips the request to (0.15 m/s, 0.05, 0.75), `--max-vx` up to 0.2
  (`nav_pad.py:95,357,447`); the robot-side proxy clamps to (0.2, 0.08, 0.8) "last line of
  defence" (`padproxy_on_duck.py:45,246`).
- Brake: if the nearest valid return in the centre four columns (columns 2-5), floor rows 6 and 7
  excluded, is under `--stop-dist` (default 0.20 m), translation is zeroed (forward and lateral;
  yaw remains) (`nav_pad.py:96,221-225,455-458`, README lines 61-63).
- Stale-data stops, three layers: the command is zeroed when the ToF frame is older than 0.25 s
  or the robot state is older than 0.25 s (`nav_pad.py:114-115,215-216,453-454`); the proxy
  stops the robot when no command arrives for 0.25 s or the request is stale after 0.3 s
  (`padproxy_on_duck.py:43-44,248-254`); when stdin closes or "stop" arrives it stops and exits,
  and the gamepad daemon copy then hands control back (`:228-229,255-258`, `nav_pad.py:506-518`).
- Driving backwards bypasses navigation and the brake (README line 63, `nav_pad.py:459`).
- Fallen robot: only logged (`nav_pad.py:487`); there is no fall stop beyond robotd's own.

### 1.11 Licence

- Code: BSD-3-Clause, "Copyright (c) 2022-2026, The Isaac Lab Project Developers" (`LICENSE:3-6`,
  SPDX header in each file). VERIFIED. We may read, adapt and port the code under that licence
  with the notice kept.
- Task and MDP terms derive from Pollen's Apache-2.0 `microduck_rl` at `d424a0c` and `bae39f5`
  (`WALK/UPSTREAM.md:5-12`). VERIFIED.
- Robot assets: geometry is copyright Pollen; STL geometry and converted mesh adaptations are
  CC BY-NC-SA 4.0 (non-commercial, share-alike); MJCF/XML and export metadata are Apache-2.0;
  "code licensing does not replace the model license" (`WALK/UPSTREAM.md:14-17`). VERIFIED.
  This matches `MICRODUCK.md`, line 4.
- Props: SimReady packages from a revision-pinned Hugging Face download, and the Isaac Sim
  traffic cone from Nucleus (`changelog.d/microduck-obstacle-avoidance.added.rst`). Their licences
  were not read: NOT VERIFIED.
- Weights: the walker teacher weights of other tasks "do not declare a weight license"
  (`WALK/UPSTREAM.md:21-22`, VelStand only). For the walker checkpoint and for a navigation
  checkpoint: NOT VERIFIED (no checkpoint licence text found).

### 1.12 Is a navigation checkpoint published?

No evidence of one. NOT VERIFIED beyond the following: the clone holds no `.onnx` or `.pt`
(`git ls-files` finds only an unrelated `examples/assets/nvidia_logo_domino_poses.pth`);
`DEP/nav_pad.py:311` defaults to a local `policy.onnx` the repo does not contain; the README says
"/path/to/navigation/exported/policy.onnx" (`DEP/README.md:39,48`); and the article (fetch) says
users train it themselves, saving to
`logs/rsl_rl/microduck_obstacle_avoidance_tof_flat_backlash/<timestamp>/`. I did not search the
Hugging Face Hub or NVIDIA's S3 listing for an unreferenced file.

### 1.13 The walking policy, and how it relates to Pollen's `0daab160`

- NVIDIA's walker: the pretrained checkpoint
  `IsaacContrib-Velocity-Rough-MicroDuck_backlash_newtonmjwarp_none_rsl_rl.pt` under
  `the Isaac 6.2 S3 path .../Isaac/IsaacLab/PretrainedCheckpoints/rsl_rl/`
  (fetch of the article; the code only names the exported `policy.pt` path,
  `obstacle_avoidance_env_cfg.py:273-277`). It is trained in Isaac Lab on Newton with the
  AGILE-inspired recipe, not the `-Pollen` recipe (`docs/source/how-to/train_microduck.rst:12-20`,
  `docs/source/how-to/microduck_tasks.rst:8-10`): MLP [512, 256, 128], ELU, 61 inputs, 16,384
  environments, 50 k iterations default (`train_microduck.rst:18-19,40-46`).
- Same interface as Pollen's: 61 numbers in, 14 joint targets out
  (`flat_env_cfg.py:156`, `ActionsCfg` `:145-147`; `MICRODUCK.md` line 23). The README tells the
  user to load it into the robot's walk slot with `robotctl policy load walk` and says "Use the
  same walking policy that trained the navigation model" (`DEP/README.md:12,23`).
- Relationship to `microduck_rl`: the task configuration derives from `microduck_rl` revisions
  `d424a0c` and `bae39f5` (`UPSTREAM.md:5-8`), not `0daab160`. Whether NVIDIA's walker behaves
  like Pollen's `0daab160` walker in our MuJoCo simulator is NOT VERIFIED; there is no file
  comparing them, and I did not diff the two repositories' task code.
- Consequence: the navigation actor is trained against NVIDIA's walker dynamics (its command
  tracking, its 0.35/0.12/0.75 limits). Our robot would run Pollen's published walker.
  Nothing verified says the residual transfers.

### 1.14 Does Newton use MuJoCo Warp?

Yes. VERIFIED two ways. The Newton README (fetch, `newton-physics/newton`): "Newton extends and
generalizes Warp's (deprecated) `warp.sim` module, and integrates MuJoCo Warp as its primary
backend." Licence of Newton: Apache-2.0 (fetch). And the task code itself configures
`NewtonCfg(solver_cfg=MJWarpSolverCfg(...))` (`WALK/flat_env_cfg.py:463-480`; docs line
`train_microduck.rst:9` "Newton MJWarp"). Our `microduck_rl` uses mjlab and MuJoCo Warp
(`MICRODUCK.md` line 11). So both stacks share the solver; they do not share the environment
framework (Isaac Lab managers, `MultiMeshRayCasterCamera`, USD scenes versus mjlab).

## R2. Our simulated sensor against theirs

### 2.1 What our simulation models

The frame is produced by Pollen's simulator, not by our plugin: our `tof8x8` plugin reads and
interprets it.

- Frame source: `/work/pollen/microduck_rl/src/mjlab_microduck/sim/tof.py` at `0daab160`. One
  `mj_ray` per zone from the MJCF `tof` site (`tof.py:85-89`), 8x8 zones over 45 degrees (`:29,
  50-62`), 4.0 m range (`:30,90`), a ray beyond range or a miss is status 255 with distance 0
  (`:75-76,90-91`), a hit is status 5 (`:98`).
- Noise: Gaussian, `sigma = 0.003 + 0.02 * hit / 4.0` m, so 3 mm up close, 23 mm at 4 m
  (`tof.py:95-96`), clipped at 0; reported in whole millimetres (`:97`). No bias, scale, or
  per-zone term.
- Rate: the body server answers `{"op":"tof"}` on request (`body_server.py:344-351,429-430`); the
  `tofd` simulator loop polls it (`/work/pollen/microduck/tof/src/main.rs:160,505`), documented as
  15 Hz (`tof.py:3`, `body_server.py:347`, `robotd/src/theremin.rs:4`). The actual poll rate in
  the `duck-sim` setup is NOT VERIFIED (default `hz` value of `tofd` not read).
- Delay: none in the simulator. The frame is read from the world at request time. Downstream,
  mapd's `tof_latency_ms` defaults to 60 in the mapper (`maploc/src/mapper.rs:184`) and the
  robotd.toml line is commented at 10 (`deploy/robotd.toml:677`); that is a compensation setting
  for the real sensor, not a simulated delay.
- Mount: the MJCF site `tof` at `pos="0.0135 0.0224086 -0.0733"` in the head frame
  (`robot_allcollisions_backlash.xml:335`, same in the other variants), fixed. Our profile
  records that the simulator looks 2.5 degrees further down than the head kinematics say, with
  radial ranges, versus the real duck's 3 degrees axial (`robots/duck/profile.json:269-275`);
  the real duck's values are mapd's (`profile.json:122-127`).
- Range kind: radial (distance along each ray), whereas the real sensor's ranges are believed
  axial and NVIDIA's policy consumes axial depth (see gaps). Our plugin can convert:
  `along_beam` divides by the beam's forward component for axial profiles
  (`robots/duck/src/duck_lab/plugins/tof8x8.py:211-214`).
- Floor handling: no special case. Floor returns are ordinary ray hits; the plugin checks floor
  and drops from geometry (`tof8x8.py:269-346`, profile `look_m 0.7`, `extra_m 0.06`,
  `floor_margin_m 0.08`: `profile.json:112-117`). A zone with status 255 is read as "nothing out
  there", and below the floor line that counts as a drop (`tof8x8.py:285-290`).
- Invalid cells: only "no target" (255) beyond 4 m. There is no minimum range: a hit closer than
  0.12 m is reported valid (`tof.py:90-98`; the profile's `emergency_mm` 150 acts on it,
  `profile.json:119`).
- Navigator thresholds that consume the stream: reflex `reflex_ahead_m 0.30`,
  `emergency_mm 150` (`profile.json:119-121`; `nav/run.py:76-81`).

### 2.2 Gap table

"Cheap?" assesses adding the impairment to our simulation path (patch to Pollen's `tof.py`
through `robots/duck/sim/patches/`, or a shim on the consumer side), not a training stack.

| Impairment | Theirs | Ours | Gap | Cheap to add? |
| --- | --- | --- | --- | --- |
| Range, FOV, grid | 8x8, 45 deg square, 0.12-4.0 m (`env_cfg:63-66`, `sensors.py:42`) | 8x8, 45 deg, 4.0 m, no minimum (`tof.py:29-30,90`) | Minimum range 0.12 m missing; zone angles differ slightly (pinhole pixels vs equal-angle centres: edge zone about 19.9 vs 19.69 deg, computed, not measured) | Yes: one line (`hit < 0.12` becomes invalid) |
| Depth kind | optical-axis depth (`sensors.py:93`) | radial (`profile.json:272`, `tof.py:86-89`) | Observation shim for any ported policy must convert radial to axial (multiply by beam forward component); whether the real VL53L5CX is axial is also unchecked (`profile.json:126`) | Yes: shim, already have `along_beam` inverse |
| Rate | 15 Hz average, 20 ms quantised (`sensors.py:83-88`) | requested at 15 Hz by tofd (`body_server.py:347`); actual rate NOT VERIFIED | Likely none | Not needed |
| Noise | std U(0.003, 0.01) + 0.008 x depth, per acquisition (`sensors.py:50-52,278`) | 0.003 + 0.005 x depth (0.02/4) (`tof.py:95`) | Ours is 3 mm at zero and 23 mm at 4 m; theirs 3-10 mm plus 0.8 % of depth (about 35-42 mm at 4 m); theirs is randomised per episode | Yes: edit one expression and add an episode draw |
| Bias and scale | episode bias +-0.02 m, scale 0.98-1.02, per-zone bias +-0.01 m (`sensors.py:44-48,276-277`) | none | Missing: systematic error, which matters for floor checks (our cliff check reads 1 cm height as 4 % of a 0.25 m range, `RANGE.md:54`) | Yes in a shim |
| Invalid cells (random) | 3 % per zone per frame, non-floor (`sensors.py:54-59,289`) | none | Missing; also dropped zones must carry a status other than 255, or `tof8x8.py:285-290` reads them as "nothing there" and may report a drop | Yes, with that status caveat |
| Invalid cells (floor, far) | floor returns beyond 0.55 m fade out; midpoint 0.556 m + U(0, 0.13), width 0.015 (`sensors.py:70-78,292-297`) | none: floor valid to 4 m | Missing; their policy learns that far floor is blank; a policy trained here would see far floor our simulator never blanks. Also our drop check relies on far floor being seen. | Yes (needs floor-hit detection; rays hitting z about 0 as in `sensors.py:291`), but it changes our cliff and map behaviour, so a measured version first |
| Floor-edge column impairment | prob. 0.5 per episode, one outer column, survival U(0.02, 0.55), floor hits 0.12-0.55 m (`sensors.py:60-67,298-301`) | none | Missing; a stress augmentation based on an observation of the real sensor, not fitted | Yes, same place as above |
| Frame dropout | 2 % per acquisition, last frame retained, age grows (`sensors.py:40-41,253-264`) | none in the simulator | Missing; the navigator's stale-frame behaviour is not exercised | Yes (shim holds frame back) |
| Delay | 0 or 1 acquired frames per episode, age reported (`sensors.py:38-39,206-209`) | none in the frame; mapd compensates 60 ms by default (`mapper.rs:184`) | Missing in simulation; a ported policy expects an age input | Yes (ring buffer in the shim) |
| Mount randomisation | pitch +-10 deg and height +-2 cm per episode (`env_cfg:230-235`, `sensors.py:223-240`) | fixed MJCF site; profile pitch 2.5 deg radial (`profile.json:271`) | Missing; ours is one fixed, measured mount | Medium: needs a model edit at reset in Pollen's simulator, or a rotation in the ray cast. Not a consumer-side change, because the plugin's belief would change but not the truth |
| Nominal mount | 0.22 m high, optical axis 20 deg down at the home head pose (`env_cfg:57-61`) | site pos `(0.0135, 0.0224, -0.0733)` in head frame, quat of 90 deg about y (`robot_*.xml`); sensor about 2.5 deg below kinematics (`profile.json:271-273`) | Different sites, different robot model revisions; not comparable without a pose export | Not applicable |
| Self-hits | not modelled (ray targets are floor and obstacles, `env_cfg:215-226`) | modelled: "self-hits are reported, not filtered" (`tof.py:67-70`) | Opposite choice; ours is harsher | n/a |
| Obstacle materials | no per-material reflectance (the 3 % dropout is generic) | none | Both lack it; the real sensor's glossy/dark failures are in neither | Needs a measured model, not cheap |

### 2.3 What R2 says

- Our sensor is clean and nearly ideal: three missing real-sensor effects (random invalid
  zones, far-floor blanking, delay/dropout) and the mount spread. The simulator is therefore
  optimistic for any component that depends on depth quality, our reflex and drop stops
  included, not only a learned policy.
- The unlabelled risk is the status code: our plugin treats status 255 as "no target, clear
  space" (`tof8x8.py:285-290`), the real sensor reports other statuses for failed zones
  (`nav_pad.py:89,179` accepts only 5 and 9). Any impairment added must use a non-255, non-valid
  status, or the cliff check will read it as a drop.
- The least costly, most informative additions are in a consumer-side shim with a seeded
  generator: minimum range, noise model, bias/scale, random invalid zones with a failed status,
  frame dropout and one-frame delay. They are useful with or without learning (item 2 of
  section 5 of the plan). Far-floor blanking and mount randomisation should wait for a
  measurement from the real duck (R8), since NVIDIA's own values are priors (`sensors.py:55-78`).

## Items that change the plan

1. **R4 is blocked on a checkpoint that does not exist.** No navigation ONNX is published, so
   R4 cannot run before R6 trains one. The plan's R4 wording "if published; else R6 first"
   resolves to "R6 first". Re-order: R6 before R4, or R4 only as an observation-shim test with a
   random-weight ONNX of the right shape (1343 in, 3 out) to prove the plumbing.
2. **The walker is part of the contract.** A navigation actor is a residual over one particular
   walker's command tracking. NVIDIA trained against Isaac Lab's AGILE-recipe walker, not
   Pollen's `0daab160` policy that our duck runs. R5's evidence on our simulator, and any later
   R8 trial, would be of a mismatched pair unless R6/R7 train against our walker. That favours
   the plan's option 2 for R6 (port the task onto `microduck_rl`/mjlab) over option 1, or at
   least requires training against Pollen's walker ONNX.
3. **Porting is bigger than "add an obstacle task".** The task uses Isaac Lab managers,
   `MultiMeshRayCasterCamera`, USD SimReady assets, Newton contact sensors and a Beta
   distribution in RSL-RL. The reward and command code is plain torch (portable); the sensor
   adapter and scene are not. Newton using MuJoCo Warp (1.14) keeps the physics comparable, not
   the framework.
4. **The observation is not "depth plus state" only.** The 1343 inputs include the previous
   navigation action, the previous applied command (after our own brake and caps), and frame
   ages. A seam for a local controller (plan section 3, item 1) must carry the post-guard command
   back to the controller and the frame age with each frame.
5. **Their deployment is gamepad emulation, not a command API.** For our case the equivalent is
   our locomotion plugin's command input; the three-layer stale stop (0.25 s on frame, state and
   command) is worth copying as the guard regardless of learning.
6. **Licence:** code is BSD-3-Clause, so reading, adapting and porting is allowed with notices.
   The robot meshes are CC BY-NC-SA, which is the same restriction MICRODUCK.md already records.
   The props' and checkpoints' licences are unread; do not assume them.
7. **Do not copy NVIDIA's impairment numbers as truth.** Their own comments call the edge and
   floor-validity parameters priors. A measured profile from the real duck (R8) should replace
   them; for now they are a reasonable stress range for a simulator.
8. **Add to plan section 8 "not known":** training budgets (16,384 x 1,500 and 4,096 x 3,000)
   come from the article, not the repository; and GB10/aarch64 support is still unchecked.

## Not covered

- No checkpoint, ONNX or `.onnx.data` file was available, so the real input name, the exported
  graph, and the normalisation statistics were not read.
- No search of the Hugging Face Hub, NVIDIA S3 listings or the Isaac Lab release pages for a
  navigation checkpoint; "not published" rests on the clone and on a summarising fetch of the
  article, which may omit a link.
- Isaac Lab core (history flattening, `PreTrainedPolicyAction`, `MultiMeshRayCasterCamera`
  internals, the `terminated_penalty` function) is outside the sparse clone and was not read.
  `symmetry.py` (mirror loss) and `geometry.py` beyond its signatures were not read in detail.
- The article's training numbers and the walker checkpoint URL come from one summarising fetch,
  not a line-by-line read. The Newton README quote likewise.
- Licences of SimReady props, the Isaac Sim cone, and any checkpoint were not read.
- Whether NVIDIA's walker differs from Pollen's `0daab160` walker in behaviour: not diffed, not
  run. The task code of `microduck_rl` at `d424a0c` was not compared to `0daab160`.
- The actual `tofd` poll rate in `duck-sim`, and whether the real VL53L5CX reports axial or radial
  ranges, are NOT VERIFIED.
- Recorded simulator runs (the plan asks R2 to compare with them) were not analysed: no run
  data was opened, and the simulator was not run. The gap table is from code and profile only.
- Our consumer-side code paths beyond `tof8x8.py` (`nav/run.py`, `anomaly.py`, `side_drops.py`)
  were checked only at the cited lines; whether an added status code would trip other readers
  was not traced.
- Cost and effort of each "cheap" rating are judgements from code size, not estimates from
  trying.
- Edge-zone angle numbers (19.9 vs 19.69 degrees) were computed by hand from the pattern
  definitions, not measured.
