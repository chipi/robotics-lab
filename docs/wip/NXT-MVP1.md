# NXT for MVP 1: where it stands, and driving it in a simulator

**Status:** draft for the operator, 2026-11-23. Read-only survey, nothing built, nothing run
against the brick.
**Builds on:** RFC-0001, RFC-0003, RFC-0020, RFC-0025, ADR-0013, K15, K16, NXT-PARTS.md,
PHASE5-NEXT-PLAN.md (item 4d, named at line 42, not yet written).
**Evidence rule:** `file:line` means I read it. "(survey)" means a read-only survey agent read it
and I did not re-read it. Both are marked in "Not covered".

## Purpose

The operator, 2026-11-23: "For MVP1, we do have to go back to Lego NXT and actually see what else
is missing there to fully integrate that and see how to operate it. That's the working robot
that I have. The gap we have is how to drive Lego in simulator. So we want to solve that on the
existing one that I have. So that should also be part of MVP1."

This note answers two things. What is missing to fully integrate and operate the NXT in the
current ecosystem (Part 1). How to drive it in a simulator, on what we have (Part 2). Then a
proposed item 4d.

## Part 1: where the NXT stands

### What works today, end to end

Short answer: the operator can drive the NXT from two places and record from one. Everything is
tested against `nxt-web --fake`, and nothing has run on the real brick through our code (K15).

Driving from nxt-web's own page (survey):

- `apps/nxt-web/src/nxt_lab/static/index.html`: tabs Drive, Sensors and log, Programs, Setup.
  Drive pad (arrows, WASD), fire, live sensors and charts, record, run and upload brick
  programs, link choice, command log, STOP ALL, the lock display.
- `web.py:316-442`: a stdlib HTTP server with no login (the README says to use an ssh tunnel).
  Routes include `/api/lock`, `/api/drive`, `/api/stop`, `/api/fire`, `/api/status`,
  `/api/live`, `/api/events`, `/api/record/start|stop`, `/api/runs`, `/api/program/*`.
- Lock (`lock.py`): a 20 s lease tied to a session id, renewed by every locked command, takeover
  only for names in a `--takeover-names` file, STOP from anyone, every end of a lease stops the
  motors first.
- Two deadmen. nxt-web's watchdog stops the motors after 0.6 s without a drive command
  (`web.py:29`). robotd-lite on the brick (`programs/robotd.nxc`) stops after 0.5 s and stops
  forward motion when the ultrasonic reads under 15 cm. The default drive mode refuses to drive
  unless robotd is running.
- Stop on connect, stop on SIGTERM, shooter off by default, program interlock (RFC-0001 section 3.3).

Driving from Mission Control (read by me, `apps/mission-control/src/mission_control/nxt.py`):

- `NxtGate` (`nxt.py:38-147`) gives the robot runtime a gate over nxt-web's HTTP lock: acquire and
  takeover, release, keepalive, who. `robot.move` becomes track percent (`nxt.py:117-120`, `184-187`).
  `robot.stop` calls `/api/stop` (`nxt.py:121-123`). A lost lease is told to the client
  (`nxt.py:128-147`).
- `NxtAdapter.state()` gives velocity from the tracks, mode, tracks, link, `battery_mv`, and flags
  `program` and `deadman_stop`. It has no pose (`nxt.py:200-210`).
- No navigator (`nxt.py:178-179`), no map (`216-217`), no camera (`222-223`). A goal is a refused run.
- Robot file `apps/mission-control/robots.nxt/nxt-1.json` (survey): adapter `nxt-web`, 0.3 m/s and
  1.5 rad/s as assumed full speeds, one HARD `fire` action, empty capabilities.
- Tests (survey): `apps/mission-control/tests/test_nxt_adapter.py` starts the real `nxt-web --fake`
  as a process and checks state, drive, clamping, STOP confirmed, lease ended by STOP, takeover
  allowed and refused, goal refused, STOP ALL, the offline case (STOP accepted but unconfirmed,
  drive 503). `test_robotfile.py` loads `nxt-1.json`.

Runs and replay:

- Runs are recorded only by nxt-web's own recorder, when someone presses Record (survey,
  `recorder.py`). They are written as format 2 MCAP, live, to
  `<data>/runs/nxt/unmapped/<run>/run.mcap` (ADR-0013, `libs/runfile/src/runfile/adapters/nxt.py`).
  Signals: `power_*`, `tacho_*`, `s<port>_<type>`, `program`; the command log as events.
- A pose exists only if `odom_sprocket_diameter_m` and `odom_track_width_m` are both set in the
  config. They are unset by default and "never guessed" (survey, `config.py:37-41`). Otherwise the
  run says `no_pose`.
- Mission Control records nothing for the NXT (survey: no `mcapio` or `write_run` in its source).
- The Observatory replays and follows NXT runs live: signals, outliner, event markers, playhead, a
  live run being written. A run with odometry gets ticks and the robot drawn. There is no scene,
  so `GET scenes/unmapped` is 404 by design (survey: `apps/observatory/tests/test_nxt_pages.py`,
  `test_nxt.py`, `shell.js:184`).

So today: drive from nxt-web or Mission Control, record from nxt-web, replay in the Observatory.
Mission Control's driving and nxt-web's recording are not connected.

### What the NXT is, as built

- Shooterbot on tracks. Motors: A shooter, B right track, C left track. Colour sensor on port 3,
  ultrasonic on port 4, ports 1 and 2 free. Stock firmware 1.28. "As checked 2026-11-14"
  (survey: `apps/nxt-web/README.md`, `apps/nxt-web/programs/common.nxh:1-12`). No later update
  found.
- robotd-lite reads only the ultrasonic (port 4) and the track tachos. The PC reads the other
  sensors through nxt-python, and stops reading them while a brick program runs (survey).
- nxt-web has no sensors endpoint. Sensor values are only inside `/api/live` samples
  (survey: `recorder.py:107-116`). `/api/status` carries no readings except the ultrasonic
  distance inside `deadman.state`.
- Tracks skid when turning, so heading from track counts is poor (`NXT-PARTS.md:52`).

### What is missing to fully integrate and operate it

Mission Control's robot page, section by section (survey: `web/app.js:188-302`, `settings.js`,
`CONTRACT.md:316-345`):

| Section | Today for the NXT | Missing |
| --- | --- | --- |
| Overview | Works for any robot: five fit checks from `GET /robots/{id}` and the alarm feed | Only battery and link feed it; no obstacle, deadman or sensor checks |
| Parts | "No profile: this robot's file holds the robot itself" | A profile |
| Body | "No 3D model". `robots/nxt-shooterbot/` has `robot.urdf` (166 lines) and `kinematics.json`, but `nxt-1.json` has no `robot` pointer and the meshes are git-ignored, built by `make robots-lego` | A registration naming the description; built meshes; joints in the state (the NXT reports none) |
| Modules | "No profile" | A profile, and plugins (none exist for a tracked robot) |
| Settings | "No profile" | A profile to edit |
| Calibration | Only "says what comes next" for every robot | The odometry geometry (sprocket, track width) and the measured speeds (K16) |

Other pieces:

| Piece | State | Evidence |
| --- | --- | --- |
| Registration and profile like the duck's | None. `robots/nxt-shooterbot/` has no `registration.json` or `profile.json`, no `robotics_lab.robots` entry point. Only the duck has them | survey: `robots/duck/pyproject.toml:42` |
| Profile schema | Duck-shaped: `REQUIRED` includes `footprint`, `locomotion`, `plugins`; four plugin kinds; sensors schema knows `tof8x8` and `camera` only. A NXT profile needs stand-ins or RFC-0025 step 2 (profile v2) | RFC-0025 section 2.4 items 4, section 7 item 3 |
| Installation file | I did not verify whether an installation entry for the NXT is needed or exists. The registry has no NXT mention | survey, `registry.py` |
| Gate and lease | Works, over nxt-web's HTTP lock. `control.lease_s` and `takeover` in `nxt-1.json` do not apply; they are nxt-web's | survey: `CONTRACT.md:418-425`; RFC-0018 section 10 calls it a second copy of the gate's rules |
| STOP and deadman | STOP works end to end on `--fake`. Offline: accepted, unconfirmed. The deadman is the brick's and nxt-web's, 0.5 s and 0.6 s | survey; RFC-0003 section 2.3 |
| Runs recorded | Not by Mission Control. Only nxt-web's Record button | survey |
| Sensors in Mission Control | None in state; `capabilities.sensors` empty | `nxt.py:200-210`; survey |
| Anomalies and alarms | `anomaly` events come only from a navigator, which the NXT lacks. Health is `battery_mv` and link only. `battery_pct` is None (`nxt.py:208`). The obstacle stop (flag 2 of robotd) is not forwarded; only `deadman_stop` is. Whether `someone_else_drives` fires for nxt-web's lock: not checked | `nxt.py:210-214`; survey |
| Fire | No `robot.fire` in the gate. Fire exists only on nxt-web's page | survey |
| Pose, map, navigator | None. RFC-0025 step 6 gives it our navigator in MVP 2; RFC-0020 step 5 says the NXT comes "once it has a sensor that can see the floor" | RFC-0025 section 8.8; survey |
| Stale docs | STATUS.md, IDEAS.md, RFC-0003, ADR-0013 point to `nxt/`; ROADMAP.md says MCAP topics `/nxt/state`; ADR-0013 says `MINIVIEW_DATA` | survey |

### Gaps ranked by what blocks operating it

1. It has never run on the real brick through our code (K15), and robotd-lite is "not yet
   verified on the real brick" (survey: README; RFC-0001 section 7 item 1). This blocks safe
   operation. Only the operator can close it.
2. The speeds are assumed (K16: 0.3 m/s, 1.5 rad/s) and the odometry geometry is unset. Without
   them Mission Control's speeds are guesses and there is no pose. This blocks any run that
   means something in metres.
3. No registration or profile. This blocks Parts, Modules, Settings and Body, and any shared
   tooling that finds a robot through the registry. It needs a decision (see questions): stand-in
   profile now, or profile v2 early.
4. Mission Control does not record the NXT's runs. A drive or session from Mission Control leaves
   nothing to replay. This blocks "runs recorded, replay in the Observatory" as one workflow.
5. No sensor values, obstacle flag, battery percent or alarms in Mission Control. The operator
   cannot see why the robot stopped (deadman or the 15 cm obstacle stop) from the robot page.
6. The simulator gap (Part 2). It blocks any rehearsal off the brick.
7. Fire is outside the gate. Whether it is MVP 1 is a question.
8. Stale documentation.
9. No navigator, no pose, no map. Not an MVP 1 gap by RFC-0025: it is step 6 of MVP 2.

### Hardware checks pending, and what the operator does at the robot

- K15: "The NXT's lock, page lock and adapter have never run on the real brick." Tested on
  `nxt-web --fake` only. Planned: "when the operator is at the brick".
- K16: "The NXT's speeds are assumed, not measured." Planned: "measured with the hardware test".
- Existing scripts, not run by me (survey): `apps/nxt-web/tests/hw_deadman.py`,
  `hw_link_speed.py`, `hw_read_sensors.py`, `hw_stop_on_connect.py`, `hw_stop_on_sigterm.py`.
  ROADMAP's next step is `make test-hardware`.

What the operator would do, as a list for the day at the robot. I have not run any of it.

1. Run the five `hw_*` scripts. Record pass or fail per script. `hw_deadman.py` is the one that
   closes RFC-0001 section 7 item 1.
2. Start nxt-web for real (USB first), then Mission Control with `robots.nxt/nxt-1.json`. Check:
   lease acquired, drive moves the tracks, STOP stops them, a second client is refused, takeover
   from a listed name works, killing nxt-web shows the robot offline. This is K15.
3. Measure the speeds (K16). Drive both tracks at 100 for a fixed time over a measured floor
   length. Drive 50 and -50 for a turn and measure the angle. Enter the two numbers in
   `nxt-1.json`.
4. Measure the track width and sprocket diameter and set them in nxt-web's Setup, so runs have a
   pose (ADR-0013, "Calibration, the operator's to run").
5. Check the 15 cm obstacle stop with a hand or a box, and note the real ultrasonic cone.

## Part 2: driving the NXT in a simulator

### What we have to build on

- `libs/simhost`: standard library only. One kind, `KINDS = ("pollen-duck-sim",)`
  (survey: `host.py:25`). `pollen` is a required key with exactly Pollen's two checkouts
  (`host.py:94-96`). Sockets are the duck's five names (`host.py:28-29`). `simulator.py` is wholly
  the duck's (`duck-sim` script, mapd, robotd toml). `truth.py` speaks Pollen's body server.
  A second kind needs per-kind dispatch in `parse()`, a reset, a truth reader and, for some kinds,
  a scene writer. RFC-0021 section 3.1 says "a module per kind comes with the second kind".
- Truth is robot-neutral: `truthcopy.py:16` "a truth is a pose by wall-clock time"; any source
  giving `(wall_ns, pose, z, quat)` fits (survey). The judge reads the profile for footprint and
  fall height (survey: `labrunner/judge.py`).
- `nxt-web --fake` (survey: `robot.py:292-427`): integrates tachos at 9 degrees per unit of power,
  battery fixed at 7800 mV, ultrasonic a sine wave `60 + 40 sin(t/4)` cm unrelated to any world
  (`_fake_distance()`, `robot.py:396`), colour cycling, touch random. `FakeDeadman`
  (`deadman.py:44`) already stops forward motion when `dist < 15` and sets the obstacle flag.
  Mission Control already drives this through the real adapter and gate in `test_nxt_adapter.py`.
  The fake has no pose and no world.
- Mission Control's own fake (`fake.py`, survey): a point robot with a bounds box, no tracks, no
  ranging sensor, bypassing nxt-web, so it skips the NXT adapter, the lock and the recorder.
- Scenes (survey): `scenes/apartment/scene.json` is the only scene. Bounds, rooms, one drop and
  about 55 boxes `{name, cx, cy, z0, z1, hx, hy, yaw}`, including thin table legs and 4 low `obj_N`
  blocks. Colours and floor patches are not in the schema.
- Ray cast: `libs/runner/src/labrunner/sim_camera.py:30-47` `_segment_hits_box` is pure Python, a
  2D slab test on a rotated box. It returns a hit, not a distance; its entry parameter `t0` is in
  hand, so a distance is a small extension (survey).
- MuJoCo: installed only in Pollen's venvs, 3.10.0 (survey:
  `/work/pollen/microduck_rl/.venv`, `/work/pollen/microduck-arena/.venv`), with a note in
  `microduck_rl/pyproject.toml:68-69` not to override it. Our code that imports it
  (`robots/duck/sim/layout.py:15` and others) runs under Pollen's Python
  (`Makefile:342` `MUJOCO_PYTHON`). The repo's own venvs have none.
- Gazebo: none on the host. Docker images `mvp2-spike:jazzy` (4.32 GB) and
  `robotics-lab-nav2:spike` exist. The spike measured real-time factor 1.00, a reset of 0.26 s
  only when the robot is in the world file, `/cmd_vel` as TwistStamped, the simulator holding the
  last velocity, and sim-time stamps (survey: MVP2-SPIKE.md). The spike never ran the NXT and says
  nothing about ultrasonic.

### Options

| | A: kinematic NXT sim of our own | B: MuJoCo model | C: Gazebo | D: extend the fake |
| --- | --- | --- | --- | --- |
| What | A pure-Python world model: track commands to a pose, ultrasonic by a 2D ray cast on scene boxes, collision, truth | A tracked or wheeled model in MuJoCo, our own loop, ultrasonic by `mj_ray` | The NXT as an SDF model in a container, `ros_gz`, a connector from nxt-web's HTTP to ROS | Add a world and sensors to Mission Control's `fake.py` |
| Takes | A SimRobot backend for nxt-web beside `NxtRobot` and `FakeRobot`; a small world lib; a kind in simhost; scene.json read directly | A model of the NXT (tracks are a contact problem); our MuJoCo loop under Pollen's Python (works today) or a new dependency in our venv (needs approval); ray casts; a kind; a scene writer to MJCF | An SDF model, diff-drive plugin, bridge, a ROS connector for an HTTP robot, an SDF scene writer; waits on RFC-0028 | A world, tracks and a range sensor in `fake.py` |
| Platform pieces it exercises | nxt-web (lock, deadman, recorder), `NxtAdapter` and gate, run format, Observatory replay, simhost kind, truth, scene.json, sim/real variants | The same, plus MuJoCo plumbing | The same, plus ROS | Mission Control's fake path only. Not nxt-web, not the NXT adapter, not the recorder |
| Fidelity | Kinematics and sensor geometry, with a slip factor. No contact dynamics, no track slip physics | Higher on contacts, but track and ground contact is hard to get right, and unmeasured (K16) | Medium; models a wheeled base well, not NXT tracks | Low |
| Cost | M | L | L, and blocked on MVP 2's spike | S |
| Risks | A kinematic sim can flatter the robot. Mitigation: parameters from K16, odometry kept separate from truth. Ultrasonic cone and the 15 cm stop must match the real sensor (cone angle, 255 cm range, 1 cm resolution are from memory, not checked here) | Slow to build; a second dependency story for MuJoCo; no better truth than A without measurements | Ties MVP 1 to MVP 2's spike; an HTTP robot behind a ROS connector is a detour | Proves nothing the fake does not already prove; two fakes |
| Fit with RFC-0025 | Second host kind (step 4), second connector in HTTP (step 1), sensors declared (3.9), a simulator for the NXT's navigator (step 6, question 16) | Second kind with a scene writer (step 9's work) | Overlaps step 5 for the wrong robot | None |

### Recommendation: A

Build the kinematic simulator as a third backend of nxt-web (real brick, fake, sim), reached
through a new simhost kind. Reasons:

- It keeps the whole real path in the loop: Mission Control adapter, gate, nxt-web's lock and
  deadman, the recorder, format 2, the Observatory. Only the brick is replaced. That is what
  "drive Lego in a simulator" means for an operator who already drives it through those.
- It is the cheapest thing that gives a world, a distance sensor that sees walls, and truth.
- The existing `FakeDeadman` already implements the 15 cm obstacle stop; a real ultrasonic value
  makes it fire for real.
- It needs no new third-party dependency. The world lib is ours; MuJoCo is not needed. (If B is
  ever wanted, it can sit behind the same kind.)
- Design shape. Add a `SimRobot` in nxt-web (same class interface as `FakeRobot`), selected like
  `--fake` today, taking `--world scenes/<id>/scene.json`, a start pose, and a truth port. The
  world lib holds the model: differential kinematics from the track powers and the assumed speeds,
  a slip factor on turns, collision against boxes, an ultrasonic cone cast, a touch bumper if
  fitted. Truth is the model's own ideal pose; odometry, as the recorder computes it from the
  tachos and the geometry, is the belief, so the error between them is real and visible.
- The kind (`nxt-kinematic-sim`) provides what RFC-0021 section 3.1 asks: reset (restart the sim
  with the start pose), connections (nxt-web's URL), truth (a port giving `(wall_ns, pose)`), and
  no scene writer, because it reads `scene.json` itself.

What it proves:

- A second host kind with a different truth source, before the host contract is written
  (RFC-0025 step 4): it shows which parts of `simhost` are really the duck's.
- A second connector in HTTP, with neither robotd nor ROS, passing through the same interface
  (RFC-0025 section 3.2 says the NXT "is the proof that a third connector ... passes through the
  same interface").
- A second sensor kind, a single range value, declared per host kind (RFC-0025 section 3.9, rule 3).
- `scene.json` as the source (RFC-0025 option 8.5 B), early and without the duck's layout readers.
- A simulator for the NXT's navigator, which answers the second half of question 16: step 6 need
  not prove itself on the real NXT only.
- The sim and real variants of one robot.

What it anticipates, and what it conflicts with:

- Anticipates step 1 (robot interface), step 2 (profile v2: it forces the question of a NXT
  profile now), step 4 (a second kind), and section 3.9 (sensors declared).
- Conflict 1: RFC-0025 step 4 plans a "stub Gazebo host" to settle the host contract. A real
  second kind arrives before it. The risk is writing the contract twice. Mitigation: keep the
  per-kind dispatch minimal, write down what the kind needed (D0), and let RFC-0028 start from it.
- Conflict 2: RFC-0025 section 3.5 says "No generalisation of the sensor schema beyond the one
  sensor that is real" and "no `lidar2d` schema until the first stub draws it". The NXT sim brings
  a second sensor kind (a single range). Say so in D0 and keep the declaration a plain list entry
  with id, kind, port and range, no more.
- Conflict 3: the RFC says "the connector does not know it is in a simulator". Here nxt-web
  selects the sim backend. This is the same as nxt-web's existing `--fake`, and the Mission
  Control adapter does not know.
- Not a conflict: MVP 1 keeps `make sim-duck` green; D3 must not change the duck's kind.

Why not the others: B costs L for contact fidelity nobody has measured; C waits for RFC-0028 and
ties MVP 1 to the MVP 2 spike for a robot that is not on ROS; D leaves out nxt-web, the lock, the
adapter and the recorder.

## Proposed item 4d

Heading for PHASE5-NEXT-PLAN.md: the NXT in MVP 1. **The operator, 2026-11-23:** quoted above.
Units, in the plan's table format:

| Unit | What | Proof | Size | Builds here |
| --- | --- | --- | --- | --- |
| D0 | A short design note (an ADR or an RFC section, number to be given): what the second host kind needs from `simhost`, the NXT sim's sensor declaration, the NXT profile route (stand-in profile or profile v2 early) | The operator accepts it; RFC-0028 can start from it | S | yes |
| D1 | The hardware check at the brick: the five `hw_*` scripts, K15 (lock, page lock, adapter on the real brick), K16 (measure the speeds, track width, sprocket), the 15 cm stop | Script results, measured numbers written into `nxt-1.json` and the config; K15 and K16 closed | S for the operator's time | no, needs the operator |
| D2 | A world for nxt-web: a `SimRobot` backend with `--world scene.json`. Pose from track commands with a slip factor, collision with boxes, ultrasonic cone cast (distance version of `_segment_hits_box`), the 15 cm stop firing on a real distance | Unit tests: drive into a wall and stop; the ultrasonic reads the wall's distance within 1 cm; turning in place; the obstacle flag; STOP and the deadman still hold | M | yes |
| D3 | The host kind `nxt-kinematic-sim` in `simhost`: per-kind dispatch in `parse()`, a reset, a truth port and reader giving `(wall_ns, pose)`, no Pollen keys required for this kind | `simhost` tests; a host file for the kind loads; `make sim-duck` unchanged | M | yes |
| D4 | The NXT registered like the duck: registration, a profile (route from D0), installation entry, variants `sim` and `real`, the description with built meshes, the two numbers (speed, turn) in the profile instead of the adapter file | Parts, Body, Modules and Settings open for the NXT in Chromium; an old `nxt-1.json` still loads | M | yes |
| D5 | Mission Control sees the NXT's sensors and stops: ultrasonic and colour in state and in `capabilities.sensors`, the obstacle-stop flag, battery percent, alarms for low battery, link lost, deadman stop and obstacle stop, and the holder line; an `/api/sensors` or a field in `/api/status` on nxt-web's side if needed | Page test: wall in the sim, the robot page shows the obstacle stop and the alarm; `test_nxt_adapter.py` extended | M | yes |
| D6 | Runs from Mission Control: a drive session starts and stops nxt-web's recorder, so every session leaves a format 2 run; in the sim the run carries truth beside the belief and the scene | Drive from Mission Control in the sim, open the run in the Observatory, the robot is drawn in the apartment | M | yes |
| D7 | `make sim-nxt`, the NXT's `sim_duck`: start the host, drive by hand through Mission Control's API, hit a wall, STOP, takeover, deadman, replay | The scenario ends PASS with exit 0 in the foreground | M | yes |
| D8 | Docs: fix the stale `nxt/` paths, ROADMAP's MCAP line, ADR-0013's old names; a recipe for starting the sim | `docs-preflight` green; a grep for `nxt/README` finds nothing | S | yes |
| D9 | Feed the measured numbers (D1) back into the sim's slip factor and speeds; compare a recorded real run with the sim's | One real and one sim run of the same command list, error between them stated | S | no, needs D1 |

Order: D0, then D2 and D1 in parallel (D1 on the operator's schedule), D3, D4, D5, D6, D7, D8; D9
after D1. Colour and light in the sim (floor patches) are left out of D2: scene.json has no floor
colour. A touch bumper is left out unless the operator has one fitted (ports 1 and 2 are free).

Where an ADR is warranted: D0. It is a decision about the second host kind and the profile route,
and RFC-0025 step 4 and step 2 will build on it.

## Questions for the operator

1. Is the NXT still the Shooterbot on tracks, as checked on 2026-11-14? Tracks or wheels now?
2. Which sensors are on which ports today? The docs say colour on 3, ultrasonic on 4, ports 1 and 2
   free. Is a touch bumper fitted? How is the ultrasonic mounted (height, angle)?
3. Does nxt-web run, and where? On the workstation by USB, by Bluetooth, in Docker, or on a Pi?
   Do you drive from nxt-web's page or from Mission Control?
4. Is the shooter part of MVP 1? Fire has no gate method; adding one is a safety decision.
5. Which scene should the sim use: the apartment as it is, or a small arena like your room?
6. The NXT's profile: stand-in blocks in the duck's schema now, or wait for profile v2 and build D4
   on it? (RFC-0025 section 8.6.)
7. Should a Mission Control drive session record a run, as in D6, or stay a live view only?
8. Have you set the sprocket diameter and track width in nxt-web's Setup? If not, a pose is absent
   until D1 is done.
9. When can you be at the robot for D1? The whole simulator work does not need it; the sim's
   numbers get better with it.

## The operator's answers (2026-11-23)

| Question | Answer |
| --- | --- |
| The simulator | Option A: the kinematic sim inside nxt-web, host kind `nxt-kinematic-sim` |
| 1, the build | As documented: Shooterbot on tracks, colour on 3, ultrasonic on 4, no touch sensor |
| 2, the ports | As documented (answer 1); the ultrasonic's height and angle are measured in D1 |
| 3, the link | USB first, then Bluetooth, then a Pi-based augmentation module; plan for all three |
| 4, the shooter | Not in MVP 1; fire stays on nxt-web's own page, outside the gate |
| 5, the scene | The apartment as it is |
| 6, the profile | A stand-in profile in today's schema now; migrated when profile v2 comes |
| 7, recording | Every Mission Control drive session records a format 2 run |
| 8, the geometry | Not set yet; D1 measures the sprocket and track width |
| 9, at the robot | This week; D1 runs alongside D2 |

The operator on the link: "I will start with 1, move to B and plan to have C as extension of the
project where I will build [a Pi-]based augmentation module with all modern sensors, so let's plan
for all of it."

What that adds to item 4d:

- **USB (MVP 1).** nxt-web on the workstation; Mission Control reaches it at a URL from the
  NXT's installation entry, never a hard-coded localhost. D1 and D7 use it.
- **Bluetooth (MVP 1, unit D10).** The same nxt-web, another transport to the brick. The
  link-lost alarm (D5) and the deadman carry it; D10 measures the command latency and how often
  the link drops, and the result decides the deadman's timeout over Bluetooth.
- **The Pi augmentation module (MVP 2, not built in 4d).** A Pi on the robot with its own
  sensors beside the brick's. It is RFC-0025's case of a robot whose software runs on the robot
  (placement as a per-robot setting) and whose sensors come from two sources (the brick's and
  the Pi's), each declared in the profile. D0 records it as a requirement so the host kind, the
  sensor declaration and the installation entry do not assume one source or one machine. It goes
  into RFC-0025 Draft 3 as a third robot shape next to the duck and the Burger.

## Not covered, and not verified

- I did not run anything. No test, no `nxt-web`, not even `--fake`. Every claim of "works" above
  is from reading code and tests and the surveys' reports of them, not from a run by me. No
  command output backs any of it.
- I read these myself: `apps/mission-control/src/mission_control/nxt.py`, RFC-0025, KNOWN-ISSUES.md,
  NXT-PARTS.md, PHASE5-NEXT-PLAN.md lines 30-50 and 320-380. Everything marked "(survey)" comes from
  two read-only survey agents; the cited lines are theirs and I did not re-read them. A line number
  could be off.
- Not read by anyone: the 704-line `index.html` beyond its routes, the bodies of `test_lock.py` and
  `test_web_smoke.py`, `labrunner/geometry.py`, `libs/runfile/src/runfile/profile.py`'s sensors and
  plugins handling, `libs/runfile/src/runfile/installation.py` (so whether the NXT needs an
  installation entry is unknown), `robots/nxt-shooterbot/robot.json` beyond its keys, `robots/ev3-*`,
  the Observatory's `ROBOT_KINDS`, RFC-0001 sections 3.1 to 3.6.
- Not checked: whether `RobotRuntime`'s `someone_else_drives` alarm fires for the NXT's lock;
  whether `meshes/` for the Shooterbot build on this machine; how the Body and Parts tabs find a
  description for a robot with no registration (the survey says a registration with a
  `robot.urdf` is needed).
- Not verified: the ultrasonic's cone angle, range and resolution (from memory); NXT track slip
  (nothing measured; K16 covers speeds only); that a SimRobot in nxt-web can share the FakeRobot
  interface without changes to `recorder.py`; that `simhost`'s per-kind dispatch can be added
  without disturbing `challenge.py`, which calls `mjcf`, `simhost.reset`, `Sampler` and mapd
  directly (survey).
- Not covered by this note: the NXT's navigator (RFC-0025 step 6 and question 16), the EV3, the
  Raspberry Pi or BrickPi options in NXT-PARTS.md, Bluetooth link quality, the arm robot and a
  second brick, and the MVP 2 seams other than the two named. Costs (S, M, L) are rough sizes,
  not estimates in time.
- This note was written under a restricted tool set (no shell, no grep). A grep for other NXT
  mentions in code I did not open was therefore left to the survey agents; a zero-result search
  would not have been trusted either way (rule 0.16).
