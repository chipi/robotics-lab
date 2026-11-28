---
name: challenge-batch
description: Run and score a navigator challenge batch as an experiment - freeze the scenario set, run one batch per arm on the same seeds, turn each batch's run folders into a scores JSONL, import it with evh import-run under the run's build identity, and read evh comparison-show. At least 10 scenarios per arm, one primary metric (success), collisions as a safety limit. Use when asked to "run a challenge batch", "compare rules and learned", "is the learned controller better", "score these runs", "import the batch into robotics-evals", "run c22 ten times", or before any claim that one arm beats another. Do not use for reading one run (robotics-run-read) or for the simulator rules alone (sim-run, which this builds on).
metadata:
  permissions:
    read: [robots/duck/runs, "/work/robotics-evals/data", libs/runner]
    write: ["a scores JSONL named with --out", "robotics-evals data/ only through evh, and only when the operator asked for the evaluation"]
    execute: [scripts/batch_scores.py, "evh (import-run, comparison-show)", "lab-challenge and lab-scenarios, under sim-run's lock"]
---

# challenge-batch

Starting a batch is a simulator job: do `sim-run` first (lock, patch, scratch installation). Scoring and reading are read only.

## The flow

1. **Freeze the scenario set.** `uv run lab-scenarios export --challenges 4,14,15 --seeds 1-5 --depth-impairment 1 --out DIR` writes one
   canonical JSON per scenario and a manifest (no simulator). It becomes a robotics-evals dataset (`evh dataset-create`, `docs/DATASET-SPEC.md`).
   An existing one: `/work/robotics-evals/data/datasets/avoidance_v1.json` (30 items: 6 challenges x seeds 1-5, sensor seed = scene seed).
   A set is frozen when its file hashes are in the dataset; never edit one, make `_v2`.
2. **One batch per arm, the same seeds and the same sensor.** Per challenge `N`:
   `scripts/sim-lock -- uv run lab-challenge N --runs 5 --seed 1 --depth-impairment 1 --miniview-data <scratch data> --out <arm folder>`
   (run i uses seed + i, and sensor seed 1 + i). The second arm changes one thing only: `--local-controller learned --model PATH`
   (in the working tree of libs/runner, not yet committed when this was written; check `lab-challenge --help`). Commit first: a run from a
   dirty tree records `-dirty` in its build, and eval-harness refuses it later.
3. **Score each arm.** `scripts/batch_scores.py <arm folder> --dataset <dataset json> --arm <name> --out <arm>.scores.jsonl`.
4. **Import** (writes into robotics-evals; only when the operator asked for this evaluation):
   `EVH_FOR=person:<operator> evh import-run --dataset-id D --system-id ARM --scores F --primary-metric success --metric-kind stand_still=descriptive --metric-kind pivot_fail=descriptive --build-ref '<id>' --source '<command line>' --scorer-id batch_scores@<commit> --by agent:<name>`.
   `--build-ref` is the id the script prints: the runs' `build.id` without the trailing `-s<sensor seed>`. A run with no build is not imported.
5. **Compare.** `evh comparison-show --runs rules,learned --baseline rules --metric success` (add `--cluster scene` for several seeds of one scene).

## Preflight

`sim-run`'s preflight READY; a clean, committed tree; the dataset id exists in `/work/robotics-evals/data/datasets/`; the arms differ in
one setting; at least 10 scenarios per arm (the script fails under `--min-items`, default 10). Exact p up to 30 items; no interval at 5 or fewer.

`evh` is at `/work/robotics-evals/.venv/bin/evh` and is not on `PATH` (`command -v evh` finds nothing); every `evh` in this skill means that file.

## Success: signals that must agree

1. `BATCH-SCORES PASS`: every dataset item has exactly one run with a verdict, all builds agree apart from the sensor seed, none dirty.
2. Each run's `clock.rtf` at least 0.95 and `truth_copy.unpaired` 0 (a slow simulator gives `pass: null`, which the script refuses).
3. `evh import-run` printed `imported ...: N/N items` (not "subset" unless that was the plan).
4. `comparison-show` gives delta, p, wins and losses and a 95% interval. A leader without the interval and the collision count is not a result.
5. Collisions: the safety limit (goal axis `limit: 0` or `baseline`, `docs/EVAL-HARNESS-0.8.1.md` section 4) holds for the arm that "wins".

Read the three together: "9 of 10 passed" is a rate, not a comparison.

## Never

- Compare arms that ran on different seeds, scenes or sensor settings, or an arm with fewer than 10 scenarios.
- Pick the metric after seeing the result; there is one primary (`success`). Collisions, clearance, time are descriptive or a limit.
- Count a repeat of the same scene as a second item; edit a frozen dataset or a run under `data/runs/`; pass a made-up `--build-ref`.
- Import runs with no build identity or a dirty one; treat `pass: null` as a failure or drop it silently.
- Start a batch outside the lock, or write into the operator's installation, data folder or index.

## Not covered

Explore batches (`lab-explore`, `explore_score`) have another format and are not scored here; the Hugging Face upload of run files
(`_hub_revision`); a goal's creation (`evh goal-new`, not run here); sequential tests; real-robot batches. `references/batch-notes.md` has the
score columns and what the sources got wrong.
