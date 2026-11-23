# RFC-0025: From MVP 1 to MVP 2, the platform's architecture and its evolution

**Status:** Draft (2026-11-23). Nothing in it is built or decided. A reflection first, then the
RFCs it names, then code. Revised the same day with an advisor's review; where the review rests
on the advisor's recollection, the text says "not verified here".
**Date:** 2026-11-23
**Builds on:** [ADR-0020](../adr/ADR-0020-robots-behind-our-own-interfaces.md) (proposed),
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
What I did not verify is marked "not verified" and collected in section 10.

## 1. Why

The operator, 2026-11-23: "By the time we get to Gazebo and Burger, we're going to be MVP version 1.
And then we are evolving architecture to fit MVP version 2." And: "I need a proper
architectural evolution, and we think of it as stepping up the game because things are working
well so far."

- **MVP 1** is everything with the Microduck (legged, MuJoCo simulator, Pollen's `robotd`, our
  plain-Python navigator) and the Lego NXT, in the current ecosystem.
- **MVP 2** is a TurtleBot3 Burger (ROS 2, arriving about a week after 2026-11-23), with more
  sensors, starting in a simulator (Gazebo Sim).

The operator's intent, in their words: "robotd and ROS are two versions of the same thing and I
need to be able to support more. This is not Pollen's style with ROS bolted on, but a platform
that supports all approaches and these two at the start." And: reflect on architecture first, do
not build.

So this RFC does three things. It says where the platform is (section 2). It says where it should
go (section 3). It names the tools around it and the hard problems on the way (sections 4 to 8).
It does not decide; it ends in questions (section 9).

Non-goals:

- No platform code before the RFCs. Stage 0b (section 6) is a zero-platform-code spike, proposed
  and not yet approved by the operator (section 9, question 14).
- Changing how the duck works. MVP 1 keeps running at every stage (section 6).
- Choosing the Burger's sensors or the ROS version (section 9).

## 2. The architecture of MVP 1 (point A)

### 2.1 The parts and their jobs

| Part | Where | Job | Neutral? |
| --- | --- | --- | --- |
| Goals and missions | `apps/mission-control` (`core.py`, `store.py`) | Goals, sites, the lock, STOP, the robot page | Mostly |
| Robot adapters | `apps/mission-control/src/mission_control/{robots,duck,nxt,fake}.py` | One adapter per robot type: `fake`, `duck-sim`, `nxt-web` (`robots.py:400-412`) | By type |
| The gate | `libs/gate/src/robotgate/__init__.py` | Lease, STOP, takeover, log, in front of a robot | Rules yes; method names no |
| Navigator contract | `libs/runner/CONTRACT.md`, `runfile/navcontract.py` | Goal in, status out, version 1.2 (`navcontract.py:4`) | Mostly |
| Runner and judge | `libs/runner` (`labrunner`) | Runs courses, judges by truth, copies the official run | Partly |
| Navigator | `robots/duck/src/duck_lab` | The duck's planner, explorer, world model, plugins | No (the duck's) |
| Robot description | `robots/duck/{registration.json,profile.json,robot.urdf}` | Who the robot is: files and numbers | Schema is duck-shaped |
| Simulator host | `libs/simhost` | Host file, reset, truth reader | One kind only |
| World and scene | `scenes/<id>/scene.json`, `robots/duck/sim/apartment_layout.json` | Bounds, rooms, drops, boxes | Half |
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
   them (`nxt.py:150-223`, `duck.py:320-463`, `fake.py`). This is the driver interface, unwritten.
   The duck's `state()` reads robotd's `odom.position`, `odom.yaw` and scales by the profile's
   0.91 (`duck.py:416-424`). robotd has no `robot.state` request, only the subscription
   (`duck.py:11`).
3. **The NXT is already a second driver, in HTTP.** `NxtGate` offers the in-process gate's
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
7. **The world is the duck's layout.** Five readers open `apartment_layout.json` through the
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

### 3.0 Roles in MVP 2

The next sections use these roles. A role is a job, not a process: one process may hold two.
"New" means the contract does not exist yet and a follow-up RFC would write it.

| Role | Owner and where | Inputs | Outputs | Contract and version |
| --- | --- | --- | --- | --- |
| Robot driver | Ours; one per robot; for the Burger a ROS 2 node process | `robot.*` calls (level 1); gated `cmd_vel` (level 2); the robot's topics | Velocity to the base; `robot.state`, `robot.health`; sensor streams | Gate protocol 1 (existing); robot interface 1.0 (new: RFC-0026) |
| Navigator, ours | `duck_lab` for the duck; a new plain one for the Burger only if wanted | Goal; sensor streams; `robot.state` | `robot.move`; status; `map` | Navigator contract 1.2 (existing) |
| Navigator, the robot's own | Nav2 with SLAM Toolbox, behind a shim | Goal (as a Nav2 action); `/scan`, `/odom`, tf | Gated `cmd_vel`; goal outcome; map grid | Navigator contract 1.3 with `yaw` (new: RFC-0029) |
| Simulator backend | A host kind in `simhost`; for the Burger `gazebo-turtlebot3` | Reset, a world, the robot's commands | The robot's topics; truth; the real-time factor | Host file 1 (existing); backend interface (new: RFC-0028) |
| World | `scenes/<id>/scene.json`; a writer per backend | Bounds, rooms, drops, boxes | MJCF, SDF | Scene file (existing); world as the source (new: RFC-0028) |
| Runner and judge | `libs/runner` | Course, navigator, truth | Verdict; the official run with truth copied in | Navigator contract; run file format 2 (existing) |
| Run store | `libs/runfile` | Ticks, events, maps; side files | `run.mcap` plus `streams/` | Run file format 2 (existing); side files (new: RFC-0028 or an ADR-0007 note) |
| Surface: Mission Control | `apps/mission-control` | Adapter state; the gate | Goals, lease, STOP, the robot page | Adapter surface (existing, unwritten; RFC-0026 writes it) |
| Surface: the Observatory | `apps/observatory` | Run files, live follow | Replay, analysis | Run file format 2 (existing) |

A picture of MVP 2 in the style of section 2.3. Both levels are drawn; the Burger can take
either.

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
 ROBOT DRIVER (one per robot)  <-- host file --- simulator backend ---'
    |   robotd (duck)   HTTP (NXT)   ROS 2 node (Burger)      kind: pollen-duck-sim | gazebo-turtlebot3
    |                                  |  ^ gated cmd_vel (level 2)        ^
    |                                  v  |                                | world from scene.json
    |                          navigator shim <-- contract 1.3 --> Nav2 + SLAM Toolbox
    v
 level 1: our navigator <-- contract 1.2 --> runner / Mission Control
```

### 3.1 The vision note's seven interfaces, on our parts

The vision note (section 10) names seven interfaces. Most already exist here under another name.
The job is to rename and fill gaps, not to start again.

| Vision interface | Ours today | Proposed role in MVP 2 |
| --- | --- | --- |
| RobotAdapter | Registration plus profile plus Mission Control's adapter | **Robot driver**: one per robot, the only way commands reach it |
| SimulationAdapter | Host kind (`simhost`) | **Simulator backend**: reset, truth, scene writer, real-time factor |
| SensorProvider | Sockets (robot, depth, map, camera); profile `sensors` | Sensors **declared** by capability; each with a stream, a frame, a calibration |
| ActuatorController | `robot.move` plus the locomotion plugin | The driver's command side; absent for a robot that navigates itself |
| MappingPlugin | `mapd@1` (localisation plugin); the navigator API's `map` | A map provider behind the navigator contract; SLAM Toolbox fits here |
| ReconstructionPlugin | Nothing | An **offline job** over a run's side files, outside the live path |
| WorldAdapter | `scene.json` plus the layout plus a scene writer per kind | `scene.json` is the world; each backend writes its own format from it |

The vision note's rule "do not require all robots to expose identical actuators; use capability
discovery" is what the profile's `capabilities` block already does (`profile.json:209-221`). It
has a `sensors` slot that is empty for the duck. The vision note's rule "a shared high-level world
model does not imply MuJoCo and Gazebo share one physical simulation" is the same split as
RFC-0021 §3.1: the host kind holds everything that knows a simulator.

### 3.2 Two integration levels

A robot joins at one of two levels. Both are valid. The platform should make both first-class.

- **Level 1, "we drive it".** A driver sits at the robot interface. Our navigator, in plain
  Python, plans and sends `robot.move`. The duck is this today. The NXT is this at the interface
  (it takes `robot.move`), but it has no navigator; RFC-0020 §6 step 5 planned tracked plugins
  for one and has not started.
- **Level 2, "it navigates itself".** The robot's own stack (for the Burger, Nav2 with SLAM
  Toolbox) sits behind the navigator contract. Mission Control and the runner see `hello`,
  `goal.start`, `goal.status`, `goal.cancel`, `goal.break`, `map`, `state`. ADR-0020 decision 1
  says this.

```text
 LEVEL 1: we drive it                    LEVEL 2: it navigates itself
 goal -> our navigator (plugins)         goal -> shim speaking navigator contract
            | robot.move                              | goal (Nav2 action)
            v                                         v
   GATE -> driver -> robot                    Nav2 + SLAM Toolbox
                                                      | cmd_vel into the DRIVER, not the robot
                                                      v
                                            GATE -> driver -> robot
```

The Burger could join at both:

| | Level 1 needs | Level 2 needs |
| --- | --- | --- |
| Driver | A ROS 2 driver: `robot.move` to `/cmd_vel`, `/odom` to `robot.state`, STOP and a deadman | The same driver. Same lease, same STOP |
| Navigator | A plain navigator with a differential-drive locomotion plugin, a 2D-scan range plugin, a localisation plugin. ADR-0020 says it does not reuse `duck_lab.nav` | A shim: `goal.start` to a Nav2 action, its outcomes mapped to our ends (RFC-0015 §3.5 has the map), `map` from SLAM Toolbox's grid |
| Contract | Profile accepts a robot with no head, no mapd, a scan sensor | Contract 1.3: `point` gets `yaw` (`CONTRACT.md:45`) |
| Safety | Lease held by the navigator | Lease held by the shim for the goal's duration |

The "Safety" row is where the two levels meet. If Nav2 publishes `/cmd_vel` itself, anyone on
that ROS graph can drive, and the gate is bypassed. ADR-0020 decision 2 says the driver is the
sole publisher to the robot. On DDS that cannot be a guarantee: any node in the domain can
publish `/cmd_vel`. It is narrowed by convention and watched, as section 3.3 says: Nav2's
output is remapped to a driver input, and the driver forwards it only while the lease holder is
the shim.

The NXT belongs at level 1 today: a driver with no navigator. It is the proof that a third driver,
with neither robotd nor ROS behind it, passes through the same interface.

### 3.3 The robot interface as ours

ADR-0020 decision 2 says neither robotd nor ROS is the platform's interface, ours is. A written
contract, "robot interface 1.0", would hold:

- **Two inputs.** The driver of a ROS robot takes commands from two places. Level 1: JSON-RPC
  `robot.*` (teleop and our navigator). Level 2: the gated `cmd_vel` from Nav2. Arbitration: the
  lease holder's commands win, and STOP zeroes both inputs.

- **Safety.** `gate.acquire`, `release`, `keepalive`, `takeover`, `who`; STOP from any
  connection, always, latching; a lease ends on release, expiry, STOP, takeover or disconnect, and
  every end stops the robot first (`robotgate/__init__.py:1-6`). The deadman (a robot stops when
  commands stop, 0.5 s on the duck, RFC-0003 §2.3) is **the driver's to guarantee**, whatever
  the robot behind it does.
- **State.** `robot.state`: pose in the driver's odometry frame, velocity requested and applied,
  mode, flags (fallen, picked up, limp), battery, link. Today's keys are in `DuckAdapter.state`
  and `NxtAdapter.state` (`duck.py:416-429`, `nxt.py:200-210`).
- **Health.** `robot.health`, polled every 10 s today (`duck.py:33`).
- **Commands.** `robot.move {vx, vy, vyaw}`; `vy` is ignored on a robot whose factsheet says it
  cannot move sideways. `robot.stop`. `robot.do {skill}` for what a robot offers (RFC-0003
  §2.1).
- **Sensors by declared capability.** A robot lists the sensors it has, each with an id, a kind,
  a stream, a frame, and a calibration reference. Today the slot exists (`capabilities.sensors`)
  and is empty for the duck (`profile.json:210`); the duck's depth arrives by a socket the host
  names, not by declaration.

The ROS driver is a ROS 2 node process, one per robot. It (a) is the gate's robot: it serves
`robot.*` over the gate socket; (b) subscribes the gated `cmd_vel` and forwards it only while the
navigator shim holds the lease; (c) can host the navigator-contract shim. This shape comes from
the advisor's review; no code of it exists.

How each robot becomes a driver:

| | robotd (duck) | ROS 2 (Burger) | NXT |
| --- | --- | --- | --- |
| Command | `robot.move` passes through | `robot.move` to `/cmd_vel` | `robot.move` to track power (`nxt.py:184-187`) |
| State | `robot.subscribe` stream | `/odom`, `/imu`, `/battery_state`, joint states | `/api/status` poll (`nxt.py:189-210`) |
| Deadman | robotd 0.5 s | **the driver's own** (not verified: whether the TurtleBot3 firmware has one) | robotd-lite on the brick, 0.5 s (RFC-0003 §2.3) |
| Lease | the gate process | the gate process | nxt-web's lock over HTTP |
| Sensors | 8x8 depth socket | `/scan`, later camera topics | ultrasonic, colour (RFC-0003) |

The honest list of what differs, so the contract does not pretend otherwise:

- **ROS topics are open.** Any node in the DDS domain can publish `/cmd_vel`; the sole
  publisher is not a property we can build in. robotd has "other doors" too (RFC-0017 §3.2:
  Pollen's app, the gamepad, `autod`), and the gate is "a convention that all of *our* programs
  follow" (§3.2 end). On ROS the doors are wider. So the rule is narrowed by convention and
  watched, in four parts. The driver remaps the base's input to a topic only it publishes. It
  owns a mux for Nav2's and any teleop's velocity (name only; not verified in this repo). It
  watches the graph for other publishers and raises `someone_else_drives` (RFC-0017 §3.2). And
  it isolates the robot's graph by `ROS_DOMAIN_ID`. A real boundary would be SROS2; that is out
  of scope.
- **ROS has a clock of its own.** Simulation stamps against our wall clock (section 3.6).
- **ROS has frames and a tf tree.** `map`, `odom`, `base_link`. ADR-0001 decision 2 already
  aligned names. Section 3.6.
- **ROS has discovery.** A graph lists topics; robotd has fixed methods. The driver exposes only
  the capabilities the profile declares, not the graph.
- **Velocity is held after silence on robotd** (hence the explicit zero, `:261-265`). Whether a
  ROS diff-drive base does the same is not verified; the driver publishes zero on STOP either
  way.

Where the code goes: the gate library needs two small changes (method names from the interface
contract, not constants; the stop sequence from the driver's declaration). `RemoteGate` and the
JSON-RPC wire in `duck.py:51-212` are already generic except for `DuckAdapter.state`. The Burger's
driver can speak the same socket protocol and reuse them. RFC-0015's `nav2/bridge.py` (the
duck-to-ROS bridge, §3.2) is the same idea in the other direction and a prior art; ADR-0018 calls
it "a candidate ROS 2 driver for Mission Control".

### 3.4 The simulator as a backend

Is a simulated Burger and a real Burger two drivers of one robot? Mostly yes, and it is how the
duck already works: the `duck-sim` adapter and a real duck differ in the host and the variant,
not in the profile's identity (`robots.py:92-99`, the installation's `variant`). For the Burger:

- One robot id, one profile with variants `sim` and `real`, as for the duck (`profile.json:224`).
- Two drivers of the same type, differing in where they connect: Gazebo's bridge (through
  `ros_gz`) or the real Burger's ROS graph.
- The backend (Gazebo) is separate from the driver: it provides reset, truth and the scene.
  The driver does not know it is in a simulator.
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
| Real time | RTF measured, runs at 1.0 (RFC-0021 §6) | RTF 1 set in the world, recorded per run (ADR-0020 decision 3) |

The host module is still one library (RFC-0021 §3.1: "a module per kind comes with the second
kind"). The host file schema needs a per-kind part: `pollen` is required today (`host.py:94-96`).

Truth for a wheeled robot is simpler, but the judge's vocabulary is legged. The judge asks for a
"trunk height" and a fall threshold (`profile.json:188`, `profile.py` `judge` block). A wheeled
robot's fall is a tilt. This is a profile change (section 7).

### 3.5 Sensors, mapping, reconstruction

What MVP 2 needs now, from the vision note's roadmap:

| Vision stage | Needs | When |
| --- | --- | --- |
| 1: simulated 2D SLAM | `/scan`, `/odom`, tf, a map; Gazebo; SLAM Toolbox | MVP 2 start |
| 2: errors | SLAM pose against the simulator's truth | MVP 2, early |
| 3: simulated RGB-D, RTAB-Map | camera streams, intrinsics, extrinsics | later |
| 4: physical mapping | a real depth camera, bandwidth, calibration | later |
| 5: object photogrammetry | overlapping photos | a separate project (section 5) |
| 6: scan missions | a mission API for viewpoints | later |

The advisor's "do not build yet" list, which this RFC keeps:

- No reconstruction interface (nothing reads one yet; ADR-0020 consequences).
- No image channels in `run.mcap`, ever (ADR-0020 decision 5). Images are side files.
- No camera intrinsics or extrinsics in the profile before a camera exists.
- No pause, step or simulated clock in the platform (ADR-0020 decision 3).
- No `lidar2d` schema until the first stub draws it.
- No generalisation of the sensor schema beyond the one sensor that is real (the Burger's
  scan), because a schema drawn from one example fits that one.

The 2D scan in the run needs care. ADR-0020 says a scan "fits today's tick records". I could not
confirm it. `/depth` is a point cloud in the `map` frame with a kind per point (`wire.py:264`,
ADR-0007). A scan stored as obstacle points loses the rays, so free space and maximum range are
gone, and those are what SLAM debugging needs. Section 8.7 gives three options. This is not
verified against a real scan. The run file already uses Foxglove schemas for its channels
(`libs/runfile/src/runfile/wire.py:23-34`: `FrameTransform`, `PoseInFrame`, `PointCloud`,
`RawImage`, `Grid`; read). The advisor says Foxglove also publishes a `LaserScan` schema; not
verified here. If it does, a `/scan` channel in that shape follows the file's own habit.

In Gazebo, the simulated sensors come from its sensor plugins: `gpu_lidar` for the scan and
`rgbd_camera` for RGB-D (names from the advisor's recollection; not verified here).

### 3.6 Frames, time, recording

Frames (ADR-0020 decision 4: ours; each driver maps onto them):

| Frame | Meaning | Source |
| --- | --- | --- |
| `world` | the simulator's or the site's truth | `wire.py:264` |
| `map` | the navigator's belief | `wire.py:264` |
| robot frames | each robot's own: `tof` for the duck | `wire.py:91` |
| a backend's | ROS `odom`, `base_link`, robotd's odometry | the driver's to translate; kept in `raw` if useful |

The duck's `site` frame and its odometry scale (0.91 in the simulator) are applied in the adapter
(`duck.py:416-420`). A ROS driver does its translation in the same place, which is why the
driver, not Mission Control, owns frames. The run's `/tf` is `world` to `map` only (ADR-0007),
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

Proposed rule, an amendment to ADR-0020 decision 3 for the operator to confirm (section 9,
question 13). It is not decided, and ADR-0020 is not edited. Inside the ROS graph:
`use_sim_time` true at a real-time factor of 1. The driver is the clock boundary: it stamps
`wall_ns` on receipt and records the ROS stamp beside it. The platform outside the driver stays
on wall time. Recording `sim_time` next to wall time costs little (`truth.py:7-9` already
carries it).

Recording: a robot's ticks (`/belief/pose`, `/truth/pose`, `/depth`, commands) stay in
`run.mcap`. Large streams are side files beside the run. ADR-0007 already has the precedent: an
import copies its source log into `source/` beside the run with a SHA-256. Proposed layout:

```text
 <run folder>/
   run.mcap                      # ticks, events, maps (format 2)
   streams/<sensor_id>/          # side files, one folder per declared sensor
     index.jsonl                 # t, wall_ns, file, sha256 per frame
     000001.jpg ...              # or png, or 16-bit depth png
   streams.json                  # per sensor: kind, frame, calibration ref, count, rate
```

A run record points at `streams.json`. Retention (plan step 7) works per run folder, so a heavy
run archives whole.

For the Burger the natural raw recording is rosbag2, written to MCAP, as one more side file
beside the run (for example `source/`, the name ADR-0007's import uses for a copied log). It
also meets the vision note's "save raw recordings". The advisor says `ros2 bag` writes MCAP by
default since ROS 2 Iron; not verified here. Our own run keeps the ticks; the bag keeps
everything the ROS graph said, with the ROS stamps, for replay into SLAM Toolbox later.

## 4. The external tools, one by one

I read no external documentation for this section (no web access). Versions, compatibility and
licences are from this repository or marked "not verified". "Replaces or duplicates" means
against our own stack.

| Tool | What it does | Role here | Integration | 2D / 3D | When |
| --- | --- | --- | --- | --- | --- |
| Gazebo Sim | Physics and sensor simulator | A second simulator backend | A host kind `gazebo-turtlebot3`; a process or container; SDF worlds written from `scene.json`; truth read from the model pose | both | MVP 2 start |
| ROS 2 | Message bus and tooling | The Burger's own stack, inside the driver and Nav2 containers | A container (ADR-0018); only the driver imports it | n/a | MVP 2 start |
| TurtleBot3 packages | The robot's bringup, models, simulation worlds | The Burger's description in ROS terms | Bringup on the Pi (real) or from the simulation package (sim) | 2D LiDAR robot | MVP 2 start |
| ros_gz bridge | Gazebo topics to ROS topics | The simulator backend's connection side | Runs beside Gazebo; carries `/scan`, `/odom`, `/cmd_vel`, `/clock`; stamps with sim time (section 3.6) | n/a | MVP 2 start |
| rosbag2 (MCAP) | Records a ROS graph's topics to a file | Raw recording, a side file beside the run | `ros2 bag record` in the ROS container; the file goes to `source/` (section 3.6) | both | MVP 2 start |
| Nav2 | Planner, controller, behaviour tree, costmaps, recoveries | Level 2 navigator behind our contract | Container; a shim maps `goal.*` to its action | 2D | MVP 2, after teleop |
| SLAM Toolbox | 2D LiDAR SLAM, a map and `map`-to-`odom` | A map provider | Container, same graph as Nav2; its grid becomes the contract's `map` | 2D | MVP 2 start |
| RViz | ROS's own live viewer | A debug aid inside the ROS container, not a surface | Optional, ROS container only | both | MVP 2 start, as a debug aid |
| RTAB-Map | RGB-D, visual and LiDAR SLAM, loop closure | A mapping plugin for 3D | ROS container; own database as a side artefact | 3D | Later |
| Open3D | Point clouds, TSDF, meshing | A reconstruction worker | Python library in a separate job | 3D | Later |
| COLMAP | Structure-from-motion, multi-view stereo | A reconstruction backend | CLI behind the photogrammetry contract (section 5) | 3D | Separate initiative |
| Nerfstudio | NeRF and splatting workflows | Visualisation experiments | Offline, GPU; never the platform | 3D | Never in the core |

Notes, one tool at a time:

- **Gazebo Sim.** What the repo says: RFC-0021 §3.1 plans a `gazebo-turtlebot3` kind: "its
  truth Gazebo's model pose, its scenes SDF". It duplicates MuJoCo's job for the Burger and
  nothing else. It pulls in a large install (not measured; ROS and Gazebo are installed on no
  host, RFC-0021 §3.1) and a second real-time risk. Versions: the vision note says to confirm a
  "compatible ROS 2 / Gazebo / TurtleBot3 combination" and I did not; ADR-0020 notes the same.
  Whether it runs on the operator's MacBook (Apple Silicon) is not verified. Its simulated
  sensors come from plugins (`gpu_lidar`, `rgbd_camera`; not verified here).
- **ROS 2 and its distro.** The parked Nav2 image is ROS 2 Jazzy on Ubuntu (ADR-0018). The
  workstation is Arch, hence the container. Whether TurtleBot3's packages support Jazzy and
  which Gazebo goes with it are not verified. ADR-0001 decision 4's trigger "ready-made SLAM or
  sensor drivers" is now met (ADR-0020 context).
- **TurtleBot3 packages.** Bringup, the Gazebo models and worlds, and navigation and SLAM
  launch files. I did not read them. The vision note says a Burger has a Raspberry Pi, an OpenCR
  controller, wheel encoders, an IMU and a 2D LiDAR "depending on kit generation" (section 4).
  Which LiDAR model is on the arriving kit is a question for the operator.
- **ros_gz bridge.** Needed to reach Gazebo from ROS. The driver should depend on topics, not
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
  (ADR-0001 context), which is the Burger's. That is evidence for level 2 on the Burger, not a
  promise. Outcome mapping already designed: SUCCEEDED to `reached`, planner failures to
  `refused`, controller failure to `stalled` (RFC-0015 §3.5). It duplicates our navigator's
  planner, costmap and recoveries (the very things RFC-0015 compared).
- **SLAM Toolbox.** Installed in the spike image (RFC-0015 §8); never driven. Needs a scan,
  odometry and tf. Replaces mapd's role for a robot that has a LiDAR; mapd stays for the duck.
- **RViz against our viewers.** The platform's surfaces are the Observatory (live and replay),
  Mission Control, and Rerun and Lichtblick for MCAP (ADR-0002). RViz would be a second viewer
  for data that is not in our runs. Keep it inside the ROS container. Do not build a RViz
  dependency into any contract.
- **RTAB-Map.** Needs RGB, depth, camera info, odometry (vision note section 6). Produces its own
  database, a format I have not looked at. Heavy compute: the vision note says desktop first.
  Not before a camera exists.
- **Open3D.** A new Python dependency. The rules require approval before any. It belongs in a
  separate worker, not in the runner or the gate.
- **COLMAP.** Standalone; no robot needed. This is the photogrammetry project's tool.
- **Nerfstudio.** The vision note itself says a pleasing model is not collision-safe
  (section 1). No role in navigation. Never in the core.
- **Licences.** Pollen's are in RFC-0021 §7 (Apache-2.0, with CC-BY-NC-SA for their 3D models).
  I did not check the licences of any tool in this section. Do that before any is distributed.

## 5. Photogrammetry as a separate initiative

The operator starts a separate, non-robotics photogrammetry project on 2026-11-24, to be reused
here "in the background". The aim of this section is one seam so neither project depends on the
other.

The seam is a file contract and a command line. No import, no shared process, no shared
package.

```text
 robotics-lab                           photogrammetry project
 (a run)                                (a standalone tool)
   streams/<sensor>/*.jpg  ---- job ---> images + images.json (+ cameras.json)
   poses from ticks                     recon --images D --manifest M --out O
   intrinsics, extrinsics   <---------- O/mesh.ply, cloud.ply, provenance.json
 reconstruction plugin = the glue
```

What the photogrammetry side takes:

- A folder of images.
- `images.json`: a version, `"manifest": 1`, then for each image its file, a time (wall
  nanoseconds), the sensor id, and optionally a pose (`world` or `map` frame, with the frame
  named) and a quality flag. Axes and units are stated once in the file: right-handed, z up,
  metres. The pose per image is the camera's pose, not the robot's. Who applies the mount (camera
  to robot base) is the glue's job, so the tool never needs the robot's frames; this is a
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
later:

1. The images, as side files (section 3.6), never in `run.mcap`.
2. A time for each image in wall nanoseconds, the same clock as the ticks. The nearest-tick rule
   with a bounded gap already exists for truth
   (`libs/runfile/src/runfile/truthcopy.py:26`), and it applies here.
3. The robot's pose at each image: the belief in `map` and, in a simulator, the truth in `world`.
   Both are in the ticks today. The glue turns it into the camera's pose with the mount.
4. The camera's intrinsics and its mount, written once per run as part of `streams.json`.
5. Which sensor each image came from, so two cameras are not mixed.
6. A privacy note per run. The vision note (section 11) names faces, screens and documents in a
   home scan; retention (plan step 7) should be able to remove side files by run.

What the photogrammetry project should know, from this RFC, without depending on it: accept
optional poses and optional intrinsics, state its output's frame and scale, and expose a command
line with a stable manifest. Which repository it lives in, and its licence, are the operator's
(section 9).

## 6. The evolution from A to B

Rules for every stage: MVP 1 keeps working; each stage ends green on `make ci-fast`,
`make sim-duck` and the challenge batch whose verdicts must match the last batch (as in plan
items 1 and 2); a stage changes one seam. Sizes are rough (S, M, L) and not estimates in time.

| Stage | What changes | What stays | Proof | Size | Decided by |
| --- | --- | --- | --- | --- | --- |
| 0 | Accept this RFC and ADR-0020; name the follow-up RFCs | All code | The operator's decision | S | this RFC, ADR-0020 |
| 0b | Proposed spike, zero platform code (section 6.1): the TurtleBot3 Gazebo simulation in a container, teleop, SLAM Toolbox, a saved map; measure the real-time factor and whether the base holds the last velocity | All code | Measured answers to many of section 10's "not verified" items | S | the operator's go (question 14) |
| 1 | The robot interface written as a contract with a number; the duck's driver and the NXT's brought to it; the gate takes method names from it; the adapter surface written down | Duck behaviour, protocol 1 accepted by the new gate | One contract test run against the fake, duck-gate and NXT adapters (as `test_contract.py` does for navigators); `make sim-duck` | M | RFC-0026, "the robot interface" |
| 2 | Profile v2: required blocks shrink to identity, factsheet, control, capabilities, plugins; locomotion, footprint, sensors become per-kind; a plugin set may be empty; the judge's fall rule by kinematics; registration names its driver | The duck's profile migrated by `upgrade` (`profile.py:503`), checksums rule | Every stored profile loads; the duck's numbers unchanged; a plugin-less stub profile validates | M | RFC-0027, "profiles for any robot" |
| 3 | The simulator backend written as an interface; `simhost` gets a module per kind; a scene writer per kind. Conditional part: scene.json becomes the world and the five readers move off the layout. On the critical path only if challenge courses must run in Gazebo (section 9, question 2); otherwise after stage 6 | MuJoCo kind unchanged | Challenge verdicts match; `scene` test (61 boxes equal) extended | M-L | RFC-0028, "backends and worlds" |
| 4 | A stub Gazebo host and the lease, STOP and state in Mission Control through the fake adapter (it already proves the gate); a run with a stub scan, to settle the run format | Everything else | The robot page shows the stub; a run opens in the Observatory | M | the three RFCs |
| 5 | The real Gazebo Burger: ROS driver, bridge, `/scan`, `/odom`, truth, an SDF world from `scene.json`; the clock rule of section 3.6 (`use_sim_time` true inside the graph, the driver stamps `wall_ns` and records the ROS stamp) | Nothing of the duck | Drive the Burger from Mission Control; a recorded run with truth; tf lookups hold | L | ADR on time and frames, after the operator's answer to question 13 |
| 6 | Level 2: Nav2 and SLAM Toolbox behind contract 1.3 (`yaw`); the shim; the outcome map | Contract 1.x readers | A `point` goal reaches by truth; the contract test passes against the shim; the duck still passes | L | RFC-0029, "a self-navigating robot" |
| 7 | 2D scan channel; SLAM pose against truth | Format 2 readers (additive) | The Observatory draws the scan and the map | M | a note in ADR-0007 |
| 8 | The real Burger on hardware: the driver on the navigator's computer, the Pi's bringup only; a safety review | The sim path | Needs the operator and the robot, as the real duck's B6 | M | the operator |
| 9 | A depth camera: side streams, calibration, retention per run | Ticks | Later | L | a later RFC |

Order of the stages (a dependency graph, not a schedule):

```text
 0 -> 0b (proposed) -> 1 -> 2 -> 4 -> 5 -> 6 -> 7 -> 8
                        \-> 3 (writer) ---^
 3 (scene.json as the world): before 5 if challenge courses must run in Gazebo,
                              otherwise after 6
 9 after 7
```

### 6.1 Stage 0b, the spike

Stage 0b is a proposal. The operator said to reflect first and not build, so nothing here runs
until the operator approves it (section 9, question 14). It touches no platform code. In a
container, run the TurtleBot3 Gazebo simulation, drive it by teleop, run SLAM Toolbox over it,
and save a map. Measure the real-time factor. Find out whether the base keeps its last velocity
after the commands stop. The advisor recalls the OpenCR firmware has a motor timeout of about
500 ms; not verified here. The spike resolves many of the "not verified" items in section 10
(versions, real-time cost, bridge stamps, the velocity hold) and feeds RFC-0026 with facts
instead of recollection.

Where an ADR is warranted: the clock policy (stage 5; an amendment to ADR-0020 decision 3 if the
operator confirms it), the rule that the driver owns the velocity path (ADR-0020 decision 2,
narrowed as section 3.3 says), and the frames rule (ADR-0020 decision 4 to
become a contract in stage 1).

What must be true before stage 4 starts: the operator's answers to section 9 questions 1, 2, 3,
4 and 5. Stage 0b, if approved, runs before stage 1.

## 7. Problems still to solve, ranked

Ranked by how early they bite and how much they cost to get wrong. Time and stamps rank above
"who drives": the first breaks tf in the simulator, the second is a design rule.

1. **The robot interface is robotd's.** It bites at the first Burger command. The gate's method
   list, the `vy` field, the stop sequence and `DuckAdapter.state` all assume robotd
   (section 2.4, items 1 and 2). Until it is a contract with a number, every second robot
   imitates the first one's daemon. This is the central design task.
2. **The profile requires the duck.** A Burger profile today must invent a circular footprint
   with a lethal and an inflation ring tuned to a duck, a locomotion block with a turn kick, and a
   plugin for every block (`profile.py:179-189`, `:235`, `:492-494`). The fix is a schema
   change. It touches every stored profile and the checksum rules, so it needs a migration, not
   an edit.
3. **Time and stamps.** The assumption of wall time is stated (ADR-0020 decision 3) but not
   enforced, and a second problem sits under it. `ros_gz_bridge` stamps with simulation time,
   starting near 0 (not verified here), so a ROS graph on `use_sim_time` false would fail its tf
   lookups (section 3.6). The proposed rule (use sim time inside the graph, the driver as clock
   boundary) is an amendment the operator has not confirmed. Separately, a Gazebo world with a
   camera or many LiDAR rays may fall below real time on this hardware (not measured). A run
   below real-time factor 1 silently changes timing, timeouts and the 0.1 s truth pairing
   (`libs/runfile/src/runfile/truthcopy.py:26`). The factor must be recorded and checked.
4. **Who drives, on an open graph.** A design rule, not a blocker in the simulator. ADR-0020
   says the driver is the sole publisher, but on DDS any node can publish `/cmd_vel`. The rule
   is narrowed by convention and watched: a remap to a topic only the driver publishes, a mux
   the driver owns, a watch for other publishers (`someone_else_drives`), and `ROS_DOMAIN_ID`
   isolation (section 3.3). On the duck, "other doors" are acknowledged and watched (plan 4b
   item B4); the ROS graph has more of them.
5. **DDS discovery across Wi-Fi and host-network containers.** The driver, Nav2 and the Burger's
   bringup will sit on different computers, with `--network host` containers (as RFC-0015's
   spike ran). Multicast discovery often fails on Wi-Fi. Likely the first thing to break on a
   real Burger (the advisor's judgement; not verified here).
6. **The world is MuJoCo geoms.** Five readers (section 2.4 item 7), the Observatory's analysis
   with its name conventions (`anomalies.py:85-100`), and the challenge scene writer that builds
   from Pollen's XML (RFC-0021 §3.1). "Fully compatible" (question 2) depends on whether
   challenge courses must run in Gazebo. If yes, an SDF writer is on the critical path.
7. **The judge and the truth for a wheeled body.** "Trunk height" and a fall threshold
   (`profile.json:188`, `truth.py:29-31`) mean nothing for a Burger. The judge needs a
   kinematics-aware fall rule and a truth reader per backend.
8. **Frames.** SLAM Toolbox publishes `map` to `odom`, which jumps. Our run has one `map` frame
   and epochs. The duck's frame has a scale correction (0.91). A ROS driver must say which
   frame its odometry is in, and whether it scales. A map's origin differs per SLAM session.
9. **A scan in the run** (section 3.5): a point cloud with kinds is not a scan. Needs an additive
   channel or a side file.
10. **Safety on Wi-Fi.** The real Burger is on Wi-Fi, the driver on another computer. A lost link
   must stop the robot. If the base holds the last velocity (not verified), the driver cannot
   guarantee a stop it cannot send. A robot-side timeout on the Pi may be needed. This is the
   Burger's version of the duck's B5 link tooling.
11. **Contract 1.3 and goals.** `point` has no heading (`CONTRACT.md:45`), and a Nav2 goal has
    one. The duck's other kinds (`go_to_object`, `explore`, `inventory`) have no Nav2 meaning
    without a recogniser and a frontier explorer; "explore" for the Burger is not defined.
12. **Data volume and bandwidth.** RGB-D at any rate is large; a Pi and Wi-Fi may not carry it
    (vision note section 11). Nothing is measured. This decides whether images are recorded on
    the robot's computer or the navigator's.
13. **Calibration and sim to real.** Extrinsics and intrinsics have no home. Plan unit A3's
    calibration frame (odometry scale through a navigator method) is the nearest, and it is
    duck-only today.
14. **Install weight and hosts.** Gazebo and a ROS image add gigabytes (the spike image is
    5.1 GB). The setup and check scripts (RFC-0021 §4) cover Pollen's simulator only. Gazebo on
    the MacBook is not verified.
15. **Anomaly kinds.** The robot-raised anomaly kinds (`anomalies.py:639`) are the duck's; a
    Burger's (a scan lost, a SLAM jump) need names, and the duck's should not be assumed.

## 8. Options and recommendations

### 8.1 The robot interface

- **A.** The duck's `robot.*` stays the platform's interface; every driver imitates robotd.
  Rejected by the operator (ADR-0020, alternatives).
- **B.** Write ours as a versioned contract, starting from the current method names where they
  fit; the duck's driver first (today a pass-through); declare what differs. Cost: a contract to
  maintain.
- **C.** Adopt an outside standard as the interface. VDA 5050 is already the factsheet's naming
  (`robots.py:8-10`) and is not a command protocol for teleoperation; ROS's messages as the
  interface would make ROS the foundation, which ADR-0020 rejects.

Recommendation: B. Keep JSON-RPC and the names `robot.move`, `robot.stop`, `robot.state`,
`robot.health` in version 1, so nothing breaks; add what is missing by capability declaration.

### 8.2 Where Nav2 and the ROS driver run

- **A.** On the Burger's Pi. Fewest hops, but the Pi's compute is limited (vision note section 4)
  and a lost link leaves a robot navigating alone.
- **B.** In a container on the navigator's computer, with the gate (RFC-0017 §3.2 puts the gate
  there). The Pi runs the robot's bringup only. Cost: ROS traffic over Wi-Fi (not verified).
- **C.** Mixed: the driver and gate on the navigator's computer; Nav2 and SLAM Toolbox in a
  sibling container there; only the bringup on the Pi.

Recommendation: C, which is B with the parts named. The vision note says the same: "run heavier
SLAM and reconstruction on a desktop initially". In the simulator everything runs on one host.

### 8.3 Integration levels

- **A.** Level 1 only. Burger driven by a new plain navigator. Writes a lot of what Nav2 has.
- **B.** Level 2 only. Fast to a mapped Burger, but nothing proves "we drive it" for ROS.
- **C.** Both first-class in the contracts; build teleop (the driver) first, then level 2, then
  level 1 only if a reason appears (a comparison like RFC-0015's).

Recommendation: C.

### 8.4 Time

- **A.** Wall clocks only, real-time factor 1 recorded (ADR-0020 decision 3 as accepted).
- **B.** A, plus `sim_time` recorded beside wall time and checked against the factor each run.
- **C.** A platform clock with pause and step.

Inside the ROS graph, the choice of A or B leaves one more question: the stamps. The
simulator's bridge stamps with simulation time (not verified here), so `use_sim_time` false
would fail tf lookups, and RFC-0015's way out (the bridge stamped with its own clock,
`nav2/bridge.py:5`) is not available for a Gazebo bridge.

Recommendation: B, with the proposed amendment to decision 3: inside the ROS graph
`use_sim_time` true at a real-time factor of 1; the driver is the clock boundary, stamps
`wall_ns` on receipt and records the ROS stamp beside it; the platform stays on wall time. It is
nearly free (`truth.py:7-9`), makes slow runs visible, and leaves C open without building it.
It is a proposal for the operator (section 9, question 13), not a decision.

### 8.5 The world

- **A.** One hand-made world per backend. Drift between them.
- **B.** `scene.json` is the world; each backend writes its format; the layout's readers move to
  the scene's boxes (the plan's test that the two agree already exists).
- **C.** Gazebo's world becomes canonical. Ties the platform to one simulator.

Recommendation: B.

### 8.6 The profile

- **A.** The Burger fills duck-shaped blocks with stand-ins.
- **B.** Profile v2: per-kind blocks, a plugin set that may be empty, sensors as a declared list.
- **C.** Split into a driver profile and a navigator profile.

Recommendation: B, with C's split noted: level 2 robots need no navigator profile.

### 8.7 The scan in the run

- **A.** As points in `/depth`.
- **B.** A new additive `/scan` channel in a Foxglove shape. The run file already uses Foxglove
  schemas (`libs/runfile/src/runfile/wire.py:23-34`) and the advisor says Foxglove publishes a
  `LaserScan` schema (not verified here).
- **C.** A side file, for example the rosbag2 MCAP of section 3.6.

Recommendation: B for a 2D scan (it is small), if the `LaserScan` schema exists as the advisor
says; C for anything image-like.

### 8.8 The NXT's place in the model

- **A.** A level 1 driver with no navigator, as today.
- **B.** A driver plus our navigator with tracked plugins (RFC-0020 step 5).
- **C.** Out of the model until MVP 1 is done.

Recommendation: A for MVP 2. It proves a third driver, and nothing else changes for it except
its gate moving to the written interface.

### 8.9 Photogrammetry

- **A.** Library: the robotics side imports it. Couples releases.
- **B.** File contract and CLI (section 5).
- **C.** A service. More to run, no gain now.

Recommendation: B.

## 9. Questions for the operator

1. **Where does Nav2 run:** on the Burger's Pi, in a container on the navigator's computer, or
   mixed (option 8.2)? It decides where the ROS driver lives.
2. **What does "fully compatible" mean for the Burger:** the challenge courses run in Gazebo
   (an SDF writer is needed), or Mission Control's goals only?
3. **Which sensors, on which robot, when:** the Burger's LiDAR model (not known here), an IMU
   used or not, a camera: which one and from which stage? Until then there is no image channel.
4. **ROS 2 and Gazebo versions.** The parked image is Jazzy; the Burger's support for it, and
   which Gazebo to pair, are not checked.
5. **The NXT's place:** option 8.8 A, B or C.
6. **Both integration levels first-class (8.3 C), or one?** And is a navigator of ours for the
   Burger wanted at all, or only Nav2 behind the contract?
7. **Time:** accept 8.4 B (record `sim_time`, check the factor)? Real-time factor 1 and the
   platform's wall clock stay as ADR-0020 decision 3 says; question 13 is the separate stamp
   rule.
8. **Does the Burger on hardware belong to MVP 2, or only the simulated one?** It changes
   whether the safety review (stage 8) is in the plan.
9. **Photogrammetry:** where does the project live (this repository or its own), what licence,
   and may its first output feed a Gazebo world later?
10. **Is ADR-0020 accepted now,** or after the interface RFC?
11. **Which viewer for 2D scans:** the Observatory, or Rerun and Lichtblick through MCAP?
12. **Should the MacBook run Gazebo,** or only the workstation?
13. **A proposed amendment to ADR-0020 decision 3, for you to confirm or refuse.** Keep the
    real-time factor at 1 and the platform on wall time, as you accepted. Add one rule: inside
    the ROS graph `use_sim_time` is true, and the driver is the clock boundary, stamping `wall_ns`
    on receipt and recording the ROS stamp beside it. The reason is that `ros_gz_bridge` stamps
    with simulation time (not verified here). Not decided; ADR-0020 is unchanged.
14. **May the zero-platform-code Gazebo spike (stage 0b, section 6.1) run?** It would use a
    container and the TurtleBot3 simulation, and no platform code. You said to reflect first and
    not build; it runs only on your go.

## 10. Not covered, and what I did not verify

Not read: Mission Control's `CONTRACT.md`; RFC-0014, 0016, 0019, 0022; ADR-0013, 0014, 0019; the
duck's navigator and its plugins in code; the Observatory beyond `anomalies.py`; the real duck's
readiness notes; the `nav2/` directory's bridge code beyond its docstring (`nav2/bridge.py:5`).

Not verified:

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
- Everything about versions and compatibility: ROS 2, Gazebo, TurtleBot3 packages, `ros_gz`,
  Nav2 beyond the parked image's 1.3.14, which is from RFC-0015 §8.
- Licences of every tool in section 4. Disk, RAM, GPU and real-time cost of Gazebo on this
  workstation or the MacBook. ROS traffic over Wi-Fi.
- The data rate of any camera, and the Pi's capacity.
- Whether a Gazebo world reload is faster than the duck's 40 s reset.
- That `twist_mux` or any specific mux is the right way to own the velocity path; I only say the
  driver must own it.

Line numbers cited: `file:line` is as the file reads on 2026-11-23. RFC citations are by section
because several RFCs are edited often. A line in `profile.py`, `host.py`, `wire.py` and the gate
was checked by reading the line itself; the 2.4 item 7 geometry lines were read in place, and
`CONTRACT.md:45` is the point goal (the advisor cited line 47; the file as read has it at 45).
