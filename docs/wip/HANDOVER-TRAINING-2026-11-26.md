# Handover: the learning arc, 2026-11-26

For the next session, starting from scratch. The operator's goal: finish today's training, then
clear the session. This page says where the arc stands, what is still running, what comes next in
order, and the rules that held. Updated as the last runs land; anything marked **in flight** was
running when it was written. The living project status stays in [HANDOVER.md](HANDOVER.md).

## The arc in one paragraph

A LinkedIn post about NVIDIA's learned obstacle-avoidance controller for the Microduck became a
research programme ([the plan](RESEARCH-LEARNED-AVOIDANCE.md)): read their code (R1), match our
simulated sensor to theirs (R2), give our navigator a slot for a learned local controller (R3),
train it ourselves on the DGX (R6), compare it with our rules on frozen scenarios (R5), then our
own variants (R7a-e), the real duck last (R8). Track E built the evaluation side: a private eval
repository on eval-harness and public datasets later. All of it, R1-R7 and S1-S5, runs before
MVP 2 (the operator's decision).

## Repositories

| Repo | What | State |
| --- | --- | --- |
| robotics-lab (this one, public) | The platform; the navigator's local-controller slot (`robots/duck/src/duck_lab/plugins/learned.py`, `rules.py`); `lab-scenarios export/mine/pool` (`libs/runner`); the training guide (`docs/training/`) | main at 9759435 or later |
| [chipi/microduck-nav](https://github.com/chipi/microduck-nav) (public) | NVIDIA's task ported to mjlab against Pollen's walker; tasks `Mjlab-Nav-OneWall-`, `-Nav-`, `-Nav-Deploy-`, `-Nav-Ours-MicroDuck`; `docs/M1.md`, `M2.md`, `R7.md`, `CHECKS.md` | main at bbeaf66 or later; 220 fast CPU tests |
| chipi/robotics-evals (private) | evh project: datasets, runs, the run ledger, the pre-registration | main at f3d68a7 or later; eval-harness **0.8.1** pinned, 0.8.2 released (upgrade pending) |
| `/work/microduck-nav-runs/` (local, not a repo) | Training run folders from the DGX and R5 evidence runs | `m1/`, `m2a-snap/`, `r5/rules_v1/`, more as they land |

## What ran today, with results

| Run | Task, size | Result |
| --- | --- | --- |
| Smoke | OneWall, 64 x 20 | First try failed: mjviser 0.0.17 pulled mujoco-core 4.0.1, which overwrote mujoco 3.10.0 (fixed b5a9fa9). Second: passed, 0.64 s/iteration |
| M1 | OneWall, 4096 x 200, 15:55Z | **Passed**: progress 0.20 to 0.35, collisions 0.74 to 0.16, replay 13 of 16 stopped before the wall (81 %), 4.76 s/iteration. Folder `m1/2026-11-26_15-55-36/` |
| M2a | `Mjlab-Nav-MicroDuck` (NVIDIA-faithful, 50 Hz, sidestep), 4096 x 1500, 16:15Z to 18:14Z, commit b5a9fa9 | **Done**, exit 0, 16 checkpoints (every 100) in `m2a/2026-11-26_16-15-00/`, each with a rate sidecar. Progress rose (0.44 to 0.49) but collisions per iteration were lowest at 250-499 (0.27) and rose to 0.52 by the end, the approach penalty growing: it learned to push closer. The end is not the best model; candidates by the pre-registered rule (lowest 100-wide collision window, 100-199 at 0.208): `model_100`, `model_200`, `model_1499`, selected on `avoidance_val` |
| M2b | `Mjlab-Nav-Deploy-MicroDuck` (10 Hz policy, no sidestep), 4096 x 400, commit 8399be8 | **In flight**: started 18:15Z, due about 20:35Z; the homelab swaps back to prod when it ends. 400 iterations because one iteration is 5x the simulated time of M2a's |
| R5 rules arm | `rules@1` on `avoidance_v1` (30 items) | **30 of 30**, 0 collisions, min clearance 0.094 m, mean 43 s; imported as `rules_v1` (robotics-evals f3d68a7) |
| R5 rules arm, v2 | `rules@1` on `avoidance_v2` (40 items, challenges 24-28 x seeds 1-8, robotics-lab e97edbe) | **23 of 40** (57.5 %), 0 collisions: narrow_doorway 3/8, dense_boxes 2/8, chair_cluster 8/8, slalom 8/8, box_behind_door 2/8. Two families at 8/8 cannot show a gain (four pilot seeds overstated them; not changed after seeing test seeds). Imported (robotics-evals a111bba) |

The DGX: the operator gave it to us for the whole series ("it stays yours until you're done with
M1 and M2"); the homelab session runs every swap and copies folders to `/work/microduck-nav-runs/`.
Prod must be back by 23:20Z; the nightly 23:45Z to 03:00Z stays clear.

## Decisions taken today (all recorded where they belong)

- RFC-0030: questions 1-6 decided (`missions`; areas in config; LLM planner off; spike capped at
  $1 per mission and two sessions; approval A by default; the loop in Mission Control). The
  `libs/missions` carve-out landed (1cd9e8c).
- MCP rules R6-R8 kept. The real sensor's failed floor zones stay a drop until R8.
- Review round 4 all A: look-and-feel closed for MVP 1; step 4.9 ready; the Observatory fronts both.
- S5: four skills in `.claude/skills/` (`robotics-run-read`, `sim-run`, `challenge-batch`,
  `dgx-training-run`).
- Zone grid `mixed` by default. A failing learned model **brakes** (RFC-0025 3.7).
- M2 as two runs, M2a (NVIDIA-faithful, the blog baseline) and M2b (deploy-matched, for R5).
- R5 judged on a harder set: `avoidance_v2` primary (success), `avoidance_v1` a safety regression
  (30/30, 0 collisions), checkpoint chosen on `avoidance_val`; written in robotics-evals
  `docs/R5-PREREGISTRATION.md` **before** any learned arm runs.
- R7a-e before MVP 2; R7d is Pollen's simulated apartment; **the operator's home is not in the
  plan**.
- RFC-0031 (learning in the lab) accepted, all eight answers as recommended: option A, a read-only
  training-run page first as an MVP 2 side lane; the trainer adapter after MVP 2.

## In flight when written

- M2b on the DGX (above).
- R5 M2a arm: an agent runs the three candidates on `avoidance_val` (33 items), writes the
  selection into the pre-registration, then the selected checkpoint on v2 and v1, imports `m2a`
  and runs `comparison-show`. Holm across arms waits for M2b.
- CI on main was red from 54defc1 to 3a22670 (`test_settings_page` waited for exactly four
  Modules rows; the local-controller slot made five). Fixed in 26097d2.

## Next, in order

1. **M2a lands** (`/work/microduck-nav-runs/m2a/`): curves with
   `.claude/skills/dgx-training-run/scripts/checkpoint_report.py`; the CPU replay
   (`uv run python -m microduck_nav.replay <model.pt>` in microduck-nav); write a sidecar
   `<model>.onnx.json` for each checkpoint (M2a predates ONNX metadata):
   `{"task": "Mjlab-Nav-MicroDuck", "policy_step_s": 0.02, "lateral_limit": 0.12, "obs_layout":
   "nav-1343-v1"}`.
2. **M2b lands** (`m2b/`): the same; its sidecar has `policy_step_s` 0.1 and `lateral_limit` 0.0.
   Then tell the homelab M1 and M2 are done, so the DGX goes back to prod.
3. **Checkpoint selection** on `avoidance_val` per the pre-registration (each arm's checkpoints,
   highest success, then fewest collisions, then latest).
4. **R5's learned arms**: the selected M2a and M2b checkpoints through the navigator
   (`lab-challenge ... --local-controller learned --model PATH`) on v2 and v1, from a clean
   worktree (`make duck-sync` first), scored with `challenge-batch`'s `batch_scores.py`, imported,
   then `evh comparison-show` against `rules_v1`. In our navigator the guards are always on, so
   these arms are already "learned under the guard".
5. **eval-harness 0.8.2**: pin it in robotics-evals, check `evh --version` and `make validate`;
   new datasets use `--fields-from-item` and `--exclude manifest.json`.
6. **Tomorrow's GPU window, R7a + R7b**: regenerate the pool at a clean robotics-lab commit with
   `--exclude-dataset` for v1, v2 and val; then `docs/R7.md`'s command (4096 x 400,
   `Mjlab-Nav-Ours-MicroDuck`). Fix `docs/R7.md`'s evaluation plan first: it still says v1; it
   must follow the pre-registration (v2 primary, v1 safety, val for selection).
7. **R7c**: mine the R5 rules and learned failures on v2 into training scenarios (`lab-scenarios
   mine`, excluding v1, v2 and val).
8. **R7d** (Pollen's apartment as a static scene, about 1-2 weeks) and **R7e** (teacher and
   student), after R7a/b.
9. **E5**: the blog post (M2a vs rules vs M2b vs R7 on our duck) and public Hugging Face datasets
   (`avoidance_v1`, `v2` as `robotics-avoidance-v1/-v2`).
10. **The MVP 1 close-out** remains: the README and docs pass, the name and branding (the
    operator's call), the RFC-0024 review's recommendation 5 (split triggers into RFC-0018). Steps
    6 (NXT at the brick) and 7 (staging) wait for hardware and the X3 window.

## Known gaps and traps

- **Rate and sidestep.** A model trained at 50 Hz with sidestep (M2a) runs in a 10 Hz navigator
  with no lateral command; `learned.py` handles the rate per model, but the mismatch is real and is
  why M2b exists.
- **A fresh worktree needs `make duck-sync`** before `lab-challenge` (the navigator runs from
  `robots/duck/.venv`); the sim-run preflight now checks it.
- **Never swap a checkout under a running training process** (prepare.sh between runs only).
- **`Train/mean_reward` is noisy** with 1000-step episodes; read per-term curves over windows
  (`scratchpad` reader: `windows.py`, worth moving into the dgx-training-run skill).
- **No evaluation set may enter training**: every `pool` and `mine` passes `--exclude-dataset` for
  v1, v2 and val.
- **Pool file**: `ours-v1.jsonl` is 29.7 MB, not in git (2.2 MB gzipped; the loader reads
  `.jsonl.gz`); its sha256 is in microduck-nav's `data/pools/ours-v1.manifest.json`.
- **Unverified in training**: the sensor mount pitch (Pollen's level vs NVIDIA's 20 degrees down),
  prop heights, the guard-intervention weight (-2), lambda at 10 Hz, `command_rate`'s 5x cost at
  10 Hz.

## Sessions and people

- **homelab** session: DGX swaps, `prepare.sh`, the stack's `.env`, copies of run folders.
- **eval harness** session: eval-harness gaps and releases; we are beta users.
- The advisor (Fable 5.1) reviewed RFC-0024, RFC-0030 and RFC-0031; reviews in `docs/wip/`.

## Where to read first

[The research plan](RESEARCH-LEARNED-AVOIDANCE.md), [the training guide](../training/index.md),
microduck-nav's `docs/M2.md` and `docs/R7.md`, robotics-evals' `docs/R5-PREREGISTRATION.md`, and
[RFC-0031](../rfc/RFC-0031-learning-in-the-lab.md).
