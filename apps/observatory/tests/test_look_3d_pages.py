"""The shared 3D stage (step 4.5, unit U4: libs/web/stage/stage.js, camera.js, trail.js) in a bare WebGL canvas in headless Chromium, no
page of the apps: the modules are loaded from /lib/ and driven with the vendored three.js. Camera presets point where the plan says (z up
and y up); fitPose puts all 8 corners of a box inside the view with the margin; follow modes keep orientation, keep a level horizon, or
follow roll and pitch; moveTo is immediate under reduced motion and tweens otherwise; the floor is the --scene-floor colour on screen (read
back from the canvas, within 2/255 per channel: the floor is not tone mapped, so the only difference is rounding through linear light), differs in
dark and light, and the clear colour is --scene-bg; lights exist with no body; the grid fades by vertex colour; the contact shadow darkens
the floor around a body; the trail's head and tail colours differ. Then the Observatory's three.js page (U11): in the 3D and chase layouts the floor
is on screen in the --scene-floor colour (light and dark differ), in the eye and the top layouts it is not drawn; the stage's lights exist before a body
loads; the contact shadow follows the body; the floor overlay turns it off and the choice is remembered; and build.js, views.js and app.js hold no
colour literal (the one allowed: the white of the anomaly pins' texture mask). Needs the system Chromium and Playwright.
Run: cd apps/observatory && uv run python tests/test_look_3d_pages.py"""

import atexit
import math
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

ROBOTS = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, ROBOTS, True)
os.environ["MINIVIEW_ROBOTS"] = str(ROBOTS)

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, catalog, make_run, scene, serve, tick  # noqa: E402
from observatory.shots import launch  # noqa: E402

# a one-link robot with a box mesh, for the page section: the body the contact shadow goes under
_v = [(x, y, z) for x in (-0.06, 0.06) for y in (-0.06, 0.06) for z in (0.0, 0.1)]
_f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
(ROBOTS / "arm" / "meshes").mkdir(parents=True)
(ROBOTS / "arm" / "robot.urdf").write_text('<robot name="arm"><link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry>'
                                           '<material name="b"><color rgba="0.8 0.6 0.3 1"/></material></visual></link></robot>')
(ROBOTS / "arm" / "robot.json").write_text('{"label": "Test arm", "stand_z": 0.0}')
(ROBOTS / "arm" / "meshes" / "base.stl").write_bytes(bytes(80) + struct.pack("<I", len(_f)) + b"".join(
    struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *_v[i]) for i in f) + struct.pack("<H", 0) for f in _f))

_checks = Checks("LOOK 3D PAGES")


def check(name, cond, detail=""):
    _checks(name, cond, "" if cond else detail)  # the detail is for a failure; a pass line stays short

SETUP = """async () => {
  const THREE = await import('/lib/vendor/three.module.js');
  const { OrbitControls } = await import('/lib/vendor/controls/OrbitControls.js');
  const S = await import('/lib/stage/stage.js');
  const C = await import('/lib/stage/camera.js');
  const T = await import('/lib/stage/trail.js');
  const M = await import('/lib/motion.js');
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 128; document.body.append(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, preserveDrawingBuffer: true });
  renderer.setSize(128, 128, false);
  const scene = new THREE.Scene();
  const approx = (a, b, e = 1e-6) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= e);
  const unit = (v) => { const l = Math.hypot(...v); return v.map((n) => n / l); };
  // an orthographic camera 1 m across looking straight down (or at the y-up floor) at p: the pixel under the middle is the floor there
  const eyeOver = (p, plane = 'xy', layers = [0, S.STAGE_LAYER]) => {
    const cam = new THREE.OrthographicCamera(-0.5, 0.5, 0.5, -0.5, 0.1, 100);
    cam.position.set(...(plane === 'xy' ? [p[0], p[1], 10] : [p[0], 10, p[1]]));
    cam.up.set(...(plane === 'xy' ? [0, 1, 0] : [0, 0, -1]));
    cam.lookAt(...(plane === 'xy' ? [p[0], p[1], 0] : [p[0], 0, p[1]]));
    cam.layers.mask = 0; for (const l of layers) cam.layers.enable(l);
    cam.updateMatrixWorld();
    return cam;
  };
  const pixel = (cam, col = 64, row = 64) => {
    renderer.render(scene, cam);
    const gl = renderer.getContext(), out = new Uint8Array(4);
    gl.readPixels(col, 128 - 1 - row, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, out);
    return [...out.slice(0, 3)];
  };
  const place = (cam, pose) => { cam.position.set(...pose.position); cam.up.set(...pose.up); cam.lookAt(...pose.target); cam.updateMatrixWorld(true); cam.updateProjectionMatrix(); };
  window.L = { THREE, OrbitControls, S, C, T, M, canvas, renderer, scene, approx, unit, eyeOver, pixel, place };
  return true;
}"""

PRESETS = """() => {
  const { C, approx, unit } = window.L;
  const out = {};
  const t = [1, 2, 3];
  for (const plane of ['xy', 'xz']) for (const n of ['iso', 'top', 'front', 'side']) {
    const p = C.presetPose(n, { target: t, distance: 5, plane });
    out[plane + '.' + n] = { dir: unit(p.position.map((v, i) => v - t[i])), up: p.up, dist: Math.hypot(...p.position.map((v, i) => v - t[i])), target: p.target };
  }
  out.reserved = [C.presetPose('follow'), C.presetPose('eye')];
  try { C.presetPose('nope'); out.unknown = 'no error'; } catch (e) { out.unknown = e.name; }
  out.lists = [C.PRESETS, C.FOLLOW];
  const g = (a, o) => { const p = C.snapFromGizmo(a, o); return { dir: unit(p.position.map((v, i) => v - (o?.target ?? [0, 0, 0])[i])), up: p.up }; };
  out.gizmo = { xy: ['+x', '-x', '+y', '-y', '+z', '-z'].map((a) => [a, g(a, {})]), xz: ['+y', '+x', '-z'].map((a) => [a, g(a, { plane: 'xz' })]) };
  return out;
}"""

FIT = """() => {
  const { THREE, C, place } = window.L;
  const out = [];
  const boxes = { xy: { min: [-1.2, -0.7, 0], max: [1.5, 2, 1.2] }, xz: { min: [-1.2, 0, -0.7], max: [1.5, 1.2, 2] } };
  for (const [plane, aspect, fov] of [['xy', 1.6, 45], ['xy', 0.5, 45], ['xy', 1.0, 75], ['xz', 1.6, 45]]) for (const preset of ['iso', 'top', 'front', 'side']) {
    const cam = new THREE.PerspectiveCamera(fov, aspect, 0.1, 100);
    const box = boxes[plane];
    const pose = C.fitPose(cam, box, { preset, plane });
    place(cam, pose);
    let worst = 0, depthOk = true;
    for (const x of [box.min[0], box.max[0]]) for (const y of [box.min[1], box.max[1]]) for (const z of [box.min[2], box.max[2]]) {
      const p = new THREE.Vector3(x, y, z).project(cam);
      worst = Math.max(worst, Math.abs(p.x), Math.abs(p.y));
      if (p.z < -1 || p.z > 1) depthOk = false;
    }
    out.push({ plane, aspect, fov, preset, worst, depthOk });
  }
  // orthographic: the same, through the zoom
  const ortho = new THREE.OrthographicCamera(-2, 2, 1, -1, 0.1, 200);
  const pose = C.fitPose(ortho, boxes.xy, { preset: 'top' });
  place(ortho, pose); ortho.zoom = pose.zoom; ortho.updateProjectionMatrix();
  let ow = 0;
  for (const x of [-1.2, 1.5]) for (const y of [-0.7, 2]) for (const z of [0, 1.2]) { const p = new THREE.Vector3(x, y, z).project(ortho); ow = Math.max(ow, Math.abs(p.x), Math.abs(p.y)); }
  const box3 = C.fitPose(new THREE.PerspectiveCamera(45, 1, 0.1, 100), new THREE.Box3(new THREE.Vector3(-1, -1, 0), new THREE.Vector3(1, 1, 1)), { margin: 1 });
  return { rows: out, ortho: ow, box3: box3.target };
}"""

FOLLOW = """() => {
  const { THREE, C, place, approx } = window.L;
  const cam = () => new THREE.PerspectiveCamera(50, 1, 0.1, 100);
  const info = (pose, c = cam()) => {
    place(c, pose);
    const e = c.matrixWorld.elements;
    const right = [e[0], e[1], e[2]], fwd = [-e[8], -e[9], -e[10]];
    return { right, fwd, q: c.quaternion.toArray(), off: pose.position.map((v, i) => v - pose.target[i]), up: pose.up };
  };
  const out = {};
  const off = [3, -4, 5];
  const a = info(C.followPose('position', { position: [2, 3, 0.2], yaw: 0.7 }, { offset: off, up: [0, 0, 1] }));
  const b = info(C.followPose('position', { position: [-5, 9, 0.2], yaw: -2 }, { offset: off, up: [0, 0, 1] }));
  out.position = { sameQ: approx(a.q, b.q, 1e-9), offset: a.off, up: a.up, target: C.followPose('position', { position: [2, 3, 0.2] }, { offset: off }).target };
  const rob = { position: [2, 3, 0.2], pitch: 0.3, roll: 0.4 };
  out.heading = [0, 1.2, -2.5].map((yaw) => {
    const i = info(C.followPose('heading', { ...rob, yaw }));
    return { yaw, rightZ: i.right[2], up: i.up, behind: Math.atan2(i.off[1], i.off[0]), fwdAtRobot: i.fwd.map((v, k) => v * Math.hypot(...i.off)).map((v, k) => -v - i.off[k]) };
  });
  out.pose = [0.4, -0.6].map((roll) => { const i = info(C.followPose('pose', { position: [0, 0, 0], yaw: 0, roll })); return { roll, rightZ: i.right[2], up: i.up, off: i.off }; });
  const p0 = info(C.followPose('pose', { position: [0, 0, 0], yaw: 0, pitch: 0.5 })), h0 = info(C.followPose('heading', { position: [0, 0, 0], yaw: 0, pitch: 0.5 }));
  out.pitch = { poseOff: p0.off, headOff: h0.off, poseUp: p0.up };
  const q = [0, 0, Math.sin(0.35), Math.cos(0.35)];
  out.quat = info(C.followPose('pose', { position: [0, 0, 0], quaternion: q })).off;
  out.yawOnlyAgree = approx(info(C.followPose('pose', { position: [1, 1, 0], yaw: 1 })).q, info(C.followPose('heading', { position: [1, 1, 0], yaw: 1 })).q, 1e-9);
  const xz = info(C.followPose('heading', { position: [0, 0, 0], yaw: 0.8, pitch: 0.4, roll: 0.5 }, { plane: 'xz' }));
  out.xz = { up: xz.up, rightY: xz.right[1], offY: xz.off[1] };
  out.off = C.followPose('off', rob);
  return out;
}"""

MOVE = """async () => {
  const { THREE, OrbitControls, C, M } = window.L;
  const mk = () => { const cam = new THREE.PerspectiveCamera(45, 1, 0.1, 100); cam.up.set(0, 0, 1); cam.position.set(5, 5, 5); cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
    const ctl = new OrbitControls(cam, window.L.canvas); ctl.update(); return [cam, ctl]; };
  const pose = C.presetPose('front', { target: [1, 1, 0], distance: 6 });
  const out = {};
  M.setMotion('reduce');
  let [cam, ctl] = mk(); let done = 0;
  C.moveTo(cam, ctl, pose, { ms: 400, onDone: () => done++ });
  out.reduced = { pos: cam.position.toArray(), target: ctl.target.toArray(), done, want: pose.position };
  M.setMotion('full');
  // a clock the test drives: requestAnimationFrame queues and performance.now answers `clock`, so the tween's progress depends on the frames
  // the test delivers and not on how long the machine took to deliver them
  const realRaf = window.requestAnimationFrame, realCancel = window.cancelAnimationFrame;
  let clock = 0, nextId = 1; const queue = new Map();
  window.requestAnimationFrame = (fn) => { queue.set(nextId, fn); return nextId++; };
  window.cancelAnimationFrame = (id) => { queue.delete(id); };
  performance.now = () => clock;
  const frame = (at) => { clock = at; const run = [...queue.values()]; queue.clear(); for (const fn of run) fn(at); };
  const want = new THREE.Vector3(...pose.position);
  [cam, ctl] = mk(); done = 0;
  const cancel = C.moveTo(cam, ctl, pose, { ms: 120, onDone: () => done++ });
  out.fullSync = { done, moved: cam.position.distanceTo(new THREE.Vector3(5, 5, 5)) };
  const dist = [cam.position.distanceTo(want)], doneAt = [done];
  for (const at of [30, 60, 90, 119]) { frame(at); dist.push(cam.position.distanceTo(want)); doneAt.push(done); }
  frame(120); dist.push(cam.position.distanceTo(want)); doneAt.push(done);
  frame(500);                                                       // nothing is queued any more: no second onDone, no move
  out.full = { done, pos: cam.position.toArray(), want: pose.position, dist, doneAt, queued: queue.size };
  [cam, ctl] = mk(); done = 0;
  const stop = C.moveTo(cam, ctl, pose, { ms: 120, onDone: () => done++ });
  frame(530); frame(560);                                           // started at 500: under way, half of it done
  const mid = cam.position.toArray();
  stop();
  frame(900); frame(1200);
  out.cancelled = { done, pos: cam.position.toArray(), mid };
  window.requestAnimationFrame = realRaf; window.cancelAnimationFrame = realCancel; delete performance.now;
  // the default duration is the --dur-base token: 0 under reduced motion, so a move to a pose with no ms is immediate
  M.setMotion('reduce'); [cam, ctl] = mk(); done = 0;
  C.moveTo(cam, ctl, pose, { onDone: () => done++ });
  out.token = { done, dur: M.ms('--dur-base') };
  M.setMotion('full'); out.tokenFull = M.ms('--dur-base');
  M.setMotion('auto');
  return out;
}"""

STAGE = """async () => {
  const { THREE, S, renderer, scene, approx, eyeOver, pixel } = window.L;
  const root = document.documentElement;
  const hex = (s) => { const n = parseInt(s.replace('#', '').slice(0, 6), 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
  const out = {};
  root.dataset.theme = 'dark';
  const before = scene.children.length;
  const stage = S.createStage(THREE, scene, renderer, { bounds: [-4, 4, -3, 3] });
  const lights = () => { const l = []; scene.traverse((o) => { if (o.isLight) l.push(o); }); return l; };
  out.noBody = { added: scene.children.length - before, lights: lights().map((l) => [l.type, l.intensity]) };
  out.renderer = { cs: renderer.outputColorSpace === THREE.SRGBColorSpace, tm: renderer.toneMapping === THREE.NeutralToneMapping };
  out.tokensDark = S.readStageTokens(); out.tokenKinds = [typeof out.tokensDark.skyK, typeof out.tokensDark.sunK];
  out.layer = { floor: stage.floor.layers.mask === (1 << stage.layer), gridL: stage.grid.layers.mask === (1 << stage.layer), n: stage.layer, lights: lights().every((l) => l.layers.mask === 1), fog: scene.fog };
  const over = eyeOver([1.5, 1.5]);
  const eye = eyeOver([1.5, 1.5], 'xy', [0]);
  const far = eyeOver([30, 30]);
  out.dark = { floor: pixel(over), want: hex(out.tokensDark.floor), eyeNoFloor: pixel(eye), clear: pixel(far), bgWant: hex(out.tokensDark.bg) };
  out.fog = scene.fog;
  // the contact shadow: a 0.4 m block at (1.5, 1.5), seen from above; the shadow is 1.7x its footprint, so a ring of it shows past the block
  const block = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.2), new THREE.MeshStandardMaterial({ color: '#cc8844' }));
  block.position.set(1.5, 1.5, 0.1); scene.add(block);
  const sh = stage.contactShadow(block);
  sh.update();
  const mesh = scene.children.find((o) => o.name === 'stage.contactShadow');
  out.shadow = { pos: mesh.position.toArray(), scale: mesh.scale.toArray(), layer: mesh.layers.mask === (1 << stage.layer), inRing: pixel(over, 96, 64), outside: pixel(over, 124, 64), tex: !!mesh.material.map };
  block.position.z = 3; sh.update();
  out.shadow.lifted = mesh.material.opacity;
  block.position.z = 0.1; sh.update();
  out.shadow.grounded = mesh.material.opacity;
  sh.dispose(); scene.remove(block);
  out.shadow.gone = !scene.children.some((o) => o.name === 'stage.contactShadow');
  const L0 = lights().map((l) => [l.type, l.color.getHexString(), l.intensity]);
  root.dataset.theme = 'light';
  stage.setTheme();
  out.tokensLight = S.readStageTokens();
  out.light = { floor: pixel(over), want: hex(out.tokensLight.floor), clear: pixel(far), bgWant: hex(out.tokensLight.bg) };
  out.lightsChanged = { before: L0, after: lights().map((l) => [l.type, l.color.getHexString(), l.intensity]) };
  stage.setLit(false); out.unlit = lights().every((l) => !l.parent.visible);
  stage.setLit(true);
  // the bounds: the floor follows
  stage.setBounds([-10, 10, -10, 10]);
  out.bounds = stage.floor.scale.toArray();
  // the grid: z = 0 (xy), fades toward the background with the distance from the middle, majors apart
  const g = S.makeGrid(THREE, [-5, 5, -5, 5], { step: 1, major: 0, tokens: out.tokensDark });
  const P = g.geometry.attributes.position, C = g.geometry.attributes.color, bg = new THREE.Color(out.tokensDark.bg);
  let near = null, farV = null;
  for (let i = 0; i < P.count; i++) {
    const r = Math.hypot(P.getX(i), P.getY(i)), d = new THREE.Color(C.getX(i), C.getY(i), C.getZ(i)); const dist = Math.hypot(d.r - bg.r, d.g - bg.g, d.b - bg.b);
    if (!near || r < near.r) near = { r, dist }; if (!farV || r > farV.r) farV = { r, dist };
  }
  out.grid = { zs: [...new Set(Array.from({ length: P.count }, (_, i) => P.getZ(i)))], near, far: farV, fogOn: !!scene.fog, mat: g.material.vertexColors };
  const gz = S.makeGrid(THREE, [-5, 5, -3, 3], { plane: 'xz', tokens: out.tokensDark }).geometry.attributes.position;
  out.gridXZ = [...new Set(Array.from({ length: gz.count }, (_, i) => gz.getY(i)))];
  const gm = S.makeGrid(THREE, [-5, 5, -5, 5], { step: 1, major: 5, tokens: out.tokensDark });
  const gp = gm.geometry.attributes.position, gc = gm.geometry.attributes.color;
  // the origin's two lines are major: their middle vertices are the major colour, brighter than a minor line's at the same radius
  const colourAt = (x, y) => { for (let i = 0; i < gp.count; i++) if (Math.abs(gp.getX(i) - x) < 1e-6 && Math.abs(gp.getY(i) - y) < 1e-6) return [gc.getX(i), gc.getY(i), gc.getZ(i)]; };
  out.major = { origin: colourAt(0, 1), minor: colourAt(1, 0) };
  try { S.createStage(THREE, new THREE.Scene(), renderer, { plane: 'yz' }); out.badPlane = 'no error'; } catch (e) { out.badPlane = e.name; }
  // y-up: the floor lies in x and z
  const sc2 = new THREE.Scene(); const s2 = S.createStage(THREE, sc2, renderer, { plane: 'xz', bounds: [-4, 4, -3, 3] });
  const floorN = new THREE.Vector3(0, 0, 1).applyQuaternion(s2.floor.quaternion);
  out.xz = { normal: floorN.toArray().map((v) => +v.toFixed(6)), pos: s2.floor.position.toArray(), hemi: sc2.children.find((o) => o.name === 'stage.lights').children[0].position.toArray() };
  s2.dispose();
  stage.dispose();
  out.disposed = !scene.children.some((o) => o.name && o.name.startsWith('stage.'));
  return out;
}"""

TRAIL = """() => {
  const { THREE, T, S, scene, renderer, eyeOver, pixel } = window.L;
  const lin = (css) => new THREE.Color(css).toArray();
  const attr = (t, i) => { const c = t.object.geometry.attributes.color; return [c.getX(i), c.getY(i), c.getZ(i)]; };
  const tr = T.createTrail(THREE, { max: 100, head: '#ff3030', fadeTo: '#101418' });
  const pts = Array.from({ length: 50 }, (_, i) => [i * 0.1, 0, 0.05]);
  tr.set(pts);
  const out = { head: attr(tr, 49), tail: attr(tr, 0), mid: attr(tr, 25), wantHead: lin('#ff3030'), wantTail: lin('#101418'), draw: tr.object.geometry.drawRange.count, isLine: tr.object.isLine };
  const flat = []; for (let i = 0; i < 250; i++) flat.push(i, 0, 0);
  tr.set(flat);
  out.capped = { count: tr.object.geometry.drawRange.count, first: tr.object.geometry.attributes.position.getX(0), last: tr.object.geometry.attributes.position.getX(99) };
  tr.setColors({ head: '#30ff30' });
  out.recolour = { head: attr(tr, 99), want: lin('#30ff30'), tail: attr(tr, 0), wantTail: lin('#101418') };
  tr.clear(); out.cleared = tr.object.geometry.drawRange.count;
  tr.set([[0, 0, 0]]); out.one = tr.object.geometry.drawRange.count;
  // on screen: a trail along the floor, the head end brighter against the floor than the tail end
  document.documentElement.dataset.theme = 'dark';
  const tk = S.readStageTokens();
  const t2 = T.createTrail(THREE, { max: 100, head: '#ff3030', fadeTo: tk.bg });
  const s2 = new THREE.Scene(); s2.add(t2.object);
  t2.set(Array.from({ length: 21 }, (_, i) => [-0.5 + i * 0.05, 0.004, 0]));
  const cam = eyeOver([0, 0], 'xy', [0]);
  renderer.setClearColor(new THREE.Color(tk.bg), 1);
  const px = (col) => { renderer.render(s2, cam); const gl = renderer.getContext(), o = new Uint8Array(4); gl.readPixels(col, 64, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, o); return [...o.slice(0, 3)]; };
  out.screen = { tail: px(2), head: px(125) };
  t2.dispose();
  return out;
}"""

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("room"))
    for key in ("arm/room/r1", "bare/room/r2"):            # arm has a body (a mesh); bare has no description: no body ever loads
        make_run(Path(tmp) / "data", key, [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})] + [tick(round(0.1 * k, 3), 0.02 * k) for k in range(30)])
    # arm/room/r3: the truth's whole pose each tick (ADR-0016), 1 m ahead of the belief, so the body stands at the truth and the belief ghost beside it
    make_run(Path(tmp) / "data", "arm/room/r3", [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
             + [tick(round(0.1 * k, 3), 0.02 * k, truth_3d={"z": 0.05, "quat": [1.0, 0.0, 0.0, 0.0]}) for k in range(30)])
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(15000)
    console, missing = [], []
    page.on("console", lambda m: console.append(m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: console.append(str(e)))
    page.on("response", lambda r: missing.append(r.url) if r.status >= 400 else None)
    try:
        page.goto(base + "/lib/tokens.css")
        page.set_content('<!doctype html><html data-theme="dark"><head><link rel="stylesheet" href="/lib/tokens.css"><script type="importmap">{"imports": {"three": "/lib/vendor/three.module.js", "three/addons/": "/lib/vendor/"}}</script></head><body></body></html>')
        page.wait_for_load_state("load")
        page.evaluate(SETUP)

        # camera: presets
        r = page.evaluate(PRESETS)
        near = lambda a, b, e=1e-6: len(a) == len(b) and all(abs(x - y) <= e for x, y in zip(a, b))  # noqa: E731
        k = 11.35 ** -1
        iso = [-5.5, -7.5, 6.5]
        iso = [v / (sum(c * c for c in iso) ** 0.5) for v in iso]
        iso_xz = [iso[0], iso[2], -iso[1]]
        want = {
            "xy.iso": (iso, [0, 0, 1]), "xy.top": ([0, 0, 1], [0, 1, 0]), "xy.front": ([1, 0, 0], [0, 0, 1]), "xy.side": ([0, -1, 0], [0, 0, 1]),
            "xz.iso": (iso_xz, [0, 1, 0]), "xz.top": ([0, 1, 0], [0, 0, -1]), "xz.front": ([1, 0, 0], [0, 1, 0]), "xz.side": ([0, 0, 1], [0, 1, 0]),
        }
        for key, (d, u) in want.items():
            got = r[key]
            check(f"presetPose {key}: the camera sits along {[round(v, 3) for v in d]} from the target, up {u}, at the distance asked",
                  near(got["dir"], d) and near(got["up"], u) and abs(got["dist"] - 5) < 1e-6 and got["target"] == [1, 2, 3], got)
        check("presetPose follow and eye are reserved (null); an unknown name is a RangeError; PRESETS and FOLLOW are the contract's",
              r["reserved"] == [None, None] and r["unknown"] == "RangeError"
              and r["lists"] == [["iso", "top", "front", "side", "follow", "eye"], ["off", "position", "heading", "pose"]], r)
        gz = dict(r["gizmo"]["xy"])
        check("snapFromGizmo (z up): +x, -x, +y, -y look along the axis with up z; +z and -z look along it with up +y",
              near(gz["+x"]["dir"], [1, 0, 0]) and near(gz["-x"]["dir"], [-1, 0, 0]) and near(gz["+y"]["dir"], [0, 1, 0]) and near(gz["-y"]["dir"], [0, -1, 0])
              and all(near(gz[a]["up"], [0, 0, 1]) for a in ("+x", "-x", "+y", "-y"))
              and near(gz["+z"]["dir"], [0, 0, 1]) and near(gz["-z"]["dir"], [0, 0, -1]) and near(gz["+z"]["up"], [0, 1, 0]) and near(gz["-z"]["up"], [0, 1, 0]), gz)
        gx = dict(r["gizmo"]["xz"])
        check("snapFromGizmo (y up): +y is the top view (up -z), +x keeps up +y", near(gx["+y"]["dir"], [0, 1, 0]) and near(gx["+y"]["up"], [0, 0, -1])
              and near(gx["+x"]["up"], [0, 1, 0]) and near(gx["-z"]["dir"], [0, 0, -1]), gx)

        # camera: fit
        f = page.evaluate(FIT)
        check("fitPose: every row ran (4 presets x 4 cameras)", len(f["rows"]) == 16, len(f["rows"]))
        bad = [x for x in f["rows"] if x["worst"] > 1 or not x["depthOk"]]
        check("fitPose: all 8 corners of the box are inside NDC (x, y within [-1, 1], z within [-1, 1]) for each preset, aspect, fov and both planes", not bad, bad[:3])
        loose = [x for x in f["rows"] if not 0.85 <= x["worst"] <= 0.885]
        check("fitPose: and no looser than the margin: the widest corner sits at 1/1.15 = 0.870 of the view", not loose, loose[:3])
        check("fitPose orthographic: the zoom puts the corners inside with the margin; a THREE.Box3 is accepted", 0.85 <= f["ortho"] <= 0.885 and near(f["box3"], [0, 0, 0.5]), f)

        # camera: follow
        o = page.evaluate(FOLLOW)
        check("follow position: the offset and the up are kept, the target is the robot, the orientation is the same wherever the robot is",
              o["position"]["sameQ"] and o["position"]["offset"] == [3, -4, 5] and o["position"]["up"] == [0, 0, 1] and o["position"]["target"] == [2, 3, 0.2], o["position"])
        check("follow heading: the horizon stays level (camera right axis has no z) however the robot is pitched and rolled; up is the world's",
              all(abs(h["rightZ"]) < 1e-9 and near(h["up"], [0, 0, 1]) for h in o["heading"]), o["heading"])
        check("follow heading: the camera is behind the robot, turning with its yaw, and looks at it",
              all(abs(((h["behind"] - (h["yaw"] + 3.141592653589793) + 3.141592653589793) % 6.283185307179586) - 3.141592653589793) < 1e-6 for h in o["heading"])
              and all(max(abs(v) for v in h["fwdAtRobot"]) < 1e-6 for h in o["heading"]), o["heading"])
        check("follow pose: a rolled robot tips the horizon (camera right axis gains z, up = the robot's up) both ways",
              all(abs(x["rightZ"]) > 0.3 and near(x["up"], [0, -__import__("math").sin(x["roll"]), __import__("math").cos(x["roll"])], 1e-9) for x in o["pose"]), o["pose"])
        check("follow pose: a pitched robot lifts the camera differently from heading (which ignores pitch); a quaternion is taken as it is; yaw alone: pose = heading",
              not near(o["pitch"]["poseOff"], o["pitch"]["headOff"], 1e-3) and abs(o["pitch"]["poseUp"][0]) > 0.1 and o["yawOnlyAgree"]
              and near(o["quat"], [-2.5 * __import__("math").cos(0.7), -2.5 * __import__("math").sin(0.7), 1.6], 1e-9), o)
        check("follow heading in a y-up world: up is +y, horizon level in y, the camera above by the height", near(o["xz"]["up"], [0, 1, 0]) and abs(o["xz"]["rightY"]) < 1e-9
              and abs(o["xz"]["offY"] - 1.6) < 1e-9, o["xz"])
        check("follow off is null", o["off"] is None)

        # camera: moveTo
        m = page.evaluate(MOVE)
        check("moveTo under reduced motion completes immediately: camera and controls at the pose and onDone called once, in the same tick",
              near(m["reduced"]["pos"], m["reduced"]["want"], 1e-9) and m["reduced"]["target"] == [1, 1, 0] and m["reduced"]["done"] == 1, m["reduced"])
        d = m["full"]["dist"]
        check("moveTo with motion tweens (on a clock the test drives): not there in the same tick, closer at each frame, onDone only at the frame that reaches 120 ms and then once, "
              "at the pose, with no frame left queued",
              m["fullSync"]["done"] == 0 and m["fullSync"]["moved"] < 1 and all(a > b for a, b in zip(d, d[1:])) and d[1] > 0.1 and d[-1] < 1e-6
              and m["full"]["doneAt"] == [0, 0, 0, 0, 0, 1] and m["full"]["done"] == 1 and m["full"]["queued"] == 0 and near(m["full"]["pos"], m["full"]["want"], 1e-6), m["full"])
        check("moveTo's cancel stops it where it is: no onDone, the camera is under way (it moved) and has not arrived, and stays put",
              m["cancelled"]["done"] == 0 and not near(m["cancelled"]["mid"], [5, 5, 5], 1e-3) and not near(m["cancelled"]["pos"], m["full"]["want"], 1e-3)
              and near(m["cancelled"]["pos"], m["cancelled"]["mid"], 1e-9), m["cancelled"])
        check("moveTo with no ms takes --dur-base, which reduced motion makes 0 (immediate)", m["token"] == {"done": 1, "dur": 0} and m["tokenFull"] == 160, m)

        # stage
        s = page.evaluate(STAGE)
        tkn = s["tokensDark"]
        check("readStageTokens: the --scene-* tokens (colours as text) and --scene-sky-k / --scene-sun-k as numbers", tkn["floor"].startswith("#") and tkn["bg"].startswith("#")
              and s["tokenKinds"] == ["number", "number"] and tkn["skyK"] == 1 and tkn["sunK"] == 1.4 and s["tokensLight"]["skyK"] == 0.7, (tkn, s["tokenKinds"]))
        check("renderer: output colour space sRGB and Neutral tone mapping are set", s["renderer"] == {"cs": True, "tm": True}, s["renderer"])
        check("lights exist with no body: a hemisphere and a directional light, intensities --scene-sky-k and --scene-sun-k (1, 1.4 in dark)",
              s["noBody"]["lights"] == [["HemisphereLight", 1], ["DirectionalLight", 1.4]], s["noBody"])
        check("the floor and grid are on their own layer (30); the lights stay on layer 0; no fog", s["layer"]["floor"] and s["layer"]["gridL"] and s["layer"]["n"] == 30
              and s["layer"]["lights"] and s["layer"]["fog"] is None and s["fog"] is None, s["layer"])
        close = lambda a, b, e=2: all(abs(x - y) <= e for x, y in zip(a, b))  # noqa: E731
        check("dark: the floor pixel read back from the canvas is the --scene-floor colour (within 2/255 per channel; the floor is not tone mapped)",
              close(s["dark"]["floor"], s["dark"]["want"]), (s["dark"]["floor"], s["dark"]["want"]))
        check("dark: the clear colour is --scene-bg (a pixel past the floor, within 2/255)", close(s["dark"]["clear"], s["dark"]["bgWant"]), (s["dark"]["clear"], s["dark"]["bgWant"]))
        check("an eye-style camera without the stage layer does not draw the floor (it sees the clear colour)", close(s["dark"]["eyeNoFloor"], s["dark"]["bgWant"]), s["dark"]["eyeNoFloor"])
        check("setTheme: in light the floor pixel is the light --scene-floor and the clear colour the light --scene-bg; both differ from dark",
              close(s["light"]["floor"], s["light"]["want"]) and close(s["light"]["clear"], s["light"]["bgWant"]) and not close(s["light"]["floor"], s["dark"]["floor"], 10)
              and not close(s["light"]["clear"], s["dark"]["clear"], 10), (s["light"], s["dark"]["floor"]))
        la = s["lightsChanged"]
        check("setTheme: the lights take the light theme's colours and intensities (sky-k 0.7, sun-k 1.1)", la["before"] != la["after"] and la["after"][0][2] == 0.7 and la["after"][1][2] == 1.1, la)
        check("setLit(false) hides the lights; setBounds resizes the floor (20 m plus a metre of margin each side)", s["unlit"] and s["bounds"][:2] == [22, 22], (s["unlit"], s["bounds"]))
        sh = s["shadow"]
        check("contactShadow: a textured plane under the root's footprint (centre 1.5, 1.5, 1.7x its 0.4 m), on the stage layer, removed on dispose",
              near(sh["pos"][:2], [1.5, 1.5], 1e-6) and abs(sh["scale"][0] - 0.68) < 1e-6 and sh["layer"] and sh["tex"] and sh["gone"], sh)
        check("contactShadow darkens the floor in the ring around the body and not outside it", sum(sh["inRing"]) < sum(sh["outside"]) - 6 and close(sh["outside"], s["dark"]["floor"]), (sh["inRing"], sh["outside"]))
        check("contactShadow thins as the body lifts off the floor", sh["lifted"] < 0.5 * sh["grounded"], (sh["lifted"], sh["grounded"]))
        g = s["grid"]
        check("makeGrid: a flat grid (z = 0) coloured per vertex, no fog; the far vertices are closer to --scene-bg than the central ones (fade by vertex colour)",
              g["zs"] == [0] and g["mat"] is True and not g["fogOn"] and g["far"]["dist"] < 0.3 * g["near"]["dist"], g)
        check("makeGrid: the major lines are a different colour from the minor ones; plane xz lays the grid at y = 0", s["major"]["origin"] != s["major"]["minor"] and s["gridXZ"] == [0], (s["major"], s["gridXZ"]))
        check("createStage: a plane that is not xy or xz is a RangeError; plane xz puts the floor's normal on +y, centred, the hemisphere light's up on +y",
              s["badPlane"] == "RangeError" and near(s["xz"]["normal"], [0, 1, 0], 1e-5) and near(s["xz"]["pos"], [0, 0, 0]) and near(s["xz"]["hemi"], [0, 1, 0]), s["xz"])
        check("dispose removes the floor, the grid and the lights from the scene", s["disposed"])

        # trail
        t = page.evaluate(TRAIL)
        check("trail: the head is the head colour and the tail is the fade colour, so they differ; the middle is between",
              near(t["head"], t["wantHead"], 1e-5) and near(t["tail"], t["wantTail"], 1e-5) and not near(t["head"], t["tail"], 0.1) and t["draw"] == 50 and t["isLine"], t)
        check("trail: more points than max keeps the newest max; clear empties; one point draws no segment", t["capped"] == {"count": 100, "first": 150, "last": 249} and t["cleared"] == 0 and t["one"] == 1, t["capped"])
        check("trail.setColors re-paints the head and keeps the fade colour", near(t["recolour"]["head"], t["recolour"]["want"], 1e-5) and near(t["recolour"]["tail"], t["recolour"]["wantTail"], 1e-5), t["recolour"])
        check("trail on screen: the head end is drawn (red) and the tail end has faded into the background", t["screen"]["head"][0] > 150 and sum(t["screen"]["tail"]) < sum(t["screen"]["head"]) - 100
              and max(t["screen"]["tail"]) < 80, t["screen"])

        # the Observatory's three.js page
        pg = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark").new_page()
        pg.set_default_timeout(30000)
        pg.on("console", lambda m: console.append(m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
        pg.on("pageerror", lambda e: console.append(str(e)))
        pg.on("response", lambda r: missing.append(r.url) if r.status >= 400 and "favicon" not in r.url else None)

        def open_run(key, view):
            fresh = "/web/three/" not in pg.url
            pg.goto(f"{base}/web/three/#scene=room&run={key}&view={view}")
            if not fresh:
                pg.reload()                      # only the hash changed: a reload makes the page read it
            pg.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
            pg.wait_for_function("window.miniview.state().run !== null")
            pg.evaluate("window.miniview.whenLoaded()")

        def go(view):
            pg.evaluate("window.__ready = false")
            pg.evaluate(f"window.miniview.setView('{view}')")
            pg.wait_for_function("window.__ready === true")

        A = "window.miniview.internals.adapter"
        tok = lambda n: pg.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('--scene-{n}').trim()")  # noqa: E731
        rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]  # noqa: E731
        # a point of the floor 0.4 m from the robot (the opening camera frames the robot closely), off the grid lines; its pixel in the first pane
        floor_px = lambda: pg.evaluate(f"(() => {{ const q = window.miniview.internals.adapter.project([0.3, -0.3, 0]); return {A}.pixelAt(q[0], q[1]); }})()")  # noqa: E731

        open_run("bare/room/r2", "3d")
        st = pg.evaluate(f"{A}.stage()")
        check("page: the stage's lights exist with no body loaded (the robot has no description): a hemisphere light and a sun, at --scene-sky-k and --scene-sun-k",
              pg.evaluate(f"{A}.body()") is None and [(x[0], x[1]) for x in st["lights"]] == [("HemisphereLight", 1), ("DirectionalLight", 1.4)], (st["lights"], pg.evaluate(f"{A}.body()")))
        check("page: the renderer tone maps (Neutral) and the stage layer is drawn by the 3D and chase cameras only, not the eye, the top or the side views",
              st["toneMapping"] == 7 and [v for v, on in st["views"].items() if on] == ["3d", "chase"], st)
        close = lambda a, b, e=2: all(abs(x - y) <= e for x, y in zip(a, b))  # noqa: E731
        dark_floor, dark_want = floor_px(), rgb(tok("floor"))
        check("page 3D, dark: the floor on screen is the --scene-floor colour", st["floor"] and close(dark_floor, dark_want), (dark_floor, dark_want))
        go("eye")
        pg.evaluate("window.miniview.setOverlay('coords', false)")          # the coordinate frame's axes would be in the way
        eye_px = pg.evaluate(f"(() => {{ const r = document.getElementById('stage').getBoundingClientRect(); return {A}.pixelAt(r.left + r.width / 2, r.top + r.height * 0.9); }})()")
        check("page eye layout: the floor is absent (the eye camera does not enable the stage layer): the lower part of the view is the clear colour --scene-bg",
              close(eye_px, rgb(tok("bg"))), (eye_px, tok("bg")))
        pg.evaluate("window.miniview.setOverlay('coords', true)")
        go("top")
        pg.evaluate("window.miniview.setOverlay('coords', false)")
        top_px = floor_px()
        pg.evaluate("window.miniview.setOverlay('coords', true)")
        check("page top layout: no floor, so the map stays as drawn (the pixel is the clear colour, not --scene-floor)", close(top_px, rgb(tok("bg"))) and not close(top_px, dark_want, 1), (top_px, tok("bg")))
        go("3d")
        pg.click("#themeBtn")
        pg.wait_for_function("document.documentElement.dataset.theme === 'light'")
        light_floor, light_want = floor_px(), rgb(tok("floor"))
        check("page 3D, light: the floor is the light --scene-floor colour and differs from dark (the theme re-reads the tokens)",
              close(light_floor, light_want) and not close(light_floor, dark_floor, 10), (light_floor, light_want, dark_floor))
        lt = pg.evaluate(f"{A}.stage()")
        check("page 3D, light: the lights take the light theme's intensities (0.7, 1.1)", [x[1] for x in lt["lights"]] == [0.7, 1.1], lt["lights"])
        pg.click("#themeBtn")
        pg.wait_for_function("document.documentElement.dataset.theme === 'dark'")

        # the floor overlay: on by default, off hides the floor in the 3D view, remembered across a reload
        def floor_row():
            pg.click("#ovBtn")
            pg.click("input[data-ov=floor]")

        pg.click("#ovBtn")
        check("page: the floor overlay is on by default; its row is in the Overlays popover, checked, and the 3D corner no longer has a Floor button",
              pg.evaluate("window.miniview.config().overlays.floor") is True and pg.evaluate("document.querySelector('input[data-ov=floor]')?.checked") is True
              and pg.evaluate("document.getElementById('floorBtn')") is None)
        pg.click("input[data-ov=floor]")
        off_px = floor_px()
        check("page: unticking the Floor row hides the floor (the pixel is --scene-bg), the grid and the rest stay", pg.evaluate(f"{A}.stage()")["floor"] is False and close(off_px, rgb(tok("bg")))
              and pg.evaluate("window.miniview.config().overlays.floor") is False, off_px)
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
        check("page: the choice is remembered after a reload, and the row is unticked", pg.evaluate("window.miniview.config().overlays.floor") is False
              and pg.evaluate("(document.getElementById('ovBtn').click(), document.querySelector('input[data-ov=floor]').checked)") is False)
        floor_row()
        check("page: setOverlay('floor', ...) and the toggle are the same switch", pg.evaluate("window.miniview.config().overlays.floor") is True
              and pg.evaluate("window.miniview.setOverlay('floor', false)") is False and pg.evaluate(f"{A}.stage()")["floor"] is False)
        pg.evaluate("window.miniview.setOverlay('floor', true)")

        # the contact shadow follows the body (the arm has one)
        open_run("arm/room/r1", "3d")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        def shadow_at(t):
            pg.evaluate("window.__ready = false")
            pg.evaluate(f"window.miniview.setTime({t})")
            pg.wait_for_function("window.__ready === true")
            return pg.evaluate(f"({{ shadow: {A}.stage().shadow, body: {A}.body() }})")
        a, c = shadow_at(0.2), shadow_at(2.5)
        check("page: the contact shadow is under the body, shown with it, and moves as the robot moves (it was at x %.2f, then %.2f)" % (a["shadow"]["pos"][0], c["shadow"]["pos"][0]),
              a["shadow"]["visible"] and c["shadow"]["visible"] and abs(c["shadow"]["pos"][0] - a["shadow"]["pos"][0]) > 0.3
              and abs(c["shadow"]["pos"][0] - c["body"]["pos"][0]) < 0.3 and abs(c["shadow"]["pos"][2] - 0.001) < 1e-6, (a, c))
        # the 0.12 m body's shadow reaches 0.1 m from its middle: the ground 0.075 m to each side, one of which the body does not cover on screen
        px = pg.evaluate(f"""(() => {{ const b = {A}.body().pos, out = [];
          for (const [dx, dy] of [[0.075, 0], [-0.075, 0], [0, 0.075], [0, -0.075]]) {{ const q = window.miniview.internals.adapter.project([b[0] + dx, b[1] + dy, 0]); out.push({A}.pixelAt(q[0], q[1])); }}
          return out; }})()""")
        check("page: the shadow darkens the floor around the robot (a pixel beside the body is darker than the floor)", min(sum(q) for q in px) < sum(rgb(tok("floor"))) - 6, (px, tok("floor")))

        # the camera (U12). The arm has a body; the run is 3 s long and the robot goes along +x, 0.2 m a second
        def cam():
            return pg.evaluate(f"{A}.camera()")

        def settle():
            pg.wait_for_function(f"{A}.camera().moving === false")

        def look(c):
            o = [p - t for p, t in zip(c["position"], c["target"])]
            n = math.hypot(*o)
            return [v / n for v in o]

        def at_time(t):
            pg.evaluate("window.__ready = false")
            pg.evaluate(f"window.miniview.setTime({t})")
            pg.wait_for_function("window.__ready === true")
            return cam()

        near3 = lambda a, b, e: all(abs(x - y) <= e for x, y in zip(a, b))  # noqa: E731
        AXIS = {"iso": [-5.5, -7.5, 6.5], "top": [0, 0, 1], "front": [1, 0, 0], "side": [0, -1, 0]}
        AXIS["iso"] = [v / math.hypot(*AXIS["iso"]) for v in AXIS["iso"]]
        # the robot's box (0.16 x 0.16 x 0.27 m here) must cover at least this much of the view's height when a run opens: 6 % (the fixed iso gave 1.5 %)
        MIN_HEIGHT = 0.06

        pg.evaluate("import('/lib/motion.js').then((m) => m.setMotion('auto'))")
        open_run("arm/room/r1", "3d")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        c = cam()
        check("camera: the corner has the controls (Iso, Top, Front, Side, Fit scene, Fit robot, Follow Off, Position, Heading, Pose) and the follow control starts on Off",
              c["bar"] and pg.evaluate("[...document.querySelectorAll('#camCtl button')].map((b) => b.textContent)")
              == ["Iso", "Top", "Front", "Side", "Fit scene", "Fit robot", "Off", "Position", "Heading", "Pose"] and c["follow"] == "off"
              and pg.evaluate("document.querySelector('#camCtl [data-follow=off]').getAttribute('aria-pressed')") == "true", c)
        n0 = c["ndc"]
        check("camera: on opening a run the robot's box is inside the view and covers at least %.0f %% of its height (here %.0f %%, %.1f %% of the area)" % (MIN_HEIGHT * 100, n0["heightFrac"] * 100, n0["areaFrac"] * 100),
              n0["inside"] and n0["heightFrac"] >= MIN_HEIGHT, n0)

        # a link to a moment opens on the robot there (t = 2 s: x about 0.4), and the playhead is that moment
        pg.goto(f"{base}/web/three/#scene=room&run=arm/room/r1&view=3d&t=2")
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
        pg.wait_for_function("window.miniview.state().t > 1.9")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        c = cam()
        check("camera: #t=2 opens at 2 s and the camera frames the robot where it is then (target within 0.05 m of it, box inside the view, same minimum size)",
              abs(pg.evaluate("window.miniview.state().t") - 2.0) < 0.11 and near3(c["target"][:2], c["robot"][:2], 0.05) and c["robot"][0] > 0.3 and c["ndc"]["inside"] and c["ndc"]["heightFrac"] >= MIN_HEIGHT,
              (c["target"], c["robot"], c["ndc"], pg.evaluate("window.miniview.state().t")))

        for name, axis in AXIS.items():
            pg.click(f"#camCtl [data-cam={name}]")
            settle()
            c = cam()
            check(f"camera: the {name} button puts the camera on its axis (within 1e-3) and the orbit's up is z afterwards", near3(look(c), axis, 1e-3) and c["up"] == [0, 0, 1], (look(c), axis, c["up"]))
        pg.click("#camCtl [data-cam=top]")
        settle()
        top = cam()
        box = pg.evaluate("(() => { const r = document.getElementById('stage').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height * 0.6]; })()")
        pg.mouse.move(*box)
        pg.mouse.down()
        pg.mouse.move(box[0], box[1] - 120, steps=6)
        pg.mouse.up()
        o = cam()
        tilt = math.acos(max(-1, min(1, look(o)[2])))
        check("camera: after Top, orbiting is z-up: a vertical drag tips the camera off the vertical (%.0f degrees), up stays z, the target stays" % math.degrees(tilt),
              tilt > 0.15 and o["up"] == [0, 0, 1] and near3(o["target"], top["target"], 1e-6), (tilt, o["up"]))

        pg.click("#camCtl [data-cam=fit-scene]")
        settle()
        scene_c = cam()
        pg.click("#camCtl [data-cam=fit-robot]")
        settle()
        c = cam()
        d_scene = math.dist(scene_c["position"], scene_c["target"])
        d_robot = math.dist(c["position"], c["target"])
        check("camera: Fit robot puts the robot's box inside the view (NDC within -1..1) at its minimum size, close in (%.1f m) where Fit scene (%.1f m) is far; the view direction stays"
              % (d_robot, d_scene), c["ndc"]["inside"] and c["ndc"]["heightFrac"] >= MIN_HEIGHT and d_robot < d_scene / 2 and near3(look(c), look(scene_c), 1e-6)
              and near3(c["target"][:2], c["robot"][:2], 0.2), (c["ndc"], d_robot, d_scene))

        # the axes gizmo is a button: a click on an axis end snaps to that preset
        def gizmo_click(end):
            a = pg.evaluate(f"{A}.gizmo()")
            k, s = end[1], 1 if end[0] == "+" else -1
            x, y = 28 + s * a[k][0] * 20, 28 - s * a[k][1] * 20
            r = pg.evaluate("(() => { const r = document.getElementById('gizmo').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
            pg.mouse.click(r[0] + x * r[2] / 56, r[1] + y * r[3] / 56)
            settle()
            return cam()
        pg.click("#camCtl [data-cam=iso]")
        settle()
        g = gizmo_click("+x")
        check("camera: a click on the gizmo's +x end snaps to the +x axis (the front view), within 1e-3", near3(look(g), [1, 0, 0], 1e-3), look(g))
        g = gizmo_click("+z")
        check("camera: a click on the +z end snaps to the top view", near3(look(g), [0, 0, 1], 1e-3) and g["up"] == [0, 0, 1], (look(g), g["up"]))
        pg.click("#camCtl [data-cam=iso]")
        settle()
        g = gizmo_click("-y")
        check("camera: a click on the opposite end (-y) snaps to the -y side (the side view looks from -y, so +y is the end seen from behind)", near3(look(g), [0, -1, 0], 1e-3) or near3(look(g), [0, 1, 0], 1e-3), look(g))

        # follow: Position keeps the camera's offset from the robot while the playhead moves
        pg.click("#camCtl [data-cam=iso]")
        settle()
        pg.click("#camCtl [data-follow=position]")
        settle()
        c0 = at_time(0.5)
        off0 = [p - t for p, t in zip(c0["position"], c0["target"])]
        c1 = at_time(2.5)
        off1 = [p - t for p, t in zip(c1["position"], c1["target"])]
        moved = math.dist(c0["robot"], c1["robot"])
        check("camera: follow Position keeps the offset (within 1e-6) while the playhead moves the robot %.2f m, the target is the robot, the camera moved with it, and the button is pressed" % moved,
              c1["follow"] == "position" and near3(off0, off1, 1e-6) and moved > 0.3 and near3(c1["target"], c1["robot"], 1e-6) and abs(math.dist(c0["position"], c1["position"]) - moved) < 1e-6
              and pg.evaluate("document.querySelector('#camCtl [data-follow=position]').getAttribute('aria-pressed')") == "true", (off0, off1, moved))
        pg.click("#camCtl [data-follow=heading]")
        settle()
        h0 = at_time(0.5)
        h1 = at_time(2.5)
        check("camera: follow Heading goes behind the robot (2.5 m back along its heading, +x here) and the horizon stays level",
              h1["follow"] == "heading" and abs((h1["position"][0] - h1["robot"][0]) + 2.5) < 1e-6 and abs(h1["position"][1] - h1["robot"][1]) < 1e-6 and h1["up"] == [0, 0, 1]
              and abs(h1["position"][0] - h0["position"][0] - moved) < 1e-6, (h0["position"], h1["position"], h1["robot"]))
        pg.click("#camCtl [data-follow=pose]")
        settle()
        p1 = at_time(1.0)
        check("camera: follow Pose is behind the robot too, the button shows it", p1["follow"] == "pose" and p1["position"][0] < p1["robot"][0] - 1, p1)
        pg.click("#camCtl [data-follow=off]")
        settle()
        f0 = at_time(0.5)
        f1 = at_time(2.5)
        check("camera: follow Off leaves the camera where it is as the playhead moves, with the horizon level", f1["follow"] == "off" and near3(f0["position"], f1["position"], 1e-9) and f1["up"] == [0, 0, 1], (f0["position"], f1["position"]))

        # reduced motion: the move is done in the same tick as the click
        pg.evaluate("import('/lib/motion.js').then((m) => m.setMotion('reduce'))")
        c = pg.evaluate(f"(() => {{ document.querySelector('#camCtl [data-cam=side]').click(); return {A}.camera(); }})()")
        check("camera: under reduced motion a preset click has the camera at its target in the same tick (not moving, on the -y axis within 1e-3)", not c["moving"] and near3(look(c), [0, -1, 0], 1e-3), (c["moving"], look(c)))
        c = pg.evaluate(f"(() => {{ document.querySelector('#camCtl [data-cam=fit-robot]').click(); return {A}.camera(); }})()")
        check("camera: under reduced motion Fit robot is also at once (not moving, the robot inside the view)", not c["moving"] and c["ndc"]["inside"], (c["moving"], c["ndc"]))
        pg.evaluate("import('/lib/motion.js').then((m) => m.setMotion('auto'))")
        check("camera: the controls are in the 3D layout only (the top layout has none)", (go("top"), not cam())[1] and pg.evaluate("document.getElementById('camCtl').hidden") is True, "")
        go("3d")

        # the bodies (U13): the belief ghost beside the truth body, the trail, the x-ray, the inspector on `i`
        def bodies():
            return pg.evaluate(f"{A}.bodies()")

        def at(t):
            pg.evaluate("window.__ready = false")
            pg.evaluate(f"window.miniview.setTime({t})")
            pg.wait_for_function("window.__ready === true")
            return bodies()

        hexof = lambda n: pg.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('--data-{n}').trim()").lower()  # noqa: E731
        open_run("arm/room/r3", "3d")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        bd = at(2.0)
        body_pos = pg.evaluate(f"{A}.body().pos")
        check("ghost: the truth body stands at the truth (x %.2f) and the belief ghost at the belief (x %.2f), a metre apart, both on screen" % (bd["truthPose"][0], bd["beliefPose"][0]),
              bd["ghost"]["visible"] and near3(body_pos[:2], bd["truthPose"][:2], 1e-4) and near3(bd["ghost"]["pos"][:2], bd["beliefPose"][:2], 1e-4)
              and abs(bd["truthPose"][0] - bd["beliefPose"][0] - 1.0) < 1e-3, (bd, body_pos))
        check("ghost: styled as a ghost (translucent, depth not written: opacity 0.4, transparent) in the --data-belief colour; the truth body stays solid and opaque",
              bd["ghost"]["style"] == "ghost" and bd["ghost"]["transparent"] is True and abs(bd["ghost"]["opacity"] - 0.4) < 1e-6 and bd["ghost"]["color"] == hexof("belief")
              and bd["body"]["style"] == "solid" and bd["body"]["opacity"] == 1, (bd["ghost"], bd["body"], hexof("belief")))
        check("ghost: it is on the belief pose's layer, so the eye (which leaves the belief marker out) does not draw it",
              bd["ghost"]["layer"] == pg.evaluate(f"{A}.layerOf('belief.pose')") and pg.evaluate(f"({A}.layerBits('eye') & {bd['ghost']['layer']}) === 0"), bd["ghost"])
        g1 = at(1.0)
        check("ghost: it follows the playhead (belief x %.2f at 1 s, %.2f at 2 s)" % (g1["beliefPose"][0], bd["beliefPose"][0]),
              near3(g1["ghost"]["pos"][:2], g1["beliefPose"][:2], 1e-4) and abs(g1["ghost"]["pos"][0] - bd["ghost"]["pos"][0]) > 0.15, (g1["ghost"], bd["ghost"]))
        pg.evaluate("window.miniview.setOverlay('ghost', false)")
        check("ghost: the Overlays row (setOverlay 'ghost') hides it", bodies()["ghost"]["visible"] is False and pg.evaluate("window.miniview.config().overlays.ghost") is False)
        pg.evaluate("window.miniview.setOverlay('ghost', true)")
        pg.evaluate("window.miniview.setFrame('map')")
        pg.wait_for_function(f"{A}.bodies().ghost.visible === false")
        check("ghost: in the map frame the body is the belief itself, so no ghost", bodies()["ghost"]["visible"] is False)
        pg.evaluate("window.miniview.setFrame('world')")
        pg.wait_for_function(f"{A}.bodies().ghost.visible === true")
        open_run("arm/room/r1", "3d")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        check("ghost: a run without the truth's whole pose draws the body at the belief, so there is no ghost beside it", at(2.0)["ghost"]["visible"] is False)

        open_run("arm/room/r3", "3d")
        pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0", timeout=30000)
        tr = at(2.0)
        i2 = pg.evaluate("window.miniview.internals.M.i")
        check("trail: through trail.js, drawn up to the playhead: %d points (ticks 0 to %d), the first the truth's tick 0 and the last the truth's pose now, at the floor" % (tr["trail"]["count"], i2),
              tr["trail"]["visible"] and tr["trail"]["count"] == i2 + 1 and abs(tr["trail"]["first"][0] - 1.0) < 1e-4 and near3(tr["trail"]["last"][:2], tr["truthPose"][:2], 1e-4)
              and 0 < tr["trail"]["last"][2] < 0.1, tr["trail"])
        check("trail: the head is in the truth's --data-truth token colour (the body stands at the truth)", tr["trail"]["headColour"] == hexof("truth"), (tr["trail"]["headColour"], hexof("truth")))
        t1 = at(1.0)
        i1 = pg.evaluate("window.miniview.internals.M.i")
        check("trail: moves with the playhead: at 1 s it has %d points (was %d) and ends at the truth then, not the truth at 2 s" % (t1["trail"]["count"], tr["trail"]["count"]),
              t1["trail"]["count"] == i1 + 1 < tr["trail"]["count"] and near3(t1["trail"]["last"][:2], t1["truthPose"][:2], 1e-4) and t1["trail"]["last"][0] < tr["trail"]["last"][0] - 0.15, (t1["trail"], tr["trail"]))
        pg.evaluate("window.miniview.setOverlay('trail', false)")
        check("trail: the Overlays row (setOverlay 'trail') hides it", bodies()["trail"]["visible"] is False)
        pg.evaluate("window.miniview.setOverlay('trail', true)")
        check("trail: shown again with the row, and on the body's layer so the eye leaves it out", bodies()["trail"]["visible"] is True
              and pg.evaluate(f"({A}.layerBits('eye') & {bodies()['trail']['layer']}) === 0"))

        bd = bodies()
        pg.evaluate("window.miniview.setOverlay('xray', true)")
        xr = bodies()
        check("x-ray: the Overlays row turns the truth body see-through (style xray, opacity 0.25); the belief ghost is unchanged",
              bd["body"]["style"] == "solid" and xr["body"]["style"] == "xray" and abs(xr["body"]["opacity"] - 0.25) < 1e-6 and xr["ghost"]["style"] == "ghost" and abs(xr["ghost"]["opacity"] - 0.4) < 1e-6, (bd["body"], xr["body"]))
        pg.evaluate("window.miniview.setOverlay('xray', false)")
        check("x-ray: off gives the solid, opaque body back", bodies()["body"] == {"style": "solid", "opacity": 1}, bodies()["body"])

        # the inspector: `i` opens it, Esc closes it, a letter typed in an input does not open it
        pg.evaluate("document.activeElement?.blur()")
        check("inspector: closed at first", bodies()["inspector"]["open"] is False and pg.evaluate("document.getElementById('inspector').hidden") is True)
        pg.keyboard.press("i")
        pg.wait_for_function(f"{A}.bodies().inspector.open === true")
        ib = bodies()["inspector"]
        check("inspector: `i` opens it with a row for each part of the model (1) and the list focused, for the keyboard", ib["rows"] == 1 and ib["focused"], ib)
        pg.keyboard.press("Enter")
        check("inspector: Enter on the list's cursor picks the part (base)", bodies()["inspector"]["selected"] == "base")
        pg.keyboard.press("Escape")
        pg.wait_for_function(f"{A}.bodies().inspector.open === false")
        check("inspector: Esc closes it, and the overlay flag with it", pg.evaluate("window.miniview.config().overlays.inspector") is False)
        pg.keyboard.press("i")
        pg.wait_for_function(f"{A}.bodies().inspector.open === true")
        pg.keyboard.press("i")
        pg.wait_for_function(f"{A}.bodies().inspector.open === false")
        check("inspector: `i` again closes it (a toggle)", pg.evaluate("window.miniview.config().overlays.inspector") is False)
        pg.focus("#q")
        pg.keyboard.type("i")
        check("inspector: an `i` typed into the stream search input goes to the input and does not open it", pg.input_value("#q") == "i" and bodies()["inspector"]["open"] is False, pg.input_value("#q"))
        pg.fill("#q", "")
        pg.evaluate("document.activeElement?.blur()")
        pg.click("#ovBtn")
        pg.click("input[data-ov=inspector]")
        pg.wait_for_function(f"{A}.bodies().inspector.open === true")
        check("inspector: the Overlays popover has a Model inspector row that opens it", bodies()["inspector"]["open"] is True)
        pg.evaluate("document.querySelector('#inspector button[aria-label^=Close]').click()")      # the popover is open over the panel
        pg.wait_for_function(f"{A}.bodies().inspector.open === false")
        check("inspector: the panel's close button closes it", pg.evaluate("window.miniview.config().overlays.inspector") is False)
        check("page: no console error or warning, no failed request on the page", not console and not missing, (console[:5], missing))

        # no colour literal in the page's scene code: the tokens are read, not copied (the allowed: the white of the pins' texture mask)
        src = {n: (Path(__file__).resolve().parents[1] / "web" / "three" / n).read_text() for n in ("build.js", "views.js", "app.js")}
        lit = {n: re.findall(r"#[0-9a-fA-F]{3,8}\b|\b0x[0-9a-fA-F]+\b|rgba?\(", t) for n, t in src.items()}
        check("no hex, 0x or rgb() colour literal in build.js, views.js or app.js, except the one '#fff' of the anomaly pins' texture mask",
              lit["views.js"] == [] and lit["app.js"] == [] and lit["build.js"] == ["#fff"] and "g.fillStyle = g.strokeStyle = '#fff'" in src["build.js"], lit)
        check("build.js reads the tokens: no fog fallback 0x9aa3b0, no setPalette", "9aa3b0" not in src["build.js"] and "setPalette" not in src["build.js"] + src["app.js"], "")

        check("no console error or warning, no failed request", not console and not missing, (console[:5], missing))
    finally:
        httpd.shutdown()
        b.close()

_checks.done()
