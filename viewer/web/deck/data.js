// Loads a scene and a run and precomputes everything the layers need, so scrubbing only picks.
const get = async (u) => (await fetch(u)).json();
export const loadIndex = () => get('/api/v1/scenes');

const COL = { f: [60, 200, 90, 255], o: [230, 50, 40, 255], v: [60, 120, 230, 255], b: [230, 0, 230, 255] };
export const KIND_NAME = { f: 'floor', o: 'obstacle', v: 'overhead', b: 'below the floor' };
export const KIND_COL = COL;
export const IDENT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

const matrix = ([x, y, yaw]) => {
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, x, y, 0, 1];
};
const apply = ([tx, ty, yaw], [x, y, h]) => {
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return [tx + c * x - s * y, ty + s * x + c * y, h + yaw];
};

export async function loadScene(id) {
  const sc = await get(`/api/v1/scenes/${id}`);
  const ring = (b, z) => {
    const c = Math.cos(b.yaw), s = Math.sin(b.yaw);
    return [[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]].map(([a, d]) => {
      const x = a * b.hx, y = d * b.hy;
      return [b.cx + c * x - s * y, b.cy + s * x + c * y, z];
    });
  };
  const paths = [];
  for (const b of sc.boxes) {
    const z1 = Math.min(b.z1, 0.5); // cut away at 0.5 m
    const lo = ring(b, b.z0), hi = ring(b, z1);
    paths.push({ path: lo }, { path: hi });
    for (let k = 0; k < 4; k++) paths.push({ path: [lo[k], hi[k]] });
  }
  const hz = sc.hazards.flatMap((h) => {
    const r = (z) => [[h.x0, h.y0, z], [h.x1, h.y0, z], [h.x1, h.y1, z], [h.x0, h.y1, z], [h.x0, h.y0, z]];
    const lo = r(-h.depth), hi = r(0);
    return [{ path: hi }, { path: lo }, ...[0, 1, 2, 3].map((k) => ({ path: [lo[k], hi[k]] }))];
  });
  return { ...sc, boxPaths: paths, hazardPaths: hz };
}

export async function loadRun(id) {
  const [run, f] = await Promise.all([get(`/api/v1/runs/${id}`), get(`/api/v1/runs/${id}/frames`)]);
  const n = f.t.length;
  const epochs = run.epochs.map((e) => ({ from_t: e.from_t, p: e.map_to_world, mat: matrix(e.map_to_world) }));
  const epochAt = (t) => { let e = epochs[0]; for (const x of epochs) if (x.from_t <= t) e = x; return e; };
  const epochIdx = new Array(n);
  for (let i = 0; i < n; i++) epochIdx[i] = epochs.indexOf(epochAt(f.t[i]));
  const beliefW = f.belief.map((p, i) => apply(epochs[epochIdx[i]].p, p));
  const trackMap = f.belief.map((p) => [p[0], p[1], 0]);
  const trackW = beliefW.map((p) => [p[0], p[1], 0]);
  const trackT = f.truth.map((p) => p && [p[0], p[1], 0]);
  // newest tick at or before i that carries depth
  const depthIdx = new Array(n);
  let last = -1;
  for (let i = 0; i < n; i++) { if (f.depth[i]) last = i; depthIdx[i] = last; }
  // Every depth point has one stable global index (file order); each kind also gets its own packed
  // arrays with a per-tick offset, so "the points of ticks a..b" is one contiguous subarray.
  let total = 0;
  for (const d of f.depth) total += d ? d.length : 0;
  const gpos = new Float32Array(total * 3), gkind = new Uint8Array(total), gtick = new Int32Array(total), goff = new Int32Array(n + 1);
  const kcount = { f: 0, o: 0, v: 0, b: 0 };
  let g = 0;
  for (let i = 0; i < n; i++) {
    goff[i] = g;
    for (const p of f.depth[i] || []) { gpos.set(p.slice(0, 3), g * 3); gkind[g] = 'fovb'.indexOf(p[3]); gtick[g] = i; kcount[p[3]]++; g++; }
  }
  goff[n] = g;
  const dk = {};
  for (const [k, ch] of ['f', 'o', 'v', 'b'].entries()) {
    const pos = new Float32Array(kcount[ch] * 3), gi = new Int32Array(kcount[ch]), off = new Int32Array(n + 1);
    let c = 0;
    for (let i = 0; i < n; i++) { off[i] = c; for (let q = goff[i]; q < goff[i + 1]; q++) if (gkind[q] === k) { pos.set(gpos.subarray(q * 3, q * 3 + 3), c * 3); gi[c++] = q; } }
    off[n] = c;
    dk[ch] = { pos, gi, off };
  }
  // the points of one kind in ticks a..b, as deck.gl binary attributes; base maps a layer index back to dk[ch].gi
  const depthRange = (ch, a, b) => {
    const { pos, off } = dk[ch];
    if (a < 0 || b < a) return null;
    const lo = off[a], hi = off[b + 1];
    return { base: lo, data: { length: hi - lo, attributes: { getPosition: { value: pos.subarray(lo * 3, hi * 3), size: 3 } } } };
  };
  const depthPoint = (gi) => ({ p: Array.from(gpos.subarray(gi * 3, gi * 3 + 3)), kind: 'fovb'[gkind[gi]], tick: gtick[gi] });
  const planData = f.plans.map((p) => [{ path: p.path.map(([x, y]) => [x, y, 0]) }]);
  const worldCache = new Map();
  const worldAt = (w) => {
    if (w < 0) return null;
    let o = worldCache.get(w);
    if (!o) {
      const W = f.worlds[w], g = W.grid, cells = [];
      for (let k = 0; k < g.cells.length; k++) {
        const ch = g.cells[k];
        if (ch === '?') continue;
        const x0 = g.origin[0] + (k % g.w) * g.res, y0 = g.origin[1] + Math.floor(k / g.w) * g.res;
        cells.push({ k, poly: [[x0, y0], [x0 + g.res, y0], [x0 + g.res, y0 + g.res], [x0, y0 + g.res]], c: ch === '#' ? [80, 80, 80, 255] : [205, 236, 205, 255] });
      }
      o = { cells, obstacles: W.obstacles.map(([x, y]) => [x, y, 0]), drops: W.drops.map(([x, y]) => [x, y, 0]) };
      worldCache.set(w, o);
    }
    return o;
  };
  const t = f.t;
  return { run, f, t, n, epochs, epochAt, epochIdx, beliefW, trackMap, trackW, trackT, depthIdx, depthRange, depthPoint, dk, depthTotal: total, planData, worldAt,
    t0: run.t0, t1: run.t1 };
}

// first tick whose time is after t - w (the start of "the last w seconds")
export const firstAfter = (t, ts) => { let lo = 0, hi = ts.length; while (lo < hi) { const m = (lo + hi) >> 1; if (ts[m] > t) hi = m; else lo = m + 1; } return lo; };
export const applyPose = apply;
export const idxAt = (t, ts) => { // last i with ts[i] <= t
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ts[m] <= t) lo = m; else hi = m - 1; }
  return lo;
};
