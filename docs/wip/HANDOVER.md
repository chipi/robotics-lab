# Handover: the MVP 1 wrap-up, for the next session

Started 2026-11-24. The operator moved the cut point: the session was cleared **on
2026-11-24 evening, in the middle of step 4.5**, and a new agent continues the next day from
here. A fresh session reads this first ("Last state" at the end is the pick-up point), then
the documents it names. Keep this file the living status; finalize it at the end of step 5.

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
| U-STOP, U0 (ADR-0021), U-SHOTS | done: 9ef2d59, de549d2 |
| U1 tokens, U2 fonts, U3 UI kit | done: 8869f21, c05f66f, 4121cd7 |
| U4 stage, U5 body, U6 time, U7 layout store, U8 confirm | done: ef8bdad, 3705020 |
| U9 the palette library (`libs/web/palette`, not wired yet) | done: fc46a9f |
| U10 Observatory restyle, U19 Mission Control restyle | done: b71ab93, 2e51865 |
| Review round 1 and its tuning, U11 Observatory on the stage | done: ea2dcf7 |
| U12 Observatory camera | done: 6f7e7f7 |
| U13 Observatory bodies (ghost, trail, x-ray, inspector on `i`) | done: 85de15f |
| U20 Mission Control two-press confirm | done: d6fa1ca |
| U21 Mission Control body view on the stage | done: 61aca43 |
| Review round 2 (3D) and its fixes | done: 5b68eb6; the answers' settings: see "Last state" |
| U22 Mission Control panels and layouts | done: c565d96 |
| U23 readiness card, U14 time, U25 Mission Control palette verbs, U15 signals | done: 187f08a, e49660a, 18e3614, 354fe11 |
| U16 Observatory panels and layouts, U17 evidence links | done: 2805f06, 5ae343f |
| U18 Observatory palette verbs, U24 Mission Control evidence link (`libs/web/evidence.js`) | done: 5275bfa, fc7d78f |
| Review round 3 | answered 2026-11-25 ([round 3](https://claude.ai/artifact/EqGutKa2fH14TcgbUuQzHM)); the decisions are in LOOK-AND-FEEL-PLAN; the fixes and the timeline redesign are in progress |
| U26 | not started |

Next: the operator's answers to **review round 3** (Q1 to Q6), their fixes and the six items
"already on my list" on the round 3 page; then U26 (the sweep), **review round 4** (final).

How a unit runs (it worked this session): an `implementer` subagent on sonnet per unit with
the brief in [look-and-feel/UNIT-BRIEF](look-and-feel/UNIT-BRIEF.md) and the plan row; units
on disjoint files run in parallel. The agent does not commit; the main session reads its
report, runs the full page suite of the app it touched through long-job, looks at the shots
itself (`scripts/look_shots.py --only <view>`), commits, pushes, and watches CI to `VERDICT`.

Review rounds: `look_shots.py --out docs/wip/look-and-feel/roundN --slim`, then a before/after
page as an Artifact ([round 1](https://claude.ai/artifact/V7JjkVFPdAmLxd6TCNdtpw),
[round 2](https://claude.ai/artifact/KmLQUpUhykST6cYDHXbqDX); their sources are
`look-and-feel/review1.html` and `review2.html`), numbered pairs, four or five questions, and
"already on my list". The operator answers by number; record the answers in the plan's
decisions list.

## Decisions to keep

- MVP 1: the official marker plus keep-by-kind; backups A + B1 after the cut-over; telemetry on
  (`staging`); tokens and `tailscale serve` at the cut-over; X3 = staging, dev = worktrees, prod
  later. Step 4.5: everything picked; verdicts neutral for a correct end; live is yellow with its
  own glyph (back to the operator if the token test finds it too close to warn); the contact
  shadow ships. One design system for both apps; density is the only deliberate difference.
  Review rounds 1 and 2: the answers are in the plan's decisions list.
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

2026-11-25 evening. Every 4.5 unit except U26 is on main (U14 to U18, U23 to U25, see the
table); each landed after the full page suite of the app it touched passed locally, plus
`make lint` and `make test-web`. Review round 3 is published and waits for the operator.

- **CI:** 187f08a and 5ae343f green. e49660a and 354fe11 were red only on the Pages deploy
  (GitHub's outage that afternoon, 500 and 502); 5ae343f's deploy replaced them.
- **Round 3's questions:** Q1 the two verdicts on the robot page (the fit card against
  Readiness), Q2 the battery line, Q3 STOP selected when the palette opens, Q4 signal limits
  only on a run without a pose, Q5 the Follow live checkbox beside the Live/Replay badge, Q6
  anything else.
- **Gaps the units found, not built:** the robot view has no run key and no `allow_real_runs`;
  a goal run's result has no time of its own (U24 uses `progress.elapsed_s`);
  `createTimeModel` cannot leave live without a seek (U14 parks 1e-5 s before the edge); play,
  speed and loop still live in the shell, not the time model.

Lessons from this session (each cost a red CI or a debug round):

- **A repaint that rebuilds a button drops its arm.** A list or drawer holding a two-press
  (`dangerous()`) button must skip a repaint whose data is unchanged (settings.js `calPaint`,
  `stVersions`; app.js `renderAreas`). Found as a CI timeout on "the tape", d6fa1ca.
- **Back-date, tick and read in one synchronous `page.evaluate`** when the page receives
  live events: a state event between the steps re-renders the element (ea2dcf7's red CI).
- **An off-screen three.js sprite is not drawn, so `onBeforeRender` never sizes it.** A test
  measuring on-screen size must put the object in view (`adapter.iso()`, test-only).
- **A page test for `libs/web` runs with an app's page tests** (Playwright, Chromium), never in
  `test-web` (standard library only), or it skips silently.
- **A deliberate change to an old token's value** goes in `AMENDED` in `test_tokens.py` with
  the round that decided it, not by editing the pre-v2 snapshot.
- Two suites running at once on this machine slow each other enough to expose races. That
  is useful: treat each such failure as real until its cause is found.
