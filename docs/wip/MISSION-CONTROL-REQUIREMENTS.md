# Mission control: requirements, 2026-11-17

Gathered before any design or build. The operator's direction on 2026-11-17: a new app to see the
robots, whether they are online and how they are, and give them goals; "the de facto interface on
top of the planner and UI for the navigation work, like a control panel"; the place where goals for
robots are defined, run in the simulator or real life, and their progress observed. "Gather
requirements now and work toward mission control and the other RFCs we have open, and build those."

This brings [RFC-0005](../rfc/RFC-0005-missions.md) (missions) and
[RFC-0006](../rfc/RFC-0006-mission-control.md) (mission control) to life; both are Proposed
(2026-11-14) and nothing of either is built. The next step is an RFC written from this list, for the
operator to read before anything is built.

## 1. The operator's requirements (2026-11-17)

| # | Requirement | Operator's words, condensed |
| --- | --- | --- |
| O1 | A **new, standalone app**: robots, online or not, status and stats, driving, goals | "an app where I can go, see my robots, when they are online, see their stats, and then give them goals" |
| O2 | **Robots:** the simulated duck, the real duck (not owned yet), the LEGO NXT, the LEGO EV3 (arriving in days) | answer 1 |
| O3 | **Goals** start as a point on the map, and evolve later | answer 2 |
| O4 | **Self-contained:** the app draws the robot's map itself and goals are set on it | answer 3 |
| O5 | **A link to miniview** (`/watch`) for the deeper, live view | "use explore to connect to live view if I want" |
| O6 | **`nxt-web` stays** the NXT's own small playground; mission control is a new app | answer 4 |
| O7 | **Goals are managed in the app:** defined once, run in the simulator or real life, progress observed | "this is where we define goals we want for robot, in real life or sim, and observe progress" |
| O8 | **Long term: robots in a swarm, collaborating;** designed for it from the start | "robots working in swarm and collaboration, so let's keep this in mind from start" |
| O9 | **Parallel communication** with several robots at once | "meaning also parallel communication with several robots" |
| O10 | **The NXT, the EV3 and the duck collaborate on the same goals**; the LEGO robots get better sensors over time | "I will boost lego robots with better sensors as I go" |
| O11 | **Full MCP and a remote API**, so a mobile app can be built later | "also full mcp and remote api control" |
| O12 | **Control through an agent** | "and control through agent" (which kind is open: §5, Q2) |

What they mean for the design (my reading, for the operator to confirm in the RFC):

- **API first.** Everything the page does is an API call; the page, MCP, an agent and a future
  mobile app are equal clients (O11, O12). Nothing works only in the page.
- **Many robots from the start, one at first.** Each robot has an identity; the app never assumes
  there is one; one shared map and frame per place; a goal names a robot and leaves room for a team
  (O8, O10).
- **One connection per robot, independent and concurrent.** A slow or dropped robot does not stall
  the others; STOP reaches all of them at once (O9).
- **Capabilities are data.** Each robot says what it has (sensors, a map, a navigator, speeds); the
  app offers what the robot can do. A sensor added to the NXT changes its description, not mission
  control's code (O10). Today only the simulated duck has a map and a navigator; the NXT and EV3
  start with status, driving and STOP.

## 2. What the open RFCs and ADRs already require

Decided (D) or proposed only (P). Line numbers for RFC-0006 are given by section.

### 2.1 Product and boundaries

- Mission control's job: operate robots (see, drive, give missions, keep safe); all robot-specific
  code lives there, none in flotilla. P, RFC-0006 §2.
- It works alone (one home, a few robots, a simple "confirm the mission"); with flotilla, flotilla's
  policy and approvals replace that confirm and flotilla's freeze stops the robots. P, RFC-0006 §2;
  [FLOTILLA-ASKS.md](FLOTILLA-ASKS.md) F1–F16.
- The line: command and keep safe (mission control), show and store (viewer and logbook), judge
  (eval-harness), govern (flotilla). D, RFC-0006 §3.3 amended by
  [RFC-0007](../rfc/RFC-0007-platform.md) §2.
- Open-source product: one Python service with a web page, MCP and Slack, a Docker image, a driver
  per robot, optional flotilla. P, RFC-0006 §4. Local first: recordings stay local. P, RFC-0007 §5.
- The viewer does not send commands to a robot. D,
  [ADR-0005](../adr/ADR-0005-miniview-api-live-from-the-start.md) (non-goals). Commanding belongs to
  mission control.

### 2.2 Robot interface

- One JSON-RPC interface for every robot, in the duck's shape: `robot.move`, `robot.stop`,
  `robot.subscribe` (state), `robot.health`, `hello`, … P,
  [RFC-0003](../rfc/RFC-0003-robot-interface.md) §2.1; the duck's methods are upstream facts,
  [RFC-0002](../rfc/RFC-0002-robot-brain.md) §2.
- The NXT gets the same method names through a Python NXT service; not built. P, RFC-0003 §2.2.
- One driver at a time, and a per-robot lock. D (non-goal), RFC-0003 §3; P, RFC-0002 §3.6.
- The brain's API: JSON-RPC `mission.start`, `mission.stop`, `status`, an events stream; every UI a
  client. P, RFC-0002 §3.10. Not built.
- Several robots: one mission per robot in parallel, a navigator per robot. P, RFC-0002 §3.9. A
  multi-robot mission needs a shared map and frame: deferred to phase 6. D, RFC-0002 §3.9, §4.
- ROS-aligned terms and shapes (Twist, Odometry, OccupancyGrid; map/odom/base_link), no ROS. D,
  [ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md).

### 2.3 Safety

- STOP goes straight to `robot.stop`, never through the planner; the robot's deadman is the
  backstop. P, RFC-0002 §3.5.
- The duck's deadman: 500 ms. D (upstream). The NXT: the web UI's 0.6 s watchdog (built) and
  robotd-lite on the brick (built against the simulated brick; the real-brick check is pending).
  RFC-0001 §3.3, RFC-0003 §2.3.
- Real-duck missions need the operator in the room with a STOP at hand. D, RFC-0002 §3.5.
- Situation rules (someone else drives, Wi-Fi drop, lost, fall, pick-up): stop, mark interrupted,
  resume only when the operator says so. P, RFC-0002 §3.6.
- Firing (the NXT shooter) is irreversible: always proposed, never automatic. P, RFC-0003 §2.3,
  RFC-0005 §2.3.

### 2.4 Missions and goals

- A mission spec: a validated JSON schema (explore, report, end, limits); anything outside it is
  refused; the spec is read back and confirmed. P,
  [RFC-0004](../rfc/RFC-0004-perception-and-planning.md) §2.1.
- Planner tools include `go_to(x, y)`, `explore`, `survey`, `go_to_start`, `stop`. P, RFC-0004 §2.5.
- Every mission rehearses on the simulated duck before it runs on the real one; a rehearsal is
  necessary, not sufficient (it does not predict timing, falls or real perception). P, RFC-0005
  §2.1–2.2.
- Goals as the navigator takes them today: a map point (x, y), reached or refused with a reason. D,
  [ADR-0015](../adr/ADR-0015-scenario-runner.md). Challenges add a scene and a pass condition. D,
  ADR-0015, [RFC-0008](../rfc/RFC-0008-challenge-course.md).

### 2.5 Map, status, records

- The map is mapd's occupancy grid (10 cm), with the navigator's layers (obstacles, drops, gaps) and
  the plan; miniview already streams them per run (`world.grid`, `world.obstacles`, `world.drops`,
  `world.gaps`, `plan.path`, `belief.pose`). D, RFC-0002 §2; `viewer/CONTRACT.md`.
- Status: the duck gives odometry, the applied twist and who sent it, fall and pick-up flags,
  autonomy, battery (`robot.health`); the NXT's web UI gives connected, battery, link and deadman
  (`GET /api/status`).
- MCAP is the record; run key `robot/scene/run`; every run records goals and outcomes. D, ADR-0004,
  ADR-0006, ADR-0014.
- Robot telemetry (battery, link, errors) goes to the homelab observability stack. P, RFC-0007 §2.

### 2.6 MCP and remote access

- MCP and Slack on every component a person or an agent talks to. P, RFC-0007 §2; RFC-0006 §3.1
  lists the first MCP tools (list robots, status, start a mission, stop, snapshot).
- miniview's query layer is built so its API and a later MCP server call the same functions. D,
  ADR-0005.
- Transport and authentication must be settled before anything listens beyond localhost. Open,
  RFC-0003 §4. nxt-web and miniview are loopback-only with no authentication today.

## 3. Where the operator's decisions change the RFCs

| # | RFC says | Operator decided | To do in the RFC |
| --- | --- | --- | --- |
| C1 | Mission control grows from `nxt-web` (RFC-0006 §3, §3.1, §5, §7; RFC-0002 §3.10) | A new app; `nxt-web` stays the NXT playground (O6) | Supersede; also STATUS.md, ROADMAP.md, ECOSYSTEM.md repeat the old line |
| C2 | Mission control draws no maps or history of its own; it links to the viewer (RFC-0006 §3.3, RFC-0007 §6) | The app draws the map and sets goals on it (O4) | Amend: the map for commanding is mission control's; history and deep views stay in the viewer |
| C3 | Links go to Foxglove (RFC-0006), then to "the viewer" (RFC-0007) | Links go to miniview (O5) | Name miniview as the deep view |
| C4 | Goal and mission history belongs to flotilla (FLOTILLA-ASKS) and the logbook (RFC-0007) | Goals are defined, run and followed in the app (O7) | Draw the line again: mission control keeps goals; flotilla, when connected, governs them |
| C5 | First interfaces: page, MCP, Slack (RFC-0006 §3.1) | Page, full MCP, a remote API for a mobile app, an agent (O11, O12); Slack not mentioned | Ask whether Slack stays in the first version |
| C6 | One driver at a time (RFC-0003) | `nxt-web` stays, so two apps can drive the NXT | A lock rule across apps |

## 4. What exists to build on

| Piece | What it gives | Where |
| --- | --- | --- |
| Duck navigator | `go_to((x, y))`, exploring; Python and CLI only (`duck-go x y`, `duck-explore`); **no API server** | `duck/src/duck_lab/nav/run.py` (`Navigator`), `explore_run.py` |
| Duck simulator | JSON-RPC over Unix sockets (robotd, mapd, tof), client classes | `duck/src/duck_lab/nav/client.py`; `~/.cache/duck-sim/` |
| NXT web UI | HTTP JSON API: status, drive, stop, record, programs; records miniview runs | `nxt/src/nxt_lab/web.py`; :8000 |
| miniview | Read-only API: runs, live stream (SSE), world/map streams, robot descriptions, `/watch` | `viewer/`; `viewer/CONTRACT.md`; :8070 |
| Robot descriptions | duck, NXT shooterbot, EV3 Spike3r and Track3r, as links and joints | `robots/`, RFC-0011 |

Missing: an API in front of the navigator, any goal store, any "is this robot online", any EV3
driver or interface, the RFC-0003 interface for the NXT, any MCP or Slack code.

## 5. Questions answered by the operator (2026-11-17)

1. **Goals carry conditions from the start.** A goal is where, what counts as done (within 25 cm,
   under 60 s) and what must not happen (no contacts), as the challenges are. The first version has
   point goals with a few fixed conditions; "explore every room" comes later as a goal kind.
2. **Agent: an outside agent through MCP first.** Claude or any MCP client operates the robots
   through the same API as the operator, with the same STOP and limits. An agent in the app that
   takes words comes later, on top (RFC-0004's missions in words).
3. **Slack later.** The first version is the API, the page and MCP.
4. **Remote access: the tailnet only, one operator.** The app listens on the workstation and the
   tailnet (phone, laptop), with nothing public. STOP works from every client and never needs a
   confirmation. In the first version the tailnet is the authentication; tokens per client come when
   the mobile app or an agent gets its own access.
5. **Name: Mission Control.** The open-source product's name can be chosen when it splits into its
   own repository (RFC-0006 §4).

Still open, already recorded in the RFCs: where the brain runs long term (RFC-0002),
the e-stop (flotilla's freeze, the UI's STOP, both; RFC-0005 §4), where the NXT's interface lives
(RFC-0003 §4), how a mission spec is confirmed (RFC-0004 §4), the logbook's home (RFC-0007 §8), when
to split mission control into its own repository and its licence (RFC-0006 §6).

## 6. Not covered by this list

- **The EV3.** No requirement, driver or safety design exists in any doc (only its robot
  descriptions). Its firmware and sensor protocol differ from the NXT's; it needs its own interface
  and deadman before it can be driven from the app.
- **The real duck.** Not owned yet; its link (ssh-forwarded sockets, then the navigator on the
  robot) is in RFC-0002 §3.3 but untested.
- **Collaboration.** What two robots doing one goal means (dividing a map, handing over, roles) is
  not specified anywhere; RFC-0002 §3.9 defers multi-robot missions to phase 6.
- **Not read** while gathering this: PRD-001 and UXS-001 (miniview), the review notes, RFC-0010,
  RFC-0012, most ADR bodies, flotilla's and eval-harness's own repositories.
- **Not checked by running anything:** the endpoints above as described; whether `nxt-web` and the
  miniview container currently run as documented.
