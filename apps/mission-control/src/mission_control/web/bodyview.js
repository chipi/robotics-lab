// The robot's body on the robot page (RFC-0024 step 2, RFC-0023 D4): libs/web's body component in a small three.js view, posed from the
// robot's live joint angles, each joint coloured by its worst live alarm. A module, loaded by app.js only when a robot with a description
// is opened, so the overview (a phone's first page) never fetches three.js.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createBody, jointStates, tokenColors } from '/lib/body/body.js';

let view = null;      // the one mounted body: { id, box, body, renderer, camera, controls, pose, states }

function frame(v) {
  const { renderer, scene, camera, box } = v;
  const w = box.clientWidth, h = box.clientHeight;
  if (w && h) {
    if (renderer.domElement.width !== Math.round(w * renderer.getPixelRatio()) || renderer.domElement.height !== Math.round(h * renderer.getPixelRatio())) renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  renderer.render(scene, camera);
}

function draw(v) {
  if (v.queued) return;
  v.queued = true;
  requestAnimationFrame(() => { v.queued = false; if (view === v) frame(v); });
}

// Mount the body of robot `id` (its description `desc`, meshes under API `api`) in `box`; the same robot again keeps what is there.
export async function mount(box, id, desc, api, init) {
  if (view?.id === id && view.box === box) return;
  unmount();
  const body = await createBody(THREE, desc, api, init);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-label', 'The robot\'s body, drag to turn it');
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(1, -1, 2);
  scene.add(sun, body.root);
  body.pose({});
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 50);
  camera.up.set(0, 0, 1);                                         // a description is z up
  const bounds = new THREE.Box3().setFromObject(body.root), centre = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
  const reach = Math.max(size.x, size.y, size.z, 0.05) * 0.75 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  camera.position.copy(centre).add(new THREE.Vector3(0.8, -1.0, 0.5).normalize().multiplyScalar(reach));
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(centre);
  controls.update();
  const v = { id, box, body, renderer, scene, camera, controls, pose: {}, queued: false };
  controls.addEventListener('change', () => draw(v));
  v.watch = new ResizeObserver(() => draw(v));
  v.watch.observe(box);
  box.replaceChildren(renderer.domElement);
  view = v;
  draw(v);
}

export function unmount() {
  if (!view) return;
  view.watch.disconnect();
  view.controls.dispose();
  view.renderer.dispose();
  view.box.replaceChildren();
  view = null;
}

// The live joint angles ({ name: radians }) and the alarms ([{ t, a }], wall seconds) of the robot, now: pose and colour the body. Returns the
// joints that are not ok, { joint: { state, anomaly } }, for the page to say in words.
export function update(joints, alarms, now, within) {
  if (!view) return {};
  const states = jointStates(alarms, now, within);
  view.pose = joints || {};
  view.body.pose(view.pose);
  view.body.health(states, tokenColors());
  draw(view);
  return states;
}

// what is drawn, for this repository's tests: the parts, the meshes, the extent in metres, the joints last posed with, each link's turn, each joint's state and colour
export function state() {
  if (!view) return null;
  const size = new THREE.Box3().setFromObject(view.body.root).getSize(new THREE.Vector3());
  return { drawn: view.body.drawn(), meshes: Object.values(view.body.links).reduce((n, g) => n + g.children.length, 0), size: [size.x, size.y, size.z], pose: view.pose, joints: view.body.healthOf(),
    links: Object.fromEntries(Object.entries(view.body.links).map(([n, g]) => [n, { quat: [g.quaternion.w, g.quaternion.x, g.quaternion.y, g.quaternion.z].map((x) => +x.toFixed(5)) }])) };
}
