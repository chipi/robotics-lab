# Walking over and up: what the duck can do (parked), 2026-11-17

Parked by the operator on 2026-11-17 ("let's park this and focus on other challenges so that we can
do explore and apartment, and we will come back to steps later"). Challenges 16–20 (RFC-0008 §3)
wait on this.

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

## When this is picked up again

1. 0.4 m/s and an angled approach (the probe's `--speed`; an angle needs a turned bar).
2. Bring the numbers upstream (the operator's call).
3. Stuck detection in the navigator (agreed regardless).
4. Challenges 16–20 rebuilt on the measured heights, every floor in edge-to-edge pieces.
