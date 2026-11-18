# RFC-0015 — Nav2 on the simulated duck: learn how the standard stack works, and compare

**Status:** Accepted, revision 3 (2026-11-18). The operator: "I would definitely want to do this,
and learn how these systems work and compare our results", and on the image: "I am OK on Docker".
Revisions 2 and 3 fold in the advisor's two reviews (Fable 5.1; the second: "accept; steps 1 and 2
can start now"; §7).
**Builds on:** [ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md) (ROS-aligned, no ROS
foundation), [RFC-0002](RFC-0002-robot-brain.md) (the robot brain),
[docs/wip/PRIOR-ART.md](../wip/PRIOR-ART.md) (what the field already does),
[docs/wip/EXPLORE-PROGRESS.md](../wip/EXPLORE-PROGRESS.md) (stream A's scoreboard).

## 1. Why

Stream A rebuilt, by measurement, things the field already names: the graded inflation ring
(Nav2's inflation layer), recovery behaviours, a collision monitor. PRIOR-ART.md maps each part of
the duck's brain to established practice. Reading is not enough: the operator wants to run the
standard stack on the same simulated duck, learn how it works by using it, and compare it with ours
on the same tests.

## 2. Goals, non-goals, and what success is

Goals:

- Nav2 (and, for one run each, `slam_toolbox`), with frontier exploring (`explore_lite`), driving
  the simulated duck through a bridge.
- The same tests for both brains: challenges 1-11 (ten seeds each) and exploring batches from the
  dock, scored by the same judge and scoreboard.
- What each does better and why, kept in PRIOR-ART.md.

**Success:** per PRIOR-ART row, an adopt-or-keep decision with a number behind it — ray-trace
clearing against our append-only obstacle memory (contacts), Nav2's recovery ladder (runs ended
"trapped"), the collision monitor's zones (stalls, contacts), Regulated Pure Pursuit's curvature
regulation (corner contacts).

Non-goals:

- Replacing our brain, or deciding whether the navigator moves to Nav2 when it moves onto the duck
  (RFC-0002 §3.9): that depends on the duck's board and Pollen's image, which this never touches.
- ROS on the real duck (ADR-0001).
- Tuning Nav2 to win or lose: only a closed list of parameters is adapted (§3.4), then frozen.

## 3. Proposal

### 3.1 Where it runs

A Docker image built from a Dockerfile in the repository: ROS 2 Jazzy, `navigation2`,
`slam_toolbox`, `m-explore-ros2` (built from source if Jazzy has no package), `foxglove_bridge`,
`ros2 bag` (MCAP). Run with `--network host` (the simulator's body server is on 127.0.0.1) and the
simulator's sockets (`~/.cache/duck-sim/`) bind-mounted. Nothing is installed on the workstation;
Docker 29.7.2 is there (32 CPUs, 133 GB). The challenge runner stays on the host (it restarts the
simulator), and talks to the bridge.

**Time:** the simulator runs at wall-clock pace (`duck-sim` will not stand below 1.0× real time), so
`use_sim_time: false` everywhere and no faster-than-real-time runs. ROS stamps from the duck's
monotonic `t_ns` (state and depth frames share `CLOCK_MONOTONIC`; a depth frame with `t_ns` 0 is
"now"): stamp = wall now − (monotonic now − `t_ns`). Costmap `transform_tolerance` 0.2 s.

### 3.2 The bridge

| From the simulator (JSON-RPC) | To ROS 2 |
| --- | --- |
| robotd's state (`robot.subscribe`), 50 Hz (ours reads 20; `base_link` → `tof` moves with the head) | `/odom` and tf `odom` → `base_link` with z (0.116 standing) and the IMU's full orientation |
| the head's sensor frame per state message (`state.frames.tof`) | tf `base_link` → `tof` (the head moves); static `tof` → `tof_optical` with the pitch offset 2.5°; the range kind (radial in the simulator, axial on the real duck) is in the cloud's construction, not the tf |
| depth frames (`tof.stream`), obstacle-class returns | `/depth/points` (PointCloud2): **marking only** |
| depth frames, per column | `/depth/scan` (LaserScan in `tof_level`, 8 beams over 45°): the nearest obstacle return's horizontal range; a column of floor only = the farthest floor return's horizontal range (it clears exactly what the beam saw); invalid or no-target zones = NaN — **clearing only**. Or, preferred if the spike shows it clears: the same `/depth/points` as a second, clearing-only source with heights −0.08..0.08 m (64 rays, not 8); the scan then serves slam_toolbox only |
| our cliff check and side drops (with their frame streak) | `/drops` (PointCloud2 at z ≈ 0.15 in `base_link`) |
| mapd (variant B only) | `/map`, and tf `map` → `odom` from mapd's fixes, matched by time as our `Localizer` does |
| `/cmd_vel` | `robot.move`, through the locomotion adapter (§3.3), resent at 10 Hz; 0.3 s without `/cmd_vel`: one explicit zero, then nothing (robotd keeps the last request after its deadman, and mapd then reads "moving") |
| the duck's description (RFC-0011) | `robot_state_publisher` (a static tf is enough for the first drive) |
| a host-facing socket | `brain.go_to`, `brain.status`, `brain.stop` (JSON-RPC, RFC-0003's style), for the challenge runner |

The odometry scale (0.91 in the simulator) is applied to the odometry, to mapd's poses and to the
grid's resolution and origin, as our navigator does; otherwise map and odometry disagree by 10 %.
The simulator's truth goes to the scoreboard only, except in the ceiling controls (§3.5).

**Why two depth sources.** Nav2's obstacle layer keeps only points between its minimum and maximum
obstacle heights, and clears only along rays to the points it keeps. The duck's sensor looks down:
most returns are floor. With the minimum at 0, floor is marked; at 0.08 m (right), floor returns are
dropped and clear nothing, so stale marks stay for ever and the comparison on clearing says nothing.
A clearing source that keeps the floor returns is what lets ray-tracing clear: the level scan (a
floor-only column ranged to its farthest floor return; not +inf, which would clear to 0.8 m what the
beam never saw), or the cloud itself in a floor height band. The band clears along 64 rays; the scan
along 8, 5.6° apart, leaves cells between rays uncleared past about 0.5 m, so free space would be
streaky and frontiers would appear between rays, which would make Nav2's exploring look bad for a
reason that is the bridge's. The spike tries both. (From the advisor's memory of
`observation_buffer.cpp`; the first drive confirms it in the costmap view.)

**`tof_level`**, the scan's frame: the sensor's position in `base_link`, yaw = the sensor's yaw, no
pitch or roll. The tilt is already in the range computation (horizontal distances from the full
sensor pose), so the frame must not tilt as well. With the fixed head it is constant relative to
`base_link`, which slam_toolbox needs (it reads the laser's offset once).

### 3.3 The locomotion adapter (shared by both brains, calibration facts, not navigation)

From `calibration/sim.json` and PHASE0-SPIKE, applied in this order: (d) the duck does not walk
backwards: negative vx becomes 0, counted in the run record; (c) the duck does not walk below
0.2 m/s: 0 < vx < 0.2 becomes 0.2 (this is where Nav2's slow approach is lost, said in the results);
then, when the result is a pivot (vx 0, vyaw non-zero): (a) a pivot from a stand does not start
below ~1.1 rad/s: when the measured yaw rate stays ≈ 0 for 1 s, send 1.2 rad/s for 1 s, then the
command — as ours does (`KICK_RAD_S`), outside the trained ±1.0 rad/s band (RFC-0002 §2) for one
second; (b) a pivot creeps forward: vx −0.06 replaces vx while pivoting.

### 3.4 Nav2's configuration: a closed list adapted, the rest default, frozen by a gate

Adapted, and only these: the footprint (`robot_radius` 0.12, our lethal radius: it already holds
the error budget; 0.083 would plan 4 cm closer and the contacts would compare radii, not stacks; the
judge's contact radius stays 0.083, the duck's true size, for both brains, so 0.12 is each brain's
same planning allowance for localization and following error, RFC-0008 §4);
speed limits (0.3 m/s, 1.0 rad/s); lookahead (`lookahead_time` 1.5 s, 0.15-0.45 m) and
`regulated_linear_scaling_min_radius` 0.3; `rotate_to_heading_angular_vel` 1.0 and
`rotate_to_heading_min_angle` 0.785 (ours: 45°); `allow_reversing: false`; costmap resolution
0.05 m (ours; 0.10 closes 42 cm doorways), local window 3 × 3 m, global a fixed 10 × 10 m window
centred on the start (covers every challenge scene and the apartment); both costmaps
`track_unknown_space: true` (explore_lite's frontiers are the free/unknown boundary; without it
there are none); `inflation_radius` 0.28 (ours), `cost_scaling_factor` default (the one shape
difference: Nav2's exponential against our quadratic ring); the two depth sources (marking: heights
0.08-0.30 m, range 0.8 m; clearing: the level scan or the floor-band cloud, §3.2, range 0.8 m); a
second obstacle layer instance `drop_layer` from `/drops`, marking only,
`footprint_clearing_enabled: false`, before inflation (Nav2 has one inflation radius: drops get the
walls' ring, not ours of 0.35/0.55 m — a known difference); `clearable_layers: [obstacle_layer]` on
both costmaps, so no recovery ever clears `drop_layer` (the one legitimate clear is the reset
between runs); Smac 2D with `allow_unknown: true`;
the behaviour tree without BackUp and DriveOnHeading (the duck cannot back up), keeping Spin, Wait
and ClearCostmap, shipped as a named XML; goal tolerance 0.15 m (ours); the collision monitor with
one stop polygon 0.30 m ahead × 0.246 m wide (our reflex), fed by `/depth/points` and `/drops`,
sources `min_height` −0.04 and `max_height` 0.20 (its band is in `base_link`, whose origin is
0.116 m up: this is 0.08-0.32 m above the floor, the obstacle class; with the defaults a 15 cm box
would never stop the duck); `explore_lite` `min_frontier_size` 0.3, `progress_timeout` 30 s (ours:
15 s, noted).

One asymmetry stays, named in the write-up and not fixed: ours also has exact-point growth, the
shadow cost and separate drop rings; Nav2 has inflation only. That is the comparison.

**The head** holds one pose, our walking pose, for the whole comparison: Nav2 does not move a head.
A head sweep while walking (as a nodding sensor) is a later variant, after a probe of whether moving
the head while walking upsets the gait.

**Frozen** when challenges 1 and 2 pass 10 of 10 through the bridge, not on a date. Any later change
is a new frozen version and names the runs it makes stale.

### 3.5 What is compared

| Row | Map and pose | Drops | Purpose |
| --- | --- | --- | --- |
| Ours | as today | ours | the baseline |
| Nav2 A (primary) | its own global costmap from the depth sources; `map` → `odom` identity (odometry only) | `drop_layer` | the comparison |
| Nav2 B | mapd's map and fixes; surveys between goals only, never during one (a stop inside a goal trips the controller's progress checker, 10 s, and explore_lite then blacklists the frontier): the bridge holds the next goal until the survey ends, proxying explore_lite's goals. The survey is ours (zeros, four 90° pivots), part of the mapd driver, since the stop is the sensor's need, not the navigator's | `drop_layer` | the map-source question; on challenges (one goal) B differs from A only by the start survey and its fix, so B runs on exploring only |
| slam_toolbox | once, on the apartment | `drop_layer` | expected to fail on 8 beams; reported, not repeated |
| Ceiling: Nav2 with truth | the scene's geoms (`scene.layout`; the apartment from `sim/apartment_layout.json`) rasterised into `/map`; `map` → `odom` = truth ∘ inverse(odom) from a 10-20 Hz body poll (about 50 lines) | as lethal cells in the truth `/map` | sensor failures told apart from gait and controller failures |
| Ceiling: ours with truth | the `Localizer` re-fixed every tick with `map_from_world` ∘ truth (the transform the challenge runner measures at the first fix), so frames and grid stay in mapd's frame; no change to `go_to` (20-30 lines) | ours | the same, for ours |

A stairwell keep-out mask comes from the scene, so it is a truth control, not a comparison row; on
challenges 8, 9 and 12 it also makes "refused" trivial (the goal is in the mask). Without the
`drop_layer`, Nav2 walks into the stairwell: measured once, reported.

**Scoring.** The judge and the scoreboard unchanged. Nav2's outcomes mapped: SUCCEEDED → reached;
planner failures (no valid path, goal or start occupied) → refused, the code as the reason;
controller failure after the recoveries → stalled; the challenge's time limit → timeout. Exploring:
explore_lite's "exploration stopped, no frontiers" → `no_frontier_left`; the truth guard →
`aborted`; the 20-minute cap → time; explore_lite has no "trapped", and its blacklisted-goal count,
the analog of our refusals in a row, is recorded per run. The clock starts when the goal is sent,
after Nav2's lifecycle is up; between runs (the simulator restart puts odometry back at the dock, so
stale marks would sit on the new start), Nav2 resets all costmaps including `drop_layer`, or
restarts its lifecycle. For the exploring areas, the bridge exports Nav2's global costmap in mapd's
grid format. Both brains write the same run record (format 2: truth samples, depth frames), through
a recorder taken out of our `Navigator`; the runner calls a `Brain` interface both implement.

## 4. Steps

1. This RFC and an ADR amending ADR-0001 together (decision 1 gains: "ROS 2 may run in a container
   as a comparison and learning tool; nothing of ours depends on it; decision 4's triggers still
   govern adoption"). The operator's go on the image is the ADR's acceptance.
2. **The spike, before the rest is committed to:** the image builds and `explore_lite` exists for
   Jazzy (about 2 h); a first drive on challenge 1 with the costmaps seen in Foxglove, checking:
   (1) floor not marked; (2) walls marked; (3) walls cleared when they leave the wedge (the duck
   turns, or, in the spike only, the head is turned by hand), by the scan and by the floor-band
   cloud, and which clears better; (4) a 15 cm box stops the collision monitor; (5) the published
   global costmap has unknown (−1) cells. Also read in the Jazzy sources: the clearing height
   filter, the `clearable_layers` default, the collision monitor's height band, explore_lite's
   `min_frontier_size` unit. If the costmap cannot be made right from this sensor, stop here and
   write up why.
3. The `Brain` interface, the shared recorder, the outcome mapping, the costmap export, the two
   ceiling controls' code (half a day).
4. Freeze (challenges 1 and 2 at 10 of 10); the two ceiling controls first (cheaper, and they
   calibrate the reading of every later row); then challenges 1-11 for Nav2 A and B.
5. Exploring batches (three runs, as ours) with the `drop_layer`.
6. The write-up: per PRIOR-ART row, adopt or keep, with the number.

**Size:** 5-8 working days to the first comparable table. Building: the image half a day, the bridge
to a first drive 1-2 days, a right costmap from a downward 8 × 8 sensor about a day (the hardest
part: nobody configures Nav2 for this sensor), the adapter until challenge 1 passes 1-2 days, the
interfaces and the recorder a day. The simulator runs in real time and is shared with stream A: one
challenge set of 11 × 10 is about 3.5-4 h per row.

## 5. Open questions

1. Whether moving the head while walking upsets the gait (a 10-minute probe; decides the head
   variant).
2. Whether the bridge later serves Mission Control as its ROS 2 driver ([RFC-0014], on the
   `mission-control` branch).

[RFC-0014]: https://github.com/chipi/robotics-lab/blob/mission-control/docs/rfc/RFC-0014-mission-control.md

## 6. Alternatives considered

- **Read only** (PRIOR-ART.md): cheaper, but does not show how the parts behave on this robot, which
  is what the operator wants to learn.
- **Adopt Nav2's concepts in our code without running Nav2**: what stream A does now; it can follow
  this comparison instead of guessing.
- **Gazebo with a stock robot instead of the duck**: learns Nav2 but compares nothing; the duck's
  sensor and gait are the point.

## 7. Discussion

- 2026-11-18, the operator asked whether we are reinventing the wheel; PRIOR-ART.md was started.
  Running Nav2 itself was offered as a question (it reopens ADR-0001); the operator: "I would
  definitely want to do this, and learn how these systems work and compare our results."
- 2026-11-18, revision 2 after the advisor's review (accept with changes): two depth sources so
  clearing works; drops as their own layer with clearing off; Nav2's own costmap as the primary row,
  mapd and slam_toolbox as variants; the locomotion adapter; a closed list of adapted parameters and
  a functional freeze gate; truth ceiling controls; the outcome mapping; the tf tree, stamps and
  wall-clock pacing; a fixed head; an explicit zero on silence; the host socket, `Brain` and the
  shared recorder; the ADR at step 1; the first drive as the spike; 5-8 days, not 2-4. Not taken
  from the review: its note that RFC-0014 does not exist (it is on the `mission-control` branch).
  Its uncertain points stay open until the spike: how Nav2 filters the clearing cloud by height,
  whether `explore_lite` has a Jazzy package, Smac's handling of unknown cells.
- 2026-11-18, the operator approved the Docker image with ROS 2 ("I am OK on Docker"); that go is
  also the ADR-0001 amendment's acceptance (§4 step 1).
- 2026-11-18, revision 3 after the advisor's second review ("accept; steps 1 and 2 can start
  now"): all nine first-review issues landed; fixed in wording: the floor-only scan column (ranged
  to its farthest floor return, not +inf), the range kind (in the cloud, not the tf), the adapter's
  order. New: `track_unknown_space` (without it explore_lite finds no frontier), the global window's
  origin, `clearable_layers` so recoveries never clear drops, the collision monitor's height band in
  `base_link`, the floor-band cloud as a clearing source to try against the scan, the scan's level
  frame, row B surveying between goals only and running on exploring only, the reason for 0.12
  against the judge's 0.083, the ceiling controls' code, exploring outcomes for Nav2, the kick
  outside the trained band, 50 Hz state. Its unsure points (the clearing height filter,
  `clearable_layers`, the monitor's band, slam_toolbox with 8 beams, explore_lite's units) are read
  in the Jazzy sources during the spike.

## 8. Spike results (step 2, 2026-11-18, first version)

Built and run: `nav2/Dockerfile`, `nav2/bridge.py`, `nav2/params_overrides.yaml` with
`nav2/merge_params.py`, `nav2/costmap_probe.py`, `nav2/first_drive.sh`. Image
`robotics-lab-nav2:spike` (5.1 GB), run `--network host` with the simulator's sockets mounted.
The bridge is the first version: odometry and tf, the depth sensor as an obstacle cloud, a floor
cloud for clearing and a drops cloud (all from `duck_lab.nav.cliff`, the geometry our navigator
uses), `/cmd_vel` to `robot.move` through the adapter's steps (d), (c) and (b). `base_link` is the
trunk's level frame on the floor (z 0 is the floor), not the trunk's centre: the clouds' heights
are heights above the floor, so every height band below is in floor metres, not §3.4's.

### What works

- The image builds. The Dockerfile's `colcon build --packages-select explore_lite` failed
  (`explore_lite_msgs` not built); `--packages-up-to` fixed it. `explore_lite` and
  `explore_lite_msgs` build from source; there is no `ros-jazzy-explore-lite` apt package
  (`apt-cache policy` empty). Nav2 is 1.3.14, `slam_toolbox` is installed.
- Nav2's lifecycle comes up on the bridge's topics (60 s after the launch in the drive script)
  with the closed parameter list merged onto the Jazzy defaults. The bridge published about 15
  depth frames a second.
- Costmap checks (`nav2/costmap_probe.py`, the duck standing at the dock, floor of the dock room
  ahead and the apartment's object 0.4 to 0.75 m ahead):
  - **Check 1, floor not marked:** yes. The local costmap has 13 to 16 lethal cells, all in the box
     x 0.40-0.75, y -0.35-0.20 (the object), none on the floor.
  - **Check 2, obstacles marked:** yes (the same cells).
  - **Check 3, clearing:** partly. With the floor-band cloud as the clearing source, 54 to 180 of the
     local window's 3600 cells are free and 3309 to 3367 unknown: the 64 rays clear lines, not
     the area, as §3.2 expected. Not tried: the level scan as the other clearing source, and
     clearing when an obstacle leaves the wedge (the duck turning or the head turned).
  - **Check 5, unknown cells in the global costmap:** yes, 39772 of 40000 are -1 (`track_unknown_space`).
- Read in the Jazzy sources (`navigation2` branch `jazzy`, `m-explore-ros2` main):
  - the observation buffer's height filter is applied to every source, clearing ones too, in the
    costmap's global frame (`observation_buffer.cpp`): a clearing cloud needs its points inside
    `[min_obstacle_height, max_obstacle_height]`, as §3.2 said;
  - **there is no `clearable_layers` parameter in Jazzy.** `ClearCostmapService` clears every
    layer whose `isClearable()` is true: `ObstacleLayer` and `VoxelLayer` true, `StaticLayer` and
    `InflationLayer` false. §3.4's plan (a second `ObstacleLayer` for drops, never cleared by the
    recoveries) does not work as written: the `ClearCostmap` recoveries would clear the drops.
    Open: drop the clearing recoveries from the behaviour tree, or feed drops through a layer that
    is not clearable;
  - the collision monitor takes a source's heights in `base_frame_id`'s coordinates
    (`pointcloud.cpp`, defaults 0.05 and 0.5), so with a floor-level `base_link` they are floor
    heights; `StopPolygon.points` is a string parameter;
  - `explore_lite`'s `min_frontier_size` is in metres (cells times resolution), default 0.5;
  - Jazzy's default controller is MPPI, not Regulated Pure Pursuit (the overrides name the
    plugin and replace its parameters); the Smac 2D plugin is `nav2_smac_planner::SmacPlanner2D`;
    the defaults name `base_footprint`.

### What does not work yet

- **No goal has been reached.** Two goals, one run each, on a freshly reset simulator: (1.0, 0.0)
  and (1.2, 0.6). Nav2 accepted both and planned (a path of 22 poses to the first); the duck
  walked 0.5 to 0.7 m, then stood while the controller logged "Failed to make progress" (7 and 4
  times) until the 90 s limit. The (1.0, 0.0) goal lies behind the object 0.4-0.75 m ahead, a poor
  first goal; (1.2, 0.6) is free in the mapd map of an earlier run. The cause is not known. Seen
  and not tied to it: `/cmd_vel_nav` carries up to 1.68 rad/s before the velocity smoother (set to
  1.0), samples of `/cmd_vel` after the smoother and the collision monitor show 1.0 rad/s
  turns and vx 0 for much of the time, and the adapter counted 84 pivots and 13 raises to 0.2 m/s
  in the second run. The adapter's kick (§3.3 a: a pivot from a stand does not start below about
  1.1 rad/s) is not built, and the controller's pivots at 1.0 rad/s are below that: a candidate,
  not a finding. Whether the collision monitor stopped the duck beside the object is not known.
- In the second run the global costmap's counts after the drive (61 free, 14 lethal) equal those
  before it, while the local costmap changed: whether the global costmap stopped updating or the
  probe read an old message is not known.
- Not done: check 4 (the 15 cm box and the collision monitor), the level scan as a clearing source,
  `explore_lite`, `slam_toolbox`, the host `brain.*` socket, the `Brain` interface, the shared
  recorder, the ceiling controls, challenge 1 as a scored run, any scoring. The run's data are not
  kept in the Observatory (a bridge run writes no run record).
- Not stopped here, for the operator: whether to go on (the first drive does not pass), and the
  `clearable_layers` question above, which changes §3.4.
