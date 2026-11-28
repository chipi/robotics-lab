# RFCs — proposals under review

Proposals that need a "should we?" review before becoming decisions.

Distinct from `docs/adr/` (architecture decisions that have been *accepted*). An RFC moves to:

- an ADR if accepted (structural decision);
- a decision-log entry if accepted at operational level;
- deletion if rejected (with a brief rationale in the closing commit).

## Format

`RFC-NNNN-short-slug.md`, numbered sequentially, never renumbered.

Required sections:

- **Status** (Proposed / Under review / Accepted → ADR-NNNN / Rejected)
- **Motivation** — what problem we're trying to solve
- **Proposal** — what we're suggesting
- **Open questions** — what's not yet resolved
- **Alternatives considered**
- **Discussion** — append-only thread of considerations (date-stamped)

Same conventions as the operator's other projects (flotilla, eval-harness).

## Index

- [RFC-0001 — The NXT web UI](RFC-0001-nxt-web-ui.md) (Proposed; describes what was built,
  2026-11-14)
- [RFC-0002 — The robot brain: modes, navigator, safety and phases](RFC-0002-robot-brain.md)
  (Proposed, revision 2 after review; phase 0 approved)
- [RFC-0003 — One robot interface: JSON-RPC for every robot, and a deadman on the
  NXT](RFC-0003-robot-interface.md) (Proposed; direction agreed)
- [RFC-0004 — Missions in words, perception and planning: the brain's models and
  tools](RFC-0004-perception-and-planning.md) (Proposed, revision 2; phase-1 models live)
- [RFC-0005 — Missions: flotilla decides, the simulated duck rehearses, eval-harness
  measures](RFC-0005-missions.md) (Proposed, revision 3; the form agreed)
- [RFC-0006 — Mission control: the robotics product, and where it ends and flotilla
  begins](RFC-0006-mission-control.md) (Proposed; a vision)
- [RFC-0007 — The platform: an open alternative to Foxglove, assembled from our
  tools](RFC-0007-platform.md) (Proposed; the operator's vision)
- [RFC-0008 — The challenge course: one difficulty at a time, then all of
  them](RFC-0008-challenge-course.md) (Proposed; phase 2's bar, by the operator's decision)
- [RFC-0009 — miniview: one run format, two faces, any
  robot](RFC-0009-miniview.md) (Proposed; with PRD-001 and UXS-001)
- [RFC-0010 — Runs, version 2: how they are stored, read, served and
  loaded](RFC-0010-run-store-v2.md) (Accepted, 2026-11-15; ADR-0006 to ADR-0012)
- [RFC-0011 — Robots drawn as themselves: a link/joint description, moved by the recorded
  joints](RFC-0011-robot-models.md) (Accepted, 2026-11-16)
- [RFC-0012 — Look far, get ready early: where to look and how fast to
  go](RFC-0012-look-far.md) (Accepted, 2026-11-18)
- [RFC-0013 — The robot's eye: what it sees, what it builds, and a page to watch
  it](RFC-0013-robot-eye.md) (Accepted, 2026-11-17)
- [RFC-0014 — Mission Control: one API for every robot, goals in words, places and
  objects](RFC-0014-mission-control.md) (Accepted, revision 2, 2026-11-18; built: the core and the API,
  the fake robot, the simulated duck (`duck-sim`, behind its runner since RFC-0021 step 6) and the NXT)
- [RFC-0015 — Nav2 on the simulated duck: learn how the standard stack works, and
  compare](RFC-0015-nav2-comparison.md) (Accepted, 2026-11-18)
- [RFC-0016 — Objects, landmarks and a semantic map: "this is the kitchen", "go to the
  fridge"](RFC-0016-objects-and-semantic-map.md) (Accepted, 2026-11-18; MVP being built)
- [RFC-0017 — Robot access: who may watch, who may drive, and one driver at a
  time](RFC-0017-robot-access.md)
  (Accepted, revision 2, 2026-11-18; the gate library and the nxt-web lock built)
- [RFC-0018 — The lab's projects, their seams, and how to split robotics-lab
  later](RFC-0018-lab-projects-and-seams.md) (decided in direction 2026-11-18: one repo,
  restructured in full; built 2026-11-19)
- [RFC-0019 — Anomalies: what went wrong, told by the software, on the timeline and the
  map](RFC-0019-anomaly-telemetry.md) (Accepted with changes, 2026-11-19)
- [RFC-0020 — Robot profiles and capability plugins: each robot brings what it is and how it
  moves](RFC-0020-robot-profiles-and-plugins.md) (Accepted, 2026-11-19)
- [RFC-0021 — The simulator host and the payload: run a navigator on any machine that has Pollen's
  simulator](RFC-0021-sim-host-and-payload.md) (Accepted, 2026-11-19; steps 1–6 built 2026-11-21)
- [RFC-0022 — The platform's layout and names: what is the duck's, and what is
  everyone's](RFC-0022-platform-layout-and-names.md) (Accepted and built, 2026-11-21)
- [RFC-0023 — The views: the operator's journeys, which surface does what, and where the telemetry
  goes](RFC-0023-the-views.md) (Accepted, 2026-11-21: A for all twelve decisions)
- [RFC-0024 — One platform: should Mission Control and the Observatory stay two
  apps?](RFC-0024-one-platform.md) (Accepted, 2026-11-23: B, reached in C's order; step 3 built)
- [RFC-0025 — From MVP 1 to MVP 2: the platform's architecture and its
  evolution](RFC-0025-mvp1-to-mvp2.md) (Accepted, 2026-11-23)
- [RFC-0030 — Missions: planning as a module, Mission Control as the executor; manual and auto
  modes](RFC-0030-missions.md) (Proposed, revision 2, 2026-11-26, after the advisor's review;
  modes and sequencing decided by the operator)
- [RFC-0031 — Learning in the lab: training as a run on another kind of
  resource](RFC-0031-learning-in-the-lab.md) (Accepted, 2026-11-26: option A, all eight questions as
  recommended, after the advisor's review; nothing built yet)
- [RFC-0032 — Robot abilities: a generic model for what a robot can do and who drives
  it](RFC-0032-robot-abilities.md) (Accepted, 2026-11-28: all six questions as recommended;
  nothing built)

The map of how the pieces fit, from these RFCs: [How the platform fits together](../architecture.md).
