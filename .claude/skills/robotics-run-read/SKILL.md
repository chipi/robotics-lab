---
name: robotics-run-read
description: Read a duck run and say what happened. Summarises a run directory (the runner's folder under robots/duck/runs/, or a data-folder run with run.mcap) into the verdict and its judge, the build identity, the ticks with requested/applied, the stops and guards that fired, and belief against truth. Use when asked "what happened in run X", "did it pass", "why did it stop", "which build was that", "does this run open in the Observatory", or before comparing two runs. Do not use to run or score a batch (use challenge-batch) or to start the simulator (use sim-run).
metadata:
  permissions:
    read: [robots/duck/runs, "<data folder>/runs", "~/.config/robotics-lab/installation.json"]
    write: []
    execute: [scripts/run_summary.py]
---

# robotics-run-read

Read-only. Nothing here starts the simulator, writes into a run, or imports into the operator's data folder.

## Preflight

1. Name the one run directory. `scripts/run_summary.py DIR` lists the runs when DIR holds several and exits 2; pick one.
2. Know which form it is: a runner folder (`ticks.jsonl`, `result.json` or `results.json`, `start.json`) or a data run (`run.mcap`,
   with `source/` for an import). Details and the file formats: `references/run-format.md`.

## Read

```bash
.claude/skills/robotics-run-read/scripts/run_summary.py robots/duck/runs/<run>        # text
.claude/skills/robotics-run-read/scripts/run_summary.py --json DIR                    # for another script
.claude/skills/robotics-run-read/scripts/run_summary.py --data <data folder> DIR      # find run.mcap by result.json's key
```

Every field the script cannot find says `recorded: false` and why. Report that as it is: a run from before 2026-11-26 (ebe0b8a) has no
`build` and no requested/applied; an explore run has no result file; a run with no `run.mcap` has no judge record.

## Success: several signals, reported rung by rung

A run "passed" only when these agree. One alone is not proof.

1. **Verdict**: `result.json` `pass` and `failed` (the runner's judge, against the simulator's truth). `end` in `run.mcap` is `ended`
   whatever the outcome, so it says the file closed, not that the run passed.
2. **Judge**: `judge_profile`, `judge_scene`, `judge_truth` in the run record. `judge_truth.available: false` or a non-empty
   `unenforced` means the truth checks did not all run.
3. **Build**: `build.id`, and `dirty: true` means the tree differed from the commit; two runs compare only if their ids differ in the part
   under test. `build.seed` is the depth-impairment seed, not the scenario seed.
4. **Ticks**: `requested` against `applied`; they differ when the speed cap acted.
5. **Truth**: no stop by guard, contact or fall; belief error small against the truth (`belief_vs_truth`).
6. **Opens**: the run imports and loads in the Observatory (below), when the question is about the file.

"IDLE" or `end: ended` is not a pass; a `stopped_by_guardrail` or `trapped` event with `pass: true` is a contradiction to report.

## The file opens in the Observatory

The Observatory's command is `observatory import <run folder>` (there is no `import-run` there; `evh import-run` is the eval harness's).
It writes. Never run it on the operator's data folder: point a scratch installation at a scratch folder and run it there
(`references/run-format.md`, "Scratch import"). The gate for the format is `make test-run-compat` (Chromium; Lichtblick only with
`COMPAT_LICHTBLICK=1`); run it when the run format or the reader changed, not to read one run.

## Never

- Write, rename or delete anything under `robots/duck/runs/` or the data folder.
- Import into `~/.config/robotics-lab/installation.json`'s data folder or index; set `ROBOTICS_LAB_INSTALLATION` to a scratch file.
- Call a run built from a dirty tree, or with no `build`, comparable to another without saying so.
- Edit `robots/duck`, `libs/runner`, `libs/runfile` while another agent works there; read them.

## Not covered

Anomaly detectors (`observatory anomalies`), the pages, video export, NXT runs, a live run being written (`run.live.mcap`), and
the real robot's runs. The belief-vs-truth number is recomputed from the start alignment and ignores a map jump after a relocalise fix.
