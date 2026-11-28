# Handover: the learning arc, 2026-11-26

For the next session, starting from scratch. Written 2026-11-26, last updated 2026-11-28 morning.
This page says where the arc stands, what is still running, what comes next in order, and the rules
that held. Anything marked **in flight** was running when it was written. The living project
status stays in [HANDOVER.md](HANDOVER.md).

**Where it stands (2026-11-28):** the operator's goal is M2b at least at M2a's level (below). M2c
(M2b trained longer) and M2bw (M2b plus walls) are trained and being evaluated as harness round r3;
M2d (M2c plus walls) is training on the DGX, due about 17:54Z, its log, copy and prod swap on X3
timers (`/work/microduck-nav-runs/m2d/STATUS`). Results are in the evals catalog,
<https://robotics-evals.tail6d0ed4.ts.net> (tailnet only).

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
| robotics-lab (this one, public, MIT) | The platform; the navigator's local-controller slot (`robots/duck/src/duck_lab/plugins/learned.py`, fixed afa5fab); `lab-scenarios export/mine/pool` (`libs/runner`); the training guide (`docs/training/`); user guides (`docs/guides/`) | main at 8560dba or later; worked from the worktree `/work/robotics-lab/mission-control`, pushed `HEAD:main` |
| [chipi/microduck-nav](https://github.com/chipi/microduck-nav) (public) | NVIDIA's task ported to mjlab against Pollen's walker; tasks `Mjlab-Nav-OneWall-`, `-Nav-`, `-Nav-Deploy-`, `-Nav-Deploy-Room-` (M2bw, M2d), `-Nav-Ours-MicroDuck` (R7); `docs/M1.md`, `M2.md`, `M2D.md`, `R7.md`, `CHECKS.md` | main at 32ac389; 235 fast CPU tests; no CI |
| chipi/robotics-evals (private) | evh project on eval-harness **0.8.2**: datasets, imported runs, models, deployments, systems, goals with rounds, the pre-registration (`docs/R5-PREREGISTRATION.md`, sections 9 R5b and 10 M2c/M2bw), the workflow (`docs/EXPERIMENTS.md`) | main at aecbd99 or later; gate `make validate`; no CI; served on the Mac mini (catalog above, MCP at `/mcp`), rebuilt from main every 5 minutes |
| `/work/microduck-nav-runs/` (local, not a repo) | Training run folders and evaluation evidence | `m1/`, `m2a/`, `m2b/`, `m2c/`, `m2bw/`, `m2d/` (tonight), `r5/`, `r5b/`, `r5c/` (r3), `pools/` |

## What ran today, with results

| Run | Task, size | Result |
| --- | --- | --- |
| Smoke | OneWall, 64 x 20 | First try failed: mjviser 0.0.17 pulled mujoco-core 4.0.1, which overwrote mujoco 3.10.0 (fixed b5a9fa9). Second: passed, 0.64 s/iteration |
| M1 | OneWall, 4096 x 200, 15:55Z | **Passed**: progress 0.20 to 0.35, collisions 0.74 to 0.16, replay 13 of 16 stopped before the wall (81 %), 4.76 s/iteration. Folder `m1/2026-11-26_15-55-36/` |
| M2a | `Mjlab-Nav-MicroDuck` (NVIDIA-faithful, 50 Hz, sidestep), 4096 x 1500, 16:15Z to 18:14Z, commit b5a9fa9 | **Done**, exit 0, 16 checkpoints (every 100) in `m2a/2026-11-26_16-15-00/`, each with a rate sidecar. Progress rose (0.44 to 0.49) but collisions per iteration were lowest at 250-499 (0.27) and rose to 0.52 by the end, the approach penalty growing: it learned to push closer. The end is not the best model; candidates by the pre-registered rule (lowest 100-wide collision window, 100-199 at 0.208): `model_100`, `model_200`, `model_1499`, selected on `avoidance_val` |
| M2b | `Mjlab-Nav-Deploy-MicroDuck` (10 Hz policy, no sidestep), 4096 x 400, 18:15Z to 20:43Z, commit 8399be8 | **Done**, exit 0, checkpoint_report PASS, 9 checkpoints (every 50) in `m2b/2026-11-26_18-15-16/`, each with a sidecar. Collisions per iteration 0.93 (0-99) to 0.107 (200-299, lowest) then 0.163; progress 0.49 to 0.59; goal arrivals doubled. Unlike M2a it got safer. Candidates (pre-registered, robotics-evals a48ff3c): `model_200`, `model_300`, `model_399`. The DGX released to prod after it |
| R5 rules arm | `rules@1` on `avoidance_v1` (30 items) | **30 of 30**, 0 collisions, min clearance 0.094 m, mean 43 s; imported as `rules_v1` (robotics-evals f3d68a7) |
| R5 rules arm, v2 | `rules@1` on `avoidance_v2` (40 items, challenges 24-28 x seeds 1-8, robotics-lab e97edbe) | **23 of 40** (57.5 %), 0 collisions: narrow_doorway 3/8, dense_boxes 2/8, chair_cluster 8/8, slalom 8/8, box_behind_door 2/8. Two families at 8/8 cannot show a gain (four pilot seeds overstated them; not changed after seeing test seeds). Imported (robotics-evals a111bba) |
| R5 validation | Candidates on `avoidance_val` (33 items) | M2a: `model_100` 22/33 0 coll., `model_200` 22/33 1 coll., `model_1499` **0/33 (never moved)**. M2b: `model_200` 22/33 2 coll., `model_300` 0/33, `model_399` 0/33. Selected M2a `model_100`, M2b `model_200` (robotics-evals 8337114, db3b3e4) |
| **R5 result** | Selected checkpoints on v2 and v1, Holm across the two arms (d64a775, 69f8c17) | **Neither learned arm beats the rules.** v2: rules 23/40, M2a 20/40 (not significant, p 0.50), M2b 9/40 (**worse**, Holm p 0.025). Each learned arm had 1 collision on v2 (the same item, `dense_boxes-s2`, 1 mm inside the footprint), so both fail the collision limit. v1 safety (30/30, 0 collisions): M2a 26/30, M2b 21/30 with 1 collision; both fail |
| **R5b** (2026-11-27) | The same checkpoints re-selected on robotics-lab afa5fab (the floor rule and pivot pass-through) | M2a `model_200`: v2 21/40 (not significant vs rules), 2 collisions, v1 30/30. M2b `model_300`: v2 10/40 (**worse**), v1 15/30. Rounds r2, closed, nothing promoted |
| M2c (2026-11-27) | `Mjlab-Nav-Deploy-MicroDuck`, 4096 x 1500, commit 8399be8 | Done, `m2c/2026-11-27_08-08-02/` (sidecars written, log kept). Candidates `model_200`, `model_300`, `model_1499`; in r3 |
| M2bw (2026-11-27) | `Mjlab-Nav-Deploy-Room-MicroDuck`, 4096 x 400, commit 32ac389 | Done, `m2bw/2026-11-27_17-43-37/`; its docker log was lost before it was copied. Candidates `model_100`, `model_200`, `model_399`; in r3 |
| M2d (2026-11-28) | `Mjlab-Nav-Deploy-Room-MicroDuck`, 4096 x 1500, commit 32ac389 | **In flight**, due about 17:54Z |

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

## What R5 found (read before R7)

- **Later checkpoints stop walking.** M2a's last checkpoint (`model_1499`) applied forward speed 0
  in all 33 validation runs; M2b's `model_300` and `model_399` barely moved. Training's own
  collision curve looked fine for M2b to the end, so "safe" in training partly meant "stands
  still" in the navigator.
- **Diagnosed (2026-11-27, `/work/microduck-nav-runs/r5/standstill-diagnosis.md`): two deployment
  defects of ours, not the training.**
  1. *The depth frame is out of distribution.* Training's impairment drops floor returns beyond
     about 0.556 m (microduck-nav `impairments.py:39,108-112`) and its scenes rarely show walls
     beyond 2 m; the navigator's frame has floor returns at 0.8-1.2 m and walls at 2.5-3.1 m.
     `model_1499`'s raw output was exactly (-1, 0, 0) on 150 of 150 traced ticks; with those
     returns removed from the recorded frames, all five checkpoints tested drive forward. R4's
     parity fixture checked the observation code on constructed states, not the impairment, so it
     missed this.
  2. *Pivots are clipped.* `learned.py` clips yaw to 0.75 rad/s, under the profile's
     `stand_turn.min_rad_s` 1.1, so a pivot request never turns the duck (pose yaw 0.02 to -0.19
     rad over a whole run; rules turns 2.83 rad on the same item). This is most of the selected
     checkpoints' stand-stills, independent of the model.
  R5's recorded result stands as run; it measured the models behind these two defects. The fair
  test is **R5b**: fix both, pre-register, redo selection on `avoidance_val`, then v2 and v1.
  R7 trains under the same impairment, so the deployment fix applies to it too.
- Stand-stills also in the selected checkpoints: applied vx 0 for a whole run in 10 of 70 M2a and
  7 of 70 M2b test runs. Two "reached" calls 0.25-0.27 m from the goal were judged failures.
- The comparison is fair on v2: rules and learned ran on navigator code with no change between
  e97edbe and 26097d2. On v1 the rules ran at 54defc1; the changes since touch only the learned
  path and new challenges.
- Evidence: `/work/microduck-nav-runs/r5/{m2a,m2b}/{validation,test}/`. One infrastructure fault:
  `/tmp`'s quota refused writes for 3 minutes; 16 M2b validation runs were re-run on the same
  seeds (recorded in the pre-registration).

## The goal (the operator, 2026-11-27)

"Get M2b to at least where NVIDIA is, and then we can go to R7; we need to be on top of the game."
Measured: **M2b (deploy-matched) at least M2a's level** (NVIDIA's recipe on our duck; NVIDIA's own
published numbers are from another robot and scenes, not comparable) on `avoidance_v2`, selection on
`avoidance_val`: success at least M2a's, collisions no more than M2a's, no whole-run stand-stills.
Then R7, whose bar is the rules arm (23/40, 0 collisions).

**One change per experiment (the operator, 2026-11-27, after M2d's first build changed three
things).** Every training is a child of one parent and differs from it in one thing, proved before
it trains: M2d's `tests/test_m2d_same_draws.py` shows obstacles, start and goal bit-identical to
M2b's per seed, and `docs/M2D.md` lists the complete difference. The lineage:

| Experiment | Parent | The one change | State |
| --- | --- | --- | --- |
| M2a | (NVIDIA's recipe) | | R5, R5b evaluated |
| M2b | M2a | 10 Hz policy, no sidestep | R5, R5b evaluated |
| M2c | M2b | 1500 iterations instead of 400 (8399be8) | trained 2026-11-27; r3 evaluation running |
| M2bw | M2b | four room walls round every scene, 400 iterations (32ac389) | trained 2026-11-27; r3 evaluation running |
| M2d | M2c | the same four walls, 1500 iterations (32ac389) | training 2026-11-28 |
| R7 | (later) | our challenge pool and the guards in training | parked until the goal is met |

Doors and joined rooms are not a separate M2e: R7 and R7d bring them; reconsider only if M2d still
fails the two door families on v2.

## Next, in order

Done since R5: the deployment fix (afa5fab) and R5b; eval-harness 0.8.2; the experiments moved
onto the harness (models, systems with hypotheses, rounds r1 = R5 and r2 = R5b on both goals,
closed by the operator's decision, nothing promoted); v2's collisions limit set to 0 (the operator,
2026-11-27); M2c and M2bw trained. R5b's result: M2a 21/40 on v2 (not significantly below rules),
30/30 on v1, but 2 collisions; M2b 10/40, 15/30, significantly worse. Record in section 9.

1. **Read round r3** (M2c and M2bw, pre-registered in section 10 with candidates M2c
   200/300/1499 and M2bw 100/200/399): the agent writes the selections and the result to section
   10 and leaves r3 **open**; closing it is the operator's. Read each against M2b (`m2b_b`) and
   against rules.
2. **M2d** lands about 18:00Z (`/work/microduck-nav-runs/m2d/`, log saved first): candidates by
   the same rule, written to the pre-registration before any run, then round r4 the same way.
3. **Decide the next experiment** from r3 and r4 against the goal: is M2b's line at M2a's level?
   If yes, R7; if not, the next single change.
4. **Failure metrics in the scorer** (`stand_still`, `pivot_fail` as per-item descriptive metrics
   in `challenge-batch`'s `batch_scores.py`) so the harness shows them from the next imports; the
   harness cannot add them to runs already imported (reported, gap 2).
5. **R7a + R7b**: parked until the goal is met; the request is ready (microduck-nav 4248b0e, the
   pool's gz sha256 `0b23ce53...`).
6. **R7c**: mine the R5 rules and learned failures on v2 into training scenarios (`lab-scenarios
   mine`, excluding v1, v2 and val).
7. **R7d** (Pollen's apartment as a static scene, about 1-2 weeks) and **R7e** (teacher and
   student), after R7a/b.
8. **The MVP 1 close-out**: done except steps 6 (NXT at the brick) and 7 (staging), which wait for
   hardware and the X3 window. Done 2026-11-26: the README and docs pass with screenshots, user
   guides for every app (`docs/guides/`), the MIT licence, the GitHub description and topics, the
   RFC-0024 review's recommendation 5 (RFC-0018 §6.1). The name stays `robotics-lab` for now.
9. **E5, after the close-out** (the operator, 2026-11-26): the blog post (M2a vs rules vs M2b vs
   R7 on our duck) and public Hugging Face datasets (`avoidance_v1`, `v2` as
   `robotics-avoidance-v1/-v2`).

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
- **Save the docker log before anything else** when a training ends: M2bw's was lost when its
  container went. M2d's log, copy and prod swap run on X3 timers that do not depend on any
  session; the prod swap after M2bw came late (00:46Z against 23:20Z).
- **Rounds are closed by the operator only.** An evaluation agent's brief says "leave the round
  open"; r1 and r2 were closed by a brief of mine and the operator kept them closed.
- **No custom tracking.** Experiments live in the harness's records (`docs/EXPERIMENTS.md`); gaps go
  to the eval harness session as feature asks (sent: lineage, failure metrics on imported runs,
  `import-run` then `round-carry` on a new training). The old run ledger is retired.
- **Loose ends (2026-11-28):** the stray file `/work/robotics-lab/main/0:` (contains "vx"), no
  decision yet; the `rl-hostsetup-proof` container (21 GB on the X3), the operator chose delete
  (A), the homelab does it; the artifact link that did not open was an account mix-up, the
  operator is bringing the connectors in.
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
