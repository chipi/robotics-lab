# Drops beside the way: unseen floor and a glance, 2026-11-16

The operator's choice after challenges 10 and 11 and the advisor's review (Fable 5.1, 2026-11-16).

## Why

- Challenge 10: 9 runs of 10 never saw the ledge.
- Challenge 11: 7 of 10 never saw the pit, and passed 0.166–0.368 m from its edge. That is inside
  the 0.45 m the planner keeps from a known drop, and only outside the judge's 0.15 m.
- The two runs that did see the pit stalled. The drop's margin closed a passage the duck fits
  through, and the planner went into unseen space instead of refusing.

## Not side zones

The forward sensor cannot see these drops. Measured by the review from the recorded frames:

- The floor-reaching zones within the cliff check's look distance reach about 0.25–0.27 m to the
  side (median of the widest).
- The outermost columns hit the floor 0.16–0.19 m out, about 0.52 m ahead.
- The drops here are 0.3–0.6 m out.
- Looking further ahead to widen the cone is no answer. At 1.1 m a 0.65° pitch error reads as a
  drop; the 2.5° calibration error gave 131 false frames at 0.7 m.

## The plan

1. **A closed way is a refusal, not a stall.** When the only plan runs through unseen or shadow
   cells beside a known drop, refuse (challenge 11, seeds 4 and 9). "Only" matters:
   - Challenge 11 seed 4's detour ran past the pit's seen edge into its unseen far half. The drop
     points reach only about 0.4 m past the edge (`BEYOND_M`), and the pit is 0.8 m across.
   - Challenge 10 seed 10 also walked through unseen floor within 0.65 m of a remembered ledge, but
     parallel to it, and safely.
   - A rule that refuses any plan over unseen floor near a drop refuses the second. Telling the two
     apart (beyond the edge, or beside it) is designed with step 2. A first version was written and
     reverted unused, 2026-11-16.
2. **Unseen floor triggers a look.** Floor the sensor has confirmed is kept in `floor_seen`. When
   floor within the drop margin beside the path ahead is free on mapd's map but not confirmed, stop
   and glance: head about 40° to that side, pitched down. The floor 0.5 m out is then about 0.58 m
   from the sensor, inside the calibrated range.
3. **The margin from measurement.** `DROP_LETHAL_M` was set to the stop distance of the time
   (0.45 m); the stop distance is now 0.60 m. Walking beside a seen edge needs the glance's measured
   error, not the stop distance.

## The forward sensor already sees most side drops (replayed, 2026-11-16)

The recorded runs say the look is often not where a drop is first noticed.

- **The returns are there.** `sim/probes/below_seen.py`: every recorded run of challenges 10 and 11
  (40 of 40) had below-floor returns ("b") inside the real drop, usually 2–10 s before the closest
  approach. Seed 8 of challenge 11 crossed the margin, yet had 57 such returns from 7.5 s on.
  They are thrown away: only a cliff stop dead ahead turns returns into remembered drops.
- **One by one they cannot be trusted.** On floor with no drop (challenges 1–5) there are below
  returns too: a median of 14–72 per run.
- **Kept per 5 cm cell, they can** (`sim/probes/below_cells.py`). A cell is a drop cell once at
  least K frames put a below return there and below outnumbers floor by the ratio:

  | Filter | Drop caught before the closest approach (10, 11) | Drop-free runs with a false drop cell |
  | --- | --- | --- |
  | K 3, ratio 2 | 38 of 40 (lead ~17 s) | 26 of 273 (up to 9 cells) |
  | K 5, ratio 3 | 36 of 40 (lead ~14–18 s) | 8 of 273 (up to 2 cells) |
  | K 8, ratio 3 | 33 of 40 | 3 of 273 |

- **The design these numbers point to,** RFC-0008 §4's drops "suspected or confirmed":
  1. **Suspect early, from the forward sensor.** Persistent below cells (K 5, ratio 3) are kept
     as suspected drops, with a smaller ring than a confirmed drop.
  2. **Confirm with a glance.** A suspected drop near the way is the attention trigger. The
     glance confirms it, placing the edge within −4.7/+0.6 cm and the depth within 5 cm. Or it
     clears it: no false drops in 14 looks. A false suspicion then costs one look, not a closed
     doorway.
  3. **Unseen floor beside the way** stays the fallback trigger, for the drops the forward
     sensor does not catch (4 of 40 here).
- **The unseen-floor trigger alone was replayed too** (`sim/probes/trigger_replay.py`). It fires
  2–5 times a run in the rooms with no drop; that is the cost of each look. It fires before the
  closest approach in every challenge 11 run. In challenge 10 it often fires only at the start:
  in 2 runs it never looked at the ledge's side. Floor seen far ahead covers most of the band
  before the duck gets there.

Not verified: any of it closed loop; the real duck.

## Gates before trusting the glance

1. **Why did the earlier glance read short? Explained, 2026-11-16.** It was timing, not
   calibration. `sim/probes/glance_replay.py` replays challenge 5 seed 1's glance frames through
   the cliff check.
   - At its target the head read the left wall at 0.25–0.26 m (true 0.257 m) and the right at
     0.29 m (true 0.30 m).
   - The short readings (0.086–0.17 m) came from frames taken while the head was still turning
     (yaw 19–36°), seeing the walls diagonally ahead. The glance collected after a fixed 0.5 s, but
     the head took about 0.9 s to arrive; the left look then had about 0.4 s at its target.
   - So collect only once the sensor's yaw, which the frame records, is within a few degrees of the
     target.
2. **No false drops with the head turned; drops beside the way seen. Measured in the simulator,
   2026-11-16.** `sim/probes/glance_floor.py`: standing, the head aimed at the floor 0.45 m to
   each side; frames used once the sensor's own yaw has held still, past 45°; each frame run
   through `cliff.depth_points`.
   - **No drop there: 0 below-floor returns in 14 looks** (challenge 1 seeds 1–5 both sides, and
     the ledge-free side of challenge 10 seeds 6, 7, 9, 10).
   - **A ledge there: seen in 6 of 6 looks** (challenge 10 seeds 1, 2 on the left; 6, 7, 9, 10 on
     the right). The depth is right within 0–5 cm: −0.22 m against 0.222, −0.15 against 0.144;
     the worst −0.24 against 0.294.
   - Floor height error on open floor: 10–14 mm at the 95th percentile.
   - Note: `cliff.drop_points` cannot be used for a side look. It drops points more than
     `CORRIDOR_DROP_M` (0.25 m) aside by design. A side look is judged by `depth_points`' "below"
     returns.

   - **Where the edge is: within −4.7 cm / +0.6 cm.** A line is fitted through the floor's
     boundary points (the farthest floor short of the first below-floor return, frame by frame),
     and the trunk's distance to it is compared with the truth (from the scene file, in the
     duck's start frame, jitter included):

     | Seed | Side | Glance (line) | Truth | Error |
     | --- | --- | --- | --- | --- |
     | 1 | left | 0.417 m | 0.438 m | −21 mm |
     | 2 | left | 0.331 m | 0.373 m | −42 mm |
     | 6 | right | 0.607 m | 0.609 m | −2 mm |
     | 7 | right | 0.460 m | 0.507 m | −47 mm |
     | 9 | right | 0.458 m | 0.458 m | 0 mm |
     | 10 | right | 0.521 m | 0.515 m | +6 mm |

     Negative means nearer than it is, which is safe. A first estimator, the farthest floor point
     wherever along the edge, read the right side 6–8 cm too far. That was the estimator, not the
     sensor.

   Open:
   - **The edge's direction from a right look.** It fits at +8–9° whatever the true angle (+0.3° to
     +7.7°). The distance is right; the line's direction cannot be trusted yet.
   - **Wall feet as "floor".** Near walls the floor class takes wall returns below the obstacle
     threshold (95th-percentile height error 68–83 mm against 10–14 on open floor).
   - **The head's commanded yaw is asymmetric.** robot.look asked −57° for the right and +68° for
     the left, yet the sensor sits at −67° and +68°. Cause unknown. Settling on the sensor's own
     yaw handles it.
   - **Only the simulator.** The real duck's head kinematics, the sag on its backlash hinges and
     its sensor's spread are not tested.
   - **The probe's first version was wrong,** and is recorded here because it was reported before
     it was caught. It counted `drop_points`, which ignore side drops by design, and took frames
     while the head was still turning. It led to two false statements: that a turned head misses
     drops, and that the head is asymmetric. Both were retracted.
3. Challenges 10 and 11: every pit seen (an event), and the closest approach to its edge by truth
   at least the margin.
4. Challenges 8 and 9 unchanged; no cliff stops in 1–7.

## Not covered

- The real duck: its head-yaw kinematics, how much the head sags on its backlash, and its sensor's
  range spread at a slant. The simulator's 1 cm agreement does not transfer.
