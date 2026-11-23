# Measuring on the real duck: four scripts

**Status:** written 2026-11-23 for plan unit B9. The scripts are proven against the simulator and
against stand-ins only; none has touched the real duck. [When the real duck arrives](REAL-DUCK.md)
says what to find out and why; this page says how, with the scripts. Every output is a plain
table, or JSON with `--json`, to paste into the profile's `measured` line
(`robots/duck/profile.json`, `variants.real`).

All four are in `libs/runner` (`labrunner.measure_*`), standard library plus the runner's own
libraries, no new dependency. Run them from `libs/runner` with `uv run`.

| Script | Question | Moves the robot | Needs |
| --- | --- | --- | --- |
| `lab-measure-cpu` | What do mapd, robotd and tofd cost the board's processor? | no | to run on the duck |
| `lab-measure-range` | Does the depth sensor report range radial or axial? | no | the depth forward, a flat board |
| `lab-measure-walk` | How fast does it walk against the speed asked; the odometry's scale by tape | yes | the gate, a lease, `--real` |
| `lab-score-sheet` | The simulator's runs and the real duck's, side by side | no | recorded runs |

## First, the link

Bring `lab-link up` up as in [the link recipe](REAL-DUCK-LINK.md) and confirm `lab-link check`
says `link PASS`. The forwarded sockets are in `~/.cache/duck-real/`: `duck.sock` (robotd),
`duck-tof.sock` (depth), `duck-map.sock` (mapd), and the gate you start on them,
`duck-gate.sock`. Only the walk goes through the gate; the others read.

## 1. mapd's CPU cost (`lab-measure-cpu`)

A forwarded socket says nothing about the board's processor, so this one runs on the duck. It is
one file with no imports beyond the standard library; send it over ssh to the duck's python:

```bash
ssh microduck@duck python3 - --seconds 120 --label map-off-standing \
  < libs/runner/src/labrunner/measure_cpu.py
```

Not verified: that the duck has `python3`. If it has none, `top -b -d 1 -n 120` on the duck gives
the same per-process percentages by hand.

Take four runs, 120 s each, with the same posture inside a pair:

1. `[map] enabled = false` in robotd.toml, the duck standing (label `map-off-standing`).
2. The same, `enabled = true` (label `map-on-standing`).
3. and 4. The same two while the duck walks by hand-driven goals through Mission Control
   (`map-off-walking`, `map-on-walking`). mapd works at stops and on frames, so a standing number
   understates it.

Read mapd's own row (`cpu% mean`, `p95`, `max`, the resident size) and the machine's busy share
and hottest thermal zone, each against the map-off run. `cpu%` is of one core: 100 is one core
fully busy, a 4-core board tops out at 400. The decision it feeds: leave `[map] enabled` on or not
(RFC-0002 phase 5).

## 2. Radial or axial (`lab-measure-range`)

Read-only: it asks the depth socket for `tof.stream` and nothing else. mapd assumes axial
(`range_is_axial = true`), the simulator is radial, the real VL53L5CX is not known
([RANGE.md](RANGE.md), K34).

The setup: the duck standing still on a flat floor, its head held in the walking pose, and a flat,
vertical, matt board square to it, large enough to cover the zones you name. Repeat at 0.25, 0.5
and 0.75 m by tape. Near is the better test: the two models part by up to 12 % of the range at
the corners.

```bash
cd libs/runner
uv run lab-measure-range --socket ~/.cache/duck-real/duck-tof.sock --tape-m 0.5 \
  --rows 0-5 --cols 0-7
```

`--rows 0-5` leaves out the bottom rows if they see the floor; row 0 is the top. The residual map
at the end of the output shows which zones stand out from the wall; take them out of the window
and run again. The verdict is `radial`, `axial`, or `inconclusive` (exit 2) with the reason: a wall
not flat, too few zones, or two models that fit equally. The median frame is in the JSON, so a
later look can re-fit with `--frames-file`. The fitted distance beside the tape (`D - tape`) will
be a few centimetres off, by where the sensor sits in the head; the verdict does not depend on it.

What follows from it: if the real sensor is radial, mapd's axial model puts off-centre returns
6 to 13 % too far, and the replay bench's `range_is_axial=false` is worth trying (REAL-DUCK.md
section 2). If it is axial, the navigator's `sensors.tof8x8.mount.range_kind` for the real
variant is `axial` and the simulator is the part that differs. The fitted pitch is the sensor's
total pitch against the wall: the head's plus the mount's offset beyond it (the simulator reads
2.5 to 2.9 degrees, mapd assumes 3).

## 3. Walking speed against the speed asked (`lab-measure-walk`)

This one moves the robot. It goes through the gate with a lease, and it refuses any robot that is
not the simulator unless `--real` is given; the refusal is made before any connection. A robot
another client holds is refused. STOP from any client ends the lease and the script. Ctrl-C stops
the robot.

Floor: clear, flat and dry for about 2 m ahead of the start mark, nothing the duck could drop
from, someone with a hand on STOP. The legs run at the slowest speed first. Speeds above 0.4 m/s
are refused. Put a tape along the line, with the start mark at its zero.

```bash
cd libs/runner
uv run lab-gate --listen ~/.cache/duck-real/duck-gate.sock --upstream ~/.cache/duck-real/duck.sock
# in another terminal
uv run lab-measure-walk --real --interactive --gate ~/.cache/duck-real/duck-gate.sock \
  --speeds 0.2,0.3
```

Each leg holds still 1 s, walks 1.5 s (getting up to speed) and 4 s (measured), then holds still
1.5 s. With `--interactive` it waits for you at the start mark before each leg and asks for the tape
distance from the mark to where the duck stopped. The output gives, per speed:

- the odometry's speed over the measured part, and the gain (measured over asked): the first
  comparison of the score sheet. The simulator walked about 0.13 m/s when asked 0.3.
- the odometry's distance for the whole leg, and with the tape, the odometry scale (tape over
  believed): REAL-DUCK.md section 4's "distance believed vs walked". It is the number the
  Calibration tab's tape entry keeps ([A3](PHASE5-NEXT-PLAN.md)); this script gives it without
  Mission Control.

Repeat on each floor type (carpet, tiles) and keep one table per floor. The B3 numbers
(`fall_tilt_deg`, `fall_s`) are a different measurement: the tilt a walking duck keeps. A walk
recorded through Mission Control carries the IMU's tilt in every tick, and the score sheet's
`trunk tilt` rows read it.

## 4. The score sheet (`lab-score-sheet`)

Read-only, on finished runs. Record the real duck's runs through Mission Control as usual (they are
format 2 runs, with the belief and no truth), then:

```bash
cd libs/runner
uv run lab-score-sheet --sim /work/robotics-lab/data/runs/duck/ch10-s1 \
  --real ~/real-runs/duck/room-a
```

Each argument is a run folder or a folder holding runs. The output has the speed gain first, by
the belief in both arms and by the truth in the simulator's, then the share of goals reached, the
time and path of a reached goal, the trunk's tilt (p99 and largest), and the trouble events per
run (stuck, stalled, reflex stop, cliff stop, guardrail, refused, recovery). `real/sim` is the
ratio where both arms have a number.

## What none of this covers

- Nothing has run on the real duck. The ssh pipe for the CPU script, `python3` on the board, the
  depth socket's real `tof.stream` frame shape (the scripts read what the simulator's gives:
  `rows`, `cols`, `distance_mm`, `status`), and robotd's answer to a second connection beside the
  gate's are all unverified.
- The radial or axial verdict assumes a flat vertical board. It does not model a board tilted
  forward or back (that looks like pitch, and is fitted as such), the sensor's own crosstalk or
  the VL53L5CX's multi-target zones; a glossy board will read wrong in either model.
- The CPU script measures what the kernel reports per process. It does not separate mapd's
  threads, and does not tell the board's other loads from the duck's own.
- The walk measures forward straight legs only. Pivot creep, steps, bars and stuck detection
  (REAL-DUCK.md section 4) have no script. The leg's tape distance is read by hand and the start
  mark is the operator's.
- The score sheet has no contact or fall count: those need the truth or the scene. Its real arm
  has no truth gain until a tape walk (section 3) supplies the odometry scale.
- B6's real adapter and its safety review are not part of this: these scripts do not drive a
  goal, only a straight leg.
