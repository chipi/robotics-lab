# Exploring the apartment: progress

Stream A (2026-11-17): the duck explores the whole apartment from the dock. One row per batch; a
batch runs only after a fix, to confirm it (the operator, 2026-11-17: "a structured way to measure
progress and drive improvements").

**Bar** (phase 2, [RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.4): all six rooms visited, each
room's area on the map within ±25 %, no falls, no contacts.

**How a batch is run and scored** (in `duck/`):

```bash
sim/explore_batch.sh b2 3 20      # 3 runs from the dock, 20 min cap, each after a simulator reset
.venv/bin/python -m duck_lab.nav.explore_score runs/explore-b2-r1 runs/explore-b2-r2 runs/explore-b2-r3 --md
```

The loop: rank the blockers by the exploring they cost (runs ended, minutes lost); reproduce the top
one from the recorded runs (no simulator); fix it and check the fix on the recordings; then one
batch to confirm.

## The plan (the operator, 2026-11-17: "document this and keep going")

In the bar's order — safety first, then reach, then quality:

1. **Safety floor.** Falls: look before you step (b3: no falls; challenges 5-11, ten seeds each:
   no contact, no fall). Contacts: remembered obstacles kept consistent with the duck (the relative
   error's worst tenth, 4-21 cm, is past the 12 cm margin); its replay check is
   `sim/probes/map_relative_error.py`, the worst tenth under the margin.
2. **Reach all six rooms.** Fixes 2-5 (loops and traps that ended runs), measured by b4; then the
   scoreboard's top blockers: the bedroom never entered, targets chased through the bath-office
   wall, stalls (the largest time cost in b3).
3. **Map quality: the areas within ±25 %.** Not worked on yet: the best run saw 10-35 % of each
   room's floor. Exploring that finishes a room (a survey inside each room, frontiers ranked by
   what they would reveal) within the 20 min budget.
4. **Speed: scanning beside the way** (RFC-0012 §2.1, the operator's "maybe both"): the head looks at
   unseen floor beside the path while walking, so look before you step stops less (b3 r3: 40 looks,
   1.9 of 10.8 min).
5. **Land and connect.** Challenges 1-4 rechecked, then commit (push on the operator's go); "explore
   the apartment" as a Mission Control library goal with this scoreboard as its pass condition; the
   real duck later, rehearsed on the simulator first.

## Batches

| Batch | Code | Runs | Rooms visited (median / best) | Areas within 25 % (best) | Contacts / falls | Top blocker |
| --- | --- | --- | --- | --- | --- | --- |
| b1 (baseline) | `c9c24f8` | 3 | 2 / 2 | 0/6 | 0 / 0 | refused: no room to turn |
| b2 (fix 1) | `c9c24f8` + fix 1 | 3 | 2 / 2 | 0/6 | 0 / **1** | refused: no path on the map |
| b3 (fix 1 + look before you step) | `c9c24f8` + both | 3 | 2 / **4** | 0/6 | **2** / 0 | stalled: reflex stop answered by the same plan |
| b4 (+ fixes 2-5, glance) | `c9c24f8` + all | 3 | 2 / 2 | 0/6 | **7** / 0 | no frontier left (fix 5 retired too much) |
| b5 (fix 5 local, 0.6 m) | `c9c24f8` + all | 3 | 2 / 3 | 0/6 | **2** / 0 | stalled: reflex stop answered by the same plan |
| b6 (head fix, low band) | `f06d48f` | 3 | **3 / 5** | **1/6** | 0 / 0 | refused: no room to turn |
| b7 (+ retired cells only) | `f06d48f` + retire | 3 | 2 / 3 | 0/6 | 0 / 0 | refused: no room to turn (`lm_office`, 3/3) |

## b1, the baseline (2026-11-17)

| Run | Rooms | Ended | Walked | Coverage (corridor / office) | Legs (reached / stalled / refused) |
| --- | --- | --- | --- | --- | --- |
| r1 (`explore-1117b`) | corridor, office | trapped at 3.1 min | 14.4 m | 37 % / 23 % | 5 / 3 / 6 |
| r2 | corridor, office | trapped at 2.0 min | 9.3 m | 24 % / 14 % | 4 / 0 / 9 |
| r3 | corridor, office | trapped at 1.6 min | 6.0 m | 19 % / 26 % | 1 / 0 / 6 |

No run reached the kitchen, the living room, the bedroom or the bath. Blockers across the batch:

| Blocker | Times | Minutes lost | Runs it ended | Where |
| --- | --- | --- | --- | --- |
| refused: no room to turn | 12 | 0.4 | 2 | office |
| refused: no path on the map | 9 | 1.4 | 1 | corridor, office |
| stalled: without getting closer | 3 | 1.6 | 0 | corridor, office |

What the runs' events show (read from the legs, not yet reproduced):

- Every run ended **trapped in the office next to something the duck sees**: r1 and r3 4–6 cm from
  `lm_office`, the office's landmark (a standing capsule the depth sensor sees but that does not
  collide in the simulator: `collides: false` in `sim/apartment_layout.json`), r2 11 cm from the
  office cabinet. Close to it, every turn is refused, six refusals end the run.
- **Targets inside obstacles:** r3's first target was inside the office cabinet; hold-off stopped
  the duck 11 cm from the cabinet's corner, where it could not turn. (Hold-off's event says "the
  goal is inside a drop's ring" for any blocked goal cell, obstacles too: a labelling bug, noted
  earlier.)
- **"No path on the map"** toward the corridor and the stairs side (targets at y −0.8 to −1.5) from
  the office.

Not established yet: how the duck gets within 4–11 cm of something it sees, and why those paths do
not exist on the map. That is the next step, from the recordings.

## b2, fix 1: no frontier next to a seen wall (2026-11-17)

Fix 1 (`explore.frontiers`): free cells within 0.30 m of an occupied cell or of the navigator's
remembered obstacle points are no frontier (a 0.8 m doorway keeps its middle 0.2 m); each pick now
records its inputs (event `pick`), so replays of b2 on are faithful (9 of 14, then 27 of 37 picks
reproduced; the navigator's own reachability check, not recorded yet, explains the rest).

| Run | Rooms | Ended | Walked | Legs (reached / refused / aborted) |
| --- | --- | --- | --- | --- |
| r1 | corridor, office | trapped at 1.5 min, 9 cm from the office cabinet | 9.5 m | 8 / 6 / 0 |
| r2 | corridor, office | **aborted at 1.9 min: the truth guard, 0.05 m from the staircase** | 13.4 m | 11 / 5 / 1 |
| r3 | corridor | trapped at 0.6 min, at the dock: six "no path" targets in the stairwell | 1.4 m | 0 / 6 / 0 |

What changed: targets in or within 15 cm of a wall or object fell from 18 of 34 (b1) to 12 of 37;
the duck got further (r1 up the north corridor to the bedroom doorway, r2 round the stairs into the
south corridor). What did not: rooms visited (median 2). What got worse: **safety** — r2 came within
0.05 m of the stairwell's corner at an angle (the corner hole PHASE2-RESULTS records from trial 8),
and the harness's truth guard ended the run. Not a fall, but against the bar it counts as one.

Tried and dropped: "fix 1b", unknown smaller than 0.25 m² enclosed by the map opens no frontier (an
object's unseen inside). The replay of b2 r1's cabinet pick showed no change: there the cabinet's
unseen inside joins the office's unexplored south, so the frontier is real and the target pulled
back from it lands in the cabinet.

Next, by the bar's order (safety first):

1. The stairwell corner: why the cliff check did not stop r2 at 0.05 m (from r2's recording).
2. "No path on the map" (14 refusals, ended 2 runs): the explorer re-picks targets in the same
   unreachable frontier (r3: six stairwell targets in 1 s, then "trapped" at the dock, free to walk
   north). Candidate: a refused target retires its whole frontier cluster, and refusals for
   unreachable targets do not count toward "trapped".

## b3, look before you step (2026-11-17)

Look before you step ([RFC-0012](../rfc/RFC-0012-look-far.md) §2.1, `nav/step_check.py`): the strip
0.20–0.40 m ahead along the path, across the duck's width, must be floor the depth sensor has seen
(cell by cell); an unseen spot stops the duck to look. Checked before the batch: challenge 11 seed 1
passed with 5 looks, challenge 8 seed 1 refused with 2 (one seed each, not the regression gate).

| Run | Rooms | Ended | Walked | Looks (time) | Contacts |
| --- | --- | --- | --- | --- | --- |
| r1 | corridor, office | trapped at 3.2 min beside the office shelf | 17.7 m | 11 (0.5 min) | **2** |
| r2 | corridor | stopped by hand at 2.4 min: four stalls in the office doorway | 4.9 m | 2 (0.1 min) | 0 |
| r3 | **kitchen, living room, bath, corridor** | stopped by hand at 10.8 min: four stalls between kitchen and living room | 51.0 m | 40 (1.9 min) | 0 |

r2 and r3 were stopped by hand once they stalled four legs in a row at one spot (stalls do not end a
run); their `map_grid.json` was written from their last pick event (t 132 s and 641 s), so their
areas are from that map.

What changed: the first run past two rooms (r3: four, 51 m); the stairwell corner that ended b2 r2
was passed with looks (r3 looked at four spots round it, all floor, and refused the targets inside
the opening); no abort. What did not: areas within 25 % (0/6). New: **two contacts** in r1, the
office doorway's north frame (the corridor–office wall's end), 7.7 cm from the trunk centre at 0.3
m/s — a door frame cut, not a look.

Blockers by time: stalls 5.9 min (14), most of them the reflex loop — a reflex stop answered by the
same plan, 28 times in r2 (the cabinet's corner in the reflex's straight-ahead corridor while the
path curves past it) and 26 in r3; "no path on the map" 13 (1 run ended); a 60 s timeout; "no room
to turn" 3.

Next, safety first:

1. The door-frame contact (r1).
2. The reflex loop: after a reflex stop with the plan still clear, turn to face the path before walking.
3. The stall clock runs during looks (b3 r1 leg 4 stalled while looking 4 times, all floor).
4. Hold-off picks a stand-in point without room to turn (b3 r1: 11 cm from the shelf; b1 r3, b2 r1).
5. A refused target retires its whole frontier; refusals for unreachable targets do not count toward
   "trapped".

## After b3: fixes 2-5, the relative error, the glance (2026-11-17)

**Relative error** (measurement first, as agreed): `sim/probes/map_relative_error.py` takes the
obstacle points the navigator remembers within 1 m, relative to its belief, and places them from the
truth pose. Over b3 r1 and r3: median 1-10 cm off the real surface, worst tenth 4-21 cm — against a
belief that is 0.05-0.9 m off the world. The map mostly drifts with the duck; the tail (old points
seen before the drift moved) is what passes the 12 cm margin, as at r1's door frame. Next fix after
these: remembered obstacles kept consistent (a fresh view of a surface replaces its stale points),
with this probe as its replay check.

Fixes, built (uncommitted, `make test-duck` PASS):

- **2, the reflex loop:** after a reflex stop the follower turns on the spot to the path's lookahead
  before walking, so the reflex looks the way the duck will walk (`run.py`, reflex branch).
- **3, the stall clock:** time spent looking before a step is not time without progress
  (`Progress.pause`; tested in `test_replay.py`).
- **4, hold-off with room to turn:** `grid.nearest_free(..., room_m=PIVOT_OBSTACLE_M)`; no such point
  within reach leaves the goal refused (tested in `test_nav.py`: without the rule 0.15 m from the
  object, with it 0.17 m).
- **5, an unreachable frontier:** a target refused with "no path on the map" retires its whole
  frontier cluster, and those refusals do not count toward "trapped" (`explore_run.py`).

Single-seed checks then found a regression from look before you step: challenge 7 seed 1 refused,
its start fenced in by two glances that said "drop" in a scene without a drop. `glance_distance.py`
(glances at 0.12-0.50 m, five bearings): not distance — every glance into the open room read a
"drop" from far floor, 1.7-2.5 m away, read 6-9 cm low; the glance counted every below-floor return,
without the range-dependent threshold (`side_drops.below_counts`) every other frame uses. Fixed in
`glance_at`; challenge 7 seed 1 then reads floor at all 40 glance spots. The challenge regression
run (5-11, ten seeds each) is the check that glances still see the real drops beside the way.

## b4, fixes 2-5 and the glance (2026-11-17)

Worse than b3: every run ended "no frontier left" at 3.2-5.5 min with two rooms, and r3 had seven
contact entries in three episodes.

- **Fix 5 retired too much.** One "no path" refusal near the stairwell retired a 124-point frontier
  cluster (r1), 201 points by r2's first logged pick: the cluster ran along the corridor, so the
  ways north and south went with it, and nothing was left. Fix 5 is changed to retire only the
  cluster's part within 0.6 m of the refused target (b2 r3's six stairwell targets were within
  0.5 m of each other).
- **Contacts.** The office door frame's south end twice (walking at 0.3 m/s, 7.6-8.2 cm; then
  turning on the spot, 7.3-8.0 cm — fix 2's turn after a reflex stop, permitted by room measured on
  a map a few cm off) and a desk leg once (standing, 8.1-8.2 cm). All three are the relative error
  (remembered obstacles a few cm off against a 12 cm margin); it is the top item now.

## b5, fix 5 retiring 0.6 m (2026-11-17)

r1 entered the **bedroom** for the first time (office, bedroom, corridor; 33 m; no contact; "no
frontier left" at 7.1 min). r2: two rooms, office coverage 46 % (the best yet), two contact entries
at the corridor console's corner, passed beside the duck while turning (7.5-8.1 cm). r3: trapped at
2.0 min. Reflex stops answered by the same plan: 0, 20, 1 — fix 2 helps in some runs, not in r2.

Three runs a batch is noisy: b3 reached four rooms in one run, b5 three; the medians (2) have not
moved. What the contacts share (b3 r1, b4 r3, b5 r2): a corner of a wall or an object beside the
duck while it turns past it — the door frame's end, the console's corner. At b3 r1's contact the
navigator's memory (24 s old) held no obstacle point within 0.55 m of the duck and mapd an occupied
cell at 0.25 m, the truth 0.08 m: next, the depth frames before each contact, to tell a corner never
seen up close (a look before turning past it, scanning beside the way) from one seen but misplaced
(the drift).

## The gate on the branch: challenge 11 below the bar, no merge (2026-11-18)

Challenges 1-11, ten seeds each, on the branch with the graded margin ring (`grid.margin_cost`,
edge cost 100): safety held (no contact, no fall), 6, 7 and 10 at 8 of 10, **challenge 11 at 6 of
10**: three "reached" 0.26-0.30 m from the goal (over the 0.25 m bar) and one refusal. My reading,
not yet checked: the graded ring keeps the plan farther from walls, so the walks are longer and the
belief has drifted more by the end. Edge cost 40 instead of 100, challenge 11 again
(`runs/gate3-ch11`): **7 of 10** — two "reached" at 0.27 and 0.32 m, one stall 2.66 m out (s2).
Main's last run of challenge 11: 8 of 10.

So the branch is not merged. What the bar says here is the trade the margin ring makes: more room
from walls (the contacts in b3-b5) for more drift at the goal. Edge 40 is kept on the branch (better
than 100 on the only challenge that failed). Not yet looked at: s2's stall, and whether the misses
are the drift (belief vs truth at the end) or the hold-off (the goal moved out of the ring). That is
the next check before another gate; the fix for the drift itself is the localization work of
challenge 21, not a navigator constant.

**Checked the same day: neither — a glance left the head pitched down.** From the recordings
(`sim/probes/head_after_glance.py`, plus truth against belief per run): no miss was a hold-off
(`held_off` none in every run); at "reached" the belief was 0.20-0.40 m behind the truth on the
branch, 0.00-0.04 m on main's runs without a glance, and each glance added drift. The odometry read
0.97-1.00 of the true distance on main and 0.89-0.91 on the branch, at the same 0.3 m/s, straight or
turning, long after a stop — and only after the glances: in ch11 s7 it read 0.98-1.02 until the
third glance, 0.87-0.89 after it. The head joints say why: walking under robotd's default head
command (zeros) the head sits at neck ~13°, pitch ~20°; `glance_at` restored "the joint angles it
had" by sending those measured angles as the command, and `robot.head` is a command to the walking
policy, not a joint target, so each glance pitched the head further down — after three, neck 44°,
pitch 83° for the rest of the walk. A duck walking with its head on its chest strides differently
from the one the odometry scale was measured on, and its depth sensor looks at its feet.

Main has the same glance code (1-4 glances a run there, odometry 0.95-0.97); look before you step
multiplied it (3-13 glances a run). Fixed: a glance ends by sending robotd's default command
(`HEAD_WALK_CMD`), with a test in `test_replay.py` that failed before the fix (it sent 13°/20°).

Challenge 11 again on the fix (`runs/gate4-ch11`): **9 of 10**, every reach 0.12-0.18 m from the
goal, belief 0.03-0.05 m from the truth (was 0.20-0.40), the odometry 0.98-1.03 of the truth.
Seed 2, which stalled before, went round the pit after a long detour. The one failure, seed 4, a
timeout: at the pit's edge, facing it, the plan needed a 75° turn; the turn on the spot was refused
because the room to turn read 0.123 m (needs 0.17), so the follower arced, the cliff check stopped
the arc, and the same stop came back every 7 s for 70 s. The drops' own gate passed (0.52 m from the
cliff points, 0.33 m from the edges). What read 0.123 m: one of mapd's whole occupied cells, at
(0.72-0.77, 0.23-0.28), while the nearest remembered obstacle point was 0.221 m away and the truth's
nearest obstacle 0.215 m — the block's cell placed about 9 cm closer than the block
(`sim/probes/room_replay.py`). I first blamed the drops' rings and changed the room to leave them
out; the replay showed the room was 0.123 m without them too, so that change was reverted before any
result was counted. Open: a mapd cell placed a few cm off reads as no room to turn (the relative
error again), and a cliff stop that comes back unchanged should end the leg, not run to the timeout.

The order agreed with the operator (2026-11-18): a full sweep is a big commitment, run only when
confident. So: hard seeds first — challenge 11 seed 4, the gate2 failures (10 s2, s8; 6 s3; 7 s3),
drops (8 and 9, seeds 1-3: with its head up the duck sees drops sooner and from farther) and 12-16
(seeds 1-3, never run on this branch) — and the full 1-16 sweep only if those hold
(`runs/gate6-hard`, on the head fix alone).

**The hard seeds (gate6, 2026-11-18): not enough to sweep.**

| Run | Result | Reading |
| --- | --- | --- |
| 10 s2, 10 s8, 6 s3 | pass | all three failed in gate2 |
| 7 s3 | refused, no room to turn (0.11 m) | the same as main |
| 11 s4 | timeout | the mapd cell above, again |
| 8, 12 (s1-3) | 6/6 right (refused across the drop) | |
| 9 s1 | right | then s2 **crashed**: `Set changed size during iteration` |
| 13, 14 (s1-3) | 6/6 | |
| 15 s1-3 | 2/3: s1 **contact** 0.075 m with small2 | safety |
| 16 s1-3 | 0/3: two refusals, one fall | walk-over family, parked; main 0/10 |

- **The crash** (fixed): the depth-frame thread adds suspected drops while a glance's
  `SuspectMemory.clear` iterates over them. Now over a copy; a test in `test_side_drops.py` does the
  add inside the iteration and failed with the crash's message before the fix. Very likely also the
  unexplained challenge 9 crash in the first gate.
- **The contact, not fixed:** small2 is 6.6 cm tall. Every return lower than `FLOOR_MARGIN_M`
  (8 cm, plus 3 cm per metre of range) is floor (`cliff.py`), so the box was floor to the duck: no
  point remembered, passed 0.156 m from its centre. Main has the same limit: its `challenges-new1`
  run of 15 s1 touched small2 (0.058 m), `challenges-margin1` passed it at 0.109 m. Boxes of 5-8 cm
  are in challenge 15 by design (5-25 cm), so this is a sensing gap, and it is a decision: lower the
  margin (and measure what floor reads above the floor first), or treat low things as the walk-over
  family's.

**The low band (the operator, 2026-11-18: measure, then lower the margin; what to walk over
depends on how tall a thing is, 1 cm and 7 cm are different; adjusting challenge 15 is
acceptable).** Measured
first (`sim/probes/floor_heights.py`, `low_persistence.py`; 27 runs since the head fix, 20 min of
depth frames, 10 low boxes): flat floor reads within +2 cm in 99 % of returns but +4.5-7 cm in one of
a thousand; low boxes read +5-6.5 cm, so a single return cannot tell them apart. A 5 cm cell read in
3 different frames can: at 3.5 cm + 2 cm/m, 0 phantom cells in 20 min and 8 of 10 boxes caught (5 at
the 8 cm margin); missed: 6.5 and 7.0 cm. Built: `cliff.low_points` (the band between that and the
floor margin; a 2 cm top stays floor, a 6 cm top is low, 15 cm an obstacle, `test_cliff.py`) and the
navigator remembers a low cell once `LOW_FRAMES` 3 different frames saw it (`test_replay.py`). The
map takes it; the reflex still stops on the obstacle class only.

Rerun (`runs/gate7-low`): **challenge 15 10/10**, no contact (s1 0.123 m from the boxes, was
0.075). Doorways not closed by phantoms: 1, 2, 3 seeds 1-3 9/9. The hard seeds all passed this time:
11 s4, 10 s2, 10 s8, 6 s3, 7 s3; 8, 9, 12 9/9 refused across the drop as they should; 13, 14 6/6.
Challenge 16 0/3 (two falls at the bar, one refusal): the walk-over family, parked, main 0/10. The
6.5-7 cm boxes the band can miss stay open; challenge 15's smallest box is not changed yet.

## b6, the head fix and the low band (2026-11-18)

The best batch yet: rooms median 3 (was 2), best 5 (was 4), the first area within 25 % (1/6), no
contact and no fall in 146 m walked.

| Run | Rooms | Areas ok | End | Walked | Legs reached / refused / stalled / timeout |
| --- | --- | --- | --- | --- | --- |
| r1 | 3 (office, bedroom, corridor) | 1/6 | no frontier left, 4.3 min | 24 m | 21 / 3 / 1 / 0 |
| r2 | 5 (kitchen, living, office, bath, corridor) | 1/6 | no frontier left, 15.5 min | 102 m | 44 / 3 / 5 / 4 |
| r3 | 2 (office, corridor) | 0/6 | trapped, 3.7 min | 20 m | 19 / 7 / 0 / 0 |

Blockers by time lost: timeouts 4x (4.0 min; bath, corridor, living), stalls 6x (2.9 min), "no
path on the map" 6x (1.7 min; bedroom, corridor), "no room to turn" 7x (0.5 min, but it ended two
runs: r3 trapped, r1's office). r1 and r2 ended "no frontier left" with rooms unvisited (r1: kitchen
and living at 0 %): the frontier list ran out before the apartment did. Not yet looked at: why each
of those frontiers went (retired, walled off by `WALL_M`, or never seen), and r3's seven refusals.

Looked at the same day (`sim/probes/last_frontiers.py`): at r1's last pick 11 frontier clusters
(446 cells, one of 194) were left, every cell within `AVOID_M` 0.4 m of an avoided point — and 188
of the 214 avoided points were frontier cells retired by fix 5 (three "no path" refusals), each
avoided like a failed target, a 0.4 m disc each. Changed: retired cells go to their own list and
take out only frontier cells within `RETIRED_M` 0.07 m of them (`explore.without_retired`, tests
in `test_explore.py`); failed targets keep `AVOID_M`. Replayed at the same pick: 56 usable cells and
a target in the corridor (r2's last pick: 5; `reachable()` not replayed).

## b7, retired cells only (2026-11-18)

Worse, and not for the change's reason: all three runs ended **trapped in the office at 2.2-3.8
min** by "no room to turn" (18 refusals), at the same spot as b6 r3 and b1 — beside `lm_office`, the
office's landmark, a standing capsule (about 4-66 cm high) the depth sensor sees and the duck can
walk through (`collides: false`; the judge does not count it). At the refusals the map gave
0.05-0.10 m of room, 10-18 remembered points within 0.2 m, the sensor's nearest return 2-10 cm; the
truth's clearance to anything that collides was 0.24-0.28 m, and the duck 3 cm from the capsule's
surface. What decides it: the duck got 3 cm from a thing it sees — with a real pillar that is a
contact. There are six such landmarks, one per room (`lm_*`). The retire change itself is not
measured by b7: no run lived long enough to need it.
