import * as THREE from 'three';
import { gapCells } from '../shell/gaps.js';
import { SEMANTIC, LANDMARK_MIN } from '../shell/semantic.js';

export const C = {
  belief: 0x4682ff, truth: 0x28b45a, plan: 0xe6b400, obst: 0xff9600, hazard: 0xe600e6,
  depth: { f: 0x3cc85a, o: 0xe63228, v: 0x3c78e6, b: 0xe600e6 },
  occ: 0x505050, free: 0xcdeccd, x: 0xe03030, y: 0x30b030, z: 0x3060e0, box: 0x8a8a96, grid: 0xdadae0, rel: 0x222222,
  boxFill: [0x8a8a96, 0.16], gap: 0xff8c1a, fog: 0x9aa3b0, error: 0xe05a4f, warn: 0xe0a030, dim: 0x9a9da6,
  ...SEMANTIC,                                 // the semantic map's (RFC-0016): not themed, the legend uses the same
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
    error: h('error'), warn: h('warn'), dim: h('text-dim'),
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
  // a perspective camera (the eye) stands where lines begin: the part of a segment behind it is cut at the near side, not projected
  if (A.w < 0.02 && B.w < 0.02) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  if (A.w < 0.02) A = mix(A, B, (0.02 - A.w) / (B.w - A.w));
  if (B.w < 0.02) B = mix(B, A, (0.02 - B.w) / (A.w - B.w));
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
  // segment k joins points k and k+1 of pos: made when both are there, wherever they are in the run
  seg(pos, k) {
    if (k >= this.cap) this._grow(Math.max(k + 1, this.cap * 2));
    const { P, Q, K, D, idx } = this, cx = [0, 0, 1, 1], cy = [-1, 1, 1, -1];
    for (let c = 0; c < 4; c++) {
      const v = k * 4 + c;
      P.set(pos.subarray(k * 3, k * 3 + 3), v * 3); Q.set(pos.subarray(k * 3 + 3, k * 3 + 6), v * 3);
      K[v * 2] = cx[c]; K[v * 2 + 1] = cy[c]; D[v * 2] = 0; D[v * 2 + 1] = 0;
    }
    for (let q = 0; q < 6; q++) idx[k * 6 + q] = k * 4 + [0, 1, 2, 0, 2, 3][q];
  }
  flush() {
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
    const r = h.corners;
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
  // the real hazards' rims again, over the robot's model (RFC-0013): drawn without depth, after the layers that tint the floor
  const over = new THREE.Group();
  for (const h of sc.hazards) {
    const t = new ThickLine(C.hazard, 2.5, 0.07, 0.05), r = h.corners;
    t.material.depthTest = false; t.renderOrder = 8;
    t.set(new Float32Array([...r, r[0]].flatMap(([x, y]) => [x, y, 0.004])), r.length + 1);
    t.range(0, r.length + 1);
    over.add(t);
  }
  g.add(boxes, hazards, over);
  g.fills = { 'fill.boxes': [boxes.children[0], boxes.children[1]], 'fill.hazards': [hf] };
  g.parts = { 'scene.boxes': boxes, 'scene.hazards': hazards, 'hazards.top': over };
  return g;
}

// a text label as a sprite that faces the camera: a dark pill with the text in white, which reads on either theme. Its size is fixed on the
// screen (LABEL_PX tall, whatever the zoom or the distance), set at each draw for the pane being drawn: sized in metres it was a few pixels
// high at the default view's 11 m.
const LABEL_PX = 20, _lp = new THREE.Vector3();
function labelSprite(text, hex) {
  const c = document.createElement('canvas'), g = c.getContext('2d'), px = 28;
  g.font = `600 ${px}px ui-monospace, monospace`;
  const w = Math.ceil(g.measureText(text).width) + 20;
  c.width = w; c.height = px + 14;
  g.font = `600 ${px}px ui-monospace, monospace`;
  g.fillStyle = 'rgba(10,14,20,0.78)'; g.beginPath(); g.roundRect(0, 0, c.width, c.height, 8); g.fill();
  g.strokeStyle = '#' + col(hex).getHexString(); g.lineWidth = 3; g.stroke();
  g.fillStyle = '#fff'; g.textBaseline = 'middle'; g.fillText(text, 10, c.height / 2 + 1);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false, depthWrite: false }));
  s.scale.set((0.15 * c.width) / c.height, 0.15, 1);
  s.renderOrder = 9; s.userData.text = text;
  const aspect = c.width / c.height;
  s.onBeforeRender = (renderer, scene, cam) => {
    const metresPerPx = cam.isOrthographicCamera ? (cam.top - cam.bottom) / cam.zoom / RES.value.y
      : (2 * Math.tan((cam.fov * Math.PI) / 360) * Math.max(0.01, -s.getWorldPosition(_lp).applyMatrix4(cam.matrixWorldInverse).z)) / RES.value.y;
    const h = LABEL_PX * metresPerPx;
    s.scale.set(h * aspect, h, 1);
    s.updateMatrixWorld();                      // the sprite's shader reads the scale from its world matrix, which was built before this call
  };
  return s;
}
const disposeAll = (group) => {
  for (const o of [...group.children]) {
    group.remove(o);
    o.traverse((x) => { x.geometry?.dispose(); if (x.material) { x.material.map?.dispose(); x.material.dispose(); } });
  }
};

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

// an anomaly pin's shape as a white texture the severity's colour multiplies: a dot, a diamond, a ring
const pinTextures = {};
function pinTexture(shape) {
  if (pinTextures[shape]) return pinTextures[shape];
  const c = document.createElement('canvas'), g = c.getContext('2d');
  c.width = c.height = 64;
  g.fillStyle = g.strokeStyle = '#fff'; g.lineWidth = 9; g.beginPath();
  if (shape === 'diamond') { g.moveTo(32, 4); g.lineTo(60, 32); g.lineTo(32, 60); g.lineTo(4, 32); g.closePath(); g.fill(); }
  else if (shape === 'ring') { g.arc(32, 32, 24, 0, 7); g.stroke(); }
  else { g.arc(32, 32, 27, 0, 7); g.fill(); }
  return (pinTextures[shape] = new THREE.CanvasTexture(c));
}
const sevHex = (s) => (s === 'critical' || s === 'major' ? C.error : s === 'minor' ? C.warn : C.dim);

const epochAt = (run, t) => {
  let e = run.epochs[0];
  for (const x of run.epochs) if (x.from_t <= t) e = x;
  return e.map_to_world;
};

export const DEPTH_KINDS = [['f', 'sensors.depth.floor'], ['o', 'sensors.depth.obstacle'], ['v', 'sensors.depth.overhead'], ['b', 'sensors.depth.below']];
export const TAIL_S = 1.0;

// One run's drawable layers, one object per stream id (R.obj). `world` applies the epoch in force
// (map -> world); otherwise the robot's own map frame is drawn as is (the data view). The run is packed
// into buffers indexed by the tick's number in the run: append({i0, i1, plans, worlds}) adds the ticks i0..i1-1 wherever
// they are (a window of a long run, the next tick of a live one) and the plans and worlds that became available, and
// costs what it adds; update() only moves draw ranges and poses. A segment of a track exists once both its ticks are
// loaded; depth returns are packed per loaded stretch of ticks. Every point keeps the tick it came from so a click can
// say which record it is (tick * 100000 + its place in the tick).
export const POINT_ID = 100000;

export function fullRange(fr) {
  const have = (arr) => arr.map((x, k) => (x ? k : -1)).filter((k) => k >= 0);
  return { ranges: fr.ranges.map((r) => [...r]), plans: have(fr.plans), worlds: have(fr.worlds) };
}

export function buildRun(run, fr, world) {
  const r = run.robot.radius, h = run.robot.height;
  const tf = (t) => {
    if (!world) return (x, y) => [x, y, 0];
    const [ox, oy, yaw] = epochAt(run, t), c = Math.cos(yaw), s = Math.sin(yaw);
    return (x, y) => [ox + c * x - s * y, oy + s * x + c * y, yaw];
  };
  const L = { group: new THREE.Group(), obj: {}, pick: {} };
  const add = (id, o) => { L.obj[id] = o; L.group.add(o); return o; };

  const posG = new Grow(Float32Array, 3), trkG = new Grow(Float32Array, 3), maskG = new Grow(Uint8Array, 1);
  const bTrack = add('belief.track', new ThickLine(C.belief, 2)), bRobot = add('belief.pose', robotMesh(r, h, C.belief));
  bRobot.position.z = 0.02;
  bRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 0 }); });
  Object.defineProperty(L, 'pose', { get: () => posG.a });

  let tTrack, tRobot, rel = null, tpG = null, trG = null;
  if (world) {
    tpG = new Grow(Float32Array, 3); trG = new Grow(Float32Array, 3);
    tTrack = add('truth.track', new ThickLine(C.truth, 2)); tRobot = add('truth.pose', robotMesh(r, h, C.truth)); tRobot.position.z = 0.02;
    tRobot.traverse((o) => { o.userData.pick = () => ({ kind: 'robot', index: 1 }); });
    Object.defineProperty(L, 'tpose', { get: () => tpG.a });
    rel = add('rel.belief_truth', lineObj(new Float32Array(6), C.rel));
  }

  // depth: per stretch of loaded ticks ("chunk"), one buffer per kind; tick i's returns of a kind are
  // [cum[i - i0], cum[i - i0 + 1]) in it, so "at t", "last N s" and "all up to t" are each one draw range per chunk.
  const kindOf = (k) => (k in { f: 1, o: 1, v: 1, b: 1 } ? k : 'o');
  const chunks = [];
  for (const [, id] of DEPTH_KINDS) add(id, new THREE.Group());
  const newChunk = (i0) => {
    const c = { i0, i1: i0, last: new Grow(Int32Array, 1), lastTick: -1, D: {} };
    for (const [k, id] of DEPTH_KINDS) {
      const B = c.D[k] = { id, pos: new Grow(Float32Array, 3), ids: new Grow(Float64Array, 1), cum: new Grow(Int32Array, 1), o: 0 };
      const pts = pointsObj(B.pos.a, null, 4);
      pts.material.color.set(C.depth[k]);
      pts.geometry.setDrawRange(0, 0); pts.visible = false;
      pts.userData.pick = (hit) => ({ kind: 'depth', index: B.ids.a[hit.index] });
      B.obj = pts; L.obj[id].add(pts);
    }
    chunks.push(c);
    return c;
  };

  // tick i's returns as drawn, by kind: [x, y, z] in this layer's frame (for this repository's tests)
  L.returnsAt = (i) => {
    const c = chunks.find((q) => i >= q.i0 && i < q.i1);
    return c && Object.fromEntries(Object.entries(c.D).map(([k, B]) => [k, Array.from({ length: B.cum.a[i - c.i0 + 1] - B.cum.a[i - c.i0] }, (_, n) => [...B.pos.a.slice((B.cum.a[i - c.i0] + n) * 3, (B.cum.a[i - c.i0] + n) * 3 + 3)])]));
  };

  const psG = new Grow(Float32Array, 3), pStart = [], pCount = [];
  let psN = 0;
  const plan = add('plan.path', new ThickLine(C.plan, 2, 0.07, 0.05));

  // The semantic map (RFC-0016), in the map frame like everything of the robot's (moved by the epoch in the world frame): each part of each
  // object a box from its bottom to its top; a confirmed object solid-ish with its kind as a label, an unconfirmed one faint, a landmark
  // (value 0.7 or more) in its own colour. And the current sighting: its field of view on the floor from the belief pose, and what it
  // saw placed from that pose, each as a box with its kind and confidence. Rebuilt when the record in force changes, not at each tick.
  const objects = add('semantic.objects', new THREE.Group()), sightings = add('semantic.sighting', new THREE.Group());
  let objKey = null, sightingKey = null;
  L.semantic = { objects: 0, confirmed: 0, labels: [], landmarks: [], sighting: null };
  // new children wear the layer of the group they are in (the page sets the group's layer once, when it builds the run)
  const wear = (group) => group.traverse((o) => { if (o !== group) o.layers.mask = group.layers.mask; });
  const triMesh = (tri, hex, opacity) => { const m = fillMesh(tri, hex, opacity); m.renderOrder = -7; return m; };
  const setObjects = (snap) => {
    const key = snap ? snap.t : null;
    if (key === objKey) return;
    objKey = key;
    disposeAll(objects);
    L.semantic.objects = snap ? snap.objects.length : 0; L.semantic.confirmed = 0; L.semantic.labels = []; L.semantic.landmarks = [];
    if (!snap) return;
    const f = tf(snap.t), faces = new Map(), edges = new Map();
    for (const o of snap.objects) {
      const hex = o.landmark >= LANDMARK_MIN ? C.landmark : C.object, solid = !!o.confirmed, k = hex + ':' + solid;
      if (!faces.has(k)) { faces.set(k, { hex, solid, tri: [] }); edges.set(k, []); }
      let top = 0, anchor = null;
      if (o.landmark >= LANDMARK_MIN) L.semantic.landmarks.push(o.id);
      for (const [x, y, hx, hy, yaw, z0, z1] of o.parts) {
        const [wx, wy, ey] = f(x, y), b = { cx: wx, cy: wy, hx, hy, yaw: yaw + (ey || 0) };
        boxFaces(faces.get(k).tri, b, z0, z1); boxEdges(edges.get(k), b, z0, z1);
        if (z1 >= top) { top = z1; anchor = [wx, wy]; }
      }
      if (solid) {
        L.semantic.confirmed++;
        if (anchor) { const s = labelSprite(o.kind, hex); s.position.set(anchor[0], anchor[1], top + 0.1); objects.add(s); L.semantic.labels.push(o.kind); }
      }
    }
    for (const [k, { hex, solid, tri }] of faces) {
      objects.add(triMesh(tri, hex, solid ? 0.42 : 0.1));
      const e = segs(edges.get(k), hex);
      e.material.opacity = solid ? 1 : 0.4; e.frustumCulled = false;
      objects.add(e);
    }
    wear(objects);
  };
  // The operator's areas (RFC-0016 rev. 3): each outline on the floor in the site frame (the map frame in the simulator, where every
  // run starts at the dock), with its name, from the run's `site` record. Built once: a site's areas do not change during a run.
  const areas = add('semantic.areas', new THREE.Group());
  L.semantic.areas = [];
  const site = (run.events || []).find((e) => e.kind === 'site' && e.site?.areas?.length);
  if (site) {
    const f = tf(site.t), pos = [];
    for (const a of site.site.areas) {
      const pts = a.polygon.map(([x, y]) => f(x, y));
      pts.forEach((p, i) => { const q = pts[(i + 1) % pts.length]; pos.push(p[0], p[1], 0.012, q[0], q[1], 0.012); });
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      const s = labelSprite(a.name, C.area); s.position.set(cx, cy, 0.05); areas.add(s);
      L.semantic.areas.push(a.name);
    }
    const e = segs(pos, C.area); e.frustumCulled = false; areas.add(e);
    wear(areas);
  }
  // The anomalies the run recorded (RFC-0019): a pin where the robot believed it was (`where.belief`, in the map frame: moved by the epoch in
  // force at its time in the world frame, as it is in the map frame), a dot for what the robot said and a diamond for what the harness found;
  // in the world frame of a simulated run also a ring where it was (`truth`) joined to the pin by a line. Coloured by severity. Built from the
  // run's events, as the areas are; the page builds the run again when a live run records one.
  const pinsG = add('anomalies', new THREE.Group());
  L.anomalies = [];
  const pinned = new Map(), joins = new Map();
  for (const e of run.events || []) {
    const a = e.anomaly;
    if (!a) continue;
    const hex = sevHex(a.severity), b = a.where?.belief ? tf(e.t)(a.where.belief[0], a.where.belief[1]) : null, w = world && a.truth ? a.truth : null;
    const pin = (shape, p) => { const k = shape + hex, g = pinned.get(k) || pinned.set(k, { shape, hex, pos: [], ts: [] }).get(k); g.pos.push(p[0], p[1], 0.05); g.ts.push(e.t); };
    if (b) pin(a.source === 'harness' ? 'diamond' : 'dot', b);
    if (w) pin('ring', w);
    if (b && w) { const j = joins.get(hex) || joins.set(hex, []).get(hex); j.push(b[0], b[1], 0.05, w[0], w[1], 0.05); }
    L.anomalies.push({ t: e.t, severity: a.severity, source: a.source, hex, belief: b && [b[0], b[1]], truth: w && [w[0], w[1]] });
  }
  for (const { shape, hex, pos, ts } of pinned.values()) {
    const p = pointsObj(new Float32Array(pos), null, shape === 'ring' ? 12 : 14);
    Object.assign(p.material, { map: pinTexture(shape), alphaTest: 0.3, depthTest: false, color: col(hex) });
    p.renderOrder = 7; p.userData.pick = (hit) => ({ kind: 'anomaly', t: ts[hit.index] });
    pinsG.add(p);
  }
  for (const [hex, pos] of joins) { const l = segs(pos, hex); l.frustumCulled = false; l.renderOrder = 7; l.material.depthTest = false; pinsG.add(l); }
  const setSighting = (sighting) => {
    const key = sighting ? sighting.t : null;
    if (key === sightingKey) return;
    sightingKey = key;
    disposeAll(sightings);
    L.semantic.sighting = null;
    if (!sighting) return;
    const f = tf(sighting.t), [px, py, pyaw] = sighting.pose, h = (sighting.hfov_deg * Math.PI) / 360, n = 14, z = 0.012;
    const apex = f(px, py), arc = [];
    for (let k = 0; k <= n; k++) arc.push(f(px + sighting.range_m * Math.cos(pyaw - h + (2 * h * k) / n), py + sighting.range_m * Math.sin(pyaw - h + (2 * h * k) / n)));
    const fan = [], outline = [apex[0], apex[1], z, arc[0][0], arc[0][1], z, arc[n][0], arc[n][1], z, apex[0], apex[1], z];
    for (let k = 1; k <= n; k++) {
      fan.push(apex[0], apex[1], z, arc[k - 1][0], arc[k - 1][1], z, arc[k][0], arc[k][1], z);
      outline.push(arc[k - 1][0], arc[k - 1][1], z, arc[k][0], arc[k][1], z);
    }
    sightings.add(triMesh(fan, C.wedge, 0.16), segs(outline, C.wedge));
    const c = Math.cos(pyaw), s = Math.sin(pyaw), seen = [];
    for (const d of sighting.seen) {
      const mx = px + c * d.x - s * d.y, my = py + s * d.x + c * d.y, r = d.radius || 0.1, z0 = d.z0 ?? 0, z1 = d.z1 ?? 0.3;
      const [wx, wy, ey] = f(mx, my), b = { cx: wx, cy: wy, hx: r, hy: r, yaw: ey || 0 }, ed = [];
      boxEdges(ed, b, z0, z1);
      const box = segs(ed, C.seen); box.frustumCulled = false; box.renderOrder = 8; box.material.depthTest = false;
      sightings.add(box);
      const text = d.confidence == null ? d.kind : `${d.kind} ${Math.round(100 * d.confidence)}%`, lab = labelSprite(text, C.seen);
      lab.position.set(wx, wy, z1 + 0.2); sightings.add(lab);
      seen.push({ kind: d.kind, label: text, map: [mx, my], world: [wx, wy] });
    }
    L.semantic.sighting = { t: sighting.t, pose: sighting.pose, hfov_deg: sighting.hfov_deg, range_m: sighting.range_m, seen };
    wear(sightings);
  };

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

  // the gaps (RFC-0013 2.1): the unknown cells of the map in force within the drop margin of the plan in force, tinted and hatched; the other
  // unknown cells as a faint fog. Made when the map or the plan in force changes, not at each tick.
  const gaps = add('world.gaps', new THREE.Group());
  const flat = (hex, opacity) => { const m = new THREE.Mesh(new THREE.BufferGeometry(), fillMat(hex, opacity)); m.renderOrder = -9; m.frustumCulled = false; return m; };
  const gFog = flat(C.fog, 0.1), gTint = flat(C.gap, 0.3);
  const gHatch = new THREE.LineSegments(new THREE.BufferGeometry(), lineMat(C.gap));
  gHatch.frustumCulled = false; gHatch.renderOrder = -8;
  gaps.add(gFog, gTint, gHatch);
  let gapKey = '';
  L.gapCount = { gap: 0, fog: 0 };
  const setGaps = (wi, pi) => {
    const w = fr.worlds[wi], p = fr.plans[pi];
    if (!w || !p) { gapKey = ''; for (const o of [gFog, gTint, gHatch]) o.visible = false; L.gapCount = { gap: 0, fog: 0 }; return; }
    const key = wi + ':' + pi;
    if (key === gapKey) return;
    gapKey = key;
    const { gap, fog } = gapCells(w.grid, p.path), f = tf(w.t), g = w.grid;
    const quad = (k, z) => {
      const i = k % g.w, j = (k / g.w) | 0, x0 = g.origin[0] + i * g.res, y0 = g.origin[1] + j * g.res;
      return [[x0, y0], [x0 + g.res, y0], [x0 + g.res, y0 + g.res], [x0, y0 + g.res]].map(([x, y]) => [...f(x, y).slice(0, 2), z]);
    };
    const tris = (ks, z) => ks.flatMap((k) => { const q = quad(k, z); return [0, 1, 2, 0, 2, 3].flatMap((m) => q[m]); });
    gFog.geometry.setAttribute('position', new THREE.Float32BufferAttribute(tris(fog, 0.0005), 3));
    gTint.geometry.setAttribute('position', new THREE.Float32BufferAttribute(tris(gap, 0.0015), 3));
    gHatch.geometry.setAttribute('position', new THREE.Float32BufferAttribute(gap.flatMap((k) => { const q = quad(k, 0.003); return [...q[0], ...q[2]]; }), 3));
    for (const o of [gFog, gTint, gHatch]) { o.geometry.boundingSphere = null; o.visible = true; }
    L.gapCount = { gap: gap.length, fog: fog.length };
  };

  const extendTicks = (a, b) => {
    posG.need(b); trkG.need(b); maskG.need(b + 1);
    if (world) { tpG.need(b); trG.need(b); }
    let lastTruth = (world && fr.truth.slice(a, b).find(Boolean)) || [0, 0, 0];     // a tick without truth wears the last one
    for (let i = a; i < b; i++) {
      const [x, y, yaw] = fr.belief[i], [wx, wy, ey] = tf(fr.t[i])(x, y);
      posG.a.set([wx, wy, yaw + ey], i * 3);
      trkG.a.set([wx, wy, 0.01], i * 3);
      maskG.a[i] = 1;
      if (world) {
        lastTruth = fr.truth[i] || lastTruth;
        tpG.a.set(lastTruth, i * 3);
        trG.a.set([lastTruth[0], lastTruth[1], 0.01], i * 3);
      }
    }
    // a track's segment k joins ticks k and k+1: made now if both are loaded (the ones beside the new ticks are)
    for (let k = Math.max(a - 1, 0); k < b; k++) {
      if (!(maskG.a[k] && maskG.a[k + 1])) continue;
      bTrack.seg(trkG.a, k);
      if (world) tTrack.seg(trG.a, k);
    }
    bTrack.flush();
    if (world) tTrack.flush();

    // depth: appended to the stretch this range continues, else a stretch of its own
    const c = chunks.find((q) => q.i1 === a) || newChunk(a);
    c.last.need(b - c.i0 + 1);
    for (const k in c.D) c.D[k].cum.need(b - c.i0 + 2);
    for (let i = a; i < b; i++) {
      const rel0 = i - c.i0;
      for (const k in c.D) c.D[k].cum.a[rel0] = c.D[k].o;
      const d = fr.depth[i];
      if (d && d.length) {
        c.lastTick = i;
        const f = tf(fr.t[i]);
        d.forEach(([x2, y2, z, kk], j) => {
          const B = c.D[kindOf(kk)], [dx, dy] = f(x2, y2);
          B.pos.need(B.o + 1); B.ids.need(B.o + 1);
          B.pos.a.set([dx, dy, z], B.o * 3);
          B.ids.a[B.o] = i * POINT_ID + j;
          B.o++;
        });
      }
      c.last.a[rel0] = c.lastTick;
    }
    c.i1 = b;
    for (const k in c.D) { c.D[k].cum.a[b - c.i0] = c.D[k].o; sync(c.D[k].obj.geometry, 'position', c.D[k].pos, 3); }
  };

  const extendPlans = (ks) => {
    for (const k of ks) {
      const p = fr.plans[k];
      if (!p || pStart[k] !== undefined) continue;
      pStart[k] = psN; pCount[k] = p.path.length;
      const f = tf(p.t);
      psG.need(psN + p.path.length);
      for (const [x, y] of p.path) { psG.a.set([...f(x, y).slice(0, 2), 0.012], psN * 3); psN++; }
      plan.made = pStart[k]; plan.acc = 0;               // the dashes start with each plan, whatever order the plans were loaded in
      plan.set(psG.a, psN);
    }
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
    for (const [a, b] of range.ranges ?? [[range.i0, range.i1]]) if (b > a) extendTicks(a, b);
    if (range.plans?.length) extendPlans(range.plans);
    if (range.worlds?.length) extendWorlds(range.worlds);
  };

  // where a record sits in this run's frame: [x, y, z, tick] or null
  L.locate = (kind, index, wi) => {
    if (kind === 'depth') {
      const tick = Math.floor(index / POINT_ID), p = fr.depth[tick]?.[index % POINT_ID];
      if (!p) return null;
      const dk = kindOf(p[3]), [wx, wy] = tf(fr.t[tick])(p[0], p[1]);
      return { stream: DEPTH_KINDS.find(([k]) => k === dk)[1], dk, p: [wx, wy, p[2]], tick };
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
      const i0 = Math.min(fr.firstAt(t - (mode === 'window' ? w : TAIL_S)), i);
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
    for (const [k, id] of DEPTH_KINDS) {
      const { mode, n: w } = cfg(id);
      const from = mode === 'window' ? Math.min(fr.firstAt(t - w), i) : 0;
      for (const c of chunks) {
        const B = c.D[k], cum = B.cum.a;
        let rg = [0, 0];
        if (mode === 'at') {
          const d = i >= c.i0 && i < c.i1 ? c.last.a[i - c.i0] : -1;
          if (d >= c.i0) rg = [cum[d - c.i0], cum[d - c.i0 + 1] - cum[d - c.i0]];
        } else {
          const lo = Math.max(c.i0, from), hi = Math.min(i, c.i1 - 1);
          if (hi >= lo) rg = [cum[lo - c.i0], cum[hi - c.i0 + 1] - cum[lo - c.i0]];
        }
        B.obj.geometry.setDrawRange(rg[0], rg[1]);
        B.obj.visible = rg[1] > 0;
        B.obj.material.size = size(id);
      }
    }
    const pi = fr.plan_at[i];
    plan.setWidth(size('plan.path'));
    plan.range(...(pi >= 0 && pStart[pi] !== undefined ? [pStart[pi], pCount[pi]] : [0, 0]));
    const wi = fr.world_at[i], none = [0, 0];
    cells.geometry.setDrawRange(...(wi >= 0 && wCell[wi] ? wCell[wi] : none));
    obst.geometry.setDrawRange(...(wi >= 0 && oRange[wi] ? oRange[wi] : none));
    drops.geometry.setDrawRange(...(wi >= 0 && dRange[wi] ? dRange[wi] : none));
    obst.material.size = size('world.obstacles'); drops.material.size = size('world.drops');
    setGaps(wi, pi);
    setObjects(fr.objectsAt?.(t) ?? null); setSighting(fr.sightingAt?.(t) ?? null);
  };
  L.append(fullRange(fr));
  return L;
}
