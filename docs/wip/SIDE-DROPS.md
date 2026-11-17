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

## Built, closed loop (2026-11-17)

Suspect early from the forward sensor, confirm with a glance, as planned. What the batches found on
the way, and what the code does now:

- **The glance's edge.** Traced per direction, all frames together, ending where the floor's run from
  the duck has a gap. Not extended past what was seen: a line fitted through a rim ran diagonally
  when the rim held the pit's far wall (challenge 10 seed 1) or went round a corner (challenge 11
  seed 2), and its extension put the goal or the passage inside the ring. A direction with only
  below-floor returns is a drop, its rim the nearest of them, and the floor before it unknown, not
  floor: a look had cleared a true suspicion that way and the duck then passed 0.141 m from the pit.
- **Suspicions.** One next to a measured edge joins it without a look (ten looks along one ledge
  before). One that blocks the way is walked toward and looked at, not refused for. Floor 10 cm
  from it clears it.
- **After a cliff stop the duck looks along the edge**, 0.4 m past each end (the operator's choice).
  Where the drop goes on, or the look saw nothing, the hole is taken to go on; where it saw floor, it
  ends. This is what lets the ring shrink: 0.45 had stood in for the hole's unmeasured length.
- **Rings from the error budget** (the advisor's review, the operator's choice of its split). Each
  ring is its kind's turn-on-the-spot gate plus the following's (~3 cm) and the belief's (~2.5 cm)
  error, so the duck may turn wherever the planner may put it. Each gate less the pivot's drift
  keeps the judge's 0.15 m and the belief.

  | Drop known from | Ring | Turn gate |
  | --- | --- | --- |
  | a cliff stop's points | 0.35 | 0.30 |
  | a glance's edge | 0.32 | 0.26 |
  | a suspicion | 0.32 (what it becomes) | — |

  Pivot drift, 87 pivots on 2026-11-17 (`sim/probes/turn_drift.py`): p95 5.1–7.9 cm, max 7.9 cm.
  The glance's error since the rim fix, 54 glances: −14/+6.4 cm looking aside, −18/+3 cm ahead.
  The 0.32 ring also keeps a path held at it out of the cliff check's corridor (0.305 with errors).
- **A turn while walking** is refused only for a drop within 0.45 m where it turns (from 20° outside
  to 120° inside), not for any drop ahead.
- **The stall rule** counts again from the path as it is when the map learns a drop.
- **Not done, and why:** a filter that let the cliff check ignore a drop near a measured edge was
  built and removed: it is trial 3's "do not stop again for a remembered drop" (grid.py), and the
  edges it relied on were sparser than the replay that seemed to support it.

Results, 10 seeds each, simulator:

| Challenge | Gate 3 (16th) | One ring 0.35 | Split rings |
| --- | --- | --- | --- |
| 1–5 | — | 50/50 | 50/50 |
| 6, 7 | — | 8, 8 | 9, 9 |
| 8, 9 (refuse) | — | 10, 10 | 10, 10 |
| 10 | 10 | 8 | 9 |
| 11 | 8 | 8 | 8 |

Closest approach to a drop over the 40 drop runs with the split rings: 0.299 m (judge 0.15).
The failures left:

- Challenge 11 seed 2: one edge point 17 cm outside the pit closes the 0.66 m passage at the 0.32
  ring. Its source is not found: a replay of the glance does not reproduce it (it pools more frames
  than the duck took). Glance records now keep their rim points to trace it next time.
- Challenge 11 seed 7: a loop of reflex stops on the block. A path at the wall's 0.12 m ring sits
  inside the obstacle reflex's corridor (0.123 m half width): the same mismatch as the drop rings
  had, for walls.
- Challenge 10 seed 2: refused near the goal (not read yet).
- Challenges 6 seed 2, 7 seed 3: refused for no room to turn; both fail the same way on the
  16th's code.

## Measured, then two more fixes (2026-11-17, afternoon)

- **The belief drifts in open scenes.** `sim/probes/belief_drift.py`: |belief − truth| p95 13–14 cm
  and up to 20 cm in challenges 10 and 11 (its change over 10 s p95 10 cm), against 1.6–3.9 cm in
  challenges 1, 5 and 8. It grows with distance walked, along the heading, with no jumps
  (`sim/probes/scale_by_speed.py`: truth / belief 0.987–0.998 walking straight in challenges 1 and 5,
  1.029–1.071 in 10 and 11). The same gait in every scene, so mapd's corrections are the likely cause,
  not the odometry scale; raw odometry is not recorded, so this is not proven. The error budget's
  2.5 cm belief holds in the short scenes only; open, for challenge 21 (ten goals in a row).
- **False suspicions** (`sim/probes/false_suspects.py`): none in 40 drop-free runs; the ones that
  closed challenge 10's goal came from floor 1.1–2.4 m away read 6.6–7.9 cm "below", just past
  cliff.EXTRA_M (6 cm), most likely the trunk's pitch. **Fix:** a below return feeds a suspicion only
  when 6 cm + 3.5 cm per metre of range under the floor (`side_drops.below_counts`). Replayed over 2
  days of runs: false cells 92 → 17, drops suspected before the closest approach 157 → 151 of 180,
  the lead unchanged (17 s).
- **A goal inside a drop's ring** (the operator: go as close as is safe and say so). **Fix:** the
  nearest free place within 0.20 m of the goal is aimed at and reported ("reached, held off"); only
  when the way there is no longer than 1.25 × the straight line + 0.3 m, so a goal across a drop is
  still refused (`sim/probes/hold_off_replay.py`: all 20 recorded refusals of challenges 8 and 9 stay
  refusals; 1.5 × let one walk 2.4 m round the drop).
- **A fall during a state-stream stall** (challenge 9 seed 10): the robot's state stopped for 655 ms
  just after a cliff stop, while the physics ran on. `sim/probes/state_stalls.py`: 2 stalls over
  200 ms in 132 runs. Cause unknown, outside the navigator; logged apart for now (the operator).

All 11 challenges with both fixes, 10 seeds each: 1–4 10/10, 5 9/10, 6 8/10, 7 8/10, 8 10/10,
9 9/10 (the stall's fall), 10 10/10, 11 10/10: 104/110, every challenge at the bar (RFC-0008 §8:
100 % safety, the stall apart; at least 8/10 reach or refuse). The other failures are reflex loops
and turn refusals near walls (challenges 5–7): the planner's work, not the drops'.

## Not covered

- False suspicions near walls (challenge 10 seeds 5 and 8: 0.28–0.6 m from the drop, 0.15–0.25 m
  from the room's east wall, with the belief 17 cm off). Cause not found.
- The real duck: its head-yaw kinematics, how much the head sags on its backlash, and its sensor's
  range spread at a slant. The simulator's 1 cm agreement does not transfer.
