# ADR-0020 — Robots behind our own interfaces: robotd and ROS 2 are peer backends

**Status:** Proposed, for reflection (2026-11-23): decisions 1, 3 and 5 are the operator's; 2 and 4
are their direction, not yet designed. It would amend decision 1 of
[ADR-0001](ADR-0001-ros-aligned-foxglove.md) beyond
[ADR-0018](ADR-0018-ros2-in-a-container-for-comparison.md)'s comparison scope. Some details are open
(below).
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

## Decision

1. **ROS 2 runs as a robot's own stack, behind our contracts.** Nothing of ours depends on ROS. A
   ROS robot's navigator (Nav2 with SLAM Toolbox) can stand behind the navigator contract
   (`libs/runner/CONTRACT.md`). Our foundation stays plain Python (not "ROS as the base layer").
2. **Neither robotd nor ROS is the platform's robot interface; ours is.** The operator: "robotd and
   ROS are two versions of the same thing, and I need to be able to support more. This is not
   Pollen's style with ROS bolted on, but a platform that supports all approaches, and these two at
   the start." The gate's `robot.*` methods become our own robot interface, written in the gate's
   contract. Each robot connects through a **driver**: a robotd driver (the Microduck), a ROS 2
   driver (the Burger), the NXT's, and later others. A driver is the only way commands reach its
   robot: for ROS, the driver is the sole publisher of velocity commands, so "someone else drives"
   (plan B4) is closed by construction, not left open by default.
3. **The simulator runs at real time.** Our clocks are wall clocks: run times (ADR-0007), the truth
   pairing (`runfile/truthcopy.py`), time limits. Gazebo runs at a real-time factor of 1 with wall
   time in its bridge, and the factor is recorded per run. Pause, step and a simulated clock are not
   built.
4. **Frames and goals are ours; each driver maps onto them.** The run file's frames (`world`, `map`,
   the robot) stay the platform's. A backend's own frames (ROS's `odom`, robotd's) are the driver's
   to translate, and are kept in `raw` when worth keeping. A point goal gains an optional `yaw` when
   navigator contract 1.3 opens. The details are worked out in the spirit of decision 2 (open,
   below).
5. **Image streams never enter `run.mcap`.** A camera's or a depth camera's raw stream is a side
   file in the run's folder, referenced by the run. Retention (plan step 7) acts per run folder. A
   2D scan fits today's tick records and needs no side file.

## Consequences

- The Burger reuses the runner, the judge, the gate, the run format, the Observatory and Mission
  Control. It does not reuse the duck's navigator (`duck_lab.nav`) or RFC-0020's Python plugins: its
  seam is the navigator contract, so a profile must allow a robot with no plugins.
- The gate's robot interface needs its own written contract and a version, before a second driver
  exists. The first driver to write against it is the robotd one, which today is a pass-through.
- Plan item 6's stubs prove these seams: a stub ROS driver behind the gate, a `gazebo-turtlebot3`
  host kind as its own module, a payload with no `duck_lab` import, and a stub 2D scan in the run.
  Not stubbed: a reconstruction output (nothing reads one yet).
- Not changed yet, as nothing uses them: the profile's sensor schema (a `lidar2d` sensor comes when
  item 6 draws it), camera intrinsics and extrinsics, image channels, a reconstruction interface.

## Open

- **Frames and goals in detail** (decision 4), in the spirit of decision 2.
- **Where Nav2 runs:** on the Burger's Raspberry Pi, or in a container on the navigator's computer
  (RFC-0017 puts the gate on the navigator's computer). It decides where the ROS driver lives.
- **What "fully compatible" means for the Burger:** the challenge courses (a Gazebo world generated
  from `scene.json`) or Mission Control's goals only.
- **Which depth camera, on which robot, and when.** Until then there is no image channel.
- **ROS 2 and Gazebo versions.** The parked Nav2 image is ROS 2 Jazzy; TurtleBot3's support for
  Jazzy and Gazebo Harmonic is not checked here.

## Alternatives considered

- **ROS 2 as our foundation** (the operator's option B): ready-made libraries, but a rewrite of the
  duck's stack and the end of the plain-Python design. Rejected.
- **A robotd stand-in for every robot** (the advisor's first framing): rejected by the operator. It
  makes one robot's daemon the platform's interface.
