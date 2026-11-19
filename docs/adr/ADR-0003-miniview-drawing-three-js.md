# ADR-0003 — miniview (now the Observatory) draws with three.js, the same page for the operator and the agent

> Now the Observatory (RFC-0018, built 2026-11-19): the product, package and command were renamed;
> this text keeps the names of its time.

**Status:** Accepted for this step (2026-11-15, by the operator); deck.gl evolves alongside for the
next rounds, and the final pick is made mid-term
**Date:** 2026-11-15
**Context documents:** [RFC-0009](../rfc/RFC-0009-miniview.md) §7, [UXS-001](../uxs/UXS-001-miniview.md),
[ADR-0002](ADR-0002-viewers-rerun-and-lichtblick.md)

## Context

miniview needs 2D views from the top and from any side, all three at once, and a 3D view with orbit;
a coordinate system in every view; up to ~10,000 grid cells, a few thousand points and long tracks
per frame; a timebar every panel follows without lag; phones; and the same picture for the agent,
rendered headless. The operator decided on a framework from the start, not a hand-drawn canvas.
A comparison of three.js, react-three-fiber, Babylon.js, deck.gl, regl, PixiJS, Plotly and embedding
Rerun's or Lichtblick's viewers was made on 2026-11-15 (versions checked on npm that day).

## Decision

1. **three.js (0.187.0, MIT)**, vendored as ES modules and loaded with an import map: no Node
   build step, static files served by `make viewers`.
2. **Views are cameras on one scene**: an orthographic camera along an axis for each side, three of
   them with `setViewport`/`setScissor` for the three-view, a perspective camera with orbit controls
   for 3D. Grid cells as one instanced mesh, returns as points, boxes and tracks as line segments;
   scrubbing rewrites typed arrays from the prepared frames rather than rebuilding objects.
3. **Labels and panels are HTML** (axis and grid numbers as HTML overlays), so they look the same
   on screen and in a screenshot.
4. **The agent's pictures are the page**, rendered in headless Chromium with software GL
   (SwiftShader) through Playwright, after the page signals it has drawn. The current SVG renderer
   in `miniview.py` is retired once this works. Deterministic output: fixed device scale,
   antialiasing fixed; pictures compared with a tolerance across Chromium versions.

**The spike that decides it:** 10,000 instances, 3,000 points and the three-view; scrub 600 frames;
screenshots under SwiftShader with the flags the comparison found; timing on a phone. If scrubbing
lags, the answer is less data per frame, not another library.

## Why three.js (2026-11-15)

1. **One 3D stack across the operator's projects**: Orrery is built with three.js — one set of skills,
   shared patterns and code, one ecosystem to follow (the operator's reason, and the main one).
2. **Side views with real depth.** Both libraries were built for the same v0.1 in an hour each
   (`viewer/web/three/`, `viewer/web/deck/`). three.js gave true orthographic cameras with depth for
   the sides and the three-view. In the deck.gl build, `OrbitView({orthographic: true})` drew almost
   nothing; side views were done by rotating the world into the 2D view, without depth ordering. The
   builder did not find the cause in the hour — it may be the build's mistake, not deck.gl's limit.
3. What deck.gl did better — thick lines, round points, built-in text — three.js reaches with
   add-ons (`Line2`, text). Speeds were measured differently by the two builds and are not compared.

## Consequences

- **Positive:** one drawing path for both faces; a widely known library, MIT, monthly releases; the
  views map onto features it has.
- **Negative:** we write the glue — camera presets, grid and axes, theme, layout of several
  viewports, layer toggles; headless rendering is slower than a GPU (one picture at a time is fine).
- **Neutral:** Rerun and Lichtblick stay as the tools for free exploration (ADR-0002).

## Alternatives considered

- **deck.gl** — least code for layered data and SDF text built in; but map-first, heavier, wireframe
  boxes and true side views of a 3D scene need workarounds (unverified). It wins if the views turn
  out to be mostly 2D data layers.
- **react-three-fiber** — declarative, a `View` per viewport; needs React and a build, more layers
  over three for little gain at this size. It wins if the page grows into a large app.
- **Babylon.js** — capable, much larger than needed. **regl** — all shaders by hand. **PixiJS** —
  2D only, a second library for 3D. **Plotly** — not for these volumes or the three-view.
- **Embedding Rerun's web viewer or Lichtblick** — their views, not ours: no truth beside belief,
  no data view, no page that equals the agent's picture; Rerun's viewer is heavy on phones and
  under software GL; Lichtblick has no embeddable 3D panel.
