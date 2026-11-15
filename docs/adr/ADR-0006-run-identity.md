# ADR-0006 — A run is `robot/scene/run`, and says who it is

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3,
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) finding 4

## Context

A run is known by its folder's name. Two robots or two scenes with a run called `run-001` collide:
the listing shows one, the data served is the other. A run whose record names it differently from
its folder is listed but cannot be opened. The scenario runner (RFC-0008) will name runs per
scenario, so collisions are expected, not rare.

## Decision

- **A run's key is its place:** `runs/<robot>/<scene>/<run>/` → `robot/scene/run`. Each part is
  lower case letters, digits, `-` and `_` only; anything else is refused by the writer.
- The API addresses a run by its key (`/api/v1/runs/<robot>/<scene>/<run>`). The commands take
  the key, or a short name when exactly one run has it; otherwise they list the candidates.
- **The first record says who the run is** (`run`, format 2): the key, a `uuid` (new for every
  run, kept on re-import of the same source), the robot (name, radius, height), the scene, the kind,
  `started_at_ns` (UTC wall clock; for an import from a log without one, the source file's
  modification time, with `started_at_source: "file_mtime"`), the `writer` (program and version),
  and for an import the source file's name and SHA-256.
- A run whose `run` record disagrees with its folder is **broken** (ADR-0008), never listed under
  a second name.

## Consequences

- **Positive:** names can repeat across robots and scenes; a run can be traced to its source; runs
  sort by when they happened, not by file times.
- **Negative:** URLs and commands get longer; the pages and tests change from a bare name.

## Alternatives considered

- **The uuid as the key.** Unique, but unreadable in URLs, commands and pictures' captions.
- **Bare names, unique across the lab.** Every writer would need to know every other run's name.
