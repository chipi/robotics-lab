# ADR-0021 — One design system and one 3D stage for both web apps

**Status:** Accepted (2026-11-24) by the operator, through the step 4 and 4.5 picks.
**Date:** 2026-11-24
**Context from:** [LOOK-AND-FEEL-RESEARCH](../wip/LOOK-AND-FEEL-RESEARCH.md) (what exists, what
other tools do, the proposal), [LOOK-AND-FEEL-PLAN](../wip/LOOK-AND-FEEL-PLAN.md) (the units and
the frozen contracts), [RFC-0023](../rfc/RFC-0023-the-views.md) (the views),
[RFC-0024](../rfc/RFC-0024-one-platform.md) (one platform).

## Context

Two web apps, the Observatory and Mission Control, share one `libs/web/tokens.css`, and it holds
colour only. Type, space, radius, motion, z-order and density are set per app, so the two drift.

The 3D is copied. The Observatory's `build.js` has its own palette table and `setPalette`; lights
sit in `three/app.js`, `views.js` and Mission Control's `bodyview.js`. `libs/web/body/body.js`
owns no scene. There is no floor, no contact shadow, no tone mapping, and no shared camera.

Mission Control cannot load the Observatory's fonts, and honours reduced motion not at all (the
Observatory does it in CSS only).

A real bug: on a phone, Mission Control's `.scrim` is `z-index: 40` and the `.stops` bar is
`z-index: 30`, so an open drawer covers STOP.

## Decision

1. **One token set in `libs/web/tokens.css`, both apps, both themes.**
   - Naming rule: property-role-emphasis (`--surface-2`, `--line-strong`, `--text-2`,
     `--status-warn-soft`).
   - Groups: surfaces, lines (with hairlines and veils), text, action, status, data, axes, HUD,
     scene, ramps, controls; the exact list is in the plan's "Frozen contracts".
   - Old names (`--border`, `--ok`, `--warn`, `--error`, `--hair-*`) were aliases in the first
     block until the sweep (U26) took them out; `libs/web/tests/test_tokens.py` now fails on any use
     of one.
   - Invariants (fonts, type scale, space, radius, elevation, z-order, motion, tap sizes) live in
     the first block only. Themed tokens have the same key set in dark, light and the
     `prefers-color-scheme` block. A test checks both, plus contrast, ramps, and that no hex
     remains outside a shrinking allowlist.
   - Density: `data-density="compact"` for the Observatory, `"regular"` for Mission Control.
     Control height, base font and padding follow it. Touch height (56), tap minimum (44) and
     STOP height (40, 56 on a phone) are invariant.
   - Motion: `--dur-fast`, `-base`, `-slow`, `--ease`. All go to 0 under reduced motion, by media
     query and by `data-motion="reduce"`; `data-motion="full"` is the user's override. This
     covers both apps.
   - Ramps (sequential, diverging with a neutral middle, categorical) are uniform in OKLab and
     checked under colour-blind simulation.
2. **One status ladder, in `libs/web/status.js`.** `ok`, `info`, `warn`, `alert` (orange),
   `error`, `unknown`, `stale`, `neutral`, `live`. Verdict mapping: ok = reached, done,
   evaluated; info = running, queued; neutral = ended, no_frontier_left, cancelled, refused,
   not_found; warn = timeout, stalled; alert = stopped_by_guardrail, trapped; error = failed,
   interrupted. A correct end is neutral; colour is for a problem.
   - A status is never colour alone: it carries a glyph and a word.
   - Data colours (belief, truth, plan, obstacle, and the rest) never carry status, and status
     colours never draw data.
   - Live is yellow, not red (red is error only), with its own glyph, a pulsing dot. Yellow sits
     near warn, so the token test checks its distance from `--status-warn` in both themes and
     under colour-blind simulation. If it fails, the hue goes back to the operator.
3. **Shared JS modules in `libs/web/`**: `status.js`, `motion.js`, `brand.js` (the one file step 5
   edits for the name), `stage/`, `body/`, `time/`, `layout/store.js`, `confirm.js`, `palette/`.
   Owner rule: a module is frozen when its unit lands; a change is an amendment made by its owner,
   not an edit from a consumer. Mission Control loads them lazily (dynamic `import()`); its phone
   overview fetches no three.js, stage, palette or layout code until used (RFC-0024 constraint 5,
   checked by request).
4. **One 3D stage, `libs/web/stage/`, driven by theme tokens.**
   - Stage: a floor on its own layer (the eye view leaves it out), a contact shadow under the
     robot (ships with the floor, no separate review), lights read from `--scene-*` tokens per
     theme, tone mapping and colour space set in one place, and a grid that fades by vertex
     colour, not fog.
   - Camera: presets `iso`, `top`, `front`, `side`, `follow`, `eye`; follow modes `off`,
     `position`, `heading`, `pose`; fit to bounds; snap from the gizmo; animated moves take 0 ms
     under reduced motion.
   - Bodies: styles `solid`, `x-ray`, `ghost`. The belief ghost is drawn beside the truth body,
     and a trail shows where the robot has been. A part inspector works from the keyboard.
5. **The time model lives in the Observatory only.** RFC-0023 D1: Mission Control is now; the
   Observatory is a run. Live and Replay, marks by kind, jumps and the linked cursor belong to
   the Observatory's one time model. Mission Control uses only `freshness` (fresh, stale,
   offline). There is no Mission Control replay. `#t=<s>` stays; `&focus=robot` is added.
6. **Layouts live in browser storage only.** Keys `rl.layouts.<app>`, `rl.layout.current.<app>`,
   `rl.theme`, `rl.motion`, `rl.palette.recent`. Legacy keys are read once and migrated;
   `mc-token` is untouched. Export and import are JSON, validated. The server never stores a
   layout.
7. **The command palette has fixed verb rules.** Ctrl/Cmd+K and a top-bar button; never from a
   key typed into an input; `/` keeps its Observatory job. The palette starts no goal, takes no
   robot, and has no real-robot verb. STOP is first in the list and runs unconfirmed, on the
   first Enter. Other dangerous verbs go through `confirm.js` (`arm`, 6 s).
8. **STOP rules, for every unit.** STOP is static HTML, one tap, never disabled, never behind
   `arm()` (`arm` throws inside `[data-stop]`), and never under another layer: `--z-stop` is the
   highest token. Shared JS never renders or gates it. The phone bug above is fixed first
   (U-STOP) with a hit-test page check.

## Consequences

- Positive: one place to change a colour, a size or a light; both apps read as one product; the
  3D looks the same in both; reduced motion works in both; STOP cannot be covered again.
- Negative: the type scale moves some labels by 1 to 2 px. The belief ghost doubles mesh draws.
  `shell.js` (1,733 lines) is the merge hotspot, so the Observatory lane is serial. The alias
  block was debt until U26, which removed it.
- Neutral: no new dependency and no deploy (the X3 build hold). JS has no test runner; it is
  tested through the Python Playwright page tests.

## Alternatives considered

- **A CSS framework** (Tailwind and the like): adds a dependency and a build step, and the
  roles we need (status, data, scene) are ours anyway. Not chosen.
- **A component library:** the apps are plain JS with no framework; a library would bring one,
  and its look is not a dense technical one. Not chosen.
- **A separate colour-blind palette switch:** a second palette to maintain and to find. One
  palette that is checked by simulation, plus glyph and word on every status, covers it.
- **Server-side layouts:** needs a new route and an owner for stored data; a layout is a
  personal preference. Browser storage with JSON export is enough.
- **Mission Control replay:** breaks RFC-0023 D1 (Mission Control is now). Replay stays in the
  Observatory, and an evidence link opens the Observatory at the moment.

## Not covered

From the plan: the brand name and README (step 5); any deploy; the deck.gl page's 3D,
`apps/nxt-web`, `mockup/` and `proto/` beyond the font link; a phone watch page and the shared
Robots and Runs navigation (RFC-0024 question 6); server-side or URL-encoded layouts; any new
API route; palette verbs that start goals or take over; found anomalies (RFC-0019's index); a
readiness check for an Observatory run; bloom, SSAO, depth of field.

Not checked, and said so: contrast and colour-blind safety are tested by simulation, not by a
person; frame time is not measured (the ghost cost); no real device was used.
