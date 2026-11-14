# Draft for Pollen: duck-sim odometry reads ~10 % long

**Status:** draft for the operator to read (2026-11-14). Not posted. Intended for
`pollen-robotics/microduck` as an issue, after the operator's go.

---

**Title:** duck-sim: robotd's odometry reads 7–15 % longer than the simulated trunk travels (backlash
scene, set v10); `mapping-design.md` says ~0.3 %/m

On `main` (094d4bb4), `scripts/duck-sim` on its default `backlash` scene with the pinned set v10,
robotd's odometry (`robot.state.odom.position`) reports more distance than the body server's trunk
actually travels, and more the slower the duck walks. `docs/design/mapping-design.md` §1 says the
twin drifts about 0.3 % per metre, so either that figure is from a different set or scene, or something
has changed.

This isn't a request for a particular fix. It's a note that, with the set a robot gets today, the
simulated duck's odometry is about 10 % long, which mapd then builds its map from.

**Measured.** Straight walks, 8 s each at the given `vx` (a `robot.move` every 100 ms, then an
explicit zero and 2 s to settle), three per speed, `DUCK_SIM_VIEWER=0`, `realtime` at 1.00x.
Odometry is `robot.state.odom.position` from `robot.subscribe` at 50 Hz (the latest state, read by a
separate thread); truth is the body server's `read` → `trunk`. Straight-line distance start to end.

| vx (m/s) | odometry (m, 3 runs) | truth (m, 3 runs) | truth / odometry |
| --- | --- | --- | --- |
| 0.2 | 2.66 (total of 3; truth ÷ ratio) | 2.26 (total of 3) | 0.849 |
| 0.3 | 1.155, 1.170, 1.165 | 1.063, 1.059, 1.058 | 0.911 (0.905–0.920) |
| 0.4 | 4.58 (total of 3; truth ÷ ratio) | 4.26 (total of 3) | 0.930 |

The same ratio, 0.909, came out of about 41 m of mixed walking and turning in the apartment scene
(with the backlash robot) over three navigation runs.

**Setup.**

- x86_64 Linux workstation, no GPU in use for the sim.
- microduck `094d4bb4` and microduck_rl `develop` `0daab160`, set v10 from `scripts/duck-sim`'s
  seeding.

**Not checked.** I haven't measured a real duck. One guess, not tested: the contact odometry works the
feet out from joint angles, and the backlash robot has ±1° of play in each joint, so a servo can turn
without the foot following — which would make the legs count more stride than happens, and more at
low speed where the play is a larger share of each step. If that is it, a robot (whose servos also
have play) might share it. A per-robot odometry scale in `robotd.toml` would let mapd and autod use
corrected distances; we are correcting it on our side for now.

**Possibly useful.** `simulation.md` §11 or `mapping-design.md` §1 could say which set and scene the
0.3 %/m was measured on (as #597 found for the walking numbers).

The measurement script: `duck/sim/probes/odom_vs_truth.py` in chipi/robotics-lab (link to add).

Investigated with an AI coding agent. I checked the numbers above by rerunning them.

---

**Notes for the operator (not part of the issue):**

- The 0.2 and 0.4 rows' per-run figures were not printed individually, only pooled; the 0.3 row has
  the three runs. Rerun with per-run output before posting if you want the table complete.
- The "x86_64 Linux workstation" line names no hardware beyond that; add what you are comfortable
  sharing.
- The backlash explanation is a hypothesis; the issue says so.
