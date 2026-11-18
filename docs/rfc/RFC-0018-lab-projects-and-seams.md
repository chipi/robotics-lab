# RFC-0018 — The lab's projects, their seams, and how to split robotics-lab later

**Status:** Proposed (2026-11-18), parked: for later — the operator: "make another RFC with idea to
split and everything else, and we're gonna come back to that later. First I wanna finish all the
ideation and I wanna make it work as it is right now."
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (§3.13 containers, question 10 licence and
splitting), [RFC-0017](RFC-0017-robot-access.md) (the gate),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0009](RFC-0009-miniview.md) (miniview, to be renamed the Observatory),
[ADR-0007](../adr/ADR-0007-run-file-format-2.md) (the run file) and
[ADR-0019](../adr/ADR-0019-semantic-map-records.md) (the semantic map in a run).
**Nothing here is to be done now.** The first job is to make the lab work as it is. This RFC
records the idea so that we can come back to it.

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

- The Observatory knows each robot's log. `adapters/duck.py` and `adapters/nxt.py` turn a robot's own
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
       RUN FORMAT <---- brains --+---- the gate <---- Mission Control
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
- The gate protocol gets a number the day RFC-0017 is built, not before.
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
   pace.** NXT and the Observatory first. Mission Control from birth: it starts as its own
   repository, not as a folder.
5. **During the move the monorepo keeps working.** The lab repository holds the projects as Git
   dependencies or submodules at pinned versions (question 6), so its `make ci` stays whole. A piece
   moves with its history (`git subtree split` or `git filter-repo`, not checked which). The folder
   is deleted from the lab only after the lab's CI is green on the dependency.

**Waits:** publishing to PyPI; a shared design-token or style package; moving the challenge course
to eval-harness; anything that needs the gate built first (RFC-0017 is proposed).

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
   the run-format library is cut (step 2), when its imports change anyway, so there is one rename and
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
- **Not checked:** `robots/` internals beyond the folder names; the `viewer` modules that would go to
  the run format; whether the run file carries a version a reader checks; the `miniview` command
  collision; the history-preserving move tools; any CI workflow files in detail.
