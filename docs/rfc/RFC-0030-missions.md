# RFC-0030: Missions, planning as a module and Mission Control as the executor

**Status:** Proposed, revision 2 (2026-11-26), after the advisor's
[review](../wip/RFC-0030-REVIEW-2026-11-26.md), which the operator approved folding in. For the
operator's decision. Nothing in it is built. Findings are cited as (review C1) and so on.
**Date:** 2026-11-26
**Decided by the operator on 2026-11-26 (recorded here, not open):** the platform keeps two
modes, named "manual" and "auto" (section 6.1); auto works as plan, review, then execute
step by step (6.2); the auto-mode spike goes ahead as proposed (6.7); the sequencing of
section 7 (the carve-out and plan contract before MVP 2, the spike as a side lane during it,
auto mode as a feature after it, with its own safety review).
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (Mission Control, goals in section 3.4),
[RFC-0018](RFC-0018-lab-projects-and-seams.md) (projects and seams),
[RFC-0024](RFC-0024-one-platform.md) (one origin),
[RFC-0025](RFC-0025-mvp1-to-mvp2.md) (MVP 2; it reserves RFC-0026 to 0029 for its follow-ups, so
this is 0030), [ADR-0007](../adr/ADR-0007-run-file-format-2.md) (the run file),
[TECH-REVIEW-2026-11-26](../wip/TECH-REVIEW-2026-11-26.md).
**Related, not built on:** [RFC-0005](RFC-0005-missions.md), an earlier "Missions" (section 13).
**Asked by the operator, 2026-11-26:** "should we separate mission planning into its own
app/module and use Mission Control like config management only? Mission planning could be
really complex". Later the same day: "I also want to explore AI-driven mission planning that
can react to signals and information, replan, and keep driving the robot in steps, sort of
evolutionary planning". We agreed to draft this RFC: a module now, an app later.
**Evidence:** every `file:line` below was read on 2026-11-26 in the `mission-control` worktree;
revision 2 re-read each one at c33f136 (the review was at fb884b2). What I did not verify is in
section 12.

## 1. Problem

Mission Control does two jobs in one package. It decides what the robot should do (goal kinds,
goals from words, an optional LLM) and it does it (the lock, the run, the guardrails, STOP).
The first job can grow without limit: sequences, several robots, schedules, an LLM that plans,
and now a planner that watches the mission and replans while the robot drives (section 6). The
second job is the safety-critical one and must stay small enough to read in an afternoon.

Today they share files and imports. `core.py` (724 lines) calls `planner.plan` at line 712 and
`goals.validate` before every run (line 311); `goals.py` holds the goal kinds next to the run
states and the rehearsal rule. Nothing is wrong yet: the planner's docstring says "the output is
data, not action ... The planner has no path to drive, stop or fire" (`planner.py:10-12`), and it
is true because the file is small and one person reads it. That is a habit, not a rule the
build enforces. A planner that gains a loop, a model client with tools, a scheduler and a fleet
view will not stay that small, and then the claim needs a wall.

This RFC asks where the wall goes, and when planning moves out of the process.

## 2. Where it stands

All counts are lines of `apps/mission-control/src/mission_control/`, at c33f136 (2026-11-26).

| File | Lines | What is in it |
| --- | --- | --- |
| `goals.py` | 220 | Goal kinds and schema (`KINDS`, `validate`, `_params`, `_done_when`), run states, the rehearsal rule, capability check, start pose |
| `planner.py` | 175 | Phrase matcher (`match`), `LlmPlanner`, `load_planner`, `read_back`, `plan` |
| `guardrails.py` | 89 | Vocabulary and limits (`_LIMITS`), `normalise`, `merge` (union, the stricter limit wins) |
| `sites.py` | 468 | Sites, areas, objects, the inventory, site guardrails, import and export, run write-back |
| `core.py` | 724 | Robots, STOP, the goal library, run start, groups, rehearsal, sync, run views, `plan` |
| `api.py` | 675 | Routes; goals and runs 288-319, `POST /plan` 321-325 |
| `mcp_server.py` | 367 | Agent tools; sim only (`:98-102`), no `sim_first: false` (`:123-127`) |

Where each piece belongs, by function:

| Piece | Where | Class | Why |
| --- | --- | --- | --- |
| `goals.KINDS`, `FIELDS`, `DEFAULT_DONE_WHEN`, `validate`, `_params`, `_done_when` (13-155) | `goals.py` | Planning | The shape of a goal; no robot is needed to check it |
| `goals.version` (156) | `goals.py` | Planning, and the executor | The checksum of a goal's content; the rehearsal rule keys on it |
| `goals.normalise_folder` (163) | `goals.py` | Config | The goal library's folders, kept by Mission Control |
| `ACTIVE`, `TERMINAL`, `STATES`, `SUCCESS` (16-20) | `goals.py` | Execution | The run's states, from the navigator contract |
| `NO_VERDICT_ANOMALIES`, `REHEARSAL_MAX_AGE_S` (38, 43) | `goals.py` | Execution | Run rules |
| `capability_refusal`, `not_checkable` (172-205) | `goals.py` | Both | Pure; the planner may ask in advance, the executor must ask again |
| `start_pose` (207) | `goals.py` | Execution | It belongs to the run, not the goal (its own docstring) |
| `Context`, `match`, `LlmPlanner`, `load_planner`, `read_back`, `plan` (29-175) | `planner.py` | Planning | The whole file; data in, data out |
| `guardrails._LIMITS`, `NAMES`, `normalise`, `normalise_list` (1-69) | `guardrails.py` | Planning vocabulary | A plan carries guardrails; its schema is data |
| `guardrails.merge` (71-89) | `guardrails.py` | Both: moves with `_LIMITS`, called by the executor | It cannot stay behind without `_LIMITS` (`:83-86`), and the reviewer's dry run needs it; "a plan never loosens" is still enforced by the executor calling it (section 4.1, review M5) |
| Areas, objects, inventory, `area_at` (117-317) | `sites.py` | Planning data | What a goal is about; the planner reads it |
| Site CRUD, dock, robot assignment, site guardrails, import and export (39-116, 247-263, 318-398) | `sites.py` | Config | Written by the operator and read by the executor |
| `merge_run_objects` (404) | `sites.py` | Execution | Run results write sightings back into the map |
| `core.plan` (703-715) | `core.py` | Planning | Builds the context from sites and robots, calls the planner |
| `create_goal` to `retire_goal` (213-258) | `core.py` | Config | The goal library: stored, versioned, edited |
| `_start_run`, `_create_and_start`, `_rehearsal`, `_sync`, `_end_run` (293-600) | `core.py` | Execution | Lock, merge, refusal, real-run key (`:479`), navigator start, events |
| `_start_group`, `_refresh_group` (339-442) | `core.py` | Execution today | One goal on several robots; the first piece of allocation |
| `stop`, `stop_all` (165-197) | `core.py` | Execution | Outside any planner |
| `RobotConfig.real_run_refusal` (`robots.py:172`) | `robots.py` | Execution | The real-run key; the robot file's `allow_real_runs` |

By line count the planning side is about 700 (goals 110 of 220, planner 175, guardrails
vocabulary 70, `core.plan` 13, sites' read side about 200) and the execution side is about
900 (`core.py` run lifecycle, run states, the gate in `robots.py`). Config is the rest. These
are my counts from the line ranges above; a different reading of "Both" moves them by tens of
lines, not hundreds. The review counts the move itself at about 480 source lines and 336 test
lines; I did not recount either.

RFC-0014 section 3.4 already treats a goal as a kind plus a validated schema, and 3.4.5 made the
planner "an independent module with one function" (`planner.py:1`). The seam exists in the
design; this RFC makes the build enforce it.

## 3. The cut

Three roles, one rule: the side that decides what to do never touches the robot.

- **Planning decides what to do.** Input: the site's areas and objects, the robots'
  capabilities and profiles (read only, as plain data), the operator's words or a form.
  Output: a validated plan, which is data.
- **Execution runs a plan.** Mission Control takes a plan and runs it under the lock, the merged
  guardrails and STOP, and emits run events. It validates the plan again on arrival: it never
  trusts that a planner did.
- **Config stays in Mission Control.** Robot files (`allow_real_runs` among them), profiles,
  sites' CRUD and the goal library are written by the operator and read by the executor on the
  safety path. A shared library for them would add a second writer's worth of API with no second
  user. The planner receives a snapshot as arguments, as `planner.Context` does today
  (`planner.py:34`, built at `core.py:703-712`). If a second program must read config, that is
  the day to share it (RFC-0018's own test for a split, section 5.1, "Ready to split when").

What the planner never gets: a robot adapter, the gate, a session token, the lease, the robot
file's key. What it may get: an LLM key, which is why it must also be unable to pass that key
anywhere but the model's endpoint (section 11).

## 4. Proposal: a module now

### 4.1 The library

A new library `libs/missions`, distribution and module `missions`, standard library only like
`libs/gate`. A library is declared by a `pyproject.toml` with a `src/<module>` folder, and
joins the build in four places, all of which must change together (review, "The cut"):

- `MODULES` (`scripts/check_boundaries.py:26`) and `ALLOWED` (`:46`); the checker's rule works
  once both name `missions`, and `libs/missions/src` is then found by `projects()` (`:96`);
- a `[tool.uv.sources]` path entry in Mission Control's `pyproject.toml` (`:23-28`);
- `libs-sync` (`Makefile:84`), whose list of libraries is fixed (`runfile simhost gate runner`),
  or `make test-libs` has no environment for `missions`;
- `LIBS_TESTS` (`Makefile:80-82`), for `make test-libs` (`:86-90`).

It holds: the goal schemas (the planning half of `goals.py`), the guardrail vocabulary and
`merge`, the planner (matcher, `LlmPlanner`, read-back), the plan document and its checksum, the
reviewer's rule checks, and mission sequences. It holds no storage, no HTTP server and no
timers.

The boundary, enforced by the checker, not by a docstring:

```python
"missions": set(),                       # ALLOWED: imports no package of the lab
"mission_control": {"robotgate", "runfile", "missions"},
```

The checker fails a build in which `missions` imports `robotgate`, `labrunner`, `simhost`,
`duck_lab`, `mission_control` or `runfile` (RFC-0018 section 10: libraries import only
libraries; here, none). It reads imports, not behaviour (its docstring says so), so section 11
names what it cannot see. Today `goals.py` imports `runfile.navcontract` (`goals.py:8`) for the
run states; those stay in Mission Control, which is why `missions` can import nothing.

**Where `merge` goes (review M5; the operator decides, my recommendation is A).**
`merge` reads `_LIMITS` (`guardrails.py:83-86`) to keep the stricter limit, so it cannot stay
behind when the vocabulary moves.

- **A (recommended): `merge` moves with `_LIMITS`, unchanged.** Same code, same `LEVELS`
  (`guardrails.py:16`: robot, site, goal), same tests. Mission Control imports it and calls it on
  the safety path exactly as today, so the executor still computes the guardrails of every run
  itself and trusts no review. The reviewer's dry run (6.2) and the plan-level fold below call
  the same function, so there is one rule and no copy. A "a plan never loosens" test stays in
  Mission Control's tests, against the imported function. Cost: the rule that decides what a robot
  may do lives in a library; a change to it is a change to the executor, and review must say so.
- **B: `LIMITS` becomes public in `missions` and `merge` stays in Mission Control.** Keeps the
  rule in the executor's package. The reviewer, which is in `missions`, then cannot dry-run it
  without a copy or a callback, and a copy is two rules.

**Plan-level guardrails add no fourth level.** A plan-level `guardrails` list is folded into
each step's `must_not` when the plan is validated, using the same function (one level's entries
of one name already keep the stricter limit, `guardrails.py:71-89`). `LEVELS` stays as it is, and
section 12's "out of scope" (no change to the guardrail rules) holds. What is lost is where a
guardrail came from: a plan's shows as the goal's in `from`.

**Errors (review M6).** `goals`, `guardrails` and `planner` raise `ApiError`, which carries an
HTTP status (`errors.py:4-24`; `planner.py:123` raises 502). The library raises its own
`PlanError(code, message)` and no status. Mission Control wraps it at each call site into the
`ApiError` it means (`invalid` for a bad goal, 502 `planner_failed` for a model that did not
answer). A `PlanError` that escapes would reach `api.py`'s handler, which catches `ApiError` only
(`api.py:634`) and answers 500, so a test pins that no call site lets one through.

### 4.2 The plan document

Mission Control depends on `missions`, not the other way round. Between them runs one document,
versioned like every contract here (RFC-0018 section 5.3: a contract changes only by adding).

```json
{
  "plan_version": 1,
  "mission": "m17",
  "site": "flat",
  "target": "sim",
  "approval_mode": 1,
  "budgets": {"steps": 12, "minutes": 40, "llm_cost_usd": 0.5, "distance_m": 60},
  "provenance": {
    "source": "words",
    "text": "go to the fridge, then take an inventory of the kitchen",
    "planner": "matcher",
    "model": null,
    "prompt_version": null,
    "created_at": 1795700000.0,
    "site_stamp": "sha256:9a1c...(full digest of the snapshot the planner was given)"
  },
  "goals": [
    {"key": "a", "after": [],
     "goal": {"name": "to the fridge", "kind": "go_to_object",
              "params": {"label": "fridge"}, "must_not": ["contact"]},
     "needs": {"robot": null, "capabilities": ["navigator", "recognisers"]}},
    {"key": "b", "after": ["a"],
     "goal": {"name": "kitchen inventory", "kind": "inventory",
              "params": {"areas": ["kitchen"]}},
     "needs": {"robot": null, "capabilities": ["navigator", "recognisers"]}}
  ],
  "binding": {"a": "duck-sim", "b": "duck-sim"},
  "guardrails": [{"name": "max_speed", "mps": 0.2}],
  "on_failure": "stop",
  "checksum": "sha256:<the full 64 hex characters>"
}
```

- **`mission`, `target`, `approval_mode`, `budgets`** (review, "The plan contract"). `mission` is
  an id Mission Control gives the mission when the operator starts it; a replan keeps it and
  gets a new checksum. `target` is `sim` or the real one, for the whole plan. `approval_mode` is
  1 to 3 (6.5) and is the operator's, never the planner's. `budgets` are the mission's: steps,
  wall minutes, LLM cost, distance (6.5).
- **`goals[]`** hold goals as `goals.validate` shapes them, plus `key`, `after` (the order and
  dependencies; a list of keys, no cycles) and `needs`: a named robot, or the capabilities a
  robot must list (`capability_refusal`'s vocabulary, `goals.py:172-198`). `needs` is advice:
  the executor binds a robot and checks again. `sim_first` is a goal field and stays per goal.
- **`binding`** is filled by Mission Control, not the planner, before review: each step's robot
  (review H2). A `needs.robot: null` is resolved to a named robot there. A rebind later (the robot
  went offline, another takes it) is a new checksum, so a new approval. A mission may bind several
  robots one after another; the stop latch of 6.5 covers all of them.
- **`guardrails`** at plan level are folded into each step's `must_not` at validation (4.1), so
  a plan can only add and `merge` sees nothing new.
- **`provenance`**: `words`, `llm` or `form`, with the text, the planner, and for an LLM the
  model and the prompt's version. An LLM plan is marked; it is never trusted more.
  **`site_stamp`** (review M2) is a digest of the snapshot the planner was given. The review
  proposed the site's `updated_at` plus an object count; read against `sites.py`, that is not
  enough: `sites.updated_at` moves on rename, retire and site guardrails only (`sites.py:85`,
  `:93`, `:259`), an area edit moves the area's own `updated_at` (`:186`), and the objects table
  has none (`store.py:36-40`), so a moved object changes neither. A digest of the areas, objects
  and site guardrails the planner received catches all of them.
- **`checksum`** (review H2): a sha256 of the canonical JSON of the whole document without the
  field, the full 64 hex characters. It is not `goals.version`: that drops `name`, `folder` and
  `sim_first` by design, because the rehearsal rule keys on what the robot does (`goals.py:159`),
  and it keeps 16 hex characters (`:160`). A plan approved and then edited to `sim_first: false`
  must not keep its checksum, and this one covers `target`, `binding`, `approval_mode`,
  `budgets` and every goal field. Execution recomputes it; a plan edited after approval is
  refused.
- **`on_failure`**: `stop` (default) or `continue`. What each end does is the table below.

**Step outcomes (review H1).** A step is a goal run, and it ends in one of the navigator
contract's ends (`navcontract.ENDS`, which `goals.TERMINAL` is, `goals.py:17`). The mission
reads them so:

| The step ends | The mission |
| --- | --- |
| `reached`, `done` (`SUCCESS`) | Goes to the next step whose `after` is met |
| `refused`, `failed`, `not_found`, `timeout`, `stalled`, `stopped_by_guardrail` | `on_failure` decides: `stop` ends the mission `failed`; `continue` marks the step failed and skips its dependents; in auto mode this is a replan trigger (6.4) |
| `cancelled`, `interrupted` | The mission ends `stopped`. It never replans, whatever `on_failure` says |

`cancelled` and `interrupted` are the ends a STOP produces (`core.py:192-201`), and a run cannot
tell a STOP from an operator's cancel (`cancel_run`, `core.py:686`). Treating both as a stop is
the safe reading: a mode 3 mission that replanned after a STOP would drive on.

**`after` with `on_failure: continue`.** A step whose `after` names a failed or skipped step is
skipped, and says so; a step with no failed ancestor still runs.

**Partial results.** `merge_run_objects` runs during a step, whenever the navigator reports
objects (`core.py:623-634`, called from `:68`), so the sightings of a step that later fails are
already in the site. A failed step is not a rolled-back one. This also changes the site's
snapshot (6.4).

**`sim_first` on a whole plan.** The rule stays per goal, as built (`core.py:532-553`): a real
run is rehearsed when the same `goals.version`, for the same site, ran as expected with a verdict
on a simulator twin of the same registered robot within 24 hours. Running the plan on the
simulator twin first therefore rehearses each step, and a plan is not one unit to it. For auto
mode on a real robot the consequence is: a replanned step is a new goal version, so it is
refused on the real robot until it has been rehearsed. That is the rule, with no exception for a
"small" replan.

The operator still confirms: `confirm_required: true` stays on what `plan` returns
(`planner.py:174`), but it is data, not a gate (4.5 makes the gate), and nothing runs until the
mission is approved and started.

### 4.3 How execution reports back

Execution adds nothing planning can use to act; it reports. The existing bus events already
carry `goal-run` with a state and `run_key` (`core.py:477`, `:517`). A plan run adds:

- `plan-run` events: `{mission, plan, state, step}`; the states are `queued`, `reviewing`,
  `awaiting_approval`, `running`, `replanning`, `done`, `failed`, `stopped` and `refused`. The
  three new ones are what auto mode adds to a plan of ordered goals (review);
- a `mission_id` column and the step's `key` on every goal run row, and the same on its
  `goal-run` events. `client` stays what it is: the token's identity (`api.py:76-82`), not a
  place for `mission:<id>`. The store gains the column by a migration (`SCHEMA_VERSION` is 4 and
  `MIGRATIONS` takes a store up one version at a time, `store.py:10-13`, `:85-90`); I did not
  check what the migration costs a large store;
- the same run view as today (`GET /goal-runs/{id}`, `CONTRACT.md:123`): decisions, anomalies,
  progress and result.

Mission Control stores the mission in its own database next to `goal_runs`: the plans, the
review and approval records, the mission's decisions and its heartbeat (6.6). A planner that
dies loses nothing the executor needs.

### 4.4 What moves, in steps

1. Create `libs/missions`; move `planner.py`, the planning half of `goals.py`, the guardrails
   vocabulary and `merge`, and their tests (`test_goals.py` 139 lines, `test_planner.py`
   197 lines) with no change of behaviour. Mission Control imports from it. The checker's tables
   and its self-test gain the new unit, and so do `libs-sync` and `LIBS_TESTS` (4.1). Two tests
   need a decision: `test_planner.py:142-144` pins the planner's imports by name and moves with
   the planner; `test_goals.py:130-137` checks the run states and the page's list of ends, which
   stay in Mission Control, so it stays and the file is split.
2. Add the plan document, its checksum and the validation in `missions`, and in Mission Control
   the mission state machine of 4.5 with its routes (`POST /plans`, then approve and run under
   `/plans/{id}/...`). `POST /goal-runs` and `POST /goals/{id}/runs` are not touched (review M7).
3. Sequences: order and `after`, run by Mission Control one goal at a time. Nothing about two
   robots yet; the group code at `core.py:339` stays as it is.

Steps 1 and 2 change no behaviour a robot can feel, except that step 2 adds a way to start
runs, which the state machine must guard. Step 3 is the first new one.

The import sites that change (review M4; `api.py` imports none of goals, planner or guardrails):

| Site | Line | Import | After the move |
| --- | --- | --- | --- |
| `core.py` | 14 | `goals, guardrails, planner` | Imports from `missions` and keeps the run-state half of `goals` |
| `cli.py` | 16 | `planner.load_planner` | Imports from `missions` |
| `telemetry.py` | 19 | `goals` | Stays: it uses the run states |
| `robots.py` | 41 | `guardrails` | Imports `normalise` from `missions` |
| `sites.py` | 9 | `guardrails` | Imports `normalise` from `missions` |
| `tests/test_goals.py` | 9 | `goals, guardrails` | Split, as above |
| `tests/test_planner.py` | 17 | `planner` | Moves with the planner |
| `tests/common.py` | 104 | `goals.TERMINAL` | Stays |

I read the import lines; I did not run the move, so a cycle or a missed site would show only in
`make ci-fast`.

### 4.5 The mission state machine, in Mission Control (review H3)

Approval is not a flag in an answer. Mission Control holds the mission's state and refuses what
the state does not allow, whoever calls:

```text
planned -> bound -> reviewed(checksum) -> approved(checksum, mode) -> step k running
   ^                                                                       |
   |   replanning <---- a trigger (6.4) -------------------------------+  | step ends
   +-- a changed plan is a new checksum and goes back to planned         v
                                        done | failed | stopped   (outcome table, 4.2)
```

- **A step starts only through the machine.** Its start path requires the state `approved` or
  `running`, a plan checksum equal to the approved one, the step's `after` met, and the stop
  latch of 6.5 clear. A plan edited after approval, or a replan not yet approved, starts nothing.
- **The approval is a record, and only a named identity makes one.** It stores the checksum, the
  `target`, the bound robots, the approval mode, who and when. Mission Control takes an approval
  only from a token identity the operator has named as an approver (`Ctx.client()`, `api.py:76`,
  gives the token's client when there is one). The MCP server's token is never one. A server that
  does not require tokens (`require_tokens` defaults to `False`, `api.py:661`) takes the caller's
  own word for its name, so it cannot hold an approval: auto mode needs tokens on. That last
  point is mine, not the review's; it follows from `client()`.
- **The MCP guards are not a defence at this layer.** `target` (`mcp_server.py:98-102`),
  `sim_robot` (`:104`) and `no_opt_out` (`:123-127`) run in the MCP server's process, so a client
  that calls the HTTP API directly never meets them. What an agent may do is therefore decided in
  Mission Control by identity: the approval above. The MCP tool for plans must also apply all
  three guards to every goal of a plan, not only the first, so an agent cannot get a real robot
  or an opt-out past them by putting it in step three.
- **A plan of one is optional.** A single goal keeps its routes. A plan is for a sequence, and
  for what auto mode runs.

## 5. When to split into its own process

A module can become an app when one of these holds, not before:

- **Long-running or heavy planning:** optimisation, simulation sweeps, a search over many
  plans that would take a core from Mission Control's 512 MB container (RFC-0024 section 2.1).
- **Fleet scheduling** across sites or robots, which has a clock of its own.
- **Its own UI** that is not a panel of Mission Control's page.
- **A different release cadence or owner:** planner changes weekly, the executor changes with
  a safety review.
- **A model that needs a GPU or a long context**, so the host differs.

Then the plan contract becomes an HTTP or MCP API (the shape of `mcp_server.py` already is an
out-of-process client with fewer rights than the operator), the planner holds no lease, and
Mission Control stays the only process that can start a run.

Splitting early costs:

- **An extra hop and an auth boundary between plan and go.** Today the planner is called in
  the process that holds the lock. As an app it needs a token, and a token that can start a
  run is a second key to a robot.
- **Who holds the lease.** The only answer is Mission Control. A planner that held it for a
  mission would make the planner a safety component.
- **A running mission when the planner dies.** With a module, process death is one fate; with
  an app, the current goal finishes or hits its budget and nothing issues the next step. That
  must be designed (section 6.5), not discovered.
- **RFC-0024's one-origin reasoning.** That RFC kept two backends behind one origin only where
  a different failure domain justified it (the Observatory must stay up when the robot stack is
  down). Planning has no such reason today: it is down exactly when Mission Control is.

## 6. Two modes: manual and auto

The operator decided on 2026-11-26 (not open questions): the platform has two modes, named
exactly **manual** and **auto**, and keeps both. Auto is explored, not built: section 6.7 is
its spike.

### 6.1 Manual and auto

- **Manual** is today's way. The operator makes goals by hand, through forms or words, and
  starts each one. It stays first-class: the module of section 4 serves it (schemas, the
  phrase matcher, the optional LLM that proposes goals, `confirm_required`), `POST /goal-runs`
  and `POST /goals/{id}/runs` stay as they are, and no auto feature may make it slower or less
  safe.
- **Auto** is closed-loop AI planning: a planner that watches the mission, replans, and keeps
  driving the robot in steps ("sort of evolutionary planning", the operator's words). It works
  like a coding-agent harness: a planner writes the plan, a review checks it, and execution
  proceeds one step at a time, replanning when the world differs from the plan.

Both modes end in the same place: Mission Control starting a run under the lock, the merged
guardrails and the real-run key. Auto changes who proposes the next goal, not who may start it.

### 6.2 Auto mode: plan, review, execute step by step

1. **Plan.** The planner (rules or an LLM) writes the whole mission plan as data in the plan
   contract of section 4.2: the steps, each with its goal, its success check (`done_when`) and
   its budget (`goals.py:23`, `DEFAULT_DONE_WHEN`, `DEFAULT_BUDGET_MIN`), the order, and the
   mission's budgets. Nothing moves. Mission Control then binds the robots (4.2), which fixes
   the checksum.
2. **Review.** The plan is reviewed before anything moves, twice over:
   - an **automated reviewer** checks it: the merged guardrails (a dry run of
     `guardrails.merge`, so a plan that would loosen one is rejected, not trimmed), reachability
     in the site's map, the robot's capabilities (`capability_refusal`), the budgets, and the
     risky steps (a real target, a step near a `no_go_area`, a long chain of steps). The first
     reviewer is rule checks; a second model, with its own prompt and not the planner's, may
     join later. A reviewer can pass, ask for changes or reject; it never edits the plan. Its
     rules run on the validated plan, never on the model's raw answer.
   - the **operator's approval**, as the mission's approval mode says (section 6.5).
   The review's verdict and findings are recorded against the plan's checksum.
3. **Execute, one step at a time.** Mission Control runs one step as a goal, through the same
   entry as a hand-made goal. The loop then observes the result and the signals that came with
   it. If the remaining plan still holds, it proceeds to the next step. If it does not, the
   planner replans, and **the changed plan goes back through review** (the automated reviewer
   always; the operator per the approval mode) before the next step runs.

The planner may not skip stage 2 for a replan because "it is a small change": the checksum
changed, and a review is of a checksum.

### 6.3 The loop, who does what, what is recorded

```text
        operator's words, a form, a goal to explore
                         |
                         v
     +--------------+  plan   +-------------+  verdict, findings
     |   PLANNER    |-------->|  REVIEWER   |-----+
     | (module:     |         | (rules, then|     |  rejected or changes asked:
     |  rules/LLM)  |<--------| a 2nd model)|     |  back to the planner
     +------^-------+  asks   +-------------+     |
            |                       | passed       |
            | replan                v              |
            |               +--------------+       |
            |               |   OPERATOR   |<------+
            |               | approval mode|
            |               +------+-------+
            |                      | approved plan (checksum)
            |                      v
            |        +--------------------------+     STOP, STOP ALL
            |        |  MISSION CONTROL         |<--- (outside the loop,
            |        |  executor: validates,    |      always win, end it)
            |        |  lock, guardrails, key,  |
            |        |  runs ONE step           |
            |        +------------+-------------+
            |                     | run events, result, alarms, anomalies,
            |                     v sightings, map, battery, link, notes
            |        +--------------------------+
            +--------|  observe: does the       |
             no      |  remaining plan hold?    |--- yes: next step
                     +--------------------------+
```

| Stage | Who does it | What is recorded |
| --- | --- | --- |
| Plan | Planner (module `missions`) | The plan document: goals, order, target, budgets, provenance (words, model, prompt version, site stamp), checksum |
| Bind | Mission Control | The robot of each step, in the plan; the checksum is taken after it |
| Review | Reviewer (module), then the operator | A review record per plan checksum: reviewer and its version, verdict, findings; an approval record: checksum, target, robots, mode, who, when |
| Execute a step | Mission Control | A goal run as today (decisions, anomalies, progress, result) with `mission_id` and the step's `key` on its row and events |
| Observe | The mission runner (section 6.6) | The inputs seen: event ids and a summary of each |
| Decide (hold or replan) | Planner | A `mission_decision` row in Mission Control's store: the inputs, the plan's checksum before and after, the reason, the model and prompt version, the next step |
| Review of a changed plan | Reviewer, then the operator | A new review record and approval, as in stage 2 |
| Stop | Operator, Mission Control | A STOP on the run as today, the mission's latch (6.5) and its end state `stopped`; no auto-resume |

**Where the record lives (review M8).** The first draft proposed a new record kind in the run
file. That is the wrong store: Mission Control may not write run files (the checker forbids its
runfile imports, `check_boundaries.py:70-74`), and a mission's decisions happen between runs,
when no run is open. Instead:

- Reviews, approvals and mission decisions stay in Mission Control's store (the tables of 4.3)
  and are served through Mission Control, which the Observatory already proxies at `/control/`
  (`observatory/server.py:28-29`).
- The spec Mission Control sends to `goal_start` already carries a `goal_run` object
  (`core.py:503`: id, name, kind, robot, site). It gains `mission`, `plan` (the checksum), `step`
  and `why {rule, reason, values}`: why this step, now. The navigator writes the object into the
  run's metadata (`nav/server.py:153-182`; today it forwards only id, name, kind and robot to
  `RunLog`, so it must forward the new keys) and writes one `event` carrying that `why` as its
  `decision` at goal start. The run format already has this shape: `{rule, reason, values}` is
  `validate.py:108-115`, and the Decided tab lists a run's events and shows each `decision`
  (`shell.js:459-471`), and adds an event kind it has not seen to its filters (`shell.js:508`,
  `:561`).
- That is one additive field of the navigator contract and no change to ADR-0007. The check of
  the run's `goal_run` metadata reads only an integer id and a name (`validate.py:47-50`), so
  extra keys pass it; I did not run a run through it.

### 6.4 Replanning triggers

After a step, the loop replans (and the changed plan is reviewed) when:

- a step ends in a failure end of the outcome table (4.2): a goal fails or is refused (a refusal
  carries a reason a planner can read). `cancelled` and `interrupted` are not triggers: they end
  the mission `stopped`, and mode 3 never replans after a STOP (review H1);
- a new object or area is seen: a sighting the plan did not know;
- an alarm or anomaly arrives (`robot_guard`, `rtf_low`, a stuck robot);
- a budget is crossed: time, battery, distance, steps, or LLM cost (section 6.5);
- the site changed since the plan was reviewed (review M2): the digest of the snapshot, taken
  again at each step start, differs from the plan's `site_stamp`. Reachability was reviewed on
  that map. A mission's own sightings change it too (`merge_run_objects`, 4.2), so a step that
  finds something new triggers a replan by this rule as well as by the second one;
- the operator edits the goal or adds a note.

A replan happens at a step boundary. A trigger that arrives mid-step cancels the step only
through the normal path (`cancel_run`, `core.py:686`), and only if the plan's step allows it. A
step cancelled that way ends `cancelled` and so ends the mission `stopped`, by the outcome
table; a mid-step trigger that should only replan therefore waits for the boundary, and the plan
says nothing else is allowed. I flag this as open in section 12.

### 6.5 Authority and safety: the loop proposes, Mission Control executes

The same rule as the cut of section 3:

- Every step goes through the **same validation, guardrails, lease and real-run key** as a
  hand-made goal: `goals.validate`, `guardrails.merge`, `capability_refusal`,
  `real_run_refusal` and the rehearsal. A step can never loosen a guardrail. The executor
  validates again and does not trust the review.
- **STOP and STOP ALL are outside the loop and always win.** They are `core.stop` and
  `stop_all` (`core.py:165`, `:171`), reachable without the loop's help. A STOP ends the loop.
  It does not resume on its own; the operator starts a new mission.
- **The mission stop latch (review C1). Safety rule: after a STOP, no step of a mission that
  could move the stopped robot starts, in any state of the runner.**
  A STOP ends a mission only by assertion unless something holds it. Between steps there is no
  active run: `_after_stop` acts only when `rt.active` is set (`core.py:192-201`), and the gate's
  `_stop_from` ends the lease (`libs/gate/src/robotgate/__init__.py:232`) while `_acquire` grants
  a new one at once, with no memory of the STOP (`:201-211`; `_stopped_at` gates only
  `motion_without_lease`, for `MOTION_GRACE_S`, 1 s, `:30`, `:297`). The runner's next step would
  start. So:
  - Mission Control sets a **latch** inside `core.stop` and `stop_all`, before they return, and
    before they call the gate, so that a robot that does not answer still latches
    (`core.py:175-179` shows `stop_all` catching a failing robot);
  - its scope is every mission whose robots include the stopped one (the bound robots, and for a
    step not yet bound the robots its `needs` could bind), and every mission for STOP ALL;
  - the step-start path takes the same lock, checks the latch and starts the run inside one
    critical section, so a STOP and a step start cannot interleave;
  - the latch is Mission Control's state, not the runner thread's, so it holds when the thread
    is wedged in a model call (6.6). It is cleared only by the operator starting a new mission,
    never by the thread and never by time;
  - the outcome table (4.2) is the second line: a run a STOP ended is `cancelled`, which ends
    the mission `stopped`, and Mission Control's `stop` and `stop-all` bus events say which STOP
    it was.
- **The first version runs on the simulator only,** like an agent today
  (`mcp_server.py:98-102`). A real robot needs the operator's decision in the room.
- **Approval modes**, chosen per mission by the operator:
  1. *Confirm each step:* nothing runs until a person says so.
  2. *Confirm when the plan changes:* steps already approved run; a replan waits for a yes.
  3. *Autonomous within a budget:* the loop runs on its own until a budget ends it. The
     automated review still runs in every mode. **Mode 3 is a rule in code (review L1):** it
     is refused unless the plan's `target` is `sim` and every bound robot has `variant == "sim"`,
     checked when the approval is recorded and again at every step start, the way
     `mcp_server.sim_robot` reads the robot's profile (`:104-112`). Section 9 question 5 recommends
     it; this makes it so.
- **Budgets:** maximum steps, wall time, LLM cost and distance. On exhaustion the loop stops
  issuing and asks; it never extends its own budget. An LLM auto mission also needs a per-mission
  cost ceiling in `planner.json` and does not start without one (review, question 3).
- **A dead planner.** If the process that holds the loop dies, the current goal ends under
  the executor's rules (its budget, its guardrails, STOP) and no next step is issued; the robot
  holds. The mission's state is in Mission Control's store, so the operator sees where it
  stopped. The thread dying while the process lives is a separate case, 6.6.

### 6.6 Does the loop fit inside Mission Control's process?

Recommendation: **yes for the first version, as a module the executor runs, not as a process.**

- Mission Control owns a small mission runner: a thread per mission that holds the mission's
  state, calls the planner's and the reviewer's pure functions from `missions`, and submits
  each step through the same entry the HTTP API uses. The thread calls no adapter and holds no
  lease; the run does, as today.
- The functions are pure (state in, steps or verdicts out); only a model call blocks, with a
  timeout (`LLM_TIMEOUT_S`, `planner.py:25`). A stuck model blocks one thread.
- A mission dies with Mission Control, which fails safe (section 6.5). A separate process would
  need a rule for the dead planner and a token that can start a run.

**The thread's failure rules (review M1).** "Dead planner" covers the process, not the thread: a
thread can die while the process lives, and the mission would stay `running`.

- The runner's loop catches as the robot loop does (`_loop`, `core.py:100-109`: the known
  errors are emitted, any other exception is said once with its traceback), with one difference:
  an exception ends the mission `failed` with its reason and the loop does not go on. A thread
  that cannot say it failed is covered by the heartbeat.
- The runner stamps a **heartbeat** on the mission row at every pass and before and after a
  model call. A mission with no active step and a stale heartbeat is shown as that (a wedged or
  dead runner), not as `running`. The staleness limit is a number to choose; a model call can
  last `LLM_TIMEOUT_S` (30 s by default).
- A mission found `running` when Mission Control starts is ended `failed` with the reason that
  it was restarted: nothing resumes a mission (my addition; it follows from "a mission dies with
  Mission Control").
- None of this lets the thread hold a safety property. The latch (6.5) is what stops a step,
  and it does not depend on the thread being alive.

The loop becomes the first reason for its own process when a trigger of section 5 fires: model
latency or cost that no longer fits a thread, a search that wants cores, or a GPU host. Even
then it is an API client with the rights of the MCP server (sim only unless the operator says
otherwise), and Mission Control stays the only starter of runs. Either way, the planner never
holds the lease and never talks to a robot directly.

### 6.7 A spike first (decided: yes, as proposed)

The operator agreed to a bounded spike before any platform commitment, structured around the
plan, review, execute-step loop of section 6.2:

- **Scenario:** explore the apartment in the duck simulator, replanning on new sightings.
- **Planner:** rules first (plan a sweep of the known areas; replan when a new area or object
  is seen; go to the nearest unvisited), then an LLM through `LlmPlanner`'s client, same
  scenario, same budgets.
- **Reviewer:** rule checks first (the dry-run merge, reachability, capabilities, budgets,
  risky steps). A second model only if the rule checks miss something the spike shows.
- **Executor:** Mission Control as it is, on the simulator, one step at a time through its
  existing run entry, approval mode "confirm each step" at first.
- **Measure:** reach and coverage of the map, time, steps, refused steps, reviews that
  rejected or asked for changes, STOPs and edits, LLM calls and cost, and the decision
  record's usefulness (can a person read why it went to the fridge second).
- **Before the first LLM run (review):** capture tokens and cost. The cost measure cannot be
  taken today: `LlmPlanner.plan` reads the model's answer and discards its `usage`
  (`planner.py:120-121`). This is a small change to the planner, and it goes in first.
- **Out of the spike:** a real robot, several robots, a UI, a scheduler.
- **Size:** S to M, a note in `docs/wip/`, throwaway code outside `libs/` if the RFC is not
  accepted.

It needs one thing more than today: a way to feed a run's events back into the planner.
Mission Control's `GET /events` stream already offers it (`api.py:467`).

### 6.8 Evaluate in the simulator first

An auto mission runs on the simulator (`sim_first`) and on replayed runs before a real robot.
To compare planners, a scored scenario set: for each scenario, reach (did it), time,
interventions (operator edits and STOPs), refused steps, reviews that failed, and cost. The
planners compared are rules, an LLM, and search. The challenge course (RFC-0008) is the
existing scoring pattern; whether a scenario set reuses its verdicts or defines its own is
open.

## 7. Sequencing, and the relation to MVP 2 (RFC-0025), decided

The operator confirmed this sequencing on 2026-11-26: it is decided, not open. Mission-level
planning is not among MVP 2's steps (RFC-0025 section 6, steps 0 to 10 are
robots, hosts, profiles and navigators). The work splits in three, by what each needs.
Manual mode is unaffected throughout.

| # | What | When | Depends on | Size |
| --- | --- | --- | --- | --- |
| 1 | The `libs/missions` carve-out (section 4.4 steps 1 and 2) and the versioned plan contract. A plan is how a sequence or an auto mission runs; manual mode keeps `POST /goal-runs` as it is, and a plan of one goal is optional, never required | **Before MVP 2**, as a step before RFC-0025's step 1, together with the technical review's two refactors | Nothing; guarded by `make ci-fast` and the goal tests. The carve-out adds `missions` to `MODULES`, `ALLOWED`, `libs-sync` and `LIBS_TESTS` (4.1) | S to M |
| 2 | The auto-mode spike (section 6.7): explore the apartment in the duck simulator, replanning on new sightings; rules planner and rule reviewer first, then an LLM. Token and cost capture before the first LLM run | **During MVP 2**, as a bounded side lane off the critical path; it stops at its measures and reports | Nothing from steps 1 to 5a; the duck simulator and Mission Control as they are | S to M |
| 3 | Auto mode as a feature: the mission runner, the review stage, the decision record, approval modes | **After MVP 2** | The written robot interface (RFC-0025 step 1); the scan and map in the run (step 8), so the decision record is one run-format change, not two; a second robot, so plans are shown not to be duck-shaped (step 5b or 6); a safety review before an AI drives a real robot, like step 10's, which covers the stop latch (6.5, C1) and the server-side approval (4.5, H3) | L |

Why 1 comes before MVP 2. It is cheap now: about 480 source lines and 336 test lines move, four
source import sites change (4.4), and it does not collide with RFC-0025
steps 1 to 3. The first draft
argued that it touches `core.py`'s run start once together with the technical review's refactors
(`TECH-REVIEW-2026-11-26.md`, "Readiness for MVP 2": the adapter surface as a `Protocol` with one
contract test, and one frame and scale owner). The review found that a weak reason: those
refactors touch `robots.py` and `duck.py`, not `_start_run`. The reason is that it is small,
that it sits on a seam the technical review already asks to settle before MVP 2, and that it
costs less now than after RFC-0025 step 3 (the navigator split) builds on today's layout.
RFC-0026 writes the adapter surface (RFC-0025 line 363); the carve-out does not change the
adapter, so the two do not collide. The guard is `make ci-fast` (which includes `make
lint`, hence `check-boundaries`, and `test-control`) and the goal tests (`test_goals.py`,
`test_planner.py`, `test_sim_first.py`, `test_core.py`).

Why 2 runs during MVP 2. It needs none of the steps it runs beside, so it costs the critical
path nothing but attention, and what it measures decides whether step 3 of this table is
worth its size and shapes the plan document's `step` field and the decision record before
anything is built on them. Its code is throwaway until the RFC is accepted.

Why 3 waits. Each dependency is real: without the interface contract the loop's observations
have no stable shape; the scan and map are what a mission's decisions mostly refer to, and
the run format should change once; one robot proves a duck-shaped plan, not a plan; and a
planner that can drive a real robot is a safety component with a review of its own.

## 8. Alternatives considered

- **(a) Keep it as it is.** Cost: nothing now. Trade-off: the safety claim in `planner.py`'s
  docstring rests on one reader's attention; every new planning feature (a loop, a scheduler,
  a model with tools) lands in the package that holds the lock. Right while planning stays at
  175 lines; it will not.
- **(b) A separate app now.** Gives the planner its own release and failure domain. Costs the
  section 5 list at full price before any trigger: a second token that can start a run, a
  dead-planner rule, a second container, a second set of contract tests, and nothing to put in
  it yet beyond 700 lines. RFC-0024 rejected two origins for the same kind of reason.
- **(c) Mission Control as config only, execution moved into the planner app.** Rejected. It
  puts the planner's complexity on the safety path: the lock, the guardrail merge, the
  real-run key and STOP would live in the process that also holds a model client, a search and
  a scheduler. The part that must stay small would become the part that grows.
- **(d) A module (recommended).** Planning in `libs/missions`, execution and config in
  Mission Control. The build enforces the wall (section 4.1), the executor stays small, and the
  split to an app later is a transport change, since the plan contract already exists as a
  document. Cost: one new library and its table entry, a small amount of churn in imports, and
  the discipline of a plan document where a function call used to do.

## 9. Questions for the operator

Each with options and a recommendation. The answer to any of them can be "none of these". Under
each, "Reviewer:" is the advisor's answer (the review, "The open questions"); the question stays
the operator's.

1. **The module's name.**
   - A: `missions` (this RFC's name; the plan is a mission).
   - B: `planning` (what it does, but a verb that invites more than plans).
   - C: `goalkit` (what it holds today, but a kit has no boundary).
   - **Recommendation: A.** The module holds plans, and a mission is the word the operator uses.
   - **Reviewer:** A, agree. The name clash with RFC-0005 is question 7.
2. **Do sites' areas and objects belong to missions or to config?**
   - A: config; Mission Control keeps `sites.py` and the planner receives a snapshot.
   - B: the module takes the read side (areas, objects, `area_at`) as types.
   - C: a third library, `sites`, both depend on.
   - **Recommendation: A.** Execution writes to sites (`merge_run_objects`, `set_dock_if_unset`),
     so they are not the planner's data. Revisit at C when a second program needs them.
   - **Reviewer:** A, agree; the site snapshot stamp goes in the provenance (4.2, M2).
3. **Does the LLM planner stay optional and off by default?**
   - A: yes; off unless `planner.json` exists (as `planner.py:7-9` says now), the matcher always
     on.
   - B: on when a key is present in the environment.
   - **Recommendation: A.** A model that costs money and can be wrong should be asked for. The
     auto mode (section 6) additionally needs its budgets set in the file.
   - **Reviewer:** A, agree; an LLM auto mission also needs a per-mission cost ceiling in
     `planner.json` and refuses to start without one (6.5).
4. **The spike's measures and stopping rule.** The scope is decided (6.7); what ends it is not.
   - A: stop at the measures of 6.7 and write the note; the operator decides on step 3.
   - B: also stop if the LLM planner's cost per mission passes a figure the operator names.
   - **Recommendation: B.** Name the figure before the first LLM run.
   - **Reviewer:** B, plus a date or session cap on the spike itself; if the rules planner alone
     meets the coverage target, the LLM is measured as a delta.
5. **The default approval mode of an auto mission.**
   - A: confirm each step.
   - B: confirm when the plan changes.
   - C: autonomous within a budget.
   - **Recommendation: A as the default, and A for the real robot and the first runs of any
     new planner; B once a planner has a record in the scenario set; C only on the
     simulator.**
   - **Reviewer:** A by default; C only on the simulator, enforced in code (6.5, L1); B requires
     the scenario set's record to be a stored artefact.
6. **Does the auto loop run in Mission Control's process first (section 6.6)?**
   - A: yes, a runner thread; its own process when a trigger fires.
   - B: its own process from the start, as an API client.
   - **Recommendation: A.** It fails safe, adds no token that can start a run, and the pure
     planner and reviewer functions make B a transport change later.
   - **Reviewer:** A, with the thread rules (6.6, M1) and the latch (6.5, C1) in Mission
     Control, not in the thread.
7. **How do this RFC and RFC-0005 relate (new in revision 2; section 13)?** A proposal, not a
   decision.
   - A: this RFC stands on its own for now; RFC-0005's loop is revisited when flotilla has a
     robot host. Section 13 sets out how the two would meet.
   - B: this RFC yields: approvals and promotion go through flotilla from the start.
   - C: merge the two into one RFC.
   - **Recommendation: A**, with the naming and the approver hook of section 13 written down now.
   - **Reviewer:** not asked. The review's header notes that RFC-0030 must say how the two relate
     before the name `missions` is fixed.

## 10. Consequences

- A library `libs/missions`, a row in the checker's tables, and an arrow
  `mission_control -> missions` in RFC-0018's picture; `libs-sync` and `LIBS_TESTS` gain it.
- `planner.py`, the planning half of `goals.py`, the guardrail vocabulary and `merge` leave
  Mission Control's package. `core.plan`, `core.create_goal` and the HTTP and MCP routes stay.
- A plan document with a version, a full-digest checksum and provenance. A contract test pins it.
- Mission Control gains a mission state machine (4.5), a stop latch (6.5), a `mission_id` column
  with a store migration and, later, a mission runner.
- The navigator contract gains additive fields in the `goal_start` spec's `goal_run` and one
  event at goal start (6.3). ADR-0007 does not change.

## 11. Risks

- **An import wall is not a behaviour wall.** The checker reads imports only. A module with
  only the standard library can still open a socket to a robot's HTTP port by a string in a
  config. The rule that stops it is that the module receives no robot address, no token and no
  session: a review check on what the runner passes in, not something the build proves.
- **The LLM key.** It sits in the module's process. The model client takes the key as an
  argument and its only network call is the model's base URL (`planner.py:112-130`); a test
  pins that the client calls nothing else.
- **A prompt injection through free text (review M3).** The first draft named "a sighting".
  An object's `kind` is a closed vocabulary; its `label` is not: it is typed by the operator
  (`sites.py:295`) or imported (`:339-372`). The free text the model reads is: the labels,
  a refusal's reason, an anomaly's `summary` (`core.py:580`; `robots.py:317` writes one), and
  the operator's notes. Any of it can say "go to the stairs". The defence has layers: the model's
  output is held to the schema (`goals.validate` refuses an unknown goal field or kind,
  `goals.py:119-124`, and `planner.plan` puts a refused goal in `dropped`, `planner.py:172`); the
  reviewer's rules run on the validated plan, not the raw answer; the guardrails and `no_go_area`
  have the last word; and approval mode 1 shows the operator each step. Not a complete defence;
  named so it is not forgotten.
- **Churn.** Two files move and 336 lines of tests with them (`test_goals.py` and
  `test_planner.py`, the first split); four source import sites change (4.4). A step that can
  be done wrong and be seen red in `make ci-fast` at once.
- **Approval by identity is only as strong as the tokens.** A server without tokens cannot hold
  an approval (4.5), so auto mode needs `require_tokens` on.

## 12. Not covered

- **Nothing here is built or run.** Every line number is from reading the files on
  2026-11-26. The line counts per class in section 2 are my reading of ranges; I did not run a
  tool over them. The advisor ran no test, checker, simulator or Mission Control either; C1 is
  read from code paths, not reproduced against a running gate, and I did not reproduce it.
- **Not verified:** that moving the goal schema out of `goals.py` leaves no import cycle
  (`goals.py` imports `guardrails` and `errors`, `planner.py` imports `goals` and `errors`; the
  library's `PlanError` (4.1) removes the shared `errors.invalid`, but I did not move the code to
  see); how `api.py` would map every `PlanError` code to a status; that the navigator forwards
  the new `goal_run` keys and the Decided tab shows the new event well (6.3); what the schema
  migration costs a large store; whether the gate lets Mission Control see a STOP sent to it
  directly; what `make ci-fast` costs after the move; the navigator's lease acquisition in
  `goal_start` (the review assumed per goal from RFC-0017 and the gate code, and so do I).
- **A STOP that skips `core.stop`.** The latch (6.5) is set by Mission Control's own `stop` and
  `stop_all`. A STOP sent to the gate by another client of it, or the robot's own deadman, ends
  the lease and the run (`cancelled` or `interrupted`, so the mission is `stopped`), but between
  steps nothing latches the mission and the next step would take a new lease. I did not find how
  Mission Control would learn of such a STOP; the review's C1 does not cover it. It must be
  closed before step 3 of section 7.
- **Not decided:** the sequence semantics beyond `after` (loops, conditions, timers); how
  multi-robot allocation fits the plan document (`needs` names one robot or a capability list,
  bound in sequence; `_start_group`'s `share` modes at `core.py:339` are not mapped to it);
  scheduling; whether a mid-step trigger may cancel a step without ending the mission `stopped`
  (6.4: today `cancelled` always does, so a mid-step replan waits for the boundary); the plan
  document's storage and retention; the heartbeat's staleness limit; MCP tools for plans and for
  the closed loop (the agent's rights follow `mcp_server.py`'s rules until decided, and 4.5 adds
  the per-goal guards).
- **Not covered:** a real robot under a closed loop; several robots under one loop; learning
  from past missions (the "evolutionary" part of the operator's phrase, beyond the scenario
  set of section 6.8); the cost model of LLM calls; a fleet view; any UI for plans; the
  planner's quality, which only the spike can say; the legal and safety review of an
  autonomous loop on the real Burger, which belongs with RFC-0025 step 10's safety review.
  Also not read by the advisor and not by me: the Observatory proxy's auth, RFC-0025 sections 3
  and 7 to 10, the duck and NXT adapters, `scripts/test_check_boundaries.py`.
- **Out of scope:** changing the guardrail rules, the lock, STOP or the real-run key. This RFC
  moves planning away from them and touches none. Moving `merge` unchanged (4.1) is not a change
  to the rule.

## 13. Relation to RFC-0005

[RFC-0005](RFC-0005-missions.md) (Proposed, revision 3, 2026-11-14, written before the Mission
Control of RFC-0014) is also called "Missions", and the first draft did not cite it.

**What RFC-0005 proposes.** A mission loop across two other projects, for the robot brain
(RFC-0002), not for Mission Control. flotilla decides: a mission is a case, and policy,
approvals and an autonomy ladder (shadow, propose, auto) decide whether the real duck may run it,
promoted per mission type by the operator on evidence. The simulated duck is a second flotilla
host capped at `auto`, and every mission rehearses there before it runs on the real duck, with
the rehearsal's score attached to the approval. eval-harness measures whether the simulator
predicts the real robot. Its non-goals include flotilla in the motion loop and several robots in
one mission.

**Where it overlaps this RFC's auto mode.**

- **Who decides.** RFC-0005: flotilla's policy and the operator's promotion of a mission type.
  This RFC: the operator's approval mode, chosen per mission, in Mission Control (6.5). Two
  places could grant "run it". Mode 3 here and `auto` there are close and not the same: one is
  per mission and budgeted, the other is per mission type and earned.
- **The simulator rehearsal.** RFC-0005 rehearses a whole mission on a simulator host first. This
  RFC's rule is per goal (4.2, `core.py:532-553`), and a plan of ten goals asks ten rehearsals.
- **The word.** There "a mission" is a flotilla case with a spec; here it is a plan run with a
  state machine. A module called `missions` and a case called a mission will be confused.

**Recommended reconciliation (a proposal for the operator to decide; question 7).** Keep this RFC
as the platform's own mission planner and executor, simulator first and one robot, and treat
RFC-0005's flotilla as an optional outer policy layer: later it can be a named approver identity
that Mission Control's approval route (4.5) accepts, and its autonomy ladder maps onto the
approval modes (shadow is a plan reviewed and not run; propose is mode 1 or 2; auto is mode 3,
which this RFC limits to the simulator). Adopt RFC-0005's rule that a mission is rehearsed before
the real robot as this RFC's whole-plan rehearsal when auto mode reaches a real robot, and write
down now that the two RFCs use "mission" for different things so the name `missions` does not
decide the question by accident. Nothing in RFC-0005 is changed here; revisiting it is the
operator's call.
