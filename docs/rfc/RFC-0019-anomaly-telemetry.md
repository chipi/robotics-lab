# RFC-0019 — Anomalies: what went wrong, told by the software, on the timeline and the map

**Status:** Accepted with changes, revision 2 (2026-11-19): the advisor's review (Fable 5.1) folded
in, the operator: "Yes"; its questions answered (§6). The operator's direction, 2026-11-19:
"track during the run all the things that are going wrong … a telemetry of the software modules
that we are building, so that after a run finishes, we can … see how software works, not only what
sensors are telling us … plot on a timeline events that were coming from the software that were
not expected … plot those events on the map, and we can see where the physical world went off from
the world [the robot believes]", and: "are there different kinds of anomalies we should be able to
detect in the Observatory, even over the sensors and not only the software?"
**Builds on:** [RFC-0010](RFC-0010-run-store-v2.md) (the run store), [RFC-0013](RFC-0013-robot-eye.md)
(the Eye, the watch page), [RFC-0014](RFC-0014-mission-control.md) (Mission Control's live side),
[RFC-0016](RFC-0016-objects-and-semantic-map.md) (relocalisation and the fix gate),
[ADR-0014](../adr/ADR-0014-replay-logging.md) (decisions in the run log).

## 1. Why

A run records what the sensors said and what each rule decided. It does not say which of those
moments were wrong. Reading a run today means knowing which events matter: a routine glance and
mapd losing itself look alike in the event list. Three runs this week needed an hour of scripts
each to tell their story:

- b10a r1: mapd moved the belief 0.9 m while the duck pivoted; 22 s later the duck touched the
  office's capsule. The jump was in no event at all; it was found by comparing belief with truth.
- b10b r2: a graze on a stool, scored as five contacts; found by a script over the truth rows.
- Challenges 16–19: the duck stalled at bars it can cross; the cause (turning while the feet meet
  the edge) took nine probe variants and a command log to find.

Each would have read in a minute as a strip of marks on a timeline and pins on a map.

## 2. What an anomaly is

Something that should not have happened, or that the robot or the analysis cannot explain: not a
rule doing its job. A reflex stop in front of a wall is the reflex working; a reflex stop in the
open, with nothing within a metre by truth, is an anomaly.

### 2.1 Two sources, one record

- **Tagged by the robot**, live: a module notices it while running (mapd lost, a fix held as a
  jump, a camera failing, a walk stuck, a thread error).
- **Found by the analysis**, after the run, in the Observatory: a detector reads the whole record,
  often with what the robot did not have (the simulator's truth, the rest of the run, earlier
  runs).

Both write the same record, so the timeline, the map, the video and Mission Control treat them
alike:

```json
{"anomaly": "fix_jump_held", "source": "robot", "module": "localizer", "severity": "major",
 "detector": "fix_gate", "version": 1, "t": 822.5, "t_end": 844.0,
 "where": {"belief": [1.94, -1.01], "mapd": [1.94, -1.01], "truth": [1.69, -0.35], "frame": "map"},
 "summary": "mapd moved the belief 0.90 m in one fix while pivoting; held",
 "values": {"jump_m": 0.90, "mapd_lost": "bumped", "relocalizations": 3}, "margin": 0.60,
 "evidence": {"t": [822.4, 822.6], "events": ["fix@822.6", "mapd_status@822.5"]},
 "related": ["contact@844.0"]}
```

- `where` carries both places when both are known: where the robot believed it was, and where it
  was. On the real robot `truth` is absent.
- `severity`: `info` (worth seeing), `minor` (cost time), `major` (put the run at risk), `critical`
  (contact, fall, a drop margin broken).
- `related` links causes and effects (the jump and the contact it led to); `evidence` is what the
  detector read (a tick range, event ids), kept apart from cause and effect.
- `detector` and `version`: which detector found it and which version, so its results are rebuilt
  when the detector changes. `margin`: how far past its threshold it was (a near miss by 1 mm and
  by 5 cm are different findings).
- `where` names its frames: the belief, mapd's own (`mapd`, when it differs) and the truth.
- A third source, `harness`: the simulator's live truth guard (the exploring runner stops a run on a
  contact by truth), neither the robot nor the analysis.
- Contact and fall are judge outcomes, not anomalies; an anomaly links to them through `related`.
- A robot-tagged anomaly is an event in the run log (ADR-0014's shape, `event: "anomaly"`): the
  run log here is the format-2 run (the MCAP the Observatory reads; `ticks.jsonl` is the navigator's
  own copy and carries the same events). A found one goes into the Observatory's derived index
  (ADR-0004, ADR-0009), rebuilt from the run, never into the recording.

## 3. The first set

### 3.1 Tagged by the robot

| Anomaly | Module | When |
| --- | --- | --- |
| `fix_jump_held` | localizer | a mapd fix over 0.3 m / 0.35 rad held by the gate |
| `mapd_lost` | mapd (read by the navigator) | `map.status` says `lost` (`bumped`, `carried`, `sat`, `fell`, `contradiction`), or its loop / relocalisation counters step |
| `reloc_refused` | relocaliser | landmark sightings disagree with each other |
| `stuck` | navigator | walking, the belief going nowhere (`stuck.py`) |
| `frames_parted` | localizer | the belief's frame and mapd's differ by more than a threshold (the landmark offset plus a held fix's residual, known every tick; recorded in every `world` event as a value too) |
| `refusal_burst` | explorer | refusals in a row at one pose with no motion between (b11 r2: 6 in 0.45 s, then "trapped") |
| `room_disagrees` | navigator | the map says no room to turn while the depth sensor sees nothing near (b11 r5: room 0.136 m, nearest 283 mm) |
| `head_off_walk` | navigator | head joints away from the walking command while walking (the glance that tilted the odometry, EXPLORE-PROGRESS.md) |
| `refused_unexplained` | navigator | a leg refused with no obstacle or drop near by the robot's own map |
| `camera_failed`, `thread_failed` | camera, navigator | an observer stopped with an error |
| `stop_latched`, `lease_lost` | gate | STOP from someone, a takeover, a lease expired mid-goal |

### 3.2 Found by the analysis

Groups 1–3 work on the real robot; group 4 needs the simulator's truth and says so.

1. **Sensors:** depth frames dropped or mostly invalid; a frame paired with a state too far apart in
   time; tilt or roll past the gait's normal sway; joints not following their commands.
2. **Movement against intent:** near miss (inside the margin of an obstacle or a drop without
   touching); dithering (back and forth on a spot, the same replan repeating); odometry scale off on
   a leg (odometry over true distance outside 0.95–1.05). Slip and veer wait for a predicate: the walk
   drifts right by design (microduck_rl#59), so a plain veer detector would fire on every leg.
3. **The robot's pieces against each other:** mapd against odometry; belief against landmarks; the
   objects' area-type guess against the operator's area; the map against itself (an obstacle where
   the robot later walked freely).
4. **The robot's world against the real one** (simulator only): phantom obstacles (in the map, not
   real), missed ones (real, never in the map); belief against truth over time, heading included
   (`yaw_vs_truth`); a drop edge placed off its real place (b11 r2: the stairwell's rim 0.45 m short
   against a −18 cm budget); wrong decisions (a refusal where a path existed, a drop that was floor);
   exploring that ended "nothing left" with an area barely covered.
5. **Across runs:** a number out of its usual range against earlier batches (refusals, crossing
   time, held fixes): regressions caught before anyone watched a run.

The first build does 3.1, and from 3.2: near miss, dithering, odometry scale, phantom and missed
obstacles, belief and heading against truth, a misplaced edge, wrong refusals, and areas left
uncovered. The rest come later in the same record.

**A detector earns its place on the track** by staying quiet on clean runs: before it joins, it
reports its count on b9 r2, b10b and b11 r1, and one that fires on routine behaviour is fixed or
left out (b11 r1 alone has 2056 sightings).

## 4. Where they show

### 4.1 The Observatory (afterwards: study a run)

- **An anomaly track** on the timeline: one mark per anomaly, coloured by severity, the found ones
  told apart from the tagged ones; click to jump there.
- **Pins on the map** at `where.belief` and `where.truth`, joined by a line: where the robot's
  world and the real one parted.
- **The three maps, told apart.** Today mapd's grid and the navigator's memory are drawn as one,
  in one frame. They are not one: mapd's grid is in mapd's frame and moves when mapd jumps; the
  navigator's memory (obstacles, drops, objects) is placed with the belief; the truth is the
  simulator's layout. Each gets its own layer and frame, and the moment they part is an anomaly
  (`frames_parted`), with the offset shown.
- **The Eye** names the anomaly in force under its decision line.
- The analysis runs when a run is indexed; its results go into the derived index and are rebuilt
  when a detector's version changes.
- The three maps can be drawn from what is already recorded (mapd's grid in every `world` event)
  once each `world` event carries the frame delta (§3.1, `frames_parted`).

### 4.2 Mission Control (live)

- A robot's card shows its anomalies in the last minute (count and the worst), a goal run's
  progress shows each as it comes, with a link into the Observatory at that moment.
- Only robot-tagged anomalies are live; the found ones arrive when the run is indexed.

### 4.3 The video and the live broadcast

- An anomaly panel beside the Eye and the HUD: the anomaly, its summary, its severity, held on
  screen a few seconds; the same in the live watch page.

## 5. Build

1. The record and the robot-tagged set (§3.1) in the navigator; mapd's lost reason and counters
   read on every fix (built: 28c5cc9, `mapd_status`); the frame delta in every `world` event (with
   the frame fix, branch nav-frames).
2. The analysis as a command-line table over one run first (a detector is a function over a run
   that returns records), used on b11 at once; then the first found set (§3.2) in the Observatory's
   derived index.
3. The Observatory's track, pins, three maps and the Eye's line; the page tests.
4. Mission Control's live side; the video panel and the watch page (kept: the operator asked for
   them; the review would have cut them from this RFC, and they come after 1–3).
5. Across-run detectors once a batch store exists.

Each step: unit tests on recorded runs, each fixture coming out as the anomaly it was: b10b r2's
graze (near miss, then contact), gate12's stalls (stuck), b11 r2 (the refusal burst and the
misplaced edge), b11 r3 (the room disagreement), gate3 ch11 (the odometry scale, the runs before
its fix). b10a r1's jump
can only be found by belief against truth: its recording has no raw fix, so it is no fixture for
`fix_jump_held`.

## 6. Questions, answered

The operator, 2026-11-19: "I will go with your recommendation on these 3 questions".

1. **Severity thresholds** (what a near miss is): proposed from the recordings when the detectors are
   built, each number with the runs it was read from, then reviewed with the operator.
2. **Does a found anomaly ever write back into the robot's run log?** No: the recording stays what
   the robot knew; found anomalies live beside the run, rebuilt when a detector changes.
3. **The NXT and EV3:** they tag the gate's anomalies (`stop_latched`, `lease_lost`) and their
   adapter's own (offline, a deadman stop) from the first build; the found detectors that need a
   map or a pose (near miss, phantom and missed obstacles, belief against truth) do not apply until
   a robot has one, and say so instead of reporting nothing.

## 7. Not covered

- Fixing the causes: the jump recovery, heading correction and the turning-while-crossing fix are
  their own work; this RFC only makes them visible.
- The real robot's truth: group 4 has none there; its stand-ins are group 3.
- Alerting outside the apps (notifications, Slack): later, with RFC-0014's step 7 remainder.
