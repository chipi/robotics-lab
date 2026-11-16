# ADR-0016 — A run records the robot's joints and the truth's whole pose

**Status:** Accepted (2026-11-16, the operator: "incorporate the duck's legs, and make sure all works
well across our ecosystem")
**Date:** 2026-11-16
**Context documents:** [ADR-0007](ADR-0007-run-file-format-2.md) (the tick),
[ADR-0013](ADR-0013-nxt-runs-in-format-2.md) (signals), [ADR-0014](ADR-0014-replay-logging.md),
[ADR-0015](ADR-0015-scenario-runner.md)

## Context

A run kept where the robot was in the plane (x, y, heading) and its sensors, not its body: no joint
angle, no trunk height, no tilt. A run could be plotted, not shown: drawing the robot as it moved,
in a viewer or in a rendered video, needs both. The duck's `robotd` reports its measured joint
angles in every state (`RobotState.joints`, radians, in `duck-ipc-proto`'s `JOINT_NAMES` order, on
the real duck and in the simulator alike), and the simulator's body server reports the trunk's
height and its whole orientation with the truth.

## Decision

### The joints are signals

- The measured joint angles are named signals (ADR-0013's generic kind), one per joint:
  `joint_<name>` in radians, declared by the run. The duck's are robotd's 15, in its order (both
  legs, neck, head, mouth). Any robot with joints names its own; no new record kind.
- They are written with every robot state the navigator receives (the IMU's signals' sample). A
  state whose joint count is not the declared one gives none: a value under the wrong name is worse
  than a gap.
- Every reader of signals reads them already: miniview (the Signals view, the inspector), Rerun
  (each a named column of the decoded struct, plottable by name), the API's signal windows.

### The truth's whole pose rides on the truth's own channel

- A tick may carry `truth_3d`: `{z, quat: [w, x, y, z]}`, the trunk's height and its whole
  orientation in the world. On the file it is `/truth/pose`'s position z and orientation
  (Foxglove `PoseInFrame` has both), so Rerun and Foxglove show the trunk's real height and tilt.
  The reader returns `truth_3d` whenever that pose has a height or a tilt; the plane pose
  `[x, y, heading]` is unchanged, its heading then taken from the whole orientation.
- A tick without it is written and read as before: older runs and robots with no truth are
  untouched.
- The duck's log rows carry `truth_z` (already) and `truth_quat`; the adapter turns the two into
  `truth_3d` and takes them out of the raw extras. A row with `truth_z` alone (a log from before)
  keeps it raw, as it was.

## Consequences

- **Positive:** a run holds what a robot model needs to be drawn moving as it moved: the trunk's
  whole pose and every joint. The video export builds on it, with any rendering engine.
- **Negative:** 15 more numbers per state sample (20 Hz in the duck): about 2 KB/s more per run
  before compression.
- **Neutral:** on a real robot there is no truth: the joints are recorded, the trunk's whole pose
  is not (the belief and the IMU's attitude are what it has).

## Alternatives considered

- **A JointState record** (ROS `sensor_msgs/JointState`): ROS's shape, but Foxglove's schemas have
  no joint state, so neither Rerun nor Foxglove would decode it without a schema of ours, and
  miniview would need a new kind. Signals are decoded everywhere already.
- **The trunk's height and orientation as raw extras:** no change to the format, but Rerun and
  Foxglove would not show them, and every reader would dig in the extras for a pose.
