# Project ideas

Ideas for robotics-lab, collected 2026-11-13. Status is what exists in this repo, not what is
planned. "Untested" means it has never run on the real robot.

Hardware: a LEGO Mindstorms NXT 2.0 (stock firmware 1.31) built as a tracked Shooterbot. The
NXT 2.0 set comes with 2 touch sensors, 1 ultrasonic distance sensor and 1 colour sensor, and
every motor counts its rotation. Also arriving: Hugging Face's **Microduck** (Pollen Robotics),
which press coverage from August 2026 describes as a $399, 25 cm walking biped with a camera,
LiDAR, 15 motors, a beak that works as a gripper, and an open-source SDK, simulator and
reinforcement-learning training stack (Apache 2.0). Not yet checked against the official docs
or the robot itself.

Ground rule: the NXT has 64 KB of RAM, so it runs the fast, simple control loops. AI
(perception, planning, language) runs on the PC or the duck.

## NXT programs that run on their own

Written in NXC under `nxt/programs/`, compiled with `nxt/scripts/nxc.sh`, uploaded and
started from the web UI. Each writes a CSV log on the brick that the UI can plot.

| Idea | What it does | Status |
|---|---|---|
| First drive | Beep, forward 1 s, back 1 s, log rotation counts | `first.nxc` written, compiles, untested |
| **Chase** (dog game) | Waits; backs away when something comes within 30 cm, stops at 60 cm; wiggles and chirps to invite a chase when left alone | `chase.nxc` written, compiles, untested |
| **Patrol** (dog game) | Wanders, turns away from obstacles; every 15 s stops and watches, alerts with a tone when the distance in front changes (something moved) | `patrol.nxc` written, compiles, untested |
| Obstacle-avoiding explorer | Drive until close, back up, turn, repeat, logging every decision | Not started. Patrol's drive/turn part is most of it |
| Line follower | Follow a tape line with the colour sensor; logs show wobble per run, good for tuning | Not started |
| Follow me | Keep about 50 cm behind what is in front; sweep to find you again after a turn | Not started. Weak point: the ultrasonic beam is wide and cannot tell a person from a chair |
| Map the home | Drive, scan distances, log (heading, distance); the PC draws a map | Not started. Expect a rough outline: tracks slip on turns so position drifts, and soft surfaces echo poorly |

Dog safety: no shooter in dog games. The balls are about 2 cm, small enough to swallow.
Expect the dog to knock the robot over or chew cables, and fur may not reflect ultrasonic
well, so readings on the dog itself may be poor.

Suggested order: explorer → line follower → follow me → map. Chase and patrol can run any time.

## With eval-harness

eval-harness asks "is this ranking real, or a lucky sample?". Robot trials are noisy and few,
so that question matters more here, not less.

1. **Controllers as arms.** Several versions of a program (tuning or approach) against a fixed
   set of scenarios (track layouts, start positions). Score from the run logs: lap time, wobble,
   collisions. `--repeat` measures run-to-run noise; `family-test` says whether B really beats A.
   The adapter's `call_system()` would start a run through the NXT web API and read its log back;
   a person resets the robot between runs.
2. **Replay recorded runs.** Freeze recorded sensor logs as the dataset and ask each controller
   "given these readings, what do you do?" without moving the robot. Many items cost nothing; live
   trials confirm the winner.
3. **Perception for the duck's camera.** Home photos: "is that me, the dog or a chair?", "which
   room is this?". Hosted vision models vs local open models vs a small classic detector vs a
   no-model baseline, on quality, cost and latency.
4. **LLM as planner.** A command ("go check the hallway") becomes a plan in the robot's few
   actions; score plans against a reference or a judge before running the best ones.
5. **Simulation vs reality** as two arms: the same controller in a simple simulator and on the robot.

First step suggested: idea 1 on the line follower.

## With flotilla

flotilla: agents plan, a policy decides (run, ask or refuse), a host agent runs only what is
signed and allowed, and every case keeps its timeline. Cases, policy, host agents and the UI are
not built in flotilla yet, so these wait for those parts or drive them.

1. **The robot as a host.** `flotilla-host` on the PC with the NXT; allowed actions are the
   robot's primitives (`drive_cm`, `turn_deg`, `scan`, `run_program`, `fire`), each with its own
   autonomy: `scan` runs, `drive_cm` asks until it has earned trust, `fire` always asks.
2. **Home-patrol fleet.** A trigger (schedule, noise, an event from home automation) opens a
   case such as "check the living room"; a worker plans, policy decides, the robot runs it, a
   check step looks at evidence (distances, a duck camera frame), the case closes.
3. **Ops fleet for the robots.** Low battery, stuck (motors on, rotation counts not moving),
   program crash: each a case with a fix (back up, stop, notify).
4. **NXT and duck as two hosts in one fleet.** The duck sees and talks, the NXT drives; flotilla
   coordinates and records who did what.

## With the Microduck

What it adds over the NXT (per the press description above): a camera and LiDAR, so it can
tell a person from a chair and measure a room far better than one ultrasonic sensor; a gripper;
and behaviours trained in simulation with reinforcement learning.

1. **Simulation first.** Set up its open-source simulator and training stack before it
   arrives, so the first day is running, not installing.
2. **The NXT's weak spots, done properly.** Follow me (camera recognises you) and mapping
   (LiDAR) are the ideas the NXT can only do roughly.
3. **Trained behaviours as arms in eval-harness.** Policies from different training runs or
   settings, compared on repeated real trials (walking distance before a fall, success at a
   pick-up), and on how far the simulator's result differs from the real robot.
4. **Duck and NXT together.** The duck watches and decides; the NXT drives or plays chase.
   In flotilla, two hosts in one fleet.
5. **Dog games, round two.** Fetch with the beak, chosen with the dog's safety in mind (what it
   carries must not be swallowable).

## AI loop

AI suggests a change to a controller → eval-harness says whether it is really better over
repeated runs → the operator approves promoting it.

## Open questions

- Which ports the ultrasonic and colour sensors are on (photos show cables in 3 and 4; the
  programs assume ultrasonic on 4).
- Which motor ports drive which track, and in which direction (assumed B left, C right).
- Microduck's actual SDK, simulator and hardware, from the official repository once it is
  in hand (the description above is from press coverage).
