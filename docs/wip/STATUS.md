# Status and open decisions

**Superseded (2026-11-21): this page is where things stood on 2026-11-14 and is kept as that
record; it is not kept up to date. Where things stand now: [the handover](HANDOVER.md), the
living status, and [the phase 5 plan](PHASE5-NEXT-PLAN.md); [how the platform fits
together](../architecture.md).**

Last updated 2026-11-14. One page to review where things stand; details live in the linked notes.

## Where things stand

| Area | State | Details |
| --- | --- | --- |
| NXT over USB | Works: info, motors, sensors, web UI, recording, programs on the brick | [apps/nxt-web/README.md](https://github.com/chipi/robotics-lab/blob/main/apps/nxt-web/README.md) |
| NXT over Bluetooth | Works: paired, `/dev/rfcomm0`, web UI drives over it | [apps/nxt-web/README.md](https://github.com/chipi/robotics-lab/blob/main/apps/nxt-web/README.md) |
| NXT ports | Checked on the robot: A shooter, B right, C left; colour 3, ultrasonic 4 | [apps/nxt-web/README.md](https://github.com/chipi/robotics-lab/blob/main/apps/nxt-web/README.md) |
| Programs on the brick | `first` ran and logged correctly; `chase` and `patrol` compiled, not yet run | [IDEAS.md](IDEAS.md) |
| NXT web UI | Drive, live sensors and charts, recording, programs, setup, link choice and diagnostics, command log | [apps/nxt-web/README.md](https://github.com/chipi/robotics-lab/blob/main/apps/nxt-web/README.md) |
| NXT safety | Motors stop on Ctrl-C / SIGTERM and 0.6 s after the last drive command; the on-brick deadman **robotd-lite is built and passes against the simulated brick, not yet checked on the real one** (RFC-0003 §2.3) | [apps/nxt-web/README.md](https://github.com/chipi/robotics-lab/blob/main/apps/nxt-web/README.md) Known issues |
| Microduck simulator | Runs here: stands, walks at 0.3 m/s asked (0.13 m/s got); turning did not match upstream | [MICRODUCK.md](MICRODUCK.md) |
| Microduck arena | Runs here: reference policy 9.392 s on the 2 m sprint | [MICRODUCK.md](MICRODUCK.md) |
| DGX training | `robotics` GPU mode exists; first measured run done (no usable policy kept); full run planned | [MICRODUCK.md](MICRODUCK.md) |
| Brain models | Live: `robot-vlm`, `robot-planner` (Qwen3-VL-30B-A3B), `robot-vlm-gemma` (Gemma 4 26B-A4B), $10/30 days | [RFC-0004](../rfc/RFC-0004-perception-and-planning.md) |
| Robot brain | Designed, revision 2 after an independent review; not built; phase 0 done 2026-11-14 ([PHASE0-SPIKE.md](PHASE0-SPIKE.md)): turning's bar changed to repeatable turning with a compensating navigator (operator) | [RFC-0002](../rfc/RFC-0002-robot-brain.md), [review](REVIEW-2026-11-14-duck-rfcs.md) |
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

- 2026-11-14 (vision, [RFC-0007](../rfc/RFC-0007-platform.md)): the operator's tools plus a few
  open-source projects and a few new ones form one platform covering command, record and store, see,
  judge and govern — an open, local-first alternative to Foxglove.
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

- Robot brain phase 1: done — run 8, and again run 15 after phase 2's changes: 20 of 20, no
  contacts, no falls ([PHASE1-RESULTS.md](PHASE1-RESULTS.md)).
- Phase 2, exploring: in progress, bar not met — trials 7 and 8 trap the duck within 2 minutes
  ([PHASE2-RESULTS.md](PHASE2-RESULTS.md)). Next: the world model in the viewer.
- The NXT on-brick deadman ("robotd-lite"): built (RFC-0003 §2.3, "As built"); check it on the
  brick with `make test-hardware`, which now uploads and tests it (`hw_deadman.py`).
- At home: chase and patrol on the floor; touch sensors as bumpers.
