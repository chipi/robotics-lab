# Robot brain phase 1 — the navigator: results

**Bar** ([RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.4, revised by the operator 2026-11-14): 20
go-to goals, each from the dock with an empty map, in the office and the north corridor; zero falls,
zero contacts (trunk centre within 8.3 cm of an obstacle's outline), upright; every goal reached or
refused with a reason, no timeouts; ≥ 18 reached within 25 cm of the goal by simulator truth.

**Met on 2026-11-14: run 7 at the edge of the bar, run 8 with margin** — 20 of 20 within 25 cm, no
refusals, no contacts (closest 9.3 cm), no falls. Code: commits "phase 1 — the obstacle layer; run 7
meets the bar" and "phase 1 — the two fixes after run 7; run 8". Runs: `duck/runs/phase1-run*`
(not committed); score with `duck-eval` (`duck/src/duck_lab/nav/evaluate.py`).

## The runs

| Run | What changed before it | Reached ≤ 25 cm | Refused | Timeouts | Contacts | Falls | What it showed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | first navigator | 6 | 11 | 0 | 2 | 0 | goals beyond the map refused; routes past half-seen furniture |
| 2 | goals beyond the map; wall margin 28 cm, all impassable | 0 | 20 | 0 | 0 | 0 | the margin stranded the duck |
| 3 | lethal core + expensive margin | — | — | — | — | **1** | walked onto the staircase (no cliff check); run stopped |
| 4 | cliff check, calibration 0.91, costs, scope, scoring by the duck's size | 6 | 4 | 4 | 8 | 0 | goals chained (not the bar): drift to 43 cm; doorway closed on 10 cm cells |
| 5 | each goal from the dock; 5 cm cells; reflex memory per zone | **20** | 0 | 0 | 4 | 0 | touches at the doorway: the cabinet's side was not on the map |
| 6 | lethal 12 → 15 cm | (stopped after goal 3: still touched the cabinet) | | | 1 | 0 | zone size was not the cause |
| 7 | the obstacle layer (what the sensor sees within 60 cm, every tick) | **18** | 2 | 0 | **0** | 0 | **bar met**, at its edge |
| 8 | lethal back to 12 cm; a drop must persist 3 frames | **20** | **0** | 0 | **0** | 0 | **bar met with margin**: closest 9.3 cm, errors 12-17 cm (median ~14) |

## Run 7, honestly

- **18 reached is the minimum the bar allows.** Median truth error ~14 cm, all 18 within 17 cm.
- **One goal passed the cabinet at exactly 8.3 cm** — the contact threshold; it counts as no contact
  only because the check is "closer than". Four more passed between 9.4 and 10 cm.
- **Both refusals are the navigator's faults**, fixed after the run and confirmed by run 8 (goal 12
  reached at 14 cm from the cabinet, goal 15 reached; the staircase test still stops 42 cm before the
  edge):
  - goal 12: the 15 cm lethal zone around the obstacle layer's cabinet and wall points closed the
    office doorway → lethal back to 12 cm (run 5's touches at 12 cm came from the unmapped side,
    which the layer now sees);
  - goal 15: a "drop" on flat corridor floor while turning — one depth frame read against a state a
    few tens of ms apart → a drop must persist for 3 frames.

## Not covered

- **Contacts are an approximation**, not MuJoCo's contact list (the body server does not expose it):
  the trunk centre against obstacles' outlines in plan, with the duck's largest radius.
- **Each goal starts from a fresh map at the dock.** Chained goals (run 4) drifted to 43 cm: no
  correction from revisiting places; that is phase 2's ground (exploring, mapd's loop closures).
- **Rooms behind walls the duck has not seen** (bath, bedroom, kitchen, living room) are out of
  scope; phase 2.
- **One scene, one seed, the simulator only.** The odometry calibration (0.91) is the simulator's;
  the real duck needs its own (phase 5). The simulator's odometry finding is drafted for Pollen
  ([UPSTREAM-ODOMETRY-DRAFT.md](UPSTREAM-ODOMETRY-DRAFT.md)).
- **The cliff check is tested on one staircase**, from one direction, with a truth guard; the
  table-edge case (no return at all) only synthetically.
- **The duck's depth sensor:** Pollen's docs say most ducks have none fitted; the navigator needs it.
