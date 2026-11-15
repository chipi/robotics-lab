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
| 16 | A threshold or bump that tilts the duck | false drops from pitch | trial 12 |
| 17 | Ten goals in a row without a reset | localization drift | phase 1 run 4 |
| 18 | One room, mapped completely | exploration coverage | — |
| 19 | A T-junction with two rooms | frontier choice | trial 6 |
| 20 | Two rooms joined by a door | room segmentation and area | trials 4–6 |

1–16 are getting around safely; 17–20 build to exploring.

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
3. The clearance model and measured margins; then the rest of 1–16; then 17–20.
4. The course in sequence, mixed, and the apartment.

## 6. Open questions

- The bar's numbers: pass rate per challenge (100 % for drops and contacts; less for reaching?).
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
