# RFC-0019 — Anomalies: what went wrong, told by the software, on the timeline and the map

**Status:** Proposed (2026-11-19), for the operator's review. The operator's direction, 2026-11-19:
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
 "t": 822.5, "t_end": 844.0,
 "where": {"belief": [1.94, -1.01], "truth": [1.69, -0.35]},
 "summary": "mapd moved the belief 0.90 m in one fix while pivoting; held",
 "values": {"jump_m": 0.90, "mapd_lost": "bumped", "relocalizations": 3},
 "related": ["contact@844.0"]}
```

- `where` carries both places when both are known: where the robot believed it was, and where it
  was. On the real robot `truth` is absent.
- `severity`: `info` (worth seeing), `minor` (cost time), `major` (put the run at risk), `critical`
  (contact, fall, a drop margin broken).
- `related` links causes and effects (the jump and the contact it led to).
- A robot-tagged anomaly is an event in the run log (ADR-0014's shape, `event: "anomaly"`); a
  found one is written beside the run by the analysis, never into the recording.

## 3. The first set

### 3.1 Tagged by the robot

| Anomaly | Module | When |
| --- | --- | --- |
| `fix_jump_held` | localizer | a mapd fix over 0.3 m / 0.35 rad held by the gate |
| `mapd_lost` | mapd (read by the navigator) | `map.status` says `lost` (`bumped`, `carried`, `sat`, `fell`, `contradiction`), or its loop / relocalisation counters step |
| `reloc_refused` | relocaliser | landmark sightings disagree with each other |
| `stuck` | navigator | walking, the belief going nowhere (`stuck.py`) |
| `refused_unexplained` | navigator | a leg refused with no obstacle or drop near by the robot's own map |
| `camera_failed`, `thread_failed` | camera, navigator | an observer stopped with an error |
| `stop_latched`, `lease_lost` | gate | STOP from someone, a takeover, a lease expired mid-goal |

### 3.2 Found by the analysis

Groups 1–3 work on the real robot; group 4 needs the simulator's truth and says so.

1. **Sensors:** depth frames dropped or mostly invalid; a frame paired with a state too far apart in
   time; tilt or roll past the gait's normal sway; joints not following their commands.
2. **Movement against intent:** slip (commanded speed against measured and true speed: the cable
   stalls); veer (heading drifting from what was asked); near miss (inside the margin of an obstacle
   or a drop without touching); dithering (back and forth on a spot, the same replan repeating).
3. **The robot's pieces against each other:** mapd against odometry; belief against landmarks; the
   objects' area-type guess against the operator's area; the map against itself (an obstacle where
   the robot later walked freely).
4. **The robot's world against the real one** (simulator only): phantom obstacles (in the map, not
   real), missed ones (real, never in the map); belief against truth over time; wrong decisions
   (a refusal where a path existed, a drop that was floor).
5. **Across runs:** a number out of its usual range against earlier batches (refusals, crossing
   time, held fixes): regressions caught before anyone watched a run.

The first build does 3.1, and from 3.2: near miss, slip, veer, dithering, phantom and missed
obstacles, belief against truth, and wrong refusals. The rest come later in the same record.

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
- The analysis runs when a run is indexed; its results are cached beside the run and rebuilt when
  a detector changes.

### 4.2 Mission Control (live)

- A robot's card shows its anomalies in the last minute (count and the worst), a goal run's
  progress shows each as it comes, with a link into the Observatory at that moment.
- Only robot-tagged anomalies are live; the found ones arrive when the run is indexed.

### 4.3 The video and the live broadcast

- An anomaly panel beside the Eye and the HUD: the anomaly, its summary, its severity, held on
  screen a few seconds; the same in the live watch page.

## 5. Build

1. The record and the robot-tagged set (§3.1) in the navigator; mapd's lost reason and counters
   read on every fix.
2. The analysis framework in the Observatory (a detector is a function over a run that returns
   records) and the first found set (§3.2).
3. The Observatory's track, pins, three maps and the Eye's line; the page tests.
4. Mission Control's live side; the video panel and the watch page.
5. Across-run detectors once a batch store exists.

Each step: unit tests on recorded runs (b10a r1's jump, b10b r2's graze, gate12's stalls are the
first fixtures: each must come out as the anomaly it was).

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
