# RFC-0001 — The NXT web UI: drive, watch, record and run programs from a browser

**Status:** Proposed — describes what was built and checked on the robot on 2026-11-13/14, for the
operator's review. On acceptance it becomes an ADR; the open questions in §7 become follow-ups.
**Builds on:** [IDEAS.md](../wip/IDEAS.md) (the NXT as the first robot project),
[ECOSYSTEM.md](../wip/ECOSYSTEM.md) (one interface per robot).
**Code:** [`nxt/`](https://github.com/chipi/robotics-lab/tree/main/nxt), served by `uv run nxt-web`.

## 1. Motivation

The operator has a LEGO Mindstorms NXT 2.0 (stock firmware 1.28) built as a tracked
Shooterbot, and wants to drive it from their own software, see what its sensors see, log
data, and put programs on the brick that run on their own. LEGO's own NXT-G software is
Windows/Mac only and was never part of the plan. The UI is the first piece of the robotics
lab: the place where a person and the robot meet before any automation is trusted.

## 2. Goals and non-goals

Goals:

- drive the robot by hand, from a desktop or a phone, safely;
- live sensor and motor readings, charts, and recordings to CSV;
- manage programs on the brick: upload, run, stop, read the logs they write;
- configure which port does what, without editing code;
- show how the robot is connected and whether the link is healthy;
- keep a log of every command sent.

Non-goals (v1):

- autonomy — that is the robot brain ([RFC-0002](RFC-0002-robot-brain.md));
- several robots, or several users at once;
- access beyond the local machine (it binds `127.0.0.1`; see §7);
- replacing the brick's firmware.

## 3. Proposal (as built)

### 3.1 Shape

- **Server:** Python standard library only (`http.server`, threads); no web framework and no new
  runtime dependency beyond [nxt-python](https://github.com/schodet/nxt-python) 3.5.1.
- **Page:** one HTML file, no build step, no outside libraries; the chart is drawn on a canvas.
  Light and dark themes; works at phone width.
- **Robot backends:** `NxtRobot` (the real brick) and `FakeRobot` (a simulated brick with made-up
  readings, `--fake`), behind the same methods, so everything above them is tested without
  hardware.

### 3.2 Tabs

| Tab | What it does |
| --- | --- |
| Drive | Hold-to-drive pad (arrows / WASD), power slider, fire, live motor readout |
| Sensors & log | Live readings, chart (pick series, time window), recording to `runs/*.csv`, re-plot or download runs, the command log |
| Programs | Files on the brick and free space; upload, run, stop, view or plot a CSV a program wrote, download, delete |
| Setup | Connection & diagnostics; which port is left/right/shooter, inverting a side, which sensor on each port, samples per second (saved to `config.json`) |

**STOP ALL** in the header stops the drive motors and any program on the brick.

### 3.3 Safety

The NXT's stock firmware has **no deadman**: a motor keeps its last command. So:

1. **Hold-to-drive with a watchdog.** The page resends the drive command every 200 ms while a
   direction is held; the server stops the motors when none has arrived for 0.6 s (tab closed,
   connection lost, button released without a stop).
2. **Stopping the server stops the motors** — on Ctrl-C and on SIGTERM. SIGTERM was added after
   incident 1 (§6) and checked on the brick: drive at power 30, SIGTERM within 0.2 s, all three
   motors idle.
3. **A program on the brick has the robot.** While one runs, driving and fire are refused, and the
   server stops reading sensors (reading can change a sensor's mode under the program); motor
   counters are still logged.
4. **Power is clamped** to ±100 and upload names are checked against the brick's file-name rules.

What it cannot cover: a hard crash of the server, or a lost link, leaves the motors running. That
needs a deadman on the brick itself ([RFC-0003](RFC-0003-robot-interface.md) §4).

### 3.4 Data

- **Live:** a sampler reads motors and sensors at the configured rate into a ring buffer the page
  polls.
- **Recording:** each sample to `nxt/runs/run-<date>-<time>.csv` (not committed): time, motor
  powers, three tacho counts, one column per configured sensor, the running program.
- **Command log:** every command with time and details — drive changes (one entry when a
  direction is held, not one per keepalive), stops, watchdog stops, fire, programs, uploads,
  setup changes, connects and lost links, failures marked — shown in the UI and appended to
  `nxt/runs/events.jsonl` (`events-fake.jsonl` for the simulated brick).

### 3.5 Links and diagnostics

- **Links:** USB, or Bluetooth through `/dev/rfcomm*` (nxt-python's device-file backend). `auto`
  tries USB first; the Setup tab switches link (stopping the motors first).
- **Header:** current link and median command time next to the battery.
- **Diagnostics:** firmware, command times (median, 90 %, max) and errors, actual vs configured
  sample rate, time connected, whether the NXT is on USB, the rfcomm binding and its pairing and
  connection state, and a link speed test.

### 3.6 Programs on the brick

NXC programs are compiled by Debian's `nbc` in Docker (`nxt/toolchain/`, `scripts/nxc.sh`) and
uploaded from the Programs tab. `first` (drive and log) ran and logged correctly; `chase` and
`patrol` (dog games) are compiled, not yet run. Programs run with no link at all; a link is only
needed to upload and to read their logs.

## 4. How it was checked

- **Smoke test** against the simulated brick: every endpoint, the watchdog, clamping, recording,
  path-traversal refusal, programs, the command log, diagnostics, and SIGTERM taking the stop path
  (that check fails on the code before the fix). It skips its real-hardware checks whenever a
  brick may be reachable (USB or any `/dev/rfcomm*`).
- **On the robot (2026-11-14):** each motor turned and identified (A shooter, B right, C left,
  positive power forward), sensors read (colour on 3, ultrasonic on 4, which reports "Sonar"), the
  operator drove and recorded over USB, then over Bluetooth; `first.rxe` ran and its log was read
  back; diagnostics and the link test checked over Bluetooth.
- Measured: about 41 ms per command over Bluetooth with nothing else running; about 170–190 ms
  median while live sampling shares the link; the sampler reaches 1.96 of 2 samples/s over
  Bluetooth.

## 5. Alternatives considered

- **A web framework (FastAPI, Flask) with WebSockets:** smoother live updates, but new
  dependencies; polling at 300 ms is enough at these rates.
- **nxt-python's own `nxt-server`:** a byte pipe to the brick, no UI; kept in mind as the protocol
  for a Wi-Fi bridge ([RFC-0003](RFC-0003-robot-interface.md)).
- **Replacing the firmware (leJOS):** more capable programs on the brick, but a reflash; rejected
  for now, NXC on the stock firmware covers what is needed.
- **A desktop app:** no phone access; rejected.

## 6. Incidents (2026-11-14)

1. The smoke test's "no brick" section ran against the plugged-in brick and left both tracks at
   power 50 after the server was killed (about a minute; the robot was lifted). Fixed: SIGTERM
   stops the motors; the test skips real-hardware checks when a brick is reachable.
2. With USB unplugged, the same section reached the brick over Bluetooth; its second connection
   hung the live server. Motors were idle. Fixed in the test; the limit underneath is open (§7).

## 7. Open questions

1. **A deadman on the brick** — the only fix for a crashed server or a lost link
   ([RFC-0003](RFC-0003-robot-interface.md) §4).
2. **One connection at a time.** A second program on the same link scrambles replies, and
   Bluetooth reads have no timeout, so a stalled link hangs the server and its watchdog. Needs a
   read timeout and, ideally, the NXT service as the only owner of the link.
3. **Access from other devices.** Today: an ssh tunnel over the tailnet. Opening the port needs a
   firewall rule and, before that, some form of login — the UI can drive a robot.
4. **The JSON-RPC interface** of [RFC-0003](RFC-0003-robot-interface.md): the UI would become one
   client of it rather than having its own HTTP API.
5. **More sensors and motors** (multiplexers, a second brick; [NXT-PARTS.md](../wip/NXT-PARTS.md)):
   the Setup tab offers LEGO's six sensor types only.

## 8. Discussion

- 2026-11-13 — First version (drive pad, watchdog) asked for by the operator; extended to the four
  tabs, recording and programs; NXC toolchain in Docker chosen by the operator over an AUR install.
- 2026-11-14 — First run on the robot over USB; ports checked; incident 1 and the SIGTERM fix;
  Bluetooth paired and used; the operator asked for the link next to the battery, diagnostics, and
  a command log; incident 2. The operator asked for this RFC.
