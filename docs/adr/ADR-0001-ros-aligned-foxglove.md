# ADR-0001 — ROS-aligned terms, no ROS foundation yet, Foxglove from the start

**Status:** Accepted (operator, 2026-11-14); decision 3 amended by
[RFC-0007](../rfc/RFC-0007-platform.md) (proposed): the Foxglove app is an interim viewer; the target
is an open-source viewer within our own platform — chosen in
[ADR-0002](ADR-0002-viewers-rerun-and-lichtblick.md): Rerun first, Lichtblick kept usable.
Decision 1 amended by [ADR-0018](ADR-0018-ros2-in-a-container-for-comparison.md) (accepted
2026-11-18): ROS 2 may run in a container as a comparison and learning tool.
**Date:** 2026-11-14
**Context from:** [RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.7–3.9 (frames, navigator, link),
[RFC-0003](../rfc/RFC-0003-robot-interface.md) (one robot interface).

## Context

ROS 2 is the most widely used robot software framework: programs exchange messages on named topics
(`/cmd_vel`, `/odom`, `/map`), with standard message types and frame names (`map → odom →
base_link`), and a large library (Nav2 for navigation, SLAM packages, MoveIt for arms, drivers) plus
tools (RViz, Foxglove, rosbag, Gazebo).

Neither robot speaks it:

- **NXT:** a 48 MHz microcontroller with 64 KB of RAM; it cannot run ROS. It can join through a
  bridge on another computer (a PC, or a Raspberry Pi or ESP32 riding on it), or be replaced by a
  BrickPi3 (a Raspberry Pi board driving NXT/EV3 motors and sensors).
- **Microduck:** runs Pollen's own Linux image and its own JSON-RPC daemons; upstream uses no ROS.
  It can join through a bridge (`/cmd_vel` → `robot.move`, `robot.state` → `/odom` and frames,
  `map.grid` → `/map`, depth and camera frames → their messages).

Nav2, ROS's main navigation attraction, has defaults built around a 360° range sensor (a lidar);
the duck has a 45° depth sensor seeing about half a metre. ROS 2 targets Ubuntu; this workstation
runs Arch.

## Decision

1. **ROS 2 is not the foundation now.** Our software (the NXT service, the robot brain, the
   navigator) stays plain Python with the robots' own interfaces.
2. **Terminology and shapes follow ROS.** Frame names (`map`, `odom`, `base_link`), and our data
   shaped like ROS's standard messages: velocity commands (`Twist`: linear x/y, angular z),
   odometry (`Odometry`: pose and twist), occupancy grids (`OccupancyGrid`), ranges and images. So a
   robot or our code can join ROS later through a thin bridge.
3. **Foxglove from the start for seeing robot data.** Run records are written as **MCAP** (the
   open, ROS-independent log format Foxglove reads), and live data can be streamed to Foxglove over
   its WebSocket protocol — no ROS needed. One viewer for both robots: map, path, pose, depth,
   camera frames, commands, on one timeline.
4. **ROS 2 is reconsidered when one of these is true:** the arm robot needs arm motion planning
   (MoveIt); we want ready-made SLAM or sensor drivers instead of writing our own; several robots
   need a standard bus between them.

## Consequences

Positive:

- No ROS install, bridge or Ubuntu container now; the brain stays small and testable.
- A real robotics viewer early, for every run, simulator and real.
- Joining ROS later is a bridge, not a rewrite.

Negative:

- We write the navigator ourselves instead of configuring Nav2.
- New Python dependencies when the brain is built: an MCAP writer (and possibly Foxglove's SDK for
  live streaming), added in the robot brain project with this ADR as the reason.
- Foxglove's desktop app is commercial with a free plan (free forever: 3 users, 10 GB cloud
  storage, 10 devices; local MCAP playback and live connections). The open-source Foxglove Studio
  ended at v1.87 (February 2024); **Lichtblick**, an open-source fork (MPL-2.0), is the fallback
  viewer if the free plan changes. MCAP itself stays open source.

Neutral:

- The NXT keeps `nxt-python` and NXC programs; how it gains a companion computer (a Raspberry Pi
  on the brick by USB, an ESP32, or a BrickPi3 replacing the brick) is a separate decision
  ([NXT-PARTS.md](../wip/NXT-PARTS.md)).

## Alternatives considered

- **ROS 2 as the foundation now:** install (a container on Arch), a bridge per robot, and Nav2's
  defaults not fitting the duck's sensors; the benefits arrive only with the triggers in decision 4.
- **ROS 2 on the duck itself:** means building ROS into Pollen's OS image and maintaining it;
  against upstream's design.
- **Our own viewer (the NXT web UI grown up):** fine for one robot's live view, a large project
  for maps, poses and timelines across robots; Foxglove already does it.
- **RViz:** needs ROS.
