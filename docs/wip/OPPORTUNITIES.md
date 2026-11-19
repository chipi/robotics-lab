# Opportunities and competitions

**Status:** ideas, collected 2026-11-19 (the operator: "write all ideas around opportunity and
competitions in one file"). Nothing here is planned work; the plan we execute on is
[EXECUTION-PLAN.md](EXECUTION-PLAN.md). A side idea is written down, not pursued, until the operator
picks it up (apartment first).

## 1. Where this could go

The operator's direction (2026-11-19): a platform where any robot can be loaded, given autonomy and
fleet-like capabilities, watched and commanded (RFC-0020). The duck is the first passenger; the LEGO
robots, upgraded with new sensors, come next. The public framing so far, in the LinkedIn teaser
(drafted 2026-11-19): "the layer underneath: autonomy that doesn't care what body it runs in, and
fleets of very different robots working toward one goal"; and an open ask for ideas on growing the
robot fleet.

## 2. Competitions that exist

Checked 2026-11-19 (web search; each line says what was and was not confirmed):

| Competition | What | Fit for us | Confirmed |
| --- | --- | --- | --- |
| BARN Challenge (Benchmark for Autonomous Robot Navigation), ICRA | navigation through tight, cluttered spaces, safely and efficiently; simulated BARN worlds and physical courses; 5th edition at ICRA 2026, Vienna | the closest in spirit (navigation and safety in clutter); built around its own robot, so entering means running our navigator on its platform: the ROS / Nav2 bridge work parked in RFC-0015 | the 2026 edition and its format; the robot (a Clearpath Jackal under ROS) is from memory |
| REAL-I (Real-world Embodied AI Learning Challenge), ICRA 2026 | picking in clutter, mobile manipulation, handing objects, cloud manipulation | manipulation, not our focus | its 2026 tracks |
| AGIBOT World Challenge, ICRA 2026 | embodied AI tracks, real-robot finals on AGIBOT G2; 526 teams | their robot, manipulation-led | its 2026 numbers |
| Habitat and RoboTHOR challenges | object navigation in scanned homes, in simulation, idealised agents | home navigation, but idealised movement and sensing | from memory; 2026 status not checked |
| Duckietown AI Driving Olympics | small autonomous cars on a road layout | small robots, but driving lanes, not exploring homes | from memory; not checked |
| RoboCup@Home, F1TENTH | service robots at home; small-car racing | home tasks; racing | from memory; not checked |

Sources: [BARN 2026](https://people.cs.gmu.edu/~xiao/Research/BARN_Challenge/BARN_Challenge26.html),
[ICRA 2026 competitions](https://2026.ieee-icra.org/program/competitions),
[AGIBOT World Challenge 2026](https://www.pulse.bot/robotics/news/agibot-world-challenge-2026-advances-embodied-ai-competition-from-simulation-to-real-robot-testing-a-52d73091-5c15-439f-9465-8fe91e2573c2/).

## 3. The gap, as far as we know

None of the above, as far as we found, puts all of these together:

- **Bring your own body:** different robots (a walking duck, LEGO machines, others) on one course,
  each with its own limits declared in a profile (RFC-0020), and scored on the same rules.
- **Real-life limits, not idealised agents:** a walking robot with odometry drift, an 8×8 depth sensor,
  a position source that can jump; the home benchmarks above usually give perfect position or movement.
- **Safety first, scored by truth:** a seeded challenge course (ours, 1–23) and a whole-home exploring
  final, every run from scratch; contacts and falls fail the run.
- **Watchable:** every run replays in the Observatory with what the robot saw and decided and, once
  RFC-0019 is built, an anomaly timeline that shows where it went wrong; good for judges and
  spectators, and for the video and live views (the teaser is one).
- **A ready community:** Pollen's Microduck owners have the same robot and the same simulator.

## 4. Ideas

1. **A Microduck navigation league.** People bring their own navigator as a plugin (behind RFC-0020's
   interfaces) or drive through Mission Control's API; it runs our challenge course and an apartment
   in the simulator, then, for the brave, in real homes. Cheapest to start: the course, the judge and
   the Observatory exist.
2. **An arena for any robot.** The same, open to other bodies: each brings its profile, and the course
   draws its heights and widths from it (RFC-0008: challenges follow the robot's capability).
3. **Enter BARN.** Run our navigator on BARN's robot through the Nav2 bridge (RFC-0015, parked after
   its first drive), to see ourselves against others on an existing, respected benchmark.
4. **Our course as a public benchmark.** Publish the challenge definitions, the judge and a scoreboard,
   with hidden seeds so nobody tunes to them.
5. **Live events.** Mission Control's live view, the Observatory's watch page and the video panels make
   a run something to watch as it happens.

## 5. What it would take

- A public scoreboard, and a way to submit (a plugin package, or a client of Mission Control's API).
- Hidden seeds and a fixed judge version, so results compare.
- Robot profiles and plugins (RFC-0020): phase 3 of the plan.
- Anomalies on the timeline (RFC-0019): phases 3 and 5.
- A second body running on the platform (the EV3): phase 6.
- For BARN: the Nav2 bridge finished (RFC-0015, parked; known issue K17).

## 6. Related, already decided

- The market and startup assessment lives in a separate private repository (`autonomy-trust`); its
  decision was to build in robotics-lab, in the open.
- The licence is MIT (RFC-0014, the operator, 2026-11-18).
