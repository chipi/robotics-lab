# Research S1-S4 (and S5 candidates): NVIDIA's agent skills

**Status:** research note, 2026-11-26, read-only. Answers activities S1 to S4 of
[RESEARCH-LEARNED-AVOIDANCE.md](RESEARCH-LEARNED-AVOIDANCE.md) section 7, and lists the S5
candidates. Nothing was installed, committed or pushed. Claims are marked VERIFIED (with the
file or URL it came from) or NOT VERIFIED.

Sources, all under `$HOME/.cache/robotics-lab-tests/research/skills/` (a prior download, reused;
the commits were read with `git log -1`):

| Folder | Repository | Commit read |
| --- | --- | --- |
| `isaacsim/` | `isaac-sim/IsaacSim`, `skills/` | `9160c0e` (2026-11-16), sparse, blob-less |
| `isaac-ros-cli/` | `NVIDIA-ISAAC-ROS/isaac-ros-cli`, `skills/` | `71c6ab6` (2026-11-17), tag `v5.1-0` |
| `imc/` | `nvidia-isaac/isaac_mission_control`, `skills/` | `73c1038` (2026-09-22) |

The third one is not in the brief. The Isaac ROS docs name it as the home of five "Mission
Control agent skills" (`public/_sources/.../mission_control_agent_skills.rst.txt` in
`NVIDIA-ISAAC-ROS/NVIDIA-ISAAC-ROS.github.io`), so it was added. It is NVIDIA's fleet Mission
Control, unrelated to our `apps/mission-control` apart from the name.

## 1. The answer in ten lines

1. There are 51 skills in three places: 44 in Isaac Sim, 2 in `isaac-ros-cli`, 5 in NVIDIA's
   Mission Control. VERIFIED: `isaacsim/skills/manifest.yaml` (44 entries), the two
   `isaac-ros-cli/skills/*` folders, `imc/skills/manifest.yaml`.
2. Licence: Isaac Sim's and Mission Control's skills are Apache-2.0 and may be copied and
   adapted with the notice kept. The two Isaac ROS CLI skills are contradictory: Apache-2.0 in
   `LICENSE`, "strictly prohibited without a licence agreement" in each file's header. Treat
   them as read-only until NVIDIA says which (section 2).
3. The Isaac ROS 5.0/5.1 skills that exist in public are only those two: `isaac-ros-activate`
   and `migrate-node-to-rosidl-buffer`. The press-named FoundationStereo and pick-and-place skills
   were not found in any NVIDIA-ISAAC-ROS repository searched (section 3.3).
4. None of the 51 targets MuJoCo, Gazebo, a time-of-flight sensor, nvblox or cuVSLAM. VERIFIED
   by grep: no `VL53`/`ToF` match; MuJoCo and Gazebo appear in no `SKILL.md`; no skill names
   `nvblox` or `cuvslam`.
5. Relevance is small and indirect: 0 skills to use as is, 8 rows to adapt as ideas, the rest to
   ignore (section 4). The best fits are the policy-deployment artifact rules (R4, R6), the
   ROS 2 bridge's Nav2 topic list (step 5a), and Mission Control's success definition.
6. Their strongest pattern is a success definition that needs several independent signals to
   agree (`submit-and-monitor-mission`), and a verification ladder that reports build, transport
   and application proof separately (`migrate-node-to-rosidl-buffer/references/verification.md`).
7. Ours are stronger on: a "what went wrong, what the script does" table, a verdict line that
   is evidence, "Not covered" sections, locks and cleanup rules. Theirs are stronger on: evals
   per skill, a read-only `preflight.sh` per skill, and an explicit permission list.
8. Hardware safety: NVIDIA's skills have almost none. They guard the machine (EULA, no
   unsandboxed execution, no destructive cleanup), not a robot. Ours must write our own (S5).
9. S4: our ROS connector design keeps Isaac ROS possible for odometry, tf and standard
   messages, but names SLAM Toolbox in five places that are behaviour, not just a default
   (section 6). One change proposed: declare the mapper's topics and its reset in the profile.
10. S5: six candidate skills, ranked in section 7. The first is a run-file reader.

## 2. S1: the licence

### 2.1 Finding

| Source | Licence of the skills | Evidence | May we copy and adapt? |
| --- | --- | --- | --- |
| Isaac Sim `skills/` | Apache-2.0 | every one of 44 `SKILL.md` has `license: Apache-2.0` (`grep -L` finds none without it); scripts carry `SPDX-License-Identifier: Apache-2.0` (`isaac-sim-sensor/scripts/attach_lidar_imu.py:2`) | Yes, with notice. Not legal advice |
| NVIDIA Mission Control `skills/` | Apache-2.0 | `license: Apache-2.0` in each `SKILL.md`; SPDX on scripts (`imc/skills/bring-up-cloud-stack/scripts/preflight.sh:17`) | Yes, with notice |
| `isaac-ros-cli/skills/` | **Contradictory** | `LICENSE` is the unmodified Apache-2.0 text with the `[yyyy] [name]` placeholder. But `SKILL.md:7-14` of both skills, `Makefile:3-7` and `check_ircli_mode.py:2-7` say: "Any use, reproduction, disclosure or distribution ... without an express license agreement from NVIDIA CORPORATION is strictly prohibited". No `license:` key in their frontmatter | Not until resolved. Read, learn the pattern, write our own |

All VERIFIED from the files named.

Two more points:

- **Apache-2.0 covers the text, not what the text drives.** `isaacsim/LICENSE:1-11` says the
  repository is Apache-2.0 but building or running Isaac Sim needs components (Kit SDK, 3D
  models and textures) under NVIDIA's separate "Isaac Sim additional software and materials"
  licence. `isaac-sim-web-viewer/references/licenses.md` says it outright: "This skill is
  Apache-2.0; the simulator is not", and requires an explicit yes to the EULA before a pull.
  VERIFIED. So a skill we adapt is free; Isaac Sim itself is a separate decision.
- **Isaac ROS packages are separate.** `gh api .../license` reports Apache-2.0 for
  `isaac_ros_nvblox` and `isaac_ros_visual_slam`; `NOASSERTION` for `isaac_ros_common` and
  `isaac_ros_nitros`. VERIFIED for those four only. The packages we would run were not audited.

Proposed handling (a proposal, the operator decides): adapt Apache-2.0 material only with a
`NOTICE`-style line naming the source skill and commit; never copy text from the two Isaac ROS
CLI skills; ask NVIDIA (an issue on `isaac-ros-cli` is the operator's to open) which header is
right.

## 3. S1: the inventory

### 3.1 Read depth, stated plainly

Read in full: `isaac-sim-ros2-bridge`, `isaac-sim-robot-navigation` (and its
`policy-deployment.md`), `isaac-sim-validator` (top), `isaac-sim-installation` (safety rules),
`skill-distillation` (top), `meta-skills/references/quality-criteria.md`,
`occupancy-map` (top), `isaac-sim-sensor` (top), all five Mission Control skills'
manifests and `submit-and-monitor-mission` fully, both Isaac ROS CLI skills.
Read as frontmatter plus a count of scripts, references and headings: the other Isaac Sim
skills. Their "verification" cell below is therefore a count, not a judgement. NOT VERIFIED:
that any script runs; none was executed.

Structure shared by Isaac Sim skills (VERIFIED from `isaac-sim-sensor`, `-robot-navigation`,
`-validator`, `urdf-mjcf-to-usd-conversion`): frontmatter (`name`, `description` with a "Use
when", `license`, `metadata.author`), then Purpose, Prerequisites, Limitations, a Troubleshooting
table, Available Scripts, "Running scripts". The Troubleshooting table is **copied verbatim
into unrelated skills**: the rows "Black or empty frames" and "Hang on stage load" appear in
the validator and the URDF converter, where they do not apply. It is template filler.

### 3.2 Isaac Sim, 44 skills

Columns: scripts and references are file counts; "check" is the number of headings matching
verif/validat/success/acceptance and failure/troubleshoot/pitfall.

| Skill | What it is for | Scripts | Refs | Check hdrs |
| --- | --- | --- | --- | --- |
| isaac-sim-installation | Install from binary, Docker or pip behind preflight, EULA, `--execute` gates; never launches the app | 6 | 5 | 0 / 1 |
| isaac-sim-assets | Asset roots, regions, offline packs | 0 | 0 | 1 / 0 |
| isaac-sim-headless-deployment | Run Isaac Sim 6 with `--no-window`, physics-only CI | 2 | 0 | 0 / 2 |
| isaac-sim-web-viewer | Isaac Sim in a browser over WebRTC (Compose) | 11 | 5 | 0 / 1 |
| isaac-sim-remote | Localhost IPC client for a live stage (`127.0.0.1:8226`) | 18 | 3 | 0 / 1 |
| isaac-sim-troubleshooting | Import, load, link failures; Kit hangs | 0 | 0 | 0 / 2 |
| isaac-sim-validator | Pre-delivery QA, 3 levels; level 3 runs the script unsandboxed, needs `--confirm-execute` | 1 | 2 | 10 / 1 |
| isaac-sim-migration | 5.1 to 6.0 audit | 0 | 0 | 2 / 1 |
| profile-isaac-sim | Benchmarks and Tracy captures | 1 | 0 | 1 / 1 |
| validation-diff-gifs | Pixel-diff GIFs against golden images | 3 | 0 | 1 / 1 |
| isaac-sim-workflow | Scope a demo before building (plan only) | 0 | 0 | 1 / 1 |
| isaac-sim-orchestrator | Run approved multi-skill demos; owns the `$ISAAC_SIM_DIR` contract | 0 | 1 | 2 / 1 |
| meta-skills, skill-distillation | Author and improve skills; propose library updates after a task | 0 | 2 / 0 | 1 / 2 |
| isaac-sim-ros2-bridge | OmniGraph ROS 2 bridge, Nav2 topics, multi-robot namespaces | 2 | 0 | 0 / 2 |
| isaac-sim-ros-workspaces | Build `IsaacSim-ros_workspaces` (Humble/Jazzy, Docker, Pixi) | 2 | 2 | 0 / 1 |
| isaac-sim-robot-navigation | Drive robots live; deploy exported RL policies (`RobotPolicyRunner`) | 0 | 2 | 0 / 2 |
| navigation-primitives | Footprints, A*, kinematics, chase camera | 3 | 0 | 1 / 1 |
| occupancy-map | Export `map.yaml`/png from USD for Nav2 | 2 | 0 | 0 / 1 |
| mobility-gen | Record trajectories, then replay-render sensors | 5 | 0 | 0 / 2 |
| isaac-sim-sensor | RTX camera, LiDAR, radar, IMU, contact, domain randomisation | 3 | 0 | 0 / 1 |
| isaac-camera | Camera prims, intrinsics, distortion | 0 | 0 | 0 / 1 |
| isaac-sim-rendering | Headless RT2 and path-traced capture, ACES | 3 | 0 | 4 / 1 |
| physics-simulation | PhysX and Newton scene and prim setup | 1 | 0 | 0 / 1 |
| physx-to-newton-conversion | Convert a PhysX-only USD robot to Newton-capable | 1 | 0 | 1 / 1 |
| urdf-mjcf-to-usd-conversion | Import URDF/MJCF to USD for Isaac Sim and Isaac Lab | 1 | 0 | 0 / 2 |
| usd-articulation, usd-composition-architecture, usd-pipeline, spatial-reasoning | USD asset and scene building | 3 / 0 / 3 / 1 | 0 | 0-2 / 1-2 |
| manipulation-ik, motion-generation | Arm IK, grasp frames, cuMotion planning | 2 / 7 | 0 / 5 | 1 / 0 |
| data-collection-sim, action-and-event-data-generation, actor-sdg-* (2), generate-incident-config, run-incident-events, object-bin-packing, vlm-scene-captioning, behavior-tree-generation | Synthetic data and warehouse-incident generation | 0-6 each | 0-3 | 0-2 / 1-2 |
| calibrate-metropolis-camera, place-camera-aim-at, place-camera-max-coverage | Camera calibration and placement for a surveillance layout | 1 each | 2 | 0 / 1 |

The grouped rows (usd-*, SDG, camera placement) are listed as a family, not one by one: they
do not touch anything we do (section 4). The per-skill numbers are in the table above only
where a skill is individually listed.

### 3.3 Isaac ROS, 2 skills (`isaac-ros-cli`)

| Skill | Purpose | Steps and scripts | Verification |
| --- | --- | --- | --- |
| `isaac-ros-activate` | Enter the Isaac ROS dev container through the host CLI (`isaac-ros activate`), as one long-lived shell, never `docker exec` | Mode gate (`scripts/check_ircli_mode.py --expected docker`, refuses `venv` and `baremetal`), set `ISAAC_ROS_WS`, activate, send later commands to the same shell | Expect `{"mode":"docker","activation":"active"}` from `isaac-ros status --output json`; prompt change; 88-line `evals.json` |
| `migrate-node-to-rosidl-buffer` | Retrofit a ROS 2 C++ or Python node to `rosidl::Buffer` fields (the 5.0 replacement for NITROS), keeping behaviour | 9 steps: record the contract, run `audit_copy_boundaries.py`, a per-field plan, smallest topology, then `rclpy`/`rclcpp` patterns; `summarize_nsys_memcopies.py` for profiler proof | A six-rung ladder in `references/verification.md`: contract, negotiation, copy audit, separate-process test, profiler, application result, each reported separately; marked early access |

VERIFIED from the two folders. The release-5.0 branch holds the same two skills
(`gh api .../git/trees/release-5.0`). The skills the 5.0 press coverage names (a
FoundationStereo fine-tuning skill, a pick-and-place skill) were **not found**: no `SKILL.md`
or `skills/` path in `isaac_ros_dnn_stereo_depth`, `isaac_ros_manipulation`, `isaac_ros_common`,
`isaac_ros_nvblox`, `isaac_ros_visual_slam`, `isaac_ros_deploy`, `isaac_ros_physical_ai`,
`isaac_ros_learned_policies`, `isaac_ros_mapping_and_localization`, `isaac_ros_robots`,
`isaac_ros_examples` on `main`, `release-5.0` or `release-5.1`. NOT VERIFIED where they are
published (possibly a private or not-yet-pushed location). No skill covers nvblox or cuVSLAM.

### 3.4 NVIDIA Mission Control, 5 user skills and 1 developer skill

| Skill | Purpose | Scripts | Verification |
| --- | --- | --- | --- |
| `bring-up-cloud-stack` | Start the cloud services from the compose stack | `preflight.sh` (261 lines), `up.sh` | Services healthy; `evals.json` |
| `change-map` | Switch the map, edit `defaults.yaml` | `preflight.sh`, `set_map.py` | `evals.json` |
| `change-fleet-composition` | Add, remove, rename robots; `sim: false` marks real hardware, kept out of the simulator command line (`SKILL.md:170-184`) | `preflight.sh`, `set_fleet.py` | `evals.json` |
| `change-stack-version` | Pin an image tag | `preflight.sh`, `set_image.py` | `evals.json` |
| `submit-and-monitor-mission` | Submit a mission and prove it completed | `preflight.sh`, `submit_mission.sh` | A six-signal success definition (database, dispatch log, robot state, robot log, pose delta, no `failure_reason`); a stalled-mission decision tree; `evals.json` |
| `build-mission-control-image` (developer) | Build the image | `build_image.sh` | not read |

VERIFIED from the folders; scripts not run.

## 4. S2: what is relevant to us

Classes: **use** (take as it stands), **adapt** (take the idea, write ours), **ignore**.
No skill is "use": every one is written for Isaac Sim, Kit 110, USD or NVIDIA's cloud stack.

Our targets: the duck navigator (`robots/duck/src/duck_lab/nav`), the MuJoCo duck simulator and
the Gazebo Burger, MVP 2's ROS connector (RFC-0025 step 5a), sensors, run files and the
Observatory, training (R6, R7).

| Skill | Maps to | Class | Reason |
| --- | --- | --- | --- |
| isaac-sim-robot-navigation, `references/policy-deployment.md` | training, R4 (their ONNX in our simulator), navigator local slot | **adapt** | Its artifact rules are the ones our section 3 item 4 wants: keep `policy.onnx`, the exported `env.yaml` and `IO_descriptors.yaml` from the same run; never take "the newest run" or a raw checkpoint; record the model's SHA-256; reuse `env.yaml` rather than rebuilding gains and timing. VERIFIED, `policy-deployment.md`, "Select the robot, task, and artifacts" |
| isaac-sim-ros2-bridge | MVP 2 step 5a | **adapt** | Its Nav2 contract is ours: publish `/odom`, `/tf`, `/scan`, `/joint_states`, `/clock`, subscribe `/cmd_vel`, `use_sim_time: true` (`SKILL.md` "Nav2 Integration"). Its rule "fix the parent shell, then relaunch; never hot-patch `LD_LIBRARY_PATH`" is a failure-handling pattern. The OmniGraph code is useless to Gazebo and `ros_gz` |
| submit-and-monitor-mission (NVIDIA Mission Control) | navigator challenge batch, Mission Control goals | **adapt** | Closest thing to our runner/judge discipline: a goal is done only when independent sources agree, "robot IDLE is not proof", no overlapping retry while a mission is non-terminal, report the sampled poses. Our judge already scores by truth (RFC-0025 §2); the pattern to take is the wording and the stalled-mission tree |
| change-fleet-composition | robot registration, profiles | **adapt** (small) | `sim: false` for real hardware, "real robots need no pose" is the same split as our `variants.sim`/`real`; no code to take |
| migrate-node-to-rosidl-buffer, `references/verification.md` | a future Isaac ROS node, and the shape of our own verification | **adapt** (later) | Only if we ever write an Isaac ROS node. The ladder "report build, transport, profiler and application proof separately" is worth copying into our own skills now |
| isaac-sim-sensor, isaac-camera | sensors, R2 impairments | **ignore** (idea only) | RTX LiDAR, camera, IMU and a domain-randomisation helper list; nothing on a ToF grid. R2's gap table must come from `microduck_obstacle`, not from here |
| urdf-mjcf-to-usd-conversion | R6 (porting the task to Isaac Lab) | **adapt, conditional** | The duck is MJCF. This is the route only if R6 picks the Isaac Lab and Newton stack. NOT VERIFIED that the duck's MJCF survives the importer |
| isaac-sim-installation, isaac-sim-headless-deployment | R6 on the DGX | **adapt, conditional** | They state Isaac Sim 6 runs on "supported DGX Spark" aarch64 (`isaac-sim-installation/SKILL.md:123-124`) and give GB10 limits (about 35K prims, `isaac-sim-headless-deployment/SKILL.md:211`). That is partial evidence for the unknown in plan section 8; it says nothing about Isaac Lab. The install gates are a good pattern (S3), the install itself is the homelab's call |
| isaac-sim-validator | run files, simulator checks | **ignore** | Checks Isaac Sim scripts. Level 3 executes target code unsandboxed |
| mobility-gen | run files | **ignore** (idea) | Two-phase "record cheap, replay-render later" is what our run file plus companion streams already is (RFC-0025 §3.6) |
| occupancy-map, navigation-primitives | navigator, planner | **ignore** | USD input. The footprint rule (circumscribed radius plus a stated margin, `navigation-primitives/SKILL.md:144`) matches our clearance model; nothing new |
| physics-simulation, physx-to-newton-conversion | training | **ignore** now | PhysX and Newton set-up. Revisit only if R6 picks Newton |
| skill-distillation, meta-skills | our skill practice | **adapt** (S3) | "Propose a library update after a correction; write only after confirmation" |
| usd-*, spatial-reasoning, rendering, SDG family, camera placement, incident skills, manipulation, motion generation, web viewer, remote, profile, migration | none | **ignore** | USD, rendering, arms, warehouses, synthetic data: not our work |
| bring-up-cloud-stack, change-map, change-stack-version, build-mission-control-image | none | **ignore** | NVIDIA's compose stack. Their preflight-then-act shape is worth copying (S3) |
| isaac-ros-activate | a Jetson dev shell | **ignore** now | Applies only on an Isaac ROS dev container; also under the contradictory header (section 2) |

Counts: adapt 8 (one conditional pair counted once), ignore the rest, use 0. NOT VERIFIED:
nothing here was run against our code.

Gaps NVIDIA does not fill and we need: a MuJoCo or Gazebo skill, a ToF-grid sensor skill,
robot-safety wording, a run-file reader, an Isaac Lab training-run skill.

## 5. S3: what makes a good robotics skill

Compared: NVIDIA's (sections 3.2 to 3.4) with ours in `/home/marko/.claude/skills/`
(`skill-authoring`, `ci-watch`, `long-job`, `repro-first`, `gpu-mode`, `process-hygiene`).
VERIFIED: we have **no robotics skill** and the repo has none (`.claude/` holds only
`worktrees/` under `/work/robotics-lab/main`; `mission-control/` has no `.claude/skills`, no
`AGENTS.md`, no `CLAUDE.md`).

| Aspect | NVIDIA | Ours | Verdict |
| --- | --- | --- | --- |
| Preconditions | A `## Prerequisites` section in every Isaac Sim skill, but templated ("built Isaac Sim, `nvidia-smi`"). Mission Control and Isaac ROS CLI do better: a read-only `preflight.sh` that "exits non-zero and names what is missing" (`submit-and-monitor-mission/SKILL.md`) and a mode gate script (`check_ircli_mode.py`) | In prose and in the script's own checks (`gpu-mode`: read-only check before any call) | **Adopt** a per-skill `preflight` that is read-only and says what is missing |
| Verification | Strongest part of Mission Control: a Success Definition with six signals that must agree, and "IDLE is not proof". The CLI's ladder separates build, transport, profiler, application proof | `ci-watch`: a one-line `VERDICT` from a script, cancelled is INCOMPLETE; `repro-first`: the failing test first; rule 0.2 | Equal. **Adopt** the multi-signal success definition and the separated ladder for robot runs |
| Failure handling | Troubleshooting tables (symptom, cause, fix) and, in `isaac-sim-robot-navigation`, "FAILURE / SYMPTOMS / CAUSE / FIX" blocks. Many tables are copied filler. A decision tree for a stalled mission | `ci-watch`'s "what went wrong (date) / what the script does" table, with a real incident behind each row; exit codes as a table; re-arm rules | **Ours stronger**: every row has an incident. Adopt the stalled-mission decision tree |
| Hardware-safety language | None for a robot. Machine safety only: no unsandboxed execution (`--confirm-execute`), EULA before pull, "never infer authorization to launch", "do not perform destructive cleanup" (`isaac-sim-installation/SKILL.md:187-198`); the only real-hardware line is `sim: false` | The rules sit in `AGENTS.md` (gates, STOP, approvals) and in the repo's own docs: "an agent never runs a command that can make sudo ask" (`docs/wip/DUCK-SIM-FOR-AGENTS.md`), `REAL-DUCK-SAFETY-REVIEW.md` | **Neither has it in a skill.** Ours must write it: who may move the robot, speed caps, STOP first, the lease, simulator-only by default |
| Scripts | Many, and in the skill folder, run by `run_script()`; `--help` on each; a `skillspector-baseline.yaml` records reviewed script warnings with a reason | Few skills ship scripts (`ci-watch`, `long-job`); "the repeatable part goes in `scripts/`, read-only by default" | Equal in rule, ours fewer in count. **Adopt** the reviewed-warning baseline idea if we add scripts |
| Evals | `evals/evals.json` with prompts, expected output and assertions, including negative prompts ("the robot is IDLE so it passed, right?", "just resubmit") and a no-secrets assertion (Mission Control, CLI). None in Isaac Sim's 44 | `triggers.json` in some skills (trigger phrases); no output evals; "test it against the live system" | **Adopt** evals with the "agent is tempted to shortcut" prompts. Ours have trigger tests, theirs have behaviour tests |
| Routing | `description` states when and when not ("Do NOT use for mobile-robot SDG, use mobility-gen"), a generated index, one nesting level, handoff contracts (`meta-skills`) | "Use when" sentence in the description; a generated `INDEX.md`; `skill-authoring` | Equal. **Adopt** the "Do not use for X, use Y" clause |
| Permissions | `metadata.permissions` lists readable, writable and executable paths (`submit-and-monitor-mission`) | None in frontmatter; a hook is the enforcement ("a rule that must hold every time is a hook") | **Ours stronger** as a principle; the listed permissions are a useful declaration |
| After the task | `skill-distillation`: propose updates after a correction, write nothing until confirmed | Not a skill; `skill-authoring` says log the proof in the commit, not in the skill | Equal. Not adopting as a skill |
| Not covered section | Limitations section, but short and templated ("does not replace official documentation") | A real "Not covered" in `ci-watch` and `long-job` | **Ours stronger** |
| Date of lessons | "Validated 2026-03-15", "(CRITICAL, 2026-03-15)" inside the body | Dated incident rows, but `skill-authoring` forbids a dated "Verified" log | Keep ours; theirs accrete |

Patterns worth adopting (a list, not a decision):

1. A read-only `scripts/preflight` per robotics skill that names what is missing.
2. A success definition of several independent signals, with "this alone is not proof" examples.
3. A stalled-run decision tree: observed state, then the next thing to inspect.
4. A verification ladder reported rung by rung (contract, run, truth, judge, replay).
5. Evals whose prompts invite the shortcut, with assertions that it is refused.
6. A "Do not use for X; use Y" clause in the description.
7. A `permissions` block (read, write, execute) so a robot skill's reach is declared.

Where ours are already stronger: incident-backed failure tables, a single verdict line, exit
codes as a contract, "Not covered", locks and cleanup (`long-job`, `process-hygiene`), and no
filler. Their boilerplate is the warning: a template table pasted into 40 skills carries no
information.

## 6. S4: does the ROS connector keep Isaac ROS possible?

### 6.1 What was read

RFC-0025 (2,229 lines): the connector (§3.2, §3.3), sensors (§3.5, §3.9), placement (§3.8),
the reset (§3.4), frames (§3.6) and the tool table. File:
`/work/robotics-lab/mission-control/docs/rfc/RFC-0025-mvp1-to-mvp2.md`. No ROS connector code
exists yet: `grep` for `rclpy`/`slam_toolbox` finds only `nav2/bridge.py` and
`nav2/costmap_probe.py` (the parked RFC-0015 comparison). So this is a judgement on a design
text, VERIFIED to that extent only.

Isaac ROS facts come from NVIDIA's docs source
(`NVIDIA-ISAAC-ROS/NVIDIA-ISAAC-ROS.github.io`, `public/_sources/repositories_and_packages/`),
read through `gh api`: the cuVSLAM page and the nvblox "topics and services" page.

### 6.2 What an Isaac ROS node would publish

| Node | Needs | Publishes (standard) | Publishes (NVIDIA-specific) |
| --- | --- | --- | --- |
| cuVSLAM (`isaac_ros_cuvslam`) | Stereo or RGB-D images, camera info, optional IMU (`visual_slam/image_{i}`, `/imu`) | `visual_slam/tracking/odometry` (`nav_msgs/Odometry`), `slam_path`/`vo_path` (`nav_msgs/Path`), tf `map`-`odom`-`base` (`publish_map_to_odom_tf` default true, `map_frame` default `map`, `odom_frame` default `odom`) | A `Reset` service (`visual_slam/reset`, custom srv), `save_map`/`load_map`, `set_slam_pose` |
| nvblox (`nvblox_node`) | Depth image and camera info (or a 3D LiDAR point cloud), a pose by tf or `pose`/`transform` topics | Mesh and voxel layers as `PointCloud2` | `nvblox_msgs/DistanceMapSlice` (a 2D ESDF slice "to be consumed by `nvblox_nav2`"), `nvblox_msgs/Mesh`. No `nav_msgs/OccupancyGrid` in the topic list |

VERIFIED from the two docs pages. NOT VERIFIED: whether `nvblox_nav2` can emit an
`OccupancyGrid`; whether nvblox has a reset service (none is in the topics page).

### 6.3 Verdict

**Partly yes.** Three things make it possible, and five things assume SLAM Toolbox.

What keeps it possible (VERIFIED in the RFC):

- The connector is the only ROS-aware piece and "only the connector imports it"
  (`RFC-0025:1308`). Isaac ROS nodes are then just more nodes on the graph.
- Odometry and tf are the connector's to translate, "which frame its odometry is in"
  (`RFC-0025:744-754`, `:1718-1720`). cuVSLAM's `map`-`odom`-`base` tf behaves like SLAM
  Toolbox's jumping `map`-`odom`, which the design already handles with epochs.
- The images stay out of the run (`RFC-0025:1236-1240`: recorded stream is the camera's output;
  images go to companion streams). On a Jetson the heavy GPU data (images, depth) need never
  cross to the connector; only odometry, tf and a map would. This matches how Isaac ROS 5
  moves GPU data: `rosidl::Buffer` subscribers that ask for nothing get the CPU backend
  (`isaac-ros-cli/skills/migrate-node-to-rosidl-buffer/SKILL.md`, "Backend-Neutral Contract":
  "CPU remains implicitly acceptable"). VERIFIED from that skill; NOT VERIFIED on hardware.

What assumes a specific node (each is where a Jetson would not fit unchanged):

| # | Where | Assumption | Consequence for Isaac ROS |
| --- | --- | --- | --- |
| 1 | `RFC-0025:848-850` (also `:560-566`) | The step 5a reset sequence is `reset all`, then `/slam_toolbox/reset`, then SLAM Toolbox's `restamp_tf: true` | cuVSLAM's reset is `visual_slam/reset` (a custom service type); nvblox's is unknown. The sequence would be hard-coded to one mapper |
| 2 | `RFC-0025:1313` | "its grid becomes the contract's `map`": the mapper's output is a 2D grid | cuVSLAM gives no grid; nvblox gives `DistanceMapSlice`, not `OccupancyGrid` |
| 3 | `RFC-0025:357-358`, `:441-442`, `:505` | Topic names are `/scan`, `/odom`, `/imu`, `/cmd_vel`, `/tf`; the range-sensing plugin is "a 2D-scan" one | cuVSLAM's odometry is `visual_slam/tracking/odometry`; its inputs are images, not a scan. Needs remapping, and a pose source distinct from wheel odometry |
| 4 | `RFC-0025:1366` | The mapper "needs a scan, odometry and tf, and the fixed link from `/tf_static`; without `robot_state_publisher` it produced no map" | A camera-based mapper needs camera extrinsics in tf and `CameraInfo`; the RFC defers cameras to step 11 (`:1561`, `:646`) |
| 5 | `RFC-0025:1624` and `:1308` | ROS 2 Jazzy decided | Isaac ROS docs on `main` say packages are built for "ROS 2 Lyrical" (`getting_started/index.rst.txt:32-34`). VERIFIED text; NOT VERIFIED which distro 5.1 uses, nor whether a Jazzy connector and a Lyrical node interoperate over DDS (standard messages usually do) |

Related, in the code: the profile's sensor kinds already include `scan2d`, `imu`, `odometry`,
`depth_image` and `image` (`libs/runfile/src/runfile/profile.py:190-200`), so **RFC-0025:316-320
(the profile "knows `tof8x8` and `camera` only") is stale**. No kind carries a pose from a
visual SLAM, a point cloud or a voxel map. NOT VERIFIED whether `odometry` with a
`child_frame` already covers a visual odometry source.

Placement: §3.8's table has only the Pi and the workstation (`RFC-0025:983-987`). A Jetson is a
third computer on the graph. The "split" placement ("the Pi runs only the robot's bringup")
extends to it without a new rule, and the DDS discovery settings of item 6
(`RFC-0025:1693-1697`) apply to it unchanged. That is a reading, NOT VERIFIED by a run.

### 6.4 One change proposed (not applied)

**Make the mapper a declared binding, not a constant.** In step 5a, the connector reads each
sensor's topic from the profile's declaration (RFC §3.9 item 2 already says "the connector says
where each one comes from: a ROS topic"), and the mapper declares its own reset: an action,
a service name and a type, plus which output is its `map` and which its pose. Concretely,
change step 2 of the reset sequence (`RFC-0025:848-850`) from "`/slam_toolbox/reset`" to
"the mapper's declared reset", with SLAM Toolbox's `restamp_tf: true` as a parameter of that
mapper, not of the connector.

Why this one: it costs a few lines of schema now and removes assumptions 1, 3 and 4 at once.
Assumption 2 (a map that is not a grid) and 5 (the distro) are decisions for when an Isaac ROS
node arrives; they need no change now. It adds no Isaac ROS dependency.

## 7. S5: candidate skills of our own

Ranked by how often the task recurs, how costly a slip is, and how much a script helps. The
evidence counts are keyword counts over the 476 commit subjects of
`/work/robotics-lab/mission-control` (`git log --format=%s | grep -i -c`) and the contents of
the repo; they show recurrence, not exact frequency. All VERIFIED as cited; none verifies that
the skill would work.

| Rank | Candidate | Recurring task it serves | Evidence the task recurs |
| --- | --- | --- | --- |
| 1 | **robotics-run-read** | Read a run file (`run.mcap`) and its `source/`, `streams/` and log; say what happened, what the judge found, where the belief and truth diverged; check it opens in the Observatory (`import-run`) | 43 commit subjects mention observatory, run file or import; `robots/duck/runs/` holds 45 entries (`c21-a` ... `explore-b13`, `gate12`, `gate13`); the plan names "run 16's door frame" and "phase 1 run 18"; `make test-run-compat`, `perf-observatory` |
| 2 | **sim-run** | Run a simulator job: take `scripts/sim-lock`, use only `duck-sim` `up`/`down`/`drive`/`status`/`ctl`/`stand`, never the sudo commands, the real-time factor check, one job at a time | 21 subjects on simulator or duck-sim; the sudo lockout of 2026-11-16 is the incident (`docs/wip/DUCK-SIM-FOR-AGENTS.md`, "The rule"); `make sim-duck`, `sim-nxt`, `sim-gate-scenarios` are all "NOT in CI"; `scripts/test_sim_lock.py` |
| 3 | **challenge-batch** | Run a navigator challenge or explore batch (at least 10 per arm), freeze the scenario set, score success, collisions, clearance, stops, falls, compare arms with intervals | 33 subjects on challenge, course or batch; `c21`, `c22`, `c22-ten`, `c23-ten`, `explore-b11`...; R5 of the plan needs it; `EVAL-HARNESS-ASKS.md` |
| 4 | **robot-motion-safety** | Before any command that can move a robot: simulator or real, who holds the lease, the speed cap, STOP first, a person present on a real robot, the watchdog | 29 subjects mention safety, STOP, e-stop or deadman; `REAL-DUCK-SAFETY-REVIEW.md`, `PHASE5-REAL-DUCK-READINESS.md`; RFC-0025 step 10; plan R8 "after a safety review". The real duck is "one to two months" away (plan section 6) |
| 5 | **ros-connector-bringup** | Bring up the Burger's Gazebo container graph, prove `/scan`, `/odom`, `/tf` are live, run the reset sequence, check the clock epochs | 17 subjects on spike, gazebo or ros; `docs/wip/MVP2-SPIKE.md`; RFC-0025 §3.4 reset sequence, step 5a; `nav2/Dockerfile`, `nav2/first_drive.sh`. Does not recur yet: it starts at step 5a, so this ranks fifth |
| 6 | **dgx-training-run** | Start a `microduck_rl` or Isaac Lab training run on the DGX: check the mode (`gpu-mode`), announce the swap, avoid the nightly, `long-job` with an `EXIT=` log, record task, commit, seed, checkpoint | Plan R6 and R7; `MICRODUCK.md`, "Training on the DGX"; only 3 commit subjects so far, so low recurrence today; builds on `gpu-mode`, `long-job`, `process-hygiene` which exist |

Notes on the ranking:

- Ranks 1 to 3 recur now and each has a script worth writing (a reader, a lock wrapper, a
  batch scorer). Rank 4 recurs rarely but costs the most when wrong; it is a short skill and
  could be the safety preamble that ranks 2 and 3 link to.
- Ranks 5 and 6 are future work (MVP 2 step 5a; R6). Writing them before the work exists
  would repeat the "schema drawn from one example" mistake RFC-0025 warns about.
- Each should follow `skill-authoring`: a read-only `scripts/` first, tested on the live
  system, with the S3 patterns (preflight, multi-signal success, evals with shortcut prompts).
- Whether skills live in the homelab's `workstation/claude/skills/` or this repo's
  `.claude/skills/` is the operator's call; robotics-specific ones read as this repo's.

## 8. Not covered

- **No script was run.** No skill was installed or executed; every statement about what a
  script does comes from reading its `SKILL.md` or its header. Isaac Sim, Isaac Lab, Isaac ROS
  and Mission Control were not started.
- **Read depth.** Most of the 44 Isaac Sim skills were read as frontmatter plus counts of
  headings, scripts and references, not line by line (section 3.1). Their classification in
  section 4 rests on that and on their descriptions. The `references/` files were read only
  for `isaac-sim-robot-navigation` and the two Isaac ROS CLI skills.
- **Licence.** Not legal advice. Only the repository `LICENSE`, the frontmatter, the file
  headers and the NVIDIA "additional software" link were read; the linked EULA text itself, and
  the licence of the assets the skills reference (USD models, Omniverse packages), were not.
  The contradiction in `isaac-ros-cli` is unresolved; NVIDIA was not asked.
  `THIRD_PARTY_NOTICE.md` was not read.
- **Isaac ROS 5.0/5.1 skills.** Only the two in `isaac-ros-cli` were found. The
  FoundationStereo and pick-and-place skills in the press coverage were not located; the
  press coverage itself (a web search summary) was not read in full. Isaac ROS documentation
  other than the cuVSLAM and nvblox topic pages was not read.
- **Isaac ROS on a Jetson was not tried.** The S4 verdict compares a design text with a
  documentation page. It does not cover: whether cuVSLAM or nvblox run on the robot we will
  have, the compute and DDS bandwidth of a Jetson beside a Pi, the Jazzy and Lyrical
  interoperation, `rosidl::Buffer` across machines, or the closed or open status of cuVSLAM's
  source (only the wrapper package's `package.xml` licence was seen).
- **RFC-0025 is a design, and one passage is stale.** No ROS connector code exists to read; the
  `profile.py` sensor list is newer than the RFC's line 316-320 and was not reconciled with
  the rest of the RFC.
- **Not checked for relevance:** the Observatory's drawing of a scan or map from an Isaac ROS
  source (RFC-0025 step 8), the `contract 1.x` `yaw` change, and the NXT.
- **Counts in S5** are keyword matches on commit subjects, which both over-count (a word in
  passing) and under-count (a commit with a vague subject). The 45 entries in
  `robots/duck/runs/` were counted with `ls`; not every one is a batch.
- **S5 was not asked to be written.** No skill was drafted; the operator picks which.
- **Not covered at all:** the learned-avoidance research items R1 to R8, the Isaac Lab task
  code, and the Microduck article's deployment scripts.
