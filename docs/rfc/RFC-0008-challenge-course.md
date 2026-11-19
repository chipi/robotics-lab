# RFC-0008 — The challenge course: one difficulty at a time, then all of them

**Status:** Proposed (2026-11-15) — the operator's direction, for review; the second-opinion review
of the navigator (Fable advisor) is folded in when it arrives.
**Amends:** [RFC-0002](RFC-0002-robot-brain.md) §3.4 — phase 2's bar (decided by the operator,
2026-11-15: the challenges are the bar, the apartment is the final exam).
**Evidence:** [PHASE1-RESULTS.md](../wip/PHASE1-RESULTS.md), [PHASE2-RESULTS.md](../wip/PHASE2-RESULTS.md).

## 1. Why

Phase 2 has been run in the full apartment: every trial since the seventh ended within about two
minutes, each on a different difficulty, each followed by a fix for that one difficulty. The
apartment mixes all of them, so a run says little about any one skill, a pass can be luck (phase 1's
run 8 was, at the office doorway), and the rules have grown without a common basis — measured from
different points (trunk, sensor, cell edges), with nothing that checks they always leave the duck
something it may do (trials 7, 8 and 12 ended with nothing allowed). Trial 10 nearly fell.

## 2. The approach

- **One small scene per challenge**, generated like the apartment (`duck/sim/apartment_backlash.py`):
  only what the challenge needs — walls, the obstacle or the drop, a start, a goal or a mission.
- **Judged by the simulator's truth**: reached (or refused for a stated reason, where refusing is
  right), no contact, no fall, within a time limit.
- **Repeated with variation** — start pose, object positions and sizes jittered, about 10 runs per
  challenge — and reported as pass rates, not one result.
- **Invariants checked throughout every run**, not only at the end: by truth, never closer than a
  set distance to a drop and never touching anything; by the brain, some allowed action always
  exists. A broken invariant names the moment and the rule.
- **Then composed**: the challenges in sequence in one scene, then mixed (the parkour course), then
  the apartment as the final exam.

## 3. The challenges

As many as it takes (the operator); this is the first list, from the trials so far.

| # | Challenge | Skill | Seen in |
| --- | --- | --- | --- |
| 1 | Straight corridor to a goal | odometry, following | — |
| 2 | Doorways 80 / 50 / 42 cm wide | planner margins against the footprint | phase 1 run 4 |
| 3 | A box corner just inside a doorway | corner cutting, lookahead | phase 1 runs 9–12 |
| 4 | A box in the open, its back unseen | unseen space beside obstacles | trial 7 |
| 5 | U-turn in a 60 cm corridor | turning drift beside walls | trial 5, run 12 |
| 6 | Dead-end corridor; out without walking backwards | recovery | trials 7, 8 |
| 7 | Start wedged in a corner | boxed-in recovery | trial 4 |
| 8 | Step down, head-on | cliff check | trial 3 (fell) |
| 9 | Step down, approached diagonally | the corridor's cliff check | trial 10 (near-fall) |
| 10 | Walking along a ledge 0.5 m away | drop memory, side beams | trial 8 |
| 11 | A narrow passage beside a hole | drop zones against passage width | trial 6 |
| 12 | A table edge with no return at all | the no-return drop | — |
| 13 | A low overhang | overhead classification | — |
| 14 | A thin pole, a chair leg | small obstacles for an 8×8 sensor | — |
| 15 | A field of small boxes | replanning, the reflex | phase 1 runs 11, 16 |
| 16 | A home door's threshold, 0.5–1.0 cm (what the walking crosses) | stepping over it, false drops from pitch | trial 12 |
| 17 | Things on the floor: a cable, a rug's edge, a book | stepping over, not round | — |
| 18 | A step up and a step down | walking up and down, not refusing | — |
| 19 | A short flight of small steps, up | climbing | — |
| 20 | A short flight of small steps, down | descending | — |
| 21 | Ten goals in a row without a reset: one room, about 3 × 3 m, a few boxes, a hole; goals beside the boxes and the hole | localization drift (the belief against the truth, in position and heading, at each goal), pivots beside obstacles, glances | phase 1 run 4, explore b10a |
| 22 | One room, explored completely, a drop 0.5–0.8 m from the start | exploring coverage, and trapped near a drop | explore b9–b11 |
| 23 | Two rooms through a door 0.6–0.8 m wide (or a short corridor) | frontier choice, crossing a door | trials 4–6 |

1–20 are getting around safely; 21–23 build to exploring and close the course (the operator,
2026-11-19: §8 has the revision, and why there is no 24). 21–23 are not one goal to reach, so each
has its own rule, all judged by truth like the others (`duck-challenge --help`):

- **21** visits ten goals in turn on one simulator reset, in a room of about 3 × 3 m with two or
  three boxes and a stairwell-like hole against a wall. A room with ten plain goals would pass
  trivially (the belief's error in explore b11 is 0.02–0.07 m); the goals ask for what failed:
  four 0.25–0.4 m from a box (the duck pivots beside it, arriving and leaving: b10a's 0.9 m belief
  jump came while pivoting in place), two 0.55–0.7 m from the hole (the planner's zone and its
  glances at suspected drops), four in the open. Pass: every goal within 0.25 m by truth, and no
  contact, fall or drop margin broken. The belief's error is recorded at each goal, in position and
  in heading (yaw, belief against truth), with the goal's kind; it is reported, not judged. The
  sequence stops at the first goal not reached.
- **22** runs the explorer (not `go_to`) for 5 minutes in a room of about 3 × 3.5 m with up to three
  boxes and a stairwell-like hole 0.5–0.8 m from the start. Pass: safe, the run did not end
  `trapped`, and the map knows at least 75 % of the room's reachable floor.
- **23** runs the explorer for 8 minutes in two rooms (2.4–3 m a side) joined by a door 0.6–0.8 m
  wide, in the wall between them or at the end of a corridor 0.4–0.8 m long, the door ahead of the
  start or behind it. Pass: safe, not `trapped`, at least 75 % of each room's reachable floor
  known, and the door crossed (the duck's truth entered the second room).

**The coverage bar (22, 23): 75 % of the reachable floor.** The reachable floor is the scene's
level-0 floor the duck could stand on and walk to: at least the footprint (0.083 m) from every
obstacle's outline, at least the planner's drop zone (0.35 m) from the drop, and connected to the
start (a pocket walled all round is not asked for). The map's share is mapd's grid read cell by
cell against it (a known cell is free or occupied; the grid is put into the world by the run's
start pose and the odometry scale). 75 % is the apartment's phase 2 bar (a room's map within 25 %
of its floor, RFC-0002 §3.4), and it fits the scenes: the floor within 0.2 m of a wall, a box or the
drop is 25–33 % of the reachable floor in the scenes drawn (`tests/test_challenge.py`), the band
the planner keeps off (lethal zone 0.12 m; frontiers are not taken within 0.3 m of a wall) and the
8 × 8 sensor sees at a grazing angle. **The 75 % is provisional**: it was fixed before the first
run, and is to be set again from the first ten seeds of 22 and 23 (the first three seeds of each gave
22: 94 %, 89 %, 95 %; 23: room A 90 % with room B never entered, then 75 % / 82 % and 96 % / 96 %).
The coverage function is not challenge-only: `duck_lab.challenge.floor` takes a layout (floors and
obstacles in `sim/apartment_layout.json`'s shape) and regions, and gives the share known per region,
so the apartment's scoreboard can use it.

16–20 follow what the robot's body can
do: each draws its heights under the robot's measured step height (`calibration/<robot>.json`), with
a variant just over it where refusing (or going round, where there is a way) is right; ordinary home
stairs stay refusals (8, 9). Under the step height the robot walks over, never round (the operator,
2026-11-17).

## 4. What changes in the brain

- **One clearance model.** A single function — from the trunk's centre, minus the footprint — used
  by the planner, the turn rules and the reflex, for obstacles and drops alike.
- **Margins from measurement, not guesses.** Turning on the spot and the arc are primitives whose
  drift is measured per challenge (5, 6, 7); the margins follow from those distributions.
- **Fixes are proven on the challenge that shows the failure** and then on all others (no
  regressions), before any apartment run.

From the second-opinion review ([REVIEW-2026-11-15-navigator.md](../wip/REVIEW-2026-11-15-navigator.md)):

- **Log for replay.** Each depth frame paired with the state nearest its time (as Pollen's `autod`
  does), raw distances and statuses, the trunk's pitch, roll and pitch rate — so a failure can be
  replayed offline, not diagnosed one trial at a time.
- **An error budget, written down, per robot**: lethal zone ≥ footprint + localization (p95) +
  half a cell + corner cutting (≈ 0.16–0.17 m in the simulator; today 0.12); the pivot gate along the
  measured drift vector (forward in this simulator, backward on the real duck by upstream).
- **Drops as edges, suspected or confirmed**: every stop stays a stop; the memory keeps an edge per
  stop, a smaller ring until a second stop confirms it. Today's rings made half the known floor lethal.
- **A recovery ladder** before "trapped": survey, forget nearby obstacle points (never drops), a
  frontier within ±45°, a short creep forward where the corridor is clear — and "trapped" only
  after a time and a recovery tried. One turn implementation for the follower and the survey.
- **Invalid depth is unknown, not a drop** (the real sensor's dark-floor statuses), except where the
  sensor reports observed clear.

## 5. Order

0. Logging for replay; the mini viewer (`miniview`, pictures of a run for the AI and for
   reviews) and Rerun driven by Playwright, so a run can be looked at, not only counted.
1. The scenario runner: scene generation with jitter, truth scoring, invariants, pass rates; the
   world-model viewer on every run (`duck-world`). No more 20-minute apartment runs until it is green.
2. Challenges 1, 2, 3, 5, 8, 9 first — the ones behind the failures so far.
3. The clearance model and measured margins; then the rest of 1–20; then 21–23.
4. The course in sequence, mixed, and the apartment.

## 6. Open questions

- ~~The bar's numbers~~ — decided 2026-11-17 (§8): 100 % on the safety invariants, at least 8/10
  reach or refuse per challenge.
- How many runs per challenge are enough to trust a rate.
- Which challenges need the real duck's sensor quirks that the simulator does not model.

## 7. Alternatives considered

- **Keep running the apartment, fixing what fails.** The weekend's experience: each run shows one
  new failure; fixes interact; passes can be luck.
- **Pollen's autod instead of our navigator.** A comparison point, not a replacement: RFC-0002's
  phase 2 includes running autod in the same scenes.

## 8. Discussion

- 2026-11-15, operator: re-consolidate, step back, generalize; subgoals that compose into the whole;
  as many challenges as needed; passing them is phase 2's bar, the apartment the final exam.
- 2026-11-17, operator: "close all challenges we did not start and move to the apartment rather than
  trying to score 10/10 for all first 11". The bar: 100 % on the safety invariants (no fall, no
  contact, never under 0.15 m from a drop), at least 8/10 reach or refuse per challenge. Challenges
  1–11 become the regression gate run before each commit; next 12–16, then 17, 18–20, the apartment
  (numbered before the renumbering below: now 12–20, then 21, 22–24).
  A fall during a simulator state-stream stall is logged apart, out of our control for now
  (`duck/sim/probes/state_stalls.py`: 2 stalls over 200 ms in 132 runs, one a fall in challenge 9).
- 2026-11-17, operator, after challenge 16 (a 1.4–2.5 cm bar across a corridor) failed 10/10 (the
  duck stalled at it or tripped): the duck should walk over such a bar, not go round it; the same for
  anything it can step over, a step up and down, and a short flight of small steps up and down; a home
  door is the model. Challenges follow the robot's physical capabilities. Renumbered with whole
  numbers: the walking-over family is 16–20, the exploring challenges 21–24. The navigator must notice
  it is stuck (walking, the depth ahead not changing) whatever the cause.
- 2026-11-18, operator, challenge 16 picked up again: the walking crosses about 1 cm whatever the
  speed (`docs/wip/STEPS.md`: 1 cm 4/5 at 0.4 m/s, 1.5 cm 0/5, 2 cm 0/5 with falls), so challenge 16's
  bar is 0.5–1.0 cm, built edge to edge; 1.5–3.5 cm becomes a later "too high to cross: stop, do not
  fall" challenge once such a bar can be seen; the numbers go upstream on the operator's call.
- 2026-11-19, operator: the course closes at 23, with a revised plan. 21 (ten goals in a row, one
  reset) is one room of about 3 × 3 m; 22 (one room, explored completely) puts a drop 0.5–0.8 m from
  the start, the "no room to turn" blocker of explore b9–b11, worst beside the stairwell by the
  dock; 23 is two rooms through a door, the old 23 (a T-junction with two rooms) and 24 (two rooms
  joined by a door) merged. **24 is removed**: it tested room segmentation and area, and the robot
  no longer segments rooms — the operator defines the areas (RFC-0014) — so there is nothing left
  for it to judge. 22 and 23 are judged on the explorer's own run (a challenge mode of
  `duck-challenge` that reuses the apartment's explorer and its scoring), against the scene's own
  floors. After an advisor review (same day), 21 was redrawn: ten goals in a plain 3 × 3 m room would
  pass trivially, so the room has a hole and the goals sit beside the boxes and the hole, and the
  heading's error is recorded with the position's.
