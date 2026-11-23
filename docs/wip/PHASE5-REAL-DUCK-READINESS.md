# The real duck's readiness

**Status:** running notes, 2026-11-23. This is the sweep the operator asked for: "which of these
things make sense to do also before telemetry ... to work with a real duck when it would arrive".
A read-only sweep covered every RFC, the architecture review and the work-in-progress notes. It
ran no code. Each item gives its verdict on whether the first real-duck goal needs it. The plan's
item 4b holds the scope; this file holds the evidence. The measurements to take on the robot are
in [when the real duck arrives](REAL-DUCK.md).

## The scope the operator set (plan item 4b), with the sweep's verdict

| Item | Source | Verdict | Why |
| --- | --- | --- | --- |
| The real duck's adapter and safety review | RFC-0014 step 8 | Required | `make_adapter` knows only the fake robot, the simulated duck and nxt-web (`apps/mission-control` `robots.py`) |
| The real duck's gate, with the watch for other doors | RFC-0017 §3.8, RFC-0002 §3.6 | Required | The gate runs on the navigator's computer; the watch for other doors (`move.source`, `autonomous`) exists only in comments |
| Relocalisation from landmarks | RFC-0014 step 10 | Strongly helps | With no truth, landmarks are the only absolute fix; a single room driven by hand can do without |
| A real camera recogniser | RFC-0014 step 11, RFC-0016 | Required for object goals only | The navigator refuses `go_to_object` and `inventory` without a camera; point goals work |
| Calibration as step guides | RFC-0023 step 4 | Strongly helps | `variants.real` is `{}` in `robots/duck/profile.json`; the base numbers are marked "not measured" |

## Found by the sweep

All seven were taken into item 4b's scope (the operator, 2026-11-23).

1. **No robot-side replacement for the truth guardrails** (fall, contact, drop clearance).
   - In the simulator they are judged only by the truth (`robots/duck/src/duck_lab/nav/guardrails.py`).
   - The profile still lists them as capabilities.
   - The navigator reads the IMU but only records its tilt.
   - mapd's `bumped` and `carried` reasons are recorded, not acted on.
   - Item 4 makes them "not enforced" and warns; nothing enforces them on the robot.
2. **Nothing stops the duck on its own health.** Over-temperature, low battery and an unhealthy
   verdict raise anomalies only. A stale state or depth stream raises `thread_failed` only. The
   0.5 s deadman is the only backstop. Not verified: whether the control loop stops.
3. **No link tooling.**
   - Nothing opens or checks the ssh-forwarded sockets.
   - There is no reconnect or back-off.
   - The ssh window the face button opens lasts 30 minutes (RFC-0002 §3.3), so it can expire
     mid-session.
   - No test covers a dead tunnel.
4. **No start pose for a real room.** The site frame assumes the robot starts at the dock
   (RFC-0014 §3.5). Nothing sets or checks the start without truth.
5. **mapd's CPU cost on the board** and a score sheet comparing the simulator with the real duck
   (RFC-0002, phase 5).
6. **A simulator-first flag for real runs** (RFC-0014 step 5): rehearse a goal in the simulator
   before the robot runs it. Mission Control has it since 2026-11-23 (unit B8): a goal's `sim_first`.
7. **mapd's sensor model** (K34): it assumes an axial depth sensor, while the simulator's is
   radial. Measured on the robot first (REAL-DUCK.md §2).

## Can wait for the real duck

- RFC-0012 steps 3 and 4 (look triggers, vertical look).
- RFC-0019's derived index (the found anomalies).
- Telemetry and retention.
- `go_to_area` on the operator's outlines; the Observatory rename; flotilla.
- VLM room typing and missions in words.

## Not for the duck

- The EV3; the NXT's hardware checks.
- The Nav2 comparison (RFC-0015, parked).
- A second simulator; the TurtleBot3 (plan item 6).

## Not covered by the sweep

- It ran no code.
- It read RFC-0004 to RFC-0008 and the review files only as far as their status lines.
- RFC-0002 to RFC-0007 still say "Proposed", though parts were taken into RFC-0014 and RFC-0021.
  Those status lines are stale, and no one has audited them paragraph by paragraph.
- Not verified: whether the gate notices a dead ssh socket.
