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

// the warn and error colours of the page's theme (libs/web/tokens.css), as CSS colours
export function tokenColors(el = document.documentElement) {
  const css = getComputedStyle(el);
  return { warn: css.getPropertyValue('--warn').trim(), error: css.getPropertyValue('--error').trim() };
}

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
  const root = new THREE.Group(), links = {};
  const q4 = (q) => new THREE.Quaternion(q[1], q[2], q[3], q[0]);           // ours are [w, x, y, z]
  for (const l of desc.links) {
    const grp = new THREE.Group();
    grp.userData.link = l.name;
    for (const v of l.visuals) {
      if (!geoms[v.url]) continue;
      const m = new THREE.Mesh(geoms[v.url], new THREE.MeshStandardMaterial({ color: new THREE.Color(v.rgba[0], v.rgba[1], v.rgba[2]), roughness: 0.6, metalness: 0.05 }));
      m.position.set(...v.origin.pos); m.quaternion.copy(q4(v.origin.quat)); m.userData.link = l.name;
      m.userData.own = m.material.color.clone();
      grp.add(m);
    }
    root.add(grp);
    links[l.name] = grp;
  }
  // the link each moving joint turns: its child (the fixed joints below it ride along)
  const turns = Object.fromEntries(desc.joints.filter((j) => j.type !== 'fixed').map((j) => [j.name, j.child]));
  let healthy = {};
  return {
    root, links,
    drawn: () => Object.values(links).filter((g) => g.children.length).length,
    // the links where the joint values put them, relative to the root (the root group carries the robot's pose)
    pose(values) {
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
        const state = states[joint]?.state ?? 'ok', meshes = links[link]?.children ?? [];
        for (const m of meshes) m.material.color.copy(state === 'ok' ? m.userData.own : new THREE.Color(colors[state]));
        healthy[joint] = { state, color: meshes[0] ? '#' + meshes[0].material.color.getHexString() : null };
      }
      return healthy;
    },
    healthOf: () => healthy,
  };
}
