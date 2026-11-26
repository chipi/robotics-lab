# Run folders and the run file

Sources: `apps/observatory/CONTRACT.md` ("Runs on disk - format 2"), `libs/runfile/src/runfile/build.py`, `libs/runner/src/labrunner/`.

## A runner's folder (what `lab-challenge`, `lab-explore`, `lab-go` write)

| File | Holds |
| --- | --- |
| `ticks.jsonl` | one JSON per line: a tick (`pose`, `vx`, `vyaw`, `tilt`, `t`, `truth`) or an event (`{"event": ..., "t": ...}`) |
| `result.json` | a challenge run's verdict: `pass`, `failed`, `status`, `error_m`, `coverage`, `min_clearance_m`, and since ebe0b8a `build` |
| `results.json` | an evaluation's list, one row per goal (`status`, `reached_truth`, `fell`, `contact`, `reflex_stops`) |
| `start.json` | the belief and truth pose at the start (`map`, `truth`): the alignment between the two frames |
| `truth.jsonl` | newer runs: truth samples (`wall_ns`, `pose`, `z`, `quat`), paired to a tick by its `wall_ns` |
| `map_grid.json`, `semantic_map.json`, `inventory.json` | an explore run's end state |

An explore run (`lab-explore`) writes no verdict file: it prints its result, and `python -m labrunner.explore_score <run folders>` scores it.

Event names that are stops or guards: `reflex_stop`, `cliff_stop` (the robot's own), `stuck`, `stalled`, `trapped`, `held_off`, `refused`,
`recovery`, `no_frontier_left`, `stopped_by_guardrail` (the runner's truth guard broke the run), `robot_guard` (the navigator's own
sensors broke a guardrail, navcontract 1.7).

Ticks written since ebe0b8a carry `requested` and `applied` (`{vx, vyaw}`); `applied` differs from `requested` where the speed cap acted.

## A data run (`<data>/runs/<robot>/<scene>/<run>/`)

`run.mcap` (zstd, indexed), `source/` (an import's original log). The first message `/miniview/run` is the run record:
`key, kind, scene, official, build, judge_profile, judge_scene, judge_truth, goal_run`. The last, `/miniview/end`, is `{verdict}`;
`ended` for a run that closed normally, `stopped` when `observatory repair` closed a dead writer's run.

`build` = `{id, brain, ctrl, walker, sim, tof, seed, dirty}`, `id` =
`brain@<commit 12>[-dirty]+ctrl@rules@1+walker@<sha 8>+sim@<commit 8|real>+tof@<preset|off>-s<seed>`. `unknown` is a part no host
could read. A run written before ebe0b8a has none.

## Scratch import (the only safe way to try `observatory import`)

```bash
SC=<a scratch folder>; mkdir -p $SC/data $SC/state
printf '{"installation": 1, "data": "%s/data", "index": "%s/state/index.sqlite", "state": "%s/state", "robots": {}}\n' $SC $SC $SC > $SC/installation.json
export ROBOTICS_LAB_INSTALLATION=$SC/installation.json
apps/observatory/.venv/bin/observatory import --scene apartment robots/duck/runs/<run>   # writes under $SC only
apps/observatory/.venv/bin/observatory runs apartment
```

A runner folder imported this way takes the scene you give (`apartment` by default for the duck). The key becomes
`duck/<scene>/<folder name>`.
