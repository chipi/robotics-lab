# Parked for the operator

Items that need the operator, collected while the two MVP 1 streams run on their own (the
operator stepped out on 2026-11-23). Each says what is needed and what was done instead.
Cleared items are struck from the list when settled.

## Standing grants for this stretch (the operator, 2026-11-23)

- Pushes to main for 4a, 4b, 4c and 4d checkpoints: each rebased, secrets-scanned, gated locally,
  CI watched and fixed if red.
- The robotics-lab stack may be redeployed in 4c only after a private test stack passes its
  smoke; a failed smoke on the real deploy rolls back to the commit deployed before.
- The NXT stream proceeds on D0's defaults; the operator reviews D0 on return.

## Needs the operator at the robot

| Item | What | Prepared |
| --- | --- | --- |
| D1 | NXT hardware check at the brick: `hw_*` scripts, K15, K16, sprocket and track width, the 15 cm stop | checklist and scripts, when written |
| D9 | One real and one simulated NXT run of the same command list | after D1 |
| D10 | NXT over Bluetooth; first check that the brick stops by itself when the link drops | after D1 |
| B6 | The real duck's safety review before a real run | adapter code only |
| B9 | Measurement scripts run on the real duck | scripts only |

## Needs a decision or a review

| Item | What | Done meanwhile |
| --- | --- | --- |
| D0 | Review the NXT design note (second host kind, sensor declaration, stand-in profile) | D2 onwards built on its defaults |
| Telemetry (5) | The robotics-lab Grafana folder's token and tailnet access from the homelab session | not started |
| D0 defaults | [NXT-D0.md](NXT-D0.md) §5 lists 12 defaults; two worth a look: the NXT's sensors sit in `capabilities.sensors`, not the profile's `sensors` block (6); and whether D0 becomes an ADR as RFC-0028's starting point (12) | D3 onwards built on them |

## Findings to know about

- **The NXT over Bluetooth stops by itself only under robotd-lite.** From `robotd.nxc` (read, not
  run): while robotd-lite runs on the brick it stops the tracks 0.5 s after the last command;
  stock firmware and direct drive mode have no brick-side stop. So D10 drives over Bluetooth
  only with robotd-lite running; the D1 checklist has the checks.
- **The standing duck did not turn in the simulator** on `POST /robots/{id}/drive` with `vx` 0 and
  `vyaw` 0.5 to 0.8 (A3's run, not investigated).
- **The duck walks slower than commanded:** a 5 s walk at 0.3 m/s covered about 0.66 m by the
  truth, about 0.13 m/s. The calibration's `by_speed` row is keyed by the commanded speed.
- **Calibration walks blind** (A3): no wall, cliff or contact check. On the real duck it needs a
  clear floor and B6's safety review.
