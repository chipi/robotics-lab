// Camera poses for the 3D stage: the named presets, fit-to-box, follow modes and the tween that moves a camera there. A pose is
// { position, target, up, zoom? } in plain arrays; this module needs no THREE (moveTo only calls the camera's and controls' own methods).
// `plane` says which way is up in the page's world: 'xy' (z up, the Observatory) or 'xz' (y up). The presets are written for z up and
// turned into a y-up world by the one mapping below.
import { ms, reducedMotion } from '../motion.js';

export const PRESETS = ['iso', 'top', 'front', 'side', 'follow', 'eye'];
export const FOLLOW = ['off', 'position', 'heading', 'pose'];
// follow and eye are placed from the robot's pose and the sensor's, not from a direction: presetPose answers null for them
const RESERVED = new Set(['follow', 'eye']);

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const norm = (a) => { const l = Math.hypot(...a) || 1; return mul(a, 1 / l); };

// z-up vectors into the page's world: y-up is (x, z, -y), a rotation that keeps handedness
const world = (plane) => {
  if (plane === 'xy') return (v) => v;
  if (plane === 'xz') return (v) => [v[0], v[2], -v[1]];
  throw new RangeError(`plane must be 'xy' or 'xz', got ${plane}`);
};

// the camera sits at target + dir * distance; up is the screen's up. iso is the Observatory's default orbit's direction
const DIRS = {
  iso: { dir: [-5.5, -7.5, 6.5], up: [0, 0, 1] },
  top: { dir: [0, 0, 1], up: [0, 1, 0] },
  front: { dir: [1, 0, 0], up: [0, 0, 1] },
  side: { dir: [0, -1, 0], up: [0, 0, 1] },
};

function fromDir(dir, up, target, distance) {
  return { position: add(target, mul(norm(dir), distance)), target: [...target], up: [...up] };
}

// presetPose('iso'|'top'|'front'|'side', { target, distance, plane }) -> { position, target, up }; null for 'follow' and 'eye'
export function presetPose(name, { target = [0, 0, 0], distance = 8, plane = 'xy' } = {}) {
  if (RESERVED.has(name)) return null;
  const d = DIRS[name];
  if (!d) throw new RangeError(`presetPose: ${name} is not one of ${PRESETS.join(', ')}`);
  const w = world(plane);
  return fromDir(w(d.dir), w(d.up), target, distance);
}

// The pose that has every corner of the box inside the view with `margin` (1.15: 15 % to spare), looking at the box's middle from the
// direction of a preset (or `dir`/`up`). `camera` supplies fov and aspect (perspective) or the frustum's size (orthographic: the answer's
// zoom). box: { min: [x,y,z], max: [x,y,z] }, or a THREE.Box3 (min and max as vectors).
export function fitPose(camera, box, { preset = 'iso', dir, up, margin = 1.15, plane = 'xy' } = {}) {
  const lo = Array.isArray(box.min) ? box.min : [box.min.x, box.min.y, box.min.z];
  const hi = Array.isArray(box.max) ? box.max : [box.max.x, box.max.y, box.max.z];
  const target = mul(add(lo, hi), 0.5);
  const w = world(plane);
  const d = dir ? norm(dir) : norm(w(DIRS[preset].dir));
  const u0 = up ?? (dir ? w([0, 0, 1]) : w(DIRS[preset].up));
  const right = norm(cross(u0, d)), upv = cross(d, right), fwd = mul(d, -1);
  const corners = [];
  for (const x of [lo[0], hi[0]]) for (const y of [lo[1], hi[1]]) for (const z of [lo[2], hi[2]]) corners.push(sub([x, y, z], target));
  const radius = Math.max(...corners.map((c) => Math.hypot(...c)));
  if (camera.isOrthographicCamera) {
    const hx = Math.max(...corners.map((c) => Math.abs(dot(c, right)))), hy = Math.max(...corners.map((c) => Math.abs(dot(c, upv))));
    const halfW = (camera.right - camera.left) / 2, halfH = (camera.top - camera.bottom) / 2;
    const zoom = Math.min(halfW / (hx * margin || Infinity), halfH / (hy * margin || Infinity));
    return { ...fromDir(d, u0, target, radius * 2 + 1), zoom: Number.isFinite(zoom) ? zoom : 1 };
  }
  const tanV = Math.tan((camera.fov * Math.PI) / 360), tanH = tanV * (camera.aspect || 1);
  // a corner at (x, y) across and z along the view is at depth `dist + z`; it is inside when |x| * margin <= depth * tanH, and the same for y
  let dist = 0;
  for (const c of corners) {
    const z = dot(c, fwd);
    dist = Math.max(dist, (Math.abs(dot(c, right)) * margin) / tanH - z, (Math.abs(dot(c, upv)) * margin) / tanV - z);
  }
  dist = Math.max(dist, radius + (camera.near || 0.1) * 2);
  return { ...fromDir(d, u0, target, dist), zoom: 1 };
}

// a rotation about a unit axis, [x, y, z, w]; and a vector turned by one
const qAxis = (axis, a) => { const s = Math.sin(a / 2); return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(a / 2)]; };
const qMul = ([ax, ay, az, aw], [bx, by, bz, bw]) => [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
  aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz];
const qRot = (q, v) => { const t = mul(cross(q, v), 2); return add(add(v, mul(t, q[3])), cross(q, t)); };

// Where the camera goes to follow a robot. robot: { position, yaw, pitch?, roll?, quaternion? }: yaw about the up axis, 0 along +x, then
// pitch about the left axis, then roll about the forward axis (a quaternion [x, y, z, w] overrides all three). opts: { plane, up, offset }.
//   'off'       -> null
//   'position'  the camera keeps its orientation and distance and slides with the robot: opts.offset is camera minus target now
//   'heading'   behind the robot, turning with its yaw, the horizon level (up stays the world's)
//   'pose'      behind the robot in its own frame, turning with yaw, pitch and roll: the horizon tips as the robot does
// opts.back and opts.height (metres, 2.5 and 1.6) say where 'heading' and 'pose' stand, in the robot's frame.
export function followPose(mode, robot, { plane = 'xy', up, offset, back = 2.5, height = 1.6 } = {}) {
  if (mode === 'off') return null;
  if (!FOLLOW.includes(mode)) throw new RangeError(`followPose: ${mode} is not one of ${FOLLOW.join(', ')}`);
  const target = [...robot.position];
  const w = world(plane), U = w([0, 0, 1]), F = [1, 0, 0], L = cross(U, F);
  if (mode === 'position') {
    const off = offset ?? mul(norm(w(DIRS.iso.dir)), 8);
    return { position: add(target, off), target, up: [...(up ?? U)] };
  }
  const yawQ = qAxis(U, robot.yaw ?? 0);
  const q = mode === 'heading' ? yawQ : (robot.quaternion ?? qMul(qMul(yawQ, qAxis(L, robot.pitch ?? 0)), qAxis(F, robot.roll ?? 0)));
  const local = add(mul(F, -back), mul(U, height));
  return { position: add(target, qRot(q, local)), target, up: mode === 'heading' ? [...U] : qRot(q, U) };
}

// the pose for a click on the axes gizmo: look along the axis toward the origin side the click named ('+x', '-y', '+z', ...), from that side
// of the target. +U (looking down) and -U get the page's y-ish axis up so the view is not degenerate; the others keep up
export function snapFromGizmo(axis, { target = [0, 0, 0], distance = 8, plane = 'xy' } = {}) {
  const m = /^([+-])([xyz])$/.exec(axis);
  if (!m) throw new RangeError(`snapFromGizmo: ${axis} is not +x, -x, +y, -y, +z or -z`);
  const w = world(plane), U = w([0, 0, 1]);
  const dir = [0, 0, 0];
  dir['xyz'.indexOf(m[2])] = m[1] === '+' ? 1 : -1;
  const vertical = Math.abs(dot(dir, U)) > 0.5;
  return fromDir(dir, vertical ? w([0, 1, 0]) : U, target, distance);
}

const ease = (t) => 1 - (1 - t) ** 3;
const lerp = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

// Move the camera (and an OrbitControls) to a pose: over `ms` (the --dur-base token by default), at once under reduced motion or 0 ms.
// Returns cancel(), which stops where it is without calling onDone. onDone runs once, after the last frame.
export function moveTo(camera, controls, pose, { ms: dur, onDone } = {}) {
  const apply = (p, t, u, z) => {
    camera.position.set(...p);
    controls?.target.set(...t);
    if (u) {
      camera.up.set(...u);
      // OrbitControls fixes its orbit axis when it is made; a changed up needs it again (no public call for it)
      controls?._quat?.setFromUnitVectors(camera.up, camera.up.clone().set(0, 1, 0));
      controls?._quatInverse?.copy(controls._quat).invert();
    }
    if (z != null && camera.zoom !== z) { camera.zoom = z; camera.updateProjectionMatrix?.(); }
    if (controls) controls.update(); else camera.lookAt(...t);
  };
  const from = { p: camera.position.toArray(), t: controls ? controls.target.toArray() : pose.target, u: camera.up.toArray(), z: camera.zoom };
  const total = dur ?? ms('--dur-base');
  if (reducedMotion() || !(total > 0)) {
    apply(pose.position, pose.target, pose.up, pose.zoom);
    onDone?.();
    return () => {};
  }
  let raf = 0, done = false;
  const t0 = performance.now();
  const step = (now) => {
    if (done) return;
    const k = Math.min(1, (now - t0) / total), e = ease(k);
    apply(lerp(from.p, pose.position, e), lerp(from.t, pose.target, e), pose.up && norm(lerp(from.u, pose.up, e)),
      pose.zoom != null ? from.z + (pose.zoom - from.z) * e : null);
    if (k < 1) raf = requestAnimationFrame(step); else { done = true; onDone?.(); }
  };
  raf = requestAnimationFrame(step);
  return () => { done = true; cancelAnimationFrame(raf); };
}
