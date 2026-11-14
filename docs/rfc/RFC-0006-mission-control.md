# RFC-0006 — Mission control: the robotics product, and where it ends and flotilla begins

**Status:** Proposed (2026-11-14) — a vision, for the operator's review. The operator's direction:
the brain's UI is planned from the start as MCP, Slack and a small dev page, "like mission
control", that evolves later; everything robot-specific goes into it, growing from the NXT web UI
we already have, toward an independent, open-source robotics product.
**Builds on:** [RFC-0001](RFC-0001-nxt-web-ui.md) (the NXT web UI), [RFC-0002](RFC-0002-robot-brain.md)
§3.10 (the brain's API and its UIs), [RFC-0003](RFC-0003-robot-interface.md) (one robot interface),
[RFC-0005](RFC-0005-missions.md) and [FLOTILLA-ASKS.md](../wip/FLOTILLA-ASKS.md) (flotilla).

## 1. Motivation

Three things are growing at once: the NXT web UI (driving, sensors, logs, programs, diagnostics),
the robot brain (missions in words, navigation, perception), and the wish to run robots through
flotilla. Without a line between them, robot-specific code ends up in flotilla, and flotilla's
governance ends up re-built in robotics. The operator wants to see where the robotics side becomes
a product of its own.

## 2. The line

| | **Mission control** (robotics-lab, open source) | **flotilla** (the operator's agent platform) |
| --- | --- | --- |
| Its job | Operate robots: see them, drive them, give them missions, keep them safe | Govern agents and hosts: what may act without asking, and what happened |
| Knows about | Robots: motors, sensors, maps, frames, missions, simulators | Cases, policy, autonomy, approvals, hosts, credentials, audit — for any fleet |
| Robot-specific code | **All of it** | None: robots are one kind of host |
| Works alone | Yes: one home, a few robots, a simple "confirm the mission" | Yes: without robots |
| Together | Mission control becomes a flotilla fleet pack and host: flotilla's policy and approvals replace mission control's simple confirm, and flotilla's freeze stops the robots | |

The rule of thumb: **if it would only make sense for a robot, it belongs in mission control**; if it
is about whether an agent may act, it belongs in flotilla.

## 3. What mission control is

Grown from `nxt-web` and the robot brain; ROS-aligned terms ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)).

| Layer | Contents |
| --- | --- |
| **Robot adapters** | One robot interface (RFC-0003) with drivers: the NXT service, the Microduck, later a ROS 2 bridge |
| **Robot safety** | Deadman handling, STOP, stop on connect, interlocks, limits, the on-robot deadman programs |
| **Brain** | Missions in words → mission spec; planner, world model, navigator (RFC-0002, RFC-0004) |
| **Rehearsal** | Running a mission on a simulated robot first |
| **Records** | Run records in MCAP, the command log, recordings |
| **Interfaces** | The dev page ("mission control"), an MCP server, a Slack app, the command line; Foxglove for viewing |

### 3.1 The three interfaces, from the start

| Interface | First version | Grows into |
| --- | --- | --- |
| **Mission control page** | `nxt-web` generalised: robots list, per-robot drive and status, mission entry in words with the spec read back and a Confirm, live mode and progress, a big STOP, the command log | Several robots; mission progress; links into Foxglove for maps, camera, plots and past runs (§3.3) |
| **MCP server** | Tools: list robots, robot status, start a mission in words (returns the spec to confirm), stop, latest snapshot | The way to talk to robots from Claude or any agent |
| **Slack app** | Notifications (mission started, needs you, done, failed, robot down), simple commands (status, stop) | Approvals — handed to flotilla when it is connected, so approvals live in one place |

### 3.2 What it is not

- Not an agent-governance platform (that is flotilla).
- Not an evaluation framework (that is eval-harness; mission control produces the run records it
  reads).
- Not a viewer framework (Foxglove; mission control streams to it).
- Not ROS (it can bridge to ROS later).

### 3.3 What Foxglove already does, and mission control does not rebuild

Foxglove (foxglove.dev, read 2026-11-14) is an observability and data platform for robotics:
visualising recordings and live robots (MCAP, ROS bags), teleoperation, multi-run comparison,
recording through its SDK and an on-robot upload agent, indexing and search of recordings by
device, time and topic, events and annotations, fleet device connectivity, and MCP for its
layouts.

The line across the four:

| Job | Owner |
| --- | --- |
| **Command and keep safe**: missions in words, planning, navigation, driving, deadman, STOP | Mission control (this RFC) |
| **Show and store**: recordings, timelines, maps, camera, history search, visual run comparison | Foxglove |
| **Judge**: is a version really better; does the simulator predict reality | eval-harness |
| **Govern**: what may act without asking; approvals; autonomy on evidence | flotilla |

So mission control's page keeps the essentials (robots, status, drive, STOP, mission entry and
progress, the command log) and **links into Foxglove** for maps, camera history, plots and past
runs instead of growing its own. Recordings stay **local** (MCAP files, the desktop app); nothing is
uploaded to Foxglove's cloud by default, because a home robot films inside a home.

## 4. The open-source product

- **Who for:** people with a hobby or education robot or two (LEGO, Microduck, small ROS robots)
  who want missions in plain words, safety and logs, without running ROS or a fleet platform.
- **Shape:** one Python service with a web page, MCP and Slack, a Docker image (as `nxt-web` has),
  drivers per robot, and an optional flotilla integration.
- **Name:** not chosen.
- **Where it lives:** in robotics-lab now (`nxt/` is its first driver); a separate repository when
  the line in §2 has held for a while.

## 5. Order

1. Keep `nxt-web` working; add the robot interface (RFC-0003) under it.
2. The robot brain's phase 0–1 (RFC-0002) behind the same API.
3. The mission control page, the MCP server and the Slack app over that API.
4. The flotilla integration once flotilla's cases and host agents exist.
5. Split out as its own repository and name.

## 6. Open questions

1. The name.
2. When to split it into its own repository.
3. Slack: one app for mission control and flotilla, or two, with approvals moving to flotilla.
4. Licence (the operator's other projects use MIT).

## 7. Alternatives considered

- **Everything in flotilla:** robot code would pull flotilla toward one domain; flotilla is meant
  for any fleet.
- **Only flotilla's UI, no mission control page:** no place to drive a robot by hand or debug one.
- **A new UI from scratch instead of growing `nxt-web`:** throws away a working, tested UI.

## 8. Discussion

- 2026-11-14 — Operator: plan the brain's UI as MCP, Slack and a small dev page like mission control
  from the start; think of mission control vs flotilla as a product line, with everything
  robot-specific in mission control, growing from the NXT web UI toward an open-source product.
- 2026-11-14 — Operator: "it seems we are doing, in a mix of my projects, what foxglove.dev is all
  about?" Partly: Foxglove is the show-and-store slice. §3.3 draws the line (command / show /
  judge /
  govern) and takes history, inline maps and plots out of mission control's growth path.
