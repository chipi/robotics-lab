# RFC-0014 — Mission Control: one API for every robot, goals in words, places and objects

**Status:** Accepted, revision 2 (2026-11-18). The operator, 2026-11-18: "goal is to deliver all
ideas we wrote down". Built, in `control/` (eb6a560): of step 1 the API contract and its tests, the
fake robot with its fake site, the registry from robot files, the lock through the gate for the fake
robot, the goal library with ad-hoc runs, `must_not` at robot, site and goal level, goal runs with
every outcome, and rates that are settings; of step 3, against the fake robot only, the site and
area library, objects with stable ids, naming, `inventory`, `go_to_object`, `explore`, `not_found`,
`done` and `result`; and, ahead of its turn, `go_to_area` and `explore {area}` of step 9. Then, in
the next commit (920cc90): the page of step 1 (robots, the map with the objects and areas layers, the
library, point goals by tapping the map, goal runs from the event stream, STOP and STOP ALL, a Watch
link that is disabled while the run key is null), the areas the operator draws, renames and deletes
on that map, and site export and import. Then the MCP server of step 1 (62de2f0; the operator
approved the official `mcp` SDK for `control/` only), so step 1 is built except the `/watch` link,
which needs a run key (the fake robot writes no Observatory run). Then, against the simulated duck:
step 2 (44686d5: the navigator API as its own process, `duck-nav-server`, and the `duck-sim` adapter
in Mission Control with run keys, the Watch link and the goal run's id and name in the Observatory
run, `viewer/CONTRACT.md`), the guardrails enforced in the real navigator with the loop's decisions
relayed per goal run (3d8ac35, O17), step 5 and 6 (1a13fa0: one goal on several robots with `share`
each or any; goals in words by a phrase matcher, with an optional LLM planner that is off unless
`planner.json` exists and has never been called against a real endpoint) and step 7 (c1339e1:
per-client tokens, off unless `--require-tokens`). Then the containers (f010f44: both images built,
run together from the root compose file, both health checks and one point goal on the fake robot
through the containerised Mission Control checked on 2026-11-18, memory capped, `make stack-up`),
step 4 (2049e7c: the NXT adapter over nxt-web's lock, tested against `nxt-web --fake` only; 2f878d7:
nxt-web's own page takes the lock and a command with no lease is refused) and step 0 (the robot
file's format of §3.3.1, decided 2026-11-18). Not built: steps 8 and 10 to 12, and `share: split`.
**Builds on:** [RFC-0006](RFC-0006-mission-control.md) (the vision, superseded in part, §2.1),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0002](RFC-0002-robot-brain.md) §3.9 to §3.10 (several robots, the brain's API),
[RFC-0005](RFC-0005-missions.md) (missions), [RFC-0007](RFC-0007-platform.md) (the platform),
[RFC-0013](RFC-0013-robot-eye.md) and [RFC-0009](RFC-0009-miniview.md) (miniview, to be renamed the
Observatory), [ADR-0015](../adr/ADR-0015-scenario-runner.md) (goals as challenges),
[RFC-0016](https://github.com/chipi/robotics-lab/blob/explore-apartment/docs/rfc/RFC-0016-objects-and-semantic-map.md)
(objects and a semantic map; it lives on the branch `explore-apartment`, so this link is absolute
and becomes relative when that branch merges),
[ADR-0019](../adr/ADR-0019-semantic-map-records.md) (the `objects` and sighting records),
[RFC-0017](RFC-0017-robot-access.md) (Accepted, 2026-11-18: robot access, pairing, permission and
exclusive control; it generalises the lock of §3.3.3).
**Requirements:** [MISSION-CONTROL-REQUIREMENTS.md](../wip/MISSION-CONTROL-REQUIREMENTS.md)
(O1 to O12 are the operator's first round, 2026-11-17; O13 to O30 the second round and the decisions
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
| site | a named place robots work in, with a kind (apartment, office, warehouse, garden, the simulated challenge course), its own frame and its own maps. Nothing in Mission Control is fixed to one kind of place: "home" is one site, named by the operator. Several sites are supported from the start; a robot is at one site at a time; the simulator's apartment is one site (the operator, 2026-11-18) |
| site frame | the one coordinate frame of a site. In the simulator it is the dock: every run starts there |
| area | a named region of a site that the operator defines: a name, an outline (a polygon on the site map, in the site frame) and optionally an area type (kitchen, bedroom...). Only the operator creates, changes or deletes areas; the robot never does (§3.5.3). Objects are in areas by geometry |
| room | an area indoors; outdoors an area is a zone |
| area type guess | what the robot's object votes say the area is like ("kitchen-like"). Information and a check on its position; never an area |
| place | something a goal can name instead of coordinates: an area, a room or an object |
| object | anything at a site that a recogniser reports: furniture, a plant, a picture. Has a stable id, a kind, parts (boxes with a bottom and a top), a confidence, maybe a label |
| kind | what an object is ("fridge"). One catalogue for every site (`kinds.json`, RFC-0016): a general default, plus optional hints per site kind (a fridge suggests a kitchen in a home and a break room in an office) |
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
| C8 | RFC-0016 §4 lists "objects in Mission Control (goals by object there, naming objects by hand)" as not in its first build | This RFC is where they are: object and room goals (§3.4.1), the site's map and naming (§3.5) |

What does not change: RFC-0006 §2 and §3.3's line (mission control commands and keeps safe, the
viewer shows and stores, eval-harness judges, flotilla governs), as amended by RFC-0007 §2; the
ROS-aligned terms ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)); RFC-0006 §3.2 and §4
(what it is not; the open-source product, whose name was chosen: Mission Control).

### 2.2 Goals

- One API that every client uses equally. Nothing works only in the page (O11, O12).
- Many robots from day one, one built first; one goal that names several robots (O8, O9, O10, O16).
- Goals at the centre (O13): a library in folders, ad-hoc runs that are not saved, the good ones
  saved; given as a point, an area, an object, an exploration, an inventory, or in words (O14, O15).
- Places and rooms in place of coordinates (O15): "go to the fridge", "explore the kitchen".
- A library of sites, each with its map of objects and areas kept between runs, owned by Mission
  Control, areas named by the operator, and objects the
  operator can name (O26).
- A map in the app with goals set on it (O4); the loop observed while a goal runs (O17); a link to
  the Observatory for the deep view (O5, O19).
- A STOP that works from every client, to every robot, without a confirmation; and one controller
  at a time per robot, by an exclusive lock (§3.3.3).

### 2.3 Non-goals

These stay out of the first versions. Robots collaborating on one goal, missions in words (an LLM)
and the EV3 and the real duck are no longer here: they are requirements, with their own steps
(§4).

- History, comparison, plots, video: the Observatory's. Governance and approvals: flotilla's.
- Public exposure, several operators, accounts (§3.9).
- Firing over MCP or from an agent: decided no (§3.8).
- An LLM as a required part. Every goal can be given without one (§3.4.5).
- Correcting a robot's position at a real site from landmarks: later (§3.5.4), not in the first
  versions.
- Areas drawn by the robot or suggested by it: never (§3.5.3). Areas are the operator's.
- A detector on real video: the recogniser slot is in the capabilities, the detector is its own
  work (RFC-0016 §3).

## 3. Proposal

### 3.1 What Mission Control is

A standalone Python service (the language of `nxt-web` and miniview) with a web page, an API and an
MCP server over that API. It is the only thing that commands several robots; `nxt-web` still
drives one NXT on its own (O6); the Observatory still only shows (ADR-0005: the viewer does not send
commands). It holds the list of robots, their live state, the goals and their runs, and the
sites' semantic maps. Its store is SQLite (the operator, 2026-11-17).

Three processes, connected by APIs and not by shared code:

```text
  page ─┐                         ┌─ adapter ─ simulated duck ─ navigator API (own process)
  MCP  ─┤                         ├─ adapter ─ fake robot (development)
  mobile┼─ Mission Control API ───┼─ adapter ─ NXT (nxt-web's API, later RFC-0003)
  agent ┘   robots, goals, sites, ├─ adapter ─ EV3 (later)
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
| `POST /api/v1/robots/{id}/lock`, `.../lock/renew`, `DELETE .../lock`, `POST .../lock/takeover` | the exclusive control lock (§3.3.3): acquire, renew, release, force a takeover (recorded); the holder is in `GET /robots/{id}` |
| `POST /api/v1/robots/{id}/stop` | stop this robot; always accepted, needs no lock |
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
| `GET /api/v1/sites`, `POST /api/v1/sites` | the site library (§3.5.1): list, create `{name, kind}` |
| `GET`, `PUT`, `DELETE /api/v1/sites/{s}` | read, rename or change the kind of, retire a site: id, name, kind, the site frame, counts |
| `GET /api/v1/sites/{s}/areas`, `POST /api/v1/sites/{s}/areas` | the operator's areas of a site (§3.5.3): list with the objects in each; create `{name, type?, outline}` (a polygon in the site frame). Only the operator creates, changes or deletes areas; there is no robot suggestion |
| `PUT`, `DELETE /api/v1/sites/{s}/areas/{a}` | rename, change the type or redraw the outline, delete |
| `POST /api/v1/sites/{s}/areas/{a}/merge`, `.../split` | merge two areas, split one |
| `GET /api/v1/sites/{s}/areas/at?x=&y=` | which area holds a point in the site frame, or "none defined" |
| `GET /api/v1/sites/{s}/objects` | the site's objects (§3.5): stable id, kind, label, area, parts, confidence |
| `POST /api/v1/sites/{s}/objects/{id}/label` | name an object: `{label}` ("this is my desk"); the MCP tool is the same call |
| `GET /api/v1/sites/{s}/inventory` | the confirmed objects by area, with sightings and confidence |
| `POST /api/v1/sites/{s}/export`, `.../import` | the site, its areas and its labelled objects as files (§3.5.2) |
| `GET /api/v1/events` | the live stream (§3.2.2) |

Errors are `{ok: false, error: {code, message}}` with an honest status code. A command to a robot
that is offline is an error, never a silent queue. A goal refused for a robot says why, in a field
a client can show (§3.3.2, the rule). Units are SI and frames are `map`/`odom`/`base_link` as in the
contract of miniview (`viewer/CONTRACT.md`), plus the site frame (§3.5.1); every response that
carries a position names its `frame`.

#### 3.2.2 Transport: HTTP JSON and a live stream

- **Requests:** HTTP with JSON bodies. Every client we know speaks it: the browser, a phone app,
  `curl`, an MCP server's tool code, a shell script.
- **Live:** one server-sent-events stream, `GET /api/v1/events?since=<seq>` — robot state at a
  steady rate, `goal-run` changes, the navigator's decisions with their reasons (§3.11), robot
  online and offline, locks, STOP, objects named. Each event carries a sequence number so a client
  that dropped can ask for what it missed. The defaults: state twice a second (pose, status,
  battery when known), events as they happen, the map only when it changes and at most once a
  second. They are settings per robot (in its file) and per subscription (a client on a slow link
  asks for less), within what the robot's interface allows. SSE is what miniview's live view
  already uses (requirements §4); not verified here against `viewer/CONTRACT.md` in detail.
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
connection, the capabilities (§3.3.2) and the robot's task kinds. There is no discovery in v1; the
registry is the set of files the operator edits.

**The file's format** is decided (2026-11-18, the operator: "All as recommended", after the specs
were read: `docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md`). JSON, one file per robot, built in
`control/src/mission_control/robots.py` and `robotfile.py`, described in `control/CONTRACT.md`:

- **`factsheet`** is a subset of VDA 5050 3.0.0's factsheet with **VDA's names verbatim**
  (camelCase, SI units), so a real VDA robot's factsheet can fill it by copying:
  `typeSpecification` (`seriesName`, `mobileRobotKinematics`, `localizationTypes`,
  `navigationTypes`), `physicalParameters` (`maximumSpeed` [m/s], `maximumAngularSpeed` [rad/s],
  `maximumAcceleration`, `maximumDeceleration`, `width`, `length`), `protocolFeatures`
  (`mobileRobotActions`: `actionType`, `actionScopes`, `blockingTypes`, `pauseAllowed`,
  `cancelAllowed`). `maximumSpeed` and `maximumAngularSpeed` replace the first format's
  `drive.max_vx` and `max_vyaw`. A value that is not measured is left out, not guessed.
- **Ours, beside it, in snake_case:** `id`, `label`, `kind`, `adapter`, `control` (`deadman_s`,
  `lease_s`, `takeover`: the lock is ours, RFC-0017; VDA has none), `capabilities` (`sensors`,
  `recognisers`, `localisation`, `map`, `navigator`, `guardrails`, `skills`, `description`: VDA has
  no field for them), `guardrails`, `rates`, `online_after_s`, `teams`.
- **Two values inside the factsheet are ours, and the contract says so:** the kinematics `LEGGED`
  for the duck (VDA's enum is extensible and has no legs) and an action's `irreversible`.
- **The robot's `max_speed` guardrail may never be above `factsheet.physicalParameters.maximumSpeed`:**
  the guardrail is the limit applied, the factsheet is what the robot can do. A file that breaks it
  does not load.
- **`id` stays ours** (lower case, digits, dashes); `manufacturer` and `serialNumber` are added only
  when a VDA robot is. **No VDA adapter is built.** The field names are borrowed so that one would be
  a copy, not a translation.

Each robot gets **one connection, its own task, its own timeouts**: a slow or dropped robot is
marked `online: false` and stays that way until it answers; it never delays another robot. Commands
to different robots run concurrently (O9). `online` is a measured fact (the last answer within a
bound), not a flag the adapter sets.

#### 3.3.2 Capabilities as data

Each robot has a `capabilities` object, and the page and the MCP tools offer only what is there.
What VDA has a field for (speed, size, kinematics, localisation type, actions) is in the robot
file's `factsheet` (§3.3.1), and the deadman and the lock's settings are in `control`; the fields
below are the ones VDA has none for:

| Field | Example |
| --- | --- |
| `sensors` | `[{name, kind: "tof8x8" \| "ultrasonic" \| "colour" \| ..., frame}]` |
| `recognisers` | `[{name, kinds, frame}]`: what can say "that is a fridge": a camera (simulated now, a video detector later), the kinds it knows (from the catalogue), the frame its detections are in. Absent or empty on a robot that has none; the NXT and the EV3 may have none |
| `localisation` | `{frame: "site" \| "run", how: "dock" \| "landmarks" \| ...}`: whether the robot's positions are in the site frame, and how it knows. The simulated duck: home, by the dock |
| `map` | `{kind: "occupancy_grid", resolution_m}` or absent |
| `navigator` | `{goal_kinds: ["point", "go_to_object", ...], conditions: [...]}` or absent |
| `guardrails` | the guardrails this robot can enforce or report: `["contact", "fall", "drop_clearance", "stuck", "time_limit", "no_go_area", "max_speed"]`, with its own limits (§3.4.8) |
| `skills` | `["fire"]`, each marked `irreversible` where it is (RFC-0003 §2.3) |
| `description` | the robot's name in the Observatory's robot list (RFC-0011), for drawing it |

A sensor added to the NXT changes its robot file, not Mission Control's code (O10: "I will boost
lego robots with better sensors as I go"). Today only the simulated duck has a map, a navigator and
a (simulated) recogniser (requirements §1); the NXT and the EV3 start with status, drive and STOP.

**The rule for object and area goals.** A goal that names an object or an area (§3.4.1) is accepted
for a robot only if it has a navigator **and** either its own recogniser (it finds the object
itself) or a shared site map it can localise in (`localisation.frame: "site"`, so it can go to a
place another robot or an earlier run found). Otherwise it is refused, with the reason: "no
recogniser and not localised in the site frame". The same rule decides which robots of a team can
take part (§3.4.4).

#### 3.3.3 One driver per robot, across apps

`nxt-web` still exists (C6), so two apps can reach the NXT, and an agent or a script can reach any
robot. The operator, 2026-11-18: "we should not allow two things to drive the same robot, so there
should be some kind of exclusivity lock built in. So that's how two things should work together,
by not being allowed to work together." So there is an **exclusive control lock per robot**, built
in:

- **One controller at a time.** Mission Control, `nxt-web`, an agent, a script: whoever holds the
  lock may drive the robot or run a goal on it. Any other that asks to drive that robot is refused
  with who holds it ("driven by Mission Control since 14:02").
- **It lives where every command to the robot passes**, not in a client: a gate at the robot's own
  interface process (for the duck, in front of robotd, behind the navigator API; for the NXT, in
  `nxt-web`'s Controller, below). The gate is a pass-through: it never resends a command, so a
  stalled client cannot replay old moves. No client can bypass it. The design is
  [RFC-0017](RFC-0017-robot-access.md) (Accepted, the advisor's version, the operator,
  2026-11-18); this RFC takes its lock as the core.
- **It is a lease tied to the connection.** It lasts 10 to 30 seconds, the holder renews it, and it
  is released at once when the connection drops, so a crashed client does not lock a robot for
  ever. Releasing is also explicit. The deadman (0.5 s on the duck) stays the safety stop; the
  lease is not a safety mechanism. On the duck, losing the lease stops the robot: `robot.stop`,
  then an explicit zero move.
- **Who holds it** is the process that sends `robot.move`. For a duck goal that is the navigator
  server: it acquires at `goal.start` and releases at the end of the run. Mission Control's manual
  drive holds it in Mission Control's own name. Mission Control's `lock` field mirrors the gate's
  "who"; it never keeps a second copy.
- **A goal run that loses its lease:** a takeover ends it `interrupted`; a STOP ends it `cancelled`.
  The navigator server reports the loss on the event stream of §3.2.
- **Takeover.** The operator can force a takeover from Mission Control: it ends the other holder's
  control and is recorded (who, from whom, when). This is for one operator with several of his own
  clients. Between different people's clients nobody may eject another while connected: that is
  RFC-0017's rule, and it may remove or restrict takeover (§5, question 3).
- **The NXT:** its lock lives in `nxt-web`'s Controller (`/api/lock`), the only process on the
  brick's link; Mission Control's NXT adapter uses it.
- **No pairing yet.** The first build has no pairing, keys, TLS or discovery: it runs in home-lab
  mode, where a client's identity is its `hello {client}`, the tailnet is the authentication, and
  the lease is enforced. Pairing and the rest come later, per RFC-0017.
- **Watching needs no lock.** Reading state, the map and the stream is open to every client. STOP
  never needs the lock (§3.8).

The API has `POST /robots/{id}/lock` (acquire, with the holder's name), `.../lock/renew`,
`DELETE .../lock` (release), `POST .../lock/takeover` (operator only) and the `lock` field of
`GET /robots/{id}` (who holds it, since when, when it expires), mirrored from the gate.

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
| `go_to_object` | `{kind \| id \| label, area?}` | the robot stands within 0.35 m of the object's outline and faces it within 45 degrees (the judge of RFC-0016), within the budget | navigator; recogniser or a shared site map (§3.3.2) |
| `go_to_area` | `{area}` | the robot is inside the area | navigator, an operator-drawn area (§3.5.3) |
| `explore` | `{area \| site}`, budget in minutes | no reachable frontier left in the area, or the budget is spent: both end `done` | navigator, map |
| `inventory` | `{areas?}`, budget | the inventory is returned: the confirmed objects by area | navigator, recogniser |

How an object is picked, for `go_to_object`: a `label` is the operator's name and wins; an `id` is
exact; a `kind` takes the nearest confirmed object of that kind in the site's map; `area` narrows
the choice to that area. If the site's map has no such object, the navigator explores until it
confirms one (`duck-explore --find` in RFC-0016) or the budget is spent. The robot goes to the
approach pose the navigator computes (a place to stand 0.25 m off the outline with room to turn),
then turns to face it.

The operator's "find all objects" is the `inventory` goal (the operator, 2026-11-18: no separate
`find_all`).

Common fields: `name`, `folder`, `scene?` (how the simulator's world is loaded, ADR-0015), a
`budget {minutes}` for exploring kinds, `must_not` (`["contact", "drop", "stall", ...]`) and
`expect: "reach" | "refuse"`. The conditions are checked by the navigator's own report and, in the
simulator, by truth (as the scenario runner's invariants are); on a real robot only what the robot
can measure is checked, and the goal run says which conditions were and were not checkable. The v1
list of `must_not` is the few the duck's navigator already reports; guardrails are their own
subsection (§3.4.8).

```text
goal   { id, name, folder, kind: "go_to_object",
         params {kind: "fridge", area?: "kitchen"},
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
  flagged on a real run (its `conditions.rehearsal`). Simulator-first is on by default for a goal
  on a real robot (the operator, 2026-11-24; unit E1): it runs there only after a passing
  simulator run of the same goal (phase 5 item 4b unit B8; [the contract][mc-contract], Goals). A
  goal that says `sim_first: false` opts out and is only flagged, since the operator is in the
  room (RFC-0002 §3.5).

[mc-contract]: https://github.com/chipi/robotics-lab/blob/main/apps/mission-control/CONTRACT.md

#### 3.4.3 Goal runs: states, outcomes, results

A goal run (an attempt) records its state: `queued → running → reached | done | refused | failed |
stopped_by_guardrail | not_found | cancelled | interrupted`, progress (distance left, time used,
conditions so far, the area it believes it is in), and the reason on any end that is not
`reached` or `done`.

`not_found` is new: an object goal whose budget was spent, or which has no frontier left to
explore, without finding what it was asked to find. It is different from `refused` (the goal could
not start, or the planner said no path) and from `failed` (the robot tried and a condition broke).

`done` is for goals that have no target to reach: an `explore` or `inventory` that ends, whether
no frontier is left or the budget is spent, is not a failure (the operator, 2026-11-18). Its
`result` says how much was covered.

The run also carries a `result`, which depends on the kind:

| Kind | `result` |
| --- | --- |
| `go_to_object` | the object found (id, kind, label, position in the site frame) and the stand pose the robot reached (`{x, y, yaw, frame}`) |
| `inventory` | the inventory: objects by area, with sightings, confidence, recognisers and evidence (RFC-0016's `inventory.json`) |
| `explore` | the coverage: counts of cells explored and objects found, and whether it ended by no frontier left or by the budget |
| `point`, `go_to_area` | none |

At goal start the navigator returns the **run key** (`robot/scene/run`), so the goal run binds at
once to the Observatory's `/watch/<key>`, live, before the run ends (§3.7).

#### 3.4.4 One goal on several robots

A goal run names `robots: [ids]` or a `team` (a named set of robots in the registry). The goal
does not change. Decided (the operator, 2026-11-18): `each` and `any` in v1, `split` later
(§5, question 11):

- **`share: "each"`:** every robot does the whole goal, independently, and the goal run holds one
  result per robot. This needs nothing new: it is parallel goal runs under one parent. It is the
  first to build.
- **`share: "any"`:** the first robot to reach the goal ends it; the others are cancelled and
  stopped. Also only parallel runs plus a rule.
- **`share: "split"`:** the goal's area is divided between robots (two robots exploring the site,
  the NXT driving to where the duck found the fridge). It needs a shared site map and frame (§3.5),
  a division of frontiers, and for the LEGO robots a way to be localised in the site frame. This is
  RFC-0002 §3.9's phase 6, later.

A robot that cannot take part (§3.3.2: no navigator, or no recogniser and not localised) is left
out of the run with its reason, or the run is refused if none can. That is how the duck, the NXT and
the EV3 collaborate (O10): by capability, not by name; the duck with a camera finds the object and
writes it to the site's map, a LEGO robot localised in the site frame can go to it.

#### 3.4.5 Goals in words, and an optional planner

The operator describes a goal in words; a planner may break the words into goals (O14). Rules:

- **The planner is an independent module** with one function: `plan(text, context) → goal specs`,
  where `context` is what the robots can do (capabilities) and the site's objects and areas. It is
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
- **A phrase matcher with no model** handles the simplest goals ("go to the fridge", "explore the
  kitchen"): it matches a known kind, label or area in the site's map and returns a goal, or
  nothing (the operator, 2026-11-18: yes). **The planner's address, model and key are in a config
  file beside the robot registry, not in the database.**

#### 3.4.6 Where goals and runs are stored

- Goals, goal runs and the sites (§3.5) are in **SQLite** in Mission Control's own state
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

#### 3.4.8 Guardrails: what a goal must not do

The operator, 2026-11-18: a goal has a `must_not` list, "additional conditions that control.
Basically, these are like guardrails of some sort for the robots ... we have to support that."
A goal is **what to do plus its guardrails**.

**Three levels, merged into every goal run.**

| Level | Set by | Examples |
| --- | --- | --- |
| the robot's | its robot file | a speed cap, a minimum clearance to a drop |
| the site's | the operator, in the site library | no-go areas: the stairwell, an area the operator marks; later, quiet or away hours |
| the goal's | the goal | no contact, within its time limit, and any extra the goal adds |

A goal can add guardrails and can never remove a site's or a robot's. The goal run records the
merged list it ran with, so it is readable alone.

**The first list** is what the robots can report today, as the challenge judge does (ADR-0015): no
contact, no fall, not within a set distance of a drop, not stuck, within the time limit. Then: a
**no-go area** (a polygon the operator draws on the site's map, §3.5.3), a maximum speed, and
quiet or away hours later. Which of them each robot kind can report is the one part left open
(§5, question 6): a robot lists the guardrails it can enforce in its
capabilities (`guardrails`), and a goal that needs one it cannot enforce is refused with the reason,
as in §3.3.2.

**Checked where it can act.** In the navigator, before and during the run, not only afterwards by
Mission Control: a no-go area is lethal in the planner (the path never enters it), a speed cap
clamps the commands, and contact, fall and stuck stop the robot at once. Mission Control checks the
merged list when the goal is accepted and reports; it does not stand between the navigator and the
robot. The robot's deadman and STOP (§3.8) are separate and always there.

**A broken guardrail stops the goal.** The outcome is `stopped_by_guardrail` with which one broke;
the robot stops safely; the stop is recorded as a decision with its reason (ADR-0014), so the
Observatory shows it (§3.11). It is a different outcome from `failed`: the robot did what it was
bound to do.

**In the library and in plans.** Guardrails are saved with the goal. A plan made by the planner
(§3.4.5) proposes guardrails as well, and the operator confirms them together with the goal; a plan
cannot loosen the site's or the robot's. The API: a goal carries `must_not`; `GET`, `PUT
/sites/{s}/guardrails` the site's (including no-go zones); the robot's are in its file and show in
`capabilities.guardrails`.

### 3.5 Sites, areas and objects

The operator wants goals as places: "go to the fridge", "explore the kitchen". For that, something
has to remember where the fridge is between runs. And nothing may be fixed to one kind of place:
"there should be nothing hard-coded to a home ... it's a terrain ... we should support multiple
terrains, and home is just one terrain being named" (the operator, 2026-11-18, who then adopted the
words **site** and **area**). Decided 2026-11-18 ("B yes"): a site's semantic map is kept between
runs, anchored to the dock, with stable object ids and labels from the operator, and **the stored
map is owned by Mission Control**.

#### 3.5.1 The site library and the site frame

A **site** has an id, a name the operator gives ("Home", "Office"), a kind (apartment, office,
warehouse, garden, the simulated challenge course) and a **site frame**. The operator names and
keeps sites in a library in the page (and through the API and MCP, §3.2.1). The simulator's
apartment is one site; so is the challenge course. Several sites are in the data model from the
start, one shown at a time (the operator, 2026-11-18, question 17). A robot is at one site at a
time.

The site frame is set by the first run at a site, from where that run starts: the dock in the
simulator (the operator, 2026-11-18, question 22). Every later run starts there too, so a run's
`map` frame is the site frame (Mission Control records the dock pose it assumed), and a run's
objects, in its own map frame, are already in the site frame. At a real site that is true only if
the robot starts at the dock (§3.5.4).

The site's kind may change the kinds' area hints: the catalogue (`kinds.json`) keeps a general
default and optional hints per site kind, so a fridge suggests a kitchen at a home and a break room
at an office. The catalogue is the navigator's, in RFC-0016; the per-site-kind hints are an
addition to it, not decided in this RFC's code.

#### 3.5.2 The map Mission Control keeps, and naming

- **What is stored** (SQLite, per site): objects with a **stable id**, a kind, parts (boxes in plan
  and height, ADR-0019's shape), the position, `confirmed`, the landmark value, the permanence,
  `confidence`, first and last time seen, the robots and recognisers that saw it, a few pieces of
  evidence, the area it is in, and the **label** the operator gave; and the site's areas (§3.5.3).
- **Stable ids are Mission Control's.** The navigator's ids belong to one run and are not assumed to
  be the same in the next. When a run ends (or while it runs, from the stream), Mission Control
  merges the run's objects into the site's by the navigator's own association rule (the operator,
  2026-11-18, question 15): the same kind nearby is the same object, and an object of a *unique*
  kind (a site has one fridge, RFC-0016 §6) within 1.5 m of a known one is the same object. A new
  one gets a new id. **An object the operator named is never merged away.**
- **Naming by hand.** `POST /sites/{s}/objects/{id}/label {label}`, and the MCP tool of the same
  meaning: the operator picks an object on the map (or an agent names one) and says "this is my
  desk". The label joins the object, shows in the map and the inventory, and works in goals
  (`go_to_object {label: "my desk"}`). A thing no recogniser knows is still an obstacle by its
  shape and can be named; naming it adds a label, and RFC-0016 §3 notes it can add a kind later.
- **The robot's map and the site's map.** The navigator keeps its own semantic map for a run
  (RFC-0016). Mission Control seeds a run with the site's objects when the robot is localised in
  the site frame (§3.3.2), so "go to the fridge" is a plan, not a search; the run's confirmed
  objects flow back. The seeding message is part of the navigator API (§3.7).
- **Files.** SQLite is the store; a site, its areas and its labelled objects can be exported and
  imported as files in folders, to diff and back up (the operator, 2026-11-18, question 23).

#### 3.5.3 Areas: the operator's regions, and the robot's type guess

An **area** is a named region of a site that **the operator defines**: a name, an **outline** (a
polygon on the site map, in the site frame) and, optionally, an **area type** (kitchen, bedroom,
office...). Indoors it is a room, outdoors a zone: the same polygon, nothing more until a robot
works outside. **Only the operator creates, changes or deletes areas.** The robot never creates or
suggests one. The operator (2026-11-18): "why would even a robot suggest an area? That's not the
goal. The goal is that he can detect in which area he is ... I definitely don't want a robot to
create areas." And: "I would name areas like my rooms, so I can manage those."

**The flow:**

1. The operator creates the site.
2. The first exploration maps it: walls, floor, objects. There are no areas yet, so "which area am I
   in" answers "none defined", and the robot's type guess (below) is shown as information.
3. The operator draws and names the areas in the site library, on the map the robot built, with its
   objects as the reference. Nothing is pre-filled. He can also rename, redraw, merge, split and
   delete them.
4. From then on "which area am I in" is geometry: the robot's pose on the site map inside an outline.
   It is exact.
5. The type guess becomes a check. Today the duck names the type of room it is in from the confirmed
   objects near it (a fridge votes kitchen). That is a **guess of the area type** ("kitchen-like"),
   not an area, and it is never stored as one. The Observatory shows it as information. When the
   pose says "Bedroom" but the objects look like a kitchen, the pose is probably wrong; in a real
   site that is the signal to relocalise from landmarks (§3.5.4).
6. Goals use the operator's areas: `go_to_area` (a free point inside the outline), `explore {area}`
   (the frontiers inside it), the guardrails' no-go areas (§3.4.8). `go_to_object` needs no area.

Objects are in areas by geometry: an object's area is the outline that holds its position. Until
areas are drawn they have none, and the inventory lists them under "none defined".

**In the simulator**, a test site's areas are drawn from the scoreboard's true room outlines, as the
operator would at home. Both are then measured: is "which area" right, and does the type guess agree
with it.

The API and MCP tools are in §3.2.1 (`/sites/{s}/areas`, with create, change, delete, merge and
split, and an `at` query for "which area holds this point or this robot"). The robot's type guess is
a field of the navigator's `rooms` method and of the state, never of the area list.

#### 3.5.4 A real site: knowing where it is

At a real site the robot is not always at the dock, and a run's frame starts wherever it started.
Before it can use the site's map, it must first recognise where it is: landmark position
correction (objects with a landmark value of 0.7 or more re-seen, matched against the site's map,
give a transform into the site frame). That is later work (RFC-0016 §4 leaves loop closure out of
its first build). Until then, `localisation.frame` is `site` only for runs that start at the dock;
elsewhere it is `run` and the rule in §3.3.2 applies: no shared site map for that robot.

### 3.6 The map in the app

The page draws a robot's map itself and a goal is placed by a click on it, or, better, by naming
a place: picking an object or an area on the map (O15). The data is the robot's own: the occupancy
grid (10 cm), the navigator's layers (obstacles, drops, gaps), the plan and the believed pose, as
the Observatory already streams them per run (`world.grid`, `world.obstacles`, `world.drops`,
`world.gaps`, `plan.path`, `belief.pose`; requirements §2.5). Mission Control serves them through
`GET /robots/{id}/map` and the event stream, in the robot's `map` frame.

Two layers are new:

- **An objects layer**, in the shape of ADR-0019's `objects` record: each object's parts in the map
  frame (`[x, y, hx, hy, yaw, z0, z1]`), `confirmed`, `landmark` (a landmark when the value is 0.7
  or more), `confidence`, kind, and the operator's label. A confirmed object is drawn solid, an
  unconfirmed one faint, a landmark in its own colour, as ADR-0019 does for the pages. For a site
  (`GET /sites/{s}/objects`) the frame is the site frame.
- **An areas layer**: the operator's areas as outlines with their names, and the robot's
  area type guess as information.

Mission Control draws its own map: it does not embed the Observatory's page. Whether it shares the
Observatory's drawing module or duplicates a small 2D drawing is **open** (§5, question 14). The
proposal is to duplicate a flat top-down drawing in the first slice, because the Observatory's
module is made for its 3D scene and not read for this RFC, and to share the code later if the two
drift.

What stays out: playback, the above/eye views, timelines, comparison. For those the page shows a
link, "Watch" (`/watch/<key>` or `.../latest`, `viewer/CONTRACT.md`), which opens the Observatory's
deep view. The map is a drawing for commanding; it is not a second Observatory.

### 3.7 Robots in v1, and the navigator API

| Robot | How | State on 2026-11-17 (historical: what is built now is RFC-0021 and the architecture page) |
| --- | --- | --- |
| **Fake robot** | An in-process adapter that moves a point, answers status, honours STOP and the deadman, can be told to drop offline, and carries a fake site with a few objects, so the objects layer, naming and the library are built with no simulator | New. Stream A owns the simulator until it hands over, so this is how Mission Control is built and tested without it |
| **Simulated duck** | A thin adapter over the navigator API (below); its recogniser is the simulated camera | `Navigator.go_to(goal, timeout_s)` returns `{"status": "refused", "why": ...}` or its result (`duck/src/duck_lab/nav/run.py`); it is Python and CLI only (`duck-go`, `duck-explore`, with `--find` and `--inventory` on the `explore-apartment` branch), with **no API server** |
| **NXT** | Status, drive and STOP through `nxt-web`'s HTTP API (`GET /api/status`, `POST /api/drive`, `POST /api/stop`; `apps/nxt-web/src/nxt_lab/web.py`); later the RFC-0003 JSON-RPC when its Python service exists. No recogniser today | `nxt-web` exists; RFC-0003 is not built |
| **EV3** | Nothing exists: no driver, no deadman, no interface, only robot descriptions (requirements §6). It needs its own link (firmware and protocol differ from the NXT's), a deadman on the robot or in the adapter, an RFC-0003-shaped interface, its battery and link status, and a safety review before it is driven | Not designed; arriving in days |
| **Real duck** | The navigator on ssh-forwarded sockets (RFC-0002 §3.3), later on the robot | Not owned; untested |

**A navigator API does not exist; this RFC proposes one, as its own process** (the operator,
2026-11-17). A small service beside the duck package (`duck-nav-server`) that owns one `Navigator`
and offers to Mission Control, over a process boundary, in the RFC-0003 JSON-RPC shape:

| Method | Meaning |
| --- | --- |
| `goal.start {kind, params, budget, conditions, seed?}` | starts a goal of any kind of §3.4.1 and returns `{run_key}` at once, so the goal run binds to the Observatory's `/watch/<run_key>` while it runs. `seed` is the site's objects (§3.5.2) |
| `goal.status`, `goal.cancel` | the run's state, progress and, at the end, its outcome and `result`; cancel stops it |
| `objects` | the navigator's current semantic map (ADR-0019's `objects` shape) |
| `rooms` | the area type guess and the votes behind it (§3.5.3); the area it is in comes from the outline, not from here |
| `inventory` | the confirmed objects by area (RFC-0016's `inventory.json`) |
| `find {kind \| label}` | the nearest confirmed object of that kind, or the labelled one; null if none is known |
| `name_object {id, label}` | name an object in the navigator's map (Mission Control also keeps the label in the site's map) |
| `map`, `state`, `sighting` | the map layers, the robot's state, the latest sighting |

It runs the navigator in its own thread; `robot.stop` never goes through it (§3.8). The method
shapes are proposed; the first slice for the duck settles them and writes them in the contract
(built: the navigator contract, version 1.0,
[`libs/runner/CONTRACT.md`](https://github.com/chipi/robotics-lab/blob/main/libs/runner/CONTRACT.md),
with Mission Control's side in `apps/mission-control/CONTRACT.md`). A goal kind the navigator does
not list in `capabilities.navigator.goal_kinds` is refused at the adapter.

### 3.8 Safety

- **STOP goes straight to the robot** (`robot.stop`, or the NXT's `/api/stop`), never through a
  planner, an LLM or a goal run (RFC-0002 §3.5). `POST /robots/{id}/stop` and `POST /stop` are
  accepted in every state, need no lock, no confirmation and no token beyond the tailnet, and stop
  all robots concurrently (a failing robot is reported, the others still stop). A STOP
  **latches**: it ends the holder's lease, the holder's next move is refused until it acquires the
  lock again, and the goal run is `cancelled`. STOP is accepted from any connection, always, and is
  logged; there is no flag to turn that off.
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
  not fire** (the operator, 2026-11-17: decided). Mission Control itself enforces it: the agent is
  Mission Control's client and the robot's gate sees only Mission Control. The agent can drive, run
  goals and STOP, with the same limits as the operator. The planner (§3.4.5) has no `fire` either.

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
- A **site** owns the shared map and the common frame (§3.5). Today that is the dock, and only for a
  robot that starts there. A LEGO robot is placed in the site frame by a marker or a camera fixing
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
a VDA 5050 adapter. No single standard covers capabilities. **The table was checked on 2026-11-18**
against VDA 5050 **3.0.0** (published 2026-03-18) and Open-RMF `rmf_ros2` 2.15.0, `rmf_api_msgs`
0.7.1 (`docs/wip/ROBOT-FILE-FORMAT-PROPOSAL.md` has the row-by-row verdicts and sources): ten rows
confirmed (some only as a design, or in part), and **three corrected**, below. Not read: VDA's JSON
schemas, Open-RMF's navigation graph format, how a fleet adapter bids for a task.

| Mission Control | VDA 5050 | Open-RMF |
| --- | --- | --- |
| robot file: capabilities, connection | the factsheet (type, physical parameters, protocol features, supported actions): the robot file's `factsheet` block borrows its names (§3.3.1) | fleet configuration: the fleet adapter's settings; not a robot description |
| robot online | the connection topic (online, offline, connection broken, hibernating) | fleet state: `robot_state.status` has `offline` |
| `point` goal | **corrected:** an order of two nodes and one edge (the first node is where the robot already is and is not reported, 6.1.1), or the temporary start node of 6.1.3.1; not one node | **corrected:** `go_to_place` is an event (an activity), not a task; a single trip is a `compose` task with one `go_to_place` phase, to a place on the nav graph |
| `go_to_object`, "go to the fridge" | resolved by Mission Control to an approach pose, then an order as for `point`; works if the site frame is the VDA `mapId`. Neither spec has objects or rooms | the same `compose` task, where objects and rooms are named places on the graph |
| `go_to_area` | a node at a point inside the area (VDA's zones are geometric; nothing more was found in 3.0.0) | the same task with the area's name; Open-RMF also has a `zone` task, not read in depth |
| patrol (several places) | an order with several nodes | `patrol`: visit places |
| `explore`, `inventory` | custom actions declared in the factsheet's supported actions | custom task kinds |
| goal run state | the state message: order, node and action states, errors, battery, operating mode | task state |
| progress and decisions | the state's action states, plus Mission Control's own events | task logs |
| STOP | goes straight to the robot first, for both. **Corrected:** VDA has no stop action: it has `cancelOrder` and `startPause`/`stopPause` (every robot must support them) and reports an emergency stop in `safetyState.activeEmergencyStop` (MANUAL, REMOTE, NONE) | **corrected:** not "not used": the fleet adapter has a `stop()`, and the API has `interrupt_task` and `kill_task` |
| a team goal | one order per robot | task assignment by the fleet adapter |
| the site's objects and areas | named places that Mission Control resolves before ordering | places on the nav graph |

A VDA 5050 robot would join by an adapter that reads its factsheet (into the robot file's
`factsheet`, by copying) and turns a goal into orders. That holds for speed, size, kinematics,
localisation and actions; it does **not** hold for `recognisers`, `map`, `goal_kinds` or
`guardrails`, which the factsheet has no field for, so the operator writes those by hand. The
object and area goals work for such a robot because Mission Control, not the robot, resolves places
to poses. No VDA adapter is built (§3.3.1).

### 3.13 Containers: run it anywhere

The operator, 2026-11-18: "that's why we need both Mini Explorer and Mission Control to be also
Dockerized, so that I can run them wherever I want to run them easy. So that's super important."
("Mini Explorer" is the Observatory, miniview.) The rule:

- **Each is a container image,** and they run together from one compose file, on any of the
  operator's machines: the workstation, the Mac mini home server, a laptop.
- **Nothing is tied to a host.** No host-specific paths in the code or the image. Configuration (the
  robot files, the planner's config, §3.4.5) and data (SQLite, runs) come in by mounted volumes and
  environment variables.
- **Robots are reached over the network,** never through a device on the container's host: the
  robot gates of [RFC-0017](RFC-0017-robot-access.md), the duck's robotd, the NXT bridge.
- **The Observatory already has this:** a Docker setup that mounts the data read-only and keeps its
  index in the host's state folder ([ADR-0012](../adr/ADR-0012-docker-read-only-data.md)). Mission
  Control gets its own image and a service in the same compose file in the first slice (§4,
  step 1), with its SQLite in a mounted state folder.
- **The NXT's Bluetooth link stays on the computer next to the brick.** That is the NXT bridge, its
  own small service (§3.3.3); a container running elsewhere reaches the NXT through the bridge's
  network address.

Not written here because it is not documented in this repository: any rule for which Docker engine
to use on the Mac mini; the operator's own setup rules apply there.

## 4. Order

Where the code lives: a new top-level directory `control/` beside `duck/`, `nxt/` and `viewer/`,
with `control/src/mission_control/` and its own tests, a `CONTRACT.md` for the API, a Makefile
target pair (`control-up`, `test-control`) like the others. Python, no new runtime dependency is
proposed here; SQLite comes with the standard library; the HTTP server and the SSE stream are
written with the standard library as `nxt-web` is (not verified: that the standard library suffices
for SSE under concurrency; if it does not, a framework would be a dependency to ask for, not
assumed). Mission Control ships as a container image from its first slice (§3.13).

0. **Read the VDA 5050 and Open-RMF specs**, then fix the robot file's format (§3.3.1, §3.12).
   Done 2026-11-18.
1. **A first slice that is useful.** The API contract (§3.2) and its tests; the fake robot with its
   fake site; the registry from robot files; the page with the robot list (online, status, lock), a
   map for a robot that has one, the goal library with folders and ad-hoc runs, a point goal set by
   a click with its conditions, a goal run with its progress, a big STOP and STOP-all, and the link
   to `/watch`; the MCP server over the same API; its container image and a compose file shared
   with the Observatory (§3.13). Done when the operator can set a point goal on the
   fake robot's map from the page, from `curl` and from an MCP client, watch it reach, and STOP from
   all three.
2. **The navigator API (its own process) and the simulated duck's adapter** (§3.7), once stream A
   hands over the simulator: a goal set on the page runs on the simulated duck and the goal run
   binds to a `/watch` link from its first moment.
3. **Sites, areas, objects and the object goals:** the site library and the site store in SQLite,
   areas the operator draws and names (merge and split), merging a run's
   objects into a site with stable ids, `objects`, `inventory`, naming by hand, `go_to_object`,
   `explore {site}`, `inventory`, the `not_found` and `done` outcomes and the `result`; the objects
   and areas layers on the map; export and import as files. Built first against the fake site, then
   the duck.
4. **The NXT's adapter** and the exclusive control lock (§3.3.3): status, drive, STOP, the lock in
   the NXT bridge that `nxt-web` and Mission Control share. Needs `nxt-web` running; the real-brick
   deadman check is pending (RFC-0003). The lock itself is built in step 1 for the fake robot and in
   step 2 for the duck.
5. **Goals with several robots:** `each` and `any`; goal conditions and runs deepened; comparing
   attempts; the simulator-first flag for real runs.
6. **The planner module and the LLM** (§3.4.5): `POST /plan`, an OpenAI-compatible client, read-back
   and confirm.
7. **Per-client tokens**, then the mobile app's needs, then Slack. Tokens built; the mobile app and
   Slack are later (the operator, 2026-11-18: "2CC").
8. **EV3 and the real duck**, each after its own interface, deadman and safety review.
9. **`go_to_area` and `explore {area}`** on the operator's outlines; the type guess as a check on
   the pose.
10. **Relocalisation at a real site** from landmarks (§3.5.4); `split` of one goal across robots.
11. **A real video recogniser** in a robot's capabilities.
12. **The Observatory rename**, and the flotilla integration (RFC-0006 §5, item 4).

## 5. Open questions

Answered by the operator, 2026-11-17: miniview becomes **Observatory** (question 1); the navigator
API is **its own process** (question 4); the goal store is **SQLite** (question 5); an MCP agent
**may not fire** (question 8). Answered 2026-11-18: **A** revise now with object, area, explore and
inventory goals and the second round; **B** a site's semantic map kept between runs, anchored at
the dock, stable ids, names from the operator, owned by Mission Control; **C** an object is a
landmark when its value is 0.7 or more; **D** the camera record is `sighting`. Then, after reading
revision 2, "I agree with all" of the proposed answers below, with one correction (question 3), and
the terms **site** and **area** in place of "home" and "room".

The robot file (agreed "for now", 2026-11-17): the body as URDF (RFC-0011); capabilities and the
connection in a small file of our own with a `factsheet` block that borrows VDA 5050's names
(§3.3.1). The design leans toward VDA 5050 from the start. The specs were read and the format
decided on 2026-11-18 (question 21).

Only question 3's open part and the questions marked **open** remain; the rest are answered and
kept to record where each answer went.

1. **miniview's new name.** Answered: **Observatory**. The rename is step 12; until then the
   package and CLI stay `miniview`.
2. **Slack in the first version?** Answered: no, later (answer 3). Kept here only to record that
   RFC-0006 §6 question 3 (one Slack app or two) stays open.
3. **Two controllers on one robot.** Answered (the operator, 2026-11-18, replacing "ask `nxt-web`
   first"): "we should not allow two things to drive the same robot, so there should be some kind of
   exclusivity lock built in." One controller per robot, an exclusive lease tied to the connection,
   held in a gate at the robot's own interface, with takeover by the operator (§3.3.3). The
   operator widened it beyond Mission Control and the NXT: five laptops and five robots in one
   room, three ducks and three laptops, each person driving only the robot they are allowed to
   connect to and not ejectable while connected. That is [RFC-0017](RFC-0017-robot-access.md),
   Accepted. The NXT's lock lives in `nxt-web`'s Controller (`/api/lock`): answered. The takeover
   and the no-ejection rule, answered with RFC-0017 (the operator, 2026-11-18: "Take the advisor
   version"): a robot's owner may take back a robot they lent; among owners of different robots
   nobody ejects anybody; v1 is a config list of the client names allowed to take over.
4. **The navigator API:** answered, its own process (§3.7).
5. **The goal store:** answered, SQLite (§3.4.6), with export and import as files (question 23).
6. **The first list of `must_not` conditions.** Answered, and made first-class (the operator,
   2026-11-18: "really good idea ... guardrails of some sort for the robots ... we have to support
   that"): what the robots report today, as the challenge judge does: no contact, no fall, not too
   close to a drop, not stuck, within its time limit; at three levels, robot, site and goal
   (§3.4.8). **Open:** the exact list per robot kind.
7. **The event stream's rate and the state's contents.** Answered, and configurable (the operator:
   "OK on Q7, but also configurable"): the defaults are state twice a second (pose, status, battery
   when known), events as they happen, the map only when it changes, at most once a second
   (§3.2.2). They are settings per robot (in its file) and per client subscription (a phone on a slow
   link may ask for less), within the limits the robot's interface allows.
8. **May an MCP agent fire?** Answered: no (§3.8).
9. **Where it runs.** Answered: the workstation now; the home server (the Mac mini) when the mobile
   app comes, always on, over the private network. Confirmed (the operator: "yes on
   Q9"). (The brain's long-term place stays open, RFC-0002 §5.5.)
10. **Licence and splitting into its own repository.** Answered: MIT; it stays in robotics-lab
    until a second program (the mobile app) uses its API, then it splits out. Confirmed ("yes on Q10").
11. **One goal on several robots (§3.4.4).** Answered: `each` and `any` in v1; `split` later.
12. **`find_all`.** Answered: dropped; "find all objects" is the `inventory` goal.
13. **An explore goal that ends by its budget.** Answered: not a failure; outcome `done`, the
    coverage as its result (§3.4.3).
14. **Mission Control's map drawing.** Answered: it draws its own small 2D map, not the
    Observatory's 3D module (§3.6).
15. **Merging into the site map (§3.5.2).** Answered: the navigator's association rule; objects the
    operator named are never merged away. **Open, smaller:** movable things that moved and objects
    expected and not seen (RFC-0016 §4: not built yet in the navigator).
16. **A no-LLM phrase matcher, and the planner's address and key.** Answered: yes, a matcher for the
    simple goals; the planner's settings are in a config file beside the registry, not in the
    database (§3.4.5).
17. **Several sites.** Answered: in the data model from the start, one shown at a time (§3.5.1).
18. **ADR-0019 and the records.** ADR-0019 on this branch still says `look` (records `look`,
    `miniview.look`, `/miniview/look`) and a landmark at `landmark >= 1.0`. Decisions C and D change
    both. Answered: being closed on the Observatory side, by another change; until then this RFC
    says `sighting` and 0.7 and the ADR says otherwise.
19. **Area regions.** Answered, and replaced by Q25: the operator draws the outlines in the site
    library, on the map the robot built (§3.5.3). Nothing is derived from objects or walls.
20. **A link back from the Observatory to the goal run.** Answered: yes, a field in the run's
    metadata (the Observatory's contract changes) (§3.11).
21. **The robot file's format.** Answered (2026-11-18, the operator: "All as recommended"): the
    specs were read; JSON; a `factsheet` block with VDA 5050 3.0.0's names verbatim (camelCase),
    snake_case blocks of ours beside it; `LEGGED` for the duck, marked as ours; a `max_speed`
    guardrail never above `maximumSpeed`; `id` kept; no VDA adapter (§3.3.1). The §3.12 table is
    checked, with three corrections (point goal, `go_to_place`, STOP).
22. **How the dock pose is recorded.** Answered: the first run at a site sets the site frame from
    where it starts (the dock in the simulator) (§3.5.1). **Open, smaller:** what happens if the
    simulator's dock moves.
23. **The goal library as files.** Answered: SQLite, with export and import as files (folders) to
    diff and back up.
24. **How much of the loop the page shows.** Answered: the current decision and the outcome; full
    detail one click away in the Observatory (§3.11).
25. **Who defines areas.** Answered (the operator, 2026-11-18): "why would even a robot suggest an
    area? That's not the goal. The goal is that he can detect in which area he is ... I definitely
    don't want a robot to create areas", then "Yes, that's it" to the flow of §3.5.3. Only the operator
    creates areas; an area is a polygon on the site frame (decided); an outdoor zone is the same
    polygon, nothing more until a robot works outside.
26. **The per-site-kind hints in the catalogue (§3.5.1).** Answered (the operator, 2026-11-18: "Ok
    on q26"): in the kinds catalogue (`kinds.json`, RFC-0016): each kind keeps general area hints
    and optional hints per site kind (`rooms_by_site`; a fridge at an office says break room), one
    catalogue for every robot; Mission Control reads it to show and edit the hints, it keeps no copy
    of its own. Built on branch `site-map` (explore), with a test.

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
- **The site's map only in the robot's navigator, or only in the Observatory's runs:** the
  navigator's map belongs to a run and a robot; the runs are a record, and the Observatory reads and
  does not command. A shared site needs one owner that outlives runs and several robots: Mission
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
  site's semantic map kept between runs, anchored to the dock in the simulator, stable object ids,
  objects named by the operator, the stored map owned by Mission Control; at a real site the robot
  must first recognise where it is, later), **C yes** (an object is a landmark at a landmark value
  of 0.7 or more), **D yes** (the camera record is `sighting`, not `look`). Changed, and why:
  - A consistency review found revision 1 behind the decisions. Fixed: the lines that still said
    firing was open, SQLite was not verified, the navigator API's process was open and miniview's
    name was open are now answered (§3.4.6, §3.7, §3.8, §5); the non-goals are re-cut (§2.3);
    RFC-0016 and ADR-0019 are in "Builds on".
  - New goal kinds, `not_found`, a result, several robots on one goal (§3.4); recognisers and
    localisation among the capabilities, with the rule (§3.3.2); sites, objects, rooms, naming (§3.5);
    the objects and rooms layers and the sighting resource (§3.6); the navigator API's new methods
    and the run key at goal start (§3.7); the Observatory link and the loop (§3.11); the VDA 5050
    and Open-RMF mapping, marked unverified (§3.12); a glossary (§1.1); the order rewritten (§4).
  - The requirements file gained O13 to O26 and a section for the decisions of 2026-11-18.
  - Not verified while writing: the VDA 5050 and Open-RMF specs (not read); the Observatory's page
    code and whether its drawing can be shared; that a navigator's object ids are not stable across
    runs (assumed not); the current `viewer/CONTRACT.md` field names.
- 2026-11-18 — Revision 2, after the operator's review (same revision number, status unchanged:
  the changes are the operator's answers, not a new proposal). Decided:
  - **Site and area replace home and room.** The operator: "there should be nothing hard-coded to a
    home ... it's a terrain ... we should support multiple terrains, and home is just one terrain
    being named", then "I'm okay that we adopt terminology site and area". A site is a named place
    robots work in, with a kind, its own frame and maps; several sites from the start, a robot at
    one site at a time; "Home" is one site in the library. An area is a part of a site (a room
    indoors, a zone outdoors); objects are in areas. `/homes/{h}` became `/sites/{s}`, "home frame"
    "site frame", `go_to_room` `go_to_area`. The catalogue keeps a general default and optional hints
    per site kind (§1.1, §3.5).
  - **A site library and an area library** in the page, API and MCP: the operator names sites, and
    within each names and manages areas ("I would name areas like my rooms, so I can manage
    those"): create, rename, draw an outline, merge, split; the robot never creates or suggests one
    (§3.5.3). Requirement O27.
  - **An exclusive control lock per robot, built in** (replacing the first answer to question 3,
    which was to ask `nxt-web` whether it is in use): "we should not allow two things to drive the
    same robot ... that's how two things should work together, by not being allowed to work
    together." A lease at the robot's own interface process, with an explicit release, expiry after
    the deadman time, and an operator takeover that is recorded (§3.3.3). Requirement O28. Open:
    where the NXT's lock lives until its bridge is settled.
  - **Q3 grows beyond this app.** The operator: "if people gather in a room, 5 laptops, 5 robots,
    and everybody can connect only to one ... like Bluetooth pairing ... you can drive only your
    robot you're allowed to connect to, and while you're connected, others cannot eject you ... beyond
    Lego, apply to ducks". Generalised in RFC-0017 (pairing, permission, exclusive control); here
    the lock stays the decided core and question 3 is answered in principle.
  - **"I agree with all"** of the proposed answers: questions 6, 7, 9, 10, 11, 12 (`find_all`
    dropped), 13 (`done` for an exploration that ends by its budget), 14, 15, 16, 17, 18, 19, 20, 21,
    22, 23 and 24 are recorded as answered in §5, each in the section it changes.
  - **Guardrails are first-class** (question 6; the operator: "we have to support that"): a goal is
    what to do plus its guardrails; three levels, robot, site and goal, merged, a goal adding and
    never removing; checked in the navigator, a broken one ends the run `stopped_by_guardrail`
    (§3.4.8). Requirement O29.
  - **Q7 is configurable** ("OK on Q7, but also configurable"): the rates are defaults, settable per
    robot and per client subscription (§3.2.2).
  - **Q9 and Q10 confirmed** ("yes on Q10, yes on Q9"), and with them a requirement the operator
    calls "super important": the Observatory and Mission Control both run as containers, so they
    run wherever he wants, easily (§3.13, O30).
  - Question 26 (where the per-site-kind hints live) was raised in this review and answered. Left
    open, smaller: movable and unseen objects in the merge (15),
    a moved simulator dock (22).
- 2026-11-18 — Revision 2, the operator on question 25 ("why would even a robot suggest an area?
  That's not the goal. The goal is that he can detect in which area he is ... I definitely don't
  want a robot to create areas", then "Yes, that's it"). Changed (§3.5.3, §3.2.1, §1.1, O27): an area
  is a region the operator defines (name, polygon outline, optional type); the robot never creates
  or suggests one; the accept-suggestion step and API row are gone. The robot's object votes are an
  area type guess, shown as information and used as a check on its position. "Which area am I in" is
  geometry once the operator has drawn the outlines. In the simulator a test site's areas are drawn
  from the scoreboard's true room outlines, so the answer and the guess are both measured. Question
  19 (regions from objects and walls) is replaced by this.
- 2026-11-18 — Revision 2, RFC-0017 accepted ("Take the advisor version, all is good feedback").
  Matching changes here (§3.3.3, §3.8, §5 question 3): the lease is tied to the connection, lasts
  10 to 30 s and is released when the connection drops; the deadman stays the safety stop; the gate
  never resends commands; on the duck, lease loss is `robot.stop` then a zero move; the holder is
  the process that sends `robot.move` (the navigator server for a goal, Mission Control for manual
  drive); a goal run ends `interrupted` on takeover and `cancelled` on STOP; a STOP latches; the
  MCP no-fire rule is enforced by Mission Control; the NXT's lock lives in `nxt-web`'s Controller
  (`/api/lock`); the first build runs in home-lab mode, with no pairing, keys, TLS or discovery.
- 2026-11-18 — Accepted, and the first slice built (eb6a560, `control/`, tests `make test-control`).
  The operator: "goal is to deliver all ideas we wrote down". What the RFC left open, and what the
  slice chose (each is open to the operator's correction):
  - **`must_not` names.** §3.4.1's example writes `["contact", "drop"]` and `stall`, §3.3.2's
    capability list `fall`, `drop_clearance` and `stuck`. The slice stores the capability names and
    accepts `drop` as `fall` and `stall` as `stuck`.
  - **The lock over HTTP.** A lease is tied to a connection, and an HTTP call has none. The lease is
    tied to a session id that `POST /lock` returns and every drive sends, as nxt-web's `/api/lock`
    does; "Mission Control's own name" is the `client` the caller gives. Release on disconnect does
    not exist over HTTP: expiry (20 s) covers it. Drive without a session is refused ("no lease, no
    motion").
  - **Merge and split of areas** (§3.2.1 names the calls, not the geometry). Merge folds `other` into
    the first area with the convex hull of both outlines unless the caller gives `outline`; split
    cuts by a line that crosses the outline in exactly two places and misses its corners, the area
    keeps the left half. An area a guardrail names is not deleted, merged away or split (a new half
    would escape it). Nested areas: the smallest holds the point.
  - **Association gates** (§3.5.2 says "the navigator's own rule"): 0.5 m, and 1.5 m for a unique kind,
    read from `ASSOC_M` and `UNIQUE_M` in `semantic_map.py` on the branch `explore-apartment`.
  - **The navigator's `seed`** (§3.7 says the site's objects) also carries the areas' outlines: a
    navigator cannot go to or stay out of an area without them.
  - **§3.3.2's rule** is applied as written to every goal that names an object or an area (so an area
    goal is accepted for a robot with a recogniser that is not localised in the site frame, which is
    doubtful: the outlines are in the site frame). `explore` needs a map, `inventory` a recogniser
    (§3.4.1's "Needs" column).
  - **A goal a robot cannot take is a run in the state `refused`** with the reason, not an HTTP error;
    an offline robot is an error (503) and creates no run (§3.2.1's two rules, read together).
  - **`explore`'s parameters** are `{area}` or `{site: true}`; `site` is the run's site, which is the
    robot's site (`PUT /robots/{id}/site`, an addition to §3.2.1) unless the run names one.
  - **The robot file** was JSON in a first format (since replaced, §3.3.1), and the slice depends on
    the duck package for the gate library (a path source, as nxt-web depends on the viewer package),
    which pulls
    `mcap` and `miniview` into Mission Control's environment.
  - **The fake robot's navigator** goes in straight lines, so a no-go area on the way is refused ("no
    path that avoids it") and its waypoints inside one are skipped; it confirms an object at two
    sightings and looks twice at each stop. The real navigator plans round a no-go area.
  - **Not checked here:** anything on a real robot, the simulator, a browser, the MCP server, Docker
    (`docker compose config` parses the compose files; no image was built or run), the stream under
    load beyond five clients, and the order of events across threads beyond what the tests show.
- 2026-11-18 — The page, area editing and site export and import built (920cc90). Choices, open to
  the operator's correction:
  - **The page duplicates a small 2D drawing** (question 14's proposal): a canvas of the robot's
    grid, the areas' outlines and the objects' boxes. It copies the Observatory's colour tokens, names
    and values, from `viewer/web/shell/shell.css` into its own `style.css`; a shared theme file does
    not exist, and Mission Control's page is served by another process, so it cannot link to one.
    The fonts are the system's (the Observatory ships Inter and JetBrains Mono as files).
  - **Plain files, no build, no library:** `web/index.html`, `app.js`, `style.css`, served at `/`
    and `/web/`. The page keeps no state the API does not have, except which robot is selected.
  - **Export is a JSON document, not files in folders** (§3.5.2 says "as files"): the page downloads
    it as one file. It holds the site, the operator's areas, the labelled objects and the
    guardrails; objects nobody named are left to the runs. **Import merges** into the chosen site
    (areas by name, replaced; a named object joins an unnamed one of its kind within the association
    gate, else is new and confirmed; a label already in use is skipped; guardrails added) and is all
    or nothing. The RFC does not say replace or merge; merge cannot lose the site's own work.
  - **Deleting an area takes two presses** on the page; the API deletes at once.
  - **The page test runs in the viewer's environment** (its Playwright and Chromium; `control/`
    has no browser dependency): `make test-control-page`.
  - **Checked in a browser now:** headless Chromium at 390 px and 1500 px, dark and light, on the
    fake robot. **Not checked:** a phone, another browser, a screen reader, a touch screen's tap
    (the test clicks), a real robot, a long-running page.
- 2026-11-18 — The MCP server built (62de2f0). The operator's answers: `control/` may depend on the
  duck-lab and miniview packages as path sources; the official Python `mcp` SDK is approved for
  `control/` only; the NXT lock covers file upload and delete (1ded610). Choices:
  - **`mcp` 2.3.0** (`uv add mcp` in `control/`): the lock gains 31 packages, annotated-types 0.8.0,
    anyio 4.16.0, attrs 26.1.0, cffi 2.1.1, click 8.5.1, cryptography 50.0.2, exceptiongroup 1.3.1,
    h11 0.16.0, httpcore2 2.16.2, httpx2 2.16.2, httpx2-jsfetch 1.0, idna 3.20, jsonschema 4.26.0,
    jsonschema-specifications 2025.9.1, mcp 2.3.0, mcp-types 2.3.0, opentelemetry-api 1.45.2,
    pycparser 3.12, pydantic 2.14.3, pydantic-core 2.50.4, pyjwt 2.15.1, python-multipart 0.0.34,
    pywin32 312, referencing 0.37.0, rpds-py 2026.9.1, sse-starlette 3.7.0, starlette 1.10.0,
    truststore 0.10.5, typing-extensions 4.16.0, typing-inspection 0.4.5, uvicorn 0.54.0. Three of
    them (exceptiongroup, httpx2-jsfetch, pywin32) are for other Python versions or Windows and are
    not installed on this machine. No locked package changed; the duck and viewer locks are
    untouched. The Dockerfile's `pip install ./control` reads no lock, so an image gets whatever
    `mcp>=2.3.0` resolves to on the day it is built.
  - **The server is a client of the HTTP API with an allow-list of 29 routes** (the page's rule,
    §3.2: no private path), over stdio. HTTP transport was not built: the RFC does not ask for it.
  - **What an agent may not do** (§3.8, O21, RFC-0017 §3.5.7, §3.5.3, RFC-0002 §3.5): fire (no
    tool, no route), take a robot another client holds (no tool; one client name, fixed by the
    operator), draw, change or delete areas, make or delete sites, import, set a site's guardrails
    or assign a robot to a site (the operator's; read only), run on a real robot unless the
    operator started the server with `--allow-real`. The last is this slice's reading of "real runs
    need the operator in the room"; §3.8 says it of the real duck, and no real robot exists yet.
  - **A departure from §3.2:** "the MCP server exposes every resource and action, not a subset
    (O11)". Writes on sites and areas (§3.2.1, §3.5.3) are left out on purpose, so the operator's
    areas stay the operator's. If an agent should draw areas, that is one more allowed route and
    tool.
  - **`nxt-web`:** the upload's session is the `session` query parameter (its body is the file); a
    delete's is in its JSON body. The page now takes the lock (acquire on the first drive, a
    keepalive every 5 s, release, who holds it in the header; its STOP stays open), so nxt-web
    enforces "no lease, no motion": with nobody holding the lock a call with no session is refused
    `no_lease`, as it is while another client holds it (`held`).
  - **The page test's flake** was found by running it under CPU load (2 of 6 runs failed): the test
    read the area list before the page had drawn it, and the two-press delete lived on the button,
    so a redraw disarmed it. Both fixed (16e5e7d); 8 of 8 passed under the same load.
  - **Not checked:** the MCP server with a real agent (Claude or another client) rather than the
    SDK's own client; the HTTP transport; the nxt-web lock against a real brick.
