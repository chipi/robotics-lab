# WIP — work in progress

Notes in progress: plans, ideas, analyses. Promotion targets:

| Promote to | When |
| --- | --- |
| `docs/adr/` | The decision is structural and final |
| `docs/rfc/` | The decision needs a proposal-and-review process before adoption |
| A reference doc | The content is stable enough to be a reference |
| `docs/history/0NNN-...md` | The session that produced it has wrapped |
| *delete* | Turned out not to matter |

## Open notes

- [Handover](HANDOVER.md) — start here: the living status of the MVP 1 wrap-up.
- [Handover: the learning arc, 2026-11-26](HANDOVER-TRAINING-2026-11-26.md) — where the
  learned-avoidance training and its evaluations stand; read it first when continuing them.
- [Research plan: learned avoidance](RESEARCH-LEARNED-AVOIDANCE.md), with
  [R1 and R2](RESEARCH-R1-R2.md), [S1 to S4](RESEARCH-S1-S4.md), [R4](RESEARCH-R4-OBS-PARITY.md)
  and [R6](RESEARCH-R6-PLAN.md); the guide to it is [Training the controller](../training/index.md).
- The 2026-11-26 reviews: [technical review](TECH-REVIEW-2026-11-26.md), and the advisor's reviews of
  [RFC-0024](RFC-0024-REVIEW-2026-11-26.md), [RFC-0030](RFC-0030-REVIEW-2026-11-26.md) and
  [RFC-0031](RFC-0031-REVIEW-2026-11-26.md).
- [Phase 5: the plan after step 1](PHASE5-NEXT-PLAN.md) — the items, the wrap-up order, what
  each built.
- [Known issues](KNOWN-ISSUES.md), [parked for the operator](PARKED-FOR-OPERATOR.md).
- [Look and feel: the step 4.5 plan](LOOK-AND-FEEL-PLAN.md), with its
  [research](LOOK-AND-FEEL-RESEARCH.md) and [unit brief](look-and-feel/UNIT-BRIEF.md).
- [Telemetry](TELEMETRY.md) and [its retention design](TELEMETRY-RETENTION-DESIGN.md);
  [deploying the platform](DEPLOY.md), [deployment notes](DEPLOYMENT-NOTES.md),
  [the staging cut-over](STAGING-CUTOVER.md), [prod on the X3](PROD-ON-X3.md).
- [MCP coverage](MCP-COVERAGE.md), [the execution plan](EXECUTION-PLAN.md) (the history up to
  phase 5; the current state is in the handover), [status (superseded)](STATUS.md).
- The real duck: [backlog](REAL-DUCK-BACKLOG.md), [bringing up the link](REAL-DUCK-LINK.md),
  [measurements](REAL-DUCK-MEASURE.md), [readiness](PHASE5-REAL-DUCK-READINESS.md).
- NXT: [D0](NXT-D0.md), [D1 checklist](NXT-D1-CHECKLIST.md), [MVP 1](NXT-MVP1.md),
  [the CH22 rim](CH22-RIM.md).
- [MVP 2 spike](MVP2-SPIKE.md), [sensors against ROS](SENSORS-VS-ROS.md),
  [pending decisions](PHASE5-DECISIONS-PENDING.md).
- [Roadmap](ROADMAP.md) — the order of work.
- [Ideas](IDEAS.md) — NXT programs, wireless NXT, bigger NXT robots and the arm robot, goal
  projects, eval-harness and flotilla ideas.
- [Long-term direction](ECOSYSTEM.md) — the robotics ecosystem.
- [Microduck](MICRODUCK.md) — upstream repos, simulator, arena, DGX training, policies and skills.
- [Running the simulated duck from an agent](DUCK-SIM-FOR-AGENTS.md) — the sudo lockout, the
  local patch, the guards.
- [eval-harness for robot trials](EVAL-HARNESS-ROBOTS.md) — what fits, the friction.
- [Stretching eval-harness and flotilla](STRETCH-EVAL-FLOTILLA.md) — the full idea list behind
  [RFC-0005](../rfc/RFC-0005-missions.md).
- [NXT parts to look for](NXT-PARTS.md).
- [Review of the duck RFCs, 2026-11-14](REVIEW-2026-11-14-duck-rfcs.md) — findings and what was done.
- [Review of all RFCs, round 2](REVIEW-2026-11-14-round2.md) — findings and what was done.
- [Review of the navigator, 2026-11-15](REVIEW-2026-11-15-navigator.md) — rules in conflict,
  blind spots, next steps (led to RFC-0008).
- [Review of miniview, 2026-11-15](REVIEW-2026-11-15-miniview.md) — 13 findings, all to be
  fixed (led to RFC-0010 and ADR-0006 to ADR-0012).
- [Review of miniview, round 2, 2026-11-16](REVIEW-2026-11-16-miniview-round2.md) — findings
  of a second review and the RFC-0008 gaps, with what was done.
- [What robotics asks of flotilla](FLOTILLA-ASKS.md) — for the flotilla session to assess.
- [What robotics asks of eval-harness (for 0.9)](EVAL-HARNESS-ASKS.md) — for the eval-harness
  session to assess.

Promoted: the robot brain draft became [RFC-0002](../rfc/RFC-0002-robot-brain.md) and
[RFC-0004](../rfc/RFC-0004-perception-and-planning.md) (2026-11-14).
