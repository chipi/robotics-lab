# RFC-0021 — The simulator host and the payload: run a navigator on any machine that has Pollen's simulator

**Status:** Proposed (2026-11-19), for the operator's decision at the phase 4 checkpoint; to be
built right after phase 4. The operator, 2026-11-19: "we should assume [the] host has [the] Pollen
repo and their MuJoCo sim env; can our code easily be transferable there if basic infra is set up
well? … can we separate sim as host from payload?", and: "[the] DGX is just an example; I could run
it on some dedicated VPS host, more realistic". **Builds on:**
[RFC-0020](RFC-0020-robot-profiles-and-plugins.md) (a robot's profile and plugins),
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

- One machine prepared once (a dedicated VPS is the realistic case: x86-64, no GPU, headless) runs a
  course for any payload with one command, and writes recordings the Observatory opens unchanged.
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

## 4. Setting up a host

A script in this repository, run once on a fresh VPS, checks and reports each requirement with
PASS/FAIL (Pollen's repositories present and built, the MuJoCo environment importable, the
`duck-sim` patch applied, our packages installed) and writes `host.json`. It installs nothing on its
own; it prints what is missing. A container image for the payload and runner follows if the host
script proves the line is clean.

## 5. Steps

1. **Host file and reset out of the payload:** `simreset` becomes a host tool; the navigator reads
   socket paths from `host.json` (the profile's `control` block keeps no paths: phase 5 needs this
   too); the data folder from the installation, not a default path.
2. **Truth out of the payload:** the runner reads the body server and merges truth into the
   recording; the navigator stops reading port 7801. The judge, the evaluation and the challenges
   move to the runner. Proof: phase 1's evaluation and challenges 1–5 judged the same as before
   (pass counts over repeats, the simulator is not deterministic: K13); the recordings open in the
   Observatory with truth where they had it.
3. **The host check script**, tried on a clean machine (a VPS or a fresh container standing in for
   one).
4. **One course on a second machine:** phase 1's 20 goals run there, the recording copied back and
   opened in the Observatory beside a run from this workstation.
5. **A second payload:** a minimal navigator (straight to the goal, stop on the depth sensor)
   through the same contract, to prove the contract is not ours alone.

## 6. Risks

- **Pollen's code changes shape** (the scene file, the services' arguments): the host check reports
  the version it was tested with; the scene builder already refuses a changed `scene_backlash.xml`.
- **Timing on a slower host:** the navigator's loop runs on wall-clock time; a slow VPS may change
  results. The host check measures the simulator's real-time factor and records it with every run.
- **Truth leaking:** step 2's proof includes a test that the payload's process has no route to the
  body server's port.

## 7. Open questions

1. Pollen's licences for `microduck` and `microduck_rl`: what a host may run and what we may
   distribute (to check before step 3).
2. The payload's contract: Mission Control's navigator API as it is, or a smaller one for the runner
   (arena question 4)?
3. Several robots on one host (one simulator with several ducks: the body server takes `--ducks`),
   or one robot per host?
