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

## What was built (parts 1 to 5, 2026-11-22)

1. **The profile's schema** (`runfile.profile`): `adapter` gone, `joints.names` and `subsystems`
   added, `upgrade()` (a missing or newer `profile_version` is refused, an older one migrated),
   `checksum()` (sha256 of the canonical JSON).
2. **The installation file** (`runfile.installation`): `data`, `index`, `observatory`, `state`,
   `robots.<name>.{navigator, gate, profile}`. `gate` was added in part 5: Mission Control's way to
   the robot, which it had read from the host file.
3. **The run carries the whole merged profile** in its calibration event, with `checksum`,
   `version` and `source`. The replay rebuilds the robot from the run, not from today's file.
4. **The version store** (`runfile.profilestore`) and the registry (`runfile.registry`, read by the
   runner and Mission Control): a named profile that does not exist refuses the robot before any
   navigator starts. In part 5 the runner began handing the navigator the store's *folder*. The
   navigator reads that folder's current version at each goal (`profilestore.resolve`), so a version
   saved while `lab-nav-server` runs applies from the next goal with no restart. Before part 5, the
   runner resolved the version once, when it started. A long-lived navigator API then kept the old
   version, which contradicted D10 ("from the next run").
5. **Mission Control.**
   - The duck's robot file is a pointer (`robot`, `variant`, the adapter type). Its kind, factsheet,
     control, capabilities, guardrails and rates are the profile's, and the file may not repeat them.
   - The adapter imports neither `duck_lab` nor `simhost` (the boundary check's last exception is
     retired):
     - the state stream is its own `robot.subscribe` through the gate;
     - the map is the navigator API's `map`, which the navigator now answers between goals too;
     - the scale comes from the profile, read again at each goal's start;
     - the addresses come from the robot file, else the installation.
   - `goal.start` answers with the profile's checksum and version. When it differs from the version
     Mission Control read, the goal run gets a decision saying so.
   - The profile endpoints: view, save, go back, export, import, diff. Mission Control is the store's
     one writer. A save the installation would not run is refused.

Not built or not covered yet:

- **Mission Control's view of the robot** (factsheet, capabilities, guardrails, rates) is read once,
  at start. A saved version changes what `GET /robots/{id}` shows only after a restart.
- **A goal started by the runner's own commands** (`lab-go`, `lab-explore`) is not compared with
  anything. Only Mission Control checks the checksum.
- **The page has no profile editor.** The endpoints exist; the view is RFC-0023 step 2's.
- **This machine has no `installation.json` yet.** Mission Control with `robots.sim` needs one
  naming `robots.duck.gate`, or it refuses to start and says where to name it.
- **The fake and the NXT robot files still hold the robot themselves.** Neither has a profile.
- **The Observatory's `data` and `index`** still come from env vars (part 6, K44).
- **The gate gave every subscriber the last subscriber's rate. Fixed.** robotd streams one
  connection at its last subscribe's rate, and the gate passed every `robot.subscribe` straight
  upstream. So Mission Control's 5 Hz subscription, when it came after the navigator's, left the
  navigator at 4.7 to 5.1 states a second for whole goals, where its own stream is 10. That showed
  up as goals refused with "no pose on the map yet" and slower walks: sim_duck's area-then-max_speed
  failed 3 times out of 3, and HEAD (12728c6) passed it 3 times out of 3. The gate now asks robotd
  for the fastest rate any subscriber wants and streams each subscriber at its own rate
  (`labrunner.gate`, test_gate_proxy, mutation-checked). It passes on robotd's integer rate as
  given: robotd refuses `hz: 5.0` ("expected u32"), which a first version of the fix sent.
- **On the simulator, Mission Control reads mapd itself; the runner path is not understood.**
  `duck-sim` requires the map's socket (`robots.<robot>.map`, or `map_socket`), as it requires
  the gate's. With the map read through the runner, sim_duck's explore-then-inventory passed 1
  run in 8, even after the gate fix. Seeded objects near where explore ended were marked gone
  (8 looks expected in view, not seen; `worldmodel.semantic_map.forget`). The same sequence passed
  5 runs in 5 with Mission Control reading mapd itself, with its map poll off, or on HEAD. A
  runner answering a fixed grid, never reading mapd, failed 1 run in 2. The extra work measured is
  2.3 KiB a grid, parsed in 0.03 ms. Mission Control's `goal.status` polls at 5 Hz go through the
  runner either way. **The cause is not found.** A robot reached only through its navigator API
  (a real robot's, no runner) would read its map there; that case is not tested.
- **Mission Control's map poll is paced at the robot's `map_hz`.** Before, it asked for the map on
  every 0.1 s tick while the map did not change: 7 requests a second measured, against a map_hz
  of 1 (test_duck_adapter).
