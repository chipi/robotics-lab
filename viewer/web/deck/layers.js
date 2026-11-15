// Builds the deck.gl layers for one pane. Static data stays referentially stable; only the
// per-moment pieces (poses, track slice, depth frame, plan, world) change with t.
import { IDENT, KIND_COL, CELL_COL, firstAfter } from './data.js';

const { PathLayer, LineLayer, ScatterplotLayer, SolidPolygonLayer, TextLayer, COORDINATE_SYSTEM } = deck;
const CART = COORDINATE_SYSTEM.CARTESIAN;
export const C = {
  belief: [70, 130, 255], truth: [40, 180, 90], plan: [230, 180, 0], obst: [255, 150, 0], haz: [230, 0, 230],
  x: [224, 48, 48], y: [48, 176, 48], z: [48, 96, 224], box: [138, 138, 150], grid: [216, 216, 224], text: [100, 100, 112],
  rel: [30, 30, 30], sel: [0, 0, 0], bg: [255, 255, 255],
};
const rgb = (hex) => { const n = parseInt(hex.replace('#', ''), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
// the page's theme tokens (shell palette, CSS hex strings) -> the colours the layers are built with
export function setPalette(p) {
  const c = (k) => rgb(p[k]);
  Object.assign(C, { belief: c('c-belief'), truth: c('c-truth'), plan: c('c-plan'), obst: c('c-obst'), haz: c('c-drop'), x: c('c-x'), y: c('c-y'), z: c('c-z'),
    box: c('c-box'), grid: c('draw-grid'), text: c('draw-label'), rel: c('draw-rel'), sel: c('draw-sel'), bg: c('bg-viewport') });
  Object.assign(KIND_COL, { f: [...c('c-floor'), 255], o: [...c('c-ob'), 255], v: [...c('c-over'), 255], b: [...c('c-drop'), 255] });
  Object.assign(CELL_COL, { occ: [...c('c-occ'), 255], free: [...c('c-free'), 255] });
  gridCache.clear();
}
const P = { depthTest: false };
// Side views are the 2D OrthographicView looking at a rotated world: the modelMatrix sends
// (x, y, z) to (screen x, screen y, depth), so every layer works as it does in the top view.
const SIDEM = {
  top: IDENT, '3d': IDENT,
  front: [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1],
  back: [-1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1],
  right: [0, 0, -1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
  left: [0, 0, 1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
};
const mul = (a, b) => { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k]; return o; };
const PLANE = { top: [0, 1], '3d': [0, 1], front: [0, 2], back: [0, 2], left: [1, 2], right: [1, 2] };
const END_ON = { top: 2, '3d': -1, front: 1, back: 1, left: 0, right: 0 }; // axis pointing at the camera: no label

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

export const SHORT_TAIL_S = 2; // what "at t" shows of a track: a short tail


// ticks a..b a stream shows at tick i, from its time mode
export function ticksFor(S, id, i, tail) {
  const { D } = S, tm = S.cfg(id);
  if (tm.mode === 'upto') return [0, i];
  if (tm.mode === 'window') return [Math.min(firstAfter(D.t[i] - tm.n, D.t), i), i];
  return tail ? [Math.min(firstAfter(D.t[i] - tail, D.t), i), i] : [i, i];
}

export function buildLayers(S, pane) {
  const { D, scene, i, dv } = S, mode = pane.kind, id = (n) => `${n}@${pane.id}`, on = (k) => S.shown(k, pane.id);
  const out = [];
  const V = SIDEM[mode];
  const mm = mul(V, dv ? IDENT : D.epochs[D.epochIdx[i]].mat);
  const px = (n) => ({ widthUnits: 'pixels', getWidth: n });
  const world = D.f.world_at[i] >= 0 ? D.worldAt(D.f.world_at[i]) : null;
  const top = mode === 'top' || mode === '3d';
  const Z = { coordinateSystem: CART, parameters: P };

  if (on('world.grid') && world) out.push(new SolidPolygonLayer({ id: id('map'), data: world.cells, getPolygon: (d) => d.poly, getFillColor: (d) => d.c, pickable: true, modelMatrix: mm, ...Z }));

  if (S.coord) {
    const g = cached(mode + scene.id, () => gridFor(mode, scene.bounds));
    out.push(new LineLayer({ id: id('grid'), data: g.lines, getSourcePosition: (d) => d.s, getTargetPosition: (d) => d.t, getColor: C.grid.concat(255), getWidth: 1, widthUnits: 'pixels', modelMatrix: V, ...Z }));
    out.push(new TextLayer({ id: id('gridnum'), data: g.labels, getPosition: (d) => d.p, getText: (d) => d.text, getSize: 11, getColor: C.text.concat(255), getTextAnchor: (d) => d.anchor, getAlignmentBaseline: (d) => d.base, modelMatrix: V, ...Z }));
  }
  if (!dv && on('scene.boxes')) out.push(new PathLayer({ id: id('boxes'), data: scene.boxPaths, getPath: (d) => d.path, getColor: C.box.concat(255), ...px(1.2), modelMatrix: V, ...Z }));
  if (!dv && on('scene.hazards')) out.push(new PathLayer({ id: id('hazards'), data: scene.hazardPaths, getPath: (d) => d.path, getColor: C.haz.concat(255), ...px(2), modelMatrix: V, ...Z }));
  if (on('plan.path') && D.f.plan_at[i] >= 0) out.push(new PathLayer({ id: id('plan'), data: D.planData[D.f.plan_at[i]], getPath: (d) => d.path, getColor: C.plan.concat(255), ...px(2.5), modelMatrix: mm, ...Z }));

  for (const ch of ['f', 'o', 'v', 'b']) {
    const sid = { f: 'sensors.depth.floor', o: 'sensors.depth.obstacle', v: 'sensors.depth.overhead', b: 'sensors.depth.below' }[ch];
    if (!on(sid)) continue;
    const tm = S.cfg(sid);
    const [a, b] = tm.mode === 'at' ? [D.depthIdx[i], D.depthIdx[i]] : ticksFor(S, sid, i);
    const r = D.depthRange(ch, a, b);
    if (!r || !r.data.length) continue;
    S.pickBase[id('depth' + ch)] = { ch, base: r.base };
    out.push(new ScatterplotLayer({ id: id('depth' + ch), data: r.data, getFillColor: KIND_COL[ch], getRadius: 3, radiusUnits: 'pixels', pickable: true, modelMatrix: mm, ...Z }));
  }
  if (on('world.obstacles') && world) out.push(new ScatterplotLayer({ id: id('obst'), data: world.obstacles, getPosition: (d) => d, getFillColor: C.obst.concat(255), getRadius: 0.025, radiusUnits: 'meters', modelMatrix: mm, ...Z }));
  if (on('world.drops') && world) out.push(new ScatterplotLayer({ id: id('drops'), data: world.drops, getPosition: (d) => d, getFillColor: C.haz.concat(255), getRadius: 0.03, radiusUnits: 'meters', modelMatrix: mm, ...Z }));

  const track = (sid, col, name, tr) => {
    const [a, b] = ticksFor(S, sid, i, SHORT_TAIL_S);
    out.push(new PathLayer({ id: id(name + 'track'), data: [{ path: tr.slice(a, b + 1).filter(Boolean) }], getPath: (d) => d.path, getColor: col.concat(200), ...px(2), modelMatrix: V, ...Z }));
  };
  const r = D.run.robot.radius, h = D.run.robot.height;
  const robot = (name, col, p, who) => {
    out.push(new PathLayer({ id: id(name + 'bot'), data: robotPaths(p, r, h), getPath: (d) => d.path, getColor: col.concat(255), ...px(2), modelMatrix: V, ...Z }));
    if (top) out.push(new ScatterplotLayer({ id: id(name + 'fill'), data: [p], getPosition: (d) => [d[0], d[1], 0], getRadius: r, radiusUnits: 'meters', getFillColor: col.concat(60), pickable: true, modelMatrix: V, ...Z }));
  };
  const tp = D.f.truth[i], bp = dv ? D.f.belief[i] : D.beliefW[i];
  if (!dv && tp) {
    if (on('truth.track')) track('truth.track', C.truth, 'truth', D.trackT);
    if (on('truth.pose')) robot('truth', C.truth, tp);
  }
  if (on('belief.track')) track('belief.track', C.belief, 'belief', dv ? D.trackMap : D.trackW);
  if (on('belief.pose')) robot('belief', C.belief, bp);

  if (S.rel.belief_truth && !dv && tp && on('belief.pose') && on('truth.pose')) {
    const q = [(bp[0] + tp[0]) / 2, (bp[1] + tp[1]) / 2, h / 2], d = Math.hypot(bp[0] - tp[0], bp[1] - tp[1]);
    out.push(new LineLayer({ id: id('rel'), data: [0], getSourcePosition: () => [bp[0], bp[1], h / 2], getTargetPosition: () => [tp[0], tp[1], h / 2], getColor: C.rel.concat(255), getWidth: 2, widthUnits: 'pixels', modelMatrix: V, ...Z }));
    out.push(new TextLayer({ id: id('reltext'), data: [0], getPosition: () => q, getText: () => `${(d * 100).toFixed(1)} cm`, getSize: 11, getColor: C.rel.concat(255), getPixelOffset: [0, -12], background: true, getBackgroundColor: C.bg.concat(215), modelMatrix: V, ...Z }));
  }
  const sp = S.selPos;
  if (sp) out.push(new ScatterplotLayer({ id: id('sel'), data: [sp], getPosition: (d) => d, getRadius: 9, radiusUnits: 'pixels', stroked: true, filled: false, getLineColor: C.sel.concat(255), lineWidthUnits: 'pixels', getLineWidth: 2, modelMatrix: V, ...Z }));

  if (S.coord) {
    const a = cached('axes' + mode, () => axesFor(mode));
    out.push(new LineLayer({ id: id('axes'), data: a.lines, getSourcePosition: (d) => d.s, getTargetPosition: (d) => d.t, getColor: (d) => d.col.concat(255), getWidth: 2.5, widthUnits: 'pixels', modelMatrix: V, ...Z }));
    out.push(new TextLayer({ id: id('axislabels'), data: a.labels, getPosition: (d) => d.p, getText: (d) => d.text, getSize: 15, fontWeight: 'bold', getColor: (d) => d.col.concat(255), modelMatrix: V, ...Z }));
    out.push(new ScatterplotLayer({ id: id('origin'), data: [[0, 0, 0]], getPosition: (d) => d, getRadius: 4, radiusUnits: 'pixels', stroked: true, filled: false, getLineColor: C.text.concat(255), lineWidthUnits: 'pixels', getLineWidth: 1.5, modelMatrix: V, ...Z }));
  }
  return out;
}
