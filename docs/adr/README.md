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

Accepted RFCs ([Proposals](../rfc/README.md)) become ADRs here.
