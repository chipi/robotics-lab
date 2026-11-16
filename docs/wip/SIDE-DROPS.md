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

   Open:
   - **Where the edge is.** The below-floor returns start where the edge's shadow allows on the
     left (0.81 m, against 0.81 m predicted for a 0.22 m ledge at 0.42 m). On the right they start
     later (1.0–1.7 m against 0.86–1.26 m). The margin needs the edge's position, not only that a
     drop exists; not measured yet.
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
