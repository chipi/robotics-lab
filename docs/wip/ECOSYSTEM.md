# Robotics ecosystem — long-term direction

The goal (operator, 2026-11-13): over time, build a small robotics ecosystem; play with the
LEGO NXT and the Microduck; and keep evolving eval-harness and flotilla so they support
robotic scenarios. Project ideas are in [IDEAS.md](IDEAS.md). This note is the direction,
not a plan; each step gets its own plan when it starts.

## The pieces

| Piece | Role | Exists today |
|---|---|---|
| **NXT** (`nxt/`) | Cheap, sturdy robot with simple sensors; fast loops run on the brick | Web UI, logging, NXC toolchain; never run on hardware yet |
| **Microduck** | Walking robot with camera, LiDAR, gripper; behaviours trained in simulation | Not arrived; nothing in this repo |
| **Robot service** | One small HTTP API per robot: status, actions, live telemetry, run logs | The NXT web server is the first one |
| **eval-harness** | Decides whether a behaviour or model change is really better | Exists, not connected to robots |
| **flotilla** | Decides what AI may make a robot do; approvals; timeline per case | Exists; cases, policy, host agents not built yet |
| **AI** | Perception, planning, language; runs on the PC, the duck, or the homelab | Not started |

The homelab already has an observability stack and an LLM gateway and GPU (per the
workstation rules); whether robot telemetry and models should use them is open.

## How it fits together

```
 operator ── approvals ──► flotilla (policy, cases, timeline)
                               │ signed, allowed actions
                               ▼
         ┌──────────── robot services (same small API) ────────────┐
         │  NXT: drive, turn, scan, run program   Microduck: walk, look, grab │
         └──────────────────────────────────────────────────────────┘
                               │ run logs, telemetry
                               ▼
            run records ──► eval-harness (is the change really better?)
                               ▲
            AI (perception, planning) proposes changes and actions
```

## Order

1. **NXT on its own.** Hardware check, first programs, logs. (Most of the code exists.)
2. **Microduck on its own.** Its SDK and simulator, its preset behaviours, our first trained one.
3. **A shared robot contract.** Only once both robots work: pull out what their services have
   in common (status, actions, telemetry, run-record format). Extracting it from one robot would
   be guessing.
4. **Run records into eval-harness.** Controllers and trained policies as arms, repeated
   physical trials, simulator vs real.
5. **Robots as flotilla hosts.** Allowed actions per robot, autonomy earned per action, safety
   stop always available.
6. **AI in the loop.** Perception and planning models chosen by eval-harness, acting only
   through flotilla.

## What robots would ask of eval-harness and flotilla

Robot scenarios differ from the text tasks both projects were built around. These are the
requirements they would push back into them; each needs checking against the projects' own
design docs (especially their Non-Goals) before it becomes work there.

**eval-harness**
- Trials that cost time and need a person to reset the robot, so very few items and repeats;
  sample-size questions dominate.
- Items that are scenarios (a track layout, a start pose), not frozen text.
- Scores computed from time-series logs (lap time, wobble, collisions, falls), not one output.
- Simulator vs real as a first-class comparison.

**flotilla**
- Actions that move things in the physical world and cannot be undone.
- A safety stop that works whatever the policy, the agent or the network is doing.
- Time limits measured in seconds, not minutes.
- A host that may be offline, on battery, or moved.
- Evidence for "check and close" coming from sensors and camera frames.

## Open

- Whether robot telemetry goes to the homelab observability stack.
- Where AI models run for the duck (on the robot, the PC, or the homelab GPU) — an
  eval-harness question once there is something to measure.
- What the Microduck's SDK actually exposes (description so far is from press coverage).
