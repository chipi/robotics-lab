# RFC-0025: From MVP 1 to MVP 2, the platform's architecture and its evolution

**Status:** Accepted (2026-11-23), at Draft 3: the spike's results folded in. Nothing
in it is built. The operator's answers to section 9 are recorded there and in section 8
("Decided:"). The spike ([MVP2-SPIKE.md](../wip/MVP2-SPIKE.md), cited as "spike §N") settled the
clock rule and the versions; one problem it found (the connector's tf state across a reset, section
3.6) has three causes, diagnosed from code and logs and confirmed by a re-run (spike §21). An
advisor review (Fable 5.1) is folded in. A reflection first, then the RFCs it names, then code.
Where a point rests on the advisor's recollection, the text says "not verified here"; where the
spike says "not verified", this RFC keeps that wording. The seven new words in "Names" are approved.
The operator added one input after the answers: cameras are one of the first hardware upgrades of
the real Burger (sections 3.5, 5 and 7, question 22). The operator answered questions 16 to 27
and confirmed the advisor's five pulled-forward decisions on 2026-11-23, and accepted the RFC
once the reset re-run (spike §21) confirmed the diagnosis. **Date:** 2026-11-23 **Builds on:**
[ADR-0020](../adr/ADR-0020-robots-behind-our-own-interfaces.md) (accepted together with
this RFC), [MVP2-SPIKE.md](../wip/MVP2-SPIKE.md), [NXT-MVP1.md](../wip/NXT-MVP1.md),
[ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md),
[ADR-0018](../adr/ADR-0018-ros2-in-a-container-for-comparison.md),
[ADR-0007](../adr/ADR-0007-run-file-format-2.md), [RFC-0003](RFC-0003-robot-interface.md),
[RFC-0015](RFC-0015-nav2-comparison.md) (parked), [RFC-0017](RFC-0017-robot-access.md),
[RFC-0018](RFC-0018-lab-projects-and-seams.md), [RFC-0020](RFC-0020-robot-profiles-and-plugins.md),
[RFC-0021](RFC-0021-sim-host-and-payload.md), [RFC-0024](RFC-0024-one-platform.md), the plan
([PHASE5-NEXT-PLAN.md](../wip/PHASE5-NEXT-PLAN.md), "MVP 1 and MVP 2" and item 6), and the
operator's vision note on depth cameras, SLAM and 3D mapping (November 2026). **Evidence:** every
`file:line` below was read on 2026-11-23 in the `mission-control` worktree. What I did not verify is
marked "not verified" and collected in section 10. The operator's answers are quoted from their
reply of 2026-11-23. Numbers that come from the spike carry its section ("spike §9"); they were
measured once, on one workstation, in a container with no GPU (spike §20, end), and I did not repeat
them.

## Changes from Draft 2

- **The spike is read and folded in** (it was "running" in Draft 2). Sections 1, 4, 6.1 and 10
  say what it found instead of what was expected.
- **The clock rule is settled** (spike §7, §13): the bridge stamps with simulation time;
  `use_sim_time` is true inside the ROS graph; the connector stamps `wall_ns` and keeps the ROS
  stamp; the run's time stays wall time. ADR-0020 decision 3 is amended to say so. Question 13 is
  closed. Section 3.6.
- **A clock epoch is first-class** (spike §20): a world reset sends the sim clock to 0. The run
  gets an event, an epoch counter and a new `map_to_world` record. **Diagnosed from code and
  logs, confirmed by a re-run (spike §21):** after a reset the prototype's belief and truth
  froze, from three causes (section 3.6, section 7 item 19, question 24).
- **The deadman is a last-hop watchdog** (spike §8, §20): the Gazebo base and the ROS 2 OpenCR
  firmware both hold the last velocity, so it runs on the computer wired to the motor controller
  in every placement. Sections 3.3, 3.8 and 7 item 12.
- **Versions are decided** (spike §2, §3): ROS 2 Jazzy, Gazebo Harmonic 8.15, `turtlebot3_gazebo`
  2.3.7, SLAM Toolbox 2.8.5. Question 4 is closed. `/cmd_vel` is `TwistStamped` in the Gazebo
  bridge; the real node's type is a bringup setting (section 3.3).
- **The reset design** (spike §9): a world reset takes 0.26 s if the robot is in the world file;
  otherwise it deletes the robot. Section 3.4.
- **The scan channel** (spike §10, §20): `foxglove.LaserScan` exists but lacks the range limits
  and the angle step, and `wire.py` cannot take a new channel unchanged. Section 8.7 and
  question 23 pose the choice.
- **Recording and camera cost** (spike §11, §19): rosbag2 writes MCAP by default; sizes and the
  cost of cameras are in section 3.5 and 3.6, and support ADR-0020 decision 5.
- **SLAM accuracy and exploration** (spike §18): numbers, with their limits, in section 3.5.
- **The truth reader and the simhost changes** (spike §20): section 3.4 and step 4.
- **A third robot shape** (NXT-MVP1.md, the operator's answers): the NXT with a Pi augmentation
  module, software on the robot and sensors from two sources. New section 3.10.
- **The NXT as a second host kind in MVP 1** (NXT-MVP1.md, item 4d): the host-kind seam is
  exercised before Gazebo. Step 4 and its risk.
- **Images designed in full** (the operator: super important), new section 3.11: capture settings
  declared in the profile and the camera's actual values recorded per frame; recording options per
  stream with the spike's sizes (depth never lossy); an optional named, versioned pipeline with
  per-consumer branches, recorded in the run and re-run on replay; an Images block in Mission
  Control's Settings; simulator against real. Section 5.1 lists requirements toward the
  photogrammetry tool and the capture set contract. Steps 11 to 13 in section 6.
- **Questions:** 4, 13 and 14 closed; 16 partly answered (the simulator half); 23 to 27 added
  (scan channel, clock epoch, JPEG against H.264, live pipeline, the tool's own vision).
  Section 9.
- **The operator's answers to questions 16 to 27 and the confirmation of the advisor's five
  decisions** (2026-11-23): the five are the truth reader plugin, no drop sensing for the
  Burger and the NXT, `rtf_low`, the DDS settings, and the settled reset. Section 9 records each
  answer. The two parts left open then (the Gazebo-scene half of questions 9 and 21, the NXT's
  range sensor of question 16) were answered on 2026-11-24. Section 5.1 is now
  requirements toward the tool's own RFCs; step 10 gains the review plan (question 19).
- **Advisor review, Fable 5.1, folded** (it read the spike's work files and upstream sources;
  nothing was run). The tf freeze has three diagnosed causes and an ordered reset sequence for
  step 5a to prove, replacing "cannot trust any tf lookup" (3.6, item 19, step 5a). The
  deadman has one home (3.3, 3.8, item 12, step 10). `/cmd_vel`'s type on the real robot
  (3.3, step 10). Step 5 is split into 5a and 5b (section 6). Recommendations first marked
  "decided, advisor's recommendation" (the operator confirmed them, 2026-11-23): the truth reader
  (3.4), the clock epoch as the pair (epoch, t_src) in step 4 (question 24), no drop sensing
  for the Burger and the NXT (3.7), `rtf_low` (item 4), DDS settings (item 6), the settled
  reset (3.4). Images: invalid depth, a companion MCAP per stream, pipeline rules, the capture
  set (3.11, 5.1). Questions 16 to 27 carried the advisor's recommendation or said they were the
  operator's; the operator answered them on 2026-11-23 (section 9).

## Names

The operator, 2026-11-23: the vision note "came from another place. And that's an idea. We don't
have to pick up any terminology. It's about what are we doing." So this RFC uses the project's
words. Where the project has none, it proposes one, in the project's style: plain English, short,
lower case. The note's own names appear only in two places: the translation table in section 3.1
and the last column of the second table below. The operator approved the seven new words on
2026-11-23 (section 9, question 15).

Two things to know first:

- **"Driver" already means something here.** In RFC-0017 and the gate's docstring a driver is
  whoever holds the lease and sends commands ("one driver per robot",
  `libs/gate/src/robotgate/__init__.py:1`; Mission Control's drive call: "so a driver repeats
  it", `apps/mission-control/CONTRACT.md:50`). A program that connects a robot is not that, so
  this RFC does not call it a driver.
- **ADR-0020 is reworded to these terms.** It said "driver" and "backend"; it now says
  "connector", "host kind" and "variant". Where this RFC quotes ADR-0018 it keeps its words
  inside the quotation.

### Our terms used here

| Term | Meaning | Where defined |
| --- | --- | --- |
| robot | A machine we run goals on, with one id | `runfile/registry.py:1-15`; architecture.md, opening |
| registration | The file naming a robot's profile, payload, navigator API and simulator folder | `runfile/registry.py:1-15` (registration 1, `:25`) |
| profile | One JSON file per robot: what it is | `runfile/profile.py:1`; RFC-0020 §3 |
| variant | What differs between environments (`sim`, `real`), merged onto the profile | `runfile/profile.py:4-5` |
| plugin | A Python class named in the profile, one of four interfaces: locomotion, range sensing, localisation, looking | RFC-0020 §4; `runfile/profile.py:11` |
| installation | What one machine holds that is not a robot's or a simulator's | `runfile/installation.py:1-4` |
| the gate | The one lock in front of a robot: lease, STOP, takeover, log | RFC-0017 §3; `robotgate/__init__.py:1` |
| lease, holder | The right to drive one robot, bound to a connection; the connection that has it | RFC-0017 §1 glossary, `:70-71` |
| the holder line | Mission Control's robot card line: who holds the robot, since when, what is left | PHASE5-NEXT-PLAN.md:252, :291 |
| STOP | Always accepted, ends the lease, latches | `apps/mission-control/CONTRACT.md:51`; RFC-0017 §3.4 |
| takeover | A named client takes the lease; the robot is stopped first | `apps/mission-control/CONTRACT.md:78` |
| deadman | The robot's own watchdog: no command for a short time stops the motors | RFC-0017:73; RFC-0003 §2.3 |
| driver | Whoever holds the lease and sends commands | RFC-0017 title and `:79`; `robotgate/__init__.py:1`; `CONTRACT.md:50` |
| robot interface | The `robot.*` methods the gate passes to a robot | RFC-0003 §2.1 |
| navigator | The brain: a goal in, a status out | architecture.md "The pieces"; `libs/runner/CONTRACT.md:1-12` |
| navigator contract | The JSON-RPC surface a navigator answers, versioned (1.2) | `libs/runner/CONTRACT.md:1-3` |
| payload | A navigator run as one process per course | RFC-0021 §3; `libs/runner/CONTRACT.md:29` |
| navigator API | Mission Control's navigator, one per goal | `libs/runner/CONTRACT.md:32` |
| runner, judge | The referee that runs courses; its rules judge by the truth | RFC-0021 §3; architecture.md "The pieces" |
| challenge, course | A goal list the runner runs; `lab-challenge` | RFC-0008; RFC-0022 §4 |
| scene, scene writer | `scenes/<id>/scene.json`; what turns it into a simulator's own files | RFC-0021 §3.1 |
| site, area | A place Mission Control knows, and the operator's regions in it | RFC-0014 §3.5 |
| run, tick, run file | One recording; its unit of records; format 2, MCAP | ADR-0007 `:18-27`, tick protocol |
| run store | The store of runs, one writer | RFC-0010; RFC-0019:34 |
| index | The derived index over the runs | ADR-0009; RFC-0019:32 |
| truth, belief | Where the robot really is (the runner's alone); where the navigator thinks | architecture.md "The rule everything follows"; `CONTRACT.md:61` |
| frame | A named coordinate frame: `site`, `world`, `map` | `apps/mission-control/CONTRACT.md:9`; `wire.py:264` |
| host, host kind, host file | A machine that runs a simulator; the kind of simulator; its file | `simhost/host.py:1`, `:25`; RFC-0021 §3, §3.1 |
| robotd, tofd, mapd | The duck's daemons: control, depth, map | RFC-0021 §3 (robotd, mapd); RFC-0023:26 (tofd) |
| Mission Control, adapter | The operator's panel; its code per robot type | RFC-0014; `mission_control/robots.py:21,400-412` |
| the Observatory | The viewer and its API, live and replay | architecture.md "The pieces" |
| `libs/web` | The shared web library (tokens, three.js, the robot body) | RFC-0024 |
| factsheet, capabilities | A robot's declared facts; what it offers (sensors, map, navigator, guardrails) | `runfile/profile.py:1`, `:135-139` |
| guardrail | A rule the navigator or its runner stops a goal for | `libs/runner/CONTRACT.md:24`, `:67` |
| anomaly, alarm | A recorded oddity; one raised live and shown on a timeline | RFC-0019; RFC-0024:27 |
| seam | A place where two projects meet through a contract | RFC-0018 title and §3 |
| piece | A part of the platform with a job | architecture.md "The pieces" |
| step | A numbered part of an RFC's build | RFC-0021 §5; RFC-0022 §6 |
| spike | A short experiment that settles facts | RFC-0015 §8; `docs/wip/PHASE0-SPIKE.md` |
| stub | A stand-in that proves a seam | PHASE5-NEXT-PLAN.md:45, `:379` |
| `lab-` | The prefix of the platform's commands | RFC-0022 §4 |

"Spike" and "stub" are the project's own, so this RFC keeps them. "Mapper" is used in the
project's notes for mapd's mapping part (`docs/wip/RANGE.md:69`); section 3.1 gives it a wider
meaning, and the second table says so.

### New terms, approved 2026-11-23

Each replaces a word from the note or a generic industry word.

| Term | Meaning | Why this word | Replaces |
| --- | --- | --- | --- |
| connector | The one program that joins a robot's own software (robotd, ROS 2, the NXT's HTTP) to the gate, and serves our robot interface for it | "Driver" is taken (above) and "adapter" is Mission Control's per robot type, in front of the gate. A connector sits behind the gate and plugs one robot in | RobotAdapter; ActuatorController (the command side); "driver" |
| interface join | A robot that joins at the robot interface: our navigator navigates it and sends `robot.move` | The seam it uses is the robot interface (RFC-0003). "Join" is plain and does not say who is better | "level 1", "integration level" |
| contract join | A robot that joins at the navigator contract: its own navigator navigates it | Same: the seam it uses is the navigator contract | "level 2", "integration level" |
| mapper | The part that builds a robot's map and its belief of where it is from its sensors: mapd for the duck, SLAM Toolbox for the Burger | The notes already call mapd's mapping part "the mapper"; one word for the job, whatever tool does it | MappingPlugin; "SLAM" as a part; "map provider" |
| companion streams | Streams stored in the run's folder beside `run.mcap`, listed in the run: images, depth images, a raw log | "Companion" says they travel with the run. The source log copied to `source/` (ADR-0007) is the first one | "side files" |
| model job | An offline job that builds a 3D model from a run's companion images by calling a tool's command line | A job, run after the run, outside the live path. It is not a plugin: our plugins are RFC-0020's | ReconstructionPlugin; "reconstruction worker" and "backend"; "glue" |
| wrapper | A small program that makes a robot's own navigator answer the navigator contract | A wrapper wraps; nothing in the project uses the word for this | "shim" |

Existing terms that take over the rest of the note's and the industry's words:

| Borrowed word | Our term instead |
| --- | --- |
| SimulationAdapter, "simulator backend", "backend interface" | host kind (`simhost`) |
| WorldAdapter, "the world as the source" | the scene (`scene.json`) and a scene writer per host kind |
| SensorProvider | the profile's `capabilities.sensors`, declared; sockets for the duck today |
| "capability discovery" | the profile's `capabilities` block |
| "a simulated robot and a real one" | one robot, two variants (`sim`, `real`) |
| "role", "surface" | piece; view (RFC-0020 §5, RFC-0023) |
| "stage" (of this RFC) | step |
| "worker", "teleop" as our concept | job; driving by hand from Mission Control |

## 1. Why

The operator, 2026-11-23: "By the time we get to Gazebo and Burger, we're going to be MVP version 1.
And then we are evolving architecture to fit MVP version 2." And: "I need a proper
architectural evolution, and we think of it as stepping up the game because things are working
well so far."

- **MVP 1** is everything with the Microduck (legged, MuJoCo simulator, Pollen's `robotd`, our
  plain-Python navigator) and the Lego NXT, in the current ecosystem.
- **MVP 2** is a TurtleBot3 Burger (ROS 2, arriving about a week after 2026-11-23), with more
  sensors, starting in a simulator (Gazebo Sim). The operator's answers add three things: our own
  navigator drives the Burger and the NXT too, not only the duck (questions 5 and 6); the real
  Burger drives from Mission Control before MVP 2 ends (question 8); and the platform's
  connectors can be placed on the robot or on the workstation, per robot (question 1). The NXT's
  link goes USB, then Bluetooth, then a Pi-based augmentation module with modern sensors on the
  robot, which is MVP 2 (NXT-MVP1.md, the operator's answers; section 3.10).

The operator's intent, in their words: "robotd and ROS are two versions of the same thing and I
need to be able to support more. This is not Pollen's style with ROS bolted on, but a platform
that supports all approaches and these two at the start." And: reflect on architecture first, do
not build.

So this RFC does three things. It says where the platform is (section 2). It says where it should
go (section 3). It names the tools around it and the hard problems on the way (sections 4 to 8).
It does not decide; it ends in questions (section 9).

Non-goals:

- No platform code before the RFCs. Step 0b (section 6) was a zero-platform-code spike. It ran on
  2026-11-23 (section 9, question 14); its notes are `docs/wip/MVP2-SPIKE.md`, read for this
  draft. Its throwaway connector and Observatory ran outside the repository (spike §20).
- Changing how the duck works. MVP 1 keeps running at every step (section 6).
- Choosing the versions anew: the spike decided them (section 8.10).

In this RFC "step N" means a step of section 6. A step of another document is always named
("plan step 7", "RFC-0021 step 2").

## 2. The architecture of MVP 1 (point A)

### 2.1 The pieces and their jobs

| Piece | Where | Job | Neutral? |
| --- | --- | --- | --- |
| Goals and missions | `apps/mission-control` (`core.py`, `store.py`) | Goals, sites, the lock, STOP, the robot page | Mostly |
| Robot adapters | `apps/mission-control/src/mission_control/{robots,duck,nxt,fake}.py` | One adapter per robot type: `fake`, `duck-sim`, `nxt-web` (`robots.py:400-412`) | By type |
| The gate | `libs/gate/src/robotgate/__init__.py` | Lease, STOP, takeover, log, in front of a robot | Rules yes; method names no |
| Navigator contract | `libs/runner/CONTRACT.md`, `runfile/navcontract.py` | Goal in, status out, version 1.2 (`navcontract.py:4`) | Mostly |
| Runner and judge | `libs/runner` (`labrunner`) | Runs courses, judges by truth, copies the official run | Partly |
| Navigator | `robots/duck/src/duck_lab` | The duck's planner, explorer, world model, plugins | No (the duck's) |
| Robot description | `robots/duck/{registration.json,profile.json,robot.urdf}` | Who the robot is: files and numbers | Schema is duck-shaped |
| Simulator host | `libs/simhost` | Host file, reset, truth reader | One kind only |
| Scene | `scenes/<id>/scene.json`, `robots/duck/sim/apartment_layout.json` | Bounds, rooms, drops, boxes | Half |
| Run store | `libs/runfile` (MCAP, format 2) | One writer, tick protocol, index | Mostly |
| Observatory | `apps/observatory` | Reads and replays runs | Mostly |
| Shared web | `libs/web` (RFC-0024 steps 1, 2) | Tokens, three.js, the robot body | Yes |
| The NXT | `apps/nxt-web` | HTTP API and its own lock over the brick | No (HTTP) |

### 2.2 The contracts between them

Each has a number, which is the platform's strongest habit. A reader accepts its own and older
ones and refuses a newer one (RFC-0018 §5.3).

| Contract | Version | Where |
| --- | --- | --- |
| Gate protocol | 1 | `robotgate/__init__.py:18` |
| Navigator contract | 1.2 | `runfile/navcontract.py:4` |
| Run file | format 2 | ADR-0007 |
| Robot registration | 1 | `runfile/registry.py:25` |
| Robot profile | 1 | `runfile/profile.py:163` |
| Host file | 1 | `simhost/host.py:24` |
| Installation file | 1 | `runfile/installation.py:25` |

The robot interface itself (`robot.move`, `robot.state` and so on) has no number and no written
contract. RFC-0003 §2.1 says "Use the duck's contract as the reference", and RFC-0017 §3.1 says
the gate "forwards the call unchanged (RFC-0003's method shapes are not touched)". Its only
written form is the duck's behaviour.

### 2.3 A picture

```text
 operator
    |
    v                                           reads runs (read only), follows live
 Mission Control :8060 --- libs/web ---------- Observatory :8070
    |  adapter by type: fake | duck-sim | nxt-web          ^
    |                                                      | run.mcap (format 2)
    v                                                      |
 GATE (lease, STOP)  <-- robot.* methods, robotd's shape   |
    |                                                runner + judge (libs/runner)
    |  robotd socket (duck)    HTTP (NXT)                  |   copies truth into the run
    v                                                      |
 duck-sim: robotd + tofd + mapd  <-- host file ------- simhost (kind pollen-duck-sim)
    ^                                  reset, truth_port --'
    |  sockets: robot, depth, map, camera
 navigator (duck_lab + 4 plugins) <-- navigator contract 1.2 --> runner / Mission Control
```

### 2.4 How robot-neutral each layer is

Neutral enough to keep:

- The run store. `libs/runfile/src/runfile/truthcopy.py:16`: "Nothing here knows a robot or a
  simulator: a truth is a pose by wall-clock time."
- The judge reads the profile, not constants (`labrunner/evaluate.py:73`: footprint, fall height
  and reach tolerance come from `prof`).
- The navigator contract is a small JSON-RPC surface (`navcontract.py:15-18`). A navigator needs
  five goal methods; the payload adds `localise` and `stop`, the API adds `map`, `state`,
  `objects`, `inventory`.
- Mission Control picks an adapter by type (`robots.py:400-412`); the Observatory reads only the
  run format (RFC-0021 §3.1).
- The registry: a robot is a file naming its profile, two commands and a simulator folder
  (`registry.py:8-15`). Nothing is installed into Mission Control to add one.

Shaped by the duck, MuJoCo or `robotd`:

1. **The gate's robot methods are robotd's.** `OPEN_METHODS` names `robot.state`,
   `robot.subscribe`, `robot.health`, `tof.frame` (`robotgate/__init__.py:23`). `STOP_METHOD` is
   `robot.stop` (`:24`). `ZERO_MOVE` has `vx`, `vy`, `vyaw` (`:25`). The stop sequence is
   `robot.stop` then an explicit zero move because "robotd keeps its last request after the
   deadman fired" (`:261-265`). Mission Control's drive sends `vy: 0.0` (`robots.py:377`).
2. **The adapter's surface is implicit.** `RobotRuntime` calls `make_gate`, `make_navigator`,
   `state`, `health`, `map`, `map_version`, `sighting`, `watch_url`. Three adapters implement
   them (`nxt.py:150-223`, `duck.py:320-463`, `fake.py`). This is the connector's interface,
   unwritten. The duck's `state()` reads robotd's `odom.position`, `odom.yaw` and scales by the
   profile's 0.91 (`duck.py:416-424`). robotd has no `robot.state` request, only the
   subscription (`duck.py:11`).
3. **The NXT is already a second connector, in HTTP.** `NxtGate` offers the in-process gate's
   interface over nxt-web's lock (`nxt.py:38-147`); `robot.move` becomes track power
   (`nxt.py:117-120`). It has no navigator (`nxt.py:178-179`) and no map (`nxt.py:216-217`).
   RFC-0018 §10 notes its lock "keeps its own copy of the gate's rules over HTTP".
4. **The profile requires duck-shaped blocks.** `REQUIRED` includes `footprint`, `locomotion`
   and `plugins` (`profile.py:235`). `locomotion` fields include the kick and pivot rules
   (`profile.py:179-189`). There are exactly four plugin interfaces: locomotion, range sensing,
   localisation, looking (`profile.py:165`). The `sensors` schema knows `tof8x8` and `camera`
   only (`profile.py:190-201`). `joints.names` is the duck's 15 (`profile.json:8-10`).
5. **The host has one kind.** `KINDS = ("pollen-duck-sim",)` (`host.py:25`). The host file must
   name Pollen's two checkouts (`host.py:94-96`). The sockets are five fixed names: robot,
   depth, map, gate, camera (`host.py:28-29`). A reset restarts the whole simulator (about 40 s)
   and puts the duck at (0, 0) facing +x (`simulator.py:1-6`). The truth reader's hello says
   `joints: 15` (`truth.py:43`).
6. **The run file knows one sensor.** `SENSOR_FRAME = "tof"` (`wire.py:91`). Frames are fixed:
   `/belief/pose`, `/depth`, `/map` in `map`, `/truth/pose` in `world`, `/depth/raw` in `tof`
   (`wire.py:264-265`). The raw frame is an 8x8 grid of 16-bit distances (`wire.py:358-361`).
   Depth kinds are `f`, `o`, `v`, `b` (ADR-0007).
7. **The scene is the duck's layout.** Five readers open `apartment_layout.json` through the
   robot's `sim` folder: `geometry.py:27`, `evaluate.py:75`, `explore_score.py:217`,
   `guard.py:32`, `sim_camera.py:49-50`. The layout is a list of MuJoCo geoms; the Observatory's
   `Truth` depends on geom names `stair*`, `floor_*`, `lm_*` (`observatory/anomalies.py:85-100`).
   Item 2 of the plan already moved bounds, rooms and drops into `scenes/apartment/scene.json`;
   the obstacles did not follow.
8. **The goal has no heading.** The `point` goal is `params {x, y}` (`CONTRACT.md:45`).
9. **Time is wall time.** The truth is paired to ticks by `wall_ns`, within 0.1 s
   (`libs/runfile/src/runfile/truthcopy.py:26`). The sampler's `Sample` carries `sim_time` and
   the real-time factor is read from it (`truth.py:7-9`), but nothing pairs by it. The gate takes
   both a monotonic and a wall clock (`robotgate/__init__.py:102`).
10. **The Observatory's anomaly vocabulary.** `ROBOT_KINDS` (`observatory/anomalies.py:639`) is
    not a list of robot types: it lists the anomaly kinds a robot raises, and several are the
    duck's own (`mapd_lost`, `head_off_walk`). A second robot adds its kinds there.

## 3. The architecture of MVP 2 (point B)

### 3.0 Pieces in MVP 2

The next sections use these pieces. A piece is a job, not a process: one process may hold two.
"New" means the contract does not exist yet and a follow-up RFC would write it.

| Piece | Owner and where | Inputs | Outputs | Contract and version |
| --- | --- | --- | --- | --- |
| Connector | Ours; one per robot; for the Burger a ROS 2 node process, placed per robot (section 3.8); the deadman's home in the simulator (section 3.3) | `robot.*` calls (interface join); gated `cmd_vel` (contract join); the robot's topics | Velocity to the base; `robot.state`, `robot.health`; sensor streams | Gate protocol 1 (existing); robot interface 1.0 (new: RFC-0026) |
| Navigator, ours, for any robot | Ours; today the duck's (`duck_lab.nav`); to drive a legged, a differential-drive and a tracked robot through per-kind plugins (section 3.7) | Goal; sensor streams; `robot.state` | `robot.move`; status; `map` | Navigator contract 1.2 (existing); plugin interfaces (RFC-0020, existing; widened by RFC-0027) |
| Sensors, declared | Ours; in the profile, per robot and variant (section 3.9) | Hardware, or a host kind's simulation | Streams per sensor kind: the scan in the run, images in companion streams | Profile v2 (new: RFC-0027) |
| Mapper | Per robot: mapd (duck); SLAM Toolbox (Burger, first); mapd on the NXT's Pi module, from its depth camera (section 9, question 16) | Range sensing; odometry | A map; the belief of where the robot is | Behind the navigator contract's `map`; localisation plugin |
| Navigator, the robot's own (Burger, later) | Nav2 with SLAM Toolbox as its mapper, behind a wrapper | Goal (as a Nav2 action); `/scan`, `/odom`, tf | Gated `cmd_vel`; goal outcome; map grid | Navigator contract, a version after 1.7, with `yaw` (new: RFC-0029; 1.3 shipped as calibration) |
| Host kind | A kind in `simhost`; for the Burger `gazebo-turtlebot3` | Reset, a scene, the robot's commands | The robot's topics; truth; the real-time factor | Host file 1 (existing); host kind contract (new: RFC-0028) |
| Scene | `scenes/<id>/scene.json`; a scene writer per host kind | Bounds, rooms, drops, boxes | MJCF, SDF | Scene file (existing); the scene as the source (new: RFC-0028) |
| Runner and judge | `libs/runner` | Course, navigator, truth | Verdict; the official run with truth copied in | Navigator contract; run file format 2 (existing) |
| Run store | `libs/runfile` | Ticks, events, maps; companion streams | `run.mcap` plus `streams/` | Run file format 2 (existing); companion streams (new: RFC-0028 or an ADR-0007 note) |
| View: Mission Control | `apps/mission-control` | Adapter state; the gate | Goals, lease, STOP, the robot page | Adapter surface (existing, unwritten; RFC-0026 writes it) |
| View: the Observatory | `apps/observatory` | Run files, live follow | Replay, analysis | Run file format 2 (existing) |

A picture of MVP 2 in the style of section 2.3. Both ways of joining are drawn. The Burger takes
the interface join first (our navigator) and the contract join second.

```text
 operator
    |
    v                                           reads runs (read only), follows live
 Mission Control --- libs/web --------------- Observatory
    |  adapter by type: fake | duck-sim | nxt-web | ros-burger        ^
    v                                                                 | run.mcap + streams/
 GATE (lease, STOP)  <-- robot interface 1.0 (new)                    |
    |                                                         runner + judge
    v                                                                 |  truth copied in
 CONNECTOR (one per robot)  <-- host file --- host kind --------------'
    |   robotd (duck)   HTTP (NXT)   ROS 2 node (Burger)      kind: pollen-duck-sim | gazebo-turtlebot3
    |                                  |  ^ gated cmd_vel (contract join)  ^
    |                                  v  |                                | scene from scene.json
    |                          navigator wrapper <-- contract 1.8+ --> Nav2 + SLAM Toolbox
    v
 interface join: our navigator <-- contract 1.2 --> runner / Mission Control
```

### 3.1 The vision note's seven interfaces, in our words

The vision note (section 10) names seven interfaces. Most already exist here under our own names.
The job is to translate and fill gaps, not to start again. This is the one place the note's names
are used.

| The note's name | The idea, in one plain phrase | Our term | Where it lives |
| --- | --- | --- | --- |
| RobotAdapter | The one way commands reach a robot | The connector: one per robot, behind the gate. Today: registration, profile and Mission Control's adapter | Behind the gate; `registry.py`; `robots.py` |
| SimulationAdapter | What knows one simulator: reset, truth, scenes, the clock | The host kind: reset, truth, scene writer, real-time factor | `libs/simhost` |
| SensorProvider | A robot's sensors, each with a stream, a frame, a calibration | Sensors declared in the profile's `capabilities`, each with a stream, a frame and a calibration | Profile; the host file's sockets today |
| ActuatorController | Turning a wanted motion into the robot's command | The connector's command side, and the locomotion plugin; absent for a robot that navigates itself | Connector; `duck_lab/plugins` |
| MappingPlugin | Building the map and the belief of where the robot is | The mapper, behind the navigator contract's `map`: mapd for the duck, SLAM Toolbox fits here | `mapd@1`; the navigator API's `map` |
| ReconstructionPlugin | Building 3D models from recorded images, afterwards | A model job over a run's companion streams, outside the live path | Nothing yet (section 5) |
| WorldAdapter | One description of the place, written out per simulator | The scene (`scene.json`); each host kind writes its own format from it | `scenes/<id>/scene.json`; a scene writer per kind |

The note says robots need not all have identical actuators, and that the platform should ask each
robot what it has. That is what the profile's `capabilities` block already does
(`profile.json:209-221`). It has a `sensors` slot that is empty for the duck. The note also says
a shared model of the place does not mean MuJoCo and Gazebo share one physical simulation. That
is the same split as RFC-0021 §3.1: the host kind holds everything that knows a simulator.

### 3.2 Two ways a robot joins

A robot joins at one of two seams. Both are valid. The operator's answer: both are first-class,
and OUR navigator comes first (question 6). For the Burger, the interface join with our
navigator comes before the contract join with Nav2.

- **An interface join, "we drive it".** A connector sits at the robot interface. Our navigator,
  in plain Python, plans and sends `robot.move`. The duck is this today. The NXT is this at the
  interface (it takes `robot.move`), but it has no navigator. RFC-0020 §6 step 5 planned tracked
  plugins for one and has not started. The operator's answer (question 5): the NXT gets our
  navigator as part of MVP 2.
- **A contract join, "it navigates itself".** The robot's own stack (for the Burger, Nav2 with
  SLAM Toolbox) sits behind the navigator contract. Mission Control and the runner see `hello`,
  `goal.start`, `goal.status`, `goal.cancel`, `goal.break`, `map`, `state`. ADR-0020 decision 1
  says this. It comes second for the Burger.

```text
 INTERFACE JOIN: we drive it             CONTRACT JOIN: it navigates itself
 goal -> our navigator (plugins)         goal -> wrapper speaking navigator contract
            | robot.move                              | goal (Nav2 action)
            v                                         v
   GATE -> connector -> robot                 Nav2 + SLAM Toolbox
                                                      | cmd_vel into the CONNECTOR, not the robot
                                                      v
                                            GATE -> connector -> robot
```

The Burger joins both ways, in this order: the interface join, then the contract join.

| | Interface join needs | Contract join needs |
| --- | --- | --- |
| Connector | A ROS 2 connector: `robot.move` to `/cmd_vel`, `/odom` to `robot.state`, STOP; the last-hop watchdog (section 3.3) | The same connector. Same lease, same STOP |
| Navigator | Our navigator for any robot (section 3.7) with a differential-drive locomotion plugin, a 2D-scan range plugin and a localisation plugin | A wrapper: `goal.start` to a Nav2 action, its outcomes mapped to our ends (RFC-0015 §3.5 has the map), `map` from SLAM Toolbox's grid |
| Contract | Profile accepts a robot with no head, no mapd, a scan sensor | A contract version after 1.7: `point` gets `yaw` (`libs/runner/CONTRACT.md`, "A goal") |
| Safety | Lease held by the navigator | Lease held by the wrapper for the goal's duration |

The "Safety" row is where the two joins meet. If Nav2 publishes `/cmd_vel` itself, anyone on
that ROS graph can drive, and the gate is bypassed. ADR-0020 decision 2 says the connector is the
sole publisher to the robot. On DDS that cannot be a guarantee: any node
in the domain can publish `/cmd_vel`. It is narrowed by convention and watched, as section 3.3
says: Nav2's output is remapped to a connector input, and the connector forwards it only while
the lease holder is the wrapper.

The NXT joins at the interface today: a connector with no navigator. It is the proof that a third
connector, with neither robotd nor ROS behind it, passes through the same interface.

### 3.3 The robot interface as ours

ADR-0020 decision 2 says neither robotd nor ROS is the platform's interface, ours is. A written
contract, "robot interface 1.0", would hold:

- **Two inputs.** The connector of a ROS robot takes commands from two places. Interface join:
  JSON-RPC `robot.*` (driving by hand and our navigator). Contract join: the gated `cmd_vel` from
  Nav2. Arbitration: the lease holder's commands win, and STOP zeroes both inputs.

- **Safety.** `gate.acquire`, `release`, `keepalive`, `takeover`, `who`; STOP from any
  connection, always, latching; a lease ends on release, expiry, STOP, takeover or disconnect, and
  every end stops the robot first (`robotgate/__init__.py:1-6`). The deadman (a robot stops when
  commands stop, 0.5 s on the duck, RFC-0003 §2.3) is **a last-hop watchdog that runs on the
  computer wired to the motor controller, in every placement**. On the real Burger it is a
  small node on the Pi that forwards `/cmd_vel` only while commands are fresh and publishes
  zero otherwise; in the simulator it is the connector itself. A connector on the workstation
  cannot stop a robot over a dead link, so the watchdog is not the connector's when the two
  sit on different computers. Decided, from the spike: the Gazebo diff-drive plugin holds the last
  velocity forever (0.1500 m/s unchanged 6 s after the last command, spike §8), and the ROS 2
  OpenCR firmware has no `cmd_vel` timeout (it holds the value; only a dead node trips a 500 ms
  heartbeat; spike §8, read from source, not run on a real robot). Through the spike's connector
  the applied velocity was zero 0.6 s after the last command (spike §20 part 1). The 500 ms
  timeout the advisor recalled is true for the older ROS 1 firmware (spike §8), not for ROS 2. Which
  firmware is flashed on the operator's Burger is unknown (spike §8).
- **State.** `robot.state`: pose in the connector's odometry frame, velocity requested and
  applied, mode, flags (fallen, picked up, limp), battery, link. Today's keys are in
  `DuckAdapter.state` and `NxtAdapter.state` (`duck.py:416-429`, `nxt.py:200-210`).
- **Health.** `robot.health`, polled every 10 s today (`duck.py:33`).
- **Commands.** `robot.move {vx, vy, vyaw}`; `vy` is ignored on a robot whose factsheet says it
  cannot move sideways. `robot.stop`. `robot.do {skill}` for what a robot offers (RFC-0003
  §2.1).
- **Sensors declared in `capabilities`.** A robot lists the sensors it has, each with an id, a
  kind, a stream, a frame, and a calibration reference. Today the slot exists
  (`capabilities.sensors`) and is empty for the duck (`profile.json:210`); the duck's depth
  arrives by a socket the host names, not by declaration.

The ROS connector is a ROS 2 node process, one per robot. It (a) is the gate's robot: it serves
`robot.*` over the gate socket; (b) subscribes the gated `cmd_vel` and forwards it only while the
navigator wrapper holds the lease; (c) can host the navigator-contract wrapper. This shape comes
from the advisor's review; no code of it exists.

How each robot gets a connector:

| | robotd (duck) | ROS 2 (Burger) | NXT |
| --- | --- | --- | --- |
| Command | `robot.move` passes through | `robot.move` to `/cmd_vel` | `robot.move` to track power (`nxt.py:184-187`) |
| State | `robot.subscribe` stream | `/odom`, `/imu`, `/battery_state`, joint states | `/api/status` poll (`nxt.py:189-210`) |
| Deadman | robotd 0.5 s | **a last-hop watchdog on the computer wired to the base** (a node on the Pi; the connector in the simulator): neither the simulator nor the ROS 2 firmware times out (spike §8) | robotd-lite on the brick, 0.5 s (RFC-0003 §2.3) |
| Lease | the gate process | the gate process | nxt-web's lock over HTTP |
| Sensors | 8x8 depth socket | `/scan`, later camera topics | ultrasonic, colour (RFC-0003) |

The honest list of what differs, so the contract does not pretend otherwise:

- **ROS topics are open.** Any node in the DDS domain can publish `/cmd_vel`; the sole
  publisher is not a property we can build in. robotd has "other doors" too (RFC-0017 §3.2:
  Pollen's app, the gamepad, `autod`), and the gate is "a convention that all of *our* programs
  follow" (§3.2 end). On ROS the doors are wider. So the rule is narrowed by convention and
  watched, in four parts. The connector remaps the base's input to a topic only it publishes. It
  owns the one place where Nav2's and any hand-driving velocity meet (ROS has a tool for that,
  `twist_mux`; not verified in this repo; it arbitrates between sources and does not stop a
  robot, so the watchdog above is a separate piece). It watches the graph for other publishers and raises
  `someone_else_drives` (RFC-0017 §3.2). And it isolates the robot's graph by `ROS_DOMAIN_ID`. A
  real boundary would be SROS2; that is out of scope.
- **ROS has a clock of its own.** Simulation stamps against our wall clock (section 3.6).
- **ROS has frames and a tf tree.** `map`, `odom`, `base_link`. ADR-0001 decision 2 already
  aligned names. Section 3.6.
- **ROS lets a node list the graph.** A graph lists topics; robotd has fixed methods. The
  connector exposes only the capabilities the profile declares, not the graph.
- **Velocity is held after silence on robotd** (hence the explicit zero, `:261-265`). A ROS
  diff-drive base does the same (spike §8). The gate's own stop, `robot.stop` then an explicit
  zero `robot.move {vx, vy, vyaw}` (`robotgate/__init__.py:313-319`), ran unchanged against the
  spike's connector, which accepted both (spike §20). The connector publishes zero on STOP; the
  watchdog publishes zero when a command goes stale.
- **`/cmd_vel` is `TwistStamped` in the Jazzy Gazebo bridge,** not `Twist` (spike §3). A plain
  `Twist` publisher does not connect. The real `turtlebot3_node` (Jazzy) subscribes `Twist`
  unless `enable_stamped_cmd_vel` is true (the advisor, from `twist_subscriber.hpp:33-39, 86`;
  not run; the Pi's node version is not verified). Proposed: the real bringup sets
  `enable_stamped_cmd_vel: true`, so one output serves both, or the type is a variant setting;
  step 10 checks it. Nav2's output and `explore_lite` publish `Twist`, so the connector
  owns a `Twist` to `TwistStamped` relay: the spike used a 15-line relay and moved the collision
  monitor's output to `cmd_vel_raw` (spike §18). That is the same "remap to a topic only the
  connector publishes" as above. `Twist` commands straight into the bridge were not tested
  (spike §17).

Where the code goes: the gate library needs two small changes (method names from the interface
contract, not constants; the stop sequence from the connector's declaration). `RemoteGate` and
the JSON-RPC wire in `duck.py:51-212` are already generic except for `DuckAdapter.state`. The
Burger's connector can speak the same socket protocol and reuse them. RFC-0015's `nav2/bridge.py`
(the duck-to-ROS bridge, §3.2) is the same idea in the other direction and a prior art; ADR-0018
calls it "a candidate ROS 2 driver for Mission Control" (its word for what this RFC calls a
connector).

### 3.4 The simulator as a host kind

Are a simulated Burger and a real Burger one robot in two variants? Mostly yes, and it is how the
duck already works: the `duck-sim` adapter and a real duck differ in the host and the variant,
not in the profile's identity (`robots.py:92-99`, the installation's `variant`). For the Burger:

- One robot id, one profile with variants `sim` and `real`, as for the duck (`profile.json:224`).
- Two connectors of the same type, differing in where they connect: Gazebo's bridge (through
  `ros_gz`) or the real Burger's ROS graph. Where each runs is a per-robot setting (section 3.8).
- The host kind (Gazebo) is separate from the connector: it provides reset, truth and the scene.
  The connector does not know it is in a simulator.
- A course reset must also reset the mapper's state, or the new run starts on the last run's map.
  It is the Burger's equivalent of a fresh `mapd` after the duck's reset. SLAM Toolbox has a
  service for it, `/slam_toolbox/reset`: after the call its map changed from 81 x 103 to 79 x 102
  cells, so it re-initialised, but the spike did not compare the maps or try a long map
  (spike §9). SLAM Toolbox itself coped with the clock going back ("Detected jump back in time.
  Clearing TF buffer", spike §9). Nav2's costmaps after a reset were not tried (spike §17), and
  whether a lifecycle restart is enough stays not verified. The spike's reset run called only
  `reset all` and never `/slam_toolbox/reset`, so it did not test this design (spike §21 re-ran
  it with the full sequence).
- **The reset design, decided** (spike §9). A world reset (`reset: {all: true}`) takes about 0.26 s
  and sends the sim clock to 0, but only if the robot is part of the world file: with the stock
  launch, which spawns the robot after start, the reset deleted the model, `/odom` and `/imu`
  stopped, and a respawn crashed the Gazebo server. So the host kind starts Gazebo from a world
  that includes the robot and resets with `reset all`; a restart of the Gazebo container is the
  fallback (48 s, measured once). `set_pose` does not reset odometry; a world reset does.
  `reset: {model_only: true}` had no visible effect. Odometry after a world reset on a robot in
  the world file was back to 0 (the model pose itself was not read, spike §9). The host then
  starts `robot_state_publisher` separately, because the world-file variant has none (spike §9).
- **A reset returns only when the simulator is settled.** Decided (the operator confirmed,
  2026-11-23; step 4, section 6.0). For Gazebo: the first post-reset
  `/odom` and a `map`-to-`odom` with a post-reset stamp have arrived. The spike's `sleep 4` was
  a placeholder. The NXT's kinematic simulator will not teach this contract.

Fit with the host model (RFC-0021 §3.1): a host kind provides four things. Reset, the robot's
connections, a truth reader, a scene writer.

| | `pollen-duck-sim` (built) | `gazebo-turtlebot3` (planned, RFC-0021 §3.1) |
| --- | --- | --- |
| Reset | restart duck-sim, about 40 s (`simulator.py:1-6`) | `reset all` on a world that holds the robot, about 0.26 s, plus `/slam_toolbox/reset`; a container restart as the fallback, 48 s (spike §9) |
| Connections | five socket paths (`host.py:28-29`) | ROS topics through the bridge |
| Truth | Pollen's body server, trunk pose plus z and quaternion (`truth.py`) | the model's pose from Gazebo. The spike read it through `gz topic --json-output` because the bridge drops entity names (spike §20); that reader crashed after a reset (section 3.6). Decided (the operator confirmed, 2026-11-23): an `OdometryPublisher` (or `PosePublisher`) plugin on the Burger model, bridged as `nav_msgs/Odometry` with the sim stamp through the host kind's bridge (not verified) |
| Scene writer | MJCF from Pollen's `scene_backlash.xml` | SDF world from `scene.json` |
| Real time | RTF measured, runs at 1.0 (RFC-0021 §6) | RTF 1.00 in every sampled run with SLAM Toolbox (the wall-following run's was not sampled, spike §6), about 0.7 of one core and 0.6 GiB; 10 reachable when asked (spike §6); recorded per run (ADR-0020 decision 3) |

The host module is still one library (RFC-0021 §3.1: "a module per kind comes with the second
kind"). The host file schema needs a per-kind part: `pollen` is required today (`host.py:94-96`).

Truth for a wheeled robot is simpler, but the judge's vocabulary is legged. The judge asks for a
"trunk height" and a fall threshold (`profile.json:188`, `profile.py` `judge` block). A wheeled
robot's fall is a tilt. This is a profile change (section 7).

What `simhost` needs for the Gazebo kind (spike §20, table; lines as read on 2026-11-23, not
edited): in `simulator.py:25-79` (`duck_sim`, `reset`, `down`), a Gazebo host kind whose reset is
`reset all` on a world that already holds the robot, with a restart as the fallback; in
`truth.py:26-35` (`Sample`, `Body`), a Gazebo reader of the true pose with `sim_time`
(`Sample.sim_time` at `:32` already exists). The spike's reader costs visible CPU: the truth stream
is 58 messages a second of 8 entities and the reader was a `gz topic` subprocess (spike §20), so the
reader is a model plugin (the Truth row above), not a subprocess. The host kind also says which
sensor kinds it can simulate (section 3.9); spike §16 proposes that a profile asking for more fails
at the start instead of running without it. That is a proposal, not something the spike tested.

### 3.5 Sensors, mapping, 3D models

The operator's answer (question 3): LiDAR, IMU and wheel odometry now; no camera channel until a
camera is chosen; the recording rules for images are written down now (section 5) and not built.
So MVP 2 starts with these sensors on the Burger:

- The 2D LiDAR: `/scan`. Which model is on the arriving kit is not known here.
- The IMU: `/imu`.
- Wheel odometry: `/odom`, and the joint states.

The operator added (2026-11-23): "One of my first upgrades will be to add RGB camera and depth
camera and other things ... for simulator we should start exactly as we say. And then once the
actual robot comes in, we'll be doing physical modifications on improving the eyesight so we can
actually do 2D and 3D mapping of way better quality." So question 3 stands for the simulator
start. The camera step is no longer "later, undecided": it follows the real Burger's arrival, as
one of the first hardware upgrades (an RGB camera, a depth camera, other sensors).

The sensor layer is therefore designed for cameras from the start, and built for the scan, the
IMU and odometry first. Designed now, in the profile v2 (step 2) and the run's companion
streams:

- Declared sensors, each with a kind, a mount (extrinsics), intrinsics, a rate, and noise per
  variant (`sim`, `real`).
- Companion streams for images (section 3.6), never in `run.mcap`.
- Calibration records, one per sensor per run.

Only the scan, the IMU and odometry are built in MVP 2's first steps. The camera pieces are not
built until the step 11 camera is chosen.

The vision note's roadmap, against that:

| The note's roadmap step | Needs | When |
| --- | --- | --- |
| 1: simulated 2D mapping | `/scan`, `/odom`, tf, a map; Gazebo; SLAM Toolbox as the mapper | MVP 2 start |
| 2: errors | The mapper's pose against the simulator's truth (done once in the spike, spike §18; the platform's version is step 8) | MVP 2, early |
| 3: simulated RGB-D, RTAB-Map | camera streams, intrinsics, extrinsics | step 11, after the real cameras are chosen (question 22) |
| 4: physical mapping | a real depth camera, bandwidth, calibration | one of the real Burger's first upgrades (step 11) |
| 5: 3D models of objects from photos | overlapping photos | a separate project (section 5) |
| 6: scan goals | a way to send the robot to chosen viewpoints | later |

The advisor's "do not build yet" list, which this RFC keeps:

- No interface for building 3D models (nothing reads one yet; ADR-0020 consequences).
- No image channels in `run.mcap`, ever (ADR-0020 decision 5). Images are companion streams.
- No camera code, and no filled-in camera intrinsics or extrinsics, before a camera is chosen.
  The schema leaves room for them now (section 3.5).
- No pause, step or simulated clock in the platform (ADR-0020 decision 3).
- No `lidar2d` schema until the first stub draws it.
- No generalisation of the sensor schema beyond the one sensor that is real (the Burger's
  scan), because a schema drawn from one example fits that one.

The 2D scan in the run needs care. ADR-0020 said a scan "fits today's tick records"; the spike
shows it does not, without a change (spike §20). `/depth` is a point cloud in the `map` frame with
a kind per point (`wire.py:264`, ADR-0007). A scan stored as obstacle points loses the rays, so
free space and maximum range are gone, and those are what debugging a mapper needs. The
operator's answer (question 11): the Observatory draws the 2D scans and the maps, from a scan
channel in the run. What the spike found:

- `foxglove.LaserScan` exists (spike §10; from Foxglove's docs page, fetched 2026-11-23). Its
  fields are `timestamp`, `frame_id`, `pose`, `start_angle`, `end_angle`, `ranges` and
  `intensities`. It has no `angle_increment`, no `range_min` and no `range_max`: the step is
  derived from the two angles and the count, and the sensor's range limits are lost on
  conversion (spike §10). ROS's `sensor_msgs/LaserScan` also has `scan_time`, `time_increment`
  and float32.
- `wire.py` cannot take a scan channel unchanged. A channel needs a topic and schema in `CHANNELS`
  (`wire.py:21`), a record kind in `KINDS` (`wire.py:19`), a branch in `to_messages` (which ends in
  `raise ValueError` at `wire.py:253`), a place in the tick protocol (`TICK_PARTS` `wire.py:260`,
  `INSIDE` `wire.py:266`), a `PROTO` entry (`wire.py:48`) and schema registration in
  `mcapio._channel` (`mcapio.py:268-273`). A scan point kind also needs a name in the viewer
  (`validate.py:65`: the depth point kind is one character) (spike §20, table).
- The spike did not modify any of that. Its scan went out as `/depth` points, each beam's end in
  the `map` frame, kind `o`, z 0.1 m, with `angle_min`, `angle_increment`, `range_min` 0.12,
  `range_max` 3.5, `n` 360 in the tick's `raw.scan`; the Observatory drew them as "Depth obstacle"
  (spike §20 part 3, part 4).
- Not verified: that our Lichtblick viewer draws `foxglove.LaserScan` (the page says the 3D panel
  does), and a ROS bag with `sensor_msgs/LaserScan` in a viewer (spike §10).

Section 8.7 poses the choice (a scan channel, or points) and question 23 asks it. The advisor's
recommendation is in 8.7: a channel, with points until step 8.

In Gazebo, the simulated sensors come from its sensor plugins. The spike's camera was a sensor of
type `rgbd_camera` (spike §19), so that name is confirmed. The advisor's `gpu_lidar` for the scan
is not confirmed: the spike says only "lidar sensor plugin" in the SDF (spike §14). They are
Gazebo's plugins, not RFC-0020's.

What the spike measured of the Burger in Gazebo, so the sensor layer designs from numbers (one
workstation, no GPU, single runs; spike §20 end):

| Sensor | Shape and rate in the simulator | Source |
| --- | --- | --- |
| `/scan` | 360 beams, 0 to 6.28 rad, 0.12 to 3.5 m, 5.0 Hz, frame `base_scan` | spike §4 |
| `/odom` | `odom` to `base_footprint`, 50.0 Hz (the SDF says 30; why 50 not found) | spike §4 |
| `/imu` | 200 Hz, frame `burger/imu_link/tb3_imu` | spike §4 |
| `/tf` | about 70 Hz, only `odom` to `base_footprint`; fixed links on `/tf_static` | spike §4 |
| `/clock` | 1000 Hz, one per 1 ms physics step | spike §4 |

The real Burger's sensor rates and ranges were not checked (spike §16, §17).

**SLAM Toolbox against truth.** Over a loop of 29.9 m of truth path (30.8 m by odometry; 179.4 sim
s; 175 s of wall-following, 897 samples; spike §18), SLAM Toolbox's pose was within a mean of 2.3 cm
and a maximum of 5.4 cm of Gazebo's true pose (first-pose alignment; heading mean 0.51 degrees, one
11.6 degree sample the odometry shows too, taken by the spike as a pairing artefact, not verified);
the error grew slowly (0.016 m at 15 s, 0.036 m at 178 s) (spike §18). The pillars: for all nine,
the nearest occupied map cell sat one 5 cm cell inside the true surface (mean 0.052 m, max 0.053 m)
(spike §18). Limits that must stay beside these numbers:

- Gazebo's odometry is nearly ideal (mean 1.4 cm against truth), so SLAM had good input; this
  says nothing about how it does on a real Burger's slipping, drifting wheel odometry
  (spike §18).
- No loop closure was logged; the spike could not say whether one fired (it did not verify what
  the graph markers' colours mean) (spike §18).
- The walls were not checked against the world file; the run covered the west part only
  (spike §18).

The judge's idea, belief against truth, works unchanged on SLAM Toolbox's pose (spike §13).

**Exploration matters.** `explore_lite` (built from source on Nav2 1.3.14, unchanged, needing the
`Twist` relay of section 3.3) mapped 21.35 m2 (19.57 m2 free), the whole hexagon with nine whole
pillars, in about 51 s; the spike's crude left-wall follower mapped 11.67 m2 (west half only) in
175 s (spike §18). The comparison is unfair to the crude one: it was written in a few minutes,
stayed in the west part, and is not a tuned algorithm; a coverage curve was not recorded.
`explore_lite` needs Nav2 and a costmap, a heavier stack whose CPU was not measured (spike §18).
What the platform takes from it: "explore" for the Burger needs a frontier explorer, and a ready
one exists for ROS (section 7 item 13). Which of ours or Nav2's runs it is part of step 3;
the mapper is SLAM Toolbox (question 17, decided).

### 3.6 Frames, time, recording

Frames (ADR-0020 decision 4: ours; each connector maps onto them):

| Frame | Meaning | Source |
| --- | --- | --- |
| `world` | the simulator's or the site's truth | `wire.py:264` |
| `map` | the navigator's belief | `wire.py:264` |
| robot frames | each robot's own: `tof` for the duck | `wire.py:91` |
| the robot software's own | ROS `odom`, `base_link`, robotd's odometry | the connector's to translate; kept in `raw` if useful |

The duck's `site` frame and its odometry scale (0.91 in the simulator) are applied in the adapter
(`duck.py:416-420`). A ROS connector does its translation in the same place, which is why the
connector, not Mission Control, owns frames. The run's `/tf` is `world` to `map` only (ADR-0007),
with "map <- world epochs" for relocalisation (RFC-0021 step 2 text; not verified in code). The
spike's connector wrote a second `map_to_world` epoch record at a reset and the run read back
(spike §20 part 3). Whether SLAM Toolbox's continuous `map` to `odom` corrections fit there as
epochs is still not verified: the spike paired the frames at two epochs only (spike §20,
"Not done").

Time: the platform's clocks are wall clocks, and the real-time factor stays 1. ADR-0020 decision 3
as the operator accepted it says "Gazebo at real time": the factor is 1 and the platform uses
its wall clock. This RFC keeps both. The cost is real: a challenge set is 3.5 to 4 hours
(ADR-0018 consequences), and a slow host silently changes results (RFC-0021 §6).

**The clock rule, settled by the spike.** Draft 2 proposed it and asked the operator to confirm
(question 13, now closed). The bridge stamps with simulation time, which starts at 0 when Gazebo
starts, not at wall time: `/scan`, `/odom`, `/imu`, `/tf` and `/clock` read 39 to 43 s while the
wall clock read 1.79e9 s (spike §7). A node with `use_sim_time` false failed every tf lookup at
its own time and only "latest" worked; with `use_sim_time` true, the node clock and the stamps
agreed, and SLAM Toolbox ran correctly on them (spike §7). So the earlier wording, "wall time in
its bridge", does not hold for a Gazebo bridge (RFC-0015's `nav2/bridge.py:5` stamped with its
own clock and does not carry over). The rule, now decided:

1. Inside the ROS graph `use_sim_time` is true, and the bridge stamps with simulation time.
2. The connector is where the two clocks meet. It stamps `wall_ns` on receipt and keeps the ROS
   stamp beside it (spike §20 part 2: a tick carries `t` in wall seconds, `t_src` the ROS stamp,
   and `wall_ns`, `ros_stamp_ns` and `epoch` in `raw`).
3. The run's own time stays wall time. `Recorder._check_open` raises "time goes back" for a time
   that goes back (`libs/runfile/src/runfile/mcapio.py:193`), and sim time does at a reset, so
   that line stays unchanged (spike §20, table).
4. The platform outside the connector stays on wall time; the real-time factor stays 1 and is
   recorded each run (decided, question 7). The one-to-one mapping between wall time and sim stamps
   holds only at a factor of 1 (the spike measured `/clock` against wall time at 0.998 over 11 s,
   and `/stats` at 0.9997 to 1.0003; spike §6, §13).
5. A ROS recorder's own time is not the run's time: `ros2 bag record` stamps the bag with sim or
   wall time depending on `--use-sim-time` (spike §7, §11). The run takes its wall time from the
   connector, not from a bag.

Not verified (spike §7): other bridge message types (images, point clouds), and a Gazebo sensor
with its own clock; the stamps of `/scan` and `/imu` were not compared at sub-step precision.

**The clock epoch.** A world reset sends the sim clock back to 0, so a sim stamp is not
monotonic (spike §9, §13). The rule needs one more clause, proven in the spike's extension C
(spike §20 part 2): the connector counts epochs. Across one reset, wall time stayed monotonic,
the sim stamp jumped from 65.4 s to 0.2 s, and the epoch counter went from 0 to 1. Recorded in
the run as:

- a `clock_epoch` event ("the simulator clock went back from 65.583 s to 0.000 s");
- an epoch counter, a first-class field next to `t_src` (the spike put it in `raw`, and its
  table says `wire.py` tick `raw` and `mcapio.py` `begin_tick` should change);
- a new `map_to_world` `epoch` record, a second pairing of SLAM's frame with truth (the first
  came at t = 0.51 s, the second at t = 61.60 s). The second was paired from a frozen belief and
  a frozen truth (below), so it is not evidence that re-pairing works.

Epoch 0's belief-against-truth median was 0.241 m in the spike's `readrun2.txt`, because the
prototype paired `map` to `world` from one first sample. Recommended: `map`-to-`world` is the
spawn pose the host kind knows. SLAM Toolbox starts its map at the start pose (spike §5, "I
believe", unverified); verify it in step 5a.

The run format already has `epoch` records. What it lacks is a place for the clock epoch and a
reason beside the record (the spike wrote an event next to it, spike §20 "What broke" item 2).
`robot.state` also has no place for the simulator's clock and epoch in the gate's contract; the
spike returned `epoch` and `sim_s` (spike §20 "What broke" item 3). Question 24, decided:
the epoch is a first-class field, the pair (epoch, t_src), settled in step 4.

**The connector's tf state across a reset: diagnosed from code and logs, confirmed
by a re-run (spike §21).** After the reset in the spike, belief and truth froze. In run 1 the 222
ticks after the reset have one distinct belief position and one distinct truth position (6235
`TF_OLD_DATA` warnings); in run 2 warnings fell to 2221 and no ticks came after the reset at
all. The advisor read the spike's work files (`~/.cache/robotics-lab-tests/mvp2-spike/`) and
upstream sources, and ran nothing. The re-run (spike §21) confirmed it: with all three fixes
and the sequence `reset all`, then `/slam_toolbox/reset`, belief and truth kept moving after
the reset (333 ticks in the new epoch, belief within 0.050 m median and 0.072 m max of truth,
no `TF_OLD_DATA`). Without `restamp_tf` the belief was gone for about 46 s of sim time; with
a plain `Buffer()` it stayed frozen (0.42 m median error). Fix 1 rests on the post-reset stamp
having no `sec` and the old traceback, not on a run without the fix. `restamp_tf` exists in
2.8.5. Each variant ran once; a reset while moving, two resets in a row and `reset all`
without `/slam_toolbox/reset` were not tried. Three concrete causes:

1. **Truth froze because the prototype's truth reader crashed.** `connector.py:144` reads
   `int(s["sec"])`, and `gz topic --json-output` omits zero-valued protobuf fields, so after a
   reset `stamp.sec` is absent and the read raises `KeyError 'sec'` (`out/connector.log`, run
   2). Run 1 is inferred from identical code. The truth stream itself was fine (checked with
   `gz topic`).
2. **Belief froze in run 1 because the tf buffer was built without the node clock**
   (`connector.py:66`, `Buffer()`). Jazzy's `tf2_ros` `Buffer` clears on a backward jump only
   when given `node=` (`buffer.py:88-109`).
3. **Belief stayed empty in run 2.** All 2221 `TF_OLD_DATA` warnings were frame `odom`. SLAM
   Toolbox stamps `map`-to-`odom` with the last processed scan's stamp unless `restamp_tf` is
   true (default false; `slam_toolbox_common.cpp:398-402, 507-511`, read on the jazzy branch
   HEAD, not verified in the 2.8.5 tag). One stale `map`-to-`odom` blocks a cleared buffer for
   tf2's 10 s cache (`cache.cpp:264`).

The spike's reset run also called only `reset all`, never `/slam_toolbox/reset`, so it did not
test the reset design of section 3.4. These are diagnoses from reading, not proofs. This
replaces the earlier wording ("the connector cannot trust any ROS tf lookup across a reset and
probably must restart SLAM Toolbox").

The reset sequence that step 5a must prove, in order:

1. `reset all`;
2. `/slam_toolbox/reset`;
3. SLAM Toolbox with `restamp_tf: true` (verify the parameter exists in 2.8.5);
4. the connector's tf buffer on the node clock (`Buffer(node=...)`);
5. a new clock-epoch clause, a stale-epoch filter at the connector's boundary: drop any
   source-stamped message whose stamp is ahead of the current sim clock by more than a small
   slack;
6. a truth reader that is not a JSON subprocess (the plugin of section 3.4).

Long-term option: the connector composes `map`-to-`odom` and `odom`-to-`base_footprint` itself
from `/tf`, keyed by epoch, which removes tf2's cache semantics from the connector. Step 5a's
proof includes a reset in the middle of a run with belief and truth still moving afterwards
(section 6, section 7 item 19).

Decided (question 7), unchanged: record the simulator's time beside wall time in every run, and
check the real-time factor each run.

Recording: a robot's ticks (`/belief/pose`, `/truth/pose`, `/depth`, commands) stay in
`run.mcap`. Large streams are companion streams beside the run. ADR-0007 already has the
precedent: an import copies its source log into `source/` beside the run with a SHA-256.
Proposed layout:

```text
 <run folder>/
   run.mcap                      # ticks, events, maps (format 2)
   streams/<stream_id>.mcap      # companion streams, one MCAP per stream (section 3.11.2)
   streams.json                  # per sensor: kind, frame, calibration ref, count, rate
```

A run record points at `streams.json`. Retention (plan step 7) works per run folder, so a heavy
run archives whole.

For the Burger the natural raw recording is rosbag2, written to MCAP, as one more companion
stream beside the run (for example `source/`, the name ADR-0007's import uses for a copied log).
It also meets the vision note's "save raw recordings". In Jazzy `ros2 bag record` writes MCAP by
default (`-s {mcap,sqlite3}`, default mcap) with compression off (spike §11). The spike installed
`ros-jazzy-rosbag2-storage-mcap` on purpose; whether the base image has it without that was not
checked (spike §11). Our own run keeps the ticks; the bag keeps everything the ROS graph said,
with the ROS stamps, for replay into SLAM Toolbox later. A replay of the bag into a viewer was not
tried (spike §11).

What the spike measured, so retention and the companion rule have numbers (all uncompressed, no
camera unless said):

| Recording | Size | Source |
| --- | --- | --- |
| `/scan /odom /tf`, 29.68 s, 5196 messages | 2.1 MiB, about 75 kB a second, 90 % of it tf and odometry | spike §11 |
| the same plus RGB, depth and camera info, 27.46 s, 7383 messages | 1.7 GiB | spike §19 |
| RGB 640 x 480 at 30 Hz, raw | 1,661 MB a minute | spike §19 |
| depth 640 x 480 at 30 Hz, raw | 2,207 MB a minute | spike §19 |
| RGB compressed (one frame: PNG 9,214 B, JPEG q80 14,098 B) | PNG 17 MB, JPEG 25 MB a minute | spike §19 |
| depth compressed (16-bit PNG, millimetres, 13,571 B a frame) | 24 MB a minute | spike §19 |

The compressed figures are a lower bound: the Gazebo render is flat shaded, with no texture and
no noise, and a real camera's JPEG would be many times larger, which the spike did not measure
(spike §19). The two raw figures together are the spike's "3.9 GB a minute" (spike §19 title and
"Answers in brief"). This supports ADR-0020 decision 5: images are companion streams, never in
`run.mcap`, stored compressed, and retention acts per run folder (plan step 7). A scan costs
little (about 75 kB a second with odometry and tf), so it can stay in `run.mcap`.

What a camera costs the simulator (spike §19, headless, software rendering, no GPU): the real-time
factor stayed 1.0001 (one read while driving), and CPU with SLAM Toolbox and the wall-follower
went from about 98 % (82 to 108 %, 6 samples) to about 266 % (253 to 284 %, 6 samples) of one
core, memory from 581 MiB to 745 to 757 MiB. That is about 1.7 extra cores and about 170 MiB. A
GPU's effect, 15 Hz and smaller sizes were not tried (spike §19, "Not done"). Gazebo's camera
frame is `camera_link`, not a ROS optical frame, so a tool that expects z forward needs a fixed
transform the spike did not add (spike §19). The sensor type was `rgbd_camera` (spike §19).

How an image is captured, recorded and processed before a consumer sees it is designed in
section 3.11. The layout above is its base: each stream's MCAP also carries the camera's
actual settings per frame as a parallel channel, and `streams.json` carries the recording and
pipeline summary.

### 3.7 Our navigator for any robot

The operator's answers 5 and 6 make this the central piece of the evolution. Today the navigator
is the duck's: `duck_lab.nav`, and RFC-0022 §3.3 says it stays "the duck's until a second robot
runs it". Now a second and a third robot run it. One navigator must drive a legged duck, a
differential-drive Burger and a tracked NXT, each through its own plugins. RFC-0020 §4 already
names the four plugin interfaces: locomotion, range sensing, localisation, looking.

What already helps:

- The four interfaces are written as protocols, and a profile names one implementation of each
  (`robots/duck/src/duck_lab/plugins/interfaces.py:1-10`).
- The navigator builds itself from the profile (`duck_lab/nav/run.py:294-307`).
- Following a path hands the turn to the locomotion plugin
  (`duck_lab/nav/follow.py:5`).
- A robot that cannot look is already a case (`run.py:743`, `looking.capable`).

What assumes the duck, found by reading the code on 2026-11-23:

- **The sensor is an 8x8 depth grid.** The reflex works "on each depth frame" and stops the walk
  (`run.py:9-11`). `run.py:28` imports the 8x8 plugin's `FrameView` directly. A Burger gives a
  360 degree scan of rays. The NXT gives an ultrasonic distance and a colour.
- **The streams are three fixed sockets.** `robot`, `depth`, `map` (`run.py:159`), and mapd is
  an RPC over the `map` socket (`run.py:230`). A scan, a SLAM Toolbox map or an NXT have no
  such sockets.
- **The pivot and kick rules are the duck's.** A turn on the spot needs a clear room and no
  remembered drop near (`explore_run.py:76-89`), and a turn starts with a kick rate
  (`explore_run.py:96`). A wheeled base turns freely. A tracked robot turns on the spot too, but
  its numbers differ (RFC-0020's interface table).
- **The head.** The navigator glances at a drop's edge with the head (`run.py:736-743`) and
  keeps a memory of suspected drops. The Burger and the NXT have no head, and a LiDAR does not
  see a drop. Whether the navigator is safe on a robot that can neither look nor see a drop is
  not verified. Decided (the operator confirmed, 2026-11-23): the
  Burger and NXT profiles declare no drop sensing, and the navigator's drop memory and glance
  are gated on a capability.
- **The stop sequence is robotd's.** "Every stop ends with an explicit zero move: robotd keeps
  the last request after its deadman trips" (`run.py:11`).
- **The belief is mapd's.** Odometry, mapd's poses and its grid share one scale
  (`run.py:217`). A Burger's belief comes from a mapper under ROS; the NXT has none.
- **The NXT senses little.** Ultrasonic and colour only (RFC-0003; not verified in the NXT
  code), and no odometry beyond the motor counts (not verified). Its belief of where it is
  would drift fast. Until the Pi module's design (section 3.10) gives it a range sensor, the NXT
  drives and reaches goals with our navigator, ultrasonic for stops, and no map (question 16).

The work has two parts. First, split `duck_lab.nav` into a part that knows no robot (the
planner, the grids, path following, recovery, the goal methods) and the duck's plugins. Second,
widen the plugin interfaces where they are duck-shaped: range sensing returns 8x8 frames today
and must return a scan or a single range; localisation must accept a mapper that is not mapd.

| Robot | Locomotion | Range sensing | Localisation | Looking |
| --- | --- | --- | --- | --- |
| Duck (exists) | `duck-walk@1` | `tof8x8@1` | `mapd@1` | `duck-head@1` |
| Burger (new) | differential drive | 2D scan | SLAM Toolbox's map and pose through the connector (question 17, decided) | none (`capable` false) |
| NXT (new) | tracked (RFC-0020 §6 step 5) | ultrasonic, and colour | dead reckoning from motor counts, no mapper until the Pi module's design (question 16) | none |

Proof, in the project's habit: the duck's challenge verdicts stay as they are, and one contract
test runs against all three plugin sets (as `test_contract.py` does for navigators).

### 3.8 Where a robot's software runs

The operator's answer (question 1): support all three placements as part of the robot's
configuration, if the effort is reasonable. The placements, for the Burger:

| Placement | The Pi runs | The workstation runs |
| --- | --- | --- |
| On the robot | bringup, the connector, the mapper, the navigator | the views and the gate's clients |
| Split | the robot's bringup only | the connector, Nav2 or our navigator, the mapper |
| On the workstation | nothing of ours (not verified: the Pi talks to the base's board) | everything |

It is a per-robot setting, designed in from the start. We build the split first. The others come
when needed, if the cost stays reasonable (section 7, item 7).

Where the setting lives. Decided (question 18): in the installation, because where processes
run is what one machine holds, and it already says where each robot's navigator and profile
are (`runfile/installation.py:1-4`). One robot can be placed differently on two machines. The
registration lists which placements the robot supports. The operator said
"installation/registration"; the answer is both (question 18).

What changes:

- **The connector.** Today the gate reaches a robot through Unix socket paths (`host.py:28-29`).
  A connector on the Pi needs a network address instead. The setting says which one a robot has.
  RFC-0026 writes this down.
- **The mapper's location.** It follows the setting: on the Pi, on the workstation. The
  navigator reads the map through the navigator contract's `map` either way.
- **The deadman.** A last-hop watchdog runs on the computer wired to the motor controller in
  every placement (section 3.3): a node on the Pi for the real Burger, the connector in the
  simulator. A lost link must stop the robot.
- **The run.** Records the placement, so a result is read with where the software ran.

### 3.9 The sensor layer, for any robot and any simulator

Today the sensor layer is the duck's:

- The profile's schema knows two sensor kinds, `tof8x8` and `camera`
  (`libs/runfile/src/runfile/profile.py:190-199`). The `capabilities.sensors` list is empty for
  the duck (`robots/duck/profile.json:216`).
- The run file has one sensor frame, `tof` (`wire.py:91`).
- The navigator's range-sensing plugin is the 8x8 one, `tof8x8@1`
  (`robots/duck/profile.json:229`).
- The depth arrives by a socket the host file names, not by declaration
  (`libs/simhost/src/simhost/host.py:28-29`).

Where simulated and real meet differs per robot, and both keep the two interchangeable:

- **The duck.** Its sensors are made by the robot's own programs, in the simulator and on the
  real robot: robotd, tofd and mapd read MuJoCo or the hardware. The boundary between simulated
  and real is below robotd.
- **The Burger.** In the simulator, Gazebo's sensor plugins make the scan, the IMU and later the
  cameras. On the real robot, the LiDAR and IMU programs do. The boundary is the ROS topic.

The model, in our terms:

1. **The profile declares sensors.** Each has an id and a kind: depth grid, 2D scan, IMU,
   odometry, image, depth image. Each has its mount on the robot, its intrinsics where they
   apply, a rate, a range, a field of view, and noise per variant (`sim`, `real`).
2. **The connector says where each one comes from:** a robotd or tofd socket, a ROS topic, or the
   NXT's HTTP.
3. **Each host kind declares which sensor kinds it can simulate.** The MuJoCo duck host: the
   depth grid, the IMU and the camera stand-in. The Gazebo host: the 2D scan, the IMU, cameras
   and depth cameras. A robot whose profile needs a kind its host cannot simulate is refused at
   start.
4. **The run has one stream kind per sensor kind.** The 2D scan is a channel (its schema to be
   confirmed by the spike). Images and depth images are companion streams.
5. **Each kind has its users.** The mapper: mapd reads the depth grid, SLAM Toolbox the scan,
   and later RTAB-Map images and depth. Our navigator's range-sensing plugins: `tof8x8@1` today,
   a 2D-scan plugin for the Burger, an ultrasonic one for the NXT. The Observatory draws each
   kind its own way.

The rules:

- Robots declare sensors, and nothing assumes one.
- The connector hides the source.
- Each host kind says what it can simulate.
- The simulated and real variants of a sensor differ only in their numbers (noise,
  calibration), never in shape.

This is the design for cameras from the start (section 3.5). The first build carries only the
scan, the IMU and odometry. Profile v2 (step 2) writes the declaration; step 4 writes each host
kind's list; step 5a builds the scan, IMU and odometry paths.

A note from the spike on what the simulator and the real robot share (spike §14, §16): for the
Burger nothing is shared below the topic, since the simulator uses plugins and the real robot uses
`turtlebot3_node` and the lidar's driver; for the duck the robot's own daemons run unchanged
against a body. So the connector must stamp wall time on receipt in all three cases (Gazebo's
bridge forwards sim time; the real Burger's node stamps with its own clock; the duck's daemons
have theirs) and keep the source stamp beside it (spike §16).

### 3.10 Three robot shapes

The platform's model must hold three shapes of robot, not two. The third comes from the
operator's answers on the NXT (NXT-MVP1.md, "The operator's answers (2026-11-23)"): "I will start
with 1, move to B and plan to have C as extension of the project where I will build [a Pi-]based
augmentation module with all modern sensors, so let's plan for all of it." The link goes USB, then
Bluetooth, then the Pi module.

| | Duck | Burger | NXT with a Pi module |
| --- | --- | --- | --- |
| Software on the robot | robotd, tofd, mapd (in the simulator, in the host) | bringup on the Pi; the rest by placement (section 3.8) | a Pi on the robot with its own sensors beside the brick's; the Pi carries a depth camera and runs mapd (question 16); the rest is not decided |
| Placement | not a setting today | a per-robot setting | a per-robot setting, in the same installation entry (question 18) |
| Sensors, source 1 | the duck's own (depth, IMU) | the kit's lidar, IMU, odometry | the brick's: ultrasonic, colour, motor counts |
| Sensors, source 2 | none | later cameras (step 11) | the Pi's modern sensors, each declared in the profile |
| Link | the robotd socket | ROS over DDS | USB, then Bluetooth, then the Pi (NXT-MVP1.md) |
| Host kind in MVP 1 or 2 | `pollen-duck-sim` | `gazebo-turtlebot3` | `nxt-kinematic-sim` (MVP 1, item 4d) |

The Pi-module shape is RFC-0025's case of a robot whose software runs on the robot and whose
sensors come from two sources, a brick and a Pi, each declared in the profile (NXT-MVP1.md). Three
things follow, all in the existing design and none built:

- **Placement is a per-robot setting** (section 3.8). The NXT's connector today is nxt-web over
  HTTP, reached at a URL from the installation entry, never a hard-coded localhost
  (NXT-MVP1.md). The Pi module adds a second machine on the robot.
- **Sensors are declared per source** (section 3.9): the profile lists each sensor with its
  id, kind and where it comes from (the brick's HTTP, or the Pi). Nothing assumes one source or
  one machine. NXT-MVP1.md's D0 records this as a requirement so the host kind, the sensor
  declaration and the installation entry do not assume either.
- **The last-hop watchdog covers both links** (section 3.3). Bluetooth's command latency and drop rate
  decide the deadman's timeout over that link; unit D10 of NXT-MVP1.md measures them. The Pi
  module's link is not measured.

The advisor's review finds the third shape sound as a requirement on profile v2 (a source per
sensor) and on the installation (two machines per robot); no further design now.

Not covered here: the Pi module's hardware, its sensors, its link to the brick, and who runs
the connector between the brick and the Pi. Those are the operator's to choose when the module is
designed (NXT-MVP1.md, "The Pi augmentation module (MVP 2, not built in 4d)").

### 3.11 Images: capture, recording, pipeline

The operator calls this super important, so it is designed in full here. Nothing of it is built:
no camera is chosen (question 22) and no consumer of images exists yet. It is built at step 11
and step 12 (section 6). The design has three layers and one rule:

- **Capture:** what the camera does (resolution, rate, exposure, gain, white balance, HDR).
- **Recording:** what is stored of what the camera produced (a companion stream in the run's
  folder, section 3.6, ADR-0020 decision 5).
- **Pipeline:** what a consumer sees (an optional, named, versioned chain of stages).
- **The rule:** the recorded stream is always the camera's output before any pipeline. A
  pipeline is never baked into a recording.

"Raw" in the spike means uncompressed decoded frames (`rgb8`, `32FC1`), not a sensor's Bayer raw
(spike §19). This section uses "uncompressed" for that and does not promise Bayer data, which a
robot's camera driver may not offer (not verified here).

```text
 camera --capture settings--> CONNECTOR --+--> recording (companion stream, run folder)
 (sim: Gazebo rgbd_camera)       |        |        camera output, before any pipeline
                                 |        +--> pipeline branch per consumer
                                 |                 mapper | detector | Observatory | model job
                                 v
                      actual settings per frame, recorded beside each image
```

#### 3.11.1 Capture settings, declared in the profile

Each camera is a sensor declared in the profile (section 3.9, profile v2, step 2), per variant
(`sim`, `real`). Its capture block, proposed:

| Setting | Values | Note |
| --- | --- | --- |
| resolution | width x height | the spike ran 640 x 480 only (spike §19) |
| rate | Hz | the spike ran 30 Hz only; 15 Hz was not tried (spike §19) |
| exposure | `auto`, or a locked value | a locked value for calibration and photogrammetry captures |
| gain | `auto`, or a locked value | |
| white balance | `auto`, or a locked value | |
| HDR | `off`, `on`, only if the camera has it | not declared for a camera without it |
| depth range | near and far limits | the spike's clip was 0.2 to 5.0 m, set as asked, not checked |

The connector applies these to the camera and reads back what the camera actually did. **The actual
values, not only the requested ones, are recorded per frame** beside each image, in the stream's
MCAP, as a parallel channel: exposure time, gain, white balance and whether HDR was on. With an auto
mode the actual value changes from frame to frame, and a run cannot be reprocessed fairly without
it. A camera that does not honour a request is a warning at the start of a run (an alarm, RFC-0019's
vocabulary), not a silent difference. Which settings a given camera lets us read back is not known
until it is chosen (question 22).

In the simulator the spike's render was flat shaded with no noise and it set no camera
settings: whether Gazebo's `rgbd_camera` models exposure, gain or white balance was not checked
(spike §19). In the simulator the settings channel records the requested values and says they are
simulated, until that is checked.

#### 3.11.2 Recording per stream, declared in the profile

Recording is declared per stream (a colour stream, a depth stream), not per camera, because the
two have different rules. Choices (confirmed by question 25) and what they cost, from the
spike's measured sizes
(640 x 480 at 30 Hz, one workstation; a flat Gazebo render, so a lower bound for any compressed
figure; spike §19):

| Stream | Option | Cost per minute | Note |
| --- | --- | --- | --- |
| colour | off | 0 | the stream is not recorded; the ticks still are |
| colour | JPEG, quality q | 25 MB at q80 (14,098 B a frame) | **default, q80**; one message per frame |
| colour | H.264 or H.265, bitrate and keyframe interval | unknown, not measured | smaller than JPEG at like quality (general knowledge, not measured here); see the trade-off below |
| colour | lossless PNG | 17 MB (9,214 B a frame) | a flat render; a textured scene is not measured |
| colour | uncompressed | 1,661 MB | for calibration and photogrammetry captures only |
| depth | off | 0 | |
| depth | lossless 16-bit PNG, millimetres | 24 MB (13,571 B a frame) | **default** |
| depth | an RVL-style lossless depth codec | not measured | not tried; a candidate if the PNG's size or CPU hurts |
| depth | uncompressed (`32FC1`, metres) | 2,207 MB | calibration and capture sets only |

All sizes are from spike §19. The two defaults together are about 49 MB a minute, about 2.9 GB an
hour, in the flat render: arithmetic on the spike's figures, not a measurement of a real camera.
A real camera's JPEG would be many times larger (spike §19), so this is a floor for retention
planning, to be replaced by a measured number on the real robot.

**Depth is never lossy.** A lossy codec smears edges and invents values at depth discontinuities,
and the mapper, the judge and a model job would read those invented values as measurements. Depth
is a measurement, so it is off, lossless or uncompressed. The 16-bit PNG in millimetres rounds
the spike's metres (`32FC1`) to 1 mm. Invalid depth is 0, meaning no data (the
`depth_image_proc` convention): NaN and infinity map to 0, which includes the infinite pixels
(18 % of the spike's depth pixels, spike §19).

**JPEG against H.264 or H.265 for colour.**

- JPEG: each frame is its own message, so a replay or a model job seeks to any frame at once and a
  damaged chunk costs a few frames. It is the largest of the lossy options (25 MB a minute in the
  flat render).
- H.264 or H.265: smaller for the same quality, but a frame decodes from its last keyframe, so a
  seek costs up to the keyframe interval, and an encoder takes CPU on the machine that runs it.
  The Pi 5 has no hardware encoder (not verified), and the software encoder's cost there is
  unknown. A message is a segment, not a frame, so the index points to a segment and a frame
  within it, and a damaged segment costs more.
- The default is JPEG q80 because replay and model jobs need frame-exact access and no encoder
  load on the robot. The default was confirmed (question 25), to be revisited when a real
  camera is measured.

**Where the recording lives.** A companion MCAP per stream, `streams/<stream_id>.mcap`, not
loose files: 30 Hz on two streams is 216,000 files an hour. Each is chunked and time-indexed
by MCAP itself, so a seek to a frame is exact. Colour is `foxglove.CompressedImage` (JPEG or
PNG); depth is the same schema with 16-bit PNG. The camera's actual settings (3.11.1) go in a
parallel channel of the same file, each chunk has a sha256 recorded in `streams.json`, and
Lichtblick plays the file (the advisor; not verified here). Images are still never in
`run.mcap` (ADR-0020 decision 5). Not measured on a Pi. `streams.json` holds the recording
summary. Retention (plan step 7) acts per run folder and per stream, so a heavy depth stream
can be dropped from an old run and its ticks and colour stream kept. The estimated MB a minute
in the panel (3.11.4) is what retention budgets against.

Where encoding runs follows placement (section 3.8): on the robot's computer or on the
workstation. A 640 x 480 stream at 30 Hz over Wi-Fi is not measured (section 7, item 14).

#### 3.11.3 The image pipeline

An optional chain of stages between the connector and the consumers of images. Proposed stages:

| Stage | Does | Applies to |
| --- | --- | --- |
| undistort, rectify | removes lens distortion with the calibration's intrinsics | colour, depth |
| exposure, gamma | brightens or darkens | colour |
| local contrast equalisation (CLAHE) | evens out contrast in dark and bright parts | colour |
| denoise | reduces sensor noise | colour |
| resize | lowers the resolution for a consumer | colour, depth |

A **pipeline** is a named, versioned, ordered list of stages with parameters, for example
`slam-clahe@1`. Rules, proposed:

1. **Per-consumer branches.** Each consumer gets its own branch of the pipeline. An example in the
   operator's words: SLAM gets CLAHE, a detector gets the plain image, the Observatory gets an
   image tuned for display. The consumers are the mapper (RTAB-Map later, section 4; SLAM Toolbox
   uses the scan, not images), a detector, the views, and a model job.
2. **The recorded stream is the camera's output before the pipeline.** The pipeline does not
   change what is on disk.
3. **The pipeline's name, version and parameters are recorded in the run** (the start record and
   `streams.json`), per branch.
4. **The pipeline re-runs on replay.** The Observatory and a model job apply a named pipeline
   version to the recorded stream, so an old run can be reprocessed with a newer version. The
   run says which version was live, and a replay can use that one or another.
5. **Depth takes geometric stages only** (undistort, rectify, resize that does not invent values).
   Exposure, equalisation and denoise would invent measurements, for the reason in 3.11.2.
6. **Determinism is a required declaration per stage,** in its version (deterministic or not),
   so a reprocessed run is comparable. No stage that depends on a learned model is proposed
   here.
7. **The undistort stage names the calibration record (its hash) it used,** in the run, so a
   reprocessed run uses the same intrinsics or says it did not.
8. **A display branch is never the input of a model job.** A model job reads the recorded
   stream or a branch built for it.

**Later, not built: per-room or per-light choices.** The operator's example is one room lit and
one not. The connector measures a brightness (for example the mean luminance of recent frames)
and picks a capture setting or a pipeline branch for it. The pick is recorded as a decision
event in `run.mcap` (the brightness, what it chose, from what), so a replay can reproduce it or
decide again with a newer rule. It may use Mission Control's areas (RFC-0014 §3.5) as the rooms;
that is not designed here.

**Where the pipeline runs** follows placement (section 3.8): in the connector on the robot, or
on the workstation. Because the recording is before the pipeline, the choice changes cost and
latency but not what a run holds. A live pipeline on a Pi has a CPU cost that is not measured.
Decided (question 26): replay and model jobs first, live when a live consumer needs it.

#### 3.11.4 The configuration panel

Mission Control's Settings is a block list with a compact read view, a side-drawer edit and a
History drawer (the approved design, PHASE5-NEXT-PLAN.md:411-412; I did not re-read the design
beyond those lines). Each camera gets one **Images** block that shows, before a run starts:

- what is **captured**: resolution, rate, exposure, gain, white balance and HDR, as requested;
- what is **recorded**: for each stream its format, quality or bitrate, and the estimated MB a
  minute and the total, marked with where the estimate comes from (a spike figure in a flat
  render, or a measurement on this robot once one exists);
- which **pipeline each consumer gets**, by name and version.

An edit opens in the side drawer; the History drawer lists changes. A change applies to the next
run, not to one in progress (proposed). **The run's start record keeps the same summary**, so the
Observatory shows for a run what was captured, recorded and processed, as it shows other run
facts.

#### 3.11.5 The simulator and the real robot

Gazebo's render is flat shaded: grey and green shapes, no texture, no noise, uniform lighting
(spike §19). So its compressed sizes are a lower bound and its images exercise little of the
capture and pipeline design. The rule of section 3.9 holds: the same settings apply to the `sim`
and `real` variants, which differ in their numbers, not their shape. To test the pipeline and the
brightness choice in the simulator, vary the world's lighting (a darker room beside a lit one),
which is a scene change for the Gazebo host kind (step 9). Whether Gazebo emulates exposure,
gain, white balance or noise is not verified (3.11.1). A real camera's JPEG size and its noise
come only from the real robot.

## 4. The external tools, one by one

I read no external documentation for this section. Versions and the behaviour of Gazebo, the
bridge, SLAM Toolbox, rosbag2 and `explore_lite` now come from the spike's runs (spike §2 to §11,
§18 to §20). Nav2, RTAB-Map, Open3D, COLMAP and Nerfstudio were not run in the spike beyond
`explore_lite`'s Nav2, and licences were checked for none; those rows are from this repository
or marked "not verified". "Replaces or duplicates" means against our own stack.

| Tool | What it does | Role here | How it joins us | 2D / 3D | When |
| --- | --- | --- | --- | --- | --- |
| Gazebo Sim | Physics and sensor simulator | A second host kind | A host kind `gazebo-turtlebot3`; a process or container; SDF scenes written from `scene.json`; truth read from the model pose; Gazebo Sim 8.15.0 (Harmonic), decided (spike §2) | both | MVP 2 start |
| ROS 2 | Message bus and tooling | The Burger's own stack, inside the connector and Nav2 containers | A container (ADR-0018); only the connector imports it; Jazzy, decided (spike §3) | n/a | MVP 2 start |
| TurtleBot3 packages | The robot's bringup, models, simulation worlds | The Burger's description in ROS terms | Bringup on the Pi (real) or from the simulation package (sim); `turtlebot3_gazebo` 2.3.7 on the `jazzy` branch (spike §3) | 2D LiDAR robot | MVP 2 start |
| ros_gz bridge | Gazebo topics to ROS topics | The host kind's connection side | Runs beside Gazebo; carries `/scan`, `/odom`, `/cmd_vel` (`TwistStamped`), `/clock`; stamps with sim time (section 3.6); `ros_gz` 1.0.25 (spike §2); drops entity names from the pose stream (section 3.4) | n/a | MVP 2 start |
| rosbag2 (MCAP) | Records a ROS graph's topics to a file | Raw recording, a companion stream beside the run | `ros2 bag record` in the ROS container, MCAP by default in Jazzy; the file goes to `source/` (section 3.6) | both | MVP 2 start |
| Nav2 | Planner, controller, behaviour tree, costmaps, recoveries | The robot's own navigator, behind our contract | Container; a wrapper maps `goal.*` to its action | 2D | MVP 2, after our navigator drives the Burger |
| SLAM Toolbox | 2D LiDAR mapping, a map and `map`-to-`odom` | The Burger's mapper, first under our navigator (question 17) | Container, same graph as Nav2; its grid becomes the contract's `map`; 2.8.5, online asynchronous mode in the spike (spike §2, §5) | 2D | MVP 2 start |
| RViz | ROS's own live viewer | Decided (question 11): a debug aid inside the ROS container only, not a view of ours | Optional, ROS container only | both | MVP 2 start, as a debug aid |
| RTAB-Map | RGB-D, visual and LiDAR mapping with loop closure | A mapper for 3D | ROS container; own database as a companion stream | 3D | Later |
| Open3D | Point clouds, TSDF, meshing | A tool a model job calls | Python library in a separate job | 3D | Later |
| COLMAP | Structure-from-motion, multi-view stereo | A tool a model job calls | CLI behind the photogrammetry project's command line (section 5) | 3D | Separate project, its own repository |
| Nerfstudio | NeRF and splatting workflows | Visualisation experiments | Offline, GPU; never the platform | 3D | Never in the core |

Notes, one tool at a time:

- **Gazebo Sim.** What the repo says: RFC-0021 §3.1 plans a `gazebo-turtlebot3` kind: "its
  truth Gazebo's model pose, its scenes SDF". It duplicates MuJoCo's job for the Burger and
  nothing else. It pulls in a large install (the spike's image is 4.32 GB with TurtleBot3, Gazebo,
  ros_gz and SLAM Toolbox, spike §12; ROS and Gazebo are installed on no host, RFC-0021 §3.1) and
  a second real-time risk, which the spike measured as RTF 1.00 (section 3.4). Versions, decided:
  Gazebo Sim 8.15.0 (Harmonic) with ROS 2 Jazzy, from `ros-jazzy-gz-sim-vendor` 0.0.13; ROBOTIS's
  `jazzy` branch and e-Manual cover that pair (spike §2, §3; the e-Manual was read through a
  summarising fetch tool). Not verified: the `main` branch, support dates, Gazebo's physics engine
  name and the lidar's renderer (spike §3, §17). It runs headless (`gz sim -r -s`), with no GPU,
  in a container (spike §4).
  The operator's answer (question 12): the workstation first; the MacBook later and not required
  for MVP 2. Whether it runs on the MacBook (Apple Silicon) is not verified. Its simulated
  sensors come from plugins (`rgbd_camera` confirmed, spike §19; `gpu_lidar` not verified).
- **ROS 2 and its distro.** ROS 2 Jazzy on Ubuntu 24.04 (the image's OS, spike §2) is decided,
  as the parked Nav2 image already was (ADR-0018). The workstation is Arch, hence the container.
  ADR-0001 decision 4's trigger "ready-made SLAM or sensor drivers" is now met (ADR-0020
  context). Humble and another pair were not tried (spike §17).
- **TurtleBot3 packages.** `turtlebot3_gazebo` and `-description` 2.3.7 and `-msgs` 2.4.0 install
  from apt, with no source build (spike §2, §3). The package does not install ROBOTIS's teleop;
  the spike drove with its own scripts (spike §3). The vision note says a Burger has a Raspberry
  Pi, an OpenCR controller, wheel encoders, an IMU and a 2D LiDAR "depending on kit generation"
  (section 4). Which LiDAR model is on the arriving kit is a question for the operator.
- **ros_gz bridge.** Needed to reach Gazebo from ROS. The connector should depend on topics, not
  on this bridge's name, so a different simulator could provide the same topics. It stamps
  messages with simulation time (section 3.6, verified in the spike §7). It turns Gazebo's pose
  stream into a `tf2_msgs/TFMessage` with every `child_frame_id` empty, so truth cannot be read
  by entity name through it (spike §20).
- **rosbag2.** In Jazzy it writes MCAP by default (spike §11), the same container format as our
  run file, and Foxglove and Lichtblick read it (a replay into a viewer was not tried, spike
  §11). It fits ADR-0007's import precedent: a copy beside the run, with a SHA-256.
- **Nav2.** RFC-0015's spike and the spike's `explore_lite` run are the only experience here. The
  parked image is 5.1 GB; the spike's `mvp2-spike:jazzy-nav2` is 5.18 GB and `-proto` 5.28 GB
  (spike §12). Nav2 came up (version 1.3.14); `explore_lite` had to be built from source and
  built without changes (spike §18); no goal was reached on the duck and the cause is not known
  (RFC-0015 §8). That result is about the duck's 8x8 sensor, which "nobody configures Nav2 for".
  Nav2's defaults suit a 360 degree LiDAR (ADR-0001 context), which is the Burger's. In Jazzy
  its output is `Twist` and the bridge wants `TwistStamped`, so it needs the relay of section 3.3
  (spike §18). That is evidence for a contract join on the Burger, not a promise; the spike ran
  no goal on the Burger beyond `explore_lite`'s (spike §17). Outcome mapping already designed:
  SUCCEEDED to `reached`, planner failures to `refused`, controller failure to `stalled`
  (RFC-0015 §3.5). It duplicates our navigator's planner, costmap and recoveries (the very things
  RFC-0015 compared).
- **SLAM Toolbox.** 2.8.5. The spike drove it, with default parameters, in online asynchronous
  mode (spike §5). Needs a scan, odometry and tf, and the fixed link to the lidar from
  `/tf_static`; without `robot_state_publisher` it produced no map (spike §9, §15). Replaces
  mapd's role for a robot that has a LiDAR; mapd stays for the duck. Its pose error against
  truth is in section 3.5; its reset in section 3.4.
- **RViz against our views.** The platform's views are the Observatory (live and replay),
  Mission Control, and Rerun and Lichtblick for MCAP (ADR-0002). RViz would be a second viewer
  for data that is not in our runs. Keep it inside the ROS container. Do not build a RViz
  dependency into any contract.
- **RTAB-Map.** Needs RGB, depth, camera info, odometry (vision note section 6). Produces its own
  database, a format I have not looked at. Heavy compute: the vision note says desktop first.
  Not before a camera exists.
- **Open3D.** A new Python dependency. The rules require approval before any. It belongs in a
  separate job, not in the runner or the gate.
- **COLMAP.** Standalone; no robot needed. This is the photogrammetry project's tool.
- **Nerfstudio.** The vision note itself says a pleasing model is not collision-safe
  (section 1). No role in navigation. Never in the core.
- **Licences.** Pollen's are in RFC-0021 §7 (Apache-2.0, with CC-BY-NC-SA for their 3D models).
  I did not check the licences of any tool in this section. Do that before any is distributed.

## 5. Photogrammetry as a separate project

The operator starts a separate, non-robotics photogrammetry project on 2026-11-24, to be reused
here "in the background". It keeps its own name. The operator's answer (question 9): it lives in
its own repository and connects to this one by the file contract (a command line and a versioned
manifest). Neither imports the other. The aim of this section is that one seam.

The seam is a file contract and a command line. No import, no shared process, no shared
package.

```text
 robotics-lab                           photogrammetry project
 (a run)                                (a standalone tool)
   streams/<stream>.mcap   ---- job ---> images + images.json (+ cameras.json)
   poses from ticks                     recon --images D --manifest M --out O
   intrinsics, extrinsics   <---------- O/mesh.ply, cloud.ply, provenance.json
 model job = the part that moves data across the seam
```

What the photogrammetry side takes:

- A folder of images.
- `images.json`: a version, `"manifest": 1`, then for each image its file, a time (wall
  nanoseconds), the sensor id, and optionally a pose (`world` or `map` frame, with the frame
  named) and a quality flag. Axes and units are stated once in the file: right-handed, z up,
  metres. The pose per image is the camera's pose, not the robot's. Who applies the mount (camera
  to robot base) is the model job's, so the tool never needs the robot's frames; this is a
  proposal, to confirm when the manifest is written.
- `cameras.json`: intrinsics, distortion, resolution, and a mount (camera to robot base), per
  sensor. All optional. With none, the tool works as a plain photo reconstruction.

What it returns:

- A mesh or a point cloud (open formats), plus `provenance.json`: the inputs' checksum, the tool
  and its version, its parameters, the frame and the scale (metric or not), the time. If poses
  were given, the output is in their frame and metric. If not, it must say its scale is
  arbitrary. That is the main trap: a model without metric scale cannot be placed in a map. A
  structure-from-motion output (COLMAP) is only up to scale without poses or a scale hint.

What the robotics side must record, from the first camera onward, or a run cannot feed this
later. These rules are written down now and not built (question 3). The cameras are one of the
real Burger's first upgrades (section 3.5), so the model job and this seam are nearer-term than
the first draft said: step 11, not a distant later.

1. The images, as companion streams (section 3.6), never in `run.mcap`.
2. A time for each image in wall nanoseconds, the same clock as the ticks. The nearest-tick rule
   with a bounded gap already exists for truth
   (`libs/runfile/src/runfile/truthcopy.py:26`), and it applies here.
3. The robot's pose at each image: the belief in `map` and, in a simulator, the truth in `world`.
   Both are in the ticks today. The model job turns it into the camera's pose with the mount.
4. The camera's intrinsics and its mount, written once per run as part of `streams.json`.
5. Which sensor each image came from, so two cameras are not mixed.
6. A privacy note per run. The vision note (section 11) names faces, screens and documents in a
   home scan; retention (plan step 7) should be able to remove companion streams by run.

What the photogrammetry project should know, from this RFC, without depending on it: accept
optional poses and optional intrinsics, state its output's frame and scale, and expose a command
line with a stable manifest. The repository is decided (its own). Its licence is decided in
the project's own RFCs (question 21). Whether its first output may feed a Gazebo scene later is
not answered (questions 9 and 21).
How the images are captured and recorded, and the capture set handed to the tool, are in
section 3.11 and section 5.1.

### 5.1 Requirements toward the photogrammetry tool

The photogrammetry project lives in its own repository and connects by a file contract
(section 9, question 9, answered). **We do not compete with its image pipeline.** Reconstruction
quality is its business: its own colour handling, feature matching, scale and meshing. What this
platform owns is the capture, the recording and the poses (section 3.11). This subsection lists
what we expect of the tool and what we hand it, as requirements toward that project's own
RFCs. Decided (question 27): this RFC fixes only the handoff, the capture set with its
versioned manifest, and what comes back, a model with a scale and a frame placeable in `world`
or `map`. Everything else belongs to the tool's own RFCs.

**What we hand it: a capture set.** A capture is a mode of the camera and a model job (section
3.11.2), not a pipeline output:

- **A capture mode:** exposure, gain and white balance locked (3.11.1), so a set has one look;
  stills uncompressed or lossless (PNG), never lossy; no pipeline stage applied (3.11.3, rule 2).
- **Camera intrinsics and distortion,** and the mount (camera to robot base), per sensor, from
  the run's calibration record (section 5, rule 4).
- **A per-frame pose** from our run: the belief in `map` and, in a simulator, the truth in
  `world`, with the frame named and `source: truth|belief` on each pose; the pose is the
  camera's pose, as section 5 says. It is the nearest tick within 0.1 s (the rule of
  `truthcopy.py:26`) and a prior the tool may refine.
- **Timestamps in wall nanoseconds,** the same clock as the ticks (section 3.6), with the clock
  epoch (section 3.6) so a set that spans a simulator reset is not misread.
- **The camera's actual settings per frame** (3.11.1), so the tool can see that they were locked.

**The file layout of a capture set is the contract.** It extends section 5's `images.json` and
`cameras.json`:

```text
 <capture set>/
   manifest.json        # "manifest": N, tool-neutral; run id; frames; axes; units; clock;
                        # the source run folder, the stream, sha256 of each source chunk
   images/000001.png    # lossless or uncompressed stills, one file per frame
   depth/000001.png     # optional: 16-bit depth, same index as images/ (0 = no data)
   images.json          # per image: file, wall_ns, sensor id, pose + frame + source, settings
   cameras.json         # per sensor: intrinsics, distortion, resolution, mount (all optional)
```

Versioning: `manifest.json` carries an integer version. A reader accepts its own and older
versions and refuses a newer one, the platform's habit (section 2.2, RFC-0018 §5.3). Neither
repository imports the other; a command line and these files are the whole seam.

**What we want back,** as section 5 says and a little more exact: a mesh, a point cloud or a
splat, in an open format, with **a scale and a frame we can place in `world` or `map`**: either
metric and in the frame of the poses we gave, or an explicit transform to it, with the scale
stated; if no poses were given, it says its scale is arbitrary. Plus `provenance.json`: input
checksums, the tool and its version, its parameters, the frame, the scale and the time.

**What we expect of the tool,** without depending on it: a command line with a stable manifest;
poses and intrinsics optional; poses accepted as priors, with a statement of whether it refines
them and returns the refined ones; the same input and parameters giving the same output, as far
as it can; no need for our code.

**Points for the tool's own RFCs, not fixed here** (question 27):

- the tool's name and its licence (decided in its RFCs, question 21); that its output feeds a
  Gazebo scene is decided (question 21, 2026-11-24) and the import is ours, designed in MVP 2;
- the splat format, and which open mesh and point cloud formats it writes;
- whether the tool does its own colour normalisation (we assume it does and we hand it locked,
  unprocessed stills), and what it needs for capture (overlap, speed, motion blur, how many
  frames);
- who triggers a capture on the robot: decided on our side (2026-11-24) as the `capture_view`
  goal kind below;
- where it runs (it may need a GPU; not verified), and whether a capture set can be large
  (uncompressed, 1,661 MB a minute of colour at the spike's size, spike §19);
- how a result is placed into our frames and whether it is ever used by a mapper or a judge
  (the vision note says a pleasing model is not collision-safe; section 4, Nerfstudio).

**The gap list: from a model back to the planner** (the tool's proposal of 2026-11-24, its
`docs/wip/gap-list-interface.md`; the operator took the recommendations on 2026-11-24). After a
reconstruction the tool lists what the model lacks, each gap with viewpoints a robot could shoot
it from. The tool advises; our planner owns goals, reachability and no-go areas.

| # | Proposal | Decided |
| --- | --- | --- |
| 1 | "What we want back" gains `gaps.json`, versioned like the manifest | yes: pulled, a file beside `provenance.json` |
| 2 | The manifest gains `site`, `frame_id` and `targets` (the gaps a set was shot for) | `site` and `targets` yes; `frame_id` once frame identity (row 5) is designed |
| 3 | A goal kind `capture_view {pose or planar, tolerance, burst, gap_ids}`, done when the burst is recorded | yes, its own kind rather than `point` with a burst (one done-condition per kind); after the Burger's cameras (step 11), with a navigator contract version that gives a goal a yaw |
| 4 | The robot file's `capabilities` gain a camera entry: mount, height, pitch range, field of view | yes, in the profile's `sensors`; the tool reads our robot file, no format of its own |
| 5 | A frame identity a planner can check | ours to mint: one id per map of a site, minted when the map is made, kept across a relocalisation only when the navigator says so; designed with section 7 item 10 |
| 6 | A slot for the tool's MCP server beside Mission Control's, with its own token and client name | yes; the tool serves its own HTTP API on the tailnet with a token, and a stdio MCP on the agent's machine is its client, as ours is |
| 7 | A robot's claim on a gap has a shorter lease than a person's | yes |

Yaw in every pose we exchange is REP-103: radians about +z, zero along +x, counter-clockwise
positive; a quaternion is the named `{x, y, z, w}` on the wire (`runfile/wire.py`), `[w, x, y, z]`
in the run (ADR-0016).

## 6. The evolution from A to B

Rules for every step: MVP 1 keeps working; each step ends green on `make ci-fast`,
`make sim-duck` and the challenge batch whose verdicts must match the last batch (as in plan
items 1 and 2); a step changes one seam. Sizes are rough (S, M, L) and not estimates in time.

The order follows the operator's answers. Goals first, courses later (question 2): MVP 2 starts
with Mission Control's goals, driving by hand, maps and runs in the Observatory. Our navigator
comes before Nav2 for the Burger (question 6). The NXT gets our navigator (question 5). The real
Burger is the end of MVP 2 (question 8).

| Step | What changes | What stays | Proof | Size | Decided by |
| --- | --- | --- | --- | --- | --- |
| 0 | Accept this RFC and ADR-0020 together (question 10); name the follow-up RFCs | All code | The operator's decision | S | this RFC, ADR-0020 |
| 0b | The spike, done (section 6.1), zero platform code: the TurtleBot3 Gazebo simulation in a container, driving by hand, SLAM Toolbox, a saved map; the real-time factor; the bridge's stamps; whether the base holds the last velocity; three extensions (SLAM against truth, cameras, a throwaway connector) | All code | Measured answers to many of section 10's "not verified" items; notes in `docs/wip/MVP2-SPIKE.md` | S | the operator (question 14) |
| 1 | The robot interface written as a contract with a number; the duck's connector and the NXT's brought to it; the gate takes method names from it (the gate's calls themselves needed no change in the spike, spike §20); the adapter surface written down, with `robot.state` gaining the clock and epoch keys (section 3.6); a connector reachable by a network address, for the placement setting (section 3.8) | Duck behaviour, protocol 1 accepted by the new gate | One contract test run against the fake, duck-gate and NXT adapters (as `test_contract.py` does for navigators); `make sim-duck` | M | RFC-0026, "the robot interface" |
| 2 | Profile v2: required blocks shrink to identity, factsheet, control, capabilities, plugins; locomotion, footprint, sensors become per-kind; a plugin set may be empty; the judge's fall rule by kinematics; sensors declared per robot and variant, with a source per sensor (sections 3.9, 3.10); registration names its connector; the placement setting has a home | The duck's profile migrated by `upgrade` (`profile.py:503`), checksums rule | Every stored profile loads; the duck's numbers unchanged; a plugin-less stub profile validates | M | RFC-0027, "profiles for any robot" |
| 3 | Our navigator for any robot (section 3.7): `duck_lab.nav` split into a part that knows no robot and the duck's plugins; the plugin interfaces widened (a scan, a single range, a mapper that is not mapd); the Burger's plugins (differential drive, 2D scan, localisation) and the NXT's (tracked, ultrasonic, dead reckoning), proved against stubs | The duck's verdicts; navigator contract 1.2 | The duck's challenge verdicts match; one contract test against all three plugin sets | L | a new RFC, "a navigator for any robot" (number to be given) |
| 4 | The host kind written as a contract; `simhost` gets a module per kind, starting from what the NXT's kind needed in MVP 1 (below); a stub Gazebo host, and the gate's fake adapter proves lease, STOP and state in Mission Control; a run with a stub scan, to settle the run format and the clock epoch (decided here, not in step 8, because step 5a's reset proof needs it); a reset that returns only when settled (section 3.4) | MuJoCo kind unchanged; `scene.json` and the layout readers untouched | The robot page shows the stub; a run opens in the Observatory; the duck's verdicts match | M | RFC-0028, "host kinds" (the scene part moves to step 9) |
| 5a | The Burger in Gazebo, joined at the interface, without our navigator: the ROS connector (split placement first), the bridge, `/scan`, `/odom`, `/imu`, truth from the model's odometry plugin (section 3.4); the host kind and its settled-reset contract; driving by hand from Mission Control; a run with truth; simulator time beside wall time and the real-time factor checked each run (question 7); the clock rule and the clock epoch of section 3.6; the last-hop watchdog (the connector in the simulator) and the `Twist` relay (section 3.3); the reset sequence of section 3.6. A stock TurtleBot3 world until step 9 (question 20, decided) | Nothing of the duck | Drive the Burger from Mission Control; a recorded run with truth; the reset sequence of 3.6 proved: a reset in the middle of a run with belief and truth still moving afterwards; `map`-to-`world` from the spawn pose checked against truth. Needs steps 1 and 4 only; runs in parallel with step 3 | L | ADR on time and frames, now that the clock rule is settled (question 13, closed) |
| 5b | Our navigator drives the Burger in Gazebo: the Burger's plugins from step 3 against the live connector; Mission Control's goals; maps and runs in the Observatory | The connector and the reset of 5a | A goal reaches by truth; the duck's verdicts still match. Needs steps 3 and 5a | M | the new navigator RFC |
| 6 | The NXT's navigator: our navigator with tracked plugins on the real NXT (RFC-0020 §6 step 5); the NXT's gate on the written interface from step 1 | The NXT's HTTP API | A goal reached by the real NXT. The kinematic NXT simulator of MVP 1 (below) can run the navigator first; with no map until the Pi module's design (question 16) | M to L | the new navigator RFC; the operator's hardware |
| 7 | The contract join: Nav2 and SLAM Toolbox behind contract 1.3 (`yaw`); the wrapper; the outcome map | Contract 1.x readers | A `point` goal reaches by truth; the contract test passes against the wrapper; the duck still passes | L | RFC-0029, "a robot that navigates itself" |
| 8 | A 2D scan channel in the run (or points, question 23); the ADR-0007 note for the clock epoch of step 4; the mapper's pose against truth; the Observatory draws the scan and the map (question 11) | Format 2 readers (additive) | The Observatory draws the scan and the map; the list of `wire.py` and `mcapio.py` changes of section 3.5 is done | M | a note in ADR-0007 |
| 9 | Courses in Gazebo: `scene.json` becomes the source; an SDF scene writer; the five layout readers move off the layout | MuJoCo kind unchanged | Challenge verdicts match; the `scene` test (61 boxes equal) extended; a challenge runs in Gazebo | M to L | RFC-0028, the scene part |
| 10 | The real Burger on hardware: the connector placed by the robot's setting (the split first), the Pi's bringup and the Pi's last-hop watchdog node; DDS set with `ROS_AUTOMATIC_DISCOVERY_RANGE` and `ROS_STATIC_PEERS`; a safety review; link loss; STOP over Wi-Fi; driving from Mission Control. The review (question 19): the operator runs it at the robot from a written checklist and test scripts we prepare (the Pi watchdog, a Wi-Fi pull test, STOP latency, the OpenCR firmware version read, a first drive by hand); an independent reviewer agent checks the results before the first navigator drive. Checklist: `/cmd_vel` type (the bringup's `enable_stamped_cmd_vel: true`, the Pi's node version, section 3.3); the OpenCR firmware version | The simulator path | The operator and the robot, as the real duck's B6; STOP and a lost link measured on the real base: pull the Wi-Fi, and the base stops within X s (X is set in the safety review). MVP 2 ends here | M | the operator, after the safety review |
| 11 | Cameras and image recording (section 3.11): an RGB and a depth camera on the real Burger (one of its first hardware upgrades), then matching simulated ones (question 22); capture settings declared in the profile and the camera's actual values recorded per frame; companion streams with the recording options of 3.11.2; calibration records; retention per run and per stream; the Images block in Mission Control's Settings and its summary in the run's start record and the Observatory (3.11.4) | Ticks | A recorded run with images whose index holds the actual settings; the panel's estimated MB a minute against the measured size; a run's summary shown in the Observatory | L | a later RFC, after the cameras are chosen |
| 12 | The image pipeline (3.11.3): named, versioned stages, per-consumer branches, recorded in the run, re-run on replay; first in a model job or live, by question 26; varied world lighting in Gazebo to test it (3.11.5) | The recorded stream stays the camera's output | An old run reprocessed with a newer pipeline version gives a new output and an unchanged recording; the pipeline version is read back from the run | M | the same later RFC, after step 11 |
| 13 | The photogrammetry seam (section 5.1): the capture mode (locked settings, lossless stills), the capture set's file layout as a versioned contract, the first model job | Ticks, companion streams | A capture set written from a run opens in the tool's command line (the tool is the operator's, question 27); its result is placed in `world` or `map` with a scale | M | the operator's tool RFC and the later RFC |

Order of the steps (a dependency graph, not a schedule):

```text
 0 -> 0b -> 1 -> 2 -> 3 --------------------------------> 6   (the NXT's navigator)
            |         |
            |         +-----------------------+
            |                                 v
            +-> 4 --> 5a ------------------> 5b --+--> 7 -> 8 -> 11 -> 12 -> 13
                       |                           |   (11: cameras, after the real
                       |                           |    Burger arrives; 12: pipeline;
                       |                           |    13: photogrammetry seam)
                       |                           +--> 9   (courses in Gazebo; off the
                       |                                     critical path)
                       +---------------------------------> 10   (the real Burger; MVP 2 ends)
```

Step 5a needs steps 1 and 4 only and can run in parallel with step 3; step 5b needs 3 and 5a.
The sizes of 5a (L) and 5b (M) are my rough split of the old step 5's L, not an estimate.

Step 3 is on the critical path and is the largest. Step 9 is off it: it starts only after the
Burger's navigation works (step 5b). Step 10 needs step 5a (the connector and the watchdog);
my reading is that it need not wait for 5b or 7 to 9 if the
robot and the review are ready. Step 8 is after step 7 in the operator's order. If the
Observatory needs the scan sooner, step 8 can move before step 7. Step 5a does not wait for the
scan's run-format change: the spike's connector carried the scan as `/depth` points with the
range limits in `raw.scan` and the Observatory drew it (spike §20), so step 5a may do the same
until step 8 (question 23). It does wait for the clock epoch, which step 4 settles.

### 6.0 The NXT's simulator in MVP 1 lowers the risk of step 4

NXT-MVP1.md (item 4d, units D0 to D10) builds a kinematic NXT simulator inside nxt-web and a host
kind `nxt-kinematic-sim` in `simhost` in MVP 1 (the operator chose option A on 2026-11-23). The
host-kind seam is therefore exercised by a real second kind before Gazebo arrives: D3 adds
per-kind dispatch in `simhost`, a reset, a truth port and a reader giving `(wall_ns, pose)`, and
no Pollen keys for that kind, with `make sim-duck` unchanged; D0 writes down what the kind needed
(NXT-MVP1.md). That reduces the risk of step 4 (writing the host-kind contract) and of the second
host kind in step 5a: the contract starts from two working kinds instead of one built and one
stubbed. It also brings forward steps 1 and 2's questions (a second connector in HTTP, a NXT
profile) and a second sensor kind, a single range value (NXT-MVP1.md). Two cautions, both from
NXT-MVP1.md: the risk of writing the host contract twice (keep the per-kind dispatch minimal, and
let RFC-0028 start from D0), and the NXT kind has a different truth source and no scene writer
(it reads `scene.json` itself), so it does not exercise the scene-writer half of the contract,
which Gazebo does (step 9). Gazebo's reset (`reset all`, section 3.4) and truth reader
(section 3.4) remain untried on the platform, and the NXT's kinematic simulator will not teach
the settled-reset contract (section 3.4). The NXT simulator also answers the simulator half
of question 16, so step 6 need not prove itself on the real NXT only. The NXT's range sensor
and mapper wait for the Pi module's design (question 16).

### 6.1 Step 0b, the spike (done)

The operator said on 2026-11-23 that the one-day spike runs now, before the RFCs (question 14). It
ran the same day, about three hours, with three extensions of about one hour more (spike §1, status
update); its notes are `docs/wip/MVP2-SPIKE.md`, read for this draft. It touched no platform code
and nothing in the repository but its own file. Its throwaway connector, Observatory and files
live outside the repository, in `~/.cache/robotics-lab-tests/mvp2-spike/` (spike header). What it
settled and what it left:

| Question | Result | Section here |
| --- | --- | --- |
| Which versions | ROS 2 Jazzy, Gazebo Harmonic 8.15, `turtlebot3_gazebo` 2.3.7, SLAM Toolbox 2.8.5, `ros_gz` 1.0.25 (spike §3) | 8.10 |
| How the bridge stamps | simulation time; the clock rule is settled (spike §7) | 3.6 |
| Does the base stop | no: the simulator and ROS 2 firmware hold the last velocity; a watchdog is needed, and the connector's worked in the simulator (spike §8, §20) | 3.3 |
| Reset | 0.26 s if the robot is in the world file; the clock goes to 0 (spike §9) | 3.4, 3.6 |
| A scan schema | `foxglove.LaserScan` exists, lacks the range limits; `wire.py` needs changes (spike §10, §20) | 3.5, 8.7 |
| Recording | MCAP by default in Jazzy (spike §11) | 3.6 |
| Cameras, SLAM accuracy, exploration | numbers with limits (spike §18, §19) | 3.5, 3.6 |
| A connector end to end | `robot.*` served, run written, Observatory replayed; the gate's calls unchanged (spike §20) | 3.3, 3.6 |
| After a reset | belief and truth froze in the prototype; three causes diagnosed, then confirmed by a re-run with the full sequence (spike §20, §21) | 3.6, 7 |

The OpenCR statement is from source on GitHub, not from the operator's robot (spike §8, §17).

Where an ADR is warranted: the clock policy (the amendment to ADR-0020 decision 3 is made, now that
the spike confirms the rule; step 5a still needs an ADR on time and frames that covers the clock
epoch), the rule that the connector owns the velocity path and the last-hop watchdog is the deadman
(ADR-0020 decision 2, narrowed as section 3.3 says), and the frames rule (ADR-0020 decision 4 to
become a contract in step 1).

What must be true before step 3 starts: the answers to questions 16 and 17 (the NXT
has no map until the Pi module's design; the Burger's mapper is SLAM Toolbox). Before step 5a:
question 18 (decided: both), and the
reset sequence of section 3.6 (the connector's tf state across a reset; the re-run, spike §21).

## 7. Problems still to solve, ranked

Ranked by how early they bite and how much they cost to get wrong. Time and stamps rank above
"who drives": the first breaks tf in the simulator, the second is a design rule. Our navigator
for any robot ranks second: it is the largest piece and the operator's answers put it on the
critical path.

1. **The robot interface is robotd's.** It bites at the first Burger command. The gate's method
   list, the `vy` field, the stop sequence and `DuckAdapter.state` all assume robotd
   (section 2.4, items 1 and 2). Until it is a contract with a number, every second robot
   imitates the first one's daemon. This is the central design task.
2. **Our navigator is the duck's.** It bites at step 3 and is the largest piece of MVP 2. The
   operator wants it to drive a legged duck, a differential-drive Burger and a tracked NXT
   (questions 5 and 6), through RFC-0020's four plugin interfaces. Today it assumes the duck in many
   places (section 3.7): an 8x8 depth grid and a reflex on each frame (`run.py:9-11`, `:28`); three
   fixed sockets, with mapd behind one (`run.py:159`, `:230`); a turn rule with a pivot room and a
   kick (`explore_run.py:76-96`); a head that glances at drops (`run.py:736-743`); and robotd's stop
   sequence (`run.py:11`). The NXT is the hard case: ultrasonic and colour only (not verified in
   code), no odometry beyond motor counts (not verified), so its belief of where it is drifts and a
   mapper needs something to map from. A navigator that is safe on a robot with no head and no drop
   sensing is not verified either; the decision on drop sensing is in section 3.7. If the split is
   done badly, the duck regresses; the duck's verdicts are the guard.
3. **The profile requires the duck.** A Burger profile today must invent a circular footprint
   with a lethal and an inflation ring tuned to a duck, a locomotion block with a turn kick, and a
   plugin for every block (`profile.py:179-189`, `:235`, `:492-494`). The fix is a schema
   change. It touches every stored profile and the checksum rules, so it needs a migration, not
   an edit.
4. **Time and stamps.** The assumption of wall time is stated (ADR-0020 decision 3) but not
   enforced, and a second problem sat under it. `ros_gz_bridge` stamps with simulation time
   starting at 0 (spike §7), so a ROS graph on `use_sim_time` false fails its tf lookups. The
   rule is now settled (section 3.6): sim time inside the graph, the connector where the two
   clocks meet. What stays: a Gazebo scene may fall below real time. The spike's scan, IMU and
   odometry run held 1.00 and cameras at 640 x 480 and 30 Hz held 1.0001 on software rendering
   (spike §6, §19), but one workstation, single runs. A run below real-time factor 1 silently
   changes timing, timeouts and the 0.1 s truth pairing
   (`libs/runfile/src/runfile/truthcopy.py:26`). The operator decided: record the simulator's
   time beside wall time and check the factor each run (question 7). Decided (the operator
   confirmed, 2026-11-23): a factor
   below 1 is the anomaly `rtf_low`, and the judge gives no verdict below a threshold (0.95 is a
   guess). The clock epoch and the tf problem across a reset are item 19.
5. **Who drives, on an open graph.** A design rule, not a blocker in the simulator. ADR-0020
   says the connector is the sole publisher, but on DDS any node can publish `/cmd_vel`. The rule
   is narrowed by convention and watched: a remap to a topic only the connector publishes, one
   place where velocity requests meet that the connector owns, a watch for other publishers
   (`someone_else_drives`), and `ROS_DOMAIN_ID` isolation (section 3.3). On the duck, "other
   doors" are acknowledged and watched (plan 4b item B4); the ROS graph has more of them.
6. **DDS discovery across Wi-Fi and host-network containers.** The connector, Nav2 and the
   Burger's bringup will sit on different computers, with `--network host` containers (as
   RFC-0015's spike ran). Multicast discovery often fails on Wi-Fi. Likely the first thing to
   break on a real Burger (the advisor's judgement; not verified here). Decided (the operator
   confirmed, 2026-11-23): step 10 sets `ROS_AUTOMATIC_DISCOVERY_RANGE`
   and `ROS_STATIC_PEERS` instead of relying on multicast.
7. **Placement as a per-robot setting costs more than one placement.** The operator asked for
   all three placements if the effort is reasonable (question 1). Each one is a case to test.
   Networking: the connector on the Pi needs a network address where today's sockets are paths.
   DDS across machines: with the connector on the Pi and Nav2 or our navigator on the
   workstation, ROS traffic crosses Wi-Fi in two of the three placements, and the discovery
   problem of item 6 applies to each. A slow link changes what the navigator sees and when the
   deadman fires. The cost of each placement is not measured. The rule: build the split first;
   add another only when the first is done and its cost is known.
8. **The scene is MuJoCo geoms.** Five readers (section 2.4 item 7), the Observatory's analysis
   with its name conventions (`anomalies.py:85-100`), and the challenge scene writer that builds
   from Pollen's XML (RFC-0021 §3.1). The operator decided goals first, courses later
   (question 2), so the SDF writer moves to step 9, off the critical path. Until then the Burger
   runs in a stock world, and the Observatory's name conventions see no `stair*` or `lm_*`.
9. **The judge and the truth for a wheeled body.** "Trunk height" and a fall threshold
   (`profile.json:188`, `truth.py:29-31`) mean nothing for a Burger. The judge needs a
   kinematics-aware fall rule and a truth reader per host kind. For Gazebo the bridge cannot be
   the truth reader: it drops entity names, so the spike read the pose with `gz topic
   --json-output` (spike §20), at a visible CPU cost and with a crash after a reset (item 19);
   the decided reader is a model plugin (section 3.4).
10. **Frames.** SLAM Toolbox publishes `map` to `odom`, which jumps. Our run has one `map` frame
   and epochs. The duck's frame has a scale correction (0.91). A ROS connector must say which
   frame its odometry is in, and whether it scales. A map's origin differs per mapping session.
11. **A scan in the run** (section 3.5): a point cloud with kinds is not a scan, and `wire.py`
    cannot take a scan channel unchanged (spike §20). The operator decided a scan channel in the
    run (question 11); its shape is section 8.7 and question 23.
12. **Safety on Wi-Fi.** The real Burger is on Wi-Fi, the connector on another computer. A lost
    link must stop the robot. The base holds the last velocity: the simulator's plugin does, and
    the ROS 2 firmware does while its node lives (spike §8, from source; not run on a real robot;
    the flashed firmware is unknown). So a connector on the workstation cannot stop a robot over
    a dead link. The deadman is a last-hop watchdog on the computer wired to the motor
    controller: a small node on the Pi that forwards `/cmd_vel` only while it is fresh and
    publishes zero otherwise (section 3.3). Step 10 proves it: pull the Wi-Fi, and the base
    stops within X s. A dead `turtlebot3_node`
    stops the base within about 500 ms through the firmware's heartbeat, which does not cover a
    live node whose `/cmd_vel` stream stops (spike §8). This is the Burger's version of the
    duck's B5 link tooling. The real Burger is in MVP 2 (question 8), so the safety review,
    link loss and STOP over Wi-Fi are part of step 10, not later.
13. **Contract 1.3 and goals.** `point` has no heading (`CONTRACT.md:45`), and a Nav2 goal has
    one. The duck's other kinds (`go_to_object`, `explore`, `inventory`) have no Nav2 meaning
    without a recogniser and a frontier explorer. "Explore" for the Burger is still not defined
    in our contract, but exploration matters and a ready frontier explorer exists for ROS:
    `explore_lite` mapped 21.35 m2 in about 51 s against a crude wall-follower's 11.67 m2 in
    175 s (spike §18; the comparison is unfair to the crude one, section 3.5).
14. **Data volume and bandwidth.** RGB-D at any rate is large: raw 640 x 480 RGB and depth at
    30 Hz are 3.9 GB a minute, and 17 to 25 MB a minute compressed in a flat render, a lower
    bound (spike §19). A Pi and Wi-Fi may not carry the raw rate (vision note section 11); that
    is not measured. This decides whether images are recorded on the robot's computer or the
    navigator's.
15. **Calibration and sim to real.** Extrinsics and intrinsics have no home. Plan unit A3's
    calibration frame (odometry scale through a navigator method) is the nearest, and it is
    duck-only today.
16. **Install weight and hosts.** Gazebo and a ROS image add gigabytes: `mvp2-spike:jazzy` is
    4.32 GB, `-nav2` 5.18 GB and `-proto` 5.28 GB (spike §12; `docker images` sizes, and the spike
    notes that its `inspect` figure of 931 MB is a different measure). The apt layer with
    TurtleBot3, ros_gz, Gazebo and SLAM Toolbox is 2.4 GB of that; the build took 157 s for apt
    (spike §12). The setup and check scripts (RFC-0021 §4) cover Pollen's simulator only. Gazebo
    runs on the workstation first (question 12); on the MacBook it is not verified and not
    required.
17. **Anomaly kinds.** The robot-raised anomaly kinds (`anomalies.py:639`) are the duck's; a
    Burger's (a scan lost, a mapper jump) need names, and the duck's should not be assumed.

18. **The real Burger's hardware upgrade for cameras.** One of its first upgrades is an RGB and
    a depth camera, and other sensors, for better 2D and 3D mapping (the operator, 2026-11-23).
    It brings four problems, all from the vision note's cautions and none verified here:
    mounting (field of view: what the camera sees of the robot's own body and of the floor);
    power (a depth camera on USB may draw more than the Pi's port gives, and cable length and
    quality matter); bandwidth and compute on the Pi (images over Wi-Fi, decoding, depth
    processing, which also decides whether images are recorded on the robot or on the
    workstation, item 14); and calibration (intrinsics, and a mount that is measured, not
    guessed, written once per run). Each one changes placement (section 3.8) and the safety
    review (step 10).
19. **The connector's tf state across a world reset (diagnosed from code and logs, confirmed by
    a re-run, spike §21).** After a reset the sim clock goes to 0, and in the spike belief and
    truth in the run froze. Three causes: the truth reader crashed on a missing `sec`; the tf
    buffer was built without the node clock; SLAM Toolbox stamped `map`-to-`odom` with the last
    scan's stamp (`restamp_tf` false), which a cleared buffer rejects (section 3.6). The reset
    is needed for every course, so step 5a must prove the ordered sequence of section 3.6: `reset
    all`, `/slam_toolbox/reset`, `restamp_tf: true`, the buffer on the node clock, a stale-epoch
    filter, and a truth reader that is not a JSON subprocess. The spike's reset run did not call
    `/slam_toolbox/reset`, so it did not test this design. The earlier "not established" is the
    reader's crash, now diagnosed (cause 1).
20. **A robot with two sensor sources.** The NXT with a Pi module has a brick's sensors and a
    Pi's, each declared in the profile, on possibly two machines (section 3.10). Nothing in
    profile v2 (step 2) assumes it yet; D0 of NXT-MVP1.md records it as a requirement. Not
    designed here: the Pi module's hardware and link.

## 8. Options and recommendations

### 8.1 The robot interface

- **A.** The duck's `robot.*` stays the platform's interface; every connector imitates robotd.
  Rejected by the operator (ADR-0020, alternatives).
- **B.** Write ours as a versioned contract, starting from the current method names where they
  fit; the duck's connector first (today a pass-through); declare what differs. Cost: a contract
  to maintain.
- **C.** Adopt an outside standard as the interface. VDA 5050 is already the factsheet's naming
  (`robots.py:8-10`) and is not a command protocol for driving by hand; ROS's messages as the
  interface would make ROS the foundation, which ADR-0020 rejects.

Recommendation: B. Keep JSON-RPC and the names `robot.move`, `robot.stop`, `robot.state`,
`robot.health` in version 1, so nothing breaks; add what is missing through the profile's
`capabilities`.

Open: not a question in section 9. B is the recommendation, and ADR-0020 decision 2 already
rules out A. It is settled when the operator accepts this RFC.

### 8.2 Where the Burger's software runs

- **A.** All on the Burger's Pi. Fewest hops, but the Pi's compute is limited (vision note
  section 4) and a lost link leaves a robot navigating alone.
- **B.** The split: the Pi runs only the robot's bringup; Nav2 or our navigator, SLAM Toolbox
  and the connector run on the workstation (RFC-0017 §3.2 puts the gate there). Cost: ROS traffic
  over Wi-Fi (not verified).
- **C.** All on the workstation.

Decided (question 1): support all three, as a per-robot setting in the robot's configuration
(section 3.8), designed in from the start. Build the split (B) first and the others when needed,
if the cost stays reasonable. The vision note says the same about the first one: "run heavier SLAM
and reconstruction on a desktop initially". In the simulator everything runs on one host.

### 8.3 Ways to join

- **A.** Interface join only. Burger driven by our navigator. Writes a lot of what Nav2 has.
- **B.** Contract join only. Fast to a mapped Burger, but nothing proves "we drive it" for ROS.
- **C.** Both first-class in the contracts.

Decided (question 6): C, and OUR navigator first. For the Burger, the interface join with our
navigator comes before the contract join with Nav2 (steps 5b and 7). The navigator is ours for
any robot (section 3.7).

### 8.4 Time

- **A.** Wall clocks only, real-time factor 1 recorded (ADR-0020 decision 3 as accepted).
- **B.** A, plus `sim_time` recorded beside wall time and checked against the factor each run.
- **C.** A platform clock with pause and step.

Inside the ROS graph, the choice of A or B leaves one more question: the stamps. The
simulator's bridge stamps with simulation time (spike §7), so `use_sim_time` false fails tf
lookups, and RFC-0015's way out (the bridge stamped with its own clock, `nav2/bridge.py:5`) is
not available for a Gazebo bridge.

Recommendation: B, with the amendment to decision 3, now settled: inside the ROS graph
`use_sim_time` true at a real-time factor of 1; the connector is where the two clocks meet, stamps
`wall_ns` on receipt and records the ROS stamp beside it; the run's time stays wall time; a clock
epoch marks each reset (section 3.6). It is nearly free (`truth.py:7-9`), makes slow runs visible,
and leaves C open without building it.

Decided (question 7): B, recording the simulator's time beside wall time and checking the factor
each run. Decided by the spike (question 13, closed): the stamp rule and the clock epoch. The
re-run confirmed the connector's tf reset sequence (section 3.6, item 19; spike §21), and
the epoch is first-class, the pair (epoch, t_src), decided in step 4 (question 24, answered).

### 8.5 The scene

- **A.** One hand-made scene per host kind. Drift between them.
- **B.** `scene.json` is the source; each host kind writes its format; the layout's readers move
  to the scene's boxes (the plan's test that the two agree already exists).
- **C.** Gazebo's world becomes canonical. Ties the platform to one simulator.

Recommendation: B.

Decided (question 2): B in direction, and later. Goals first. The SDF writer from `scene.json`
and the move of the five layout readers come after the Burger's navigation works, off the
critical path (step 9).

### 8.6 The profile

- **A.** The Burger fills duck-shaped blocks with stand-ins.
- **B.** Profile v2: per-kind blocks, a plugin set that may be empty, sensors as a declared list.
- **C.** Split into a connector profile and a navigator profile.

Recommendation: B, with C's split noted: a robot that joins at the contract needs no navigator
profile.

Open: not a question in section 9. B is the recommendation, and step 3 (our navigator for any
robot) leans on it. It is settled when the operator accepts this RFC.

### 8.7 The scan in the run

- **A.** As points in `/depth`, with the range limits in the tick's `raw.scan`. This is what the
  spike's connector did, and the Observatory drew it as "Depth obstacle" (spike §20). Needs no
  run-format change, but loses the rays: free space and maximum range.
- **B.** A new additive `/scan` channel in a Foxglove shape. `foxglove.LaserScan` exists (spike
  §10). It has no range limits and no angle step, so those go in the run's header or the profile
  (spike §13), and the channel needs the `wire.py` and `mcapio.py` changes of section 3.5.
- **C.** A companion stream, for example the rosbag2 MCAP of section 3.6, with
  `sensor_msgs/LaserScan` (cdr), a route the spike did not test in a viewer (spike §10).

Recommendation: B for a 2D scan (it is small: about 75 kB a second with odometry and tf,
spike §11), with the range limits and angle step in the profile's sensor declaration (the
numbers sim and real disagree on belong there, spike §16); A until step 8 so that step 5a does not
wait; C for anything image-like.

The advisor's recommendation adds: the range limits (`range_min`, `range_max`) and the angle
step (`angle_increment`) are static, in the profile's sensor declaration; while A is used,
`carried_as` stays in `raw.scan`; the scan is in the `map` frame with its pose as the scan's
origin, matching `/depth`; and a protobuf float64 `ranges` array costs 360 x 8 B x 5 Hz, which
is 14 kB a second.

Decided (question 11): a scan channel in the run (B). The Observatory draws the 2D scans and the
maps, and MCAP viewers (Rerun, Lichtblick) read the file for free (not verified for
`foxglove.LaserScan` in Lichtblick, spike §10). RViz is a debug aid in the ROS container only.
Decided (question 23, 2026-11-23): B, with A until step 8, so step 5a may start with A;
`range_min`, `range_max` and `angle_increment` live in the profile's sensor declaration.

### 8.8 The NXT's place in the model

- **A.** An interface join with no navigator, as today.
- **B.** A connector plus our navigator with tracked plugins (RFC-0020 step 5).
- **C.** Out of the model until MVP 1 is done.

The first draft recommended A. The operator decided otherwise.

Decided (question 5): B. The NXT gets our navigator, with tracked plugins (RFC-0020 §6 step 5),
as part of MVP 2 (step 6). What it senses and whether it needs new hardware wait
for the Pi module's design (question 16).

### 8.9 Photogrammetry

- **A.** Library: the robotics side imports it. Couples releases.
- **B.** File contract and CLI (section 5).
- **C.** A service. More to run, no gain now.

Recommendation: B.

Decided (question 9): B. The photogrammetry project lives in its own repository and connects by
the file contract; neither imports the other. Its licence is decided in that project's RFCs
(question 21). The Gazebo-scene half of questions 9 and 21 is not answered.

### 8.10 ROS 2 and Gazebo versions

- **A.** ROS 2 Jazzy, the parked image's (ADR-0018), with the Gazebo that goes with it.
- **B.** Another pair, if the TurtleBot3 packages need one.

Decided by the spike (question 4, closed): A. ROS 2 Jazzy, Gazebo Sim 8.15.0 (Harmonic),
`turtlebot3_gazebo` 2.3.7, SLAM Toolbox 2.8.5, `ros_gz` 1.0.25 (spike §2, §3); no second pair was
needed. Not verified: the `main` branch, support dates of Jazzy and Harmonic (spike §3). ADR-0020's
"Open" item is settled.

### 8.11 Where Gazebo runs

- **A.** The workstation. **B.** The workstation and the MacBook.

Decided (question 12): A first. The MacBook comes later and is not required for MVP 2.

## 9. Questions for the operator

Questions 1 to 15 were answered by the operator on 2026-11-23; the answers are under each.
Questions 16 to 27 were raised by the answers, the operator's later input on cameras, and the
spike; the operator answered them on 2026-11-23 too, and each answer is under its question
("Answered (2026-11-23)"). The advisor's recommendations (Fable 5.1) stay on the questions as
the record of what was proposed. The last two open parts, the Gazebo-scene half of questions 9
and 21 and the NXT's range sensor and mapper (question 16), were answered on 2026-11-24.
Draft 3 closed questions 4 and 13 (the spike answered them) and 14 (the spike ran), answered
the simulator half of 16 (NXT-MVP1.md), and added questions 23 to 27.

1. **Where does Nav2 run:** on the Burger's Pi, in a container on the navigator's computer, or
   mixed (option 8.2)? It decides where the ROS connector lives.
   Answered: "Maybe we can have some flexibility here and support all 3 options as part of
   platform:robot configuration. If reasonable effort." Placement is a per-robot setting
   (section 3.8). Build the split first; the others when needed, if the cost stays reasonable.
2. **What does "fully compatible" mean for the Burger:** the challenge courses run in Gazebo
   (an SDF writer is needed), or Mission Control's goals only?
   Answered: goals first, courses later. MVP 2 starts with Mission Control goals, driving by
   hand, maps and runs in the Observatory. The courses in Gazebo (the scene writer from
   `scene.json`, moving the five layout readers) come after the Burger's navigation works, off
   the critical path (step 9).
3. **Which sensors, on which robot, when:** the Burger's LiDAR model (not known here), an IMU
   used or not, a camera: which one and from which step? Until then there is no image channel.
   Answered: LiDAR, IMU and wheel odometry now. No camera channel until a camera is chosen. The
   recording rules for images are written down now (section 5), not built. Added later the same
   day: this holds for the simulator start. An RGB and a depth camera are one of the real
   Burger's first hardware upgrades (step 11), so the sensor layer is designed for cameras now
   (section 3.5).
4. **ROS 2 and Gazebo versions.** The parked image is Jazzy; the Burger's support for it, and
   which Gazebo to pair, are not checked.
   Answered: decide in the spike; the default is ROS 2 Jazzy, the parked image's.
   **Closed by the spike (spike §2, §3, §13):** ROS 2 Jazzy, Gazebo Sim 8.15.0 (Harmonic),
   `turtlebot3_gazebo` 2.3.7, SLAM Toolbox 2.8.5, `ros_gz` 1.0.25. Section 8.10.
5. **The NXT's place:** option 8.8 A, B or C.
   Answered: the NXT gets our navigator (tracked-robot plugins; RFC-0020 step 5) as part of
   MVP 2. That is option B (section 3.7, step 6).
6. **Both ways of joining first-class (8.3 C), or one?** And is a navigator of ours for the
   Burger wanted at all, or only Nav2 behind the contract?
   Answered: both joins first-class; OUR navigator first. For the Burger, the interface join
   with our navigator comes before the contract join with Nav2.
7. **Time:** accept 8.4 B (record `sim_time`, check the factor)? Real-time factor 1 and the
   platform's wall clock stay as ADR-0020 decision 3 says; question 13 is the separate stamp
   rule.
   Answered: yes. Record the simulator's time beside wall time in every run, and check the
   real-time factor each run.
8. **Does the Burger on hardware belong to MVP 2, or only the simulated one?** It changes
   whether the safety review (step 10) is in the plan.
   Answered: both, simulator first. MVP 2 ends with the real Burger driving from Mission Control
   after a safety review (step 10).
9. **Photogrammetry:** where does the project live (this repository or its own), what licence,
   and may its first output feed a Gazebo scene later?
   Answered: in its own repository, connected by the file contract (a command line and a
   versioned manifest). Neither imports the other. The licence and the Gazebo scene part were
   not answered; question 21 asks them again.
10. **Is ADR-0020 accepted now,** or after the interface RFC? And, if the words in "Names" are
    approved, is it amended to use them?
    Answered: ADR-0020 is accepted together with RFC-0025, when the operator accepts the RFC,
    reworded with the new terms. It is reworded in this revision.
11. **Which viewer for 2D scans:** the Observatory, or Rerun and Lichtblick through MCAP?
    Answered: the Observatory draws the 2D scans and the maps (a scan channel in the run), and
    MCAP viewers come for free. RViz is a debug aid in the ROS container only.
12. **Should the MacBook run Gazebo,** or only the workstation?
    Answered: Gazebo on the workstation first. The MacBook later, not required for MVP 2.
13. **A proposed amendment to ADR-0020 decision 3, for you to confirm or refuse.** Keep the
    real-time factor at 1 and the platform on wall time, as you accepted. Add one rule: inside
    the ROS graph `use_sim_time` is true, and the connector is where the two clocks meet,
    stamping `wall_ns` on receipt and recording the ROS stamp beside it. The reason is that
    `ros_gz_bridge` stamps with simulation time (not verified here).
    Answered: the clock rule stays PROPOSED until the spike confirms how Gazebo's bridge stamps
    messages. ADR-0020 decision 3 carries it as a "proposed amendment, pending the spike".
    **Closed by the spike (spike §7, §13, §20):** the bridge stamps with simulation time, so the
    rule holds and ADR-0020 decision 3 now states it as settled, with the clock epoch added
    (section 3.6). Accepting this RFC accepts the rule with it; the operator's refusal of the
    amendment is still possible at acceptance. What the spike did not settle is question 24 and
    the open problem of section 7 item 19.
14. **May the zero-platform-code Gazebo spike (step 0b, section 6.1) run?** It would use a
    container and the TurtleBot3 simulation, and no platform code.
    Answered: the one-day spike runs now, before the RFCs. It is running; its notes will be
    `docs/wip/MVP2-SPIKE.md`. **Done and closed:** it ran on 2026-11-23 and its notes are
    `docs/wip/MVP2-SPIKE.md` (section 6.1).
15. **Are the seven new words in "Names" right?** Connector, interface join, contract join,
    mapper, companion streams, model job, wrapper.
    Answered: approved, all seven.

New questions the answers raised:

- **16. What does the NXT have for a navigator, and what is its mapper?** The NXT senses
  ultrasonic and colour (RFC-0003; not verified in code) and has motor counts, not a full odometry
  (not verified). Is that enough for our navigator to localise and map, and with what mapper (mapd
  needs depth frames; SLAM Toolbox needs a scan)? Does the NXT's navigator need new hardware, such
  as a better range sensor or a wheel or track encoder? And is there a simulator for it, or does
  step 6 prove itself on the real NXT only? **The simulator half is answered:** the operator chose
  option A on 2026-11-23, a kinematic NXT simulator in nxt-web and the host kind `nxt-kinematic-sim`
  in MVP 1 (NXT-MVP1.md, item 4d; section 6.0). The sensors and mapper half stayed open, and the Pi
  module (section 3.10) adds modern sensors to it. **Genuinely the operator's:** whether the NXT, or
  its Pi module, gets a range sensor that can map.
  Answered (2026-11-23): decided with the Pi module's design (section 3.10). Until then the NXT
  drives and reaches goals with our navigator, ultrasonic for stops, and no map.
  Answered (2026-11-24): the Pi module gets a depth camera and the NXT maps with mapd, the
  duck's depth path (the recommendation was a 2D LiDAR and SLAM Toolbox, the Burger's path).
  The camera model, its price and the Pi's CPU headroom for mapd are not checked.
- **17. What is the Burger's mapper under our navigator?** SLAM Toolbox as a ROS component under
  our navigator, with the connector handing the map and pose across, or a mapper of ours?
  The first uses ready-made SLAM, which ADR-0001's trigger asks for, but our navigator then
  depends on a ROS component through the connector. The second is more to write. This RFC's
  lean is SLAM Toolbox first; it is not decided. The spike's evidence: SLAM Toolbox's pose stayed
  within 5.4 cm of truth over 30 m in the simulator, on near-ideal odometry (spike §18), and it
  survived a clock reset by itself (spike §9); what it does on a real Burger's slip is not known.
  **Advisor's recommendation: SLAM Toolbox.**
  Answered (2026-11-23): SLAM Toolbox, the advisor's recommendation.
- **18. Where does the placement setting live:** the installation, the registration, or both?
  Proposed (section 3.8): the installation holds where this machine places the robot's
  software; the registration lists the placements the robot supports. The NXT's Pi module
  (section 3.10) needs the same setting for a second machine on the robot. **Advisor's
  recommendation: both,** as proposed.
  Answered (2026-11-23): both. The registration lists the placements a robot supports; the
  installation says which one this machine uses (section 3.8).
- **19. Who runs the safety review of the real Burger, and what does it cover?** At least: the
  deadman at the robot, link loss, STOP over Wi-Fi, and a first drive by hand before any
  navigator. Which join runs on hardware first: the interface join (our navigator) or both?
  The spike adds a fact the review must start from: the ROS 2 firmware holds the last velocity
  while its node lives (spike §8, from source), so the deadman cannot rest on the robot's
  firmware; and which firmware the operator's Burger runs is unknown. **Genuinely the
  operator's:** who runs the review, and what it covers (the advisor suggests the Pi watchdog,
  a Wi-Fi pull test, STOP latency and the OpenCR firmware version).
  Answered (2026-11-23): the operator runs the review at the robot with a written checklist and
  test scripts we prepare: the Pi watchdog, a Wi-Fi pull test, STOP latency, the OpenCR firmware
  version read, and a first drive by hand. An independent reviewer agent checks the results
  before the first navigator drive. This is in step 10.
- **20. Do the Burger's first runs use a stock TurtleBot3 world** until the scene writer exists
  (step 9)? It keeps the critical path short, and the Observatory's name conventions
  (`anomalies.py:85-100`) will see no `stair*` or `lm_*` there. **Advisor's recommendation:
  yes.**
  Answered (2026-11-23): yes, a stock TurtleBot3 world first (step 5a).
- **21. The photogrammetry project's licence, and may its first output feed a Gazebo scene later?**
  The two parts of question 9 not answered. **Genuinely the operator's.**
  Answered (2026-11-23): the licence is decided in the photogrammetry project's own RFCs.
  Answered (2026-11-24), the Gazebo-scene half (of this question and question 9): yes, and the
  import is designed now, in MVP 2: a model from the tool, metric and placed in `world` or `map`,
  becomes a Gazebo scene beside the scene writer's from `scene.json` (step 9).
- **22. When the real Burger gets its cameras, does the simulator variant gain matching simulated
  cameras?** Gazebo has an `rgbd_camera` sensor that ran headless at 640 x 480 and 30 Hz, RTF
  1.0001, about 1.7 extra cores (spike §19). With them, the sim and the real Burger stay one robot
  with two variants, each with its own noise and calibration. Recommended (the advisor's
  recommendation as well): yes, after the real cameras are chosen and calibrated, so the simulated
  ones copy real intrinsics, mount and noise: the spike's camera was flat shaded with no noise, and
  its 1.2 rad field of view and 0.2 to 5 m range were set as asked, not checked against a datasheet
  (spike §19).
  Answered (2026-11-23): yes, after the real cameras are chosen and calibrated; the simulated
  ones copy real intrinsics, mount and noise.
- **23. The scan in the run: a `/scan` channel or points, and where do the range limits live?**
  Option 8.7 B (`foxglove.LaserScan`, range limits and angle step in the profile or the run's
  header) against A (points in `/depth` with `raw.scan`, which the spike's run used). B needs the
  `wire.py` and `mcapio.py` changes of section 3.5. Recommended: B, with A until step 8. Raised
  by spike §10 and §20. **Advisor's recommendation:** B with A until step 8; `range_min`,
  `range_max` and `angle_increment` in the profile's sensor declaration (static); `carried_as`
  stays in `raw.scan` while A is used; the `map` frame with the pose as the scan's origin,
  matching `/depth`; protobuf float64 `ranges`, 360 x 8 B x 5 Hz = 14 kB a second.
  Answered (2026-11-23): a scan channel (B), with points (A) until step 8; `range_min`,
  `range_max` and `angle_increment` in the profile's sensor declaration (section 8.7).
- **24. Is the clock epoch a first-class field of the run format?** The spike put an epoch counter
  and `wall_ns` in the tick's `raw` and wrote a `clock_epoch` event beside a new `map_to_world`
  record (spike §20). Recommended: a field next to `t_src`, an additive change noted in ADR-0007,
  and the simulator's clock and epoch as keys of `robot.state`; the writer's time stays wall
  time (`mcapio.py:193` unchanged). **Advisor's recommendation:** the clock epoch is
  first-class as the pair (epoch, t_src), decided in step 4, not step 8, because step 5a's
  reset proof needs it. It does not fix the connector's tf state across a reset (section 7
  item 19), whose sequence includes a stale-epoch filter (section 3.6).
  Answered (2026-11-23): yes, the clock epoch is first-class as the pair (epoch, t_src),
  decided in step 4.
- **25. The default recording for colour: JPEG q80 or H.264?** Section 3.11.2 proposes JPEG q80
  (frame-exact seek, no encoder load on the robot; 25 MB a minute in the flat render, spike §19)
  and lists H.264 and H.265 as options (smaller, keyframe seek, encoder CPU; not measured).
  Also confirm: depth is never lossy (default lossless 16-bit PNG, 24 MB a minute, spike §19),
  and uncompressed is for calibration and capture sets only. Recommended: JPEG q80 and
  lossless 16-bit PNG until a real camera's sizes and the Pi's encoder cost are measured.
  **Advisor's recommendation:** the same, stored as a companion MCAP per stream (section
  3.11.2), not loose files.
  Answered (2026-11-23): JPEG q80 for colour, lossless 16-bit PNG for depth (depth never
  lossy), a companion MCAP per stream; uncompressed for calibration and capture sets only.
  Revisit when a real camera and the Pi's encoder are measured.
- **26. Does the image pipeline run live at first, or only in a model job?** Section 3.11.3. Live
  gives a consumer an adjusted image at once but costs CPU on whichever machine runs it, which
  placement decides and which is not measured. A model job (and replay) needs no live load and the
  recorded stream is unchanged either way. Recommended: replay and model jobs first (step 12), live
  when a live consumer needs it (the advisor agrees: replay-first). Also asks whether per-room or
  per-light choices from a measured brightness stay "later".
  Answered (2026-11-23): replay and model jobs first; live when a live consumer needs it;
  per-room and per-light choices stay later.
- **27. The photogrammetry tool's own vision.** Section 5.1 lists what we hand it and expect
  back. The operator's open points: its name and licence (question 21), the capture set contract
  as written (layout, manifest version, what the tool returns), who triggers a capture, the
  splat and mesh formats, and where it runs. Which of these this RFC should fix and which the
  tool's own RFCs own is the operator's call. **Genuinely the operator's.**
  Answered (2026-11-23): this RFC fixes only the handoff: the capture set with its versioned
  manifest, and what comes back, a model with a scale and a frame placeable in `world` or `map`.
  Everything else belongs to the tool's own RFCs. Section 5.1 is reframed as requirements
  toward those RFCs.

## 10. Not covered, and what I did not verify

Not read: Mission Control's `CONTRACT.md` beyond the lines cited in "Names"; RFC-0014, 0016,
0019, 0022 beyond the lines cited (RFC-0022 §3.3's wording is the operator's, quoted from their
brief); ADR-0013, 0014, 0019; the duck's navigator beyond the lines cited in section 3.7, found
by search and a spot read, not read through; the duck's plugins in code; the Observatory beyond
`anomalies.py`; the `nav2/` directory's bridge code beyond its docstring (`nav2/bridge.py:5`);
the real duck's readiness notes. The spike's notes and NXT-MVP1.md were read for Draft 3. The
spike's own files outside the repository (`connector.py`, the scripts, the bags) were not
read by me; the advisor read them for the tf diagnosis, and nothing was run. Every spike number
here is from its notes, not repeated by me. The `file:line` citations
of `wire.py`, `mcapio.py`, `validate.py`, `simulator.py`, `truth.py` and the gate in sections 3.4
to 3.6 are the spike's (it read them on 2026-11-23), not re-read for this draft, and the gate's
files are being edited in this worktree.

Settled by the spike (no longer "not verified" in this RFC; each is a single run on one
workstation, spike §20 end): that `ros_gz_bridge` stamps with simulation time starting at 0
(§7); that a ROS graph with `use_sim_time` false fails tf lookups at its own time (§7); that
Foxglove has a `LaserScan` schema (§10, from its docs page); that `ros2 bag` writes MCAP by
default in Jazzy (§11); that the sensor type `rgbd_camera` exists and runs (§19); the versions
(§2, §3); that the base holds the last velocity in the simulator, and in the ROS 2 firmware as
read from source (§8); that a world reset takes 0.26 s when the robot is in the world file (§9),
against the duck's 40 s; the image rates and sizes and the camera's cost in the simulator (§19).

Not verified:

- What the NXT senses and its odometry (RFC-0003 and the operator's brief, not the NXT code).
- That `duck_lab.nav` can be made robot-free without regressing the duck, and that it is safe on
  a robot with no head and no drop sensing.
- That a connector on the Pi, or all software on the workstation, can drive the real Burger; the
  third placement in particular.
- That `foxglove.LaserScan` draws in our Lichtblick viewer, and that a ROS bag with
  `sensor_msgs/LaserScan` does (spike §10); a bag replay in a viewer (spike §11).
- That SLAM Toolbox's continuous `map` to `odom` corrections fit our `world` to `map` epochs
  (the spike paired the frames at two epochs only, spike §20).
- **The connector's tf state across a world reset: the fixed sequence ran once per
  variant** (spike §21; section 3.6, section 7 item 19): fix 1 was not taken out in a run; a
  reset while moving, two resets in a row and `reset all` without `/slam_toolbox/reset` were
  not tried. That `map`-to-`world` equals the spawn pose (SLAM Toolbox starts its map at the
  start pose, spike §5, "I believe"); that the reset sequence of section 3.6 holds as a whole.
- That the Pi's `turtlebot3_node` takes `enable_stamped_cmd_vel` (the advisor read the Jazzy
  source), and which version the Pi runs.
- That a `nav_msgs/Odometry` plugin on the Burger model bridges with the sim stamp.
- That the Pi 5 has no hardware H.264 encoder, that Lichtblick plays a companion MCAP of
  `foxglove.CompressedImage`, and its size and CPU on a Pi (the advisor's statements).
- Whether `/slam_toolbox/reset` gives a clean map on a long map, and whether Nav2's costmaps need
  a lifecycle restart after a reset (spike §9, §17); Nav2's costmaps after a reset were not
  tried.
- Bridge message types other than the ones the spike ran (images, point clouds), and a Gazebo
  sensor with its own clock (spike §7).
- That the OpenCR firmware flashed on the operator's Burger is the one read from source, and the
  real Burger's sensor rates and ranges (spike §8, §16, §17). Nothing ran on hardware.
- Gazebo's physics engine name, the lidar's renderer and the name of the `gpu_lidar` plugin
  (spike §14, §17); that the spike's CPU and RTF figures hold at 10 times real time with good
  maps (spike §6), and the upper limit of the factor.
- SLAM Toolbox with a slipping odometry, loop closures (none was readable, spike §18), the walls
  against the world file, and `explore_lite`'s coverage curve and the CPU of Nav2's stack
  (spike §18).
- Whether DDS discovery works across Wi-Fi and `--network host` containers (the spike ran
  everything in one container, spike §2).
- Everything about the camera upgrade: which cameras, their power draw, cable limits, the Pi's
  compute and bandwidth, a real camera's compression ratio, a GPU's effect on the camera cost, 15
  Hz, smaller sizes, an optical frame, a recording with companion streams in a run (spike §19, §20;
  section 7, item 18). Section 3.11 adds more that is not verified: whether a camera driver offers
  Bayer data or readback of its exposure, gain and white balance; whether Gazebo's `rgbd_camera`
  models exposure, gain, white balance or noise; H.264, H.265 and RVL-style sizes and the encoder's
  CPU on a Pi; a real camera's JPEG size; the live pipeline's CPU; and that Settings' block-list
  design fits an Images block (read only at PHASE5-NEXT-PLAN.md:411-412). The photogrammetry tool's
  own design was not read; section 5.1 states requirements toward it, not facts about it.
- Nav2 beyond the parked image's 1.3.14 and `explore_lite`'s run (spike §18), and Nav2 on the
  Burger with goals (spike §17).
- Licences of every tool in section 4. GPU and real-time cost of Gazebo on the MacBook. ROS
  traffic over Wi-Fi.
- That `twist_mux` or any specific tool is the right way to own the velocity path; I only say
  the connector must own it. A `Twist` command straight into the bridge (spike §17).
- The Pi module's hardware, sensors and link (NXT-MVP1.md: "not built in 4d").
- NXT-MVP1.md's own limits: it ran nothing (its "Not covered, and not verified"), so the claims
  of the NXT simulator and its units are from reading code, not from a run.
- The line numbers cited in "Names" were read on 2026-11-23 for the files named there; the
  glossary rows that cite a section only (RFC-0008, RFC-0010, RFC-0014 §3.5, RFC-0018, RFC-0021
  §3) were matched by section title and a spot read, not read through.

Line numbers cited: `file:line` is as the file reads on 2026-11-23. RFC citations are by section
because several RFCs are edited often. A line in `profile.py`, `host.py`, `wire.py` and the gate
was checked by reading the line itself; the 2.4 item 7 geometry lines were read in place, and
`CONTRACT.md:45` is the point goal (the advisor cited line 47; the file as read has it at 45).
