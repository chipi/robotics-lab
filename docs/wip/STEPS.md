# Walking over and up: what the duck can do (parked), 2026-11-17

Parked by the operator on 2026-11-17 ("let's park this and focus on other challenges so that we can
do explore and apartment, and we will come back to steps later"). Challenges 16–20 (RFC-0008 §3)
wait on this. Challenge 16 picked up again on 2026-11-18 (the last section).

## What was decided before parking

- The duck should walk **over** small things (a home door's threshold, a cable, a rug's edge, a
  book), **not round** them; a step up and down and a short flight of small steps, up and down,
  too. Ordinary home stairs stay refusals (challenges 8 and 9).
- Two numbers in the robot's profile: a **walk-over height** (a thin thing, the floor level on both
  sides) and a **step height** (a change of level, up and down apart).
- The navigator must **notice it is stuck** (walking, the depth ahead not changing) whatever the
  cause: challenge 16 showed the odometry counting on while the feet were blocked (belief 0.29 m off).

## Measured (simulator, `duck/sim/probes/step_height.py`, straight on)

Crossed of tries, at 0.3 m/s:

| Case | 0.5 cm | 1.0 cm | 1.5 cm | 2.0 cm |
| --- | --- | --- | --- | --- |
| Bar, 4 cm deep | 3/3 | 2/3 | 1/3 | 0/3, 2 fell |
| A step up | 3/3 | 3/3 | 0/3, 2 fell | 0/3, 1 fell |
| A step down | 3/3 | 3/3 | 3/3 | 3/3 |
| A flight of 3 up, 0.25 m treads | 1/3 | 0/3 | — | — |
| The same, 0.5 m treads | 1/3 | 1/3 | — | — |
| A flight of 3 down | — | 3/3 | — | 3/3 |

- **Each riser is a chance, not a limit:** up a flight, about 70 % of risers cleared at 0.5–1.0 cm;
  deeper treads did not help.
- **Slower is worse:** at 0.2 m/s, a 1 cm step up 0/5 and a 1 cm bar 1/5 (no falls; stuck with the
  toes at the edge). At 0.15 m/s the duck did not start walking within 6 s.
- **Faster does not help** (2026-11-18, picked up again by the operator, edge-to-edge build, 5
  tries each at 0.4 m/s): a 1 cm bar 4/5, 1.5 cm 0/5 (1 fell), 2 cm 0/5 (1 fell). The limit is about
  1 cm whatever the speed.
- **Not tried:** an angle to the bar; a round cable; the real duck.
- **The scene's construction matters:** a bar laid on a floor that runs under it (challenge 16 as
  built) was crossed 0 of 3 at 1 cm against 2 of 3 for the bar built as three pieces meeting edge to
  edge. Challenge 16's 0/10 was mostly that. Build every floor as pieces meeting edge to edge.

## Reading

In the simulator this walking clears 0.5 cm reliably, 1 cm going up most of the time, and at least
2 cm going down; above about 1.5 cm going up it often falls rather than stops. A 1–2 cm threshold,
cable or rug edge, which the duck should walk over, is beyond it: the gap is in the walking policy
(upstream), not the navigator, unless an approach not yet tried (0.4 m/s, an angle) changes that.

## Picked up again, 2026-11-18

The operator took up challenge 16 again and agreed (2026-11-18, "OK on all suggestions"):

1. **Done:** 0.4 m/s measured (above: no better). An angled approach is still not tried.
2. **Done:** challenge 16 rebuilt in edge-to-edge pieces, its bar 0.5–1.0 cm (what the walking
   crosses), "reach". Not yet run.
3. **In progress:** stuck detection in the navigator (walking, the depth ahead not changing).
4. **The numbers upstream:** drafted for the operator to send, as the odometry note was
   (`UPSTREAM-STEP-HEIGHT-DRAFT.md`, the operator 2026-11-18: "draft it as the other one we have").
5. **Later, low priority — a challenge "too high to cross: stop, do not fall"** for bars of 1.5–3.5
   cm: higher than the walking crosses, lower than the low band sees (3.5 cm + 2 cm/m; flat floor
   reads up to +2 cm). It needs a way to see them first — a straight line of slightly raised returns
   across the way, held over several frames — not tried yet. Low priority: the operator's apartment
   has no door thresholds (2026-11-18).
6. Challenges 17–20 (cables, rug edges, a step up and down, small flights) on the measured heights,
   every floor in edge-to-edge pieces.

## Parked again, 2026-11-18

The operator: "ok on parked 16". What was measured:

- Challenge 16 as rebuilt: 2 of 10 (gate10), then 1 of 10 with a straight push on stuck
  (gate11, reverted). Every failure is "stuck: walking without moving" with a foot at the bar;
  bars of 0.6 cm stalled as well as 0.9 cm.
- The probe with turning (`step_height.py --yaw`, 1 cm, 0.3 m/s, 5 each): straight 4 of 5, turning
  ±0.18 rad/s 2 of 5. The navigator turns 0.1–0.34 rad/s on the way to the bar (correcting the
  walk's drift), more than the probe's turning. Five tries each do not show that turning hurts:
  Fisher's exact test gives a two-sided p of about 0.52 (the RFC-0012 planning pass, 2026-11-18).
  An earlier note here read it as support; it is not evidence either way.
- Once a foot is caught, walking straight does not free it (1.5 s at 0.3 m/s, no motion), and the
  duck does not walk backwards.

Not tried: capping the turn while walking (touches every challenge: a full gate after), seeing the
bar (the low band starts at 3.5 cm) and squaring up to it.

## The cause: turning while the feet meet the edge (2026-11-19)

Challenges 17–19 (gate12, 10 seeds each) failed the same way as 16: 17 1/10 (cables of 0.52 cm
stalled), 18 3/10, 19 0/10, every failure "stuck", no contact or fall. Probed one difference at a
time on a 0.5 cm bar, 5 tries each (`step_height.py`, options `--bar-deep`, `--nav`, `--no-stuck`,
`--no-steer`, `--glance-first`, `--stand`, `--cmd-log`):

| What the walk was | Crossed |
| --- | --- |
| Straight, no turn (4 cm deep; 2 cm deep; after a glance; after 20 s standing; logged) | 21 of 23 |
| Straight with turns of ±0.1 rad/s | 3 of 5 |
| Straight with turns of ±0.25 rad/s | 2 of 5 |
| The navigator's own `go_to` (as is; no stuck rule; small turns zeroed; logged) | 5 of 18 |

Ruled out: the bar's depth, the stuck rule, gaps between commands (0.10 s, the largest 0.11 s), the
head (all zeros while walking), a glance before, standing 20 s before, the simulator falling behind
(its clock / wall 0.996–1.007). The command log shows the difference: walking, the navigator asks
for a turn over 0.1 rad/s in 25–30 of about 70 ticks, +0.57 to +0.65 rad in all, correcting the
walk's drift to the right (also reported upstream, microduck_rl#59). Zeroing turns under 0.35
rad/s made the drift grow until larger turns passed, so that variant still turned while crossing.

Upstream (read 2026-11-19): the walking policy is blind to the floor (no height input), trained on
steps up to 1.5 cm with a 2 cm swing target; walking and turning together are trained (sampled
independently). Nothing upstream reports this effect; the closest is an unmerged dedicated step-up
skill (microduck_rl PR #25) trained with no turn at all.

Next (not built): steer in short corrections only past a heading error, zero turn the rest of the
time; replay, then challenges 16–19, then the full gate (it changes every challenge's walking).

## Phase 4: a constant trim, then a deadband (2026-11-19)

`robots/duck/sim/trim_probe.py`, the simulator, 0.3 m/s, a 1 m wide corridor, truth sampled every tick.

**The walk's drift.** With no turn commanded, the heading falls 0.0706 rad/s on average (clockwise;
the trials' slopes −0.054 to −0.097, 5 trials), −0.56 to −0.88 rad in 10–12 s, 0.41 m off the
line in that time (the trial's 0.4 m limit).

**A constant trim** (a fixed turn added while walking), 5 trials each:

| Trim | Heading slope, flat floor | Crossed a 0.5 cm bar |
| --- | --- | --- |
| 0 (no turn commanded) | −0.0706 rad/s | 5 of 5 |
| +0.07 rad/s | −0.0263 (drift not cancelled) | 3 of 5 |
| +0.11 rad/s | −0.0095 (cancelled on average; the ends of the trials −0.19 to +0.10 rad) | 3 of 5 |

So the trim does not walk straight at 0.07, and at 0.11 walks straight on average but crosses no
better than a commanded turn does: with the drift left alone (heading falling 0.5 rad on the way)
the straight walk crossed 5 of 5; with the turn commanded, 3 of 5. The drift is not what stops the
step-over, a commanded turn is, which agrees with the table above (±0.1 rad/s: 3 of 5). The plan's
next step, a deadband, was built.

**A deadband** (`locomotion.steer.deadband_rad`, `DuckWalk.drive`): no turn while the heading
error is inside the band, a correction once past it, kept until inside half of it; never in a
squeeze (`close`). The navigator's own `go_to` over the 0.5 cm bar, 5 trials each:

| Deadband | Pace on; off in a margin ring or on unseen floor (first run) | Pace off; off only in a squeeze (second run) |
| --- | --- | --- |
| 0 | 1 of 5 | 2 of 5 |
| 0.15 / 0.2 rad | 1 of 5 (0.15) | 2 of 5 (0.2) |
| 0.25 / 0.3 rad | 3 of 5 (0.25) | 3 of 5 (0.3) |

(In the first run the deadband was also off wherever `near` was true, in a margin ring or on unseen
floor: 0 to 49 turn commands over 0.1 rad/s within 0.5 m of the bar per trial at every
setting, so it was off for much of the walk.) A trace of one trial at 0.3 rad: no turn until the
heading error reached 0.35 rad at x = 0.51 m, then a 0.52 rad/s correction while the feet were at
the bar (0.6 m), then the stuck rule fired after 2.9 s with zero turn commanded. The drift makes
the correction fall due where the feet meet the edge as often as anywhere else, and a foot caught
once is not freed by walking straight on (above).

**Challenges 16–19**, seeds 1–3, two repeats (24 runs per row), the navigator as it is:

| What | 16 | 17 | 18 | 19 | Total |
| --- | --- | --- | --- | --- | --- |
| Base `c79fe6b` | 0/6 | 1/6 | 0/6 | 0/6 | 1/24 |
| The pace (phase 4) | 0/6 | 0/6 | 2/6 | 0/6 | 2/24 |
| The pace and a 0.3 rad deadband | 2/6 | 3/6 | 0/6 | 0/6 | 5/24 |
| A 0.3 rad deadband, pace off | 1/6 | 0/6 | 2/6 | 1/6 | 4/24 |

Every failure "stuck", no contact or fall in any of the 96 runs. One to five of 24 do not separate
the rows (Fisher's exact test, base 1/24 against 5/24: p about 0.2). **The deadband did not fix
the crossing, and is off in the duck's profile.** The code, its test and the probe stay.

What is left: the crossing needs a walk that makes no commanded turn while the feet are at an
edge, at a time the navigator cannot know (it cannot see a 0.5–1 cm bar); or a walking policy
that steps over (upstream); or a navigator that goes back a step and tries again after the stuck
rule fires (the duck does not walk backwards, 2026-11-17). None was tried.
