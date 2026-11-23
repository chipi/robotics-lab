# Challenge 22's rim: a target beside floor the sensor never saw

Unit B1 of [PHASE5-NEXT-PLAN.md](PHASE5-NEXT-PLAN.md). Evidence: the 10-a-side batch
`item3-ch22x10-20261123-120033` (seed 1), two runs of the new navigator failed `drop_margin`; probes
`sim/probes/rim_approach.py` (the picks and the approach against the true hole) and
`sim/probes/rim_fixture.py` (freezes one pick into `tests/fixtures/ch22_rim_pick.json`).

## The scene

The hole is at (0.314, 1.003) in the run's world, 0.98 x 0.84 m, yaw -0.097 rad: x -0.18..0.80, y
0.58..1.42. The duck starts 0.57 m south-west of it. The judge fails a trunk centre under 0.15 m
from the outline (`judge.py:48`).

## What the map held

At the failing pick of run 125800 (t 266.4 s) the recorded `world` event had 44 drop points, all on
the **north** rim (the glance from the east at t ~243 s measured them; at least 0.59 m from the
target). The `pick`'s avoid list had one point, a failed target: `nav.drops` was empty (no cliff
stop in the run), and `explore_run.py:201` (before) built the avoid list from `nav.drops` only, not
the 44 edges the planner uses (`run.py:643`, `:649-650`). mapd draws the whole hole as **free** (the
grid at that pick: `.` over the hole's area, `?` only in two pockets). The frontier the target came
from is the unknown pocket three cells wide on the hole's west rim (belief frame, cells x 19-23, y
66-72).

## The picks and the approach

Run 125800 (min_drop 0.032 m): pick at 266.4 s, target world (-0.17, 0.68): 0.00 m from the hole's
outline by the epoch transform (the belief's drift is up to 0.12 m; the target is on the rim, not in
the hole). From (0.57, -0.11). The truth path, every second from 272 s: (0.28, 0.05) 0.53 m from the
hole, (0.06, 0.25) 0.35 m, (-0.12, 0.47) 0.156 m, at 283.5 s (-0.23, 0.60) 0.032 m, with the hole at
-60 to -25 degrees from the nose throughout: on the right, outside the 8x8 sensor's +-22 degrees.
The forward cliff check (`tof8x8.py` corridor, `run.py:1183` with `DROP_FRAMES = 3`) looks along the
line of travel; this approach never put the hole there.

Run 123656 (min_drop 0.079 m): pick at 236.5 s, target (0.92, 0.80), 0.14 m from the hole's east rim
(refused, no path); then at 247.1 s target (-0.90, 0.83) from (0.99, 0.50): the path ran west along
the south rim at 0.14-0.29 m with the hole at -67 to -102 degrees from the nose, nearest 0.079 m at
268.3 s. Same blindness: side-on, no drop point on that rim.

Before side (old navigator): in 8 of the 10 runs the explorer picked a target on the rim (t 30-128
s; with the true hole counted as unseen, the target's ring is 0.10-0.46 unseen). All 8 were stopped
by the forward cliff check (min_drop 0.19-0.47 m): the old navigator approached head-on, the new one
(side-drop suspects, glances, a hold-off) walks the rim sideways.

## The fix, and why this one

`explore.rim_unseen` (`explore.py:108-125`): the share of mapd's free cells within `RIM_M` = 0.35 m
of a target in which the depth sensor never saw floor (`Navigator.floor_seen_near`, 5 cm cells). A
target at or above `RIM_UNSEEN` = 0.10 is not offered (`explore_run.py`, `reachable`). For a
straight rim this is a target within about 0.21 m of unseen ground; the judge's 0.15 m plus the
belief's error. The explorer already refused a target with no seen floor within 0.10 m (upstream
issue 599, "mapd draws a stairwell as free"); this extends the same fact from the target's own cell
to its surroundings.

Chosen over: (a) a head-on last stretch: the planner owns the path, and the target need not be at
the rim (123656's path); (b) widening the side-drop check: it needs below-floor returns, which the
explorer's approach did not produce. The unseen-floor ring needs nothing the navigator does not
already hold.

Also: `Explorer.avoid` and `Explorer.hazard_costs` use the planner's hazard set (drops, edges,
suspects).

## Replay

With the true hole standing in for "never seen" (`rim_approach.py`): run 125800's pick at 266.4 s
has ring share 0.36 and is rejected (the next pick is world (0.84, -1.38)); run 123656's pick at
236.5 s, share 0.34, is rejected (next (0.61, -0.33)). Its pick at 247.1 s (share 0.00, 0.70 m from
the hole) is not caught by this rule: the path-level case stays open unless the sequence changes (it
follows from the east-rim leg that the rule removes). The recorded `floor_seen` is not in the ticks,
so the real navigator's ring share is read from the new `pick` event's `rim` field in the proof
runs.

## Proof runs

Challenge 22, seed 1, ten runs each, same scene; the runs are in
`~/.cache/robotics-lab-tests/b1-ch22{b,c,d}`.

| Code | Pass | drop_margin | trapped | coverage under 0.8 | min_drop median |
| --- | --- | --- | --- | --- | --- |
| item 3 batch (main), after side | 7/10 | 2 | 1 | 0 | 0.415 |
| control today (main's code) | 8/10 | 0 | 1 (+1 contact) | 1 | 0.459 |
| hazards only (`avoid`, `hazard_costs`) | 8/10 | 0 | 0 | 2 (`no_frontier_left`, 46% and 66%) | 0.33 |
| hazards + rim rule | 6/10 | 0 | 4 | 4 | 0.31 |

The two drop_margin failures did not recur in 20 runs of unfixed or fixed code today, so ten runs
cannot show the rim fix working; they show its cost. The rim rule's four trapped runs are the
existing "no room to turn (0.13-0.15 m to an obstacle)" refusal streak at the south boxes (one a
"start boxed in" at the east rim): its mechanism is not traced, only its correlation with the rule
(4 of 10 against 1 of 20 without). Challenges 11 (seeds 2, 3) and 22 (seeds 2, 3): all four pass.

## Decision (2026-11-23)

- **Kept:** the hazard set (`Explorer.avoid`, `Explorer.hazard_costs`). It is a plain bug: the
  explorer avoided drops only, while the planner avoids drops, edges and suspects. The unit test
  failed before the fix. In the simulator it cost no trapped run.
- **Not enforced:** the rim rule. `rim_unseen` is computed and recorded as the `pick` event's `rim`
  field, so later runs measure it, but a target is not refused on it. At `RIM_UNSEEN` = 0.10 the
  trapped runs rose from 1 in 20 to 4 in 10, and the two `drop_margin` failures it targets did not
  recur in 20 runs with or without it.
- **Open:** a path that grazes an unseen rim (run 123656 at 247.1 s), a rim whose hole mapd leaves
  unknown, and the trapped mechanism. B3 (robot-side drop guardrail) must not claim that a side-on
  approach to an unseen rim is covered.
