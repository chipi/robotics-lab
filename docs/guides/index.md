# User guides

Provisional guides for using the lab, written 2026-11-26 against main and run against the fake
robot, a fixture run and the simulated brick. Each starts with what the app is for, its key use
cases and the few words it uses, then walks through the basic steps with a screenshot each, and
ends with what it does not cover yet.

| Guide | For |
| --- | --- |
| [Mission Control](mission-control.md) | Operating robots: readiness, sites and areas, goals, watching a run, STOP |
| [The Observatory](observatory.md) | Watching and replaying every run: the 3D scene, belief against truth, the timeline, alarms |
| [The NXT web app](nxt-web.md) | Driving and debugging the NXT directly; the brick's gate that Mission Control drives through |
| [The lab from the command line](command-line.md) | The simulator, one run, the challenge course, scenario sets, training, the checks |

Start with Mission Control and the Observatory: a run started in one is watched in the other.

**Retaking the screenshots:** `make screenshots-guides` (Mission Control and the Observatory) and
`make screenshots-nxt`. They need no simulator; the Body and Explorer shots need the robot meshes
(`make robots`).
