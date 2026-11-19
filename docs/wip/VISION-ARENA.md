# Vision: an arena where robots prove what they can do

**Status:** ideation, 2026-11-19 (the operator: "make [a] document with vision and ideation around
[the] gap and opportunity, with one angle focus on Pollen as community and then other as open for
all"). Not planned work: the plan we execute on is [EXECUTION-PLAN.md](EXECUTION-PLAN.md). The facts
behind it (which competitions exist, what was confirmed) are in
[OPPORTUNITIES.md](OPPORTUNITIES.md).

## 1. The gap

Robot navigation is judged today in two kinds of places:

- **Benchmarks in simulation** (Habitat, RoboTHOR and the like): homes scanned in detail, but agents
  that move perfectly and know where they are. They measure planning, not a robot.
- **Competitions with their own robot** (BARN at ICRA, the embodied-AI challenges): real courses,
  but every team brings the same machine, or the organiser's.

What neither does, as far as we have found:

- let **your own robot, with its own body and its own limits**, compete on the same rules as
  everyone else's;
- judge a run on **safety first** (no contact, no fall, a drop never approached) and on what was
  **really** reached, by the simulator's truth and later by an observer in the room;
- start every run **from scratch** (no map, nothing remembered), the way a robot meets a new home;
- make every run **watchable and explainable**: what the robot saw, what it decided and why, where
  its picture of the world and the real one parted.

Robotics at home is moving from a few labs to many people with small, affordable robots. Those
people have no common place to find out how good their robot's navigation is, compare with others,
or learn from the runs that went wrong.

## 2. The vision

**An arena where any robot can be loaded, given a course, and shown to the world: safely, from
scratch, and with every decision visible.** The same platform we are building for our own robots
(robot profiles and plugins, the challenge course and its judge, the Observatory, Mission Control,
the anomaly timeline) is most of that arena already.

What a run in the arena looks like:

1. A robot arrives with its **profile**: its shape, how it moves, what it senses, its measured
   errors (RFC-0020). The course draws its heights and widths from that profile, so a small walking
   duck and a tracked LEGO machine each meet a fair test of what their bodies can do.
2. It runs a **seeded course** it has never seen (doorways, drops, clutter, steps, a whole home),
   with hidden seeds so nobody tunes to them.
3. The **judge** scores it by truth: safety first, then what it reached and how much of the home it
   came to know.
4. The **Observatory** replays it for everyone: the robot's eye, its map growing over the real one,
   its decisions, its anomalies. A run that fails teaches as much as one that wins.

## 3. Angle one: the Pollen community

### Why start here

Pollen Robotics' Microduck owners already share the same robot, the same simulator (`duck-sim`) and
the same walking. That makes them the easiest community in which comparisons mean something from day
one: the bodies are equal, so the navigation is what differs. The duck is also small, safe and
affordable enough to run in a living room.

### What we would offer

- **A Microduck navigation league.** A course in the simulator first (our challenges and the
  apartment), then real homes for those who want it. Bring your navigator as a plugin, or drive
  through Mission Control's API; get a score, a replay and an anomaly report.
- **The tools, open (MIT):** the challenge course and judge, the Observatory to watch and replay any
  duck run, Mission Control to give goals, the recording format.
- **Shared knowledge, back to Pollen and the community:** what we measured about the walking (it
  crosses about 1 cm; turning while crossing hurts), about mapd's position jumps, about odometry:
  written as notes and issues for Pollen's repositories, with the recordings that show them. Some
  are drafted (UPSTREAM-STEP-HEIGHT-DRAFT.md, UPSTREAM-ODOMETRY-DRAFT.md); upstream already has
  related reports (microduck_rl#59, microduck#597, PR #25 for a dedicated step-up skill).
- **Courses as content:** challenge scenes and apartments others can add, so the league grows its
  own courses.

### How we would do it

- **With Pollen, not in their name.** Pollen owns the duck, its brand and its community spaces. The
  league would be offered to them and run with their blessing, or stay clearly an independent
  community project that credits them; never presented as theirs.
- **Start small:** one public course in the simulator, a scoreboard, our own runs as the first
  entries, a short post to Pollen's community with a video like the teaser.
- **Real homes later,** once the real duck is here and the safety rules for real runs are written.

### What it gives back to us

Many navigators run on the same body, in the same scenes, with recordings: the fastest way to learn
what works on this robot, to find the walking's and mapping's limits, and to grow the platform in
public.

## 4. Angle two: open for all

### Any robot

The same arena, opened to every body: LEGO machines with added sensors (ours are next), small
wheeled and tracked robots, other legged ones. Each brings its profile; the course adapts to it; the
rules stay the same. Robots of different makers compete on what matters, safety and what they
achieve, not on who has the biggest motors.

### Any team

- **Students and clubs:** a free, open course to learn navigation on, with replays that explain why
  a run failed.
- **Makers and hobbyists:** a way to show what their home robot can do, with a video and a score.
- **Researchers:** a benchmark of real limits (drift, narrow sensors, jumps in position) next to the
  idealised ones.
- **Companies:** a neutral place to show a navigation stack on more than one body.

### Fleets

Later, the same arena for several robots at once: a home explored by a duck and a LEGO machine
together, goals shared between them, judged as a team. That is where the platform's fleet capability
(RFC-0014's goals with several robots) becomes something to watch.

### Existing competitions

Not rivals but neighbours: entering BARN through our Nav2 bridge (RFC-0015, parked) would show our
navigator against others on a respected benchmark, and bring that community's attention to an arena
that accepts any body.

## 5. What it takes

What exists or is planned, and what an arena adds:

| Piece | Today | For an arena |
| --- | --- | --- |
| Robot profiles and plugins | RFC-0020, phase 3 | a published profile format; a plugin a team can submit |
| The challenge course and judge | 1–23 built, judged by truth | hidden seeds, a fixed judge version, courses drawn from the profile |
| The Observatory | built, renamed, replays any run | public replay pages per run, shareable |
| Anomalies | RFC-0019, phases 3 and 5 | a per-run report for the team |
| Mission Control | built, API and MCP | a submission path through its API |
| A second robot | the EV3, phase 6 | proof that the arena takes more than one body |
| A scoreboard | none | new: runs, scores, replays, per course and per robot |
| Real-world runs | none | rules for safety and for an observer's truth |

## 6. Open questions

1. Pollen: offer the league to them, or start as an independent community project and invite them?
2. Simulator first only, or real homes from the start for those with a duck?
3. Where the arena lives: a hosted site, or a kit anyone runs locally with a shared scoreboard?
4. What a "submission" is: a plugin package, a container, or a client of Mission Control's API?
5. How to keep it fair across bodies: one score with the profile's handicap, or leagues per body
   class?
