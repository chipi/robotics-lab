// The three.js page: the shared workbench (../shell/) with a three.js renderer in #stage.
import * as THREE from 'three';
import { createShell } from '../shell/shell.js';
import { Views } from './views.js';
import { buildScene, buildRun, readPalette, C } from './build.js';
import { createStage, STAGE_LAYER } from '/lib/stage/stage.js';
import { createTrail } from '/lib/stage/trail.js';
import { createBody, jointStates, tokenColors } from '/lib/body/body.js';
import { mountInspector } from '/lib/body/inspector.js';
import { axes as sensorAxes } from '../shell/eye.js';

// One three.js layer bit per drawable stream: a camera shows a stream only when its layer is on,
// which is what makes "off in this view only" free. Layer 0 is the coordinate frame and the marker.
const DRAWN = ['scene.boxes', 'scene.hazards', 'belief.pose', 'belief.track', 'truth.pose', 'truth.track',
  'sensors.depth.floor', 'sensors.depth.obstacle', 'sensors.depth.overhead', 'sensors.depth.below',
  'world.grid', 'world.obstacles', 'world.drops', 'world.gaps', 'plan.path', 'semantic.objects', 'semantic.sighting', 'semantic.areas', 'anomalies', 'rel.belief_truth', 'fill.boxes', 'fill.hazards', 'body.model', 'hazards.top'];
// what the eye does not draw: the robot itself, whose body the sensor sits in
const NOT_IN_EYE = new Set(['body.model', 'belief.pose', 'truth.pose', 'rel.belief_truth']);
const LAYER = Object.fromEntries(DRAWN.map((id, k) => [id, k + 1]));
const DEPTH_NAME = { f: 'floor', o: 'obstacle', v: 'overhead', b: 'below the floor' };
const deg = (r) => (r * 180) / Math.PI;

let S, M, renderer, scene, views, marker, canvas, stg, camBar, camToggle, floorSaved = true, camPending = false, camFocused = false, ovSaved = { ghost: true, open_scene: false };
let camRun = null;
let sceneG = null, scn = null, run = null, fr = null, RW = null, RM = null, rebuilding = false;
const R = () => (M.frame === 'world' ? RW : RM);
const bounds = () => scn?.bounds ?? [-4, 4, -3, 3];
// the shell's own preferences (miniview.left), where the layer toggles that persist live
const prefs = () => { try { return JSON.parse(localStorage.getItem('miniview.left') || '{}'); } catch (_) { return {}; } };
const savePref = (p) => { try { localStorage.setItem('miniview.left', JSON.stringify({ ...prefs(), ...p })); } catch (_) { /* no storage */ } };
const setLayers = (obj, id) => obj.traverse((o) => o.layers.set(LAYER[id]));

// the selection marker: a ring that stays the same size on screen
// a ring in --scene-select with a halo in --scene-bg, so it reads on either background
function markerTexture(ring, halo) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.lineWidth = 13.5; g.strokeStyle = halo; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  g.lineWidth = 7.4; g.strokeStyle = ring; g.beginPath(); g.arc(32, 32, 24, 0, 7); g.stroke();
  return new THREE.CanvasTexture(c);
}
function makeMarker() {
  const m = new THREE.Points(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3)),
    new THREE.PointsMaterial({ map: markerTexture(stg.tokens.select, stg.tokens.bg), size: 26, sizeAttenuation: false, transparent: true, depthTest: false, toneMapped: false }));
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
let body = null, bodyFor = null, shadow = null, ghost = null, trail = null, trailFor = null, insp = null, inspPanel = null, inspHost = null, inspOpen = false;
const TRAIL_MAX = 600, TRAIL_Z = 0.04;                              // points kept (the newest), and the trail's height above the floor (clear of the flat tracks)
async function buildBody() {
  const desc = S.robot();
  if (!desc || bodyFor === desc) return;
  bodyFor = desc;
  if (body) {
    scene.remove(body.root, ghost.root); shadow?.dispose(); shadow = null; ghost.dispose(); body.dispose(); body = ghost = null;
    insp?.dispose(); insp = null;
  }
  const b = await createBody(THREE, desc, S.api);
  if (bodyFor !== desc) return;                                   // another run's robot came meanwhile
  body = b;
  setLayers(body.root, 'body.model');
  scene.add(body.root);
  ghost = body.clone({ style: { mode: 'ghost', color: C.belief } });       // the belief's second opinion; on the belief's layer so a view that hides the belief hides it
  setLayers(ghost.root, 'belief.pose');
  ghost.root.visible = false;
  scene.add(ghost.root);
  insp = mountInspector(inspHost, body, { onSelect: (link) => body.highlight(link) });
  shadow = stg.contactShadow(body.root);                            // the stage's lights (made at init) shade the body; everything else is drawn flat
  if (fr) adapter.draw();
}
// where the belief puts the trunk at tick i (pose P: its x, y and yaw), tilted by the IMU, at the robot's standing height: [position, quaternion wxyz]
function beliefPlace(P, i) {
  const tl = fr.tilt?.[i];
  const yaw = P[i * 3 + 2], pitch = tl ? (tl[0] * Math.PI) / 180 : 0, roll = tl ? (tl[1] * Math.PI) / 180 : 0;
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(roll, pitch, yaw, 'ZYX'));
  return [[P[i * 3], P[i * 3 + 1], S.robot()?.stand_z ?? 0], [q.w, q.x, q.y, q.z]];
}
// the trunk where the truth had it (the whole pose, ADR-0016) in the world frame of a simulated run; else at the belief's
// x, y and yaw (the frame being looked at), tilted by the IMU, at the robot's standing height
function placeBody() {
  if (!body) return;
  const on = !!fr && !!RW && S.shown('body.model');
  body.root.visible = on;
  shadow.visible = on;
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
  else body.place(...beliefPlace(R().pose, i));
  body.pose(S.joints());
  shadow.update();
  body.health(jointStates(S.anomalies(), M.t), tokenColors());       // each joint by the worst anomaly naming it at or before the playhead
}

// The body stands at the truth (world frame, a whole truth pose at this tick): only then is the belief a second opinion beside it. Without
// the truth's whole pose the body is drawn at the belief, so a ghost would sit exactly in it.
const bodyAtTruth = () => !!body?.root.visible && M.frame === 'world' && !!RW?.tpose && !!fr?.truth_3d?.[M.i];

// the belief ghost: the same body in the belief's pose, translucent, in the belief's colour; shown while the truth body is, belief or not near it (no
// tolerance below which it hides: the offset between them is the thing it shows, and zero is an answer)
function placeGhost() {
  if (!ghost) return;
  const on = bodyAtTruth() && M.ov.ghost && S.shown('belief.pose');
  ghost.root.visible = on;
  if (!on) return;
  ghost.place(...beliefPlace(RW.pose, M.i));
  ghost.pose(S.joints());
}

// the trail: where the robot the body stands for has been, up to the playhead, the newest `TRAIL_MAX` ticks of the stretch of the run that is loaded
function placeTrail() {
  trail.object.visible = !!body?.root.visible && M.ov.trail;
  if (!trail.object.visible) return;
  const atTruth = bodyAtTruth(), P = atTruth ? RW.tpose : R().pose, i = M.i;
  const key = atTruth ? 'truth' : 'belief';
  if (trailFor !== key) { trail.setColors({ head: C[key], fadeTo: stg.tokens.bg }); trailFor = key; }
  const [a] = fr.ranges.find(([x, y]) => x <= i && i < y) ?? [i];
  const pts = [];
  for (let k = Math.max(a, i - TRAIL_MAX + 1); k <= i; k++) pts.push([P[k * 3], P[k * 3 + 1], TRAIL_Z]);
  trail.set(pts);
}

// x-ray: the truth body see-through, to look inside it
function placeStyle() {
  if (!body) return;
  const mode = M.ov.xray ? 'xray' : 'solid';
  if (body.style().mode !== mode) body.setStyle({ mode });
}

// ---- the model inspector (row 25): the body's parts, their joints and values, on `i`, closed by Esc or the Overlays row --------------------
const typing = (e) => !!e.target?.matches?.('input, textarea, select');
function buildInspector(stage) {
  inspPanel = document.createElement('aside');
  inspPanel.id = 'inspector'; inspPanel.className = 'inspector'; inspPanel.hidden = true;
  inspPanel.setAttribute('aria-label', 'Model inspector');
  inspPanel.innerHTML = '<header><span>Model inspector</span><button type="button" class="icon-btn" aria-label="Close the model inspector" title="Close (Esc)">&times;</button></header><div class="insp-host"></div>';
  inspHost = inspPanel.querySelector('.insp-host');
  inspPanel.querySelector('button').onclick = () => setInspector(false);
  stage.append(inspPanel);
  addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
    if (e.key === 'i' || e.key === 'I') { if (insp) { e.preventDefault(); setInspector(!M.ov.inspector, true); } }
    else if (e.key === 'Escape' && M.ov.inspector) setInspector(false);
  });
}
// every way in (the key, the Overlays row, a script) is the overlay `inspector`; this is the key's and the button's
function setInspector(on, focus = false) {
  window.miniview.setOverlay('inspector', on);
  if (on && focus) inspHost.querySelector('.insp-list')?.focus();
}
function syncInspector() {
  const open = !!M.ov.inspector && !!insp;
  inspPanel.hidden = !open;
  if (inspOpen && !open) body?.highlight(null);                       // the part picked in the list is lit only while the list is open
  inspOpen = open;
  if (open) insp.update(S.joints());
}

// ---- the placed cameras (RFC-0013): the eye at the sensor's pose at the playhead, the chase camera behind the robot -------------------
let eyeAt = null;
function placeCams() {
  if (!views.slots.some((s) => s.name === 'eye' || s.name === 'chase')) return;
  const e = S.eyePose();
  if (e && !e.pending) {                                         // pending: the frame is being asked for, the camera stays where it was
    eyeAt = e;
    const a = sensorAxes(e.quat);
    views.place('eye', { pos: e.pos, forward: a.forward, up: a.up });
  }
  // the robot where the truth had it, else where it believed it was (in the world frame), as the Robot layer stands it
  const i = M.i, P = RW.tpose && fr.truth[i] ? RW.tpose : RW.pose, x = P[i * 3], y = P[i * 3 + 1], yaw = P[i * 3 + 2], c = Math.cos(yaw), s = Math.sin(yaw);
  views.place('chase', { pos: [x - 0.9 * c, y - 0.9 * s, 0.55], target: [x + 0.35 * c, y + 0.35 * s, 0.08] });
}

// the floor and the shadow are on the stage layer, which only the 3D and chase cameras draw (layerMask): top and the side views stay as flat
// drawings so the map's cells and the numbered grid read as before, and the eye is the sensor's view, not a room
const FLOOR_VIEWS = new Set(['3d', 'chase']);
function setFloor(on) {
  M.ov.floor = !!on;
  stg.floor.visible = M.ov.floor;
}
// the viewer preferences kept across a reload: the ones that differ from what was stored are written
function persistOv() {
  if (M.ov.floor !== floorSaved) { floorSaved = M.ov.floor; savePref({ floor: floorSaved }); }
  for (const k of Object.keys(ovSaved)) if (!!M.ov[k] !== ovSaved[k]) { ovSaved[k] = !!M.ov[k]; savePref({ [k]: ovSaved[k] }); }
}
function applyVis() {
  persistOv();
  setFloor(M.ov.floor);
  stg.grid.visible = M.ov.coords;                                   // the grid is the coordinate system's, as the flat views' is
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

// the semantic labels' height on the screen, in pixels of the first 3D (else the first) pane: meant to be the same at any zoom
function labelPx() {
  const s = views.slots.find((q) => q.is3) || views.slots[0];
  if (!s || !RW) return [];
  const c = s.camera, up = new THREE.Vector3(0, 1, 0).applyQuaternion(c.quaternion);
  return ['semantic.objects', 'semantic.sighting'].flatMap((id) => RW.obj[id].children.filter((o) => o.isSprite)).map((sp) => {
    const p = sp.getWorldPosition(new THREE.Vector3()), a = p.clone().project(c), b = p.clone().add(up.clone().multiplyScalar(sp.scale.y)).project(c);
    return +((Math.abs(b.y - a.y) / 2) * s.h).toFixed(1);
  });
}

// ---- the 3D camera (U12): where the robot is, what to frame, the corner controls and the gizmo's clicks ------------------------------------
// the least width (m) of the frame round the robot: a small robot is shown with its surroundings, not filling the pane
const CONTEXT_MIN = 1.2;
const SCENE_TOP = 1.5;                                          // m: the height the scene's frame covers (the grid's z labels end there)
const hashTime = () => { const t = new URLSearchParams(location.hash.slice(1)).get('t'); return t !== null && Number.isFinite(+t) ? +t : null; };
// the tick the opening camera frames: a `#t=` link opens on the moment it names
const camTick = () => (camPending && hashTime() !== null ? S.tickAt(hashTime()) : M.i);

// the robot as the 3D view draws it at tick i: its trunk's position (mid height) and heading; the body's whole orientation when the body is shown
function robotAt(i = M.i, full = false) {
  if (!fr || !RW) return null;
  const h2 = (run.robot.height || 0.3) / 2;
  // the body is where placeBody put it (the truth's pose, else the belief's), which is the one the viewer sees at the playhead
  if (body?.root.visible && i === M.i) {
    const p = body.root.position, q = body.root.quaternion;
    const out = { position: [p.x, p.y, p.z + h2], yaw: new THREE.Euler().setFromQuaternion(q, 'ZYX').z };
    if (full) out.quaternion = q.toArray();
    return out;
  }
  const P = M.frame === 'world' && RW.tpose && fr.truth_3d?.[i] ? RW.tpose : R().pose;                  // the rule placeBody follows
  if (!P) return null;
  return { position: [P[i * 3], P[i * 3 + 1], h2], yaw: P[i * 3 + 2] };
}
// the robot's own box: its footprint and height, and the body's when it is drawn
function robotBox(i = M.i) {
  const r = robotAt(i);
  if (!r) return null;
  const [x, y] = r.position, rad = run.robot.radius || 0.15, h = run.robot.height || 0.3;
  const min = [x - rad, y - rad, 0], max = [x + rad, y + rad, h];
  if (body?.root.visible) {
    const b = new THREE.Box3().setFromObject(body.root);
    if (!b.isEmpty()) for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], b.min.getComponent(k)); max[k] = Math.max(max[k], b.max.getComponent(k)); }
  }
  return { min, max };
}
// what Fit robot and the opening camera put in view: the robot's box with room round it (twice its width, never under CONTEXT_MIN across)
// an evidence link's `focus=robot` is about the robot, so it is framed tighter: a box two and a half times its width, never under FOCUS_MIN across
const FOCUS_MIN = 0.6;
function robotFrame(i = M.i, tight = false) {
  const b = robotBox(i);
  if (!b) return null;
  const span = Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1]);
  const half = tight ? Math.max(FOCUS_MIN / 2, 1.25 * span) : Math.max(CONTEXT_MIN / 2, 2 * span);
  const cx = (b.min[0] + b.max[0]) / 2, cy = (b.min[1] + b.max[1]) / 2;
  return { min: [cx - half, cy - half, 0], max: [cx + half, cy + half, Math.max(b.max[2], 0.01)] };
}
const sceneFrame = () => { const b = bounds(); return { min: [b[0], b[2], 0], max: [b[1], b[3], SCENE_TOP] }; };

// the robot's box in the 3D camera's normalised device coordinates: the corners' extent, and how much of the view's height and area it covers
function robotNdc() {
  const s = views.slot3(), b = robotBox();
  if (!s || !b) return null;
  s.camera.updateMatrixWorld(true);
  const lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
  for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) {
    const p = new THREE.Vector3(x, y, z).project(s.camera);
    lo[0] = Math.min(lo[0], p.x); hi[0] = Math.max(hi[0], p.x); lo[1] = Math.min(lo[1], p.y); hi[1] = Math.max(hi[1], p.y);
  }
  const w = (hi[0] - lo[0]) / 2, h = (hi[1] - lo[1]) / 2;
  return { min: lo, max: hi, inside: lo.every((v) => v >= -1) && hi.every((v) => v <= 1), heightFrac: h, widthFrac: w, areaFrac: w * h };
}

const CAM_VIEWS = [['iso', 'Iso'], ['top', 'Top'], ['front', 'Front'], ['side', 'Side']];
const CAM_FOLLOW = [['off', 'Off'], ['position', 'Position'], ['heading', 'Heading'], ['pose', 'Pose']];
const btns = (attr, list, tip) => list.map(([k, t]) => `<button type="button" data-${attr}="${k}" title="${tip(k, t)}">${t}</button>`).join('');
const FOLLOW_TIP = { off: 'The camera stays where you put it', position: 'The camera slides with the robot, keeping your view', heading: 'Behind the robot, turning with its heading, the horizon level', pose: 'Behind the robot, tipping with it' };

function syncCamBar() {
  for (const b of camBar.querySelectorAll('[data-follow]')) b.setAttribute('aria-pressed', String(b.dataset.follow === views.follow));
}
// every camera action ends here: the page draws the new place, the gizmo and the buttons follow
function camAct(fn) {
  camFocused = false;
  fn();
  syncCamBar();
  if (fr) adapter.draw();
  S.viewChanged();
}

function buildCamBar(stage) {
  camBar = document.createElement('div');
  camBar.id = 'camCtl'; camBar.className = 'camctl'; camBar.hidden = true;
  camBar.setAttribute('role', 'toolbar'); camBar.setAttribute('aria-label', 'Camera');
  camBar.innerHTML = `<button type="button" class="camtoggle" id="camToggle" aria-expanded="false" aria-controls="camPanel">Camera</button>
    <div class="campanel" id="camPanel"><div class="seg sm" role="group" aria-label="View">${btns('cam', CAM_VIEWS, (k, t) => `${t} view`)}</div>
    <div class="seg sm" role="group" aria-label="Fit"><button type="button" data-cam="fit-scene" title="Fit the whole scene">Fit scene</button><button type="button" data-cam="fit-robot" title="Fit the robot with its surroundings">Fit robot</button></div>
    <div class="camfol"><span class="lab" id="camFolLab">Follow</span><div class="seg sm" role="group" aria-labelledby="camFolLab">${btns('follow', CAM_FOLLOW, (k) => FOLLOW_TIP[k])}</div></div></div>`;
  camToggle = camBar.querySelector('#camToggle');
  // on a phone the controls sit behind the one button (camera.css); on a wide screen the button is hidden and the panel always shows
  const openCam = (on) => { camBar.classList.toggle('open', on); camToggle.setAttribute('aria-expanded', String(on)); };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && camBar.classList.contains('open')) { openCam(false); if (camBar.contains(document.activeElement)) camToggle.focus(); } });
  document.addEventListener('pointerdown', (e) => { if (camBar.classList.contains('open') && !camBar.contains(e.target)) openCam(false); });
  camBar.onclick = (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b === camToggle) { openCam(!camBar.classList.contains('open')); return; }
    const v = b.dataset.cam, f = b.dataset.follow;
    if (f) camAct(() => views.setFollow(f, robotAt(M.i, true)));
    else if (v === 'fit-scene') camAct(() => views.fitBox(sceneFrame()));
    else if (v === 'fit-robot') camAct(() => { const f0 = robotFrame(); if (f0) views.fitBox(f0, { keepFollow: true }); });
    else camAct(() => views.preset(v));
  };
  stage.append(camBar);
  syncCamBar();
}

// the gizmo's six axis ends (the +x, +y, +z dots it draws and the -x, -y, -z ends opposite them) are buttons: the nearest to the click, within
// 9 of the gizmo's 56 units, wins; where two ends overlap (an axis pointing at or away from the viewer) the one facing the viewer does
function gizmoSnap(e, el) {
  const a = M.view === '3d' ? views.axes3d() : null;
  if (!a) return;
  const r = el.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * 56, py = ((e.clientY - r.top) / r.height) * 56;
  let best = null;
  for (const k of ['x', 'y', 'z']) for (const sg of [1, -1]) {
    const v = a[k], d = Math.hypot(px - (28 + sg * v[0] * 20), py - (28 - sg * v[1] * 20)), depth = sg * v[2];
    if (d <= 9 && (!best || d < best.d - 1 || (Math.abs(d - best.d) <= 1 && depth > best.depth))) best = { name: (sg > 0 ? '+' : '-') + k, d, depth };
  }
  if (best) camAct(() => views.snap(best.name));
}

const adapter = {
  init(stage, shell) {
    S = shell; M = shell.M;
    canvas = document.createElement('canvas'); canvas.id = 'gl';
    stage.prepend(canvas);
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    scene = new THREE.Scene();
    readPalette();
    stg = createStage(THREE, scene, renderer, { bounds: bounds() });
    floorSaved = prefs().floor !== false;
    M.ov.floor = floorSaved;                                          // an overlay like the others: miniview.setOverlay('floor', false), the overlays menu
    setFloor(M.ov.floor);
    views = new Views(stage, renderer, scene, () => { if (fr && !rebuilding) adapter.draw(); S.viewChanged(); });
    marker = makeMarker(); scene.add(marker);
    trail = createTrail(THREE, { max: TRAIL_MAX, head: C.belief, fadeTo: stg.tokens.bg });
    setLayers(trail.object, 'body.model');
    trail.object.visible = false;
    scene.add(trail.object);
    ovSaved = { ghost: prefs().ghost !== false, open_scene: prefs().open_scene === true };     // the ghost is on and the view opens on the robot until a viewer chooses otherwise
    Object.assign(M.ov, { ghost: ovSaved.ghost, open_scene: ovSaved.open_scene, trail: true, xray: false, inspector: false });       // overlays like the floor: the Overlays menu and setOverlay
    buildInspector(stage);
    views.home3d = () => (run && fr && RW && (camFocused || !M.ov.open_scene) ? robotFrame(camTick(), camFocused) : null);       // null: the fixed iso that sees the whole scene
    const css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = new URL('../shell/camera.css', import.meta.url).href;
    document.head.append(css);
    const css2 = document.createElement('link');
    css2.rel = 'stylesheet'; css2.href = new URL('../shell/bodies.css', import.meta.url).href;
    document.head.append(css2);
    buildCamBar(stage);
    const gz = stage.querySelector('#gizmo');
    if (gz) gz.addEventListener('click', (e) => gizmoSnap(e, gz));
    views.layerMask = (view) => {
      let m = 1;
      if (FLOOR_VIEWS.has(view)) m |= 1 << STAGE_LAYER;
      for (const id of DRAWN) {
        if (view === 'eye' && NOT_IN_EYE.has(id)) continue;
        const fill = id.startsWith('fill.');     // the faint faces of boxes and pits: from above and in 3D, outlines only in a side view
        if (fill ? (view === 'top' || view === '3d' || view === 'eye' || view === 'chase') && S.shown(id === 'fill.boxes' ? 'scene.boxes' : 'scene.hazards', view) : S.shown(id, view)) m |= 1 << LAYER[id];
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
      const rank = { anomaly: -1, depth: 0, robot: 1, cell: 2 };
      const hits = rc.intersectObject(R().group, true)
        .map((h) => ({ h, sel: h.object.userData.pick?.(h) })).filter((x) => x.sel && x.sel.kind in rank)
        .sort((a, b) => rank[a.sel.kind] - rank[b.sel.kind] || (a.h.distanceToRay ?? a.h.distance) - (b.h.distanceToRay ?? b.h.distance));
      if (hits[0]?.sel.kind === 'anomaly') S.seek(hits[0].sel.t);      // a pin on the map: the playhead goes to its anomaly
      else S.pick(hits.length ? hits[0].sel : null);
    };
  },

  setScene(sc) { scn = sc; stg.setBounds(bounds()); buildSceneObjects(); },
  setRun(r, f) {
    if (M.runId !== camRun) { camRun = M.runId; camPending = true; camFocused = false; }           // a run opened: the camera frames its robot at the first draw; a rebuild of the same run leaves it
    run = r; fr = f; buildRunObjects(); buildBody();
  },
  // the run grew: add what it gained (ticks i0..i1-1, the plans and worlds that became available); nothing is rebuilt
  append(range) {
    if (!RW) return;
    RW.append(range); RM.append(range);
    for (const Rn of [RW, RM]) for (const [id, o] of Object.entries(Rn.obj)) setLayers(o, id);       // a new stretch of depth points joins its stream's layer
  },
  // the shell draws after a layout, so the draw views.setup() would trigger is skipped
  setLayout(view, frame) { if (camBar) camBar.hidden = view !== '3d'; rebuilding = true; views.setup(view, bounds(), frame); rebuilding = false; },

  draw(sync = false) {
    if (!fr || !RW) return;
    RW.update(M.i, M.t, S.cfg, S.size); RM.update(M.i, M.t, S.cfg, S.size);
    applyVis(); placeMarker(); placeStyle(); placeBody(); placeGhost(); placeTrail(); syncInspector(); placeCams();
    if (views.applyFollow(robotAt(M.i, true))) S.viewChanged();
    camPending = false;
    views.coords = M.ov.coords;
    views.render();
    S.drawn?.();
    if (sync) { const gl = renderer.getContext(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4)); }
  },
  settled: () => new Promise((res) => requestAnimationFrame(() => res())),
  resize() { views.resize(); },
  fit() { views.fit(); },
  // an evidence link's `focus=robot`: the 3D camera on the robot at the playhead, whatever the opening-camera setting; false without a 3D camera
  focusRobot() {
    const f0 = views.slot3() && robotFrame(M.i, true);
    if (!f0) return false;
    camAct(() => views.fitBox(f0, { keepFollow: true }));
    camFocused = true;                                            // the stage resizes as the panels settle, which re-homes the camera: home stays the robot until a camera action
    return true;
  },
  persist: persistOv,
  theme() {
    readPalette();
    stg.setTheme();                                                  // the clear colour, the floor, the grid, the lights and the shadows
    marker.material.map = markerTexture(stg.tokens.select, stg.tokens.bg); marker.material.needsUpdate = true;
    ghost?.setStyle({ mode: 'ghost', color: C.belief });
    trailFor = null;                                                 // the trail takes its colours again at the next draw
    if (scn) buildSceneObjects();
    if (run && fr) buildRunObjects();
    if (views.layout) { rebuilding = true; views.setup(views.layout, bounds(), views.frameName); rebuilding = false; }
  },
  describe,
  // the stage as drawn (for this repository's tests): the floor and grid shown, the lights in the scene, which views draw the stage layer, the contact shadow
  stage: () => {
    const lights = [];
    scene.traverse((o) => { if (o.isLight) lights.push([o.type, o.intensity, '#' + o.color.getHexString()]); });
    return { floor: stg.floor.visible, grid: stg.grid.visible, lights, tokens: stg.tokens, toneMapping: renderer.toneMapping,
      views: Object.fromEntries(['top', 'front', 'back', 'left', 'right', '3d', 'eye', 'chase'].map((v) => [v, !!((views.layerMask(v) >> STAGE_LAYER) & 1)])),
      shadow: shadow ? { visible: shadow.visible, pos: shadow.mesh.position.toArray(), opacity: shadow.mesh.material.opacity } : null };
  },
  // the colour the canvas has at a screen point (client pixels), read straight after a draw (before the page is composited)
  pixelAt: (cx, cy) => {
    adapter.draw();
    const gl = renderer.getContext(), r = canvas.getBoundingClientRect(), out = new Uint8Array(4);
    gl.readPixels(Math.round(cx - r.left), canvas.height - 1 - Math.round(cy - r.top), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, out);
    return [...out.slice(0, 3)];
  },
  // the belief ghost, the trail, the x-ray and the inspector as drawn (for this repository's tests)
  bodies: () => {
    const mesh = ghost?.root.getObjectByProperty('isMesh', true), g = trail.object.geometry, n = g.drawRange.count, p = g.attributes.position.array;
    const hex = (c) => '#' + c.getHexString();
    return {
      ghost: ghost ? { visible: ghost.root.visible, pos: ghost.root.position.toArray().map((v) => +v.toFixed(5)), style: ghost.style().mode,
        color: mesh ? hex(mesh.material.color) : null, opacity: mesh?.material.opacity ?? null, transparent: mesh?.material.transparent ?? null, layer: ghost.root.layers.mask } : null,
      body: body ? { style: body.style().mode, opacity: body.root.getObjectByProperty('isMesh', true)?.material.opacity ?? null } : null,
      trail: { visible: trail.object.visible, count: n, first: n ? [...p.slice(0, 3)] : null, last: n ? [...p.slice((n - 1) * 3, n * 3)] : null,
        headColour: n ? hex(new THREE.Color(...g.attributes.color.array.slice((n - 1) * 3, n * 3))) : null, layer: trail.object.layers.mask },
      inspector: { open: !inspPanel.hidden, rows: inspPanel.querySelectorAll('.insp-row').length, focused: inspHost.contains(document.activeElement), selected: insp?.selected() ?? null },
      truthPose: RW?.tpose ? [...RW.tpose.slice(M.i * 3, M.i * 3 + 3)] : null, beliefPose: RW ? [...RW.pose.slice(M.i * 3, M.i * 3 + 3)] : null,
    };
  },
  // the Robot layer as drawn: shown, where its root is, how many parts (for this repository's tests)
  body: () => (body ? { visible: body.root.visible, pos: body.root.position.toArray().map((v) => +v.toFixed(5)),
    quat: [body.root.quaternion.w, body.root.quaternion.x, body.root.quaternion.y, body.root.quaternion.z].map((v) => +v.toFixed(5)), drawn: body.drawn(),
    joints: body.healthOf(),
    joint_upper_quat: body.links.upper ? [body.links.upper.quaternion.w, body.links.upper.quaternion.y].map((v) => +v.toFixed(5)) : null,
    // per marker: [fill shown, outline shown]
    cylinders: Object.fromEntries([['truth', RW?.obj['truth.pose']], ['belief', R()?.obj['belief.pose']]].map(([k, m]) => [k, m ? [m.children[0].visible, m.children[1].visible] : null])) } : null),
  // the eye's camera as drawn (RFC-0013): where it is, which way it looks, which way is up (world frame), and which pose it was placed from
  eye: () => {
    const s = views.slots.find((q) => q.name === 'eye');
    if (!s) return null;
    const c = s.camera, f = new THREE.Vector3(), u = new THREE.Vector3(0, 1, 0).applyQuaternion(c.quaternion), r5 = (v) => v.map((n) => +n.toFixed(5));
    c.getWorldDirection(f);
    return { source: eyeAt?.source ?? null, frame_t: eyeAt?.t ?? null, position: r5(c.position.toArray()), forward: r5(f.toArray()), up: r5(u.toArray()), fov: c.fov };
  },
  eyeView: () => views.eyeView(),
  // the gaps as drawn at the playhead: the unknown cells near the plan, and the other unknown cells
  gaps: () => (RW ? { ...RW.gapCount, visible: RW.obj['world.gaps'].visible && S.shown('world.gaps') } : null),
  // the semantic map as drawn at the playhead, in the world frame: how many objects and confirmed ones (labelled), and the current sighting
  semantic: () => (RW ? { ...RW.semantic, objectsVisible: RW.obj['semantic.objects'].visible && S.shown('semantic.objects'),
    sightingVisible: RW.obj['semantic.sighting'].visible && S.shown('semantic.sighting'), labelPx: labelPx() } : null),
  // the anomaly pins as drawn in the frame being looked at: [{t, severity, source, belief, truth}] (for this repository's tests), and whether they are shown
  anomalies: () => (R() ? { pins: R().anomalies, visible: R().obj.anomalies.visible && S.shown('anomalies') } : null),
  // tick i's returns as drawn in the world frame, by kind
  returns: (i) => RW?.returnsAt(i) ?? null,
  cursor: (x, y) => views.cursorAt(x, y),
  scale: () => views.scale(),
  layerOf: (id) => 1 << LAYER[id],
  layerBits: (view) => views.layerMask(view),
  fillsDrawn: (pane) => (views.layerMask(pane) & (1 << LAYER['fill.boxes'])) !== 0,
  project: (p) => views.project(p),
  gizmo: () => views.axes3d(),
  // the fixed iso that sees the whole scene, which the deck page keeps as its only camera (for this repository's tests: the two pages' cameras are compared there)
  iso: () => {
    const home = views.home3d;
    views.home3d = () => null;
    views.fit();
    views.home3d = home;
  },
  // the 3D camera as drawn (for this repository's tests): where it is, what it looks at, its up, the follow mode, whether a move is under way, the robot's box in NDC
  camera: () => {
    const s = views.slot3();
    if (!s) return null;
    const c = s.camera, t = s.controls.target, r = robotAt(M.i);
    return { position: c.position.toArray(), target: t.toArray(), up: c.up.toArray(), fov: c.fov, aspect: c.aspect, follow: views.follow, moving: s.moving,
      robot: r ? r.position : null, ndc: robotNdc(), bar: camBar ? !camBar.hidden : false };
  },
};

createShell(adapter, { title: 'miniview - three.js', eye: true, watch: location.pathname.startsWith('/watch/') });

