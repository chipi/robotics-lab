// The robot's eye (RFC-0013 2.2): where the depth sensor was, in the world frame, from what the run recorded. Quaternions are
// [w, x, y, z]; the trunk and the sensor have x ahead, y left, z up. Pure, so a page test can ask it directly.

// duck_lab.nav.cliff's default: how much further down the sensor looks than the kinematics say (a run's calibration may differ)
export const TOF_PITCH_OFFSET_DEG = 3.0;
// the sensor's field of view, square, as the navigator uses it (cliff.FOV_DEG)
export const FOV_DEG = 45;
// For a run whose depth frames carry no state: the sensor as mounted on the duck's head, in the trunk's frame. Its pitch is fitted to
// ch11-s8's frame at 22.45 s (bottom row on flat floor at 0.46-0.50 m with the sensor 0.228 m up), not recorded.
export const NOMINAL_MOUNT = { pos: [0.08, 0, 0.11], pitch_deg: 9 };

export const qmul = ([aw, ax, ay, az], [bw, bx, by, bz]) => [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
  aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw];
export const qrot = (q, v) => { const r = qmul(qmul(q, [0, ...v]), [q[0], -q[1], -q[2], -q[3]]); return [r[1], r[2], r[3]]; };
export const qz = (a) => [Math.cos(a / 2), 0, 0, Math.sin(a / 2)];
export const qy = (a) => [Math.cos(a / 2), 0, Math.sin(a / 2), 0];
export const qx = (a) => [Math.cos(a / 2), Math.sin(a / 2), 0, 0];
export const yawOf = ([w, x, y, z]) => Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
const rad = (d) => (d * Math.PI) / 180;

// A depth frame that carries the state it was paired with (ADR-0014: `state` = {quat, odom_z, tof: {pos, quat}}) and the map pose it
// was placed with (`pose` = [x, y, yaw]); `mapToWorld` = [tx, ty, yaw] of the epoch in force. The navigator's own geometry
// (cliff.sensor_pose, depth_points): the trunk is at the pose with the IMU's tilt and the pose's heading, the sensor on it at
// tof.pos, turned by tof.quat and the calibration's pitch offset.
export function sensorFromFrame({ state, pose }, mapToWorld, pitchOffsetDeg = TOF_PITCH_OFFSET_DEG) {
  const [tx, ty, h] = mapToWorld, c = Math.cos(h), s = Math.sin(h);
  const wx = tx + c * pose[0] - s * pose[1], wyaw = pose[2] + h, wy = ty + s * pose[0] + c * pose[1];
  const trunk = qmul(qz(wyaw - yawOf(state.quat)), state.quat);
  const off = qrot(trunk, state.tof.pos);
  return { pos: [wx + off[0], wy + off[1], state.odom_z + off[2]], quat: qmul(qmul(trunk, state.tof.quat), qy(rad(pitchOffsetDeg))) };
}

// The estimate for a run with no frame state: the trunk where the tick put it (position and orientation in the world), the nominal mount on it
export function sensorFromTrunk(pos, quat, mount = NOMINAL_MOUNT) {
  const off = qrot(quat, mount.pos);
  return { pos: [pos[0] + off[0], pos[1] + off[1], pos[2] + off[2]], quat: qmul(quat, qy(rad(mount.pitch_deg))) };
}

// the trunk's orientation from a belief yaw and the IMU's tilt (pitch, roll in degrees), as the Robot layer stands it
export const trunkQuat = (yaw, tilt) => qmul(qmul(qz(yaw), qy(rad(tilt ? tilt[0] : 0))), qx(rad(tilt ? tilt[1] : 0)));

// the sensor's axes as a camera wants them: ahead, up, and right (the sensor's y is left)
export function axes(q) {
  const f = qrot(q, [1, 0, 0]), u = qrot(q, [0, 0, 1]), l = qrot(q, [0, 1, 0]);
  return { forward: f, up: u, right: [-l[0], -l[1], -l[2]] };
}
