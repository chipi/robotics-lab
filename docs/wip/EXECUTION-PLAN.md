# The plan we execute on (from 2026-11-19)

**Status:** the operator's plan, 2026-11-19: "write this down in a file and we execute on this". Each
phase ends with a checkpoint (§ The checkpoint) before the next one starts.

**What it is for** (the operator, 2026-11-19): "we are creating [a] baseline and after we do all
RFCs and [the] rest of the plan we will go back to making [the] planner better; now [the] goal is to
have a baseline and to deliver our vision so we can enable ourselves to evolve [the] planner and
explore boundaries." So the phases deliver the platform (robot profiles and plugins, anomalies, the
views, the restructure) and record where the duck stands as the baseline; a weak result is recorded
as baseline and a known issue, not chased inside the plan. Improving the planner comes after phase
6.

The order: **land and phase 1 → restructure → profiles and anomalies in parallel → look-far on the
profiles → views → the EV3.** RFC-0018's restructure moves every file, so it happens in a quiet
moment with nothing else in flight; the RFCs after it build on the new layout.

Constraint #1 throughout: every run starts from scratch; no map, objects or landmarks carried
between runs. Nothing learned on one robot is hard-coded for all (RFC-0020).

## Phase 0 — done (2026-11-19)

- The navigator (worktree `nav-frames`): one frame for the grid, the belief and the memory, the fix
  gate branching on mapd's own status; the stairwell edge b11 r2 placed 0.45 m short, reproduced
  from its depth frames and fixed; a recovery before a refusal counts and before "trapped"; then b12
  (3 runs × 20 min from scratch, cut from 5 by the operator, scored by floor coverage and rooms).
- The challenges: 22 (one room explored completely, a drop by the start), 23 (two rooms through a
  door), then 21 (ten goals in a row without a reset, pivoting beside boxes, heading scored). The
  course closes at 23. Seeds: 22 at 10, 21 and 23 at 3 (the operator: no 10-seed runs now).

### Phase 0 checkpoint

**Built:** one frame (`09922a6`), the glance's rim (`af7a6fb`), the recovery (`8f96429`), floor
coverage for the apartment (`b2c06a5`); challenges 21–23, a challenge mode for exploring and a
reusable floor-coverage judge (`14e58af`, `d2eafdb`); mapd's own status on every fix (`28c5cc9`).
Merged into mission-control as `05f4468`; `make test-duck`, `test-viewer`, `test-control`, `lint`
and `docs-lint` all PASS on the merged tree.

**Measured:**

| What | Result | Against |
| --- | --- | --- |
| One frame, an injected 0.9 m jump at 120 s | walls off their real place relative to the duck after the jump: median 0.034 m, worst 0.109 m | 0.228 m and 0.261 m without the fix (one run each) |
| The glance's rim, 379 recorded glances | apartment: short by over 30 cm 0 of 24 (was 5), worst −21 cm (was −47); challenges 8–11: over 30 cm 5 of 355 (was 67) | the replay of the same frames before the fix |
| b12, 3 runs from scratch | rooms median 4, floor known mean 36.9 %, trapped at 2.0, 12.5, 10.3 min; no contact, no fall in 117 m | b11: rooms median 2, floor 31.7 %, four of five trapped under 4 min |
| Challenge 22 | 9 of 10, coverage 88–97 % (the one fail trapped at 65 %); nearest to the drop 0.28 m | the bar 8 of 10; the coverage bar set at 0.80 from these runs |
| Challenge 21 | 3 of 3, every goal; position error max 0.12 m, heading max 2.4° | 3 seeds only |
| Challenge 23 | 1 of 3 at the 0.80 bar (2 of 3 at 0.75): a narrow door never crossed (K2), one room at 75 % | 3 seeds only |

**Did not work:** the recovery fired 9 times in b12 and freed the duck none of them (the creep never
ran: the sensor saw a wall or frame 46–140 mm ahead); every b12 run still ended "trapped", each in
the kitchen with 0.147 m of room, just under the 0.15 m pivot gate. A tight-pivot-gated target the
explorer should not have chosen is the agent's reading, not tested (K22). Safety held in every run.

**Not done:** the taken-loop-closure path of the gate never ran (mapd's `loops` never stepped); the
creep never ran in the simulator; one run per arm for the frame fix; 21 and 23 at 3 seeds.

**Known issues:** closed K-rim (the misplaced edge); new K22–K27 (the explorer's targets without room
to pivot, the recovery not freeing the duck, the arc's inner sweep and the tight pivot without a
sensor check, phantom remembered points, the untested loop-closure branch, the glance's error in the
challenge scenes).

**Recommendation:** proceed to phase 1. The baseline is measured; what did not work is the planner's
to improve after phase 6, recorded as known issues. The operator had said to start phase 1 as soon
as phase 0 was done; its go-to evaluation started at once (run 16), the push to main waits for the
operator's go.

## Phase 1 — done (2026-11-19)

- Merge `nav-frames` into mission-control; push to main on the operator's go (no pull requests).
- The phase 1 go-to evaluation in the apartment (`duck-eval`), not run in a long time.

### Phase 1 checkpoint

**Landed:** mission-control pushed to main at `245017b` on the operator's "Push 0 to main", with the
Observatory video changes (`6970d6e`: the discovered map over a faint outline of the real room,
objects labelled in the view, a compact fixed HUD, `--hide`, `--intro`); CI on `245017b`:
`VERDICT GREEN — success 6`.

**Measured:** run 16 (`duck-eval --goals 20`, each goal from the dock with an empty map): navigator
reached 20, within 0.25 m by truth 20, refused 0, timeouts or stalls 0, contacts 0, falls 0 — the bar
met, as run 15 met it on 2026-11-15, now on the navigator with everything since (the lease, guardrails,
relocalisation, the frame fix, the rim fix, the recovery).

**Not done:** run 17 (the same goals chained without a reset) was optional and not run.

**Recommendation:** proceed to phase 2 (the restructure), with its ten decisions
([PHASE2-RESTRUCTURE-PLAN.md](PHASE2-RESTRUCTURE-PLAN.md) §6) taken first.

## Phase 2 — one repository, restructured (RFC-0018), and the Observatory rename

- `apps/` (the Observatory, Mission Control, nxt-web), `libs/` (the run format, the gate, the world
  model), `robots/` (each robot's profile, description and plugins); a CI check on package
  boundaries.
- miniview becomes the Observatory in name too (RFC-0014 step 12).
- Nothing else in flight. Done when every test and the docs build are green and one recorded run
  replays identically.

**Done 2026-11-19** on the branch `mission-control`, not yet on main: the result, the golden and what
differed from the plan are in [PHASE2-RESTRUCTURE-PLAN.md](PHASE2-RESTRUCTURE-PLAN.md) §7.

## Phase 3 — two parallel streams on the new layout

- **RFC-0020, steps 1–3:** the duck's profile; the numbers out of code; the four interfaces
  (locomotion, range sensing, localisation and map, looking) with the duck's code behind them. The
  duck's behaviour stays identical, proven by replays and seeded challenges 1–5. Owns the navigator
  and the simulator.
- **RFC-0019, steps 1–2:** the robot-tagged anomalies; the analysis as a command-line table over a
  run, used on b11 and b12; a detector joins only if it stays quiet on clean runs.

## Phase 4 — behaviour on the profiles

- **RFC-0012, look far:** the pace from the map ahead, its numbers read from the robot's profile.
- **Crossing edges:** first probe a constant trim against the walk's drift (5 tries); a deadband or
  burst steering only if the trim does not walk straight. Challenge 16 waits on this.
- An apartment batch scored by floor coverage.

## Phase 5 — the views

- **RFC-0019:** the Observatory's anomaly track, map pins and the three maps; Mission Control's live
  side; the anomaly panel in the video and the watch page.
- **RFC-0020:** the robot page in the Observatory; runs carrying their profile and plugin versions;
  the Eye drawn from the profile; Mission Control showing a robot's profile and why a goal was
  refused.

## Phase 6 — the first other robot

- **The EV3** through RFC-0020 step 5: its profile, a tracked locomotion plugin, its sensors, odometry
  localisation: the test of "a robot platform where we can load any robot".
- The NXT after it, once it has a sensor that sees the floor. The NXT hardware test (the operator at
  the brick) can happen at any time.

## Parked

Nav2 (RFC-0015, after its first drive); heading correction (a `yaw_vs_truth` detector only, built if
it fires); Mission Control's mobile app and Slack; challenge 16 (waits on phase 4's crossing fix).

## The checkpoint

At the end of every phase, before the next one starts (the operator, 2026-11-19: "after phase 0
let's do a summary of how things went and should we [do] another small iteration here and fine tune
some things before we proceed with phase 1. Same after each other phase"):

1. **A summary of how the phase went:** what was built, what was measured (each number with the
   command or run behind it), what did not work, what was learned, and what is NOT done.
2. **A recommendation:** proceed to the next phase, or one small iteration first to fine-tune named
   things, with its cost and what it would show.
3. **The operator decides.** The next phase starts only on the operator's word.
4. The summary is written into this file under the phase (a few lines and the commits), so the plan
   stays the record of how it went.
