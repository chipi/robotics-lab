# RFC-0014 — Mission Control: one API for every robot, a page, goals on a map

**Status:** Proposed (2026-11-17) — draft for the operator's review
**Builds on:** [RFC-0006](RFC-0006-mission-control.md) (the vision, superseded in part, §2.1),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0002](RFC-0002-robot-brain.md) §3.9 to §3.10 (several robots, the brain's API),
[RFC-0005](RFC-0005-missions.md) (missions), [RFC-0007](RFC-0007-platform.md) (the platform),
[RFC-0013](RFC-0013-robot-eye.md) and [RFC-0009](RFC-0009-miniview.md) (miniview),
[ADR-0015](../adr/ADR-0015-scenario-runner.md) (goals as challenges).
**Requirements:** [MISSION-CONTROL-REQUIREMENTS.md](../wip/MISSION-CONTROL-REQUIREMENTS.md)
(O1 to O12 are the operator's, 2026-11-17; C1 to C6 the conflicts with earlier RFCs).

## 1. Why

The operator wants "an app where I can go, see my robots, when they are online, see their stats, and
then give them goals", in the simulator or in real life, with the progress observed. Later the
robots work as a swarm, "so let's keep this in mind from start", and the LEGO robots get better
sensors as they go. The app must also be reachable by MCP, by a remote API for a mobile app,
and by an agent.

RFC-0006 describes this product but grows it from `nxt-web`, draws no maps and points at Foxglove.
The operator decided otherwise: a new app, which draws the map and takes goals on it, linked to
miniview. Nothing of RFC-0006 or RFC-0005 is built (requirements §4: no API in front of the
navigator, no goal store, no "is this robot online", no EV3 driver). This RFC settles the shape
before any code.

## 2. Goals and non-goals

### 2.1 What this changes in earlier RFCs

| # | Earlier statement | After this RFC |
| --- | --- | --- |
| C1 | Mission control is grown from `nxt-web` (RFC-0006 §3, §3.1, §5, §7; RFC-0002 §3.10) | A new app. `nxt-web` stays the NXT's small playground and is not generalised. RFC-0006 §3.1 (the page), §5 (order) and §7 (the alternative "grow nxt-web") are superseded. STATUS.md, ROADMAP.md and ECOSYSTEM.md repeat the old line: not checked, to be corrected when this is accepted |
| C2 | Mission control draws no maps or history (RFC-0006 §3.3, RFC-0007 §6) | The map for commanding is Mission Control's. History, comparison and deep views stay in miniview |
| C3 | Links go to Foxglove (RFC-0006), then "the viewer" (RFC-0007) | The link goes to miniview's `/watch` |
| C4 | Goal and mission history belongs to flotilla and the logbook | Goals are defined, run and followed in Mission Control. flotilla, once connected, governs them (§3.4.4) |
| C5 | First interfaces: page, MCP, Slack (RFC-0006 §3.1) | Page, MCP and the remote API. Slack later (operator, answer 3) |
| C6 | One driver at a time (RFC-0003 §3, non-goal) | Holds per robot, now across apps: a lock (§3.3.3) |

What does not change: RFC-0006 §2 and §3.3's line (mission control commands and keeps safe, the
viewer shows and stores, eval-harness judges, flotilla governs), as amended by RFC-0007 §2; the
ROS-aligned terms ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)); RFC-0006 §3.2 and §4
(what it is not; the open-source product, whose name was chosen: Mission Control).

### 2.2 Goals

- One API that every client uses equally. Nothing works only in the page (O11, O12).
- Many robots from day one, one built first (O8, O9, O10).
- Goals with conditions, defined once, run on the simulated duck or on a real robot, with attempts
  and progress kept (O3, O7).
- A map in the app with goals set on it (O4); a link to miniview for the deep view (O5).
- A STOP that works from every client, to every robot, without a confirmation.

### 2.3 Non-goals (v1)

- Missions in words, a planner, an in-app agent (RFC-0004, later; an outside agent over MCP first).
- Robots collaborating on one goal (§3.9 keeps room; RFC-0002 §3.9 defers it to phase 6).
- History, comparison, plots, video: miniview's. Governance and approvals: flotilla's.
- Public exposure, several operators, accounts (§3.8).
- Driving the EV3 or the real duck (§3.6: nothing exists for the EV3).

## 3. Proposal

### 3.1 What Mission Control is

A standalone Python service (the language of `nxt-web` and miniview) with a web page, an API and an
MCP server over that API. It is the only thing that commands several robots; `nxt-web` still
drives one NXT on its own (O6); miniview still only shows (ADR-0005: the viewer does not send
commands). It holds the list of robots, their live state, the goals and their attempts.

```text
  page ─┐                         ┌─ adapter ─ simulated duck (navigator)
  MCP  ─┤                         ├─ adapter ─ fake robot (development)
  mobile┼─ Mission Control API ───┼─ adapter ─ NXT (nxt-web's API, later RFC-0003)
  agent ┘   robots, goals, events ├─ adapter ─ EV3 (later)
                  │               └─ adapter ─ real duck (later)
                  └─ writes runs (MCAP) ─ miniview /watch
```

### 3.2 API first

One remote API. The page, the MCP server, an outside agent and a later mobile app are clients of it
and have no private path. The MCP server exposes every resource and action below, not a subset
(O11); the STOP and its limits are the same for an agent as for the operator.

#### 3.2.1 Resources

| Resource | Meaning |
| --- | --- |
| `GET /api/v1/robots` | the robots: id, label, kind, `online`, `lock` (who holds it), last-seen age |
| `GET /api/v1/robots/{id}` | identity, `capabilities` (§3.3.2), `status` (battery, link, pose, mode, safety flags) |
| `POST /api/v1/robots/{id}/drive` | `{vx, vyaw}` with the deadman rules of §3.7; refused if a goal run holds the robot |
| `POST /api/v1/robots/{id}/stop` | stop this robot; always accepted |
| `POST /api/v1/stop` | stop every robot at once; always accepted |
| `GET /api/v1/robots/{id}/map` | the robot's map for drawing (§3.5), if its capabilities say it has one |
| `GET /api/v1/goals`, `POST /api/v1/goals` | goals (§3.4): list, define |
| `GET`, `PUT`, `DELETE /api/v1/goals/{id}` | read, change, retire one goal (never one that is running) |
| `POST /api/v1/goals/{id}/runs` | run it: body `{robot, target: "sim" \| "real"}`; creates a goal run |
| `GET /api/v1/goal-runs`, `GET /api/v1/goal-runs/{id}` | attempts of a goal: state, progress, outcome, run key |
| `POST /api/v1/goal-runs/{id}/cancel` | stop the run: the navigator stops, the robot is stopped |
| `GET /api/v1/events` | the live stream (§3.2.2) |

Errors are `{ok: false, error: {code, message}}` with an honest status code. A command to a robot
that is offline is an error, never a silent queue. Units are SI and frames are `map`/`odom`/
`base_link` as in the contract of miniview (`viewer/CONTRACT.md`).

#### 3.2.2 Transport: HTTP JSON and a live stream

- **Requests:** HTTP with JSON bodies. Every client we know speaks it: the browser, a phone app,
  `curl`, an MCP server's tool code, a shell script.
- **Live:** one server-sent-events stream, `GET /api/v1/events?since=<seq>` — robot state at a
  steady rate, `goal-run` changes, robot online and offline, locks, STOP. Each event carries a
  sequence number so a client that dropped can ask for what it missed. SSE is what miniview's live
  view already uses (requirements §4); not verified here against `viewer/CONTRACT.md` in detail.
- **Why not JSON-RPC to clients, as RFC-0003 does to robots:** the robot interface is a private,
  persistent, bidirectional line to one robot, where JSON-RPC's methods and subscriptions fit.
  Clients are many, include browsers and phones, and want cacheable reads, status codes and tools
  such as `curl`. The two layers differ on purpose; the adapters translate. Nothing prevents a
  JSON-RPC front door later if a client needs it.
- **Stability:** the path carries `v1`; a change that breaks a client is `v2`. Like miniview's
  contract, the API is written down in a `CONTRACT.md` beside the code, with the tests checking it.

### 3.3 Many robots from day one

#### 3.3.1 Identity and connections

A robot has an id (`duck-sim`, `nxt-1`), a label, a kind, and an adapter. The registry is a file
the operator edits (robot id, adapter, address); there is no discovery in v1. Each robot gets
**one connection, its own task, its own timeouts**: a slow or dropped robot is marked `online:
false` and stays that way until it answers; it never delays another robot. Commands to different
robots run concurrently. `online` is a measured fact (the last answer within a bound), not a flag
the adapter sets.

#### 3.3.2 Capabilities as data

Each adapter reports a `capabilities` object, and the page and the MCP tools offer only what is
there. Proposed fields (the first slice settles the schema and writes it in the contract):

| Field | Example |
| --- | --- |
| `drive` | `{max_vx, max_vyaw, deadman_s}`: speeds and the deadman the adapter enforces |
| `sensors` | `[{name, kind: "tof8x8" \| "ultrasonic" \| "colour" \| ..., frame}]` |
| `map` | `{kind: "occupancy_grid", resolution_m}` or absent |
| `navigator` | `{goal_kinds: ["point"], conditions: [...]}` or absent |
| `skills` | `["fire"]`, each marked `irreversible` where it is (RFC-0003 §2.3) |
| `description` | the robot's name in miniview's robot list (RFC-0011), for drawing it |

A sensor added to the NXT changes its adapter's description, not Mission Control's code (O10).
Today only the simulated duck has a map and a navigator (requirements §1); the NXT and the EV3
start with status, drive and STOP.

#### 3.3.3 One driver per robot, across apps

`nxt-web` still exists (C6), so two apps can reach the NXT. A per-robot **lock** with an owner and
a time: Mission Control takes it when it connects, shows who holds it, and refuses to drive or run a
goal while another holds it. STOP is the exception: it never needs the lock. How the lock is shared
with `nxt-web` is open (§5, question 3); the minimum is that Mission Control checks `nxt-web`'s
status before driving and says "NXT is driven by nxt-web".

### 3.4 Goals

#### 3.4.1 What a goal is

A goal is a point on a robot's map and its conditions, shaped like a challenge in ADR-0015, whose
vocabulary it reuses: **reach** (get there) or **refuse** (say why not before the time limit).
Proposed v1 shape:

```text
goal   { id, name, scene?, where {x, y, frame}, kind: "point",
         done_when {within_m: 0.25, within_s: 60},
         must_not  [ "contact", "drop", "stall", ... ],
         expect: "reach" | "refuse" }
```

`within_m` defaults to ADR-0015's `REACHED_M` (0.25 m). The conditions are checked by the
navigator's own report and, in the simulator, by truth (as the scenario runner's invariants are);
on a real robot only what the robot can measure is checked, and the goal run says which conditions
were and were not checkable. The v1 list of `must_not` conditions is the few the duck's navigator
already reports; which ones are fixed is for the first slice to settle against `duck_lab`.

Later goal kinds (not v1): "explore every room", survey, follow, hold a position. A goal kind is a
name plus a validated schema; an unknown kind is refused, as RFC-0004 §2.1 requires of mission
specs.

#### 3.4.2 Defined once, run anywhere

A goal is robot-independent. A **goal run** (an attempt) binds a goal to a robot and a target,
simulator or real, and records state: `queued → running → reached | refused | failed | cancelled |
interrupted`, progress (distance left, time used, conditions so far), and the reason on any end that
is not `reached`. Per RFC-0005 §2.1, a goal that has not run in the simulator is flagged on a real
run; Mission Control does not forbid it, since the operator is in the room (RFC-0002 §3.5).

#### 3.4.3 Where goals and runs are stored

- Goals and goal runs: a small embedded store in Mission Control's own state directory (SQLite is
  what miniview uses for its index, requirements §4 / `viewer/CONTRACT.md`; not verified for
  other uses). Goals are small and need a query by robot and by goal.
- The record of a run is not stored again: each goal run that moves a robot writes (or points at) a
  miniview run, key `robot/scene/run`, in MCAP
  ([ADR-0004](../adr/ADR-0004-runs-in-mcap-with-derived-index.md),
  [RFC-0010](RFC-0010-run-store-v2.md)); the goal run keeps that key, so `/watch/<key>` is one
  link. The duck's navigator already writes such runs with a `RunLog` (`Navigator.runlog`,
  `duck/src/duck_lab/nav/run.py`).
- Scenes: a goal may name a scene (`data/scenes/<scene>/`); for the simulator it is how the goal's
  world is loaded (ADR-0015 writes scenes the simulator loads from `DUCK_SIM_SCENE`).

#### 3.4.4 Relation to flotilla

Mission Control keeps goals and goal runs. When flotilla is connected, its policy and approvals
replace the simple "confirm" (RFC-0006 §2) and its freeze calls the same STOP; flotilla reads goals
and attempts through the API. Nothing in the goal's shape is flotilla's. The older ask, that goal
history lives in flotilla ([FLOTILLA-ASKS.md](../wip/FLOTILLA-ASKS.md)), is changed by C4; that file
is to be corrected when this RFC is accepted.

### 3.5 The map in the app

The page draws a robot's map itself and a goal is placed by a click on it. The data is the robot's
own: the occupancy grid (10 cm), the navigator's layers (obstacles, drops, gaps), the plan and the
believed pose, as miniview already streams them per run (`world.grid`, `world.obstacles`,
`world.drops`, `world.gaps`, `plan.path`, `belief.pose`; requirements §2.5). Mission Control serves
them through `GET /robots/{id}/map` and the event stream, in the robot's `map` frame.

What stays out: playback, the above/eye views, timelines, comparison. For those the page shows a
link, "Watch" (`/watch/<robot>/<scene>/<run>` or `.../latest`, `viewer/CONTRACT.md`), which opens
miniview's deep view. The map is a drawing for commanding; it is not a second miniview.

### 3.6 Robots in v1

| Robot | How | State today |
| --- | --- | --- |
| **Fake robot** | An in-process adapter that moves a point, answers status, honours STOP and the deadman, and can be told to drop offline. For developing the API, page and MCP with no simulator | New. Stream A owns the simulator until it hands over, so this is how Mission Control is built and tested without it |
| **Simulated duck** | A thin adapter over the navigator | `Navigator.go_to(goal, timeout_s)` returns `{"status": "refused", "why": ...}` or its result (`duck/src/duck_lab/nav/run.py`); it is Python and CLI only (`duck-go`, `duck-explore`), with **no API server** |
| **NXT** | Status, drive and STOP through `nxt-web`'s HTTP API (`GET /api/status`, `POST /api/drive`, `POST /api/stop`; `nxt/src/nxt_lab/web.py`); later the RFC-0003 JSON-RPC when its Python service exists | `nxt-web` exists; RFC-0003 is not built |
| **EV3** | Nothing exists: no driver, no deadman, no interface, only robot descriptions (requirements §6). It needs its own link (firmware and protocol differ from the NXT's), a deadman on the robot or in the adapter, an RFC-0003-shaped interface, its battery and link status, and a safety review before it is driven | Not designed |
| **Real duck** | The navigator on ssh-forwarded sockets (RFC-0002 §3.3), later on the robot | Not owned; untested |

**A navigator API does not exist; this RFC proposes one.** A small service beside the duck package
(`duck-nav-server`, or inside the adapter's process in the first slice) that owns one
`Navigator` and offers, in the process boundary Mission Control uses:
`goal.start {x, y, timeout_s, conditions}`,
`goal.status`, `goal.cancel`, `map`, `state`. Whether it is a separate process with the RFC-0003
JSON-RPC shape or a Python import inside the adapter is open (§5, question 4); the first slice may
import it, as long as the adapter's interface is the one a process boundary would use. It runs the
navigator in its own thread; `robot.stop` never goes through it (§3.7).

### 3.7 Safety

- **STOP goes straight to the robot** (`robot.stop`, or the NXT's `/api/stop`), never through a
  planner or a goal run (RFC-0002 §3.5). `POST /robots/{id}/stop` and `POST /stop` are accepted in
  every state, need no lock, no confirmation and no token beyond the tailnet, and stop all
  robots concurrently (a failing robot is reported, the others still stop). After a STOP the goal
  run is `cancelled` and the robot is not driven again until a client drives or runs a goal.
- **The deadman is the backstop.** Drive commands carry a lifetime; Mission Control stops sending
  them and the robot's own watchdog stops it: the duck's 500 ms (upstream), the NXT's 0.6 s in the
  web UI and robotd-lite on the brick (RFC-0001 §3.3, RFC-0003 §2.3). The page's STOP works with
  the API's connection to a robot gone, because the robot's deadman also fires; Mission Control
  shows a robot with no answer as offline and says that a STOP cannot be confirmed for it.
- **Situation rules** from RFC-0002 §3.6 (someone else drives, Wi-Fi drop, lost, fall, pick-up) are
  the navigator's: stop, mark the goal run `interrupted`, resume only when the operator says so.
- **Real-duck goals** need the operator in the room with a STOP at hand (RFC-0002 §3.5). Firing
  (the NXT shooter) is irreversible: always proposed, never automatic, and the API offers it only
  as an explicit call by the operator (RFC-0003 §2.3, RFC-0005 §2.3). An agent over MCP has the
  same STOP and the same limits; whether it may fire is open (§5, question 8).

### 3.8 Access

Tailnet only, one operator (operator, answer 4). The service listens on the workstation and its
tailnet address, never on a public interface; `nxt-web` and miniview are loopback-only with no
authentication today (requirements §2.6), so Mission Control is the first thing here that listens
on the tailnet, and RFC-0003 §4's open question (transport and authentication) is answered by this
for Mission Control only. In v1 the tailnet is the authentication. Per-client tokens come when the
mobile app or an agent gets its own access: a token names a client, so the event stream and the
goal-run records say who commanded, and a token can be revoked with STOP still open to all.
Slack comes later, on the API.

**Agent:** an outside agent through MCP first, with the same API and the same STOP as the operator
(answer 2). An agent in the app that takes words (RFC-0004's missions in words) comes later, on top
of the goals, and produces goals, not twists.

### 3.9 Swarm and collaboration: what v1 leaves room for

Nothing of collaboration is built (RFC-0002 §3.9, §4: phase 6; the requirements §6: not specified).
The v1 shape keeps these doors open:

- A goal run names **one robot** today; the field is a `robot` that may later be a `team`. The
  goal does not change.
- Robots are peers in one registry with capabilities, so assigning "the duck watches, the NXT
  drives" is choosing robots by capability, not by name.
- A **place** (a scene or a real room) can later own a shared map and a common frame; v1 has one
  `map` per robot and says so in each response (`frame`, `map_id`). Markers or a camera fixing the
  NXT in the duck's frame are RFC-0002 §3.9's open work.
- Events are per robot and carry a sequence number and a time, so a later layer can join them.

### 3.10 miniview

The operator will bring miniview feedback through this stream, and the fixes land in miniview (not
in Mission Control). miniview gets a new name, chosen as a partner to "Mission Control". Candidates
are in §5, question 1. Renaming touches the package, the Docker image, `/watch` links in the docs
and the RFC titles that say "miniview"; it is its own step (§4, step 7), not part of the first
slice, and the API path `/watch` stays what the contract says until then.

## 4. Order

Where the code lives: a new top-level directory `control/` beside `duck/`, `nxt/` and `viewer/`,
with `control/src/mission_control/` and its own tests, a `CONTRACT.md` for the API, a Makefile
target pair (`control-up`, `test-control`) like the others. Python, no new runtime dependency is
proposed here; the HTTP server and the SSE stream are written with the standard library as
`nxt-web` is (not verified: that the standard library suffices for SSE under concurrency; if it
does not, a framework would be a dependency to ask for, not assumed). A Docker image later, as
`nxt-web` and miniview have.

1. **A first slice that is useful.** The API contract (§3.2) and its tests; the fake robot; the
   registry; the page with the robot list (online, status, lock), a map for a robot that has one, a
   goal set by a click with its conditions, a goal run with its progress, a big STOP and STOP-all,
   and the link to `/watch`; the MCP server over the same API. Done when the operator can set a
   point goal on the fake robot's map from the page, from `curl` and from an MCP client, watch it
   reach, and STOP from all three.
2. **The navigator API and the simulated duck's adapter** (§3.6), once stream A hands over the
   simulator: a goal set on the page runs on the simulated duck and the attempt is a miniview run
   with a `/watch` link.
3. **The NXT's adapter** over `nxt-web`'s HTTP API: status, drive, STOP, the lock check (§3.3.3).
   Needs `nxt-web` running; the real-brick deadman check is pending (RFC-0003).
4. **Goal conditions and attempts, deepened:** the full list of conditions, the history of attempts
   per goal, comparing attempts, the simulator-first flag for real runs.
5. **Per-client tokens**, then the mobile app's needs, then Slack.
6. **EV3 and the real duck**, each after its own interface, deadman and safety review.
7. **The "explore every room" goal kind; collaboration** (RFC-0002 phase 6); the miniview rename;
   the in-app words agent (RFC-0004); the flotilla integration (RFC-0006 §5, item 4).

## 5. Open questions

Answered by the operator, 2026-11-17: miniview becomes **Observatory** (question 1); the navigator
API is **its own process** (question 4); the goal store is **SQLite** (question 5); an MCP agent
**may not fire** (question 8). Next: a mockup of the page, to shape it before building.
The robot file (agreed "for now", 2026-11-17): the body as URDF (RFC-0011); capabilities and the
connection in a small file of our own that borrows the VDA 5050 factsheet's fields and Open-RMF's
task kinds, so a bridge to either stays easy. The operator's long-term goal is better support for
VDA 5050-type robots, so the design leans toward VDA 5050 from the start: its terms where they fit
(factsheet, actions, state), and room for a VDA 5050 adapter. No single standard covers
capabilities; the specs themselves are to be read before the format is fixed.

Not folded in yet: the mockup's two review rounds (goals at the centre, the map one way to set a
goal, a goal library in folders, robots from config files, places and rooms instead of coordinates,
the LLM optional over an OpenAI-compatible API, one goal on several robots, the loop observed per
robot) — the operator is reviewing the mockup; this RFC is revised from that review.

1. **miniview's new name, a partner to "Mission Control".** Candidates: **Replay** (the viewer's
   job: watch a run again; plain, but one word); **Logbook** (RFC-0007 uses "logbook" for the run
   store, so it would blur the store and the viewer); **Flight Recorder** (what it keeps; long);
   **Observatory** (a place to look at what happened; pairs as control and observation);
   **Telemetry** (accurate, generic). Recommendation: **Observatory** — it reads as the partner of
   a control room, it does not collide with a term already used in the docs, and it covers both live
   and recorded views. The operator decides.
2. **Slack in the first version?** Answered: no, later (answer 3). Kept here only to record that
   RFC-0006 §6 question 3 (one Slack app or two) stays open.
3. **How the per-robot lock is shared with `nxt-web`.** Options: a lock file both honour; Mission
   Control asks `nxt-web` for its status first; `nxt-web` gains a "driven by" field. The minimum is
   the second.
4. **The navigator API:** a separate process with RFC-0003's JSON-RPC, or an import inside the
   adapter, for the first version.
5. **The goal store:** SQLite in Mission Control's state directory (§3.4.3), or goals as files in
   the lab's data folder next to scenes. The first is simpler to query; the second is what the lab
   already backs up and diffs.
6. **The first list of `must_not` conditions,** to be fixed against what the duck's navigator and
   the scenario runner's invariants can report (ADR-0015).
7. **The event stream's rate and the state's contents** per robot; settled in the first slice.
8. **May an MCP agent fire?** Proposed: not in v1; it can drive, run goals and STOP.
9. **Where it runs:** the workstation first (the brain's long-term place is open, RFC-0002 §5.5).
10. **Licence and splitting into its own repository** (RFC-0006 §6): unchanged; the operator's other
    projects use MIT.

## 6. Alternatives considered

- **Grow `nxt-web` into Mission Control** (RFC-0006's plan): rejected by the operator (O6). It would
  carry an NXT-shaped page and API into a many-robot app.
- **A JSON-RPC API for clients, like RFC-0003:** one protocol end to end. Rejected for clients:
  browsers, phones and `curl` get less from it than from HTTP; the adapters still speak JSON-RPC to
  robots. Revisitable (§3.2.2).
- **WebSocket instead of SSE:** two-way, but the commands already have HTTP and a second path for
  STOP is a second way to get it wrong; SSE is one direction and reconnects with a sequence number.
- **gRPC or MQTT:** a good fit for fleets, but a new dependency and a poor fit for `curl` and an
  MCP server; not needed for one operator on a tailnet.
- **A ROS 2 bridge as the API:** not now ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).
  Terms and shapes follow ROS, so a bridge is an adapter later.
- **Goals inside miniview:** miniview does not send commands (ADR-0005), and its job is to show.
- **Goals only in flotilla:** robot-specific code would pull flotilla toward one domain (RFC-0006
  §7), and the app has to work alone.
- **No fake robot; wait for the simulator:** blocks the API, the page and MCP on stream A.

## 7. Discussion

- 2026-11-17 — Operator, requirements gathered
  ([MISSION-CONTROL-REQUIREMENTS.md](../wip/MISSION-CONTROL-REQUIREMENTS.md)): a new app with
  robots, goals, a map of its own, a link to miniview, full MCP and a remote API, swarm in mind; the
  five answers of its section 5 (conditions from the start; an outside agent over MCP first; Slack
  later; tailnet only with one operator; the name Mission Control).
- 2026-11-17 — Draft of this RFC, for the operator's review. Not verified while writing: that the
  endpoints of `nxt-web` and miniview behave as documented when run; PRD-001, UXS-001, RFC-0010 and
  RFC-0012 were not read; flotilla's and eval-harness's repositories were not read.
