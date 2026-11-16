# ADR-0012 — Docker: the data read only, the index in the host's state folder

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3, [ADR-0009](ADR-0009-index-and-lifecycle.md),
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) finding 9

## Context

The container mounts the lab's data folder read-write only because the index lives in it. A
viewer that can write the robot's records can damage them.

## Decision

- The container mounts `runs/` and `scenes/` **read only**; the index (ADR-0009) is **one**: the
  host's state folder (`MINIVIEW_STATE`, default `/work/robotics-lab/state/miniview`, where the
  commands' `MINIVIEW_INDEX` points) is mounted writable at `/index`, so the service and the commands
  share it. While a service holds the index (a lock file beside it, `flock`, which works across the
  bind mount), the commands (`scenes`, `runs`, `events --all`, `state`, `frame`) read it and write
  nothing, and say so in one line; `miniview index` refuses.
- **Imports and writers run on the host** (or on the robot side), never in the viewer's container.
- The default data path comes from the environment (`MINIVIEW_DATA`), with the workstation's path
  as the default only in the compose file and the Makefile.
- `make test-viewer-image` checks that the container cannot write to the data mount, and that its
  state mount is writable and shows the index on the host.

**What changed on 2026-11-16, and why.** The first version put the index on a named volume. Review
round 2 found two indexes: the commands, run on the host, scanned and wrote the host's index while
the service's was in the volume, so they answered differently and each re-opened every changed run.
One index fixes that; the cost is a writable mount of one small folder, never of the data.

## Consequences

- **Positive:** the viewer cannot change a run; the index survives container rebuilds and is one
  file, on the host, that the commands read too.
- **Negative:** the index is not in the data folder (it is in the state folder); the container user
  must be able to write the state folder (`MINIVIEW_UID`, `MINIVIEW_GID`).

## Alternatives considered

- **Read-write as today.** Simpler; one bug away from a damaged record.
- **The index on a named volume** (the first version of this record): two indexes, as above.
