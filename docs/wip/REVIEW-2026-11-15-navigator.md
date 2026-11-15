# Review of the navigator and explorer (2026-11-15)

Independent, read-only review by the `advisor` agent on Fable 5.1, at the operator's request ("are we
adding rules that fight each other; what are our blind spots; how do we get further with the trials"),
over `duck/src/duck_lab/nav/`, the docs and the run logs (`duck/runs/explore9..12`,
`phase1-run15/17/18`, `tof-flat-0.json`). Every number below is the reviewer's, from its own scripts;
the robotics-lab session re-checked one (see the end). It led to [RFC-0008](../rfc/RFC-0008-challenge-course.md).

## Severity 1 — can put the duck on the floor or into furniture

1. **The false drop is real-surface returns misread as "below the floor", and the 3-frame rule
   suppresses it rather than removing the cause.** In trial 12 the frames that produced "below"
   points around both cliff stops came while turning, the points 0.00–0.02 m from wall `wG` by truth.
   The second stop (9 zones) added 51 drop points up to 2.06 m from the staircase. Leading hypothesis:
   `run.py` pairs the newest depth frame with the newest state (frames at 15 Hz, state at 20 Hz: up
   to ~50 ms apart), where Pollen's `autod` pairs each frame with the state nearest its `t_ns`; and
   a fixed `EXTRA_M = 0.06` along the beam at 0.5–0.75 m is only ~4° of pitch. The same error can hide
   a real drop when its sign flips. Not verified: the logs have no `t_ns` or raw frames.
2. **The margin budget is negative.** `LETHAL_M` 0.12 − footprint 0.083 leaves 3.7 cm, against
   localization error p90 4.4 cm (max 6.4) in trial 12 (2.9–4.0 cm in phase 1), half-cell
   quantization 2.3 cm, corner cutting up to 4.4 cm, pivot drift 4.1 cm/rad. In trial 12 a plan passed
   13–17 cm from the cabinet and truth clearance fell to 0.097 m. The tight pivot (0.11 m) has 2.7 cm
   of budget, checked against a cost map up to 3 s old: it can record a contact, not prevent one.
3. **Pivot drift in this simulator is forward; the turn rules look all round.** Over 10,513 pivot
   ticks (807 rad): +4.1 cm/rad forward, +0.2 cm/rad sideways. Upstream says the real duck drifts
   backwards (`autonomous.md`). The drift vector should be a per-robot calibration (beside
   `odom_scale`) and the pivot gate should test room along it.
4. **On a real duck, dark floor becomes a cliff.** An invalid beam where floor is expected counts as
   a drop; `autod` §5.2 treats statuses 4/13 as valid dark targets and 255 as observed clear. The
   simulator only emits 5, so this will not show before phase 5. Invalid should mean unknown, not drop.

## Severity 2 — stops it exploring

1. **"Trapped" is six refusals in a quarter of a second, from one pose, with no recovery tried.**
   The recovery is keyed on "start boxed in" and never runs for "no room to turn"; frontier choice
   ignores heading, so every candidate needs the turn just refused. Nav2 runs a recovery ladder
   (clear, spin, back up, wait) before giving up.
2. **Drop zones made 43 % of the known free floor lethal after the true cliff stop, 53 % after the
   false one** (walls 15 %). Every zone of every stop gets a permanent 0.45 m ring, plus 0.4 m behind
   and the edge extension. The detector is tuned for recall, the memory for permanence. Keep every
   stop, but store edges, and give a suspected drop a smaller ring until a second stop confirms it.
3. **The survey turn is a second, cruder turn implementation**: one clearance check, pivot or nothing,
   and one refusal ends the whole sweep. mapd's phantom cells near the dock (11 cells 0.6–0.7 m from
   anything real) gate the first survey; fewer surveys, "no frontier left".
4. **`CLIFF_STOP_M = 0.60` is nominal.** With the recorded sensor pose the rows meet the floor at
   0.65 / 0.49 / 0.39 / 0.31 m; nothing lies between 0.52 and 0.64, so the stop fires at ~0.49 m
   unless the trunk pitches forward — trial 8's 0.48 m and trial 12's 0.475 m. The comment's "room to
   turn round" is not what happens.

Smaller: the short lookahead's "near" includes unknown and shadow cells, so it applies everywhere off
the seen map; `_arc_clear` uses the nearest return of the central columns, floor and overhead included;
`keep_current` rejects a path whose first cells are lethal, forcing a replan every cycle inside a ring.

## Blind spots

- **Evaluation:** phase 2 has no clearance or contact column and no repeats; runs end before areas
  are measured; the only scenario bench is the stairs probe.
- **Logging:** no `t_ns`, no raw frames, no pitch rate — the false drop cannot be replayed, which is
  why each cause took one trial.
- **Behind the duck** nothing senses; the obstacle memory is the only guard, and the boxed-in recovery
  removes exactly that.
- **mapd's "free" is not walkable** (the stairwell, #599; floor under overhangs); seen floor covers
  the first only.
- **The real duck:** the reflex over Wi-Fi, backward drift, statuses 4/13, most ducks without a depth
  sensor.

## The reviewer's next three steps

1. **Log for replay, then diagnose the false drop offline:** frame and state `t_ns`, raw
   `distance_mm`/`status`, IMU pitch, roll and pitch rate; replay `drop_points` with nearest-`t_ns`
   pairing and a range-scaled threshold over every stairs and exploration log.
2. **Write the error budget down and derive the margins from it, per robot:** lethal ≥ footprint +
   p95 localization + half a cell + corner cut (≈ 0.16–0.17 m; a 42 cm doorway still leaves an 8 cm
   lane); the pivot gate along the measured drift; drop memory as edges, suspected or confirmed;
   drop the tight pivot unless the budget shows it stops before contact.
3. **A scenario bench with per-tick invariants**, run before every change, and no more 20-minute
   explorations until it is green: truth clearance ≥ 0.083 + 2 cm every tick, no false drop, and
   "trapped" only after ≥ 30 s and at least one recovery attempt.

## What the robotics-lab session checked

- **Item 1, in part.** Across all of trial 12, "below" returns are not specific to turning: 271 in
  pivots, 61 in arcs, 405 while walking straight, about a quarter of each within 5 cm of a real object
  (`check_below.py`). So low readings of real surfaces happen in every mode; whether turning makes
  them reach the cliff check's range is the open question step 1 answers. The reviewer's narrower
  claim (none in the straight-walking frames around the two stops) was not contradicted.
- The session's own earlier explanations of trial 12 (missing returns at grazing angles; outer columns
  making false drops likelier) were wrong by its pitch sweep: the old central-only check trips at the
  same ≥ 5° error.
