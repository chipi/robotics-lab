# RFC-0024 — One platform: should Mission Control and the Observatory stay two apps?

**Status:** Accepted (2026-11-23, the operator: "I agree on B, reached in C's order, as next step
here"): questions 1 and 2 of §7 are answered. Questions 3 to 6 stay open until B's step 3. The build
starts with steps 1 and 2: the shared library, then the body in Mission Control. These are phase 5's
item 4a unit A4. Proposed the same day. The operator, 2026-11-23, asked where the duck's
realistic 3D body view should live: "maybe we rethink about bringing together mission control and
observatory into one platform and not look at them as 2 fully independent things".
**Builds on:** [RFC-0022](RFC-0022-platform-layout-and-names.md) (the layout),
[RFC-0023](RFC-0023-the-views.md) (the views, D1, D2, D4, D12 and step 5), RFC-0014 §1-3
(Mission Control), RFC-0009 and RFC-0013 (the Observatory), RFC-0006 and RFC-0007 (the platform's
vision). The map: [How the platform fits together](../architecture.md).

## 1. Problem

RFC-0023 gave each surface one job (§3 there): Mission Control operates and configures, now; the
Observatory explains runs, live or past. It also decided the robot's 3D body, coloured by health,
is "one component, live in Mission Control and on replay in the Observatory" (D4, D12, step 5).

That decision hides a cost. The body is built with three.js, and three.js lives only in the
Observatory. Mission Control is plain HTML, CSS and JavaScript with no 3D. To show the body in both
places as one component, something has to give. The same wall stands in front of every view that
wants the live robot and the recorded run together:

- **The body view:** live joints from Mission Control; the meshes, the kinematics and the run's
  record from the Observatory.
- **Alarms** (RFC-0023 D5): raised live by Mission Control, shown on the Observatory's timeline,
  opened "at this moment" in the other app.
- **The robot page** (D2, D3): live and editable in Mission Control, "as it was" in the Observatory.
- **Watch:** a goal starts in one app and is followed in the other.

Today the two apps meet only through links. This RFC asks whether that is the right seam.

## 2. What is there today

All of it read from the repository on 2026-11-23.

### 2.1 Mission Control

`apps/mission-control`. A Python HTTP API (`src/mission_control/api.py`, 576 lines) over a core
(`core.py`) that holds the robots, goals, guardrails and sites. Its contract is `CONTRACT.md`.
It serves one page from `src/mission_control/web/` (`index.html`, `app.js` 713 lines, `style.css`
152 lines), live over a server-sent event stream (`GET /events`). It also has an MCP server
(`mcp_server.py`) and optional per-client tokens.

- **It writes, and it holds the robot.** Its SQLite store (`store.py`, the `MC_STATE` folder) keeps
  goals, sites and the gates' logs. Through the gate library (`libs/gate`) it takes the robot's
  control lock; a second driver is refused (RFC-0017).
- **Port 8060**, `compose.yml`: bound to loopback, or to the tailnet address in `MC_BIND`. Memory
  cap 512 MB. Dependencies: `robotgate`, `runfile`, `mcp`.
- **No 3D.** Its map is drawn on a canvas; it loads no three.js.

### 2.2 The Observatory

`apps/observatory`. A standard-library HTTP server (`src/observatory/server.py`, 561 lines) over
the runs: `/api/v1/scenes`, `/runs`, `/robots` (descriptions and mesh URLs), `/runs/.../live`
(server-sent events), `/watch/<robot>/<scene>/<run|latest>`, and `/web/...` for the pages.

- **Its pages** (`web/`): the shell, a workbench of about 4400 lines of JavaScript
  (`web/shell/shell.js` 1731 lines, with `explore*.js`, `robotbody.js`, `robot.js`, `runstore.js`);
  the three.js renderer (`web/three/`, with `vendor/` 2.1 MB); the deck.gl renderer (`web/deck/`,
  with `vendor/` 2.0 MB); the watch page (`web/three/watch.html`); the fonts; a mock-up and a
  prototype.
- **It reads, never writes the record.** The data folder is mounted read only in Docker
  (`compose.yml`, ADR-0012). The runs are MCAP files (ADR-0004, format 2); the index is a derived
  SQLite file in the host's state folder (ADR-0009, ADR-0012). It follows a run live while the
  runner writes it (RFC-0013: `/watch/.../latest`).
- **Port 8070**, loopback only, 768 MB. Dependency: `runfile`. The robot's description and meshes
  come from `robots/` mounted read only (RFC-0011).
- **The realistic body already exists here**: `web/shell/robotbody.js` loads the description's
  meshes, one group per link, placed by `robot.js`'s forward kinematics; the Explore tab and the 3D
  view's Robot layer use it.

### 2.3 How they meet

- The Watch link: Mission Control's adapter builds `<observatory>/watch/<run key>`
  (`mission_control/duck.py`, from the robot file's or the installation file's `observatory` URL).
  The page's button opens it in a new tab (`web/app.js`, "Open in the Observatory at this moment";
  the `#t=` fragment names the moment).
- `libs/runfile` is the only code both import: the run key, the profile store, the paths.
- The two never call each other. Each reads its own source: Mission Control the robot, the
  Observatory the runs.
- The Observatory's pages send `frame-ancestors 'self'` (`server.py`, `CSP`), so another origin
  cannot embed them in a frame today.

### 2.4 Shared and duplicated

| | Shared | Duplicated or only in one |
| --- | --- | --- |
| Run format, keys, paths | `libs/runfile` | |
| Design tokens (colours, light and dark, fonts) | the same names and values | copied: Mission Control's `style.css` says it takes them from `shell.css`; nothing checks they agree |
| Fonts (Inter, JetBrains Mono) | | the files are the Observatory's; Mission Control names them in CSS |
| three.js, the body, the kinematics | | only the Observatory |
| Web shell, theme switch, icons | | two shells, two sets of components |
| Test harness | Playwright, headless Chromium | Mission Control's page tests borrow the Observatory's venv (`test-control-page`) |
| Deployment | `make stack-up` starts both from their compose files | two images, two ports, two state folders |

## 3. Constraints

1. **The Observatory's data is read only, in Docker** (ADR-0012). Whatever is built must not give
   the viewer of runs a way to write them.
2. **Mission Control writes state and holds the robot's lock** (RFC-0017). A failure of the viewer
   must not take the lock, the STOP bar or the goals with it.
3. **The real duck and a second robot must fit**: the NXT and the simulated duck today, the EV3
   in phase 6, the TurtleBot3 after the plan. A view is built from a robot's description and
   profile, not from the duck.
4. **No new dependencies without the operator's approval.** A bundler, a front-end framework, a
   reverse-proxy product and a second web server are all new dependencies. three.js is vendored
   already.
5. **Mobile first for Mission Control** (its STOP bar is always on screen); the Observatory is a
   workbench for a large screen. A change must not make the phone page heavy.
6. **Keep the boundary check** (RFC-0018, RFC-0022): `apps/` do not import a robot's package or
   each other.

## 4. Options

### Option A — one app and one process

One Python server and one web app serve the live robot and the recorded runs.

**What changes.** The Observatory's server, index and pages move into Mission Control's process
(or the reverse); one port, one image, one shell.

**What moves where.** `apps/observatory/src/observatory/*` and `web/` into the one app; the run
store (read only) and Mission Control's SQLite (read-write) live in one process.

**Migration.** (1) Choose the host app. (2) Move the server routes behind one router. (3) Merge the
two shells. (4) Merge the compose files and images. (5) Redo every test that names a port or an
image.

**Risks.**

- The process that holds the robot's lock also serves 1.9 GB of runs and decodes MCAP. A slow
  replay, a big index build or a memory spike (768 MB plus 512 MB today, separately capped)
  now threatens STOP.
- The read-only mount (ADR-0012) is a property of the container. In one container the process
  holding the lock needs a writable state folder; the data stays read only, but the guarantee "the
  viewer cannot write" becomes a promise of the code, not of the container.
- The Observatory runs on the Mac mini's tailnet as a viewer others may open; Mission Control can
  drive a robot. One process means one exposure.
- The largest rewrite of the four, with no new capability over B.

**Effect on the robots.** None gained. The real duck's lock path is touched by the move.
TurtleBot3: no difference.

**How the body is built.** `robotbody.js` and its three.js sit in the same app as the live state
stream; one component, direct calls.

### Option B — one web shell, two backends, one origin

One web application (one shell, one navigation, one set of components) in front of the two
backends, which stay separate processes. The browser sees one origin; the paths decide the backend.

**What changes.** A shared web library `libs/web` (plain ES modules, no bundler): the design
tokens, the fonts, the icons, the theme switch, three.js, the robot body, the alarm badge and
inspector, the timeline. Both backends serve their pages from it. One entry point routes
`/api/control/...` to Mission Control (8060) and `/api/v1/...`, `/watch/...` to the Observatory
(8070).

**What moves where.**

- To `libs/web`: `web/shell/robotbody.js`, `robot.js`, `icons.js`, `eye.js`, the tokens from
  `shell.css`, the fonts, and `web/three/vendor` (one copy of three.js, not two).
- Stays in the Observatory: its server, the index, the run readers, the render service, the
  workbench shell.
- Stays in Mission Control: the API, the core, the store, the gates.
- The one origin: a small router in front. The options for it are in §6 (question 3).

**Migration.**

1. Extract the tokens and the body into `libs/web`, served by both apps; a test fails if the
   tokens differ (the missing check today). No behaviour change.
2. Mission Control gets the body: the robot page's Body section (RFC-0023 step 5) built from
   `libs/web`, posed by the live state stream (`/events`).
3. One origin and one navigation: a "Robots / Runs" bar both pages share.
4. The robot page and the alarm inspector use one component for "live" and "this run's".
5. Later and only if wanted: fold the two shells into one.

**Risks.**

- The router is one more piece to run and to secure: tokens (`--require-tokens`) are Mission
  Control's; the Observatory has none. A shared origin means a shared decision on who may look.
- A shared library without a bundler is plain files and import paths; the cost is discipline.
- Two backends means two health checks in one page: the page must stay useful when one is down.

**Effect on the robots.** The second robot and the TurtleBot3 need nothing new: the body comes from
a description (RFC-0011). The real duck's lock stays in Mission Control. A shared origin also
makes the cross-links work as embeds (the Observatory's `frame-ancestors 'self'` allows a same-
origin frame).

**How the body is built.** Once, in `libs/web`: `robotbody.js` plus a pose source. A pose source
is "the live state stream" in Mission Control and "the run at the playhead" in the Observatory;
the component is the same. Health colouring (RFC-0023 D4) is a function of the joint's state,
also shared.

### Option C — two apps, a shared library, views embedded by URL

Keep two origins, two ports and two shells. Add `libs/web` for the shared parts (as in B).
Each app can then draw the body itself; where a view belongs to the other app, embed it.

**What changes.** `libs/web` as in B steps 1-2. Cross-app views are frames: Mission Control's
robot page frames the Observatory's watch page. The Observatory's `frame-ancestors 'self'` becomes
a list of allowed origins (a code change, and a security change).

**Migration.** Steps 1-2 of B; then the frame and the CSP change; the apps stay as they are.

**Risks.**

- Cross-origin frames: the two apps cannot share the theme, the selected run or the playhead
  except by `postMessage`, and the phone cannot show two big pages in one.
- Auth stays per app and a frame shows an app the user is not signed in to.
- Two shells keep drifting; the shared library covers parts, not the experience.
- Embedding the watch page under a live page is exactly "two fully independent things" glued
  together, which the operator doubted.

**Effect on the robots.** As in B; no new capability for the second robot.

**How the body is built.** As in B (one component in `libs/web`); each app mounts it.

### Option D — the status quo

Mission Control gets its own three.js and its own copy of the body; the Observatory keeps its own.
This is RFC-0023 step 5 as written ("in Mission Control live").

**What changes.** Nothing structural. Copy `robotbody.js`, `robot.js` and the 2.1 MB three.js
into Mission Control's `web/`.

**Risks.** Two bodies to keep equal (joint colours, the meshes' placement, the second robot's
description); the tokens already drift unchecked; every view in §1 is built twice or linked.
Mission Control's phone page grows 2 MB of three.js loaded for one section.

**Effect on the robots.** Each new robot's body is verified in two places.

## 5. Comparison

| | A one process | B one shell, one origin | C shared library, embeds | D status quo |
| --- | --- | --- | --- | --- |
| Body built once | yes | yes | yes | no, twice |
| One experience for the operator | yes | yes | partly | no |
| Read-only data kept by the container (ADR-0012) | no | yes | yes | yes |
| Viewer failure can touch the lock | yes | no | no | no |
| New dependency | none | a router (§6) | none | none |
| Rewrite size | largest | medium, in steps | small | none |
| Reversible after step 1 | no | yes | yes | n/a |
| Second robot, TurtleBot3 | neutral | neutral | neutral | two places to check |

## 6. Recommendation

**B, reached in the order of C.** Build the shared library first (B step 1 and 2 are C), prove
the body in Mission Control, then join the two behind one origin and one navigation (B steps 3
and 4). Decide step 5, folding the shells, only after living with 3 and 4.

Why:

- It answers the operator's question: the two stop being "fully independent things" for the
  person using them, with one navigation, one look, one body, one alarm inspector.
- It does not merge the two risks (§3, 1 and 2). The process that holds the lock stays small and
  separate from the one that reads 1.9 GB of runs, and the read-only mount stays the container's
  guarantee.
- The first step helps every option, so nothing is lost if the operator later picks A or C: B's
  steps 1 and 2 are C, and A would start with them too.
- It pays for the second robot: the body, the alarms and the robot page are written once against
  a description and a profile, so the TurtleBot3 inherits them.
- It needs no dependency until step 3, and step 3 may need none (question 3).

**Not chosen.**

- **A:** the largest rewrite for no new capability, and it puts the STOP bar and the lock in the
  same process as the heaviest reader. It is the right end state only if both apps become small and
  the run store moves behind an API (see question 5).
- **C alone:** it leaves two shells and two origins, so alarms, "open at this moment" and the
  theme stay glued with `postMessage` and a looser CSP.
- **D:** it builds the same body twice and lets the tokens drift; RFC-0023 chose "one component".

### 6.1 What this changes in RFC-0023

D1 (which surface does what) stands: the jobs are the same, now shared in one place for the
operator. D4 and D12 stand: one body component, live and on replay. Step 5 of RFC-0023 §7 is
built as B step 2 here. D2 stands: the robot page is Mission Control's, and the Observatory's is
read only.

### 6.2 How the realistic body is built, in B

1. `libs/web/body` (extracted from `robotbody.js`, `robot.js`): load the description's meshes
   (`/api/v1/robots/{robot}`), place one group per link, pose from a joint map.
2. A pose source, two kinds: live (Mission Control's `/events` state) and recorded (the run at
   the playhead, as the Explore tab reads it today).
3. A health colour per joint from RFC-0023 D4's worst state; today the run keeps only the angle,
   so the colour waits for step 2 of RFC-0023 §7 (the run keeps the body) while the live view
   can start with the angle alone and the tracking error.
4. Mounted in the robot page (Mission Control), the watch page (Observatory) and the alarm
   inspector (both).

## 7. Questions for the operator

1. **Which option?** The recommendation is B, in C's order. If you prefer A, say whether you
   accept the lock and the run reader sharing a process (§4, A, risks).
2. **Is a shared library the right first step even if you later choose A?** It is in all three.
3. **The one origin (B step 3).** How would you like it served: Mission Control proxies the
   Observatory's paths (stdlib only, no new dependency; the lock's process then fronts the
   viewer), or a reverse proxy in front of both (Caddy or nginx: a new dependency and a new
   container; needs your approval).
4. **Who may look?** One origin means one rule. Today Mission Control can require per-client
   tokens and the Observatory has none. Should the Observatory's runs need the same token?
5. **The run store behind an API.** Should a future version let Mission Control read runs through
   the Observatory's API (never the files), so the two never share a folder? It would make A
   safer later. Not needed for B.
6. **Phone.** Should the shared navigation show the Observatory at phone width, or only link to
   it (it is a workbench for a large screen)?

## 8. Not covered

- **Not verified by a build.** Every number here is from reading the files on 2026-11-23: nothing
  was built or run, and the cost of moving the three.js loaders to a shared folder (import paths,
  the CSP in `server.py`, the Playwright tests) is an estimate, not a measurement.
- **Not read in detail:** the Observatory's `shell.js` (1731 lines) beyond its imports and
  headers; whether Mission Control's SSE stream carries enough joint data for the live body
  (RFC-0023 step 2 says the state stream is being widened).
- **Not decided:** the shared navigation's design, the theme switch's single home, the
  deck.gl renderer's place (2 MB, only the Observatory needs it), the Docker layout of B (one
  compose file or two) and the build order against phase 5's open items.
- **Out of scope:** the telemetry to the operator's stack (RFC-0023 D6, D7); the operator's
  other tools.
