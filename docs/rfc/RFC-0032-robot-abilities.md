# RFC-0032: Robot abilities, a generic model for what a robot can do and who drives it

**Status:** Accepted (the operator, 2026-11-28: all six questions of section 8 as recommended).
Nothing here is built.
**Date:** 2026-11-28
**Builds on:** [RFC-0002](RFC-0002-robot-brain.md) §3.6 (someone else drives: stop and report),
[RFC-0003](RFC-0003-robot-interface.md) §2.1 (`robot.do {skill}`),
[RFC-0014](RFC-0014-mission-control.md) §3.3 (the robot file, VDA 5050's factsheet, capabilities
as data), [RFC-0017](RFC-0017-robot-access.md) (the lease, STOP, the gate),
[RFC-0031](RFC-0031-learning-in-the-lab.md) §7 (the promotion rule).
**Asked by the operator, 2026-11-28,** after the
[gap analysis](../wip/MICRODUCK-GAP-ANALYSIS.md): "we have to deal with all these 8 items and
structure new additions with skills and new concepts well from the start, to be also generic at
some level since we can expect similar concepts with other robots, and then specialise for
Pollen."
**Evidence:** the gap analysis (Pollen's repos at microduck 4024f6ee, microduck_rl 0daab160;
ours at 1f2066b) and, read for this RFC, RFC-0002 §3.6, RFC-0003 §2.1, RFC-0014 §3.3.1-3.3.2,
`apps/mission-control/src/mission_control/robots.py` (the adapter protocol, lines 278-303) and
`duck.py`. What I did not verify is in section 9.

## 1. The problem

Mission Control knows a robot as "something that moves, stops and reports health". The duck is
far more: Pollen ships skills, emotions, voice, LEDs, slots of networks, an updater, a lifetime
record and three other ways to drive it (gap analysis §1). We use none of it, and four of the
gaps are weaknesses of what we offer now, not only missing features:

| # | Gap or opportunity | Why it matters |
| --- | --- | --- |
| 1 | **Our STOP and lease do not cover the whole robot.** A pad, an NFC tag or Pollen's app can drive the duck; the robot keeps the last writer | Mission Control shows "held by us" while someone else drives. RFC-0002 §3.6 asked for the check; it is not built |
| 2 | **We do not know what the robot runs.** No version, update state, loaded network | A run record cannot say which walker it ran on; a result is not reproducible |
| 3 | **Skills are an empty concept.** Both robots' `skills` are `[]`; the NXT's `fire` bypasses Mission Control through nxt-web's own lock | The one irreversible action we have is outside the control centre's lease and log |
| 4 | **The simulator's fidelity is not recorded.** Our walk is 0.13 m/s asked 0.3; Pollen's docs disagree on whether the body uses BAM | Every sim number in the learning arc carries an unknown |
| 5 | **One catalogue of abilities across robots** | Pollen's tools are per robot; a fleet view is ours to offer |
| 6 | **Vetting another party's network** | Pollen: "nothing a stranger publishes is verified by anybody"; we have simulation, frozen sets and a promotion rule |
| 7 | **One lifetime record per robot** | The robot's own record (the vet book) beside our runs and approvals |
| 8 | **Generic pages, not per-robot remotes** | The page is built from capabilities (RFC-0014 §3.3.2); new robots get the same cards |

## 2. Principles

1. **Generic first, specialised in the adapter.** Each concept below has one shape in Mission
   Control's contract, the API, the MCP tools and the page. A robot's adapter maps it to that
   robot's own calls. A robot that lacks a concept leaves it out, and the page offers only what is
   there (RFC-0014 §3.3.2).
2. **Borrow names where a standard has them.** VDA 5050 already has *actions* with
   `actionType`, `blockingTypes`, `actionScopes`, `pauseAllowed`, `cancelAllowed` (RFC-0014
   §3.3.1). We use them; ROS 2 actions (goal, feedback, result, cancel) shape the run of one.
3. **Everything that makes a robot do something passes the gate.** Lease, STOP, log, as for
   `robot.move` today (RFC-0017). Reading needs no lease.
4. **Read before write.** Every concept starts read-only; changing the robot (loading a network,
   a setting) comes after, behind approval.
5. **Measured, not declared.** As with `online`, what the robot reports wins over what a file
   says; the robot file holds only what the robot cannot tell us.
6. **No code of ours on the robot** (RFC-0002's non-goal, unchanged). All of it is host side.

## 3. The six concepts

### 3.1 Facts: what the robot is and runs (gaps 2, 4)

A read-only record, fetched on connect, on demand and at the start of every run:

```json
{"read_at": "...", "identity": {"model": "microduck-beta", "serial": "..."},
 "software": [{"name": "robotd", "running": "0.14.2", "installed": "0.14.2"}],
 "interface": {"model_api": 2},
 "update": {"state": "idle", "available": null},
 "behaviours": [{"slot": "walk", "artefact": {"origin": "official",
   "repo": "pollen-robotics/microduck-policies", "revision": "v3", "sha256": "..."}}]}
```

- **Into the run record.** The run's build identity gains the facts' digest, so two runs on
  different walkers never read as the same system. In the simulator the facts add the body model
  (MJCF source, commit, sha256) and the actuator model (BAM or position actuators), which answers
  gap 4 for every sim result from then on.
- **Shown** on the robot page's Overview, with "read 3 s ago".
- **Duck:** `robot.modelApi`, `update.status`, `robot.policies`, `system.*` identity.
  **NXT:** firmware version, battery, the programs on the brick. **Fake:** fixed values.

### 3.2 Control source: who is driving (gap 1)

Every state frame is checked for who moved the robot last and whether its own autonomy is on:

```json
{"source": "robot-brain-412", "ours": true, "autonomous": false, "pad": "connected"}
```

- **The rule** (RFC-0002 §3.6, now built): during a goal run, `ours: false` or `autonomous: true`
  stops the goal with the end `interrupted`, reason `driven_by <source>`, and an alarm. Resuming
  needs the operator. Outside a run the page shows "driven by pad" on the robot's card.
- **A pad is a control source like any other.** Phase 1 only sees it (gap analysis §2 option A).
  A pad that drives *through* Mission Control (option B, the browser's Gamepad API on our lease;
  or D, a pad client of the gate) is a later, separate choice.
- **Duck:** `move.source`, `autonomous`, `pad.status`, NFC mode switches. **NXT:** an on-brick
  program running (RFC-0003 §2.1, `robot.autonomous`). **Fake:** settable, for tests.

### 3.3 Actions: what the robot can be asked to do (gaps 3, 5)

One concept for a duck's kick, an emotion, a sound, and the NXT's shot. An action is named,
bounded and asked for; it is not a goal (no place, no navigator).

| Field | Meaning |
| --- | --- |
| `actionType` | the name (VDA): `kick_left`, `bow`, `quack`, `fire` |
| `kind` | `motion` (moves the body), `expression` (emotion, sound, light; the body may move in place), `effector` (fires, grips) |
| `blockingTypes` | VDA: `NONE`, `SOFT`, `HARD`: whether driving continues during it |
| `irreversible` | ours (RFC-0014 §3.3.1): asks for a confirmation, never run by an agent without the operator's switch |
| `duration_s`, `params` | expected length; a small parameter schema |
| `source` | `robot` (reported by it) or `file` (the robot file names it) |
| `backed_by` | the artefact that does it, when there is one (section 3.4) |

- **The catalogue** is the robot's report merged with the robot file. It is shown on the robot
  page and offered to the MCP server and to RFC-0030's missions as steps.
- **Running one** is `POST /robots/{id}/actions/{actionType}`: it takes the lease (or uses the
  caller's), passes the gate as `robot.do`, records an *action run* with its own id, state
  (`running`, `done`, `failed`, `cancelled`) and log line, and STOP cancels it. The gate already
  treats `robot.do` as needing a lease (`libs/gate/tests/test_gate.py:95-96`).
- **The NXT's fire moves under it.** `fire` becomes an `effector` action, `irreversible`; nxt-web
  calls it through Mission Control instead of its own lock. The MCP server keeps "no fire":
  irreversible actions stay off the agent tools.
- **Duck:** `robot.skills` → catalogue, `robot.do` → run, emotions and sounds as `expression`.
  **NXT:** `fire`, on-brick programs. **Fake:** a `wave` that takes 2 s, for tests.

### 3.4 Artefacts and slots: what implements a behaviour (gap 2, opportunity 6)

A robot's default behaviours (Pollen's *slots*: walk, stand, sitstand...) and its actions are
implemented by **artefacts**: a network file, an on-brick program, our own `learned@<sha8>`.

```json
{"kind": "onnx", "origin": "official" | "community" | "local" | "ours",
 "repo": "...", "revision": "...", "sha256": "...", "contract": {"obs_len": 61, "action_len": 14}}
```

- **Phase 1 reads them** (they are part of the facts). **Changing a slot** (Pollen's
  `robot.loadPolicy`) is a write that needs the lease, passes the gate, and is allowed only for an
  artefact with an approval (section 3.5).
- **Ours is an artefact too.** Our navigation residual is a host-side artefact behind the
  `local_controller` slot of the navigator; the same record names it, so one page lists what
  drives a robot at every level, theirs and ours.

### 3.5 Approvals: when an artefact may run (opportunity 6)

Pollen's safety boundary for a community network is clamps, a fall reflex and a shape check. Ours
adds evidence, on the shape RFC-0031 §7 already decided for our own models:

1. **Contract check:** the artefact's manifest against the robot's facts (shape, `model_api`,
   robot model). A mismatch is refused, as Pollen refuses it.
2. **Rehearsal in the simulator** through the goal's `sim_first` path.
3. **Frozen sets in the harness:** the artefact is a system in robotics-evals, scored on the
   sets for its slot (walking, avoidance, the action's own), against the current artefact.
4. **The operator signs** an approval record: artefact sha256, robot model, slot, evidence links.
5. **Only then** can a slot load it, on that robot model. `allow_community` is set by the
   adapter for that one load, never left on.

The approval record is generic: an NXT program or one of our learned controllers takes the same
path. The simulator's walking shortfall (gap 4) limits what step 2 proves; the record says so.

### 3.6 The robot record: one lifetime view (opportunity 7)

Per robot, one timeline: the robot's own record where it has one (the duck's vet book: falls,
hours, repairs), our runs and action runs, the facts as they changed (versions, slots), the
approvals, and the alarms. Read-only; built from what Mission Control and the Observatory already
keep plus the robot's report. **Duck:** `robot.vetbook`. **NXT, fake:** our history only.

### 3.7 Robot settings (part of opportunity 8)

The robot's own configuration (the duck's video quality, pad gains) is a seventh concept only
when the robot exposes it as data. Pollen has no configure call: `robotctl configure` edits a file
on the board (gap analysis §1). So phase 1 shows the robot's settings read-only where a robot
reports them, and changing them is an open question (section 8, Q4).

## 4. Where it lives

```text
page / MCP / missions        cards and tools built from capabilities (3.1-3.6)
Mission Control API          GET facts, GET actions, POST actions/{name}, GET record
                             approvals store; action runs beside goal runs
adapter protocol             facts(), control_source(state), actions(), do(name, params),
  (robots.py:278)            behaviours(); each optional
  duck adapter               robot.modelApi, update.status, robot.policies, move.source,
                             pad.status, robot.skills, robot.do, robot.vetbook
  nxt adapter                firmware, programs, fire
  fake adapter               all of it, settable, for tests
gate (libs/gate)             robot.do and robot.loadPolicy: lease, STOP, log
```

The robot file's `capabilities` gains `actions` (VDA's `mobileRobotActions` inside the factsheet
already has the slot) and an `artefacts` hint for robots that cannot report their own. A concept
absent from both the file and the robot's report is absent from the page.

## 5. The page: cards, not remotes

The robot page gets cards that render from data, the same for every robot:

| Card | Tab | Shows |
| --- | --- | --- |
| Facts | Overview | identity, versions, update state, read time |
| Driven by | Overview, robot card | the control source; red when not ours |
| Actions | a new Actions tab | the catalogue; run, with a confirmation for irreversible ones; the action runs |
| Behaviours | Modules | the slots and the artefact behind each, ours and the robot's |
| Record | a new Record tab | the lifetime timeline |

A duck-only page is justified only for something no other robot has; none of the above is.

## 6. Phases

| Phase | What | Needs a real robot? |
| --- | --- | --- |
| 1 | Facts (3.1, with the sim body and actuator model in the run record); control source with the stop rule (3.2); the action catalogue read-only (3.3) | No: fake and duck-sim (which runs Pollen's daemons) |
| 2 | Running actions through the gate (3.3), the NXT's fire moved under it; the Actions and Behaviours cards | No for the duck in sim; the NXT's move is checked at the brick by the operator |
| 3 | The robot record (3.6); robot settings read-only (3.7) | No |
| 4 | Approvals and slot loading (3.4-3.5), after R7 has shown what "approved" means for our own models | Sim first; the real duck after R8 |
| 5 | A pad through Mission Control (option B or D), if wanted | Yes |

Phase 1's control-source rule is the one safety item: it lands before any real duck run.

## 7. Alternatives considered

- **A duck console tab that proxies Pollen's tools.** Fast, but per robot, outside the lease and
  the log, and it does not help the NXT or the EV3.
- **Use Pollen's RPC names as the generic contract.** They are good names but one vendor's; VDA's
  are a standard the robot file already borrows.
- **Skills as a kind of goal.** A goal has a place and a navigator; an action does not, and
  missions (RFC-0030) need both as steps.
- **Leave it to `robotctl` over ssh.** Free, but nothing is logged, leased or visible.

## 8. Questions for the operator (answered 2026-11-28: all as recommended)

1. **Q1, the order:** phases 1 to 5 as above, phase 1 first because it carries the safety rule?
   Recommended: yes.
2. **Q2, the NXT's fire under Mission Control in phase 2,** nxt-web calling through the gate?
   Recommended: yes; the operator checks it at the brick.
3. **Q3, the pad:** see only (option A) until a real duck is here? Recommended: yes.
4. **Q4, robot settings:** read-only until Pollen has a configure call, or write through
   `robotctl configure` over the link? Recommended: read-only.
5. **Q5, approvals before R7?** Recommended: no; phase 4 waits for R7, so the rule is tested on
   our own models first.
6. **Q6, the simulator's actuator model (gap 4):** record it in phase 1 and ask Pollen which one
   `duck-body` runs? Recommended: yes; the measurement of the walk with BAM is a separate task.

## 9. Not verified

- That duck-sim answers `robot.skills`, `robot.policies`, `robot.vetbook`, `update.status` and
  publishes `move.source` and `pad.status`: read in Pollen's protocol crate (gap analysis §1),
  not called.
- The fields of Pollen's replies; the JSON in sections 3.1-3.4 is our shape, not theirs.
- That nxt-web can call through the gate without a change to its lock semantics; I did not read
  `apps/nxt-web` for this RFC.
- How RFC-0030's mission steps would take an action; only the principle is stated.
- Which artefact fills the duck's walk slot in our simulator today.
- VDA 5050's `instantActions` semantics beyond the factsheet fields RFC-0014 already uses.
