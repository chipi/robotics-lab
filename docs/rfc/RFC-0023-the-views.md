# RFC-0023 — The views: the operator's journeys, which surface does what, and where the telemetry goes

**Status:** Accepted (2026-11-21: the operator chose A for all twelve decisions, §5). Phase 5's design
round: proposals and mock-ups for the operator to
decide, decision by decision, before anything is built (the operator, 2026-11-20: "I don't want to
rush. I want to consolidate all of these things and make a round of how exactly we're going to do
that and in which surfaces. I'd like to see some proposals and some mock-ups"). The round's inputs
are the plan's phase 5 ([EXECUTION-PLAN](../wip/EXECUTION-PLAN.md)), RFC-0019's anomaly views,
RFC-0020's robot page, RFC-0014's control panel and the map of the platform
([How the platform fits together](../architecture.md)).

## 1. What phase 5 is for

The platform runs a robot end to end today: a profile and plugins, a host, a navigator behind a
runner, the Observatory for runs, Mission Control for goals. What it lacks is the operator's side
of it as one experience: setting a robot up and trusting it before a mission, seeing what it does
and what is wrong while it works, and finding out why afterwards, with the robot's telemetry going
to the operator's own observability stack instead of piling up in ours.

## 2. The journeys

Each journey is the operator's, in their words where they gave them; each names what they must be
able to do and what good looks like. The surfaces and decisions below are judged against these.

**J1. Get a robot ready** ("I'm in the robot configuring, things are working"). Open the robot;
see that every part is up (its subsystems: for the simulated duck robotd, tofd, configd, mapd and
the others; which client holds the robot and why another cannot drive); see its modules (the four
interfaces and the plugin filling each, with its live state); look at its settings (every profile
number with what measured it and why, sim and real side by side). Good: in under a minute the
operator knows the robot is fit to go, or exactly which part is not.

**J2. Calibrate it** ("calibration with what to look at highlighted and a step guide"). Pick a
measurement (the odometry by speed, the depth sensor's pitch, the pivot's creep), follow the steps,
see the measured value beside the current one, keep it as a new profile version or not. Good: no
probe script by hand; the real duck's `real` variant can be filled this way.

**J3. Send it on a mission and watch** ("the explorer with the robot's small model at the side, the
option to see a simulation or animation of what it is doing, the status of everything, shown
visually"). Start a goal in Mission Control; watch it in the Observatory: the map, the plan, what
it sees, its body (each joint coloured by its state), its subsystems. Good: the operator can tell at
a glance whether it is going well.

**J4. Something is off** ("a small alarm, click it, inspect it … a dose of interactivity, that it's
not only nice looking, but actually you can do something with it"; "his knee is not working … that
engine is blinking red, and there's an error message next to it"). An alarm appears where the
operator is looking; one click shows what, where and since when, with the evidence (the depth
frame, the joint's current, the subsystem's log); the operator can act (stop, take over, open the
run at that moment). Good: from alarm to cause in two clicks.

**J5. Understand a run afterwards.** Open the run in the Observatory, find its anomalies on the
timeline and the map, replay the body's health at any moment, compare with another run. Good:
every "why did it do that" has its evidence in the run.

**J6. Move a robot to another installation.** Export its profile as one file, import it elsewhere,
checked; see the difference between two versions. Good: no path or socket of one machine travels
with the robot.

**J7. See the robots in the operator's own observability** ("our system should not be a sink";
OpenTelemetry, the Victoria stack on the Mac mini). The subsystems' states, the joints' health and
the anomalies arrive in the operator's VictoriaMetrics, VictoriaLogs and VictoriaTraces, with
dashboards there; our views read back only what they show. Good: the same telemetry a homelab
service sends, under the same rules (dev apart from prod).

## 3. Which surface does what

A rule for every item of phase 5, so each lands in one place:

| Surface | Its job | Writes | Time |
| --- | --- | --- | --- |
| **Mission Control** | operate and configure: robots, their parts, settings, calibration, goals, STOP | yes: goals, profile versions, calibration | now |
| **The Observatory** | understand: every run, live and replayed, its anomalies and evidence | no (read-only over runs) | a run, live or past |
| **The operator's observability stack** (Victoria*, Grafana) | keep and chart the telemetry over weeks: subsystems, joints, anomalies, across runs and robots | n/a (it is the store) | long term |

Mission Control and the Observatory link to each other at the same moment (a goal run's Watch
link; a run's "open in Mission Control"); neither copies the other's view.

## 4. The telemetry and the data

### 4.1 What the operator's stack takes today (read from `agentic-ai-homelab`, 2026-11-21)

- **Endpoints** (`docs/recipes/observability-endpoints.md`): VictoriaMetrics, VictoriaLogs and
  VictoriaTraces on the Mac mini (`homelab`, ports 8428, 9428, 10428), and TLS tailnet nodes for
  senders off the mini (`vm.`, `vlogs.`, `vtraces.`; the mini's own forwarded ports dropped 2.3 % of
  span batches, the TLS nodes none). Grafana on :3000 and its TLS node. No ingest authentication:
  the tailnet's ACL decides which hosts may send.
- **OpenTelemetry today:** traces only, OTLP/HTTP straight from the apps' SDK to VictoriaTraces.
  Metrics and logs go through Alloy (Prometheus remote-write, Loki push). Whether VictoriaMetrics
  v1.154 and VictoriaLogs v1.52 take OTLP directly is not documented there: to be proven by a test
  send before relying on it (the homelab's `telemetry-probe` skill).
- **Limits that matter for a robot:** VictoriaMetrics deduplicates samples closer than 15 s on a
  series (`--dedup.minScrapeInterval=15s`); 6 months of metrics, 30 days of logs and traces (traces
  capped at 5 GiB). The stack holds about 22k series and 80k spans a day today.
- **Naming** (ADR-0010): `namespace` is the product, `service` one deployable, `environment`
  `prod`, `dev` or `ci`, `instance` the box; dev data is kept apart (`environment=dev`, a
  `worktree` label).
- **Dashboards:** provisioned from files, or a project's own folder synced by API with a service
  account token the homelab session mints.

### 4.2 What goes where (the proposal)

The 15 s deduplication settles the main question: a robot's 20 Hz data (joints, poses, depth frames)
cannot live in the metrics store, and should not: it is the run's record, and the run (format 2,
MCAP) already holds it, with the truth. So:

| Data | Where | Why |
| --- | --- | --- |
| Every tick of a run: joints, poses, depth frames, plans, decisions, the truth | **the run** (MCAP, the Observatory) | the record; replayed frame by frame |
| A goal run and its legs, as spans (start, end, outcome, the guardrail that broke) | **VictoriaTraces** (OTLP) | the timeline across runs and robots; already the stack's OTLP path |
| Anomalies, subsystem state changes, the runner's and navigator's events, subsystem logs | **VictoriaLogs** | searchable over weeks; the alarm feed's history |
| Low-rate health, at most one sample per 15 s per series: each subsystem up or down, each joint's peak current and temperature over the window, the real-time factor, goals by outcome | **VictoriaMetrics** | the long-term charts, Grafana's alerts |

Our views keep no store of their own beyond the runs: Mission Control reads the robot live; the
Observatory reads runs; the history across weeks is Grafana's, on dashboards provisioned from this
repository.

### 4.3 The runs over time

Today a run is a folder of MCAP files in the data folder and a row in the Observatory's index
(SQLite). That scales with disk, not with robots: a 5-minute exploration is 7.3 MB (about 1.5 MB a
minute, measured on two runs), and the data folder holds 1617 runs in 1.9 GB today. With more
robots the choice is between keeping the folder (with a retention and an archive rule), or an
object store (MinIO or S3) holding the runs and the index pointing at it. Decision D8 below.

## 5. The decisions

Each is the operator's, made on the mock-up page (section 6) and recorded here with the answer.
The first option of each is the recommendation.

**Decided by the operator (2026-11-21, on the page): A for all twelve.** One comment, on D3: "Lets
use icons where applicable also and when we show robot it should be very realistic". So: icons on
the robot page and the views where they help reading (a part, a module, a state, an alarm), and
the robot drawn from its own 3D model and meshes (RFC-0011), as the Observatory's Explore tab
already does, never a schematic like the mock-up's.

- **D1. Which surface does what** (§3). A: the table as written (Mission Control operates and
  configures, the Observatory explains runs, the homelab stack keeps the long-term telemetry).
  B: one app for both (Mission Control grows the Observatory's views).
- **D2. Where the robot lives as a page.** A: Mission Control has the robot's page (parts, modules,
  settings, calibration, body), live and editable; the Observatory shows a run's robot as it was (the
  profile version and plugins that run used), read-only. B: one robot page in the Observatory, with
  Mission Control linking to it.
- **D3. The robot's page, its sections.** A: Overview (fit to go or not, and why), Parts (the
  subsystems and who holds the robot), Modules (the four plugins, live), Settings (the profile by
  block, sim and real side by side, versions), Calibration (guided procedures), Body (the 3D model,
  each joint coloured). B: fewer sections, Overview carrying parts and modules.
- **D4. The body's health.** A: one body view, the robot's own 3D model with each joint coloured by
  its worst state (tracking error, load, temperature, a trip), the same component live in Mission
  Control and on replay in the Observatory; the run keeps the commanded angle, the velocity and
  the current per joint (today it keeps only the angle). B: a table of joints with sparklines, no
  3D.
- **D5. Alarms.** A: one feed of anomalies (RFC-0019's shape) from every source (the navigator,
  the runner, the subsystems, the joints): a badge where the operator is (Mission Control's header,
  the Observatory's timeline); a click opens the inspector with what, where, since when, the
  evidence and the actions (stop, take over, open the run at that moment). B: alarms only in
  Mission Control, the Observatory keeps its anomaly track as is.
- **D6. Telemetry out.** A: OpenTelemetry from our processes straight to the operator's stack
  (traces to VictoriaTraces as the stack does today; logs and metrics over OTLP to VictoriaLogs and
  VictoriaMetrics once a test send proves those paths, else through Alloy); what goes where as in
  §4.2. B: an OpenTelemetry Collector of our own in front of the stack. C: Alloy only.
- **D7. Names in the stack** (ADR-0010). A: `namespace=robotics-lab`; `service` per deployable
  (`mission-control`, `observatory`, `lab-runner`, `navigator`, and one per robot subsystem);
  `environment=dev` for the simulator on the workstation and `prod` for a real robot; `robot`,
  `host` and `run_key` as attributes. B: the simulator as an environment of its own (`sim`), which
  the contract does not list today (the homelab session would add it).
- **D8. The runs over time.** A: the data folder as it is, with a retention rule (keep the
  official runs, archive the rest after N days) and an object store only when a second machine
  writes runs. B: an object store (MinIO on the mini) now.
- **D9. Where a machine's settings live.** A: one installation file per machine (the robot's
  sockets come from the host file already; the Observatory's URL, the telemetry endpoints and the
  data folder join it), so the robot's profile holds only the robot and exports clean. B: keep them
  in the profile's `control` block per variant.
- **D10. Changing a setting.** A: edited in Mission Control, checked by the profile's validator,
  saved as a new profile version that applies from the next run, never during one; export and
  import as one file with a version and a checksum; a diff of two versions. B: edit the JSON file by
  hand, Mission Control only shows it.
- **D11. Calibration.** A: each measurement a guided procedure in Mission Control, run by the
  runner (in the simulator the truth measures; on the real robot the operator enters a tape
  measure's reading), the result beside the current value, kept or not as a new version. B: the
  probes stay scripts, Mission Control shows their last results. (Built as A in unit A3, with the
  motion in the navigator API, not the runner: the navigator drives, the runner adds the truth's
  reference, Mission Control keeps the meaning; navigator contract 1.3, `libs/runner/CONTRACT.md`.)
- **D12. The explorer while the robot works.** A: the Observatory's watch page gains the robot's
  small 3D model beside the map (posed by the recorded joints, coloured by health), a subsystems
  strip, and the alarm badge on its timeline; "animation of what it is doing" is the replay of the
  run's own poses. B: Mission Control gets its own live 3D view.

## 6. The mock-ups

One clickable page per journey (§2), drawn in the apps' own design (their tokens, Inter and
JetBrains Mono, dark and light), with the duck's real names and numbers; a decision card under each
for the operator's choice and comment, saved with the page and read back before any build:
<https://claude.ai/artifact/UgoSQef1rJDiV3UE1dzMSA> (private to the operator). Built from today's
surfaces, surveyed 2026-11-21: the Observatory's workbench already draws the duck's 3D body (its
Explore tab), no anomaly view exists yet, Mission Control is one page of panels with no robot page.

## 7. The build, from the decisions

In this order, each step proven before the next (its own tests, the views opened headless, a live
run where it touches the simulator), committed and pushed at each:

1. **The installation file and profile versions** (D9, D10's base). A per-machine file takes the
   Observatory's URL, the navigator's address, the telemetry endpoints and the data folder out of the
   profile; the profile gets a version and a checksum; every run records the version it used.
2. **The run keeps the body** (D4's data). Per joint, beside the angle: the commanded angle, the
   velocity and the current (an empty list is "not reported", never zero); robot-wide what robotd
   reports of its health. The simulator's bridge carries velocities and currents
   (`duck-control/src/sim.rs`); which of them reach our state stream is checked first.
3. **One alarm feed** (D5). The anomalies of every source in RFC-0019's shape: the navigator's
   (built), the runner's truth guardrails, the subsystems (a part down, a stale stream), the joints
   (load, tracking error, a trip; limits in the profile). Served live by Mission Control, kept in the
   run, and the Observatory's timeline and map marks (RFC-0019's views, not built yet).
4. **Mission Control's robot page** (D2, D3, D10, D11), with icons: Overview (fit to go, and why
   not), Parts (the profile's subsystem list, each with its check, its logs, its conflicts; who holds
   the robot), Modules (the four plugins, live), Settings (edit a copy, validated, a new version from
   the next run; export, import, diff), Calibration (today's probes as step guides run by the
   runner), Body (step 5's component).
5. **The body, realistic** (D4, D12, the operator's comment): the Observatory's Explore body (the
   duck's own meshes) coloured by each joint's worst state, as one component, on the watch page
   beside the map with the parts strip and the alarm marks, and in Mission Control live.
6. **Telemetry out** (D6, D7). Goal runs and legs as spans to VictoriaTraces; anomalies, events and
   subsystem logs to VictoriaLogs; health at most one sample per 15 s to VictoriaMetrics; ADR-0010's
   names (`namespace=robotics-lab`, `environment=dev` for the simulator). One test send per signal
   first; dashboards in a robotics-lab folder.
7. **The runs over time** (D8): a retention rule (official runs kept, the rest archived after N
   days).

**Needs the operator before it starts:** step 6's OpenTelemetry SDK for Python
(`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`: new dependencies); step 6's test
sends into the Victoria stack (the operator's production observability); asking the homelab session
for the robotics-lab Grafana folder's token and the tailnet access for this workstation's sends;
step 7's N.

### 7.1 Adjusted after the architecture review (2026-11-22)

The operator asked for a review of everything built before step 1
([the review](../wip/ARCHITECTURE-REVIEW-2026-11-22.md)) and took the lead's recommendation ("let's
adjust approach and follow your recommendation as next step, and then do another round of
review"). The build, adjusted:

1. **Step 1, wider:** the installation file and profile versions as reviewed
   ([the design](../wip/PHASE5-STEP1-DESIGN.md)), and inside it: Mission Control's robot file a
   pointer to the robot (its factsheet, capabilities, guardrails and rates from the profile
   version); Mission Control's adapter no longer importing the duck's navigator or the host library
   (the map through the navigator API, the scale per run, the addresses from the installation file);
   a policy for profile schema versions (older ones read and migrated) with the blocks phase 5 needs
   added now (the subsystems, the joint limits); the libraries' own tests (`libs/*/tests`,
   `make test-libs`).
2. **Then a second review round** of what step 1 built.
3. **One navigator contract** (the payload's a subset of the navigator API's, one vocabulary of end
   states, a version, written down in `libs/runner`) and **the apartment out of the runner**, before
   step 3.
4. Steps 2 and 3 side by side; then 4, 5.
5. **A runner that works without the truth**, before step 6; the gate protocol's version with
   step 4's "who holds the robot".
6. Step 6; step 7 (retention) when convenient, out of the sequence.

**Where it stands (2026-11-22, after the second review).** Items 1 and 2 are done. Step 1 is built
(phase 5 step 1, parts 1 to 10), and the second review was answered with the operator's
decisions, each built: robots registered by a file the installation names (Mission Control and
the runner have no robot's package installed); the checksum over the profile as stored; the
referee judging by the version the navigator runs; whole-number state streams, refused by the
gate otherwise; the navigator never reading the installation; one source for the gate's socket;
the forget rule counting only sight lines mapd has mapped (K45). What each is and how it was
proven is in [the design](../wip/PHASE5-STEP1-DESIGN.md); what is still open is in
[the known issues](../wip/KNOWN-ISSUES.md) (K46: inventory goals ending trapped). Next is item 3:
one navigator contract and the apartment out of the runner.
