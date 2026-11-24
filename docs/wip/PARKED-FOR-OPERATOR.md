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
| B6 | The real duck's safety review before a real run | the adapter is built; [the checklist](REAL-DUCK-SAFETY-REVIEW.md) is written, none of it done |
| B9 | Measurement scripts run on the real duck | scripts only |

## Needs a decision or a review

| Item | What | Done meanwhile |
| --- | --- | --- |
| D0 | Review the NXT design note (second host kind, sensor declaration, stand-in profile) | D2 onwards built on its defaults |
| ~~Telemetry (5)~~ | Settled 2026-11-23: you approved the `robotics-lab` Grafana folder in the homelab session; service account `robotics-lab-sync` (Edit on that folder only), token in `~/grafana/robotics-lab-sync.env` on the mini, read over ssh, never printed | sending needs no token: OTLP over protobuf to the tailnet nodes (agent-access.md §5) |
| D0 defaults | [NXT-D0.md](NXT-D0.md) §5 lists 12 defaults; two worth a look: the NXT's sensors sat in `capabilities.sensors`, not the profile's `sensors` block (6; moved into the block 2026-11-24, E4); and whether D0 becomes an ADR as RFC-0028's starting point (12) | D3 onwards built on them |
| B3 second opinion | Arm the robot-side guardrails (fall, contact, drop) also when a truth exists, as a second opinion? Today: only without truth | built: only without truth |
| B3 alarm | Add a `robot_guard` anomaly kind so a robot-side fall or contact reaches the alarm feed as critical? Today it ends the goal `stopped_by_guardrail` but the alarm feed does not show it | not added |
| B7 frame | A start pose you place on the map lasts one goal. Keep it until the robot is carried again instead? (Needs a clear control and a rule for stale placements.) | built: per goal |
| B7 dock | The first start pose a site sees becomes its dock pose when it has none. Right? | built that way |
| B8 defaults | Simulator-first: opt-in per goal; a rehearsal counts for 24 h, same goal content, same site, a sim robot of the same kind. `rtf_low` below 0.95, minor. Right numbers? Should `sim_first` be the default for every goal on a real robot? | built as listed |
| B3 numbers | `fall_tilt_deg` 45 and `fall_s` 0.5 are proposals; measure on the real duck (with B9) | in the profile, marked unmeasured |

## Asked after the answers (2026-11-24)

| Item | What | Done meanwhile |
| --- | --- | --- |
| Retention: official | A run record has no "official" marker. Proposal: official = the record has `judge_truth` or `judge_profile` (the runner's truth copy writes them). Explore runs, NXT recordings and imported runs are not verified under it ([the design](TELEMETRY-RETENTION-DESIGN.md)) | `observatory archive` built on the proposal, a dry run by default; not run on the real data folder |
| Prod on the X3 | A Docker engine of its own for prod; [the proposal](PROD-ON-X3.md) recommends a second rootful `dockerd` (host network only, iptables off), set up by your one sudo step; the homelab session is reviewing it | the real redeploy held; the stack still runs `36670fb` from `/work` |
| Backups (homelab's plan) | State (97 MB, holds tokens): age-encrypted nightly to `chipi/homelab-backup`, as the mini's, no new cost. Data (1.9 GB, growing): B1 restic to an off-site store (a new account, a few euros a month), or B2 rsync to the mini (same house). Data and archive together; the archive move after the night's backup | nothing set up |
| Retention: first apply | Run `observatory archive` on the real data folder (moves whole run folders to `<data>-archive/`, deletes nothing) | the dry run only |

## The operator's answers (2026-11-24)

The operator decided every item in the table above, and the ones in the link and findings lists
that needed a decision. The work each answer creates is the "follow-ups" unit set in
[PHASE5-NEXT-PLAN.md](PHASE5-NEXT-PLAN.md) (item 4e).

| Item | Answer |
| --- | --- |
| B8 sim-first | On by default for goals on a real robot, opt out per goal |
| B8 numbers | 24 h and 0.95, as built |
| B3 second opinion | The robot-side guardrails also run when a truth exists, recording only (the referee still judges) |
| B3 alarm | A robot-side stop raises a critical `robot_guard` alarm |
| B7 frame | A placement lasts one goal, as built |
| B7 dock | Kept, and the site page says the dock was set from the first placed start |
| D0 sensors | Generalise the profile's `sensors` block now, for both robots (not `capabilities.sensors`) |
| D0 ADR | No ADR; RFC-0028 starts from NXT-D0.md |
| B6 hand drive | Behind `allow_real_runs` too; STOP never is |
| B5 gate restart | `lab-link up --gate` restarts the gate once the forwards are back |
| D7 takeover | A `takeover_names` key in the NXT host file, passed to nxt-web |
| Simulator lock | `fcntl.flock` on the same file is acceptable; a repo `sim-lock` helper for every job |
| NXT turn rate | Wait for D1's measurement, then fix the wrong side (D9) |
| Duck motion | One investigation unit now: turning in place, the two speed figures, the placed-start stall |
| Link check | Moved into `libs/runfile`, one copy for `lab-link` and Mission Control |

## For the real duck's link (B5, `lab-link`, recipe in [REAL-DUCK-LINK.md](REAL-DUCK-LINK.md))

- Confirm the duck's ssh address, key and sshd; `microduck@duck` comes from RFC-0002.
- `lab-gate` does not reconnect: after a dropped link it exits. `lab-link up --restart-gate`
  starts it again once the forwards answer (E6, 2026-11-24).
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
- ~~Duck walk speed: two numbers disagree~~ Explained 2026-11-24 (E10, KNOWN-ISSUES K49): B9's
  0.36 was a wall 0.55 m ahead in the default scene; the sheet's 0.55 summed the pose's sway; the
  duck walks about 0.47 of the asked speed over the ground. Both tools fixed.
- **The NXT's turn rate disagrees between Mission Control and the simulator** (D7): Mission
  Control maps 1.5 rad/s to track powers of plus or minus 50 %, the simulated world reads its
  1.5 rad/s as 100 %, so a 1 rad/s turn turns about 0.46 rad in a second. D1's K16 measurement
  decides which side is right; then one side is fixed.
- ~~simhost cannot pass nxt-web's takeover list~~ Settled 2026-11-24 (E7): a `takeover_names` key
  in the NXT host file, passed to nxt-web; `make sim-nxt` no longer starts its own.
- ~~A subagent took the simulator lock through `fcntl.flock`~~ Settled 2026-11-24 (E8): accepted,
  and `scripts/sim-lock` takes it the same way for every simulator job.
- ~~An intermittent `test_recorder_sim` failure~~ Fixed 2026-11-24: a record start that landed
  between a sample's truth read and its write gave the run a first tick without a truth, so the
  epoch came after it. That sample now goes to the next recording only; an in-process check
  reproduces the race.
- **A page-test flake under load** (`test_page`, "event stream is live"): seen once at a load of
  60 to 70 during B8, passed on re-run. Not diagnosed.
- **A `test_duck_real` flake** (E5): once in about nine runs the last check found no `run` in the
  answer. Unverified guess: the held robot was still offline after the gate restart. The test
  now waits for it to be online and prints the whole answer; 3 of 3 passed since, which does not
  prove it gone.
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
- **The standing duck does not turn on `vx` 0 with `vyaw` under about 1.0 to 1.1 rad/s** (E10,
  KNOWN-ISSUES K48): the simulator's walking network, not ours. Open and needs an owner of
  `robots.py` / `duck.py`: Mission Control's `POST /robots/{id}/drive` should refuse that command
  with the reason (the floor is the profile's `locomotion.stand_turn.min_rad_s`, 1.1).
- **The duck walks about 0.47 of the commanded speed over the ground:** a 5 s walk at 0.3 m/s
  covers 0.65 m (the slow first second in it). The calibration's `by_speed` row is keyed by the
  commanded speed (K49).
- **Calibration walks blind** (A3): no wall, cliff or contact check. On the real duck it needs a
  clear floor and B6's safety review.
