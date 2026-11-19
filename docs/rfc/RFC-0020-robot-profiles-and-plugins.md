# RFC-0020 — Robot profiles and capability plugins: each robot brings what it is and how it moves

**Status:** Accepted (2026-11-19; its three questions answered, §7). The operator's direction, 2026-11-19:
"I want this to be generic platform, observatory and control thing for any robot … I also want not
to apply in practice things that we really learned on one robot only, and instead I want each robot
to bring its impact on planning in some way, like a little plugins of some sort", and: "on profile we
expand [the] existing robot profile we have been developing and also augment [the] view surfaces to
inspect all of these", and the goal: "robot platform where we can load any robot".
**Build status (2026-11-19, phase 3 stream A, branch `p3-profiles`):** step 1 built: the schema
and validator are `libs/runfile/src/runfile/profile.py` (Mission Control's `robotfile.py`
re-exports them), the duck's profile is `robots/duck/profile.json` (variants `sim` and `real`),
and `robots/duck/tests/test_profile.py` compares every one of its numbers with the constant it
replaces. Step 2 built: the navigator, the judge and the world model read the footprint,
locomotion, error budget, localisation gate and look numbers from the profile
(`Navigator.configure`). Step 3 built: the four interfaces
(`robots/duck/src/duck_lab/plugins/interfaces.py`) and the duck's plugins behind them
(`duck-walk@1`, `tof8x8@1`, `mapd@1`, `duck-head@1`), loaded by the names the profile gives;
the navigator calls them, and a run's `calibration` event records the profile and plugin
versions. What is left in code is listed in KNOWN-ISSUES K32. Steps 4 and 5: not started.
**Builds on:** [RFC-0011](RFC-0011-robot-models.md) (a description per robot),
[RFC-0012](RFC-0012-look-far.md) §2.3 (each robot supplies its own numbers; the policy holds none),
[RFC-0014](RFC-0014-mission-control.md) §3.3 (robot files, capabilities as data),
[RFC-0018](RFC-0018-lab-projects-and-seams.md) (adapters per robot, loaded by name),
[RFC-0008](RFC-0008-challenge-course.md) §4 (an error budget per robot),
[RFC-0019](RFC-0019-anomaly-telemetry.md) (anomalies; a profile's numbers are thresholds).

## 1. Why

An inventory of the code (2026-11-19) found the navigator built for one robot. Four numbers come
from a per-robot file (`duck/calibration/sim.json`: odometry scale, the depth sensor's pitch and
range kind, pivot creep, the camera's fidelity); everything else is a constant tuned on the
simulated duck, and four things only the duck has are assumed outright:

- **mapd** (Pollen's mapping service) for the pose and the grid, opened unconditionally
  (`run.py:340`);
- **the 8×8 depth sensor** (`cliff.py`: 45°, 8×8 zones, the floor and drop margins);
- **a head** to glance with (`robot.look`, `robot.head`, `HEAD_WALK_CMD`): without one every glance
  fails and the spot is blocked (`run.py:486-488`, `1012-1013`);
- **the duck's robot API** (`robotd`'s JSON-RPC and state keys, 15 joint names).

And the duck's numbers, hard-coded: its 0.083 m radius in four places and the 0.12 m lethal ring;
0.3 m/s cruise and 0.2 m/s as the slowest walk; the turn kick (1.2 rad/s, then 0.8) because the
walk does not start turning below about 1.1 rad/s; pivot rules built around an 8 cm drift; the drop
rings, stop distances, the stuck rule and the jump gate tuned on its errors; "stop to map" and a
survey in four 90° turns because mapd maps only at stops and the sensor sees 45°.

A tracked LEGO robot would be kicked into spinning at 1.2 rad/s, refused pivots it can do, judged
"fallen" by a trunk height it does not have, and could not start the navigator at all.

Mission Control and the Observatory are mostly generic already (robot files and adapters; robot
descriptions, the run format). The work is in the navigator, the world model's few robot facts,
the judge, and the views.

## 2. The principle

A robot brings two things; everything else is shared and reads from them.

1. **A profile: data.** What the robot is: its shape, how it moves, what it senses, its measured
   errors. One profile per robot, from today's three pieces (§3).
2. **Capability plugins: code, behind four small interfaces** (§4). How the robot does the few things
   no number can describe: turning a wanted motion into its commands, turning its sensor's readings
   into obstacles and drops, knowing where it is, looking.

The shared parts (planning, exploring, the safety rules, anomalies, goals, the views) hold no robot's
numbers. A lesson learned on one robot becomes a number in its profile or code in its plugin; it
reaches another robot only when that robot's profile or plugin says so.

## 3. The profile: one file per robot, extended from what exists

Today a robot's facts live in three places: `robots/<robot>/` (its description: URDF and
`robot.json`, RFC-0011), the Mission Control robot file (factsheet, control, capabilities,
guardrails, rates: RFC-0014, VDA 5050 names in `factsheet`), and `duck/calibration/<robot>.json`
(measured numbers, each with its measurement and its reason). They become one profile under
`robots/<robot>/`, the robot file's format extended; the three stay readable during the move.

| Block | What | From today |
| --- | --- | --- |
| `factsheet` | VDA 5050 names: speeds, size (`width`, `length`, `heightMax`), kinematics | the robot file (`width`/`length` exist, unused) |
| `body` | the description (URDF), standing height, joints and their chains | `robots/<robot>/robot.json`, URDF |
| `footprint` | shape (circle or rectangle), size, where the turning centre is | four copies of 0.083 m |
| `locomotion` | cruise, caution and creep speeds; turn limits; dead zones (the slowest walk, the turn that does not start); pivot creep; walks backwards or not; step-over height | `follow.py`, `sim.json` `pivot`, STEPS.md |
| `sensors` | each sensor: kind (`tof8x8`, `ultrasonic`, `ir_cliff`, `camera`), mount, field of view, range, rate, noise, calibration (pitch, radial/axial) | `cliff.py`, `sim.json` `tof`/`camera`, the Eye's constants |
| `looking` | with a head (its joints, its walking pose) or by turning the body | `HEAD_WALK_CMD`, `run.py` |
| `localisation` | the source (`mapd`, odometry and own map), maps only at stops or not, its known error (odometry scale by speed), the jump gate's thresholds | `sim.json`, `frames.py`, `run.py` |
| `error_budget` | following error, belief p95, pivot drift, corner cutting: the margins and rings are derived from it (RFC-0008 §4) | `grid.py`, `run.py` |
| `judge` | what a fall is for this body (trunk height, tilt), what a contact is (the footprint), reach tolerance | `evaluate.py`, `guardrails.py` |
| `capabilities`, `guardrails`, `rates`, `control`, `adapter` | as today | the robot file |

Every measured number keeps its `measured` and `why` (as `sim.json` does), so a number can be
traced to the run that gave it. A profile names its plugins (§4) by name and version.

## 4. Capability plugins

Four interfaces the navigator calls instead of assuming the duck. Each robot names one
implementation of each; the duck's are today's code moved behind them, unchanged.

| Interface | Asked | The duck's | A tracked LEGO robot's |
| --- | --- | --- | --- |
| **Locomotion** | a wanted motion (speed, turn rate) → the robot's command; can it pivot here, how far does a pivot move it | the kick, the 0.2 m/s floor, pivot creep, no reversing | tracks: straight from the factsheet's speeds, no kick, reverses, pivots in place |
| **Range sensing** | a frame → obstacles, floor, drops, overhead, with the sensor's geometry | the 8×8 depth sensor (`cliff.py`, `side_drops.py`) | an ultrasonic ahead (obstacles only), an IR cliff sensor (drops only) |
| **Localisation and map** | where am I, the grid, and how sure; when to stand still to map | mapd (fixes at stops, the gate, the frame delta) | odometry and the navigator's own map from the range sensing |
| **Looking** | look at a spot; is the view settled | a head glance | turn the body toward it, or "cannot look" (the spot stays unseen, not blocked) |

The shared navigator decides; the plugins only answer. A plugin is a Python class named in the
profile and loaded by name, as RFC-0018 decided for the Observatory's adapters; the Observatory's
run adapter and Mission Control's robot adapter are the same kind of named plugin.

## 5. The views: inspect a robot's profile and its plugins

- **The Observatory:**
  - **A robot page** (from the Explore view's robot body): its profile, block by block, each
    measured number with its `measured` and `why`; its plugins and their versions; its footprint
    and sensors drawn on the body (the sensor cones from the profile, not the Eye's constants); the
    error budget and the margins and rings derived from it.
  - **Each run records the profile and plugin versions it ran with**, so a run shows what the robot
    was believed to be then; a change of profile between two runs shows as a difference.
  - **The Eye and the video** draw the sensor from the run's profile (field of view, mount, range).
  - **Anomalies** (RFC-0019) name the profile number behind a threshold ("stuck: under 5 cm in 3 s,
    from `locomotion.cruise_mps` 0.3").
- **Mission Control:** a robot's card opens its profile and capabilities; a goal refused because a
  capability is missing says which; a profile that does not validate is shown with the field and why.
- **The challenge course** draws heights and widths from the robot's profile (RFC-0008 §3: "under
  the robot's measured step height"), and the judge uses its `judge` block.

## 6. Build, in steps

The duck is the first plugin of each kind. Each step leaves its behaviour identical, proven by the
navigator's tests, replays of recorded runs, and challenges 1–5 seeded as before (the same
commands, tick for tick, where the run is deterministic).

1. The profile format and its validator; the duck's profile from today's three pieces; loaded beside
   the old files, which stay.
2. Numbers out of code: footprint, locomotion, error budget, the judge's, the world model's (walk-over
   height, overhead clearance, approach distance), read from the profile. Behaviour unchanged.
3. The four interfaces, with the duck's plugins as today's code behind them.
4. The views (§5).
5. The first other robot: the EV3 (arriving) with tracks: its profile, a locomotion plugin, its range
   sensing (its sensors decide which), odometry localisation. The NXT next, once it has a sensor that
   can see the floor.

It starts after the navigator work in flight (the frame fix, recovery) lands, since both change
`run.py`.

## 7. Questions, answered

The operator, 2026-11-19: "Yes to all 3".

1. **One profile file per robot** under `robots/<robot>/`, the Mission Control robot file and the
   description folded into it.
2. **One profile per robot with a variant block per environment** (`sim`, `real`): measured numbers
   that differ live in the variant; the variant is named at goal start.
3. **Plugins in Python only for now**; a process boundary (a plugin as its own service) later, if a
   robot driven by another runtime needs one.

## 8. Not covered

- New behaviour for other robots beyond what is needed to run them safely (the EV3's own exploring
  quality is measured after it runs).
- A plugin marketplace or third-party plugins.
- Swarm behaviour (several robots sharing one map): later, after a second robot explores alone.
