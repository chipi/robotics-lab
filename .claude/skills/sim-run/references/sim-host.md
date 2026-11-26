# The simulator host

- Host file: `$ROBOTICS_LAB_HOST` else `~/.config/robotics-lab/host.json` (`simhost show` prints it resolved). Names Pollen's `microduck` and `microduck_rl` checkouts, the duck-sim state folder (`~/.cache/duck-sim`), the body server's `truth_port` (7801).
- Pollen is pinned at `094d4bb4` (`robots/duck/sim/pollen-pins.json`). `scripts/host-check` lists what the host may carry on top (our patch to `scripts/duck-sim`, our scene file).
- `simhost.duck_sim()` refuses a `duck-sim` that still has the sudo check, so a runner fails at its first reset; the preflight reports it earlier.
- Probe: `robots/duck/sim/probes/sudo_free_down.py` stops the simulator and reads the faillock tally: run it only with the simulator unused.

## The lock

`scripts/sim-lock` is an exclusive `flock(2)` on `${ROBOTICS_LAB_SIM_LOCK}`, else `${XDG_RUNTIME_DIR:-/tmp}/robotics-lab-sim.lock`. The holder writes `pid <pid> <command>` into the file. A waiting job prints who holds it and gives up with 75 after `--timeout` / `ROBOTICS_LAB_SIM_LOCK_TIMEOUT`. A nested `sim-lock` does not wait for itself (`ROBOTICS_LAB_SIM_LOCK_HELD`). Not covered by the lock: a job that starts the simulator without `sim-lock` (`uv run lab-challenge`, a probe, `simhost reset`).

`scripts/preflight.py` reads `/proc/locks` to see a holder, so it takes nothing. `scripts/test_sim_lock.py` (`make test-sim-lock`) is the lock's own self-test and needs no simulator.

## Targets (all NOT in CI; each resets the simulator; nobody else may use it)

`make sim-duck` (~10 min), `sim-nxt` (~1 min, no Pollen), `sim-gate-scenarios` (~6 min), `sim-deployed` (~10 min); `ARGS="--only a,b"` picks scenarios.

## A scratch installation

```json
{"installation": 1, "data": "<scratch>/data", "index": "<scratch>/state/index.sqlite", "state": "<scratch>/state",
 "robots": {"duck": {"navigator": "127.0.0.1:8061", "gate": "~/.cache/duck-sim/duck-a-gate.sock",
                      "registration": "<repo>/robots/duck/registration.json"}}}
```

Unknown keys are errors (`libs/runfile/src/runfile/installation.py`). The operator's own file additionally carries `observatory` and `telemetry`; a scratch file leaves them out so a run does not send telemetry or touch the operator's Observatory.
