# The plan we execute on (from 2026-11-19)

**Status:** the operator's plan, 2026-11-19: "write this down in a file and we execute on this".
Each phase ends with a checkpoint (§ The checkpoint) before the next one starts.

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

**Known issues:** closed K-rim (the misplaced edge); new K22–K27 (the explorer's targets without
room to pivot, the recovery not freeing the duck, the arc's inner sweep and the tight pivot without
a sensor check, phantom remembered points, the untested loop-closure branch, the glance's error in
the challenge scenes).

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
reached 20, within 0.25 m by truth 20, refused 0, timeouts or stalls 0, contacts 0, falls 0 — the
bar met, as run 15 met it on 2026-11-15, now on the navigator with everything since (the lease,
guardrails, relocalisation, the frame fix, the rim fix, the recovery).

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

**Done 2026-11-19** on the branch `mission-control`, not yet on main: the result, the golden and
what differed from the plan are in [PHASE2-RESTRUCTURE-PLAN.md](PHASE2-RESTRUCTURE-PLAN.md) §7.

### Phase 2 checkpoint

**Built:** C0–C10, 14 commits (`a3bad74` … `b7c7d13`): `libs/runfile`, `libs/gate` (`robotgate`),
`libs/worldmodel`; `apps/observatory`, `apps/mission-control`, `apps/nxt-web`; `robots/duck`; the
rename to the Observatory with compatibility aliases; `OBSERVATORY_*` variables with the old names
as fallback; an import-boundary check in `make lint` and CI.

**Verified by the lead, on the final tree:** `make ci` → every stage PASS, `ci PASS`, `MAKE_EXIT=0`;
the golden (`python3 scripts/golden.py`) gives the same five hashes on `pre-restructure` and on the
final tree (`3e1aa07b…`, `f357641d…`, `6bfdfdde…`, `11b9a04a…`, `b1edc258…`); main has no branch
protection, so the renamed CI jobs break nothing; the operator's Observatory restarted under its new
name, healthy, 1618 runs.

**Did not go to plan:** two history rewrites on the unpushed branch (a red page test in C4–C5, a
lint line in C3–C6d), each fixed in its own commit; the tip unchanged by them.

**Not done:** ~40 probes not run after the path rewrite (K28); the container mounts `robots/` from
this worktree and has a new memory cap (K29); four moved-aside environments for the operator to
delete; names kept as `miniview` on purpose (K30); nothing run on GitHub yet.

**Recommendation:** push to main, re-up the Observatory from main, then phase 3.

## Phase 3 — two parallel streams on the new layout

- **RFC-0020, steps 1–3:** the duck's profile; the numbers out of code; the four interfaces
  (locomotion, range sensing, localisation and map, looking) with the duck's code behind them. The
  duck's behaviour stays identical, proven by replays and seeded challenges 1–5. Owns the navigator
  and the simulator.
- **RFC-0019, steps 1–2:** the robot-tagged anomalies; the analysis as a command-line table over a
  run, used on b11 and b12; a detector joins only if it stays quiet on clean runs.

### Phase 3 checkpoint (2026-11-19)

**Built** (branch `mission-control`, not yet on main; details in
[PHASE3-PREP.md](PHASE3-PREP.md) results):

- RFC-0020 steps 1–3: the profile format and validator (`libs/runfile`), the duck's profile
  (`robots/duck/profile.json`, variants `sim` and `real`), the navigator reading its numbers from
  it, the four interfaces with the duck's plugins behind them.
- RFC-0019 steps 1–2: nine detectors over a recording and `observatory anomalies` (five on the
  default track, quiet on the clean runs); the navigator raising twelve kinds of anomaly itself.
- The "phantom" by the dock is a real cube the layout omitted ([PHANTOM.md](PHANTOM.md)); the layout
  now holds the seven free bodies; the depth shortfall is the sensor's pitch with radial ranges, and
  mapd's axial model is what differs ([RANGE.md](RANGE.md), K34).
- Phase 1's 20 goals frozen in `robots/duck/sim/phase1_goals.json`; run 19 on them: 19 of 20 within
  0.25 m by truth, refused 1 (K38), 0 contacts, 0 falls, 0 timeouts: the bar met.

**Verified by the lead:** `make ci` on the merged tree (`9589921`): every stage PASS, `ci PASS`,
`MAKE_EXIT=0`; `observatory anomalies` re-run on b9 r2 (0 on the default track) and b10b r2 (the
graze: near miss 0.071 m, then contact); the cube in Pollen's scene file at (−0.30, 0.10); the
navigator's diff for the hooks leaves the files that decide commands untouched.

**Behaviour unchanged, how strongly:** exact where inputs are recorded (`duck-replay` over 122–126
runs identical before and after each step; the locomotion replay 36,888 of 36,888); pass counts
where they are not (seeded challenges 1–5, 11, 16–19 within the base's own flips). The simulator is
not deterministic (K13), so "identical" is not claimed for live runs.

**Not done:** RFC-0019 steps 3–5 (index, pages, Mission Control, video: phase 5); ten of the twelve
robot-tagged anomalies raised by tests only (K37); duck numbers still in code (K32); the radial
model on Pollen's replay bench (K34); the real duck's numbers (REAL-DUCK.md).

**For the operator to review (RFC-0019 §6):** the robot-tagged anomalies' severities and limits:
refusal burst 3 legs within 0.10 m, room disagrees 280 mm, head off its walking pose 0.30 rad for
1 s, refused unexplained 0.30 m, a silent stream 3 s.

**Recommendation:** push phase 3 to main, then phase 4.

## Phase 4 — behaviour on the profiles

- **Odometry by speed (K8)** first, since look-far makes slow walking common.
- **RFC-0012, look far:** the pace from the map ahead, its numbers read from the robot's profile.
- **Crossing edges (K1):** first probe a constant trim against the walk's drift (5 tries); a
  deadband or burst steering only if the trim does not walk straight. Challenge 16 waits on this.
- A regression gate: challenges 1–11 (3 seeds), phase 1's evaluation on the fixed goals.
- **Open items closed alongside** (the operator, 2026-11-19: "close all open items along the way"):
  the probes run and fixed (K28), old runs marked in `duck-replay` (K33), the radial model on
  Pollen's replay bench (K34), the edge-error budget (K27), the unexplained point (K25), better
  detector rules (K12, K36), where the simulator's runs diverge (K13), the Observatory's memory
  (K29).
- An apartment batch scored by floor coverage, which also measures K37, K18 and K4–K6.
- Staying with their phases: the planner's (K22–K24, K38, K2, K9, K11) after phase 6; the EV3's
  (K10) in phase 6; hardware and choices waiting on the operator (K15–K17, K19, K20).

### Phase 4 results (2026-11-20, branch `p4-nav`, not pushed; the apartment batch not run)

**Built** (3 commits on `c79fe6b`):

- **K8 closed for the navigator's dead reckoning:** the profile's `odometry.by_speed` table, its
  validator, each odometry step of a straight walk scaled by the speed commanded (arcs and pivots
  keep `scale`, which measured right on arcs). Re-measured: truth/odometry 0.856, 0.893, 0.913,
  0.940 at 0.2, 0.25, 0.3, 0.4 m/s. Walking at 0.2 m/s in navigation, belief/truth 0.993 over
  30.8 m. The map stays in one scale: K39.
- **RFC-0012 step 2, the pace:** `nav/pace.py`, `locomotion.pace` in the profile. On challenges
  6, 7, 10, 11 (seeds 1–3, two repeats) against the base: no gain in refusals or closeness, about
  15 % more time on 10 and 11. Caution covers 79 % of the straight walking.
  `caution_mps` = `cruise_mps` turns it off.
- **K1, the crossing, open:** a constant trim does not help (3 of 5 against 5 of 5 with no turn
  commanded); a heading deadband built and left off: challenges 16–19 base 1/24, pace 2/24,
  pace and deadband 5/24, deadband alone 4/24 (STEPS.md). Challenge 16 still waits.

**The regression gate** (the tree with the pace, deadband off): challenges 1–11, seeds 1–3 once:
1–4 3/3 each, 5 2/3 (seed 2 refused "no room to turn", the flip K13 describes), 6 0/3, 7 0/3,
8 and 9 3/3 (the right answer is a refusal; all refused), 10 3/3, 11 3/3; 0 contacts, 0 falls,
the closest approach by truth 0.126 m (challenge 11, the contact line 0.083 m). Phase 1's
evaluation: `PHASE1 goals 20: navigator reached 20, within 0.25 m by truth 20, refused 0,
timeouts or stalls 0, goals with a contact 0, falls 0 — bar MET` (run 19: 19 of 20; goal 20 is
now reached, 0.103 m).

**Challenges 6 and 7 do not meet the 8-of-10 bar, on the base too (K40):** 1/6 and 0/6 on
`c79fe6b`, 2/3 and 0/3 before phase 3 (`c61ca7f`); last recorded 6–10 of 10 on 2026-11-16.

**Not done:** the apartment exploring batch (the lead); the map's error against truth by pace
(K39); 10 seeds anywhere (3 seeds, per the operator); the pace's measurement on 16–19 beyond the
table in STEPS.md; any cause for K40.

### Phase 4 checkpoint (2026-11-20)

**Built and merged** on the branch `mission-control` (34 commits ahead of main, not pushed): the
three above (K8, the pace, the deadband left off); the tooling items (K28 the probes, K33
`duck-replay` on old runs, K34 the radial model, K25, K12's belief-vs-truth rule, K13's first
divergence, K29); K36's room rule in the navigator; K27's comment; the STOP race in Mission
Control's fake robot (the page test's 1-in-4 failure, `b8fca06`); every anomaly limit in the
profile; and three safety fixes found by the apartment batch:

- **K24, the recovery arc** (`2ce1990`): it caused b13 r3's contact (the sensor read 408 mm with the
  head turned away, the memory held 0.098 m; the arc moved 0.043 m into the office landmark). An
  arc now needs the memory's room. Replay of the 16 recorded recoveries: the old rule reproduces 16
  of 16, the new one turns 5 of 10 arcs into a survey, the contact's among them.
- **K26, loop closures** (`8f40737`): the gate took mapd's loop closures unchecked; both ever
  recorded made the belief worse (one by 2.28 m, error 0.11 → 2.22 m). A large closure is now held
  unless the landmarks agree. Replay: both held (error stays 0.11 and 0.17 m); the other 65 recorded
  fix events of 1614 runs unchanged.
- **Raw odometry recorded on every tick** (`6ade19d`), so dead reckoning can be replayed (K41).

**K40 (challenges 6 and 7) found and decided:** the cause is `3ceef19`, the tight-pivot rule of
2026-11-18 (0.15 m, once per spot; parent 7 of 12, it 0 of 12 on seeds 1–3, which are these
challenges' hard seeds). The operator kept the rule (option A); the fix goes to the planner after
phase 6.

**Measured:** apartment batch b13 (3 × 20 min): r1 the full 20 min, 72.6 % of the floor, 5 rooms;
r2 11.1 % (25 refusals at one spot); r3 36.6 %, trapped, the contact (fixed by K24). The live check
after K24 and K26 (6 + 3 runs of 10 min): 0 contacts, 0 falls. The navigator's own anomalies fire
live (`refusal_burst`, once per place).

**Verified by the lead:** `make ci` on the final tree: every stage PASS, `ci PASS`, `MAKE_EXIT=0`.

**Not done or not proven:** a held loop closure has not happened live (no closure in the 3 runs
after K26; unit-tested, replayed); a right closure was never recorded, so `closure.agree_m` 0.2 m is
untested on one; K1 (the crossing) stays open; K41 (0.2 m/s 3 % long) is not re-fitted; most
exploring runs still end trapped or boxed in early (K22, the planner); the pace shows no measured
gain (it stays on; its cost is about 15 % time); the edge gate (K27) is the operator's decision.

**For the operator:** the edge gate (K27): the worst measured glance leaves 0.068 m to a real edge,
under the judge's 0.15 m (over 566 runs the closest real approach was 0.108 m, once). Raise the
gate from 0.26 m (measured first), or keep it.

**Recommendation:** decide the edge gate, push phase 4 to main, then phase 4b.

## Phase 4b — the simulator host and the payload (RFC-0021)

[RFC-0021](../rfc/RFC-0021-sim-host-and-payload.md), accepted by the operator 2026-11-19, built
after the phase 4 checkpoint (any host that runs Pollen's simulator; the first is this workstation):
the reset and the socket paths out of the navigator into a host file and host tool, the truth read
by the runner only, a host setup script and a host check script (Linux and macOS on Apple Silicon
from the start), one course run through the split on this workstation (the first host; another host
later, the operator's, with the arena), a second minimal navigator through the same contract.
The runner keeps RFC-0021 §3.1's rule (the operator, 2026-11-20): everything that knows a simulator
lives behind the host file's `kind`, so a second simulator is a new kind, not a change to the
runner, the judge, the recording, the Observatory or Mission Control.

## Phase 5 — the views

- **RFC-0019:** the Observatory's anomaly track, map pins and the three maps; Mission Control's live
  side; the anomaly panel in the video and the watch page.
- **RFC-0020:** the robot page in the Observatory; runs carrying their profile and plugin versions;
  the Eye drawn from the profile; Mission Control showing a robot's profile and why a goal was
  refused.
- **Mission Control as the navigator's control panel** (the operator, 2026-11-19: "really good and
  elaborate", following the patterns the Observatory and Mission Control already have). Per robot:
  - **Modules:** the four interfaces, the plugin filling each (name, version), and its live state
    (streams alive, last fix and whether it was held, the lease, the walking command).
  - **Settings:** every profile number by block, with its `measured` and `why`, the `sim` and `real`
    values side by side, editable through the profile validator; a change applies at the next run,
    never during one, and is saved as a new profile version; every run names the version it used.
  - **Transferable between installations:** the profile holds only the robot (no paths, sockets,
    URLs: today its `control` block has this machine's socket paths and the Observatory's URL, which
    move to a per-installation file); export and import of a profile as one file, checked by the
    validator on import, with a version and a checksum; a diff between two profiles.

## Phase 6 — the first other robot

- **The EV3** through RFC-0020 step 5: its profile, a tracked locomotion plugin, its sensors,
  odometry localisation: the test of "a robot platform where we can load any robot".
- The NXT after it, once it has a sensor that sees the floor. The NXT hardware test (the operator at
  the brick) can happen at any time.

## After the plan

- **TurtleBot3 in Gazebo under ROS 2** (the operator, 2026-11-20: "a different robot, different
  sensor and different sim: it tests our capabilities of abstraction"; "it comes after we finish our
  vision"; a real one maybe bought later). The second simulator kind (RFC-0021 §3.1,
  `gazebo-turtlebot3`): wheeled, a 2D LiDAR, ROS 2 topics, Gazebo's truth, SDF scenes; its profile
  and ROS plugins (RFC-0020), its host setup and check, then a phase-1-style course and challenges
  1–5 judged by the same runner. Needs ROS 2 and Gazebo installed on a host: the operator approves
  that install first.

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
