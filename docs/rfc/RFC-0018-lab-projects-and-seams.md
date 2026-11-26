# RFC-0018 — The lab's projects, their seams, and how to split robotics-lab later

**Status:** Built (2026-11-19): one repository, restructured in full into apps, libraries and
robots with package seams and a boundary check (the operator, 2026-11-18: "5C since this is
more/less big shape we are after"; 2026-11-19: "Yes to all 10 and go for phase 2"), together with
the Observatory rename. §10 records what was built and where it differs; §1–§9 are the proposal as
decided on 2026-11-18, kept as written. Earlier on 2026-11-18 it was parked: "make another RFC with
idea to split and everything else, and we're gonna come back to that later."
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (§3.13 containers, question 10 licence and
splitting), [RFC-0017](RFC-0017-robot-access.md) (the gate),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0009](RFC-0009-miniview.md) (miniview, now the Observatory),
[ADR-0007](../adr/ADR-0007-run-file-format-2.md) (the run file) and
[ADR-0019](../adr/ADR-0019-semantic-map-records.md) (the semantic map in a run).
**The first version said nothing here was to be done yet;** the lab then worked as it was,
and §10 is the move.

## 1. Why

The operator, 2026-11-18: "as we are evolving this so fast, very soon I'm gonna be thinking how to
separate this out of the lab into little projects with little readmes … What are the seams? Is this
one thing? Is this two things?"

Today robotics-lab is one repository with several programs in it. Some of them are already one
program each (the NXT web UI). Some are tangled (the duck's code writes its runs by importing the
Observatory's package). A split done without knowing the seams cuts in the wrong place and breaks
things. This RFC names the seams first, so the split, when it comes, is only moving folders.

Two decided facts frame it: the licence is MIT (RFC-0014 question 10, confirmed), and the
Observatory and Mission Control must each run anywhere from one compose file (RFC-0014 §3.13, which
the operator calls "super important"). A split must keep both true.

## 2. What is in the repository now

Read from the two worktrees on 2026-11-18: `mission-control` (the Observatory and the Mission
Control RFCs) and `explore` (branch `explore-apartment`: the duck's navigator and world model).

| Folder | Package | What it is |
| --- | --- | --- |
| `viewer/` | `miniview` | The Observatory: run store, index, API, two pages, video export, adapters for the duck and the NXT (`adapters/duck.py`, `adapters/nxt.py`), `CONTRACT.md` |
| `duck/` | `duck-lab` | The navigator and explorer (`nav/`), the world model (`world_model/`: objects, semantic map, `kinds.json`), the challenge course (`challenge/`), recording and replay, `sim/` probes and scenes |
| `nxt/` | `nxt-lab` | The NXT web UI, NXC programs, toolchain, its own `Dockerfile`, README, lock file and tests |
| `robots/` | none | Robot models: duck, EV3 Spike3r and Track3r, NXT Shooterbot, LDraw converter |
| `nav2/` | none | A ROS 2 Dockerfile for comparison (RFC-0015, ADR-0018); its first line says nothing of ours depends on it |
| `docs/` | none | RFCs, ADRs, PRDs, one `mkdocs.yml` |
| `scripts/` | none | `check_workflows.py`, `viewers.sh` |
| `Makefile` | none | One target set for every project (`nxt-sync`, `duck-sync`, `viewer-sync`, `test-*`, `ci`) |

Each of `viewer/`, `duck/` and `nxt/` already has its own `pyproject.toml` and lock file, and the
Makefile has per-project sync and test targets. So the folders are the right size; the imports
between them are the problem.

## 3. The finding: the seam that is not cut

Verified by `grep` in `explore/duck/src` and `nxt/src`:

- The duck imports the Observatory's package to write its run files:
  `duck_lab/nav/runlog.py` (`from miniview import keys`, `miniview.adapters.duck`,
  `miniview.mcapio` for `Recorder`, `WriterBusy`, `new_run`) and `duck_lab/replay.py`
  (`miniview.keys`, `miniview.mcapio` for `FINAL`, `LIVE`, `Follower`). `duck/pyproject.toml`
  lists `miniview` as a path source, `../viewer`, with the comment that it is not a release.
- `challenge/run.py` does not import `miniview` itself. It writes through `nav.runlog.RunLog`, so
  it depends on the Observatory by that one hop.
- The NXT does the same: `nxt/src/nxt_lab/recorder.py` imports `miniview.keys`,
  `miniview.adapters.nxt` and `miniview.mcapio`, and `nxt/Dockerfile` installs `viewer/` first
  because the build context is the repository root (ADR-0013).
- The other direction does not happen: `grep` for `duck_lab` and `nxt_lab` as an import in
  `viewer/src` finds nothing. One string match, `"nxt_lab.run"`, is a recording's name that
  `adapters/nxt.py` reads, not an import.

So the arrow runs one way: robots depend on the Observatory, to write runs. But the Observatory
package holds two different things: the **run format** (writer, reader, keys, schemas) and the
**viewer** (index, API, pages, video). The robots need the first and not the second. Today they
install both. That is why the run format is the first seam to cut.

Other seams found:

- The Observatory knows each robot's log. `adapters/duck.py` and `adapters/nxt.py` turn a robot's
  own
  records into run records. It is the Observatory that knows the duck's event names, not the duck
  that knows the Observatory's. The adapters are the run format's other half and should live
  with the run format or with each robot (open question 7).
- `world_model/objects.py` imports `duck_lab.nav.cliff` (`OVERHEAD_M`). The world model is
  meant to be robot-independent, but one constant ties it to the navigator. Cutting it out later
  means moving that constant.
- `duck_lab/miniview.py` is an older command-line tool of the duck that is also called `miniview`
  (`pyproject.toml`: `miniview = "duck_lab.miniview:main"`), the same name as the Observatory's
  command. Two commands with one name, in two projects. Not checked: which one wins when both are
  installed in one environment.
- `nxt/Dockerfile` builds from the repository root. After a split it must install the run format
  from a release, not from a folder.

## 4. Goals and non-goals

### 4.1 Goals

- Name the projects, what each contains, and the contract between each pair.
- A split that is moving folders, not rewriting code.
- One small run-format library that a robot can use without the viewer.
- Each project has its own README, tests, version and, where it runs, its container image.
- The lab keeps working at every step, including during the move.

### 4.2 Non-goals

- **Nothing is split now.** This is parked until the operator returns to it.
- Not a decision on repository names or hosting (open questions).
- Not a change to the run format, the gate protocol or any behaviour.
- Not a plan to publish to PyPI. A path or Git source is enough until a second user exists.

## 5. Proposal

### 5.1 The projects

| # | Project | Contents | Contract with the rest | Depends on | Ready to split when |
| --- | --- | --- | --- | --- | --- |
| 1 | **Run format** | The run file's format: keys, schemas, writer, reader, follower, validate. Today `miniview` modules `keys`, `mcapio`, `schemas`, `validate`, `wire` (not checked: exactly which modules, see question 7) | The run format: ADR-0007, ADR-0019, `viewer/CONTRACT.md`; a version number in the file | `mcap`, `protobuf`, `foxglove-schemas-protobuf` | It is the first piece cut, inside the repository (§6, step 2). Split out when a second repository imports it |
| 2 | **The Observatory** | Index, store, API, two pages, video export, CLI, its image and compose file | Reads run files (contract 1); the HTTP API of ADR-0010; the compose file | Run format | A second user, or a release pace unlike the robots' |
| 3 | **Mission Control** | API, app, registry, sites, goals, guardrails (RFC-0014) | The robot gate (contract 4); the Observatory's API for runs; its own API | Gate client, Observatory API | Born as its own package (RFC-0014 question 10: splits out when a second program uses its API) |
| 4 | **The robot gate** | One robot interface plus access (RFC-0003, RFC-0017); a gateway per robot: duck, NXT bridge, simulator, fake | The gate protocol, with a version; the `gate.*` methods | Standard library | When Mission Control exists and a second client or robot kind uses it |
| 5 | **Robot brains** | The duck's navigator and explorer (`nav/`); the world model (objects, semantic map, `kinds.json`, sites) as its own small robot-independent library | The robot interface (contract 4) in; run records (contract 1) out; the world model's objects and map records | Gate client, run format | The world model alone when a second robot uses it (question 4); the navigator with the duck |
| 6 | **NXT** | `nxt-web`, NXC programs, toolchain, the bridge | The gate (as a gateway); the run format (writes runs); its image | Run format, `nxt-python` | Nearly now: its own `pyproject.toml`, README, Dockerfile, tests |

What robotics-lab keeps: the cross-project design docs (RFCs, ADRs, `PRIOR-ART`), the robot
models (`robots/`), the simulator tooling and probes (`duck/sim/`), the challenge course
(`challenge/`; perhaps later the operator's own eval-harness project, open question 5), experiments
such as `nav2/`, and the integration tests that need several projects together.

### 5.2 How the pieces meet

```text
        robots (duck, NXT, simulator)           people, agents, scripts
             |  runs (file)      ^ commands              |
             v                   |                       v
       RUN FORMAT <---- brains --+---- the gate <---- Mission Control ----> missions (planning, RFC-0030)
             ^                                              |
             |  reads                                       | API
        THE OBSERVATORY <-----------------------------------'
```

Four contracts hold it together. Nothing else may cross a project line.

| Contract | What it fixes | Where it lives now | Version carried by |
| --- | --- | --- | --- |
| Run format | What a run file holds | ADR-0007, ADR-0019, `viewer/CONTRACT.md` | A format number in the run file |
| Gate protocol | `robot.*` and `gate.*` methods, errors, tokens | RFC-0003, RFC-0017 (proposed, not built) | A protocol number in `gate.who` and in every call |
| Observatory API | Runs, scenes, video | ADR-0010 | The API's own version |
| World-model records | Objects, sightings, kinds | RFC-0016, ADR-0019 | Inside the run format's number until it grows its own |

### 5.3 Versioning

- **A contract changes only by adding**, and takes a new number when it must break. A reader accepts
  its own number and the ones before it, and refuses a newer one with a clear message.
- The run format already has a number ("format 2", ADR-0007). Whether the file carries it in a
  way a reader can check is not checked here.
- The gate protocol has a number, `protocol: 1` (phase 5, 2026-11-23): in `gate.who`, in every
  other `gate.*` reply, in a refusal's data and in `hello`'s answer (RFC-0017 §3.1). A client
  reads it at its `hello`: missing is 0, accepted with one warning; newer is refused.
- A project names the contract versions it speaks in its README.

### 5.4 CI, docs, images

- **CI per project.** One workflow per project, run only when its folder or its contracts
  change, each with its own tests (today `test-duck`, `test-viewer`, `test-unit` in the one
  Makefile). The lab's integration job (`test-run-compat`: a run opens in Rerun and the
  Observatory) stays in robotics-lab, since it needs several projects.
- **Docs.** Each project has a small README and its own ADRs for its own choices. Cross-project
  design (RFCs, the seams, `PRIOR-ART`) stays in the lab's docs site, which links to each project.
  One site or many is question 3.
- **Container images.** Each project that runs ships its own image: the Observatory, Mission
  Control, the NXT web UI. The RFC-0014 §3.13 rule stays: one compose file runs the Observatory and
  Mission Control anywhere. After the split the compose file lives in the lab (or in Mission
  Control) and names the images by version, not by build context.

## 6. Order

1. **Make the seams real inside the one repository.** Each piece in its own folder with its
   README and tests. No import across pieces except through the contracts. Check it with a test that
   fails when a forbidden import appears.
2. **Start with the run-format library.** Move the writer, reader, keys and schemas out of
   `viewer/src/miniview` into their own package in the repository. The Observatory, the duck and the
   NXT all depend on it. The duck and the NXT stop installing the viewer. Done when `grep miniview`
   in `duck/src` and `nxt/src` finds no import of the viewer, and the existing tests, including
   `test-run-compat`, pass unchanged.
3. **Cut the smaller knots.** Move `OVERHEAD_M` out of `nav/cliff` so the world model stands
   alone; settle which `miniview` command wins (§3).
4. **Split a piece into its own repository when it has a second user or a different release
   pace.** NXT and the Observatory first. Mission Control was planned "its own repository from
   birth"; it was built as a folder (`apps/mission-control`) and nothing broke: the boundary check
   held the seam (amended 2026-11-26, the advisor's review of RFC-0024). The triggers, per piece,
   are in §6.1.
5. **During the move the monorepo keeps working.** The lab repository holds the projects as Git
   dependencies or submodules at pinned versions (question 6), so its `make ci` stays whole. A piece
   moves with its history (`git subtree split` or `git filter-repo`, not checked which). The folder
   is deleted from the lab only after the lab's CI is green on the dependency.

**Waits:** publishing to PyPI; a shared design-token or style package; moving the challenge course
to eval-harness; anything that needs the gate built first (RFC-0017 is proposed).

### 6.1 Split triggers (2026-11-26)

From the [review of RFC-0024](../wip/RFC-0024-REVIEW-2026-11-26.md) at main 54defc1. Nothing splits
now; each piece leaves when its trigger fires, and not before.

| What | Trigger |
| --- | --- |
| `libs/runfile` as a published package | A second repository imports it (robotics-evals reading ticks or scans) |
| The ROS 2 connector | First its own folder, image and CI job here; leaves only if the ROS distro drives its release cadence or a second ROS robot appears |
| The Observatory | A second user of its API, or a release pace unlike Mission Control's |
| `libs/web` | Never alone; moves with whichever app leaves |
| Mission planning as an app | RFC-0030 §5's five triggers |
| `apps/nxt-web` | Not planned; MVP 2 step 6 couples it more |
| Flotilla | Deferred; an HTTP contract, no bearing on repository structure |

The satellites that did leave (chipi/microduck-nav, robotics-evals) left for licence, privacy and
dependency weight, and meet the lab by file contract (a golden fixture, `result.json` by path);
they import nothing of the lab's, so §5.1's trigger for the run format has not fired.

## 7. Alternatives considered

- **Stay one repository for ever.** Cheapest. Rejected as the end state, not as the present: a
  second user of the Observatory or the run format, or a different release pace, makes one
  repository wrong. Until then it is right.
- **Split now, by folder.** Rejected: the duck and the NXT import the Observatory, so a folder
  split breaks both. The seam must be cut first (§3).
- **Two projects only: lab and Mission Control.** Simplest picture, but it leaves the run format
  welded to the viewer, which is the knot in §3.
- **One package per module (many tiny packages).** Rejected: each package costs a version, a README
  and CI. Six projects is the most the operator can keep in his head.
- **A shared monorepo tool (uv workspace, Bazel).** Possible for step 1 and not checked here; it is
  a new tool, so it needs the operator's approval.

## 8. Open questions

All eight are **answered, as recommended** (the operator, 2026-11-18: "I also accept all previous
recommendations"). Each **Answered:** below is the recommendation he accepted. The RFC stays
parked; the answers are recorded for when it is picked up.

1. **Repository names and the Observatory's rename.** RFC-0014 says miniview becomes the
   Observatory; the package is still `miniview`. **Answered:** rename the package at the moment
   the run-format library is cut (step 2), when its imports change anyway, so there is one rename
   and
   not two.
2. **Name of the run-format library.** **Answered:** a plain name such as `runfile`, not tied to
   a viewer name.
3. **One docs site or many?** **Answered:** one lab site now; each project has a README and, when
   it splits, its own small site that the lab site links to.
4. **Does the world model go with the brains or alone?** **Answered:** alone, as its own small
   library, from the day a second robot uses it; until then a folder in `duck-lab` with the
   `OVERHEAD_M` knot cut (§6, step 3).
5. **When does the challenge course move to eval-harness?** Perhaps; it depends on what that
   project becomes. **Answered:** stay in the lab; decide when eval-harness is named.
6. **Submodules or version pins for the lab's view of its projects?** Not checked. **Answered:**
   version pins to Git tags, the simpler of the two, until a reason for submodules appears.
7. **Do the Observatory's robot adapters (`adapters/duck.py`, `adapters/nxt.py`) go to the run
   format or to each robot?** **Answered:** to each robot, so the format knows no robot and the
   Observatory loads adapters by name. The cost is a plug-in point in the Observatory; your call.
8. **When is the first split?** **Answered:** after the lab "works as it is" and RFC-0014's first
   slices are built; not before you say.

## 9. Discussion

- 2026-11-18: written at the operator's request, parked. Verified against the repository: the
  folder layout of both worktrees, the three `pyproject.toml` files (`viewer`, `duck`, `nxt`), the
  imports named in §3, the Makefile's per-project targets, the `nav2/Dockerfile` header, and the
  existence of ADR-0007 and ADR-0019 here. ADR-0018 and RFC-0015/0016 exist only in the
  `explore` worktree.
- **Not checked:** `robots/` internals beyond the folder names; the `viewer` modules that would go
  to
  the run format; whether the run file carries a version a reader checks; the `miniview` command
  collision; the history-preserving move tools; any CI workflow files in detail.

## 10. What was built (2026-11-19)

One branch, commits C0 to C10 of [the plan](../wip/PHASE2-RESTRUCTURE-PLAN.md), each with its
gates green; a golden (a fixture run's API answers, one `duck-replay` report) hashed before and
after every move, equal throughout.

| Path | Package | Holds | From |
| --- | --- | --- | --- |
| `libs/runfile` | `runfile` | keys, schemas, wire, signals, validate, mcapio, se2, store, catalog, index, the adapters, `env` | `viewer/src/miniview` |
| `libs/gate` | `robotgate` | the gate (RFC-0017), standard library only | `duck_lab/gate.py` |
| `libs/worldmodel` | `worldmodel` | objects, semantic map, relocalise, site, `kinds.json` | `duck_lab/world_model` |
| `libs/missions` | `missions` | goal schemas, the guardrail vocabulary and merge, the planner (RFC-0030), standard library only | `mission_control` (2026-11-26) |
| `apps/observatory` | `observatory` | the server, importer, pages, video, export, CLI | `viewer/` |
| `apps/mission-control` | `mission_control` | as before | `control/` |
| `apps/nxt-web` | `nxt_lab` | as before, with its programs and toolchain | `nxt/` |
| `robots/duck` | `duck_lab` | the navigator, challenges, replay, gate proxy, simulator, calibration, beside the robot's description | `duck/` |

Which package may import which, as `scripts/check_boundaries.py` enforces it (stdlib `ast`, run by
`make lint` and so by CI; its self-test proves a forbidden import fails). Libraries import no other
package of the lab; apps never import apps; robots never import apps.

| Importer | runfile | robotgate | worldmodel | observatory | mission_control | nxt_lab | duck_lab |
| --- | --- | --- | --- | --- | --- | --- | --- |
| runfile, robotgate, worldmodel | self | - | - | - | - | - | - |
| observatory | yes | - | - | self | - | - | - |
| mission_control | tests | yes | tests | tests (Chromium shots) | self | - | tests |
| nxt_lab | yes | - | - | tests (Chromium shots) | - | self | - |
| duck_lab | yes | yes | yes | - | - | - | self |

**Since then (2026-11-21):** two libraries joined, `libs/simhost` (RFC-0021, imports no other
unit) and `libs/runner` (`labrunner`, RFC-0022: imports runfile, robotgate, worldmodel and simhost,
never a robot's package); and the duck's navigator (`duck_lab.nav`, the payload, the plugins, the
profile)
is a unit of its own that may import neither `labrunner` nor `simhost`, while the duck's tools may.
The table in force is `scripts/check_boundaries.py`'s.

**Since then (2026-11-26):** `libs/missions` (`missions`, RFC-0030 row 1) joined: it imports no
other
unit, and only `mission_control` imports it, through one module (`planning.py`). The arrow
`mission_control -> missions` is in the picture of section 5.2; no robot, gate or runner can be
reached from it.

The one exception, by module, was `mission_control.duck` (Mission Control's duck adapter),
which imported `duck_lab.nav.client` and `duck_lab.nav.run.load_scale`. It is retired: phase 5
step 1 (RFC-0023) cut it, and `EXCEPTIONS` in `scripts/check_boundaries.py` is empty
(2026-11-26). A test or probe of a project may also use what the table lists as "tests".

Where it differs from §5 to §8, and why:

- **Names.** `runfile`, `robotgate`, `worldmodel`, `observatory`; the gate is the package's
  `__init__` (`from robotgate import Gate`).
- **The index** moved with the catalog: `catalog` imports it, and a library may not import an app.
- **Adapters** stayed in `runfile` (answer 7 of §8 is deferred to RFC-0020's plugin loader).
- **The world model** needed two cuts: `OVERHEAD_M` now lives in `worldmodel.objects` and the
  navigator reads it from there; the `duck-site` command, which draws the simulator's rooms with the
  navigator's frames, moved to `duck_lab.site_cli` with the sites folder's default.
- **The navigator** stays in `robots/duck` as `duck_lab`; its generic part moves to a library in
  RFC-0020 step 3.
- **The NXT's lock** (`nxt_lab/lock.py`) keeps its own copy of the gate's rules over HTTP;
  unifying it would change behaviour.
- **No split into repositories** and no uv workspace: each project keeps its own `pyproject.toml`
  and `uv.lock`, the libraries are path sources.
- **The rename.** The command is `observatory` (`miniview` still runs it, one release), the make
  targets `observatory-*` and `test-observatory*` (`viewer-up`, `viewer-down`, `test-viewer` kept
  one
  release), the variables `OBSERVATORY_*` (`MINIVIEW_*` read as a fallback). Kept so old runs and
  fixtures read byte for byte: the MCAP topics `/miniview/*`, schema names and profile, the signals
  proto, the index folder `state/miniview`, `window.miniview` and the pages' storage keys, the
  `--miniview-data` flags. Revisit with format 3.
- **The duck's old `miniview` tool** is `duck-pic`.
