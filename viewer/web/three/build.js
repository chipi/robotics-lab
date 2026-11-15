import * as THREE from 'three';

export const C = {
  belief: 0x4682ff, truth: 0x28b45a, plan: 0xe6b400, obst: 0xff9600, hazard: 0xe600e6,
  depth: { f: 0x3cc85a, o: 0xe63228, v: 0x3c78e6, b: 0xe600e6 },
  occ: 0x505050, free: 0xcdeccd, x: 0xe03030, y: 0x30b030, z: 0x3060e0, box: 0x8a8a96, grid: 0xdadae0, rel: 0x222222,
  boxFill: [0x8a8a96, 0.16],
};

// the page's theme tokens (shell palette, CSS hex strings) -> the colours the objects are built with
export function setPalette(p) {
  const h = (k) => new THREE.Color(p[k]).getHex();
  const bf = p['box-fill'];                                    // #rrggbbaa
  C.boxFill = [new THREE.Color('#' + bf.slice(1, 7)).getHex(), parseInt(bf.slice(7, 9) || 'ff', 16) / 255];
  Object.assign(C, {
    belief: h('c-belief'), truth: h('c-truth'), plan: h('c-plan'), obst: h('c-obst'), hazard: h('c-drop'), occ: h('c-occ'), free: h('c-free'),
    x: h('c-x'), y: h('c-y'), z: h('c-z'), box: h('c-box'), grid: h('draw-grid'), rel: h('draw-rel'),
    depth: { f: h('c-floor'), o: h('c-ob'), v: h('c-over'), b: h('c-drop') },
  });
}
const col = (hex) => new THREE.Color(hex);
// everything but the faint fills is transparent, so it is drawn after them (renderOrder) and never tinted by them
const lineMat = (hex) => new THREE.LineBasicMaterial({ color: hex, transparent: true });
const dashMat = (hex) => new THREE.LineDashedMaterial({ color: hex, dashSize: 0.06, gapSize: 0.04, transparent: true });
const fillMat = (hex, opacity) => new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity, side: THREE.DoubleSide, depthTest: false, depthWrite: false });
const fillMesh = (tri, hex, opacity) => {
  const g = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(tri, 3));
  const m = new THREE.Mesh(g, fillMat(hex, opacity));
  m.renderOrder = -10; m.frustumCulled = false;
  return m;
};

// WebGL draws every line one pixel wide, so a polyline with a width (and dashes) is a strip of quads that a vertex
// shader widens in screen space; the width stays in pixels when zooming. range(i0, n) draws points i0 .. i0+n-1.
// RES is the size in pixels of the pane being drawn; the views set it before each pane.
export const RES = { value: new THREE.Vector2(1, 1) };
const THICK_VS = `
attribute vec3 pb; attribute vec2 corner; attribute vec2 dist;
uniform vec2 res; uniform float width;
varying float vD;
void main() {
  vec4 A = projectionMatrix * modelViewMatrix * vec4(position, 1.0), B = projectionMatrix * modelViewMatrix * vec4(pb, 1.0);
  vec2 sa = A.xy / A.w * res * 0.5, sb = B.xy / B.w * res * 0.5, d = sb - sa;
  float L = length(d); d = L > 1e-4 ? d / L : vec2(1.0, 0.0);
  vec2 off = (vec2(-d.y, d.x) * corner.y + d * (corner.x * 2.0 - 1.0)) * width * 0.5;
  vec4 P = mix(A, B, corner.x);
  gl_Position = vec4(P.xy + off / (res * 0.5) * P.w, P.zw);
  vD = mix(dist.x, dist.y, corner.x);
}`;
const THICK_FS = `
uniform vec3 color; uniform float dash, gap;
varying float vD;
void main() {
  if (dash > 0.0 && mod(vD, dash + gap) > dash) discard;
  gl_FragColor = vec4(color, 1.0);
  #include <colorspace_fragment>
}`;
class ThickLine extends THREE.Mesh {
  constructor(hex, width, dash = 0, gap = 0) {
    super(new THREE.BufferGeometry(), new THREE.ShaderMaterial({ vertexShader: THICK_VS, fragmentShader: THICK_FS, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { res: RES, width: { value: width }, color: { value: new THREE.Color(hex) }, dash: { value: dash }, gap: { value: gap } } }));
    this.frustumCulled = false;
    this.made = 0; this.cap = 0; this.acc = 0;
    this._grow(64);
  }
  _grow(cap) {
    const mk = (T, size, old) => { const a = new T(cap * size); if (old) a.set(old); return a; };
    this.P = mk(Float32Array, 12, this.P); this.Q = mk(Float32Array, 12, this.Q); this.K = mk(Float32Array, 8, this.K); this.D = mk(Float32Array, 8, this.D);
    this.idx = mk(Uint32Array, 6, this.idx);
    this.cap = cap;
    const g = this.geometry;
    g.setAttribute('position', new THREE.BufferAttribute(this.P, 3)); g.setAttribute('pb', new THREE.BufferAttribute(this.Q, 3));
    g.setAttribute('corner', new THREE.BufferAttribute(this.K, 2)); g.setAttribute('dist', new THREE.BufferAttribute(this.D, 2));
    g.setIndex(new THREE.BufferAttribute(this.idx, 1));
  }
  // the polyline is pos[0 .. n); only the segments not made yet are made (appending costs what it adds)
  set(pos, n) {
    const m = Math.max(0, n - 1), cx = [0, 0, 1, 1], cy = [-1, 1, 1, -1];
    if (m > this.cap) this._grow(Math.max(m, this.cap * 2));
    const { P, Q, K, D, idx } = this;
    for (let k = this.made; k < m; k++) {
      const len = Math.hypot(pos[k * 3 + 3] - pos[k * 3], pos[k * 3 + 4] - pos[k * 3 + 1], pos[k * 3 + 5] - pos[k * 3 + 2]);
      for (let c = 0; c < 4; c++) {
        const v = k * 4 + c;
        P.set(pos.subarray(k * 3, k * 3 + 3), v * 3); Q.set(pos.subarray(k * 3 + 3, k * 3 + 6), v * 3);
        K[v * 2] = cx[c]; K[v * 2 + 1] = cy[c]; D[v * 2] = this.acc; D[v * 2 + 1] = this.acc + len;
      }
      this.acc += len;
      for (let q = 0; q < 6; q++) idx[k * 6 + q] = k * 4 + [0, 1, 2, 0, 2, 3][q];
    }
    this.made = Math.max(this.made, m);
    const g = this.geometry;
    for (const name of ['position', 'pb', 'corner', 'dist']) g.getAttribute(name).needsUpdate = true;
    g.index.needsUpdate = true;
  }
  setWidth(w) { this.material.uniforms.width.value = w; }
  range(i0, n) { this.geometry.setDrawRange(i0 * 6, Math.max(0, n - 1) * 6); }
  raycast() {}
}

// a typed array that doubles when it is full: what a run being appended to is packed into
class Grow {
  constructor(T, stride, cap = 512) { this.T = T; this.s = stride; this.a = new T(cap * stride); }
  need(n) {
    if (n * this.s <= this.a.length) return;
    const b = new this.T(Math.max(n, (this.a.length / this.s) * 2) * this.s);
    b.set(this.a); this.a = b;
  }
}
// the attribute follows its array: replaced when the array was reallocated, else marked for upload
function sync(geom, name, G, size) {
  const at = geom.getAttribute(name);
  if (!at || at.array !== G.a) geom.setAttribute(name, new THREE.BufferAttribute(G.a, size)); else at.needsUpdate = true;
  geom.boundingSphere = null;
}

function segs(pos, hex) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.LineSegments(g, lineMat(hex));
}

function dashed(pos, hex) {
  const l = segs(pos, hex);
  l.material = dashMat(hex);
  l.computeLineDistances();
  return l;
}

// the top and the four sides of a box, as triangles (the bottom sits on the floor)
function boxFaces(out, b, z0, z1) {
  const c = Math.cos(b.yaw), s = Math.sin(b.yaw);
  const p = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([i, j]) => {
    const x = i * b.hx, y = j * b.hy;
    return [b.cx + c * x - s * y, b.cy + s * x + c * y];
  });
  out.push(...p[0], z1, ...p[1], z1, ...p[2], z1, ...p[0], z1, ...p[2], z1, ...p[3], z1);
  for (let k = 0; k < 4; k++) {
    const [ax, ay] = p[k], [bx, by] = p[(k + 1) % 4];
    out.push(ax, ay, z0, bx, by, z0, bx, by, z1, ax, ay, z0, bx, by, z1, ax, ay, z1);
  }
}

function boxEdges(out, b, z0, z1) {
  const c = Math.cos(b.yaw), s = Math.sin(b.yaw);
  const p = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([i, j]) => {
    const x = i * b.hx, y = j * b.hy;
    return [b.cx + c * x - s * y, b.cy + s * x + c * y];
  });
  for (let k = 0; k < 4; k++) {
    const [ax, ay] = p[k], [bx, by] = p[(k + 1) % 4];
    out.push(ax, ay, z0, bx, by, z0, ax, ay, z1, bx, by, z1, ax, ay, z0, ax, ay, z1);
  }
}

// The scene in the world frame: boxes cut away at `cut` metres, stairs and the hazard in magenta.
// Two groups (the streams scene.boxes and scene.hazards) under one.
export function buildScene(sc, cut = 0.5) {
  const g = new THREE.Group(), boxes = new THREE.Group(), hazards = new THREE.Group();
  const gray = [], mag = [], hz = [], grayFill = [], magFill = [];
  for (const b of sc.boxes) {
    if (b.z0 >= cut) continue;
    const stair = b.name.startsWith('stair');
    boxEdges(stair ? mag : gray, b, b.z0, Math.min(b.z1, cut));
    boxFaces(stair ? magFill : grayFill, b, b.z0, Math.min(b.z1, cut));
  }
  const fill = [];
  for (const h of sc.hazards) {
    const r = [[h.x0, h.y0], [h.x1, h.y0], [h.x1, h.y1], [h.x0, h.y1]];
    for (let k = 0; k < 4; k++) {
      const [ax, ay] = r[k], [bx, by] = r[(k + 1) % 4];
      hz.push(ax, ay, 0, bx, by, 0, ax, ay, -h.depth, bx, by, -h.depth, ax, ay, 0, ax, ay, -h.depth);
    }
    const q = [0, 1, 2, 0, 2, 3].map((k) => [...r[k], 0.002]);
    fill.push(...q.flat());
  }
  boxes.add(fillMesh(grayFill, C.boxFill[0], C.boxFill[1]), fillMesh(magFill, C.hazard, 0.12), segs(gray, C.box), segs(mag, C.hazard));
  hazards.add(dashed(hz, C.hazard));
  const fg = new THREE.BufferGeometry();
  fg.setAttribute('position', new THREE.Float32BufferAttribute(fill, 3));
  const hf = new THREE.Mesh(fg, fillMat(C.hazard, 0.12));
  hf.renderOrder = -10; hf.frustumCulled = false;
  hazards.add(hf);
  g.add(boxes, hazards);
  g.fills = { 'fill.boxes': [boxes.children[0], boxes.children[1]], 'fill.hazards': [hf] };
  g.parts = { 'scene.boxes': boxes, 'scene.hazards': hazards };
  return g;
}

function robotMesh(r, h, hex) {
  const g = new THREE.Group();
  const cyl = new THREE.CylinderGeometry(r, r, h, 24).rotateX(Math.PI / 2).translate(0, 0, h / 2);
  g.add(new THREE.Mesh(cyl, new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.25, depthWrite: false })));
  g.add(new THREE.LineSegments(new THREE.EdgesGeometry(cyl, 30), lineMat(hex)));
  const head = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, h, r * 1.8, 0, h], 3));
  g.add(new THREE.Line(head, lineMat(hex)));
  const dot = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, h], 3));
  g.add(new THREE.Points(dot, new THREE.PointsMaterial({ color: hex, size: 7, sizeAttenuation: false })));
  return g;
}

function lineObj(pos, hex) {
  const g = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const l = new THREE.Line(g, lineMat(hex));
  l.frustumCulled = false;
  return l;
}

function pointsObj(pos, colors, size) {
  const g = new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const m = { size, sizeAttenuation: false, transparent: true };
  if (colors) { g.setAttribute('color', new THREE.BufferAttribute(colors, 3)); m.vertexColors = true; }
  const p = new THREE.Points(g, new THREE.PointsMaterial(m));
  p.frustumCulled = false;
  return p;
}

const epochAt = (run, t) => {
  let e = run.epochs[0];
  for (const x of run.epochs) if (x.from_t <= t) e = x;
  return e.map_to_world;
};

export const DEPTH_KINDS = [['f', 'sensors.depth.floor'], ['o', 'sensors.depth.obstacle'], ['v', 'sensors.depth.overhead'], ['b', 'sensors.depth.below']];
export const TAIL_S = 1.0;

// One run's drawable layers, one object per stream id (R.obj). `world` applies the epoch in force
// (map -> world); otherwise the robot's own map frame is drawn as is (the data view). The run is packed
// into buffers that grow: append({i0, i1, plans, worlds}) adds the ticks i0..i1-1 and the plans and
// worlds that became available, and costs what it adds; update() only moves draw ranges and poses.
// Every point keeps the tick it came from so a click can say which record it is.
export function fullRange(fr) {
  const have = (arr) => arr.map((x, k) => (x ? k : -1)).filter((k) => k >= 0);
  return { i0: 0, i1: fr.t.length, plans: have(fr.plans), worlds: have(fr.worlds) };
}

export function buildRun(run, fr, world) {
  const r = run.robot.radius, h = run.robot.height;
  let n = 0;                                          // ticks built
  const tf = (t) => {
    if (!world) return (x, y) => [x, y, 0];
    const [ox, oy, yaw] = epochAt(run, t), c = Math.cos(yaw), s = Math.sin(yaw);
    return (x, y) => [ox + c * x - s * y, oy + s * x + c * y, yaw];
  };
  const L = { group: new THREE.Group(), obj: {}, pick: {} };
  const add = (id, o) => { L.obj[id] = o; L.group.add(o); return o; };
  // first tick at or after time x
  const firstAt = (x) => {
    let lo = 0, hi = n;
    while (lo < hi) { const m = (lo + hi) >> 1; if (fr.t[m] < x) lo = m + 1; else hi = m; }
    return lo;
  };

  const posG = new Grow(Float32Array, 3), trkG = new Grow(Float32Array, 3);
  const bTrack = add('belief.track', new ThickLine(C.belief, 2)), bRobot = add('belief.pose', robotMesh(r, h, C.belief));
  bRobot.position.z = 0.02;
  bRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 0 }); });
  Object.defineProperty(L, 'pose', { get: () => posG.a });

  let tTrack, tRobot, rel = null, tpG = null, trG = null, lastTruth = null, firstTruthAt = -1;
  if (world) {
    tpG = new Grow(Float32Array, 3); trG = new Grow(Float32Array, 3);
    tTrack = add('truth.track', new ThickLine(C.truth, 2)); tRobot = add('truth.pose', robotMesh(r, h, C.truth)); tRobot.position.z = 0.02;
    tRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 1 }); });
    Object.defineProperty(L, 'tpose', { get: () => tpG.a });
    rel = add('rel.belief_truth', lineObj(new Float32Array(6), C.rel));
  }

  // depth: one buffer per kind; tick i's returns of a kind are [cum[i], cum[i+1]) in it, so "at t",
  // "last N s" and "all up to t" are each one draw range.
  const kindOf = (k) => (k in { f: 1, o: 1, v: 1, b: 1 } ? k : 'o');
  const D = {};
  for (const [k, id] of DEPTH_KINDS) {
    D[k] = { id, pos: new Grow(Float32Array, 3), flat: new Grow(Int32Array, 1), tick: new Grow(Int32Array, 1), cum: new Grow(Int32Array, 1), o: 0 };
    const pts = add(id, pointsObj(D[k].pos.a, null, 4));
    pts.material.color.set(C.depth[k]);
    pts.geometry.setDrawRange(0, 0);
    pts.userData.pick = (hit) => ({ kind: 'depth', index: D[k].flat.a[hit.index] });
  }
  const dLast = new Grow(Int32Array, 1);
  const flatOf = [];  // flat index (file order) -> [kind, buffer index]
  let last = -1;
  L.depth = { D, flatOf };

  const psG = new Grow(Float32Array, 3), pStart = [], pCount = [];
  let psN = 0;
  const plan = add('plan.path', new ThickLine(C.plan, 2, 0.07, 0.05));

  // the world model: grid cells as quads in one geometry, obstacles and drops as points, all with
  // per-world ranges. (InstancedMesh has no offset into its instances, so ranges on plain
  // geometry it is.)
  const qP = new Grow(Float32Array, 3, 4096), qC = new Grow(Float32Array, 3, 4096), oG = new Grow(Float32Array, 3, 64), dG = new Grow(Float32Array, 3, 64);
  let qN = 0, oN = 0, dN = 0;
  const quadWorld = [], quadK = [], wCell = [], oRange = [], dRange = [];
  const cg = new THREE.BufferGeometry();
  cg.setAttribute('position', new THREE.BufferAttribute(qP.a, 3)); cg.setAttribute('color', new THREE.BufferAttribute(qC.a, 3));
  cg.setDrawRange(0, 0);
  const cells = add('world.grid', new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })));
  cells.frustumCulled = false;
  cells.userData.pick = (hit) => { const q = hit.faceIndex >> 1; return { kind: 'cell', index: quadK[q], world: quadWorld[q] }; };
  const obst = add('world.obstacles', pointsObj(oG.a, null, 5)), drops = add('world.drops', pointsObj(dG.a, null, 6));
  obst.material.color.set(C.obst); drops.material.color.set(C.hazard);

  const extendTicks = (a, b) => {
    posG.need(b); trkG.need(b); dLast.need(b); for (const k in D) D[k].cum.need(b + 1);
    if (world) { tpG.need(b); trG.need(b); }
    for (let i = a; i < b; i++) {
      const [x, y, yaw] = fr.belief[i], [wx, wy, ey] = tf(fr.t[i])(x, y);
      posG.a.set([wx, wy, yaw + ey], i * 3);
      trkG.a.set([wx, wy, 0.01], i * 3);
      if (world) {
        const tr = fr.truth[i];
        if (tr && firstTruthAt < 0) {                      // ticks before the first truth wear it
          firstTruthAt = i;
          for (let j = 0; j < i; j++) { tpG.a.set(tr, j * 3); trG.a.set([tr[0], tr[1], 0.01], j * 3); }
        }
        lastTruth = tr || lastTruth || [0, 0, 0];
        tpG.a.set(lastTruth, i * 3);
        trG.a.set([lastTruth[0], lastTruth[1], 0.01], i * 3);
      }
      for (const k in D) D[k].cum.a[i] = D[k].o;
      const d = fr.depth[i];
      if (d) {
        last = i;
        const f = tf(fr.t[i]);
        for (const [x2, y2, z, kk] of d) {
          const k = kindOf(kk), B = D[k], [dx, dy] = f(x2, y2);
          B.pos.need(B.o + 1); B.flat.need(B.o + 1); B.tick.need(B.o + 1);
          B.pos.a.set([dx, dy, z], B.o * 3);
          B.flat.a[B.o] = flatOf.length; B.tick.a[B.o] = i;
          flatOf.push([k, B.o]);
          B.o++;
        }
      }
      dLast.a[i] = last;
    }
    for (const k in D) D[k].cum.a[b] = D[k].o;
    for (const [k, id] of DEPTH_KINDS) sync(L.obj[id].geometry, 'position', D[k].pos, 3);
    bTrack.set(trkG.a, b);
    if (world) tTrack.set(trG.a, b);
  };

  const extendPlans = (ks) => {
    for (const k of ks) {
      const p = fr.plans[k];
      if (!p || pStart[k] !== undefined) continue;
      pStart[k] = psN; pCount[k] = p.path.length;
      const f = tf(p.t);
      psG.need(psN + p.path.length);
      for (const [x, y] of p.path) { psG.a.set([...f(x, y).slice(0, 2), 0.012], psN * 3); psN++; }
    }
    plan.set(psG.a, psN);
  };

  const extendWorlds = (ks) => {
    for (const wi of ks) {
      const w = fr.worlds[wi];
      if (!w || wCell[wi] !== undefined) continue;
      const f = tf(w.t), g = w.grid, s0 = qN;
      qP.need(qN + g.cells.length * 6); qC.need(qN + g.cells.length * 6);
      for (let k = 0; k < g.cells.length; k++) {
        const ch = g.cells[k];
        if (ch === '?') continue;
        const i = k % g.w, j = (k / g.w) | 0;
        const x0 = g.origin[0] + i * g.res, y0 = g.origin[1] + j * g.res;
        const q = [[x0, y0], [x0 + g.res, y0], [x0 + g.res, y0 + g.res], [x0, y0 + g.res]].map(([x, y]) => f(x, y));
        const c = col(ch === '#' ? C.occ : C.free);
        for (const m of [0, 1, 2, 0, 2, 3]) { qP.a.set([q[m][0], q[m][1], 0.001], qN * 3); qC.a.set([c.r, c.g, c.b], qN * 3); qN++; }
        quadWorld.push(wi); quadK.push(k);
      }
      wCell[wi] = [s0, qN - s0];
      oG.need(oN + w.obstacles.length); dG.need(dN + w.drops.length);
      oRange[wi] = [oN, w.obstacles.length];
      for (const [x, y] of w.obstacles) { oG.a.set([...f(x, y).slice(0, 2), 0.03], oN * 3); oN++; }
      dRange[wi] = [dN, w.drops.length];
      for (const [x, y] of w.drops) { dG.a.set([...f(x, y).slice(0, 2), 0.03], dN * 3); dN++; }
    }
    sync(cg, 'position', qP, 3); sync(cg, 'color', qC, 3);
    sync(obst.geometry, 'position', oG, 3); sync(drops.geometry, 'position', dG, 3);
  };

  L.append = (range) => {
    if (range.i1 > n) { extendTicks(Math.max(range.i0, n), range.i1); n = range.i1; }
    if (range.plans?.length) extendPlans(range.plans);
    if (range.worlds?.length) extendWorlds(range.worlds);
  };

  // where a record sits in this run's frame: [x, y, z, tick] or null
  L.locate = (kind, index, wi) => {
    if (kind === 'depth') {
      const fo = L.depth.flatOf[index];
      if (!fo) return null;
      const B = D[fo[0]], o = fo[1];
      return { stream: B.id, dk: fo[0], p: [B.pos.a[o * 3], B.pos.a[o * 3 + 1], B.pos.a[o * 3 + 2]], tick: B.tick.a[o] };
    }
    if (kind === 'cell') {
      const g = fr.worlds[wi]?.grid;
      if (!g || index >= g.cells.length) return null;
      const f = tf(fr.worlds[wi].t), i = index % g.w, j = (index / g.w) | 0;
      const [x, y] = f(g.origin[0] + (i + 0.5) * g.res, g.origin[1] + (j + 0.5) * g.res);
      return { stream: 'world.grid', p: [x, y, 0], cell: g.cells[index], res: g.res, wt: fr.worlds[wi].t };
    }
    return null;
  };

  // cfg(id) -> {mode: 'at'|'window'|'upto', n: seconds}
  L.update = (i, t, cfg, size) => {
    const pose = posG.a, tpose = tpG?.a;
    bRobot.position.set(pose[i * 3], pose[i * 3 + 1], 0.02);
    bRobot.rotation.z = pose[i * 3 + 2];
    const trackRange = (id) => {
      const { mode, n: w } = cfg(id);
      if (mode === 'upto') return [0, i + 1];
      const i0 = Math.min(firstAt(t - (mode === 'window' ? w : TAIL_S)), i);
      return [i0, i - i0 + 1];
    };
    bTrack.range(...trackRange('belief.track')); bTrack.setWidth(size('belief.track'));
    if (world) {
      tRobot.position.set(tpose[i * 3], tpose[i * 3 + 1], 0.02);
      tRobot.rotation.z = tpose[i * 3 + 2];
      tTrack.range(...trackRange('truth.track')); tTrack.setWidth(size('truth.track'));
      const a = rel.geometry.attributes.position;
      a.array.set([pose[i * 3], pose[i * 3 + 1], 0.05, tpose[i * 3], tpose[i * 3 + 1], 0.05]);
      a.needsUpdate = true;
    }
    const d = dLast.a[i];
    for (const [k, id] of DEPTH_KINDS) {
      const { mode, n: w } = cfg(id), B = D[k], cum = B.cum.a;
      let rg;
      if (mode === 'upto') rg = [0, cum[i + 1]];
      else if (mode === 'window') { const i0 = Math.min(firstAt(t - w), i); rg = [cum[i0], cum[i + 1] - cum[i0]]; }
      else rg = d < 0 ? [0, 0] : [cum[d], cum[d + 1] - cum[d]];
      L.obj[id].geometry.setDrawRange(rg[0], rg[1]);
      L.obj[id].material.size = size(id);
    }
    const pi = fr.plan_at[i];
    plan.setWidth(size('plan.path'));
    plan.range(...(pi >= 0 && pStart[pi] !== undefined ? [pStart[pi], pCount[pi]] : [0, 0]));
    const wi = fr.world_at[i], none = [0, 0];
    cells.geometry.setDrawRange(...(wi >= 0 && wCell[wi] ? wCell[wi] : none));
    obst.geometry.setDrawRange(...(wi >= 0 && oRange[wi] ? oRange[wi] : none));
    drops.geometry.setDrawRange(...(wi >= 0 && dRange[wi] ? dRange[wi] : none));
    obst.material.size = size('world.obstacles'); drops.material.size = size('world.drops');
  };
  L.append(fullRange(fr));
  return L;
}
