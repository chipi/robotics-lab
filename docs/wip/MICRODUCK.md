# Microduck — what Pollen / Hugging Face already built

Read 2026-11-13 from the official repos (READMEs and the simulator doc), not from the robot.
Everything is Apache-2.0 except the 3D meshes in `microduck_rl` (CC BY-NC-SA 4.0).

## The official repos (github.com/pollen-robotics)

| Repo | What it is |
|---|---|
| `microduck` | The robot's software: Rust daemons on a Rockchip RK3566. `robotd` (50 Hz control loop, 15 servos, neural policies), `updaterd` (signed, health-gated, reversible updates), `configd`, `btd`, `padd` (gamepad), `autod` ("the duck's own brain"), `mediad` (camera over WebRTC), `tofd` (8×8 time-of-flight depth). All talk one **JSON-RPC contract over Unix sockets**; app, console, gamepad and scripts send the same calls. CLI: `robotctl`; `duckctl` drives it from a laptop over Bluetooth. |
| `microduck_rl` | Training: MuJoCo (mjlab / MuJoCo Warp) + PPO, actuator model (BAM), domain randomisation, export to ONNX, `publish` to the Hugging Face Hub. 13 task families (walk, fall recovery, stand up, sit/stand, ground pick, ball kick, roll, roller skating …). **Training needs a CUDA GPU** or Hugging Face Jobs (`--hf-jobs`). |
| `microduck-arena` | Hugging Face Space and local CLI: races a policy on a fixed course **over five perturbed seeds**, scores the mean finish time (a fall counts as the time limit). Runs locally with no account and no network. Events: `sprint-2m`, `roller-sprint-2m`, `hill-climb-1m5`; also "Got a Talent", tug of war, sock heist. |
| `microduck-challenges` | One training folder per arena event, with an `AGENTS.md` written for coding agents. |
| `microduck_emotions` | 14 emotions, each a motion (keyframes) and a sound. |
| `duck_detector` | Finds Microducks in a Microduck's camera; dataset → train → quantise for the NPU. |
| `microduck_yocto` | The robot's OS. |

Community: `awesome-microduck` (curated list), `microduck-lab` (trains on a Mac, no CUDA), and
several hardware replicas.

## Facts that shape our plans

- **A policy is one ONNX file: 61 numbers in, 14 out.** The same contract on the robot, in
  the simulator and in the arena. Policies are swappable at runtime (walk / recover / trick).
- **There is a simulated duck driven by the real daemons.** `scripts/duck-sim` in `microduck`
  runs `robotd --sim` against a MuJoCo body from `microduck_rl` (`duck-body`). Same
  `robotctl`, same sockets, same policies; only the body is simulated. Options: several ducks,
  a six-room `apartment` scene, a rendered head camera served at `http://127.0.0.1:8080`.
  It cannot simulate drivers (servo bus, radio, camera ISP, NPU). It must run at or above real
  time, or the policies cannot balance.
- **The arena already does sim evaluation** — a fixed course, five perturbed seeds, a mean.
  It does not test whether two policies differ significantly; that is eval-harness's job.
- **Times are only reproducible on the same hardware** (the servo model is chaotic): the
  arena says a local time is "indicative, not the board's".

## Policies, slots and skills

In the duck's own terms (`microduck/docs/robot/cheatsheet.md`, "Policies and skills"):

- **Policy:** a trained neural network in one ONNX file that the robot runs 50 times a second:
  61 numbers in (48 about the body's own state, plus the command: speed and turn 3, head pose 4,
  body pose 6), 14 joint targets out. Every policy has the same shape, so the robot can swap them
  at any moment.
- **Slot:** what the robot runs **by default** (seven slots, e.g. the walking gait). Loading a
  policy into the walk slot changes how it walks.
- **Skill:** what it runs **when asked** (`robotctl robot do <name>`, or a gamepad button). Backed
  by a policy (kicks, the roll, a community "polite bow"), by a policy the robot drives itself
  (ground pick, sit/stand), or by an **emotion** — keyframes plus a sound, no network at all.

**The network**, read from the actual files (`velstand.onnx`, `roulade.onnx`, the arena's
reference walker; all the same): a plain fully connected network (MLP), 61 → 512 → 256 → 128 →
14, ELU activations, an input normaliser baked in; **197,896 parameters, about 790 KB**. Small
enough for 50 runs a second on the RK3566. Training also uses a second network of the same size
(`hidden_dims=(512, 256, 128)` appears twice in the task configs) — PPO's critic, by my reading of
the config, not traced in code — which is not shipped.

**Making your own skills**, easiest first:
1. **Emotions:** a keyframes JSON (head, body, beak over time) plus a `.wav`; no training. 13 ship.
2. **Choreography:** the arena's "Got a Talent" timelines string existing moves, sounds and up to
   8 ducks together; try it in simulation.
3. **A new trained policy:** a new environment and reward in `microduck_rl`, trained on the DGX
   (about 3 h), checked in `duck-sim` and the arena, published, installed as a skill. Only an
   "episodic, constant command" policy can be a generic one-shot skill. Jumping: unknown — the
   roll and stand-up show dynamic moves work; whether jumps do, and what they do to the gears,
   would show in simulation first.

## Getting our environment ready

What this machine has (checked 2026-11-13): `uv`, `git-lfs`, GStreamer, `systemd-nspawn`,
Node/npm, 32 cores, 124 GB RAM, about 1 TB free disk. Missing: a **Rust toolchain**
(`cargo` builds the daemons), `mmdebstrap` (only for the multi-duck container mode), and an
**NVIDIA GPU** (`nvidia-smi` not found).

| Step | Needs | Gives |
|---|---|---|
| 1. Clone `microduck`, `microduck_rl`, `microduck-arena`, `microduck-challenges` | Nothing installed | The code to read and run |
| 2. `uv sync` in `microduck-arena`, race the vendored reference policy (`arena score … --event sprint-2m`) | Its own venv | First sim results on CPU, no account |
| 3. Install Rust (rustup), `uv sync` in `microduck_rl`, run `scripts/duck-sim` | Rust; `microduck_rl`'s venv pulls about 2 GB of CUDA wheels | A simulated duck in a window, driven with `robotctl` |
| 4. Train a policy | A CUDA GPU: the homelab DGX (shared; coordinated with the `gpu-mode` skill) or Hugging Face Jobs (paid) | Our own policies |

### Done on this workstation (2026-11-13)

- Clones in `/work/pollen/`: `microduck` (`094d4bb4`, release 0.21.1), `microduck_rl`
  (`0daab160`, branch `develop`, its default), `microduck-arena` (`9bf04c0`),
  `microduck-challenges` (`5cee942`).
- **Arena:** `uv sync` in `microduck-arena`; the vendored reference policy on `sprint-2m`:
  `score 9.392s · 5/5 finished` (seeds 9.39 / 9.385 / 9.45 / 9.365 / 9.37 s, at 0.45 m/s),
  6.5 s of CPU time. The saved run (`--store DIR` → `runs/<event>/<id>.json`) has a `per_seed`
  list with each seed's status and `time_s` — what eval-harness needs per item.
- **Rust** 1.100.0 for this user only (`~/.cargo`, `~/.rustup`, installed with rustup,
  shell profile not changed: put `~/.cargo/bin` on `PATH` to use it).
- **`microduck_rl` venv:** `uv sync` OK, 7.7 GB (more than the ~2 GB the README warns about).
- **Simulated duck:** `scripts/duck-sim` built the daemons, fetched the official policy set
  from the Hub (no policy was set locally), and stood up headless: `robot healthy`,
  `loop 50.0 of 50.0 Hz · 0 missed`, world at `1.00x real time`. Walking, measured with
  `scripts/duck-sim drive`:

  | Asked | Got |
  |---|---|
  | 0.15 m/s forward, 8 s | 1 cm (0.001 m/s): "it did not walk" |
  | 0.3 m/s forward, 8 s | 104 cm (0.130 m/s), drifted −25° |
  | 0.8 rad/s on the spot, 8 s | +6° (upstream measured about 50°/s) |

  The first two match what upstream documents (arena README: the policy tracks about 44 % of
  its commanded speed and does not walk below about 0.2 m/s; `docs/design/simulation.md` §11
  lists the forward shortfall as open). The turn does not match upstream's measurement; cause
  not investigated.

Run it (window): `PATH=$HOME/.cargo/bin:$PATH DUCK_SIM_RL=/work/pollen/microduck_rl
/work/pollen/microduck/scripts/duck-sim`, then `scripts/duck-sim drive 0.3 0`, and
`scripts/duck-sim down` when done. Add `DUCK_SIM_VIEWER=0` for no window.

### Training on the DGX (homelab, 2026-11-13)

The homelab added a `robotics` GPU mode (agentic-ai-homelab `7bae371`; recipe
`docs/recipes/robotics-training.md`, stack `infra/robotics/microduck/`). `gpu-mode-swap.sh
robotics` stops every vLLM and Ollama and starts the `robotics-train` container (uv image pinned
by digest, nvidia runtime, as `ops`, memory capped at 64g, under a timeout). Training code is
`/opt/robotics/microduck_rl` at `0daab160d3fb`; results land in
`/opt/robotics/microduck_rl/logs/rsl_rl/velocity/<run>/`. Settings in the ops checkout's
`infra/robotics/microduck/.env` (`ROBOTICS_TRAIN_ARGS`, `ROBOTICS_MAX_RUNTIME`,
`ROBOTICS_NUM_ENVS`, `ROBOTICS_MEM_LIMIT`).

First measured run (homelab's numbers, 21:33Z–21:44Z, 4096 envs): GPU memory 5.1 GB, container
memory 2.6 GiB, 90 % GPU utilisation, 2.78 s per iteration, mean reward 77 at iteration 100.
torch 2.9.1+cu129 warns that GB10 (capability 12.1) is newer than it supports, and trained anyway.
Switching to `robotics` took about 1 min, back to `prod` 6 min 18 s.

Lessons: mjlab logs to Weights & Biases by default and stops without a key (use
`--agent.logger tensorboard`); rsl_rl does **not** save when stopped, so the measured run kept
only `model_0.pt` (iteration 0, not a usable policy). Always set `--agent.save_interval`.

Full run (planned): `--agent.max_iterations 4000 --agent.save_interval 100`, about 3 h 5 min,
`ROBOTICS_MAX_RUNTIME=3h30m`, after the nightly (infra keeps 23:45Z–03:00Z clear). Leaving
`prod` is the operator's call each time.

## How it connects to the rest

- **eval-harness** — policies as arms; the arena's five seeds become repeated items with a
  real significance test. See [EVAL-HARNESS-ROBOTS.md](EVAL-HARNESS-ROBOTS.md).
- **flotilla** — the daemons' JSON-RPC contract is a ready-made action surface for a host
  agent; `updaterd`'s signed, health-gated, rollback updates are close to flotilla's own model.
- **NXT** — the duck's `robotctl` / JSON-RPC is a better-designed version of the HTTP API in
  `nxt-web`; when the time comes to write a shared robot contract (ECOSYSTEM.md step 3), it is
  the reference to learn from.

Sources: the READMEs of the repos above, `microduck/docs/robot/simulation.md`.
