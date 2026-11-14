# Review of the duck RFCs (2026-11-14)

An independent, read-only review of [RFC-0002](../rfc/RFC-0002-robot-brain.md),
[RFC-0004](../rfc/RFC-0004-perception-and-planning.md) and
[RFC-0005](../rfc/RFC-0005-missions.md) (and RFC-0003 where it touches the duck), asked for by the
operator and run by the `advisor` agent on Fable 5. Claims were checked against upstream at
`microduck` `094d4bb4` (API v61), `microduck_rl` `0daab160`, eval-harness `bc2286392`, flotilla
`299ac86`. The robotics-lab session re-checked the two blockers and the turn range in the source.

## Verdict (reviewer)

The layering is right and matches upstream's own `autod`. As written, the plan could not pass its
own phases: the simulated apartment has no table a 25 cm duck fits under, and `mapd` does not map
while the duck's autonomy is off under the default config. Two speed limits were wrong. "Shadow =
run on the simulator" contradicted flotilla's ADR-0008.

## Findings and what was done

| # | Finding | Decision / change |
| --- | --- | --- |
| B1 | No kitchen table to hide under in the sim (`apartment.xml`: island solid to 0.40 m; the coffee table's top at 0.14–0.22 m) | Operator: drop the table. Missions take an end option: A landmark (coat rack in the hall, 1 m), B back to start, C doorway of the largest room. RFC-0002 §1, RFC-0004 §2.1 |
| B2 | `mapd` maps only while `autod` runs unless `[map] enabled = true` (`mapd/src/main.rs:85–100`) | Phase 0 enables it and starts `mapd`; two modes (auto / brain) with one switch. RFC-0002 §3.1, §3.5 |
| M1 | Turn limit ≤ 1.0 rad/s (trained range), forward floor 0.15 m/s, not 0.12 | Fixed. RFC-0002 §2 |
| M2 | Shadow already means "recorded, nothing done" in flotilla | Operator agreed: the simulated duck is a second host at `auto`; rehearsal precedes every real run. RFC-0005 §2.2 |
| M3 | The sim does not predict real motion (44 % speed, turning failed locally) | Navigator closes the loop on measured odometry; phase 0 is a spike that checks turning; rehearsal's limits stated. RFC-0002 §3.4, RFC-0005 §2.2 |
| M4 | ssh-forwarded sockets are upstream's documented dev path | Default link for the real duck. RFC-0002 §3.3 |
| M5 | Unhandled failures: autonomy switched on mid-run, shared client names, reconnects, getting lost, falls | A table of rules. RFC-0002 §3.6 |
| M6 | Local models in robotics mode take prod down | Operator: dismissed — a playground; prod only matters at night. RFC-0004 §5 |
| m1 | `map.wipe` exists | "The brain never calls `map.wipe`". RFC-0002 §2 |
| m2 | `/frame` is served on the robot too | Camera on the LAN via `/frame` in both. RFC-0002 §2 |
| m3 | `autod` also yields to an external soccer game | Noted. RFC-0002 §2 |
| m4 | "Done when" oracles missing | Collisions from MuJoCo contacts, a room-area tolerance, ≥ 10 starts per arm. RFC-0002 §3.4 |
| m5 | eval-harness `--build-ref` is one string; a run is three versions | `brain@<commit>+model@<alias>+policies@<set>`. RFC-0005 §2.4 |
| nits | VL53L8CX name; flotilla host agent "planned, skeleton started"; ADR-0006's argv-template executions fit a long-lived navigator poorly | Applied in RFC-0002 §2 and RFC-0005 §2.5, §4 |

New from the session while applying it: the corridor has a **staircase hole** (`apartment.xml`
lines 95–114) — a cliff on the way to the hall; the navigator stops when the floor disappears in
the depth sensor's lower rows (RFC-0002 §3.6).

## Riskiest assumption and the spike (reviewer)

That the simulated duck is a faithful stand-in. Spike, before anything else: make turning match
upstream's measurement in the backlash scene; port the backlash robot into the apartment; run
`mapd` with `[map] enabled = true` and check the map gains keyframes with `robot.autonomous` off.
If it fails, the navigator phases are blocked and the rehearsal idea is revisited. This is now
phase 0 of RFC-0002.

## Not verified by the reviewer

- The LiteLLM aliases, budgets and DGX details (homelab, out of scope).
- Whether the simulated depth sensor sees the apartment's furniture.
- The real robot's command-to-measured speed.
- Whether `mapd` counts a zero twist as "no twist asked for" when deciding a stop.
- The cause of the local turning mismatch.
