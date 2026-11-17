# ADR-0015 — The scenario runner: small generated scenes, scored by truth, as pass rates

**Status:** Accepted (2026-11-16, the operator)
**Date:** 2026-11-16
**Context documents:** [RFC-0008](../rfc/RFC-0008-challenge-course.md) §2 "The approach" and §5
step 1, [ADR-0014](ADR-0014-replay-logging.md) (every run is written for replay),
[ADR-0007](ADR-0007-run-file-format-2.md)

## Context

The navigator has been judged on 20-minute apartment runs: one result per run, every failure mixed
with every other, and a fix proven by the next apartment run. RFC-0008 asks for one small scene per
difficulty, repeated with variation, judged by the simulator's truth and reported as a pass rate.

What the simulator gives, checked on 2026-11-16:

- **Any scene file.** `duck-sim` takes a path in `DUCK_SIM_SCENE`. A scene written outside upstream's
  folder loads when it includes the robot by absolute path and links `assets` to upstream's (the
  robot's `meshdir` is relative to the scene file): MuJoCo loaded it with the keyframes, and the
  simulator booted on it with the duck standing (trunk 0.116 m) in 39.8 s.
- **A fixed start.** The body server puts the duck at (0, 0) facing +x on every start and takes no
  position (`Body.place`). The only reset is a restart (`simreset.reset`, ~40 s).
- **Every world geom is seen.** The depth sensor casts `mj_ray` against all of them.
- **No contact list.** The body server does not expose MuJoCo's contacts; truth is the trunk pose.

## Decision

### A challenge is a function from a seed to a scene

- `duck_lab.challenge` holds one builder per challenge: `build(seed) -> Scene`. A `Scene` is boxes
  (walls, furniture, steps: centre, half sizes, yaw, z range), floor slabs (a drop is a slab lower
  than the start's), the goal, a time limit, and what counts as right: `reach`, or `refuse` where
  refusing is right (a goal beyond a drop).
- **Variation is in the seed**: each builder draws its sizes and positions from stated ranges
  (corridor width, doorway offset, drop depth, start yaw). The same seed is the same scene.
- **The start is jittered by moving the world.** The duck always starts at the origin facing +x, so
  a start offset and yaw are applied as the inverse transform to the whole scene. What the duck
  meets is the same as if it had started elsewhere.

### One scene, three outputs, from the same description

- **The simulator's scene file**: upstream's `scene_backlash.xml` (its keyframes), the full-collision
  backlash robot by absolute path, an `assets` link, the floor plane replaced by our slabs and boxes.
  Written to `~/.cache/duck-sim/scenarios/<scene id>/`, never into upstream's checkout.
- **miniview's scene** (`scenes/<scene id>/scene.json` in the lab data folder): boxes and drop
  hazards, so every challenge run shows its room (the gap of the first goal screenshots).
- **The truth layout**: the same geoms in the shape of `sim/apartment_layout.json`, so the
  evaluation's footprint and underside code scores challenges as it scores the apartment.

The scene id is the challenge and the seed: `ch2-s3`.

### A run is the evaluation's, on the challenge's scene

`duck-challenge <challenge> --runs 10` resets the simulator on each seed's scene, starts a navigator,
gives it the goal, and writes the run as a miniview run (`duck/<scene id>/<run>`, kind `challenge`,
ADR-0014), so every run can be looked at and replayed.

### Judged by truth, every tick, not only at the end

Invariants are checked on every truth sample; the first one broken names the time and the rule, and
is written into the run as an event, so the viewer shows the moment:

| Invariant | Rule |
| --- | --- |
| no contact | the trunk centre stays `FOOTPRINT_M` (0.083 m) from every box's outline |
| no fall | the trunk stays above `FALLEN_Z_M` (0.06 m) over the start's level |
| drop margin | the trunk centre stays `DROP_MARGIN_M` (proposed 0.15 m) from a drop's edge |
| in the scene | the trunk stays within the scene's bounds |

A run passes when no invariant broke and the outcome is the right one: `reach` — the navigator says
reached and truth is within `REACHED_M` (0.25 m) of the goal, inside the time limit; `refuse` — it
refuses, with its reason, before the time limit. A stall is not a refusal: it stops safely but gave
up rather than said why not (the operator, 2026-11-16, after challenge 8's first run passed on a
stall). A challenge's result is its pass rate, with each failure's reason and run key.

### The first six (RFC-0008 §5, step 2)

Built with the runner so it is proven on them; the ranges are first guesses, to tune when they run.

| # | Challenge | Scene | Right | Varied |
| --- | --- | --- | --- | --- |
| 1 | Straight corridor | walls both sides, goal 2–2.8 m ahead | reach | width 0.7–0.9 m |
| 2 | Doorways | a wall across with a gap of 0.80, 0.50 or 0.42 m (by seed) | reach | gap offset ±0.1 m |
| 3 | Box corner inside a doorway | 0.6 m gap, a box whose corner is 0.05–0.2 m inside the gap's line | reach | corner, goal side |
| 4 | Box in the open, its back unseen | a 0.3–0.6 m box 1.0–1.4 m ahead across the line to the goal, in a walled 3.6 × 2.4 m room; the goal 0.6–0.8 m behind it | reach | box size, its offset ±0.15 m, goal offset ±0.2 m |
| 5 | U-turn in a 60 cm corridor | corridor 0.6 m wide, goal 1.5 m behind the start | reach | goal 1.2–1.8 m |
| 6 | Dead-end corridor | the start inside a dead end 0.45–0.55 m wide, its closed end 0.2–0.3 m ahead, 0.9–1.1 m long, opening behind into a room; the goal in the room beside the mouth. (A dead end entered from outside is on the map before the duck walks in: the sensor reaches 4 m.) | reach | width, end, length, goal side |
| 7 | Start wedged in a corner | facing a room's corner, a wall 0.20–0.25 m ahead of the trunk and one 0.20–0.25 m beside (left or right; wall centre lines); the goal 1.5–2 m behind. Distances from the trunk, which stands 0.05 m ahead of the start (`scene.TRUNK_START`); with the jitter, no wall nearer than 0.13 m, the pivot gate's budget (docs/wip/CLEARANCE-MODEL.md) | reach | the clearances, the side, the goal |
| 8 | Step down, head-on | the start's floor ends 1 m ahead; the goal is on the lower floor | refuse | depth 0.1–0.3 m |
| 9 | Step down, diagonally | the same, the edge at 30–60° to the start's heading | refuse | angle, depth |
| 10 | Walking along a ledge | the start's floor ends in a drop 0.1–0.3 m deep running beside the way, 0.4–0.6 m from it (left or right); the other side walled 0.8 m out; the goal 2.4–2.8 m ahead on the upper floor. A straight walk does not show the drop to the sensor (9 of the first 10 runs saw none): it tests not drifting toward a ledge, not drop memory | reach | ledge distance, depth, side |
| 11 | A narrow passage beside a hole | a pit 0.1–0.3 m deep, 0.8–1.0 m long, from the passage to the room's wall on one side; a block from the passage to the wall on the other, so the passage is the only way; 0.65–0.8 m wide (block face to pit edge), the duck's line 0.3–0.4 m from the edge; the goal beyond. A pass is not yet evidence of drop handling: the forward sensor cannot see a pit 0.3 m or more to the side, and 7 of the first 10 runs passed without seeing it (docs/wip/CLEARANCE-MODEL.md, the review of 2026-11-16) | reach | width, edge, depth, side |
| 12 | A table edge with no return | the start's floor ends 0.9–1.1 m ahead, met at 0–45°; the floor beyond is 4.5 m down, out of the sensor's 4 m range, so every beam past the edge returns "no target"; the goal is down there | refuse | edge distance, angle |
| 13 | A low overhang | a shelf 0.6 m deep right across the straight way, 1.0–1.3 m ahead, in a 3 m wide room; its underside 0.32–0.40 m (walk under it) or 0.15–0.22 m (go round), by seed; the goal 2.6–3.0 m ahead | reach | underside, position |
| 14 | A thin pole, a chair's legs | legs 2–4 cm across on the way to the goal, 1.0–1.4 m ahead: one pole, or four in a 0.38 m square under a seat at 0.42 m, by seed | reach | leg size, position |
| 15 | A field of small boxes | 6–10 boxes 8–20 cm across and 5–25 cm tall between the start and the goal, 0.45 m apart or more, none within 0.3 m of the start or the goal | reach | count, sizes, positions |
| 16 | A threshold to step over | a bar 1–3 cm high, 4 cm deep, across a 0.8 m corridor 0.8–1.2 m ahead: a raised floor, walked over (not a contact); the goal 1.4–1.8 m beyond | reach | height, position |

Every scene also gets the start's jitter: ±0.05 m, ±10°.

## Consequences

- **Positive:** a failure is one difficulty, repeated until its rate is known; a fix is proven on the
  challenge that shows it, then on all (no regressions), before an apartment run; every run is a
  miniview run with its room.
- **Negative:** ~40 s of restart per run (10 runs of a challenge ≈ 15 min; the first six ≈ 1.5 h). A
  reset that keeps the simulator up needs an upstream body-server change.
- **Negative:** "contact" stays the footprint approximation, not MuJoCo's contact list.

## Not decided here (the operator's)

- The bar: decided 2026-11-17 (RFC-0008 §8): 100 % for the invariants (no contact, no fall, drop
  margin) and at least 8/10 reach or refuse per challenge; challenges 1–11 are the regression gate.
- `DROP_MARGIN_M` (0.15 m proposed) and the ranges above.
- **The brain's invariant** (RFC-0008 §2: "some allowed action always exists") needs the navigator to
  report its allowed actions each tick; not in this step.
- **`duck-world` on every run** (RFC-0008 §5 step 1): proposed that the miniview run, with its scene,
  map, memory and plan, is the world-model view of every run, and `duck-world` stays for Rerun on
  demand.

## Alternatives considered

- **Positions inside the apartment as challenges.** No new scenes, but the apartment cannot make a
  42 cm doorway or a diagonal edge on demand, and every run would cross unrelated difficulties.
- **A placement op in the body server** (start anywhere, reset without restart): faster, but a change
  to upstream's code; worth offering upstream once the runner shows the cost.
- **Scenes written into upstream's folder** (as `apartment_backlash.py` does): avoids the `assets`
  link, but fills another project's checkout with generated files.
