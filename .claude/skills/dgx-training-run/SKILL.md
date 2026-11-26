---
name: dgx-training-run
description: Ask for a DGX training run of a Microduck project (microduck_rl or microduck-nav) and check it afterwards - a local preflight (repo clean and pushed, uv.lock with cu129 torch for aarch64, the walker's sha256, --agent.save-interval in the args, a runtime and window clear of the nightly), the request to send the homelab session, and the post-run check of curves, replay and the checkpoint's ONNX shape. Use when asked to "train the controller on the DGX", "start the M1 run", "request a GPU window", "is the training run done / any good", "check the checkpoint". Do not use to run swaps, edit the stack's .env, run prepare.sh or touch the DGX - the homelab session does that; do not use for simulator jobs (sim-run).
metadata:
  permissions:
    read: ["/work/microduck-nav", "/work/agentic-ai-homelab/docs/recipes/robotics-training.md", "~/.cache/duck-sim/policies/current", "a run's logs/ folder copied locally"]
    write: []
    execute: [scripts/preflight.py, scripts/checkpoint_report.py, "git ls-remote origin"]
---

# dgx-training-run

## The split

**The homelab session runs the swaps (`gpu-mode-swap.sh`), the stack's `.env` and `prepare.sh`.** We send a request and read what comes back.
We never log in to the DGX, run docker or `gpu-mode-swap.sh`, edit `.env`, or touch the Mac mini's production Docker socket. The homelab's
recipe is `/work/agentic-ai-homelab/docs/recipes/robotics-training.md`; the project's own plan for a first run is `/work/microduck-nav/docs/M1.md`.

## Preflight (local, read only)

```bash
.claude/skills/dgx-training-run/scripts/preflight.py /work/microduck-nav --task <task> --num-envs 4096 --max-runtime 30m \
  --args="--agent.max-iterations 200 --agent.save-interval 50 --agent.logger tensorboard" [--start 2026-11-27T04:00Z]
```

It ends `DGX-PREFLIGHT READY` with the request block, or `NOT READY` and what to fix. What each line stands for:

| Line | Why it matters |
| --- | --- |
| `repo clean`, `pushed` | the DGX trains a commit, not a working tree; an unpushed commit cannot be checked out there |
| `lock` | a lock without a `+cu129` aarch64 wheel gives the GB10 a CPU torch and the mode ends at once |
| `walker` | the task refuses to start without Pollen's walker (policies v10, sha256 `ce894d30...63e0a`); the DGX's copy is the homelab's to check |
| `args` | `--agent.save-interval N`: rsl_rl saves nothing on a stop, so a timed run keeps only `model_0` without it. `--agent.logger tensorboard`: mjlab's default W&B stops at once without a key |
| `runtime` | one number and one unit (`210m`); `3h30m` made `timeout` refuse and failed a swap on 2026-11-14 |
| `window` | prod is back by 23:20Z; 23:45Z to 03:00Z stays clear for the nightly |

The preflight is evidence, not approval: the operator gives the window, and the homelab checks that prod is idle.

## Send

The request names: the project and the full commit sha, the entry (`train`), the task, `--env.scene.num-envs`, the trainer args, and the max
runtime. Say it to the homelab session in those words; wait for its "up" before anything else. A run is: swap in (about 1 min), the run,
swap back (about 6 min, 6 m 18 s measured). Everything in `references/dgx-notes.md`.

## Check afterwards: three signals that must agree

1. **Curves**, from the run's `logs/rsl_rl/<name>/<timestamp>/` copied back: `Episode_Reward/progress` rises and `Episode_Termination/obstacle_collision`
   falls (`checkpoint_report.py`, run with `/work/microduck-nav/.venv/bin/python`). Under 8 points the script says INCONCLUSIVE.
2. **Replay**: `uv run python -m microduck_nav.replay <logs>/model_N.pt --num-envs 16 --steps 600`; M1 is met when at least 80 % of the
   replay environments stop before the wall (exit 0). It plays the ONNX beside the checkpoint, the file that deploys.
3. **The ONNX**: `(1, 1343) -> (1, 3)` with the normaliser inside (`checkpoint_report.py` checks it).

A curve alone is not proof; a replay of a policy from a run that kept one checkpoint (no save interval) says little. Training rollouts are
stochastic and the replay is deterministic, so a policy can look worse in training than in replay.

## Never

- Touch the DGX, `gpu-mode-swap.sh`, the stack's `.env`, `prepare.sh`, or the production socket.
- Ask for a run that overlaps 23:45Z to 03:00Z, or ends after 23:20Z; or a window the operator has not given.
- Send args without `--agent.save-interval` and `--agent.logger tensorboard`, or a runtime like `3h30m`.
- Train a dirty or unpushed commit; claim "it learned" from the curves without the replay.

## Not covered

How the swap goes, the DGX's mode or load (the homelab's `gpu-mode`), the cost of the window, W&B, resuming (`--agent.resume True`), the
GPU run of M2/M3, and the iteration time of the nav task on the GB10 (unmeasured; the plan's estimate is 3.2 to 4.5 s).
