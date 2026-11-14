# RFC-0002 — The robot brain: modes, navigator, safety and phases

**Status:** Proposed, revision 2 (2026-11-14): the [review](../wip/REVIEW-2026-11-14-duck-rfcs.md)
and the operator's decisions taken in. Phase 0 approved by the operator.
**Builds on:** [ECOSYSTEM.md](../wip/ECOSYSTEM.md), [MICRODUCK.md](../wip/MICRODUCK.md),
[RFC-0001](RFC-0001-nxt-web-ui.md) (the NXT's safety lessons).
**Part of a set:** [RFC-0003](RFC-0003-robot-interface.md) (the robot interface),
[RFC-0004](RFC-0004-perception-and-planning.md) (missions in words, models, perception, planning),
[RFC-0005](RFC-0005-missions.md) (missions with flotilla and eval-harness).
**Replaces:** the draft `docs/wip/ROBOT-BRAIN.md` (2026-11-13).

## 1. Motivation

The operator's goal: tell the Microduck, in plain words, something like "visit every room, tell me
roughly how big each is, then wait for me by the front door" — and have it do that on its own, with
models on the homelab DGX. Later the NXT joins through the same brain.

A mission is **explore + report + an end**. The end is one of three options (operator,
2026-11-14), passed with the mission:

| End | In words | In the simulated apartment |
| --- | --- | --- |
| **A. Landmark** (first) | "…then go to the front door" | stop 1 m from the coat rack in the corridor (the hall) |
| **B. Start** | "…then come back" | return to where the mission began |
| **C. Largest room** | "…then wait in the biggest room" | stop in the doorway of the room it measured largest |

Each end needs the whole home explored first, and each ends at a checkable place. (A kitchen table
to hide under was the first idea; the simulated apartment has none a 25 cm duck fits under, so it
was dropped.)

The duck walks, balances and keeps a map on board; it cannot be sent somewhere, and leaves planning
to "the autonomy layer". This RFC is that layer. Facts about the duck come from
`/work/pollen/microduck` (API v61), checked by the review.

## 2. What the duck gives, and what it does not

Gives:

- **One interface:** JSON-RPC 2.0, one object per line, over Unix sockets, one socket per daemon; a
  subscription owns its connection.
- **Moving:** `robot.move {vx, vy, vyaw}` (m/s, rad/s), sent repeatedly; `robot.head`, `robot.look`,
  `robot.do {skill}`, `robot.stop`, `robot.flashlight` (an RGB light any client may set).
- **State:** `robot.subscribe` streams odometry, the applied twist and who sent it, what limited it
  (e.g. `deadman`), fall and pick-up flags, whether the duck's own autonomy is on.
- **Depth:** a VL53L8CX, 8×8 zones over 45°, about 15 times a second — "a cane, not a lidar": the
  useful median range is about 0.5 m.
- **Map:** `mapd` keeps an occupancy grid built at stops (`map.grid`, pose, a `lost` reason). It
  has no go-to; it has `map.wipe`, which the brain never calls. **It maps only while the duck's
  autonomy is on, unless `[map] enabled = true`** (off by default upstream because its standing CPU
  cost on the board has not been measured).
- **Camera:** `GET /frame` on the duck's own console, on the robot and in the simulator alike;
  `media.stream` for pushing video to a remote receiver.
- **A 500 ms deadman:** the twist goes to zero if move commands stop. Stop is not limp.

Does not give, and what that forces:

1. **No speed clamp.** The brain keeps inside the walking policy's training: forward 0.15–0.3 m/s
   (trained ±0.4; upstream reports no walking below about 0.2 m/s in simulation and `autod` never
   asks for less than 0.15 m/s, with a short full-speed start), turning ≤ 1.0 rad/s (trained ±1.0).
2. **No arbitration** — last writer wins. `autod` yields only to the gamepad (and to an external
   soccer game). So the duck's autonomy and our navigator never drive at the same time (§3.1).
3. **No obstacle stop of its own** (it lives in `autod`). When our navigator drives, it stops on the
   depth sensor itself, every frame.
4. **No path planning:** upstream lists "go there" as not built. We build the navigator.
5. **The map grows only at stops:** a stop opens after a few seconds with no twist asked for.
   Exploring is: walk a little, stop, look around (a **survey**), repeat.
6. **The deadman needs a fresh move command at least every 0.5 s**, so whatever sends them must be
   on the LAN or on the robot.

## 3. Proposal

### 3.1 Two modes, one switch

| Mode | Who drives | Mapping | The brain |
| --- | --- | --- | --- |
| **auto** (explore) | the duck's own `autod`: wanders, avoids obstacles, ends each wander in a 4–6 s survey | on by itself | **watches**: copies the map, labels rooms from the camera, collects data |
| **brain** | our navigator | on (`[map] enabled = true`) | drives to goals and to the mission's end |

The switch is `robot.autonomous` on/off, flipped by the brain (or the operator). The duck's
flashlight shows the mode: green auto, blue brain, red stopped or waiting for the operator.

A mission can use both: explore in **auto** while the brain watches, then switch to **brain** to
finish (end A/B/C) — reusing upstream's tested explorer and obstacle handling. Whether `autod`'s
novelty-driven wandering covers every room in reasonable time is measured in phase 2; if not, the
brain explores itself.

### 3.2 Layers

```text
 instruction ─► PLANNER   words → mission spec → tool calls          seconds       (RFC-0004)
                  ▼
               BRAIN      world model, perception, mode, run log      0.5–2 Hz
                  ▼ goals (x, y), surveys, skills, head
               NAVIGATOR  path on the map, depth + cliff stop,        10–20 Hz      we build it
                          limits, deadman refresh, measured odometry
                  ▼ JSON-RPC                                                        (RFC-0003)
               ROBOT      the duck's daemons (later the NXT service)  50 Hz
```

- **The LLM never sends a twist.** It chooses the next step; the navigator moves; the robot
  balances. A slow or failed model call means the robot waits, standing.
- **Navigator (ours):** A* on `map.grid` at 10 cm, keeping 15 cm clear of walls (as `autod`
  checks); pure pursuit to the next waypoint; frontier exploration toward unseen floor; surveys
  (send no twist, sweep the head, wait until `mapd` reports `collecting`); a depth stop distance and
  a cliff check every frame. It **closes its loop on measured odometry, never on commanded speed**,
  and logs commanded vs measured per run — the simulator walks at about 44 % of what is asked.
- **Run record:** every run writes JSONL — the instruction, the mission spec, every tool and model
  call with latency and cost, poses, mode switches, map snapshots, the outcome — the input to
  eval-harness ([RFC-0005](RFC-0005-missions.md)).

### 3.3 Where things run, and how they reach the duck

The duck's daemons listen on Unix sockets, which are files on the duck: unreachable over the
network on purpose. **ssh** carries them to the workstation:

```text
workstation                                         the duck (Wi-Fi)
/tmp/duck/robotd.sock ══ ssh -L … microduck@duck ══► /run/robotd.sock
/tmp/duck/tof.sock    ══════════════════════════════► /run/tofd/tof.sock
/tmp/duck/map.sock    ══════════════════════════════► /run/mapd/map.sock
```

Our software connects to the local socket files exactly as if it were on the duck — and in the
simulator they are local files in `~/.cache/duck-sim/`, so **the same code drives both**; only the
paths change. This is upstream's documented developer path (running the gamepad program from a
laptop: `docs/robot/cheatsheet-dev.md`). ssh on Wi-Fi is opened with the face button (30 min), over
USB until reboot, or kept open by the developer image. Frames come from `/frame` on the LAN.

| | Simulator (phases 0–4) | Real duck (phase 5) |
| --- | --- | --- |
| Link | local sockets | ssh-forwarded sockets over the LAN |
| Navigator, brain, planner client | workstation | workstation |
| Models | LiteLLM aliases ([RFC-0004](RFC-0004-perception-and-planning.md)) | same |

The Hugging Face relay ("rendezvous": JSON-RPC over HTTP/SSE, 1200 requests and 400 notifications a
minute, no pixels) is for a brain away from home, not for the navigator.

### 3.4 Phases

| # | Phase | Done when |
| --- | --- | --- |
| 0 | **Spike: is the simulator a usable stand-in?** Turning in the backlash scene; the backlash robot in the apartment; `mapd` with `[map] enabled = true` beside `duck-sim` | Turning on the spot within 20 % of upstream's ~50°/s; the duck walks in the apartment; the map gains keyframes with autonomy off. If not, phases 1–4 are blocked and RFC-0005's rehearsal is revisited |
| 1 | **Groundwork + navigator.** Project (uv), JSON-RPC client, modes, flashlight, navigator | 20 go-to goals from fixed starts: each reached or refused; zero contacts between the duck and walls or furniture in MuJoCo's contact list; all logged |
| 2 | **Explore, map, rooms** (both ways: `autod` exploring with the brain watching, and the brain exploring) | All six rooms visited; each room's area within ±25 % of `apartment.xml`'s floor boxes; time per way compared |
| 3 | **Perception** ([RFC-0004](RFC-0004-perception-and-planning.md)) | Room type right at most survey stops; the coat rack found from every start |
| 4 | **Missions in words** | End A from ≥ 10 start poses, then B and C, scored by eval-harness; mission specs from sentences checked offline |
| 5 | **Real duck** | `mapd`'s CPU cost on the board measured; the same score sheet, simulator vs real, with the commanded/measured speed gain as the first comparison |

### 3.5 Prerequisites in the simulator

- `mapd` is not started by `duck-sim`: phase 0 starts it with the sim's `robotd.toml` plus
  `[map] enabled = true`.
- The `apartment` scene carries the robot without backlash, on which the walking policy does not
  step: phase 0 makes a backlash variant. Scene changes are offered to Pollen, not forked silently.
- The corridor has a **staircase hole** on the way to the hall: the cliff check is tested there.

### 3.6 Safety

Limits: §2.1 speeds, a depth stop distance, a maximum mission time, a geofence (cells mapped free,
plus the frontier). An operator STOP sends `robot.stop` directly, never through the planner. The
planner's tools are an allowlist; every model call has a timeout.

| Situation | Rule |
| --- | --- |
| The duck's autonomy switched on while the brain drives (NFC tag, `robotctl`) | Watch `autonomous` in every state frame; stop, mark the mission interrupted; resume only when it is off **and** the operator says so |
| Someone else drives (a gamepad, a second brain) | Name each run `robot-brain-<run-id>` (`hello`), hold a per-robot lock; if `move.source` is not us, stop and report |
| Wi-Fi drops | The deadman stops the duck. Reconnect with back-off, re-read pose, `map.status` and the driver; resume only if not lost, still the driver, within the mission's time; else survey or ask |
| Lost (`carried`, `bumped`, `sat`, `fell`, `contradiction`, or a reason not known) | No pose → no geofence: turn-in-place surveys only (upstream relocalises after two agreeing stops); not found after N → abort and report |
| Fall, pick-up or bump | The duck stands itself up; the mission drops out of `auto` and resuming needs the operator's OK (never walk back into the dog) |
| The floor disappears ahead (stairs) | Stop, treat as an obstacle, never cross |

### 3.7 Frames of reference: dead reckoning with fixes

| Frame | What it is | Source |
| --- | --- | --- |
| **trunk** | the duck's body: x forward, y left, z up; move commands are in it | `robot.move` |
| **odom** | position from legs and gyro since boot; 50 Hz and smooth, but it **drifts** | `robot.state.odom` |
| **map** | `mapd`'s floor plan, origin at its first stop, "no north"; it **jumps** when corrected, does not drift | `map.stream`, `map.grid` |

The standard arrangement (ROS: `map → odom → base_link`), and what `autod` does. It is a
navigator's dead reckoning: odometry is the log and compass, a survey stop is taking a fix, the
map→odom offset is the fix plotted, and "lost" is fog. The navigator keeps one offset: at each
`mapd` pose, offset = map pose − odom pose at the same `t_ns`; between fixes, position on the map =
latest odometry + offset. Upstream measured the simulator's drift at about 0.3 % per metre; the real
robot's is not measured.

### 3.8 Building the navigator

Python, as pure functions (state in, command out, no sockets inside, like `autod`'s brain), unit
tested on recorded state and replayed offline before it drives:

1. **Cost map:** `map.grid` at 10 cm every few seconds; obstacles grown by about 15 cm plus the
   duck's half-width; unknown cells expensive, not forbidden.
2. **Path:** A* to the goal; replan when the map changes or the path is blocked.
3. **Following:** pure pursuit to a point about 30 cm ahead → forward speed 0.15–0.3 m/s and turn
   ≤ 1.0 rad/s; turn on the spot first when the heading is over about 45° off; a short full-speed
   start; speed and turn corrected from measured odometry.
4. **Reflexes, every depth frame:** something close ahead → stop; floor gone → stop.
5. **Deadman:** a move command every 100 ms while walking.
6. **Surveys:** no twist, head sweep, wait for `collecting`.
7. **Exploring:** the nearest worthwhile frontier (free cells next to unknown).

The concepts and frame names follow ROS 2 Nav2, the standard navigation stack, so moving to Nav2
later stays possible. Not now: it means installing ROS 2 and bridging the duck's JSON-RPC, and Nav2
assumes a lidar, not a 45° short-range depth sensor.

### 3.9 How the link evolves

The duck's daemons listen only on files inside the duck, on purpose: nothing on the network drives
it without an authenticated door. Upstream's doors: the WebRTC control channel (browser and app; the
same JSON-RPC), the Hugging Face relay (programs anywhere; rate-limited, no pixels), Bluetooth
(setup only), and ssh (developers). Across robotics the pattern is the same: **fast loops on the
robot, slow thinking off it** (ROS 2 topics, vendor APIs such as Spot's gRPC SDK, WebRTC or DDS,
MQTT for fleets).

1. **Now:** the simulator's local sockets.
2. **First real-duck runs:** ssh-forwarded sockets — the real duck looks exactly like the simulator,
   no new code. A developer tool, not the end state.
3. **Grown up:** the navigator runs **on the duck** beside `autod` (it is a Linux computer); the
   brain stays off-board and talks to it through the relay, the WebRTC channel, or our own JSON-RPC
   ([RFC-0003](RFC-0003-robot-interface.md)). The reflex loop no longer crosses Wi-Fi. This
   reverses the v1 non-goal "no code of ours on the duck", so it is an open decision (§5).

## 4. Non-goals (v1)

- Training walking policies (separate work, [MICRODUCK.md](../wip/MICRODUCK.md)).
- The LLM controlling motion, or anything in the 50 Hz loop.
- Changing the duck's own daemons; our code on the duck.
- Several robots at once; the NXT joins after phase 4.

## 5. Open questions

1. `autod`'s coverage in auto mode — measured in phase 2.
2. `mapd`'s CPU cost on the real board with `[map] enabled = true` — measured in phase 5.
3. Room segmentation on a coarse grid from a short-range sensor — phase 2.
4. Whether `mapd` treats a zero twist as "no twist asked for" when deciding a stop, or the
   navigator must stop sending — checked in phase 0.
5. Where the brain runs long-term (workstation, DGX, an always-on box).
6. **Whether the navigator moves onto the duck** (§3.9, step 3) — the operator decides; it reverses
   a v1 non-goal.

## 6. Alternatives considered

- **Give `autod` goals:** not possible; it takes none and listens on no socket.
- **Let the LLM send twists:** rejected — model latency is seconds, the deadman 0.5 s, and a stop
  must not wait for a model.
- **Run `autod` and our navigator together:** rejected — no arbitration; they would alternate.
- **Everything over the relay:** rejected for the navigator (rate limits, no pixels).
- **The navigator as a daemon on the robot:** not needed; ssh-forwarded sockets give the same
  interface on the LAN.

## 7. Discussion

- 2026-11-13 — Draft as `docs/wip/ROBOT-BRAIN.md`; the operator approved phase 0 and the phase-1
  models.
- 2026-11-13 — Operator: the combined mission loop is the direction ([RFC-0005](RFC-0005-missions.md)).
- 2026-11-14 — Split into RFC-0002 to RFC-0005 at the operator's request.
- 2026-11-14 — Independent review ([REVIEW](../wip/REVIEW-2026-11-14-duck-rfcs.md)). Operator: drop
  the kitchen table; missions take end options A/B/C, A first, described in plain words; two modes
  (auto / brain) with a switch, watching and collecting data during auto; the navigator is ours;
  ssh-forwarded sockets for the real duck. Revision 2 applies all of it, plus the stairs check.
- 2026-11-14 — Operator asked how the navigator is built and why an ssh tunnel; added §3.7 frames
  (dead reckoning with fixes — the operator's sailing analogy), §3.8 the navigator build, §3.9 how
  the link evolves (navigator on the duck as an open decision).
