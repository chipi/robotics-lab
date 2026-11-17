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
