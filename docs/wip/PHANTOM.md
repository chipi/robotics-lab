# The phantom obstacle by the dock (K3): a real 7 cm cube

**Status:** investigated 2026-11-19 (phase 3, stream B; the operator: investigate it first,
read-only on recordings, no navigator fix without the operator's word). Linked from [known
issues](KNOWN-ISSUES.md) K3 and K25.

**Finding:** the cluster is not phantom. It is a real object in the simulator: `obj_3`, a 7 cm cube
(half size 0.035 m, 50 g, a free body) placed at world (−0.30, 0.10), 0.35 m behind the dock start
pose. The apartment's layout file (`robots/duck/sim/apartment_layout.json`) does not hold it,
because `robots/duck/sim/layout.py` dumps only the geoms on the world body, and the cube hangs on a
`freejoint` body. Every truth comparison made against that file called the cube "0.5 m from any real
outline". The cluster needs no fault in mapd, the navigator or the sensor model to exist; the one
thing here not explained is a 6 … 11 % shortfall of the recorded ranges against a ray cast (NOT
VERIFIED).

## Evidence

All on b9 r2 (`data/runs/duck/apartment/explore-b9-r2`) unless said; recordings read, never written.

1. **The cells.** The first map grid the navigator reads (`pick`, t = 30.9 s) has three occupied
   cells in a vertical line at map x = −0.27, y = 0.09 … 0.19. In the world (the run's epoch) that
   is (−0.27, 0.08 … 0.17), the cube's east face (x = −0.265, y 0.065 … 0.135) within a cell.
2. **Which frames, which rows, which pose.** Re-projecting the recorded raw depth frames by maploc's
   own rules (`project.rs`: statuses 5 and 9, a return higher than `0.03 + 0.03 × range` over the
   floor is an obstacle, 3° pitch offset, the sensor placed by `trunk pose × frames.tof`): 43 of the
   452 frames before 31 s put an obstacle point inside 0.15 m of the cluster, from t = 14.44 s to
   17.33 s, and only from pixels row 7 (the bottom row), columns 3, 4 and 5 (column 2 once), every
   one with status 5 (valid), ranges 263 … 298 mm, the points 0.054 … 0.067 m above the floor, over
   maploc's floor line of about 0.04 m. maploc's keyframe votes a cell occupied at 3 or more
   agreeing frames (`min_hits = 3`), so 43 frames make the cluster. The pose: the opening survey is
   a 360° turn in quarter turns, the head sweeping at each stop; at t = 14.4 … 17.3 s the trunk
   faces −x (belief yaw −3.07 rad, truth −3.06) at about (0.01, 0.12), the sensor at x = −0.07, 0.09
   m in front of the trunk's centre along that heading, looking back down at the cube.
3. **The geometry matches the cube.** A ray cast from the truth pose at t = 14.9 s and 15.6 s
   against the floor and a box of the cube's size at its position gives: bottom row columns 3, 4, 5
   hit the cube (predicted 294 mm; recorded 276, 269, 270 and 271, 274, 272), columns 0 … 2 and 6, 7
   the floor (predicted 423 … 434 mm; recorded 378 … 397). The recorded ranges are 6 … 11 % shorter
   than predicted on every pixel of rows 6 and 7 (the cube pixels as much as the floor ones), so
   which pixels are near is the cube's pattern, and the shortfall is the same kind everywhere.
4. **Every run.** In 54 of 54 apartment runs with a map (`explore-b*`, `find-fridge-*`, `frames-*`,
   `relo-*`), the first world grid has 1 … 6 occupied cells within 0.15 m of the cube's outline; 0
   runs without.
5. **The detector.** `phantom_obstacle` over b9 r2, b10b r1, b10b r3 and b11 r1: with the layout
   file alone, 1 phantom each at (−0.27 … −0.28, 0.12 … 0.14), 0.47 … 0.52 m from any outline (the
   figure in PHASE3-PREP B2); with the free bodies in the layout (the seven, from `apartment.xml`;
   the layout file was regenerated with them, K32), 0 each.

## Does it explain early "no room to turn"?

Partly, once, and not as the main cause. Refusals and tight pivots (events `refused`, `tight_pivot`)
in b9 r2, b10b r1 and r3, b11 r1 to r3, b12 r1 to r3, by truth distance to the cube:

- **b11 r2, t = 32 … 39 s** (the run that ended "trapped" at 38.8 s with 6 refusals): the duck stood
  0.20 … 0.23 m from the cube (truth (−0.04 … −0.07, 0.01 … 0.05)); the nearest occupied map cell is
  the cube's, 0.175 … 0.234 m from the belief. The first refusal ("no room to turn", room 0.146 m
  against the 0.15 m gate) is consistent with that cell (a cell's half width off the 0.175 m): by
  truth the room was 0.20 m, so the mapped cube was about 0.055 m too near (a cell and the belief's
  offset). The next refusals (room 0.197 m, over the gate) refuse on the other number in the same
  decision, "0.25 m to a drop" against the 0.26 m edge clearance: a drop memory 0.254 m from the
  duck while the stairwell is 0.7 m away, the rim the glance at 32.3 s placed (the rim fixed in
  `af7a6fb`). So the cube is the likely start of the burst, and the misplaced edge kept it going;
  the second part is measured, the first is a reading of one number.
- **Every other early refusal near the start** is "no path on the map" with a goal cost of 10⁹ or
  infinity, a lethal goal (b10b r1 32.5 s, b11 r1 34.8 … 40.8 s, b12 r2 35.1 s, b12 r1 50.2 s), with
  the start cost 1.0 … 3.7 (30 for b12 r1 at 50 s): the cube may add inflation to the start cost;
  the refusal is the goal's.
- **b12 r1's "no room to turn" at 110 … 120 s** is at (−0.98, 1.75), 1.7 m from the cube: K22.
- b9 r2, b10b r3, b11 r3, b12 r2, r3: no "no room to turn" within 0.8 m of the cube.

So: of nine runs, one early refusal burst has the cube as its first cause. The cube is a real
obstacle the duck may see 0.35 m behind it at every start; it is not a reason the early refusals are
systematic.

## What this changes

- **One truth file.** `layout.py` now dumps the free bodies too (at their reset positions), and
  `apartment_layout.json` was regenerated with them (82 geoms, 89 now; none changed or removed): the
  operator's call, 2026-11-19. `observatory anomalies --layout
  robots/duck/sim/apartment_layout.json` is the whole truth; without the free bodies
  `phantom_obstacle` fires on every run at the cube.
- **K32:** the layout dump leaving out the free bodies. Closed by that regeneration. It moves phase
  1's go-to goals (`draw_goals`): see PHASE3-PREP "Stream B results".
- **K25:** b11 r3's six remembered points 0.33 … 0.41 m from every layout geom are at `ball_1` (a 4
  cm sphere at (2.40, 2.30); the points are at (2.36 … 2.39, 2.28 … 2.36)); b11 r1's group at (2.17
  … 2.23, −2.46 … −2.41) is at `obj_2` (2.10, −2.40). b11 r2's one point at (0.02, 0.21) is 0.29 m
  from the cube's face, not on it: not explained.
- **The navigator:** nothing was changed. Options for the operator, not done: the explorer's start
  could step forward before the opening survey; the survey could ignore it; or leave it, as it is a
  real object.

## NOT VERIFIED

- mapd was not run. The projection above is my re-implementation of `project.rs` in Python from its
  source; the 3-frame vote, the keyframe's local frame and the grid render were read, not replayed.
  The cluster's agreement with the cube is by position (1), by pixel and time (2) and by ray cast
  (3).
- The 6 … 9 % shorter recorded ranges are not explained here (the simulator's radial ranges against
  mapd's axial assumption, and the 2.5° pitch offset against its 3°, are candidates, not tested).
- The cube's pose is its XML reset position; the recordings do not carry free bodies' poses, so
  whether a run pushed it is not known (a push would show as occupied cells elsewhere, none seen in
  b9 r2's first map).
- The ray cast was done for two frames (14.9 s and 15.6 s) of one run; the other 41 frames and the
  other runs were checked by projection only.
- Only the apartment's seven free bodies were looked at; whether other simulated scenes (the
  challenges) hold any was not checked.
- "Early refusal" was taken as within the first 120 s of nine runs and within 0.8 m of the cube;
  other runs (b1 … b8, find-fridge, relo) were not read for refusals.
