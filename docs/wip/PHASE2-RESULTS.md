# Robot brain phase 2 — exploring and rooms: results so far

**Bar** ([RFC-0002](../rfc/RFC-0002-robot-brain.md)): from the dock with an empty map, the duck
explores the apartment; all six rooms visited, and each room's area from the map within ±25 % of the
real one. Scored with `duck-rooms` (`duck/src/duck_lab/nav/rooms.py`) against the simulator's layout.

**Not met.** Phase 1 holds (run 15, [PHASE1-RESULTS.md](PHASE1-RESULTS.md)); exploring does not yet
get past the first rooms. Runs: `duck/runs/explore*` (not committed).

## The trials

| Trial | What changed before it | Rooms visited | Ended | What it showed |
| --- | --- | --- | --- | --- |
| 1 | frontier explorer (nearest frontier, survey after each leg) | — | stopped | targets underfoot and inside lethal zones |
| 2 | targets 0.6 m away, checked against the cost map | — | stopped | stop, replan and stop again by the stairs |
| 3 | "no new stop for a remembered drop" | — | **fell** | that filter switched the cliff check off over the unseen part of the stairs; removed |
| 4 | drop zones 0.45 m, escape 0.5 m, a truth guard (harness only) | 2 of 6 | 8.8 min, no frontier left | 85 % of the time in surveys; one boxed-in spot refused 37 frontiers |
| 5 | survey only with no frontier in sight; boxed-in recovery; stop after 6 refusals | 2 of 6 | trapped, 3 min | turning on the spot drifted the duck 26 cm, to 24 cm of the stairs edge |
| 6 | logging of plans and drops | 2 of 6 | stopped, ~7 min | reached the office; three 60 s timeouts chasing a door behind an unseen wall |
| 7 | phase 1's fixes, frontier scoring, the turn rules | — | trapped, 1 min | planned past a cabinet's unseen face and wedged the duck there |
| 8 | unseen cells by obstacles cost more; a monitored pivot | — | trapped, 1.5 min | trapped beside the stairs, 0.29 m from a remembered drop |

## What stops it now

- **Phantom obstacles.** mapd's grid and the obstacle layer both hold points where the simulator
  has nothing (two cells 26 cm from the dock; 0.16 m of "room" where truth had 0.28 m). They make the
  turn rules refuse turns that are safe.
- **The drop memory has holes.** The cliff check stops for what its central beams see ahead, and the
  planner keeps away from those points only. Approaching the stairs at an angle, the stairwell's
  corner is closer than anything remembered: trial 8 reached a target 0.3 m from it, and first saw
  the drop at 0.48 m, not the 0.60 m stop distance.
- **No way out beside a drop.** The duck does not walk backwards (`duck/sim/probes/backward.py`:
  no motion at −0.15 and −0.3 m/s), a pivot needs 0.30 m from any drop, and an arc needs no drop in
  front. Stopped close to the stairs, nothing is allowed.
- **Turning on the spot moves the duck** in the simulator (upstream issue #597), which is why the
  rules above exist.

## Next

The world model in the viewer ([ROADMAP.md](ROADMAP.md)): mapd's grid, depth points, remembered
obstacles and drops, plans, belief against truth — so the phantoms and the drop memory's holes can
be seen run by run before they are fixed.
