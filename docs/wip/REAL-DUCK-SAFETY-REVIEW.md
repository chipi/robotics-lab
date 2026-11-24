# The real duck: the safety review before the first real run

**Status:** written 2026-11-24 for plan unit B6. The code is built and proven against stand-ins;
the review below is the operator's, and nothing in it has been done. No real run happens until
you set one key in one file, and that is meant to follow this list, not to replace it. Where an
item says "not verified", it was never run on the real duck.

## What the key is

- The key is `allow_real_runs`, in the `adapter` block of the real duck's robot file
  (`apps/mission-control/robots.real/duck-real.json`). It is `false` as shipped. A value that is
  not `true` or `false` stops Mission Control from starting (a string `"false"` is not a no).
- Mission Control reads it when it starts. Changing it means restarting Mission Control.
- With it `false`, Mission Control refuses, naming the key and this file:
  - every goal run on a robot whose profile variant is `real`, whatever the run's `target` says;
  - every calibration on such a robot. A calibration walk is a real run in the strictest sense:
    the robot walks straight and blind, with no wall, cliff or contact check.
- A robot whose variant is `sim` is never asked for the key. The fake robot has no registered
  profile and is never a real robot.
- Simulator-first (B8) still applies on top: a goal with `sim_first` needs a passing run in the
  simulator before the real robot takes it, with or without the key. The key is not the
  rehearsal, and the rehearsal is not the key.

## What the key does not cover

The key is Mission Control's rule, and nothing else asks it:

- Driving by hand through the page's lock and drive controls, and STOP. Both stay available on
  the real duck by design: STOP must never wait on a review. Driving by hand is a move of the
  real robot with no key.
- Anything that reaches the gate or the navigator without Mission Control: `lab-go`,
  `lab-measure-walk` (which asks for `--real` itself), a script, a client of
  `lab-nav-server`'s TCP port (it has no login; loopback only).
- A robot file that is not Mission Control's own: another copy of the robot's file with the key
  `true` is a second permission. Keep one.

## Before you set the key

Each item says what to look at. Tick it only when you saw it on the real duck, not when you read
that it should be so.

### The room

- [ ] A clear floor, flat, at least 3 m ahead of the robot, and no drop, stair or table edge
  within reach of its first runs ([when the real duck arrives](REAL-DUCK.md), sections 1 and 3).
- [ ] A person next to the robot with a hand on STOP for every run, and the page's STOP button
  within reach of the other hand.
- [ ] The profile's `max_speed` guardrail set below the simulator's cruise (0.3 m/s) until the
  walking has been seen on this floor.

### The link and the gate

- [ ] `lab-link check` prints `link PASS`, three times over a minute
  ([the link recipe](REAL-DUCK-LINK.md)). The ssh window lasts 30 minutes: start the run
  with most of it left.
- [ ] The gate runs on this workstation on the forwarded robot socket, and `lab-link check
  --gate` shows it answering.
- [ ] Mission Control shows the robot online, with a pose that moves when you move the robot by
  hand (carried, then put down). Stop the link: the robot goes offline with the reason.
- [ ] **STOP, on the real robot:** drive by hand at the lowest speed, press STOP, see it stop
  and the answer say `confirmed`. Repeat with the page's "stop all".
- [ ] **The deadman, on the real robot:** with the robot walking by hand, close the ssh window
  (or kill `lab-link`). The robot must stop within about a second. Nothing in this repository
  proves it: the gate cannot send a stop to a robot it cannot reach, so robotd's own 0.5 s
  deadman is the only stop. Not verified on the real duck.
- [ ] Whether robotd takes a second connection beside the gate's (the link check opens one every
  2 s, Mission Control's check every 5 s). If the real one refuses, the check says `DEAD`
  on a working link ([the link recipe](REAL-DUCK-LINK.md), "Not verified").

### The other doors

- [ ] What else can drive the robot: the face button, another client of robotd on the duck,
  the camera console. The gate's watch for other doors (B4) needs robotd's real `move.source`
  name for the proxy's `--own-source`; it is an open item, so the "someone else drives" alarm
  is not verified on the real duck.

### The numbers the run depends on

- [ ] `variants.real` in `robots/duck/profile.json` is `{}`: every number is the base's and
  marked unmeasured. Read each one the first goal depends on (the speed, the footprint, the
  odometry scale of 1.0) and decide whether to run before measuring
  ([the measuring scripts](REAL-DUCK-MEASURE.md): the walk's speed gain first).
- [ ] The guardrails the robot enforces without a truth (B3) use `fall_tilt_deg` 45 and
  `fall_s` 0.5, proposals nobody has measured. The fall and contact checks were proven only
  against stubs: the simulator never tilts or bumps on demand. Only the drop check has a
  simulator proof, and a rim mapd has not yet seen is not covered. So the first goals stay
  far from any drop.
- [ ] The health stops (B2: `motor_hot`, battery, unhealthy, a stale stream) end a run
  `stopped_by_guardrail`. Look at the real robot's health for a minute: if robotd reports
  something the stops misread, a run would stop for nothing, or not stop for something.

### The navigator

- [ ] `lab-nav-server` is started from a host file with `truth_port: null` and the real folder
  (below). Its first line says `camera none (no truth)`.
- [ ] The installation names no variant for the duck. The runner takes it from the installation
  first; a `sim` there would run the real navigator on the simulator's numbers.
- [ ] On the first goal, the run's decisions show no "the navigator runs profile ... Mission
  Control reads ..." line. That line is a mismatch between the profile the navigator runs and
  the one Mission Control scales poses by.
- [ ] The goal run's `not_enforced` list is what you expect: with no truth, `no_go_area` is
  not enforced, and the robot-side `fall`, `contact` and `drop_clearance` replace the truth's.

### The first goal, and a calibration

- [ ] Rehearse the same goal in the simulator first, with `sim_first` set on it. The twin is a
  `duck-sim` robot in the same Mission Control (the installation names one variant per
  registered robot, so the twin's file names the `duck-sim` adapter and the real file names none).
- [ ] Make the first real goal a point 0.5 m ahead on a floor you cleared, with the site's dock
  where the robot stands.
- [ ] A calibration walks straight for its seconds at its speed with no check. Clear the 3 m,
  keep a hand at STOP, and measure the distance with the tape before you keep it.

## Setting the key, and the first run

1. Copy the files: `robots.real/duck-real.json` into the folder Mission Control reads
   (`--robots`, or `MC_ROBOTS`) beside the simulated duck's file.
2. Bring the stack up in this order, each from its own terminal: `lab-link up`, `lab-gate`,
   `lab-nav-server --host <the real host file> --listen 127.0.0.1:8062 --robot-socket
   ~/.cache/duck-real/duck-gate.sock`, then Mission Control. The robot is offline with a reason
   until each part is up; start the parts in any order and it comes online by itself.
3. Edit only the one line: `"allow_real_runs": true`. Restart Mission Control.
4. Run the first goal. Watch the Observatory's live page and keep a hand on STOP.
5. To undo: `false`, restart. The refusal is back for the next run; a run that is going on is
   ended by STOP.

The host file for the real duck is the simulator's with the truth removed and the real folder
named. The reader still asks for the `pollen` and `cargo_bin` keys of its kind; the real duck
uses neither:

```json
{"host": 1, "kind": "pollen-duck-sim", "robot": "duck",
 "pollen": {"microduck": "/work/pollen/microduck", "microduck_rl": "/work/pollen/microduck_rl"},
 "state": "~/.cache/duck-real", "truth_port": null, "cargo_bin": "~/.cargo/bin"}
```

The adapter's addresses are the real duck's: the gate at `~/.cache/duck-real/duck-gate.sock`, the
navigator at `127.0.0.1:8062`, the link's folder `~/.cache/duck-real`. The installation file's
gate and navigator for the duck are read only when that entry says `"variant": "real"`: they
are the simulator's otherwise, and a gate of the simulator never answers for the real duck. Each
can be named in the file's `adapter` block (`gate_socket`, `navigator`, `link_dir`).

## Not covered by this list

- It is not a hazard analysis of the robot: the duck's falls, the motors' heat, the battery, a
  child or a pet in the room, the Wi-Fi, are yours to add.
- No run of `lab-nav-server` against the real duck's host file has been made. That a host
  with `truth_port: null` and the real folder starts the navigator without a simulator is read
  from the code and proven on the simulator with its truth removed (`sim_duck --no-truth`), not
  on the robot.
- The adapter was proven against stand-in sockets only. The real robotd's, tofd's and mapd's
  answers to the link check's questions (`robot.health`, `tof.stream`, `map.status`) are the
  names this repository's clients call, not verified on the daemons.
- Nothing here checks the profile's real numbers are right; section 4 of
  [when the real duck arrives](REAL-DUCK.md) is where they get measured.
