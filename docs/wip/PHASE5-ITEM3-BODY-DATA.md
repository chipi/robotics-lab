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
