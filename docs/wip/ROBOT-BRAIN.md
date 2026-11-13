# Robot brain — design

Status: draft, 2026-11-13. Not built. The first robot is the Microduck (simulated first); the
NXT joins later through the same interface.

Goal (operator): tell the duck "walk into every room, roughly size each one, then find the
kitchen table and stop under it", and have it do that on its own, with models on the DGX.

Facts about the duck below come from `/work/pollen/microduck` (API v61) unless marked
otherwise; file references are into that repo. They were read, not yet exercised, except where
[MICRODUCK.md](MICRODUCK.md) says a thing was run.

## 1. What the duck already gives us

- **One interface:** JSON-RPC 2.0, one object per line, over Unix sockets, one socket per daemon
  (`duck-ipc-proto/src/lib.rs`). A subscription owns its connection, so streams and requests
  use separate connections.
- **Moving:** `robot.move {vx, vy, vyaw}` (m/s, rad/s, trunk frame), sent repeatedly;
  `robot.head`, `robot.look {x,y,z}`, `robot.do {skill}`, `robot.stop`, `robot.enable`.
- **State:** `robot.subscribe {hz}` streams `robot.state`: odometry `{position, yaw}`, the
  applied twist and who sent it (`move.source`), what limited it (`limited_by`, e.g.
  `deadman`), safety (`fallen`, `picked_up`, …), IMU, camera/ToF poses. Battery is in
  `robot.health`.
- **Depth:** `tof.stream` → `tof.frame`, 8×8 distances in mm, about 15 Hz. "A cane, not a lidar":
  median valid range about 0.5 m, 90 % under 1 m (`docs/design/mapping-design.md` §1).
- **Map:** `mapd` builds an occupancy grid from depth and odometry, only at stops:
  `map.status`, `map.stream` (pose in map frame, `lost` reasons), `map.grid {res_m}` (cells
  `?` unknown, `.` free, `#` occupied, plus keyframes and pose). **Read-only. No go-to, no
  planning:** "Planning on the grid (`go there`) — … in the autonomy layer, not here"
  (`mapping-design.md` §8).
- **Camera:** on the robot, `media.stream` makes the robot dial *our* WebSocket and send H.264
  or JPEG at a chosen fps and size (reference receiver `spaces/vision-demo/receiver.py`). In the
  simulator, `http://127.0.0.1:8080/frame` (PNG) or the frame socket.
- **Safety:** a **500 ms deadman** zeroes the twist if move intents stop ("losing comms makes
  the robot stand still"). Head targets are not zeroed.

## 2. What the duck does not give us, and what that forces

1. **No speed clamp.** `robotd` passes any `robot.move` through; the policy only behaves inside
   what it was trained on. The brain enforces limits: forward 0.15–0.3 m/s (below about
   0.12 m/s the gait does not move), turn ≤ 1.5 rad/s, as `autod` and the console use.
2. **No arbitration.** Every intent is last-writer-wins. `autod` yields only to `padd`. So
   while the brain drives: `robot.autonomous` off, no gamepad in use, and the brain names
   itself with `hello {client: "robot-brain"}` and checks that `move.source` is still itself.
3. **No obstacle stop of its own.** Obstacle avoidance lives in `autod`, which must be off. So
   the brain's navigator must stop on the depth sensor itself, every frame, before anything
   smarter.
4. **No go-to, no exploration API.** `autod`'s exploring cannot be given goals. The brain
   needs its own planner on `map.grid` and its own exploration.
5. **The map grows only at stops.** Exploring means walk a little, stop, look around (head
   sweep), repeat — the same rhythm `autod` uses (4–6 s surveys).
6. **The deadman needs a fresh `robot.move` at least every 0.5 s**, so whatever sends twists
   must be close to the robot and reliable. That decides where the navigator runs (§4).

## 3. Architecture

```
 instruction ─► PLANNER (LLM, DGX/cloud via LiteLLM `robot-planner`)     seconds
                  │ tool calls: explore, go_to, survey, look, ask_view, stop, report
                  ▼
               BRAIN (Python, robotics-lab/brain)                         0.5–2 Hz
                  world model: map copy, rooms, objects + positions, task state
                  perception: frames ─► VLM (LiteLLM `robot-vlm`)          every few s
                  run log ─► run record (JSONL) ─► eval-harness
                  ▼ goals (x, y) / skills / head
               NAVIGATOR                                                  10–20 Hz
                  path on map.grid (walls inflated), pure pursuit ─► robot.move
                  depth-sensor stop, speed limits, deadman refresh, stuck/fallen/lost
                  ▼ JSON-RPC (NDJSON)
               DUCK  robotd · tofd · mapd · mediad                         50 Hz
```

- **The LLM never sends a twist.** It picks the next step; the navigator moves; the duck
  balances. A slow or failed model call means the duck waits, standing.
- **The VLM answers questions about frames**, not control: "which room type is this?", "is
  there a kitchen table? where in the image?", "are we under a table?". Its bounding box plus
  the camera intrinsics (`media.video`) gives a bearing; depth when close gives range.
- **Rooms and sizes:** from the map (free-space segments split at doorways) plus the VLM's
  room label per survey stop. "Size" is the segment's free area and bounding box — rough by
  design, given the depth sensor.
- **Under the table:** find it (VLM), approach along its bearing, then confirm "under" from the
  camera (VLM yes/no) and position within the table's footprint. The duck is about 25 cm tall.
- **Run records:** every run writes JSONL: instruction, every tool call and model call (with
  latency and cost), poses, map snapshots, outcome. Success, time and distance per run go to
  eval-harness with `evh import-run` ([EVAL-HARNESS-ROBOTS.md](EVAL-HARNESS-ROBOTS.md)).

## 4. Where things run, and how they reach the duck

| | Simulator (now) | Real duck (later) |
|---|---|---|
| Transport to the duck | Unix sockets in `~/.cache/duck-sim/` directly | **Open**, see below |
| Navigator | Workstation | Close to the robot (see below) |
| Brain + planner client | Workstation | Workstation |
| Models | LiteLLM aliases → cloud (phase 1), later DGX `:8006` | same |
| Frames | `/frame` on `127.0.0.1:8080` | `media.stream` to our WebSocket receiver |

Real-duck transport options (decided when the duck arrives):
1. **Rendezvous control lane** (upstream's supported path for "a server-side agent / LLM",
   `architecture.md` §5.3; client `spaces/shared/wire.py`): JSON-RPC over HTTP/SSE through the
   Hugging Face account. Limits: no pixels, 1200 requests per 60 s per peer, the robot pushes at
   most 400 notifications per 60 s. Fine for the brain; too thin for a navigator streaming
   depth at 15 Hz and refreshing twists every 0.5 s.
2. **Navigator on the duck**: a small socket client running on the robot itself (like `autod`),
   taking goals from the brain over the rendezvous lane. Fast and robust, but means running
   our own code on the robot (dev image or ssh).
3. **LAN socket access over ssh**: possible (ssh on Wi-Fi opens for 30 min from the face button,
   or on the dev image), not endorsed upstream for programs.

Design rule: the navigator talks to the duck through one small transport interface, so the
simulator (sockets) and the real duck (whichever option) are the same code above it.

## 5. Safety and limits

- Speed limits (§2.1), depth-sensor stop distance, a maximum task time, and a geofence (only
  cells already mapped as free, plus the frontier).
- Stop on: `safety.fallen` / `picked_up`, `map.state.lost`, `move.source` not ours, battery
  low, model budget exhausted, operator stop.
- An operator STOP in the UI that sends `robot.stop` directly, not through the planner.
- Tool allowlist for the planner (no `robot.setMode`, no updates, no `account.*`). Later,
  flotilla decides what may run without asking ([IDEAS.md](IDEAS.md), flotilla ideas).
- Every model call has a timeout; failure means stand still and report.

## 6. Models (agreed with homelab, 2026-11-13)

- **Phase 1 (operator approved, live 2026-11-13):** LiteLLM on the mini, two aliases of our own,
  `robot-vlm` and `robot-planner`, both routed to **Qwen3-VL-30B-A3B-Instruct** on OpenRouter
  (open weights, 3B active parameters, vision and tool calling, runs on the GB10). Our key is
  in `~/robotics-brain-litellm.env` (mode 600, never committed; `set -a; . ~/robotics-brain-litellm.env;
  set +a` gives `LITELLM_API_KEY` and `LITELLM_API_BASE`). It reaches those two aliases only.
  Hard cap $10 per 30 days (homelab's setting; the operator's direction is "whatever we need",
  raised on request). Checked: one text call to each alias, HTTP 200 in 1.7 s and 1.5 s;
  another alias with the same key, 403. A second open-weight candidate to compare
  (homelab suggests Gemma 4 26B-A4B) needs the operator's yes.
- **Phase 2:** once eval-harness picks a model, a local vLLM on the DGX (`:8006`, homelab
  `infra/robotics/`), inside the `robotics` GPU mode; the aliases move, the brain's code does
  not. One vision model can serve both aliases. Any robotics window takes prod down; prod must
  be back by 23:30Z.

## 7. Phases

| # | Phase | Done when |
|---|---|---|
| 0 | **Groundwork.** Brain project skeleton (uv). JSON-RPC client for the sockets. Start `mapd` beside `duck-sim` (`duck-sim` does not start it) with `[map] enabled`. Make the `apartment` scene walkable: its robot lacks the backlash model that `velstand` needs | A script reads `robot.state`, `tof.frame`, `map.grid` from the simulated duck in the apartment, and walks it 1 m on command |
| 1 | **Navigator.** Twist refresh, limits, depth stop, go-to on the grid, survey stops | 20 go-to goals in the apartment from fixed starts: reached or refused, never a collision, logged |
| 2 | **Explore + map + rooms.** Frontier exploration, room segmentation, sizes | Map covers all six rooms; room areas within an agreed tolerance of the scene's real ones |
| 3 | **Perception.** Frames → VLM (phase-1 aliases), room labels, find the table | Correct room type at most survey stops; table found from every start |
| 4 | **Planner.** LLM with tools, the full instruction | "Tour then hide under the kitchen table" end to end in simulation, scored by eval-harness over a fixed start set |
| 5 | **Real duck.** Transport chosen, same tasks at home | Same score sheet, sim vs real |

## 8. Not in scope (v1)

- Training new walking policies (separate work, [MICRODUCK.md](MICRODUCK.md)).
- The LLM controlling motion directly, or anything on the 50 Hz loop.
- Changing the duck's own daemons. If something upstream must change (e.g. a backlash
  apartment scene), it is raised with Pollen, not forked silently.
- Several robots at once; the NXT joins after phase 4.
- flotilla integration (later; a local tool allowlist stands in for it).

## 9. Alternatives considered

- **Give `autod` goals:** not possible, it has no input for goals and listens on no socket.
- **Let the LLM send twists:** rejected: model latency is seconds, the deadman is 0.5 s, and
  obstacle stops must not wait for a model.
- **Everything over the rendezvous lane:** rejected for the navigator (rate limits, no pixels);
  kept as the likely transport for the brain itself.
- **Write the navigator in Rust as a daemon on the robot now:** deferred; Python on the
  workstation against the simulator is faster to iterate. Option 2 in §4 keeps the door open.

## 10. Open questions

1. Real-duck transport (§4) — decided when the duck is here.
2. Making the apartment walkable: is a backlash variant of the apartment a small scene change,
   and does upstream want it?
3. Phase-1 model and budget (operator).
4. Room segmentation method on a 2.5–10 cm grid with a short-range sensor — measured in phase 2.
5. The NXT's JSON-RPC interface: the same method names where they make sense (`robot.move`,
   `robot.state`, `robot.do`), designed after the brain's needs are clear.
