# Phase 2 prepared: the restructure (RFC-0018) and the Observatory rename

**Status:** prepared 2026-11-19 (a read-only planning pass over the code), for
[the plan we execute on](EXECUTION-PLAN.md) phase 2. Not started; it starts on the operator's word
at the phase 1 checkpoint, with nothing else in flight. Decisions in §6.

## 0. What the code says (it shapes the plan)

- No workspace: `viewer/`, `duck/`, `control/` and `nxt/` each have their own `pyproject.toml` and
  `uv.lock`; CI has no uv cache.
- The run format is wider than RFC-0018 §3 says. The duck writes runs through `miniview.keys`,
  `adapters.duck` and `mcapio` (`duck/src/duck_lab/nav/runlog.py:20-22`, `replay.py:19-20`, about 30
  probes); the NXT through `keys`, `adapters.nxt`, `mcapio` (`nxt/src/nxt_lab/recorder.py:15-17`);
  and `adapters/duck.py` needs `store` and `se2` (`adapters/duck.py:13-14`).
- Mission Control imports `duck_lab` beyond the gate: `nav.client` (`StateStream`, `Rpc`) and
  `nav.run.load_scale` (`control/src/mission_control/duck.py:20-22, 328`).
- The world model leans on the navigator: `objects.py:12` (`cliff.OVERHEAD_M`), `site.py:221-222`
  (`frames`, `rooms.ROOMS`).
- The viewer imports nothing from `duck_lab` or `nxt_lab`.
- Paths that break when a folder moves deeper: `viewer/src/miniview/robots.py:14`,
  `video/__init__.py:25` (`parents[3]`); viewer tests with `parents[2]` (`test_kinematics:12`,
  `test_ldraw:15`, `test_run_compat:29`, `test_explore_pages:27`); control tests
  (`test_nxt_adapter.py:25`, `sim_duck.py:34`); hard-coded `.venv` paths (`test_run_compat.py:89`,
  `viewers.sh:16`, `sim_duck.py:74`, `Makefile:33`).
- The data folder (`/work/robotics-lab/data`) and the index (`state/miniview`) do not move.

## 1. The target tree (`git mv`, history kept)

| Path | Package | Contents | From |
| --- | --- | --- | --- |
| `libs/runfile` | `runfile` | keys, schemas, wire, signals, validate, mcapio, se2, store, catalog, adapters | `viewer/src/miniview` |
| `libs/gate` | `robotgate` | the gate (stdlib only) | `duck_lab/gate.py` |
| `libs/worldmodel` | `worldmodel` | objects, semantic map, relocalise, site, kinds, `duck-site` | `duck_lab/world_model` |
| `apps/observatory` | `observatory` | the server, importer, index, pages, video, export | `viewer/` |
| `apps/mission-control` | `mission_control` | as today | `control/` |
| `apps/nxt-web` | `nxt_lab` | as today | `nxt/` |
| `robots/duck` | `duck_lab` | the navigator, challenges, replay, gate proxy, sim, calibration, beside its description | `duck/` less the gate and the world model |
| `robots/ev3-*`, `nxt-shooterbot`, `ldraw` | — | unchanged | `robots/` |

Untracked data (`duck/runs` 202 MB, `duck/sites`, `nxt/runs`, `nxt/config.json`, every `.venv`)
does not move with `git mv`: moved or recreated by hand, each path on the operator's OK.

## 2. Which package may import which

| Importer | runfile | robotgate | worldmodel | observatory | mission_control | nxt_lab | duck_lab |
| --- | --- | --- | --- | --- | --- | --- | --- |
| libs | — | — | — | — | — | — | — |
| observatory | yes | — | — | self | — | — | — |
| mission_control | tests | yes | — | — | self | — | exception |
| nxt_lab | yes | — | — | tests (shots) | — | self | — |
| duck_lab | yes | yes | yes | — | — | — | self |

Libraries import nothing above; apps never import apps; robots never import apps. The one
exception, listed by file: Mission Control's duck adapter importing `duck_lab` (`nav.client`,
`load_scale`), retired by RFC-0020's plugins. `nxt_lab/lock.py` keeps its own copy of the gate's rules
over HTTP for now (unifying it changes behaviour).

The check: `scripts/check_boundaries.py`, stdlib `ast`, run from `make lint` (as
`check_workflows.py` is), so CI's unit job runs it; it also reads each `pyproject`'s path sources.
A self-test (`scripts/test_check_boundaries.py`) proves a forbidden import fails. It cannot see
string module names (`-m duck_lab…`) or `PYTHONPATH` tricks; its docstring says so.

## 3. The rename

| Item | Now | After | Kept for compatibility |
| --- | --- | --- | --- |
| package | `miniview` | `observatory` (`runfile` for the format) | — (about 40 imports rewritten) |
| CLI | `miniview` | `observatory` | a `miniview` alias, one release |
| the duck's old `miniview` tool | `duck_lab.miniview:main` | `duck-pic` | — (the names collide today) |
| image, compose project, service | `miniview` | `observatory` | the old image stays on disk |
| make targets | `viewer-*`, `test-viewer*` | `observatory-*` | aliases for `viewer-up`, `viewer-down`, `test-viewer` |
| CI job names, docs titles, CONTRACT | miniview wording | Observatory | historic RFC and ADR bodies not rewritten |
| environment variables | `MINIVIEW_*` | `OBSERVATORY_*` | the old names read as a fallback |
| **kept as they are** | MCAP topics `/miniview/*`, schema names, MCAP profile, `signals.proto`, `state/miniview`, the data folder | — | old runs and fixtures must read byte for byte; revisit with format 3 |

## 4. The commits, each leaving the tests green

| # | What | Proof |
| --- | --- | --- |
| C0 | baseline: `make ci`, tag `pre-restructure`; a golden: one fixture run imported and its API answer hashed, one `duck-replay` hashed | the hashes written down |
| C1 | the boundary checker against today's layout, today's breaches as its baseline | `make lint`, its self-test |
| C2 | cut the knots in place (`OVERHEAD_M`, `site.py`'s navigator imports); `duck-pic` | `make test-duck`, the golden |
| C3 | carve `libs/runfile` (the package still `miniview`); imports rewritten; locks regenerated; Dockerfiles | `make ci-fast test-run-compat test-integration test-viewer-image`, the golden |
| C4 | `libs/gate` | `make test-duck test-control` |
| C5 | `libs/worldmodel` | `make test-duck test-control`, the golden |
| C6a–d | `git mv` control, nxt, viewer, duck into `apps/` and `robots/`; Makefile, compose, workflows, the `parents[N]` lines, locks | `make ci-fast` plus the moved project's target; after the viewer, `make test-viewer-pages` |
| C7 | the rename (§3) | `make ci`, the golden |
| C8 | environment variables with fallback (can be dropped alone) | tests with the old names still pass |
| C9 | docs: nav, README, "now the Observatory" notes, RFC-0018's status | `make docs-lint docs-build` |
| C10 | the boundary table final, a CI step | `make ci`, the golden equal to C0, the stack on test ports up and healthy, then down |

## 5. Risks and the way back

- Every `uv.lock` changes (path sources are relative): regenerated per package, the diff read to
  hold only paths and names. Not verified that `uv lock` keeps every pin offline.
- Virtual environments hold absolute paths and break when moved: recreated with `make *-sync`;
  deleting one is the operator's call.
- The Observatory's Docker context moves to the repo root: an allowlist keeps `duck/runs` out.
- The operator's running Observatory on :8070 (compose project `miniview`) collides with the renamed
  one: it is brought down and up only on the operator's go; the old image stays for rollback.
- Worktrees in flight conflict with every move: merged or parked first (the phase's own rule).
- The way back: one branch; before merging, `git reset --hard pre-restructure`; after, a revert of
  the merge. The data, the scenes and the index are outside the repo or mounted read only.

## 6. Decisions for the operator (recommendation first)

1. The navigator stays in `robots/duck` as `duck_lab` for now; its generic part moves to a library
   in RFC-0020 step 3 (else it moves twice).
2. MCAP topics, schema names and the profile: kept.
3. Environment variables renamed with a fallback; the index stays at `state/miniview`.
4. The run adapters stay in `runfile` until RFC-0020's plugin loader.
5. Names: `robotgate` for the gate library, `duck-pic` for the duck's old tool.
6. The NXT lock's copy of the gate's rules: left, noted.
7. Historic RFC and ADR text: not rewritten, titles and nav only.
8. No uv workspace (a new tool needs approval; per-package locks work).
9. The NXT's programs and toolchain stay with `apps/nxt-web` for now.
10. The compatibility aliases (`miniview` CLI, `viewer-*` targets) kept one release, then removed.

## NOT VERIFIED

The unread parts of `store.py`, `catalog.py`, `se2.py`; whether `uv lock` is stable offline;
whether branch protection names CI jobs; which `miniview` command wins in a shared environment;
duck tests that depend on the untracked `duck/runs`.
