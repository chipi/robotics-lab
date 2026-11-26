# Batch notes

## What batch_scores.py writes (one row per scenario per arm)

`{"item_id", "success" 1/0, "collisions" 1/0, "falls" 1/0, "min_clearance", "time_s", "stops", "_run", "_ticks_sha256", "_build"}`.
Every key but `item_id` is a metric; a key starting with `_` is metadata; finite numbers only, no booleans. Accepted by `evh import-run`
0.8.1 (tested in a scratch copy of robotics-evals, subset import: `imported ...: 1/30 items (subset), 6 metric(s), success=1.0`).

- `success`: result.json `pass`. A run judged by truth: no invariant broken (fall, drop margin, contact, bounds) and the right outcome within `judge.reached_m`.
- `collisions`: only the FIRST broken invariant is recorded in `failed`; a run that fell first and touched later reads `falls 1, collisions 0`. Read `min_clearance` beside it.
- `time_s`: `clock.sim_s` where recorded, else the last tick's `t`.
- `stops`: `reflex_stop` and `cliff_stop` events (the robot's own stops, not the judge's).

## The build identity

`brain@<commit 12>[-dirty]+ctrl@<rules@1 | learned@<8 of the model's sha256>>+walker@<8>+sim@<8|real>+tof@<nvidia|off>-s<seed>`
(`libs/runfile/src/runfile/build.py`). The trailing seed is the DEPTH-IMPAIRMENT seed; run i of a batch takes SEED + i, so a batch's ids differ
by it, and `-s0` is "no impairment, seed 0", not the scenario seed. The scene's own seed is `seed` in result.json.

## The commands

```bash
uv run lab-scenarios export --challenges 4,14,15,2,3,1 --seeds 1-5 --depth-impairment 1 --out /work/robotics-evals/data/sources/avoidance-v1
EVH_FOR=person:<operator> evh import-run ...        # --by agent:<name> needs EVH_FOR; without it: "an agent (claude) acts for a person"
evh comparison-show --runs rules,learned,guarded --baseline rules --metric success
```

## What the sources got wrong or stale (found while writing this skill)

- `/work/robotics-evals/docs/EVAL-HARNESS-0.8.1.md` ("Our build identity") writes `ctrl@<name>-<8 of the model's sha256>`; the code writes `ctrl@learned@<8>` (and `ctrl@rules@1`).
- `/work/robotics-evals/projects/ledger/build_ledger.py` marks a run's identity `known` only when `result.json` has `commit`; the runner now writes `build`, so every new run reads "unknown: the run recorded no commit". `KEEP` already lists `build`; the `identity` test should read it. Its README line "None records the commit it ran from" is true of the existing 85 runs.
- The task text and RESEARCH-S1-S4 name "the Observatory's `import-run`". The Observatory's command is `observatory import`; `import-run` is `evh`'s.
- `--local-controller` is no longer "coming": `lab-challenge --help` lists it (uncommitted in libs/runner when checked).
- `robots/duck/runs/c23-ten` holds 3 runs, not ten (`ten-progress.log` ends `CH23 EXIT=143`).
