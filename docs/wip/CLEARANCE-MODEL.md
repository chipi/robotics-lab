# One clearance model (RFC-0008 §4), 2026-11-16

The operator's choice, after challenges 6 and 7 (commit 9ee931e), from these options: the clearance
model; the pivot gate only; loosening the scenes; or moving on with them failing.

## Why

The planner's margins and the pivot gate are measured on mapd's 5 cm cells (0.0455 m scaled). A wall
cell is about 4.5 cm, and the surface can lie anywhere inside it. `grid.clearance` also measures from
the duck's cell centre, not its position. Together, the room reads up to about a cell short.

- Challenge 7: 3/10. All 7 failures are refusals, none a contact. The map's room read 0.07–0.08 m
  where the truth was 0.10–0.14 m, against an 0.083 m footprint.
- Challenge 6: 6/10.

## What changes

The navigator already keeps exact obstacle points: depth hits within 0.6 m, about 3 cm apart
(`Navigator.blocked`).

1. **Explained cells.** A mapd wall cell with an exact point inside it, or within half a cell of
   it, is left out of the walls: the points describe that obstacle more precisely. Cells without
   exact points stay, such as far walls or what the sensor has not seen up close.
2. **Planner.** Around exact points, the lethal and margin zones are measured from each cell's
   centre to the point itself, not rounded to the point's cell.
3. **Pivot room** (`clearance`): the minimum of the distance to the exact points and the distance
   from the duck's own position to the squares of the remaining wall cells.
4. **Points while standing.** The current depth frame is remembered before the first decision of a
   leg. At challenge 7's refusals the memory was empty because the duck had not moved yet.

Margins are unchanged: `LETHAL_M` 0.12 m, the tight pivot 0.11 m. Only the measurement changes.

## Proof

1. Unit tests: explained cells, clearance to points and to cell squares, and a 0.45 m corridor that
   points keep open where whole cells close it. Mutation checks on each.
2. Replay: `sim/probes/room_models.py` on the recorded refusals.
3. Closed loop, 10 seeds each: challenges 6 and 7 against 6/10 and 3/10, then 1–5, 8 and 9 for
   regressions. Contacts and drop margins are judged by truth, so a model that cuts too fine shows
   up as a failure, not a pass.

## Results, 2026-11-16 (closed loop, 10 seeds each)

| Challenge | Before (9ee931e) | With the model |
| --- | --- | --- |
| 6 dead end | 6/10 | 10/10 |
| 7 wedged | 3/10 | 2/10 |
| 5 U-turn | 10/10 | 10/10 |
| 1, 3, 4, 8, 9 | 10/10 each | 10/10 each |
| 2 doorways | 9/10 | 10/10 |

- No contacts and no falls. Closest to a wall: 0.113 m, against the 0.083 m footprint. Closest to
  a drop: 0.366 m (ch9-s3).
- Challenge 7's start room now reads 0.135 m against a truth of 0.134 m; whole cells read 0.079 m.
- What still refuses in challenge 7 is the pivot's own motion, within the gate's budget. The kick
  creeps about 1 cm forward and the belief is off by about 1.3 cm during it. The footprint is
  0.083 m, so the total is about 0.106 m against the 0.11 m gate. The failing seeds start with a
  wall about 0.13 m from the trunk.

The kick (`follow.step`) now stands still: vx 0 for the first second, then the robot's pivot speed.
`sim/probes/pivot_kick.py`, 6 starts each from a stand, turn rate 1.2 rad/s:

| Kick speed | Turns started | Forward in the kick |
| --- | --- | --- |
| 0 | 6/6 | 5–11 mm |
| −0.03 | 6/6 (one slow) | 2–16 mm |
| −0.06 | 5/6 (one stalled at 8° after 3 s) | 0–4 mm |

## Not covered

- The real duck's error budget: localization, sensor noise and its pivot. The margins stay the
  simulator's.
- Drops: still remembered and grown as now (`DROP_LETHAL_M`).
