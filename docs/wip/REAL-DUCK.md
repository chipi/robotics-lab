# When the real duck arrives

**Status:** running notes, started 2026-11-19 (the operator: "start [a] new file with running notes
[on] what to do when [the] real duck arrives"). Add to it whenever a simulator finding says "not
measured on the real duck". Every number we measure here goes into the duck's profile,
`robots/duck/profile.json` `variants.real`, with its `measured` (how, when) and `why`, as the
simulator's numbers are. The scripts that take §2's range model, §4's walking speed and the board's
CPU cost, and the score sheet, are in [REAL-DUCK-MEASURE.md](REAL-DUCK-MEASURE.md).

## 1. First, safety

- Only through the gate: every command with a lease, STOP always honoured (RFC-0017). Mission
  Control's duck adapter drives it; no probe script talks to the robot directly. The one measuring
  script that moves it (`lab-measure-walk`) goes through the gate with a lease too, and refuses a
  robot that is not the simulator without `--real`.
- No real run until the review is done: Mission Control refuses every goal run and calibration on
  the real duck unless its robot file says `allow_real_runs: true`. What to verify before setting
  it is in [the safety review](REAL-DUCK-SAFETY-REVIEW.md).
- Lowest speeds first: the profile's guardrail `max_speed` set below the simulator's cruise until
  the walking is seen on our floor.
- On the floor, not a table: no drop the duck could reach until the drop checks (§3) are measured.
- Nothing from `robots/duck/sim/probes` runs on the real duck unless it was written for it (most
  assume the simulator, and K28: they were not run after the restructure).

## 2. The depth sensor (8×8 ToF)

What the simulator showed and what we do not know for the real one ([RANGE.md](RANGE.md), K34):

| Question | Simulator | Real duck |
| --- | --- | --- |
| Range along the beam (radial) or straight ahead (axial)? | radial (`tof.py`, `mj_ray`) | unknown; mapd assumes axial |
| How far down the sensor looks, beyond the head's kinematics | about 2.5° (challenges) to 2.6–2.9° (apartment), most likely the head sagging on its backlash | unknown; mapd assumes 3° |
| The sensor's height error | not separated from the pitch (1 cm ≈ 4 % of a 0.25 m floor range) | unknown |

To measure: the duck standing still on a flat floor, head in the walking pose, frames recorded; fit
the floor the way `robots/duck/sim/probes/floor_fit.py` does (convention × pitch); then a box at
known distances (0.25, 0.5, 0.75 m), centre and off-centre pixels, to separate radial from axial.
Repeat while walking (the head moves). Then: if the real sensor is radial too, mapd's axial model
puts off-centre returns 6–13 % too far: try the radial setting on maploc's replay bench and report
to Pollen (with the upstream drafts).

## 3. Drops and steps

- The drop checks (`cliff.py`, `side_drops.py`) were tuned on simulated ranges with 2.5° radial:
  re-check at a real edge (a step, a box edge) from 0.6 m, approaching slowly, before any real drop
  is near.
- The glance's edge error budget (K27) is a simulator measurement.

## 4. Walking

| Question | Simulator | Real duck |
| --- | --- | --- |
| Pivot creep (moving while turning on the spot) | −0.06 m/s | profile says 0, not measured |
| Odometry scale (distance believed vs walked) | 0.91, by speed | not measured, no scale applied ([UPSTREAM-ODOMETRY-DRAFT.md](UPSTREAM-ODOMETRY-DRAFT.md)) |
| Highest bar it walks over | about 1 cm, straight; turning while crossing hurts ([STEPS.md](STEPS.md)) | not measured; not tried at an angle or on a round cable |
| Stuck detection (3 s, 0.05 m) | tuned in the simulator | unknown on a real floor (carpet, tiles) |

To measure: walk marked straight lines (1, 2 m) at the slowest and cruise speeds on each floor type,
compare odometry with the tape; pivot on a mark and measure the drift; bars of 0.5, 1, 1.5, 2 cm
(a ruler, a book, a cable) straight on, then at an angle. Then finish the two upstream drafts with
real numbers ([UPSTREAM-STEP-HEIGHT-DRAFT.md](UPSTREAM-STEP-HEIGHT-DRAFT.md)).

## 5. Position (mapd)

- Its position jumps and our fix gate (0.3 m / 0.35 rad, frames parted at 0.25 m / 0.1 rad) were
  measured in the simulator only. Record real runs and run `observatory anomalies` on them.
- No truth on a real floor: a way to know where the duck really is (tape marks on the floor and a
  phone video from above, or marked stops) before any go-to score means anything.

## 6. The camera and objects

- The simulated camera's recognition numbers are guesses (RFC-0016), not measurements: field of
  view, range, the chance of recognising an object, noise. Measure them with the real camera and
  detector.

## 7. Then, in order

1. The profile's `variants.real` filled from §2–§6, each number with `measured` and `why`.
2. The navigator on the real duck in one room, goals by hand through Mission Control, recorded.
3. The anomaly detectors on those recordings: which fire, and whether they are right.
4. A small real course (the arena's question 2: how to make real courses).
