# RFC-0012 — Look far, get ready early: where to look and how fast to go

**Status:** Accepted (2026-11-18, the operator: "3A": accept, and build it in the challenge stream,
the first thing when it resumes); proposed 2026-11-16 on the operator's direction.
Built so far: step 1 (the unseen floor beside the way; SIDE-DROPS.md) and, in phase 4
(2026-11-19), step 2's pace (section 5 says what was measured). Steps 3-5 are not built.
**Builds on:** [RFC-0008](RFC-0008-challenge-course.md) (the challenge course, its error budget per
robot), [RFC-0002](RFC-0002-robot-brain.md) (the robot brain), [RFC-0011](RFC-0011-robot-models.md)
(each robot's description).
**Serves:** every robot the brain drives: the duck first, then the NXT and EV3, then others.

## 1. Why

The operator rides motorbikes off-road and snowboards. The rule there is to look far and get ready
for an obstacle before you are close to it, because once you are close, it is what it is. A driver
does the same: something in the distance, slow down, look, then decide.

The duck has done the opposite so far. It looks where it walks, at one speed, and finds out about
a drop or a wall when it is already near it. The challenges show the cost:

- Challenges 10 and 11: drops beside the way went unseen in 9 of 10 and 7 of 10 runs. The
  forward sensor cannot see them, and the duck never looked.
- Challenge 11: two runs saw a pit and then stalled. Seen late, it left no good way.
- Challenges 6 and 7: refusals in tight places, where the start was already decided by what the
  duck knew, not what was there.
- The removed glance (challenge 5) read short because it looked while its head was still turning.
  How a robot looks matters as much as when (docs/wip/SIDE-DROPS.md).

This RFC makes looking and pace one policy, the same for every robot. Each robot supplies its own
numbers.

## 2. The concept

Two parts that work together: **attention** (where to look, and when to stop to look) and **pace**
(how fast to go, given what is known ahead).

### 2.1 Attention: look where the next move depends on something unknown

A look is triggered by what the map does not know and the next move needs, not by a timer. Each
trigger is a rule with a reason, logged as an event, and has a challenge that tests it.

| Trigger | The question it answers | Tested by |
| --- | --- | --- |
| Unseen floor beside the way, within the drop margin | Is there floor where the robot will pass? | 10, 11 |
| A large turn coming | What is on the side the robot is about to face? | 5, 7 |
| An opening: a doorway, the end of a box, a junction | What is just past the edge? | 2, 3, 4 |
| Something ahead that is not floor or wall | How high is it, how far does it go? | 12, 13, 14 |
| New ground, while exploring | What is around, for the map? | 22–24 |
| Floor the robot is about to step on, never seen as floor | Is there floor under the next step? | 8–11, exploring |

**Look before you step** (added 2026-11-17, the operator: "maybe both"): the last trigger is a rule,
not a heuristic — the robot walks only over floor its depth sensor has seen. The strip the duck is
about to walk over (0.20–0.40 m ahead along the path, across its width) is checked against the floor
seen, cell by cell with no tolerance (at an edge, a few cm of tolerance is the whole margin); an
unseen spot stops the duck to look at it; floor goes on, a drop is remembered, still unseen is not
walked on. Why: exploring batch b2 run 2 cut the staircase opening's corner it had never had in view
(beside the duck, then just outside the 45° wedge, the corner under the head); mapd draws the
stairwell as free and no drop was remembered; the harness's truth guard stopped it 0.05 m from the
opening. Replayed on that run, the rule stops the duck 1.3 s before, to look at a spot inside the
opening. Its cost, replayed on five recorded runs: a stop in 7–15 % of walking ticks (an upper bound;
one look covers more than the spot it was for). **Scanning beside the way while walking** (the first
trigger, done ahead of time) is what keeps that cost down: the rule is the guarantee, the scanning
the speed.

Rules for every look:

- **Look only once the sensor is there.** Collect when the sensor's own pose, as recorded with the
  frame, is at the target, not after a fixed time.
- **A look that blinds the forward check happens standing.** While the head is turned away, the
  robot does not walk.
- **Every look has a budget.** It is logged with its duration and what it found, so a challenge
  can show what each trigger costs and catches.

### 2.2 Pace: slow down when what is ahead is uncertain or close to the limit

A robot has a few named speeds, not one:

| Pace | When |
| --- | --- |
| **cruise** | The way ahead is known and clear for at least the robot's look distance |
| **caution** | Unknown ground within reach, a known drop or a narrow passage near the way, or something far ahead not yet resolved |
| **creep** | The last part before a stop or through a squeeze, where the robot can still walk |
| **stop and look** | Something must be resolved that the forward view cannot (an attention trigger) |

Pace is chosen from the map ahead, as far as the robot sees, so it slows before it arrives. What
"slow" buys is more frames per metre and more time to decide. A robot gains as much as its speed
range allows.

### 2.3 Per robot: the numbers

Each robot's calibration (for the duck, `duck/calibration/<robot>.json`) gives:

- its speeds: cruise, caution and creep (m/s), and its slowest reliable speed;
- per speed, anything that depends on it (the duck's odometry scale changes with speed);
- its look distance and field of view, and what it can look with (a head with yaw and pitch, or
  only by turning the body), with how long a look takes;
- the error budget RFC-0008 §4 asks for, which sets the margins pace and attention work within.

The policy code reads these numbers and holds none of its own.

## 3. The duck's numbers (first instance)

| Item | Value | Source |
| --- | --- | --- |
| cruise | 0.3 m/s | `follow.WALK_MPS` |
| caution | 0.2 m/s | `follow.ARC_MPS`, its slowest reliable walk |
| creep | 0.2 m/s | the same: the duck cannot walk slower, nor backwards (PHASE2-RESULTS) |
| odometry scale | 0.849 at 0.2, 0.911 at 0.3, 0.930 at 0.4 | `calibration/sim.json` "by_speed" |
| look distance | 0.7 m for drops (`cliff.LOOK_M`); the sensor reaches 4 m in the simulator | `cliff.py`, Pollen's `tof.py` |
| field of view | 45° (8×8 zones); floor seen about 0.25 m to the side within 0.7 m | the review, 2026-11-16 |
| a look | the head to a side about 0.9 s, then frames | `glance_replay.py` |

So for the duck, caution is a third slower than cruise, and creep cannot go lower. Most of what this
RFC gives the duck is attention. A faster robot with a wider speed range (a wheeled one) gains more
from pace.

## 4. What changes in the brain

- One **attention** module: the triggers as rules over the map, the path and the robot's numbers.
  Each fired trigger is a decision event with its reason.
- One **pace** rule in the follower: cruise, caution or creep, chosen from the map ahead; the
  odometry scale for that speed.
- Looks done with what the robot has: the duck's head (robot.look / robot.head), collecting once the
  sensor's recorded pose is at the target.

## 5. Order

1. Unseen floor beside the way: the trigger and the glance (docs/wip/SIDE-DROPS.md), with its gates
   (zero false drops with the head turned; every pit in 10 and 11 seen; 1–9 unchanged).
2. Pace: caution near known drops, unknown ground within reach and narrow passages, with the
   odometry scale per speed. Measured on 6, 7, 10 and 11: refusals, closest approach, time.
   **Built, 2026-11-19 (phase 4):** `nav/pace.py` (cruise or caution from the path's next
   0.7 m: a known drop beside the way, a narrow passage, unseen floor within 0.4 m), its
   numbers in the duck's profile (`locomotion.pace`, with the measurement beside them), a
   `pace` decision event on each change, and the odometry scale by speed (K8). Measured
   against the base (seeds 1–3, two repeats): passes 6 1/6 → 2/6, 7 0/6 → 0/6, 10 and 11
   6/6 → 6/6; refusals 11 → 10; contacts and falls 0 → 0; closest approach unchanged (within
   0.01 m); the mean time of a run +7 s on 10 and 11 (about 15 %), +8 s on 6, +0.6 s on 7.
   Caution covered 79 % of the straight walking, started mostly by unseen floor, because the
   map grows at stops. So for the duck pace buys nothing measurable on these four, as §3
   expected ("most of what this RFC gives the duck is attention"); whether it stays on is a
   decision for the apartment batch's time and coverage (`locomotion.pace.caution_mps` =
   `cruise_mps` turns it off). Walking at 0.2 m/s with the scale by speed: belief/truth
   0.993 over 30.8 m.
3. Turn and opening triggers (5, 7, 2–4), then the vertical look with challenges 12–14.
4. Exploration looks with 22–24.
5. The real duck's numbers; then a second robot's, to check that nothing duck-specific is left in
   the policy.

## 6. Open questions

- How much time each trigger may cost before it is not worth it (per challenge, by measurement).
- Whether caution should come from distance to the uncertainty or only from its presence.
- How a robot without a head looks: turning its body, at what cost to its pose.

## 7. Alternatives considered

- **Scan on a timer.** Simple, but it spends time where everything is known, and blinds the forward
  check while it scans.
- **Wider sensing without looking** (a longer look distance). False drops grow fast with distance
  (docs/wip/SIDE-DROPS.md: at 1.1 m a 0.65° pitch error reads as a drop).
- **One speed and bigger margins.** What the duck had: margins large enough to be safe at speed
  close passages it fits through (challenges 6 and 11).

## 8. Discussion

- 2026-11-16, the operator: look far and get ready before you are close, as on a motorbike or a
  snowboard; slowing from 0.3 to 0.2 is fine; the concept must serve many robots, and what slowing
  down means is set per robot.
- 2026-11-17, stream A (exploring the apartment): the duck cut a stairwell corner it had never seen.
  Two answers were put to the operator — walk only over seen floor and look before stepping, or scan
  the sides while walking; the operator: "maybe both". Look before you step is built first, as the
  guarantee (§2.1); scanning beside the way follows, to win back its time.
