"""The shared 3D stage (step 4.5, unit U4: libs/web/stage/stage.js, camera.js, trail.js) in a bare WebGL canvas in headless Chromium, no
page of the apps: the modules are loaded from /lib/ and driven with the vendored three.js. Camera presets point where the plan says (z up
and y up); fitPose puts all 8 corners of a box inside the view with the margin; follow modes keep orientation, keep a level horizon, or
follow roll and pitch; moveTo is immediate under reduced motion and tweens otherwise; the floor is the --scene-floor colour on screen (read
back from the canvas, within 2/255 per channel: the floor is not tone mapped, so the only difference is rounding through linear light), differs in
dark and light, and the clear colour is --scene-bg; lights exist with no body; the grid fades by vertex colour; the contact shadow darkens
the floor around a body; the trail's head and tail colours differ. Needs the system Chromium and Playwright.
Run: cd apps/observatory && uv run python tests/test_look_3d_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
from observatory.shots import launch

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
  [cam, ctl] = mk(); done = 0;
  const t0 = performance.now();
  const cancel = C.moveTo(cam, ctl, pose, { ms: 120, onDone: () => done++ });
  out.fullSync = { done, moved: cam.position.distanceTo(new THREE.Vector3(5, 5, 5)) };
  await new Promise((r) => setTimeout(r, 400));
  out.full = { done, pos: cam.position.toArray(), want: pose.position, took: performance.now() - t0 };
  [cam, ctl] = mk(); done = 0;
  const stop = C.moveTo(cam, ctl, pose, { ms: 120, onDone: () => done++ });
  stop();
  await new Promise((r) => setTimeout(r, 300));
  out.cancelled = { done, pos: cam.position.toArray() };
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
        check("moveTo with motion tweens: not there yet in the same tick, there when it ends, onDone once, in about the time asked",
              m["fullSync"]["done"] == 0 and m["fullSync"]["moved"] < 1 and m["full"]["done"] == 1 and near(m["full"]["pos"], m["full"]["want"], 1e-6), m)
        check("moveTo's cancel stops it: no onDone, the camera has not arrived", m["cancelled"]["done"] == 0 and not near(m["cancelled"]["pos"], m["full"]["want"], 1e-3), m["cancelled"])
        check("moveTo with no ms takes --dur-base, which reduced motion makes 0 (immediate)", m["token"] == {"done": 1, "dur": 0} and m["tokenFull"] == 160, m)

        # stage
        s = page.evaluate(STAGE)
        tkn = s["tokensDark"]
        check("readStageTokens: the --scene-* tokens (colours as text) and --scene-sky-k / --scene-sun-k as numbers", tkn["floor"].startswith("#") and tkn["bg"].startswith("#")
              and s["tokenKinds"] == ["number", "number"] and tkn["skyK"] == 0.35 and tkn["sunK"] == 0.6 and s["tokensLight"]["skyK"] == 0.7, (tkn, s["tokenKinds"]))
        check("renderer: output colour space sRGB and Neutral tone mapping are set", s["renderer"] == {"cs": True, "tm": True}, s["renderer"])
        check("lights exist with no body: a hemisphere and a directional light, intensities --scene-sky-k and --scene-sun-k (0.35, 0.6 in dark)",
              s["noBody"]["lights"] == [["HemisphereLight", 0.35], ["DirectionalLight", 0.6]], s["noBody"])
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

        check("no console error or warning, no failed request", not console and not missing, (console[:5], missing))
    finally:
        httpd.shutdown()
        b.close()

_checks.done()
