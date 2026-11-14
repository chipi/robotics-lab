# What robotics asks of eval-harness (for 0.9)

Written 2026-11-14 for the operator and the eval-harness session, to assess and plan for
**eval-harness 0.9** (the operator's target). Nothing here is decided for eval-harness: these are
the robotics side's needs, each through eval-harness's own RFCs, and its non-goals are read first.
Code references are into `/work/eval-harness/main` at `bc2286392` (harness 0.6.0) and come from
two reads of it on 2026-11-13/14 ([EVAL-HARNESS-ROBOTS.md](EVAL-HARNESS-ROBOTS.md) has the first,
with file and line references).

## 1. The key use case: does the simulator predict the real robot?

A robot mission is rehearsed on a simulated robot before it runs on the real one
([RFC-0005](../rfc/RFC-0005-missions.md)). Whether that rehearsal is worth anything is an
evaluation question with three parts:

| Question | Measure |
| --- | --- |
| **How big is the gap?** (simulator fidelity) | The same scenarios as two arms, `sim` and `real`, same software; per metric (success, time, path length, contacts, falls, commanded vs measured speed) a paired test of the difference |
| **Does the simulator rank versions correctly?** | N versions, many simulator runs and few real runs each: rank agreement between the two arms. If A beats B in the simulator, does it on the robot? |
| **Can a rehearsal be trusted?** | Pairs of (rehearsal pass/fail, real pass/fail) over missions: the **false-pass rate** (rehearsal passed, real failed) is what decides whether a passed rehearsal may count toward promoting a mission to running on its own |

Plus **coverage**: a simulator run over many randomised seeds gives a distribution; a faithful
simulator has the real result inside it. "How often does the real run fall inside the simulator's
90 % range?" is a calibration number.

These are general "does a cheap proxy predict the expensive reality?" questions — the same shape
as an LLM judge against people, or an offline test against production — so they belong in
eval-harness, not in the robot project.

## 2. Today: what already fits

- Trials run outside the harness and are imported: `evh import-run` takes per-item numeric scores
  as a run; `pair-test` and `family-test` read it (`import_run.py`).
- Two arms on one frozen scenario set: `sim` and `real`.
- Paired sign-flip permutation tests on continuous per-item values (`pair_test.py`, `stats.py`).
- Lower-is-better metrics (`METRIC_DIRECTIONS`), reference-free scoring (`score(output, None)`).
- Evaluating what already happened, offline, is in scope (PRD-014's "datasets from production"):
  real robot runs are "production". Live trials driven by the harness would touch PRD-014's
  online-evaluation non-goal; importing avoids it.
- Model choice for the robot brain fits as is: sentences → mission specs as a dataset with the
  candidate models as arms; camera frames → room type and objects.

## 3. The asks

| # | Ask | Why for robots | Today |
| --- | --- | --- | --- |
| E1 | **Paired arms across environments**: `sim` vs `real` as a first-class comparison, the gap per metric reported | The central sim-to-real question | Possible as two imported arms; nothing names or reports the gap |
| E2 | **Rank agreement between two arms across versions** (e.g. Kendall's tau with an interval) | Whether the simulator chooses versions correctly | Not present |
| E3 | **Coverage**: how often a single real result falls inside an arm's distribution over seeds | Simulator calibration | Repeats are averaged per item; distributions are not compared |
| E4 | **Predictor quality**: a pass/fail predictor (the rehearsal) against an outcome (the real run): false-pass and false-alarm rates with intervals | What flotilla's promotion needs | Not present |
| E5 | **Side-effect-safe adapters**: a flag for "this moves hardware" — no automatic retries, an adapter timeout, a pause for a human reset between items | A retried trial is a second physical run | Core retries up to 8 times on "timeout"/"connection" (`_retry.py`); no core timeout |
| E6 | **Structured scenario items**: the adapter receives the item id and fields (start pose, scene, instruction) | Scenarios are data, not text | `call_system(text, params)` gets the item text only (`run.py`) |
| E7 | **Trajectories as outputs, and scorers over them**: success, time, path length, contacts, closest approach; path error against a ground-truth track | A run is a time series | Output is a string; numbers via `Result.extra` |
| E8 | **Sequential testing**: run trials until the answer is clear (significant or clearly not) | Robot time is the scarce resource | Fixed counts |
| E9 | **Repeat variance in the tests** | Few items, noisy repeats | Tests average repeats per item; the spread is printed, not used |
| E10 | **Safety as a gate**: a hard limit (e.g. contacts = 0) that excludes an arm whatever its score | A faster unsafe controller must never win | Goal axes with limits point this way |
| E11 | **Mission judging against a reference plan**: an LLM judge grading a mission's plan and log with a reference | Was the plan sensible, not only did it finish | Judges read no reference (`judge_score.py`) |
| E12 | **Composite build identity**: brain commit + model alias + policy set in one run's identity | A robot run depends on three versions | `--build-ref` is one string; we would format it `brain@…+model@…+policies@…` meanwhile |
| E13 | **Replay in the inspector**: a trajectory or video beside the scores | Seeing why a run failed | — |
| E14 | **Run records in MCAP** as an import format (the robotics side writes MCAP for the Foxglove viewer) | One record format for viewing and evaluating | JSONL imports |

Suggested priority for 0.9, from the robotics side: E1, E4, E5, E6, E2, E8 first (they decide
whether rehearsal can be trusted and make physical trials safe); E3, E7, E9, E10 next; E11–E14
later.

## 4. What the robotics side does meanwhile

- Runs trials outside the harness and imports them (`evh import-run`), one arm per environment.
- Writes run records with per-item numbers and a composite build reference.
- Logs every friction point and sends it to the eval-harness session.
- First real comparison when the robot arrives: the arena's 2 m sprint in simulation vs a taped
  2 m strip at home; later a taped obstacle course rebuilt in simulation; later the operator's
  home itself, as a simulator scene generated from the robot's own map. Ground truth for real paths:
  a phone on the ceiling and a printed marker on the robot.

## 5. What the robotics side asks the eval-harness session

1. **Assess** E1–E14 for 0.9: fits as is / needs a change / out of scope, against eval-harness's
   PRDs (especially PRD-014's non-goals) and RFCs.
2. **Which RFCs** they become (new ones, or extensions of existing ones such as RFC-019 datasets from
   production or RFC-022 scoring that evolves).
3. **The order** within 0.9 and what slips to later.
4. **What the robotics side should produce** to make it simplest: the import format, the per-item
   fields, how to name arms and environments.

## 6. Not verified

- The minimum number of items eval-harness needs for a confidence interval: the first read reported
  "more than 5"; the second review did not find that threshold in `stats.py`.
- Code references are from 0.6.0 at `bc2286392`; 0.7 and 0.8 may have changed them.
