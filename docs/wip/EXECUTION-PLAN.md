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

## Phase 0 — in flight

- The navigator (worktree `nav-frames`): one frame for the grid, the belief and the memory, the fix
  gate branching on mapd's own status; the stairwell edge b11 r2 placed 0.45 m short, reproduced
  from its depth frames and fixed; a recovery before a refusal counts and before "trapped"; then b12
  (5 runs × 20 min from scratch, scored by floor coverage and rooms).
- The challenges: 22 (one room explored completely, a drop by the start), 23 (two rooms through a
  door), then 21 (ten goals in a row without a reset, pivoting beside boxes, heading scored). The
  course closes at 23.

## Phase 1 — land it, and the go-to evaluation

- Merge `nav-frames` into mission-control; push to main on the operator's go (no pull requests).
- The phase 1 go-to evaluation in the apartment (`duck-eval`), not run in a long time.

## Phase 2 — one repository, restructured (RFC-0018), and the Observatory rename

- `apps/` (the Observatory, Mission Control, nxt-web), `libs/` (the run format, the gate, the world
  model), `robots/` (each robot's profile, description and plugins); a CI check on package
  boundaries.
- miniview becomes the Observatory in name too (RFC-0014 step 12).
- Nothing else in flight. Done when every test and the docs build are green and one recorded run
  replays identically.

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
