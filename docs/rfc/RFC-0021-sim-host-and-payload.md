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
   *Design (2026-11-20, with the advisor's review):* a format 2 tick holds its truth inside it and a
   run has one writer (`wire.py`, `mcapio.py`), so the truth cannot be added by a second writer or
   a side file without a format change. Instead the runner is the official run's one writer: the
   payload writes its own run, without truth, into a scratch folder the runner owns (outside the
   Observatory's data folder); the runner follows it live (`Follower`) and copies every record into
   the official run, putting into each tick the truth sample nearest it in wall-clock time (every
   row gains `wall_ns`; ticks with no sample within 100 ms keep no truth, counted), and writing the
   map ← world epochs, its own judged events and the run's end. Live viewing keeps its truth, about
   a poll period late. Sub-steps, each green on its own: (a) `wall_ns` on every row; (b) the copier
   in `libs/runfile`, tested record by record against today's path, live, multi-goal and offline;
   (c) the truth sampler (`Body` moves to `simhost`) and the judge on its samples, still in one
   process; (d) the payload as its own process under the runner (the nav server given only its
   sockets, a goal sequence kind for challenge 21, cancel with a reason, the runner stopping the
   robot itself if the payload dies); (e) truth removed from the navigator, and the test that the
   payload's process connects to no truth port (a test-owned fake body server that counts
   connections). Later than step 2: the simulated camera becomes a sensor socket the host serves (it
   reads truth today; `duck-explore` and the nav server keep it, behind an explicit interim, until
   then), and Mission Control's truth guardrails (fall, contact, drop clearance) move to the runner
   when it fronts the navigator API. Traps to keep: the body server's port also writes joint targets
   (the "no route" test guards actuation, not only truth); a payload killed mid-goal leaves the
   robot walking, so the runner cancels, waits, and sends a zero move itself.
   *Built for the challenge course (2026-11-20):* `duck-challenge` runs the navigator as a payload
   process (`duck_lab.payload`, `duck-payload`) with no truth; the runner side is
   `duck_lab.challenge.runner.Remote` (the copier live, the runner's own events, stop then signals
   then its own zero move), the judge on the runner's sampler (`simhost.truth`). The payload's
   contract (open question 2, answered: a smaller one than Mission Control's, which another navigator
   can implement): newline JSON-RPC on a socket the runner names; `hello` (name, version, kinds),
   `localise` (its pose in its map), `start` (`point {goal, time_s}` in its map, `explore
   {minutes}`), `status` (state, why, pose, result), `cancel {reason}`, `stop`; the navigator is
   kept between starts, so challenge 21 is ten points on one map and memory. The payload is given
   `--robot`, `--depth`, `--map`, `--listen`, `--out`, `--data`, `--scene`, `--name`, `--variant`:
   no host file, no port. Proof: challenges 1–5, seeds 1–3, two repeats, the payload process against
   the navigator in the runner with the truth in its rows (same commit, alternating): 30 of 30 both
   ways; every one of the payload runs' 12142 ticks paired with a truth sample (largest gap 49.7
   ms); the payload process's connections to the truth's port, counted from its own sockets every
   2 s, 0 in all 583 checks (`test_payload.py` shows the counter counts a real connection; it reads
   `/proc`, so on macOS it records "not measured"); importing the payload loads no `simhost`. Not yet
   through the split: the phase 1 evaluation (`duck-eval`, step 4), `duck-explore` and Mission
   Control's nav server (the camera and guardrails above); challenge 21 through the payload ran
   once and missed one goal by 1 cm (8 of 10), not repeated yet.
3. **The setup and check scripts** (§4), each platform proven on a clean machine: Linux in a fresh
   container standing in for a new machine; macOS on the operator's MacBook Pro (M4 Pro), the
   simulation environment first, since it is the open risk; phase 1's 20 goals run there and the
   recording opened in the Observatory.
   *Linux proven 2026-11-20:* in a fresh `ubuntu:24.04` container with only the base tools a person
   installs by hand (git, a C toolchain, python3, rustup, uv), our repository cloned and
   `scripts/host-setup` run: Pollen's checkouts cloned at the pins, mapd built, the simulation
   environment synced, our patch, the apartment scene, the walking policy fetched, our three
   environments, the host file; `HOST-CHECK PASS (17 pass, 0 fail, 1 not run)`, `HOST-SETUP PASS`.
   Found on the way: macOS's system `python3` is 3.9 (the MacBook's: 3.9.6), so the two scripts
   and `simhost` defer their annotations. Not done: the simulator run inside that container; saving
   it as an image (`docker commit`) fails three times out of three on this workstation's Docker
   store (fs-verity "FILE CORRUPTED" on the blobs being written, no disk errors; the homelab
   session's report, the next step the operator's).
   *macOS proven 2026-11-21* on the operator's MacBook Pro (M4 Pro, macOS 27.2.1; the operator's go
   for the installs, and the laptop's prod session agreed the paths): Rust installed for the user
   (rustup `--no-modify-path`), our repository cloned, `scripts/host-setup`: `HOST-SETUP PASS`,
   `HOST-CHECK PASS (18 pass, 0 fail, 1 not run)`, also with macOS's own python3 3.9.6. Pollen's
   simulation environment installs and imports on Apple Silicon (MuJoCo 3.10.0), the risk named
   above. Found: Pollen's configd does not build on macOS since Pollen's 2026-11-13 change
   (`CLOCK_BOOTTIME`, Linux-only, `configd/src/wifi_ssh.rs:57`; still so on Pollen's main): our
   patch `configd-macos-clock.patch` (the operator's yes), applied and checked on macOS only, and a
   note for Pollen drafted, not sent (`docs/wip/UPSTREAM-CONFIGD-MACOS-DRAFT.md`); and simhost left
   mapd running on a host with no `/proc` (fixed, 63062ae). Then challenge 1 seed 1 through the
   payload split passed on the MacBook twice (0.103 m from the goal; real-time factor 1.0; 345 of
   345 ticks with truth; the truth-port counter "not measured" there, no `/proc`), and no mapd was
   left after the second. Not yet: phase 1's 20 goals on the MacBook, and the recording opened in
   the Observatory there.
4. **One course through the split on this workstation** (the operator's X3, Omarchy, the first
   host): phase 1's 20 goals run by the runner with the host file, the recording opened in the
   Observatory beside a run made the old way. A second host is the operator's, later, with the basic
   arena setup.
   *Done 2026-11-21:* `duck-eval` through the split (a payload per goal, one official run copied
   from the 20 payload runs: `TruthCopy.next_source`), phase 1's fixed 20 goals: bar MET, 20 of 20
   reached within 0.25 m by truth (largest error 0.206 m), 0 contacts, 0 falls, 0 timeouts, closest
   0.134 m; 9016 of 9016 ticks with truth. The run read by the Observatory's run builder beside run
   19 (the old way): the same kind, 20 epochs each, a segment per goal (21 against 20: the last
   payload's trailing one kept). Not done: the run opened in the Observatory's page (it was
   written to a scratch data folder, not the one the operator's Observatory serves).
5. **A second payload:** a minimal navigator (straight to the goal, stop on the depth sensor)
   through the same contract, to prove the contract is not ours alone.
   *Done 2026-11-21:* `robots/duck/payloads/straight.py` (the standard library and `runfile`, none
   of `duck_lab`), run by `duck-challenge --payload`: challenges 1–5 seed 1, judged the same way, 0
   of 5 passed, each failure the judge's (1 and 2 said reached 0.37 m short by truth; 3 and 4
   refused at something under 300 mm; 5 timed out), no contact, no fall; every tick with truth; 0
   connections to the truth's port.
6. **Every path through the split** (the operator's go, 2026-11-21): the apartment's exploration
   (`duck-explore`) and Mission Control's navigator API still ran the navigator with the truth in
   its process, for two jobs that are not the navigator's:
   - **The simulated camera becomes a sensor the host serves.** `duck_lab.camera_server` answers on
     a socket (`camera.info`: its field of view, range and period; `camera.detect`: what it
     recognises now, as `worldmodel` Detections, relative to the duck). It reads the truth and the
     scene's layout itself, so the navigator gets only what a real camera's detector would give.
     The navigator's `CameraClient` asks it; on the real duck the same socket would be its camera's
     detector. The runner serves it for the run, as a connection the host provides (§3.1, 2); the
     host file names it `camera` (`<robot>-camera.sock`).
   - **The runner sits in front of Mission Control's navigator API.** `duck-nav-server`, the
     command an operator starts, becomes the runner: it reads the host file and the truth, serves
     the camera, and starts the navigator API (`duck_lab.nav.server`, given only sockets) as its
     own process. Mission Control's calls pass through unchanged. Each goal run's official
     recording is the runner's (the navigator's run copied with the truth put in, as a course's),
     and the truth guardrails (`contact`, `fall`, `drop_clearance`, the robot inside a
     `no_go_area`) are checked by the runner, which breaks the run through the API's
     `goal.break {name, detail}`. The guardrails that need no truth stay the navigator's: the speed
     cap, the no-go area in the planner, the time limit, stuck.
   - **`duck-explore` goes through the runner** (`runner.Remote`, as a course does): the
     payload's `explore` goal takes the explorer's options (find, inventory, a site, the test
     faults), and the truth guard by the staircase is the runner's.

   Proven by: the payload and the navigator API holding no connection to the truth's port; an
   apartment exploration that finds objects through the camera's socket; `make sim-duck`, every
   scenario, including the drop clearance and contact stops, through the runner.

   *Done 2026-11-21:* `duck_lab/camera_server.py` and `nav/camera.py` (the host file's `camera`
   socket), `duck_lab/nav_runner.py` (`duck-nav-server`), the navigator API given only sockets
   (`goal.break`, `no_camera`), `guardrails.TruthGuard`, `duck-explore` through `runner.Remote`.
   - A 5-minute exploration through the runner, `--inventory`: 18 objects in 4 rooms, 598
     sightings from 598 looks the camera served (120 a minute, its period), no camera failure; the
     payload held 0 connections to the truth's port in 150 checks; the official run 3063 of 3063
     ticks with the truth, `kind: exploration`. Earlier explorations the old way found 18 objects in
     3.6 and 6.9 minutes at 119 sightings a minute: the same order, not a controlled comparison
     (one run, other lengths).
   - `make sim-duck` through the runner: 44 checks passed, none failed (`PASS sim_duck`), every
     scenario (point, cancel, STOP, takeover, explore, inventory, an object, an area, max speed, a
     no-go area, the time limit, drop clearance); drop clearance broke by the runner's truth check
     ("the trunk is 0.71 m from the drop stairwell, nearer than 3 m"); the navigator API's process
     held 0 connections to the truth's port in 282 checks over 15 goals; the last goal's official
     run 307 of 307 ticks paired.
   - Unit: `test_camera_server.py` (a fake body server: detections relative to the duck, nothing
     of the world over the socket, the same as the sensor model in process, a restarted body server
     connected again), `test_guardrails.py` (the navigator's guard and the runner's), and
     `test_payload.py` (importing the payload or the navigator API loads no `simhost` and no
     runner side).

   Not proven: a contact or a fall stopping a run through the runner live (the scenarios arm
   them and a good run is not stopped; the checks themselves are unit-tested); `duck-explore`'s
   `--find`, `--site` and the test faults through the payload (only `--inventory` ran; finding an
   object ran through Mission Control's path); the MacBook; the runs opened in the Observatory's
   page. `duck-explore` now refuses to run with no data folder (the run is the record). Two
   runners on one host would share the camera's socket path: not guarded.

## 6. Risks

- **Pollen's code changes shape** (the scene file, the services' arguments): the host check reports
  the version it was tested with; the scene builder already refuses a changed `scene_backlash.xml`.
- **Timing on a slower host:** the navigator's loop runs on wall-clock time; a slower host may
  change results. The host check measures the simulator's real-time factor and records it with every
  run.
- **Truth leaking:** step 2's proof includes a test that the payload's process has no route to the
  body server's port.

## 7. Open questions

1. ~~Pollen's licences~~ Read 2026-11-20, late: it was to be read before step 3 and was read after
   it was built. `microduck`: Apache-2.0. `microduck_rl`: Apache-2.0 for the code, its 3D model
   files CC-BY-NC-SA-4.0 (`LICENSE-MODELS.md`: non-commercial, share-alike). A host clones both from
   Pollen and runs them; this repository distributes neither (challenge scenes include Pollen's
   robot model by path, not a copy). Open for the arena: a hosted service that charges money would
   run the models under a non-commercial licence; ask Pollen before that.
2. ~~The payload's contract~~ Answered 2026-11-20: a smaller contract than Mission Control's (step 2,
   above), which another navigator can implement (arena question 4).
3. Several robots on one host (one simulator with several ducks: the body server takes `--ducks`),
   or one robot per host?
4. ~~How the lead reaches the MacBook~~ Answered 2026-11-20 (the operator: "you can SSH to it", and
   the `prod` session on the laptop to discuss what the laptop needs): ssh over the tailnet,
   `markodragoljevic@markos-macbook-pro-1` with `~/.ssh/macbook`. Read then: arm64, macOS 15.7.3
   (read again 2026-11-20 evening, `sw_vers`: 27.2.1; which reading was wrong, or whether it was
   upgraded between, is not known), Apple M4 Pro, 14 cores, 48 GB, 260 GiB free, system python3
   3.9.6, uv a pyenv shim (the laptop's prod session: use it as it is); Homebrew and uv in
   `/opt/homebrew/bin` (not on a non-interactive shell's PATH); Xcode present; no Rust (cargo) yet;
   no Pollen checkout.
