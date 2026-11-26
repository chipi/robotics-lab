// The 3D stage both apps share (RFC-0024, ADR-0021): a floor, a contact shadow, theme-aware lights, tone mapping and a grid that fades
// out, all coloured by the --scene-* tokens (libs/web/tokens.css). The page owns the scene, the camera and the renderer and hands in
// THREE; this module adds to the scene and never draws. Bounds are [h0, h1, v0, v1] along the plane's two axes: plane 'xy' is the
// Observatory's world (z up), 'xz' is a y-up world (the grid and the floor lie in x and z).

// Three.js layer for the floor, the grid and the contact shadows. Layer 0 and 1..24 are the Observatory's own; the lights stay on layer 0
// (a camera only gathers the lights on its layers). A camera that should see the floor enables this layer; an eye or sensor view does not.
export const STAGE_LAYER = 30;

const NUMBERS = ['sky-k', 'sun-k'];
const COLORS = ['bg', 'floor', 'grid', 'grid-major', 'label', 'rel', 'select', 'box-fill', 'gap-hatch', 'sky', 'ground', 'sun', 'shadow'];
const camel = (s) => s.replace(/-(\w)/g, (_, c) => c.toUpperCase());

// the --scene-* tokens as the page resolves them now (theme included): colours as the CSS text, the two light intensities as numbers
export function readStageTokens(el = document.documentElement) {
  const css = getComputedStyle(el);
  const out = {};
  for (const n of COLORS) out[camel(n)] = css.getPropertyValue('--scene-' + n).trim();
  for (const n of NUMBERS) {
    const v = parseFloat(css.getPropertyValue('--scene-' + n));
    out[camel(n)] = Number.isFinite(v) ? v : 1;
  }
  return out;
}

// a CSS colour (#rgb, #rgba, #rrggbb, #rrggbbaa, or anything THREE parses) as { color, alpha }; THREE's own parser drops an 8-digit hex alpha
export function parseColor(THREE, css) {
  const m = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(css.trim());
  if (!m) return { color: new THREE.Color(css), alpha: 1 };
  let h = m[1];
  if (h.length <= 4) h = [...h].map((c) => c + c).join('');
  return { color: new THREE.Color('#' + h.slice(0, 6)), alpha: h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1 };
}

// plane axes: which world axes the floor spans (h, v) and which is up, as unit vectors
const AXES = { xy: { h: 0, v: 1, up: 2 }, xz: { h: 0, v: 2, up: 1 } };
const axes = (plane) => AXES[plane] ?? (() => { throw new RangeError(`plane must be 'xy' or 'xz', got ${plane}`); })();
const at = (plane, h, v, up = 0) => { const a = axes(plane), p = [0, 0, 0]; p[a.h] = h; p[a.v] = v; p[a.up] = up; return p; };

function paintGrid(THREE, geometry, bounds, { step, major, plane }, tokens, fade) {
  const [h0, h1, v0, v1] = bounds;
  const cx = (h0 + h1) / 2, cv = (v0 + v1) / 2, rad = Math.hypot(h1 - h0, v1 - v0) / 2 || 1;
  const minor = parseColor(THREE, tokens.grid).color, maj = parseColor(THREE, tokens.gridMajor).color, bg = parseColor(THREE, tokens.bg).color;
  const pos = [], col = [];
  const tmp = new THREE.Color();
  // a vertex fades toward the background with its distance from the middle, so the grid dissolves instead of ending in a hard edge
  const vert = (h, v, c) => {
    pos.push(...at(plane, h, v, 0));
    tmp.copy(c).lerp(bg, fade * Math.min(1, Math.hypot(h - cx, v - cv) / rad) ** 2);
    col.push(tmp.r, tmp.g, tmp.b);
  };
  const line = (fixed, from, to, alongH, c) => {
    const n = Math.max(1, Math.ceil((to - from) / step));
    for (let k = 0; k < n; k++) {
      const a = from + ((to - from) * k) / n, b = from + ((to - from) * (k + 1)) / n;
      if (alongH) { vert(a, fixed, c); vert(b, fixed, c); } else { vert(fixed, a, c); vert(fixed, b, c); }
    }
  };
  const isMajor = (n) => major > 0 && n % major === 0;
  for (let n = Math.ceil(h0 / step); n * step <= h1 + 1e-9; n++) line(n * step, v0, v1, false, isMajor(n) ? maj : minor);
  for (let n = Math.ceil(v0 / step); n * step <= v1 + 1e-9; n++) line(n * step, h0, h1, true, isMajor(n) ? maj : minor);
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  geometry.computeBoundingSphere();
}

// Metre grid over the bounds in the plane's two axes: every `major`-th line in --scene-grid-major, the rest in --scene-grid, each line cut
// into `step` pieces whose vertex colours fade toward --scene-bg with the distance from the middle (`fade`: how far at the edge, 0 to 1).
// Vertex colours, not fog: fog would also fade the body. The object's userData.paint(bounds, tokens) re-colours and re-lays it.
export function makeGrid(THREE, bounds, { step = 1, major = 5, plane = 'xy', tokens = readStageTokens(), fade = 0.9 } = {}) {
  axes(plane);
  const geometry = new THREE.BufferGeometry();
  const material = new THREE.LineBasicMaterial({ vertexColors: true, toneMapped: false, depthWrite: false });
  const grid = new THREE.LineSegments(geometry, material);
  grid.layers.set(STAGE_LAYER);
  grid.renderOrder = -2;
  grid.userData.paint = (b, t) => {
    const old = grid.geometry;
    grid.geometry = new THREE.BufferGeometry();
    paintGrid(THREE, grid.geometry, b, { step, major, plane }, t, fade);
    old.dispose();
  };
  paintGrid(THREE, geometry, bounds, { step, major, plane }, tokens, fade);
  return grid;
}

// a white radial falloff in the alpha channel, written as pixels (the stops are alpha only); the material's colour and opacity (the --scene-shadow token) tint it
const FALLOFF = [[0, 1], [0.35, 0.7], [0.7, 0.25], [1, 0]];
function shadowTexture(THREE) {
  const size = 128, c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d'), img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const d = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) / (size / 2), i = FALLOFF.findIndex(([s]) => d <= s), o = (y * size + x) * 4;
    const [s0, a0] = FALLOFF[Math.max(i, 1) - 1], [s1, a1] = FALLOFF[Math.max(i, 1)];
    img.data.fill(255, o, o + 3);
    img.data[o + 3] = i < 0 ? 0 : Math.round(255 * (a0 + (a1 - a0) * (d - s0) / (s1 - s0)));
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// The stage: floor, grid, lights and the renderer's colour handling, for `scene` drawn by `renderer`.
//   bounds: [h0, h1, v0, v1] the floor and grid cover (plus a margin); lit: false leaves the lights off (a page that lights itself)
//   plane: 'xy' (z up, default) or 'xz' (y up); step, major: the grid's metres per line and lines per major line
// -> { tokens, setBounds, setTheme, setLit, floor, grid, contactShadow(root), layer, dispose }. setTheme(el) re-reads the tokens, after
// the page changed theme. The floor is not tone mapped, so it is the token's colour on screen; the lit bodies are.
export function createStage(THREE, scene, renderer, { bounds = [-4, 4, -3, 3], lit = true, plane = 'xy', step = 1, major = 5 } = {}) {
  const a = axes(plane);
  let tokens = readStageTokens();
  let box = bounds;

  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1;

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ toneMapped: false, depthWrite: false }));
  floor.name = 'stage.floor';
  if (plane === 'xz') floor.rotation.x = -Math.PI / 2;
  floor.layers.set(STAGE_LAYER);
  floor.renderOrder = -3;
  const grid = makeGrid(THREE, bounds, { step, major, plane, tokens });
  grid.name = 'stage.grid';

  const up = at(plane, 0, 0, 1);
  const hemi = new THREE.HemisphereLight();
  hemi.position.set(...up);
  const sun = new THREE.DirectionalLight();
  sun.position.set(...at(plane, 3, -4, 6));
  const lights = new THREE.Group();
  lights.name = 'stage.lights';
  lights.add(hemi, sun);
  lights.visible = lit;

  scene.add(floor, grid, lights);
  const shadows = new Set();

  const layout = () => {
    const [h0, h1, v0, v1] = box, m = 1;
    floor.scale.set(h1 - h0 + 2 * m, v1 - v0 + 2 * m, 1);
    floor.position.set(...at(plane, (h0 + h1) / 2, (v0 + v1) / 2, 0));
    grid.userData.paint(box, tokens);
  };
  const paint = () => {
    renderer.setClearColor(parseColor(THREE, tokens.bg).color, 1);
    floor.material.color.copy(parseColor(THREE, tokens.floor).color);
    hemi.color.copy(parseColor(THREE, tokens.sky).color);
    hemi.groundColor.copy(parseColor(THREE, tokens.ground).color);
    hemi.intensity = tokens.skyK;
    sun.color.copy(parseColor(THREE, tokens.sun).color);
    sun.intensity = tokens.sunK;
    const s = parseColor(THREE, tokens.shadow);
    for (const sh of shadows) sh.tint(s);
  };
  layout();
  paint();

  function contactShadow(root) {
    const tex = shadowTexture(THREE);
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
    mesh.name = 'stage.contactShadow';
    if (plane === 'xz') mesh.rotation.x = -Math.PI / 2;
    mesh.layers.set(STAGE_LAYER);
    mesh.renderOrder = -1;
    let alpha = 1;
    const bbox = new THREE.Box3();
    const entry = { tint: (s) => { mat.color.copy(s.color); alpha = s.alpha; mat.opacity = alpha; } };
    entry.tint(parseColor(THREE, tokens.shadow));
    shadows.add(entry);
    scene.add(mesh);
    // under the root's footprint on the floor; it thins as the body rises off the floor (a hop, a lifted arm). Cheap enough per frame.
    function update() {
      bbox.setFromObject(root);
      if (bbox.isEmpty()) { mesh.visible = false; return; }
      const lo = bbox.min.toArray(), hi = bbox.max.toArray();
      const w = hi[a.h] - lo[a.h], d = hi[a.v] - lo[a.v];
      const size = Math.max(w, d, 1e-3) * 1.7;
      const lift = Math.max(0, lo[a.up]);
      mesh.visible = true;
      mesh.scale.set(size, size, 1);
      mesh.position.set(...at(plane, (lo[a.h] + hi[a.h]) / 2, (lo[a.v] + hi[a.v]) / 2, 0.001));
      mat.opacity = alpha * Math.max(0, 1 - lift / size);
    }
    update();
    return {
      update,
      mesh,
      get visible() { return mesh.visible; },
      set visible(on) { mesh.visible = !!on; },
      dispose() { shadows.delete(entry); scene.remove(mesh); mesh.geometry.dispose(); mat.dispose(); tex.dispose(); },
    };
  }

  return {
    get tokens() { return tokens; },
    floor,
    grid,
    layer: STAGE_LAYER,
    contactShadow,
    setBounds(b) { box = b; layout(); },
    setTheme(el) { tokens = readStageTokens(el); layout(); paint(); return tokens; },
    setLit(on) { lights.visible = !!on; },
    dispose() {
      scene.remove(floor, grid, lights);
      for (const o of [floor, grid]) { o.geometry.dispose(); o.material.dispose(); }
      hemi.dispose?.(); sun.dispose?.();
    },
  };
}
