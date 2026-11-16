// A robot's description in the pages (RFC-0011): its kinematic chains, its forward kinematics and its meshes. The FK is
// miniview.kinematics in JavaScript (the same composition, the same clamping), checked against the same MuJoCo fixture
// (tests/test_explore.py), so posing by hand needs no request per slider move. Poses are { pos: [x,y,z], quat: [w,x,y,z] }.

export const qmul = (a, b) => [
  a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
  a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]];
export const qrot = (q, v) => qmul(qmul(q, [0, ...v]), [q[0], -q[1], -q[2], -q[3]]).slice(1);
const axisAngle = (ax, a) => { const n = Math.hypot(...ax) || 1, s = Math.sin(a / 2) / n; return [Math.cos(a / 2), ax[0] * s, ax[1] * s, ax[2] * s]; };
export const compose = (a, b) => { const r = qrot(a.quat, b.pos); return { pos: [a.pos[0] + r[0], a.pos[1] + r[1], a.pos[2] + r[2]], quat: qmul(a.quat, b.quat) }; };
export const IDENTITY = { pos: [0, 0, 0], quat: [1, 0, 0, 0] };

// the child link's pose in the parent's for this value (radians or metres), clamped to the joint's limits
export function jointTransform(j, value = 0) {
  let v = value;
  if (j.lower != null && j.upper != null && j.type !== 'continuous') v = Math.min(Math.max(v, j.lower), j.upper);
  if (j.type === 'revolute' || j.type === 'continuous') return compose(j.origin, { pos: [0, 0, 0], quat: axisAngle(j.axis, v) });
  if (j.type === 'prismatic') return compose(j.origin, { pos: j.axis.map((c) => c * v), quat: [1, 0, 0, 0] });
  return j.origin;
}

// every link's pose in the root pose's frame; desc.joints come from the API root-outwards; a joint missing from values is 0
export function linkPoses(desc, values = {}, root = IDENTITY) {
  const out = { [desc.root]: root };
  for (const j of desc.joints) out[j.child] = compose(out[j.parent], jointTransform(j, values[j.name] ?? 0));
  return out;
}

// the robot's chains: each joint off the root starts one (a leg, the head); fixed joints carry the chain, are not listed
export function chainsOf(desc) {
  const byParent = {};
  for (const j of desc.joints) (byParent[j.parent] ||= []).push(j);
  const walk = (j, out) => { out.push(j); for (const c of byParent[j.child] || []) walk(c, out); return out; };
  const name = (js) => {
    const n = js.filter((j) => j.type !== 'fixed').map((j) => j.name);
    if (n.every((x) => x.startsWith('left_'))) return 'Left leg';
    if (n.every((x) => x.startsWith('right_'))) return 'Right leg';
    if (n.some((x) => /neck|head/.test(x))) return 'Head';
    return js[0].child;
  };
  return (byParent[desc.root] || []).map((j) => { const js = walk(j, []); return { name: name(js), joints: js.filter((x) => x.type !== 'fixed') }; })
    .filter((c) => c.joints.length);
}

// a binary STL as flat positions (9 floats per triangle); null for an ASCII one (the descriptions' meshes are binary)
export function parseSTL(buf) {
  const dv = new DataView(buf);
  if (buf.byteLength < 84) return null;
  const n = dv.getUint32(80, true);
  if (84 + n * 50 !== buf.byteLength) return null;
  const pos = new Float32Array(n * 9);
  for (let i = 0; i < n; i++) for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(84 + i * 50 + 12 + k * 4, true);
  return pos;
}
