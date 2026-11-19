// A robot's body as three.js objects (RFC-0011): its description's meshes, one group per link, placed by the pages' forward
// kinematics (robot.js) under a root group that is set to the robot's pose in the world. Used by Explore and by the 3D view's
// Robot layer: one loader, one placement.
import { linkPoses, parseSTL } from './robot.js';

const geometries = {};      // mesh URL -> BufferGeometry (or null): loaded once per page, shared by every body

export async function createBody(THREE, desc, api) {
  const missing = new Set(desc.meshes_missing || []);
  const urls = [...new Set(desc.links.flatMap((l) => l.visuals.filter((v) => !missing.has(v.mesh)).map((v) => v.url)))];
  await Promise.all(urls.map(async (u) => {
    if (u in geometries) return;
    geometries[u] = (async () => {
      const pos = parseSTL(await (await fetch(api + u)).arrayBuffer());
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
      grp.add(m);
    }
    root.add(grp);
    links[l.name] = grp;
  }
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
  };
}
