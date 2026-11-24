// The body of the robot on the robot page (RFC-0024 step 2, RFC-0023 D4, look-and-feel U21): libs/web's body component on the shared 3D stage
// (floor, contact shadow, theme lights, tone mapping, faded grid; z up), posed from the robot's live joint angles, each joint coloured by its
// worst live alarm. Camera presets, Fit robot, an x-ray toggle and the model inspector (key i, Esc closes) sit over the view. A module, loaded by
// app.js only when a robot with a description is opened, so the overview (a phone's first page) never fetches three.js or the stage.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createBody, jointStates, tokenColors } from '/lib/body/body.js';
import { createStage, STAGE_LAYER } from '/lib/stage/stage.js';
import { presetPose, fitPose, moveTo } from '/lib/stage/camera.js';
import { mountInspector } from '/lib/body/inspector.js';

let view = null;      // the one mounted body: { id, box, body, renderer, camera, controls, stage, shadow, pose, states, ... }

// after the top view the camera keeps z up, tipped this far (rad) off the vertical so the orbit has a defined azimuth (as the Observatory's views do)
const POLE_TILT = 5e-4;
const Z_UP = [0, 0, 1];
const PRESETS = [['iso', 'Iso'], ['top', 'Top'], ['front', 'Front'], ['side', 'Side']];

// the grid's metres per line: about ten to twenty lines across the floor, whatever the robot's size
const gridStep = (half) => [0.02, 0.05, 0.1, 0.25, 0.5, 1].find((s) => half / s <= 10) ?? 1;

const typing = (t) => t instanceof Element && (t.closest('input, textarea, select, [contenteditable]') !== null);

function frame(v) {
  const { renderer, scene, camera, box } = v;
  const w = box.clientWidth, h = box.clientHeight;
  if (w && h) {
    if (renderer.domElement.width !== Math.round(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.round(h * renderer.getPixelRatio())) renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  v.shadow.update();
  renderer.render(scene, camera);
}

function draw(v) {
  if (v.queued) return;
  v.queued = true;
  requestAnimationFrame(() => { v.queued = false; if (view === v) frame(v); });
}

const robotBox = (v) => new THREE.Box3().setFromObject(v.body.root);

// z up again from where the camera is; a view straight down is tipped POLE_TILT off the vertical so orbiting goes on around z
function level(v) {
  const t = v.controls.target.toArray(), p = v.camera.position.toArray(), off = p.map((x, i) => x - t[i]), d = Math.hypot(...off);
  let pose = { position: p, target: t, up: Z_UP };
  if (Math.abs(off[2]) / d > 1 - 1e-6) {
    const sgn = Math.sign(off[2]);
    pose = { position: [t[0], t[1] - sgn * Math.sin(POLE_TILT) * d, t[2] + sgn * Math.cos(POLE_TILT) * d], target: t, up: Z_UP };
  }
  moveTo(v.camera, v.controls, pose, { ms: 0 });
}

function go(v, pose, preset) {
  v.cancel?.();
  v.moving = true;
  v.preset = preset;
  syncTools(v);
  const done = () => { v.moving = false; v.cancel = null; if (pose.up && pose.up[2] < 0.999) level(v); draw(v); };
  const stop = moveTo(v.camera, v.controls, pose, { onDone: done });
  if (v.moving) v.cancel = () => { stop(); v.moving = false; v.cancel = null; };      // under reduced motion done() has run already
}

function lookDir(v) {
  const off = v.camera.position.clone().sub(v.controls.target);
  return off.length() > 1e-9 ? off.normalize().toArray() : null;
}

function fitRobot(v) {
  const b = robotBox(v);
  if (b.isEmpty()) return;
  frame(v);                                                       // the aspect is the pane's now
  go(v, fitPose(v.camera, b, { dir: lookDir(v) ?? undefined, preset: 'iso' }), v.preset);
}

function setPreset(v, name) {
  const b = robotBox(v);
  if (b.isEmpty()) return;
  frame(v);
  go(v, fitPose(v.camera, b, { preset: name }), name);
}

function syncTools(v) {
  for (const b of v.tools.querySelectorAll('[data-preset]')) b.setAttribute('aria-pressed', String(b.dataset.preset === v.preset));
  v.xrayBtn.setAttribute('aria-pressed', String(v.xray));
  v.inspBtn.setAttribute('aria-pressed', String(!v.insp.hidden));
}

function setXray(v, on) {
  v.xray = on;
  v.body.setStyle({ mode: on ? 'xray' : 'solid' });
  syncTools(v);
  draw(v);
}

// the inspector mounts on first use and is only repainted when its data changed, so a row the viewer is on is not rebuilt under them
function paintInspector(v) {
  if (!v.inspector || v.insp.hidden) return;
  const sig = JSON.stringify([v.pose, v.states]);
  if (sig === v.inspSig) return;
  v.inspSig = sig;
  v.inspector.update(v.pose);
}

function setInspector(v, open) {
  if (!open) {
    v.insp.hidden = true;
    v.body.highlight(null);
    v.inspector?.select(null);
  } else {
    if (!v.inspector) v.inspector = mountInspector(v.inspList, v.body, { onSelect: (link) => { v.body.highlight(link); draw(v); } });
    v.insp.hidden = false;
    v.inspSig = null;
    paintInspector(v);
    v.inspList.querySelector('.insp-list')?.focus();
  }
  syncTools(v);
  draw(v);
}

function tools(v) {
  const bar = document.createElement('div');
  bar.className = 'bodytools'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Camera and view');
  const btn = (text, attrs, title) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'ui-btn'; b.textContent = text; b.title = title;
    for (const [k, val] of Object.entries(attrs)) b.setAttribute(k, val);
    return b;
  };
  for (const [k, t] of PRESETS) bar.append(btn(t, { 'data-preset': k, 'aria-pressed': 'false' }, `${t} view`));
  bar.append(btn('Fit robot', { 'data-act': 'fit' }, 'Frame the whole robot'));
  v.xrayBtn = btn('X-ray', { 'data-act': 'xray', 'aria-pressed': 'false' }, 'See through the body');
  v.inspBtn = btn('Inspector', { 'data-act': 'inspector', 'aria-pressed': 'false', 'aria-keyshortcuts': 'i' }, 'The model\'s parts (i)');
  bar.append(v.xrayBtn, v.inspBtn);
  bar.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.preset) setPreset(v, b.dataset.preset);
    else if (b.dataset.act === 'fit') fitRobot(v);
    else if (b.dataset.act === 'xray') setXray(v, !v.xray);
    else if (b.dataset.act === 'inspector') setInspector(v, v.insp.hidden);
  });
  v.tools = bar;
}

// the keys: i toggles the inspector (never from a text field), Escape closes it
function keys(e) {
  const v = view;
  if (!v || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
  if (e.key === 'i' && v.box.offsetParent !== null) { e.preventDefault(); setInspector(v, v.insp.hidden); }
  else if (e.key === 'Escape' && !v.insp.hidden) { e.preventDefault(); setInspector(v, false); }
}

// the stage follows the page's theme: its tokens, the lights, and the health colours (which are status tokens)
function retheme(v) {
  v.stage.setTheme();
  v.body.health(v.states, tokenColors());
  draw(v);
}

// Mount the body of robot `id` (its description `desc`, meshes under API `api`) in `box`; the same robot again keeps what is there.
export async function mount(box, id, desc, api, init) {
  if (view?.id === id && view.box === box) return;
  unmount();
  const body = await createBody(THREE, desc, api, init);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-label', 'The robot\'s body, drag to turn it');
  const scene = new THREE.Scene();
  scene.add(body.root);
  body.pose({});
  const feet = new THREE.Box3().setFromObject(body.root);
  if (!feet.isEmpty()) body.root.position.z -= feet.min.z;         // the lowest point stands on the floor
  const bounds = new THREE.Box3().setFromObject(body.root), centre = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
  const half = Math.max(0.5, 2 * Math.max(size.x, size.y));
  const stage = createStage(THREE, scene, renderer, { bounds: [centre.x - half, centre.x + half, centre.y - half, centre.y + half], step: gridStep(half) });
  const shadow = stage.contactShadow(body.root);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 50);
  camera.up.set(...Z_UP);                                         // a description is z up
  camera.layers.enable(STAGE_LAYER);
  const controls = new OrbitControls(camera, renderer.domElement);
  const v = { id, box, body, renderer, scene, camera, controls, stage, shadow, pose: {}, states: {}, queued: false, preset: 'iso', xray: false, moving: false, cancel: null };
  tools(v);
  v.insp = document.createElement('div');
  v.insp.className = 'bodyinsp'; v.insp.hidden = true; v.insp.setAttribute('role', 'region'); v.insp.setAttribute('aria-label', 'Model inspector');
  v.inspList = document.createElement('div');
  v.insp.append(v.inspList);
  v.inspBtn.setAttribute('aria-controls', 'rp-body-insp');
  v.insp.id = 'rp-body-insp';
  controls.addEventListener('change', () => draw(v));
  controls.addEventListener('start', () => { v.cancel?.(); v.preset = null; syncTools(v); });     // a hand on the view stops a move and leaves the preset
  v.watch = new ResizeObserver(() => draw(v));
  v.watch.observe(box);
  v.theme = new MutationObserver(() => retheme(v));
  v.theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  v.media = matchMedia('(prefers-color-scheme: dark)');
  v.mediaFn = () => retheme(v);
  v.media.addEventListener('change', v.mediaFn);
  document.addEventListener('keydown', keys);
  box.replaceChildren(renderer.domElement, v.tools, v.insp);
  view = v;
  controls.target.copy(centre);
  frame(v);                                                       // the aspect is the pane's before the first fit
  moveTo(camera, controls, fitPose(camera, bounds, { preset: 'iso' }), { ms: 0 });
  syncTools(v);
  draw(v);
}

export function unmount() {
  if (!view) return;
  const v = view;
  view = null;
  v.cancel?.();
  document.removeEventListener('keydown', keys);
  v.media.removeEventListener('change', v.mediaFn);
  v.theme.disconnect();
  v.watch.disconnect();
  v.inspector?.dispose();
  v.shadow.dispose();
  v.stage.dispose();
  v.body.dispose();
  v.controls.dispose();
  v.renderer.dispose();
  v.box.replaceChildren();
}

// The live joint angles ({ name: radians }) and the alarms ([{ t, a }], wall seconds) of the robot, now: pose and colour the body. Returns the
// joints that are not ok, { joint: { state, anomaly } }, for the page to say in words.
export function update(joints, alarms, now, within) {
  if (!view) return {};
  const states = jointStates(alarms, now, within);
  view.pose = joints || {};
  view.body.pose(view.pose);
  view.body.health(states, tokenColors());
  view.states = states;
  paintInspector(view);
  draw(view);
  return states;
}

// what is drawn, for this repository's tests: the parts, the meshes, the extent in metres, the joints last posed with, each link's turn, each joint's state and colour
export function state() {
  if (!view) return null;
  const size = new THREE.Box3().setFromObject(view.body.root).getSize(new THREE.Vector3());
  return { drawn: view.body.drawn(), meshes: Object.values(view.body.links).reduce((n, g) => n + g.children.length, 0), size: [size.x, size.y, size.z], pose: view.pose, joints: view.body.healthOf(),
    stage: stageState(view), camera: cameraState(view), xray: view.xray, style: view.body.style().mode, inspector: { open: !view.insp.hidden, rows: view.inspList.querySelectorAll('.insp-row').length, selected: view.inspector?.selected() ?? null },
    links: Object.fromEntries(Object.entries(view.body.links).map(([n, g]) => [n, { quat: [g.quaternion.w, g.quaternion.x, g.quaternion.y, g.quaternion.z].map((x) => +x.toFixed(5)) }])) };
}

function stageState(v) {
  const lights = [];
  v.scene.traverse((o) => { if (o.isLight) lights.push(o.type); });
  return { floor: v.stage.floor.visible && v.stage.floor.parent === v.scene, grid: v.stage.grid.visible, shadow: v.shadow.visible, shadowOpacity: v.shadow.mesh.material.opacity,
    lights, toneMapping: v.renderer.toneMapping, neutral: v.renderer.toneMapping === THREE.NeutralToneMapping, cameraSeesStage: ((v.camera.layers.mask >> STAGE_LAYER) & 1) === 1, tokens: v.stage.tokens };
}

// where the camera is, what it looks at, its up, the preset, and the robot's box in normalised device coordinates (inside: every corner in view)
function cameraState(v) {
  const b = robotBox(v), lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
  v.camera.updateMatrixWorld(true);
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) {
    const p = new THREE.Vector3(x, y, z).project(v.camera);
    lo[0] = Math.min(lo[0], p.x); hi[0] = Math.max(hi[0], p.x); lo[1] = Math.min(lo[1], p.y); hi[1] = Math.max(hi[1], p.y);
  }
  return { position: v.camera.position.toArray(), target: v.controls.target.toArray(), up: v.camera.up.toArray(), preset: v.preset, moving: v.moving,
    ndc: { min: lo, max: hi, inside: lo.every((x) => x >= -1) && hi.every((x) => x <= 1), height: (hi[1] - lo[1]) / 2, width: (hi[0] - lo[0]) / 2 } };
}
