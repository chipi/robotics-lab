---
name: sim-run
description: Run a job on the simulated duck (Pollen's duck-sim) without locking the operator out of sudo and without two jobs corrupting each other. Preflight (lock, host, patch, installation), start under scripts/sim-lock, use only duck-sim up/down/drive/status/ctl/stand, check the real-time factor and the truth. Use when asked to "run the simulator", "run sim-duck / sim-nxt / a challenge / an explore", "start the sim", "is the sim free", "why is my sudo locked", or before any command that resets the simulator. Do not use to read a finished run (use robotics-run-read) or to run a scored batch (use challenge-batch, which builds on this).
metadata:
  permissions:
    read: [scripts/sim-lock, docs/wip/DUCK-SIM-FOR-AGENTS.md, "~/.config/robotics-lab/host.json", "/proc"]
    write: ["a scratch installation file and scratch data folder outside the repo"]
    execute: [scripts/preflight.py, scripts/sim-lock]
---

# sim-run

## The rule (docs/wip/DUCK-SIM-FOR-AGENTS.md, "The rule")

**An agent never runs a command that can make sudo ask with no terminal.** Of `duck-sim`, use only `up`, `down`, `drive`, `status`, `ctl`
and `stand`, with the sudo-free patch applied. Never `boot`, `rootfs` or `shell`: they need sudo by design and are a person's commands.
Why: on 2026-11-16 every `down` asked sudo sixteen times with no terminal, `pam_faillock` (10 failures, 120 s) locked the operator's
sudo for as long as the challenge runs lasted, and a correct password read as "Sorry, try again".

## Preflight

```bash
.claude/skills/sim-run/scripts/preflight.py          # read only; READY exit 0, NOT READY 1, BUSY 3
```

| Line | Means | If not |
| --- | --- | --- |
| `lock` FAIL, held | another job (a person's or an agent's) has the simulator | wait; never start a second job, never delete the lock file |
| `duck-sim sudo patch` FAIL | unpatched `duck-sim` still asks sudo | stop; the operator applies `robots/duck/sim/patches/duck-sim-sudo-free-down.patch` (`scripts/host-setup` does it) |
| `host file` FAIL | no host file, or it names no Pollen checkout | `simhost show`, `scripts/host-check`; ask |
| `installation` WARN | `ROBOTICS_LAB_INSTALLATION` unset, or it is the operator's file or shares its data/index | write a scratch installation (below) and set the variable |
| `simulator` INFO up | a simulator is running | with a free lock it is a leftover or a hand session: ask before a job resets it |

The preflight is evidence, not a verdict: READY says the lock is free and the files are in order, not that the simulator will start.

## Run

1. Scratch installation, outside the repo (`docs/wip/NXT-SIM.md`, "A test installation file"): a JSON file with `installation: 1`, a scratch
   `data`, `index` and `state`, and the `robots` the job needs. **Never edit `~/.config/robotics-lab/installation.json`.**
   `export ROBOTICS_LAB_INSTALLATION=<scratch file>`.
2. One job, under the lock, in the foreground with an exit line (`long-job` for anything over a few minutes):
   `scripts/sim-lock -- <command>` (or `make sim-duck` and the other `sim-*` targets, which take the lock themselves; do not wrap those in `flock`).
   `sim-lock` exits 75 when the lock was not free in its timeout (default 7200 s) and the command did not run.
3. Watch it live; on the first failure read the log and diagnose while the rest runs.

## Success: signals that must agree

1. The job's own exit status, ending `EXIT=0` in your log.
2. `result.json` `clock.rtf` at least 0.95 (`RTF_LOW`); under it the run has `pass: null` and `no_verdict: rtf_low` and is not a result.
3. `truth_copy.unpaired` 0 and `judge_truth.available` true (`robotics-run-read`).
4. No sudo prompt or `pam_unix(sudo:auth)` failure appeared in the journal during the job.
5. The lock is free again afterwards (`preflight.py`: `lock ... is free`).

`status` answering, or a pass line alone, is not proof the run was sound.

## Never

- `duck-sim boot|rootfs|shell`, any `sudo`, or `sudo -n` probing from a job.
- A second simulator job while the lock is held; `rm` on the lock file; wrapping a `make sim-*` target in `flock`.
- Edit the operator's installation file or host file; run a job against the default installation by accident.
- Start the simulator "to look" in a session that was asked only to read. Real hardware and the real robot are not this skill.

## When sudo says "Sorry, try again"

Stop every job, then follow the last section of `docs/wip/DUCK-SIM-FOR-AGENTS.md`: read the faillock tally, find the caller with `ps -o pid,ppid,args`,
wait the 2 minutes, try once. Do not retry in a loop.

## Not covered

The real-time factor check before a run (the host check measures it with the simulator up), macOS hosts, the NXT simulator's details,
Rerun and Lichtblick. `references/sim-host.md` has the files and commands.
