# ADRs — architecture decision records

Decisions that shape the *structure* of this project: what's in scope, how it's organised, what
conventions govern it.

Distinct from a decision log (operational choices — what tool, what port). The rule of thumb:

- **ADR:** would a future contributor need to know this to make a consistent change? → ADR.
- **Decision log:** a one-shot choice with a clear context → log entry.

## Format

`ADR-NNNN-short-slug.md`, numbered sequentially, never renumbered.

Required sections:

- **Status** (Proposed / Accepted / Superseded by ADR-XXXX)
- **Date**
- **Context** — the problem
- **Decision**
- **Consequences** — positive, negative, neutral
- **Alternatives considered**

## Index

- [ADR-0001 — ROS-aligned terms, no ROS foundation yet, Foxglove from the start](ADR-0001-ros-aligned-foxglove.md)
  (Accepted, 2026-11-14)
- [ADR-0002 — Viewers: Rerun first, Lichtblick kept usable, MCAP the record](ADR-0002-viewers-rerun-and-lichtblick.md)
  (Accepted, 2026-11-14)
- [ADR-0003 — miniview draws with three.js, the same page for the operator and the
  agent](ADR-0003-miniview-drawing-three-js.md) (Accepted for this step, 2026-11-15; reviewed mid-term)
- [ADR-0004 — Runs: MCAP the record of truth; a SQLite index and prepared frames derived from
  it](ADR-0004-runs-in-mcap-with-derived-index.md) (Accepted, 2026-11-15)
- [ADR-0005 — miniview: one API over the run store, live from the
  start](ADR-0005-miniview-api-live-from-the-start.md) (Accepted, 2026-11-15)

Accepted RFCs ([Proposals](../rfc/README.md)) become ADRs here.
