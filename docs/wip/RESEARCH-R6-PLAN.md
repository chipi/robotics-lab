# Research R6: training NVIDIA's Microduck avoidance controller ourselves, against Pollen's walker

**Status:** plan, 2026-11-26, read-only research; nothing was installed, run or trained. Activity R6
of `RESEARCH-LEARNED-AVOIDANCE.md`. Inputs: [R1 and R2](RESEARCH-R1-R2.md), the "Training on the
DGX"
section of `MICRODUCK.md`, NVIDIA's clone, Pollen's `microduck_rl`.

Marks: VERIFIED means read in a file, with a citation; NOT VERIFIED means not established.
Paths: `PR` = `/work/pollen/microduck_rl` (commit `0daab160`), `SP` = `PR/.venv/lib/python3.12/
site-packages`, `NV` = `$HOME/.cache/robotics-lab-tests/research/isaaclab` (branch `exp/microduck`,
`802b8d5`), `OBS` = `NV/source/isaaclab_tasks/isaaclab_tasks/contrib/microduck_obstacle`.

## 0. Recommendation

1. Option A, the port to mjlab, in stages. It trains and evaluates on one physics (MuJoCo Warp
   for training, MuJoCo for `duck-sim`), against the walker our duck runs.
2. The homelab already runs this stack (mjlab 1.3.0, torch 2.9.1+cu129 on the GB10): no new
   stack, no new CUDA, only our task code in the container.
3. B is not cheaper in effort: a new CUDA 13, torch 2.11, Warp 1.17 stack, unproven on this
   task's GB10 (section 2), and the result would train on Newton and be judged on MuJoCo.
4. C (NVIDIA's task as is, their walker) is not the fair comparison; it is only the reference
   arm that plan section 8 already asks us to report beside ours. It needs B's stack too.
5. Everything is gated by cheap CPU checks (section 5) before the first GPU swap; one decision
   record (ADR) is warranted after milestone M1: the stack choice (plan section 5, item 4).

First milestone (M1): a short run, about 200 iterations at 4096 envs, that learns to stop before
one wall with the real walker inside the action term. GPU estimate: about 0.2 to 0.3 h of
training, about 0.5 h of GPU-mode window; the whole programme about 8 to 12 GPU hours (section 4).

## 1. Option A: port the task to mjlab

### 1.1 What exists on the mjlab side (VERIFIED unless marked)

- mjlab 1.3.0, mujoco 3.10.0, mujoco_warp 3.8.1, warp-lang 1.12.0, rsl_rl_lib 5.0.1
  (`PR/pyproject.toml:17-18`, dist-info METADATA of each in `SP`).
- **Batched ray casting exists.** `mujoco_warp.rays` is exported at `SP/mujoco_warp/__init__.py:
  63-64`; `rays(m, d, pnt, vec, geomgroup, flg_static, bodyexclude, dist, geomid, normal, rc=None)`
  is at `SP/mujoco_warp/_src/ray.py:1224`, documented "Ray intersection for multiple worlds and
  multiple rays"; `pnt` and `vec` are `(nworld, nray)`, outputs `(nworld, nray)`; it launches
  over `(d.nworld, nray)`, or a BVH kernel when `rc` is given. Supported geoms: plane, sphere,
  capsule, ellipsoid, cylinder, box (`ray.py:809-830`), mesh and hfield (`ray.py:833-900`, BVH
  `:1023-1065`). The single-ray `ray()` (`ray.py:1180`) asserts one ray source, so use `rays`.
- **mjlab wraps it.** `RayCastSensor` and `RayCastSensorCfg` at `SP/mjlab/sensor/
  raycast_sensor.py:426,349`: a frame (body, site or geom), a pattern (`GridPatternCfg`,
  `PinholeCameraPatternCfg`, `RingPatternCfg`, `:315`), `ray_alignment` base, yaw or world,
  `max_distance`, `exclude_parent_body`, `include_geom_groups`. Buffers are `(num_envs, num_rays)`
  (`:528-531`); the kernel calls `mujoco_warp.rays(..., flg_static=True, bodyexclude, rc)`
  (`:749-769`). Output `RayCastData` (`:315-346`): `distances [B,N]` (-1 for no hit),
  `normals_w`, `hit_pos_w [B,N,3]`. So 64 zones x N envs is one batched call, 64 rays per env.
- Pollen's velocity task already uses a ray sensor: `TerrainHeightSensorCfg`, a `RayCastSensorCfg`
  subclass, per-foot (`PR/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py:246-255`).
  So the sensor path is exercised on the GB10 at training scale for 2 rays per foot.
- Pollen's ToF simulation `PR/src/mjlab_microduck/sim/tof.py` is NOT usable for training: a
  Python loop of 64 CPU `mujoco.mj_ray` calls per frame (`tof.py:85-89`), one robot. It is the
  reference for zone directions (`:50-62`) and the status convention.
- Contact sensors: `SP/mjlab/sensor/contact_sensor.py:51-60` (`ContactMatch`, primary and
  secondary filters), already used by Pollen for feet against terrain (`env_cfg:220-232`). A
  trunk-versus-obstacle-geoms force is expressible this way.
- Task structure to copy: flat task `make_microduck_velocity_env_cfg` (`env_cfg:193`), 949 lines,
  on mjlab's `make_velocity_env_cfg()` (`:263`); step 5 ms, decimation 4, 50 Hz (mjlab
  `velocity_env_cfg.py:442-452`); action `JointPositionActionCfg`, scale 1.0, 14 joints
  (`env_cfg:273`); actor observation 61 numbers (`PR/AGENTS.md:61-64`).
- NOT FOUND: any per-episode obstacle placement API in mjlab 1.3.0; only static terrain
  generators (`SP/mjlab/terrains/`, including `HfDiscreteObstaclesTerrainCfg`).

### 1.2 What must be rewritten, with size

NVIDIA's task is 2,302 lines (`wc -l` over `OBS`: env_cfg 427, events 368, sensors 310, rewards
299, commands 255, geometry 129, actions 103, navigation_distribution 103, symmetry 93, PPO cfg 58,
terminations 31, observations 38, rest 44). Estimates below are judgements from those sizes, marked
NOT VERIFIED; code only, tests extra (about 500 to 700 lines).

| # | Part | From (NVIDIA) | To (mjlab) | Est. lines |
| --- | --- | --- | --- | --- |
| 1 | Scene and obstacles | USD props, `events.py` layouts (9 families, 8 slots), SimReady downloads | MJCF primitives (box, cylinder, cone as cylinder or small mesh), a placement event writing per-env poses at reset | 450 |
| 2 | ToF sensor wrapper | `MultiMeshRayCasterCamera` (`sensors.py`, env_cfg `:211`) | `RayCastSensorCfg` with an 8x8 `PinholeCameraPatternCfg` on a head site; radial to axial depth; ages and history buffers | 120 |
| 3 | Sensor impairments | `sensors.py:27-301` (plain torch mostly) | torch on `distances`; floor hits found by `hit_pos_w` z near 0 | 250 |
| 4 | Observation terms | `observations.py`, env_cfg groups `:246-259` | 1343-wide actor group (history 10, ranges+flags, ages), critic extras | 90 |
| 5 | Command term | `commands.py` (destination, `:149-171,244-255`) | mjlab `CommandTerm` subclass | 150 |
| 6 | Residual action on the frozen walker | `actions.py:52-76` + `PreTrainedPolicyAction` | custom `ActionTerm`: nav residual, limits, slew, stale zero, then Pollen's walker network, then joint targets | 220 |
| 7 | Rewards | `rewards.py`, `geometry.py` (weights `env_cfg:326-350`) | mjlab reward terms, same torch maths | 400 |
| 8 | Terminations and contacts | `terminations.py` (force over 0.1 N on trunk) | mjlab `ContactSensorCfg` + termination terms, field boundary | 60 |
| 9 | Env cfg, events, curricula, registration | `obstacle_avoidance_env_cfg.py` (427) | `make_..._env_cfg`, DR reuse from Pollen, `register_mjlab_task` | 300 |
| 10 | PPO, Beta distribution, export | `agents/` (161), `navigation_distribution.py:18-63` | `rsl_rl` cfg, Beta head, export wrapper to `[1,1343] -> [1,3]` | 200 |
| | Total | | | about 2,240 (range 1,800 to 2,700) |

Not in the first pass: the mirror loss (`symmetry.py`, 93 lines, coefficient 0.1). Pollen's own
symmetry switch is off (`env_cfg` `ENABLE_SYMMETRY=False`, `:28`); add only if training is lopsided.

Part notes:

- **Part 1.** Scene. Eight fixed slots, six shuffled per reset, nine layout families (R1 section
  1.6).
  Cheapest route to per-env poses that rays see: bodies with `mocap` pose written per world at
  reset. Whether `mujoco_warp` keeps `geom_xpos` per world for mocap bodies and `rays` sees them
  is NOT VERIFIED: the first CPU/GPU test of section 5. Fallback: free-joint bodies reset with the
  robot and held by a stiff constraint (heavier). Primitive props replace SimReady assets, which
  also drops their unread licences (R1 section 1.11).
- **Part 2.** Sensor. Mount: NVIDIA's is 55 degrees about y on the head, 0.22 m high, randomised
  pitch
  +-10 degrees and height +-2 cm per episode (R1 section 1.5). Per-world site pose
  randomisation in mjlab is NOT VERIFIED; fallback: rotate the pattern directions in torch.
  Their policy consumes optical-axis depth, so convert radial ranges (multiply by the beam's
  forward component) as `tof8x8.py:211-214` does the inverse.
- **Part 3.** Impairments. Copy the parameters of R1 section 1.5 as stress priors, not truths (R1
  item 7).
  One consistency decision for the operator: train with NVIDIA's priors, or with the simulator
  impairments we added in R2 (status 13 for invalid zones). Recommended: NVIDIA's numbers in
  the first runs, so the retrained controller equals their recipe except for the walker.
- **Part 6.** The walker. Pollen's walker is an MLP 61 -> 512 -> 256 -> 128 -> 14, ELU, normaliser
  baked in
  (`MICRODUCK.md`, "The network"). Its exported ONNX has a static batch of 1
  (`SP/mjlab/rl/runner.py:34-57`: `dynamic_axes={}`; `SP/rsl_rl/models/mlp_model.py:245`), so for
  4096 envs rebuild it as a torch module from the ONNX initialisers (about 60 lines, needs the
  `onnx` package to read the file: NOT VERIFIED whether it is in the venv; otherwise read the
  training checkpoint `model_*.pt` instead). Verify against `onnxruntime` first (section 5, C3).
  The walker's input includes the command (3), head (4) and body (6) poses: head and body zero,
  as in NVIDIA's task (`env_cfg:393-394`), and the twist is the command after the residual.
- **Part 10.** Beta head: `rsl_rl_lib` 5.0.1 appears to take a distribution class by config (Pollen
  sets a
  `GaussianDistribution`, `env_cfg:912-949`); a custom class is NOT VERIFIED to be accepted.
  Export: NVIDIA's exported output is the Beta mean with a brake fallback
  (`navigation_distribution.py:18-30,59-63`), so the stock exporter is not enough.

### 1.3 The hardest part

Per-episode obstacle layouts that are moved per environment and that the batched rays see
(parts 1 and 2 together). mjlab ships only static terrain generators (NOT FOUND above); the
placement event is about 300 of the 450 lines of part 1 and the one place where framework
behaviour, not our code, can block us. Second: the walker inside the action term at 4096 envs
(part 6), because every physics substep group calls it, and its correctness decides what the
residual learns. Third risk, not code: Pollen's walker tracks about 44 % of the commanded
speed and does not walk below about 0.2 m/s in `duck-sim` (`MICRODUCK.md`, measured 2026-11-13:
0.15 m/s asked, 0.001 m/s got). Whether mjlab's training physics reproduces that shortfall is
NOT VERIFIED; the goal-speed range (NVIDIA: U(0.15, 0.35)) may need a floor of 0.2 for this walker.

### 1.4 Ray-casting cost (estimate, NOT VERIFIED)

64 rays x 4096 envs = 262,144 rays per control step, against a scene of about 10 primitive
geoms plus a plane (BVH path with `rc`). Pollen's task already runs 2 rays per foot at the
measured 2.78 s per iteration. Additional work: 1343-wide observation with history, impairment
tensors, obstacle contacts, walker network inference. Estimate: 3.2 to 4.5 s per iteration at
4096 envs (about +15 % to +60 %), to be replaced by the M1 measurement. Obstacle contacts
could raise `nconmax`/`njmax` needs (NVIDIA raised them, R1 section 1.8).

## 2. Option B: Isaac Lab and Newton on the DGX

- **Does it install on aarch64 GB10?** Partly documented, not shown for this task.
  VERIFIED in the clone (git HEAD objects; the sparse working tree lacks `docs/`):
  `docs/source/isaaclab/installation.rst:83-91` lists Python 3.12, "Ubuntu 22.04+ on x86_64, Linux
  aarch64 (including DGX Spark), or Windows 11", CUDA 13, driver 580.159 on aarch64, Warp 1.17,
  PyTorch with CUDA 13.0; `:124-136` is a "Linux aarch64 and DGX Spark requirements" dropdown, and
  SkillGen, XR teleop, livestream, Cosmos Transfer1 and RLinf are "not validated" there.
  `pyproject.toml`: `torch==2.11.0`, `warp-lang==1.17.0`, `requires-python >=3.12,<3.13`, Newton
  pinned at a git commit, `open3d` excluded on aarch64 (line 100). `.github/workflows/arm-ci.yml:7`
  runs "aarch64 build + marker-gated tests on NVIDIA DGX Spark self-hosted runners";
  `install-ci.yml:159` has a GB10 note. NOT FOUND: any statement about the Microduck tasks on GB10
  (`train_microduck.rst` names no hardware beyond GPU counts). The article's "about 6 h on a DGX
  Spark" for 4,096 environments is an article claim (fetch, R1 section 1.8), NOT VERIFIED here.
- **Newton on aarch64:** NOT VERIFIED. Only the earlier fetch of Newton's README is on record
  (it says Newton integrates MuJoCo Warp as its primary backend, R1 section 1.14); it was not
  read for platform support, and I did not fetch it again.
- **What it costs the homelab:** a second GPU stack (CUDA 13 wheels, torch 2.11, Warp 1.17, versus
  the running torch 2.9.1+cu129 and Warp 1.12.0), driver compatibility with the DGX's installed
  driver (NOT VERIFIED; the DGX driver version was not read), the SimReady asset download, and a
  separate container beside `infra/robotics/microduck/`. This is the homelab's call (plan header).
- **Can the walker be Pollen's under Isaac Lab?** Yes in principle, small change, not shown.
  The frozen walker is loaded with `torch.jit.load` in `PreTrainedPolicyAction`
  (`navigation/mdp/pre_trained_policy_action.py` at git HEAD; policy path
  `env_cfg:273-277`), so Pollen's ONNX needs an override of that load and call (about 100 lines,
  same torch rebuild as part 6 above, because the ONNX has batch 1). Interface agreement, read
  on both sides: joint order, default pose (`microduck_constants.py:116-140` against
  `isaaclab_assets/robots/microduck.py:76-90`), action `scale=1.0` with default offset, 5 ms
  step with decimation 4, and the 61-wide actor order (ang vel, gravity, joint pos, joint vel,
  last action, twist, head, body) all match (`env_cfg:273`; `flat_env_cfg.py:145-147,158-187,
  491-495`). Not shown: equal numeric conventions (gravity sign and frame, last-action raw or
  processed, normaliser statistics), and that Pollen's walker walks in Newton at all.
- **Fairness of B with Pollen's walker:** the walker is ours, the physics is Newton's MuJoCo
  Warp solver inside Isaac Lab, a different scene, contact and actuator setup from `duck-sim`.
  It fixes the walker mismatch, not the physics mismatch.

## 3. Option C: NVIDIA's task as is, swap the walker at deploy

Not fair, and not cheaper. The actor is a residual over the command, trained against their
walker's command tracking and its 0.35/0.12/0.75 limits (R1 section 1.1, 1.13). On our duck
it would meet a walker it never saw, and Pollen's walker does not walk below about 0.2 m/s
while the controller is capped at 0.15 to 0.2 m/s (R1 section 1.10; `MICRODUCK.md`). A failure
would be uninterpretable: controller or walker mismatch. It also needs B's stack. Its use: the
published-recipe reference arm, reported beside ours (plan section 8), if the homelab ever
installs B. Not a milestone here.

## 4. Steps, GPU time and cost to the homelab

Measured (homelab, 2026-11-13, `MICRODUCK.md`): 4096 envs, 2.78 s per iteration, 5.1 GB GPU,
90 % utilisation; swap to `robotics` about 1 min, back to `prod` 6 min 18 s; prod models are
down for the whole window; the nightly keeps 23:45Z-03:00Z clear, and the homelab recipe wants
prod back by 23:30Z. So each GPU window costs the run time plus about 7.5 min, and a run must
end by about 23:20Z. rsl_rl does not save when stopped: always set `--agent.save_interval`.
Use `--agent.logger tensorboard`.

Iteration time below is the section 1.4 estimate, 3.2 to 4.5 s at 4096 envs (NOT VERIFIED).

| Step | What | Needs GPU | Window incl. swaps | Done when |
| --- | --- | --- | --- | --- |
| S0 | CPU checks (section 5), port parts 1 to 10 in a fork or plugin package | none | none | all CPU checks green |
| S1 | Placement of our task code on the DGX (a second code path next to `/opt/robotics/microduck_rl`) | none | none | the homelab agrees; their call |
| M1 | Smoke: one wall layout, no impairments, 64 envs for 20 iterations, then 4096 envs for 200 iterations, `save_interval 50` | 0.2 to 0.3 h | about 0.5 h | mean forward progress up, collisions down, learned policy stops before the wall in a replay |
| M2 | Full layout mix and impairments, 4096 envs, 1,500 iterations (the article's 16,384 x 1,500 is NOT matched; 4096 x 1500 first) | 1.3 to 1.9 h | about 2.1 h | success and collision rate in the scenarios of R5, checkpoint ONNX passes section 5 C4 |
| M3 | NVIDIA's second recipe, 4096 x 3,000 | 2.7 to 3.8 h | about 4 h | same metrics; picks the recipe |
| T | Up to two tuning reruns (rewards, goal speed floor, walker pairing) | 2 to 4 h | about 3 to 5 h | decision on the recipe |
| | Total | about 6.5 to 10.5 h | five or six swaps, about 8 to 12 h of `prod` down | |

Each swap in and out, 7.5 min of prod models down; a swap is announced beforehand and never
overlaps 23:45Z-03:00Z. The prod-down time is the larger cost, so M1 is kept to one short window
and M2 and M3 each run in the 03:00Z to 23:20Z span as one window.

## 5. Checks first, cheap, before any GPU swap (CPU, this workstation, no NVIDIA GPU)

- **C1, framework facts.** On CPU (Warp has a CPU device; whether `mjlab` and the BVH ray path run
  on CPU is NOT VERIFIED, test it first): build a 4-env scene with one box, a head site, an 8x8
  `PinholeCameraPatternCfg` sensor, check distances against the CPU `mujoco.mj_ray` loop of
  `tof.py:85-89`; move the box per world through its mocap pose and check that the rays see it
  per world. If rays need CUDA, the ray test moves into M1's first 5 minutes and C1 falls back to a
  torch reference of the geometry.
- **C2, sensor maths.** The zone directions of the sensor against `tof.py:50-62`; radial to axial
  conversion; the impairment functions with seeded draws against hand-computed cases and, where
  possible, against the formulas of `OBS/sensors.py:206-301` (range gate, bias, scale, noise,
  invalid zone, dropout, delay, floor sigmoid, edge column).
- **C3, walker.** Rebuild Pollen's walker as a torch module from the ONNX; compare with
  `onnxruntime` on random 61-vectors (max absolute difference around 1e-5); run 3 to 8 envs
  of mjlab on CPU for 500 steps with a constant command and report the speed achieved against the
  speed asked (the 44 % shortfall question). Output is evidence, not a verdict.
- **C4, export round-trip.** A random-weight actor (1343 -> 128 -> 128 -> 3, tanh, normaliser
  baked) exported through our wrapper; `onnxruntime` input shape `(1, 1343)`, output `(1, 3)`
  (R1 section 1.9, `nav_pad.py:67,158-163`); output equals the torch Beta mean within 1e-5, and a
  forced collapsed forward head or a NaN gives the brake (-1, 0, 0). This also serves R4's plumbing.
- **C5, the residual action term.** Unit tests: limits (0.35, 0.12, 0.75), no speed-up over the
  request, slew (1, 1, 3) per second, zero on an all-zero request or on a frame older than 0.25 s
  (`actions.py:52-76`), against hand cases.
- **C6, scene and rewards.** The MJCF compiles with `mujoco` on CPU; seeds give identical
  layouts; collision force over 0.1 N on a pushed trunk; reward terms (progress, approach risk,
  arrival, command rate) on constructed trajectories, against NVIDIA's functions when imported
  with stubs for their framework calls.
- **C7, 8 envs for 50 iterations on CPU** (if C1 allows): the task steps without NaN, the
  reward is finite, a checkpoint saves, and the nav policy exports.

A failed check blocks the swap; a passed one is not evidence the policy learns.

## 6. Risks and open questions

- Per-world obstacle moves not visible to `rays`: the hardest-part risk (1.3).
- Pollen's walker below about 0.2 m/s: the residual may have no authority at the caps NVIDIA uses.
- rsl_rl 5.0.1 may not take a custom Beta distribution or export it; part 10 may grow.
- Our code on the DGX needs a second code path or a fork of `microduck_rl` (CC BY-NC-SA applies
  to its meshes; our task code can stay BSD-3-Clause with NVIDIA's notice where adapted).
- NVIDIA's priors for floor blanking and the edge column are stress priors (R1 item 7).
- Operator decisions: GPU swaps (each announced); whether training uses NVIDIA's impairment
  numbers or ours; whether B is wanted later as the reference arm (the homelab's call).
- An ADR is warranted after M1: the training stack (plan section 5, item 4) and the training record
  (plan section 3, item 5).

## Not covered

- Nothing was run: no import, no ray test, no training, no export. Every line estimate and
  every GPU-time estimate is a judgement from file sizes and the one measured walking run.
- The ray-cast cost on the GB10 was not measured; 3.2 to 4.5 s per iteration is a guess.
- Whether mjlab or the BVH ray path runs on CPU, whether mocap or per-world site moves are seen by
  `rays`, whether `onnx` is installed in the venv, whether rsl_rl 5.0.1 accepts a Beta head: all
  NOT VERIFIED.
- Newton's own README and platform support were not read this time; the DGX's driver version
  and CUDA 13 compatibility were not checked; no Isaac Lab install was attempted.
- No ONNX file or checkpoint was opened (neither Pollen's walker nor NVIDIA's); numeric equality
  of the two walkers' observation conventions is read from code, not tested.
- The bodies of `rewards.py`, `events.py`, `commands.py`, `geometry.py` were not read line by
  line for this plan (classified by imports and sizes); Pollen's `mdp.py` (7,707 lines) was not
  read beyond cited lines.
- NVIDIA's training budgets (16,384 x 1,500, 4,096 x 3,000 in about 6 h) come from the article,
  not the code; the homelab driver, power and thermals for long runs were not assessed.
- Licences of props, checkpoints and the Newton dependency chain were not read.
