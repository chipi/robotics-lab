# Running the simulated duck from an agent

Pollen's `scripts/duck-sim` (in `/work/pollen/microduck`, pinned at `094d4bb4`) is written for a
person at a terminal. Driven by an agent or a script, from a process with no terminal, two of its
habits change meaning. This page is how robotics-lab runs it unattended: the challenge runner
(`duck-challenge`), the explorers and the probes all go through `duck_lab.nav.simreset`.

## Why: the sudo lockout (2026-11-16)

Every `duck-sim down`, the plain one included, first runs `down_containers`. That asks
`sudo systemctl is-active` about sixteen container units (`duck-a` … `duck-p`). For a person,
that is at most one password prompt. From a process with no terminal, sudo has nowhere to ask:
each of the sixteen asks is a failed password conversation (`pam_unix(sudo:auth): conversation
failed` in the journal). The machine's PAM counts failures with `pam_faillock` (`deny=10
unlock_time=120` in `/etc/pam.d/system-auth`), so ten failures lock the user's sudo for two
minutes.

The challenge runs stop the simulator every ~70 s, so the operator's sudo stayed locked for as
long as they ran. A correct password typed at the time was refused ("Sorry, try again"), which
looked like a forgotten password. `su marko -c true` accepted the same password, because `su`
fell between the lockouts.

The `duck-ether` stop in plain `down` uses `sudo -n`, which fails without asking and is not
counted. Only `down_containers` locks.

## The rule

**An agent never runs a command that can make sudo ask with no terminal.** In `duck-sim` that
means:

- Use only `up`, `down`, `drive`, `status`, `ctl` and `stand`, with the patch below applied.
- Never `boot`, `rootfs` or `shell`. These need sudo by design (`systemd-nspawn`, mounts) and
  are a person's commands.

## The patch (a local change, not sent upstream)

[`duck/sim/patches/duck-sim-sudo-free-down.patch`](https://github.com/chipi/robotics-lab/blob/main/duck/sim/patches/duck-sim-sudo-free-down.patch)
drops `sudo` from the `is-active` check. Asking whether a unit runs needs no root. The
`stop` and `umount` that follow are reached only when a container really runs, and still prompt
a person as before. On this machine no `duck-*` unit exists, so they are never reached.

```bash
cd /work/pollen/microduck
git apply /work/robotics-lab/main/duck/sim/patches/duck-sim-sudo-free-down.patch          # apply
git apply --reverse --check /work/robotics-lab/main/duck/sim/patches/duck-sim-sudo-free-down.patch && echo applied
```

Re-apply it after any update or reset of the Pollen checkout. The operator decided on
2026-11-16 to keep it local: for a person, upstream's line is right.

## The guards

- **`simreset.duck_sim()`** refuses to run a `duck-sim` that still has the sudo check, and names
  the patch. Every runner fails at its first reset instead of locking the user out.
  `tests/test_challenge.py` checks it both ways.
- **`duck/sim/probes/sudo_free_down.py`** runs one real `down` through `simreset` and fails if the
  user's faillock tally was written during it. It also prints the tally's records (time,
  service or terminal), which is how a lockout is read without root. Run it with no simulator
  in use: it stops the simulator.

## When sudo says "Sorry, try again"

1. Read the tally: `uv run python sim/probes/sudo_free_down.py` (in `duck/`, nothing running),
   or the record file `/run/faillock/<user>` directly. Many entries seconds apart, whose source
   is the service `sudo` rather than a terminal, mean a script is failing sudo. The operator's
   own attempts carry a terminal (`/dev/pts/N`).
2. Find the caller: list running `sudo` processes with their parents (`ps -o pid,ppid,args`)
   while the failures arrive.
3. Stop it, wait two minutes (`unlock_time=120`), then try once.
