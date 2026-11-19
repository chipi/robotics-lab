# The simulated depth sensor's ranges: radial, pitched 2.4 to 2.9 degrees down (K34)

**Status:** measured 2026-11-19 (phase 3, stream B; read-only on recordings, no simulator run,
nothing edited under `robots/duck`). It answers the shortfall that [PHANTOM](PHANTOM.md) left open:
the recorded ranges were 6 to 11 % shorter than a ray cast from the pose the recording gives.

**Finding:** the simulator reports radial ranges, and its sensor looks about 2.5 to 2.9 degrees
further down than the head's kinematics (`frames.tof`) say. Both are what the duck's profile already
records; the duck's sim calibration numbers are right. What does not match is mapd's fixed model of
the sensor.

## What the simulator reports

`microduck_rl/src/mjlab_microduck/sim/tof.py`: 8×8 zones over 45°, zone centres at ±19.69° (the same
as `kinematics/src/tof.rs`), one `mujoco.mj_ray` per zone from the `tof` site along the unit beam,
the hit distance plus noise `0.003 + 0.02 × range / 4 m` (sigma, metres), in millimetres, status 5.
That distance is along the beam: radial, not along the optical axis. The `tof` site's orientation is
the simulator's own; `robotd` publishes `frames.tof` from the head's forward kinematics, which is
what mapd and the recordings carry.

## The test

For each frame the sensor was placed from the recording (truth x, y; IMU orientation; `odom_z`;
`frames.tof`), and for every pixel in rows 5 to 7 that read as floor (recorded/predicted between
0.75 and 1.05, range under 0.8 m) the pitch error that would make the recorded range the floor's was
computed, once reading the range as radial and once as axial (divided by the beam's cosine on the
optical axis, as mapd does):

| Run (frames) | Radial: median pitch error, rows 5 / 6 / 7 | Radial: row 7 spread over columns | Axial: medians, rows 5 / 6 / 7 | Axial: row 7 spread |
| --- | --- | --- | --- | --- |
| b9 r2, 0–31 s (452) | 2.87 / 2.78 / 2.72° | 0.51° | 2.07 / 1.26 / −0.11° | 2.26° |
| b11 r1, 300–400 s (1475) | 2.71 / 2.63 / 2.78° | 0.18° | 1.86 / 1.08 / −0.12° | 2.10° |
| ch11 seed 1, gate4 (580) | 2.44 / 2.40 / 2.50° | 0.49° | 1.62 / 0.81 / −0.50° | 2.31° |
| ch11 seed 5, gate4 (548) | 2.51 / 2.40 / 2.52° | 0.21° | 1.60 / 0.70 / −0.65° | 2.38° |

Read as radial, every pixel of every row and column gives the same 2.4 to 2.9° (columns within
0.5°); read as axial the answer changes by 2 to 3° between rows and columns, which a mounting error
cannot do. The shortfall is one downward pitch, about 2.5° in the challenge scenes (the 2.5° in
`robots/duck/calibration/sim.json`, which the navigator logs as `pitch_offset_deg 2.5, range_kind
radial`) and 2.6 to 2.9° in the apartment.

Object pixels (b9 r2, the cube `obj_3`, t = 14.4 to 17.4 s, rows 6 and 7; ratio of recorded to
ray-cast range):

| Pitch offset applied | cube pixels (n ≈ 120) | floor pixels, row 7 (n ≈ 230) |
| --- | --- | --- |
| 0° | 0.920 | 0.914 |
| 2.5° | 0.980 | 0.972 |
| 2.7° | 0.984 | 0.977 |
| 3.0° | 0.991 | 0.984 |

The 6 to 11 % shortfall of the PHANTOM note is the missing pitch; the object pixels and the floor
pixels move together, as a pitch error predicts. 1 to 3 % is left (the sensor height is taken from
`odom_z` and `frames.tof`: 1 cm of height is 4 % of a 0.25 m floor range).

## What does not match: mapd's model

`mapd` builds its `MapperConfig` from `robotd.toml`'s `[map]` with only `tof_latency_ms` read
(`mapd/src/main.rs`, `start_mapping`), so the sensor model is maploc's default in the simulator and
on a robot: `range_is_axial = true` (ranges divided by the beam's cosine) and `pitch_offset_rad` of
3° (`maploc/src/project.rs`; its own comment calls the axial choice "unsettled for the VL53L5CX").
On the simulator's radial ranges that makes every off-axis return longer than the beam's: by `1 /
(cos elevation × cos azimuth)`, 6 % at the bottom row's centre, up to 12.7 % at the corners (0.5 m
of range: 3 to 6 cm). The 3° pitch is within 0.1 to 0.6° of the 2.4 to 2.9° measured, so it is the
range model that differs. Predicted, not measured: where it shows in mapd's grid (walls and objects
placed farther off-axis, a flat wall bent). The duck's navigator already reads the sim as radial for
its own depth points (`cliff.configure`); mapd's grid is the part that does not.

## So

- **The duck profile's sim calibration** (`pitch_offset_deg 2.5`, `range radial`): consistent with
  the measurement (2.4 to 2.5° in the challenge scenes, 2.6 to 2.9° in the apartment); no change
  asked. The apartment's 0.1 to 0.4° higher median is not explained (the head posture while walking
  and tilt are candidates).
- **mapd in the simulator** assumes axial ranges; this is a setting of Pollen's code (not
  configurable from `robotd.toml` today), not of ours. Whether a grid built with the radial model
  matches the walls better was not tried (it needs mapd, or maploc's replay bench, run on a recorded
  frame set).

## NOT VERIFIED

- mapd and maploc were not run; the grid effect of the axial assumption is a calculation, not a
  comparison.
- The pitch error was estimated from floor pixels with the sensor height from `odom_z` and
  `frames.tof`; a height error and a pitch error are not separated by these data.
- The simulator was not asked for its `tof` site's true pose; the 2.4 to 2.9° is inferred from the
  frames.
- Four runs (two apartment windows and two challenge seeds); the real duck's sensor was not measured
  here.
- Noise: the simulator's range noise is symmetric, so medians were used; the spread of single pixels
  was not analysed.
