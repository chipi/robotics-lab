# eval-harness for robot trials — ideas 1, 2, 4 and 5

How the four eval-harness ideas in [IDEAS.md](IDEAS.md) map onto what eval-harness actually
supports. Based on a read of `/work/eval-harness/main` (harness 0.6.0, commit `bc2286392`) on
2026-11-13; file references are into that repo. Nothing here has been run yet.

## What fits without changing eval-harness

- **One adapter, many controllers.** `call_system(text, params)` gets the item and the
  config's `params` untouched (`adapter.py:60`, `data/configs/README.md`). One robot adapter,
  one YAML per arm: `params: {controller: chase_v2, near_cm: 30}`.
- **Scenarios as items.** An item is a file; a JSON scenario (`{"course": "hall", "start":
  "door", "seed": 3}`) is fine. The adapter receives it as text and parses it (`run.py:346-348`).
- **Robot metrics, no reference needed.** `Result.extra` numbers become metrics
  (`adapter.py:49-55`); `score(output, None)` is supported (`INTEGRATION.md:96-99`);
  `METRIC_DIRECTIONS = {"lap_time_s": "lower"}` marks lower as better (`adapter.py:108-110`).
  A trial's own duration can be reported as `latency_ms` instead of wall-clock (`run.py:151-167`).
- **Trials that already happened.** `evh import-run --scores scores.jsonl` turns per-item
  numbers computed elsewhere (our CSV logs) into an ordinary run that `pair-test`,
  `family-test` and `leaderboard` read (`import_run.py:1-33`).
- **Continuous scores in the tests.** `pair-test` and `family-test` are paired sign-flip
  permutation tests on per-item values, exact up to 30 items (`pair_test.py`, `stats.py`);
  nothing is limited to right/wrong scores.
- **Firmware / build identity.** `EVAL_BUILD_REF` can be a version or image digest rather than
  the project's git commit (`CONCEPTS.md:19-21`) — fits an `.rxe` hash or an ONNX revision.

## The four ideas

### 1. Controllers as arms (live trials)

Items: a handful of fixed scenarios. Arms: program versions. The adapter starts a trial
through the robot's API (`nxt-web` for the NXT, `robotctl` for the duck), waits, reads the log
back, returns the metrics in `extra`. A person resets the robot between trials.

Friction:

- No per-call timeout in the core, and up to 8 automatic retries on errors mentioning
  "timeout" or "connection" (`_retry.py:44-79`). A physical trial must not be repeated
  automatically: the adapter enforces its own timeout and the run sets `EVAL_MAX_RETRIES=1`.
- **The unit of evidence is items, not repeats.** Tests average repeats per item
  (`_runs.py:110-130`); at least 3 items for any test, more than 5 for a confidence interval
  (`pair_test.py:172`, `stats.py:296-310`), and "ten items is a smoke test"
  (`INTEGRATION.md:428-430`). With slow live trials, design many short scenarios rather than
  many repeats of few.
- Manual resets fit badly in one long `evh run`. The likely shape: run trials from our own
  tool, then `import-run` the per-trial numbers.

### 2. Replay recorded runs (offline)

Items: frozen sensor logs (CSV/JSON as text). Arms: controller logic run in Python against the
log ("given these readings, what would you do?"). Score: agreement with what worked, or
reference-free rules (would it have hit the wall?). Fast and free, so hundreds of items.

Friction: the NXC programs run on the brick, not in Python, so replay needs the decision logic
also available in Python (or nbc's simulator, untested). Items are read as UTF-8 with
replacement (`run.py:348`), so logs must be text.

### 4. LLM as planner

Items: commands plus a scene description. Arms: models. Output: a plan in the robot's actions,
as JSON text. Two ways to score:

- **Rule-based `score()`**: the plan parses, uses only allowed actions, respects limits.
- **LLM judges** in `grade` mode on declared dimensions (`RUNBOOK.md:695-780`). A judge
  "reads no reference" (`judge_score.py:1333`), so "compare to the ideal plan" needs custom
  code in `score()`. Judges must be validated against people before they count.

Then the top plans are executed (idea 1) — eval-harness picks which ones deserve robot time.

### 5. Simulation vs reality

The Microduck makes this concrete: the same ONNX policy in the MuJoCo simulator and on the
robot are two arms on the same scenarios. The arena already races policies over five perturbed
seeds and reports a mean ([MICRODUCK.md](MICRODUCK.md)); eval-harness adds whether two policies
really differ.

Friction: arms on different dataset versions are never compared (PRD-001), so sim and real
must share the same frozen scenario files.

## Gaps that would be eval-harness work (robotics pushing back)

Each needs checking against eval-harness's own design before it becomes work there.

1. `call_system` gets only the item text and params — no `item_id`, no typed fields
   (`run.py:362-365`).
2. No "do not retry, this has side effects" mode for adapters that move hardware.
3. Run-to-run spread is computed but not used by the tests; the leaderboard computes
   `__spread_*` (`leaderboard.py:643`) and does not appear to show it.
4. Reference-free robot metrics are treated as "quality cannot be scored" in messages
   (`run.py:733`) and only cost/speed kinds count as reference-free in the catalog
   (`catalog_adapter.py:573-578`).
5. Trials with a human in the loop (reset between items) have no first-class shape.

## Suggested first step

Idea 5's first half needs no hardware: race the arena's vendored reference policy and one
other policy over the arena's seeds, export per-seed times, and `import-run` them as two
arms. That tests the whole path (scenario items → per-item scores → `pair-test`) before any
robot is on the desk. The arena does report per-seed times: a stored run's JSON has
`per_seed: [{seed, status, time_s}]` (checked 2026-11-13, see MICRODUCK.md). Five seeds is too
few items for a confidence interval (more than 5 needed), so a useful comparison races more
seeds or more events than the arena's default five.
