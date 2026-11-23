# RFC-0025: From MVP 1 to MVP 2, the platform's architecture and its evolution

**Status:** Draft 2 (2026-11-23): the operator's answers folded in; for review. Nothing in it is
built. The operator's answers to section 9 are recorded there and in section 8 ("Decided:").
Two things stay open: the clock rule and the versions, both waiting for the spike. A reflection
first, then the RFCs it names, then code. Where a point rests on the advisor's recollection, the
text says "not verified here". The seven new words in "Names" are approved. The operator added
one input after the answers: cameras are one of the first hardware upgrades of the real Burger
(sections 3.5, 5 and 7, question 22).
**Date:** 2026-11-23
**Builds on:** [ADR-0020](../adr/ADR-0020-robots-behind-our-own-interfaces.md) (proposed;
accepted together with this RFC),
[ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md),
[ADR-0018](../adr/ADR-0018-ros2-in-a-container-for-comparison.md),
[ADR-0007](../adr/ADR-0007-run-file-format-2.md),
[RFC-0003](RFC-0003-robot-interface.md), [RFC-0015](RFC-0015-nav2-comparison.md) (parked),
[RFC-0017](RFC-0017-robot-access.md), [RFC-0018](RFC-0018-lab-projects-and-seams.md),
[RFC-0020](RFC-0020-robot-profiles-and-plugins.md),
[RFC-0021](RFC-0021-sim-host-and-payload.md), [RFC-0024](RFC-0024-one-platform.md), the plan
([PHASE5-NEXT-PLAN.md](../wip/PHASE5-NEXT-PLAN.md), "MVP 1 and MVP 2" and item 6), and the
operator's vision note on depth cameras, SLAM and 3D mapping (November 2026).
**Evidence:** every `file:line` below was read on 2026-11-23 in the `mission-control` worktree.
What I did not verify is marked "not verified" and collected in section 10. The operator's
answers are quoted from their reply of 2026-11-23.

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
  connectors can be placed on the robot or on the workstation, per robot (question 1).

The operator's intent, in their words: "robotd and ROS are two versions of the same thing and I
need to be able to support more. This is not Pollen's style with ROS bolted on, but a platform
that supports all approaches and these two at the start." And: reflect on architecture first, do
not build.

So this RFC does three things. It says where the platform is (section 2). It says where it should
go (section 3). It names the tools around it and the hard problems on the way (sections 4 to 8).
It does not decide; it ends in questions (section 9).

Non-goals:

- No platform code before the RFCs. Step 0b (section 6) is a zero-platform-code spike. The
  operator started it on 2026-11-23 (section 9, question 14); its notes go to
  `docs/wip/MVP2-SPIKE.md`, which I have not read.
- Changing how the duck works. MVP 1 keeps running at every step (section 6).
- Choosing the ROS and Gazebo versions. The spike decides them (section 9, question 4).

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
| The NXT | `apps/nxt-web`, `nxt/` | HTTP API and its own lock over the brick | No (HTTP) |

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
| Connector | Ours; one per robot; for the Burger a ROS 2 node process, placed per robot (section 3.8) | `robot.*` calls (interface join); gated `cmd_vel` (contract join); the robot's topics | Velocity to the base; `robot.state`, `robot.health`; sensor streams | Gate protocol 1 (existing); robot interface 1.0 (new: RFC-0026) |
| Navigator, ours, for any robot | Ours; today the duck's (`duck_lab.nav`); to drive a legged, a differential-drive and a tracked robot through per-kind plugins (section 3.7) | Goal; sensor streams; `robot.state` | `robot.move`; status; `map` | Navigator contract 1.2 (existing); plugin interfaces (RFC-0020, existing; widened by RFC-0027) |
| Sensors, declared | Ours; in the profile, per robot and variant (section 3.9) | Hardware, or a host kind's simulation | Streams per sensor kind: the scan in the run, images in companion streams | Profile v2 (new: RFC-0027) |
| Mapper | Per robot: mapd (duck); SLAM Toolbox (Burger, first); the NXT's is open (section 9, question 16) | Range sensing; odometry | A map; the belief of where the robot is | Behind the navigator contract's `map`; localisation plugin |
| Navigator, the robot's own (Burger, later) | Nav2 with SLAM Toolbox as its mapper, behind a wrapper | Goal (as a Nav2 action); `/scan`, `/odom`, tf | Gated `cmd_vel`; goal outcome; map grid | Navigator contract 1.3 with `yaw` (new: RFC-0029) |
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
    |                          navigator wrapper <-- contract 1.3 --> Nav2 + SLAM Toolbox
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
| Connector | A ROS 2 connector: `robot.move` to `/cmd_vel`, `/odom` to `robot.state`, STOP and a deadman | The same connector. Same lease, same STOP |
| Navigator | Our navigator for any robot (section 3.7) with a differential-drive locomotion plugin, a 2D-scan range plugin and a localisation plugin | A wrapper: `goal.start` to a Nav2 action, its outcomes mapped to our ends (RFC-0015 §3.5 has the map), `map` from SLAM Toolbox's grid |
| Contract | Profile accepts a robot with no head, no mapd, a scan sensor | Contract 1.3: `point` gets `yaw` (`CONTRACT.md:45`) |
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
  commands stop, 0.5 s on the duck, RFC-0003 §2.3) is **the connector's to guarantee**, whatever
  the robot behind it does.
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
| Deadman | robotd 0.5 s | **the connector's own** (not verified: whether the TurtleBot3 firmware has one) | robotd-lite on the brick, 0.5 s (RFC-0003 §2.3) |
| Lease | the gate process | the gate process | nxt-web's lock over HTTP |
| Sensors | 8x8 depth socket | `/scan`, later camera topics | ultrasonic, colour (RFC-0003) |

The honest list of what differs, so the contract does not pretend otherwise:

- **ROS topics are open.** Any node in the DDS domain can publish `/cmd_vel`; the sole
  publisher is not a property we can build in. robotd has "other doors" too (RFC-0017 §3.2:
  Pollen's app, the gamepad, `autod`), and the gate is "a convention that all of *our* programs
  follow" (§3.2 end). On ROS the doors are wider. So the rule is narrowed by convention and
  watched, in four parts. The connector remaps the base's input to a topic only it publishes. It
  owns the one place where Nav2's and any hand-driving velocity meet (ROS has a tool for that,
  `twist_mux`; not verified in this repo). It watches the graph for other publishers and raises
  `someone_else_drives` (RFC-0017 §3.2). And it isolates the robot's graph by `ROS_DOMAIN_ID`. A
  real boundary would be SROS2; that is out of scope.
- **ROS has a clock of its own.** Simulation stamps against our wall clock (section 3.6).
- **ROS has frames and a tf tree.** `map`, `odom`, `base_link`. ADR-0001 decision 2 already
  aligned names. Section 3.6.
- **ROS lets a node list the graph.** A graph lists topics; robotd has fixed methods. The
  connector exposes only the capabilities the profile declares, not the graph.
- **Velocity is held after silence on robotd** (hence the explicit zero, `:261-265`). Whether a
  ROS diff-drive base does the same is not verified; the connector publishes zero on STOP either
  way.

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
- A course reset must also reset SLAM Toolbox's and Nav2's state (a lifecycle restart of both),
  or the new run starts on the last run's map and costmaps. It is the Burger's equivalent of a
  fresh `mapd` after the duck's reset. Whether a lifecycle restart is enough is not verified.

Fit with the host model (RFC-0021 §3.1): a host kind provides four things. Reset, the robot's
connections, a truth reader, a scene writer.

| | `pollen-duck-sim` (built) | `gazebo-turtlebot3` (planned, RFC-0021 §3.1) |
| --- | --- | --- |
| Reset | restart duck-sim, about 40 s (`simulator.py:1-6`) | a world reload or a pose reset, plus a lifecycle restart of SLAM Toolbox and Nav2 (not verified which is cheaper) |
| Connections | five socket paths (`host.py:28-29`) | ROS topics through the bridge |
| Truth | Pollen's body server, trunk pose plus z and quaternion (`truth.py`) | the model's pose from Gazebo |
| Scene writer | MJCF from Pollen's `scene_backlash.xml` | SDF world from `scene.json` |
| Real time | RTF measured, runs at 1.0 (RFC-0021 §6) | RTF 1 set in the Gazebo world, recorded per run (ADR-0020 decision 3) |

The host module is still one library (RFC-0021 §3.1: "a module per kind comes with the second
kind"). The host file schema needs a per-kind part: `pollen` is required today (`host.py:94-96`).

Truth for a wheeled robot is simpler, but the judge's vocabulary is legged. The judge asks for a
"trunk height" and a fall threshold (`profile.json:188`, `profile.py` `judge` block). A wheeled
robot's fall is a tilt. This is a profile change (section 7).

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
| 2: errors | The mapper's pose against the simulator's truth | MVP 2, early |
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

The 2D scan in the run needs care. ADR-0020 says a scan "fits today's tick records". I could not
confirm it. `/depth` is a point cloud in the `map` frame with a kind per point (`wire.py:264`,
ADR-0007). A scan stored as obstacle points loses the rays, so free space and maximum range are
gone, and those are what debugging a mapper needs. The operator's answer (question 11): the
Observatory draws the 2D scans and the maps, from a scan channel in the run. Section 8.7 keeps the
shape of that channel. This is not verified against a real scan. The run file already uses
Foxglove schemas for its channels
(`libs/runfile/src/runfile/wire.py:23-34`: `FrameTransform`, `PoseInFrame`, `PointCloud`,
`RawImage`, `Grid`; read). The advisor says Foxglove also publishes a `LaserScan` schema; not
verified here. If it does, a `/scan` channel in that shape follows the file's own habit.

In Gazebo, the simulated sensors come from its sensor plugins: `gpu_lidar` for the scan and
`rgbd_camera` for RGB-D (names from the advisor's recollection; not verified here). They are
Gazebo's plugins, not RFC-0020's.

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
with "map <- world epochs" for relocalisation (RFC-0021 step 2 text; not verified in code). SLAM
Toolbox's `map` to `odom` correction fits there as epochs; I did not check it.

Time: the platform's clocks are wall clocks, and the real-time factor stays 1. ADR-0020 decision 3
as the operator accepted it says "Gazebo at real time": the factor is 1 and the platform uses
its wall clock. This RFC keeps both. The cost is real: a challenge set is 3.5 to 4 hours
(ADR-0018 consequences), and a slow host silently changes results (RFC-0021 §6).

The review adds a problem that decision 3 does not name. `ros_gz_bridge` stamps the messages it
carries with simulation time, which starts near 0 (the advisor's recollection; not verified
here). A ROS graph with `use_sim_time` false would then compare wall time against sim stamps,
and tf lookups fail. RFC-0015 avoided this because `nav2/bridge.py` stamped with its own clock
(`nav2/bridge.py:5`: "all stamped with this node's clock, use_sim_time false"; read). So that
earlier wording, "wall time in the bridge, `use_sim_time` false", does not carry over to a
Gazebo bridge.

Decided (question 7): record the simulator's time beside wall time in every run, and check the
real-time factor each run.

The rule below stays PROPOSED until the spike confirms how Gazebo's bridge stamps messages
(question 13). ADR-0020 decision 3 carries it as a "proposed amendment, pending the spike". Inside
the ROS graph:
`use_sim_time` true at a real-time factor of 1. The connector is where the two clocks meet: it
stamps `wall_ns` on receipt and records the ROS stamp beside it. The platform outside the
connector stays on wall time. Recording `sim_time` next to wall time costs little
(`truth.py:7-9` already carries it).

Recording: a robot's ticks (`/belief/pose`, `/truth/pose`, `/depth`, commands) stay in
`run.mcap`. Large streams are companion streams beside the run. ADR-0007 already has the
precedent: an import copies its source log into `source/` beside the run with a SHA-256.
Proposed layout:

```text
 <run folder>/
   run.mcap                      # ticks, events, maps (format 2)
   streams/<sensor_id>/          # companion streams, one folder per declared sensor
     index.jsonl                 # t, wall_ns, file, sha256 per frame
     000001.jpg ...              # or png, or 16-bit depth png
   streams.json                  # per sensor: kind, frame, calibration ref, count, rate
```

A run record points at `streams.json`. Retention (plan step 7) works per run folder, so a heavy
run archives whole.

For the Burger the natural raw recording is rosbag2, written to MCAP, as one more companion
stream beside the run (for example `source/`, the name ADR-0007's import uses for a copied log).
It also meets the vision note's "save raw recordings". The advisor says `ros2 bag` writes MCAP by
default since ROS 2 Iron; not verified here. Our own run keeps the ticks; the bag keeps
everything the ROS graph said, with the ROS stamps, for replay into SLAM Toolbox later.

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
  not verified.
- **The stop sequence is robotd's.** "Every stop ends with an explicit zero move: robotd keeps
  the last request after its deadman trips" (`run.py:11`).
- **The belief is mapd's.** Odometry, mapd's poses and its grid share one scale
  (`run.py:217`). A Burger's belief comes from a mapper under ROS; the NXT has none.
- **The NXT senses little.** Ultrasonic and colour only (RFC-0003; not verified in the NXT
  code), and no odometry beyond the motor counts (not verified). Its belief of where it is
  would drift fast. Question 16 asks what it needs.

The work has two parts. First, split `duck_lab.nav` into a part that knows no robot (the
planner, the grids, path following, recovery, the goal methods) and the duck's plugins. Second,
widen the plugin interfaces where they are duck-shaped: range sensing returns 8x8 frames today
and must return a scan or a single range; localisation must accept a mapper that is not mapd.

| Robot | Locomotion | Range sensing | Localisation | Looking |
| --- | --- | --- | --- | --- |
| Duck (exists) | `duck-walk@1` | `tof8x8@1` | `mapd@1` | `duck-head@1` |
| Burger (new) | differential drive | 2D scan | SLAM Toolbox's map and pose through the connector (question 17) | none (`capable` false) |
| NXT (new) | tracked (RFC-0020 §6 step 5) | ultrasonic, and colour | dead reckoning from motor counts, a mapper of ours (question 16) | none |

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

Where the setting lives. Proposed: in the installation, because where processes run is what one
machine holds, and it already says where each robot's navigator and profile are
(`runfile/installation.py:1-4`). One robot can be placed differently on two machines. The
registration says which placements the robot supports. The operator said
"installation/registration", so question 18 asks for the split.

What changes:

- **The connector.** Today the gate reaches a robot through Unix socket paths (`host.py:28-29`).
  A connector on the Pi needs a network address instead. The setting says which one a robot has.
  RFC-0026 writes this down.
- **The mapper's location.** It follows the setting: on the Pi, on the workstation. The
  navigator reads the map through the navigator contract's `map` either way.
- **The deadman.** It stays at the robot in every placement (section 3.3). A lost link must
  stop the robot.
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
kind's list; step 5 builds the scan, IMU and odometry paths.

## 4. The external tools, one by one

I read no external documentation for this section (no web access). Versions, compatibility and
licences are from this repository or marked "not verified". "Replaces or duplicates" means
against our own stack.

| Tool | What it does | Role here | How it joins us | 2D / 3D | When |
| --- | --- | --- | --- | --- | --- |
| Gazebo Sim | Physics and sensor simulator | A second host kind | A host kind `gazebo-turtlebot3`; a process or container; SDF scenes written from `scene.json`; truth read from the model pose | both | MVP 2 start |
| ROS 2 | Message bus and tooling | The Burger's own stack, inside the connector and Nav2 containers | A container (ADR-0018); only the connector imports it; version decided in the spike, default Jazzy | n/a | MVP 2 start |
| TurtleBot3 packages | The robot's bringup, models, simulation worlds | The Burger's description in ROS terms | Bringup on the Pi (real) or from the simulation package (sim) | 2D LiDAR robot | MVP 2 start |
| ros_gz bridge | Gazebo topics to ROS topics | The host kind's connection side | Runs beside Gazebo; carries `/scan`, `/odom`, `/cmd_vel`, `/clock`; stamps with sim time (section 3.6) | n/a | MVP 2 start |
| rosbag2 (MCAP) | Records a ROS graph's topics to a file | Raw recording, a companion stream beside the run | `ros2 bag record` in the ROS container; the file goes to `source/` (section 3.6) | both | MVP 2 start |
| Nav2 | Planner, controller, behaviour tree, costmaps, recoveries | The robot's own navigator, behind our contract | Container; a wrapper maps `goal.*` to its action | 2D | MVP 2, after our navigator drives the Burger |
| SLAM Toolbox | 2D LiDAR mapping, a map and `map`-to-`odom` | The Burger's mapper, first under our navigator (question 17) | Container, same graph as Nav2; its grid becomes the contract's `map` | 2D | MVP 2 start |
| RViz | ROS's own live viewer | Decided (question 11): a debug aid inside the ROS container only, not a view of ours | Optional, ROS container only | both | MVP 2 start, as a debug aid |
| RTAB-Map | RGB-D, visual and LiDAR mapping with loop closure | A mapper for 3D | ROS container; own database as a companion stream | 3D | Later |
| Open3D | Point clouds, TSDF, meshing | A tool a model job calls | Python library in a separate job | 3D | Later |
| COLMAP | Structure-from-motion, multi-view stereo | A tool a model job calls | CLI behind the photogrammetry project's command line (section 5) | 3D | Separate project, its own repository |
| Nerfstudio | NeRF and splatting workflows | Visualisation experiments | Offline, GPU; never the platform | 3D | Never in the core |

Notes, one tool at a time:

- **Gazebo Sim.** What the repo says: RFC-0021 §3.1 plans a `gazebo-turtlebot3` kind: "its
  truth Gazebo's model pose, its scenes SDF". It duplicates MuJoCo's job for the Burger and
  nothing else. It pulls in a large install (not measured; ROS and Gazebo are installed on no
  host, RFC-0021 §3.1) and a second real-time risk. Versions: the vision note says to confirm a
  "compatible ROS 2 / Gazebo / TurtleBot3 combination" and I did not; ADR-0020 notes the same.
  The spike settles it (question 4).
  The operator's answer (question 12): the workstation first; the MacBook later and not required
  for MVP 2. Whether it runs on the MacBook (Apple Silicon) is not verified. Its simulated
  sensors come from plugins (`gpu_lidar`, `rgbd_camera`; not verified here).
- **ROS 2 and its distro.** The parked Nav2 image is ROS 2 Jazzy on Ubuntu (ADR-0018). The
  workstation is Arch, hence the container. Whether TurtleBot3's packages support Jazzy and
  which Gazebo goes with it are not verified. ADR-0001 decision 4's trigger "ready-made SLAM or
  sensor drivers" is now met (ADR-0020 context).
- **TurtleBot3 packages.** Bringup, the Gazebo models and worlds, and navigation and SLAM
  launch files. I did not read them. The vision note says a Burger has a Raspberry Pi, an OpenCR
  controller, wheel encoders, an IMU and a 2D LiDAR "depending on kit generation" (section 4).
  Which LiDAR model is on the arriving kit is a question for the operator.
- **ros_gz bridge.** Needed to reach Gazebo from ROS. The connector should depend on topics, not
  on this bridge's name, so a different simulator could provide the same topics. It stamps
  messages with simulation time (section 3.6; not verified here).
- **rosbag2.** Not read here. The advisor says it writes MCAP by default since ROS 2 Iron (not
  verified here). If so, it is the same container format as our run file, and Foxglove and
  Lichtblick read it. It fits ADR-0007's import precedent: a copy beside the run, with a
  SHA-256.
- **Nav2.** RFC-0015's spike is the only experience here. The image is 5.1 GB; Nav2 came up
  (version 1.3.14 in that image); explore_lite had to be built from source; no goal was reached
  on the duck and the cause is not known (RFC-0015 §8). That result is about the duck's 8x8
  sensor, which "nobody configures Nav2 for". Nav2's defaults suit a 360 degree LiDAR
  (ADR-0001 context), which is the Burger's. That is evidence for a contract join on the Burger,
  not a promise. Outcome mapping already designed: SUCCEEDED to `reached`, planner failures to
  `refused`, controller failure to `stalled` (RFC-0015 §3.5). It duplicates our navigator's
  planner, costmap and recoveries (the very things RFC-0015 compared).
- **SLAM Toolbox.** Installed in the spike image (RFC-0015 §8); never driven. Needs a scan,
  odometry and tf. Replaces mapd's role for a robot that has a LiDAR; mapd stays for the duck.
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
   streams/<sensor>/*.jpg  ---- job ---> images + images.json (+ cameras.json)
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
line with a stable manifest. The repository is decided (its own). Its licence, and whether its
first output may feed a Gazebo scene later, are still the operator's (section 9, question 21).

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
| 0b | The spike, running (section 6.1), zero platform code: the TurtleBot3 Gazebo simulation in a container, driving by hand, SLAM Toolbox, a saved map; the real-time factor; the bridge's stamps; whether the base holds the last velocity | All code | Measured answers to many of section 10's "not verified" items; notes in `docs/wip/MVP2-SPIKE.md` | S | the operator (question 14) |
| 1 | The robot interface written as a contract with a number; the duck's connector and the NXT's brought to it; the gate takes method names from it; the adapter surface written down; a connector reachable by a network address, for the placement setting (section 3.8) | Duck behaviour, protocol 1 accepted by the new gate | One contract test run against the fake, duck-gate and NXT adapters (as `test_contract.py` does for navigators); `make sim-duck` | M | RFC-0026, "the robot interface" |
| 2 | Profile v2: required blocks shrink to identity, factsheet, control, capabilities, plugins; locomotion, footprint, sensors become per-kind; a plugin set may be empty; the judge's fall rule by kinematics; sensors declared per robot and variant (section 3.9); registration names its connector; the placement setting has a home | The duck's profile migrated by `upgrade` (`profile.py:503`), checksums rule | Every stored profile loads; the duck's numbers unchanged; a plugin-less stub profile validates | M | RFC-0027, "profiles for any robot" |
| 3 | Our navigator for any robot (section 3.7): `duck_lab.nav` split into a part that knows no robot and the duck's plugins; the plugin interfaces widened (a scan, a single range, a mapper that is not mapd); the Burger's plugins (differential drive, 2D scan, localisation) and the NXT's (tracked, ultrasonic, dead reckoning), proved against stubs | The duck's verdicts; navigator contract 1.2 | The duck's challenge verdicts match; one contract test against all three plugin sets | L | a new RFC, "a navigator for any robot" (number to be given) |
| 4 | The host kind written as a contract; `simhost` gets a module per kind; a stub Gazebo host, and the gate's fake adapter proves lease, STOP and state in Mission Control; a run with a stub scan, to settle the run format | MuJoCo kind unchanged; `scene.json` and the layout readers untouched | The robot page shows the stub; a run opens in the Observatory; the duck's verdicts match | M | RFC-0028, "host kinds" (the scene part moves to step 9) |
| 5 | The Burger in Gazebo, joined at the interface: the ROS connector (split placement first), the bridge, `/scan`, `/odom`, `/imu`, truth; our navigator drives it; Mission Control's goals and driving by hand; maps and runs in the Observatory; simulator time recorded beside wall time and the real-time factor checked each run (question 7); the clock rule of section 3.6 if the spike confirms it. A stock TurtleBot3 world until step 9 (my proposal, to confirm in RFC-0028) | Nothing of the duck | Drive the Burger from Mission Control; a goal reaches by truth; a recorded run with truth; tf lookups hold | L | ADR on time and frames, after the spike (question 13) |
| 6 | The NXT's navigator: our navigator with tracked plugins on the real NXT (RFC-0020 §6 step 5); the NXT's gate on the written interface from step 1 | The NXT's HTTP API | A goal reached by the real NXT. There may be no NXT simulator (not verified); depends on question 16 | M to L | the new navigator RFC; the operator's hardware |
| 7 | The contract join: Nav2 and SLAM Toolbox behind contract 1.3 (`yaw`); the wrapper; the outcome map | Contract 1.x readers | A `point` goal reaches by truth; the contract test passes against the wrapper; the duck still passes | L | RFC-0029, "a robot that navigates itself" |
| 8 | A 2D scan channel in the run; the mapper's pose against truth; the Observatory draws the scan and the map (question 11) | Format 2 readers (additive) | The Observatory draws the scan and the map | M | a note in ADR-0007 |
| 9 | Courses in Gazebo: `scene.json` becomes the source; an SDF scene writer; the five layout readers move off the layout | MuJoCo kind unchanged | Challenge verdicts match; the `scene` test (61 boxes equal) extended; a challenge runs in Gazebo | M to L | RFC-0028, the scene part |
| 10 | The real Burger on hardware: the connector placed by the robot's setting (the split first), the Pi's bringup; a safety review; link loss; STOP over Wi-Fi; driving from Mission Control | The simulator path | The operator and the robot, as the real duck's B6; STOP and a lost link measured on the real base. MVP 2 ends here | M | the operator, after the safety review |
| 11 | Cameras: an RGB and a depth camera on the real Burger (one of its first hardware upgrades), then matching simulated ones (question 22); companion streams, calibration, retention per run; the model job and the photogrammetry seam nearer | Ticks | Calibration records; a recorded run with images; the first model job (section 5) | L | a later RFC, after the cameras are chosen |

Order of the steps (a dependency graph, not a schedule):

```text
 0 -> 0b -> 1 -> 2 -> 3 --------------------> 6   (the NXT's navigator)
            |         |
            +-> 4 ----+--> 5 --------------> 10   (the real Burger; MVP 2 ends)
                          |  |
                          |  +--> 7 -> 8 -> 11    (11: cameras, after the real Burger arrives)
                          |
                          +--> 9                  (courses in Gazebo; off the critical path)
```

Step 3 is on the critical path and is the largest. Step 9 is off it: it starts only after the
Burger's navigation works (step 5). Step 10 needs step 5; it need not wait for 7 to 9 if the
robot and the review are ready. Step 8 is after step 7 in the operator's order. If the
Observatory needs the scan sooner, step 8 can move before step 7.

### 6.1 Step 0b, the spike

The operator said on 2026-11-23 that the one-day spike runs now, before the RFCs, and that it is
running (question 14). Its notes will be `docs/wip/MVP2-SPIKE.md`. I have not read them. It
touches no platform code. In a container, run the TurtleBot3 Gazebo simulation, drive it by hand
with ROS's own teleop tool, run SLAM Toolbox over it, and save a map. Measure the real-time
factor. Find out whether the base keeps its last velocity after the commands stop. The advisor
recalls the OpenCR firmware has a motor timeout of about 500 ms; not verified here.

The spike decides two things the operator left to it. The ROS 2 and Gazebo versions: default
ROS 2 Jazzy, the parked image's (question 4). And the clock rule: how Gazebo's bridge stamps
messages decides whether the rule stays or goes (question 13). It also resolves many of the
"not verified" items in section 10 and feeds RFC-0026 with facts instead of recollection.

Where an ADR is warranted: the clock policy (step 5; an amendment to ADR-0020 decision 3 only if
the spike confirms the rule), the rule that the connector owns the velocity path (ADR-0020
decision 2, narrowed as section 3.3 says), and the frames rule (ADR-0020 decision 4 to become a
contract in step 1).

What must be true before step 3 starts: the answers to questions 16 and 17 (what the NXT senses,
and the Burger's mapper). Before step 5: the spike's notes, and question 18 (where the placement
setting lives).

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
   (questions 5 and 6), through RFC-0020's four plugin interfaces. Today it assumes the duck in
   many places (section 3.7): an 8x8 depth grid and a reflex on each frame (`run.py:9-11`, `:28`);
   three fixed sockets, with mapd behind one (`run.py:159`, `:230`); a turn rule with a pivot
   room and a kick (`explore_run.py:76-96`); a head that glances at drops (`run.py:736-743`); and
   robotd's stop sequence (`run.py:11`). The NXT is the hard case: ultrasonic and colour only
   (not verified in code), no odometry beyond motor counts (not verified), so its belief of where
   it is drifts and a mapper needs something to map from. A navigator that is safe on a robot
   with no head and no drop sensing is not verified either. If the split is done badly, the duck
   regresses; the duck's verdicts are the guard.
3. **The profile requires the duck.** A Burger profile today must invent a circular footprint
   with a lethal and an inflation ring tuned to a duck, a locomotion block with a turn kick, and a
   plugin for every block (`profile.py:179-189`, `:235`, `:492-494`). The fix is a schema
   change. It touches every stored profile and the checksum rules, so it needs a migration, not
   an edit.
4. **Time and stamps.** The assumption of wall time is stated (ADR-0020 decision 3) but not
   enforced, and a second problem sits under it. `ros_gz_bridge` stamps with simulation time,
   starting near 0 (not verified here), so a ROS graph on `use_sim_time` false would fail its tf
   lookups (section 3.6). The proposed rule (use sim time inside the graph, the connector where
   the two clocks meet) stays proposed until the spike confirms how the bridge stamps.
   Separately, a Gazebo
   scene with a camera or many LiDAR rays may fall below real time on this hardware (not
   measured). A run below real-time factor 1 silently changes timing, timeouts and the 0.1 s
   truth pairing (`libs/runfile/src/runfile/truthcopy.py:26`). The operator decided: record the
   simulator's time beside wall time and check the factor each run (question 7).
5. **Who drives, on an open graph.** A design rule, not a blocker in the simulator. ADR-0020
   says the connector is the sole publisher, but on DDS any node can publish `/cmd_vel`. The rule
   is narrowed by convention and watched: a remap to a topic only the connector publishes, one
   place where velocity requests meet that the connector owns, a watch for other publishers
   (`someone_else_drives`), and `ROS_DOMAIN_ID` isolation (section 3.3). On the duck, "other
   doors" are acknowledged and watched (plan 4b item B4); the ROS graph has more of them.
6. **DDS discovery across Wi-Fi and host-network containers.** The connector, Nav2 and the
   Burger's bringup will sit on different computers, with `--network host` containers (as
   RFC-0015's spike ran). Multicast discovery often fails on Wi-Fi. Likely the first thing to
   break on a real Burger (the advisor's judgement; not verified here).
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
   kinematics-aware fall rule and a truth reader per host kind.
10. **Frames.** SLAM Toolbox publishes `map` to `odom`, which jumps. Our run has one `map` frame
   and epochs. The duck's frame has a scale correction (0.91). A ROS connector must say which
   frame its odometry is in, and whether it scales. A map's origin differs per mapping session.
11. **A scan in the run** (section 3.5): a point cloud with kinds is not a scan. The operator
    decided a scan channel in the run (question 11); its shape is section 8.7.
12. **Safety on Wi-Fi.** The real Burger is on Wi-Fi, the connector on another computer. A lost
    link must stop the robot. If the base holds the last velocity (not verified), the connector
    cannot guarantee a stop it cannot send. A robot-side timeout on the Pi may be needed. This is
    the Burger's version of the duck's B5 link tooling. The real Burger is in MVP 2 (question 8),
    so the safety review, link loss and STOP over Wi-Fi are part of step 10, not later.
13. **Contract 1.3 and goals.** `point` has no heading (`CONTRACT.md:45`), and a Nav2 goal has
    one. The duck's other kinds (`go_to_object`, `explore`, `inventory`) have no Nav2 meaning
    without a recogniser and a frontier explorer; "explore" for the Burger is not defined.
14. **Data volume and bandwidth.** RGB-D at any rate is large; a Pi and Wi-Fi may not carry it
    (vision note section 11). Nothing is measured. This decides whether images are recorded on
    the robot's computer or the navigator's.
15. **Calibration and sim to real.** Extrinsics and intrinsics have no home. Plan unit A3's
    calibration frame (odometry scale through a navigator method) is the nearest, and it is
    duck-only today.
16. **Install weight and hosts.** Gazebo and a ROS image add gigabytes (the spike image is
    5.1 GB). The setup and check scripts (RFC-0021 §4) cover Pollen's simulator only. Gazebo runs
    on the workstation first (question 12); on the MacBook it is not verified and not required.
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
navigator comes before the contract join with Nav2 (steps 5 and 7). The navigator is ours for
any robot (section 3.7).

### 8.4 Time

- **A.** Wall clocks only, real-time factor 1 recorded (ADR-0020 decision 3 as accepted).
- **B.** A, plus `sim_time` recorded beside wall time and checked against the factor each run.
- **C.** A platform clock with pause and step.

Inside the ROS graph, the choice of A or B leaves one more question: the stamps. The
simulator's bridge stamps with simulation time (not verified here), so `use_sim_time` false
would fail tf lookups, and RFC-0015's way out (the bridge stamped with its own clock,
`nav2/bridge.py:5`) is not available for a Gazebo bridge.

Recommendation: B, with the proposed amendment to decision 3: inside the ROS graph
`use_sim_time` true at a real-time factor of 1; the connector is where the two clocks meet, stamps
`wall_ns` on receipt and records the ROS stamp beside it; the platform stays on wall time. It is
nearly free (`truth.py:7-9`), makes slow runs visible, and leaves C open without building it.

Decided (question 7): B, recording the simulator's time beside wall time and checking the factor
each run. Open (question 13): the stamp rule. It stays PROPOSED until the spike confirms how
Gazebo's bridge stamps messages.

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

- **A.** As points in `/depth`.
- **B.** A new additive `/scan` channel in a Foxglove shape. The run file already uses Foxglove
  schemas (`libs/runfile/src/runfile/wire.py:23-34`) and the advisor says Foxglove publishes a
  `LaserScan` schema (not verified here).
- **C.** A companion stream, for example the rosbag2 MCAP of section 3.6.

Recommendation: B for a 2D scan (it is small), if the `LaserScan` schema exists as the advisor
says; C for anything image-like.

Decided (question 11): a scan channel in the run (B). The Observatory draws the 2D scans and the
maps, and MCAP viewers (Rerun, Lichtblick) read the file for free. RViz is a debug aid in the ROS
container only. Open: the channel's exact schema, until the first real scan is stored.

### 8.8 The NXT's place in the model

- **A.** An interface join with no navigator, as today.
- **B.** A connector plus our navigator with tracked plugins (RFC-0020 step 5).
- **C.** Out of the model until MVP 1 is done.

The first draft recommended A. The operator decided otherwise.

Decided (question 5): B. The NXT gets our navigator, with tracked plugins (RFC-0020 §6 step 5),
as part of MVP 2 (step 6). What it senses and whether it needs new hardware are open
(question 16).

### 8.9 Photogrammetry

- **A.** Library: the robotics side imports it. Couples releases.
- **B.** File contract and CLI (section 5).
- **C.** A service. More to run, no gain now.

Recommendation: B.

Decided (question 9): B. The photogrammetry project lives in its own repository and connects by
the file contract; neither imports the other.

### 8.10 ROS 2 and Gazebo versions

- **A.** ROS 2 Jazzy, the parked image's (ADR-0018), with the Gazebo that goes with it.
- **B.** Another pair, if the TurtleBot3 packages need one.

Open: the spike decides (question 4). The default is A.

### 8.11 Where Gazebo runs

- **A.** The workstation. **B.** The workstation and the MacBook.

Decided (question 12): A first. The MacBook comes later and is not required for MVP 2.

## 9. Questions for the operator

Questions 1 to 15 were answered by the operator on 2026-11-23; the answers are under each.
Questions 16 to 22 are new, raised by the answers and the operator's later input on cameras.

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
14. **May the zero-platform-code Gazebo spike (step 0b, section 6.1) run?** It would use a
    container and the TurtleBot3 simulation, and no platform code.
    Answered: the one-day spike runs now, before the RFCs. It is running; its notes will be
    `docs/wip/MVP2-SPIKE.md`.
15. **Are the seven new words in "Names" right?** Connector, interface join, contract join,
    mapper, companion streams, model job, wrapper.
    Answered: approved, all seven.

New questions the answers raise:

- **16. What does the NXT have for a navigator, and what is its mapper?** The NXT senses
  ultrasonic and colour (RFC-0003; not verified in code) and has motor counts, not a full
  odometry (not verified). Is that enough for our navigator to localise and map, and with
  what mapper (mapd needs depth frames; SLAM Toolbox needs a scan)? Does the NXT's navigator
  need new hardware, such as a better range sensor or a wheel or track encoder? And is there
  a simulator for it, or does step 6 prove itself on the real NXT only?
- **17. What is the Burger's mapper under our navigator?** SLAM Toolbox as a ROS component under
  our navigator, with the connector handing the map and pose across, or a mapper of ours?
  The first uses ready-made SLAM, which ADR-0001's trigger asks for, but our navigator then
  depends on a ROS component through the connector. The second is more to write. This RFC's
  lean is SLAM Toolbox first; it is not decided.
- **18. Where does the placement setting live:** the installation, the registration, or both?
  Proposed (section 3.8): the installation holds where this machine places the robot's
  software; the registration lists the placements the robot supports.
- **19. Who runs the safety review of the real Burger, and what does it cover?** At least: the
  deadman at the robot, link loss, STOP over Wi-Fi, and a first drive by hand before any
  navigator. Which join runs on hardware first: the interface join (our navigator) or both?
- **20. Do the Burger's first runs use a stock TurtleBot3 world** until the scene writer exists
  (step 9)? It keeps the critical path short, and the Observatory's name conventions
  (`anomalies.py:85-100`) will see no `stair*` or `lm_*` there.
- **21. The photogrammetry project's licence, and may its first output feed a Gazebo scene later?**
  The two parts of question 9 not answered.
- **22. When the real Burger gets its cameras, does the simulator variant gain matching
  simulated cameras?** Gazebo has camera and depth-camera sensors (not verified here). With
  them, the sim and the real Burger stay one robot with two variants, each with its own noise
  and calibration. Recommended: yes, after the real cameras are chosen and calibrated, so the
  simulated ones copy real intrinsics, mount and noise.

## 10. Not covered, and what I did not verify

Not read: Mission Control's `CONTRACT.md` beyond the lines cited in "Names"; RFC-0014, 0016,
0019, 0022 beyond the lines cited (RFC-0022 §3.3's wording is the operator's, quoted from their
brief); ADR-0013, 0014, 0019; the duck's navigator beyond the lines cited in section 3.7, found
by search and a spot read, not read through; the duck's plugins in code; the Observatory beyond
`anomalies.py`; the spike's notes (`docs/wip/MVP2-SPIKE.md`); the real duck's readiness notes;
the `nav2/` directory's bridge code beyond its docstring (`nav2/bridge.py:5`).

Not verified:

- What the NXT senses and its odometry (RFC-0003 and the operator's brief, not the NXT code).
- That `duck_lab.nav` can be made robot-free without regressing the duck, and that it is safe on
  a robot with no head and no drop sensing.
- That a connector on the Pi, or all software on the workstation, can drive the real Burger; the
  third placement in particular.
- That a 2D scan fits today's tick records (ADR-0020 says so; I found the opposite risk).
- That SLAM Toolbox's `map` to `odom` corrections fit our `world` to `map` epochs.
- Whether Foxglove has a `LaserScan` schema (the advisor's recollection).
- That `ros_gz_bridge` stamps with simulation time starting near 0, and that a ROS graph on
  `use_sim_time` false then fails tf lookups (the advisor's recollection).
- That `ros2 bag` writes MCAP by default since ROS 2 Iron.
- Gazebo's sensor plugin names `gpu_lidar` and `rgbd_camera`.
- That the OpenCR firmware has a motor timeout of about 500 ms.
- Whether a lifecycle restart of SLAM Toolbox and Nav2 fully resets a course.
- Whether DDS discovery works across Wi-Fi and `--network host` containers.
- Whether the TurtleBot3 base or its firmware holds the last velocity or has a timeout.
- Everything about the camera upgrade: which cameras, their power draw, field of view, cable
  limits, the Pi's compute and bandwidth, and Gazebo's camera sensors (section 7, item 18).
- Everything about versions and compatibility: ROS 2, Gazebo, TurtleBot3 packages, `ros_gz`,
  Nav2 beyond the parked image's 1.3.14, which is from RFC-0015 §8.
- Licences of every tool in section 4. Disk, RAM, GPU and real-time cost of Gazebo on this
  workstation or the MacBook. ROS traffic over Wi-Fi.
- The data rate of any camera, and the Pi's capacity.
- Whether a Gazebo world reload is faster than the duck's 40 s reset.
- That `twist_mux` or any specific tool is the right way to own the velocity path; I only say
  the connector must own it.
- The line numbers cited in "Names" were read on 2026-11-23 for the files named there; the
  glossary rows that cite a section only (RFC-0008, RFC-0010, RFC-0014 §3.5, RFC-0018, RFC-0021
  §3) were matched by section title and a spot read, not read through.

Line numbers cited: `file:line` is as the file reads on 2026-11-23. RFC citations are by section
because several RFCs are edited often. A line in `profile.py`, `host.py`, `wire.py` and the gate
was checked by reading the line itself; the 2.4 item 7 geometry lines were read in place, and
`CONTRACT.md:45` is the point goal (the advisor cited line 47; the file as read has it at 45).
