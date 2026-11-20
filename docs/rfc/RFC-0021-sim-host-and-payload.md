# RFC-0021 — The simulator host and the payload: run a navigator on any machine that has Pollen's simulator

**Status:** Accepted (2026-11-19, the operator: "I agree; we do it, and that is how we start running
it on my X3/Omarchy after all of it is done, and later I will test on some other host when I get
into [the] basic arena setup"); to be built right after phase 4. The operator, 2026-11-19: "we
should assume [the] host has [the] Pollen repo and their MuJoCo sim env; can our code easily be
transferable there if basic infra is set up well? … can we separate sim as host from payload?", and:
"[the] DGX is just an example; I could run it on some dedicated VPS host, more realistic", then:
"let's not be specific about [a] VPS as host; it can be any Pollen-sim-compatible host". **Builds
on:** [RFC-0020](RFC-0020-robot-profiles-and-plugins.md) (a robot's profile and plugins),
[RFC-0008](RFC-0008-challenge-course.md) (the course and its judge),
[RFC-0010](RFC-0010-run-store-v2.md) (the recording), [RFC-0017](RFC-0017-robot-access.md) (the gate
and its lease). Serves the arena idea ([VISION-ARENA.md](../wip/VISION-ARENA.md): hosted, simulator
first, "what a submission is" open).

## 1. Problem

Running our navigator anywhere but this workstation takes hours by hand: three repositories,
Pollen's Rust services built, their MuJoCo environment, a patch to their `duck-sim` script, then our
environments. And the navigator package does host work itself. A search of `robots/duck/src` for
this machine's ties (2026-11-19):

| Tie | Where | Belongs to |
| --- | --- | --- |
| Pollen's repository paths (`/work/pollen/microduck`, `…/microduck_rl`), overridable by `DUCK_SIM_REPO`, `DUCK_SIM_RL` | `nav/simreset.py`, `challenge/scene.py` | the host |
| The robot's sockets under `~/.cache/duck-sim/` (robotd, the depth sensor, mapd, the gate) | `nav/client.py`, `gate_proxy.py`, `nav/server.py`, `record.py`, the profile's `control` block | the host |
| The simulator's truth (the body server, port 7801) | `nav/run.py` (logged as `truth` on every tick), `record.py` | the judge only |
| Restarting the simulator for each goal, starting mapd (`simreset.reset`) | the navigator package | the host |
| Writing challenge scenes from Pollen's `scene_backlash.xml` into `~/.cache/duck-sim/scenarios` | `challenge/scene.py` | the task (built by the runner, run by the host) |
| The data folder (`/work/robotics-lab/data`) as a default | six modules | the installation |

## 2. Goals and non-goals

**Goals:**

- One machine prepared once (any host that runs Pollen's simulator: a workstation, a server, a VPS)
  runs a course for any payload with one command, and writes recordings the Observatory opens
  unchanged.
- The same course, judge and recording format for every payload, so two runs on two machines
  compare.
- A payload never sees the simulator's truth.
- Several hosts can run batches in parallel (our own validation, and later the arena).

**Non-goals:** a hosted service, a scoreboard, accounts (the arena, later); real robots (the payload
interface is the same, the host is different: RFC-0017's gate); packaging Pollen's code into
anything we distribute (their licence is not checked yet: §7).

## 3. Three parts and a runner

**The host** is a machine with Pollen's two repositories built and their MuJoCo environment (the
operator's assumption). It provides three things, described by one host file (`host.json`):

1. **The robot's sockets:** robotd, the depth sensor, mapd, the gate (paths).
2. **A reset:** put the robot at its start on a named scene with an empty map, and report when it
   stands (today's `simreset.reset`, moved out of the navigator into a host tool).
3. **The truth:** the body server's port, read by the runner only.

**The payload** is a navigator: ours (`duck_lab` plus `libs/`, installed as packages) or anyone's.
It receives the robot's sockets and a goal, and nothing else: no truth, no host paths. Its contract
is the same Mission Control already uses for a robot's navigator (a goal in, a status and events
out, RFC-0014), so our own navigator needs no new interface, and another one can implement it.

**The task** is one file: a course (a goal list like `robots/duck/sim/phase1_goals.json`, or
challenges with seeds), the robot's profile (RFC-0020: only the robot, no paths), and where runs go.
Challenge scenes are built from it by the runner and handed to the host's reset.

**The runner** (ours, the same everywhere) joins them: it reads the host file and the task, resets
the host per goal, starts the payload with the sockets, gives it the goal, reads the truth, judges
(the judge stays ours: RFC-0008's rules, the phase 1 bar), and writes the recording with the truth
added by the runner, not by the payload.

### 3.1 Simulator kinds

The operator, 2026-11-20: "different robots bring different simulators … we want our mini explorer
and control to work with all of those combinations", and: "let's add support for TurtleBot3, that is
the ROS standard, which I don't have but plan buying maybe".

**The rule:** a host file's `kind` names the simulator, and everything that knows a simulator lives
behind that kind. Nothing outside it names Pollen, MuJoCo, Gazebo or ROS. A kind provides four
things:

1. **Reset** to a named scene, with the robot at its start and an empty map.
2. **The robot's connections**, by the names its profile's plugins take (RFC-0020): for the duck,
   robotd, the depth sensor and mapd sockets; for a ROS robot, topics and services.
3. **A truth reader** for the runner: the robot's pose in the world, its height and orientation,
   on the runner's clock.
4. **A scene writer**: a challenge scene (ADR-0015's boxes and floor slabs) in the simulator's own
   format (MuJoCo XML for Pollen's; an SDF world for Gazebo).

The runner, the judge, the recording (format 2), the Observatory and Mission Control are the same for
every kind. A robot is a profile and plugins (RFC-0020); a simulator is a kind; a host file pairs
them. The Observatory already reads only the run format, and Mission Control picks an adapter by type
in the robot file, so both need no change for a new kind beyond its adapter.

**Kinds:** `pollen-duck-sim` (built: `libs/simhost`). **Planned second: `gazebo-turtlebot3`**,
ROBOTIS's TurtleBot3 (Burger or Waffle Pi) in Gazebo under ROS 2, the ROS standard's reference
robot. It proves the rule on a second simulator, a second robot (wheeled, 2D LiDAR) and ROS together:
its plugins would speak ROS 2 topics (`/cmd_vel`, `/scan`, `/odom`, a map from slam_toolbox or its
own), its truth Gazebo's model pose, its scenes SDF. ADR-0001 holds: no ROS foundation under our
code, ROS terms and shapes; a ROS bridge is that kind's plugins, not the navigator's core. A real
TurtleBot3 later (the operator may buy one) is the same profile with real plugins, as the real duck
is to the simulated one. Not built: ROS 2 and Gazebo are not installed on any host (an install
the operator approves first), and the operator placed it after the current plan ("it comes after we
finish our vision": EXECUTION-PLAN, "After the plan").

## 4. Setting up a host

The operator, 2026-11-20: a setup script beside the check, "I want to set up this project on a new
laptop, run that script and it sets up the Pollen repo, the sim, everything", and macOS from the
start: "I would like to run all of this on my laptop, a MacBook Pro M4 Pro".

**Platforms from the start:** Linux x86-64 (Arch/Omarchy, the operator's workstation; Debian and
Ubuntu, servers) and macOS on Apple Silicon (the operator's MacBook Pro, M4 Pro).

**The setup script** (`scripts/host-setup`), run once on a new machine, safe to run again (each step
skips what is done), each step printing what it did and stopping at the first failure:

1. The tools: git, Rust (cargo), uv, a C toolchain, what MuJoCo needs headless. What is missing is
   printed with the command that installs it on that platform (pacman, apt, Homebrew); system
   packages are the person's to install, never a system upgrade.
2. Pollen's `microduck` and `microduck_rl`, cloned from Pollen's own repositories at the commits
   this repository pins (one pin file, the versions every host runs).
3. Pollen's Rust services built; their simulation environment created with uv.
4. Our patch to `duck-sim` applied (the sudo-free stop, `robots/duck/sim/patches/`).
5. Our environments, by the Makefile's sync targets.
6. `host.json` written for this machine.
7. The check script run, its PASS/FAIL lines printed.

**The check script** (`scripts/host-check`) reports each requirement with PASS/FAIL (Pollen's
repositories present at the pinned commits and built, the simulation environment importable, the
`duck-sim` patch applied, our packages installed, the simulator's real-time factor) and installs
nothing. A container image for the payload and runner follows if the scripts prove the line clean.

**macOS, what is known and what is not (read 2026-11-20, nothing built on a Mac yet):** Pollen's
`duck-sim` already handles a laptop and a Mac (its own comments: "`setsid` is util-linux: Linux has
it, a Mac does not", and the laptop's paths and identity). Their Rust services keep the Linux-only
parts (the head's I2C bus, the camera capture) to the real robot. The open risk is their simulation
environment: it pins `warp-lang`, `mjlab` (built on MuJoCo Warp) and `torch`; whether that runs on
Apple Silicon without an NVIDIA GPU is unknown and is the first thing step 3 finds out.

## 5. Steps

1. **Host file and reset out of the payload:** `simreset` becomes a host tool; the navigator reads
   socket paths from `host.json` (the profile's `control` block keeps no paths: phase 5 needs this
   too); the data folder from the installation, not a default path.
   *Built 2026-11-20:* `libs/simhost` (standard library only) reads the host file (`--host`, else
   `$ROBOTICS_LAB_HOST`, else `~/.config/robotics-lab/host.json`; a missing or wrong file is an
   error, never this workstation's paths) and owns the reset (`simhost.reset`, `simhost.down`, moved
   from `nav/simreset.py`, deleted); `simhost init` and `simhost show`. The navigator takes its
   three sockets and its truth reader as arguments (`Navigator(sockets, body)`); the commands that
   start it (`duck-go`, `duck-eval`, `duck-explore`, `duck-challenge`, `duck-nav-server`,
   `duck-record`, `duck-gate`) and the probes build them from the host file (`host_links`). The
   data folder was already the installation's (`OBSERVATORY_DATA`). Proof: `test_simhost.py`
   (refusals, sockets, `init`, the sudo guard); `make lint test-duck test-control
   test-control-page` PASS; challenge 1 seed 1 through the host file passed; `make sim-duck`
   (point, cancel: the gate and the nav server) PASS. Still tied to this machine: eight standalone
   probes that open port 7801 or `~/.cache/duck-sim` themselves (`backward`, `head_walk`,
   `kick_turn`, `move`, `still`, `where`, `record_session`, `repeat_sim`) and Mission Control's
   robot-file defaults (`duck.py`), for phase 5's control panel.
2. **Truth out of the payload:** the runner reads the body server and merges truth into the
   recording; the navigator stops reading port 7801. The judge, the evaluation and the challenges
   move to the runner. Proof: phase 1's evaluation and challenges 1–5 judged the same as before
   (pass counts over repeats, the simulator is not deterministic: K13); the recordings open in the
   Observatory with truth where they had it.
3. **The setup and check scripts** (§4), each platform proven on a clean machine: Linux in a fresh
   container standing in for a new machine; macOS on the operator's MacBook Pro (M4 Pro), the
   simulation environment first, since it is the open risk; phase 1's 20 goals run there and the
   recording opened in the Observatory.
4. **One course through the split on this workstation** (the operator's X3, Omarchy, the first
   host): phase 1's 20 goals run by the runner with the host file, the recording opened in the
   Observatory beside a run made the old way. A second host is the operator's, later, with the basic
   arena setup.
5. **A second payload:** a minimal navigator (straight to the goal, stop on the depth sensor)
   through the same contract, to prove the contract is not ours alone.

## 6. Risks

- **Pollen's code changes shape** (the scene file, the services' arguments): the host check reports
  the version it was tested with; the scene builder already refuses a changed `scene_backlash.xml`.
- **Timing on a slower host:** the navigator's loop runs on wall-clock time; a slower host may
  change results. The host check measures the simulator's real-time factor and records it with every
  run.
- **Truth leaking:** step 2's proof includes a test that the payload's process has no route to the
  body server's port.

## 7. Open questions

1. Pollen's licences for `microduck` and `microduck_rl`: what a host may run and what we may
   distribute (to check before step 3).
2. The payload's contract: Mission Control's navigator API as it is, or a smaller one for the runner
   (arena question 4)?
3. Several robots on one host (one simulator with several ducks: the body server takes `--ducks`),
   or one robot per host?
4. ~~How the lead reaches the MacBook~~ Answered 2026-11-20 (the operator: "you can SSH to it", and
   the `prod` session on the laptop to discuss what the laptop needs): ssh over the tailnet,
   `markodragoljevic@markos-macbook-pro-1` with `~/.ssh/macbook`. Read then: arm64, macOS 15.7.3,
   Apple M4 Pro; Homebrew and uv in `/opt/homebrew/bin` (not on a non-interactive shell's PATH);
   Xcode present; no Rust (cargo) yet; no Pollen checkout.
