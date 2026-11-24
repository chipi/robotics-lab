# Brief for every step 4.5 implementer

Read before your unit. Repo: `/work/robotics-lab/mission-control` (worktree of
github.com/chipi/robotics-lab, branch `mission-control`). Several implementers work in this
tree at the same time, each on its own files.

## Read first

- [LOOK-AND-FEEL-PLAN](../LOOK-AND-FEEL-PLAN.md): the rules for every unit, the operator's
  decisions, your unit's row, the frozen contracts. Names in the contracts are frozen: if one
  cannot work, stop and report; do not rename.
- [ADR-0021](../../adr/ADR-0021-one-design-system-and-3d-stage.md).
- `libs/web/tokens.css` (U1), `libs/web/ui.css`, `status.js`, `motion.js`, `brand.js` (U3):
  use them; do not edit them. Need a token or a kit change? Report it; do not add it.
- One design system for both apps (the operator): the same tokens and components; density is
  the only deliberate difference (Observatory compact, Mission Control regular).

## Rules

- Repro first: a failing check, then the change, then a mutation check. Quote the failure.
- Touch only the files your brief names. Do **not** edit the `Makefile` or
  `libs/web/tests/test_tokens.py`: if a new test file must join a Makefile list, or a hex
  allowlist cap in `test_tokens.py` can go down, say so in the report with the exact line.
- STOP stays static HTML, one tap, never disabled, never behind a confirm, never under a layer.
- Reduced motion is honoured (the `--dur-*` tokens, `motion.js`).
- Mission Control's phone page stays light: shared modules load lazily.
- No new dependencies. No Docker builds (a build hold is in force). Do not commit or push.
- Never `pkill`; stop only PIDs you started. No `python3 - <<EOF` heredocs: write scripts to
  files under `$HOME/.cache/robotics-lab-tests`.
- Code comments only to say why.

## Running things

```bash
export TMPDIR=$HOME/.cache/robotics-lab-tests
export ROBOTICS_LAB_SIM_LOCK=/tmp/claude-1000/-work-robotics-lab-main/sim.lock
make lint; echo EXIT=$?
make test-web; echo EXIT=$?
# one Observatory page test
cd apps/observatory && uv run --frozen python tests/<file>.py; echo EXIT=$?
# one Mission Control page test: copy the invocation from the Makefile's test-control-page
```

Run only your unit's page test files, not the full suites: other implementers run tests at the
same time, and the full suites run once per wave. A failure that looks like interference (a
port, a lock, a timeout) is re-run alone before it counts.

Screenshots: `cd apps/observatory && uv run --frozen python ../../scripts/look_shots.py --out
DIR [--only TEXT]`. The before set is `docs/wip/look-and-feel/before/`. Shot
`observatory-eye-dark-1440` is not stable across runs (K51).

## Report

Files changed, the failing check before the change, gate lines with their EXIT values, the
mutation result, the shots that changed (when your unit changes a page), the Makefile or
allowlist lines to change, and what you did not do or could not check.
