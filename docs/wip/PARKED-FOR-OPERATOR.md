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
| ~~Telemetry (5)~~ | Settled 2026-11-23: you approved the `robotics-lab` Grafana folder in the homelab session; service account `robotics-lab-sync` (Edit on that folder only), token in `~/grafana/robotics-lab-sync.env` on the mini, read over ssh, never printed | sending needs no token: OTLP over protobuf to the tailnet nodes (agent-access.md §5) |
| D0 defaults | [NXT-D0.md](NXT-D0.md) §5 lists 12 defaults; two worth a look: the NXT's sensors sit in `capabilities.sensors`, not the profile's `sensors` block (6); and whether D0 becomes an ADR as RFC-0028's starting point (12) | D3 onwards built on them |
| B3 second opinion | Arm the robot-side guardrails (fall, contact, drop) also when a truth exists, as a second opinion? Today: only without truth | built: only without truth |
| B3 alarm | Add a `robot_guard` anomaly kind so a robot-side fall or contact reaches the alarm feed as critical? Today it ends the goal `stopped_by_guardrail` but the alarm feed does not show it | not added |
| B7 frame | A start pose you place on the map lasts one goal. Keep it until the robot is carried again instead? (Needs a clear control and a rule for stale placements.) | built: per goal |
| B7 dock | The first start pose a site sees becomes its dock pose when it has none. Right? | built that way |
| B8 defaults | Simulator-first: opt-in per goal; a rehearsal counts for 24 h, same goal content, same site, a sim robot of the same kind. `rtf_low` below 0.95, minor. Right numbers? Should `sim_first` be the default for every goal on a real robot? | built as listed |
| B3 numbers | `fall_tilt_deg` 45 and `fall_s` 0.5 are proposals; measure on the real duck (with B9) | in the profile, marked unmeasured |

## For the real duck's link (B5, `lab-link`, recipe in [REAL-DUCK-LINK.md](REAL-DUCK-LINK.md))

- Confirm the duck's ssh address, key and sshd; `microduck@duck` comes from RFC-0002.
- `lab-gate` does not reconnect: after a dropped link it exits and is restarted once `lab-link`
  says `up`. A hook that restarts it is not built (a scope decision).
- The link polls `robot.health` every 2 s on its own connection; if the real robotd refuses a
  second connection beside the gate's, the check says DEAD on a working link.
- A dropped link does not stop the robot; robotd's own 0.5 s deadman is the backstop, not
  verified on the real duck.

## Findings to know about

- **An installation that registers both robots** makes `labrunner.robots.get()` ask for
  `--robot`; and `lab-go --robot nxt-shooterbot` would fail on the NXT's missing navigator API
  (`navapi.py:209`, `remote.py:150`) instead of refusing clearly. A small fix, due with D7.
- ~~`sim_duck` in one full run fails `calibrate` after `profile`~~ Fixed 2026-11-24: the check
  takes the version the keep reports, and the corridor setup ends with a short goal north (a
  point goal does not choose its final heading; it had ended at 126 degrees twice).
  `--only profile,calibrate` gave `PASS sim_duck`, EXIT=0.
- **Duck walk speed: two numbers disagree.** Old challenge runs show 0.55 of the commanded
  speed; fresh simulator walks 0.36 (B9). Not explained.
- **The NXT's turn rate disagrees between Mission Control and the simulator** (D7): Mission
  Control maps 1.5 rad/s to track powers of plus or minus 50 %, the simulated world reads its
  1.5 rad/s as 100 %, so a 1 rad/s turn turns about 0.46 rad in a second. D1's K16 measurement
  decides which side is right; then one side is fixed.
- **simhost cannot pass nxt-web's takeover list** (D7): on the nxt-web that simhost starts nobody
  may take the lock; `make sim-nxt` starts a second nxt-web itself to test takeover. A host-file
  key for the list would remove that.
- **A subagent could not run `flock(1)`** (the shell's deny list) and took the same simulator lock
  through Python's `fcntl.flock` on the same file. Same lock, same semantics; say if that is not
  acceptable.
- **The NXT's battery percent is a guess:** a linear span from 6000 mV (0 %) to 8400 mV (100 %),
  low below 20 % (D5); D1 can calibrate it. A robot file overrides the span.

- **B3's fall and contact are proven only by stubs:** the sim duck neither tilts past 45 degrees
  nor reports `bumped` or `carried` on demand. Only drop clearance has a simulator proof. A false
  `bumped` from mapd on the real duck would stop a goal; how often mapd says it is unknown.
- **A flake in the A3 tape-calibration setup** (`sim_duck --no-truth`): "the duck stands in the
  corridor facing north" failed once (yaw 137 degrees against 35 tolerance), passed on re-run.
  Not diagnosed; related to the duck not turning in place (below), not verified.

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
