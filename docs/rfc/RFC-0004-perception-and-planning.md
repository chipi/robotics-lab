# RFC-0004 — Missions in words, perception and planning: the brain's models and tools

**Status:** Proposed, revision 2 (2026-11-14): missions described in plain words with end options,
and the [review](../wip/REVIEW-2026-11-14-duck-rfcs.md) taken in. Phase-1 models live.
**Builds on:** [RFC-0002](RFC-0002-robot-brain.md) (modes, layers),
[MICRODUCK.md](../wip/MICRODUCK.md), [EVAL-HARNESS-ROBOTS.md](../wip/EVAL-HARNESS-ROBOTS.md).

## 1. Motivation

The duck can walk to a point and keep a map. It cannot understand "visit every room, tell me how
big each is, then wait by the front door", tell a bedroom from a hallway, or recognise the coat
rack. Those are jobs for an LLM planner and a vision-language model, called from the brain every
few seconds — never in the control loop.

## 2. Proposal

### 2.1 Missions in plain words

```text
"Visit every room, tell me how big each is, then wait for me by the front door"
   │  robot-planner: words → a mission spec (a fixed, validated schema)
   ▼
{ "explore": "all_rooms",
  "report": ["room_sizes"],
  "end": { "kind": "landmark", "landmark": "coat rack", "distance_m": 1.0 },
  "limits": { "max_minutes": 20 } }
   │  read back in plain words: "I'll visit all 6 rooms, report their sizes, then stop
   │  1 m from the coat rack in the hall. OK?"   — the operator confirms, or it asks
   ▼
the brain runs it (§2.5)
```

- **End options** (operator, 2026-11-14): `landmark` (A: "…go to the front door"; in the simulated
  apartment, the coat rack in the corridor), `start` (B: "…come back"), `largest_room_doorway`
  (C: "…wait in the biggest room"). A first.
- **Other fields:** what to explore (`all_rooms`, or named rooms), what to report (room sizes, room
  types, objects seen), limits (time, rooms to avoid), the mode for exploring (`auto` or `brain`,
  [RFC-0002](RFC-0002-robot-brain.md) §3.1).
- **The LLM only translates and plans.** The spec is checked against the schema; anything outside
  it is refused, and an unclear instruction gets a question back, not a guess.
- **Evaluated offline and cheaply:** sentences paired with the spec each should become are an
  eval-harness dataset; the candidate models are its arms. No robot needed.

### 2.2 Models (decided with homelab, 2026-11-13)

Behind LiteLLM, the homelab's OpenAI-compatible gateway, under aliases owned by the brain, with a
key (`~/robotics-brain-litellm.env`, mode 600, never committed) that reaches only these:

| Alias | Model | Use |
| --- | --- | --- |
| `robot-vlm` | Qwen3-VL-30B-A3B-Instruct (open weights, 3B active) | eyes |
| `robot-planner` | same | planner (calls tools) |
| `robot-vlm-gemma` | Gemma 4 26B-A4B (open weights, 4B active) | second candidate |

- Operator's direction: open-weight models that can also run on the DGX; budget "whatever we need"
  (the cap is $10 per 30 days today, raised on request).
- Phase 1 (now): served from the cloud. Phase 2: a local vLLM on the DGX (`:8006`, in the
  `robotics` GPU mode) once eval-harness has picked a model; the aliases move, the code does not.
- Checked: one call to each alias returned HTTP 200 (0.4–1.7 s); another alias with the same key
  returned 403.

### 2.3 Perception

- **Frames:** `GET /frame` from the duck's console, on the robot and in the simulator alike.
- **Questions, not control:** "which room type is this?", "is there a coat rack? where in the
  image?", "how big does this room look?".
- **From image to map:** the model's bounding box plus the camera intrinsics (`media.video`) give a
  bearing; the depth sensor gives range when close; the result is an object with a position.
- **In auto mode the brain only watches:** it copies the map, takes frames at the duck's survey
  stops, labels rooms, records objects — the data for the end of the mission and for later
  evaluation.
- **Simulation caveat:** the simulated apartment is textured boxes. Room labelling there is
  plausible but says little about a real home; phase-3 accuracy in the simulator does not transfer.

### 2.4 World model

The map (a copy of `map.grid`); rooms (free-space segments split at doorways, each with the vision
model's label); objects with positions and when last seen; the mission's progress. **Room size** is
a segment's free area and bounding box — rough by design. Saved with the run record.

### 2.5 Planner tools

| Tool | Does |
| --- | --- |
| `set_mode(auto \| brain)` | switch who drives |
| `explore()` | next frontier, then a survey (brain mode) |
| `survey()` | stop, head sweep, until `mapd` collects |
| `go_to(x, y)` / `go_to_object(id)` | navigator goal |
| `go_to_start()` | end B |
| `go_to_room_doorway(room)` | end C |
| `look(question)` | one frame to `robot-vlm`, answer stored |
| `rooms()` / `objects()` | read the world model |
| `report(text)` / `stop()` | finish |

The planner sees summaries, not raw frames or the full grid. Every call is logged with latency and
cost.

### 2.6 Choosing models with evidence

Two datasets for eval-harness: sentences → mission specs (§2.1), and frames from survey stops with
the right room type and objects. Arms: the candidate models plus a no-model baseline; quality,
latency, cost, and whether the difference is real.

## 3. Non-goals

- Training or fine-tuning vision models (later, if evaluation shows a need).
- Visual odometry: upstream found it fails on a bobbing biped; position comes from legs and gyro.
- Models in the walking or navigation loops.

## 4. Open questions

1. Latency in practice: 1–3 s per answer is the target; measured in phase 3.
2. One model for eyes and planning, or a small fast one for eyes.
3. Room segmentation, and how much the vision model's estimate helps sizing.
4. How the operator confirms a mission spec: the web UI, chat, or flotilla's approvals
   ([RFC-0005](RFC-0005-missions.md)).

## 5. Alternatives considered

- **Providers called directly from the brain:** rejected; LiteLLM gives one endpoint, keys and
  budgets, and lets the model move without code changes.
- **Free-form plans from the LLM, no spec:** rejected; a fixed schema is checkable, explainable to
  the operator, and testable offline.
- **Closed models first:** possible, but the operator chose open weights runnable on the DGX.
- **An object detector only:** cannot answer "which room is this?"; may join later as a fast pass.

## 6. Discussion

- 2026-11-13 — Homelab proposed LiteLLM aliases; the operator chose open-weight models runnable on
  the DGX and approved phase 1; aliases and a second candidate went live.
- 2026-11-14 — Split out of the robot brain draft at the operator's request.
- 2026-11-14 — Review: local models in robotics mode take the DGX's prod down. Operator: dismissed —
  this is a playground and prod only matters at night, so daytime robotics windows are fine.
- 2026-11-14 — Operator: missions in plain words, with end options A (landmark), B (start) and C
  (largest room) passed with the mission; A first. Revision 2 adds §2.1 and the tools for them.
