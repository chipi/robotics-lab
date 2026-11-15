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
  constructor(pos, hex, width, dash = 0, gap = 0) {
    const n = pos.length / 3, m = Math.max(0, n - 1), P = new Float32Array(m * 12), Q = new Float32Array(m * 12), K = new Float32Array(m * 8), D = new Float32Array(m * 8);
    const idx = new Uint32Array(m * 6), cx = [0, 0, 1, 1], cy = [-1, 1, 1, -1];
    let acc = 0;
    for (let k = 0; k < m; k++) {
      const len = Math.hypot(pos[k * 3 + 3] - pos[k * 3], pos[k * 3 + 4] - pos[k * 3 + 1], pos[k * 3 + 5] - pos[k * 3 + 2]);
      for (let c = 0; c < 4; c++) {
        const v = k * 4 + c;
        P.set(pos.subarray(k * 3, k * 3 + 3), v * 3); Q.set(pos.subarray(k * 3 + 3, k * 3 + 6), v * 3);
        K[v * 2] = cx[c]; K[v * 2 + 1] = cy[c]; D[v * 2] = acc; D[v * 2 + 1] = acc + len;
      }
      acc += len;
      idx.set([0, 1, 2, 0, 2, 3].map((q) => k * 4 + q), k * 6);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(P, 3)); g.setAttribute('pb', new THREE.BufferAttribute(Q, 3));
    g.setAttribute('corner', new THREE.BufferAttribute(K, 2)); g.setAttribute('dist', new THREE.BufferAttribute(D, 2));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    super(g, new THREE.ShaderMaterial({ vertexShader: THICK_VS, fragmentShader: THICK_FS, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      uniforms: { res: RES, width: { value: width }, color: { value: new THREE.Color(hex) }, dash: { value: dash }, gap: { value: gap } } }));
    this.frustumCulled = false;
  }
  setWidth(w) { this.material.uniforms.width.value = w; }
  range(i0, n) { this.geometry.setDrawRange(i0 * 6, Math.max(0, n - 1) * 6); }
  raycast() {}
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
// (map -> world); otherwise the robot's own map frame is drawn as is (the data view). Everything is
// packed into buffers here; update() only moves draw ranges and poses. Every point keeps the tick
// it came from so a click can say which record it is.
export function buildRun(run, fr, world) {
  const n = fr.t.length, r = run.robot.radius, h = run.robot.height;
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

  const pose = new Float32Array(n * 3), track = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const [x, y, yaw] = fr.belief[i], [wx, wy, ey] = tf(fr.t[i])(x, y);
    pose.set([wx, wy, yaw + ey], i * 3);
    track.set([wx, wy, 0.01], i * 3);
  }
  L.pose = pose;
  const bTrack = add('belief.track', new ThickLine(track, C.belief, 2)), bRobot = add('belief.pose', robotMesh(r, h, C.belief));
  bRobot.position.z = 0.02;
  bRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 0 }); });

  let tTrack, tRobot, tpose = null, rel = null;
  if (world) {
    tpose = new Float32Array(n * 3);
    const tr = new Float32Array(n * 3);
    let last = fr.truth.find(Boolean) || [0, 0, 0];
    for (let i = 0; i < n; i++) {
      last = fr.truth[i] || last;
      tpose.set(last, i * 3);
      tr.set([last[0], last[1], 0.01], i * 3);
    }
    tTrack = add('truth.track', new ThickLine(tr, C.truth, 2)); tRobot = add('truth.pose', robotMesh(r, h, C.truth)); tRobot.position.z = 0.02;
    tRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 1 }); });
    L.tpose = tpose;
    rel = add('rel.belief_truth', lineObj(new Float32Array(6), C.rel));
  }

  // depth: one buffer per kind; tick i's returns of a kind are [cum[i], cum[i+1]) in it, so "at t",
  // "last N s" and "all up to t" are each one draw range.
  const cnt = { f: 0, o: 0, v: 0, b: 0 };
  const kindOf = (k) => (k in cnt ? k : 'o');
  for (const d of fr.depth) if (d) for (const p of d) cnt[kindOf(p[3])]++;
  const D = {};
  for (const [k, id] of DEPTH_KINDS) {
    D[k] = { id, pos: new Float32Array(cnt[k] * 3), flat: new Int32Array(cnt[k]), tick: new Int32Array(cnt[k]), cum: new Int32Array(n + 1), o: 0 };
  }
  const dLast = new Int32Array(n);
  const flatOf = [];  // flat index (file order) -> [kind, buffer index]
  let last = -1;
  for (let i = 0; i < n; i++) {
    for (const k in D) D[k].cum[i] = D[k].o;
    const d = fr.depth[i];
    if (d) {
      last = i;
      const f = tf(fr.t[i]);
      for (const [x, y, z, kk] of d) {
        const k = kindOf(kk), B = D[k], [wx, wy] = f(x, y);
        B.pos.set([wx, wy, z], B.o * 3);
        B.flat[B.o] = flatOf.length; B.tick[B.o] = i;
        flatOf.push([k, B.o]);
        B.o++;
      }
    }
    dLast[i] = last;
  }
  for (const k in D) D[k].cum[n] = D[k].o;
  for (const [k, id] of DEPTH_KINDS) {
    const pts = add(id, pointsObj(D[k].pos, null, 4));
    pts.material.color.set(C.depth[k]);
    pts.userData.pick = (hit) => ({ kind: 'depth', index: D[k].flat[hit.index] });
  }
  L.depth = { D, flatOf };

  const ps = [], pStart = [], pCount = [];
  for (const p of fr.plans) {
    pStart.push(ps.length / 3); pCount.push(p.path.length);
    const f = tf(p.t);
    for (const [x, y] of p.path) ps.push(...f(x, y).slice(0, 2), 0.012);
  }
  const plan = add('plan.path', new ThickLine(new Float32Array(ps), C.plan, 2, 0.07, 0.05));

  // the world model: grid cells as quads in one geometry, obstacles and drops as points, all with
  // per-world ranges. (InstancedMesh has no offset into its instances, so ranges on plain
  // geometry it is.)
  const cq = [], cc = [], quadWorld = [], quadK = [], wCell = [], op = [], oRange = [], dp = [], dRange = [];
  for (const [wi, w] of fr.worlds.entries()) {
    const f = tf(w.t), g = w.grid, s = cq.length / 3;
    for (let k = 0; k < g.cells.length; k++) {
      const ch = g.cells[k];
      if (ch === '?') continue;
      const i = k % g.w, j = (k / g.w) | 0;
      const x0 = g.origin[0] + i * g.res, y0 = g.origin[1] + j * g.res;
      const q = [[x0, y0], [x0 + g.res, y0], [x0 + g.res, y0 + g.res], [x0, y0 + g.res]].map(([x, y]) => f(x, y));
      const c = col(ch === '#' ? C.occ : C.free);
      for (const m of [0, 1, 2, 0, 2, 3]) { cq.push(q[m][0], q[m][1], 0.001); cc.push(c.r, c.g, c.b); }
      quadWorld.push(wi); quadK.push(k);
    }
    wCell.push([s, cq.length / 3 - s]);
    oRange.push([op.length / 3, w.obstacles.length]);
    for (const [x, y] of w.obstacles) op.push(...f(x, y).slice(0, 2), 0.03);
    dRange.push([dp.length / 3, w.drops.length]);
    for (const [x, y] of w.drops) dp.push(...f(x, y).slice(0, 2), 0.03);
  }
  const cg = new THREE.BufferGeometry();
  cg.setAttribute('position', new THREE.Float32BufferAttribute(cq, 3));
  cg.setAttribute('color', new THREE.Float32BufferAttribute(cc, 3));
  const cells = add('world.grid', new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })));
  cells.frustumCulled = false;
  cells.userData.pick = (hit) => { const q = hit.faceIndex >> 1; return { kind: 'cell', index: quadK[q], world: quadWorld[q] }; };
  const obst = add('world.obstacles', pointsObj(new Float32Array(op), null, 5)), drops = add('world.drops', pointsObj(new Float32Array(dp), null, 6));
  obst.material.color.set(C.obst); drops.material.color.set(C.hazard);

  // where a record sits in this run's frame: [x, y, z, tick] or null
  L.locate = (kind, index, wi) => {
    if (kind === 'depth') {
      const fo = L.depth.flatOf[index];
      if (!fo) return null;
      const B = D[fo[0]], o = fo[1];
      return { stream: B.id, dk: fo[0], p: [B.pos[o * 3], B.pos[o * 3 + 1], B.pos[o * 3 + 2]], tick: B.tick[o] };
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
    const d = dLast[i];
    for (const [k, id] of DEPTH_KINDS) {
      const { mode, n: w } = cfg(id), B = D[k];
      let r;
      if (mode === 'upto') r = [0, B.cum[i + 1]];
      else if (mode === 'window') { const i0 = Math.min(firstAt(t - w), i); r = [B.cum[i0], B.cum[i + 1] - B.cum[i0]]; }
      else r = d < 0 ? [0, 0] : [B.cum[d], B.cum[d + 1] - B.cum[d]];
      L.obj[id].geometry.setDrawRange(r[0], r[1]);
      L.obj[id].material.size = size(id);
    }
    const pi = fr.plan_at[i];
    plan.setWidth(size('plan.path'));
    plan.range(...(pi >= 0 ? [pStart[pi], pCount[pi]] : [0, 0]));
    const wi = fr.world_at[i], none = [0, 0];
    cells.geometry.setDrawRange(...(wi >= 0 ? wCell[wi] : none));
    obst.geometry.setDrawRange(...(wi >= 0 ? oRange[wi] : none));
    drops.geometry.setDrawRange(...(wi >= 0 ? dRange[wi] : none));
    obst.material.size = size('world.obstacles'); drops.material.size = size('world.drops');
  };
  return L;
}
