# Bringing up the link to the real duck

**Status:** written 2026-11-23 for plan unit B5 (the link tooling). The tool is proven against
stand-ins only; no ssh was run and no robot reached. Where a step says "not verified", it is the
first thing to watch on the real duck. For what to measure once the link is up, see
[the real duck's notes](REAL-DUCK.md).

## What it does

The duck's daemons listen on Unix sockets that exist only on the duck (RFC-0002 §3.3). One ssh
session carries three of them to this workstation. `lab-link` (in `libs/runner`) opens that
session, asks each socket a read-only question to prove the robot's end answers, and starts the
session again, with growing waits, when it dies. It runs on the workstation only.

| Name | On the duck | On the workstation | Asked |
| --- | --- | --- | --- |
| robot | `/run/robotd.sock` | `~/.cache/duck-real/duck.sock` | `robot.health` |
| depth | `/run/tofd/tof.sock` | `~/.cache/duck-real/duck-tof.sock` | `tof.stream` |
| map | `/run/mapd/map.sock` | `~/.cache/duck-real/duck-map.sock` | `map.status` |

The gate is not forwarded. It runs here (RFC-0017 §3.8) and reads the `robot` socket above as its
upstream. The folder is not the simulator's (`~/.cache/duck-sim`), so a simulator socket never
answers for the real duck.

## Steps

1. Open the duck's ssh. It lasts 30 minutes from the face button, until reboot over USB, or stays
   open on the developer image (RFC-0002 §3.3). Confirm `ssh microduck@duck` works by hand first,
   with a key, no password: the link runs with `BatchMode`, so a prompt is a failure.
   The address `microduck@duck` is the one the RFC uses; use the real one.
2. See the command without running anything:

   ```bash
   cd libs/runner && uv run lab-link up --host microduck@duck --dry-run
   ```

3. Bring the link up and leave it running in its own terminal:

   ```bash
   cd libs/runner && uv run lab-link up --host microduck@duck --gate ~/.cache/duck-real/duck-gate.sock
   ```

   It prints `up: robot, depth, map` when all three answer. When ssh exits (the window closed, Wi-Fi
   dropped) it prints why and retries after 1, 2, 4 ... 30 seconds. After the window closes, press
   the face button again; the next retry picks it up. Ctrl-C ends the session and the tool.
4. From another terminal, ask once whether it is alive:

   ```bash
   cd libs/runner && uv run lab-link check --host microduck@duck --gate ~/.cache/duck-real/duck-gate.sock
   ```

   Each socket gets one line, then `link PASS` (exit 0) or `link FAIL` (exit 1). The words after a
   `DEAD` name the cause: no socket file (ssh not up), nothing listens (a stale file, ssh gone),
   closed (ssh is up but the robot's end hangs up), silent (no answer in 2 s).
5. Start the gate on the forwarded robot socket and name it in the installation file
   (`robots.duck.gate`, with `variant` `real`):

   ```bash
   cd libs/runner && uv run lab-gate --listen ~/.cache/duck-real/duck-gate.sock \
     --upstream ~/.cache/duck-real/duck.sock
   ```

## When the link drops

- The gate does not reconnect. When the forward dies it prints "the robot's socket closed the
  connection" and exits. Start it again after `lab-link` says `up`.
- With no gate, the robot's own 0.5 s deadman is the backstop (RFC-0017). A dropped link is not a
  stop command; the gate cannot send one to a robot it can no longer reach.
- `lab-link check` says `FAIL` while ssh is down, so it is a fit pre-flight line for a run.

## Options

- Another ssh port or key: `-o Port=2222 -o IdentityFile=~/.ssh/duck`.
- Another folder or robot name: `--dir`, `--robot`.
- A robot that is not the duck: `--forward NAME=LOCAL=REMOTE=METHOD`, repeated, replaces the
  duck's three. METHOD is any read-only JSON-RPC call the remote end answers.

## Not verified

- That robotd accepts a second connection beside the gate's, which the `robot.health` check opens
  every 2 s. The simulator's does. If the real one refuses it, the check will say `DEAD` on a
  working link: change the robot's method or stop checking that socket.
- That `robot.health`, `map.status` and `tof.stream` are the real daemons' method names. They are
  what this repository's clients call on the simulator's copies.
- The ssh options' behaviour on the duck's sshd (`StreamLocalBindUnlink`, `ServerAlive*`) and how
  fast a Wi-Fi drop is seen (about 15 s by the settings, not measured).
- The camera console (`-L 8080:127.0.0.1:8080`, RFC-0002 §3.3) is not part of this tool.
