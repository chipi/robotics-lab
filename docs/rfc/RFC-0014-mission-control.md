# RFC-0014 — Mission Control: one API for every robot, goals in words, places and objects

**Status:** Proposed, revision 2 (2026-11-18), for the operator's review
**Builds on:** [RFC-0006](RFC-0006-mission-control.md) (the vision, superseded in part, §2.1),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0002](RFC-0002-robot-brain.md) §3.9 to §3.10 (several robots, the brain's API),
[RFC-0005](RFC-0005-missions.md) (missions), [RFC-0007](RFC-0007-platform.md) (the platform),
[RFC-0013](RFC-0013-robot-eye.md) and [RFC-0009](RFC-0009-miniview.md) (miniview, to be renamed the
Observatory), [ADR-0015](../adr/ADR-0015-scenario-runner.md) (goals as challenges),
[RFC-0016](https://github.com/chipi/robotics-lab/blob/explore-apartment/docs/rfc/RFC-0016-objects-and-semantic-map.md)
(objects and a semantic map; it lives on the branch `explore-apartment`, so this link is absolute
and becomes relative when that branch merges),
[ADR-0019](../adr/ADR-0019-semantic-map-records.md) (the `objects` and sighting records).
**Requirements:** [MISSION-CONTROL-REQUIREMENTS.md](../wip/MISSION-CONTROL-REQUIREMENTS.md)
(O1 to O12 are the operator's first round, 2026-11-17; O13 to O26 the second round and the decisions
of 2026-11-17/18; C1 to C8 the conflicts with earlier RFCs).

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

Revision 1 (2026-11-17) covered the first round of requirements: point goals on a map. Since then
the operator reviewed a mockup of the page and gave a second round: goals at the centre, in a
library, in words; places and rooms instead of coordinates, because "maps and coordinates make no
sense" to the operator as the way to give goals; one goal on several robots; the loop observed. And
on 2026-11-18 the duck learned to recognise objects and keep a semantic map (RFC-0016, ADR-0019),
which makes "go to the fridge" a real goal. The operator's decision, 2026-11-18: "A yes", revise
this RFC now with object, room, explore and inventory goals, recognisers among the robot's
capabilities, objects and rooms in the map and the API, and the second round folded in. This
revision does that.

### 1.1 Words used

| Word | Meaning here |
| --- | --- |
| home | one place robots live and work in: a flat, or the simulator's apartment. Has an id |
| home frame | the one coordinate frame of a home. In the simulator it is the dock: every run starts there |
| room | a named part of a home ("kitchen"). Today the duck names the room it is in from the objects near it; a room has no extent yet (§3.5.3) |
| place | something a goal can name instead of coordinates: a room or an object |
| object | anything in a home that a recogniser reports: furniture, a plant, a picture. Has a stable id, a kind, parts (boxes with a bottom and a top), a confidence, maybe a label |
| kind | what an object is ("fridge"). One catalogue for every home (`kinds.json`, RFC-0016) |
| label | the name the operator gives one object: "this is my desk" |
| landmark | an object whose landmark value is 0.7 or more (value 0 to 1: how distinctive and how well seen; the operator, 2026-11-18). A role an object plays, not a different thing |
| sighting | one record of what a camera saw at one moment: where the camera was, its field of view, the detections. The record ADR-0019 calls `look`; renamed `sighting` (the operator, 2026-11-18) |
| the Observatory | the viewer, now called miniview. Its package, CLI and Docker image keep the name `miniview` until the rename step (§4, step 12) |

## 2. Goals and non-goals

### 2.1 What this changes in earlier RFCs

| # | Earlier statement | After this RFC |
| --- | --- | --- |
| C1 | Mission control is grown from `nxt-web` (RFC-0006 §3, §3.1, §5, §7; RFC-0002 §3.10) | A new app. `nxt-web` stays the NXT's small playground and is not generalised. RFC-0006 §3.1 (the page), §5 (order) and §7 (the alternative "grow nxt-web") are superseded. STATUS.md, ROADMAP.md and ECOSYSTEM.md repeat the old line: not checked, to be corrected when this is accepted |
| C2 | Mission control draws no maps or history (RFC-0006 §3.3, RFC-0007 §6) | The map for commanding is Mission Control's. History, comparison and deep views stay in the Observatory |
| C3 | Links go to Foxglove (RFC-0006), then "the viewer" (RFC-0007) | The link goes to the Observatory's `/watch` |
| C4 | Goal and mission history belongs to flotilla and the logbook | Goals are defined, run and followed in Mission Control. flotilla, once connected, governs them (§3.4.7) |
| C5 | First interfaces: page, MCP, Slack (RFC-0006 §3.1) | Page, MCP and the remote API. Slack later (operator, answer 3) |
| C6 | One driver at a time (RFC-0003 §3, non-goal) | Holds per robot, now across apps: a lock (§3.3.3) |
| C7 | RFC-0004 puts missions in words and a planner later; RFC-0002 §3.9 defers robots collaborating on one goal to phase 6 | Both are requirements now (O14, O16). The planner is an independent, optional module (§3.4.5); a goal can name several robots (§3.4.4), built in steps |
| C8 | RFC-0016 §4 lists "objects in Mission Control (goals by object there, naming objects by hand)" as not in its first build | This RFC is where they are: object and room goals (§3.4.1), the home's map and naming (§3.5) |

What does not change: RFC-0006 §2 and §3.3's line (mission control commands and keeps safe, the
viewer shows and stores, eval-harness judges, flotilla governs), as amended by RFC-0007 §2; the
ROS-aligned terms ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)); RFC-0006 §3.2 and §4
(what it is not; the open-source product, whose name was chosen: Mission Control).

### 2.2 Goals

- One API that every client uses equally. Nothing works only in the page (O11, O12).
- Many robots from day one, one built first; one goal that names several robots (O8, O9, O10, O16).
- Goals at the centre (O13): a library in folders, ad-hoc runs that are not saved, the good ones
  saved; given as a point, a room, an object, an exploration, an inventory, or in words (O14, O15).
- Places and rooms in place of coordinates (O15): "go to the fridge", "explore the kitchen".
- A home's map of objects and rooms kept between runs, owned by Mission Control, with objects the
  operator can name (O26).
- A map in the app with goals set on it (O4); the loop observed while a goal runs (O17); a link to
  the Observatory for the deep view (O5, O19).
- A STOP that works from every client, to every robot, without a confirmation.

### 2.3 Non-goals

These stay out of the first versions. Robots collaborating on one goal, missions in words (an LLM)
and the EV3 and the real duck are no longer here: they are requirements, with their own steps
(§4).

- History, comparison, plots, video: the Observatory's. Governance and approvals: flotilla's.
- Public exposure, several operators, accounts (§3.9).
- Firing over MCP or from an agent: decided no (§3.8).
- An LLM as a required part. Every goal can be given without one (§3.4.5).
- Correcting a robot's position in a real home from landmarks: later (§3.5.4), not in the first
  versions.
- Room extents (regions): not here, waiting on the navigator (§3.5.3). Until then `go_to_room` and
  `explore {room}` are not offered.
- A detector on real video: the recogniser slot is in the capabilities, the detector is its own
  work (RFC-0016 §3).

## 3. Proposal

### 3.1 What Mission Control is

A standalone Python service (the language of `nxt-web` and miniview) with a web page, an API and an
MCP server over that API. It is the only thing that commands several robots; `nxt-web` still
drives one NXT on its own (O6); the Observatory still only shows (ADR-0005: the viewer does not send
commands). It holds the list of robots, their live state, the goals and their runs, and the
homes' semantic maps. Its store is SQLite (the operator, 2026-11-17).

Three processes, connected by APIs and not by shared code:

```text
  page ─┐                         ┌─ adapter ─ simulated duck ─ navigator API (own process)
  MCP  ─┤                         ├─ adapter ─ fake robot (development)
  mobile┼─ Mission Control API ───┼─ adapter ─ NXT (nxt-web's API, later RFC-0003)
  agent ┘   robots, goals, homes, ├─ adapter ─ EV3 (later)
  planner   events, SQLite        └─ adapter ─ real duck (later)
  (optional)      │
                  └─ run keys ─ the Observatory /watch/<key>  (reads the runs the navigator writes)
```

### 3.2 API first

One remote API. The page, the MCP server, an outside agent and a later mobile app are clients of it
and have no private path. The MCP server exposes every resource and action below, not a subset
(O11); the STOP and its limits are the same for an agent as for the operator, and an agent cannot
fire (§3.8).

#### 3.2.1 Resources

| Resource | Meaning |
| --- | --- |
| `GET /api/v1/robots` | the robots: id, label, kind, `online`, `lock` (who holds it), last-seen age |
| `GET /api/v1/robots/{id}` | identity, `capabilities` (§3.3.2), `status` (battery, link, pose, mode, safety flags) |
| `POST /api/v1/robots/{id}/drive` | `{vx, vyaw}` with the deadman rules of §3.8; refused if a goal run holds the robot |
| `POST /api/v1/robots/{id}/stop` | stop this robot; always accepted |
| `POST /api/v1/stop` | stop every robot at once; always accepted |
| `GET /api/v1/robots/{id}/map` | the robot's map for drawing (§3.6), if its capabilities say it has one |
| `GET /api/v1/robots/{id}/sighting` | the robot's latest sighting (the camera record, ADR-0019): where the camera was, its field of view, what it detected; if it has a recogniser |
| `GET /api/v1/goals?folder=`, `POST /api/v1/goals` | the goal library (§3.4.2): list (a folder, or all), define |
| `GET`, `PUT`, `DELETE /api/v1/goals/{id}` | read, change, retire one goal (never one that is running) |
| `POST /api/v1/goals/{id}/runs` | run a library goal: body `{robots \| team, target: "sim" \| "real"}`; creates a goal run |
| `POST /api/v1/goal-runs` | run a goal that is not in the library: body `{goal, robots \| team, target}`; creates a goal run, saves no goal |
| `POST /api/v1/goal-runs/{id}/save` | save the goal of that run into the library: `{name, folder}` |
| `GET /api/v1/goal-runs`, `GET /api/v1/goal-runs/{id}` | goal runs: state, progress, outcome, `result`, run key (§3.4.3) |
| `POST /api/v1/goal-runs/{id}/cancel` | stop the run: the navigator stops, the robot is stopped |
| `POST /api/v1/plan` | words in, goals out (§3.4.5): `{text}`; returns proposed goals, runs nothing |
| `GET /api/v1/homes`, `GET /api/v1/homes/{h}` | the homes: id, label, the home frame, counts |
| `GET /api/v1/homes/{h}/objects` | the home's objects (§3.5): stable id, kind, label, parts, confidence |
| `POST /api/v1/homes/{h}/objects/{id}/label` | name an object: `{label}` ("this is my desk"); the MCP tool is the same call |
| `GET /api/v1/homes/{h}/rooms` | the rooms: name, the objects that vote for it (no extent yet, §3.5.3) |
| `GET /api/v1/homes/{h}/inventory` | the confirmed objects by room, with sightings and confidence |
| `GET /api/v1/events` | the live stream (§3.2.2) |

Errors are `{ok: false, error: {code, message}}` with an honest status code. A command to a robot
that is offline is an error, never a silent queue. A goal refused for a robot says why, in a field
a client can show (§3.3.2, the rule). Units are SI and frames are `map`/`odom`/`base_link` as in the
contract of miniview (`viewer/CONTRACT.md`), plus the home frame (§3.5.1); every response that
carries a position names its `frame`.

#### 3.2.2 Transport: HTTP JSON and a live stream

- **Requests:** HTTP with JSON bodies. Every client we know speaks it: the browser, a phone app,
  `curl`, an MCP server's tool code, a shell script.
- **Live:** one server-sent-events stream, `GET /api/v1/events?since=<seq>` — robot state at a
  steady rate, `goal-run` changes, the navigator's decisions with their reasons (§3.11), robot
  online and offline, locks, STOP, objects named. Each event carries a sequence number so a client
  that dropped can ask for what it missed. SSE is what miniview's live view already uses
  (requirements §4); not verified here against `viewer/CONTRACT.md` in detail.
- **Why not JSON-RPC to clients, as RFC-0003 does to robots:** the robot interface is a private,
  persistent, bidirectional line to one robot, where JSON-RPC's methods and subscriptions fit.
  Clients are many, include browsers and phones, and want cacheable reads, status codes and tools
  such as `curl`. The two layers differ on purpose; the adapters translate. Nothing prevents a
  JSON-RPC front door later if a client needs it.
- **Stability:** the path carries `v1`; a change that breaks a client is `v2`. Like miniview's
  contract, the API is written down in a `CONTRACT.md` beside the code, with the tests checking it.

### 3.3 Many robots from day one

#### 3.3.1 Identity, connections and robot files

A robot has an id (`duck-sim`, `nxt-1`), a label, a kind, and an adapter. Robots are configured by
files (the operator, 2026-11-17): the body as a URDF (RFC-0011) and a small file of our own with the
connection, the capabilities (§3.3.2) and the robot's task kinds, which borrows the field names of
the VDA 5050 factsheet and of Open-RMF's task kinds, so a bridge to either stays easy (§3.12). The
file's format is not fixed here: the specs themselves are to be read first (§5, question 21). There
is no discovery in v1; the registry is the set of files the operator edits.

Each robot gets **one connection, its own task, its own timeouts**: a slow or dropped robot is
marked `online: false` and stays that way until it answers; it never delays another robot. Commands
to different robots run concurrently (O9). `online` is a measured fact (the last answer within a
bound), not a flag the adapter sets.

#### 3.3.2 Capabilities as data

Each adapter reports a `capabilities` object, and the page and the MCP tools offer only what is
there. Proposed fields (the first slice settles the schema and writes it in the contract):

| Field | Example |
| --- | --- |
| `drive` | `{max_vx, max_vyaw, deadman_s}`: speeds and the deadman the adapter enforces |
| `sensors` | `[{name, kind: "tof8x8" \| "ultrasonic" \| "colour" \| ..., frame}]` |
| `recognisers` | `[{name, kinds, frame}]`: what can say "that is a fridge": a camera (simulated now, a video detector later), the kinds it knows (from the catalogue), the frame its detections are in. Absent or empty on a robot that has none; the NXT and the EV3 may have none |
| `localisation` | `{frame: "home" \| "run", how: "dock" \| "landmarks" \| ...}`: whether the robot's positions are in the home frame, and how it knows. The simulated duck: home, by the dock |
| `map` | `{kind: "occupancy_grid", resolution_m}` or absent |
| `navigator` | `{goal_kinds: ["point", "go_to_object", ...], conditions: [...]}` or absent |
| `skills` | `["fire"]`, each marked `irreversible` where it is (RFC-0003 §2.3) |
| `description` | the robot's name in the Observatory's robot list (RFC-0011), for drawing it |

A sensor added to the NXT changes its robot file, not Mission Control's code (O10: "I will boost
lego robots with better sensors as I go"). Today only the simulated duck has a map, a navigator and
a (simulated) recogniser (requirements §1); the NXT and the EV3 start with status, drive and STOP.

**The rule for object and room goals.** A goal that names an object or a room (§3.4.1) is accepted
for a robot only if it has a navigator **and** either its own recogniser (it finds the object
itself) or a shared home map it can localise in (`localisation.frame: "home"`, so it can go to a
place another robot or an earlier run found). Otherwise it is refused, with the reason: "no
recogniser and not localised in the home frame". The same rule decides which robots of a team can
take part (§3.4.4).

#### 3.3.3 One driver per robot, across apps

`nxt-web` still exists (C6), so two apps can reach the NXT. A per-robot **lock** with an owner and
a time: Mission Control takes it when it connects, shows who holds it, and refuses to drive or run a
goal while another holds it. STOP is the exception: it never needs the lock. How the lock is shared
with `nxt-web` is open (§5, question 3); the minimum is that Mission Control checks `nxt-web`'s
status before driving and says "NXT is driven by nxt-web".

### 3.4 Goals

Goals are at the centre of the app (O13): you define them, keep them, run them on one robot or
several, and watch what happens.

#### 3.4.1 Goal kinds

A goal has a kind, a place or thing it is about, and conditions, shaped like a challenge in
ADR-0015, whose vocabulary it reuses: **reach** (get there) or **refuse** (say why not before the
time limit). A kind is a name plus a validated schema; an unknown kind is refused, as RFC-0004 §2.1
requires of mission specs.

| Kind | Parameters | done_when | Needs |
| --- | --- | --- | --- |
| `point` | `{x, y, frame}` | within 0.25 m (ADR-0015's `REACHED_M`) within 60 s | navigator |
| `go_to_object` | `{kind \| id \| label, room?}` | the robot stands within 0.35 m of the object's outline and faces it within 45 degrees (the judge of RFC-0016), within the budget | navigator; recogniser or a shared home map (§3.3.2) |
| `go_to_room` | `{room}` | the robot is inside the room | navigator, room regions (not yet, §3.5.3) |
| `explore` | `{room \| home}`, budget in minutes | no reachable frontier left in the area | navigator, map |
| `inventory` | `{rooms?}`, budget | the inventory is returned: the confirmed objects by room | navigator, recogniser |
| `find_all` | `{kind \| label}`, budget | the area has no frontier left, or the budget is spent; every object of that kind found is returned | navigator, recogniser |

How an object is picked, for `go_to_object`: a `label` is the operator's name and wins; an `id` is
exact; a `kind` takes the nearest confirmed object of that kind in the home's map; `room` narrows
the choice to that room. If the home's map has no such object, the navigator explores until it
confirms one (`duck-explore --find` in RFC-0016) or the budget is spent. The robot goes to the
approach pose the navigator computes (a place to stand 0.25 m off the outline with room to turn),
then turns to face it.

`find_all` is my reading of the operator's list ("find_all"): `inventory` answers "what is where",
`find_all` answers "every fridge". The operator may have meant the same thing as `inventory`
(§5, question 12).

Common fields: `name`, `folder`, `scene?` (how the simulator's world is loaded, ADR-0015), a
`budget {minutes}` for exploring kinds, `must_not` (`["contact", "drop", "stall", ...]`) and
`expect: "reach" | "refuse"`. The conditions are checked by the navigator's own report and, in the
simulator, by truth (as the scenario runner's invariants are); on a real robot only what the robot
can measure is checked, and the goal run says which conditions were and were not checkable. The v1
list of `must_not` is the few the duck's navigator already reports (§5, question 6).

```text
goal   { id, name, folder, kind: "go_to_object",
         params {kind: "fridge", room?: "kitchen"},
         done_when {within_m: 0.35, facing_deg: 45, within_s: 300},
         must_not  [ "contact", "drop" ], expect: "reach" }
```

#### 3.4.2 The goal library, and runs that are not saved

- **A library in folders.** Goals have a `folder` path ("kitchen/", "tests/course"). The page shows
  folders; `GET /goals?folder=` lists them. The folders are a column in SQLite, not directories;
  whether they should also be files in the lab's data folder, to diff and back up, is open (§5,
  question 23).
- **Ad-hoc runs.** `POST /goal-runs` runs a goal given in the request. Nothing is saved but the goal
  run (its goal is copied into the run, so the run is readable alone).
- **Saving the good ones.** `POST /goal-runs/{id}/save {name, folder}` puts the run's goal in the
  library. A goal run whose goal was saved keeps the link.
- **Defined once, run anywhere.** A goal does not name a robot. A goal run binds a goal to robots
  and a target, simulator or real. Per RFC-0005 §2.1, a goal that has not run in the simulator is
  flagged on a real run; Mission Control does not forbid it, since the operator is in the room
  (RFC-0002 §3.5).

#### 3.4.3 Goal runs: states, outcomes, results

A goal run (an attempt) records its state: `queued → running → reached | refused | failed |
not_found | cancelled | interrupted`, progress (distance left, time used, conditions so far, the
room it believes it is in), and the reason on any end that is not `reached`.

`not_found` is new: an object or find goal whose budget was spent, or which has no frontier left to
explore, without finding what it was asked to find. It is different from `refused` (the goal could
not start, or the planner said no path) and from `failed` (the robot tried and a condition broke).

The run also carries a `result`, which depends on the kind:

| Kind | `result` |
| --- | --- |
| `go_to_object` | the object found (id, kind, label, position in the home frame) and the stand pose the robot reached (`{x, y, yaw, frame}`) |
| `find_all` | the list of objects found |
| `inventory` | the inventory: objects by room, with sightings, confidence, recognisers and evidence (RFC-0016's `inventory.json`) |
| `explore` | the area covered: counts of cells explored and objects found |
| `point`, `go_to_room` | none |

At goal start the navigator returns the **run key** (`robot/scene/run`), so the goal run binds at
once to the Observatory's `/watch/<key>`, live, before the run ends (§3.7).

#### 3.4.4 One goal on several robots

A goal run names `robots: [ids]` or a `team` (a named set of robots in the registry). The goal
does not change. What several robots do with it is open (§5, question 11); this is the proposal:

- **`share: "each"`:** every robot does the whole goal, independently, and the goal run holds one
  result per robot. This needs nothing new: it is parallel goal runs under one parent. It is the
  first to build.
- **`share: "any"`:** the first robot to reach the goal ends it; the others are cancelled and
  stopped. Also only parallel runs plus a rule.
- **`share: "split"`:** the goal's area is divided between robots (two robots exploring the home,
  the NXT driving to where the duck found the fridge). It needs a shared home map and frame (§3.5),
  a division of frontiers, and for the LEGO robots a way to be localised in the home frame. This is
  RFC-0002 §3.9's phase 6, later.

A robot that cannot take part (§3.3.2: no navigator, or no recogniser and not localised) is left
out of the run with its reason, or the run is refused if none can. That is how the duck, the NXT and
the EV3 collaborate (O10): by capability, not by name; the duck with a camera finds the object and
writes it to the home's map, a LEGO robot localised in the home frame can go to it.

#### 3.4.5 Goals in words, and an optional planner

The operator describes a goal in words; a planner may break the words into goals (O14). Rules:

- **The planner is an independent module** with one function: `plan(text, context) → goal specs`,
  where `context` is what the robots can do (capabilities) and the home's objects and rooms. It is
  a package of its own that Mission Control calls through `POST /plan`; it can run as its own
  process, and no part of Mission Control imports a model client.
- **An LLM is one way to plan, never required.** Every goal can be defined by hand, from the
  library, or by an outside agent over MCP. With no planner configured, `POST /plan` answers that
  there is none, and everything else works.
- **OpenAI-compatible API.** The module speaks that protocol to a base URL, a model name and a key
  read from a file or the environment. Default: LiteLLM on the DGX (the gateway; the address is
  configuration, not code). An OpenRouter key works the same way by changing the base URL.
- **The output is data, not action.** The planner returns goal specs. Each is validated against the
  goal kinds (§3.4.1), an unknown kind is dropped, the result is read back to the operator, and
  nothing runs until the operator confirms it (RFC-0004 §2.1). The planner has no path to `drive`,
  `stop` or `fire`; STOP is unaffected.
- A phrase matcher with no model for the simplest goals ("go to the fridge") is possible and is an
  open question (§5, question 16).

#### 3.4.6 Where goals and runs are stored

- Goals, goal runs and the homes (§3.5) are in **SQLite** in Mission Control's own state
  directory (the operator, 2026-11-17). Goals are small and need queries by folder, robot and goal.
- The record of a run is not stored again: each goal run that moves a robot writes (or points at) an
  Observatory run, key `robot/scene/run`, in MCAP
  ([ADR-0004](../adr/ADR-0004-runs-in-mcap-with-derived-index.md),
  [RFC-0010](RFC-0010-run-store-v2.md)); the goal run keeps that key, so `/watch/<key>` is one
  link. The duck's navigator already writes such runs with a `RunLog` (`Navigator.runlog`,
  `duck/src/duck_lab/nav/run.py`).
- Scenes: a goal may name a scene (`data/scenes/<scene>/`); for the simulator it is how the goal's
  world is loaded (ADR-0015 writes scenes the simulator loads from `DUCK_SIM_SCENE`).

#### 3.4.7 Relation to flotilla

Mission Control keeps goals and goal runs. When flotilla is connected, its policy and approvals
replace the simple "confirm" (RFC-0006 §2) and its freeze calls the same STOP; flotilla reads goals
and attempts through the API. Nothing in the goal's shape is flotilla's. The older ask, that goal
history lives in flotilla ([FLOTILLA-ASKS.md](../wip/FLOTILLA-ASKS.md)), is changed by C4; that file
is to be corrected when this RFC is accepted.

### 3.5 Homes, rooms and objects

The operator wants goals as places: "go to the fridge", "explore the kitchen". For that, something
has to remember where the fridge is between runs. Decided 2026-11-18 ("B yes"): a home's semantic
map is kept between runs, anchored to the dock, with stable object ids and labels from the
operator, and **the stored map is owned by Mission Control**.

#### 3.5.1 The home and its frame

A **home** has an id (`apartment`, the simulator's flat; a real home later) and a **home frame**.
In the simulator the home frame is the dock: every run starts there, so a run's `map` frame is the
home frame (Mission Control records the dock pose it assumed). A run's objects, in its own map
frame, are therefore already in the home frame. In a real home that is true only if the robot
starts at the dock (§3.5.4).

#### 3.5.2 The map Mission Control keeps, and naming

- **What is stored** (SQLite, per home): objects with a **stable id**, a kind, parts (boxes in plan
  and height, ADR-0019's shape), the position, `confirmed`, the landmark value, the permanence,
  `confidence`, first and last time seen, the robots and recognisers that saw it, a few pieces of
  evidence, and the **label** the operator gave. Rooms as names with the objects that vote for them.
- **Stable ids are Mission Control's.** The navigator's ids belong to one run and are not assumed to
  be the same in the next. When a run ends (or while it runs, from the stream), Mission Control
  merges the run's objects into the home's: an object of a *unique* kind (a home has one fridge,
  RFC-0016 §6) within 1.5 m of a known one is the same object; others by kind and distance; a new
  one gets a new id. A label stays with the id. How movable things that moved, and objects no longer
  seen, are merged or forgotten is open (§5, question 15).
- **Naming by hand.** `POST /homes/{h}/objects/{id}/label {label}`, and the MCP tool of the same
  meaning: the operator picks an object on the map (or an agent names one) and says "this is my
  desk". The label joins the object, shows in the map and the inventory, and works in goals
  (`go_to_object {label: "my desk"}`). A thing no recogniser knows is still an obstacle by its
  shape and can be named; naming it adds a label, and RFC-0016 §3 notes it can add a kind later.
- **The robot's map and the home's map.** The navigator keeps its own semantic map for a run
  (RFC-0016). Mission Control seeds a run with the home's objects when the robot is localised in
  the home frame (§3.3.2), so "go to the fridge" is a plan, not a search; the run's confirmed
  objects flow back. The seeding message is part of the navigator API (§3.7).

#### 3.5.3 Rooms

Today the duck names the room it is in from the confirmed objects near it (a fridge votes kitchen),
and the scoreboard compares it with the truth. A room has **no extent**: there is no region
anywhere that says where the kitchen is. So `GET /homes/{h}/rooms` returns names and the objects
voting for each, and the inventory sorts objects by the room their own place votes for. `go_to_room`
and `explore {room}` wait on room regions (§5, question 19); `explore {home}`, `inventory`, and the
object goals do not. A room goal given today is refused with "rooms have no extent yet".

#### 3.5.4 A real home: knowing where it is

In a real home the robot is not always at the dock, and a run's frame starts wherever it started.
Before it can use the home's map, it must first recognise where it is: landmark position
correction (objects with a landmark value of 0.7 or more re-seen, matched against the home's map,
give a transform into the home frame). That is later work (RFC-0016 §4 leaves loop closure out of
its first build). Until then, `localisation.frame` is `home` only for runs that start at the dock;
elsewhere it is `run` and the rule in §3.3.2 applies: no shared home map for that robot.

### 3.6 The map in the app

The page draws a robot's map itself and a goal is placed by a click on it, or, better, by naming
a place: picking an object or a room on the map (O15). The data is the robot's own: the occupancy
grid (10 cm), the navigator's layers (obstacles, drops, gaps), the plan and the believed pose, as
the Observatory already streams them per run (`world.grid`, `world.obstacles`, `world.drops`,
`world.gaps`, `plan.path`, `belief.pose`; requirements §2.5). Mission Control serves them through
`GET /robots/{id}/map` and the event stream, in the robot's `map` frame.

Two layers are new:

- **An objects layer**, in the shape of ADR-0019's `objects` record: each object's parts in the map
  frame (`[x, y, hx, hy, yaw, z0, z1]`), `confirmed`, `landmark` (a landmark when the value is 0.7
  or more), `confidence`, kind, and the operator's label. A confirmed object is drawn solid, an
  unconfirmed one faint, a landmark in its own colour, as ADR-0019 does for the pages. For a home
  (`GET /homes/{h}/objects`) the frame is the home frame.
- **A rooms layer**: room names placed at the centre of the objects that vote for them, until rooms
  have extents.

Mission Control draws its own map: it does not embed the Observatory's page. Whether it shares the
Observatory's drawing module or duplicates a small 2D drawing is **open** (§5, question 14). The
proposal is to duplicate a flat top-down drawing in the first slice, because the Observatory's
module is made for its 3D scene and not read for this RFC, and to share the code later if the two
drift.

What stays out: playback, the above/eye views, timelines, comparison. For those the page shows a
link, "Watch" (`/watch/<key>` or `.../latest`, `viewer/CONTRACT.md`), which opens the Observatory's
deep view. The map is a drawing for commanding; it is not a second Observatory.

### 3.7 Robots in v1, and the navigator API

| Robot | How | State today |
| --- | --- | --- |
| **Fake robot** | An in-process adapter that moves a point, answers status, honours STOP and the deadman, can be told to drop offline, and carries a fake home with a few objects, so the objects layer, naming and the library are built with no simulator | New. Stream A owns the simulator until it hands over, so this is how Mission Control is built and tested without it |
| **Simulated duck** | A thin adapter over the navigator API (below); its recogniser is the simulated camera | `Navigator.go_to(goal, timeout_s)` returns `{"status": "refused", "why": ...}` or its result (`duck/src/duck_lab/nav/run.py`); it is Python and CLI only (`duck-go`, `duck-explore`, with `--find` and `--inventory` on the `explore-apartment` branch), with **no API server** |
| **NXT** | Status, drive and STOP through `nxt-web`'s HTTP API (`GET /api/status`, `POST /api/drive`, `POST /api/stop`; `nxt/src/nxt_lab/web.py`); later the RFC-0003 JSON-RPC when its Python service exists. No recogniser today | `nxt-web` exists; RFC-0003 is not built |
| **EV3** | Nothing exists: no driver, no deadman, no interface, only robot descriptions (requirements §6). It needs its own link (firmware and protocol differ from the NXT's), a deadman on the robot or in the adapter, an RFC-0003-shaped interface, its battery and link status, and a safety review before it is driven | Not designed; arriving in days |
| **Real duck** | The navigator on ssh-forwarded sockets (RFC-0002 §3.3), later on the robot | Not owned; untested |

**A navigator API does not exist; this RFC proposes one, as its own process** (the operator,
2026-11-17). A small service beside the duck package (`duck-nav-server`) that owns one `Navigator`
and offers to Mission Control, over a process boundary, in the RFC-0003 JSON-RPC shape:

| Method | Meaning |
| --- | --- |
| `goal.start {kind, params, budget, conditions, seed?}` | starts a goal of any kind of §3.4.1 and returns `{run_key}` at once, so the goal run binds to the Observatory's `/watch/<run_key>` while it runs. `seed` is the home's objects (§3.5.2) |
| `goal.status`, `goal.cancel` | the run's state, progress and, at the end, its outcome and `result`; cancel stops it |
| `objects` | the navigator's current semantic map (ADR-0019's `objects` shape) |
| `rooms` | the room it believes it is in and the votes; the rooms it has named |
| `inventory` | the confirmed objects by room (RFC-0016's `inventory.json`) |
| `find {kind \| label}` | the nearest confirmed object of that kind, or the labelled one; null if none is known |
| `name_object {id, label}` | name an object in the navigator's map (Mission Control also keeps the label in the home's map) |
| `map`, `state`, `sighting` | the map layers, the robot's state, the latest sighting |

It runs the navigator in its own thread; `robot.stop` never goes through it (§3.8). The method
shapes are proposed; the first slice for the duck settles them and writes them in the contract. A
goal kind the navigator does not list in `capabilities.navigator.goal_kinds` is refused at the
adapter.

### 3.8 Safety

- **STOP goes straight to the robot** (`robot.stop`, or the NXT's `/api/stop`), never through a
  planner, an LLM or a goal run (RFC-0002 §3.5). `POST /robots/{id}/stop` and `POST /stop` are
  accepted in every state, need no lock, no confirmation and no token beyond the tailnet, and stop
  all robots concurrently (a failing robot is reported, the others still stop). After a STOP the
  goal run is `cancelled` and the robot is not driven again until a client drives or runs a goal.
- **The deadman is the backstop.** Drive commands carry a lifetime; Mission Control stops sending
  them and the robot's own watchdog stops it: the duck's 500 ms (upstream), the NXT's 0.6 s in the
  web UI and robotd-lite on the brick (RFC-0001 §3.3, RFC-0003 §2.3). The page's STOP works with
  the API's connection to a robot gone, because the robot's deadman also fires; Mission Control
  shows a robot with no answer as offline and says that a STOP cannot be confirmed for it.
- **Situation rules** from RFC-0002 §3.6 (someone else drives, Wi-Fi drop, lost, fall, pick-up) are
  the navigator's: stop, mark the goal run `interrupted`, resume only when the operator says so.
- **Real-duck goals** need the operator in the room with a STOP at hand (RFC-0002 §3.5).
- **Firing** (the NXT shooter) is irreversible: always proposed, never automatic, and the API offers
  it only as an explicit call by the operator (RFC-0003 §2.3, RFC-0005 §2.3). **An agent over MCP may
  not fire** (the operator, 2026-11-17: decided). It can drive, run goals and STOP, with the same
  limits as the operator. The planner (§3.4.5) has no `fire` either.

### 3.9 Access

Tailnet only, one operator (operator, answer 4). The service listens on the workstation and its
tailnet address, never on a public interface; `nxt-web` and miniview are loopback-only with no
authentication today (requirements §2.6), so Mission Control is the first thing here that listens
on the tailnet, and RFC-0003 §4's open question (transport and authentication) is answered by this
for Mission Control only. In v1 the tailnet is the authentication. Per-client tokens come when the
mobile app or an agent gets its own access: a token names a client, so the event stream and the
goal-run records say who commanded, and a token can be revoked with STOP still open to all.
Slack comes later, on the API.

**Agent:** an outside agent through MCP first, with the same API and the same STOP as the operator
(answer 2), "control through an agent" (O12). The in-app words planner (§3.4.5) is a separate, later
module on top of the goals, and produces goals, not twists.

### 3.10 Swarm and collaboration

Revision 1 left only doors open here. The operator wants collaboration from the start (O8, O10,
O16), so this revision builds toward it in steps (§4):

- A goal run names robots or a team (§3.4.4). `each` and `any` are parallel goal runs under one
  parent and come first; `split` needs more.
- Robots are peers in one registry with capabilities, so "the duck finds it, the NXT goes to it" is
  choosing robots by capability (§3.3.2), not by name.
- A **home** owns the shared map and the common frame (§3.5). Today that is the dock, and only for a
  robot that starts there. A LEGO robot is placed in the home frame by a marker or a camera fixing
  it in the duck's frame, which is RFC-0002 §3.9's open work.
- Events are per robot and carry a sequence number and a time, so a layer can join them.
- Parallel communication is the connection model of §3.3.1: one connection and one task per robot.

### 3.11 The Observatory, and the loop observed

Mission Control and the Observatory (miniview, renamed) stay two apps, separate and well connected
(O19). Separate: the Observatory shows and stores and never sends a command (ADR-0005); Mission
Control commands. Connected:

1. **The run key at goal start** (§3.7): a goal run holds the key, and the page offers "Watch" at
   once, live.
2. **A per-robot link**, `/watch/<robot>/<scene>/latest`, for a robot with no goal running.
3. **The same records.** The navigator writes `objects` and the sighting records (ADR-0019), which
   the Observatory draws in its 3D scene, eye panel and video; Mission Control reads the same
   shapes through the navigator API, so one object has one meaning in both.
4. **A link back:** an Observatory run could carry the goal run id and name so its page shows "goal
   run 42, go_to_object fridge". That needs a field in the run's metadata (§5, question 20).
5. **Names.** Until the rename step the package, the CLI and the Docker image are `miniview`; the
   docs and the page say "the Observatory".

**Observing the loop** (O17): while a goal runs, the operator sees what the robot decides and why.
The navigator already writes its decisions as events with a reason (ADR-0014; the explorer's `pick`,
`leg`, `trapped`, `no_frontier_left`). Mission Control's event stream relays them per goal run, and
the page lists them under the run: "picked a frontier at (3.1, 0.4)", "no frontier left". The deep
view of the same data, with the map at each moment and the thinking panel, is the Observatory's.
How much of the loop appears in Mission Control's page is open (§5, question 24).

### 3.12 VDA 5050 and Open-RMF

The operator's long-term goal is better support for VDA 5050-type robots, so the design leans
toward VDA 5050 from the start: its terms where they fit (factsheet, actions, state), and room for
a VDA 5050 adapter. No single standard covers capabilities. **This table is unverified: the specs
have not been read; it is from memory and is to be checked before the robot file's format is
fixed** (§5, question 21).

| Mission Control | VDA 5050 | Open-RMF |
| --- | --- | --- |
| robot file: capabilities, connection | the factsheet (type, physical parameters, protocol features, supported actions) | fleet configuration: the fleet adapter's settings |
| robot online | the connection topic (online, offline, connection broken) | fleet state |
| `point` goal | an order with one node: a position with a map id | `go_to_place` to a place on the nav graph |
| `go_to_object`, "go to the fridge" | resolved by Mission Control to an approach pose, then an order with one node; works if the home frame is the VDA `mapId` | `go_to_place` where objects and rooms are named places on the graph |
| `go_to_room` | a node at a point inside the room | `go_to_place` with the room's name |
| patrol (several places) | an order with several nodes | `patrol`: visit places |
| `explore`, `inventory`, `find_all` | custom actions declared in the factsheet's supported actions | custom task kinds |
| goal run state | the state message: order, node and action states, errors, battery, operating mode | task state |
| progress and decisions | the state's action states, plus Mission Control's own events | task logs |
| STOP | goes straight to the robot first; the VDA instant action for stop or pause is a second path, not the first | not used; the same rule |
| a team goal | one order per robot | task assignment by the fleet adapter |
| the home's objects and rooms | named places that Mission Control resolves before ordering | places on the nav graph |

If this holds, a VDA 5050 robot joins by an adapter that reads its factsheet into `capabilities`
and turns a goal into orders; the object and room goals work for it because Mission Control, not
the robot, resolves places to poses.

## 4. Order

Where the code lives: a new top-level directory `control/` beside `duck/`, `nxt/` and `viewer/`,
with `control/src/mission_control/` and its own tests, a `CONTRACT.md` for the API, a Makefile
target pair (`control-up`, `test-control`) like the others. Python, no new runtime dependency is
proposed here; SQLite comes with the standard library; the HTTP server and the SSE stream are
written with the standard library as `nxt-web` is (not verified: that the standard library suffices
for SSE under concurrency; if it does not, a framework would be a dependency to ask for, not
assumed). A Docker image later, as `nxt-web` and miniview have.

0. **Read the VDA 5050 and Open-RMF specs**, then fix the robot file's format (§3.3.1, §3.12).
1. **A first slice that is useful.** The API contract (§3.2) and its tests; the fake robot with its
   fake home; the registry from robot files; the page with the robot list (online, status, lock), a
   map for a robot that has one, the goal library with folders and ad-hoc runs, a point goal set by
   a click with its conditions, a goal run with its progress, a big STOP and STOP-all, and the link
   to `/watch`; the MCP server over the same API. Done when the operator can set a point goal on the
   fake robot's map from the page, from `curl` and from an MCP client, watch it reach, and STOP from
   all three.
2. **The navigator API (its own process) and the simulated duck's adapter** (§3.7), once stream A
   hands over the simulator: a goal set on the page runs on the simulated duck and the goal run
   binds to a `/watch` link from its first moment.
3. **Homes, objects and the object goals:** the home store in SQLite, merging a run's objects into
   it with stable ids, `objects`, `rooms`, `inventory`, naming by hand, `go_to_object`, `explore
   {home}`, `inventory`, `find_all`, the `not_found` outcome and the `result`; the objects and rooms
   layers on the map. Built first against the fake home, then the duck.
4. **The NXT's adapter** over `nxt-web`'s HTTP API: status, drive, STOP, the lock check (§3.3.3).
   Needs `nxt-web` running; the real-brick deadman check is pending (RFC-0003).
5. **Goals with several robots:** `each` and `any`; goal conditions and runs deepened; comparing
   attempts; the simulator-first flag for real runs.
6. **The planner module and the LLM** (§3.4.5): `POST /plan`, an OpenAI-compatible client, read-back
   and confirm.
7. **Per-client tokens**, then the mobile app's needs, then Slack.
8. **EV3 and the real duck**, each after its own interface, deadman and safety review.
9. **Room regions** from the navigator, then `go_to_room` and `explore {room}`.
10. **Relocalisation in a real home** from landmarks (§3.5.4); `split` of one goal across robots.
11. **A real video recogniser** in a robot's capabilities.
12. **The Observatory rename**, and the flotilla integration (RFC-0006 §5, item 4).

## 5. Open questions

Answered by the operator, 2026-11-17: miniview becomes **Observatory** (question 1); the navigator
API is **its own process** (question 4); the goal store is **SQLite** (question 5); an MCP agent
**may not fire** (question 8). Answered 2026-11-18: **A** revise now with object, room, explore and
inventory goals and the second round; **B** a home's semantic map kept between runs, anchored at
the dock, stable ids, names from the operator, owned by Mission Control; **C** an object is a
landmark when its value is 0.7 or more; **D** the camera record is `sighting`.

The robot file (agreed "for now", 2026-11-17): the body as URDF (RFC-0011); capabilities and the
connection in a small file of our own that borrows the VDA 5050 factsheet's fields and Open-RMF's
task kinds, so a bridge to either stays easy. The design leans toward VDA 5050 from the start. The
specs themselves are to be read before the format is fixed (question 21).

1. **miniview's new name.** Answered: **Observatory**. The rename is step 12; until then the
   package and CLI stay `miniview`.
2. **Slack in the first version?** Answered: no, later (answer 3). Kept here only to record that
   RFC-0006 §6 question 3 (one Slack app or two) stays open.
3. **How the per-robot lock is shared with `nxt-web`.** Options: a lock file both honour; Mission
   Control asks `nxt-web` for its status first; `nxt-web` gains a "driven by" field. The minimum is
   the second.
4. **The navigator API:** answered, its own process (§3.7).
5. **The goal store:** answered, SQLite (§3.4.6). Whether the library also exists as files: see 23.
6. **The first list of `must_not` conditions,** to be fixed against what the duck's navigator and
   the scenario runner's invariants can report (ADR-0015).
7. **The event stream's rate and the state's contents** per robot; settled in the first slice.
8. **May an MCP agent fire?** Answered: no (§3.8).
9. **Where it runs:** the workstation first (the brain's long-term place is open, RFC-0002 §5.5).
10. **Licence and splitting into its own repository** (RFC-0006 §6): unchanged; the operator's other
    projects use MIT.
11. **One goal on several robots (§3.4.4):** is `each` / `any` / `split` the right set, and is
    `each` and `any` enough for the first version? Who decides the share: the goal, or the run?
12. **What `find_all` means.** My reading: every object of one kind. The operator's list may have
    meant `inventory`; if so, drop one.
13. **An explore goal that ends by its budget:** `failed` with the reason "budget spent" (proposed),
    or its own outcome? `not_found` is only for find goals.
14. **Mission Control's map drawing:** share the Observatory's drawing module or duplicate a small
    2D one (§3.6). Proposed: duplicate first. Not read: the Observatory's page code.
15. **Merging into the home map (§3.5.2):** movable things that moved, objects expected and not
    seen (RFC-0016 §4: not built yet in the navigator), two objects of one non-unique kind close
    together, and what the operator sees when the merge guesses wrong.
16. **A no-LLM phrase matcher** for the simplest goals, or none? And where the planner's address
    and key live (a file beside the registry is proposed).
17. **Several homes in v1?** A home id is in the API, so it is possible; the simulator has one.
18. **ADR-0019 and the records.** ADR-0019 on this branch still says `look` (records `look`,
    `miniview.look`, `/miniview/look`) and a landmark at `landmark >= 1.0`. Decisions C and D change
    both. The ADR, the records and the viewer code are another change, not made here; until then
    this RFC says `sighting` and 0.7 and the ADR says otherwise (a doc-versus-code divergence to
    close).
19. **Room regions.** `go_to_room` and `explore {room}` need an extent for a room: from the map's
    segmentation, drawn by hand, or from the objects' footprints. The navigator's work first.
20. **A link back from the Observatory to the goal run:** a field in the run's metadata, which is
    the Observatory's contract to change.
21. **The robot file's format,** after the VDA 5050 and Open-RMF specs are read; the §3.12 table is
    unverified until then.
22. **How the dock pose is recorded** for a home, and what happens if the simulator's dock moves.
23. **The goal library as files:** SQLite only, or also exported to folders in the lab's data
    folder to diff and back up.
24. **How much of the loop** (decisions, the map at each decision) the page shows, against sending
    the operator to the Observatory.

## 6. Alternatives considered

- **Grow `nxt-web` into Mission Control** (RFC-0006's plan): rejected by the operator (O6). It would
  carry an NXT-shaped page and API into a many-robot app.
- **A JSON-RPC API for clients, like RFC-0003:** one protocol end to end. Rejected for clients:
  browsers, phones and `curl` get less from it than from HTTP; the adapters still speak JSON-RPC to
  robots. Revisitable (§3.2.2).
- **WebSocket instead of SSE:** two-way, but the commands already have HTTP and a second path for
  STOP is a second way to get it wrong; SSE is one direction and reconnects with a sequence number.
- **gRPC or MQTT:** a good fit for fleets, but a new dependency and a poor fit for `curl` and an
  MCP server; not needed for one operator on a tailnet. (MQTT is VDA 5050's transport; a VDA
  adapter would speak it, §3.12.)
- **A ROS 2 bridge as the API:** not now ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).
  Terms and shapes follow ROS, so a bridge is an adapter later.
- **Goals inside the Observatory:** it does not send commands (ADR-0005), and its job is to show.
- **Goals only in flotilla:** robot-specific code would pull flotilla toward one domain (RFC-0006
  §7), and the app has to work alone.
- **No fake robot; wait for the simulator:** blocks the API, the page and MCP on stream A.
- **The home's map only in the robot's navigator, or only in the Observatory's runs:** the
  navigator's map belongs to a run and a robot; the runs are a record, and the Observatory reads and
  does not command. A shared home needs one owner that outlives runs and several robots: Mission
  Control (the operator, "B yes").
- **Goals given only as coordinates:** rejected; "maps and coordinates make no sense" to the
  operator as the way to give goals. Points stay as one kind among the others.
- **An LLM that all goals pass through:** rejected. It would make a model a requirement for
  every goal and put it in the path to the robot. The planner is optional and returns data to be
  confirmed (§3.4.5).

## 7. Discussion

- 2026-11-17 — Operator, requirements gathered
  ([MISSION-CONTROL-REQUIREMENTS.md](../wip/MISSION-CONTROL-REQUIREMENTS.md)): a new app with
  robots, goals, a map of its own, a link to miniview, full MCP and a remote API, swarm in mind; the
  five answers of its section 5 (conditions from the start; an outside agent over MCP first; Slack
  later; tailnet only with one operator; the name Mission Control).
- 2026-11-17 — Draft of this RFC (revision 1), for the operator's review. Not verified while
  writing: that the endpoints of `nxt-web` and miniview behave as documented when run; PRD-001,
  UXS-001, RFC-0010 and RFC-0012 were not read; flotilla's and eval-harness's repositories were not
  read.
- 2026-11-17 — Operator, answers after revision 1: Observatory; the navigator API its own process;
  SQLite; an MCP agent may not fire; and, from reviewing the mockup, a second round of requirements
  (goals at the centre, a library in folders, robots from files, places and rooms, the LLM optional,
  one goal on several robots, the loop observed), recorded in the requirements as O13 to O23.
- 2026-11-18 — Revision 2, for the operator's review. The operator decided: **A yes** (revise now
  with object, room, explore and inventory goals; recognisers in robot capabilities; objects and
  rooms in the map and API; fold in the second round, which revision 1 did not), **B yes** (a
  home's semantic map kept between runs, anchored to the dock in the simulator, stable object ids,
  objects named by the operator, the stored map owned by Mission Control; in a real home the robot
  must first recognise where it is, later), **C yes** (an object is a landmark at a landmark value
  of 0.7 or more), **D yes** (the camera record is `sighting`, not `look`). Changed, and why:
  - A consistency review found revision 1 behind the decisions. Fixed: the lines that still said
    firing was open, SQLite was not verified, the navigator API's process was open and miniview's
    name was open are now answered (§3.4.6, §3.7, §3.8, §5); the non-goals are re-cut (§2.3);
    RFC-0016 and ADR-0019 are in "Builds on".
  - New goal kinds, `not_found`, a result, several robots on one goal (§3.4); recognisers and
    localisation among the capabilities, with the rule (§3.3.2); homes, objects, rooms, naming (§3.5);
    the objects and rooms layers and the sighting resource (§3.6); the navigator API's new methods
    and the run key at goal start (§3.7); the Observatory link and the loop (§3.11); the VDA 5050
    and Open-RMF mapping, marked unverified (§3.12); a glossary (§1.1); the order rewritten (§4).
  - The requirements file gained O13 to O26 and a section for the decisions of 2026-11-18.
  - Not verified while writing: the VDA 5050 and Open-RMF specs (not read); the Observatory's page
    code and whether its drawing can be shared; that a navigator's object ids are not stable across
    runs (assumed not); the current `viewer/CONTRACT.md` field names.
