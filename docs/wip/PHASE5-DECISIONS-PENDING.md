# Phase 5: decisions pending the operator

**Status:** running log, started 2026-11-23. The operator is away, on a flight. The operator,
2026-11-23: "take the recommended default, log it". Each entry is either a default taken (built,
reversible) or parked (not built). It says why and what to ask. The plan is
[PHASE5-NEXT-PLAN.md](PHASE5-NEXT-PLAN.md), "The build package for 4a and 4b".

## Decided before the flight

- **Calibration:** a navigator-API method, contract 1.3.
- **The duck's meshes:** served from the main checkout's built folder; nothing generated goes into
  git.
- **Pushes:** each green checkpoint of 4, 4a and 4b goes to main, with CI watched and fixed.
- **Decisions not covered:** the recommended default is taken where reversible, and logged here.

## Parked

### P3. The Observatory and Mission Control deployed together (done)

**Done (2026-11-23), the operator: "we should deploy now together observatory and mission
control as one platform".** From main at `36670fb`: `make observatory-down` (project
`observatory`), then `make stack-up` (project `robotics-lab`, EXIT=0, both containers healthy).

- `/api/v1/health`: the Observatory `{"ok":true,"runs":1629}`, Mission Control
  `{"ok": true, "service": "mission-control", "robots": 1}`.
- Both serve `/lib/` (200). In Chromium, Mission Control's overview and robot page and the
  Observatory's 3D page load with no console error and no failed request.
- What it is not yet: two origins (:8070, :8060), and Mission Control sees only the fake robot
  (`robots.example`). The duck needs the gate's and the navigator's Unix sockets, the
  installation file, the robot folder (description, meshes) and the profile store mounted at
  the paths the installation names. One origin is RFC-0024 step 3. The operator: "note these as
  4c" ([the plan](PHASE5-NEXT-PLAN.md), 4c: C1 to C3).

### P2. Redeploy the Observatory (shared state) (done)

**Done (2026-11-23).** The operator: "you can do P2 when you think is best". After A4's CI was green,
`make observatory-up` ran from main at `aea6d23` and the container came up healthy (EXIT=0).

- Health: `{"ok":true,"runs":1629}`.
- `/lib/tokens.css`, `/lib/vendor/three.module.js` and `/lib/body/body.js` return 200. The old
  `/web/three/vendor/...` path is 404, as moved.
- In Chromium, the 3D page and `/watch/duck/apartment/find2` both reach ready and draw (2
  canvases each). The 3D page logs two 404s: the browser's own `/favicon.ico` (no page declares
  an icon). That predates A4.

The situation before the redeploy:

After A4 (`aea6d23`), the running Observatory container still serves its old image. In it,
three.js sits under `web/three/vendor`, and the watch page's body is not coloured by alarms. The
main checkout moved three.js to `libs/web`. The image builds and serves `/lib/`:
`make test-observatory-image` PASS on the `observatory:ci` tag. Redeploying (`make observatory-up`)
needs the operator's go.

- **Ask:** "Redeploy the Observatory from main?"

### P1. One platform for Mission Control and the Observatory? (decided)

**Decided (the operator, 2026-11-23): "I agree on B, reached in C's order, as next step here".**
RFC-0024 is accepted. Unit A4 is RFC-0024's steps 1 and 2: the shared `libs/web`, then the body in
Mission Control. It is built after A1, because both touch Mission Control's web. Still open, and
needed only at B's step 3: questions 3 to 6, which cover how the one origin is served, tokens,
the run store behind an API, and the phone.

The question and the draft, as they stood:

The operator, asked where the realistic body should live (2026-11-23): "maybe we rethink about
bringing together mission control and observatory into one platform and not look at them as 2
fully independent things".

- **Not built:** unit A4, the realistic body, waits for this.
- **Drafted:** [RFC-0024, one platform](../rfc/RFC-0024-one-platform.md), proposed. It has four
  options:
  - A: one app and one process.
  - B: one web shell, two backends, one origin, and a shared `libs/web`.
  - C: two apps that embed each other's views by URL.
  - D: as today.
- **The draft's recommendation:** B, reached in C's order. Build `libs/web` first and prove the body
  in Mission Control, then one origin. Not reviewed yet by the advisor.
- **Found while drafting:**
  - The Observatory already has a body view (`apps/observatory/web/shell/robotbody.js`).
  - Its CSP forbids being framed by another origin (`frame-ancestors 'self'`,
    `apps/observatory/src/observatory/server.py:67`), so the "embed" option in the question asked
    before the flight would not have worked as it stood.
- **Ask:**
  - Which option?
  - Is the shared web library the first step whatever the answer?
  - How is the one origin served: Mission Control proxying with the stdlib, or Caddy or nginx (a
    new dependency)?

## Defaults taken

(Each entry: the unit, the decision, the default, why, how to undo it.)

### A1, the robot page (2026-11-23)

- **What makes the robot unfit:** it is offline, its gate cannot be reached, someone holds it (Mission
  Control's own goal run too), any status flag is set, or a major or critical alarm came in the last
  60 s. A minor or info alarm does not count. The plan named only critical; major was added by
  default. Undo: `fitReasons` in `web/app.js`.
- **Where alarms come from:** the fit verdict reads the page's live alarm feed, so it knows only
  the alarms since the page opened. Ask: should the robot view carry the last minute's worst alarm
  from the server?
- **Battery:** low battery is not yet a reason. B2 owns that threshold.
- **The parts' state:** no source reports it, so each part says "state not reported".
- **The STOP bar:** it stays on the robot page and names that robot.

### A4, the shared web library and the body (2026-11-23)

- **The tokens:** the Observatory's set is the shared one. Mission Control's was a strict subset
  with the same values (checked by a script over both files, dark and light, and its system-light
  block), so nothing was reconciled and nothing changed on either page. The file is
  `libs/web/tokens.css`; each app's own sizes (`--left`, `--right`, `--row`) stay in its
  stylesheet. `libs/web/tests/test_tokens.py` fails if an app declares a token again, the light
  block and its media-query copy differ, a page does not load the file, or there is a second
  three.js. Undo: put the blocks back into the two stylesheets.
- **The library's layout:** `libs/web/{tokens.css, vendor/, body/{robot.js, body.js}}`, moved (not
  copied) from the Observatory's `web/three/vendor` and `web/shell/robot.js`, `robotbody.js`. Both
  apps serve it at `/lib/`, from `libs/web` found by the server's own place (`parents[4]`), the
  same in the repository and in the images. The Observatory's old paths are gone, no redirect.
- **The CSP:** the Observatory's is unchanged (`/lib/` is the same origin). Mission Control has
  none; none added.
- **Where Mission Control gets the description and the meshes:** its own routes, `GET
  /robots/{id}/description` and `GET /robots/{id}/meshes/{file}`, from the robot's folder: the
  folder of the registration file the installation names (the profile's folder for an entry-point
  robot). The JSON is the Observatory's, so one component draws either. Mission Control has its
  own URDF reader (`description.py`, about 60 lines) because apps may not import each other; the
  Observatory's `kinematics.py` also runs inside Blender, so it was not moved into `libs/runfile`.
  A test compares the two over the real duck description. Ask: move the reader into `libs/runfile`
  and drop the copy. A robot whose file holds the robot itself answers `description: null` (200),
  not 404, so the page logs no error for it.
- **The meshes:** served from where the description is. In a worktree without `make robots` output
  they are missing; the Body section says so and draws nothing. In production Mission Control runs
  against the main checkout's folder, as the Observatory does.
- **Live joint angles:** the duck adapter's state carries `joints {name: radians}`, robotd's list
  under the profile's `joints.names` (the smallest addition: `status` and the `state` event, in
  CONTRACT.md); the fake robot has `joints` for tests. A robot that reports none has no key.
- **A joint's colour:** `ok` keeps the mesh's own colour (a green duck would say nothing), `warn`
  and `error` are the page's tokens. Severity: major and critical are `error`, minor `warn`, info
  is ok. A joint is coloured only by `joint_overload`, `joint_tracking` and `motor_hot` naming it
  (`values.joint`); a `motor_hot` names the hottest servo. Undo: `STATE_OF` and `JOINT_ANOMALIES`
  in `libs/web/body/body.js`.
- **How long an alarm colours a joint:** live, 60 s (the window of the fit verdict, one constant);
  on replay, from the anomaly to the end of the run (at or before the playhead, as asked). The
  live page knows only the alarms since it opened (A1's ask stands).
- **Colour never alone:** the joints that are not ok are listed under the body, state and alarm.
- **three.js on the phone:** loaded only when a robot with a description is opened (a dynamic
  import), never on the overview.
- **Mission Control's token:** the meshes are fetched with the token header when one is set.
- **Docker:** both Dockerfiles copy `libs/web`, both dockerignores allow it. Not built (no Docker
  here).

### A2, Modules and Settings (2026-11-23)

- **Modules:** the profile's four plugins (`name@version`), each with the block it answers for
  (`locomotion`, `sensors`, `localisation`, `looking`) and that block's first eight numbers as the
  running variant has them. No source reports a plugin's state to Mission Control, so each says
  "live state not reported"; no feed was invented. Undo: `paintModules` in `web/settings.js`.
- **No new endpoint:** a version's profile is read through `export?version=`; the versions, save,
  go back, diff and import are the existing ones. The page's code is `web/settings.js`, loaded
  before `app.js`.
- **What can be edited:** the numbers (and `null`s) of any block except the robot's identity
  (`factsheet`, `control`, `capabilities`, `plugins`, `subsystems`), in the base layer or in one
  variant layer, with the `measured` and `why` of the dict the number sits in (a variant's number
  needs them; the server says so at the field). Lists and tables are edited in the file. Emptying
  a variant field removes its override; the base field cannot be emptied except a `null` one.
  Undo: `stForm` and `stSave`.
- **"From the next goal":** shown on the version this page made current (save, make current,
  import) until the page is reloaded; the server does not say which version a running goal started
  with, so the mark does not survive a reload. Ask: should `GET profile` carry the version the
  last goal ran?
- **A store the installation names but that is empty:** `GET profile` answers 409 (the existing
  behaviour), so the page shows the load error; seed the store first (as the CLI does). Not
  changed here.
- **Settings spans both columns** on a desktop; the form is a grid of the block's dicts.

### A1 and A2 rebuilt to the approved design (2026-11-23)

The operator called the first Settings "stacks of fields" and approved a mock-up (tabs, collapsible
cards, Settings as a block list with a compact read view, an edit drawer and a History drawer):
"mockup is good". The page was rebuilt to it on the same API calls. Defaults taken:

- **Route:** `#robot/<id>[/<tab>]`; reload and back keep the tab.
- **STOP:** in the top bar on a desktop (40 px), pinned to the bottom on a phone (56 px).
- **Overview's Body card:** a text summary ("all N joints ok", or the ones that are not), not a
  second 3D view: three.js loads only on the Body tab, never on the phone's first screen.
- **The edit drawer** opens on the running variant; measured and why are editable on every layer,
  base included.
- **History:** compares on change (no Compare button); a stale answer cannot overwrite a newer one.
  The per-version Export is gone; Export exports the version shown.
- **Edit, Save and Import** are disabled when the store is not writable.
- **Contrast:** primary buttons are the accent darkened to 78 % (white text 5.2:1 dark, 6.9:1
  light); tags and units use `--text-dim`, not `--text-faint` (about 3:1).
- **Not covered:** no screen reader or axe run; Chromium only; no `inert` behind a drawer (a Tab
  trap only); the Modules row highlights overrides only among its first 12 values.

### A6, the robot view carries the last minute's alarms (2026-11-23)

- **Where:** `GET /robots/{id}` gains `alarms {window_s, worst, joints}` (additive): the worst
  alarm of the last 60 s and the worst per joint, each with its time. The window is one constant,
  `alarms.WINDOW_S`; the page takes it from the server.
- **Seeded:** a page that opens seeds only the worst overall and the worst per joint, not every
  alarm of the minute: the fit verdict and the joints are right at once, but the "N in the last
  minute" count shows only those for alarms from before the page opened.
- **Kept from the event bus**, so an alarm with no goal run running counts too. In memory only:
  Mission Control's restart forgets the minute. No cap, only age, so the worst is never dropped.
- **Not covered:** a browser clock that differs from the server's; the real duck's meshes test
  (the colour proof is on the stand-in body).

### B2, stopping on its own health (2026-11-23)

- **The end:** the contract's `stopped_by_guardrail`, no version change. `broken` is `{name, detail}`
  with the name `motor_hot`, `battery_low`, `robot_unhealthy` or `stale_stream` (the names are open:
  `goal.break` already carries any name). The run keeps a `guardrail` event with the decision
  `guardrail`; the cause's anomaly (`motor_hot`, `robot_unhealthy`, `thread_failed`) is raised where
  it is seen, as before. No new anomaly kind, so the Observatory's list is unchanged.
- **Thresholds:** `joints.limits.hot_c` (60 C) and the anomalies block's `state_stale_s` and
  `depth_stale_s` (3 s each) are reused, not duplicated. New: the profile's `health` block,
  `battery_min_pct` 15 and `battery_low_s` 10, in the base only (sim and real inherit it).
- **The battery default (the real duck's number to measure):** 15 % held for 10 s, two of the
  navigator's 10 s health polls, so one low reading or a servo's sag never stops it. The percent is
  robotd's, inferred from a 6.6 to 8.2 V span, so 15 % is about 6.8 V. Measure on the robot: percent
  and volts under a walking load, the sag in a step, where the servos brown out. Undo: the block's
  numbers, or remove the block (no stop watch, nothing stops on health).
- **An unhealthy verdict stops at the first poll** (not degraded: that stays a minor anomaly). A
  stale stream stops at the same moment `thread_failed` is said.
- **In the simulator:** the battery (about 50 %) and temperature (32 C) are constants, so a test
  profile (`--profile`) with `hot_c` 20 stops the point goal as motor_hot, and one with
  `battery_min_pct` 99 as battery_low. Unhealthy and a stale stream cannot be raised there.
- **Not covered:** a robotd that does not answer health (said once, not a stop: the 0.5 s deadman
  covers it); a stop between goals on the payload (the next goal clears it, the next poll stops it
  again, up to 10 s later); a bad state at the start of a goal (no preflight: B6's adapter or
  Mission Control's fit verdict); the health poll's 10 s, so a servo can be hot for up to 10 s
  before the stop.

### A3, calibration (2026-11-23)

- **Three parties, one part each.** The navigator API drives the motion and reports what the robot's
  own sensors said (contract 1.3: `calibration.list`, `.start`, `.status`, `.cancel`); its runner
  adds the reference by the host's truth; Mission Control holds the meaning (the step guide, the
  setting a procedure sets, how a measurement and a reference become its value). The navigator is
  never given the truth. Another robot adds a procedure in all three places.
- **`odometry_scale`:** stand 1.5 s, walk straight at `speed_mps` for `seconds`, stand 1.5 s, the
  odometry read at the two stands. Default speed is the profile's `at_speed_mps` (0.3), else
  `cruise_mps`, at most the factsheet's `maximumSpeed`; default 8 s, allowed 2 to 30. The value is
  reference over the odometry's distance, to 3 decimals; a value outside 0.5 to 1.5 is not kept
  (the robot was probably blocked, or the tape misread). No bound is the operator's: they are
  constants in `calibration.py`.
- **What keeping writes,** in the variant the robot runs (`variants.<variant>.localisation.odometry`):
  the table's `by_speed` entry at the speed walked, and `scale` when that is `at_speed_mps` (the
  profile's rule ties them within 1 %); with no table (the real variant today), `scale` alone. Its
  `measured` line says when, by which procedure and run, the walk, both distances and the value,
  and keeps the line it replaced after "Before this:" (so it grows by one line a calibration; the
  version history has the rest). Its `why` is the variant's own, else a generic one. The version
  is the next one, current, and applies from the next goal like any save.
- **State:** one run per robot, in memory, read from the navigator when the page asks (it polls
  every second while a run runs). Mission Control's restart forgets an unkept measurement.
- **The tape (the real duck's path):** a runner on a host with no truth sends `reference: null`;
  the page then asks for the distance the operator measured with a tape. Built and proven only
  with the simulator's truth read by the test as the tape, not on the real duck.
- **The page:** Calibration has a card per procedure and the measured lines under it. A card
  opens the same side drawer as Settings (a drawer carries its tab, so one does not stay open on
  another tab): the guide, the parameters, the run, the measurement beside the value now, what
  keeping changes, Keep. The Parts, Modules and Settings tabs are unchanged.
- **In the simulator:** 0.911 by the truth and 0.902 by a tape (the profile has 0.91). Two things
  seen, not investigated: a straight walk of 5 s at a commanded 0.3 m/s covered 0.66 m by the
  truth, about 0.13 m/s, so the by_speed row "0.3" is the commanded speed, not the one walked;
  and from the dock a blind walk runs into the office cabinet 0.7 m ahead (the first run did:
  0.54 m of 2.4), so the proof places the duck in the corridor first, by a point goal.
  `POST /robots/{id}/drive` with `vx` 0 and `vyaw` 0.5 to 0.8 did not turn the standing duck in
  40 s (the truth's heading did not change), so the proof does not turn it that way.
- **Not covered:** a calibration is blind (no wall, cliff or contact check, and the truth guard
  does not run): the operator clears the floor, and the real duck's walk needs the safety review
  (4b's B6); a second procedure; the pivot and depth-pitch procedures of RFC-0023 J2; a
  calibration while the robot is held by another client (refused live is not proven: the stand-in
  gate's refusal is); a cancel and a STOP, proven in the navigator's unit test (a stand-in gate)
  and the API test (the fake), not live in the simulator.

## Findings to watch

- **`test_replay_pages.py` failed once, cause unknown (2026-11-23).** It failed in a
  `make lint test-observatory test-observatory-pages` run while B1's simulator jobs and A2's page
  tests ran on the same machine. The failing check was not kept (the output was filtered away). It
  passed run alone and in a full rerun of `make test-observatory-pages` (EXIT=0). If it fails again,
  keep the whole log.
