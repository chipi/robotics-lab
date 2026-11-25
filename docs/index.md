# robotics-lab

A robot platform where any robot can be loaded: the operator's LEGO Mindstorms NXT 2.0 and EV3s,
Pollen Robotics' Microduck (in simulation first), and a TurtleBot3 later. A robot brings a profile
and plugins, a simulator brings a host, a navigator is tested behind a runner that judges it by the
simulator's truth, every run is recorded one way and watched in the Observatory, and the operator
drives it all from Mission Control.

## Where to start

- **How the pieces fit:** [How the platform fits together](architecture.md).
- **Where do things stand?** [The handover](wip/HANDOVER.md) is the living status;
  [the phase 5 plan](wip/PHASE5-NEXT-PLAN.md) has the items and the wrap-up order;
  [the plan we execute on](wip/EXECUTION-PLAN.md) is the plan as written, with each phase's history.
- **Proposals:** [Proposals (RFC)](rfc/README.md).
- **Accepted decisions:** [Decisions (ADR)](adr/README.md).
- **Ideas and notes:** [In progress](wip/README.md).
- **How it got here:** [History](history/README.md).

## Projects in this repo

| Folder | What |
| --- | --- |
| [`apps/observatory/`](https://github.com/chipi/robotics-lab/tree/main/apps/observatory) | The Observatory: every run, live and replayed |
| [`apps/mission-control/`](https://github.com/chipi/robotics-lab/tree/main/apps/mission-control) | Mission Control: robots, sites, goals, STOP |
| [`apps/nxt-web/`](https://github.com/chipi/robotics-lab/tree/main/apps/nxt-web) | The NXT: Python control, web UI, NXC programs for the brick |
| [`libs/simhost/`](https://github.com/chipi/robotics-lab/tree/main/libs/simhost) | The simulator host: the host file, the reset, the truth sampler |
| [`libs/runner/`](https://github.com/chipi/robotics-lab/tree/main/libs/runner) | The runner: starts a navigator as a payload, judges it by the truth, writes the official run |
| [`libs/runfile/`](https://github.com/chipi/robotics-lab/tree/main/libs/runfile) | The run format |
| [`libs/gate/`](https://github.com/chipi/robotics-lab/tree/main/libs/gate) | The robot gate: one driver per robot |
| [`libs/worldmodel/`](https://github.com/chipi/robotics-lab/tree/main/libs/worldmodel) | Objects, the semantic map, sites |
| [`libs/web/`](https://github.com/chipi/robotics-lab/tree/main/libs/web) | The web library both apps share: tokens, fonts, the 3D stage, the palette |
| [`robots/`](https://github.com/chipi/robotics-lab/tree/main/robots) | Each robot: the duck's profile, plugins and navigator; the robots' descriptions and meshes |

Pollen's own code (the Microduck's simulator and services) is not in this repository: each machine
that runs the simulator has its checkouts, named in its host file (`simhost init`,
[RFC-0021](rfc/RFC-0021-sim-host-and-payload.md) §4; [MICRODUCK.md](wip/MICRODUCK.md)).

---

Source on GitHub: [chipi/robotics-lab](https://github.com/chipi/robotics-lab).
