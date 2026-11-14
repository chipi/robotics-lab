# Robot brain phase 0 — the spike: is the simulator a usable stand-in?

**Run:** 2026-11-14, against `duck-sim` headless at 1.00× real time. Stack: microduck `094d4bb4`
(release 0.21.1), microduck_rl `0daab160` (`develop`), policy set `seed-v10` (velstand,
checkpoint 1250). The question and the bars are [RFC-0002](../rfc/RFC-0002-robot-brain.md) §3.4.
Probes: `duck/sim/probes/` (each says what it measures); simulator truth is the body server's
trunk pose, not the daemon's odometry.

## Verdict

| Check | Bar | Result | Met? |
| --- | --- | --- | --- |
| Turning on the spot, backlash scene | within 20 % of upstream's ~50°/s at 0.8 rad/s | 0.7°/s from a stand; 26°/s once stepping | **No** |
| The backlash robot in the apartment | the duck walks there | walks and stays upright; slower and drifts more than on the plane | Yes, with limits |
| `mapd` with autonomy off | the map gains keyframes | 3 stops from 3 stops, with an explicit zero move first | Yes, with a workaround |

By RFC-0002's rule, a miss blocks phases 1–4 and sends RFC-0005's rehearsal back for review. What
the miss is, though, matters for that decision (below).

## 1. Turning

On the plane scene (`scene_backlash.xml`), 8 s per run, two runs per row:

| Asked (rad/s, on the spot) | From a stand (°/s) | After 2 s at 1.2 rad/s (°/s) |
| --- | --- | --- |
| 0.5 | — | 13.9 (48 % of asked) |
| 0.6 | 0.4, 0.4 | 17.0 (50 %) |
| 0.8 | 0.7, 0.7 | 26.3 (57 %) |
| 0.9 | 0.9, 0.9 | — |
| 1.0 | 0.9, 0.9 | — |
| 1.2 | 33.3, 35.3 (49 %) | — |

- **From a stand, the duck does not start stepping below about 1.1 rad/s.** Once stepping, it
  turns at about half the asked rate, as it walks at about 44 % of the asked speed forward.
- With forward motion: 0.3 m/s with 0.8 rad/s gave 21.5°/s and 0.09 m/s.
- Upstream (`docs/design/simulation.md` §11) measured 50°/s at 0.8 rad/s with `duck-sim drive`;
  the same command here gives 0.7°/s. Why the two differ is **not found**: same script, same
  scene; the policy set, the body server's commit, or both may differ from upstream's run.
- Ruled out: the commands reaching robotd (each `robot.move` is accepted, and its deadman trips
  only after a run ends), the simulator's speed (1.00×), limits in the sim's `robotd` config (none).

## 2. The apartment

Pollen's `apartment` scene carries the robot without backlash, on which velstand does not step.
`duck/sim/apartment_backlash.py` builds `scene_apartment_backlash.xml` from upstream's own files —
`scene_backlash.xml`'s keyframes with the full-collision backlash robot and `apartment.xml` — and
writes it next to them (an untracked file in the microduck_rl checkout, to offer upstream). It
loads (`nq 84`, 233 geoms) and `DUCK_SIM_SCENE=apartment_backlash scripts/duck-sim` stands the duck
up at its dock in the office.

- Facing open floor: 0.3 m/s asked for 6 s gave 52 cm (0.087 m/s; the plane gives 0.13), and the
  heading drifted 50°. Upright throughout (lowest trunk 0.112 m).
- Turning 148° at 1.2 rad/s took 16 s (about 9°/s; the plane gives 33°/s).
- The first walk from the dock ran into the office cabinet 8 cm ahead: start poses need checking
  against the furniture.

## 3. Mapping with autonomy off

`mapd`, built from the same workspace (offline, nothing downloaded), with `[map] enabled = true` in
a config copy of our own (`duck-sim` rewrites its own on every start) and the command in RFC-0002
§3.5.

- Its pose agreed with the simulator's to within 7 cm after walking.
- **It mapped nothing at first.** `mapd` maps a stop only when the robot is not commanded, and it
  reads "commanded" from robotd's *requested* twist. After robotd's deadman trips, the request
  stays at the last move (`robotctl monitor`: `req[+0.30 +0.00 +0.30] app[+0.00 +0.00 +0.00]
  [deadman]`), so a client that lets its intent expire leaves the duck "commanded" forever.
- **With an explicit zero move before each stop, it maps:** 1, 2 and 3 stops after 3 walks with
  8 s stops, and `robotctl map show` draws the office.
- For us: the navigator always ends with an explicit zero move. For Pollen (to offer): `mapd`
  could read the applied twist, or robotd could clear the request when the deadman trips — a pad
  or app that drops out would otherwise stop mapping too.

## What this means

- **The forward and turning shortfalls are one pattern:** in this simulator the duck moves at about
  half of what it is asked, and needs a kick to start turning on the spot. A navigator that closes
  the loop on heading and position (RFC-0002 §3.8) does not need the gain to be right, only
  stable; a planner that times moves open-loop does.
- **The bar was written against upstream's 50°/s**, which this stack does not reproduce. Two ways
  on, for the operator to choose:
  1. Keep the bar; first find why upstream's run differs (policy set, body server, BAM actuators —
     upstream's own first suspect for the forward shortfall).
  2. Change the bar to what phase 1 needs: turning that is repeatable (it is: two runs agree within
     2°/s) and a navigator that compensates (kick-start, closed loop), measured in phase 1's 20
     go-to goals.
- **Rehearsal (RFC-0005)** stands on "the plan is valid and avoids what the map knows", not on
  timing; nothing here changes that, and the rehearsal table already lists timing as not predicted.

## Not covered

- Why upstream's 50°/s differs from this run: not investigated past the three causes ruled out.
- Turning in the apartment from a stand (only with the 1.2 rad/s kick).
- The daemon's odometry against simulator truth, beyond one 7 cm agreement.
- Loop closures and relocalization: three stops along one line close no loop.
- The staircase hole and the cliff check (RFC-0002 §3.5).
- `mapd`'s CPU cost (phase 5, on the board).
- Repeat runs in the apartment (one run each).
