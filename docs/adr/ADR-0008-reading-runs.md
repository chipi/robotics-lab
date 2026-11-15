# ADR-0008 — Reading runs: validated, isolated, aware of rewrites

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3,
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) findings 1, 4

## Context

A garbage file stops the service from starting (in Docker, a restart loop). A record without a
field it needs kills the follower thread, so no live run updates any more, new ones included, and
nothing says so. A file replaced or truncated under the reader is read from a stale offset, mid
record, without error.

## Decision

- **Every record is checked** against its kind: required fields, types, list lengths, finite
  numbers, time that does not go back. A bad record is skipped; the run counts `rejects` and keeps
  the first error, and is served with them.
- **A run is broken** when its file is not MCAP, its `run` record is missing or invalid, or its key
  disagrees with its folder (ADR-0006). A broken run is listed with its error and not loaded.
- **Nothing in one run reaches another.** Opening, following and summarizing a run each catch
  everything; a failure marks that run broken and is logged with the run's key.
- **The follower never stops.** Its loop catches, logs and continues.
- **Rewrites are noticed.** The reader keeps the file's inode and size; a file that shrank or was
  replaced is read again from the start, and the run says `rewritten`.

## Consequences

- **Positive:** a bad file or record costs one run, visibly; the service always starts; a replaced
  run shows its new content.
- **Negative:** checking every record costs time on load (small next to JSON parsing).

## Alternatives considered

- **Fail fast on any bad record.** Right for a writer's own tests, wrong for a viewer that must show
  the other ninety-nine runs.
- **Repair bad records on the fly.** Guessing hides writer bugs; skipping and counting shows them.
