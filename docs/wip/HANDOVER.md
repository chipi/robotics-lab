# Handover: the MVP 1 wrap-up, for the next session

Started 2026-11-24. The operator's cut point: the session is cleared **after step 5 (the
close-out)**, and a new agent continues from here with steps 6 and 7. Until then this is the
living status, updated as work lands; it is finalized at the end of step 5. A fresh session
reads this first, then the documents it names.

## Where the work happens

- Worktree: `/work/robotics-lab/mission-control`, branch `mission-control`. Commits go to main
  with `git push origin HEAD:main` after `git fetch origin && git rebase origin/main`.
- `/work/robotics-lab/main` is the main worktree; the session's lean-ctx tools are rooted there
  and refuse other paths, so read and edit the mission-control worktree with the native tools.
- The staging stack (`robotics-lab` project) runs on the X3: Observatory 127.0.0.1:8070,
  Mission Control 127.0.0.1:8060, deployed 4e13c2e from `~/deploy/robotics-lab`, fake robot
  only. Telemetry arrives in the homelab (dashboard `robotics-lab-live`).

## The order (the operator, 2026-11-24)

| Step | What | Status |
| --- | --- | --- |
| 3 | MCP for every surface ([MCP-COVERAGE](MCP-COVERAGE.md)) | done: 41ec285, CI green |
| 4 | Look-and-feel research ([LOOK-AND-FEEL-RESEARCH](LOOK-AND-FEEL-RESEARCH.md)) | done: a0425fc, CI green |
| 4.5 | The look-and-feel build ([LOOK-AND-FEEL-PLAN](LOOK-AND-FEEL-PLAN.md), ADR-0021) | in progress |
| 4.9 | Ready for MVP 2? Repo structure, how the apps combine, which app fronts the other | waiting |
| 5 | Close-out: docs, README, screenshots after 4.5, rename and branding, RFC-0024 advisor review | waiting |
| 6 | NXT at the brick (D1, D9, D10); staging redeployed with the NXT robot file first | waiting |
| 7 | Staging cut-over ([STAGING-CUTOVER](STAGING-CUTOVER.md)) after the X3 maintenance window | waiting |

The full step descriptions are in [PHASE5-NEXT-PLAN](PHASE5-NEXT-PLAN.md), "The MVP 1 wrap-up,
in order".

## Step 4.5, where it stands

| Unit | Status |
| --- | --- |
| U-STOP: STOP never under a drawer or the toast (it was, on phone and desktop) | done: 9ef2d59 |
| U0: ADR-0021, the contracts | done: 9ef2d59 |
| U-SHOTS: `scripts/look_shots.py` and the "before" set in `docs/wip/look-and-feel/before/` | see "Last state" below |
| U1 to U26 | not started; the order and waves are in the plan |

Next, in order: U1 (tokens) and U2 (fonts) in parallel, then U3, then wave 3, then **review
round 1 with the operator** (a before/after page from `look_shots.py --compare`). Do not start
U1 or U2 before the "before" set exists, or it is not a before.

The operator wants before/after screenshots at four review rounds (the plan, "Before and
after") and time to give feedback; tune on it before the next wave.

## Decisions to keep

- MVP 1: the official marker plus keep-by-kind; backups A + B1 after the cut-over; telemetry on
  (`staging`); tokens and `tailscale serve` at the cut-over; X3 = staging, dev = worktrees, prod
  later. Step 4.5: everything picked; verdicts neutral for a correct end; live is yellow with its
  own glyph (back to the operator if the token test finds it too close to warn); the contact
  shadow ships.
- MVP 2: RFC-0025 section 9 (Q16 depth camera and mapd on the NXT's Pi; Q21 Recce models feed
  Gazebo, the import designed in MVP 2) and section 5.1 "The gap list" (seven decisions);
  [DEPLOYMENT-NOTES](DEPLOYMENT-NOTES.md) "Decided for MVP 2" (five decisions).
- Still the operator's: the three MCP rules marked as open in MCP-COVERAGE (R6 tokens, R7
  profiles, R8 no opt-out of the rehearsal).

## Constraints that bind every session

- The operator's rules (`~/.config/AGENTS.md`) and the repo's `AGENTS.md`. Push to main is
  granted for this arc's checkpoints; rebase first, secrets scan
  (`~/.claude/skills/secrets-scan/scripts/scan.sh --push`), then watch CI with
  `~/.claude/skills/ci-watch/scripts/ci_watch.py <sha> --repo chipi/robotics-lab` under Monitor
  until `VERDICT`; fix red.
- No new dependencies without approval (approved: OpenTelemetry, `mcp` in the Observatory).
  Never open GitHub issues. Never pkill; stop only your own PIDs.
- Subagents: sonnet or haiku; fable for the advisor; no Opus, no forks.
- Tests: `export TMPDIR=$HOME/.cache/robotics-lab-tests
  ROBOTICS_LAB_SIM_LOCK=/tmp/claude-1000/-work-robotics-lab-main/sim.lock`. Long gate runs go
  through `~/.claude/skills/long-job/scripts/long-job.sh start <name> --cwd <worktree> -- ...`
  and a Monitor on its log: a plain background shell loop died midway once.
- Docs gates without pipes: `make -s docs-lint >/dev/null 2>&1; echo DOCSLINT=$?` and
  `.venv/bin/mkdocs build --strict > $HOME/.cache/robotics-lab-tests/mk.out 2>&1; echo MK=$?`
  then `grep -c '^WARNING'` on it. Lines at most 100 characters, fences with a language, links
  out of `docs/` as full GitHub URLs. A pipe once hid a failing lint and a red push followed.
- `python3 - <<EOF` heredocs are blocked: write scripts to a file.
- **The X3 build hold:** no image build that writes new layers on the X3 until the homelab's
  maintenance window; deploys must be fully cached. So no 4.5 change and not the STOP fix can
  reach staging yet. The cut-over runbook forbids a real robot on a stack older than 9ef2d59.
- The staging engine only through `sudo -n /usr/local/libexec/robotics-staging-deploy
  up|rollback|smoke|status|stop`, up and rollback with the operator's go.
- Never touch Rerun (pid 735512), the robotics-lichtblick container, the NXT or EV3 hardware,
  or test folders in `~/.cache/robotics-lab-tests`; never run `uv sync --no-dev` in
  `robots/duck`. Do not edit `~/.config/robotics-lab/installation.json` without reason.
- The Grafana token is read only through the homelab's env file over ssh, never printed.
- The real duck arrives in one to two months: its items are in
  [REAL-DUCK-BACKLOG](REAL-DUCK-BACKLOG.md). Do not raise it; the operator will say.

## Other sessions

- Recce (the photogrammetry project, renamed 2026-11-24: github.com/chipi/recce, docs
  chipi.github.io/recce, prefix RC-): the gap-list decisions are folded into its
  `docs/wip/gap-list-interface.md`. Nothing is owed to it.
- The homelab agent: planned the backups and built the staging engine; the maintenance window
  is in its NEXT_STEPS.

## Last state

Filled in at the end of step 5, before the session is cleared.
