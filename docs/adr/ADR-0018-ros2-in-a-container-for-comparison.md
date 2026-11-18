# ADR-0018 — ROS 2 may run in a container, as a comparison and learning tool

**Status:** Accepted (operator, 2026-11-18: "I am OK on Docker"); amends decision 1 of
[ADR-0001](ADR-0001-ros-aligned-foxglove.md).
**Date:** 2026-11-18
**Context from:** [RFC-0015](../rfc/RFC-0015-nav2-comparison.md) (Nav2 on the simulated duck),
[docs/wip/PRIOR-ART.md](../wip/PRIOR-ART.md).

## Context

ADR-0001 decision 1 keeps ROS 2 out: our software stays plain Python with the robots' own
interfaces. Stream A (exploring the apartment) kept rebuilding by measurement what Nav2 already
names (a graded inflation ring, recoveries, a collision monitor). The operator wants to run Nav2
itself on the simulated duck, to learn how the standard stack behaves on this robot and to compare
it with ours on the same challenges and exploring batches (RFC-0015). That needs ROS 2 Jazzy, which
targets Ubuntu; this workstation runs Arch.

## Decision

Decision 1 of ADR-0001 gains one sentence: **ROS 2 may run in a container as a comparison and
learning tool; nothing of ours depends on it; decision 4's triggers still govern adoption.**

- The container is built from a Dockerfile in the repository (ROS 2 Jazzy, `navigation2`,
  `explore_lite`, `slam_toolbox`, `foxglove_bridge`) and talks to the simulator through a bridge
  over the existing JSON-RPC interfaces.
- The robot brain, the navigator, mapd, the challenge runner and the run store keep no import of,
  and no runtime need for, ROS. Removing the container removes nothing they use.
- Adopting a Nav2 part into our stack (or replacing a part of ours with it) is not decided here: it
  follows RFC-0015's write-up, per PRIOR-ART row, and a trigger of ADR-0001 decision 4.

## Consequences

Positive:

- The comparison is measured, not argued: the same judge, scoreboard and run records for both.
- The bridge is the thin ROS join ADR-0001 promised, built early, and a candidate ROS 2 driver for
  Mission Control (RFC-0014).

Negative:

- A Docker image and a ROS 2 workspace to maintain in the repository.
- The bridge is code that exists only for the comparison while nothing adopts Nav2.
- The simulator runs in real time and is shared with stream A: comparison rows take simulator
  hours (about 3.5-4 h per challenge set of 11 × 10).

Neutral:

- Run records stay MCAP format 2, written by our recorder for both brains; Foxglove reads both.

## Alternatives considered

- **Keep ADR-0001 unchanged, read only (PRIOR-ART.md):** cheaper, but shows nothing of how the
  parts behave on this sensor and gait, which is what the operator wants to learn.
- **ROS 2 as the foundation now:** decision 4's triggers are not met; the comparison is how we
  learn whether one is.
- **ROS 2 on the host (Arch, unofficial packages):** fragile; a container is reproducible and
  removable.
