// Prepares a scene and a run (as the shell fetched them from the API) and precomputes everything the
// layers need, so scrubbing only picks.
export const KIND_COL = { f: [60, 200, 90, 255], o: [230, 50, 40, 255], v: [60, 120, 230, 255], b: [230, 0, 230, 255] };
export const CELL_COL = { occ: [80, 80, 80, 255], free: [205, 236, 205, 255] };
export const KIND_NAME = { f: 'floor', o: 'obstacle', v: 'overhead', b: 'below the floor' };
export const IDENT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

const matrix = ([x, y, yaw]) => {
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, x, y, 0, 1];
};
const apply = ([tx, ty, yaw], [x, y, h]) => {
  const c = Math.cos(yaw), s = Math.sin(yaw);
  return [tx + c * x - s * y, ty + s * x + c * y, h + yaw];
};

export function prepareScene(sc) {
  const ring = (b, z) => {
    const c = Math.cos(b.yaw), s = Math.sin(b.yaw);
    return [[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]].map(([a, d]) => {
      const x = a * b.hx, y = d * b.hy;
      return [b.cx + c * x - s * y, b.cy + s * x + c * y, z];
    });
  };
  const paths = [], fill = [], stairs = [];
  for (const b of sc.boxes) {
    if (b.z0 >= 0.5) continue;
    const z1 = Math.min(b.z1, 0.5); // cut away at 0.5 m
    const lo = ring(b, b.z0), hi = ring(b, z1);
    const stair = b.name.startsWith('stair');
    (stair ? stairs : fill).push({ poly: lo.slice(0, 4), z0: b.z0, z1 });
    paths.push({ path: lo, stair }, { path: hi, stair });
    for (let k = 0; k < 4; k++) paths.push({ path: [lo[k], hi[k]], stair });
  }
  const hz = sc.hazards.flatMap((h) => {
    const r = (z) => [[h.x0, h.y0, z], [h.x1, h.y0, z], [h.x1, h.y1, z], [h.x0, h.y1, z], [h.x0, h.y0, z]];
    const lo = r(-h.depth), hi = r(0);
    return [{ path: hi }, { path: lo }, ...[0, 1, 2, 3].map((k) => ({ path: [lo[k], hi[k]] }))];
  });
  const pits = sc.hazards.map((h) => ({ poly: [[h.x0, h.y0], [h.x1, h.y0], [h.x1, h.y1], [h.x0, h.y1]], z0: -h.depth, z1: 0 }));
  return { ...sc, boxPaths: paths, boxFill: fill, stairFill: stairs, hazardPaths: hz, pitFill: pits };
}

// a typed array that doubles when it is full
class Grow {
  constructor(T, stride, cap = 512) { this.T = T; this.s = stride; this.a = new T(cap * stride); }
  need(n) {
    if (n * this.s <= this.a.length) return;
    const b = new this.T(Math.max(n, (this.a.length / this.s) * 2) * this.s);
    b.set(this.a); this.a = b;
  }
}

// One run, prepared for drawing. It grows: append({i0, i1, plans, worlds}) prepares the ticks i0..i1-1 (and the plans
// and worlds that became available) and costs what it adds; nothing already prepared is touched.
export function prepareRun(run, f) {
  const epochs = [];
  const epochAt = (t) => { let e = epochs[0]; for (const x of epochs) if (x.from_t <= t) e = x; return e; };
  const epochIdx = [], beliefW = [], trackMap = [], trackW = [], trackT = [], depthIdx = [];
  // Every depth point has one stable global index (file order); each kind also gets its own packed
  // arrays with a per-tick offset, so "the points of ticks a..b" is one contiguous subarray.
  const gpos = new Grow(Float32Array, 3), gkind = new Grow(Uint8Array, 1), gtick = new Grow(Int32Array, 1), goff = new Grow(Int32Array, 1);
  const dk = {};
  for (const ch of ['f', 'o', 'v', 'b']) dk[ch] = { pos: new Grow(Float32Array, 3), gi: new Grow(Int32Array, 1), off: new Grow(Int32Array, 1), c: 0 };
  const planData = [];
  const worldCache = new Map();
  let n = 0, g = 0, last = -1;

  const append = (range) => {
    for (let k = epochs.length; k < run.epochs.length; k++) epochs.push({ from_t: run.epochs[k].from_t, p: run.epochs[k].map_to_world, mat: matrix(run.epochs[k].map_to_world) });
    const a = Math.max(range.i0 ?? 0, n), b = range.i1;
    gkind.need(g + 1); goff.need(b + 1);
    for (const ch in dk) dk[ch].off.need(b + 1);
    for (let i = a; i < b; i++) {
      epochIdx[i] = epochs.indexOf(epochAt(f.t[i]));
      beliefW[i] = apply(epochs[epochIdx[i]].p, f.belief[i]);
      trackMap[i] = [f.belief[i][0], f.belief[i][1], 0];
      trackW[i] = [beliefW[i][0], beliefW[i][1], 0];
      trackT[i] = f.truth[i] && [f.truth[i][0], f.truth[i][1], 0];
      if (f.depth[i]) last = i;
      depthIdx[i] = last;
      goff.a[i] = g;
      for (const ch in dk) dk[ch].off.a[i] = dk[ch].c;
      for (const p of f.depth[i] || []) {
        const ch = 'fovb'.includes(p[3]) ? p[3] : 'o', K = dk[ch];
        gpos.need(g + 1); gkind.need(g + 1); gtick.need(g + 1); K.pos.need(K.c + 1); K.gi.need(K.c + 1);
        gpos.a.set(p.slice(0, 3), g * 3); gkind.a[g] = 'fovb'.indexOf(p[3]); gtick.a[g] = i;
        K.pos.a.set(p.slice(0, 3), K.c * 3); K.gi.a[K.c++] = g;
        g++;
      }
    }
    goff.a[b] = g;
    for (const ch in dk) dk[ch].off.a[b] = dk[ch].c;
    n = Math.max(n, b);
    X.n = n; X.depthTotal = g;
    for (const k of range.plans || []) if (f.plans[k] && !planData[k]) planData[k] = [{ path: f.plans[k].path.map(([x, y]) => [x, y, 0]) }];
  };

  // the points of one kind in ticks a..b, as deck.gl binary attributes; base maps a layer index back to dk[ch].gi
  const depthRange = (ch, a, b) => {
    const pos = dk[ch].pos.a, off = dk[ch].off.a;
    if (a < 0 || b < a) return null;
    const lo = off[a], hi = off[b + 1];
    return { base: lo, data: { length: hi - lo, attributes: { getPosition: { value: pos.subarray(lo * 3, hi * 3), size: 3 } } } };
  };
  const depthPoint = (gi) => ({ p: Array.from(gpos.a.subarray(gi * 3, gi * 3 + 3)), kind: 'fovb'[gkind.a[gi]], tick: gtick.a[gi] });
  const worldAt = (w) => {
    if (w < 0 || !f.worlds[w]) return null;
    let o = worldCache.get(w);
    if (!o) {
      const W = f.worlds[w], g2 = W.grid, cells = [];
      for (let k = 0; k < g2.cells.length; k++) {
        const ch = g2.cells[k];
        if (ch === '?') continue;
        const x0 = g2.origin[0] + (k % g2.w) * g2.res, y0 = g2.origin[1] + Math.floor(k / g2.w) * g2.res;
        cells.push({ k, poly: [[x0, y0], [x0 + g2.res, y0], [x0 + g2.res, y0 + g2.res], [x0, y0 + g2.res]], c: ch === '#' ? CELL_COL.occ : CELL_COL.free });
      }
      o = { cells, obstacles: W.obstacles.map(([x, y]) => [x, y, 0]), drops: W.drops.map(([x, y]) => [x, y, 0]) };
      worldCache.set(w, o);
    }
    return o;
  };
  const X = { run, f, t: f.t, n: 0, epochs, epochAt, epochIdx, beliefW, trackMap, trackW, trackT, depthIdx, depthRange, depthPoint, dk: null, depthTotal: 0, planData, worldAt, append,
    get t0() { return run.t0; }, get t1() { return run.t1; } };
  X.dk = new Proxy(dk, { get: (o, ch) => ({ pos: o[ch].pos.a, gi: o[ch].gi.a, off: o[ch].off.a }) });
  append({ i0: 0, i1: f.t.length, plans: f.plans.map((x, k) => (x ? k : -1)).filter((k) => k >= 0) });
  return X;
}

// first tick whose time is after t - w (the start of "the last w seconds")
export const firstAfter = (t, ts) => { let lo = 0, hi = ts.length; while (lo < hi) { const m = (lo + hi) >> 1; if (ts[m] > t) hi = m; else lo = m + 1; } return lo; };
export const applyPose = apply;
export const idxAt = (t, ts) => { // last i with ts[i] <= t
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ts[m] <= t) lo = m; else hi = m - 1; }
  return lo;
};
