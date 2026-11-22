# Phase 5, step 1: the installation file and profile versions (design for review)

RFC-0023 §7 step 1, from decisions D9 (a machine's settings leave the profile) and D10 (a setting is
changed in Mission Control as a new profile version; export, import, diff). This note is the design
put to the advisor before anything is built (the operator, 2026-11-22: "lets first do review with
advisor").

## What exists today (read 2026-11-22)

- **The robot's profile:** `robots/duck/profile.json`, in the repository, schema and validator in
  `libs/runfile/src/runfile/profile.py` (`validate_profile`, `merge_variant`, `load_profile(path,
  variant)` → `Profile`). Blocks with `measured` and `why`; variants `sim` and `real`; `plugins`
  (`duck-walk@1` …). No version field beyond `profile_version` (the schema's version, 1). Its `sim`
  variant has an `adapter` block (`type: duck-sim`, `navigator: 127.0.0.1:8061`, `observatory:
  http://127.0.0.1:8070`): this machine's addresses inside the robot.
- **Mission Control's robot files:** `apps/mission-control/robots.sim/duck-sim.json` (and
  `robots.example`, `robots.nxt`): `id`, `label`, `kind`, `adapter` (type and this machine's
  addresses; Mission Control reads this one, `robots.py:57`), and a `factsheet`, `control`,
  `capabilities` and `rates` that repeat parts of the profile. Read and checked by
  `mission_control/robotfile.py`, which re-exports the profile's validator.
- **The host file:** `~/.config/robotics-lab/host.json` (`libs/simhost`, RFC-0021): one machine's
  simulator: its kind, the robot's name there, Pollen's checkouts, the state folder, the truth port,
  the sockets.
- **What a run records of its profile:** the navigator's `calibration` event: `profile: {id,
  variant, plugins}` and a few numbers (odometry scale, the depth sensor's mounting, pivot speed). No
  version or checksum: two runs with different profile numbers can not be told apart by it.
- **The Observatory:** its data folder from `OBSERVATORY_DATA` or `--data`, its index from
  `OBSERVATORY_INDEX` (default a path on this workstation, K44).
- **The runner:** finds a robot by name (`labrunner.robots`, the entry point), loads its profile from
  the path the robot registers.

## The proposal

**A. One installation file per machine, extending the host file rather than adding a fourth file.**
`host.json` becomes the machine's file: what it already holds (the simulator, when the machine has
one) plus `observatory` (URL), `data` (the runs' folder), `index`, `telemetry` (OTLP endpoints per
signal, the environment label) and `robots` (per robot on this machine: the navigator API's address,
the gate's socket, the profile's source). `simhost` keeps reading its part; a small reader in
`runfile` reads the rest. A machine with no simulator (a real robot's controller) has the file with
no `kind`. The profile's `sim.adapter` block is removed; Mission Control's robot files keep only
what is Mission Control's (the robot's `id`, `label`, the adapter `type`) and take addresses from
the installation file.

**B. Profile versions in a store, the repository's file as the seed.**

- A profile's identity is its id plus a content checksum (sha256 of the canonical JSON, the schema
  validated). Every run records `{id, variant, version, checksum}` in its run record and in the
  calibration event.
- Mission Control keeps versions under its state folder: `profiles/<id>/<n>.json` plus `current`;
  version 1 is the repository's `profile.json` as found. An edit is made on a copy, validated, saved
  as `n+1` and made current; it applies from the next run (a run that has started keeps the version
  it started with).
- The runner and the navigator read the current version from the installation file's `robots.<name>.profile`
  (a path to a file); with none, the repository's file (today's behaviour).
- Export: one JSON file (the profile, its version, checksum, the variant values). Import: validated,
  the checksum checked, saved as a new version. Diff: two versions, block by block, leaf by leaf.

## Questions for the review

1. Extending the host file (A) or a separate installation file: which keeps the boundaries cleaner
   (simhost is the standard library only and knows simulators; runfile knows runs)?
2. Versions in Mission Control's state folder (B): the navigator runs where Mission Control may not
   (a course on another machine). Should the store be the repository (versions as commits), a file
   store any process reads, or the runs themselves (each run carries its full profile)?
3. Should each run carry the whole profile (a few KB) rather than a reference, so a run explains
   itself with no store?
4. What breaks: the runner, `duck_lab.profile.load`, Mission Control's robot files and their tests,
   the Observatory, RFC-0020's validator. What is the smallest order that keeps every step green?
5. Anything in this design that a second robot (an EV3, a TurtleBot3) or a second machine would
   break.

## The review (the advisor, Fable, 2026-11-22), and the design as revised

Verified by the lead against the code before taking it: the profile's `variants.sim.adapter` is
read by no running code (its schema entry and a test only); Mission Control reads the odometry
scale once, at start (`duck.py:269`); the replay rebuilds a run's profile from the repository's
current file, not the run's (`replay.py:55-58`); the host file refuses unknown keys
(`host.py:83-85`) and requires Pollen's checkouts, so no non-Pollen machine could have it.

What changes, and why:

1. **A separate installation file, not the host file** (`~/.config/robotics-lab/installation.json`,
   read by `runfile.installation`, standard library). Extending the host file would loosen its
   unknown-keys rule, exclude every machine without Pollen's simulator, and sit in the file the
   runner deliberately hides from the navigator.
2. **The version store belongs to the installation, one writer.** `profiles/<robot>/<n>.json` and
   `current` under the installation's `state` folder; Mission Control writes, the runner reads. No
   silent fallback: a robot whose installation entry names a profile that does not exist is refused
   (the design's "else the repository's file" would run version 1 while the run claimed otherwise).
   With no entry at all, the repository's file, recorded as `source: repository`.
3. **The run carries the whole merged profile** (about 12 KB), with `version`, `checksum` and
   `source`: the replay and the Observatory's "the robot as it was" read the run, not today's file.
4. **The checksum is the identity across machines; the version number is a local label.** Import
   matches on the checksum.
5. **Mission Control takes the scale per goal run** (from the run's calibration event or the current
   version), not once at start.
6. **One name per robot:** the installation keys robots by the entry-point name (`duck`); Mission
   Control's robot file gains `"robot": "duck"`; the host file's `robot` stays the simulator's
   instance (`duck-a`). Versions are keyed by that robot name, so two ducks on one machine keep two
   chains.
7. **No `telemetry` block yet:** step 6 decides its shape; a guessed block would be a breaking
   change later (unknown keys are errors).

The commit order and the tests are the review's (six commits, each green; must-fail cases: a
named profile that does not exist refuses to start a navigator; an import whose checksum does not
match its profile is refused, nothing written). To check before commit 3: the run format's limit on
one event's size (about 12 KB).
