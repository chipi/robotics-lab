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
is imported; the simulator's truth is data, `robots/duck/sim/apartment_layout.json` (regenerated
with the free bodies, which the dump had omitted: [PHANTOM](PHANTOM.md)); a detector that needs the
layout or the truth pose says it did not apply, not "0". The table is: t, end, anomaly, source,
severity, margin, summary, belief → truth place; the footer counts, names what did not apply and
what was not run. The record is RFC-0019 §2.1's, source `analysis`, with `detector` and `version`.
Tests: `apps/observatory/tests/test_anomalies.py` (each rule at its threshold; seven fixtures cut
from real recordings by `tests/make_anomaly_fixtures.py`, about 260 kB; the command line; nothing
written).

**The default track** (quiet on b9 r2, b10b r1, b10b r3, b11 r1, all five at 0): near miss (truth
clearance of the trunk centre to the layout's solid geoms under 0.090 m; the radius 0.083 m is the
contact line, an episode that crosses it is critical and links `contact@t`), dithering, odometry
scale, phantom obstacle (with the free bodies in the truth), misplaced edge. **Behind
`--experimental`**, each said not quiet in the footer: belief vs truth, missed obstacle, wrong
refusal, area uncovered. *Changed 2026-11-19 (K12, KNOWN-ISSUES): belief vs truth is on the default
track as version 2 (a jump of the belief's offset from the truth, 0.30 m within 10 s, and the p95
rule at 0.35 m; quiet on the same four runs, finds b10a r1's 0.94 m jump); missed obstacle is
version 2 and still experimental (0, 17, 18, 12 on the clean runs).*

**Counts per run** (every detector, the layout with the free bodies as truth; `n/a` = did not apply:
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

**The regenerated layout and phase 1's goals** (`draw_goals(layout, 20, seed 1)`, what run 16's
`duck-eval --goals 20` draws; the evaluation was not re-run). The dump gained 7 geoms and changed
none. The goals change: old goals 5 (−0.13, 0.42, cor_n) and 17 (−0.17, −0.07, cor_n) are no longer
drawn, because the cube `obj_3` at (−0.30, 0.10) is 0.315 m and 0.165 m from them, under the 0.35 m
goal clearance. The draws are sequential from one seeded generator, so the other 18 keep their order
and values but shift up (by one before old goal 17, by two after it), and two new goals are appended
at the end: (1.69, −0.57, office) and (−0.31, 2.11, cor_n). Phase 1's results are for the old 20; a
comparison with them needs the old layout (`git show
c61ca7f:robots/duck/sim/apartment_layout.json`).

**Over all 65 apartment runs, the default track fires in 30** (near miss 33 episodes in 23 runs,
odometry scale in 9 early-batch runs b3–b5 and explore-1117b, dithering in 4, phantom in 5,
misplaced edge in 2): those are runs with contacts, the pre-fix odometry, displaced maps and stalls,
not the clean four; no run was read one by one.

**Not built (at stream B's end):** the robot-tagged anomalies (B1: `fix_jump_held`, `reloc_refused`,
`stuck`, `frames_parted`, `refusal_burst`, `room_disagrees`, `head_off_walk`, `refused_unexplained`,
`camera_failed`, `thread_failed`, `stop_latched`, `lease_lost`): their raise points are inside the
navigator and waited for the profiles branch to merge (built since: "Results of B1" below); the
derived index; the pages; Mission Control; the video.

**Not verified:** the detectors ran on the recordings by their MCAP, not on a live run; the fixtures
are slices trimmed to the fields the rules read (tick rows keep pose, truth, speed, tilt, time; the
events the rules read); `wrong_refusal`'s "a path existed" ignores the planner's margins on purpose
and was not compared with a planner replay; `belief vs truth` for runs with several epochs (phase
1's evaluations) was computed with each tick's epoch and not checked against `observatory state`;
the challenge scenes (ch11) have no layout here, so nothing that needs one was run on them; the free
bodies' poses are their reset positions.

## Results of B1: the robot-tagged anomalies in the navigator (RFC-0019 step 1), branch `p3-hooks`, 2026-11-19

**Built.** `Navigator.anomaly(kind, summary, severity, ...)`
(`robots/duck/src/duck_lab/nav/anomaly.py` builds the record) writes RFC-0019 §2.1's record as an
event row of the run: `event: "anomaly"`, `source: "robot"`, `module`, `detector`, `version` 1,
`severity`, `summary`, `values`, `margin`, `evidence`, `related`, `duration_s`, and `where: {belief,
frame: "map"}` (mapd's own place too for a held fix); the simulator's truth pose is in the row,
added by `record` as to every row. It has no `decision`, so Mission Control's listeners and
guardrails do not see it and nothing it does changes a decision or a command (a unit test: two rows
with an anomaly between them are the rows without it). A failure to write one goes to stderr and
never stops the navigation. In the Observatory, the adapter lists it as a notable event with a line
of text (`anomaly stuck (major): ...`: `observatory events --kinds anomaly`), and `observatory
anomalies` reads the events back into the found records' shape (`t_end` is `t` plus the duration,
the belief placed in the world by the epoch in force, the truth from the row) beside the found ones,
the `source` column `robot`, a footer line counting them by kind; `--detector` takes a robot kind
(`stuck`) as well as a found detector, naming only found ones hides the robot's. The thresholds that
are the duck's are the profile's new `anomalies` block (`runfile.profile` validates it;
`test_profile.py` holds each number), with the measurement in its own `measured` and `why`; the
policy numbers are in `nav/anomaly.py`.

**The raise points**, with the numbers and where they came from. "The recordings" are the 66
apartment runs in `/work/robotics-lab/data` (read only; scratch scripts, not committed).

| Anomaly | Raised in | Rule as built | Number and its source | Severity |
| --- | --- | --- | --- | --- |
| `fix_jump_held` | `Navigator._watch_fix`, after every fix | the gate held the fix: every one, none throttled (the `fix` event keeps the first 3, then every 20th) | the gate's `localisation.fix` `jump_m` 0.3, `jump_rad` 0.35 (RFC-0016, existing); margin past the limit in m, or in rad when the turn held it | major |
| `reloc_refused` | the camera thread, where the relocaliser says `refused` | at least 4 sightings in 6 s that spread over 0.12 m | the relocaliser's own `localisation.landmarks` `min_n`, `window_s`, `spread_m` (existing); it clears its window on a refusal, so it repeats only after 4 new sightings | minor |
| `stuck` | `_go_to`'s stuck branch | the existing rule: 3 s of walking, the belief under 0.05 m | `locomotion.stuck` (existing) | major |
| `frames_parted` | `_watch_frames`, at the existing event's moments | the frames past 0.25 m or 0.1 rad, and again 0.25 m further | `localisation.fix` `parted_m`, `parted_rad` (existing) | major when the last fix was held, else minor (the landmarks' offset) |
| `refusal_burst` | `Explorer.watch_burst`, after each leg | 3 refused legs within 0.10 m of the first, no leg of another outcome between; once a streak | `BURST_N` 3, `BURST_MOVED_M` 0.10. The recordings' refused legs grouped by pose: groups of 1: 81, 2: 18, 3: 16, 4: 3, 5: 3, 6 or more: 35 (the explorer's "trapped" is 6); 57 streaks of 3 or more in 66 runs | major |
| `room_disagrees` | `_check_room`, at the refusal "no room to turn" | the sensor reads `room_disagrees_clear_mm` or more clear ahead | **280 mm** (the table's number, kept): of the 240 such refusals, 123 read 280 mm or more (109 at 300, 97 at 350, 63 at 400). By truth (the layout's nearest obstacle to the true pose) the map was more than 5 cm tighter than the real clearance in 25 of those 123 and in 19 of the 117 below 280 mm, at every limit from 200 to 400 mm the same share: the reading does not separate a wrong map from a right one (K36; replaced 2026-11-20 by the rule that looks at the map's nearest obstacle, `anomaly.room_verdict`: 22 flagged, the map wrong in 8, and `room_disagrees_clear_mm` is gone from the profile). One for a place (`PLACE_MOVED_M` 0.10, `PLACE_GAP_S` 5: b11 r5 refused six times in 1 s at one pose) | info |
| `head_off_walk` | `_check_head`, on every state | a head joint more than `head_off_walk_rad` from `head_walk_pose` for `head_off_walk_s` of walking (a forward command); standing clears the timer, the episode ends when the head is back | **0.30 rad, 1.0 s**, the pose `{neck_pitch 0.239, head_pitch 0.358, head_yaw -0.078, head_roll -0.023}`: each joint's median over the 63 runs' medians, from 160107 walking samples (the docs' "neck 13 deg, pitch 20 deg" are 0.227 and 0.349). A sample is within 0.10 rad of it in 81 %, 0.10-0.20 in 5 %, over 0.30 rad in 12 %. Episodes of 1 s or more: 0.20 rad 269 in 30 runs (8 and 9 in b10b r1 and r2), 0.30 rad 209 in 20 runs (1 each in b9 r2, b10b r1, b11 r1, 2 in b10b r2; the long ones, to 38 s, in b2-b5) | minor |
| `refused_unexplained` | `_check_unexplained`, at "no path on the map" / "start boxed in" | start not lethal, goal not lethal, and nothing in the planner's own cost map (walls, remembered obstacles, drops, edges, suspected drops) within `unexplained_clear_m` of the pose; one for a place | **0.30 m**: of 181 such refusals, 121 had a lethal goal and 28 a lethal start (both explain them), 32 neither; of those 32, 22 had something within 0.2 m, and nothing within 0.30 m in 8 (2 runs: b10b r1 at 1113 s and 1149-1156 s, b12 r2 at 407 s), within 0.40 m in 6, 0.50 m in 4, 0.60 m in 0. The table's rule had no "goal not lethal"; 121 of 181 refusals are a goal in a wall's ring | minor |
| `camera_failed` | the camera thread, where the event was | a look raised; said once for each different error | none | major |
| `thread_failed` | `_watchdog`, a thread every 0.5 s | the state or the depth stream silent for `state_stale_s` / `depth_stale_s`, once until it speaks again; says whether its thread is alive | **3.0 s** each: the longest gap between state samples is 1.40 s and between depth frames 1.41 s over the 66 recordings (apartment-1117 and, for 1.16 s, relo-fault-nogate-r1), and 25 s in `apartment-1117c`, a stalled recording; 120 state and 103 depth gaps over 0.2 and 0.3 s, all but the 25 s ones under 1.41 s | major |
| `stop_latched`, `lease_lost` | `Navigator.move` (the command the gate refuses), and `GoalRun._work` | `stopped_by <who>` is `stop_latched`; an expired lease, a takeover, another holder or any other end is `lease_lost`; said once for a navigator | none | info, major |

Not tagged: `mapd_lost` (RFC-0019 §3.1's second row; the `mapd_status` event already says it).

**Proof the navigator behaves the same.** The change adds rows and reads state: the diff to the
navigator's modules is `nav/anomaly.py` (new), `run.py` (+154 lines: the emit path, the raise
points, the watchdog), `explore_run.py`, `server.py` (2 lines) and `plugins/tof8x8.py` (the stream
thread kept as an attribute); `follow.py`, `duck_walk.py`, `grid.py`, `stuck.py`, `frames.py` and
the planner are untouched.

- `duck-replay` over 126 recorded runs (all 66 apartment recordings and the latest run of each seed
  of challenges 5, 11, 16, 17, 18, 19), before the change (be77f60) and after: the output of 125 is
  identical file for file. `apartment/phase1-run19` differed because another agent's evaluation was
  still writing it during the first pass (8370 records then, 33449 after); run again on the finished
  recording with be77f60's source (`PYTHONPATH` to a `git archive` of it) and with the new tree, the
  output is identical. 118 PASS and 8 FAIL on both: K33's seven and `apartment/explore-1117` (1178
  differences, the same kind: recorded before the derived points' present form). **What this proves
  and what it does not:** `duck-replay` replays the perception (the depth frames derived again from
  the recorded raw distances and states) and compares it with what was logged; it does not run the
  planner, the follower or the gates, so it does not by itself say the commands and decisions are
  the same. They are the same by the diff above (those modules are untouched; the anomaly code only
  reads state and writes a row) and by the test that two rows with an anomaly between them are the
  rows without it.
- `sim/probes/stuck_replay.py` over 169 recorded runs of challenges 16 and 5 (the stuck rule on the
  recorded belief and commands): 20 verdicts, 0 false alarms, the output identical between be77f60's
  source and the new tree.
- The unit tests drive the real `Navigator._go_to`, `fix`, `move`, `enable_objects` and
  `GoalRun._work` with the duck's real plugins and stub sockets:
  `robots/duck/tests/test_anomaly.py`, 62 checks, each raise point once for what raises it and for
  what must not (the gate taking a fix, 279 mm against 280, a wall 0.05 m from the pose, a
  stand-still head, a stream that keeps talking, a refusal repeated at one pose, a distinct pose).
  Mutation-checked: 16 deliberate breaks (a raise point not called or saying nothing, the 280 mm
  limit made exclusive, a lethal goal not counted as an explanation, the head watch counting
  standing, the lease said at every refusal, the server not telling the navigator, the watchdog
  thread not started) each fail the file; the explorer's loop calling the burst watch and the
  constructor starting the watchdog are checked by reading the source, as they need the simulator or
  sockets. `apps/observatory/tests/test_anomalies.py` reads the robot's tags from a made-up run (the
  epoch, the truth, the duration, the filters) and from
  `tests/fixtures/anomalies/robot_tagged_fault` (a real simulator run, below): the table, the
  footer, `--json`, `--detector`, `events`.

**The simulator, under the lock** (scratch data folder; the simulator was up and was not left as
found: `duck-challenge` stops it at its end, and the last run's `sim/reset_sim.py` started the
apartment scene, which is up):

- challenge 5 seed 1: passed (reached, error 0.181 m, 0.7 min), **no anomaly** in the run;
- challenge 11 seed 1: passed (reached, error 0.144 m, 0.8 min), **no anomaly**;
- so that the check sees a record in a real run, a third, not asked for: `duck-explore --minutes 2
  --fix-fault 30,0.9,0.0` (mapd's pose shifted 0.9 m from 30 s on, a persistent jump like b10a r1):
  **53 anomalies**, 52 `fix_jump_held` (every held fix, major, margin 0.59-0.61 m; the `fix` event
  was written 5 times in the run) and 1 `frames_parted` (major, at 32.0 s), each with the belief's
  place and the truth's, 0.9-4.4 cm apart, median 2.2 cm (the belief held while mapd was 0.9 m off).
  `observatory anomalies` lists them with source `robot` beside 3 found `phantom_obstacle`s;
  `observatory events --kinds anomaly` lists the same 53. No `thread_failed`, `camera_failed`,
  `head_off_walk` or other false alarm in the three runs. A slice of it is the fixture.

**Not verified** (the same list is in KNOWN-ISSUES K36, K37): `refusal_burst`, `room_disagrees`,
`refused_unexplained`, `head_off_walk`, `reloc_refused`, `stuck`, `camera_failed`, `thread_failed`,
`stop_latched` and `lease_lost` were raised by unit tests only, not by a live run: the three
simulator runs raised only `fix_jump_held` and `frames_parted`. Whether each stays quiet on the
navigator as it is now was not measured (the 66 recordings include the early batches), and the real
duck was not touched, so its walking head pose, its stream gaps and its two distances are the
simulator's. The simulator is not deterministic (K13), so the passes of challenges 5 and 11 are not
a proof of equal commands.

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
