# Status and open decisions

Last updated 2026-11-14. One page to review where things stand; details live in the linked notes.

## Where things stand

| Area | State | Details |
| --- | --- | --- |
| NXT over USB | Works: info, motors, sensors, web UI, recording, programs on the brick | [nxt/README.md](https://github.com/chipi/robotics-lab/blob/main/nxt/README.md) |
| NXT over Bluetooth | Works: paired, `/dev/rfcomm0`, web UI drives over it | [nxt/README.md](https://github.com/chipi/robotics-lab/blob/main/nxt/README.md) |
| NXT ports | Checked on the robot: A shooter, B right, C left; colour 3, ultrasonic 4 | [nxt/README.md](https://github.com/chipi/robotics-lab/blob/main/nxt/README.md) |
| Programs on the brick | `first` ran and logged correctly; `chase` and `patrol` compiled, not yet run | [IDEAS.md](IDEAS.md) |
| NXT web UI | Drive, live sensors and charts, recording, programs, setup, link choice and diagnostics, command log | [nxt/README.md](https://github.com/chipi/robotics-lab/blob/main/nxt/README.md) |
| NXT safety | Motors stop on Ctrl-C / SIGTERM and 0.6 s after the last drive command; **no deadman on the brick yet** | [nxt/README.md](https://github.com/chipi/robotics-lab/blob/main/nxt/README.md) Known issues |
| Microduck simulator | Runs here: stands, walks at 0.3 m/s asked (0.13 m/s got); turning did not match upstream | [MICRODUCK.md](MICRODUCK.md) |
| Microduck arena | Runs here: reference policy 9.392 s on the 2 m sprint | [MICRODUCK.md](MICRODUCK.md) |
| DGX training | `robotics` GPU mode exists; first measured run done (no usable policy kept); full run planned | [MICRODUCK.md](MICRODUCK.md) |
| Brain models | Live: `robot-vlm`, `robot-planner` (Qwen3-VL-30B-A3B), `robot-vlm-gemma` (Gemma 4 26B-A4B), $10/30 days | [RFC-0004](../rfc/RFC-0004-perception-and-planning.md) |
| Robot brain | Designed, revision 2 after an independent review; not built; phase 0 (a spike: is the simulator a usable stand-in?) approved | [RFC-0002](../rfc/RFC-0002-robot-brain.md), [review](REVIEW-2026-11-14-duck-rfcs.md) |
| eval-harness / flotilla for robots | The mission loop agreed: the simulated duck is a second host at `auto`, every mission rehearses there first | [RFC-0005](../rfc/RFC-0005-missions.md) |

## Incidents (2026-11-14, both caused by our own test, both fixed)

1. The web smoke test's "no brick" section ran against the plugged-in NXT and left both tracks at
   power 50 after the server was killed (about a minute, robot lifted). Fixed: SIGTERM stops the
   motors (checked on the brick); the test skips real-hardware checks when a brick is reachable.
2. With USB unplugged, the same section reached the brick over Bluetooth, and its second
   connection hung the live UI server. Motors were idle. Fixed in the test; the underlying limit
   (one connection at a time, no read timeout) is a known issue.

## Open decisions (operator)

1. **DGX full training run:** daytime is fine (operator, 2026-11-14: prod only matters at night);
   which day and hour is open (back in prod by 23:30 UTC).
2. **Where the NXT's JSON-RPC lives:** Python service + dumb ESP32 bridge (proposed) or JSON-RPC
   on the ESP32 — after things work. See [IDEAS.md](IDEAS.md), "Wireless NXT".
3. **Robot-brain model budget:** $10 / 30 days now; the operator's direction is "whatever we need";
   raise when needed (via a homelab session).
4. **What to buy** for bigger NXT robots / the arm robot: [NXT-PARTS.md](NXT-PARTS.md).
5. **Homelab pushes** waiting for the operator's go in that session: `ed61aab` (brain key and
   aliases), `d3f82e3` (the Gemma alias).
6. **A computer on board the NXT:** a Raspberry Pi on the brick (recommended first), an ESP32, or
   a BrickPi3 replacing the brick — [NXT-PARTS.md](NXT-PARTS.md).

## Decided

- [ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md) (2026-11-14): ROS 2 not the foundation now;
  terms and data shapes aligned with ROS; Foxglove (MCAP run records, live streaming) from the start.
- 2026-11-14: the navigator moves onto the robot mid-term; the brain oversees several missions;
  robots working together is a later phase ([RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.10).
- 2026-11-14: the brain's UI from the start is a mission control page, an MCP server and a Slack
  app; everything robot-specific goes into mission control, a future open-source product; the line
  to Foxglove, eval-harness and flotilla in [RFC-0006](../rfc/RFC-0006-mission-control.md).
- 2026-11-14: NXT stops its motors on every connect; the shooter is off unless enabled
  ([RFC-0001](../rfc/RFC-0001-nxt-web-ui.md) §3.3).

## Next (full order: [roadmap](ROADMAP.md))

- Robot brain phase 0, the spike: turning in the backlash scene, the backlash robot in the
  apartment, `mapd` mapping with autonomy off.
- The NXT on-brick deadman ("robotd-lite"), with the coexistence rule of RFC-0003 §2.4: write and
  compile; test on the brick at home, with `make test-hardware` (now including stop on connect).
- At home: chase and patrol on the floor; touch sensors as bumpers.
