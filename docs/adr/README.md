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
- With [RFC-0010](../rfc/RFC-0010-run-store-v2.md), all Accepted 2026-11-15:
  - [ADR-0006 — A run is robot/scene/run, and says who it is](ADR-0006-run-identity.md)
  - [ADR-0007 — The run file, format 2](ADR-0007-run-file-format-2.md)
  - [ADR-0008 — Reading runs: validated, isolated, aware of rewrites](ADR-0008-reading-runs.md)
  - [ADR-0009 — The index, run states and a bounded cache](ADR-0009-index-and-lifecycle.md)
  - [ADR-0010 — The API, version 2](ADR-0010-api-2.md)
  - [ADR-0011 — Loading a run into the UI: by window, then by record](ADR-0011-loading-into-the-ui.md)
  - [ADR-0012 — Docker: the data read only, the index on its own volume](ADR-0012-docker-read-only-data.md)
- [ADR-0013 — NXT runs in format 2: signals, odometry, a scene with no
  layout](ADR-0013-nxt-runs-in-format-2.md) (Proposed, 2026-11-16)

Accepted RFCs ([Proposals](../rfc/README.md)) become ADRs here.
