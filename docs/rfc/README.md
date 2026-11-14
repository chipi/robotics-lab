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
  measures](RFC-0005-missions.md) (Proposed, revision 2; the form agreed)
