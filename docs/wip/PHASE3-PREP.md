# Phase 3 prepared: robot profiles (RFC-0020) and anomalies (RFC-0019)

**Status:** prepared 2026-11-19 by a read-only planning pass (its scans delegated; line numbers
not all spot-checked; nothing run), for [the plan we execute on](EXECUTION-PLAN.md) phase 3. Plans
against the navigator as it will be after phase 0 (branch `nav-frames`). Decisions at the end.

## A. RFC-0020, steps 1–3

### A1. The duck's profile (draft, `robots/duck/profile.json`)

One file: `body`, `factsheet` (VDA names), `footprint`, `locomotion`, `sensors`, `looking`,
`localisation`, `error_budget`, `judge`, `capabilities`, `guardrails`, `rates`, `control`,
`adapter`, `plugins` (`duck-walk@1`, `tof8x8@1`, `mapd@1`, `duck-head@1`), and `variants.sim` /
`variants.real` for what differs (pivot creep −0.06 m/s in the simulator, 0 on the real duck; the
depth sensor's calibration 2.5° radial in the simulator, 3° axial real; the odometry scale 0.91 by
speed in the simulator, unknown real). Measured numbers keep their `measured` and `why` from
`duck/calibration/sim.json`, verbatim. Every number's source:

| Block | Numbers (source) |
| --- | --- |
| footprint | radius 0.083 (`evaluate.py:39`, copied in `run.py:82`, `adapters/duck.py:20`, `step_check.py:17`); height 0.272 (`evaluate.py:38`); overhead 0.30 (`evaluate.py:42`, `cliff.py:105`); lethal 0.12, inflate 0.28 (`grid.py:16,18`); stand-off 0.25 (`semantic_map.py:23`); goal clearance 0.35 (`evaluate.py:43`) |
| locomotion | cruise 0.3, slowest 0.2, yaw max 1.0, gain 1.5, kick 1.2 for 1 s, hold 0.8, pivot first 45°, done 15°, slow yaw 0.4, slow clearance 0.25, lookahead 0.30/0.15 (`follow.py:12-36`; the kick copied in `explore_run.py:29`); arc rules (`run.py:114-119`); pivot gates 0.17 / 0.30 / 0.26 / tight 0.15 (`run.py:112-123,136`); stuck 3 s / 0.05 m (`stuck.py:17-19`); walk-over 0.01 (`objects.py:15`) |
| sensors | the 8×8 depth sensor: 45°, 8×8, valid statuses, range 4 m, look 0.7 m, drop extra 0.06, floor and low margins, emergency 150 mm, reflex 0.30 m, side-drop thresholds (`cliff.py`, `run.py:81-83,157-158`, `side_drops.py:18-21`; the Eye's copy `eye.js:5-10`); the simulated camera (`sim.json`) |
| looking | head joints, the walking command, settle frames, tolerances, timings, confirm and look-along distances, the survey's four 90° steps (`run.py:98-99,141-154`, `explore_run.py:27-28,91-93`) |
| localisation | mapd, maps only at stops, 0.05 m grid; the fix gate 0.3 m / 0.35 rad and its hold rules (`run.py:91`, `frames.py:15-19,74`); the landmark relocaliser (`relocalise.py:21-31`) |
| error_budget | the edge and drop rings, stop distance 0.60, corridor 0.25, association distances (`run.py:86,124-149`, `grid.py:60-61`, `cliff.py:47`, `semantic_map.py:17-18`) |
| judge | fall 0.06, contact 0.083, drop margin 0.15, reach 0.25, bounds 0.05, the phase-1 bar (`evaluate.py`, `challenge/judge.py`) |

Shared policy stays out of the profile: the tick and replan periods, the grid's costs, the
explorer's gains, the refusal limit. Test-world facts (the apartment's stairs) are scene data.
A run records its profile and plugin versions in its header (`nav/runlog.py:53-54`,
`mcapio.py:40-54`).

### A2. The schema and its validator

- Lives where the navigator, Mission Control and the Observatory can all read it: proposed beside the
  run format (`libs/runfile` after phase 2), Mission Control's `robotfile.py` re-exporting it.
- Required: `profile_version`, `id`, `label`, `kind`, `factsheet`, `footprint`, `locomotion`,
  `plugins`, `control`. The rest optional.
- Rules: unknown fields are errors; `plugins` names every interface the blocks need; a variant is
  merged on the base and validated again; a value that differs between variants carries `measured`
  and `why`; cruise ≤ the factsheet's maximum speed, slowest ≤ cruise, radius ≤ lethal ≤ inflate,
  the `max_speed` guardrail ≤ the maximum (as today); errors name the path and what is wrong.

### A3. The four interfaces and what moves behind them

| Interface | Asked | Moves behind it (today's code) |
| --- | --- | --- |
| Locomotion | `command(speed, turn)`, `stop()`, `can_pivot(…)`, `pivot(…)`, `arc_clear(…)` | `run.py` `move`, `load_pivot_vx`, `_tight_allowed`, `_pivot_clear_of_drops`, `_arc_clear`; `follow.py`'s kick and creep (the path-to-motion part of `follow.step` stays shared) |
| RangeSensing | `on_frame(cb)`, `derive(frame) → perception`, `nearest_mm()` | `TofStream`, `FrameView`, `cliff.py` (its module-wide calibration becomes instance state), `step_check.py`, `side_drops.py` |
| Localisation | `pose()`, `fix()`, `grid()`, `needs_stationary()`, `frame_delta()`, `nudge()` | `frames.Localizer`, `fix`, `_watch_mapd`, `survey`, `grid`; mapd opened only by the mapd plugin |
| Looking | `capable`, `look_at(target, pose, hold)`, `settled()`, `restore()` | `glance_at`, `look_along`; a robot that cannot look leaves a spot unseen, not blocked |

Hazard memory (edges, drops, suspects, what the floor showed) stays in the shared navigator; a look
returns classified frames. Planned against `nav-frames`' `run.py`, whose line numbers differ.

### A4. Proving the duck behaves the same

0. First measure whether the simulator is deterministic tick for tick: challenge 5, three seeds,
   twice on one commit, the commands and decisions compared. If identical, that is the criterion;
   if not, pass counts per seed against the base commit.
1. A test loads the profile (variant `sim`) and compares every number with the old constant.
2. `make test-duck`, `duck-replay` on b9, b10b, b11 and the gate runs, the probe replays old against
   new, challenges 1–5 seeded.
3. Step 2 plus a replay of recorded inputs through the duck's locomotion plugin, its commands
   compared with the logged ones; challenges 2, 5, 11 and 16–19 on top.

## B. RFC-0019, steps 1–2

### B1. Robot-tagged anomalies: where each is raised

| Anomaly | Where | Rule |
| --- | --- | --- |
| `fix_jump_held` | `Navigator.fix` (the gate in `frames.py`) | a held fix; every one, not throttled as today's `fix` event is |
| `reloc_refused` | the relocaliser (`relocalise.py`) | ≥ 4 sightings in 6 s that spread more than 0.12 m |
| `stuck` | `_go_to` (an event exists) | a re-tag of the stuck rule |
| `frames_parted` | `nav-frames`' frame watch | the frames differ by over 0.25 m or 0.1 rad |
| `refusal_burst` | the explorer (`explore_run.py`) | N refusals at one pose with no motion between |
| `room_disagrees` | the turn rules in `_go_to` | no room to turn by the map while the sensor sees ≥ 280 mm clear (to be set) |
| `head_off_walk` | the state handler | a head joint away from the walking pose while walking (threshold read from the recordings) |
| `refused_unexplained` | the planner's refusals | refused with nothing lethal and no obstacle or drop within R |
| `camera_failed`, `thread_failed` | the camera watch (exists); the state and depth streams (silent today: they need a watchdog) | an observer stops or goes stale |
| `stop_latched`, `lease_lost` | the navigator server catching the gate's lease loss | `stopped_by …` vs expired, taken over, disconnected |

### B2. Found detectors: rules and how they behave on recorded runs

Counted on the clean runs (b9 r2, b10b r1 and r3, b11 r1) and the fixtures, from `ticks.jsonl`
and the simulator's truth:

| Detector | Rule (proposed) | Clean runs | Fixtures |
| --- | --- | --- | --- |
| near miss | truth clearance under 0.090 m without contact | quiet (0.093 fires twice on b9 r2) | b10b r2's graze found |
| dithering | walking with net displacement under 0.12 m in 3 s | quiet | every gate12 stall (but each is also a `stuck`: duplicate) |
| odometry scale | walking ratio outside 0.95–1.05 over a run or ≥ 3 legs | per leg not quiet (mapd's fixes inflate legs: needs a fix-aware filter) | **gate3 ch11** (all ten out, 0.87–0.92); gate4 ch11 is after the fix (0 of 10) |
| belief vs truth | p95 warn 0.20 m, major 0.35 m; heading 20° | not quiet at 0.20 (b9 r2 p95 0.28) | no fixture with a real jump |
| phantom obstacle | an occupied cluster ≥ 3 cells over 0.30 m from any real outline | **fires on every run**: a 2–4 cell cluster at world (−0.29, 0.09…0.17), about 0.5 m from the nearest outline, in every run checked; cause not investigated | — |
| missed obstacle | ≥ 3 outline samples in known cells, no occupied cell within 0.15 m | not quiet until thin legs are left out | b10b r2: 2 |
| misplaced edge | a glance's rim median over 0.25 m from the hole, with a refusal or trap within 5 s | the plain 0.20 m does not separate | b11 r2: 0.27 m median, 0.475 max |
| wrong refusal | a path existed by truth | fires on clean runs (b11 r1: 12 of 19) | room disagreement by truth found in b11 r2, r3, b10b r1 |
| area uncovered | "nothing left" with a room under 0.5 covered | fires on b11 r1 (kitchen 0.10, bedroom 0.38): a true positive | — |

Not yet quiet on clean runs: belief vs truth at 0.20, near miss at 0.093, wrong refusal, phantom,
missed obstacle: each needs a better rule or a fix before it joins the track.

### B3. The command line

`miniview anomalies <run> [--detector …] [--min-severity …] [--json]` (renamed with phase 2), beside
`miniview events`; detectors over the recording in the Observatory, the ones that need the duck's
truth layouts registered from the duck's side (to decide). A table: t, end, anomaly, source,
severity, margin, summary, believed → true place; a footer with counts and the detectors that did
not apply. Nothing written into the run; the derived index takes the results later, keyed by run,
detector and version.

## Decisions for the operator

**Decided 2026-11-19, all as recommended:** the validator with the run format (`libs/runfile`);
duck-only detectors read the truth layout as data (no robot code in the Observatory); near miss
0.090 m; the phantom cluster investigated first (read-only on recordings, no navigator fix without
the operator's word).

1. Where the profile validator lives (proposed: with the run format, `libs/runfile`).
2. How duck-only detectors register (an entry point from the duck's package, or the truth layout
   passed as data).
3. The near-miss threshold: 0.090 m (quiet on the clean runs) or 0.093.
4. The phantom cluster by the dock: investigate it first; it may also explain early "no room to
   turn" (it is near where every run starts).

## Results of stream A (RFC-0020, steps 1–3), branch `p3-profiles`

Written as the steps land; each lists what was proved and what was not.

### Step 1: the schema, the validator, the duck's profile

- `libs/runfile/src/runfile/profile.py`: the validator. Unknown fields are errors at every
  level; `plugins` names every interface the blocks need; a number that differs between
  variants needs `measured` and `why` in its block; cruise ≤ the factsheet's maximum speed,
  slowest ≤ cruise, the turn limits ≤ the maximum angular speed, radius ≤ lethal ≤ inflate,
  the `max_speed` guardrail ≤ the maximum; every error names its path. It holds Mission
  Control's factsheet and control parsers, which `robotfile.py` there now re-exports
  (`scripts/check_boundaries.py` lets `mission_control` import `runfile`).
- `robots/duck/profile.json`: one profile, variants `sim` and `real`. The simulator's measured
  numbers (odometry scale and by speed, pivot creep, the depth sensor's mount) keep `measured`
  and `why` verbatim from `calibration/sim.json`. The base holds the real duck's values (no
  creep, mapd's 3° axial mount, no odometry scale); `real` is empty, `sim` lays the measured
  numbers on it.
- `robots/duck/tests/test_profile.py`: every number of the profile (140 then, 142 after step 3)
  compared with the constant it replaces, exactly, both directions (a number with no expected
  value fails, an expected value missing from the profile fails). Derived values (`LETHAL_M + 0.05`,
  `0.083 + 0.04`, the radians) are checked to the last bit; `measured` and `why` against
  `sim.json`; one case per rule.

### Step 2: the numbers out of the navigator

- `duck_lab/profile.py` loads `robots/duck/profile.json` for an environment (`sim`, or `real`
  for a navigator built with no calibration). `Navigator.configure(profile)` reads the numbers
  and keeps them as attributes: the rings, the pivot, arc and tight-pivot gates, the reflex and
  the cliff stop, the fix gate's thresholds, the look's timings, the odometry scale, the pivot
  creep, the depth sensor's mount. Derived values are computed the way the constants were
  (`lethal + 0.05` is not `0.17` in floats), so they are the same to the last bit.
- Pure functions take what they need: `follow.step(…, loco)`, `StuckWatch(window_s,
  moved_max_m)`, `Localizer(fix)`, `CostGrid.from_map_grid(…, lethal_m=, inflate_m=)` (a grid
  carries the rings it was built with), `FrameView(…, reflex_half_w_m)`.
- The world model library takes `Limits` (walk-over and overhead heights, where to stand, the
  association gates) and the relocaliser its `localisation.landmarks`; the navigator passes the
  profile's. The library keeps the duck's as the default (`DUCK_LIMITS`, `DUCK_LANDMARKS`),
  tested equal to the profile: K32.
- The harness (`evaluate.py`, `challenge/judge.py`, `challenge/floor.py`) reads the judge's
  and the footprint's numbers from the profile in variant `sim`. The simulated camera's
  fidelity comes from the profile too.
- `duck-replay` reads the profile the run's `calibration` event names (the event now carries
  `profile: {id, variant}`); a run from before it was recorded with numbers that are the
  `real` variant's.
- `test_profile.py` now holds each constant's value as it was, where it was, and compares the
  profile with those; the sensor's own geometry (`cliff.py`, `side_drops.py`) is still code
  until step 3, and is compared with its module.

### Step 3: the four interfaces and the duck's plugins

`robots/duck/src/duck_lab/plugins/`: `interfaces.py` (the four, runtime-checkable Protocols),
`__init__.py` (`load(profile)`: the names the profile gives, a name or version it does not
have is an error naming it), and the duck's four, each built from the profile with its numbers
as instance state and no socket opened at construction.

| Interface | The duck's | What moved behind it (the code is the same, moved) |
| --- | --- | --- |
| Locomotion | `duck-walk@1` | `command`/`stop` (`robot.move`), `drive` (the kick, the slowest walk, the creep: `follow.step`'s second half), `can_pivot`, `tight_pivot_ok` (one per spot, its own state), `arc_clear` |
| RangeSensing | `tof8x8@1` | the stream (`TofStream`), `FrameView`/`derive`, all of `cliff.py` as methods (the mount is instance state: two sensors in one process), `below_counts`, `step_check.py`'s strip and `unseen_ahead` |
| Localisation | `mapd@1` | mapd's RPC, the odometry scale, `Localizer` (the belief), `fix`, mapd's account of itself, `grid`, `settle` (stand until mapd maps this stop), `needs_stationary` |
| Looking | `duck-head@1` | `glance_at`'s aiming and frame collection, the head's walking command, `restore`; `capable` |

What stays in the navigator, as RFC-0020 §A3 says: the hazard memory (drops, edges, suspected
cells, the floor seen), the frames logic that moves the memory with the belief, the planner and
the safety rules. `follow.step` keeps the path geometry (lookahead, heading error) and calls
the plugin's `drive`. A robot that cannot look (`capable = False`) leaves the spot unseen, not
blocked (tested with a stub). A run's `calibration` event records `profile: {id, variant,
plugins}`.

Also: `nav/cliff.py` and `nav/step_check.py` are gone (their code is `plugins/tof8x8.py`);
`nav/decision.py` holds `decision` (plugins record decisions too); `SuspectMemory` takes its
frames, ratio and clear distance from the profile; the probes read the sensor through
`sim/probes/cliff_shim.py`.

### Proof that the duck behaves the same (A4), 2026-11-19

Three trees: the base `c61ca7f`, step 2 `b90731d`, step 3 `0e32d31`. Simulator jobs ran one at a
time under the shared lock, into a scratch data folder, three seeds per challenge, two repeats.

**0. Is the simulator deterministic? No** (K13). Challenge 5, seeds 1–3, three complete repeats
on the base: in all 9 pairs the commands first differ at command 84–156 of 200–330, and the
truth pose already differs by 0.9 mm at the first command (27 mm by command 120), so no
tick-for-tick comparison of simulator runs is possible. The criterion used instead: exact
equality where the inputs are recorded (replays, the locomotion replay), pass counts per seed
over repeats where they are not (challenges).

**1. Every number against its constant:** `test_profile.py`, 142 numbers, exact, both ways.

**2. Step 2.** `make test-duck` PASS (and `make lint`, `make test-control`).
`duck-replay` over 122 recorded runs (b9 r1–r3, b10b r1–r3, b11 r1–r5, b12 r1–r3, the other
apartment runs, and the latest run of each seed of challenges 5, 11, 16, 17, 18, 19): the output of
each run on the base and on step 2 is identical, file for file (115 PASS; the 7 that FAIL fail
the same on both, K33). Challenges, pass counts by seed (P pass, F fail, one letter per repeat):

| Challenge | Base `c61ca7f` | Step 2 `b90731d` | Step 3 `0e32d31` |
| --- | --- | --- | --- |
| 1 | 6/6 | 6/6 | 6/6 |
| 2 | 6/6 | 6/6 | 6/6 |
| 3 | 6/6 | 6/6 | 6/6 |
| 4 | 6/6 | 6/6 | 6/6 |
| 5 | 7/9: s1 PPP, s2 FPF, s3 PPP | 5/6: s1 PP, s2 PF, s3 PP | 6/6 |
| 11 | 6/6 | not run | 6/6 |
| 16 | 2/6: s1 FP, s2 FF, s3 PF | not run | 1/6: s1 FF, s2 FF, s3 PF |
| 17 | 0/6 | not run | 0/6 |
| 18 | 1/6: s1 FF, s2 FF, s3 PF | not run | 0/6 |
| 19 | 0/6 | not run | 0/6 |

Every failure of 16–19 on both trees is "stuck: walking without moving" (K1), except one base
run of challenge 18 ("no room to turn"); the failures of challenge 5 are "no room to turn" on
both. The base flips by itself (challenge 5 seed 2; 16 seeds 1 and 3; 18 seed 3), and six runs
per challenge cannot rule out a drop of 30 points: what they show is no change beyond that
variation, and no new failure kind.

**3. Step 3.** `make lint`, `make test-duck`, `make test-control`, `make test-observatory`
PASS. `duck-replay`: the same 122 runs, identical to the base file for file. The locomotion
replay (`sim/probes/loco_replay.py`: the base's `follow.step` beside `follow.step` and
`DuckWalk.drive`, fed 21 recorded runs' poses and plans, every combination of the three flags
the log does not keep): 4611 ticks, 36 888 evaluations, the same motion and the same follower
state on every one. The logged commands: 2906 of the 3148 non-zero logged commands (92 %) are
reproduced, within 0.15 rad/s, by some combination of the flags; the other 8 % and the zero
commands (stands, surveys) are not outputs of `step`, or depend on inputs the log does not keep
(the pose is logged after the command). Probe replays, base against step 3, identical output:
`stuck_replay` (challenges 16, 5), `hold_off_replay` (12 refusals of challenges 8–11),
`glance_replay`, `glance_from_run`, `false_drops`, `trigger_replay` (challenges 10, 11).
Challenges: the table above.

## NOT VERIFIED

Written for step 3's proof: the numbers above are from the runs named, no others. Challenges 20
and up, and the apartment batches, were not run. The EV3, the NXT and the real duck were not
touched. `margin_replay` and `step_check_replay` need `ticks.jsonl` files the data folder does
not hold, so they ran on neither tree. The simulator's first divergence between repeats is
measured, its cause is not. By its COPY lines (the image was not built or run here), Mission
Control's image (`apps/mission-control/Dockerfile`) has `robots/duck/src` and not the profile, as it
did not have `calibration/`: the duck adapter's `load_scale` has nothing to read in that image,
before and after.

Below: the preparation's own note, from before any of this was run.

## NOT VERIFIED (preparation)

Nothing was run, parsed or type-checked; line numbers come from delegated scans and were not
spot-checked; tick-for-tick determinism of the simulator is not measured; the detector counts cover
only the runs named and were computed by scratch scripts not re-run here; the URDF was not read (the
width and the sensor's mount come from code comments).
