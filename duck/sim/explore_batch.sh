#!/usr/bin/env bash
# One exploration batch (docs/wip/EXPLORE-PROGRESS.md): K runs from the dock, each after a simulator reset (fresh mapd),
# each a miniview run. Usage: sim/explore_batch.sh BATCH K [MINUTES]   e.g. sim/explore_batch.sh b1 2 20
# FIRST=n numbers the runs from n (a batch that already has runs). ARGS="..." passes options to duck-explore (e.g.
# ARGS=--object-costs). Prints one "RUN <name> EXIT=<code>" line per run, then "BATCH <name> DONE".
set -u
batch=$1 k=$2 minutes=${3:-20}
cd "$(dirname "$0")/.."
for i in $(seq 1 "$k"); do
  name="explore-$batch-r$((i + ${FIRST:-1} - 1))"
  .venv/bin/python sim/reset_sim.py || { echo "RUN $name RESET FAILED"; exit 1; }
  # shellcheck disable=SC2086 # ARGS is a list of options, split on purpose
  .venv/bin/duck-explore --minutes "$minutes" --out "runs/$name" --miniview-data /work/robotics-lab/data ${ARGS:-}
  echo "RUN $name EXIT=$?"
done
echo "BATCH $batch DONE"
