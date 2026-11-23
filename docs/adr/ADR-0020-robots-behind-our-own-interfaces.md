# ADR-0020 — Robots behind our own interfaces: robotd and ROS 2 are peer robot types

**Status:** Proposed, for reflection (2026-11-23). It is accepted together with
[RFC-0025](../rfc/RFC-0025-mvp1-to-mvp2.md), when the operator accepts the RFC (the operator's
answer, 2026-11-23). Decisions 1, 3 and 5 are the operator's; 2 and 4 are their direction, not
yet designed. It would amend decision 1 of [ADR-0001](ADR-0001-ros-aligned-foxglove.md) beyond
[ADR-0018](ADR-0018-ros2-in-a-container-for-comparison.md)'s comparison scope. Its words are
RFC-0025's approved terms: connector, host kind, variant, interface join, contract join, mapper.
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
   ROS 2 connector (the Burger), the NXT's, and later others. A connector is the only way commands
   reach its robot: for ROS, the connector is the sole publisher of velocity commands, so
   "someone else drives" (plan B4) is closed by construction, not left open by default. The
   connector's placement (on the robot or on the workstation) is a per-robot setting.
3. **The simulator runs at real time.** Our clocks are wall clocks: run times (ADR-0007), the truth
   pairing (`runfile/truthcopy.py`), time limits. Gazebo runs at a real-time factor of 1 with wall
   time in its bridge, and the factor is recorded per run, with the simulator's own time beside
   wall time. Pause, step and a simulated clock are not built. Proposed amendment, pending the
   spike: inside the ROS graph `use_sim_time` is true, and the connector is where the two clocks
   meet, stamping wall time on receipt and keeping the ROS stamp. It stays proposed until the
   spike confirms how Gazebo's bridge stamps messages; "wall time in its bridge" above is the
   text the operator accepted.
4. **Frames and goals are ours; each connector maps onto them.** The run file's frames (`world`,
   `map`, the robot) stay the platform's. A robot software's own frames (ROS's `odom`, robotd's)
   are the connector's to translate, and are kept in `raw` when worth keeping. A point goal gains
   an optional `yaw` when navigator contract 1.3 opens. The details are worked out in the spirit
   of decision 2 (open, below).
5. **Image streams never enter `run.mcap`.** A camera's or a depth camera's raw stream is a
   companion stream in the run's folder, referenced by the run. Retention (plan step 7) acts
   per run folder. A 2D scan fits today's tick records and needs no companion stream.

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
- **The clock rule** (decision 3's proposed amendment): until the spike confirms how Gazebo's
  bridge stamps messages.
- **ROS 2 and Gazebo versions.** The parked Nav2 image is ROS 2 Jazzy; TurtleBot3's support for
  Jazzy and Gazebo Harmonic is not checked here. The spike decides; the default is Jazzy.

Settled by the operator on 2026-11-23, in RFC-0025: where the software runs is a per-robot
setting (decision 1); the first courses come after goals (the Burger's challenge courses in
Gazebo are off the critical path); no image channel until a camera is chosen.

## Alternatives considered

- **ROS 2 as our foundation** (the operator's option B): ready-made libraries, but a rewrite of the
  duck's stack and the end of the plain-Python design. Rejected.
- **A robotd stand-in for every robot** (the advisor's first framing): rejected by the operator. It
  makes one robot's daemon the platform's interface.
