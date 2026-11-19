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
| phantom obstacle | an occupied cluster ≥ 3 cells over 0.30 m from any real outline | **fires on every run**: a 2–4 cell cluster at world (−0.29, 0.09…0.17), about 0.5 m from the nearest outline, in every run checked; cause: a real 7 cm cube the layout lacks ([PHANTOM](PHANTOM.md)) | — |
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

### Stream B results: steps 1–2, the Observatory's side (2026-11-19)

**Built:** `observatory anomalies <run> [--detector a,b] [--min-severity info|minor|major|critical]
[--experimental] [--layout FILE …] [--json]` (the `miniview` script is the same entry point),
reading the run straight from the data folder (no index, nothing written, the run's MCAP read with
`keep_raw` so events come whole), in `apps/observatory/src/observatory/anomalies.py`: no robot code
is imported; the simulator's truth is data, the layout file and
`robots/duck/sim/apartment_free_bodies.json` together (the free bodies the layout dump omits:
[PHANTOM](PHANTOM.md)); a detector that needs the layout or the truth pose says it did not apply,
not "0". The table is: t, end, anomaly, source, severity, margin, summary, belief → truth place; the
footer counts, names what did not apply and what was not run. The record is RFC-0019 §2.1's, source
`analysis`, with `detector` and `version`. Tests: `apps/observatory/tests/test_anomalies.py` (each
rule at its threshold; seven fixtures cut from real recordings by `tests/make_anomaly_fixtures.py`,
about 260 kB; the command line; nothing written).

**The default track** (quiet on b9 r2, b10b r1, b10b r3, b11 r1, all five at 0): near miss (truth
clearance of the trunk centre to the layout's solid geoms under 0.090 m; the radius 0.083 m is the
contact line, an episode that crosses it is critical and links `contact@t`), dithering, odometry
scale, phantom obstacle (with the free bodies in the truth), misplaced edge. **Behind
`--experimental`**, each said not quiet in the footer: belief vs truth, missed obstacle, wrong
refusal, area uncovered.

**Counts per run** (every detector, the layout and the free bodies as truth; `n/a` = did not apply:
a challenge scene has no layout here; refused legs for scale):

| Run | near miss | dithering | odometry scale | phantom | misplaced edge | belief vs truth | missed obstacle | wrong refusal | area uncovered | refused legs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b9 r2 (clean) | 0 | 0 | 0 | 0 | 0 | 1 (p95 0.28 m) | 34 | 0 | 0 | 2 |
| b10b r1 (clean) | 0 | 0 | 0 | 0 | 0 | 0 | 17 | 9 | 0 | 12 |
| b10b r3 (clean) | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 6 | 0 | 7 |
| b11 r1 (clean) | 0 | 0 | 0 | 0 | 0 | 0 | 21 | 16 | 2 (kitchen 0.10, bedroom 0.38) | 19 |
| b10b r2 (the graze) | **1** (kit_stool2, 0.0709 m, then a contact at 187.7 s) | 0 | 0 | 0 | 0 | 1 (p95 0.25 m) | 21 | 10 | 0 | 10 |
| b11 r2 (the edge) | 0 | 0 | 0 | 0 | **1** (rim median 0.27 m, max 0.475 m, refused 32.3 s) | 0 | 2 | 9 | 0 | 10 |
| gate3 ch11 s1–s10 | n/a | 0 each | **10 of 10** (0.890, 0.872, 0.885, 0.894, 0.924, 0.888, 0.902, 0.898, 0.872, 0.904) | n/a | n/a | 7 of 10 | n/a | n/a | n/a | — |
| gate4 ch11 s1–s10 | n/a | 0 each | **0 of 10** | n/a | n/a | 0 of 10 | n/a | n/a | n/a | — |

The B2 figures that carry over: near miss 0.093 m fires twice on b9 r2 (0.0930 and 0.0907 m at 648.2
and 652.3 s; the 0.090 m line is quiet); gate3 ch11's ten ratios are 0.87–0.92; gate4's are in the
band; b9 r2's belief error p95 is 0.28 m; b11 r2's rim median is 0.27 m and its maximum 0.475 m; b11
r1's kitchen and bedroom are 0.099 and 0.384. Dithering finds the gate12 stalls: all 26 failed runs
of ch17–ch19 have one episode each, from 20.6 to 27.6 s, net 0.057–0.088 m in 3 s (the 4 that passed
have none); ch20's 10 runs, which fail otherwise, have none.

**Rules as built, against B2's:**

- *Odometry scale:* the run's walking belief/truth ratio, a belief step over 0.15 m in one tick (a
  fix) left out with its truth step, under 2 m of walking says nothing. B2's "or on 3 legs" is off
  by default (`odom_legs_out`): with it, b10b r1, a clean run, fires (3 of 35 legs outside
  0.95–1.05, at 1.057 and 1.074 among them, the run at 1.004), the per-leg noise B2 named; a
  fix-aware leg filter was not built.
- *Phantom:* as B2 (3 cells, 0.30 m), over every map snapshot, one record per place. It fired on
  every run because the truth lacked the cube; with the free bodies it is quiet on the four clean
  runs. Over all 65 apartment runs it fires in five (b10a r1 15 places, frames-before-r2 4, b3 r3 3,
  b4 r3 1, relo-plain-on 1): b10a r1 has K4's mapd jump, relo-plain-on K4's second, frames-before-r2
  is from before the frame fix; b3 r3 and b4 r3 were not examined.
- *Misplaced edge:* B2's rim median over 0.25 m from the stairwell, with a refusal or trap within 5
  s; the plain 0.20 m is not used. Over all 65 runs: b11 r2 (1) and relo-plain-on (5).
- *Missed obstacle:* B2's rule unchanged (3 samples, 0.15 m), not quiet: it fires on walls, table
  and stool legs. The thin-legs variant of B2 was not built.
- *Wrong refusal:* a refused leg whose goal and truth pose lie in one component of the floor a 0.083
  m disc can occupy (inside a floor, clear of every obstacle and the stairwell by the radius), 0.025
  m raster. b11 r1: 16 of 19 refused legs (B2: 12 of 19); the planner's margins (0.28 m inflation,
  0.26 m from an edge) are wider than the radius, so it fires on routine refusals.
- *Area uncovered:* "nothing left to explore" with a layout room's floor, on a 0.1 m lattice, under
  50 % in cells the last map knows; the rooms are the layout's `floor_*` decals.
- *Belief vs truth:* p95 over the run of the belief's distance from the truth in the world (warn
  0.20 m, major 0.35 m), and of the heading error (20°), as two anomalies.

**Over all 65 apartment runs, the default track fires in 30** (near miss 33 episodes in 23 runs,
odometry scale in 9 early-batch runs b3–b5 and explore-1117b, dithering in 4, phantom in 5,
misplaced edge in 2): those are runs with contacts, the pre-fix odometry, displaced maps and stalls,
not the clean four; no run was read one by one.

**Not built:** the robot-tagged anomalies (B1: `fix_jump_held`, `reloc_refused`, `stuck`,
`frames_parted`, `refusal_burst`, `room_disagrees`, `head_off_walk`, `refused_unexplained`,
`camera_failed`, `thread_failed`, `stop_latched`, `lease_lost`): their raise points are inside the
navigator and wait for the profiles branch to merge; the derived index; the pages; Mission Control;
the video.

**Not verified:** the detectors ran on the recordings by their MCAP, not on a live run; the fixtures
are slices trimmed to the fields the rules read (tick rows keep pose, truth, speed, tilt, time; the
events the rules read); `wrong_refusal`'s "a path existed" ignores the planner's margins on purpose
and was not compared with a planner replay; `belief vs truth` for runs with several epochs (phase
1's evaluations) was computed with each tick's epoch and not checked against `observatory state`;
the challenge scenes (ch11) have no layout here, so nothing that needs one was run on them; the free
bodies' poses are their reset positions.

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

## NOT VERIFIED

Nothing was run, parsed or type-checked; line numbers come from delegated scans and were not
spot-checked; tick-for-tick determinism of the simulator is not measured; the detector counts cover
only the runs named and were computed by scratch scripts not re-run here; the URDF was not read (the
width and the sensor's mount come from code comments).
