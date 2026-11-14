# Review of all RFCs, round 2 (2026-11-14)

Second independent, read-only review, run by the `advisor` agent on Fable 5 at the operator's
request, over RFC-0001 to RFC-0005 and ADR-0001 (with the notes for consistency). Checked against
`microduck` `094d4bb4`, the `microduck_rl` apartment scene, nxt-python 3.5.1, the `nxt/` code,
flotilla and eval-harness. The robotics-lab session re-checked the `/frame`, flashlight, stop-rule
and stop-on-connect findings in the source before applying anything.

## Verdict (reviewer)

13 of the first review's 15 findings were fixed; one partly (the stretch note still said "shadow =
simulator"); one regressed into a wrong statement (`/frame` on the LAN). Nothing blocks phase 0.
The serious gaps were on the NXT side: nothing stopped the motors on connect, and robotd-lite
collided with the web UI's program interlock.

## Findings and what was done

| # | Finding | Done |
| --- | --- | --- |
| MAJ-1 | `/frame` is the robot's loopback only since daemon 0.19 (`webrtc-console.md`); not on the LAN | RFC-0002 §2, §3.3, RFC-0004 §2.3: frames through the ssh tunnel (forward port 8080) or `duckctl open`. The error was the session's: the first review's claim was taken without checking |
| MAJ-2 | robotd-lite is a program; the UI refuses driving while any program runs | RFC-0003 §2.4 coexistence rule |
| MAJ-3 | Nothing stopped the NXT's motors on connect or server start | **Code:** motors idled on every connect, logged as "stop on connect" with the ports that were running; smoke check; hardware check `hw_stop_on_connect.py`. RFC-0001 §3.3 |
| MAJ-4 | `robot.flashlight` is refused in the simulator | RFC-0002 §3.1: mode lamp from phase 5; the brain tolerates the refusal |
| MAJ-5 | RFC-0003's NXT mapping too thin | RFC-0003 §2.1: state, speed calibration, `limited_by`, "a program drives" |
| MAJ-6 | Two bricks missing from RFC-0003 | RFC-0003 §2.5 |
| MAJ-7 | Safety: shooter fireable any time; no NXT obstacle stop from the PC; duck sees only forward; every STOP path on the workstation | **Code:** `shooter_enabled`, default off, Fire disabled until enabled; RFC-0001 §3.3; RFC-0002 §3.6 (operator in the room for real-duck missions); RFC-0003 §2.3 (robotd-lite first); RFC-0005 firing irreversible |
| MIN-1 | Exact `mapd` command for phase 0 | RFC-0002 §3.5 |
| MIN-2 | Zero twist counts as "not commanded" (deadband 0.02 m/s, 0.05 rad/s, `maploc/src/input.rs`) | RFC-0002 §3.8, open question closed |
| MIN-3 | `autod` surveys only with mapping on | RFC-0002 §3.1 |
| MIN-4 | The coat rack is a 4 cm pole the map will not hold | RFC-0002 §3.4: judged by camera and odometry; simulator ground truth |
| MIN-5 | RFC-0001 omissions | RFC-0001 §3.3, §7; **code:** a bad `since=` is a 400 |
| MIN-6 | RFC-0001 test coverage needs a "not covered" list | RFC-0001 §4 |
| MIN-7 | Message-box throughput | RFC-0003 §2.3: 200 ms, 0.5 s deadman, a no-reply write |
| MIN-8 | Stale lines | ECOSYSTEM, IDEAS, the stretch note marked superseded |
| MIN-9 | "Nav2 assumes a lidar" too strong | ADR-0001, RFC-0002: "Nav2's defaults assume a 360° range sensor" |
| nits | "hall" vs corridor; SIGTERM handler order; `s3_color_name`; Makefile hid test output | Applied; `make test-unit` now prints the whole log on failure |

## Not verified (reviewer)

NXT mailbox queue depth and overflow; whether motors stop when an NXC program exits; Bluetooth
master and slave at once; the relay's 400 notifications a minute; eval-harness's minimum items for
an interval; whether the simulated depth sensor sees the 4 cm coat rack; Nav2's sensor
assumptions; anything about the real duck.
