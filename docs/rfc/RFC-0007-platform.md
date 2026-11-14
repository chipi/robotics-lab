# RFC-0007 — The platform: an open alternative to Foxglove, assembled from our tools

**Status:** Proposed (2026-11-14) — the operator's vision, for review. It amends
[ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md) decision 3 and
[RFC-0006](RFC-0006-mission-control.md) §3.3 (see §6).
**Builds on:** [RFC-0006](RFC-0006-mission-control.md) (mission control),
[RFC-0005](RFC-0005-missions.md) (the mission loop), [EVAL-HARNESS-ASKS.md](../wip/EVAL-HARNESS-ASKS.md),
[FLOTILLA-ASKS.md](../wip/FLOTILLA-ASKS.md).

## 1. Motivation

Foxglove (foxglove.dev) is a commercial observability and data platform for robotics: record,
store, search, view, compare, connect to devices, teleoperate. Asked whether we were rebuilding
it across the operator's projects, the answer was "partly". The operator's direction
(2026-11-14): **make that deliberate.** Learn from Foxglove, but aim for a platform where the
operator's own tools, plus a few open-source projects and a few new ones, cover every need a robot
lab has — an open, local-first alternative.

## 2. The five needs and who covers them

| Need | Component | Kind |
| --- | --- | --- |
| **Command and keep safe** — missions in words, planning, navigation, driving, deadman, STOP | **Mission control** + the robot brain + robot adapters ([RFC-0006](RFC-0006-mission-control.md), [RFC-0002](RFC-0002-robot-brain.md), [RFC-0003](RFC-0003-robot-interface.md)) | **New** (ours; grows from `nxt-web`) |
| **Record and store** — every run as a recording; index by robot, time and topic; events and annotations; search; retention | **MCAP** (the open log format) + a **logbook** service | MCAP reused; logbook **new** |
| **See** — live and recorded: maps, paths, poses, camera, plots, timelines; compare runs visually | **Rerun** or **Lichtblick** (chosen by a spike, §4) + our own panels | Reused, extended |
| **Judge** — is a version really better; does the simulator predict reality | **eval-harness** (0.9 asks: E1–E14) | Ours, extended |
| **Govern** — what may act without asking; approvals; autonomy earned on evidence; audit | **flotilla** (F1–F16) | Ours, extended |

Cross-cutting pieces that already exist and are reused:

- **Models:** LiteLLM aliases, the DGX ([RFC-0004](RFC-0004-perception-and-planning.md)).
- **Operational telemetry:** the homelab's observability stack (VictoriaMetrics, VictoriaLogs,
  VictoriaTraces, Grafana) for robot health numbers and service logs — battery, link quality, command
  times, errors. Recordings (high-rate, multimodal) go to the logbook, not there.
- **Simulation:** MuJoCo and Pollen's `duck-sim`; the arena.
- **Interfaces everywhere:** MCP and Slack on every component that a person or an agent talks to.

## 3. How it fits together

```text
             ┌──────────────── flotilla (govern) ────────────────┐
             │  missions as cases · approvals · autonomy · audit  │
             └───────────────┬───────────────────▲────────────────┘
                     decide  │                   │ evidence
┌──────────────────────────────▼──────┐   ┌────────┴──────────────────┐
│ mission control (command, safety)   │   │ eval-harness (judge)      │
│ brain · navigator · robot adapters  │   │ sim vs real, versions,    │
│ page · MCP · Slack                  │   │ rehearsal trust           │
└──────────┬───────────────▲──────────┘   └────────▲──────────────────┘
   commands│               │ live data             │ runs, scores
           ▼               │                       │
      robots / simulators ─┴──► MCAP ──► logbook (record, store, search, events)
                                            │
                                            ▼
                              viewer (Rerun or Lichtblick + our panels)
     telemetry numbers ──► homelab observability (Grafana)
```

## 4. What we build, reuse and learn

**New:**

1. **Mission control** — RFC-0006.
2. **Logbook** — a local-first recording store: MCAP files on disk, an index (robot, mission, time,
   topics, outcome), events and annotations, search, retention, an API and MCP; serves files to the
   viewer and runs to eval-harness. Small at first: a folder and an index.
3. **Viewer panels** — the robotics-lab views the chosen viewer lacks (a mission timeline, the
   brain's decisions, the mission spec), as its extensions.

**Reused (open source):** MCAP; Rerun (Apache-2.0 / MIT) or Lichtblick (MPL-2.0, a fork of the last
open-source Foxglove Studio); nxt-python; Pollen's Microduck stack; MuJoCo.

**Extended (the operator's):** eval-harness, flotilla.

**Learned from Foxglove:** MCAP as the one format; layouts and panels; events and annotations on
recordings; indexing by device, time and topic; multi-run comparison; an on-robot agent that ships
recordings; MCP for driving the viewer.

**The viewer spike:** record one real NXT run and one simulated duck run as MCAP; open both in Rerun
and in Lichtblick; compare live streaming, map and camera display, timelines, run comparison,
extension effort, and how each works on a phone. The result picks the viewer; the Foxglove app
stays usable for MCAP in the meantime.

## 5. Principles

- **Local-first:** a home robot films inside a home; recordings stay on the operator's machines.
- **Open formats:** MCAP for recordings, JSON-RPC and ROS-shaped messages for robots
  ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).
- **Each component stands alone** and is useful without the others; together they are the platform.
- **Open source:** mission control and the logbook are meant to be released (licence to choose;
  the operator's projects use MIT).

## 6. What this changes

- **ADR-0001 decision 3** ("Foxglove from the start"): MCAP from the start is unchanged; the
  Foxglove app becomes an interim viewer, and the target is an open-source viewer in our platform.
  A new ADR records this once the viewer spike has chosen.
- **RFC-0006 §3.3** ("show and store" owned by Foxglove): owned by the logbook and the chosen
  viewer instead; mission control still does not grow its own plots and history views — it links to
  the viewer.

## 7. Order

1. MCAP recording from mission control (`nxt-web` first).
2. The viewer spike (Rerun vs Lichtblick).
3. A minimal logbook: a folder, an index, search, events.
4. eval-harness reads runs from the logbook (with its 0.9 asks).
5. flotilla cases reference logbook recordings.

## 8. Open questions

1. Rerun, Lichtblick, or both (Rerun for live and robot-learning data, Lichtblick for a
   Foxglove-like workspace)?
2. The logbook: its own project, or part of mission control at first?
3. A name for the platform.
4. Whether the logbook also serves non-robot traces (flotilla's agent runs, eval-harness runs), which
   would make it useful beyond robots.

## 9. Alternatives considered

- **Use Foxglove for record, store and see** (RFC-0006 revision 1): least work, but commercial,
  cloud-centred for storage and search, and not ours to extend or release.
- **Build a viewer from scratch:** a large project; Rerun and Lichtblick already exist and are open.
- **ROS 2 tools (RViz, rosbag2):** need ROS ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).

## 10. Discussion

- 2026-11-14 — Operator: "I see all I do as a possible alternative to Foxglove, so we can learn from
  there, but I want with my tools to be able to do all 5 needs … this to be our vision for all these
  things together … a platform assembled out of a few open-source projects and some new ones we need
  to build."
