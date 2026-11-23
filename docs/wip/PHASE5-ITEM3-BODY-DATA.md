# Phase 5 item 3: what the body data is today

**Status:** written 2026-11-23, overnight. It is the read-only first check of
[RFC-0023](../rfc/RFC-0023-the-views.md) §7 step 2: "the simulator's bridge carries velocities and
currents; which of them reach our state stream is checked first". Nothing was changed or run. The
operator decides what to build from it.

Paths: P is the Pollen tree (`/work/pollen/microduck`), M is this repository.

## The answer

The joints' velocities and currents reach our state stream. The commanded angles do too. None of
the three is read or recorded today; a run keeps only the measured angle.

| Per joint | The simulator sends | robotd's `robot.state` | Our side reads | A run records |
| --- | --- | --- | --- | --- |
| Measured angle | `positions`, rad | `joints` | the navigator (`nav/run.py`) | yes, `joint_<name>` signals, rad (`nav/runlog.py`) |
| Commanded angle | (robotd writes it to the simulator) | `targets` | no | no |
| Velocity | `velocities`, rad/s | `velocities`; an empty list is "not reported" | no | no |
| Current | `currents_ma`, mA (optional on the wire) | `currents_ma`, magnitude only; empty is "not reported" | no | no |
| Temperature | `temps_c`, on the slow read | no: only `robot.health`'s `motors{hottest, max_c, mean_c}` | no | no |
| Torque or load | none (`currents_ma` is the only load measure) | no | no | no |

- **The gate passes the state message on whole** (`libs/runner/src/labrunner/gate.py`, the relay
  sends each subscriber `msg` as it came, at that subscriber's own rate). Nothing is dropped on the
  way; our readers take what they need.
- **`duck-record` keeps the whole message** (`robots/duck/src/duck_lab/record.py`, `/duck/state` in
  its MCAP), so the old recordings have velocities and currents. The run file (format 2) does not:
  its signals are the IMU's, the navigator's and the 15 joint angles.

## Robot-wide health

The state stream has no battery and no health. robotd's design doc shows `battery` in the state
frame; its `RobotState` struct (P `duck-ipc-proto/src/lib.rs`) has none. Health is a separate call,
`robot.health`, with:

- `healthy`, `degraded`, `reason`;
- `battery{volts, percent}`, `motors{hottest, max_c, mean_c}`, `cpu_temp_c`, `cpu_throttle`;
- `control_loop{target_hz, achieved_hz, ticks, missed, last_tick_age_ms}`;
- `bus{consecutive_errors, startup_failures, missing[]}`, `imu{ready, stale_blocks, stale_run, ...}`.

Mission Control polls it every 10 s (`HEALTH_EVERY_S`, `mission_control/duck.py`) and keeps only
`battery.percent`. On the stream it reads `safety{fallen, picked_up, limp}`; `loop{hz, missed}` and
`move.limited_by` are on the stream and not read.

## What to know before building step 2

- **The simulator's current is a stand-in:** the body server sends `abs(actuator_force) * 100` as
  `currents_ma`, "not calibrated against a real servo" (P_rl
  `mjlab_microduck/sim/body_server.py`). Limits learned from it are the simulator's, as K37 says of
  the anomalies.
- **The simulator's health is constant:** 7.4 V and 32 °C for every joint, so battery and
  temperature alarms cannot be exercised in the simulator. The battery percent is constant too; its
  value (about 50 %) is inferred from the design doc's 6.6 to 8.2 V span, not read.
- **The current has no sign:** a push and a pull look the same.
- **An empty list has three causes the wire does not tell apart:** an older robotd, a backend with
  nothing to measure, or `publish_velocity_and_load=false` (default true). Recording "not reported"
  as an empty list, never zero, is what RFC-0023 already asks.
- **Size:** at the navigator's 20 Hz, three more lists of 15 numbers is 900 values a second, against
  the 300 the angles take now.

## The choices for the operator

1. **Where the three lists go in a run.** As signals (`joint_<name>_target`, `_vel`, `_ma`: 45 more
   named signals, every reader understands them today), or as one per-joint record of its own (smaller,
   one row per tick, but the readers have to learn it). The plan's line "Needs the recording to
   keep the three per-joint values it drops today" (`EXECUTION-PLAN.md`) does not say which.
2. **Health in the run:** poll `robot.health` during a run (at the 15 s the telemetry step allows,
   RFC-0023 §7 step 6) and keep it as a record, or keep only what the stream has (`loop`,
   `safety`).
3. **Temperature per joint:** robotd does not stream it. Asking Pollen for it is an upstream request;
   without it, the alarm feed (step 3) has the hottest servo only.

Not read: `ImuHealth` and `CpuThrottle` past their first fields; how the vetbook (wear, trips) is
exposed; the `ticks.jsonl` rows beyond the signal list.

## Decided (the operator, 2026-11-23), and built

1. **1A, signals:** `joint_<name>_target` (rad), `_vel` (rad/s) and `_ma` (mA) beside the angles. A
   list of the wrong length, an empty list or a value that is not a number is left out (absent, never
   zero).
2. **2B, both:** the state stream's loop rate and misses, safety flags (0/1) and movement limits (text)
   on every tick; `robot.health` polled every 10 s on its own connection as signals (verdict, battery,
   hottest servo, CPU, loop, bus), and a `robot_health` event when the verdict changes or after a
   failed ask.
3. **Pollen is not asked:** they are an independent company. The hottest servo (`motor_hottest`,
   `motor_max_c`, `motor_mean_c`) is the only temperature.

Code: `duck_lab/nav/body.py`, used by `nav/run.py` and declared in `nav/runlog.py`; tests in
`robots/duck/tests/test_body.py` (in `DUCK_TESTS`), 8 of 8 mutants killed.

**Proof on the simulator** (this checkout's navigator as `--payload`, seed 1): challenge 1 passes,
648 of 652 signal ticks carry the body values, health asked 4 times 10.0 s apart (7.4 V, 50 %, loop
50.08 Hz), one `robot_health` event. Challenge 22: one run failed (coverage 0.755, ended
`no_frontier_left`, with 35 `fix_jump_held` and a `frames_parted`, the localisation mode
`PHASE3-PREP.md` records). Then three runs a side, alternating with main's navigator, all passed:
before 0.895, 0.950, 0.888; after 0.956, 0.958, 0.848. The signal ticks' spacing is the same on both
sides (median 60 ms, p95 61-62 ms). Not covered: three runs a side cannot see a small change in the
pass rate; the body values in those six runs were not re-checked (challenge 1's were); a run is about
5 % larger.

## Step 3, part 1: the body's anomalies (2026-11-23)

The operator: limits in the profile, for the simulator and the real duck both. `joints.limits` in
`robots/duck/profile.json`, read by `body.BodyWatch` (`duck_lab/nav/body.py`) in the navigator:

| Anomaly | Raised when | Real duck | Simulator |
| --- | --- | --- | --- |
| `joint_overload` (major) | a joint's current at or over `current_ma` for `current_s` | 900 mA, 1 s | 120, 1 s |
| `joint_tracking` (major) | commanded angle less angle over `tracking_rad` for `tracking_s` | not checked (null) | 0.5 rad, 1 s |
| `loop_slow` (minor) | the state's loop rate under `loop_min_hz` for `loop_slow_s` | 45 Hz, 2 s | the same |
| `motor_hot` (major) | the hottest servo at or over `hot_c` (each health answer) | 60 C | the same (never fires: 32 C constant) |
| `robot_unhealthy` | robotd's verdict, when it changes: major not healthy, minor degraded | | |

The real duck's numbers are Pollen's (`duck-control/src/model.rs` `CURRENT_LIMIT_MA` 1000,
`duck-ipc-proto/src/vetbook.rs` `HOT_C` 60, the XL330's shutdown at 70 C); no tracking number
exists there, so it is null until `sim/probes/body_limits.py` measures a real run, and every run's
`body_watch` event says what is not checked. The hold times are proposed, not measured.

**Proof:** `tests/test_body.py` (the watch, both variants of the profile, the navigator raising
through the state stream and the health thread), 9 of 9 mutants killed; `make ci-fast` PASS. On
the simulator (seed 1, this navigator as `--payload`): challenges 1-11, 21 and 22 once each, every
run with its `body_watch` event and no anomaly of any kind; challenges 1-11 the same verdicts as
item 2's batch (6 and 7 refused there too). Challenge 21 failed once by a hair (goal 9 said reached
0.25 m from it); then 21 and 6 three times a side, alternating with main's navigator: 21 before 2
of 3 (one stalled on goal 9), after 3 of 3; 6 before 0 of 3, after 2 of 3 (K40). **Not covered:** no
run raised a body anomaly live, so the raise is proven by the unit tests only; the real duck's
limits have not met a real run.
