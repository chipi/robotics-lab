import * as THREE from 'three';
import { Views } from './views.js';
import { buildScene, buildRun } from './build.js';

const $ = (id) => document.getElementById(id);
const DATA = '/site/data/';
const json = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u + ' ' + r.status); return r.json(); });
const KIND = { cliff_stop: '#e03030', reflex_stop: '#e07020', refused: '#c08000', trapped: '#802020', reached: '#28a050', leg: '#8a8a96', tight_pivot: '#8a40c0', no_survey_turn: '#20a0a0' };
const kindColor = (k) => KIND[k] || `hsl(${[...k].reduce((a, c) => a * 31 + c.charCodeAt(0), 7) % 360} 50% 45%)`;

// One three.js layer bit per drawable stream: a camera shows a stream only when its layer is on,
// which is what makes "off in this view only" free. Layer 0 is the coordinate frame and the marker.
const DRAWN = ['scene.boxes', 'scene.hazards', 'belief.pose', 'belief.track', 'truth.pose', 'truth.track',
  'sensors.depth.floor', 'sensors.depth.obstacle', 'sensors.depth.overhead', 'sensors.depth.below',
  'world.grid', 'world.obstacles', 'world.drops', 'plan.path', 'rel.belief_truth'];
const LAYER = Object.fromEntries(DRAWN.map((id, k) => [id, k + 1]));
const VIEW_ALIAS = { side: 'right', T: 'top', F: 'front', S: 'right' };
const MODE_LABEL = { at: 'at t', window: 'last N s', upto: 'all up to t' };
const PIPS = [['T', 'top'], ['F', 'front'], ['S', 'right']];

const renderer = new THREE.WebGLRenderer({ canvas: $('gl'), antialias: true });
renderer.setClearColor(0xffffff);
const scene = new THREE.Scene();
const views = new Views($('stage'), renderer, scene, () => { if (fr) draw(); });

const st = {
  index: null, sceneId: null, runId: null, view: 'top', frame: 'world', t: 0, i: 0,
  vis: {}, groupVis: {}, modes: {}, rel: { belief_truth: true, depth_pose: false }, vv: {}, sel: null,
};
const sceneCache = {};
let sceneG = null, run = null, fr = null, RW = null, RM = null, streams = [];

// the selection marker: a ring that stays the same size on screen
const ring = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.lineWidth = 6; g.strokeStyle = '#000'; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  g.lineWidth = 3; g.strokeStyle = '#fff'; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  return new THREE.CanvasTexture(c);
})();
const marker = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
  new THREE.PointsMaterial({ map: ring, size: 26, sizeAttenuation: false, transparent: true, depthTest: false }));
marker.frustumCulled = false; marker.renderOrder = 10; marker.visible = false;
scene.add(marker);

const meta = (id) => streams.find((s) => s.id === id);
const R = () => (st.frame === 'world' ? RW : RM);

// a stream shows when it is in the run, its eye, its group's eye and its parent's are all on
function eff(id) {
  if (id === 'rel.belief_truth') return st.rel.belief_truth && st.frame === 'world' && eff('belief.pose') && eff('truth.pose');
  const s = meta(id);
  if (!s || s.missing) return false;
  return st.vis[id] !== false && st.groupVis[s.group] !== false && (!s.parent || eff(s.parent));
}
const seenIn = (view, id) => {
  const s = meta(id);
  return st.vv[view]?.[id] !== false && (!s?.parent || seenIn(view, s.parent));
};
const cfg = (id) => st.modes[id] || { mode: 'at', n: 0.5 };

views.layerMask = (view) => {
  let m = 1;
  for (const id of DRAWN) if (eff(id) && seenIn(view, id)) m |= 1 << LAYER[id];
  return m;
};

function setLayers(obj, id) { obj.traverse((o) => o.layers.set(LAYER[id])); }

function hashRead() {
  const p = new URLSearchParams(location.hash.slice(1));
  return { scene: p.get('scene'), run: p.get('run'), view: p.get('view'), frame: p.get('frame') || (p.get('data') === '1' ? 'map' : null) };
}
function hashWrite() {
  history.replaceState(null, '', st.runId ? '#' + new URLSearchParams({ scene: st.sceneId, run: st.runId, view: st.view, frame: st.frame }) : '#scenes');
}

function applyVis() {
  const w = st.frame === 'world';
  if (sceneG) {
    sceneG.visible = w;
    for (const [id, o] of Object.entries(sceneG.parts)) o.visible = eff(id);
  }
  for (const [Rn, on] of [[RW, w], [RM, !w]]) {
    if (!Rn) continue;
    Rn.group.visible = on;
    for (const [id, o] of Object.entries(Rn.obj)) o.visible = eff(id);
  }
  for (const e of $('track').querySelectorAll('.ev')) e.style.display = eff('events') ? '' : 'none';
}

function draw() {
  applyVis();
  placeMarker();
  views.render();
}

function tickAt(t) {
  let lo = 0, hi = fr.t.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (fr.t[m] <= t) lo = m; else hi = m - 1; }
  return lo;
}

const f2 = (v) => v.toFixed(3);
const deg = (r) => (r * 180 / Math.PI).toFixed(1) + '°';
const lastEvent = () => [...run.events].reverse().find((e) => e.t <= st.t) || null;
const dist = () => {
  const i = st.i, tr = fr.truth[i], p = RW.pose;
  return tr ? Math.hypot(p[i * 3] - tr[0], p[i * 3 + 1] - tr[1]) : null;
};

// What a selection is, in the frame being looked at. Robots follow the cursor; points and cells stay.
function describe(sel) {
  if (!sel) return null;
  const Rn = R(), i = st.i;
  let o;
  if (sel.kind === 'robot') {
    const tr = sel.index === 1;
    const P = tr ? RW.tpose : Rn.pose;
    if (!P) return null;
    o = { stream: tr ? 'truth.pose' : 'belief.pose', p: [P[i * 3], P[i * 3 + 1]], height: run.robot.height, tick: i, yaw: P[i * 3 + 2] };
  } else {
    const l = Rn.locate(sel.kind, sel.index, sel.world);
    if (!l) return null;
    o = { stream: l.stream, p: [l.p[0], l.p[1]], height: l.p[2] };
    if (sel.kind === 'depth') { o.tick = l.tick; o.depth_kind = l.dk; o.t = fr.t[l.tick]; }
    if (sel.kind === 'cell') {
      o.tick = tickAt(l.wt); o.t = l.wt; o.state = { '#': 'occupied', '.': 'free' }[l.cell] || 'unknown'; o.res = l.res;
    }
  }
  if (o.t === undefined) o.t = fr.t[o.tick];
  return { kind: sel.kind, index: sel.index, ...(sel.world !== undefined && { world: sel.world }), ...o };
}

function placeMarker() {
  const d = st.sel && fr ? describe(st.sel) : null;
  marker.visible = !!d;
  if (!d) return;
  const a = marker.geometry.attributes.position;
  a.array.set([d.p[0], d.p[1], d.height]); a.needsUpdate = true;
}

function moment() {
  const i = st.i, b = [...RW.pose.slice(i * 3, i * 3 + 3)], bm = fr.belief[i], tr = fr.truth[i];
  const ev = lastEvent();
  let h = `<h4>moment</h4>t = <b>${st.t.toFixed(2)}</b> s (tick ${i})`;
  if (st.frame === 'map') {
    h += `<h4>belief (map)</h4>${f2(bm[0])}, ${f2(bm[1])}, ${deg(bm[2])}<h4>truth</h4>hidden in the data view`;
  } else {
    h += `<h4>belief (world)</h4>${f2(b[0])}, ${f2(b[1])}, ${deg(b[2])}`;
    h += tr ? `<h4>truth (world)</h4>${f2(tr[0])}, ${f2(tr[1])}, ${deg(tr[2])}` : '<h4>truth</h4>none';
    if (tr && st.rel.belief_truth) h += `<h4>belief ↔ truth</h4><b>${f2(dist())}</b> m apart`;
  }
  h += `<h4>last event</h4>` + (ev ? `<span style="color:${kindColor(ev.kind)}">&#9632;</span> ${ev.kind} at ${ev.t.toFixed(1)} s<br>${ev.text}` : '—');
  const d = describe(st.sel);
  h += '<h4>selection</h4>' + (d ? [
    `stream <b>${d.stream}</b>`, `kind ${d.depth_kind ? ({ f: 'floor', o: 'obstacle', v: 'overhead', b: 'below the floor' })[d.depth_kind] : d.state || d.kind}`,
    `position ${f2(d.p[0])}, ${f2(d.p[1])} (${st.frame})`, `height ${f2(d.height)} m`, `tick ${d.tick} (t ${d.t.toFixed(2)} s)`,
  ].join('<br>') : '<span class="dim">click a depth point, a robot or a map cell</span>');
  $('moment').innerHTML = h;
}

function setTime(t, sync) {
  if (!fr) return;
  t = Math.min(Math.max(t, fr.t[0]), fr.t[fr.t.length - 1]);
  st.t = t; st.i = tickAt(t);
  RW.update(st.i, t, cfg); RM.update(st.i, t, cfg);
  $('cursor').style.left = ((t - fr.t[0]) / (fr.t[fr.t.length - 1] - fr.t[0]) * 100) + '%';
  moment();
  draw();
  if (sync) { const gl = renderer.getContext(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4)); }
}

function timebar() {
  const tr = $('track');
  tr.querySelectorAll('.ev').forEach((e) => e.remove());
  const t0 = fr.t[0], t1 = fr.t[fr.t.length - 1];
  for (const e of run.events) {
    const d = document.createElement('div');
    d.className = 'ev'; d.title = `${e.t.toFixed(1)} s ${e.text}`;
    d.style.left = ((e.t - t0) / (t1 - t0) * 100) + '%'; d.style.background = kindColor(e.kind);
    tr.insertBefore(d, $('cursor'));
  }
  const kinds = [...new Set(run.events.map((e) => e.kind))];
  $('legend').innerHTML = kinds.map((k) => `<i style="background:${kindColor(k)}"></i>${k}`).join('');
}

// ---- the streams panel ------------------------------------------------------------------------

const EYE = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 8s2.5-4.5 7-4.5S15 8 15 8s-2.5 4.5-7 4.5S1 8 1 8z"/><circle cx="8" cy="8" r="2"/><path class="slash" d="M2 14L14 2"/></svg>';
const eyeBtn = (on, dis, attrs) => `<button class="eye${on ? '' : ' off'}" ${dis ? 'disabled' : ''} ${attrs}>${EYE}</button>`;
const nfmt = (n) => (n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n));

function panel() {
  const groups = [...new Set(streams.map((s) => s.group))];
  const noTruth = meta('truth.pose')?.missing;
  let h = `<h5>view frame</h5><div class="seg"><button data-frame="world" class="${st.frame === 'world' ? 'on' : ''}">world</button><button data-frame="map" class="${st.frame === 'map' ? 'on' : ''}">map</button></div>`;
  h += `<div class="note">${st.frame === 'world' ? 'the scene, and truth beside belief' : 'the data view: the robot\'s own map frame, no scene, no truth'}</div>`;
  h += '<h5>relations</h5>';
  h += `<label class="rel${noTruth ? ' off' : ''}"><input type="checkbox" data-rel="belief_truth" ${st.rel.belief_truth ? 'checked' : ''} ${noTruth ? 'disabled' : ''}> belief ↔ truth${noTruth ? ' (no truth in this run)' : ''}</label>`;
  h += '<label class="rel off"><input type="checkbox" data-rel="depth_pose" disabled> depth ↔ pose</label><div class="note">unavailable: the run has no frame times</div>';
  h += '<h5>streams</h5>';
  for (const g of groups) {
    h += `<div class="grp">${eyeBtn(st.groupVis[g] !== false, false, `data-group="${g}"`)}${g}</div>`;
    for (const s of streams.filter((x) => x.group === g)) {
      const off = st.vis[s.id] === false;
      const stats = s.missing ? `<span class="chip missing">missing: ${s.why || 'not in this run'}</span>`
        : `<span>${nfmt(s.count)}${s.rate_hz ? ' · ' + s.rate_hz + ' Hz' : ''}</span>`;
      const modes = s.time_modes && s.time_modes.length > 1 && !s.missing;
      const cur = cfg(s.id);
      const tm = modes ? `<span class="tm"><select data-tm="${s.id}">${s.time_modes.map((m) => `<option value="${m}"${m === cur.mode ? ' selected' : ''}>${MODE_LABEL[m]}</option>`).join('')}</select>`
        + `<input type="number" min="0.1" step="0.1" value="${cur.n}" data-tn="${s.id}" ${cur.mode === 'window' ? '' : 'hidden'}></span>` : '';
      const pips = !s.missing && (LAYER[s.id] || s.id === 'sensors.depth')
        ? `<span class="pips">${PIPS.map(([l, v]) => `<button class="pip${seenIn(v, s.id) ? ' on' : ''}" data-pip="${v}" data-id="${s.id}" title="${s.id} in the ${v} view">${l}</button>`).join('')}</span>` : '';
      h += `<div class="row${s.parent ? ' child' : ''}${s.missing ? ' missing' : ''}${st.frame === 'map' && (s.id.startsWith('scene.') || s.id.startsWith('truth.')) ? ' na' : ''}" data-row="${s.id}">${eyeBtn(!off, s.missing, `data-eye="${s.id}"`)}`
        + `<span class="nm" title="${s.id}">${s.name}</span>${pips}<span class="sub"><span class="chip ${s.frame}">${s.frame}</span>${stats}${tm}</span></div>`;
    }
  }
  $('layers').innerHTML = h;
  $('layers').classList.toggle('three', st.view === 'three');
}

$('layers').onclick = (e) => {
  const b = e.target.closest('button'), c = e.target.closest('[data-rel]');
  if (c) return api.setRelation(c.dataset.rel, c.checked);
  if (!b) return;
  if (b.dataset.frame) api.setFrame(b.dataset.frame);
  else if (b.dataset.eye) api.setVisible(b.dataset.eye, st.vis[b.dataset.eye] === false);
  else if (b.dataset.group) api.setVisible(b.dataset.group, st.groupVis[b.dataset.group] === false);
  else if (b.dataset.pip) api.setViewVisible(b.dataset.pip, b.dataset.id, !seenIn(b.dataset.pip, b.dataset.id));
};
$('layers').onchange = (e) => {
  const t = e.target;
  if (t.dataset.tm) api.setTimeMode(t.dataset.tm, t.value, cfg(t.dataset.tm).n);
  if (t.dataset.tn) api.setTimeMode(t.dataset.tn, cfg(t.dataset.tn).mode, parseFloat(t.value) || 0.5);
};

// ---- selection by picking ---------------------------------------------------------------------

const rc = new THREE.Raycaster();
rc.params.Line.threshold = 0.001;
views.onPick = (s, x, y) => {
  if (!fr) return;
  rc.setFromCamera({ x, y }, s.camera);
  rc.layers.mask = views.layerMask(s.name);
  rc.params.Points.threshold = 7 * views.metresPerPx(s);
  const rank = { depth: 0, robot: 1, cell: 2 };
  const hits = rc.intersectObject(R().group, true)
    .map((h) => ({ h, sel: h.object.userData.pick?.(h) })).filter((x) => x.sel && x.sel.kind in rank)
    .sort((a, b) => rank[a.sel.kind] - rank[b.sel.kind] || (a.h.distanceToRay ?? a.h.distance) - (b.h.distanceToRay ?? b.h.distance));
  st.sel = hits.length ? hits[0].sel : null;
  moment(); draw();
};

// ---- loading ----------------------------------------------------------------------------------

function setViewLayout(v) {
  views.setup(v, scene_bounds(), st.frame);
  $('layers').classList.toggle('three', v === 'three');
}
const scene_bounds = () => (sceneCache[st.sceneId]?.bounds ?? [-4, 4, -3, 3]);

async function loadScene(id) {
  st.sceneId = id; $('scenesel').value = id;
  sceneCache[id] ||= await json(`${DATA}scenes/${id}.json`);
  if (sceneG) scene.remove(sceneG);
  sceneG = buildScene(sceneCache[id]);
  for (const [sid, o] of Object.entries(sceneG.parts)) setLayers(o, sid);
  scene.add(sceneG);
  const runs = st.index.scenes.find((s) => s.id === id).runs;
  $('runsel').innerHTML = runs.map((r) => `<option value="${r.id}">${r.id} (${r.kind}, ${r.length_s} s)</option>`).join('');
}

async function loadRun(id) {
  st.runId = id; $('runsel').value = id;
  [run, fr] = await Promise.all([json(`${DATA}runs/${id}/run.json`), json(`${DATA}runs/${id}/frames.json`)]);
  for (const Rn of [RW, RM]) if (Rn) scene.remove(Rn.group);
  RW = buildRun(run, fr, true); RM = buildRun(run, fr, false);
  for (const Rn of [RW, RM]) for (const [sid, o] of Object.entries(Rn.obj)) setLayers(o, sid);
  scene.add(RW.group, RM.group);
  streams = run.streams || [];
  st.vis = {}; st.groupVis = {}; st.vv = {}; st.sel = null;
  st.modes = Object.fromEntries(streams.map((s) => [s.id, { mode: s.default_mode || 'at', n: 0.5 }]));
  document.body.classList.remove('scenes');
  setViewLayout(st.view);
  panel(); timebar();
  $('runinfo').textContent = `${run.robot.name} · ${run.verdict} · ${(run.t1 - run.t0).toFixed(1)} s · ${fr.t.length} ticks`;
  hashWrite();
  setTime(fr.t[0]);
}

function showScenes() {
  document.body.classList.add('scenes');
  st.runId = null; hashWrite();
  $('scenespage').innerHTML = st.index.scenes.map((s) => `<div class="sc"><h2>${s.name}</h2><span class="dim">${s.id === s.kind ? s.kind : s.id + ' · ' + s.kind} · ${s.runs.length} runs</span>`
    + `<table><thead><tr><th>run</th><th>kind</th><th>robot</th><th>length</th><th>verdict</th><th>events</th></tr></thead><tbody>`
    + s.runs.map((r) => `<tr data-scene="${s.id}" data-run="${r.id}"><td><a href="#scene=${s.id}&run=${r.id}">${r.id}</a></td><td>${r.kind}</td><td>${r.robot}</td><td>${r.length_s} s</td>`
      + `<td><span class="verdict ${r.verdict}">${r.verdict}</span></td><td>${r.events}</td></tr>`).join('')
    + '</tbody></table></div>').join('');
}
$('scenespage').onclick = (e) => {
  const tr = e.target.closest('tr[data-run]');
  if (tr) { e.preventDefault(); api.load(tr.dataset.scene, tr.dataset.run); }
};
$('scenes-link').onclick = (e) => { e.preventDefault(); api.load(); };

async function open(sceneId, runId) {
  if (!runId) return showScenes();
  if (sceneId !== st.sceneId) await loadScene(sceneId);
  await loadRun(runId);
}

// ---- the script API (CONTRACT.md) -------------------------------------------------------------
// every call clears __ready, does its work, and sets it again once the frame has been drawn

const settled = () => new Promise((res) => requestAnimationFrame(() => { window.__ready = true; res(); }));
const call = (fn) => (...a) => {
  window.__ready = false;
  let out;
  try { out = fn(...a); } catch (e) { settled(); throw e; }
  if (out instanceof Promise) return out.then((v) => settled().then(() => v), (e) => { settled(); throw e; });
  settled();
  return out;
};
const need = (id) => { const s = meta(id); if (!s) console.warn('miniview: no stream', id); return s; };
const kids = (id) => streams.filter((s) => s.parent === id).map((s) => s.id);

const api = {
  load: (scene, runId) => open(scene || st.sceneId || st.index.scenes[0].id, runId),
  setTime: (t, sync = false) => setTime(t, sync),
  setView(v) {
    v = VIEW_ALIAS[v] || v;
    st.view = v; $('viewsel').value = v;
    setViewLayout(v); hashWrite();
    if (fr) { panel(); draw(); }
  },
  setFrame(f) {
    st.frame = f === 'map' ? 'map' : 'world';
    setViewLayout(st.view); hashWrite();
    if (fr) { panel(); moment(); draw(); }
  },
  setVisible(id, on) {
    if (st.groupVis[id] !== undefined || streams.some((s) => s.group === id)) st.groupVis[id] = !!on;
    else if (need(id)) st.vis[id] = !!on;
    panel(); draw();
  },
  setTimeMode(id, mode, n) {
    const s = need(id);
    if (!s) return;
    if (!s.time_modes?.includes(mode)) return console.warn('miniview: stream', id, 'has no time mode', mode);
    for (const k of [id, ...kids(id)]) st.modes[k] = { mode, n: n ?? st.modes[k].n };
    panel(); setTime(st.t);
  },
  setRelation(name, on) {
    if (name === 'depth_pose') return console.warn('miniview: depth_pose is unavailable, the run has no frame times');
    st.rel[name] = !!on;
    panel(); moment(); draw();
  },
  setViewVisible(view, id, on) {
    view = VIEW_ALIAS[view] || view;
    (st.vv[view] ||= {})[id] = !!on;
    panel(); draw();
  },
  select(sel) {
    st.sel = sel && sel.kind ? { kind: sel.kind, index: sel.index, world: sel.kind === 'cell' ? sel.world ?? fr.world_at[st.i] : undefined } : null;
    moment(); draw();
  },
  state: () => ({
    t: st.t, tick: st.i, frame: st.frame, view: st.view,
    belief: [...RW.pose.slice(st.i * 3, st.i * 3 + 3)], belief_map: fr.belief[st.i],
    truth: fr.truth[st.i], distance: dist(), last_event: lastEvent(), selection: describe(st.sel),
    t_range: [fr.t[0], fr.t[fr.t.length - 1]],
  }),
};
window.miniview = Object.fromEntries(Object.entries(api).map(([k, f]) => [k, call(f)]));
window.miniview.setData = (d) => window.miniview.setFrame(d ? 'map' : 'world');

async function init() {
  st.index = await json(DATA + 'index.json');
  $('scenesel').innerHTML = st.index.scenes.map((s) => `<option value="${s.id}">${s.name}</option>`).join('');
  const h = hashRead();
  st.view = h.view || 'top'; st.frame = h.frame === 'map' ? 'map' : 'world'; $('viewsel').value = st.view;
  const sc = st.index.scenes.find((s) => s.id === h.scene);
  if (sc && sc.runs.some((r) => r.id === h.run)) await open(sc.id, h.run);
  else showScenes();
  await settled();
}

$('scenesel').onchange = async (e) => { await loadScene(e.target.value); await loadRun($('runsel').value); };
$('runsel').onchange = (e) => window.miniview.load(st.sceneId, e.target.value);
$('viewsel').onchange = (e) => window.miniview.setView(e.target.value);
new ResizeObserver(() => views.resize()).observe($('stage'));

const track = $('track');
const fromX = (ev) => { const r = track.getBoundingClientRect(); return fr.t[0] + Math.min(Math.max((ev.clientX - r.left) / r.width, 0), 1) * (fr.t[fr.t.length - 1] - fr.t[0]); };
track.onpointerdown = (e) => { track.setPointerCapture(e.pointerId); setTime(fromX(e)); };
track.onpointermove = (e) => { if (track.hasPointerCapture(e.pointerId)) setTime(fromX(e)); };

window.__ready = false;
init().catch((e) => { document.body.append(String(e)); console.error(e); });
