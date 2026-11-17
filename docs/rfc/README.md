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
  go](RFC-0012-look-far.md) (Proposed, 2026-11-16)
- [RFC-0013 — The robot's eye: what it sees, what it builds, and a page to watch
  it](RFC-0013-robot-eye.md) (Accepted, 2026-11-17)
- [RFC-0015 — Nav2 on the simulated duck: learn how the standard stack works, and
  compare](RFC-0015-nav2-comparison.md) (Accepted, 2026-11-18)
