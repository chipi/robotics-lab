# RFC-0005 — Missions: flotilla decides, the simulated duck rehearses, eval-harness measures

**Status:** Proposed, revision 2 (2026-11-14). The combined mission loop is the operator's
direction (2026-11-13); after the [review](../wip/REVIEW-2026-11-14-duck-rfcs.md) the operator
agreed its form: **the simulated duck is a second host at `auto`, and every mission rehearses there
before it runs on the real duck** — flotilla's "shadow" keeps its meaning. Changes to flotilla and
eval-harness themselves go through those projects' own RFCs.
**Builds on:** [STRETCH-EVAL-FLOTILLA.md](../wip/STRETCH-EVAL-FLOTILLA.md),
[RFC-0002](RFC-0002-robot-brain.md), [RFC-0004](RFC-0004-perception-and-planning.md).
**Other projects:** flotilla (`/work/flotilla/main`: ADR-0005 cases, ADR-0006 host agent, ADR-0008
autonomy) and eval-harness (`/work/eval-harness/main`, harness 0.6.0).

## 1. Motivation

A robot that acts on its own needs two answers the brain cannot give itself:

- **May it do this, now, without asking?** — flotilla: cases, policy, approvals, and one autonomy
  ladder (shadow → propose → auto) earned on evidence and promoted only by the operator.
- **Is this version really better, or did it get lucky?** — eval-harness: frozen cases, arms, and
  whether a ranking is real.

Robots need both more than software does: trials are few and noisy, and actions happen in the
physical world. And the two fit: **flotilla promotes on evidence; eval-harness produces it.**

## 2. Proposal

### 2.1 The mission loop

```text
instruction ("visit every room, tell me their sizes, then wait by the front door")
   │
   ▼  flotilla: a MISSION CASE, mission spec attached (RFC-0004 §2.1)
REHEARSAL on host duck-sim (autonomy cap: auto) ─► score: plan valid? reached the end? collisions?
   │
   ▼  policy for host duck (the real robot): its autonomy level for this mission type
   │     shadow  = the plan is recorded, nothing is done          (flotilla's meaning, unchanged)
   │     propose = ask the operator, with the rehearsal's score, a camera frame and the route
   │     auto    = run it
   ▼
the real duck runs it ─► check: sensors + vision model ("are we 1 m from the coat rack?") ─► close
   │
   ▼  run records of both hosts (RFC-0002 §3.2)
eval-harness: success / time / safety over many runs, simulator and real
   │
   └──► the evidence the operator uses to promote a mission type on the real duck
```

### 2.2 The simulated duck is a host

flotilla's ADR-0008 defines shadow as "plans recorded, nothing done", and its freeze relies on that
("nothing outward happens"). So shadow is not redefined. Instead:

- **Two hosts:** `duck-sim` (the simulated duck: the real daemons against a MuJoCo body) with its
  autonomy cap at `auto`, and `duck` (the robot) starting at `shadow`.
- **Rehearsal is a step of every mission case**, not a rung of the ladder: the plan runs on
  `duck-sim` first, and its score is attached to the decision for `duck`.
- **The freeze** still lowers everything to shadow, the simulator included.

What a rehearsal can and cannot predict (the simulator walks at about 44 % of the asked speed, and
turning did not match upstream locally — RFC-0002 phase 0 checks it):

| Predicts | Does not predict |
| --- | --- |
| The plan is valid: the spec parses, the tools exist, the end is reachable on the map | Timing |
| Collisions with what the map knows | Falls, slips, the dog |
| The planner's choices given the same world model | Perception in a real home (the simulator is textured boxes) |

So a rehearsal is necessary, not sufficient: it can stop a bad plan, not prove a good one.

### 2.3 What maps onto flotilla

| Robot need | flotilla concept |
| --- | --- |
| A mission | a case, one per instruction, with its spec |
| What the brain may do | capabilities with risk and reversibility; moving mostly reversible, grabbing or pulling not |
| The robots | hosts with autonomy caps: `duck-sim` at `auto`, `duck` earned step by step |
| E-stop for all robots | the freeze, alongside the UI's STOP and each robot's own deadman |
| "No missions at night", "dog in the room" | holds |
| One mission per robot | the per-target lock |
| Three falls → stop | the circuit breaker |
| Approval with evidence | an approval carrying the rehearsal's score, a camera frame and the route |
| Closing a mission | the check step, from sensors and the vision model |

### 2.4 What eval-harness measures

- **Items:** scenarios (start pose, scene, instruction), frozen as files; at least 10 per arm for
  intervals to mean anything (eval-harness needs more than 5 items for a confidence interval).
- **Arms:** brain versions, model choices, controller settings; the simulator and the robot as two
  arms on the same scenarios.
- **Scores from run records:** success, time, distance, contacts, falls, model cost.
- **Build identity:** eval-harness takes one build reference; a run is three versions, written
  `brain@<commit>+model@<alias>+policies@<set>`.
- **Today:** trials run outside the harness and their per-item scores are imported (`evh
  import-run`), with the friction in [EVAL-HARNESS-ROBOTS.md](../wip/EVAL-HARNESS-ROBOTS.md).

### 2.5 Order

1. **Until the robot brain runs (RFC-0002 phases 0–4):** no changes to either project; use
   eval-harness via `import-run`; log every friction point.
2. **eval-harness capabilities** from that log (likely: side-effect-safe adapters, structured
   scenario items, trajectory scorers, sequential testing) — through eval-harness's RFCs.
3. **flotilla:** a robot-host ADR there, then mission cases with rehearsal on `duck-sim` — after
   its host agent (planned 2026-11-13, a skeleton started).
4. **The real duck:** mission types move from shadow to propose to auto one at a time, on evidence.

## 3. Non-goals

- flotilla in the motion loop: it decides whether and which mission, never twists.
- Changing either project from here: this RFC states needs; the projects decide.
- Several robots in one mission before one robot works end to end.

## 4. Open questions

1. eval-harness lists online evaluation as a non-goal (PRD-014): keep live trials outside and
   imported, or change that on purpose.
2. A robot host in flotilla wants its own ADR there: cases run minutes to hours; ADR-0006's host
   actions are exact argv templates with a 10-minute signature expiry, which fits a long-lived
   navigator poorly (a mission is better an action that starts and supervises one).
3. Where a robot host agent runs: next to the robot on the LAN, or on it.
4. Which stop is the e-stop: the freeze, the UI's STOP, or both — with each robot's deadman beneath.

## 5. Alternatives considered

- **Shadow redefined as "execute on the simulator":** the first version of this RFC. Rejected after
  the review: it would give shadow two meanings across flotilla, and the freeze would start
  simulator runs.
- **The brain decides its own autonomy:** rejected; the operator promotes on evidence.
- **A separate robotics-only approval system:** duplicates flotilla.

## 6. Discussion

- 2026-11-13 — Ideas as `docs/wip/STRETCH-EVAL-FLOTILLA.md`; the operator: "100% on the combined
  mission loop, with the key idea that shadow means running the plan on the simulated duck".
- 2026-11-14 — Written as this RFC at the operator's request.
- 2026-11-14 — Review (M2): shadow already has a meaning in flotilla. Operator agreed: the simulated
  duck is a second host at `auto`, rehearsal before every real run. Revision 2. Also: the example
  mission is now "…then wait by the front door" (the kitchen table was dropped, RFC-0002 §1); build
  identity format; host-agent status corrected; ADR-0006 friction recorded.
