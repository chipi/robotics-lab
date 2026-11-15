import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { C } from './build.js';

const ZR = [-0.7, 1.8];
// dir: where the camera sits (looking at the origin); hAxis/vAxis: what runs right / up on the screen
export const VIEWS = {
  top:   { dir: [0, 0, 1],  up: [0, 1, 0], h: 'x', hs: 1,  v: 'y', note: 'looking down, x right, y up' },
  front: { dir: [1, 0, 0],  up: [0, 0, 1], h: 'y', hs: 1,  v: 'z', note: 'from +x, y right, z up' },
  back:  { dir: [-1, 0, 0], up: [0, 0, 1], h: 'y', hs: -1, v: 'z', note: 'from -x, y left, z up' },
  left:  { dir: [0, 1, 0],  up: [0, 0, 1], h: 'x', hs: -1, v: 'z', note: 'from +y, x left, z up' },
  right: { dir: [0, -1, 0], up: [0, 0, 1], h: 'x', hs: 1,  v: 'z', note: 'from -y, x right, z up' },
  '3d':  { note: 'perspective, drag to orbit' },
};
export const LAYOUTS = {
  three: [['top', [0, 0, 0.5, 1]], ['front', [0.5, 0, 0.5, 0.5]], ['right', [0.5, 0.5, 0.5, 0.5]]],
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
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.85, 8).translate(0, 0.425, 0), new THREE.MeshBasicMaterial({ color: hex }));
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.15, 12).translate(0, 0.925, 0), new THREE.MeshBasicMaterial({ color: hex }));
  g.add(shaft, head);
  g.rotation.set(...{ x: [0, 0, -Math.PI / 2], y: [0, 0, 0], z: [Math.PI / 2, 0, 0] }[axis]);
  return g;
}

// The coordinate system of one view: metre grid in the plane the view shows, numbered along the
// bottom and left screen edges, origin axes x red / y green / z blue, labelled.
function buildFrame(name, bounds) {
  const g = new THREE.Group(), v = VIEWS[name], is3 = name === '3d';
  const [ha, va] = is3 ? ['x', 'y'] : [v.h, v.v], hs = is3 ? 1 : v.hs;
  const [h0, h1] = rng(bounds, ha), [v0, v1] = rng(bounds, va);
  const at = (a, b) => { const p = [0, 0, 0]; p['xyz'.indexOf(ha)] = a; p['xyz'.indexOf(va)] = b; return p; };
  const pos = [];
  for (let a = Math.ceil(h0); a <= h1; a++) pos.push(...at(a, v0), ...at(a, v1));
  for (let b = Math.ceil(v0); b <= v1; b++) pos.push(...at(h0, b), ...at(h1, b));
  const grid = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)),
    new THREE.LineBasicMaterial({ color: 0xdadae0 }));
  grid.position.z = is3 || va !== 'z' ? 0.003 : 0;
  g.add(grid);
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
    Object.assign(this, { host, renderer, scene, onChange, slots: [], bounds: [-4, 4, -3, 3], frameName: 'world', coords: true,
      layerMask: () => 0xffffffff, onPick: () => {} });
  }

  setup(layout, bounds, frameName) {
    this.bounds = bounds; this.frameName = frameName; this.layout = layout;
    for (const s of this.slots) { s.controls.dispose(); s.el.remove(); this.scene.remove(s.frame); }
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
    cap.innerHTML = `<b>${this.frameName}</b> frame · ${name} · ${VIEWS[name].note}`;
    el.append(lr.domElement, cap);
    this.host.append(el);
    const is3 = name === '3d';
    const camera = is3 ? new THREE.PerspectiveCamera(45, 1, 0.1, 100) : new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
    camera.up.set(...(is3 ? [0, 0, 1] : VIEWS[name].up));
    const controls = new OrbitControls(camera, el);
    controls.addEventListener('change', () => this.quiet || this.onChange());
    if (!is3) {
      controls.enableRotate = false; controls.screenSpacePanning = true; controls.zoomToCursor = true;
      controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    }
    let down = null;
    el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = el.getBoundingClientRect();
      this.onPick(this.slots.find((q) => q.el === el), ((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    });
    const frame = buildFrame(name, this.bounds);
    this.scene.add(frame);
    return { name, rect, el, lr, camera, controls, frame, is3 };
  }

  resetCamera(s) {
    const b = this.bounds, v = VIEWS[s.name], cam = s.camera;
    if (s.is3) {
      cam.position.set(-5.5, -7.5, 6.5); s.controls.target.set(0, 0, 0);
      cam.aspect = s.w / s.h; cam.updateProjectionMatrix();
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

  render() {
    const r = this.renderer;
    r.setScissorTest(true);
    for (const s of this.slots) {
      for (const o of this.slots) o.frame.visible = o === s && this.coords;
      s.camera.layers.mask = this.layerMask(s.name);
      r.setViewport(s.x, this.H - s.y - s.h, s.w, s.h);
      r.setScissor(s.x, this.H - s.y - s.h, s.w, s.h);
      r.render(this.scene, s.camera);
      s.frame.visible = this.coords;
      s.lr.render(s.frame, s.camera);
    }
    for (const s of this.slots) s.frame.visible = this.coords;
  }
}
