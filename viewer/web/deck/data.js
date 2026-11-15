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

// One run, prepared for drawing. It grows, wherever the new ticks are: append({i0, i1, plans, worlds}) prepares the ticks
// i0..i1-1 (a window of a long run, the next tick of a live one) and the plans and worlds that became available, and costs
// what it adds; nothing already prepared is touched. Per-tick arrays are indexed by the tick's number in the run (holes
// where it is not loaded); depth returns are packed per stretch of loaded ticks ("chunk"), tick by tick.
export const POINT_ID = 100000;     // a depth point's id: tick * POINT_ID + its place in the tick

export function prepareRun(run, f) {
  const epochs = [];
  const epochAt = (t) => { let e = epochs[0]; for (const x of epochs) if (x.from_t <= t) e = x; return e; };
  const epochIdx = [], beliefW = [], trackMap = [], trackW = [], trackT = [], depthIdx = [];
  const chunks = [];
  const planData = [];
  const worldCache = new Map();

  const newChunk = (i0) => {
    const c = { i0, i1: i0, last: -1, dk: {} };
    for (const ch of ['f', 'o', 'v', 'b']) c.dk[ch] = { pos: new Grow(Float32Array, 3), ids: new Grow(Float64Array, 1), off: new Grow(Int32Array, 1), n: 0 };
    chunks.push(c);
    return c;
  };

  const appendTicks = (a, b) => {
    const c = chunks.find((q) => q.i1 === a) || newChunk(a);
    for (const ch in c.dk) c.dk[ch].off.need(b - c.i0 + 1);
    for (let i = a; i < b; i++) {
      epochIdx[i] = epochs.indexOf(epochAt(f.t[i]));
      beliefW[i] = apply(epochs[epochIdx[i]].p, f.belief[i]);
      trackMap[i] = [f.belief[i][0], f.belief[i][1], 0];
      trackW[i] = [beliefW[i][0], beliefW[i][1], 0];
      trackT[i] = f.truth[i] && [f.truth[i][0], f.truth[i][1], 0];
      if (f.depth[i] && f.depth[i].length) c.last = i;
      depthIdx[i] = c.last;
      for (const ch in c.dk) c.dk[ch].off.a[i - c.i0] = c.dk[ch].n;
      (f.depth[i] || []).forEach((p, j) => {
        const K = c.dk['fovb'.includes(p[3]) ? p[3] : 'o'];
        K.pos.need(K.n + 1); K.ids.need(K.n + 1);
        K.pos.a.set(p.slice(0, 3), K.n * 3); K.ids.a[K.n++] = i * POINT_ID + j;
      });
    }
    for (const ch in c.dk) c.dk[ch].off.a[b - c.i0] = c.dk[ch].n;
    c.i1 = b;
  };

  const append = (range) => {
    for (let k = epochs.length; k < run.epochs.length; k++) epochs.push({ from_t: run.epochs[k].from_t, p: run.epochs[k].map_to_world, mat: matrix(run.epochs[k].map_to_world) });
    for (const [a, b] of range.ranges ?? [[range.i0, range.i1]]) if (b > a) appendTicks(a, b);
    for (const k of range.plans || []) if (f.plans[k] && !planData[k]) planData[k] = [{ path: f.plans[k].path.map(([x, y]) => [x, y, 0]) }];
  };

  // the points of one kind of a chunk in ticks a..b, as deck.gl binary attributes; base maps a layer index back to ids
  const depthRange = (ci, ch, a, b) => {
    const c = chunks[ci];
    if (!c || a < 0) return null;
    const lo = Math.max(a, c.i0), hi = Math.min(b, c.i1 - 1);
    if (hi < lo) return null;
    const { pos, off } = c.dk[ch], l = off.a[lo - c.i0], h = off.a[hi - c.i0 + 1];
    return { base: l, data: { length: h - l, attributes: { getPosition: { value: pos.a.subarray(l * 3, h * 3), size: 3 } } } };
  };
  const depthId = (ci, ch, k) => chunks[ci].dk[ch].ids.a[k];
  const depthPoint = (id) => {
    const tick = Math.floor(id / POINT_ID), p = f.depth[tick]?.[id % POINT_ID];
    return p ? { p: p.slice(0, 3), kind: p[3], tick } : null;
  };
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
  const X = { run, f, t: f.t, epochs, epochAt, epochIdx, beliefW, trackMap, trackW, trackT, depthIdx, chunks, depthRange, depthId, depthPoint, planData, worldAt, append,
    get t0() { return run.t0; }, get t1() { return run.t1; } };
  append({ ranges: f.ranges.map((r) => [...r]), plans: f.plans.map((x, k) => (x ? k : -1)).filter((k) => k >= 0) });
  return X;
}

export const applyPose = apply;
