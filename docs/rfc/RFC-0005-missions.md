# RFC-0005 — Missions: flotilla decides, the simulator rehearses, eval-harness measures

**Status:** Proposed (2026-11-14). The core idea — the combined mission loop, with shadow meaning
"run the plan on the simulated duck" — is the operator's agreed direction (2026-11-13). Changes to
flotilla and eval-harness themselves go through those projects' own RFCs.
**Builds on:** [STRETCH-EVAL-FLOTILLA.md](../wip/STRETCH-EVAL-FLOTILLA.md) (the full list of
ideas), [RFC-0002](RFC-0002-robot-brain.md), [RFC-0004](RFC-0004-perception-and-planning.md).
**Other projects:** flotilla (`/work/flotilla/main`: ADR-0005 cases, ADR-0006 host agent, ADR-0008
autonomy) and eval-harness (`/work/eval-harness/main`, harness 0.6.0).

## 1. Motivation

A robot that acts on its own needs two answers the brain cannot give itself:

- **May it do this, now, without asking?** — flotilla's job: cases, policy, approvals, and one
  autonomy ladder (shadow → propose → auto) earned on evidence and promoted only by the operator.
- **Is this version really better, or did it get lucky?** — eval-harness's job: frozen cases, arms,
  and whether a ranking is real.

Robots need both more than software does: trials are few and noisy, and actions happen in the
physical world. And the two fit: **flotilla promotes on evidence; eval-harness produces it.**

## 2. Proposal

### 2.1 The mission loop

```text
instruction ("tour the rooms, hide under the kitchen table")
   │
   ▼  flotilla: a MISSION CASE
planned by the robot brain ─► policy: each action's autonomy level
   │                            shadow  = run the plan on the simulated duck, score it
   │                            propose = ask the operator, with a camera frame and the route
   │                            auto    = run it
   ▼
the robot runs it ─► check: sensors + vision model ("are we under the table?") ─► close
   │
   ▼  run record (RFC-0002 §3.1)
eval-harness: success / time / safety over many runs, simulator and real
   │
   └──► the evidence the operator uses to promote an action or mission type
```

### 2.2 Shadow is the simulator

flotilla's shadow today records a plan and does nothing. For a robot, **shadow executes the plan on
the simulated duck** (`duck-sim`, the same daemons, the same policies) and scores it: a measured
rehearsal, not a dry run. That makes the simulator a permanent part of the system, and is why
[RFC-0002](RFC-0002-robot-brain.md) requires the same code to drive the simulator and the robot.

### 2.3 What maps onto flotilla

| Robot need | flotilla concept |
| --- | --- |
| A mission | a case, one per instruction |
| What the brain may do | capabilities with risk and reversibility; moving mostly reversible, grabbing or pulling not |
| The robot | a host with an autonomy cap |
| E-stop for all robots | the freeze (alongside the UI's STOP and each robot's own deadman) |
| "No missions at night", "dog in the room" | holds |
| One mission per robot | the per-target lock |
| Three falls → stop | the circuit breaker |
| Approval with evidence | a Slack approval carrying the camera frame and route |
| Closing a mission | the check step, from sensors and the vision model |

### 2.4 What eval-harness measures

- Items: scenarios (start pose, scene, instruction), frozen as files.
- Arms: brain versions, model choices, controller settings; simulator and real as two arms.
- Scores from run records: success, time, distance, collisions, falls, model cost.
- Today this works by running trials outside the harness and importing per-item scores
  (`evh import-run`), with the friction listed in
  [EVAL-HARNESS-ROBOTS.md](../wip/EVAL-HARNESS-ROBOTS.md).

### 2.5 Order

1. **Until the robot brain runs (RFC-0002 phases 0–4):** no changes to either project. Use
   eval-harness as it is via `import-run`; log every friction point.
2. **eval-harness capabilities**, from that log (likely: side-effect-safe adapters, structured
   scenario items, trajectory scorers, sequential testing) — each through eval-harness's RFCs.
3. **flotilla:** a robot-host ADR there, then mission cases with shadow on the simulator — after
   its host agent, now being built.
4. **The real duck:** mission types move from propose to auto one at a time, on evidence.

## 3. Non-goals

- flotilla in the motion loop: it decides whether and which mission, never twists.
- Changing either project from here: this RFC states needs; the projects decide.
- Several robots in one mission before one robot works end to end.

## 4. Open questions

1. eval-harness lists online evaluation as a non-goal (PRD-014): keep live trials outside and
   imported, or change that on purpose.
2. flotilla's cases run in minutes to hours and its host agent is built for servers: a robot host
   wants its own ADR there.
3. Where a robot host agent runs: next to the robot on the LAN, or on it.
4. Which stop is the e-stop: flotilla's freeze, the UI's STOP, or both — with each robot's deadman
   underneath either way.

## 5. Alternatives considered

- **The brain decides its own autonomy:** rejected; the point is that the operator promotes on
  evidence.
- **Shadow as "record the plan only":** loses the main benefit — a plan rehearsed and scored before
  it moves a real robot.
- **A separate robotics-only approval system:** duplicates flotilla.

## 6. Discussion

- 2026-11-13 — Ideas written as `docs/wip/STRETCH-EVAL-FLOTILLA.md`; the operator: "100% on the
  combined mission loop, with the key idea that shadow means running the plan on the simulated
  duck".
- 2026-11-14 — Written as this RFC at the operator's request.
