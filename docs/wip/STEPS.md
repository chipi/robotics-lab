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
  walk's drift), more than the probe's turning.
- Once a foot is caught, walking straight does not free it (1.5 s at 0.3 m/s, no motion), and the
  duck does not walk backwards.

Not tried: capping the turn while walking (touches every challenge: a full gate after), seeing the
bar (the low band starts at 3.5 cm) and squaring up to it.
