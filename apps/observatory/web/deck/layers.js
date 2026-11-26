// Builds the deck.gl layers for one pane. Static data stays referentially stable; only the
// per-moment pieces (poses, track slice, depth frame, plan, world) change with t.
import { IDENT, KIND_COL, CELL_COL } from './data.js';

const { PathLayer, LineLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer, PathStyleExtension, COORDINATE_SYSTEM } = deck;
const DASH = [new PathStyleExtension({ dash: true })];
const CART = COORDINATE_SYSTEM.CARTESIAN;
export const C = {
  belief: [70, 130, 255], truth: [40, 180, 90], plan: [230, 180, 0], obst: [255, 150, 0], haz: [230, 0, 230],
  x: [224, 48, 48], y: [48, 176, 48], z: [48, 96, 224], box: [138, 138, 150], grid: [216, 216, 224], text: [100, 100, 112],
  rel: [30, 30, 30], sel: [0, 0, 0], bg: [255, 255, 255], boxFill: [138, 138, 150, 41], error: [224, 90, 79], warn: [224, 160, 48], dim: [154, 157, 166],
};
// an anomaly's colour by severity (the theme's error, warn and dim colours)
export const sevColor = (s) => (s === 'critical' || s === 'major' ? C.error : s === 'minor' ? C.warn : C.dim);
const rgb = (hex) => { const n = parseInt(hex.replace('#', ''), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
// the page's theme tokens (shell palette, CSS hex strings) -> the colours the layers are built with
export function setPalette(p) {
  const c = (k) => rgb(p[k]);
  Object.assign(C, { belief: c('data-belief'), truth: c('data-truth'), plan: c('data-plan'), obst: c('data-obstacle'), haz: c('data-drop'), x: c('axis-x'), y: c('axis-y'), z: c('axis-z'),
    box: c('data-box'), boxFill: [...rgb(p['scene-box-fill'].slice(0, 7)), parseInt(p['scene-box-fill'].slice(7, 9) || 'ff', 16)], grid: c('scene-grid'), text: c('scene-label'), rel: c('scene-rel'), sel: c('scene-select'), bg: c('surface-1'),
    error: c('status-error'), warn: c('status-warn'), dim: c('text-2') });
  Object.assign(KIND_COL, { f: [...c('data-floor'), 255], o: [...c('data-depth-obstacle'), 255], v: [...c('data-depth-overhead'), 255], b: [...c('data-drop'), 255] });
  Object.assign(CELL_COL, { occ: [...c('data-occupied'), 255], free: [...c('data-free'), 255] });
  gridCache.clear();
}
const P = { depthTest: false };
// Side views are the 2D OrthographicView looking at a rotated world: the modelMatrix sends
// (x, y, z) to (screen x, screen y, depth), so every layer works as it does in the top view.
const SIDEM = {
  top: IDENT, '3d': IDENT,
  front: [0, 0, -1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],    // from +x: y right, z up
  back: [0, 0, 1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],     // from -x: y left, z up
  right: [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1],    // from -y: x right, z up
  left: [-1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1],     // from +y: x left, z up
};
const mul = (a, b) => { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k]; return o; };
const PLANE = { top: [0, 1], '3d': [0, 1], front: [1, 2], back: [1, 2], left: [0, 2], right: [0, 2] };
const END_ON = { top: 2, '3d': -1, front: 0, back: 0, left: 1, right: 1 }; // axis pointing at the camera: no label

const vec = (a, va, b, vb) => { const v = [0, 0, 0]; v[a] = va; v[b] = vb; return v; };

function gridFor(mode, bounds) {
  const [a, b] = PLANE[mode];
  const rng = [[bounds[0], bounds[1]], [bounds[2], bounds[3]], [-1, 2]];
  const [a0, a1] = rng[a], [b0, b1] = rng[b];
  const lines = [], labels = [];
  for (let v = Math.ceil(a0); v <= Math.floor(a1); v++) {
    lines.push({ s: vec(a, v, b, b0), t: vec(a, v, b, b1) });
    labels.push({ p: vec(a, v, b, b0 - 0.22), text: String(v), anchor: 'middle', base: 'center' });
  }
  for (let v = Math.ceil(b0); v <= Math.floor(b1); v++) {
    lines.push({ s: vec(a, a0, b, v), t: vec(a, a1, b, v) });
    labels.push({ p: vec(a, a0 - 0.12, b, v), text: String(v), anchor: 'end', base: 'center' });
  }
  return { lines, labels };
}

function axesFor(mode) {
  const lines = [], labels = [], L = 1;
  const names = ['x', 'y', 'z'];
  for (let k = 0; k < 3; k++) {
    const col = C[names[k]], tip = [0, 0, 0]; tip[k] = L;
    lines.push({ s: [0, 0, 0], t: tip, col });
    for (const j of [0, 1, 2].filter((j) => j !== k)) for (const sg of [-1, 1]) {
      const h = [0, 0, 0]; h[k] = L - 0.15; h[j] = sg * 0.06;
      lines.push({ s: tip, t: h, col });
    }
    if (END_ON[mode] !== k) { const p = [0, 0, 0]; p[k] = L + 0.14; labels.push({ p, text: names[k], col }); }
  }
  return { lines, labels };
}

const circle = (x, y, z, r, n = 28) => Array.from({ length: n + 1 }, (_, k) => [x + r * Math.cos((k / n) * 2 * Math.PI), y + r * Math.sin((k / n) * 2 * Math.PI), z]);
function robotPaths(pose, r, h) {
  const [x, y, yaw] = pose, c = Math.cos(yaw), s = Math.sin(yaw);
  const paths = [{ path: circle(x, y, 0, r) }, { path: circle(x, y, h, r) }];
  for (let k = 0; k < 4; k++) { const a = yaw + (k * Math.PI) / 2; paths.push({ path: [[x + r * Math.cos(a), y + r * Math.sin(a), 0], [x + r * Math.cos(a), y + r * Math.sin(a), h]] }); }
  paths.push({ path: [[x, y, h], [x + 1.8 * r * c, y + 1.8 * r * s, h]] }); // heading
  return paths;
}

const gridCache = new Map();
const cached = (k, f) => { if (!gridCache.has(k)) gridCache.set(k, f()); return gridCache.get(k); };

// The faint faces of boxes and pits, in what each view shows: the footprint from above, the projected rectangle in
// a side view (already in screen coordinates), and in 3D an extruded footprint (a flat polygon is the exact colour
// the CSS mockup has; an extruded one is lit and comes out darker, so only 3D uses it).
function faces(list, mode) {
  if (mode === '3d') return list.map((d) => ({ poly: d.poly.map(([x, y]) => [x, y, d.z0]), h: d.z1 - d.z0 }));
  if (mode === 'top') return list.map((d) => ({ poly: d.poly }));
  const [a, sg] = { front: [1, 1], back: [1, -1], right: [0, 1], left: [0, -1] }[mode];
  return list.map((d) => {
    const v = d.poly.map((p) => sg * p[a]), lo = Math.min(...v), hi = Math.max(...v);
    return { poly: [[lo, d.z0], [hi, d.z0], [hi, d.z1], [lo, d.z1]] };
  });
}

export const SHORT_TAIL_S = 2; // what "at t" shows of a track: a short tail


// the loaded stretches of tr[a..b] as paths (a hole in the run is a break in the line, not a bridge over it)
function pathsOf(tr, a, b) {
  const out = [];
  let cur = null;
  for (let k = a; k <= b; k++) {
    if (!tr[k]) { cur = null; continue; }
    if (!cur) out.push(cur = { path: [] });
    cur.path.push(tr[k]);
  }
  return out;
}

// ticks a..b a stream shows at tick i, from its time mode
export function ticksFor(S, id, i, tail) {
  const { D } = S, tm = S.cfg(id);
  if (tm.mode === 'upto') return [0, i];
  if (tm.mode === 'window') return [Math.min(D.f.firstAfter(D.t[i] - tm.n), i), i];
  return tail ? [Math.min(D.f.firstAfter(D.t[i] - tail), i), i] : [i, i];
}

// Every layer of a pane is in the list at every moment, with `visible` (and empty data) saying whether it draws:
// a layer that comes and goes costs deck.gl a new shader program each time it comes back (hundreds of ms in a
// software renderer), one that stays costs nothing.
const EMPTY = [];
const FLAT = { ambient: 1, diffuse: 0, shininess: 0, specularColor: [0, 0, 0] };   // unlit: the colour as given
const EMPTY_POINTS = { length: 0, attributes: { getPosition: { value: new Float32Array(0), size: 3 } } };

export function buildLayers(S, pane) {
  const { D, scene, i, dv } = S, mode = pane.kind, id = (n) => `${n}@${pane.id}`, on = (k) => S.shown(k, pane.id);
  const out = [];
  const V = SIDEM[mode];
  const mm = mul(V, dv ? IDENT : D.epochs[D.epochIdx[i]].mat);
  const px = (n) => ({ widthUnits: 'pixels', getWidth: n });
  const world = D.f.world_at[i] >= 0 ? D.worldAt(D.f.world_at[i]) : null;
  const top = mode === 'top' || mode === '3d';
  const Z = { coordinateSystem: CART, parameters: P };

  out.push(new SolidPolygonLayer({ id: id('map'), data: world ? world.cells : EMPTY, visible: !!world && on('world.grid'), getPolygon: (d) => d.poly, getFillColor: (d) => d.c, pickable: true, modelMatrix: mm, ...Z }));

  const g = cached(mode + scene.id, () => gridFor(mode, scene.bounds));
  out.push(new LineLayer({ id: id('grid'), data: g.lines, visible: S.coord, getSourcePosition: (d) => d.s, getTargetPosition: (d) => d.t, getColor: C.grid.concat(255), getWidth: 1, widthUnits: 'pixels', modelMatrix: V, ...Z }));
  out.push(new TextLayer({ id: id('gridnum'), data: g.labels, visible: S.coord, getPosition: (d) => d.p, getText: (d) => d.text, getSize: 11, getColor: C.text.concat(255), getTextAnchor: (d) => d.anchor, getAlignmentBaseline: (d) => d.base, modelMatrix: V, ...Z }));

  const solid = (n, list, col, vis) => new SolidPolygonLayer({ id: id(n), data: cached(`${scene.id}:${n}:${mode}`, () => faces(list, mode)), visible: vis, getPolygon: (d) => d.poly, getFillColor: col,
    ...(mode === '3d' ? { extruded: true, getElevation: (d) => d.h, material: FLAT } : {}), modelMatrix: IDENT, ...Z });
  const boxes = !dv && on('scene.boxes'), hazards = !dv && on('scene.hazards');
  // faces are filled from above and in 3D only: in a side view the boxes' rectangles pile up into a dark band, so they are outlines there
  const filled = mode === 'top' || mode === '3d';
  out.push(solid('boxfill', scene.boxFill, C.boxFill, boxes && filled), solid('stairfill', scene.stairFill, C.haz.concat(31), boxes && filled), solid('pitfill', scene.pitFill, C.haz.concat(31), hazards && filled));
  out.push(new PathLayer({ id: id('boxes'), data: scene.boxPaths, visible: boxes, getPath: (d) => d.path, getColor: (d) => (d.stair ? C.haz : C.box).concat(255), ...px(1.2), modelMatrix: V, ...Z }));
  out.push(new PathLayer({ id: id('hazards'), data: scene.hazardPaths, visible: hazards, getPath: (d) => d.path, getColor: C.haz.concat(255), ...px(1.5), getDashArray: [3, 2], dashJustified: true, extensions: DASH, modelMatrix: V, ...Z }));
  const pi = D.f.plan_at[i];
  out.push(new PathLayer({ id: id('plan'), data: pi >= 0 ? D.planData[pi] : EMPTY, visible: pi >= 0 && on('plan.path'), getPath: (d) => d.path, getColor: C.plan.concat(255), ...px(S.size('plan.path')), getDashArray: [3, 2], dashJustified: true, extensions: DASH, modelMatrix: mm, ...Z }));

  for (const ch of ['f', 'o', 'v', 'b']) {
    const sid = { f: 'sensors.depth.floor', o: 'sensors.depth.obstacle', v: 'sensors.depth.overhead', b: 'sensors.depth.below' }[ch];
    const tm = S.cfg(sid), vis = on(sid);
    const [a, b] = tm.mode === 'at' ? [D.depthIdx[i], D.depthIdx[i]] : ticksFor(S, sid, i);
    D.chunks.forEach((c, ci) => {                      // one layer per stretch of loaded ticks, always in the list
      const r = vis ? D.depthRange(ci, ch, a, b) : null;
      if (r) S.pickBase[id(`depth${ch}${ci}`)] = { ch, ci, base: r.base };
      out.push(new ScatterplotLayer({ id: id(`depth${ch}${ci}`), data: r ? r.data : EMPTY_POINTS, visible: !!r && r.data.length > 0, getFillColor: KIND_COL[ch], getRadius: S.size(sid) / 2, radiusUnits: 'pixels', pickable: true, modelMatrix: mm, ...Z }));
    });
  }
  out.push(new ScatterplotLayer({ id: id('obst'), data: world ? world.obstacles : EMPTY, visible: !!world && on('world.obstacles'), getPosition: (d) => d, getFillColor: C.obst.concat(255), getRadius: S.size('world.obstacles') / 2, radiusUnits: 'pixels', modelMatrix: mm, ...Z }));
  out.push(new ScatterplotLayer({ id: id('drops'), data: world ? world.drops : EMPTY, visible: !!world && on('world.drops'), getPosition: (d) => d, getFillColor: C.haz.concat(255), getRadius: S.size('world.drops') / 2, radiusUnits: 'pixels', modelMatrix: mm, ...Z }));

  const tp = D.f.truth[i], bp = dv ? D.f.belief[i] : D.beliefW[i];
  const track = (sid, col, name, tr, vis) => {
    const [a, b] = ticksFor(S, sid, i, SHORT_TAIL_S);
    out.push(new PathLayer({ id: id(name + 'track'), data: vis ? pathsOf(tr, a, b) : EMPTY, visible: vis, getPath: (d) => d.path, getColor: col.concat(200), ...px(S.size(sid)), modelMatrix: V, ...Z }));
  };
  const r = D.run.robot.radius, h = D.run.robot.height;
  const robot = (name, col, p, vis) => {
    out.push(new PathLayer({ id: id(name + 'bot'), data: vis ? robotPaths(p, r, h) : EMPTY, visible: vis, getPath: (d) => d.path, getColor: col.concat(255), ...px(2), modelMatrix: V, ...Z }));
    out.push(new ScatterplotLayer({ id: id(name + 'fill'), data: vis ? [p] : EMPTY, visible: vis && top, getPosition: (d) => [d[0], d[1], 0], getRadius: r, radiusUnits: 'meters', getFillColor: col.concat(60), pickable: true, modelMatrix: V, ...Z }));
  };
  const showTruth = !dv && !!tp;
  track('truth.track', C.truth, 'truth', D.trackT, showTruth && on('truth.track'));
  robot('truth', C.truth, tp, showTruth && on('truth.pose'));
  track('belief.track', C.belief, 'belief', dv ? D.trackMap : D.trackW, on('belief.track'));
  robot('belief', C.belief, bp, on('belief.pose'));

  const rel = S.rel.belief_truth && !dv && !!tp && on('belief.pose') && on('truth.pose');
  const q = rel ? [(bp[0] + tp[0]) / 2, (bp[1] + tp[1]) / 2, h / 2] : [0, 0, 0], d = rel ? Math.hypot(bp[0] - tp[0], bp[1] - tp[1]) : 0;
  out.push(new LineLayer({ id: id('rel'), data: rel ? [0] : EMPTY, visible: rel, getSourcePosition: () => [bp[0], bp[1], h / 2], getTargetPosition: () => [tp[0], tp[1], h / 2], getColor: C.rel.concat(255), getWidth: 2, widthUnits: 'pixels', modelMatrix: V, ...Z }));
  out.push(new TextLayer({ id: id('reltext'), data: rel ? [0] : EMPTY, visible: rel, getPosition: () => q, getText: () => `${(d * 100).toFixed(1)} cm`, getSize: 11, getColor: C.rel.concat(255), getPixelOffset: [0, -12], background: true, getBackgroundColor: C.bg.concat(215), modelMatrix: V, ...Z }));
  // the anomalies (RFC-0019): a pin where the robot believed it was (a harness's finding ringed in the viewport's colour), in the world frame also a
  // ring where it was, joined to it by a line; coloured by severity
  const pins = D.anomalyPins(), onA = on('anomalies'), at = (d) => (dv ? d.map : d.world), believed = onA ? pins.filter(at) : EMPTY;
  const both = onA && !dv ? pins.filter((d) => d.world && d.truth) : EMPTY, truthPins = onA && !dv ? pins.filter((d) => d.truth) : EMPTY;
  out.push(new LineLayer({ id: id('anomjoin'), data: both, visible: both.length > 0, getSourcePosition: (d) => d.world, getTargetPosition: (d) => d.truth, getColor: (d) => sevColor(d.severity).concat(255), getWidth: 1.5, widthUnits: 'pixels', modelMatrix: V, ...Z }));
  out.push(new ScatterplotLayer({ id: id('anomtruth'), data: truthPins, visible: truthPins.length > 0, getPosition: (d) => d.truth, getRadius: 6, radiusUnits: 'pixels', stroked: true, filled: false, getLineColor: (d) => sevColor(d.severity).concat(255), lineWidthUnits: 'pixels', getLineWidth: 2, pickable: true, modelMatrix: V, ...Z }));
  out.push(new ScatterplotLayer({ id: id('anomalies'), data: believed, visible: onA, getPosition: at, getRadius: 6, radiusUnits: 'pixels', getFillColor: (d) => sevColor(d.severity).concat(255), stroked: true, getLineColor: (d) => (d.source === 'harness' ? C.bg : sevColor(d.severity)).concat(255), lineWidthUnits: 'pixels', getLineWidth: 2, pickable: true, modelMatrix: V, ...Z }));
  const sp = S.selPos;
  const ring = (n, col, w) => new ScatterplotLayer({ id: id(n), data: sp ? [sp] : EMPTY, visible: !!sp, getPosition: (d) => d, getRadius: 10, radiusUnits: 'pixels', stroked: true, filled: false, getLineColor: col.concat(255), lineWidthUnits: 'pixels', getLineWidth: w, modelMatrix: V, ...Z });
  out.push(ring('selhalo', C.bg, 5.5), ring('sel', C.sel, 3));    // the ring in the theme's selection colour, a halo in the viewport's

  const a = cached('axes' + mode, () => axesFor(mode));
  out.push(new LineLayer({ id: id('axes'), data: a.lines, visible: S.coord, getSourcePosition: (d) => d.s, getTargetPosition: (d) => d.t, getColor: (d) => d.col.concat(255), getWidth: 2.5, widthUnits: 'pixels', modelMatrix: V, ...Z }));
  out.push(new TextLayer({ id: id('axislabels'), data: a.labels, visible: S.coord, getPosition: (d) => d.p, getText: (d) => d.text, getSize: 15, fontWeight: 'bold', getColor: (d) => d.col.concat(255), modelMatrix: V, ...Z }));
  out.push(new ScatterplotLayer({ id: id('origin'), data: [[0, 0, 0]], visible: S.coord, getPosition: (d) => d, getRadius: 4, radiusUnits: 'pixels', stroked: true, filled: false, getLineColor: C.text.concat(255), lineWidthUnits: 'pixels', getLineWidth: 1.5, modelMatrix: V, ...Z }));
  return out;
}
