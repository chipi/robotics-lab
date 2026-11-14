# RFC-0002 — The robot brain: layers, navigator, safety and phases

**Status:** Proposed (2026-11-14). Phase 0 approved by the operator; the rest for review.
**Builds on:** [ECOSYSTEM.md](../wip/ECOSYSTEM.md), [MICRODUCK.md](../wip/MICRODUCK.md),
[RFC-0001](RFC-0001-nxt-web-ui.md) (the NXT's safety lessons).
**Part of a set:** [RFC-0003](RFC-0003-robot-interface.md) (the robot interface),
[RFC-0004](RFC-0004-perception-and-planning.md) (models, perception, planning),
[RFC-0005](RFC-0005-missions.md) (missions with flotilla and eval-harness).
**Replaces:** the draft `docs/wip/ROBOT-BRAIN.md` (2026-11-13).

## 1. Motivation

The operator's goal: tell the Microduck "walk into every room, roughly size each one, then find
the kitchen table and stop under it", and have it do that on its own, with models running on the
homelab DGX. Later the NXT joins through the same brain.

The duck walks, balances and keeps a map on board; it does not know what a kitchen is, cannot be
sent somewhere, and leaves planning to "the autonomy layer". This RFC is that layer.

Facts about the duck come from `/work/pollen/microduck` (API v61); read, not yet exercised unless
[MICRODUCK.md](../wip/MICRODUCK.md) says they were run.

## 2. What the duck gives, and what it does not

Gives:

- **One interface:** JSON-RPC 2.0, one object per line, over Unix sockets, one socket per daemon;
  a subscription owns its connection.
- **Moving:** `robot.move {vx, vy, vyaw}` (m/s, rad/s), sent repeatedly; `robot.head`,
  `robot.look`, `robot.do {skill}`, `robot.stop`.
- **State:** `robot.subscribe` streams odometry, the applied twist and who sent it, what limited
  it (e.g. `deadman`), fall and pick-up flags, IMU, sensor poses.
- **Depth:** 8×8 distances about 15 times a second — "a cane, not a lidar": median valid range
  about 0.5 m.
- **Map:** `mapd` keeps an occupancy grid built at stops, readable through `map.grid`, with a pose
  and a `lost` reason. **Read-only; no go-to.**
- **Camera:** on the robot, it dials our WebSocket and streams; in the simulator, `/frame`.
- **A 500 ms deadman:** the twist goes to zero if move commands stop.

Does not give, and what that forces:

1. **No speed clamp.** The brain keeps commands within what the walking policy was trained on:
   forward 0.15–0.3 m/s (below about 0.12 m/s the gait does not move), turning ≤ 1.5 rad/s.
2. **No arbitration** — last writer wins, and `autod` yields only to the gamepad. While the brain
   drives: the duck's autonomy off, no gamepad in use, and the brain names itself (`hello {client:
   "robot-brain"}`) and checks every state frame that it is still the one driving.
3. **No obstacle stop of its own** (that lives in `autod`, which is off). The brain's navigator
   stops on the depth sensor itself, every frame.
4. **No go-to, no exploring on request.** The brain plans paths and exploration itself.
5. **The map grows only at stops.** Exploring is: walk a little, stop, look around, repeat.
6. **The deadman needs a fresh move command at least every 0.5 s**, so whatever sends them must be
   close to the robot and reliable.

## 3. Proposal

### 3.1 Layers

```text
 instruction ─► PLANNER   LLM with tools                            seconds        (RFC-0004)
                  ▼ tool calls
               BRAIN      world model, perception, run log          0.5–2 Hz
                  ▼ goals (x, y), skills, head
               NAVIGATOR  path on the map, depth stop, limits,      10–20 Hz
                          deadman refresh, stuck/fallen/lost
                  ▼ JSON-RPC                                                       (RFC-0003)
               ROBOT      the duck's daemons (later the NXT service) 50 Hz
```

- **The LLM never sends a twist.** It chooses the next step; the navigator moves; the robot
  balances. A slow or failed model call means the robot waits, standing.
- **Navigator:** A* (or similar) on `map.grid` at 10 cm with walls inflated by about 15 cm (as
  `autod` does), pure pursuit to the next waypoint, frontier exploration toward unseen floor,
  survey stops with a head sweep, and a depth-sensor stop distance checked every frame.
- **Run record:** every run writes JSONL — the instruction, every tool call and model call with
  latency and cost, poses, map snapshots, the outcome — the input to eval-harness
  ([RFC-0005](RFC-0005-missions.md)).

### 3.2 Where things run

| | Simulator (now) | Real duck (later) |
| --- | --- | --- |
| Link to the duck | Unix sockets in `~/.cache/duck-sim/` | Open (§5) |
| Navigator | Workstation | Close to the robot |
| Brain, planner client | Workstation | Workstation |
| Models | LiteLLM aliases (RFC-0004) | same |

Rule: the navigator talks to the robot through one small transport interface, so the simulator
and the real duck are the same code above it. This matters beyond development: in the mission
loop the simulator is where plans are rehearsed ([RFC-0005](RFC-0005-missions.md)).

### 3.3 Safety

- Speed limits (§2.1), a depth stop distance, a maximum task time, and a geofence (cells mapped
  free, plus the frontier).
- Stop on: fallen or picked up, map lost, another client driving, battery low, model budget spent,
  operator stop.
- An operator STOP that sends `robot.stop` directly, never through the planner.
- The planner's tools are an allowlist (no mode changes, updates or accounts).
- Every model call has a timeout; failure means stand still and report.

### 3.4 Phases

| # | Phase | Done when |
| --- | --- | --- |
| 0 | **Groundwork.** Project skeleton (uv), JSON-RPC client for the sockets, `mapd` started beside `duck-sim` (it does not start it), the `apartment` scene made walkable (its robot lacks the backlash model the walking policy needs) | A script reads state, depth and the map from the simulated duck in the apartment and walks it 1 m on command |
| 1 | **Navigator** | 20 go-to goals from fixed starts: each reached or refused, never a collision, all logged |
| 2 | **Explore, map, rooms** | All six apartment rooms mapped; room areas within an agreed tolerance |
| 3 | **Perception** (RFC-0004) | Correct room type at most survey stops; the table found from every start |
| 4 | **Planner** (RFC-0004) | "Tour, then hide under the kitchen table" end to end in simulation, scored by eval-harness |
| 5 | **Real duck** | The same score sheet, simulator vs real |

## 4. Non-goals (v1)

- Training walking policies (separate work, [MICRODUCK.md](../wip/MICRODUCK.md)).
- The LLM controlling motion, or anything in the 50 Hz loop.
- Changing the duck's own daemons. If upstream must change (e.g. a backlash apartment scene), it is
  raised with Pollen, not forked silently.
- Several robots at once; the NXT joins after phase 4.

## 5. Open questions

1. **The real-duck link.** Upstream's supported path for a server-side program is the "rendezvous"
   relay through the Hugging Face account: JSON-RPC over HTTP/SSE, no pixels, 1200 requests per
   minute, 400 notifications per minute pushed. Enough for the brain; too thin for a navigator
   refreshing the deadman and reading depth at 15 Hz. Options: the navigator on the robot (our
   code on the duck), or LAN socket access over ssh (possible, not endorsed upstream). Decide when
   the duck is here.
2. **The walkable apartment:** a small scene change, and does upstream want it?
3. **Room segmentation** on a coarse grid from a short-range sensor — measured in phase 2.
4. **Where the brain runs long-term:** the workstation, the DGX, or a small always-on box.

## 6. Alternatives considered

- **Give `autod` goals:** not possible; it takes no goals and listens on no socket.
- **Let the LLM send twists:** rejected — model latency is seconds, the deadman 0.5 s, and an
  obstacle stop must not wait for a model.
- **Everything over the rendezvous relay:** rejected for the navigator (rate limits, no pixels);
  likely for the brain itself.
- **The navigator as a Rust daemon on the robot now:** deferred; Python against the simulator is
  faster to iterate, and §3.2 keeps the door open.

## 7. Discussion

- 2026-11-13 — Draft written as `docs/wip/ROBOT-BRAIN.md` after reading the duck's interface; the
  operator approved phase 0 and the phase-1 models.
- 2026-11-13 — The operator: the combined mission loop, shadow = running the plan on the simulated
  duck, is the direction ([RFC-0005](RFC-0005-missions.md)). The simulator becomes a permanent part
  of the system, not a development convenience.
- 2026-11-14 — Split into RFC-0002 to RFC-0005 at the operator's request.
