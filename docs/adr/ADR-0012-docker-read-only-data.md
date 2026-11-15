# ADR-0012 — Docker: the data read only, the index on its own volume

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3, [ADR-0009](ADR-0009-index-and-lifecycle.md),
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) finding 9

## Context

The container mounts the lab's data folder read-write only because the index lives in it. A
viewer that can write the robot's records can damage them.

## Decision

- The container mounts `runs/` and `scenes/` **read only**; the index (ADR-0009) is on a named
  volume (`miniview-index`) at `MINIVIEW_INDEX`.
- **Imports and writers run on the host** (or on the robot side), never in the viewer's container.
- The default data path comes from the environment (`MINIVIEW_DATA`), with the workstation's path
  as the default only in the compose file and the Makefile.
- `make test-viewer-image` checks that the container cannot write to the data mount.

## Consequences

- **Positive:** the viewer cannot change a run; the index survives container rebuilds.
- **Negative:** the index is no longer visible as a file in the data folder (`docker volume
  inspect` shows where it is).

## Alternatives considered

- **Read-write as today.** Simpler; one bug away from a damaged record.
