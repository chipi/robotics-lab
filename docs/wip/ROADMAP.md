# Roadmap

Order of work as of 2026-11-14. Each item points at where it is designed. Dates are not set.

## Now

1. **NXT safety:** stop on connect and the shooter lockout (done 2026-11-14); **robotd-lite**, the
   deadman on the brick ([RFC-0003](../rfc/RFC-0003-robot-interface.md) §2.3–2.4) — built
   2026-11-14, checked against the simulated brick; next: `make test-hardware` on the brick.
2. **Robot brain phase 0, the spike** — run 2026-11-14 ([PHASE0-SPIKE.md](PHASE0-SPIKE.md)): turning
   misses its bar, the rest passes; the operator decides how phase 1 goes on. Was: turning in
   the backlash scene, the backlash robot in the apartment, `mapd` mapping with autonomy off.
3. **DGX full training run** — started 2026-11-14 12:36Z (4000 iterations, 210 min cap).

## Next

1. Robot brain phases 1–4 in simulation: navigator, exploring and rooms, perception, missions in
   words ([RFC-0002](../rfc/RFC-0002-robot-brain.md), [RFC-0004](../rfc/RFC-0004-perception-and-planning.md)).
2. **Mission control** from the start: the dev page, an MCP server, a Slack app, over the brain's
   API ([RFC-0006](../rfc/RFC-0006-mission-control.md)).
3. The robot interface (JSON-RPC) for the NXT, under `nxt-web` ([RFC-0003](../rfc/RFC-0003-robot-interface.md)).
4. Run records in MCAP; Foxglove ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).

## When the Microduck arrives

1. Phase 5: the real duck over ssh-forwarded sockets; `mapd`'s CPU cost; the first simulator-vs-real
   comparison (the 2 m sprint) ([RFC-0005](../rfc/RFC-0005-missions.md)).

## The platform (RFC-0007)

1. MCAP recording from mission control (`nxt-web` first).
2. Viewer spike: Rerun vs Lichtblick on one NXT run and one simulated duck run.
3. A minimal logbook: a folder, an index, search, events.
4. eval-harness reads runs from the logbook; flotilla cases reference recordings.

## Later

1. **The navigator moves onto the robot** (operator, 2026-11-14): onto the duck; for the NXT, onto a
   Raspberry Pi riding on the brick ([RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.9).
2. **Robots working together** — phase 6: a shared map and common frame, shared objects, missions
    across robots. The brain already oversees several missions at once; working together needs these
    new concepts first ([RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.10).
3. flotilla integration: missions as cases, robot hosts, rehearsal on `duck-sim`
    ([FLOTILLA-ASKS.md](FLOTILLA-ASKS.md), assessment deferred by the operator until flotilla's
    planned work is done, 2026-11-14).
4. eval-harness 0.9 capabilities for sim vs real ([EVAL-HARNESS-ASKS.md](EVAL-HARNESS-ASKS.md),
    assessment after eval-harness 0.8.0 is finished, by the operator's decision, 2026-11-14).
5. Bigger NXT robots: the arm robot on two bricks ([IDEAS.md](IDEAS.md), RFC-0003 §2.5).
6. Mission control split out as its own open-source product ([RFC-0006](../rfc/RFC-0006-mission-control.md)).
