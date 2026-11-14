# RFC-0004 — Perception and planning: the brain's models, tools and world model

**Status:** Proposed (2026-11-14). Phase-1 models live; the rest for review.
**Builds on:** [RFC-0002](RFC-0002-robot-brain.md) (layers), [MICRODUCK.md](../wip/MICRODUCK.md),
[EVAL-HARNESS-ROBOTS.md](../wip/EVAL-HARNESS-ROBOTS.md).

## 1. Motivation

The duck can walk to a point and keep a map. It cannot tell a kitchen from a hallway, recognise a
table, or turn "tour the rooms, then hide under the kitchen table" into steps. Those are the jobs
for a vision-language model and a planner, called from the brain every few seconds — never in the
control loop.

## 2. Proposal

### 2.1 Models (decided with homelab, 2026-11-13)

- **Behind LiteLLM**, the homelab's single OpenAI-compatible gateway, under aliases owned by the
  brain, with their own key (`~/robotics-brain-litellm.env`, mode 600, never committed) that
  reaches those aliases only:

  | Alias | Model | Use |
  | --- | --- | --- |
  | `robot-vlm` | Qwen3-VL-30B-A3B-Instruct (open weights, 3B active) | eyes |
  | `robot-planner` | same | planner (it calls tools) |
  | `robot-vlm-gemma` | Gemma 4 26B-A4B (open weights, 4B active) | second candidate |

- **Operator's direction:** open-weight models that can also run on the DGX; budget "whatever we
  need" (the cap is $10 per 30 days today, raised on request).
- **Phase 1 (now):** served from the cloud (OpenRouter). **Phase 2:** once eval-harness has picked
  the model, a local vLLM on the DGX (`:8006`, in the `robotics` GPU mode); the aliases move, the
  brain's code does not. The DGX cannot serve it next to prod (memory, and a second GPU user next
  to prod has wedged that host).
- Checked: one call to each alias returned HTTP 200 (0.4–1.7 s); another alias with the same key
  returned 403.

### 2.2 Perception

- **Frames:** the simulator's `/frame`; on the robot, `media.stream` to our receiver.
- **Questions, not control:** "which room type is this?", "is there a kitchen table? where in the
  image?", "are we under a table?", "how big does this room look?".
- **From image to map:** the model's bounding box plus the camera intrinsics (`media.video`) give a
  bearing; the depth sensor gives range when close; the result is an object with a position on
  the map.

### 2.3 World model

- The map (a copy of `map.grid`), rooms (free-space segments split at doorways, each with the
  vision model's label from survey stops), objects with positions and when they were last seen.
- **Room size** is the segment's free area and bounding box — rough by design, given a depth
  sensor that sees about half a metre.
- Kept per mission, saved with the run record; later, recall across missions
  ([RFC-0005](RFC-0005-missions.md)).

### 2.4 Planner and tools

An agent loop on `robot-planner` with a fixed tool allowlist:

| Tool | Does |
| --- | --- |
| `explore()` | go to the next frontier, survey |
| `go_to(x, y)` / `go_to_object(id)` | navigator goal |
| `survey()` | stop, head sweep, update map and rooms |
| `look(question)` | one frame to `robot-vlm`, answer stored |
| `rooms()` / `objects()` | read the world model |
| `do(skill)` | a robot skill (sit, a sound) |
| `stop()` / `report(text)` | end the mission |

The planner sees summaries, not raw frames or the full grid. Every call is logged with latency and
cost in the run record.

### 2.5 Choosing models with evidence

Model choice is an eval-harness question
([EVAL-HARNESS-ROBOTS.md](../wip/EVAL-HARNESS-ROBOTS.md), idea 3): frames captured in the simulated
apartment (later at home) with the right answers, both candidate models as arms, plus a no-model
baseline; quality, latency and cost compared, and whether the difference is real.

## 3. Non-goals

- Training or fine-tuning vision models (later, if eval-harness shows a need).
- Visual odometry: the duck's upstream found it fails on a bobbing biped; position comes from legs
  and gyro.
- Models in the walking or navigation loops.

## 4. Open questions

1. Latency budget in practice: 1–3 s per answer is the target; measure in phase 3.
2. One model for eyes and planning, or a small fast one for eyes and a larger one for planning.
3. Room segmentation method and how much the vision model's estimate helps sizing.
4. How the brain reaches frames from the real duck (`media.stream` needs a WebSocket the robot can
   dial).

## 5. Alternatives considered

- **Calling providers directly from the brain:** rejected; LiteLLM gives one endpoint, keys,
  budgets, and lets phase 2 move the model without code changes.
- **Closed models first:** possible through LiteLLM, but the operator chose open weights so the
  same model can run on the DGX.
- **An object detector only:** cheaper and faster, but cannot answer "which room is this?"; may
  join later as a fast first pass.

## 6. Discussion

- 2026-11-13 — Homelab proposed LiteLLM aliases; the operator chose open-weight models runnable on
  the DGX and approved phase 1; aliases and a second candidate went live.
- 2026-11-14 — Split out of the robot brain draft at the operator's request.
