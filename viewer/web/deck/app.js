import { loadIndex, loadScene, loadRun, idxAt, applyPose, KIND_NAME } from './data.js';
import { buildLayers, shown } from './layers.js';

const { Deck, OrthographicView, OrbitView } = deck;
const $ = (s) => document.querySelector(s);
const EVCOL = [[/stop/, '#e03030'], [/refus/, '#e68a00'], [/cliff|drop|hazard/, '#e600e6'], [/recover|reset/, '#2a8bd8'], [/reach|done|end|arriv/, '#28a050']];
const evColor = (k) => (EVCOL.find(([r]) => r.test(k)) || [0, '#8a8a96'])[1];
const MODE_NAME = { at: 'at t', window: 'last N s', upto: 'all up to t' };
const PIPS = { top: 'T', front: 'F', right: 'S', '3d': '3' };

const S = {
  mode: 'top', dv: false, coord: true, t: 0, i: 0, scene: null, D: null, index: null,
  streams: {}, vis: {}, tm: {}, vv: {}, rel: { belief_truth: true, depth_pose: false }, sel: null, selPos: null, pickBase: {},
};
let dk, panes = [], viewState = {}, userView = false, afterRender = [];

// --- views -----------------------------------------------------------------
const paneList = (mode) => mode === 'three'
  ? [{ id: 'top', kind: 'top', x: 0, y: 0, w: 0.5, h: 0.5 }, { id: '3d', kind: '3d', x: 0.5, y: 0, w: 0.5, h: 0.5 },
    { id: 'front', kind: 'front', x: 0, y: 0.5, w: 0.5, h: 0.5 }, { id: 'right', kind: 'right', x: 0.5, y: 0.5, w: 0.5, h: 0.5 }]
  : [{ id: mode, kind: mode, x: 0, y: 0, w: 1, h: 1 }];

function makeViews() {
  return panes.map((p) => {
    const box = { x: `${p.x * 100}%`, y: `${p.y * 100}%`, width: `${p.w * 100}%`, height: `${p.h * 100}%` };
    return p.kind === '3d' ? new OrbitView({ id: p.id, controller: true, ...box }) : new OrthographicView({ id: p.id, flipY: false, near: -100, far: 100, controller: true, ...box });
  });
}

function fit() {
  const b = S.scene.bounds, W = $('#stage').clientWidth, H = $('#stage').clientHeight, cx = (b[0] + b[1]) / 2, cy = (b[2] + b[3]) / 2;
  viewState = {};
  for (const p of panes) {
    const w = W * p.w, h = H * p.h, m = 1.0;
    if (p.kind === 'top') viewState[p.id] = { target: [cx, cy, 0], zoom: Math.log2(Math.min(w / (b[1] - b[0] + m), h / (b[3] - b[2] + m))) };
    else if (p.kind === '3d') viewState[p.id] = { target: [cx, cy, 0], zoom: Math.log2(Math.min(w, h) / 10), rotationX: 40, rotationOrbit: -25 };
    else {
      const fb = p.kind === 'front' || p.kind === 'back', ext = fb ? b[1] - b[0] : b[3] - b[2];
      const c = fb ? cx : cy, sign = p.kind === 'back' || p.kind === 'left' ? -1 : 1; // screen x = sign * c
      viewState[p.id] = { target: [sign * c, 0.5, 0], zoom: Math.log2(Math.min(w / (ext + 1), h / 3.6)) };
    }
  }
  userView = false;
}

function tags() {
  const frame = S.dv ? 'map' : 'world', dirs = { top: 'x right, y up', front: 'x right, z up', back: 'x left, z up', left: 'y left, z up', right: 'y right, z up', '3d': 'orbit' };
  $('#tags').innerHTML = panes.map((p) => `<div class="pane" style="left:${p.x * 100}%;top:${p.y * 100}%;width:${p.w * 100}%;height:${p.h * 100}%"></div>
    <div class="tag" style="left:calc(${p.x * 100}% + 6px);top:calc(${p.y * 100}% + 6px)">frame: <b>${frame}</b> · ${p.kind} · ${dirs[p.kind]}</div>`).join('');
}

function setMode(m) {
  if (!['top', 'front', 'back', 'left', 'right', 'three', '3d'].includes(m)) return false;
  S.mode = m; panes = paneList(m); $('#view').value = m;
  fit(); tags();
  dk.setProps({ views: makeViews(), viewState });
  panel(); render(); writeHash();
  return true;
}

// --- render ----------------------------------------------------------------
function render() {
  if (!S.D) return;
  S.i = idxAt(S.t, S.D.t);
  S.selPos = selInfo()?.pos || null;
  S.pickBase = {};
  dk.setProps({ layers: panes.flatMap((p) => buildLayers(S, p)) });
  moment();
  $('#cursor').style.left = `${((S.t - S.D.t0) / (S.D.t1 - S.D.t0)) * 100}%`;
  $('#cursor').dataset.t = S.t.toFixed(1);
  const evs = shown(S, 'events') ? '' : 'none';
  $('#track').querySelectorAll('.ev').forEach((e) => { e.style.display = evs; });
}
let queued = false;
const requestRender = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; render(); }); } };

const f3 = (n) => (n == null ? null : +n.toFixed(4));
const pose = (p) => (p ? p.map(f3) : null);
function current() {
  const { D, i } = S, f = D.f, b = D.beliefW[i], tr = f.truth[i], mb = f.belief[i];
  const ev = D.run.events.filter((e) => e.t <= Math.max(S.t, f.t[i])).pop() || null;
  return { b, tr, mb, ev, dist: tr ? Math.hypot(b[0] - tr[0], b[1] - tr[1]) : null };
}

function moment() {
  const { D, i } = S, f = D.f, { b, tr, mb, ev, dist } = current();
  const fmt = (p) => (p ? `${p[0].toFixed(3)}, ${p[1].toFixed(3)}<br>yaw ${(p[2] * 180 / Math.PI).toFixed(1)}°` : '—');
  const ep = D.epochAt(f.t[i]);
  $('#momentbody').innerHTML = `<table>
    <tr><td>t</td><td>${f.t[i].toFixed(2)} s (tick ${i})</td></tr>
    <tr><td><span class="sw" style="background:#4682ff"></span>belief ${S.dv ? '(map)' : '(world)'}</td><td>${fmt(S.dv ? mb : b)}</td></tr>
    <tr><td><span class="sw" style="background:#28b45a"></span>truth (world)</td><td>${fmt(tr)}</td></tr>
    <tr><td>belief ↔ truth</td><td>${dist == null ? '—' : dist.toFixed(3) + ' m'}${S.rel.belief_truth ? '' : ' (line off)'}</td></tr>
    <tr><td>epoch</td><td>from ${ep.from_t.toFixed(1)} s</td></tr>
    <tr><td>last event</td><td>${ev ? `<span class="sw" style="background:${evColor(ev.kind)}"></span>${ev.t.toFixed(1)} s<br>${ev.text}` : '—'}</td></tr></table>`;
  const s = selInfo();
  $('#selbody').innerHTML = s ? `<table>
    <tr><td>stream</td><td>${s.stream}</td></tr><tr><td>kind</td><td>${s.detail}</td></tr>
    <tr><td>position</td><td>${s.x.toFixed(3)}, ${s.y.toFixed(3)} (${s.frame})</td></tr>
    <tr><td>height</td><td>${s.z.toFixed(3)} m</td></tr>
    <tr><td>tick</td><td>${s.tick} (t ${D.t[s.tick].toFixed(2)} s)</td></tr></table>` : '<span style="color:#999">click a depth point, a robot or a map cell</span>';
}

// --- selection -------------------------------------------------------------
// kinds: depth (index = the point's place in the file, all ticks in order), belief / truth (index = tick),
// cell (index = row-major cell of the map grid at the current tick)
function selInfo() {
  const sel = S.sel, D = S.D;
  if (!sel || !D) return null;
  const shownFrame = S.dv ? 'map' : 'world';
  const at = (p, tick) => { const q = S.dv ? p : applyPose(D.epochs[D.epochIdx[tick]].p, p); return [q[0], q[1]]; };
  if (sel.kind === 'depth') {
    if (sel.index < 0 || sel.index >= D.depthTotal) return null;
    const { p, kind, tick } = D.depthPoint(sel.index), [x, y] = at(p, tick);
    return { stream: `sensors.depth.${{ f: 'floor', o: 'obstacle', v: 'overhead', b: 'below' }[kind]}`, detail: KIND_NAME[kind], x, y, z: p[2], tick, frame: shownFrame, pos: [x, y, p[2]] };
  }
  if (sel.kind === 'belief' || sel.kind === 'truth') {
    const tick = sel.index, p = sel.kind === 'belief' ? (S.dv ? D.f.belief[tick] : D.beliefW[tick]) : D.f.truth[tick];
    if (!p || (sel.kind === 'truth' && S.dv)) return null;
    return { stream: `${sel.kind}.pose`, detail: `robot, yaw ${(p[2] * 180 / Math.PI).toFixed(1)} deg`, x: p[0], y: p[1], z: 0, tick, frame: sel.kind === 'truth' ? 'world' : shownFrame, pos: [p[0], p[1], 0] };
  }
  if (sel.kind === 'cell') {
    const W = D.f.worlds[sel.world];
    if (!W) return null;
    const g = W.grid, k = sel.index, p = [g.origin[0] + ((k % g.w) + 0.5) * g.res, g.origin[1] + (Math.floor(k / g.w) + 0.5) * g.res, 0];
    const [x, y] = at(p, S.i);
    return { stream: 'world.grid', detail: g.cells[k] === '#' ? 'occupied cell' : g.cells[k] === '.' ? 'free cell' : 'unknown cell', x, y, z: 0, tick: S.i, frame: shownFrame, pos: [x, y, 0] };
  }
  return null;
}

function select(sel) {
  if (!sel || sel.kind == null) S.sel = null;
  else {
    S.sel = { kind: sel.kind, index: sel.index };
    if (sel.kind === 'cell') S.sel.world = sel.world ?? S.D.f.world_at[S.i];
    if (!selInfo()) S.sel = null;
  }
  render();
  return S.sel && { ...S.sel, ...selInfo() };
}

function onClick(info) {
  const lid = info.layer && info.layer.id.split('@')[0];
  if (!lid || info.index < 0) return select(null);
  if (lid.startsWith('depth')) { const b = S.pickBase[info.layer.id]; return select({ kind: 'depth', index: S.D.dk[b.ch].gi[b.base + info.index] }); }
  if (lid === 'map') return select({ kind: 'cell', index: info.object.k });
  if (lid.startsWith('belief')) return select({ kind: 'belief', index: S.i });
  if (lid.startsWith('truth')) return select({ kind: 'truth', index: S.i });
  return select(null);
}

// --- the streams panel -----------------------------------------------------
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
function row(st, kind) {
  const id = st.id, miss = st.missing, off = S.vis[id] === false, tm = S.tm[id];
  const nonFrame = S.dv && (id.startsWith('truth.') || id.startsWith('scene.'));
  const cls = ['row', kind === 'child' ? 'child' : '', miss ? 'missing' : '', nonFrame ? 'offframe' : ''].join(' ');
  const pips = S.mode === 'three' ? `<span class="pips">${Object.entries(PIPS).map(([v, c]) => `<button class="pip ${S.vv[v] && S.vv[v][id] === false ? 'off' : ''}" data-pip="${v}|${id}" title="${id} in the ${v} view">${c}</button>`).join('')}</span>` : '';
  const sub = !miss && st.time_modes && st.time_modes.length > 1
    ? `<div class="sub">time <select data-tm="${id}">${st.time_modes.map((m) => `<option value="${m}" ${tm.mode === m ? 'selected' : ''}>${MODE_NAME[m]}</option>`).join('')}</select>${tm.mode === 'window' ? `<input type="number" min="0.1" max="600" step="0.1" value="${tm.n}" data-tmn="${id}"> s` : ''}</div>` : '';
  return `<div class="${cls}" data-id="${id}" title="${nonFrame ? 'not drawn in the map frame' : ''}"><button class="eye ${off ? 'off' : ''}" data-eye="${id}" ${miss ? 'disabled' : ''} title="show / hide">${off ? '○' : '●'}</button>
    <span>${esc(st.name)}</span><span class="chip ${st.frame}">${st.frame}</span>
    ${miss ? `<span class="chip miss">missing: ${esc(st.why || '')}</span>` : `<span class="cnt">${st.count}${st.rate_hz ? ` · ${Math.round(st.rate_hz * 10) / 10} Hz` : ''}</span>${pips}`}${sub}</div>`;
}

function panel() {
  if (!S.D) return;
  const list = S.D.run.streams, groups = [...new Set(list.map((s) => s.group))];
  const tree = groups.map((g) => {
    const key = 'group:' + g, off = S.vis[key] === false;
    const pips = S.mode === 'three' ? `<span class="pips">${Object.entries(PIPS).map(([v, c]) => `<button class="pip ${S.vv[v] && S.vv[v][key] === false ? 'off' : ''}" data-pip="${v}|${key}">${c}</button>`).join('')}</span>` : '';
    const mine = list.filter((s) => s.group === g);
    return `<div class="row group"><button class="eye ${off ? 'off' : ''}" data-eye="${key}">${off ? '○' : '●'}</button><span>${esc(g)}</span>${pips}</div>`
      + mine.map((s) => row(s, s.parent ? 'child' : 'top')).join('');
  }).join('');
  const bt = S.rel.belief_truth;
  $('#layers').innerHTML = `<h4>view frame</h4>
    <div class="seg"><button data-frame="world" class="${S.dv ? '' : 'on'}">world</button><button data-frame="map" class="${S.dv ? 'on' : ''}">map (data only)</button></div>
    <label class="opt"><input type="checkbox" data-coord ${S.coord ? 'checked' : ''}> coordinate system</label>
    <h4>relations</h4>
    <label class="opt ${S.dv ? 'dis' : ''}"><input type="checkbox" data-rel="belief_truth" ${bt ? 'checked' : ''} ${S.dv ? 'disabled' : ''}> belief ↔ truth: line and distance</label>
    <label class="opt dis"><input type="checkbox" data-rel="depth_pose" disabled> depth ↔ pose<br><span style="font-size:11px">unavailable: the run has no frame times</span></label>
    <h4>streams</h4>${tree}`;
}

// every control is one call of the script API, so a click and a command do the same thing
function ui(e) {
  const d = e.target.dataset;
  if (d.eye) api.setVisible(d.eye, S.vis[d.eye] === false);
  else if (d.pip) { const [v, id] = d.pip.split('|'); api.setViewVisible(v, id, S.vv[v] && S.vv[v][id] === false); }
  else if (d.frame) api.setFrame(d.frame);
  else if (d.rel) api.setRelation(d.rel, e.target.checked);
  else if (d.tm) api.setTimeMode(d.tm, e.target.value);
  else if (d.tmn) api.setTimeMode(d.tmn, 'window', +e.target.value);
  else if ('coord' in d) { S.coord = e.target.checked; render(); }
}

// --- loading ---------------------------------------------------------------
async function load(sceneId, runId) {
  window.__ready = false;
  if (!S.index) S.index = await loadIndex();
  const sc = S.index.scenes.find((s) => s.id === sceneId) || S.index.scenes[0];
  const run = sc.runs.find((r) => r.id === runId) || sc.runs[0];
  document.body.classList.remove('scenes');
  S.scene = await loadScene(sc.id);
  S.D = await loadRun(run.id);
  S.streams = Object.fromEntries(S.D.run.streams.map((s) => [s.id, s]));
  S.vis = {}; S.vv = {}; S.sel = null;
  S.tm = Object.fromEntries(S.D.run.streams.map((s) => [s.id, { mode: s.default_mode || 'at', n: 0.5 }]));
  $('#scene').value = sc.id;
  $('#run').innerHTML = sc.runs.map((r) => `<option value="${r.id}">${r.id} (${r.kind}, ${r.length_s} s)</option>`).join('');
  $('#run').value = run.id;
  $('#runinfo').textContent = `${S.D.run.robot.name} · r ${S.D.run.robot.radius} m · ${S.D.run.verdict}`;
  $('#track').querySelectorAll('.ev').forEach((e) => e.remove());
  for (const e of S.D.run.events) {
    if (e.t < S.D.t0 || e.t > S.D.t1) continue;
    const d = document.createElement('div');
    d.className = 'ev'; d.title = `${e.t.toFixed(1)} s ${e.text}`; d.style.background = evColor(e.kind);
    d.style.left = `${((e.t - S.D.t0) / (S.D.t1 - S.D.t0)) * 100}%`;
    $('#track').append(d);
  }
  $('#tl').textContent = S.D.t0.toFixed(0) + ' s'; $('#tr').textContent = S.D.t1.toFixed(0) + ' s';
  S.t = Math.min(Math.max(S.t, S.D.t0), S.D.t1);
  fit(); dk.setProps({ viewState });
  panel(); render(); writeHash();
  await settle();
  window.__ready = true;
}

function scenesPage() {
  window.__ready = false;
  document.body.classList.add('scenes');
  history.replaceState(null, '', '#scenes');
  $('#scenespage').innerHTML = S.index.scenes.map((sc) => `<h2>${esc(sc.name)}</h2><div class="sub2">${esc(sc.id)} · ${sc.runs.length} runs</div>
    <table><tr><th>run</th><th>kind</th><th>length</th><th>verdict</th><th>events</th></tr>
    ${sc.runs.map((r) => `<tr class="run" data-scene="${sc.id}" data-run="${r.id}"><td><b>${esc(r.id)}</b></td><td>${esc(r.kind)}</td><td>${r.length_s} s</td><td><span class="verdict ${esc(r.verdict)}">${esc(r.verdict)}</span></td><td>${r.events}</td></tr>`).join('')}</table>`).join('');
  requestAnimationFrame(() => requestAnimationFrame(() => { window.__ready = true; }));
}

const settle = () => new Promise((r) => {
  const done = () => { clearTimeout(to); r(); };
  const to = setTimeout(done, 1500);
  afterRender.push(done);
  if (dk.redraw) dk.redraw('miniview');
});
function writeHash() {
  history.replaceState(null, '', `#scene=${S.scene.id}&run=${S.D.run.id}&view=${S.mode}${S.dv ? '&data=1' : ''}`);
}

// --- timebar ---------------------------------------------------------------
function scrub(ev) {
  const r = $('#track').getBoundingClientRect();
  S.t = S.D.t0 + Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * (S.D.t1 - S.D.t0);
  requestRender();
}
$('#track').addEventListener('pointerdown', (e) => { $('#track').setPointerCapture(e.pointerId); scrub(e); $('#track').onpointermove = scrub; });
$('#track').addEventListener('pointerup', () => { $('#track').onpointermove = null; });

// --- the script API (CONTRACT.md): every call clears __ready, draws, and sets it again ----------
const call = (fn) => async (...a) => {
  window.__ready = false;
  const r = await fn(...a);
  if (S.D) { render(); await settle(); }
  window.__ready = true;
  return r;
};
const streamIds = (id) => [id, ...Object.values(S.streams).filter((s) => s.parent === id).map((s) => s.id)];
const api = {
  load: async (scene, run) => { await load(scene, run); },
  scenes: () => scenesPage(),
  setTime: (t) => { S.t = Math.min(Math.max(+t, S.D.t0), S.D.t1); return S.t; },
  setView: (m) => setMode(m === 'side' ? 'right' : m),
  setFrame: (f) => { S.dv = f === 'map'; tags(); panel(); writeHash(); return S.dv ? 'map' : 'world'; },
  setVisible: (id, v) => { S.vis[id] = !!v; panel(); return S.vis[id]; },
  setTimeMode: (id, mode, seconds) => {
    const st = S.streams[id];
    if (!st || !(st.time_modes || []).includes(mode)) return false;
    for (const k of streamIds(id)) if ((S.streams[k].time_modes || []).includes(mode)) { S.tm[k].mode = mode; if (seconds != null) S.tm[k].n = seconds; }
    panel();
    return true;
  },
  setRelation: (name, v) => {
    if (name === 'depth_pose') return false; // the run has no frame times
    if (name !== 'belief_truth') return false;
    S.rel[name] = !!v; panel();
    return S.rel[name];
  },
  setViewVisible: (view, id, v) => {
    view = view === 'side' ? 'right' : view;
    (S.vv[view] = S.vv[view] || {})[id] = !!v; panel();
    return !!v;
  },
  select: (sel) => select(sel),
  state: () => {
    const { b, tr, mb, ev, dist } = current(), s = selInfo();
    return { t: f3(S.D.t[S.i]), frame: S.dv ? 'map' : 'world', belief: pose(S.dv ? mb : b), truth: pose(tr), distance: f3(dist), last_event: ev,
      selection: s && { kind: S.sel.kind, index: S.sel.index, stream: s.stream, detail: s.detail, position: [f3(s.x), f3(s.y)], height: f3(s.z), tick: s.tick, frame: s.frame } };
  },
};

window.miniview = Object.fromEntries(Object.entries(api).map(([k, fn]) => [k, ['state', 'scenes'].includes(k) ? fn : call(fn)]));
window.miniview.scenes = () => { scenesPage(); };
window.miniview.internals = { S, deck: () => dk };

// --- boot ------------------------------------------------------------------
async function boot() {
  S.index = await loadIndex();
  const h = new URLSearchParams(location.hash.slice(1));
  $('#scene').innerHTML = S.index.scenes.map((s) => `<option value="${s.id}">${s.name}</option>`).join('');
  S.mode = h.get('view') || 'top'; S.dv = h.get('data') === '1'; $('#view').value = S.mode;
  panes = paneList(S.mode);
  dk = new Deck({
    parent: $('#deck'), views: makeViews(), viewState: {}, controller: true, layers: [], useDevicePixels: 1, pickingRadius: 5,
    layerFilter: ({ layer, viewport }) => layer.id.endsWith('@' + viewport.id),
    onViewStateChange: ({ viewId, viewState: v }) => { viewState = { ...viewState, [viewId]: v }; userView = true; dk.setProps({ viewState }); },
    onAfterRender: () => { const q = afterRender; afterRender = []; q.forEach((r) => r()); },
    onClick: (info) => onClick(info),
    getCursor: () => 'crosshair',
  });
  $('#scene').onchange = () => load($('#scene').value);
  $('#run').onchange = () => load(S.scene.id, $('#run').value);
  $('#view').onchange = () => miniview.setView($('#view').value);
  $('#fit').onclick = () => { fit(); dk.setProps({ viewState }); };
  $('#scenes-link').onclick = (e) => { e.preventDefault(); scenesPage(); };
  $('#scenespage').addEventListener('click', (e) => { const r = e.target.closest('tr.run'); if (r) load(r.dataset.scene, r.dataset.run); });
  $('#layers').addEventListener('click', (e) => { if (e.target.matches('button')) ui(e); });
  $('#layers').addEventListener('change', (e) => { if (!e.target.matches('button')) ui(e); });
  window.addEventListener('resize', () => { if (!userView && S.D && !document.body.classList.contains('scenes')) { fit(); dk.setProps({ viewState }); } });
  tags();
  if (h.get('run') || h.get('scene')) await load(h.get('scene'), h.get('run'));
  else scenesPage();
}
boot();
