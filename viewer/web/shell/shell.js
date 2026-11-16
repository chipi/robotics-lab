// The miniview workbench, built once for both pages (UXS-001 "The whole page"): top bar, outliner and
// stream properties, inspector, timeline, status bar, themes, keys. A page supplies only a renderer
// adapter, which draws into #stage; everything else, and every byte of data, is this file's (the data
// comes only from the API, CONTRACT.md).
//
// adapter = {
//   init(stage, shell)       create the canvas / deck inside the stage element; shell.M is the model
//   setScene(scene)          the scene (world frame) of the run about to open
//   setRun(run, fr)          a run's summary and the frames loaded so far (ticks 0..n-1 without a hole); again when what depends on an epoch changed
//   append(range)            the run grew: range = {i0, i1, plans: [k..], worlds: [k..]}, the ticks i0..i1-1 and the plan and world numbers that became available; nothing is rebuilt
//   setLayout(view, frame)   rebuild the panes for view (top|front|back|left|right|three|3d) and frame
//   draw(sync)               draw the model now (time, visibility, time modes, relations, selection)
//   settled() -> Promise     resolves once what was drawn has been painted
//   resize(), fit(), theme(palette)
//   describe(sel) -> {stream, detail, p:[x,y], height, tick, t, frame, ...} | null
//   cursor(clientX, clientY) -> {axes:['x','y'], v:[a,b], note?} | null   the world axes of the pane under the pointer
//   fillsDrawn(pane) -> whether the faint box faces are drawn in the pane named so (top and 3d: yes; side views: outlines only)
//   project([x,y,z]) -> [clientX, clientY] of a world point in the first pane (tests probe pixels there)
//   scale() -> pixels per metre of the first (bottom-left) orthographic pane, or null (3D)
//   gizmo() -> {x:[dx,dy,dz], y, z} | null     camera-space unit vectors (3D view only)
// }
// shell (given to the adapter): M, shown(id, view), cfg(id), size(id), pick(sel), viewChanged(), tickAt(t), palette()
import { svgI, paintIcons } from './icons.js';
import { RunStore } from './runstore.js';
import { createSignalsView, sigColor, sampleAt } from './signals.js';

const API = '/api/v1/';
const json = (u, o) => fetch(u, o).then((r) => { if (!r.ok) throw new Error(u + ' ' + r.status); return r.json(); });
const noScene = (id) => ({ id, name: id, kind: 'no layout', frame: 'world', bounds: [-4, 4, -3, 3], boxes: [], hazards: [] });   // a run whose scene has no layout (ADR-0013 `unmapped`)
// each hazard's outline for the renderers: its rectangle, turned by `yaw` about its centre when it has one (ADR-0015's scenes)
function withCorners(sc) {
  for (const h of sc.hazards) {
    const cx = (h.x0 + h.x1) / 2, cy = (h.y0 + h.y1) / 2, c = Math.cos(h.yaw || 0), s = Math.sin(h.yaw || 0);
    h.corners = [[h.x0, h.y0], [h.x1, h.y0], [h.x1, h.y1], [h.x0, h.y1]].map(([x, y]) => [cx + c * (x - cx) - s * (y - cy), cy + s * (x - cx) + c * (y - cy)]);
  }
  return sc;
}
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const f3 = (n) => (n == null ? null : +n.toFixed(4));
const fx = (n, d = 3) => (n == null ? '—' : n.toFixed(d).replace('-', '−'));
const nf = (n) => Number(n).toLocaleString('en');
const deg = (r) => (r * 180) / Math.PI;
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

const VIEW_ALIAS = { side: 'right', T: 'top', F: 'front', S: 'right', '3D': '3d' };
const VIEWS = ['top', 'front', 'back', 'left', 'right', 'three', '3d'];
const VIEW_NOTE = {
  top: 'Top · x right, y up', front: 'Front · from +x, y right, z up', back: 'Back · from -x, y left, z up',
  left: 'Left · from +y, x left, z up', right: 'Side · from -y, x right, z up', '3d': '3D · perspective, drag to orbit',
  three: 'Three views · top, front and side',
};
// screen directions of the world axes in the one-view layouts (dx, dy up, dz toward the viewer)
const AXES = {
  top: { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }, front: { x: [0, 0, 1], y: [1, 0, 0], z: [0, 1, 0] },
  back: { x: [0, 0, -1], y: [-1, 0, 0], z: [0, 1, 0] }, left: { x: [-1, 0, 0], y: [0, 0, 1], z: [0, 1, 0] },
  right: { x: [1, 0, 0], y: [0, 0, -1], z: [0, 1, 0] },
};
const GROUP_IDS = { Scene: 'g.scene', 'Robot (belief)': 'g.belief', Truth: 'g.truth', Sensors: 'g.sensors', 'World model': 'g.world', Plan: 'g.plan', Robot: 'g.robot' };

// drawn size per stream, in pixels: a point's diameter or a line's width (Display > Point size / Line width)
const SIZE_KIND = {
  'sensors.depth.floor': 'point', 'sensors.depth.obstacle': 'point', 'sensors.depth.overhead': 'point', 'sensors.depth.below': 'point',
  'world.obstacles': 'point', 'world.drops': 'point', 'belief.track': 'line', 'truth.track': 'line', 'plan.path': 'line',
};
const SIZE_DEFAULT = { 'world.obstacles': 5, 'world.drops': 6 };

// event kinds: [colour, stop-like (drawn as a triangle)]
const KINDS = {
  cliff_stop: ['#e05a4f', 1], reflex_stop: ['#ff9600', 1], refused: ['#c8a040', 1], trapped: ['#ff4d6d', 1],
  reached: ['#3cc85a', 0], tight_pivot: ['#a070e0', 0], leg: ['#8a8d96', 0], no_survey_turn: ['#3cb4b4', 0],
};
const kindColor = (k) => KINDS[k]?.[0] || `hsl(${[...k].reduce((a, c) => a * 31 + c.charCodeAt(0), 7) % 360} 50% 55%)`;
const isStop = (k) => (k in KINDS ? !!KINDS[k][1] : /stop|refus|trap/.test(k));

const MODES = [['at', 'At t'], ['window', 'Window'], ['upto', 'Up to t']];
const MODE_WORD = { at: 'at t', window: 'window', upto: 'up to t' };
const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const LANE_NAME = {
  'belief.pose': 'Belief pose', 'truth.pose': 'Truth pose', 'sensors.depth.floor': 'Depth floor', 'sensors.depth.obstacle': 'Depth obstacle',
  'sensors.depth.overhead': 'Depth overhead', 'sensors.depth.below': 'Depth below', 'sensors.tilt': 'Tilt', 'sensors.raw': 'Raw depth frame', 'world.grid': 'Map grid', 'plan.path': 'Plan',
};

// colour (a token) and icon of a stream, by id
function styleOf(id) {
  const c = (v, i) => ({ c: `var(--${v})`, i });
  if (id === 'scene.boxes') return c('c-box', 'box');
  if (id === 'scene.hazards') return c('c-drop', 'hazard');
  if (id.startsWith('belief.')) return c('c-belief', id.endsWith('track') ? 'track' : 'pose');
  if (id.startsWith('truth.')) return c('c-truth', id.endsWith('track') ? 'track' : 'pose');
  if (id === 'sensors.depth') return c('c-floor', 'points');
  if (id.endsWith('.floor')) return c('c-floor', 'points');
  if (id.endsWith('.obstacle')) return c('c-ob', 'points');
  if (id.endsWith('.overhead')) return c('c-over', 'points');
  if (id.endsWith('.below')) return c('c-drop', 'points');
  if (id === 'sensors.tilt') return c('text-dim', 'tilt');
  if (id === 'sensors.raw') return c('c-floor', 'grid');
  if (id === 'world.grid') return c('c-occ', 'grid');
  if (id === 'world.obstacles') return c('c-obst', 'points');
  if (id === 'world.drops') return c('c-drop', 'points');
  if (id === 'plan.path') return c('c-plan', 'route');
  if (id === 'events') return c('warn', 'flag');
  if (id.startsWith('signals.')) return { c: sigColor(id.slice(8)), i: 'track' };
  return c('text-dim', 'points');
}

// ---- the outliner's tree, from the run's stream list (D3: Belief and Truth under Robot) ----------
function buildTree(run) {
  const S = run.streams || [], taken = new Set();
  const mk = (s) => {
    taken.add(s.id);
    const kids = S.filter((x) => x.parent === s.id).map(mk);
    return kids.length ? { id: s.id, s, kids, i: 'points', sfx: s.frame } : { id: s.id, s, leaf: true };
  };
  const top = (groups) => S.filter((s) => groups.includes(s.group) && !s.parent && !taken.has(s.id)).map(mk);
  const frameOf = (kids) => { const fr = new Set(); const walk = (k) => k.forEach((n) => (n.kids ? walk(n.kids) : fr.add(n.s.frame))); walk(kids); return fr.size === 1 ? [...fr][0] : ''; };
  const grp = (id, name, groups, sfx) => { const kids = top(groups); return kids.length ? { id, name, kids, i: 'group', sfx: sfx ?? frameOf(kids) } : null; };
  const belief = grp('g.belief', 'Belief', ['Robot (belief)']), truth = grp('g.truth', 'Truth', ['Truth'], 'world · sim only');
  const robotKids = [belief, truth].filter(Boolean);
  const tree = [
    grp('g.scene', 'Scene', ['Scene']),
    robotKids.length ? { id: 'g.robot', name: 'Robot', sfx: run.robot?.name || '', i: 'robot', kids: robotKids } : null,
    grp('g.sensors', 'Sensors', ['Sensors'], ''), grp('g.world', 'World model', ['World model']), grp('g.plan', 'Plan', ['Plan']),
  ].filter(Boolean);
  for (const s of S) {
    if (taken.has(s.id) || s.parent) continue;
    const same = S.filter((x) => x.group === s.group && !taken.has(x.id) && !x.parent);
    if (same.length === 1 && s.group.toLowerCase() === s.name.toLowerCase()) tree.push(mk(s));
    else tree.push({ id: 'g.' + s.group, name: s.group, i: 'group', kids: same.map(mk), sfx: '' });
  }
  const nodes = {}, parents = {}, order = [];
  const walk = (list, ps) => list.forEach((n) => {
    if (nodes[n.id]) return;
    nodes[n.id] = n; parents[n.id] = ps; order.push(n.id);
    if (n.kids) walk(n.kids, [...ps, n.id]);
  });
  walk(tree, []);
  const leaves = (id) => { const n = nodes[id], out = []; const w = (x) => (x.kids ? x.kids.forEach(w) : out.push(x.id)); if (n) w(n); return out; };
  return { tree, nodes, parents, order, leaves };
}

export function createShell(adapter, { title = 'miniview' } = {}) {
  document.title = title;
  // ---- the model ---------------------------------------------------------------------------------
  const M = {
    index: null, sceneId: null, runId: null, scene: null, run: null, fr: null, pres: null, bw: [],
    t: 0, i: 0, view: 'top', frame: 'world', on: {}, vv: {}, modes: {}, rel: { belief_truth: true, depth_pose: false },
    size: {}, sel: null, selNode: null, ov: { coords: true, gizmo: true, legend: true }, open: {}, query: '', hideMissing: false,
    tab: 'moment', secOpen: {}, kinds: {}, rows: true, play: { on: false, speed: 1, loop: false }, loading: false, theme: 'dark', follow: true,
  };
  let T = { tree: [], nodes: {}, parents: {}, order: [], leaves: () => [] };
  const sceneCache = {};
  let busy = 0, laidOut = false;

  document.body.innerHTML = TEMPLATE;
  paintIcons();
  const stage = $('stage'), app = $('app');
  const sigView = createSignalsView($('sigview'), { seek: (t) => setTime(t) });

  const stream = (id) => (M.run?.streams || []).find((s) => s.id === id);
  const cfg = (id) => M.modes[id] || { mode: 'at', n: 2 };
  const nodeId = (id) => {
    if (T.nodes[id]) return id;
    const k = String(id).replace(/^group:/, '');
    return T.nodes[k] ? k : T.nodes[GROUP_IDS[k]] ? GROUP_IDS[k] : (T.order.find((x) => T.nodes[x].name === k) || null);
  };
  // the loaded tick at or before t (the nearest loaded one when t lies in a part that is not loaded yet)
  const tickAt = (t) => store.tickAt(t);
  const hasTicks = () => !!M.fr && M.fr.ranges.length > 0;
  // a robot's named values (ADR-0013): the run declares them; a run with them and no pose shows them as charts in the viewport
  const hasSignals = () => !!M.run?.signals?.length;
  const signalsOnly = () => !!M.runId && hasSignals() && !hasTicks();
  const sampleN = () => store.sig.t.length;
  const sampleIdx = (t) => sampleAt(store.sig.t, t);
  // the span of the run's ticks (from the data rows), whatever is loaded
  const tickSpan = () => { const sp = M.pres?.streams?.['belief.pose']?.spans; return sp?.length ? [sp[0][0], sp[sp.length - 1][1]] : [M.run.t0, M.run.t1]; };
  // the span the timeline marks as recorded: the ticks', else the samples' (a run with signals and no pose); null when there is nothing yet
  const dataSpan = () => (hasTicks() ? tickSpan() : hasSignals() && sampleN() ? [store.sig.t[0], store.sig.t[sampleN() - 1]] : null);

  // a stream shows when it is in the run and it, its parent and its groups are on, here and (given a view) in that view
  function shown(id, view) {
    if (id === 'rel.belief_truth') return M.rel.belief_truth && M.frame === 'world' && shown('belief.pose', view) && shown('truth.pose', view);
    const s = stream(id);
    if (!s || s.missing) return false;
    return [id, ...(T.parents[id] || [])].every((k) => M.on[k] !== false && !(view && M.vv[view]?.[k] === false));
  }
  const size = (id) => M.size[id] ?? SIZE_DEFAULT[id] ?? (SIZE_KIND[id] === 'line' ? 2 : 4);
  const frameName = () => (M.frame === 'map' ? 'Map' : 'World');
  const palette = () => {
    const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue('--' + n).trim();
    return Object.fromEntries(['bg-viewport', 'c-belief', 'c-truth', 'c-plan', 'c-obst', 'c-drop', 'c-floor', 'c-ob', 'c-over', 'c-box', 'c-occ', 'c-free',
      'c-x', 'c-y', 'c-z', 'draw-grid', 'draw-label', 'draw-rel', 'draw-sel', 'box-fill', 'text'].map((n) => [n, v(n)]).concat([['dark', M.theme === 'dark']]));
  };

  // ---- epochs, belief in the world, the moment ---------------------------------------------------------
  const epochAt = (t) => { const eps = (store.run || M.run).epochs; let e = eps[0]; for (const x of eps) if (x.from_t <= t) e = x; return e; };
  const toWorld = ([tx, ty, h], [x, y, yaw]) => { const c = Math.cos(h), s = Math.sin(h); return [tx + c * x - s * y, ty + s * x + c * y, yaw + h]; };
  const lastEvent = () => {
    if (!M.run) return null;
    const lim = Math.max(M.t, hasTicks() ? M.fr.t[M.i] : M.t);
    return [...M.run.events].reverse().find((e) => e.t <= lim + 1e-9) || null;
  };
  function moment() {
    const { fr, run } = M, i = M.i, bm = fr.belief[i], bw = M.bw[i], tr = fr.truth[i];
    const dist = tr ? Math.hypot(bw[0] - tr[0], bw[1] - tr[1]) : null;
    let di = -1; for (let k = i; k >= 0; k--) if (fr.depth[k]) { di = k; break; }
    const cnt = { f: 0, o: 0, v: 0, b: 0 };
    for (const p of fr.depth[di] || []) if (p[3] in cnt) cnt[p[3]]++;
    const pi = fr.plan_at[i], wi = fr.world_at[i];
    return {
      t: fr.t[i], tick: i, n: run.ticks, epoch: epochAt(fr.t[i]).from_t, bm, bw, tr, dist,
      herr: tr ? deg(wrap(bw[2] - tr[2])) : null, cmd: fr.cmd[i], depthTick: di, cnt,
      plan: pi >= 0 ? { k: pi + 1, n: store.planCount, t: fr.plans[pi].t } : null, world: wi >= 0 ? { k: wi + 1, n: store.worldCount, t: fr.worlds[wi].t } : null,
      ev: lastEvent(), run,
    };
  }
  // the signals' values at the playhead: the sample at or before it (ADR-0013); null when there is no sample yet
  function sigMoment() {
    const n = sampleN(), i = sampleIdx(M.t);
    if (!n || i < 0) return null;
    const { t, v } = store.sig;
    return { i, n, t: t[i], values: Object.fromEntries((M.run.signals || []).map((d) => [d.name, v[d.name]?.[i] ?? null])) };
  }

  // The raw depth frame at the playhead (ADR-0014), for the inspector: asked of /sensor, and kept while the playhead stays between that
  // frame and the next (`next_t`); the last frame stays current until the stream's count (it arrives by record) says a newer one exists.
  // One request at a time.
  const RAW_VALID = [5, 9];          // the sensor's "range valid" statuses
  // `failed` starts at -Infinity: performance.now() counts from the page's start, so 0 read as "failed just now" for the first 500 ms
  // and a page that drew its inspector that early never asked for a frame (CI 2026-11-16)
  const raw = { key: null, fr: null, busy: false, failed: -Infinity };
  function rawFrame(strict = false) {
    const s = stream('sensors.raw');
    if (!M.runId || !M.run || s?.missing) return null;
    const r = raw, f = r.fr, now = performance.now();
    const fresh = f && r.key === M.runId && (f.index === 0 || M.t >= f.t) && (f.next_t != null ? M.t < f.next_t : f.index >= (s?.count ?? f.n) - 1);
    if (!fresh && !r.busy && now - r.failed > 500) {
      r.busy = true;
      const key = M.runId;
      // a failed request (or one unanswered for 5 s) is asked again once the pause is over: nothing else may redraw the inspector before then
      json(`${API}runs/${key}/sensor?t=${M.t}`, { signal: AbortSignal.timeout(5000) }).then((a) => { r.fr = a; r.key = key; },
        () => { r.fr = null; r.failed = performance.now(); setTimeout(() => M.runId === key && scheduleInsp(), 550); })
        .finally(() => { r.busy = false; if (M.runId === key) scheduleInsp(); });
    }
    return f && r.key === M.runId && (fresh || !strict) ? f : null;
  }
  // for scripts: the frame at the playhead, or null while it is still being asked for (the inspector keeps showing the last one meanwhile)
  const rawSummary = () => { const f = rawFrame(true); return f ? { i: f.index, n: f.n, t: f.t, frame_t_ns: f.frame_t_ns, state_t_ns: f.state_t_ns ?? null, pair_dt_ms: f.pair_dt_ms ?? null } : null; };
  // the 8 x 8 distances as an image, coloured by distance (near warm, far cool) with the mm in each zone; a zone whose status is not valid is hatched and says its status
  function paintRaw(cv, f) {
    const cell = cv.width / f.cols, g = cv.getContext('2d');
    g.font = `${Math.round(cell * 0.3)}px ui-monospace, monospace`; g.textAlign = 'center'; g.textBaseline = 'middle';
    for (let r = 0; r < f.rows; r++) for (let c = 0; c < f.cols; c++) {
      const k = r * f.cols + c, x = c * cell, y = r * cell, d = f.distance_mm[k], ok = RAW_VALID.includes(f.status[k]);
      if (ok) { g.fillStyle = `hsl(${Math.round(240 * Math.min(Math.max(d, 0) / 4000, 1))} 65% 38%)`; g.fillRect(x, y, cell, cell); g.fillStyle = '#fff'; g.fillText(String(d), x + cell / 2, y + cell / 2); }
      else {
        g.fillStyle = '#2c2e34'; g.fillRect(x, y, cell, cell);
        g.strokeStyle = '#6b6f78'; g.lineWidth = 1; g.beginPath();
        for (let o = -cell; o < cell; o += 6) { g.moveTo(x + Math.max(o, 0), y + Math.max(-o, 0)); g.lineTo(x + Math.min(o + cell, cell), y + Math.min(cell - o, cell)); }
        g.stroke(); g.fillStyle = '#e8c070'; g.fillText('s' + f.status[k], x + cell / 2, y + cell / 2);
      }
      g.strokeStyle = 'rgba(0,0,0,.45)'; g.strokeRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
    }
  }
  function rawSection() {
    if (!M.runId || stream('sensors.raw')?.missing !== false) return kv('Raw frame', 'not in this run', '', 'na');
    const f = rawFrame();
    if (!f) return kv('Raw frame', 'loading', '', 'na');
    const ok = f.status.map((s, k) => (RAW_VALID.includes(s) ? f.distance_mm[k] : null)).filter((d) => d != null);
    const dt = f.pair_dt_ms;
    return `<canvas class="rawcv" id="rawcv" width="240" height="240" data-i="${f.index}" data-t="${f.t}" data-valid="${ok.length}" data-rows="${f.rows}" data-cols="${f.cols}" title="The sensor's ${f.rows} x ${f.cols} zones, row 0 at the top, mm; hatched = status not valid"></canvas>`
      + kv('Raw frame', `${f.index + 1} of ${f.n}`) + kv('Recorded at', fx(f.t, 3), 's')
      + kv('Valid zones', `${ok.length} of ${f.rows * f.cols}`) + kv('Nearest valid', ok.length ? String(Math.min(...ok)) : 'none', ok.length ? 'mm' : '', ok.length ? '' : 'na')
      + (dt != null ? kv('State minus frame', (dt > 0 ? '+' : '') + fx(dt, 1), 'ms') : kv('Paired state', f.state_t_ns != null ? 'no time to pair by' : 'none', '', 'na'));
  }

  // ---- loading (ADR-0011): the run store loads by window, then by record; the renderers take appends ----------
  const store = new RunStore({
    json,
    onAppend: (range) => {
      for (let k = range.i0; k < range.i1; k++) M.bw[k] = toWorld(epochAt(store.fr.t[k]).map_to_world, store.fr.belief[k]);
      if (built) adapter.append(range);
      grew();
    },
    onRecord: (kind, d) => {
      if (kind === 'epoch' && built && hasTicks() && d.t <= store.lastT) {        // an epoch behind drawn ticks: what depends on it is drawn again
        M.bw = store.fr.belief.map((p, k) => toWorld(epochAt(store.fr.t[k]).map_to_world, p));
        adapter.setRun(M.run, M.fr);
      }
      if (kind === 'event' && !(d.kind in M.kinds)) M.kinds[d.kind] = d.kind !== 'leg';
      grew();
    },
    onStatus: () => { renderChrome(); grew(); },
    onReload: () => { const sc = M.sceneId, r = M.runId; if (r) openRun(sc, r).catch((e) => console.warn(e)); },
  });
  let built = false;                           // the adapter has the run: from now on it is told what was appended
  const ensureIndex = async (fresh) => { if (!M.index || fresh) M.index = await json(API + 'scenes'); return M.index; };
  const runsOf = (sc) => sc.runs;
  // a run of a scene by key, or by name when only one run has it
  function findRun(sc, id) {
    const exact = sc.runs.find((r) => r.key === id);
    if (exact) return exact;
    const named = sc.runs.filter((r) => r.id === id);
    if (named.length > 1) throw new Error(`${named.length} runs are called ${id} in scene ${sc.id}: ${named.map((r) => r.key).join(', ')}`);
    return named[0] || null;
  }

  function layout() { laidOut = hasTicks(); if (laidOut) adapter.setLayout(M.view, M.frame); }

  async function openRun(sceneId, runId) {
    M.loading = true;
    try {
      await ensureIndex(true);
      if (sceneId === undefined && runId === undefined) { M.loading = false; return scenesPage(); }
      const sc = sceneId === undefined ? (M.index.scenes.find((s) => s.id === M.sceneId) || M.index.scenes[0]) : M.index.scenes.find((s) => s.id === sceneId);
      if (!sc) throw new Error(`unknown scene ${sceneId}`);
      const r0 = runId === undefined ? sc.runs[0] : findRun(sc, runId);
      if (!r0) throw new Error(runId === undefined ? `scene ${sc.id} has no runs` : `unknown run ${runId} in scene ${sc.id}`);
      // the index says which scenes have no layout (their runs are listed, nothing of the scene is drawn): no request for one
      const scene = sceneCache[sc.id] ||= withCorners(sc.kind === 'no layout' ? noScene(sc.id) : await json(`${API}scenes/${sc.id}`).catch((e) => { if (/ 404$/.test(String(e))) return noScene(sc.id); throw e; }));
      built = false;
      const first = await store.open(r0.key, M.follow && r0.status === 'live' ? 'end' : 'start');
      if (!first) return null;                                           // another load took over
      const { run, pres } = first;
      if (scene.kind === 'no layout') for (const s of run.streams || []) if (s.id.startsWith('scene.')) Object.assign(s, { count: 0, missing: true, why: 'no scene' });
      if (M.sceneId !== sc.id || M.scene !== scene) { M.scene = scene; adapter.setScene(scene); }
      M.sceneId = sc.id; M.runId = r0.key;
      M.on = {}; M.vv = {}; M.size = {}; M.sel = null; M.kinds = {};
      T = buildTree(run);
      const live0 = (id) => T.nodes[id]?.leaf && !T.nodes[id].s.missing;
      M.selNode = live0('belief.pose') || !run.signals?.length ? (T.nodes['belief.pose'] ? 'belief.pose' : T.order[0] || null) : T.order.find((id) => id.startsWith('signals.') && live0(id)) || 'g.Signals';
      M.open = Object.fromEntries(T.order.filter((id) => T.nodes[id].kids).map((id) => [id, true]));
      M.modes = Object.fromEntries((run.streams || []).map((s) => [s.id, { mode: s.default_mode || 'at', n: 2 }]));
      M.run = run; M.fr = store.fr; M.pres = pres;
      if (hasSignals() && !hasTicks()) M.hideMissing = true;                   // what the run has is the signals: the streams it lacks are a click away ("Show them")
      M.bw = M.fr.belief.map((p, k) => toWorld(epochAt(M.fr.t[k]).map_to_world, p));
      for (const e of run.events) if (!(e.kind in M.kinds)) M.kinds[e.kind] = e.kind !== 'leg';
      if (hasTicks()) { adapter.setRun(run, M.fr); built = true; }
      const live = run.status === 'live';
      $('follow').hidden = !live;
      M.t = M.follow && live ? run.t1 : run.t0;
      M.i = hasTicks() ? tickAt(M.t) : 0;
      app.classList.remove('scenes');
      M.loading = false;
      layout();
      askRender();
      renderAll();
      return state();
    } finally { M.loading = false; }
  }

  function scenesPage() {
    play(false);
    app.classList.add('scenes');
    M.runId = null; store.close(); built = false; $('follow').hidden = true;
    writeHash();
    $('scenespage').innerHTML = M.index.scenes.map((s) => `<div class="sc"><h2>${esc(s.name)}</h2><span class="dim">${esc(s.id === s.kind ? s.kind : s.id + ' · ' + s.kind)} · ${s.runs.length} runs</span>`
      + '<table><thead><tr><th>run</th><th>kind</th><th>robot</th><th>length</th><th>verdict</th><th>events</th></tr></thead><tbody>'
      + s.runs.map((r) => `<tr data-scene="${esc(s.id)}" data-run="${esc(r.key)}"><td><b>${esc(r.id)}</b></td><td>${esc(r.kind)}</td><td>${esc(r.robot)}</td><td class="mono">${r.length_s} s</td>`
        + `<td><span class="${verdictClass(r.verdict)}">${esc(r.verdict)}</span>${r.status === 'live' ? ' <span class="live-dot"></span>' : ''}${r.status === 'broken' ? ` <span class="verdict" title="${esc(r.error || '')}">broken</span>` : ''}</td><td class="mono">${r.events}</td></tr>`).join('')
      + '</tbody></table></div>').join('');
    renderChrome();
    return null;
  }
  const verdictClass = (v) => (['reached', 'evaluated'].includes(v) ? 'verdict ok' : 'verdict');

  // ---- live (ADR-0005, ADR-0011): the store applies the records; the page follows what it gained, at most 4 times a second ----
  let growTimer = 0, presAt = 0;
  function grew() {
    if (growTimer || !M.run) return;
    growTimer = setTimeout(async () => {
      growTimer = 0;
      if (!M.run || M.loading || !M.runId) return;
      const live = M.run.status === 'live';
      $('follow').hidden = !live;
      if (hasTicks() && !built) { adapter.setRun(M.run, M.fr); built = true; }
      if (hasTicks() && !laidOut) { M.t = M.follow && live ? M.run.t1 : M.run.t0; layout(); }
      if (M.follow && live && (hasTicks() || hasSignals())) M.t = clamp(M.run.t1, M.run.t0, M.run.t1);
      M.i = hasTicks() ? tickAt(M.t) : 0;
      for (const sx of M.run.streams || []) M.modes[sx.id] ||= { mode: sx.default_mode || 'at', n: 2 };
      T = buildTree(M.run);
      renderAll();
      if (live || presStatus !== M.run.status) { presStatus = M.run.status; wantPresence(); }
    }, 250);
  }
  // the timeline's data rows: refetched at most every 2 s while live, and once more after the last change (also at the end)
  let presTimer = 0, presStatus = null;
  function wantPresence() {
    if (presTimer) return;
    presTimer = setTimeout(() => {
      presTimer = 0; presAt = Date.now();
      const key = M.runId;
      if (key) json(`${API}runs/${key}/presence`).then((p) => { if (M.runId === key) { M.pres = p; renderLanes(); } }).catch(() => {});
    }, Math.max(0, 2000 - (Date.now() - presAt)));
  }

  // ---- state changes: each one is a function, a click and a script call do the same thing -----------
  // `following` is the one caller that does not turn Follow live off: the follow itself
  function setTime(t, sync, following = false) {
    if (!M.run) return M.t;
    if (!following && M.follow) { M.follow = false; $('follow-on').checked = false; renderChrome(); }
    M.t = clamp(+t, M.run.t0, M.run.t1);
    if (hasTicks()) { M.i = tickAt(M.t); adapter.draw(sync); }
    syncTime();
    if (signalsOnly()) sigView.update(M.t);
    if (!store.covers(M.t)) store.ensure(M.t).then(() => { if (M.run && hasTicks()) { M.i = tickAt(M.t); adapter.draw(); syncTime(); } });
    return M.t;
  }
  function setView(v) {
    v = VIEW_ALIAS[v] || v;
    if (!VIEWS.includes(v)) return false;
    M.view = v;
    layout();
    renderChrome(); writeHash();
    if (M.run) { renderProps(); renderInsp(); if (hasTicks()) adapter.draw(); updateGizmo(); }
    return true;
  }
  function setFrame(f) {
    M.frame = f === 'map' ? 'map' : 'world';
    layout();
    renderChrome(); writeHash();
    if (M.run) { renderTree(); renderProps(); renderInsp(); if (hasTicks()) adapter.draw(); }
    return M.frame;
  }
  function setVisible(id, v) {
    const nid = nodeId(id);
    if (!nid && !stream(id)) { console.warn('miniview: no stream', id); return false; }
    M.on[nid || id] = !!v;
    refresh();
    return !!v;
  }
  function setTimeMode(id, mode, n) {
    const nid = nodeId(id) || id, ids = T.nodes[nid] ? [...(stream(nid) ? [nid] : []), ...T.leaves(nid)] : [id];
    const hit = ids.filter((k) => stream(k)?.time_modes?.includes(mode));
    if (!hit.length) { console.warn('miniview: stream', id, 'has no time mode', mode); return false; }
    for (const k of hit) M.modes[k] = { mode, n: n ?? M.modes[k]?.n ?? 2 };
    refresh();
    return true;
  }
  function setRelation(name, on) {
    if (name === 'depth_pose') { console.warn('miniview: depth_pose is unavailable, the run has no frame times'); return false; }
    if (name !== 'belief_truth') return false;
    M.rel[name] = !!on;
    refresh();
    return M.rel[name];
  }
  function setViewVisible(view, id, on) {
    view = VIEW_ALIAS[view] || view;
    (M.vv[view] ||= {})[nodeId(id) || id] = !!on;
    refresh();
    return !!on;
  }
  function normSel(sel) {
    if (!sel || sel.kind == null) return null;
    if (sel.kind === 'belief' || sel.kind === 'truth') return { kind: 'robot', index: sel.kind === 'truth' ? 1 : 0 };
    return { kind: sel.kind, index: sel.index, ...(sel.kind === 'cell' && { world: sel.world ?? M.fr?.world_at[M.i] }) };
  }
  function select(sel, tab = true) {
    M.sel = hasTicks() ? normSel(sel) : null;
    if (M.sel && !adapter.describe(M.sel)) M.sel = null;
    if (M.sel && tab) M.tab = 'sel';
    renderInsp();
    if (hasTicks()) adapter.draw();
    return M.sel && selectionOut();
  }
  const selectionOut = () => {
    const d = M.sel && hasTicks() ? adapter.describe(M.sel) : null;
    if (!d) return null;
    const { p, ...rest } = d;
    return { kind: M.sel.kind, index: M.sel.index, ...(M.sel.world !== undefined && { world: M.sel.world }), ...rest, position: [f3(p[0]), f3(p[1])], height: f3(d.height) };
  };
  const identity = () => ({ run: M.runId ? M.run?.key ?? null : null, scene: M.runId ? M.sceneId : null, status: M.runId ? M.run?.status ?? null : null,
    seq: M.runId ? store.seq : null, follow: M.follow, loaded: M.runId ? { ticks: store.ticks, of: M.run?.ticks ?? 0, complete: store.complete, ranges: store.ranges.map((r) => [...r]), samples: sampleN() } : null });
  function state() {
    if (!M.run || !hasTicks()) {
      return { ...identity(), t: M.t, tick: 0, frame: M.frame, view: M.view, belief: null, truth: null, distance: null, last_event: M.run ? lastEvent() : null, selection: null,
        t_range: M.run ? [M.run.t0, M.run.t1] : null, ...(M.run && hasSignals() && { signals: sigMoment(), signals_view: signalsOnly() }) };
    }
    const m = moment();
    return {
      ...identity(), t: M.t, tick: m.tick, tick_t: m.t, frame: M.frame, view: M.view, ...(hasSignals() && { signals: sigMoment() }), raw_frame: rawSummary(),
      belief: m.bw.map(f3), belief_map: m.bm.map(f3), truth: m.tr ? m.tr.map(f3) : null, distance: f3(m.dist), last_event: m.ev,
      selection: selectionOut(), t_range: [M.run.t0, M.run.t1],
      hidden: (M.run.streams || []).filter((s) => !s.missing && !shown(s.id)).map((s) => s.id),
    };
  }

  // ---- playback ---------------------------------------------------------------------------------
  let raf = 0, lastTs = 0;
  function play(on) {
    M.play.on = !!on && !!M.run;
    cancelAnimationFrame(raf);
    if (M.play.on) {
      if (M.t >= M.run.t1 - 1e-6) setTime(M.run.t0);
      lastTs = performance.now();
      raf = requestAnimationFrame(function step(now) {
        if (!M.play.on) return;
        let t = M.t + ((now - lastTs) / 1000) * M.play.speed;
        lastTs = now;
        if (t >= M.run.t1) {
          if (M.play.loop) t = M.run.t0 + (t - M.run.t1); else { setTime(M.run.t1); play(false); return; }
        }
        setTime(t);
        raf = requestAnimationFrame(step);
      });
    }
    renderTransport();
  }
  // the tick numbered k (0-based) of the run: when it is not loaded, the window around where it should be is loaded first
  async function gotoTick(k) {
    k = clamp(k, 0, M.run.ticks - 1);
    if (M.fr.t[k] === undefined) {
      const [a, b] = tickSpan(), est = a + ((b - a) * k) / Math.max(1, M.run.ticks - 1);
      await store.ensure(est);
    }
    setTime(M.fr.t[k] ?? M.fr.t[tickAt(M.t)]);
  }
  function stepSample(d) {
    const ts = store.sig.t, i = sampleIdx(M.t);
    if (i < 0) return;
    setTime(ts[clamp(d < 0 ? (M.t > ts[i] + 1e-6 ? i : i - 1) : i + 1, 0, ts.length - 1)]);
  }
  function stepTick(d) {
    if (!hasTicks()) { if (signalsOnly()) stepSample(d); return; }
    const i = M.i, at = M.fr.t[i];
    gotoTick(d < 0 ? (M.t > at + 1e-6 ? i : i - 1) : i + 1);
  }
  function stepEvent(d) {
    if (!M.run) return;
    const ts = [...new Set(M.run.events.filter((e) => M.kinds[e.kind] !== false).map((e) => e.t))].sort((a, b) => a - b);
    const t = d > 0 ? ts.find((x) => x > M.t + 1e-6) : [...ts].reverse().find((x) => x < M.t - 1e-6);
    if (t !== undefined) setTime(t);
  }

  // ---- popovers ---------------------------------------------------------------------------------
  let popEl = null;
  function popover(anchor, html, bind) {
    closePop();
    popEl = document.createElement('div'); popEl.className = 'pop'; popEl.innerHTML = html; document.body.appendChild(popEl);
    paintIcons(popEl);
    const r = anchor.getBoundingClientRect(), w = popEl.offsetWidth, h = popEl.offsetHeight;
    popEl.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px';
    popEl.style.top = (r.bottom + 4 + h > innerHeight ? Math.max(8, r.top - h - 4) : r.bottom + 4) + 'px';
    bind && bind(popEl);
    setTimeout(() => document.addEventListener('pointerdown', outside), 0);
  }
  const outside = (e) => { if (popEl && !popEl.contains(e.target)) closePop(); };
  function closePop() { popEl?.remove(); popEl = null; document.removeEventListener('pointerdown', outside); }

  // ---- export video (ADR-0017): the render service's engines, asked when a run opens; a job, polled once a second ----------
  let render = null;                      // /api/v1/render's answer, null while it is asked
  let xjob = null, xtimer = null;         // the export started here: { run, engine, id, status, error }
  const SIZES = ['1280x720', '960x540'];
  const BUSY = ['starting', 'queued', 'running'];
  const exportEngines = () => (render?.engines || []).filter((e) => e.available && e.robots.includes(M.runId.split('/')[0]));
  function exportWhy() {
    if (!M.runId) return 'open a run first';
    if (!render) return 'asking the render service';
    if (!render.engines) return render.why || 'no render service';
    if (exportEngines().length) return null;
    const robot = M.runId.split('/')[0];
    return `no engine can render ${robot} runs (${render.engines.map((e) => `${e.name}: ${e.why || 'no model for ' + robot}`).join('; ')})`;
  }
  function renderExport() {
    const why = exportWhy(), b = $('exportBtn');
    b.disabled = !!why;
    b.title = why ? `Export video: ${why}` : 'Render this run as a video';
    paintExport();
  }
  function askRender() {
    const key = M.runId;
    render = null;
    fetch(API + 'render').then((r) => r.json()).catch((e) => ({ available: false, why: `miniview not answering: ${e.message}` }))
      .then((j) => { if (M.runId === key) { render = j; renderExport(); } });
  }
  function openExport(anchor) {
    const engines = exportEngines();
    popover(anchor, `<h6>Export video</h6><div class="xp" id="xp">
      <label>Engine<select id="xEngine">${engines.map((e) => `<option>${esc(e.name)}</option>`).join('')}</select></label>
      <label>From<input id="xFrom" type="number" step="0.1" value="${M.run.t0.toFixed(2)}"><span class="faint">s</span></label>
      <label>To<input id="xTo" type="number" step="0.1" value="${M.run.t1.toFixed(2)}"><span class="faint">s</span></label>
      <label>Size<select id="xSize">${SIZES.map((s) => `<option>${s}</option>`).join('')}</select></label>
      <button class="pick-btn" id="xGo">Start</button>
      <div class="xs" id="xStatus" role="status"></div><div id="xResult"></div></div>`,
    (p) => { p.querySelector('#xGo').onclick = startExport; paintExport(); });
  }
  async function startExport() {
    const key = M.runId, v = (id) => popEl.querySelector(id).value;
    const from = parseFloat(v('#xFrom')), to = parseFloat(v('#xTo'));
    const job = xjob = { run: key, engine: v('#xEngine'), id: null, status: 'starting', error: null };
    if (!Number.isFinite(from) || !Number.isFinite(to) || from > to) { job.status = 'failed'; job.error = 'From must be a number, not after To'; return paintExport(); }
    const body = { engine: job.engine, size: v('#xSize') };
    if (Math.abs(from - M.run.t0) > 0.01) body.from = from;               // the whole run is the default: send a span only when it was changed
    if (Math.abs(to - M.run.t1) > 0.01) body.to = to;
    paintExport();
    try {
      const r = await fetch(`${API}runs/${key}/video`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
      job.id = j.id; job.status = 'queued';
      pollExport(job);
    } catch (e) { job.status = 'failed'; job.error = e.message; }
    if (job === xjob) paintExport();
  }
  function pollExport(job) {
    clearTimeout(xtimer);
    xtimer = setTimeout(async () => {
      try { Object.assign(job, await json(API + 'videos/' + job.id)); } catch (e) { job.status = 'failed'; job.error = e.message; }
      if (job === xjob) paintExport();
      if (BUSY.includes(job.status)) pollExport(job);
    }, 1000);
  }
  function paintExport() {
    const p = popEl?.querySelector('#xp');
    if (!p) return;
    const j = xjob && xjob.run === M.runId ? xjob : null;
    p.querySelector('#xGo').disabled = !!j && BUSY.includes(j.status);
    p.querySelector('#xStatus').innerHTML = !j ? '' : j.status === 'failed' ? `<span class="err">Failed: ${esc(j.error)}</span>` : `Status: <b>${esc(j.status)}</b>`;
    const res = p.querySelector('#xResult'), want = j?.status === 'done' ? j.id : '';
    if (res.dataset.id !== want) {                                          // drawn once: a new innerHTML every second would restart the video
      res.dataset.id = want;
      const url = `${API}videos/${want}/file`;
      res.innerHTML = want ? `<video controls preload="metadata" src="${url}"></video><a class="dl" href="${url}" download="${esc(j.run.replace(/\//g, '-'))}-${esc(j.engine)}.mp4">Download</a>` : '';
    }
  }

  // ---- rendering: the outliner ------------------------------------------------------------------------
  const hl = (s) => { const q = M.query; if (!q) return esc(s); const i = s.toLowerCase().indexOf(q); return i < 0 ? esc(s) : esc(s.slice(0, i)) + '<mark>' + esc(s.slice(i, i + q.length)) + '</mark>' + esc(s.slice(i + q.length)); };
  const nodeName = (n) => (n.s ? cap(n.s.name) : n.name);
  const matches = (n) => !M.query || nodeName(n).toLowerCase().includes(M.query) || n.id.toLowerCase().includes(M.query) || (n.kids || []).some(matches);
  function triState(n) {
    if (M.on[n.id] === false) return 'off';
    if (!n.kids) return 'on';
    const L = T.leaves(n.id).filter((l) => !stream(l).missing), k = L.filter((l) => M.on[l] !== false).length;
    return !L.length ? 'off' : k === L.length ? 'on' : k === 0 ? 'off' : 'mix';
  }
  const notDrawnHere = (id) => M.frame === 'map' && (id.startsWith('scene.') || id.startsWith('truth.'));
  const rate = (s) => (s.missing ? 'missing' : !s.rate_hz && s.count ? 'static' : `${nf(s.count)} · ${s.rate_hz} Hz`);

  function renderTree() {
    if (!M.run) { $('tree').innerHTML = ''; return; }
    let h = '', nMiss = 0;
    const row = (n, d) => {
      const s = n.s, miss = s?.missing;
      if (miss) nMiss++;
      const ps = T.parents[n.id], opened = M.open[n.id] || (M.query && n.kids);
      const st = triState(n), inh = !ps.every((x) => M.on[x] !== false), sty = styleOf(n.id);
      const meta = s ? rate(s) : '';
      const title = s ? `${n.id}\n${miss ? s.why || 'missing' : s.count + ' records' + (s.rate_hz ? ', ' + s.rate_hz + ' Hz' : '')}\nframe ${s.frame}` : n.id;
      const na = !n.kids && notDrawnHere(n.id);
      h += `<div class="row ${n.kids ? 'group' : ''} ${st === 'off' ? 'off' : ''} ${inh ? 'inh' : ''} ${miss ? 'missing' : ''} ${na ? 'na' : ''}" role="treeitem" data-id="${esc(n.id)}" aria-level="${d + 1}"`
        + `${n.kids ? ` aria-expanded="${!!opened}"` : ''} aria-selected="${M.selNode === n.id}" title="${esc(title + (na ? '\nnot drawn in the map frame' : ''))}" style="padding-left:${4 + d * 14}px">`
        + `<span class="caret">${n.kids ? svgI('chev', 12) : ''}</span>`
        + `<span class="ti" style="color:${s && !miss && !n.kids ? sty.c : ''}">${svgI(miss ? 'hazard' : s ? sty.i : n.i, 13)}</span>`
        + `<span class="name">${hl(nodeName(n))}</span>${n.sfx ? `<span class="sfx">${esc(n.sfx)}</span>` : ''}`
        + `<span class="extra"><span class="meta">${esc(meta)}</span><button class="eye" data-eye="${esc(n.id)}" ${miss ? 'disabled' : ''} aria-pressed="${st !== 'off'}" aria-label="Show ${esc(nodeName(n))}">`
        + `${svgI(st === 'on' ? 'eye' : st === 'mix' ? 'eyemix' : 'eyeoff', 13)}</button></span></div>`;
    };
    const walk = (list, d) => list.forEach((n) => {
      if (n.s?.missing && M.hideMissing) { nMiss++; return; }
      if (!matches(n)) return;
      row(n, d);
      if (n.kids && (M.open[n.id] || M.query)) walk(n.kids, d + 1);
    });
    walk(T.tree, 0);
    const missing = (M.run.streams || []).filter((s) => s.missing).length;
    h += `<div class="tfoot">${missing} streams missing in this run${missing ? ` · <button id="hm">${M.hideMissing ? 'Show them' : 'Hide them'}</button>` : ''}</div>`;
    $('tree').innerHTML = h;
    $('hm') && ($('hm').onclick = () => { M.hideMissing = !M.hideMissing; renderTree(); });
  }

  function eyeClick(id) {
    const n = T.nodes[id]; if (!n) return;
    if (!n.kids) { M.on[id] = M.on[id] === false; return refresh(); }
    const st = triState(n);
    if (M.on[id] === false) M.on[id] = true;                          // a hidden group comes back as it was
    else if (st === 'on') M.on[id] = false;                           // children keep their own state, shown dimmed
    else for (const l of T.leaves(id)) if (!stream(l).missing) M.on[l] = true;
    refresh();
  }

  // ---- rendering: the selected stream's properties (left, under the outliner) ----------------------------
  const sec = (key, title, body, extra = '') => `<div class="sec" data-open="${M.secOpen[key] !== false}" data-sec="${key}"><button class="shead"><span class="caret">${svgI('chev', 12)}</span>${title}<span class="act">${extra}</span></button><div class="sbody">${body}</div></div>`;
  const segMode = (cur, avail, id) => `<div class="seg sm" role="group" aria-label="Time mode">${MODES.map(([k, l]) => `<button data-mode="${k}" data-for="${esc(id)}" aria-pressed="${cur === k}" ${avail.includes(k) ? '' : 'disabled title="this stream does not offer it"'}>${l}</button>`).join('')}</div>`;
  const cssColour = (c) => { const m = /^var\((--[^)]+)\)$/.exec(c); return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() : c; };
  function presenceRange(id) {
    const p = M.pres?.streams?.[id]; if (!p) return null;
    const ts = p.spans ? p.spans.flat() : p.times || [];
    return ts.length ? [Math.min(...ts), Math.max(...ts)] : null;
  }

  // A live run refreshes the panels every second; a field being typed in or dragged must not be rebuilt
  // under the cursor, so the panel waits and redraws once the edit ends.
  let propsBusy = false, propsStale = false;
  const propsIdle = () => { propsBusy = false; if (propsStale) { propsStale = false; renderProps(); } };
  function renderProps() {
    const el = $('props');
    if (propsBusy || (el.contains(document.activeElement) && document.activeElement.matches('input, select, textarea'))) {
      propsStale = true; return;
    }
    if (!M.run) { el.innerHTML = '<div class="empty">No run open.</div>'; return; }
    const n = T.nodes[M.selNode];
    if (!n) { el.innerHTML = '<div class="empty">Select a stream in the list.</div>'; return; }
    const s = n.s, sty = s ? styleOf(n.id) : null, group = !!n.kids;
    const leafIds = group ? T.leaves(n.id) : [n.id], live = leafIds.filter((l) => !stream(l).missing);
    let h;
    if (s) {
      h = `<div class="phead"><span style="color:${s.missing ? 'var(--warn)' : sty.c}">${svgI(s.missing ? 'hazard' : sty.i, 16)}</span><span class="nm">${esc(cap(s.name))}</span><span class="fchip">${esc(s.frame)}</span>`
        + `<span class="id">${esc(n.id)}</span><span class="stat">${s.missing ? `<span style="color:var(--warn)">${esc(cap(s.why || 'missing'))}</span>` : `${nf(s.count)} records${s.rate_hz ? ` · ${s.rate_hz} Hz` : ' · static'}`}</span></div>`;
    } else {
      h = `<div class="phead"><span>${svgI(n.i, 16)}</span><span class="nm">${esc(n.name)}</span>${n.sfx ? `<span class="fchip">${esc(n.sfx)}</span>` : '<span></span>'}`
        + `<span class="id">${esc(n.id)}</span><span class="stat">${leafIds.length} streams · ${leafIds.length - live.length} missing</span></div>`;
    }
    const timed = live.filter((l) => !(l.startsWith('scene.') || l === 'events') && stream(l).time_modes?.length);
    if (timed.length) {
      const modes = new Set(timed.map((l) => cfg(l).mode)), cur = modes.size === 1 ? [...modes][0] : null;
      const avail = [...new Set(timed.flatMap((l) => stream(l).time_modes))];
      const win = timed.filter((l) => cfg(l).mode === 'window'), wv = win.length ? cfg(win[0]).n : cfg(timed[0]).n;
      h += sec('time', 'Time', `<span class="lab">Show</span><span>${segMode(cur, avail, n.id)}${modes.size > 1 ? `<span class="ro faint" style="margin-left:6px">mixed: ${[...modes].map((m) => MODE_WORD[m]).join(', ')}</span>` : ''}</span>`
        + `<span class="lab">Window</span><span class="field" id="winf" aria-disabled="${!win.length}" title="Drag to change, click to type; Shift fine, Ctrl coarse"><input id="winv" value="${(+wv).toFixed(1)}" aria-label="Window length in seconds"><span class="u">s</span></span>`);
    }
    const ptIds = live.filter((l) => SIZE_KIND[l] === 'point'), lnIds = live.filter((l) => SIZE_KIND[l] === 'line');
    const hidden = M.on[n.id] !== false && !T.parents[n.id].every((p) => M.on[p] !== false);
    const vis = group ? `${live.filter((l) => shown(l)).length} of ${live.length} shown` : '';
    h += sec('display', 'Display', `<span class="lab">Visible</span><label class="cb"><input type="checkbox" id="vis" ${M.on[n.id] !== false ? 'checked' : ''} ${s?.missing ? 'disabled' : ''}>`
      + `${hidden ? '<span class="faint">hidden by its group</span>' : ''}${vis ? `<span class="dim">${vis}</span>` : ''}</label>`
      + (live.length && !live.every((l) => l.startsWith('signals.')) ? `<span class="lab">In views</span><span class="toggles">${[['top', 'T', 'Top'], ['front', 'F', 'Front'], ['right', 'S', 'Side'], ['3d', '3D', '3D']].map(([v, l, t]) =>
        `<button class="tg" data-vv="${v}" aria-pressed="${M.vv[v]?.[n.id] !== false}" title="${t}">${l}</button>`).join('')}</span>` : '')
      + (s && !s.missing ? `<span class="lab">Colour</span><span class="swatch"><i style="background:${sty.c}"></i>${esc(cssColour(sty.c))}</span>` : '')
      + (ptIds.length ? `<span class="lab">Point size</span><span class="field" id="pszf" title="Drag to change, click to type; Shift fine, Ctrl coarse"><input id="pszv" value="${size(ptIds[0]).toFixed(1)}" aria-label="Point size in pixels"><span class="u">px</span></span>` : '')
      + (lnIds.length ? `<span class="lab">Line width</span><span class="field" id="lszf" title="Drag to change, click to type; Shift fine, Ctrl coarse"><input id="lszv" value="${size(lnIds[0]).toFixed(1)}" aria-label="Line width in pixels"><span class="u">px</span></span>` : ''));
    if (s) {
      const pr = presenceRange(n.id);
      h += sec('source', 'Source', `<span class="lab">Frame</span><span class="ro">${esc(s.frame)}</span><span class="lab">Records</span><span class="ro">${nf(s.count)}</span>`
        + `<span class="lab">Rate</span><span class="ro">${s.rate_hz ? s.rate_hz + ' Hz' : 'static'}</span>`
        + (s.kind ? `<span class="lab">Value</span><span class="ro">${esc(s.kind)}${s.unit ? ' · ' + esc(s.unit) : ''}</span>` : '')
        + (pr ? `<span class="lab">First – last</span><span class="ro">${pr[0].toFixed(2)} – ${pr[1].toFixed(2)} s</span>` : '')
        + (s.missing ? `<span class="lab">Why missing</span><span class="ro" style="color:var(--warn);font-family:var(--ui)">${esc(s.why || 'missing')}</span>` : ''));
    }
    const m = hasTicks() ? moment() : null;
    if (/^(belief|truth)\./.test(n.id) || n.id === 'g.belief' || n.id === 'g.truth' || n.id === 'g.robot') {
      const noTruth = stream('truth.pose')?.missing;
      h += sec('rel', 'Relations', `<span class="lab">Belief ↔ truth</span><label class="cb"><input type="checkbox" id="relcb" ${M.rel.belief_truth ? 'checked' : ''} ${noTruth || M.frame === 'map' ? 'disabled' : ''}>`
        + `<span class="ro">${noTruth ? 'no truth in this run' : M.frame === 'map' ? 'world frame only' : m?.dist != null ? m.dist.toFixed(3) + ' m now' : ''}</span></label>`);
    }
    if (n.id.startsWith('sensors.depth')) h += sec('rel', 'Relations', '<span class="lab">Depth ↔ pose</span><label class="cb"><input type="checkbox" disabled><span class="dim">unavailable: the run has no frame times</span></label>');
    el.innerHTML = h;
    bindSecs(el);
    el.querySelectorAll('[data-mode]').forEach((b) => (b.onclick = () => { setTimeMode(b.dataset.for, b.dataset.mode, undefined); }));
    el.querySelectorAll('[data-vv]').forEach((b) => (b.onclick = () => setViewVisible(b.dataset.vv, n.id, M.vv[b.dataset.vv]?.[n.id] === false)));
    const vc = $('vis'); if (vc) vc.onchange = () => setVisible(n.id, vc.checked);
    const rc = $('relcb'); if (rc) rc.onchange = () => setRelation('belief_truth', rc.checked);
    const wf = $('winf');
    if (wf && wf.getAttribute('aria-disabled') === 'false') {
      const targets = () => leafIds.filter((l) => !stream(l).missing && cfg(l).mode === 'window');
      dragField(wf, { get: () => cfg(targets()[0] || n.id).n, set: (v) => { for (const l of targets()) M.modes[l] = { ...M.modes[l], n: v }; syncTime(); if (hasTicks()) adapter.draw(); }, lo: 0.1, hi: 600, k: 0.05, fmt: (v) => v.toFixed(1) });
    }
    for (const [fid, ids, lo, hi] of [['pszf', ptIds, 1, 24], ['lszf', lnIds, 0.5, 12]]) {
      const f = $(fid);
      if (f) dragField(f, { get: () => size(ids[0]), set: (v) => { for (const l of ids) M.size[l] = v; if (hasTicks()) adapter.draw(); }, lo, hi, k: 0.05, fmt: (v) => v.toFixed(1) });
    }
    renderBand();
  }
  function bindSecs(el) {
    el.querySelectorAll('.shead').forEach((b) => (b.onclick = () => { const s = b.parentElement, k = s.dataset.sec; M.secOpen[k] = s.dataset.open !== 'true'; s.dataset.open = M.secOpen[k]; }));
  }

  // a field you drag sideways to change, or click to type in (Shift fine, Ctrl coarse)
  function dragField(el, { get, set, lo, hi, k, fmt }) {
    const input = el.querySelector('input');
    let x0 = null, v0 = 0, dragged = false;
    const apply = (v) => { v = clamp(v, lo, hi); input.value = fmt(v); set(v); };
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || el.getAttribute('aria-disabled') === 'true') return;
      if (document.activeElement === input) return;
      e.preventDefault(); x0 = e.clientX; v0 = get(); dragged = false; el.setPointerCapture(e.pointerId);
      propsBusy = true;
    });
    el.addEventListener('pointermove', (e) => {
      if (x0 === null) return;
      if (Math.abs(e.clientX - x0) > 3) dragged = true;
      if (dragged) apply(v0 + (e.clientX - x0) * (typeof k === 'function' ? k() : k) * (e.shiftKey ? 0.1 : e.ctrlKey ? 10 : 1));
    });
    el.addEventListener('pointerup', () => {
      if (x0 === null) return;
      x0 = null; propsBusy = false;
      if (!dragged) { input.focus(); input.select(); } else propsIdle();
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { const v = parseFloat(input.value); if (Number.isFinite(v)) apply(v); input.blur(); }
      else if (e.key === 'Escape') { input.value = fmt(get()); input.blur(); }
      e.stopPropagation();
    });
    input.addEventListener('blur', () => { input.value = fmt(get()); setTimeout(propsIdle, 0); });
  }

  // ---- rendering: the inspector (right) -----------------------------------------------------------------
  const kv = (k, v, u = '', cls = '') => `<div class="kv ${cls}"><span class="k">${k}</span><span class="v">${v}</span><span class="u">${u}</span><button class="cp" title="Copy" data-copy="${esc(`${k}: ${v} ${u}`.replace(/<[^>]+>/g, ''))}">${svgI('copy', 11)}</button></div>`;
  const isec = (key, title, dot, body, act = '') => `<div class="sec" data-open="${M.secOpen['i' + key] !== false}" data-sec="i${key}"><button class="shead"><span class="caret">${svgI('chev', 12)}</span>${dot ? `<span class="dot" style="background:${dot}"></span>` : ''}${title}<span class="act">${act}</span></button><div class="ibody">${body}</div></div>`;
  let momentJson = null;
  // the inspector's last event, and the events before and after the playhead to jump to
  function eventSections(ev) {
    const prev = [...M.run.events].reverse().find((e) => M.kinds[e.kind] !== false && e.t < M.t - 1e-6), next = M.run.events.find((e) => M.kinds[e.kind] !== false && e.t > M.t + 1e-6);
    return isec('v', 'Last event', '', (ev ? `<div class="evrow"><span class="sw" style="background:${kindColor(ev.kind)}"></span><span class="mono">${fx(ev.t, 2)} s</span><b style="font-weight:500">${esc(ev.kind)}</b><span class="txt">${esc((ev.text.startsWith(ev.kind) ? ev.text.slice(ev.kind.length) : ev.text).trimStart())}${Math.max(0, M.t - ev.t) > 0 ? ` · ${Math.max(0, M.t - ev.t).toFixed(2)} s ago` : ''}</span></div>` : '<div class="evrow"><span></span><span class="faint">none yet</span></div>')
      + (ev?.decision ? decisionRows(ev.decision) : ''))
      + `<div class="evnav"><button data-seek="${prev ? prev.t : ''}" ${prev ? '' : 'disabled'}>${svgI('left', 12)} ${prev ? esc(prev.kind) + ' ' + prev.t.toFixed(2) : 'no earlier event'}</button><button data-seek="${next ? next.t : ''}" ${next ? '' : 'disabled'}>${next ? next.t.toFixed(2) + ' ' + esc(next.kind) : 'no later event'} ${svgI('right', 12)}</button></div>`;
  }
  // the rule that fired and the values it compared (ADR-0014): the reason, then each value
  const decisionRows = (d) => `<div class="decision" data-rule="${esc(d.rule)}"><div class="why"><span class="faint">${esc(d.rule)}</span> ${esc(d.reason)}</div>`
    + Object.entries(d.values).map(([k, v]) => kv(esc(k), v == null ? 'none' : typeof v === 'number' ? fx(v, Number.isInteger(v) ? 0 : 3) : esc(String(v)), '', v == null ? 'na' : '')).join('') + '</div>';
  // the values of the robot's signals at the playhead (ADR-0013), one row each, in the order the run declares them
  function signalsSection(sg) {
    const rows = (M.run.signals || []).map((d) => {
      const v = sg?.values[d.name];
      return v == null ? kv(esc(d.name), 'none', '', 'na') : kv(esc(d.name), typeof v === 'number' ? fx(v, Number.isInteger(v) ? 0 : 2) : esc(v), esc(d.unit || ''));
    }).join('');
    return isec('g', 'Signals', '', rows || kv('Signals', 'none yet', '', 'na'), sg ? `<span class="fchip">sample ${sg.i + 1} of ${sg.n} · ${fx(sg.t, 2)} s</span>` : '');
  }

  function renderInsp() {
    const el = $('inspBody');
    $('tabMoment').setAttribute('aria-selected', M.tab === 'moment'); $('tabSel').setAttribute('aria-selected', M.tab === 'sel');
    if (!M.run || (!hasTicks() && !hasSignals())) { el.innerHTML = `<div class="empty">${M.run ? 'The run has no ticks yet.' : 'No run open.'}</div>`; return; }
    if (M.tab === 'moment' && !hasTicks()) {
      const sg = sigMoment(), ev = lastEvent();
      momentJson = { t: M.t, sample: sg ? sg.i : null, signals: sg ? sg.values : null, last_event: ev };
      el.innerHTML = isec('m', 'Moment', '', kv('Time', fx(M.t, 2), 's') + kv('Sample', sg ? `${sg.i + 1} of ${sg.n}` : 'none yet', '', sg ? '' : 'na'), '<span class="mono" data-json="1" style="cursor:pointer">copy JSON</span>')
        + signalsSection(sg) + eventSections(ev);
    } else if (M.tab === 'moment') {
      const m = moment(), map = M.frame === 'map', ev = m.ev, sg = hasSignals() ? sigMoment() : null;
      const pose = (p) => kv('x', fx(p[0]), 'm') + kv('y', fx(p[1]), 'm') + kv('Yaw', fx(deg(p[2]), 1), '°');
      momentJson = { t: m.t, tick: m.tick, frame: M.frame, belief: (map ? m.bm : m.bw).map(f3), truth: m.tr && !map ? m.tr.map(f3) : null, distance: f3(m.dist), heading_error_deg: f3(m.herr), cmd: m.cmd, last_event: ev, ...(sg && { signals: sg.values }) };
      el.innerHTML =
        isec('m', 'Moment', '', kv('Time', fx(M.t, 2), 's') + kv('Tick', `${m.tick + 1} of ${m.n}`) + kv('Map epoch from', fx(m.epoch, 2), 's'), '<span class="mono" data-json="1" style="cursor:pointer">copy JSON</span>')
        + (hasSignals() ? signalsSection(sg) : '')
        + isec('b', 'Belief', 'var(--c-belief)', pose(map ? m.bm : m.bw), `<span class="fchip">${map ? 'map' : 'world'}</span>`)
        + isec('t', 'Truth', 'var(--c-truth)', map ? kv('Truth', 'hidden in the map frame', '', 'na') : m.tr ? pose(m.tr) : kv('Truth', 'none in this run', '', 'na'), '<span class="fchip">world</span>')
        + isec('e', 'Error', '', (map ? kv('Belief to truth', 'world frame only', '', 'na derived') : m.dist != null ? kv('Belief to truth', fx(m.dist), 'm', 'derived') + kv('Heading error', fx(m.herr, 1), '°', 'derived') : kv('Belief to truth', 'no truth', '', 'na derived')) + kv('Nearest obstacle', 'not in the data yet', '', 'na'))
        + isec('c', 'Command', '', kv('Forward', fx(m.cmd?.[0]), 'm/s') + kv('Turn', fx(m.cmd?.[1]), 'rad/s'))
        + isec('d', 'Depth frame', '', m.depthTick < 0 ? kv('Depth', 'no frame yet', '', 'na') : kv('Frame tick', `${m.depthTick + 1} of ${m.n}`) + kv('Floor returns', String(m.cnt.f)) + kv('Obstacle returns', String(m.cnt.o)) + kv('Overhead returns', String(m.cnt.v)) + kv('Below the floor', String(m.cnt.b)))
        + isec('r', 'Raw depth frame', '', rawSection())
        + isec('w', 'Plan and map', '', (m.plan ? kv('Plan', `${m.plan.k} of ${m.plan.n}`) + kv('Plan made at', fx(m.plan.t, 2), 's') : kv('Plan', 'none yet', '', 'na')) + (m.world ? kv('Map', `${m.world.k} of ${m.world.n}`) + kv('Map made at', fx(m.world.t, 2), 's') : kv('Map', 'none yet', '', 'na')))
        + eventSections(ev);
    } else {
      const d = M.sel ? adapter.describe(M.sel) : null;
      if (!d) el.innerHTML = `<div class="empty">${svgI('crosshair', 20)}<br>Nothing picked.<br>${signalsOnly() ? 'This run has no pose to pick: click a chart to move the playhead.' : 'Click a point in the view: a depth return, a robot or a map cell.'}</div>`;
      else {
        const sty = styleOf(d.stream), id = d.stream;
        el.innerHTML = isec('s', esc(cap(d.detail || d.kind)), sty.c, kv('x', fx(d.p[0]), 'm') + kv('y', fx(d.p[1]), 'm') + kv('Height z', fx(d.height), 'm')
          + (d.yaw != null ? kv('Yaw', fx(deg(d.yaw), 1), '°') : '') + (d.res ? kv('Cell size', fx(d.res, 4), 'm') : '') + kv('Frame tick', `${d.tick + 1} of ${M.run.ticks}`) + kv('Time', fx(d.t, 2), 's'), `<span class="fchip">${esc(d.frame)}</span>`)
          + `<div class="evnav" style="padding-top:8px"><button id="toRow" data-stream="${esc(id)}" title="${esc(id)}">${svgI('chev', 12)} Select the stream</button></div>`;
      }
    }
    bindSecs(el);
    const rcv = $('rawcv'), rf = rcv && raw.fr;
    if (rcv && rf) paintRaw(rcv, rf);
    el.querySelectorAll('.cp').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); try { navigator.clipboard.writeText(b.dataset.copy.trim()).catch(() => {}); } catch (_) { /* no clipboard here */ } b.style.color = 'var(--ok)'; setTimeout(() => (b.style.color = ''), 600); }));
    el.querySelectorAll('[data-seek]').forEach((b) => (b.onclick = () => b.dataset.seek !== '' && setTime(+b.dataset.seek)));
    const jb = el.querySelector('[data-json]');
    if (jb) jb.onclick = (e) => { e.stopPropagation(); try { navigator.clipboard.writeText(JSON.stringify(momentJson, null, 1)).catch(() => {}); } catch (_) { /* no clipboard here */ } jb.textContent = 'copied'; setTimeout(() => (jb.textContent = 'copy JSON'), 800); };
    const tr = $('toRow');
    if (tr) tr.onclick = () => { selectNode(tr.dataset.stream); };
  }
  function selectNode(id) {
    if (!T.nodes[id]) return;
    M.selNode = id;
    for (const p of T.parents[id]) M.open[p] = true;
    renderTree(); renderProps(); renderLanesSel();
  }

  // ---- rendering: top bar, viewport chrome, legend, status ----------------------------------------------
  function renderChrome() {
    // the chrome follows the run that is open: on the scenes page (M.runId null) M.run is only the last one opened
    const r = M.runId ? M.run : null, sc = r && M.index?.scenes.find((s) => s.id === M.sceneId), live = r?.status === 'live';
    $('sceneName').textContent = sc ? sc.id : '—';
    $('runName').textContent = r ? r.id : 'choose a run';
    $('runVerdict').textContent = r ? (live ? 'live' : r.verdict) : '';
    $('runVerdict').className = r ? (live ? 'verdict live' : verdictClass(r.verdict)) : '';
    $('layoutSeg').querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.view === M.view));
    $('frameSeg').querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.frame === M.frame));
    $('runinfo').innerHTML = r ? `<b>${esc(r.robot.name)}</b> · ${esc(r.kind)} · ${live ? '<span class="live-dot"></span> <span class="verdict live">live</span>' : `<span class="${verdictClass(r.verdict)}">${esc(r.verdict)}</span>`} · <span class="mono">${(r.t1 - r.t0).toFixed(1)} s</span> · ${r.ticks || !r.samples ? `<span class="mono">${r.ticks}</span> ticks` : ''}${r.ticks && r.samples ? ' · ' : ''}${r.samples ? `<span class="mono">${r.samples}</span> samples` : ''}` : 'no run open';
    app.classList.toggle('signals-only', signalsOnly());
    $('vt').innerHTML = signalsOnly() ? '<b>Signals</b> · time series, click or drag to seek' : `<b>${frameName()}</b> · ${VIEW_NOTE[M.view] || M.view}`;
    $('st-run').textContent = r ? `${M.sceneId} / ${r.id}` : 'no run open';
    $('st-live').textContent = live ? (M.follow ? 'live · following' : 'live') : r ? `${r.status} · ${r.verdict}` : '';
    $('st-live').className = live ? 'live' : '';
    $('gizmo').style.display = M.ov.gizmo && M.view !== 'three' ? '' : 'none';
    $('legend').style.display = M.ov.legend ? '' : 'none';
    $('themeBtn').innerHTML = svgI(M.theme === 'dark' ? 'sun' : 'moon', 14);
    $('themeBtn').title = M.theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme';
    renderLegend(); updateGizmo(); updateScale(); renderExport();
  }
  function legendHtml() {
    if (!M.run) return '';
    const w = M.frame === 'world', sh = (id) => shown(id);
    const L = [['Belief', 'c-belief', sh('belief.pose') || sh('belief.track')], ['Truth', 'c-truth', w && (sh('truth.pose') || sh('truth.track'))], ['Plan', 'c-plan', sh('plan.path'), 1],
      ['Floor', 'c-floor', sh('sensors.depth.floor')], ['Obstacle', 'c-ob', sh('sensors.depth.obstacle')], ['Overhead', 'c-over', sh('sensors.depth.overhead')], ['Below floor', 'c-drop', sh('sensors.depth.below')],
      ['Memory', 'c-obst', sh('world.obstacles')], ['Drop', 'c-drop', sh('world.drops')], ['Occupied', 'c-occ', sh('world.grid')], ['Hazard', 'c-drop', w && sh('scene.hazards')]];
    return L.filter((x) => x[2]).map(([n, c, , ln]) => `<span><i class="${ln ? 'ln' : ''}" style="background:var(--${c})"></i>${n}</span>`).join('');
  }
  const renderLegend = () => { $('legend').innerHTML = legendHtml(); };
  // where the legend is hidden (narrow windows) the overlays popover carries the colour keys
  const legendHidden = () => matchMedia('(max-width: 960px)').matches;
  // a scale bar the length of 1 m on the screen (a nicer length when zooming makes 1 m too long or too short)
  const SCALE_M = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20];
  function updateScale() {
    const el = $('scale'), ppm = M.run && hasTicks() ? adapter.scale?.() : null;
    el.hidden = !(ppm > 0);
    if (el.hidden) return;
    const L = ppm >= 30 && ppm <= 220 ? 1 : [...SCALE_M].reverse().find((m) => m * ppm <= 160) || SCALE_M[0];
    el.dataset.m = L; el.dataset.px = (L * ppm).toFixed(2);
    el.innerHTML = `<i style="width:${(L * ppm).toFixed(1)}px"></i><span>${L} m</span>`;
  }
  const fit = () => { adapter.fit(); updateScale(); };
  function updateGizmo() {
    const g = $('gizmo');
    if (!M.run || !hasTicks() || M.view === 'three') return;
    const a = M.view === '3d' ? adapter.gizmo?.() : AXES[M.view];
    if (!a) { g.innerHTML = ''; return; }
    const R = 20, C = 28, items = ['x', 'y', 'z'].map((k) => ({ k, v: a[k] })).sort((p, q) => p.v[2] - q.v[2]);
    g.innerHTML = '<circle cx="28" cy="28" r="26" fill="var(--hair-2)" stroke="var(--hair)"/>' + items.map(({ k, v }) => {
      const x = C + v[0] * R, y = C - v[1] * R, flat = Math.hypot(v[0], v[1]) < 0.2, col = `var(--c-${k})`;
      return (flat ? '' : `<line x1="${C}" y1="${C}" x2="${x}" y2="${y}" stroke="${col}" stroke-width="2"/>`)
        + `<circle cx="${flat ? C : x}" cy="${flat ? C : y}" r="${flat ? 4 : 6}" fill="${col}"/>` + (flat ? '' : `<text x="${x}" y="${y + 3.2}" text-anchor="middle" font-size="8" font-family="var(--mono)" fill="var(--bg-app)" font-weight="700">${k.toUpperCase()}</text>`);
    }).join('');
  }

  // ---- rendering: the timeline --------------------------------------------------------------------------
  const span = () => {
    const r = M.run, pad = Math.max(0.05, 0.012 * (r.t1 - r.t0));
    return [r.t0 - pad, r.t1 + pad];
  };
  const pct = (t) => { const [a, b] = span(); return ((t - a) / (b - a)) * 100; };
  const tFromX = (x) => { const r = $('overlay').getBoundingClientRect(), [a, b] = span(); return clamp(a + clamp((x - r.left) / r.width, 0, 1) * (b - a), M.run.t0, M.run.t1); };
  const NICE = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600];
  const MINOR = { 0.1: 0.02, 0.2: 0.05, 0.5: 0.1, 1: 0.2, 2: 0.5, 5: 1, 10: 2, 20: 5, 30: 5, 60: 10, 120: 20, 300: 60, 600: 120 };

  function renderRuler() {
    if (!M.run) return;
    const [a, b] = span(), w = $('overlay').clientWidth || 800, pps = w / (b - a), step = NICE.find((s) => s * pps >= 70) || 600, minor = MINOR[step];
    let h = '';
    const each = (st, k) => { for (let t = Math.ceil(a / st - 1e-9) * st; t <= b + 1e-9; t += st) k(+t.toFixed(4)); };
    each(minor, (t) => { if (Math.abs(t / step - Math.round(t / step)) > 1e-6) h += `<span class="t min" style="left:${pct(t)}%"></span>`; });
    each(step, (t) => { h += `<span class="t maj" style="left:${pct(t)}%"></span><span class="lb" style="left:${pct(t)}%">${+t.toFixed(2)}</span>`; });
    const ds = dataSpan();
    if (ds) h += `<span class="data" style="left:${pct(ds[0])}%;width:${pct(ds[1]) - pct(ds[0])}%" title="Recorded ${hasTicks() ? 'ticks' : 'samples'} ${ds[0].toFixed(2)} – ${ds[1].toFixed(2)} s"></span>`;
    $('ruler').innerHTML = h;
    if (ds) $('rbar').style.cssText = `left:${pct(ds[0])}%;width:${pct(ds[1]) - pct(ds[0])}%`;
  }
  function renderMarkers() {
    if (!M.run) return;
    $('mlane').innerHTML = M.run.events.map((e, i) => (M.kinds[e.kind] === false ? '' : `<span class="mk ${isStop(e.kind) ? 'stop' : ''}" style="left:${pct(e.t)}%;color:${kindColor(e.kind)}" data-ev="${i}"><i style="background:${isStop(e.kind) ? 'none' : kindColor(e.kind)}"></i></span>`)).join('');
    const n = M.run.events.filter((e) => M.kinds[e.kind] !== false).length;
    $('kindsN').textContent = n;
  }
  function renderLanes() {
    const wrap = $('lanes'); wrap.hidden = !M.rows;
    $('lanesBtn').setAttribute('aria-pressed', M.rows);
    if (!M.run || !M.rows) { $('lanesL').innerHTML = ''; $('dlanes').innerHTML = ''; return; }
    // one row per stream the API reports presence for (the events have their own lane), in outliner order
    // a run with no pose has nothing to show for the streams it lacks: only the rows it has
    const ids = T.order.filter((id) => T.nodes[id].leaf && id !== 'events' && (M.pres?.streams?.[id] || stream(id)?.missing)
      && (hasTicks() || !hasSignals() || !stream(id)?.missing));
    const quant = (t) => Math.round(pct(t) * 20) / 20;
    $('lanesL').innerHTML = ids.map((id) => { const s = stream(id), m = s.missing || !(M.pres?.streams?.[id]); return `<div class="lane-l ${m ? 'missing' : ''} ${shown(id) ? '' : 'hid'} ${M.selNode === id ? 'sel' : ''}" data-lane="${esc(id)}" title="${esc(id)}${m ? ' — ' + esc(s.why || 'missing') : ''}"><i style="background:${styleOf(id).c}"></i>${esc(LANE_NAME[id] || cap(s.name))}</div>`; }).join('');
    const gaps = depthGaps().map(([a, b]) => `<span class="gap" style="left:${pct(a)}%;width:${pct(b) - pct(a)}%" title="No depth frames ${a.toFixed(2)} – ${b.toFixed(2)} s"></span>`).join('');
    $('dlanes').innerHTML = gaps + ids.map((id) => {
      const s = stream(id), p = M.pres?.streams?.[id], miss = s.missing || !p;
      const sp = (p?.spans || []).map(([x, y]) => `<span class="sp" style="left:${pct(x)}%;width:calc(${pct(y) - pct(x)}% + 2px)"></span>`).join('');
      const seen = new Set(), pt = (p?.times || []).filter((t) => { const q = quant(t); if (seen.has(q)) return false; seen.add(q); return true; }).map((t) => `<span class="pt" style="left:${pct(t)}%"></span>`).join('');
      return `<div class="dl ${miss ? 'missing' : ''} ${shown(id) ? '' : 'hid'}" style="color:${styleOf(id).c}">${sp}${pt}</div>`;
    }).join('');
  }
  // where the run has ticks but no depth frames: between the depth spans (the presence of floor, obstacle and
  // overhead returns, merged), inside the span of the ticks
  function depthGaps() {
    if (!hasTicks()) return [];
    const sp = ['floor', 'obstacle', 'overhead'].flatMap((k) => M.pres?.streams?.['sensors.depth.' + k]?.spans || []).sort((a, b) => a[0] - b[0]), merged = [];
    for (const [a, b] of sp) { const l = merged[merged.length - 1]; if (l && a <= l[1]) l[1] = Math.max(l[1], b); else merged.push([a, b]); }
    const [t0, t1] = tickSpan();
    return merged.slice(1).map((m, i) => [merged[i][1], m[0]]).filter(([a, b]) => a >= t0 && b <= t1 && b > a);
  }
  function renderLanesSel() { document.querySelectorAll('#lanesL .lane-l').forEach((l) => l.classList.toggle('sel', l.dataset.lane === M.selNode)); renderBand(); renderSignals(); }
  function renderBand() {
    document.querySelectorAll('.wband').forEach((b) => b.remove());
    const id = M.selNode, s = stream(id);
    if (!M.run || !hasTicks() || !s || s.missing || cfg(id).mode !== 'window' || !s.time_modes?.includes('window')) return;
    const w = cfg(id).n, b = document.createElement('div');
    b.className = 'wband'; b.style.left = pct(M.t - w) + '%'; b.style.width = (pct(M.t) - pct(M.t - w)) + '%'; b.title = `${cap(s.name)}: the last ${w.toFixed(1)} s`;
    $('overlay').appendChild(b);
  }
  function renderTransport() {
    $('playBtn').innerHTML = svgI(M.play.on ? 'pause' : 'play', 12);
    $('playBtn').title = M.play.on ? 'Pause (Space)' : 'Play (Space)';
    $('speedBtn').firstChild.textContent = M.play.speed + '×';
    $('loopBtn').setAttribute('aria-pressed', M.play.loop);
  }
  function renderTimeline() { renderRuler(); renderMarkers(); renderLanes(); renderBand(); syncTime(); renderTransport(); }

  function syncTime() {
    if (!M.run) return;
    const ph = $('ph'), at = pct(M.t); ph.style.left = at + '%'; ph.firstChild.textContent = M.t.toFixed(2) + ' s';
    // the time label is centred on the playhead but kept inside the strip, by its measured width
    const head = ph.firstChild, hw = head.offsetWidth, sw = $('overlay').clientWidth, x = (at / 100) * sw;
    head.style.transform = 'none';
    head.style.left = clamp(x - hw / 2, 0, Math.max(0, sw - hw)) - x + 'px';
    const ti = $('tin'), ki = $('kin');
    if (document.activeElement !== ti) ti.value = M.t.toFixed(2);
    const bySample = !hasTicks() && hasSignals();
    $('tfK').firstElementChild.textContent = bySample ? 'sample' : 'tick';
    if (document.activeElement !== ki) ki.value = hasTicks() ? M.i + 1 : bySample ? Math.max(0, sampleIdx(M.t) + 1) : 0;
    $('kn').textContent = 'of ' + (hasTicks() ? M.run.ticks : bySample ? sampleN() : 0);
    renderBand();
    if (M.tab === 'moment' || M.sel) scheduleInsp();
  }
  // the inspector follows the time at most once a frame; a script call flushes it before it says it is ready
  let inspDirty = false, inspRaf = false;
  function flushInsp() { if (inspDirty) { inspDirty = false; renderInsp(); } }
  function scheduleInsp() {
    inspDirty = true;
    if (!inspRaf) { inspRaf = true; requestAnimationFrame(() => { inspRaf = false; flushInsp(); }); }
  }

  // ---- the whole thing ------------------------------------------------------------------------------
  function refresh() {
    renderTree(); renderProps(); renderInsp(); renderChrome(); renderLanes(); renderSignals();
    if (hasTicks()) adapter.draw();
  }
  function renderAll() {
    renderTree(); renderProps(); renderInsp(); renderChrome(); renderTimeline(); renderSignals(); writeHash();
    if (hasTicks()) adapter.draw();
  }
  // the Signals view takes the viewport of a run that has signals and no pose (ADR-0013); a run with a pose keeps its views
  function renderSignals() {
    const on = signalsOnly();
    $('sigview').hidden = !on;
    if (!on) return;
    const ids = T.order.filter((id) => id.startsWith('signals.') && T.nodes[id].leaf && shown(id));
    sigView.render({ run: M.run, sig: store.sig, ids, selected: M.selNode, t: M.t });
  }
  function writeHash() {
    history.replaceState(null, '', M.runId ? '#' + new URLSearchParams({ scene: M.sceneId, run: M.runId, view: M.view, frame: M.frame }) : '#scenes');
  }

  // ---- theme (D1): dark by default, follows the system, a switch overrides and is remembered -------------
  const mq = matchMedia('(prefers-color-scheme: light)');
  const stored = () => { try { return localStorage.getItem('miniview.theme'); } catch (_) { return null; } };
  function applyTheme(name, remember) {
    M.theme = name === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = M.theme;
    if (remember) { try { localStorage.setItem('miniview.theme', M.theme); } catch (_) { /* private mode */ } }
    adapter.theme(palette());
    renderChrome();
    if (hasTicks()) adapter.draw();
    if (M.run) { renderTree(); renderProps(); renderLanes(); renderSignals(); }      // the signals' colours follow the theme
  }
  mq.addEventListener?.('change', () => { if (!stored()) applyTheme(mq.matches ? 'light' : 'dark'); });

  // ---- the script API (CONTRACT.md): every call clears __ready, does its work, sets it once drawn --------
  const begin = () => { busy++; window.__ready = false; };
  const end = () => { busy--; if (busy <= 0) { busy = 0; window.__ready = true; } };
  const call = (fn) => async (...a) => {
    begin();
    try {
      const out = await fn(...a);
      if (M.run && hasTicks()) await adapter.settled();
      else await new Promise((r) => requestAnimationFrame(() => r()));
      flushInsp();
      return out;
    } finally { end(); }
  };
  const api = {
    load: (scene, run) => openRun(scene, run),
    scenes: () => scenesPage(),
    setTime: async (t, sync = false) => { if (M.run) await store.ensure(+t); return setTime(t, sync); },
    setView, setFrame, setVisible, setTimeMode, setRelation, setViewVisible,
    select: (sel) => select(sel),
  };
  window.miniview = Object.fromEntries(Object.entries(api).map(([k, f]) => [k, call(f)]));
  window.miniview.state = state;
  // the settings a script can have changed, as plain data: per-stream time modes, visibility (global and per view), drawn
  // sizes, event kinds, the playback state, overlays, the relation flag
  window.miniview.config = () => JSON.parse(JSON.stringify({ modes: M.modes, on: M.on, vv: M.vv, size: M.size, kinds: M.kinds, play: M.play, rel: M.rel, overlays: M.ov,
    view: M.view, frame: M.frame, theme: M.theme, follow: M.follow, scene: M.sceneId, run: M.runId }));
  // resolves when every tick of the open run is loaded (the page draws from the first window on; this waits for the rest)
  window.miniview.whenLoaded = async () => { await store.whenComplete(); return { ticks: store.ticks }; };
  window.miniview.scenes = () => { scenesPage(); };
  window.miniview.setData = (d) => window.miniview.setFrame(d ? 'map' : 'world');
  // FOR THE TESTS OF THIS REPOSITORY ONLY: the model and the renderer's probes. Scripts use the functions above (load, state, config, ...).
  window.miniview.internals = { M, adapter, store, raw, shell: () => shell };

  // ---- wiring ---------------------------------------------------------------------------------------
  const shell = {
    M, shown, cfg, size, tickAt, palette,
    pick: (sel) => select(sel),
    viewChanged: () => { updateGizmo(); updateScale(); },
  };

  $('scenes-link').onclick = () => window.miniview.scenes();
  $('scenespage').onclick = (e) => { const tr = e.target.closest('tr[data-run]'); if (tr) window.miniview.load(tr.dataset.scene, tr.dataset.run); };
  $('layoutSeg').onclick = (e) => { const b = e.target.closest('button'); if (b) window.miniview.setView(b.dataset.view); };
  $('frameSeg').onclick = (e) => { const b = e.target.closest('button'); if (b) window.miniview.setFrame(b.dataset.frame); };
  $('themeBtn').onclick = () => applyTheme(M.theme === 'dark' ? 'light' : 'dark', true);
  $('follow-on').onchange = () => { M.follow = $('follow-on').checked; renderChrome(); if (M.follow && M.run?.status === 'live') setTime(M.run.t1, false, true); };
  $('sceneBtn').onclick = (e) => ensureIndex().then(() => popover(e.currentTarget, '<h6>Scenes</h6>' + M.index.scenes.map((s) => `<button class="item ${s.id === M.sceneId ? 'cur' : ''}" data-scene="${esc(s.id)}"><span>${esc(s.id)}</span><span class="mono dim">${s.runs.length} runs</span><small>${esc(s.name)}</small></button>`).join(''),
    (p) => p.querySelectorAll('[data-scene]').forEach((b) => (b.onclick = () => { closePop(); window.miniview.load(b.dataset.scene); }))));
  $('runBtn').onclick = (e) => ensureIndex().then(() => {
    const sc = M.index.scenes.find((s) => s.id === M.sceneId) || M.index.scenes[0];
    if (!sc) return;
    popover(e.currentTarget, `<h6>Runs in ${esc(sc.id)}</h6>` + sc.runs.map((r) => `<button class="item ${r.key === M.runId ? 'cur' : ''}" data-run="${esc(r.key)}"><span>${esc(r.id)}</span><span class="mono dim">${r.length_s} s</span>`
      + `<small>${esc(r.kind)} · ${r.status === 'live' ? '<span class="verdict live">live</span>' : `<span class="${verdictClass(r.verdict)}">${esc(r.verdict)}</span>`} · ${r.events} events</small></button>`).join(''),
    (p) => p.querySelectorAll('[data-run]').forEach((b) => (b.onclick = () => { closePop(); window.miniview.load(sc.id, b.dataset.run); })));
  });
  $('ovBtn').onclick = (e) => popover(e.currentTarget, `<h6>Overlays</h6>
    <label class="cb"><input type="checkbox" data-ov="coords" ${M.ov.coords ? 'checked' : ''}>Coordinate system and grid</label>
    <label class="cb"><input type="checkbox" data-ov="rel" ${M.rel.belief_truth ? 'checked' : ''}>Belief ↔ truth line</label>
    <label class="cb"><input type="checkbox" data-ov="gizmo" ${M.ov.gizmo ? 'checked' : ''}>Axis gizmo</label>
    <label class="cb"><input type="checkbox" data-ov="legend" ${M.ov.legend ? 'checked' : ''}>Legend</label>${legendHidden() && M.run ? `<h6>Legend</h6><div class="lg" id="lgpop">${legendHtml()}</div>` : ''}`,
  (p) => p.querySelectorAll('[data-ov]').forEach((c) => (c.onchange = () => {
    if (c.dataset.ov === 'rel') setRelation('belief_truth', c.checked); else { M.ov[c.dataset.ov] = c.checked; renderChrome(); if (hasTicks()) adapter.draw(); }
  })));
  $('exportBtn').onclick = (e) => openExport(e.currentTarget);
  $('fitBtn').onclick = () => fit();
  $('helpBtn').onclick = () => help();
  $('filterBtn').onclick = (e) => popover(e.currentTarget, `<h6>Show in the list</h6><label class="cb"><input type="checkbox" id="fm" ${M.hideMissing ? '' : 'checked'}>Missing streams</label>`,
    (p) => (p.querySelector('#fm').onchange = (ev) => { M.hideMissing = !ev.target.checked; renderTree(); }));
  $('collapseBtn').onclick = () => { for (const k in M.open) M.open[k] = false; renderTree(); };
  $('q').oninput = (e) => { M.query = e.target.value.trim().toLowerCase(); renderTree(); };
  $('tree').onclick = (e) => {
    const eye = e.target.closest('[data-eye]');
    if (eye) { eyeClick(eye.dataset.eye); return; }
    const row = e.target.closest('.row'); if (!row) return;
    const id = row.dataset.id, n = T.nodes[id];
    if (e.target.closest('.caret') && n.kids) { M.open[id] = !M.open[id]; renderTree(); return; }
    M.selNode = id; renderTree(); renderProps(); renderLanesSel();
  };
  $('tree').ondblclick = (e) => { const row = e.target.closest('.row'); if (row && T.nodes[row.dataset.id].kids) { M.open[row.dataset.id] = !M.open[row.dataset.id]; renderTree(); } };
  $('tabMoment').onclick = () => { M.tab = 'moment'; renderInsp(); };
  $('tabSel').onclick = () => { M.tab = 'sel'; renderInsp(); };
  $('lanesL').onclick = (e) => { const l = e.target.closest('[data-lane]'); if (l) selectNode(l.dataset.lane); };
  $('lanesBtn').onclick = () => { M.rows = !M.rows; renderLanes(); };
  $('loopBtn').onclick = () => { M.play.loop = !M.play.loop; renderTransport(); };
  $('speedBtn').onclick = (e) => popover(e.currentTarget, '<h6>Playback speed</h6>' + SPEEDS.map((s) => `<button class="item ${s === M.play.speed ? 'cur' : ''}" data-speed="${s}"><span>${s}×</span></button>`).join(''),
    (p) => p.querySelectorAll('[data-speed]').forEach((b) => (b.onclick = () => { M.play.speed = +b.dataset.speed; closePop(); renderTransport(); })));
  $('kindsBtn').onclick = (e) => M.run && popover(e.currentTarget, '<h6>Event kinds</h6>' + Object.keys(M.kinds).map((k) =>
    `<label class="cb"><input type="checkbox" data-k="${esc(k)}" ${M.kinds[k] ? 'checked' : ''}><span style="width:8px;height:8px;background:${kindColor(k)};border-radius:1px;display:inline-block"></span>${esc(k)}<span class="mono faint" style="margin-left:auto">${M.run.events.filter((x) => x.kind === k).length}</span></label>`).join(''),
  (p) => p.querySelectorAll('[data-k]').forEach((c) => (c.onchange = () => { M.kinds[c.dataset.k] = c.checked; renderMarkers(); renderInsp(); })));
  $('tFirst').onclick = () => setTime(M.run?.t0 ?? 0);
  $('tPrev').onclick = () => stepTick(-1);
  $('playBtn').onclick = () => play(!M.play.on);
  $('tNext').onclick = () => stepTick(1);
  $('tLast').onclick = () => setTime(M.run?.t1 ?? 0);

  // seeking on the strip: click or drag on the ruler, the data rows, the range bar, or an event marker
  for (const id of ['ruler', 'dlanes', 'range', 'mlane']) {
    const el = $(id);
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !M.run) return;
      if (e.target.closest('.mk')) return;
      el.setPointerCapture(e.pointerId); setTime(tFromX(e.clientX));
    });
    el.addEventListener('pointermove', (e) => { if (M.run && el.hasPointerCapture(e.pointerId)) setTime(tFromX(e.clientX)); });
  }
  const tip = $('tip');
  $('mlane').addEventListener('click', (e) => { const m = e.target.closest('.mk'); if (m) setTime(M.run.events[m.dataset.ev].t); });
  $('mlane').addEventListener('mousemove', (e) => {
    const m = e.target.closest('.mk');
    if (!m) { tip.hidden = true; return; }
    const ev = M.run.events[m.dataset.ev];
    tip.innerHTML = `<b>${ev.t.toFixed(2)} s</b> · <span style="color:${kindColor(ev.kind)}">${esc(ev.kind)}</span><br><span class="dim">${esc(ev.text)}</span>${ev.decision ? `<br><span class="dim">${esc(ev.decision.reason)}</span>` : ''}${hasTicks() && ev.t > tickSpan()[1] ? `<br><span style="color:var(--warn)">after the last recorded tick (${tickSpan()[1].toFixed(2)} s)</span>` : ''}`;
    tip.hidden = false; tip.style.left = Math.min(e.clientX + 12, innerWidth - 330) + 'px'; tip.style.top = (e.clientY - 60) + 'px';
  });
  $('mlane').addEventListener('mouseleave', () => { tip.hidden = true; });
  dragField($('tfT'), { get: () => M.t, set: (v) => setTime(v), lo: -1e9, hi: 1e9, k: () => (M.run ? (M.run.t1 - M.run.t0) / 700 : 0.05), fmt: (v) => (+v).toFixed(2) });
  dragField($('tfK'), {
    get: () => (hasTicks() ? M.i + 1 : sampleIdx(M.t) + 1),
    set: (v) => { if (hasTicks()) gotoTick(Math.round(v) - 1); else if (signalsOnly() && sampleN()) setTime(store.sig.t[clamp(Math.round(v) - 1, 0, sampleN() - 1)]); },
    lo: 1, hi: 1e9, k: () => 0.3, fmt: (v) => String(Math.round(v)),
  });
  new ResizeObserver(() => { if (M.run) { renderRuler(); renderMarkers(); renderLanes(); syncTime(); } }).observe($('overlay'));

  // the splitter between the outliner and the properties
  $('split').addEventListener('pointerdown', (e) => { e.preventDefault(); $('split').setPointerCapture(e.pointerId); $('split').classList.add('drag'); });
  $('split').addEventListener('pointermove', (e) => {
    if (!$('split').hasPointerCapture(e.pointerId)) return;
    const r = $('left').getBoundingClientRect();
    $('left').style.setProperty('--split', clamp(e.clientY - r.top, 120, r.height - 125) + 'px');
  });
  $('split').addEventListener('pointerup', () => $('split').classList.remove('drag'));

  // the cursor's world coordinates, from whichever view the pointer is over
  stage.addEventListener('pointermove', (e) => {
    if (!hasTicks()) return;
    const c = adapter.cursor(e.clientX, e.clientY);
    $('readout').textContent = c ? `${c.axes[0]} ${fx(c.v[0])}  ${c.axes[1]} ${fx(c.v[1])} m  ${M.frame}${c.note ? ' · ' + c.note : ''}` : `x —  y — m  ${M.frame}`;
  });
  stage.addEventListener('pointerleave', () => { $('readout').textContent = 'x —  y — m'; });
  new ResizeObserver(() => { adapter.resize(); updateScale(); if (M.run) renderSignals(); }).observe(stage);

  function help() {
    if (document.querySelector('.help')) return;
    const d = document.createElement('div'); d.className = 'help';
    d.innerHTML = '<div><h3>Keyboard</h3>' + [['Space', 'Play / pause'], ['← →', 'Step a tick'], ['Shift ← →', 'Step 1 s'], [', .', 'Previous / next event'], ['Home End', 'Start / end'],
      ['Shift ↑ ↓', 'Speed'], ['H', 'Hide selected'], ['Alt H', 'Show all'], ['Shift H', 'Isolate selected'], ['/', 'Search streams'],
      ['1 2 3', 'Top / Three / 3D'], ['W', 'World / map'], ['F', 'Fit the run'], ['?', 'This list'], ['Esc', 'Close']]
      .map(([k, v]) => `<span class="kbd" style="font-size:11px;padding:1px 5px">${k}</span><span>${v}</span>`).join('') + '</div>';
    d.onclick = () => d.remove(); document.body.appendChild(d);
  }
  addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey) return;
    if (e.target.matches?.('input, textarea, select')) { if (e.key === 'Escape') e.target.blur(); return; }
    const k = e.key, lk = k.toLowerCase();
    if (k === '/') { e.preventDefault(); $('q').focus(); }
    else if (k === '?') help();
    else if (k === 'Escape') { closePop(); document.querySelector('.help')?.remove(); }
    else if (!M.run) return;
    else if (k === ' ') { e.preventDefault(); play(!M.play.on); }
    else if (k === 'ArrowLeft' || k === 'ArrowRight') { e.preventDefault(); const d = k === 'ArrowLeft' ? -1 : 1; if (e.shiftKey) setTime(M.t + d); else stepTick(d); }
    else if ((k === 'ArrowUp' || k === 'ArrowDown') && e.shiftKey) { e.preventDefault(); const i = SPEEDS.indexOf(M.play.speed); M.play.speed = SPEEDS[clamp(i + (k === 'ArrowUp' ? 1 : -1), 0, SPEEDS.length - 1)]; renderTransport(); }
    else if (k === 'Home') { e.preventDefault(); setTime(M.run.t0); }
    else if (k === 'End') { e.preventDefault(); setTime(M.run.t1); }
    else if (k === ',') stepEvent(-1);
    else if (k === '.') stepEvent(1);
    else if (lk === 'h' && e.altKey) { M.on = {}; refresh(); }
    else if (lk === 'h' && e.shiftKey) {
      const sel = M.selNode, keep = new Set(T.nodes[sel]?.kids ? T.leaves(sel) : [sel]);
      M.on = {}; for (const id of T.order) if (T.nodes[id].leaf) M.on[id] = keep.has(id);
      refresh();
    } else if (lk === 'h') { if (M.selNode) { M.on[M.selNode] = M.on[M.selNode] === false; refresh(); } }
    else if (k === '1') setView('top');
    else if (k === '2') setView('three');
    else if (k === '3') setView('3d');
    else if (lk === 'w') setFrame(M.frame === 'world' ? 'map' : 'world');
    else if (lk === 'f') fit();
  });

  // ---- boot ---------------------------------------------------------------------------------------------
  adapter.init(stage, shell);
  applyTheme(stored() || (mq.matches ? 'light' : 'dark'));
  const h = new URLSearchParams(location.hash.slice(1));
  M.view = VIEW_ALIAS[h.get('view')] || (VIEWS.includes(h.get('view')) ? h.get('view') : 'top');
  M.frame = h.get('frame') === 'map' || h.get('data') === '1' ? 'map' : 'world';
  renderChrome(); renderProps(); renderInsp(); renderTransport();
  window.__ready = false;
  begin();
  (async () => {
    try {
      await ensureIndex();
      if (h.get('run') || h.get('scene')) {
        try { await openRun(h.get('scene') || undefined, h.get('run') || undefined); } catch (e) { console.warn('the URL names no run:', String(e)); scenesPage(); }
      } else if (!M.run && !M.loading) scenesPage();
      renderChrome();
      await fontsReady();
    } catch (e) { console.error(e); document.body.append(String(e)); } finally { end(); }
  })();
  return shell;
}

// The pages link Inter and JetBrains Mono from the service (web/fonts, no CDN). A font file is fetched only when
// text first uses it, so a screenshot taken at once used to show the system fallbacks; ready waits for them,
// but never longer than 3 s (offline, the system fonts in the --ui and --mono stacks stay).
async function fontsReady() {
  await new Promise((r) => requestAnimationFrame(() => r()));
  await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 3000))]);
}

const TEMPLATE = `
<div class="app" id="app">
  <header class="top">
    <button class="mark" id="scenes-link" title="All scenes and runs"><i></i>miniview</button>
    <button class="pick-btn" id="sceneBtn" aria-haspopup="listbox"><span class="k">Scene</span><span id="sceneName">—</span><svg class="i" data-i="down"></svg></button>
    <button class="pick-btn" id="runBtn" aria-haspopup="listbox"><span class="k">Run</span><span id="runName">—</span><span id="runVerdict" class="verdict"></span><svg class="i" data-i="down"></svg></button>
    <span class="sep"></span>
    <div class="seg" role="group" aria-label="Layout" id="layoutSeg">
      <button data-view="top" aria-pressed="true" title="One top view (1)"><svg class="i" data-i="square"></svg>Top</button>
      <button data-view="three" aria-pressed="false" title="Top, front and side (2)"><svg class="i" data-i="cols"></svg>Three</button>
      <button data-view="3d" aria-pressed="false" title="3D (3)"><svg class="i" data-i="box"></svg>3D</button>
    </div>
    <div class="seg" role="group" aria-label="Frame" id="frameSeg">
      <button data-frame="world" aria-pressed="true" title="The scene's frame, where truth is (W)">World</button>
      <button data-frame="map" aria-pressed="false" title="The robot's own map frame (W)">Map</button>
    </div>
    <span class="grow"></span>
    <label id="follow" class="follow" hidden><input type="checkbox" id="follow-on" checked> Follow live</label>
    <span class="chip" id="runinfo"></span>
    <button class="pick-btn" id="exportBtn" disabled aria-haspopup="dialog">Export video</button>
    <button class="icon-btn" id="themeBtn" title="Theme"></button>
    <button class="icon-btn" id="helpBtn" title="Keyboard shortcuts (?)"><svg class="i" data-i="key"></svg></button>
  </header>

  <aside class="left" id="left">
    <section class="region">
      <div class="rhead">
        <span class="rtitle">Streams</span>
        <label class="search"><svg class="i" data-i="search" style="width:12px;height:12px"></svg><input id="q" placeholder="Search" aria-label="Search streams"><span class="kbd">/</span></label>
        <button class="icon-btn" id="filterBtn" title="Filter"><svg class="i" data-i="funnel"></svg></button>
        <button class="icon-btn" id="collapseBtn" title="Collapse all"><svg class="i" data-i="collapse"></svg></button>
      </div>
      <div class="tree" id="tree" role="tree" aria-label="Streams" tabindex="0"></div>
    </section>
    <div class="split" id="split" title="Drag to resize"></div>
    <section class="props" id="props" aria-label="Stream properties"></section>
  </aside>

  <main class="view" id="stage">
    <div class="vhead">
      <span class="vt" id="vt"></span>
      <span class="grow"></span>
      <button class="icon-btn" id="ovBtn" title="Overlays"><svg class="i" data-i="layers"></svg></button>
      <button class="icon-btn" id="fitBtn" title="Fit the run (F)"><svg class="i" data-i="fit"></svg></button>
    </div>
    <svg class="gizmo" id="gizmo" viewBox="0 0 56 56" aria-hidden="true"></svg>
    <div class="vcorner"><div class="scale" id="scale" hidden></div><div class="legend" id="legend"></div></div>
    <div class="readout" id="readout">x —  y — m</div>
    <div class="sigview" id="sigview" hidden aria-label="Signals"></div>
  </main>

  <aside class="right region" id="insp">
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" aria-selected="true" id="tabMoment">Moment</button>
      <button class="tab" role="tab" aria-selected="false" id="tabSel">Selection</button>
      <span class="grow"></span>
    </div>
    <div class="props" id="inspBody"></div>
  </aside>

  <section class="tl" id="tl" aria-label="Timeline">
    <div class="transport">
      <button class="icon-btn" id="tFirst" title="Start (Home)"><svg class="i" data-i="first"></svg></button>
      <button class="icon-btn" id="tPrev" title="Previous tick (←)"><svg class="i" data-i="left"></svg></button>
      <button class="play" id="playBtn" title="Play (Space)"></button>
      <button class="icon-btn" id="tNext" title="Next tick (→)"><svg class="i" data-i="right"></svg></button>
      <button class="icon-btn" id="tLast" title="End (End)"><svg class="i" data-i="last"></svg></button>
      <span class="tfield" id="tfT" title="Drag to scrub, click to type"><input id="tin" aria-label="Time in seconds" value="0.00"><span class="u">s</span></span>
      <span class="tfield tick" id="tfK" title="Tick: drag to scrub, click to type"><span class="u">tick</span><input id="kin" aria-label="Tick (1-based)" value="1"><span class="u" id="kn">of 0</span></span>
    </div>
    <div class="tlopts">
      <button class="mini" id="speedBtn" title="Playback speed (Shift+↑/↓)">1×<svg class="i" data-i="down" style="width:11px;height:11px"></svg></button>
      <button class="mini" id="loopBtn" aria-pressed="false" title="Loop"><svg class="i" data-i="repeat" style="width:12px;height:12px"></svg></button>
      <button class="mini" id="kindsBtn" title="Event kinds shown">Events <span class="mono" id="kindsN">0</span><svg class="i" data-i="down" style="width:11px;height:11px"></svg></button>
      <span class="grow"></span>
      <button class="mini" id="lanesBtn" aria-pressed="true" title="Data rows, one per stream"><svg class="i" data-i="rows" style="width:12px;height:12px"></svg>Rows</button>
    </div>
    <div class="ruler" id="ruler"></div>
    <div class="mlane" id="mlane"></div>
    <div class="lanes" id="lanes"><div class="lanes-l" id="lanesL"></div><div class="dlanes" id="dlanes"></div></div>
    <div class="tlfill-l"></div>
    <div class="range" id="range"><div class="bar" id="rbar"></div></div>
    <div class="overlay" id="overlay"><div class="ph" id="ph"><span class="head">0.00 s</span></div></div>
  </section>

  <section class="scenespage" id="scenespage"></section>

  <footer class="status">
    <span>Space play · ←/→ step · , . events · H hide · / search · ? keys</span>
    <span class="mono" id="st-run"></span>
    <span id="st-live"></span>
  </footer>
</div>
<div class="tip" id="tip" hidden></div>`;
