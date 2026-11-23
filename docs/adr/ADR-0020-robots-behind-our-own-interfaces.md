# ADR-0020 — Robots behind our own interfaces: robotd and ROS 2 are peer robot types

**Status:** Accepted (2026-11-23) by the operator, together with
[RFC-0025](../rfc/RFC-0025-mvp1-to-mvp2.md). Decisions 1, 3 and 5 are the operator's; 2 and 4
are their direction, not yet designed. It amends decision 1 of
[ADR-0001](ADR-0001-ros-aligned-foxglove.md) beyond
[ADR-0018](ADR-0018-ros2-in-a-container-for-comparison.md)'s comparison scope. Its words are
RFC-0025's approved terms: connector, host kind, variant, interface join, contract join, mapper.
Decision 3's clock rule, first a proposed amendment, is settled by the spike (2026-11-23).
Decisions 2 and 3 were revised after an advisor review (Fable 5.1) of the spike's work files.
Some details are open (below).
**Date:** 2026-11-23
**Context from:** the operator's vision note on depth cameras, SLAM
and 3D mapping (November 2026: a TurtleBot3 Burger in Gazebo, 2D LiDAR SLAM, then RGB-D mapping),
plan item 6 in [PHASE5-NEXT-PLAN.md](../wip/PHASE5-NEXT-PLAN.md), the advisor's review (Fable 5.1,
2026-11-23), [RFC-0017](../rfc/RFC-0017-robot-access.md) (the gate),
[RFC-0021](../rfc/RFC-0021-sim-host-and-payload.md) (the simulator host),
[ADR-0007](ADR-0007-run-file-format-2.md) (the run file).

## Context

The next robot is a TurtleBot3 Burger with Gazebo Sim as a second simulator. Its software is ROS 2:
drivers, SLAM Toolbox, Nav2. ADR-0001 keeps ROS out of our software and reconsiders it "when we want
ready-made SLAM or sensor drivers instead of writing our own". That trigger is now met.

Today the gate's robot methods are robotd's own (`robot.move`, `robot.stop`, `robot.state`,
`robot.subscribe`, `robot.health`, `tof.frame`; `libs/gate/src/robotgate/__init__.py`), passed
through. A ROS robot would need a "robotd stand-in", which makes the Microduck's daemon the model
every robot must imitate.

"Driver" already means whoever holds the lease and sends commands (RFC-0017). So the program that
joins a robot to the gate is called a connector here.

## Decision

1. **ROS 2 runs as a robot's own stack, behind our contracts.** Nothing of ours depends on ROS. A
   ROS robot's navigator (Nav2 with SLAM Toolbox) can stand behind the navigator contract
   (`libs/runner/CONTRACT.md`): a contract join. Our own navigator can also drive it at the robot
   interface: an interface join, and for the Burger it comes first. Our foundation stays plain
   Python (not "ROS as the base layer"). Where a robot's software runs (on the robot, split, or
   on the workstation) is a per-robot setting in its configuration, not a decision of this ADR.
2. **Neither robotd nor ROS is the platform's robot interface; ours is.** The operator: "robotd and
   ROS are two versions of the same thing, and I need to be able to support more. This is not
   Pollen's style with ROS bolted on, but a platform that supports all approaches, and these two at
   the start." The gate's `robot.*` methods become our own robot interface, written in the gate's
   contract. Each robot connects through a **connector**: a robotd connector (the Microduck), a
   ROS 2 connector (the Burger), the NXT's, and later others. Commands reach a robot through its
   connector. On a ROS graph that is a rule, not a guarantee: any node in the DDS domain can
   publish `/cmd_vel`, so "someone else drives" (plan B4) is narrowed by convention and watched
   (RFC-0025 sections 3.2, 3.3). The base's input is remapped to a topic only the connector
   publishes, the connector owns the one place where velocity requests meet, it watches for
   other publishers (`someone_else_drives`), and `ROS_DOMAIN_ID` isolates the graph. The
   connector's placement (on the robot or on the workstation) is a per-robot setting: the
   registration lists the placements a robot supports, the installation says which one this
   machine uses (RFC-0025 question 18). The
   **deadman is a last-hop watchdog** on the computer wired to the motor controller, in every
   placement: on the real Burger a small node on the Pi that forwards `/cmd_vel` only while
   commands are fresh and publishes zero otherwise; in the simulator, the connector itself. The
   Gazebo diff-drive plugin holds the last velocity, and the ROS 2 OpenCR firmware has no
   `cmd_vel` timeout (spike §8, from source); through the spike's connector the velocity was zero
   0.6 s after the last command (spike §20).
3. **The simulator runs at real time.** Our clocks are wall clocks: run times (ADR-0007), the truth
   pairing (`runfile/truthcopy.py`), time limits. Gazebo runs at a real-time factor of 1, and the
   factor is recorded per run, with the simulator's own time beside wall time. Pause, step and a
   simulated clock are not built. Settled by the spike (2026-11-23,
   [MVP2-SPIKE.md](../wip/MVP2-SPIKE.md) §7, §13, §20), amending the text first accepted, which
   said "wall time in its bridge": Gazebo's bridge stamps with simulation time, which starts at 0
   (a node with `use_sim_time` false fails every tf lookup at its own time). So inside the ROS
   graph `use_sim_time` is true, and the connector is where the two clocks meet: it stamps
   `wall_ns` on receipt and keeps the ROS stamp beside it. The run's own time stays wall time
   (`runfile/mcapio.py:193` rejects a time that goes back, and sim time does at a reset). A world
   reset sends the sim clock back to 0, so the run carries a clock epoch: an event, an epoch
   counter next to the source stamp (the pair (epoch, t_src); RFC-0025 question 24), and a new
   `map_to_world` record. The spike wrote one at a reset, but from a frozen belief and a frozen
   truth (§20), so it is not evidence that re-pairing works. After a reset the spike's
   belief and truth froze, from three causes diagnosed from code and logs and confirmed by a
   re-run (spike §21): the truth reader crashed on a missing `sec`; the tf buffer had no
   node clock, so it did not clear on the backward jump; SLAM Toolbox stamped `map`-to-`odom`
   with the last scan's stamp (`restamp_tf` false), which a cleared buffer rejects. The reset
   sequence of RFC-0025 section 3.6 must prove the fix in step 5a.
4. **Frames and goals are ours; each connector maps onto them.** The run file's frames (`world`,
   `map`, the robot) stay the platform's. A robot software's own frames (ROS's `odom`, robotd's)
   are the connector's to translate, and are kept in `raw` when worth keeping. A point goal gains
   an optional `yaw` when navigator contract 1.3 opens. The details are worked out in the spirit
   of decision 2 (open, below).
5. **Image streams never enter `run.mcap`.** A camera's or a depth camera's raw stream is a
   companion stream in the run's folder, referenced by the run. Retention (plan step 7) acts
   per run folder. The spike's numbers support it: 640 x 480 RGB and depth at 30 Hz are 3.9 GB a
   minute uncompressed and 17 to 25 MB a minute compressed in a flat render, a lower bound
   (spike §19), against about 75 kB a second for scan, odometry and tf (spike §11). A 2D scan
   needs no companion stream, but it does not fit today's tick records unchanged: it needs a scan
   channel in the run format (spike §20; RFC-0025 section 3.5, question 23). Widened, with
   RFC-0025 section 3.11: the recording of each stream (format, quality) is declared in the
   profile; the recorded stream is always the camera's output before any image pipeline, which is
   applied on replay and recorded in the run; and a depth stream is never recorded lossy.
   Retention acts per run folder and per stream. Defaults and the pipeline are RFC-0025 questions
   25 and 26, answered there on 2026-11-23.

## Consequences

- The Burger reuses the runner, the judge, the gate, the run format, the Observatory and Mission
  Control. Joined at the contract, it does not use our navigator: its seam is the navigator
  contract, so a profile must allow a robot with no plugins. Joined at the interface, it uses
  our navigator, which RFC-0025 makes ours for any robot (a legged duck, a differential-drive
  Burger, a tracked NXT) through RFC-0020's plugins, not the duck's alone.
- The gate's robot interface needs its own written contract and a version, before a second
  connector exists. The first connector to write against it is the robotd one, which today is a
  pass-through.
- Plan item 6's stubs prove these seams: a stub ROS connector behind the gate, a
  `gazebo-turtlebot3` host kind as its own module, a payload with no `duck_lab` import, and a
  stub 2D scan in the run. Not stubbed: a model job's output (nothing reads one yet).
- Not changed yet, as nothing uses them: the profile's sensor schema (a `lidar2d` sensor comes when
  item 6 draws it), camera intrinsics and extrinsics, image channels, a model job.

## Open

- **Frames and goals in detail** (decision 4), in the spirit of decision 2.
- **The connector's tf state across a world reset** (decision 3): three causes diagnosed and
  confirmed by a re-run; step 5a builds the sequence ([MVP2-SPIKE.md](../wip/MVP2-SPIKE.md) §20, §21);
  RFC-0025 section 3.6 and section 7 item 19.

Settled by the spike on 2026-11-23: the clock rule (decision 3, now stated as settled, not as a
proposed amendment), and the versions: ROS 2 Jazzy, Gazebo Sim 8.15.0 (Harmonic),
`turtlebot3_gazebo` 2.3.7, SLAM Toolbox 2.8.5, `ros_gz` 1.0.25 (spike §2, §3). `/cmd_vel` is
`TwistStamped` in that bridge (spike §3); the real node's type is a bringup setting
(RFC-0025 section 3.3).

Settled by the operator on 2026-11-23, in RFC-0025: where the software runs is a per-robot
setting (decision 1), held in both the registration and the installation (question 18); the
first courses come after goals (the Burger's challenge courses in Gazebo are off the critical
path); no image channel until a camera is chosen. Also settled that day (RFC-0025 section 9):
the clock epoch is first-class as the pair (epoch, t_src), decided in step 4 (decision 3,
question 24); the scan is its own channel in the run, with points until step 8 and the range
limits in the profile's sensor declaration (question 23); colour is recorded as JPEG q80 and
depth as lossless 16-bit PNG, never lossy, as a companion MCAP per stream (decision 5,
question 25); the real Burger's safety review is run by the operator at the robot, and an
independent reviewer agent checks its results before the first navigator drive (question 19).
The five decisions the advisor pulled forward are confirmed by the operator. Not answered: the
Gazebo-scene half of RFC-0025 questions 9 and 21.

## Alternatives considered

- **ROS 2 as our foundation** (the operator's option B): ready-made libraries, but a rewrite of the
  duck's stack and the end of the plain-Python design. Rejected.
- **A robotd stand-in for every robot** (the advisor's first framing): rejected by the operator. It
  makes one robot's daemon the platform's interface.
