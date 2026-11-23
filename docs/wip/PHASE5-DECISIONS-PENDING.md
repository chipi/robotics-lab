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
