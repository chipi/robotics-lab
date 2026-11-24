# The real duck: backlog

Everything that waits for the real Microduck. The operator expects it in one to two months
(said 2026-11-24) and says when it is here; until then this list is not raised. Each item says
what it needs and where its preparation is.

## Before the first real run

| Item | What | Prepared |
| --- | --- | --- |
| B6 safety review | Go through [the checklist](REAL-DUCK-SAFETY-REVIEW.md) at the robot; only then set `allow_real_runs: true` in `apps/mission-control/robots.real/duck-real.json` | the adapter refuses real runs, calibration walks and hand drive until then; STOP never refused |
| The link | `lab-link up --restart-gate`: the duck's ssh address, key and sshd (`microduck@duck` from RFC-0002); whether the real robotd accepts the link's second connection for `robot.health` | [REAL-DUCK-LINK.md](REAL-DUCK-LINK.md); the link check is `runfile.linkcheck` |
| robotd's deadman | Check that robotd's own 0.5 s deadman stops the duck when the link drops (the only backstop: a dropped link does not stop it otherwise) | not verified on the real duck |
| mapd's `bumped` | How often the real mapd reports `bumped` or `carried` falsely; a false one stops a goal (B3) | unknown |

## Measurements (B9)

| Item | What | Prepared |
| --- | --- | --- |
| Walk speed | The walk gain against the commanded speed on a tape, at 0.2, 0.3 and 0.4 m/s (the simulator gives about 0.47 of commanded, net, at 0.3) | `lab-measure-walk`, `lab-score-sheet`; K49 |
| Turn floor | The slowest turn on the spot that starts from a stand (the simulator's is about 1.1 rad/s; `locomotion.stand_turn.min_rad_s`) | `lab-measure-walk`, the probe `robots/duck/sim/probes/drive_response.py`; K48 |
| Fall thresholds | `fall_tilt_deg` 45 and `fall_s` 0.5 are proposals; measure tilt in normal walking and in a fall | in the profile, marked unmeasured |
| Range sensor | The ToF's real range and noise (`lab-measure-range`) | the script |
| CPU | The Pi's load with the navigator on board (`lab-measure-cpu`) | the script |
| Odometry | The calibration walk's `by_speed` rows on the real floor (A3), on a clear floor only: it walks blind | calibration in Mission Control; `sim_first` on by default |

## The first real goals

1. A point goal with simulator-first on: the rehearsal on the same site, then the real run.
2. A placed start and the dock: the first placed start sets the site's dock.
3. A guardrail: on a real robot with no truth, the robot-side guards enforce; check a fall
   or contact stop raises the critical `robot_guard` alarm.

## Not covered

- What the real duck needs that the simulator never showed: these are found at the robot.
- The real variant's profile numbers: they come from the measurements above.
