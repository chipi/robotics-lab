# Project ideas

Ideas for robotics-lab, collected 2026-11-13. Status is what exists in this repo, not what is
planned. "Untested" means it has never run on the real robot.

Hardware: a LEGO Mindstorms NXT 2.0 (stock firmware 1.31) built as a tracked Shooterbot. The
NXT 2.0 set comes with 2 touch sensors, 1 ultrasonic distance sensor and 1 colour sensor, and
every motor counts its rotation. Also arriving: Hugging Face's **Microduck** (Pollen Robotics),
which its official repo (`pollen-robotics/microduck`) describes as about 25 cm and 800 g, run by
a Rockchip RK3566: fifteen servos driven at 50 Hz by neural policies, a camera, an 8×8
time-of-flight depth sensor (press coverage said LiDAR; the repo does not), a beak that works
as a gripper, and an Apache-2.0 software stack. Details in [MICRODUCK.md](MICRODUCK.md). Not
yet checked on the robot itself.

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

## Wireless NXT

The NXT speaks classic Bluetooth (serial port profile). Plan: start with the PC's own
Bluetooth, then a small board riding on the robot for house-level range.

1. **PC Bluetooth (start).** Pair, `rfcomm bind` (package `bluez-deprecated-tools`), and
   nxt-python's device-file backend. One-line change in `robot.py`. Room range.
2. **ESP32 bridge on the robot (house level).** Bluetooth to the NXT, Wi-Fi to the house.
   nxt-python already has a network backend for its own `nxt-server`, whose protocol is tiny
   (`0x98` asks the link type, `0x99` closes, anything else is a command forwarded to the brick
   and its reply sent back; `nxt/backend/socket.py`, `nxt/command/server.py`). If the ESP32
   firmware speaks that protocol, `nxt-web` works over Wi-Fi with no change beyond choosing the
   backend.
   - Needs an **original ESP32** (classic Bluetooth). ESP32-S2/S3/C3/C6 have Bluetooth LE only.
   - Off the shelf and small: M5Stack **Atom Lite** (ESP32-PICO-D4: "Bluetooth v4.2 BR/EDR and
     Bluetooth LE" per Espressif's datasheet; the PICO series is marked not recommended for new
     designs, so stock may thin out). Avoid AtomS3 / CoreS3 / StampS3 (ESP32-S3).
3. **Raspberry Pi Zero 2 W on the robot (alternative).** USB to the NXT, runs `nxt-web`
   itself; heavier and needs more power, but no firmware to write and room for a camera.

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

What it adds over the NXT: a camera and an 8×8 depth sensor, so it can tell a person from a
chair and see a room better than one ultrasonic sensor; a beak gripper;
and behaviours trained in simulation with reinforcement learning.

1. **Simulation first.** Set up its open-source simulator and training stack before it
   arrives, so the first day is running, not installing.
2. **The NXT's weak spots, done properly.** Follow me (camera recognises you) and mapping
   (camera and depth sensor; the simulator ships a six-room `apartment` scene) are the ideas
   the NXT can only do roughly.
3. **Trained behaviours as arms in eval-harness.** Policies from different training runs or
   settings, compared on repeated real trials (walking distance before a fall, success at a
   pick-up), and on how far the simulator's result differs from the real robot.
4. **Duck and NXT together.** The duck watches and decides; the NXT drives or plays chase.
   In flotilla, two hosts in one fleet.
5. **Dog games, round two.** Fetch with the beak, chosen with the dog's safety in mind (what it
   carries must not be swallowable).

### Goal project: "tour the home, then hide under the kitchen table"

Operator's goal (2026-11-13): tell the duck to walk into every room, roughly size each one,
then find the kitchen table and stop under it. Layers, fastest first:

1. **Walking, on the duck, 50 Hz:** the walking policy turns a velocity command into joint
   targets. Exists.
2. **Map, obstacles, exploring, on the duck:** `mapd` builds a floor plan (2.5 cm cells) from the
   depth sensor and leg/gyro odometry, mapping at stops; `autod` avoids obstacles and explores
   (`microduck/docs/design/mapping-design.md`, `autonomous.md`). Exist upstream, off by default;
   real-robot drift not yet measured upstream. The depth sensor is "a cane, not a lidar": median
   valid range about 0.5 m, 90 % under 1 m.
3. **Meaning, off the duck, every few seconds:** a vision-language model on the DGX reads camera
   frames (streamed over Wi-Fi, WebRTC): which room is this, is that the kitchen table, are we
   under it. Upstream's mapper does not use the camera yet.
4. **Plan, off the duck:** an LLM agent turns the instruction into steps and calls tools (explore,
   go to, look around, describe view, stop), reading the map for room sizes.

The LLM is not in the walking loop: the duck keeps balance and stops on its own (its deadman
stops it if commands stop arriving), so seconds of model latency are fine at walking speed.
Open: how a program off the duck reaches `map.*` / `robot.*` (ssh, or the WebRTC control
lane); which DGX GPU mode serves a vision model (robotics mode stops all vLLMs); the
`apartment` sim scene needs the backlash robot before the duck walks in it. Test bed: the
simulated apartment; measured with eval-harness over many start positions (success, time).

## AI loop

AI suggests a change to a controller → eval-harness says whether it is really better over
repeated runs → the operator approves promoting it.

## Open questions

- ~~Which ports the sensors are on~~ Checked 2026-11-14: colour on 3, ultrasonic on 4 (reports type "Sonar", read 73–83 cm).
- ~~Which motor ports drive which track~~ Checked 2026-11-14: A shooter, B right, C left, positive power forward on both.
- Microduck's actual SDK, simulator and hardware, from the official repository once it is
  in hand (the description above is from press coverage).
