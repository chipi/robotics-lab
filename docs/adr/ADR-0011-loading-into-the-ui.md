# ADR-0011 — Loading a run into the UI: by window, then by record

**Status:** Accepted (2026-11-15, by the operator)
**Date:** 2026-11-15
**Context documents:** [RFC-0010](../rfc/RFC-0010-run-store-v2.md) §3, [ADR-0010](ADR-0010-api-2.md),
[the miniview review](../wip/REVIEW-2026-11-15-miniview.md) findings 2, 7, 8

## Context

The page loads a whole run before drawing; while a run is live it re-downloads the whole run every
second and rebuilds both renderers, ignoring the records the live stream sends. The agent's
interface loads a different run without saying so when a name is wrong, undoes a script's
`setTime` within a second while following, and does not say which run `state()` describes. Event
kinds from the file go into a regular expression unescaped. The fonts come from Google on every
load.

## Decision

- **A run store in the page**, shared by both renderers: the run's summary first; then the ticks of
  the window around the playhead (±30 s) so the page draws at once; then the rest of the run in
  windows in the background. Plans and maps arrive inside the window answer, by index, those the
  window's ticks refer to (there is no separate fetch for them).
- **Live by record:** the page applies the records of the live stream in order. It checks `seq`; a
  gap reloads from the last seq it has. Renderers take appends (`append(records)`) instead of
  rebuilding; an epoch change redraws what depends on it.
- **Follow live is a mode:** it pins the playhead to the newest tick; any change of time, by hand
  or by script, turns it off.
- **The agent's interface:** `load(scene, run)` fails with an error on an unknown scene or run;
  `state()` returns the run key, status, seq and follow mode; what the tests need is in the
  interface, and `internals` is documented as for tests only.
- **Nothing from a file is used as code or a pattern** (event kinds are compared as text).
- **The fonts are served by the service** (Inter and JetBrains Mono, open licence, as files).

## Consequences

- **Positive:** a long run draws at once; a live page costs what the run adds; scripts are not
  overridden; a wrong name is an error, not a different picture; the pages work offline.
- **Negative:** the renderers change to accept appends, both of them.

## Alternatives considered

- **Load the whole run, live by re-fetch** (today): simple, does not scale.
- **The page reads MCAP itself.** Every page would repeat the reading logic (against ADR-0005).
