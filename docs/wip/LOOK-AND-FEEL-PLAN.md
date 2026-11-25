# Step 4.5: the look-and-feel build, the plan

Contracts recorded in [ADR-0021](../adr/ADR-0021-one-design-system-and-3d-stage.md).

The plan for implementing what the operator picked from
[LOOK-AND-FEEL-RESEARCH](LOOK-AND-FEEL-RESEARCH.md) (all of section 4 and the five additions of
section 5a). Written 2026-11-24 by a planner from a read of the code; nothing was run for it.
Each unit's first step is to check the facts it rests on.

## The operator's decisions (2026-11-24)

- **Verdict colours:** accepted as proposed (section "status.js" below). A correct end is
  neutral; colour only for a problem.
- **The live indicator is yellow,** not red (red is error only). Yellow sits near amber (warn),
  so live also carries its own shape (a pulsing dot) and the token test checks its distance
  from `--status-warn`, both themes and under colour-blind simulation; if it fails, the hue goes
  back to the operator.
- **The contact shadow under the robot ships** with the floor, no separate review.
- **The large items are in 4.5:** panels, palette, layouts, readiness.
- **Review round 1** ([the page](https://claude.ai/artifact/V7JjkVFPdAmLxd6TCNdtpw)): the
  verdict `stopped` is neutral; the primary button is solid again, one shared style in
  `ui.css` for both apps; offline is its own status (`--status-offline`, grey, its own glyph,
  not stale's); alert against warn under deuteranopia in the light theme is accepted (the glyph
  and word tell them apart).
- **Review round 2** ([the page](https://claude.ai/artifact/KmLQUpUhykST6cYDHXbqDX)): the 3D
  view opens on the robot, with the whole scene as a setting; the belief ghost is on by
  default, with a setting; the camera toolbar collapses on a phone; Mission Control's body
  view has no follow modes and no gizmo (the robot stands still there). Accepted fixes: one
  light rig (the `--scene-*` lights) for the 3D pane, the Explore body and Mission Control,
  dark lights brighter and neutral (sky 1, sun 1.4); the dark grid one step brighter
  (`--draw-grid` follows it, an amendment in `test_tokens.py`); `I` in the keyboard help.
- **Review round 3** ([the page](https://claude.ai/artifact/EqGutKa2fH14TcgbUuQzHM), 2026-11-25):
  the rest looks good for now; more feedback after using it. Q1: the Readiness card replaces
  the fit card, and the robot page's header verdict follows it (one verdict, one list). Q2: the
  battery check uses the server's rule (an error under 20 %, cleared above 25 %), read from the
  server, not copied into the page. Q3: STOP stays the palette's first row but is not selected
  when it opens. Q4: the Signals view opens for runs with a pose too, so the duck's joints get
  their limit bands. Q5: the "Follow live" checkbox folds into the Live/Replay badge. The
  timeline's many flat lanes look dull and basic: one redesigned direction is built directly
  (not variants), reviewed in round 4, mixing all four ideas offered: lanes grouped by section
  that fold to a summary lane; the data inside the bars (a sparkline for a signal, density for
  a sensor's rate, so a gap shows); an events and alarms lane on top; a muted tone per section,
  colour kept for what needs attention.
- **One design system for both apps:** the same tokens, type scale, colours and components,
  from `libs/web`, for full consistency. The one difference kept on purpose is density:
  the Observatory compact (12 px base, 24 px controls), Mission Control regular (14 px base,
  36 px controls, 44 to 56 px touch targets on a phone).

## Before and after, reviewed by the operator

The operator asked (2026-11-24) to see before and after and to give feedback, with time set
aside for it. So:

- **U-SHOTS** (with U0): a script that starts both apps locally on fixed fixture runs and
  takes the same named set of screenshots every time: each main view of both apps, dark and
  light, 1440 px and a 390 px phone, 3D at fixed camera poses and a fixed time. The "before"
  set is taken from main before any change, so before and after compare like for like (the
  research's staging shots show other data and stay as context).
- **Review rounds**, each a before/after page for the operator, then a tuning pass on the
  feedback before the next wave starts:
  1. after U1, U2, U3, U10, U19: colour, type, density, top bar;
  2. after U11 to U13 and U21: the 3D (floor, shadow, light, camera, belief ghost, trail);
  3. after U14 to U18 and U20 to U25: time, panels, layouts, palette, readiness, evidence;
  4. after U26: the whole set, for step 5's screenshots.

### How to take the shots

`scripts/look_shots.py` starts its own Observatory and Mission Control (the fake robot, behind
`/control/`) on free ports and temp folders under `~/.cache/robotics-lab-tests`; it never touches
8060 or 8070. It takes 42 pictures, `<app>-<view>-<theme>-<width>.png`: views `runs`, `3d`, `map`,
`eye`, `chase`, `watch`, `explore` of the Observatory, `overview`, `robot`, `body` of Mission
Control, and `drawer` (phone only), each dark and light at 1440 and 390 px.

```bash
cd apps/observatory
uv run --frozen python ../../scripts/look_shots.py --out DIR --html
uv run --frozen python ../../scripts/look_shots.py \
  --compare ../../docs/wip/look-and-feel/before DIR --out CMP
```

- The "before" set is `docs/wip/look-and-feel/before/` (`index.html`, `shots.json` with the commit).
  Open `CMP/index.html` for before and after side by side; unpaired names are listed.
- `--only TEXT` takes just the names containing TEXT; `--slim` drops the 1440 light shots of the
  flat views.
- Two runs of the same code gave byte-identical files (41 of 42 on the first try; the
  fake robot's map fills in over a second, so a shot now waits until two pictures agree).
- The "before" set was taken at 9ef2d59, which already has U-STOP (STOP above the drawer).
- Not covered: the 3D camera is the page's default orbit plus four wheel steps (the page has no
  camera setter); a live run, a real robot, the semantic-object layer and the video export have no
  fixture; the drawer shot shows the robot's profile path of the checkout it was taken in.

## Facts the plan rests on (read, not run)

- STOP on a phone: Mission Control's `.scrim` is `z-index: 40` and the phone `.stops` bar
  `z-index: 30` (`style.css:247`, `:296`), so an open drawer covers STOP. Fixed first (U-STOP).
- The time model lives in `createShell` (`shell.js`): `M.t`, `M.i`, `M.play`, `setTime`, `#t=`.
  Mission Control has no replay.
- The 3D palette is copied: `build.js`'s `C` table and `setPalette`, lights in `three/app.js`,
  `views.js` and Mission Control's `bodyview.js`. `libs/web/body/body.js` owns no scene.
- The fonts were in `apps/observatory/web/fonts/` and Mission Control could not load them;
  U2 moved them to `libs/web/fonts/`.
- No JS test runner: JS is tested through the Python Playwright page tests
  (`page.evaluate("import('/lib/...')")`, as `test_eye_pages.py` does). `make lint` covers no JS.
- `/lib/` is served by both apps with no allow-list; both images copy `libs/web`.
- Reduced motion: the Observatory honours it in CSS only; Mission Control not at all.

## Rules for every unit

- Repro first: a failing check, then the change, then a mutation check.
- One page test file per unit while working; the full `make test-observatory-pages` and
  `make test-control-page` once per wave. `make lint` always.
- New test files: `apps/observatory/tests/test_look_{ui,3d,time,shell}_pages.py`,
  `apps/mission-control/tests/test_look_page.py`; each added to its Makefile list (one line).
- STOP stays static HTML, one tap, never disabled, never behind `arm()`, never under another
  layer. Shared JS never renders or gates it.
- Mission Control's phone page stays light: shared modules load lazily (dynamic `import()`); the
  overview fetches no three.js, stage, palette or layout menu until used.
- No new dependencies. No deploy (the X3 build hold); validation is local.
- A `libs/web` module is frozen once its unit lands; a change to it is an amendment by its owner.

## Units

| Unit | What | Rows | Depends on |
| --- | --- | --- | --- |
| U-STOP | STOP above every layer on a phone; a hit-test page check | 10 | none |
| U-SHOTS | The screenshot script and the "before" set (see "Before and after") | review | none |
| U0 | ADR: the contracts below, the decisions above | all | none |
| U1 | Tokens v2 in `libs/web/tokens.css`; checks: sync, invariants, aliases, contrast, ramps, no hex (allowlist shrinking to zero) | 1, 2, 6, 11, 14, 20, ramps | U0 |
| U2 | Fonts to `libs/web/fonts`; Mission Control loads Inter | 7 | none |
| U3 | Shared UI kit: `ui.css`, `status.js`, `brand.js`, `motion.js`; a check that every `libs/web` module imports clean | 3, 4, 6, 24, 20 | U1, U2 |
| U4 | `libs/web/stage/`: stage (floor, contact shadow, theme lights, tone mapping, faded grid), camera (presets, fit, follow, gizmo snap), trail | 5, 8, 13, 16, 17, trail | U1, U3 |
| U5 | `libs/web/body/`: `setStyle` (solid, x-ray, ghost), `clone`, `parts`, `highlight`, `isolate`, `inspector.js` | 25, belief | U1 |
| U6 | `libs/web/time/`: time model (pure), `freshness` | 9, 12, 15 | U1, U3 |
| U7 | `libs/web/layout/store.js` | 21, 23 | U1 |
| U8 | `libs/web/confirm.js`; STOP guard | 10 | U1, U3 |
| U9 | `libs/web/palette/` | 22 | U1, U3, U8 |
| U10 | Observatory restyle: tokens, density compact, top bar, statuses, tabular figures, reduced motion | 1-4, 6, 24 | U1-U3 |
| U11 | Observatory 3D: the stage, token-driven palette, floor and shadow | 5, 13 | U4, U10 |
| U12 | Observatory camera: presets, fit, gizmo snap, follow modes | 8, 16, 17 | U11 |
| U13 | Observatory bodies: belief ghost beside truth, trail, x-ray, inspector on `i` | 25, belief, trail | U5, U12 |
| U14 | Observatory time: Live and Replay, marks by kind, jumps, linked cursor | 9, 12, 15 | U6, U10, U13 |
| U15 | Observatory signals: threshold bands, state-duration bars, uniform ramps | 18, 19, ramps | U1, U10, U14 |
| U16 | Observatory panels and layouts | 21, 23 | U7, U10, U12, U14 |
| U17 | Observatory evidence links: `#t=<s>&focus=robot` | evidence | U12, U14 |
| U18 | Observatory palette verbs | 22 | U9, U12, U14, U16 |
| U19 | Mission Control restyle: tokens, density regular, top bar, freshness (STOP never disabled) | 1-4, 6, 24 | U1-U3 |
| U20 | Mission Control confirm for dangerous non-STOP actions | 10 | U8, U19 |
| U21 | Mission Control body view: stage, presets, fit, x-ray, inspector | 5, 8, 13, 25 | U4, U5, U20 |
| U22 | Mission Control panels and layouts | 21, 23 | U7, U21 |
| U23 | Mission Control readiness card: named checks from fields the robot view has; "unknown" when absent; no new route | readiness | U3, U22 |
| U24 | Mission Control evidence link to the Observatory moment | evidence | U17, U23 |
| U25 | Mission Control palette verbs: navigation, panels, layouts, theme, STOP first and unconfirmed; no goal, takeover or real-robot verb | 22 | U9, U20, U22 |
| U26 | Sweep: hex allowlist to zero, legacy names banned, after-screenshots, stale references | all | all |

Waves: U-STOP and U0; then U1 and U2 in parallel; U3; then U4, U5, U6, U7, U8, U10, U19 in
parallel (disjoint files), U9 after U8; then two serial lanes, the Observatory (U11 to U18,
`shell.js` and `three/app.js` are hotspots) and Mission Control (U20 to U25); then U26.

## Frozen contracts

### Tokens (`libs/web/tokens.css`)

"I" is invariant (first block only); the rest has the same key set in dark, light and the media
block. Old names stay as aliases in the first block until U26.

- Surfaces: `--surface-0` app, `-1` viewport, `-2` panel, `-3` header, `-field`, `-hover`,
  `-press`, `-selected`, `-section`, `-section-hover`, `-tip`.
- Lines: `--line-subtle`, `--line` (was `--border`), `--line-strong`, `--line-hover`,
  `--line-focus`. Hairlines `--hairline-1..5` (from `--hair-2`, `--hair`, `--hair-5`, `--hair-3`,
  `--hair-4`). Veils `--veil-1`, `--veil-2`, `--veil-scrim`; `--elev-shadow`.
- Text: `--text-1` value, `--text-2` label, `--text-3` hint, `--text-on-solid`.
- Action: `--accent`, `--accent-soft`, `--accent-ring`, `--accent-text` (on soft tints),
  `--accent-on` and `--accent-hover` (the solid primary, round 1), `--danger-solid` (STOP
  only).
- Status, each with `-soft` and `-on`: `--status-ok`, `-info`, `-warn`, `-alert` (orange),
  `-error`, `-unknown`, `-stale`, `-live` (yellow, with its own glyph), `-offline` (grey, its
  own glyph; round 1). `--ok`, `--warn`, `--error` stay as aliases. A status is never colour
  alone: a glyph and a word.
- Data (never a status): `--data-belief`, `-truth`, `-plan`, `-obstacle`, `-drop`, `-floor`,
  `-depth-obstacle`, `-depth-overhead`, `-box`, `-occupied`, `-free`, `-gap`.
- Axes `--axis-x/y/z`. HUD `--hud-bg`, `-line`, `-text`, `-key`, `-value`, `-warn`.
- Scene: `--scene-bg`, `-floor`, `-grid`, `-grid-major`, `-label`, `-rel`, `-select`,
  `-box-fill`, `-gap-hatch`, `-sky`, `-ground`, `-sun`, `-shadow`, `-sky-k`, `-sun-k`.
- Ramps, uniform in OKLab and colour-blind-safe, checked by the test: `--ramp-seq-1..9`,
  `--ramp-div-1..9` (neutral middle, not red-green), `--ramp-cat-1..8`.
- Controls: `--control-track`, `--control-knob`, `--control-border`.
- I: fonts `--font-ui`, `--font-mono`, `--font-num` (tabular); type `--fs-1..5` = 11, 12, 14,
  16, 20 px, `--lh-tight`, `--lh-body`; space `--sp-1..8` = 4, 8, 12, 16, 20, 24, 32, 40 px;
  `--radius-1..3` = 2, 4, 8 px, `--radius-pill`; `--elev-0..3`; z `--z-base`, `-sticky`,
  `-popover`, `-drawer`, `-palette`, `-toast`, `-stop` (highest); motion `--dur-fast`, `-base`,
  `-slow`, `--ease` (0 under reduced motion: `@media (prefers-reduced-motion: reduce)` on
  `:root:not([data-motion="full"])`, and `:root[data-motion="reduce"]`).
- Density, `:root[data-density="compact"|"regular"]`: `--ctl-h` 24 or 36, `--fs-base`, `--pad`.
  I: `--ctl-h-touch` 56, `--tap-min` 44, `--stop-h` 40 (56 on a phone).

### Modules (`libs/web/`)

- `status.js`: `STATUS = ['ok', 'info', 'warn', 'alert', 'error', 'unknown', 'stale',
  'neutral', 'live', 'offline']`; `statusOf(kind, value)` for `verdict`, `severity`, `event`,
  `conn`, `goal_state`; `statusVar`, `glyph`, `label`. Verdicts: ok = reached, done,
  evaluated; info = running, queued; neutral = ended, stopped, no_frontier_left, cancelled,
  refused, not_found; warn = timeout, stalled; alert = stopped_by_guardrail, trapped; error =
  failed, interrupted.
- `motion.js`: `reducedMotion()`, `ms(token)`, `setMotion('auto'|'reduce'|'full')`, `onChange`;
  writes `data-motion` and `rl.motion`.
- `brand.js`: `APPS = {control: {name: 'Mission Control', href: '/control/'}, observatory:
  {name: 'miniview', href: '/'}}`; step 5 changes this one file.
- `stage/stage.js`: `readStageTokens(el)`; `createStage(THREE, scene, renderer, {bounds, lit})`
  -> `{tokens, setBounds, setTheme, setLit, floor, grid, contactShadow(root) -> {update,
  dispose}, layer, dispose}`; sets colour space, tone mapping, clear colour. `makeGrid(THREE,
  bounds, {step, major, plane, tokens, fade})`. The floor is on its own layer (the eye view
  leaves it out); the grid fades by vertex colour, not fog.
- `stage/camera.js`: `PRESETS = ['iso','top','front','side','follow','eye']`,
  `FOLLOW = ['off','position','heading','pose']`; `presetPose`, `fitPose`, `followPose`,
  `moveTo(camera, controls, pose, {ms, onDone}) -> cancel` (0 ms under reduced motion),
  `snapFromGizmo`.
- `stage/trail.js`: `createTrail(THREE, {max, head, fadeTo})` -> `{object, set, clear,
  setColors, dispose}`.
- `body/body.js` additions: `setStyle({mode: 'solid'|'xray'|'ghost', color, opacity})`,
  `clone({style})` (shared geometry), `parts()`, `highlight(link, {color})`, `isolate(link)`;
  `tokenColors` keeps `{warn, error}`. `body/inspector.js`: `mountInspector(el, body,
  {onSelect, format})` -> `{update, select, dispose}`, keyboard-accessible.
- `time/timemodel.js`: `createTimeModel({mode, t0, t1, playing, speed, loop})`; `state` ->
  `{mode, t, t0, t1, playing, speed, loop, atEdge, behind_s}`; `seek(t, {source})`, `tick`,
  `play`, `pause`, `setSpeed` from `[.25, .5, 1, 2, 4, 8]`, `setLoop`, `setRange`, `goLive`,
  `jump(marks, dir, kind)`, `on('change', fn)`; added in U6: `finish()` (a live run
  ends) and `state.canLive`. `time/freshness.js`: `freshness(ageS,
  {staleAfterS: 5, offlineAfterS: 30})` -> `fresh|stale|offline`. The Observatory shell owns
  one time model; `setTime` and `window.miniview.setTime` keep their signatures. Mission Control
  uses only `freshness`. URL: `#t=<s>` stays; `&focus=robot` is added.
- `layout/store.js`: `createLayoutStore({app, version, defaults, storage})` -> `get`, `save`,
  `load`, `list`, `remove`, `exportJSON`, `importJSON` (validated), `current`, `onChange`.
  Keys `rl.layouts.<app>`, `rl.layout.current.<app>`, `rl.theme`, `rl.motion`,
  `rl.palette.recent`; legacy `miniview.theme`, `mc-theme`, `miniview.left` read once and
  migrated; `mc-token` untouched. Browser storage only, never the server.
- `confirm.js`: `arm(button, {ms: 6000, armedLabel, onConfirm})` -> `disarm`; throws inside
  `[data-stop]` or `.stops`; `disarm` is a full teardown (U8): the button stops confirming.
- `palette/`: `registry.register({id, title, section, keywords, when, hotkey, run, danger:
  'none'|'confirm'|'stop', api, mcp})`, `unregister`, `list(ctx)`; `createPalette({host,
  registry, storage})` -> `open`, `close`, `toggle`. Ctrl/Cmd+K and a top-bar button, never
  from a key typed in an input; `/` keeps its Observatory job. A `stop` verb runs on the first
  Enter. The palette starts no goal and takes no robot.

## Risks

- RFC-0023 D1: Mission Control is now, the Observatory is a run. Live and Replay live in the
  Observatory only.
- RFC-0024 constraint 5: the phone page stays light (lazy loading, checked by request).
- `shell.js` (1,733 lines) is the merge hotspot: the Observatory lane is serial, each feature a
  new module with a short hook.
- Type-scale rounding moves some labels by 1 to 2 px; reviewed in the U26 screenshots.
- The belief ghost doubles mesh draws; frame time is not measured.
- Colour-blind safety is checked by simulation, not by a person.

## Not covered

The brand name and README (step 5); any deploy; the deck.gl page's 3D, `apps/nxt-web`,
`mockup/` and `proto/` beyond the font link; a phone watch page and the shared Robots/Runs
navigation (RFC-0024 question 6); server-side or URL-encoded layouts; any new API route; palette
verbs that start goals or take over; found anomalies (RFC-0019's index); a readiness check for an
Observatory run; bloom, SSAO, depth of field; a review by a person of contrast or colour-blind
safety; frame-time measurement; real devices.
