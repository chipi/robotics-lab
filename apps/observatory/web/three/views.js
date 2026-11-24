import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { C, RES } from './build.js';
import { presetPose, fitPose, followPose, snapFromGizmo, moveTo } from '/lib/stage/camera.js';

// after the top (or bottom) view the camera keeps z up, tipped this far (rad) off the vertical so the orbit has a defined azimuth: 0.03 degrees, far
// below what the eye sees, far above OrbitControls' own pole guard (1e-6)
const POLE_TILT = 5e-4;
const Z_UP = [0, 0, 1];

const ZR = [-0.7, 1.8];
// dir: where the camera sits (looking at the origin); hAxis/vAxis: what runs right / up on the screen
export const VIEWS = {
  top:   { dir: [0, 0, 1],  up: [0, 1, 0], h: 'x', hs: 1,  v: 'y', note: 'looking down, x right, y up' },
  front: { dir: [1, 0, 0],  up: [0, 0, 1], h: 'y', hs: 1,  v: 'z', note: 'from +x, y right, z up' },
  back:  { dir: [-1, 0, 0], up: [0, 0, 1], h: 'y', hs: -1, v: 'z', note: 'from -x, y left, z up' },
  left:  { dir: [0, 1, 0],  up: [0, 0, 1], h: 'x', hs: -1, v: 'z', note: 'from +y, x left, z up' },
  right: { dir: [0, -1, 0], up: [0, 0, 1], h: 'x', hs: 1,  v: 'z', note: 'from -y, x right, z up' },
  '3d':  { note: 'perspective, drag to orbit' },
  eye:   { note: 'the depth sensor, where it was' },
  chase: { note: 'behind and above the robot' },
};
// the perspective cameras: the orbiting 3D view, and the two placed from the run (RFC-0013) by the page at each draw
const PERSP = { '3d': 45, eye: 75, chase: 55 };
export const EYE_FOV = PERSP.eye;
export const LAYOUTS = {
  three: [['top', [0, 0, 0.5, 1]], ['front', [0.5, 0, 0.5, 0.5]], ['right', [0.5, 0.5, 0.5, 0.5]]],
  watch: [['eye', [0, 0, 1, 1]], ['top', [0.012, 0.5, 0.27, 0.42]]],        // the eye, the top view inset
};

const rng = (b, a) => a === 'x' ? [b[0], b[1]] : a === 'y' ? [b[2], b[3]] : ZR;

function label(text, pos, cls = '') {
  const d = document.createElement('div');
  d.className = 'lbl ' + cls; d.textContent = text;
  const o = new CSS2DObject(d);
  o.position.set(...pos);
  return o;
}

function arrow(axis, hex) {
  const g = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.85, 8).translate(0, 0.425, 0), new THREE.MeshBasicMaterial({ color: hex, toneMapped: false }));
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.15, 12).translate(0, 0.925, 0), new THREE.MeshBasicMaterial({ color: hex, toneMapped: false }));
  g.add(shaft, head);
  g.rotation.set(...{ x: [0, 0, -Math.PI / 2], y: [0, 0, 0], z: [Math.PI / 2, 0, 0] }[axis]);
  return g;
}

// The coordinate system of one view: metre grid in the plane the view shows, numbered along the
// bottom and left screen edges, origin axes x red / y green / z blue, labelled.
function buildFrame(name, bounds) {
  const g = new THREE.Group(), v = VIEWS[name], is3 = name in PERSP;
  const [ha, va] = is3 ? ['x', 'y'] : [v.h, v.v], hs = is3 ? 1 : v.hs;
  const [h0, h1] = rng(bounds, ha), [v0, v1] = rng(bounds, va);
  const at = (a, b) => { const p = [0, 0, 0]; p['xyz'.indexOf(ha)] = a; p['xyz'.indexOf(va)] = b; return p; };
  const pos = [];
  for (let a = Math.ceil(h0); a <= h1; a++) pos.push(...at(a, v0), ...at(a, v1));
  for (let b = Math.ceil(v0); b <= v1; b++) pos.push(...at(h0, b), ...at(h1, b));
  // the 3D and chase views have the stage's grid (it fades out, on the stage layer); the eye and the flat views keep this one
  if (!is3 || name === 'eye') {
    const grid = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)),
      new THREE.LineBasicMaterial({ color: C.grid, toneMapped: false }));
    grid.position.z = is3 || va !== 'z' ? 0.003 : 0;
    g.add(grid);
  }
  const hEdge = hs > 0 ? h0 - 0.3 : h1 + 0.3, vEdge = v0 - 0.3;
  for (let a = Math.ceil(h0); a <= h1; a++) g.add(label(String(a), at(a, vEdge)));
  for (let b = Math.ceil(v0); b <= v1; b++) g.add(label(String(b), at(hEdge, b)));
  if (is3) for (const z of [0.5, 1, 1.5]) g.add(label('z ' + z, [-0.25, 0, z]));
  for (const [ax, hex] of [['x', C.x], ['y', C.y], ['z', C.z]]) {
    g.add(arrow(ax, hex));
    const t = [0, 0, 0]; t['xyz'.indexOf(ax)] = 1.2;
    if (ax === 'z' && !is3 && va !== 'z') t[0] = t[1] = 0.12;
    g.add(label(ax, t, 'ax'));
  }
  g.add(label('0', [-0.12, -0.12, 0]));
  return g;
}

export class Views {
  constructor(host, renderer, scene, onChange) {
    // home3d() -> a box { min, max } the 3D view opens on (null: the fixed iso), set by the page once it knows the robot; follow: off|position|heading|pose
    Object.assign(this, { host, renderer, scene, onChange, slots: [], bounds: [-4, 4, -3, 3], frameName: 'world', coords: true,
      layerMask: () => ~0, onPick: () => {}, home3d: () => null, follow: 'off' });
  }

  setup(layout, bounds, frameName) {
    this.bounds = bounds; this.frameName = frameName; this.layout = layout;
    for (const s of this.slots) { s.cancel?.(); s.controls.dispose(); s.el.remove(); this.scene.remove(s.frame); }
    const list = LAYOUTS[layout] || [[layout, [0, 0, 1, 1]]];
    this.slots = list.map(([name, rect]) => this.makeSlot(name, rect));
    this.resize();
  }

  makeSlot(name, rect) {
    const el = document.createElement('div');
    el.className = 'slot';
    const lr = new CSS2DRenderer();
    lr.domElement.className = 'labels';
    const cap = document.createElement('div');
    cap.className = 'cap';
    cap.textContent = `${this.frameName} · ${name}`;
    cap.style.top = rect[1] === 0 ? '32px' : '6px';
    if (!LAYOUTS[this.layout]) cap.hidden = true;
    el.append(lr.domElement, cap);
    this.host.append(el);
    const is3 = name in PERSP;
    if (this.layout === 'watch' && rect[2] < 1) el.style.zIndex = 3;           // an inset stays over the HUD's darkness
    const camera = is3 ? new THREE.PerspectiveCamera(PERSP[name], 1, name === '3d' ? 0.1 : 0.02, 100) : new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
    camera.up.set(...(is3 ? [0, 0, 1] : VIEWS[name].up));
    const controls = new OrbitControls(camera, el);
    let slot = null;
    controls.addEventListener('change', () => {
      if (this.quiet) return;
      if (slot && !slot.moving) slot.offset = camera.position.clone().sub(controls.target).toArray();       // the orbit the viewer chose: position-follow keeps it
      this.onChange();
    });
    if (name === 'eye' || name === 'chase') controls.enabled = false;
    if (name === '3d') controls.enabled = this.follow === 'off' || this.follow === 'position';
    if (!is3) {
      controls.enableRotate = false; controls.screenSpacePanning = true; controls.zoomToCursor = true;
      controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    }
    let down = null;
    el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; slot?.cancel?.(); });     // a hand on the view stops a camera move
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = el.getBoundingClientRect();
      this.onPick(this.slots.find((q) => q.el === el), ((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    });
    const frame = buildFrame(name, this.bounds);
    this.scene.add(frame);
    slot = { name, rect, el, lr, camera, controls, frame, is3, moving: false, cancel: null, offset: null };
    return slot;
  }

  slot3() { return this.slots.find((q) => q.name === '3d') ?? null; }

  // ---- the 3D camera (U12): presets, fit, follow. Poses come from /lib/stage/camera.js; this is the only place that moves the camera ----
  // move the 3D camera to a pose: tweened over --dur-base (at once under reduced motion). A pose that is not z-up (the top view) ends z-up, see level()
  go(s, pose) {
    s.cancel?.();
    s.moving = true;
    const done = () => {
      s.moving = false; s.cancel = null;
      if (pose.up && pose.up[2] < 0.999) this.level(s);
      s.offset = s.camera.position.clone().sub(s.controls.target).toArray();
      this.onChange();
    };
    const stop = moveTo(s.camera, s.controls, pose, { onDone: done });
    if (s.moving) s.cancel = () => { stop(); s.moving = false; s.cancel = null; };       // under reduced motion done() has run already
  }

  // a horizon tipped by the 'heading' and 'pose' follow ends when the viewer asks for a view of their own
  levelTipped() { if (this.follow === 'heading' || this.follow === 'pose') this.setFollow('off'); }

  // z up again, from where the camera is: a view straight down (or up) is tipped POLE_TILT off the vertical toward the side its screen-up needs, so
  // it looks the same and orbiting continues around z (drag turns the view about the vertical, tips it up and down) instead of about the page's y
  level(s) {
    const t = s.controls.target.toArray(), p = s.camera.position.toArray(), off = p.map((v, i) => v - t[i]), d = Math.hypot(...off);
    if (Math.abs(off[2]) / d > 1 - 1e-6) {
      const sgn = Math.sign(off[2]);
      const o = [0, -sgn * Math.sin(POLE_TILT) * d, sgn * Math.cos(POLE_TILT) * d];
      this.place3(s, { position: t.map((v, i) => v + o[i]), target: t, up: Z_UP });
    } else this.place3(s, { position: p, target: t, up: Z_UP });
  }

  // a pose now, without the page redrawing for it
  place3(s, pose) {
    const q = this.quiet;
    this.quiet = true;
    moveTo(s.camera, s.controls, pose, { ms: 0 });
    this.quiet = q;
  }

  look(s) {
    const off = s.camera.position.clone().sub(s.controls.target);
    return off.length() > 1e-9 ? off.normalize().toArray() : [-5.5, -7.5, 6.5].map((v) => v / Math.hypot(-5.5, -7.5, 6.5));
  }

  // the 3D camera on a preset's axis, from where the target and the distance are now
  preset(name) {
    const s = this.slot3();
    if (!s) return false;
    this.levelTipped();
    this.go(s, presetPose(name, { target: s.controls.target.toArray(), distance: s.camera.position.distanceTo(s.controls.target) }));
    return true;
  }

  // a click on the axes gizmo: '+x', '-y', '+z', ...
  snap(axis) {
    const s = this.slot3();
    if (!s) return false;
    this.levelTipped();
    this.go(s, snapFromGizmo(axis, { target: s.controls.target.toArray(), distance: s.camera.position.distanceTo(s.controls.target) }));
    return true;
  }

  // the whole box in view, looking the way the camera looks now
  fitBox(box, { keepFollow = false } = {}) {
    const s = this.slot3();
    if (!s) return false;
    if (keepFollow) this.levelTipped(); else this.setFollow('off');
    this.go(s, fitPose(s.camera, box, { dir: this.look(s) }));
    return true;
  }

  // follow: 'off', or 'position' (the camera slides with the robot, keeping its offset and its orientation), 'heading' (behind it, horizon level),
  // 'pose' (behind it, tipping with it). robot: { position, yaw, quaternion? } now. Orbiting works for off and position only
  setFollow(mode, robot) {
    const prev = this.follow, s = this.slot3();
    this.follow = mode;
    if (!s) return;
    s.controls.enabled = mode === 'off' || mode === 'position';
    if (mode === prev) return;
    if (mode === 'off') { if (prev === 'heading' || prev === 'pose') { s.cancel?.(); this.level(s); } return; }
    if (!robot) return;
    s.cancel?.();
    if (mode === 'position') {
      const target = robot.position;
      s.offset = s.camera.position.toArray().map((v, i) => v - target[i]);
      this.go(s, followPose('position', robot, { offset: s.offset }));
    } else this.go(s, followPose(mode, robot));
  }

  // each draw: the camera goes where the follow mode says (not while it is moving to its first place)
  applyFollow(robot) {
    const s = this.slot3();
    if (!s || this.follow === 'off' || s.moving || !robot) return false;
    if (!s.offset) s.offset = s.camera.position.clone().sub(s.controls.target).toArray();
    this.place3(s, followPose(this.follow, robot, { offset: s.offset }));
    return true;
  }

  resetCamera(s) {
    const b = this.bounds, v = VIEWS[s.name], cam = s.camera;
    if (s.name === 'eye' || s.name === 'chase') {
      cam.aspect = s.w / s.h; cam.updateProjectionMatrix();                      // where it stands is the page's, at each draw
      return;
    }
    if (s.is3) {
      cam.aspect = s.w / s.h; cam.updateProjectionMatrix();
      s.cancel?.();
      const home = this.home3d();
      if (home) {                                                               // the page knows the robot: open on it, with its surroundings
        this.place3(s, fitPose(cam, home, { preset: 'iso' }));
        s.offset = cam.position.clone().sub(s.controls.target).toArray();
        return;
      }
      // 9.4 m of height fill the pane from 11.35 m away; 11 m leave the grid numbers clear of the legend and the readout
      const k = 11 / 9.4;
      this.place3(s, { position: [-5.5 * k, -7.5 * k, 6.5 * k], target: [0, 0, 0], up: Z_UP });
      s.offset = null;
    } else {
      const [h0, h1] = rng(b, v.h), [v0, v1] = rng(b, v.v), m = 0.7;
      const cx = (h0 + h1) / 2, cy = (v0 + v1) / 2;
      const hh = Math.max((h1 - h0) / 2 + m, ((v1 - v0) / 2 + m) * s.w / s.h), hv = hh * s.h / s.w;
      cam.left = -hh; cam.right = hh; cam.top = hv; cam.bottom = -hv; cam.zoom = 1; cam.updateProjectionMatrix();
      const c = [0, 0, 0]; c['xyz'.indexOf(v.h)] = cx; c['xyz'.indexOf(v.v)] = cy;
      cam.position.set(c[0] + v.dir[0] * 50, c[1] + v.dir[1] * 50, c[2] + v.dir[2] * 50);
      s.controls.target.set(...c);
    }
    s.controls.update();
  }

  resize() {
    const W = this.host.clientWidth, H = this.host.clientHeight;
    if (!W || !H) return;
    this.W = W; this.H = H; this.quiet = true;
    for (const s of this.slots) {
      const [fx, fy, fw, fh] = s.rect;
      s.x = Math.round(fx * W); s.y = Math.round(fy * H); s.w = Math.round(fw * W); s.h = Math.round(fh * H);
      Object.assign(s.el.style, { left: s.x + 'px', top: s.y + 'px', width: s.w + 'px', height: s.h + 'px' });
      s.lr.setSize(s.w - 2, s.h - 2);
      this.resetCamera(s);
    }
    this.quiet = false;
    this.renderer.setSize(W, H, false);
    this.onChange();
  }

  // metres per pixel at the view's target, to turn a pixel tolerance into a pick threshold
  metresPerPx(s) {
    const c = s.camera;
    if (!s.is3) return (c.right - c.left) / c.zoom / s.w;
    return c.position.distanceTo(s.controls.target) * 2 * Math.tan(c.fov * Math.PI / 360) / s.h;
  }

  // put a placed camera (eye, chase) where the page says: position, and the sensor's axes (ahead, up) or a point to look at
  place(name, { pos, forward, up, target }) {
    const s = this.slots.find((q) => q.name === name);
    if (!s) return null;
    const c = s.camera;
    c.position.set(...pos);
    c.up.set(...(up || [0, 0, 1]));
    c.lookAt(...(target || pos.map((v, k) => v + forward[k])));
    c.updateMatrixWorld(true);
    return s;
  }

  // the placed camera's field of view and its pane's height in pixels, for what is drawn over it
  eyeView() {
    const s = this.slots.find((q) => q.name === 'eye');
    return s && s.h ? { fov: s.camera.fov, h: s.h } : null;
  }

  fit() {
    for (const s of this.slots) this.resetCamera(s);
    this.onChange();
  }

  // the world coordinates under a screen point: the two axes an orthographic view shows, or in the 3D view the point
  // of the floor (z = 0) under the pointer (null values where the ray misses it); null outside every pane
  cursorAt(cx, cy) {
    for (const s of this.slots) {
      const r = s.el.getBoundingClientRect();
      if (cx < r.left || cx > r.right || cy < r.top || cy > r.bottom) continue;
      const nx = ((cx - r.left) / r.width) * 2 - 1, ny = -((cy - r.top) / r.height) * 2 + 1;
      if (s.is3) {
        const rc = new THREE.Raycaster(), hit = new THREE.Vector3();
        rc.setFromCamera({ x: nx, y: ny }, s.camera);
        const ok = rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), hit);
        return { axes: ['x', 'y'], v: ok ? [hit.x, hit.y] : [null, null], note: 'floor z 0' };
      }
      const p = new THREE.Vector3(nx, ny, 0).unproject(s.camera), v = VIEWS[s.name];
      return { axes: [v.h, v.v], v: [p[v.h], p[v.v]] };
    }
    return null;
  }

  // the screen position (client pixels) of a world point in the first pane
  project(p) {
    const s = this.slots[0];
    if (!s) return null;
    const v = new THREE.Vector3(...p).project(s.camera), r = s.el.getBoundingClientRect();
    return [r.left + ((v.x + 1) / 2) * r.width, r.top + ((1 - v.y) / 2) * r.height];
  }

  // pixels per metre of the first orthographic pane (the top view in the three-view layout), or null
  scale() {
    const s = this.slots[0];
    return s && !s.is3 && s.w ? 1 / this.metresPerPx(s) : null;
  }

  // the world axes in the 3D view's camera space (x right, y up, z toward the viewer)
  axes3d() {
    const s = this.slots.find((q) => q.is3);
    if (!s) return null;
    const m = s.camera.matrixWorldInverse, d = (x, y, z) => new THREE.Vector3(x, y, z).transformDirection(m).toArray();
    return { x: d(1, 0, 0), y: d(0, 1, 0), z: d(0, 0, 1) };
  }

  render() {
    const r = this.renderer;
    r.setScissorTest(true);
    for (const s of this.slots) {
      for (const o of this.slots) o.frame.visible = o === s && this.coords;
      s.camera.layers.mask = this.layerMask(s.name);
      r.setViewport(s.x, this.H - s.y - s.h, s.w, s.h);
      r.setScissor(s.x, this.H - s.y - s.h, s.w, s.h);
      RES.value.set(s.w, s.h);
      r.render(this.scene, s.camera);
      s.frame.visible = this.coords;
      s.lr.render(s.frame, s.camera);
    }
    for (const s of this.slots) s.frame.visible = this.coords;
  }
}
