# RFC-0003 — One robot interface: JSON-RPC for every robot, and a deadman on the NXT

**Status:** Proposed (2026-11-14). Direction agreed by the operator ("align the next LEGO on one
JSON-RPC interface for everything"); where the NXT's interface lives is the operator's decision
once the current pieces work.
**Builds on:** [RFC-0001](RFC-0001-nxt-web-ui.md), [RFC-0002](RFC-0002-robot-brain.md),
[IDEAS.md](../wip/IDEAS.md) ("Wireless NXT").

## 1. Motivation

The robot brain ([RFC-0002](RFC-0002-robot-brain.md)) should drive any robot in the lab the same
way. The Microduck already has a well-designed interface: every client — app, gamepad, `robotctl`,
scripts — sends the same JSON-RPC calls to its daemons. The NXT has an HTTP API invented for its
web UI ([RFC-0001](RFC-0001-nxt-web-ui.md)). Two interfaces mean two brains.

The NXT also has a safety gap the duck does not: its stock firmware keeps a motor's last command,
so a crashed server or a lost link leaves the motors running. Twice on 2026-11-14 our own test
code showed what that means.

## 2. Proposal

### 2.1 The interface: the duck's shape

Use the duck's contract as the reference (JSON-RPC 2.0, newline-delimited, methods by namespace),
and give the NXT the subset that makes sense, with the same names:

| Method | Duck | NXT |
| --- | --- | --- |
| `hello {client}` | names the caller | same |
| `robot.subscribe` → `robot.state` | odometry, twist, source, safety | motor powers and tachos, sensors, running program, link |
| `robot.move {vx, vyaw}` | walk | tracks (differential drive: speed and turn → left/right power) |
| `robot.stop` | stop | stop all motors |
| `robot.do {skill}` | kicks, roll, emotions | fire, run an on-brick program |
| `robot.health` | battery, temperatures | battery, firmware, link, free flash |
| `tof.frame` / sensors | 8×8 depth | ultrasonic, colour (as their own stream) |

The web UI then becomes one client of this interface instead of having its own API.

### 2.2 Where the NXT's interface lives

Two layers: the **interface** (above) and the **link to the brick** (LEGO's direct commands over
USB, PC Bluetooth, or a Wi-Fi bridge).

```text
robot brain / web UI
   │  JSON-RPC (2.1)
   ▼
NXT service (Python; today's nxt-web grown up)      on the PC, or a Pi later
   │  LEGO direct commands
   ├─ USB
   ├─ PC Bluetooth (/dev/rfcomm*)
   └─ ESP32 bridge: Wi-Fi ↔ Bluetooth, a byte pipe
   ▼
NXT brick  +  robotd-lite (2.3)
```

- **Proposed:** the JSON-RPC interface in the Python NXT service. The ESP32, when added for
  house-wide range, is a dumb byte bridge speaking nxt-python's existing `nxt-server` protocol
  (`0x98` asks the link type, `0x99` closes, anything else is forwarded to the brick and the reply
  returned), so nothing above it changes.
- **Alternative:** the JSON-RPC interface on the ESP32 itself — a self-contained Wi-Fi robot with
  no PC, at the cost of C++ firmware for every change. Revisit if the NXT must work with no
  computer at all.

ESP32 choice: it must be an **original ESP32** (classic Bluetooth); S2, S3, C3 and C6 have
Bluetooth LE only. An off-the-shelf candidate: M5Stack Atom Lite (ESP32-PICO-D4; Espressif's
datasheet: "Bluetooth v4.2 BR/EDR and Bluetooth LE"; marked not recommended for new designs).

### 2.3 robotd-lite: a deadman on the brick

A small NXC program running on the brick:

- receives move commands through the brick's message boxes (sent by the NXT service over USB or
  Bluetooth with LEGO's `message_write`);
- drives the motors from them;
- **stops the motors when no command arrives for 0.5 s** — the duck's deadman, on the NXT;
- stops on the ultrasonic sensor locally (a minimum distance), and on a bumper when touch sensors
  are fitted;
- reports state back through a message box.

With it, a crashed server, a hung link or a dropped Bluetooth connection stops the robot within
half a second, whatever the link.

## 3. Non-goals

- Re-implementing the duck's interface in full on the NXT; only what the brain needs.
- Changing the duck's interface.
- Several clients driving at once (the duck has no arbitration either; one driver at a time).

## 4. Open questions

1. **Where the interface lives** (2.2) — the operator decides once the current pieces work.
2. **Transport of the interface** for remote clients: TCP or WebSocket, and authentication, before
   anything listens beyond localhost.
3. **Message-box throughput** on the NXT for robotd-lite: a move command every 100–200 ms over
   Bluetooth at about 41 ms per command must fit with the state reads. To measure.
4. **Name mapping for state:** how close `robot.state` for the NXT should be to the duck's, so a
   brain can treat both as "a robot" without special cases.

## 5. Alternatives considered

- **Keep the NXT's own HTTP API** and teach the brain two interfaces: rejected, two brains.
- **A new interface designed for both:** rejected for now; the duck's is designed, documented and
  in use, and we do not own it.
- **Deadman in the NXT service only:** cannot help when the service or the link is what failed.
- **Replacing the NXT firmware** to get a deadman (leJOS): a reflash; NXC on the stock firmware
  does it.

## 6. Discussion

- 2026-11-14 — Operator: "good idea to align next LEGO on one JSON-RPC interface for everything";
  asked whether the ESP32 would carry the JSON-RPC; the two layers explained; the decision is
  deferred until the current pieces work.
- 2026-11-14 — Incidents 1 and 2 of [RFC-0001](RFC-0001-nxt-web-ui.md) §6 moved the on-brick
  deadman up the list.
