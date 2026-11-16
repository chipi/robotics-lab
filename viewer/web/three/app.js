// The three.js page: the shared workbench (../shell/) with a three.js renderer in #stage.
import * as THREE from 'three';
import { createShell } from '../shell/shell.js';
import { Views } from './views.js';
import { buildScene, buildRun, setPalette } from './build.js';
import { createBody } from '../shell/robotbody.js';

// One three.js layer bit per drawable stream: a camera shows a stream only when its layer is on,
// which is what makes "off in this view only" free. Layer 0 is the coordinate frame and the marker.
const DRAWN = ['scene.boxes', 'scene.hazards', 'belief.pose', 'belief.track', 'truth.pose', 'truth.track',
  'sensors.depth.floor', 'sensors.depth.obstacle', 'sensors.depth.overhead', 'sensors.depth.below',
  'world.grid', 'world.obstacles', 'world.drops', 'plan.path', 'rel.belief_truth', 'fill.boxes', 'fill.hazards', 'body.model'];
const LAYER = Object.fromEntries(DRAWN.map((id, k) => [id, k + 1]));
const DEPTH_NAME = { f: 'floor', o: 'obstacle', v: 'overhead', b: 'below the floor' };
const deg = (r) => (r * 180) / Math.PI;

let S, M, renderer, scene, views, marker, canvas;
let sceneG = null, scn = null, run = null, fr = null, RW = null, RM = null, rebuilding = false;
const R = () => (M.frame === 'world' ? RW : RM);
const bounds = () => scn?.bounds ?? [-4, 4, -3, 3];
const setLayers = (obj, id) => obj.traverse((o) => o.layers.set(LAYER[id]));

// the selection marker: a ring that stays the same size on screen
// a ring in the theme's selection colour with a halo in the viewport's, so it reads on either background
function markerTexture(ring, halo) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.lineWidth = 13.5; g.strokeStyle = halo; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  g.lineWidth = 7.4; g.strokeStyle = ring; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  return new THREE.CanvasTexture(c);
}
function makeMarker() {
  const m = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ map: markerTexture('#fff', '#000'), size: 26, sizeAttenuation: false, transparent: true, depthTest: false }));
  m.frustumCulled = false; m.renderOrder = 10; m.visible = false;
  return m;
}

function buildSceneObjects() {
  if (sceneG) scene.remove(sceneG);
  sceneG = buildScene(scn);
  for (const [id, o] of Object.entries(sceneG.parts)) setLayers(o, id);
  for (const [id, list] of Object.entries(sceneG.fills)) for (const o of list) setLayers(o, id);
  scene.add(sceneG);
}

function buildRunObjects() {
  for (const Rn of [RW, RM]) if (Rn) scene.remove(Rn.group);
  RW = buildRun(run, fr, true); RM = buildRun(run, fr, false);
  for (const Rn of [RW, RM]) for (const [id, o] of Object.entries(Rn.obj)) setLayers(o, id);
  scene.add(RW.group, RM.group);
}

// ---- the Robot layer (RFC-0011): the robot's body from its description, its joints at the playhead, where it was --------
let body = null, bodyFor = null, lit = false;
async function buildBody() {
  const desc = S.robot();
  if (!desc || bodyFor === desc) return;
  bodyFor = desc;
  if (body) { scene.remove(body.root); body = null; }
  const b = await createBody(THREE, desc, S.api);
  if (bodyFor !== desc) return;                                   // another run's robot came meanwhile
  body = b;
  setLayers(body.root, 'body.model');
  if (!lit) {                                                      // the body is shaded; everything else is drawn flat and ignores lights
    lit = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1, -1, 2);
    scene.add(sun);
  }
  scene.add(body.root);
  if (fr) adapter.draw();
}
// the trunk where the truth had it (the whole pose, ADR-0016) in the world frame of a simulated run; else at the belief's
// x, y and yaw (the frame being looked at), tilted by the IMU, at the robot's standing height
function placeBody() {
  if (!body) return;
  const on = !!fr && !!RW && S.shown('body.model');
  body.root.visible = on;
  const i = M.i, t3 = on && M.frame === 'world' ? fr.truth_3d?.[i] : null;
  // with the body shown no marker fills its cylinder (the body would sit inside a coloured haze: belief and truth are often
  // where it is); the marker it stands in for drops the outline too, keeping its heading line and dot. Hidden parts stay
  // pickable (the raycaster does not skip them)
  const standIn = !on ? null : t3 && RW.tpose ? RW.obj['truth.pose'] : R().obj['belief.pose'];
  for (const m of [RW?.obj['truth.pose'], RW?.obj['belief.pose'], RM?.obj['belief.pose']]) {
    if (!m) continue;
    m.children[0].visible = !on;
    m.children[1].visible = m !== standIn;
  }
  if (!on) return;
  if (t3 && RW.tpose) body.place([RW.tpose[i * 3], RW.tpose[i * 3 + 1], t3.z], t3.quat);
  else {
    const P = R().pose, tl = fr.tilt?.[i];
    const yaw = P[i * 3 + 2], pitch = tl ? (tl[0] * Math.PI) / 180 : 0, roll = tl ? (tl[1] * Math.PI) / 180 : 0;
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(roll, pitch, yaw, 'ZYX'));
    body.place([P[i * 3], P[i * 3 + 1], S.robot()?.stand_z ?? 0], [q.w, q.x, q.y, q.z]);
  }
  body.pose(S.joints());
}

function applyVis() {
  const w = M.frame === 'world';
  if (sceneG) {
    sceneG.visible = w;
    for (const [id, o] of Object.entries(sceneG.parts)) o.visible = S.shown(id);
  }
  for (const [Rn, on] of [[RW, w], [RM, !w]]) {
    if (!Rn) continue;
    Rn.group.visible = on;
    for (const [id, o] of Object.entries(Rn.obj)) o.visible = S.shown(id);
  }
}

// What a selection is, in the frame being looked at. Robots follow the cursor; points and cells stay.
function describe(sel) {
  if (!sel || !fr || !RW) return null;
  const Rn = R(), i = M.i;
  let o;
  if (sel.kind === 'robot') {
    const tr = sel.index === 1;
    if (tr && M.frame === 'map') return null;
    const P = tr ? RW.tpose : Rn.pose;
    if (!P) return null;
    o = { stream: tr ? 'truth.pose' : 'belief.pose', detail: `${tr ? 'truth' : 'belief'} robot`, p: [P[i * 3], P[i * 3 + 1]], height: run.robot.height, tick: i, yaw: P[i * 3 + 2], frame: tr ? 'world' : M.frame };
  } else {
    const l = Rn.locate(sel.kind, sel.index, sel.world);
    if (!l) return null;
    o = { stream: l.stream, p: [l.p[0], l.p[1]], height: l.p[2], frame: M.frame };
    if (sel.kind === 'depth') { o.tick = l.tick; o.depth_kind = l.dk; o.detail = `${DEPTH_NAME[l.dk]} return`; }
    if (sel.kind === 'cell') {
      const st = { '#': 'occupied', '.': 'free' }[l.cell] || 'unknown';
      o.tick = S.tickAt(l.wt); o.t = l.wt; o.state = st; o.res = l.res; o.detail = `${st} cell`;
    }
  }
  if (o.t === undefined) o.t = fr.t[o.tick];
  return o;
}

function placeMarker() {
  const d = M.sel && fr ? describe(M.sel) : null;
  marker.visible = !!d;
  if (!d) return;
  const a = marker.geometry.attributes.position;
  a.array.set([d.p[0], d.p[1], d.height]); a.needsUpdate = true;
}

const adapter = {
  init(stage, shell) {
    S = shell; M = shell.M;
    canvas = document.createElement('canvas'); canvas.id = 'gl';
    stage.prepend(canvas);
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    scene = new THREE.Scene();
    views = new Views(stage, renderer, scene, () => { if (fr && !rebuilding) adapter.draw(); S.viewChanged(); });
    marker = makeMarker(); scene.add(marker);
    views.layerMask = (view) => {
      let m = 1;
      for (const id of DRAWN) {
        const fill = id.startsWith('fill.');     // the faint faces of boxes and pits: from above and in 3D, outlines only in a side view
        if (fill ? (view === 'top' || view === '3d') && S.shown(id === 'fill.boxes' ? 'scene.boxes' : 'scene.hazards', view) : S.shown(id, view)) m |= 1 << LAYER[id];
      }
      return m;
    };
    const rc = new THREE.Raycaster();
    rc.params.Line.threshold = 0.001;
    views.onPick = (s, x, y) => {
      if (!fr || !RW) return;
      rc.setFromCamera({ x, y }, s.camera);
      rc.layers.mask = views.layerMask(s.name);
      rc.params.Points.threshold = 7 * views.metresPerPx(s);
      const rank = { depth: 0, robot: 1, cell: 2 };
      const hits = rc.intersectObject(R().group, true)
        .map((h) => ({ h, sel: h.object.userData.pick?.(h) })).filter((x) => x.sel && x.sel.kind in rank)
        .sort((a, b) => rank[a.sel.kind] - rank[b.sel.kind] || (a.h.distanceToRay ?? a.h.distance) - (b.h.distanceToRay ?? b.h.distance));
      S.pick(hits.length ? hits[0].sel : null);
    };
  },

  setScene(sc) { scn = sc; buildSceneObjects(); },
  setRun(r, f) { run = r; fr = f; buildRunObjects(); buildBody(); },
  // the run grew: add what it gained (ticks i0..i1-1, the plans and worlds that became available); nothing is rebuilt
  append(range) {
    if (!RW) return;
    RW.append(range); RM.append(range);
    for (const Rn of [RW, RM]) for (const [id, o] of Object.entries(Rn.obj)) setLayers(o, id);       // a new stretch of depth points joins its stream's layer
  },
  // the shell draws after a layout, so the draw views.setup() would trigger is skipped
  setLayout(view, frame) { rebuilding = true; views.setup(view, bounds(), frame); rebuilding = false; },

  draw(sync = false) {
    if (!fr || !RW) return;
    RW.update(M.i, M.t, S.cfg, S.size); RM.update(M.i, M.t, S.cfg, S.size);
    applyVis(); placeMarker(); placeBody();
    views.coords = M.ov.coords;
    views.render();
    if (sync) { const gl = renderer.getContext(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4)); }
  },
  settled: () => new Promise((res) => requestAnimationFrame(() => res())),
  resize() { views.resize(); },
  fit() { views.fit(); },
  theme(p) {
    setPalette(p);
    renderer.setClearColor(p['bg-viewport']);
    marker.material.map = markerTexture(p['draw-sel'], p['bg-viewport']); marker.material.needsUpdate = true;
    if (scn) buildSceneObjects();
    if (run && fr) buildRunObjects();
    if (views.layout) { rebuilding = true; views.setup(views.layout, bounds(), views.frameName); rebuilding = false; }
  },
  describe,
  // the Robot layer as drawn: shown, where its root is, how many parts (for this repository's tests)
  body: () => (body ? { visible: body.root.visible, pos: body.root.position.toArray().map((v) => +v.toFixed(5)),
    quat: [body.root.quaternion.w, body.root.quaternion.x, body.root.quaternion.y, body.root.quaternion.z].map((v) => +v.toFixed(5)), drawn: body.drawn(),
    joint_upper_quat: body.links.upper ? [body.links.upper.quaternion.w, body.links.upper.quaternion.y].map((v) => +v.toFixed(5)) : null,
    // per marker: [fill shown, outline shown]
    cylinders: Object.fromEntries([['truth', RW?.obj['truth.pose']], ['belief', R()?.obj['belief.pose']]].map(([k, m]) => [k, m ? [m.children[0].visible, m.children[1].visible] : null])) } : null),
  cursor: (x, y) => views.cursorAt(x, y),
  scale: () => views.scale(),
  fillsDrawn: (pane) => (views.layerMask(pane) & (1 << LAYER['fill.boxes'])) !== 0,
  project: (p) => views.project(p),
  gizmo: () => views.axes3d(),
};

createShell(adapter, { title: 'miniview - three.js' });

