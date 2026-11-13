# Stretching eval-harness and flotilla into robotics

Status: ideas, 2026-11-13. The operator wants to see how far their two projects can be stretched
to be useful in robotics. Nothing here is decided in either project: each item would go through
that project's own RFC/ADR process, and its Non-Goals are read first.

Sources: eval-harness `/work/eval-harness/main` (harness 0.6.0, `bc2286392`; details in
[EVAL-HARNESS-ROBOTS.md](EVAL-HARNESS-ROBOTS.md)); flotilla `/work/flotilla/main` (README,
ADR-0005 agent pipeline, ADR-0006 node agent, ADR-0008 autonomy). The robot side is
[ROBOT-BRAIN.md](ROBOT-BRAIN.md).

## The two projects at their core

- **eval-harness** answers *is this change really better, or a lucky sample?* Freeze cases, run
  alternatives as arms, test whether the ranking is real, refuse unsound comparisons.
- **flotilla** answers *what may an agent do without asking, and what happened?* Every problem
  is a **case** with a lifecycle (detected → planned → awaiting approval → executing → checking →
  closed). Agents plan; policy decides; a host agent runs only signed, allowed actions. Autonomy is
  one ladder — **shadow → propose → auto** — earned on evidence and promoted only by the operator
  (ADR-0008).

Robots need both more than software does: trials are noisy and few ("is it better?" is hard),
and actions happen in the physical world ("may it act?" matters more). And they lock together:
**flotilla promotes on evidence; eval-harness produces evidence.**

## The combined loop

```
instruction ("tour the rooms, hide under the kitchen table")
   │
   ▼  flotilla: a MISSION CASE
planned by the robot brain (LLM) ─► policy: autonomy level of each action
   │                                  shadow  = run it in the simulator twin
   │                                  propose = ask the operator (with a camera snapshot)
   │                                  auto    = do it
   ▼
robot host executes ─► check: sensors + vision model ("are we under the table?") ─► close
   │
   ▼  run record
eval-harness: success / time / safety over many runs, sim and real
   │
   └──► evidence the operator uses to promote an action or mission type
```

**The key idea: for a robot, shadow can mean "run it in the simulator".** Today flotilla's
shadow records a plan and does nothing. For a robot it can execute the plan on the simulated
twin and score it — a measured rehearsal instead of a dry run.

## eval-harness: capabilities robotics would push

| # | Capability | Why for robots | Today |
|---|---|---|---|
| 1 | **Side-effect-safe adapters**: a "moves hardware" flag, no automatic retries, own timeout, a pause for "reset the robot" | A retried trial is a second physical run | Core retries up to 8 times on "timeout"/"connection" errors (`_retry.py`) |
| 2 | **Structured scenario items**: the adapter gets the item id and fields (start pose, scene, instruction) | Scenarios are data, not text | Adapter gets item text and params only (`run.py`) |
| 3 | **Trajectories as outputs** + scorers over them (success, time, path length, collisions, closest approach) | A run is a time series, not one answer | Output is a string; numbers via `Result.extra` |
| 4 | **Sequential testing**: run until significant or clearly not | Robot time is the scarce resource | Fixed item and repeat counts |
| 5 | **Repeat variance in the tests** | Few items, noisy repeats | Tests average repeats per item; spread is printed, not used |
| 6 | **Sim vs real as a first-class comparison**, the gap as a metric | The sim-to-real gap is the central robotics question | Possible as two arms on one dataset version |
| 7 | **Safety as a gate** ("collisions = 0"), not a score | A faster, unsafe controller must never win | Goal axes with limits point this way |
| 8 | **Mission judging** against a reference plan | Was the plan sensible, not just did it finish | Judges read no reference |
| 9 | **Perception datasets from the robot** (frames → frozen datasets, vision models as arms) | Choosing the robot's eyes | Works today via capture |
| 10 | **Replay in the inspector**: trajectory or video beside the scores | Seeing why a run failed | — |

**Tension to settle first:** eval-harness PRD-014 lists online evaluation as a non-goal ("the
harness evaluates what production did, offline, after it did it"). Live robot trials sit on that
line. Either trials run outside and are imported (`evh import-run` works today), or the PRD is
changed on purpose.

## flotilla: capabilities robotics would push

| # | Capability | Maps onto |
|---|---|---|
| 1 | **A robot host type**: a host agent near (later on) the robot; allowed actions are robot actions with risk and reversibility (moving: mostly reversible; grabbing, firing: not) | ADR-0006 host agent: allowlist, autonomy cap, signed executions |
| 2 | **Missions as cases** at the right timescale: flotilla decides whether and which mission and approves risky steps; the brain and navigator own seconds and milliseconds. flotilla is never in the motion loop | ADR-0005 case lifecycle |
| 3 | **Guardrails**: the freeze as an e-stop for every robot; holds ("no missions at night", "dog in the living room"); per-target lock (one mission per robot); circuit breaker (three falls → stop); caps (missions per hour) | ADR-0005 §7 guardrails |
| 4 | **Triggers**: home-automation events and robot telemetry (battery low, stuck) open cases — the robot ops fleet | Monitors |
| 5 | **Recall**: map, rooms, objects seen, mission history ("where was the table last time?") | ADR-0005 recall, ADR-0010 |
| 6 | **Approvals with evidence**: a camera frame and the planned route in the Slack approval | Channels and approvals |
| 7 | **Check steps from sensors**: a frame plus a vision-model verdict closes the case | The "checking" stage |
| 8 | **Promotion tied to eval-harness**: the promote button shows N runs, success rate, the significance result | ADR-0008: promoted on evidence |
| 9 | **A robotics fleet pack** | ADR-0013 fleet packs |
| 10 | **Several robots, one fleet**: the duck sees, the NXT drives, one case, two hosts | — |

**Tension to settle first:** flotilla's cases run in minutes to hours and its host agent is
designed for server operations. A robot host pushes on both, so it wants its own ADR, as the
host agent got ADR-0006.

## Staged path

1. **Until the duck arrives — no changes to either project.** Use eval-harness as it is (arena
   races, the brain's simulator phases, via `import-run`) and log every friction point. That log
   decides which capability to build first.
2. **eval-harness capabilities**, probably in this order: side-effect-safe adapters, structured
   items, trajectory scorers, sequential testing — each through its RFC process.
3. **flotilla**: a robot-host ADR, then mission cases with shadow running in the simulator —
   after the host agent now being built.
4. **The real duck**: mission types move from propose to auto one at a time, on eval-harness
   evidence.

## Open

- Whether eval-harness changes PRD-014 or keeps live trials outside and imported.
- Where a robot host agent runs (next to the robot on the LAN, or on it).
- Which guardrail is the e-stop: flotilla's freeze, the robot UI's STOP, or both (both, probably,
  with the robot's own deadman underneath either way).
