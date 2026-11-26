# Notes from the homelab recipe and M1

Sources: `/work/agentic-ai-homelab/docs/recipes/robotics-training.md` (read 2026-11-26), `/work/microduck-nav/docs/M1.md`.

## What the homelab sets (the stack's `.env`, not ours)

`ROBOTICS_PROJECT` (microduck_rl or microduck-nav), `ROBOTICS_TRAIN_ENTRY` (`train`), `ROBOTICS_TASK`, `ROBOTICS_NUM_ENVS` (4096), `ROBOTICS_LOGGER` (tensorboard),
`ROBOTICS_TRAIN_ARGS` (our args), `ROBOTICS_MAX_RUNTIME` (GNU `timeout` syntax), `ROBOTICS_MEM_LIMIT` (64g), `MICRODUCK_WALKER_ONNX` (microduck-nav only).
microduck-nav has no reviewed pin yet: `prepare.sh microduck-nav <REF>` needs the commit, which is why the request carries it.

## Measured on the first run (2026-11-13, microduck_rl)

Swap in 1 min; first `uv sync` 1 m 45 s; torch `2.9.1+cu129`; 2.78 s per iteration at 4096 envs (100 iterations in about 5 min); the trainer used 5.1 GB of
GPU memory; swap back 6 m 18 s. A full 4000-iteration run was 3 h 5 min, in a window of about 3 h 45 min with the swaps.

## M1 in numbers

Task `Mjlab-Nav-OneWall-MicroDuck`; smoke 64 envs x 20 iterations (`--agent.save-interval 10`); run 4096 envs x 200 iterations (`--agent.save-interval 50`):
checkpoints at 0, 50, 100, 150 and `model_199.pt`, each with a `model_N.onnx` of shape `(1, 1343) -> (1, 3)`. On a machine with no GPU add `--gpu-ids None`.

## Found wrong or inconsistent while writing the skill

- The recipe says be back in prod by 23:30Z; the operator's instruction for this skill is 23:20Z. The preflight uses 23:20Z.
- The recipe and M1 spell the trainer flags both ways (`--agent.save_interval` and `--agent.save-interval`, `--agent.max_iterations` and `--agent.max-iterations`).
  The preflight accepts both and warns about neither; whether the trainer's parser accepts both is not verified here.
- The recipe's first full-run example uses the microduck_rl task; microduck-nav's tasks are `Mjlab-Nav-MicroDuck` and `Mjlab-Nav-OneWall-MicroDuck`.
