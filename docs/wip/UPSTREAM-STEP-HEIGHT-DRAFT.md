# Draft for Pollen: duck-sim walks over about 1 cm; at 1.5–2 cm it stops or falls

**Status:** draft for the operator to read (2026-11-18). Not posted. Intended for
`pollen-robotics/microduck` (or `microduck_rl`, where the walking policy is trained) as an issue,
after the operator's go.

---

**Title:** duck-sim: the walking policy crosses a 1 cm bar or step up, not 1.5–2 cm (it stalls or
falls); speed does not change it (backlash scene, set v10)

On `main` (094d4bb4), `scripts/duck-sim` on its default `backlash` scene with the pinned set v10
(microduck_rl `develop` 0daab160), the walking policy steps over things up to about 1 cm high. At
1.5–2 cm it stops with its toes at the edge, or trips and falls. Walking faster does not help, and
walking slower makes it worse.

This isn't a request for a particular fix. A home's door thresholds, rug edges and cables are often
1–2 cm, so it seemed worth saying where the simulated duck's limit is today.

**Measured.** A straight corridor 1 m wide. The duck starts 0.6 m before the change and walks straight
at the given `vx` (a `robot.move` every 100 ms) until it is 0.25 m past it, until it is stuck (less
than 2 cm in 3 s), or for 30 s. "Fell" means the trunk dropped below 0.06 m (standing: 0.116 m).
Each trial resets the simulator on its scene. The floors are pieces meeting edge to edge (see the
note below).

Crossed of tries, at 0.3 m/s:

| Case | 0.5 cm | 1.0 cm | 1.5 cm | 2.0 cm |
| --- | --- | --- | --- | --- |
| A bar 4 cm deep across the way | 3/3 | 2/3 | 1/3 | 0/3, 2 fell |
| A step up | 3/3 | 3/3 | 0/3, 2 fell | 0/3, 1 fell |
| A step down | 3/3 | 3/3 | 3/3 | 3/3 |

A bar at 0.4 m/s, five tries each: 1.0 cm 4/5, 1.5 cm 0/5 (1 fell), 2.0 cm 0/5 (1 fell).

Slower: at 0.2 m/s a 1 cm step up was crossed 0 of 5 and a 1 cm bar 1 of 5, stalled with the toes
at the edge, no falls. At 0.15 m/s the duck did not start walking within 6 s.

Flights of three steps up, 0.25 m or 0.5 m treads, 0.5–1.0 cm risers: 0–1 of 3 reached the top;
each riser was cleared about 70 % of the time. Down, 1–2 cm risers: 3 of 3.

**How the scene is built matters.** A bar laid on top of a floor that runs under it was crossed 0 of
12 times, against 2 of 3 at 1 cm for the same bar built as three pieces meeting edge to edge. That
looks like a contact quirk of overlapping boxes rather than the policy, but it may be worth knowing
for anyone building test scenes.

**Setup.**

- x86_64 Linux workstation, no GPU in use for the sim.
- microduck `094d4bb4` and microduck_rl `develop` `0daab160`, set v10 from `scripts/duck-sim`'s
  seeding; `DUCK_SIM_VIEWER=0`, `realtime` at 1.00x.

**Not checked.** I haven't measured a real duck, or an angled approach to the bar, or a round cable.
Whether the policy saw obstacles of this height during training is something only you can say. If
it didn't, terrain with small bars and steps in training might be the way; we don't know.

The measurement script: `duck/sim/probes/step_height.py` in chipi/robotics-lab (link to add); the
results with more detail: `docs/wip/STEPS.md` there.

Investigated with an AI coding agent. I checked the numbers above by rerunning them.

---

**Notes for the operator (not part of the issue):**

- **Check before posting:** "I checked the numbers above by rerunning them" holds for the 0.4 m/s
  row (rerun 2026-11-18). The 0.3 m/s table, the slower speeds and the flights were measured once on
  2026-11-17 and not rerun. Rerun them, or soften that sentence, before posting.
- The trials are few (3–5 per cell); the pattern holds across cells, but no single number is
  precise.
- The two links need the repository's public URL.
- The "x86_64 Linux workstation" line names no hardware beyond that; add what you are comfortable
  sharing.
- Our side does not depend on this: the operator's apartment has no door thresholds (2026-11-18),
  and challenge 16 now uses 0.5–1.0 cm bars.
