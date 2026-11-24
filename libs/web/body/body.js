// A robot's body as three.js objects (RFC-0011, RFC-0024): its description's meshes, one group per link, placed by forward kinematics
// (robot.js) under a root group that is set to the robot's pose in the world, and a colour per joint from its worst state (RFC-0023 D4).
// One component for every page that draws the robot: the Observatory's Explore and 3D view, its watch page, Mission Control's robot page.
// The page owns the scene, the camera and the renderer; it hands in THREE.
import { linkPoses, parseSTL } from './robot.js';

const geometries = {};      // mesh URL -> BufferGeometry (or null): loaded once per page, shared by every body

// The anomalies that name a joint (RFC-0019, the navigator's body watch) and the state each severity puts it in.
export const JOINT_ANOMALIES = ['joint_overload', 'joint_tracking', 'motor_hot'];
const STATE_OF = { info: 'ok', minor: 'warn', major: 'error', critical: 'error' };
const RANK = { ok: 0, warn: 1, error: 2 };

// Each joint's worst state from anomaly records [{ t, a }] (a: RFC-0019's record, its values.joint the joint's name): those at or before
// `at` and, when `within` is given, no older than it. { joint: { state, anomaly } }, anomaly the name of the worst one; a joint nothing
// names is not in the answer (it is ok). Live a page passes the wall clock and a window (a robot that stopped complaining is ok again);
// a replay passes the playhead and none.
export function jointStates(anomalies, at = Infinity, within = Infinity) {
  const out = {};
  for (const { t, a } of anomalies) {
    const joint = a?.values?.joint;
    if (!JOINT_ANOMALIES.includes(a?.anomaly) || typeof joint !== 'string' || t > at || at - t > within) continue;
    const s = STATE_OF[a.severity] ?? 'ok';
    if (RANK[s] > RANK[out[joint]?.state ?? 'ok']) out[joint] = { state: s, anomaly: a.anomaly };
  }
  return out;
}

// the status colours of the page's theme (libs/web/tokens.css, --status-*), as CSS colours; warn and error are what health() takes
export function tokenColors(el = document.documentElement) {
  const css = getComputedStyle(el);
  const out = {};
  for (const n of ['ok', 'info', 'warn', 'alert', 'error', 'unknown', 'stale', 'neutral', 'live']) out[n] = css.getPropertyValue('--status-' + n).trim();
  return out;
}

// the material of the solid style: what every body was drawn with before the styles existed
const SURFACE = { roughness: 0.6, metalness: 0.05 };
// opacity a style gets when the caller names none: the x-ray shows what is inside, the ghost is the second opinion beside the body
const OPACITY = { xray: 0.25, ghost: 0.4 };
const HIGHLIGHT_EMISSIVE = 0.35;       // share of the highlight colour a highlighted link also glows with

// `init`: fetch's options for the meshes (Mission Control's token)
export async function createBody(THREE, desc, api, init) {
  const missing = new Set(desc.meshes_missing || []);
  const urls = [...new Set(desc.links.flatMap((l) => l.visuals.filter((v) => !missing.has(v.mesh)).map((v) => v.url)))];
  await Promise.all(urls.map(async (u) => {
    if (u in geometries) return;
    geometries[u] = (async () => {
      const pos = parseSTL(await (await fetch(api + u, init)).arrayBuffer());
      if (!pos) return null;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.computeVertexNormals();
      return g;
    })();
  }));
  const geoms = Object.fromEntries(await Promise.all(urls.map(async (u) => [u, await geometries[u]])));
  return build(THREE, desc, geoms);
}

// The body from geometries already loaded; clone() calls it again, so a second body costs no request and no second copy of a mesh.
function build(THREE, desc, geoms) {
  const root = new THREE.Group(), links = {};
  const q4 = (q) => new THREE.Quaternion(q[1], q[2], q[3], q[0]);           // ours are [w, x, y, z]
  for (const l of desc.links) {
    const grp = new THREE.Group();
    grp.userData.link = l.name;
    for (const v of l.visuals) {
      if (!geoms[v.url]) continue;
      const m = new THREE.Mesh(geoms[v.url], new THREE.MeshStandardMaterial({ color: new THREE.Color(v.rgba[0], v.rgba[1], v.rgba[2]), ...SURFACE }));
      m.position.set(...v.origin.pos); m.quaternion.copy(q4(v.origin.quat)); m.userData.link = l.name;
      m.userData.own = m.material.color.clone();
      m.userData.tint = null;           // the health colour, null while ok
      grp.add(m);
    }
    root.add(grp);
    links[l.name] = grp;
  }
  // the link each moving joint turns: its child (the fixed joints below it ride along)
  const turns = Object.fromEntries(desc.joints.filter((j) => j.type !== 'fixed').map((j) => [j.name, j.child]));
  const hangs = Object.fromEntries(desc.joints.map((j) => [j.child, j]));
  let healthy = {}, style = { mode: 'solid', color: null, opacity: null }, lit = null, only = null, last = {};
  const meshesOf = (link) => links[link]?.children ?? [];
  const allMeshes = () => Object.values(links).flatMap((g) => g.children);

  // one place decides what a mesh looks like: a highlight beats the style's colour, which beats the health colour, which beats its own
  function paint(m) {
    const { mode } = style;
    const mat = m.material, on = lit && m.userData.link === lit.link;
    mat.color.copy(on ? new THREE.Color(lit.color) : style.color ? new THREE.Color(style.color) : m.userData.tint ?? m.userData.own);
    mat.emissive.copy(on ? new THREE.Color(lit.color).multiplyScalar(HIGHLIGHT_EMISSIVE) : new THREE.Color(0, 0, 0));
    const see = mode !== 'solid';
    mat.opacity = see ? style.opacity ?? OPACITY[mode] : 1;
    mat.transparent = see;
    mat.depthWrite = !see;
    mat.needsUpdate = true;
  }
  const repaint = () => allMeshes().forEach(paint);
  const hexOf = (m) => m ? '#' + m.material.color.getHexString() : null;
  const shown = () => { for (const [n, g] of Object.entries(links)) g.visible = only == null || n === only; };

  const body = {
    root, links,
    drawn: () => Object.values(links).filter((g) => g.children.length).length,
    // the links where the joint values put them, relative to the root (the root group carries the robot's pose)
    pose(values) {
      last = { ...values };
      const poses = linkPoses(desc, values);
      for (const [n, g] of Object.entries(links)) {
        const p = poses[n];
        if (p) { g.position.set(...p.pos); g.quaternion.set(p.quat[1], p.quat[2], p.quat[3], p.quat[0]); }
      }
      return poses;
    },
    // the root (the description's root link, the trunk) at a pose in the world: position [x, y, z], quaternion [w, x, y, z]
    place(pos, quat) { root.position.set(...pos); root.quaternion.set(quat[1], quat[2], quat[3], quat[0]); },
    // each moving joint's link in the colour of its state (jointStates' answer, a joint left out is ok): `colors` has warn and
    // error as CSS colours (tokenColors); ok is the mesh's own colour. Returns { joint: { state, color } }, color a hex string, as drawn.
    health(states = {}, colors) {
      healthy = {};
      for (const [joint, link] of Object.entries(turns)) {
        const state = states[joint]?.state ?? 'ok', meshes = meshesOf(link);
        for (const m of meshes) { m.userData.tint = state === 'ok' ? null : new THREE.Color(colors[state]); paint(m); }
        healthy[joint] = { state, color: hexOf(meshes[0]) };
      }
      return healthy;
    },
    healthOf: () => healthy,
    // how the body is drawn: 'solid' (opaque, as always), 'xray' (see-through, to look inside, depth not written) or 'ghost' (the same
    // body as a second opinion beside the first, the belief beside the truth); `color` paints every mesh one colour (a CSS colour, null
    // gives the own and the health colours back), `opacity` replaces the mode's default.
    setStyle({ mode = 'solid', color = null, opacity = null } = {}) {
      if (!(mode === 'solid' || mode in OPACITY)) throw new Error(`unknown body style ${mode}`);
      style = { mode, color, opacity };
      repaint();
      return body;
    },
    style: () => ({ ...style }),
    // another body of the same robot on the same geometries (no request); `style` is setStyle's argument. It starts at this one's pose
    // and in no health colour, a highlight or an isolation.
    clone({ style: s } = {}) {
      const twin = build(THREE, desc, geoms);
      twin.pose(last);
      if (s) twin.setStyle(s);
      return twin;
    },
    // every link, the root first: { link, parent, joint (the one it hangs from, null for the root), type (that joint's, 'root' for the root),
    // meshes, triangles, size [x, y, z] in metres in the link's own frame, colour (as drawn, null without a mesh), state (the joint's) }
    parts() {
      const box = new THREE.Box3(), one = new THREE.Box3();
      return desc.links.map((l) => {
        const j = hangs[l.name], meshes = meshesOf(l.name);
        let triangles = 0;
        box.makeEmpty();
        for (const m of meshes) {
          triangles += m.geometry.getAttribute('position').count / 3;
          m.updateMatrix();
          if (!m.geometry.boundingBox) m.geometry.computeBoundingBox();
          box.union(one.copy(m.geometry.boundingBox).applyMatrix4(m.matrix));
        }
        const size = meshes.length ? box.getSize(new THREE.Vector3()).toArray() : [0, 0, 0];
        return {
          link: l.name, parent: j?.parent ?? null, joint: j?.name ?? null, type: j?.type ?? 'root',
          meshes: meshes.length, triangles, size, colour: hexOf(meshes[0]), state: healthy[j?.name]?.state ?? 'ok',
        };
      });
    },
    // one link in a colour (CSS; the info colour of the theme when none), the rest as they were; null puts it back
    highlight(link, { color } = {}) {
      lit = link == null || !links[link] ? null : { link, color: color ?? tokenColors().info };
      repaint();
    },
    // one link and nothing else (the bodies on the page stay); null shows them all again
    isolate(link) { only = link == null || !links[link] ? null : link; shown(); },
    // the materials, not the geometries: those are shared with every other body on the page
    dispose() { for (const m of allMeshes()) m.material.dispose(); },
  };
  return body;
}
