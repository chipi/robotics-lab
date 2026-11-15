// The deck.gl page: the shared workbench (../shell/) with a deck.gl renderer in #stage.
import { createShell } from '../shell/shell.js';
import { prepareScene, prepareRun, idxAt, applyPose, KIND_NAME } from './data.js';
import { buildLayers, setPalette } from './layers.js';

const { Deck, OrthographicView, OrbitView } = deck;

const ELEVATION = (Math.asin(6.5 / Math.hypot(5.5, 7.5, 6.5)) * 180) / Math.PI, ORBIT = 36.3;
let S, M, dk, stage, deckEl, tagsEl;
let panes = [], viewState = {}, userView = false, afterRender = [];
// what layers.js reads: the run, the scene, the moment, and the shell's say on what is shown
const X = { D: null, scene: null, i: 0, dv: false, coord: true, rel: null, selPos: null, pickBase: {}, shown: () => false, cfg: () => ({ mode: 'at', n: 2 }), size: () => 4 };
let runRaw = null, frRaw = null;

// --- views -----------------------------------------------------------------
const paneList = (mode) => (mode === 'three'
  ? [{ id: 'top', kind: 'top', x: 0, y: 0, w: 0.5, h: 1 }, { id: 'front', kind: 'front', x: 0.5, y: 0, w: 0.5, h: 0.5 },
    { id: 'right', kind: 'right', x: 0.5, y: 0.5, w: 0.5, h: 0.5 }]
  : [{ id: mode, kind: mode, x: 0, y: 0, w: 1, h: 1 }]);

function makeViews() {
  return panes.map((p) => {
    const box = { x: `${p.x * 100}%`, y: `${p.y * 100}%`, width: `${p.w * 100}%`, height: `${p.h * 100}%` };
    return p.kind === '3d' ? new OrbitView({ id: p.id, controller: true, fovy: 45, ...box }) : new OrthographicView({ id: p.id, flipY: false, near: -100, far: 100, controller: true, ...box });
  });
}

function fit() {
  const b = X.scene ? X.scene.bounds : [-4, 4, -3, 3], W = stage.clientWidth, H = stage.clientHeight, cx = (b[0] + b[1]) / 2, cy = (b[2] + b[3]) / 2;
  viewState = {};
  for (const p of panes) {
    const w = W * p.w, h = H * p.h, m = 1.8;
    if (p.kind === 'top') viewState[p.id] = { target: [cx, cy, 0], zoom: Math.log2(Math.min(w / (b[1] - b[0] + m), h / (b[3] - b[2] + m))) };
    // the three.js page's camera: 45 degrees, from (-5.5, -7.5, 6.5) at the origin, so 11 m of height fill the pane (the same framing)
    else if (p.kind === '3d') viewState[p.id] = { target: [0, 0, 0], zoom: Math.log2(h / 11), rotationX: ELEVATION, rotationOrbit: ORBIT };
    else {
      const fb = p.kind === 'front' || p.kind === 'back', ext = fb ? b[3] - b[2] : b[1] - b[0];   // front and back show y across, right and left x
      const c = fb ? cy : cx, sign = p.kind === 'back' || p.kind === 'left' ? -1 : 1;           // screen x = sign * c
      viewState[p.id] = { target: [sign * c, 0.5, 0], zoom: Math.log2(Math.min(w / (ext + 1), h / 3.6)) };
    }
  }
  userView = false;
}

function tags() {
  const frame = M.frame === 'map' ? 'map' : 'world';
  tagsEl.innerHTML = panes.length < 2 ? '' : panes.map((p) => `<div class="pane-box" style="left:${p.x * 100}%;top:${p.y * 100}%;width:${p.w * 100}%;height:${p.h * 100}%"></div>
    <div class="pane-tag" style="left:calc(${p.x * 100}% + 8px);top:calc(${p.y * 100}% + ${p.y === 0 ? 32 : 6}px)">${frame} · ${p.kind}</div>`).join('');
}

// --- selection -------------------------------------------------------------
// kinds: depth (index = the point's place in the file, all ticks in order), robot (0 belief, 1 truth, at the
// current tick), cell (index = row-major cell of a map grid, world = which grid)
function describe(sel) {
  const D = X.D;
  if (!sel || !D) return null;
  const dv = M.frame === 'map', frame = M.frame;
  const at = (p, tick) => { const q = dv ? p : applyPose(D.epochs[D.epochIdx[tick]].p, p); return [q[0], q[1]]; };
  if (sel.kind === 'depth') {
    if (sel.index < 0 || sel.index >= D.depthTotal) return null;
    const { p, kind, tick } = D.depthPoint(sel.index), q = at(p, tick);
    return { stream: `sensors.depth.${{ f: 'floor', o: 'obstacle', v: 'overhead', b: 'below' }[kind]}`, detail: `${KIND_NAME[kind]} return`, depth_kind: kind, p: q, height: p[2], tick, t: D.t[tick], frame };
  }
  if (sel.kind === 'robot') {
    const tick = M.i, truth = sel.index === 1, p = truth ? D.f.truth[tick] : (dv ? D.f.belief[tick] : D.beliefW[tick]);
    if (!p || (truth && dv)) return null;
    return { stream: truth ? 'truth.pose' : 'belief.pose', detail: `${truth ? 'truth' : 'belief'} robot`, p: [p[0], p[1]], height: D.run.robot.height, tick, t: D.t[tick], yaw: p[2], frame: truth ? 'world' : frame };
  }
  if (sel.kind === 'cell') {
    const W = D.f.worlds[sel.world];
    if (!W) return null;
    const g = W.grid, k = sel.index;
    if (k == null || k < 0 || k >= g.cells.length) return null;
    const c = [g.origin[0] + ((k % g.w) + 0.5) * g.res, g.origin[1] + (Math.floor(k / g.w) + 0.5) * g.res, 0];
    const st = { '#': 'occupied', '.': 'free' }[g.cells[k]] || 'unknown';
    return { stream: 'world.grid', detail: `${st} cell`, state: st, res: g.res, p: at(c, idxAt(W.t, D.t)), height: 0, tick: idxAt(W.t, D.t), t: W.t, frame };
  }
  return null;
}

function onClick(info) {
  const lid = info.layer && info.layer.id.split('@')[0];
  if (!lid || info.index < 0) return S.pick(null);
  if (lid.startsWith('depth')) { const b = X.pickBase[info.layer.id]; return S.pick({ kind: 'depth', index: X.D.dk[b.ch].gi[b.base + info.index] }); }
  if (lid === 'map') return S.pick({ kind: 'cell', index: info.object.k });
  if (lid.startsWith('belief')) return S.pick({ kind: 'robot', index: 0 });
  if (lid.startsWith('truth')) return S.pick({ kind: 'robot', index: 1 });
  return S.pick(null);
}

// the viewport under a client point, as stage-relative pixels
function viewportAt(cx, cy) {
  const r = stage.getBoundingClientRect(), x = cx - r.left, y = cy - r.top;
  const vp = dk.getViewports().find((v) => x >= v.x && x < v.x + v.width && y >= v.y && y < v.y + v.height);
  return vp ? { vp, x: x - vp.x, y: y - vp.y } : null;
}

const adapter = {
  init(stage_, shell) {
    stage = stage_; S = shell; M = shell.M;
    deckEl = document.createElement('div'); deckEl.id = 'deck';
    tagsEl = document.createElement('div'); tagsEl.id = 'tags';
    stage.prepend(tagsEl); stage.prepend(deckEl);
    X.rel = M.rel;
    X.shown = (id, pane) => S.shown(id, pane); X.cfg = (id) => S.cfg(id); X.size = (id) => S.size(id);
    panes = paneList('top');
    dk = new Deck({
      parent: deckEl, views: makeViews(), viewState: {}, controller: true, layers: [], useDevicePixels: 1, pickingRadius: 5,
      layerFilter: ({ layer, viewport }) => layer.id.endsWith('@' + viewport.id),
      onViewStateChange: ({ viewId, viewState: v }) => { viewState = { ...viewState, [viewId]: v }; userView = true; dk.setProps({ viewState }); S.viewChanged(); },
      onAfterRender: () => { const q = afterRender; afterRender = []; q.forEach((r) => r()); },
      getCursor: () => 'crosshair',
    });
    // A click is a press and a release that moved less than 4 px, however long it took: deck's own tap gives up after
    // 250 ms, which a slow frame exceeds. Picking is by hand on the release; dragging still pans.
    let down = null;
    deckEl.addEventListener('pointerdown', (e) => { down = e.button === 0 ? [e.clientX, e.clientY] : null; }, true);
    deckEl.addEventListener('pointerup', (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
      down = null;
      if (moved > 4) return;
      const r = deckEl.getBoundingClientRect();
      onClick(dk.pickObject({ x: e.clientX - r.left, y: e.clientY - r.top, radius: 5 }) || { index: -1 });
    }, true);
  },

  setScene(sc) { X.scene = prepareScene(sc); },
  setRun(run, fr) { runRaw = run; frRaw = fr; X.D = prepareRun(run, fr); },
  // the run grew: prepare what it gained; nothing prepared is touched
  append(range) { if (X.D) X.D.append(range); },
  setLayout(view, frame) {
    X.dv = frame === 'map';
    panes = paneList(view);
    fit(); tags();
    dk.setProps({ views: makeViews(), viewState });
  },

  draw() {
    if (!X.D) return;
    X.i = M.i; X.dv = M.frame === 'map'; X.coord = M.ov.coords;
    const d = M.sel ? describe(M.sel) : null;
    X.selPos = d ? [d.p[0], d.p[1], d.height] : null;
    X.pickBase = {};
    dk.setProps({ layers: panes.flatMap((p) => buildLayers(X, p)) });
  },
  // deck.gl applies the layers set by draw() on its next animation frame, and calls onAfterRender when that frame is
  // drawn: ready is that call (or, should deck have nothing to redraw, 1.5 s). Never force a redraw here: each one
  // is a whole frame, and they pile up.
  settled: () => new Promise((r) => {
    const finish = () => { clearTimeout(to); r(); };
    const to = setTimeout(finish, 1500);
    afterRender.push(finish);
  }),
  resize() { if (!userView && X.D && stage.clientWidth && stage.clientHeight) { fit(); dk.setProps({ viewState }); } },
  fit() { fit(); dk.setProps({ viewState }); },
  theme(p) {
    setPalette(p);
    if (runRaw) X.D = prepareRun(runRaw, frRaw);
  },
  describe,
  deck: () => dk,
  fillsDrawn: (pane) => dk.props.layers.some((l) => l.id === 'boxfill@' + pane && l.props.visible),
  project(p) {
    const vp = dk.getViewports()[0], r = stage.getBoundingClientRect();
    if (!vp) return null;
    const q = vp.project(p);
    return [r.left + vp.x + q[0], r.top + vp.y + q[1]];
  },

  // world coordinates under the pointer: the two axes of an orthographic pane (the side views through their rotation);
  // in the 3D pane the point of the floor (z = 0) under it, found by intersecting the pointer's ray (the unprojected
  // near and far points) with that plane; null values where it misses
  cursor(cx, cy) {
    const h = viewportAt(cx, cy);
    if (!h) return null;
    const pane = panes.find((p) => p.id === h.vp.id);
    if (!pane) return null;
    if (pane.kind === '3d') {
      const a = h.vp.unproject([h.x, h.y, 0]), b = h.vp.unproject([h.x, h.y, 1]), t = a[2] / (a[2] - b[2]);
      const ok = Number.isFinite(t) && t >= 0 && t <= 1;
      return { axes: ['x', 'y'], v: ok ? [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])] : [null, null], note: 'floor z 0' };
    }
    const [sx, sy] = h.vp.unproject([h.x, h.y]);
    return { top: { axes: ['x', 'y'], v: [sx, sy] }, front: { axes: ['y', 'z'], v: [sx, sy] }, back: { axes: ['y', 'z'], v: [-sx, sy] },
      right: { axes: ['x', 'z'], v: [sx, sy] }, left: { axes: ['x', 'z'], v: [-sx, sy] } }[pane.kind] || null;
  },

  // pixels per metre of the first pane when it is orthographic (deck.gl's zoom is the log2 of it)
  scale() {
    const p = panes[0], z = p && viewState[p.id]?.zoom;
    return p && p.kind !== '3d' && Number.isFinite(z) ? 2 ** z : null;
  },

  // the world axes as the 3D pane's camera sees them, from projecting the origin and the unit points
  gizmo() {
    const vp = dk.getViewports().find((v) => v.id === '3d');
    if (!vp) return null;
    const o = vp.project([0, 0, 0]), v = {};
    let big = 1e-6;
    for (const [k, p] of [['x', [1, 0, 0]], ['y', [0, 1, 0]], ['z', [0, 0, 1]]]) {
      const q = vp.project(p);
      v[k] = [q[0] - o[0], -(q[1] - o[1]), -((q[2] ?? 0) - (o[2] ?? 0))];
      big = Math.max(big, Math.hypot(v[k][0], v[k][1]));
    }
    for (const k in v) v[k] = [v[k][0] / big, v[k][1] / big, v[k][2] * 1e3];
    return v;
  },
};

createShell(adapter, { title: 'miniview - deck.gl' });
