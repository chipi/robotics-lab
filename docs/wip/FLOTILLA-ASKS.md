# What robotics asks of flotilla

Written 2026-11-14 for the operator and the flotilla session (homelab), to assess and plan the
integration in flotilla's own process (its RFCs and ADRs). Nothing here is decided for flotilla:
these are the robotics side's needs, with what we already know about where they fit and where they
rub. flotilla terms as of `eee98c9`: cases (ADR-0005), host agent (ADR-0006), one autonomy scale
(ADR-0008), routines (ADR-0007), memory and knowledge (ADR-0010), tools and actions (ADR-0011),
fleet packs (ADR-0013), operator UI (ADR-0014).

Sources on the robotics side: [RFC-0002](../rfc/RFC-0002-robot-brain.md) (robot brain),
[RFC-0003](../rfc/RFC-0003-robot-interface.md) (robot interface),
[RFC-0004](../rfc/RFC-0004-perception-and-planning.md) (missions in words),
[RFC-0005](../rfc/RFC-0005-missions.md) (the mission loop),
[STRETCH-EVAL-FLOTILLA.md](STRETCH-EVAL-FLOTILLA.md) (the first idea list; its "shadow = simulator"
wording is superseded by RFC-0005 revision 2).

## 1. The picture

The robots: a Pollen/Hugging Face **Microduck** (walking biped; its own Linux and JSON-RPC daemons)
and a **LEGO NXT** (a microcontroller brick driven from a PC or a Pi riding on it). The **robot
brain** (ours, Python) turns an instruction in plain words into a mission and runs it: a planner
(LLM) and a brain (world model, perception) decide; a **navigator** runs the fast loop (10–20 Hz)
next to the robot; the robot balances and stops on its own deadman (500 ms on the duck; a planned
on-brick deadman on the NXT).

Agreed direction (operator, 2026-11-13/14): a mission is a flotilla case; **the simulated duck is a
second host at `auto` and every mission rehearses there before it runs on the real duck**; eval-
harness evidence is what the operator promotes on. flotilla's `shadow` keeps its meaning (plans
recorded, nothing done).

```text
instruction ─► flotilla case ─► rehearsal on host duck-sim (auto) ─► policy for host duck
             ─► approval (propose) with rehearsal score + camera frame + route ─► host agent
             ─► mission runs (brain + navigator, robot's own safety) ─► check from sensors/vision
             ─► close ─► run record ─► eval-harness ─► evidence for promotion
```

## 2. The asks

| # | Ask | Maps onto | Friction / open |
| --- | --- | --- | --- |
| F1 | **A mission is a case**: one per instruction, the mission spec (RFC-0004 §2.1) attached, stages plan → rehearse → approve → execute → check → close | Cases (ADR-0005) | A "rehearse" step inside the case, before the decision for the real host |
| F2 | **Robot hosts**: `duck-sim` (autonomy cap `auto`), `duck`, `nxt` — each earning autonomy separately | Host agent, host autonomy cap (ADR-0006, ADR-0008) | Where a robot host agent runs: next to the robot on the LAN (workstation, a Pi on the NXT) or on the robot (the duck is a Linux computer). The duck runs Pollen's OS image; installing on it is a later decision |
| F3 | **Robot actions** with risk and reversibility: `start_mission`, `set_mode` (auto / brain), `survey`, `go_to`, `stop`, `fire`, `grab`, `pull` | Tools and actions (ADR-0011) | Moving is mostly reversible; firing, grabbing, pulling are not → always `propose`. Reads (map, rooms, frames, state) are tools |
| F4 | **The timescale split**: flotilla decides *whether and which* mission and approves risky steps; the brain and navigator run *inside* one action for minutes | Host agent executions (ADR-0006) | ADR-0006's exact argv templates with a 10-minute signature expiry fit a long-lived, supervised process poorly. A robot host ADR is likely needed: an action that starts, supervises, reports progress, and can be stopped |
| F5 | **flotilla never in the motion loop**; the robot's deadman and the navigator's stops are below it | — | A design rule to state, not a feature |
| F6 | **The freeze as an e-stop for every robot** | The freeze (ADR-0014 amendment: lowers everything to `shadow`) | Lowering to `shadow` stops new actions; a running mission must also be told to stop (`robot.stop`). Today every STOP path runs on the workstation; the on-robot deadman is the backstop |
| F7 | **Holds**: "no missions at night", "dog in the living room", "operator not home" | Holds (ADR-0005 guardrails) | Holds from home-automation state |
| F8 | **One mission per robot** | Per-target lock (ADR-0005) | The brain also names itself per run and refuses a second driver (RFC-0002 §3.6) |
| F9 | **Circuit breaker**: e.g. three falls or two lost-localisation aborts → the robot's missions stop until the operator resets | Circuit breaker (ADR-0005) | |
| F10 | **Approvals with evidence**: the rehearsal score, a camera frame, the planned route; on the phone and in Slack | Approvals, operator UI (ADR-0014), Slack | Images in an approval |
| F11 | **Check step from sensors**: "1 m from the coat rack?" answered by odometry + the vision model | The checking stage (ADR-0005) | The check runs a model; its own reliability is measured by eval-harness |
| F12 | **A robotics worker role**: the planner as a flotilla worker — reads through named tools, plans actions, never runs them; models through the LiteLLM aliases `robot-planner`, `robot-vlm` | Workers, model client (ADR-0004/0005) | Whether the planner lives in flotilla's runtime or in the robot brain process calling flotilla |
| F13 | **Memory and knowledge**: maps, rooms, objects seen, mission history ("where was the table last time?") | Memory and knowledge (ADR-0010) | Maps are large binary-ish data; probably a reference to the robot's map, not stored in flotilla |
| F14 | **Promotion tied to evidence**: the promote button shows N runs, success rate, the eval-harness significance result, the rehearsal false-pass rate | Autonomy promotion (ADR-0008) | Needs a link from flotilla to eval-harness results |
| F15 | **A robotics fleet pack** | Fleet packs (ADR-0013) | Routines below |
| F16 | **Several robots in one case** (later): the duck watches, the NXT drives | Cases, hosts | After one robot works end to end |

### Routines for a robotics fleet (F15)

1. **Missions** — triggered by the operator (words), a schedule, or a home-automation event
   ("motion at night → patrol").
2. **Robot ops** — low battery, stuck, fallen, lost → a case with a fix (back up, stop, call the
   operator).
3. **Training** — ask for a DGX `robotics` GPU window (a GPU mode switch is a host action needing
   the operator's approval), train a walking policy (`microduck_rl`), race it in the arena, report
   with evidence. Brings the homelab's GPU-mode switching under approvals and the case timeline.
4. **Evaluation** — run records → eval-harness → the evidence attached to promotion (F14).

## 3. What the robotics side does meanwhile

flotilla's cases, policy and host agents are not built yet (README; the host agent is planned). The
robot brain is built standalone first **in flotilla's shapes** so plugging in is wiring:

- missions as case-like run records (stages, plan, decision, execution, check, outcome);
- actions with risk and reversibility; reads as tools;
- an allowlist for the planner;
- the simulated duck as a separate "host" in configuration.

## 4. What the robotics side asks the flotilla session

1. **Assess** each ask (F1–F16): fits as is / needs a change / out of scope, against flotilla's
   ADRs and their non-goals.
2. **The robot host**: is it a new ADR (long-lived supervised actions, robots as hosts, the
   rehearsal step), and what would it contain?
3. **Order**: which asks can come with what flotilla is building now, which wait.
4. **What the robot brain should expose** to make the integration simplest (an API shape, events,
   the run-record format).

## 5. Not decided / not verified

- Where a robot host agent runs (F2).
- Whether flotilla stores anything robot-specific (maps, frames) or only references.
- Whether the planner is a flotilla worker or a robot-brain component (F12).
- flotilla facts here are from its ADRs at `eee98c9`; the host agent's state (planned, skeleton
  started) was not verified in code.
