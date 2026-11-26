# Research plan: learned obstacle avoidance, and training our own

**Decided (the operator, 2026-11-26):** all activities approved, R1-R7 and S1-S5 to run before MVP
2;
R8 when the real duck arrives. `onnxruntime` approved as a dependency (R4); GPU training on the DGX
approved (R6, R7), each GPU-mode swap still announced beforehand and kept clear of the nightly
window; a new Isaac Lab stack on the DGX is the homelab's call.

**Results so far** ([R1 and R2](RESEARCH-R1-R2.md), 2026-11-26), and what they change:

- No trained navigation checkpoint is published; NVIDIA expects users to train their own. R4
  waits for R6 (a random-weight model can test the plumbing only).
- Their controller is a residual on the requested velocity, trained against NVIDIA's own walker,
  not Pollen's `0daab160` that our simulator runs. Testing it on our duck would pair it with a
  walker it never saw, which favours training against Pollen's walker (R6's port to our stack).
- The seam (R3) must hand the controller the command actually applied after the guard, and the
  depth frame's age: both are inputs it observes.
- Our simulated depth sensor is near-ideal: noise only. The cheap impairments to add (R2): minimum
  range, bias and scale, random invalid zones, dropped frames, one frame of delay. An invalid zone
  must not use status 255, which the navigator reads as a drop below the floor line
  (`tof8x8.py:286`).
- Licences: their code BSD-3-Clause; the robot meshes CC BY-NC-SA 4.0.

From [S1 to S4](RESEARCH-S1-S4.md), 2026-11-26:

- 51 NVIDIA skills found (44 Isaac Sim, 2 isaac-ros-cli, 5 in NVIDIA's own "Mission Control");
  none covers MuJoCo, Gazebo, a time-of-flight sensor, nvblox or cuVSLAM. None to use as is; a few
  patterns to adapt (a model's deployment files recorded together with their checksums, for R4
  and R6; read-only preflight scripts; evals that tempt a shortcut).
- Licences: the Isaac Sim and Mission Control skills are Apache-2.0 (copy and adapt with a
  notice). The two isaac-ros-cli skills carry NVIDIA's proprietary header despite an Apache
  `LICENSE`: read only, write our own. Asking NVIDIA is the operator's call.
- S4: the ROS connector keeps Isaac ROS possible only in part. RFC-0025 names SLAM Toolbox's
  reset, a 2D grid map, fixed topic names, and ROS 2 Jazzy. Proposed for step 5a: the mapper as a
  declared binding in the profile (its topics and its reset service), not SLAM Toolbox by name.
- S5 candidates, ranked: reading a run file, a simulator job under the lock, a challenge batch with
  arms, a motion-safety preamble, the ROS connector bring-up, a DGX training run. The operator
  picks.

**Status:** a research plan, written 2026-11-26 at the operator's request ("see it first as a
series of research activities, and then we decide"). Nothing here is planned work or approved;
each activity names what it needs from the operator. The trigger: NVIDIA's tutorial
[Microduck Obstacle Avoidance: A Sim2Real Workflow with Isaac Lab and
Newton](https://huggingface.co/blog/nvidia/microduck-obstacle-avoidance)
(2026-11-25), and the operator's wish to be able to train this kind of controller ourselves.

## 1. What NVIDIA showed

Read from the article and the deployment README of `isaac-sim/IsaacLab` branch `exp/microduck`
(`scripts/deploy/microduck_tof_nav`), through a summarising fetch; the task code is not read yet
(activity R1).

- **Two layers.** The duck's walking policy stays frozen. A separate navigation policy runs at
  50 Hz, takes the commanded velocity, a history of the 8x8 time-of-flight frames (VL53L5CX,
  15 Hz, 0.12-4 m, 45 degrees) and the body state the robot has, and outputs an adjusted forward,
  sideways and turn velocity for the walking policy.
- **Training.** Isaac Lab on the Newton physics engine; the sensor model has noise, delays,
  invalid cells near the floor edge, and a randomised mount. 16,384 parallel environments for
  1,500 iterations, or 4,096 for 3,000 in about 6 h. Obstacles: cones, boxes, bins, cabinets.
  Rewards for progress and safe arrival, penalties for collisions, falls and risky approaches.
- **Deployment.** Exported to ONNX; the navigation policy runs on a laptop and reaches the duck by
  emulating its gamepad over SSH (`nav_pad.py`, `padproxy_on_duck.py`, `relay_on_duck.py`).
  Forward speed capped at 0.15 m/s (up to 0.2), and a hard brake: translation stops when a
  central return is within 0.20 m (floor rows excluded). Stale sensor data or a missing command
  stops navigation.
- **Its goal is one fixed point or the gamepad.** It is a local controller: no map, no plan, no
  rooms.

## 2. Where it meets our design

Our navigator (`duck_lab.nav`) already has the layers; NVIDIA's controller fits one of them.

```text
 goal --> planner on the grid (explore, rooms, pace) --> path follower (follow.py)
      --> [ local layer: today the depth reflex, rules ] --> locomotion plugin --> robotd's walking policy
```

- **Same slot, different method.** Our local layer is the depth reflex: a return in the corridor
  the duck sweeps within 0.30 m, or any return within 150 mm, stops it (`nav/run.py:76-81`,
  profile `sensors.tof8x8`). It stops; it does not steer. NVIDIA's controller steers around.
- **Same sensor, same robot, same walking policy.** Their observation is built from what our
  navigator already reads (the depth stream, the robot state). Their brake is our reflex in
  another form.
- **Different simulator.** They train in Isaac Lab and Newton; we simulate in MuJoCo with
  Pollen's model (`microduck_rl`, mjlab and MuJoCo Warp), and the homelab DGX already trains
  `microduck_rl` (`MICRODUCK.md`, "Training on the DGX"). Running their policy in our simulator
  is a sim-to-sim test before any sim-to-real one.

## 3. How it would influence our architecture and approach

These are proposals to test, not decisions.

1. **A named local-controller seam.** RFC-0025 section 3.7 splits the navigator into a part that
   knows no robot and the robot's plugins, at step 3 of MVP 2. The local layer is robot-specific
   (a learned controller is trained on one body and one sensor), so it belongs on the plugin side:
   a fifth plugin interface beside locomotion, range sensing, localisation and looking, taking the
   follower's command and the sensor history and returning a command. Implementations: the rules
   we have, a learned one, and for the Burger possibly Nav2's own controller. Cheap to leave room
   for now, expensive to retrofit after the split.
2. **Rules stay as the guard; learning is an arm.** The reflex, the drop stop, the guardrails'
   speed caps and STOP stay outside and above any learned controller, which never gets the last
   word on safety. NVIDIA's own brake does the same. The project's habit, a rule baseline measured
   against alternatives, decides by evidence (eval-harness, RFC-0005's arms).
3. **A run records the steering.** The requested command and the controller's adjusted command,
   per tick, as signals (NVIDIA's overlay shows "Requested" and "Policy steering"), so the
   Observatory shows when and how much the controller overrode the follower. Additive to the run
   format.
4. **A model is part of a run's identity.** The ONNX file's checksum joins the build identity
   (RFC-0005: `brain@<commit>+model@<alias>+policies@<set>`), and the profile names which local
   controller and which model a robot runs.
5. **Training becomes a capability of the lab**, with its own record: the task, the commit, the
   simulator and its version, the seed, the reward, the checkpoint, the evaluation. The DGX is
   shared and leaving its `prod` mode is the operator's call each time.

## 4. The research activities

Ordered by cost; each says what it answers, how, what it needs, and what it produces. None needs
hardware until R8.

| # | Question | How | Needs | Produces |
| --- | --- | --- | --- | --- |
| R1 | What exactly do they observe, output and assume? | Read the task (`isaaclab_tasks.contrib.microduck_obstacle`) and the deployment scripts on `exp/microduck`: the observation vector, history length, action scaling, rates, the brake, the licence, whether a trained navigation checkpoint is published | Nothing | A short note: the contract, and whether we may use it |
| R2 | Is our simulated depth sensor as imperfect as theirs? | Compare their sensor model (noise, delay, invalid cells, floor-edge impairment, mount randomisation) with our `tof8x8` simulation and with recorded simulator runs | Nothing | A gap table; a list of impairments to add to our simulator, useful with or without learning |
| R3 | Where does the seam go? | A paper design: the local-controller interface in RFC-0025 section 3.7's split, the safety layering, the recorded signals, the profile entry | Nothing | A section proposed for RFC-0025 before step 3, or a short RFC if the operator wants one |
| R4 | Does their policy avoid obstacles in our simulator? | Run their ONNX (if published; else R6 first) in the navigator's local slot against the MuJoCo duck, after building their observation from our streams | `onnxruntime` as a new dependency (approval); simulator time | Sim-to-sim result on a handful of layouts; the observation shim |
| R5 | Is it better than our rules, by evidence? | Frozen scenarios (cones, boxes, door frames, the cases our reflex stopped for, e.g. phase 1 run 16's door frame), at least 10 per arm, arms: rules, learned, learned with the rules as guard; scores: success, collisions, minimum clearance, time, stops, falls | R4; eval-harness via `import-run` | A comparison with intervals, and the decision input for R3 |
| R6 | Can we train it ourselves? | Two candidates on the DGX: their Isaac Lab and Newton task as published (does it run on the DGX's GB10, aarch64? unknown), or the same task ported to `microduck_rl`/mjlab, which already trains there. A short run each, timed and measured | The operator's go per GPU-mode swap; Isaac Lab's install, a new stack on the DGX (the homelab's call) | A training recipe with numbers, and the choice of stack |
| R7 | Can we train our own variant? | Our command (the path follower's, not a gamepad), our obstacles (apartment-like rooms, door frames, chair legs), our caps; trained on R6's stack, judged in R5's scenarios | R6; GPU hours | Our own local controller, its record, and its evaluation |
| R8 | Does it hold on the real duck? | When the real duck arrives: the rules first, then the learned controller under the guard, at the capped speed, after a safety review like RFC-0025 step 10's | The real duck; the operator present; a safety review | The sim-to-real gap for the local layer |

## 5. Decisions the research feeds

1. Leave a local-controller seam in the navigator split (R3): the cheapest decision, and the one
   with a deadline (MVP 2 step 3).
2. Add the sensor impairments to our simulator (R2): useful whatever is decided about learning.
3. Allow `onnxruntime` in the navigator (R4).
4. The training stack: Isaac Lab and Newton, or our MuJoCo stack (R6). The second keeps one
   physics engine for training and evaluation; the first follows NVIDIA's published work.
5. Whether a learned local controller ships, per robot, by R5's evidence and then R8's.

## 6. Order and timing

- **Now, no cost:** R1, R2, R3. R3 should land before MVP 2 step 3 (the navigator split).
- **During MVP 2, with approval:** R4 and R5 in the simulator; R6's two short runs when the DGX
  can leave `prod`.
- **When the real duck arrives (one to two months):** R8, after its safety review.
- **After MVP 2:** R7, if R5 and R6 justify it.

MVP 2's own path (the Burger, Gazebo, the ROS connector) does not wait for any of this.

## 7. A second track: Isaac ROS and NVIDIA's agent skills

The operator, 2026-11-26: keep the Isaac ROS path open for the future, and get NVIDIA's agent
skills, analyse them, and see whether we can make better skills for what we do.

**What exists.** NVIDIA ships "Isaac agent skills": version-controlled `SKILL.md` workflow guides
for coding agents (Claude Code through `.claude/skills/`, Cursor, Codex), the same format as our
own skills. Isaac Sim ships them in its `skills/` directory (robot assets, physics, navigation,
sensors, ROS 2 integration, synthetic data, profiling); Isaac ROS 5.0 added skills for setup and
manipulation and "agent-ready" documentation, and the 2026-11-25 office hours covered Isaac ROS
5.1's. Isaac ROS itself is GPU-accelerated ROS 2 packages for NVIDIA GPUs and Jetson (perception,
mapping such as nvblox, manipulation).

**Keeping the path open (architecture).** MVP 2 uses plain ROS 2, Nav2 and Gazebo through our ROS
connector (RFC-0025). Isaac ROS packages are ROS 2 nodes, so the path stays open as long as the
connector speaks ROS 2 topics and services and assumes no particular node behind them: an Isaac
ROS perception or mapping node on a Jetson would then be one more source the connector reads. Check
this in RFC-0025 step 5a's design (activity S4); no Isaac ROS dependency is proposed.

| # | Question | How | Needs | Produces |
| --- | --- | --- | --- | --- |
| S1 | What do NVIDIA's skills contain, and may we use them? | Get the Isaac Sim `skills/` set and the Isaac ROS skills (from their packages or repositories, not by installing Isaac Sim into a shared environment); read the licence; list each skill's purpose, steps, scripts and checks | Nothing (a download into a scratch folder) | An inventory with the licence |
| S2 | Which are relevant to what we do? | Map each against our work: the navigator and its challenges, the MuJoCo and Gazebo simulators, the ROS connector (MVP 2 step 5a), sensors, run files and the Observatory, training (R6) | S1 | A relevance table: use as is, adapt, ignore |
| S3 | What makes a good robotics skill? | Compare their structure with our skills (`skill-authoring`): how they state preconditions, verification, failure modes, hardware safety | S1 | Patterns worth adopting, and what ours already do better |
| S4 | Does our ROS connector keep Isaac ROS possible? | Read RFC-0025 step 5a's connector design against an Isaac ROS node set (nvblox, visual SLAM) | Nothing | A note, or one change proposed to step 5a |
| S5 | Better skills of our own | Write or improve skills for our recurring robotics work, e.g. running a navigator challenge batch, reading a run file, the ROS connector bring-up, a training run on the DGX (R6), each with its own verification | S2, S3; the operator's pick of which | New or revised skills, through `skill-authoring` |

S1 to S4 cost nothing and can run any time; S5 follows the operator's pick.

## 8. Not known yet

Whether a trained navigation checkpoint is published (the article gives the walking policy's);
the licence of the `exp/microduck` branch; whether Isaac Lab runs on the DGX's GB10 (aarch64);
whether Newton and our MuJoCo stack share MuJoCo Warp (believed, not checked); how close their
walking checkpoint is to Pollen's model in our simulator (`0daab160`). The article and README were
read through a summarising fetch, not line by line; R1 reads the code.
