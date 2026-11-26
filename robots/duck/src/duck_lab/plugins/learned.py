"""The duck's learned local controller `learned@<sha8>` (RFC-0025 section 3.7, R3): an ONNX policy that adds a residual to the follower's
command, in the simulator only for now (R8 decides the real duck).

The model is NVIDIA's navigation actor as the research read it (docs/wip/RESEARCH-R1-R2.md, section 1): one float input (1, 1343), one
output (1, 3), three residuals in [-1, 1] for forward, lateral and yaw. The 1343 are built from what the navigator holds (`observation`),
and the residual is applied the way `microduck-nav`'s `residual_action.py` does (itself NVIDIA's `MicroDuckWalkingAction.process_actions`
and `command_from_action`): limits (0.35, 0.12, 0.75), translation never faster than requested, slew, a zero request or a stale frame
gives zero. That logic is ported here, not imported. A non-finite input or output gives the brake: NVIDIA's guard warns on a far-off
input only and misses an infinite one (R1/C4).

Not verified against NVIDIA's `nav_pad.py` (not in this repository): the order of the 14 joints and their default pose (taken as
robotd's order less the mouth, and Pollen's HOME_FRAME), the sign and frame of the gravity, the order of the sensor's 64 zones, and
the history layout (tick by tick, oldest first, each tick's 64 ranges then its 64 valid flags, as R1's table reads).
"""

import hashlib
from pathlib import Path

import numpy as np
import onnxruntime as ort

from duck_lab.nav.follow import Twist
from duck_lab.nav.runlog import JOINTS
from duck_lab.plugins.tof8x8 import rotate

OBS_DIM, ACTION_DIM = 1343, 3
HISTORY, ZONES = 10, 64
MIN_RANGE_M, MAX_RANGE_M = 0.12, 4.0       # a return outside it is invalid (NVIDIA's observations.py:18-28)
EMPTY_AGE_S = 1.0                          # a tick with no frame: empty, aged 1 s, as at a training reset
LIMITS, SLEW, MAX_AGE_S, LATERAL_RATIO = (0.35, 0.12, 0.75), (1.0, 1.0, 3.0), 0.25, 0.35
BRAKE = (-1.0, 0.0, 0.0)

NAV_JOINTS = tuple(n for n in JOINTS if n != "mouth")
DEFAULT_POSE = {"left_hip_yaw": 0.0, "left_hip_roll": -0.0873, "left_hip_pitch": -0.4579, "left_knee": -0.0049, "left_ankle": 0.4530,
                "neck_pitch": 0.3491, "head_pitch": 0.3491, "head_yaw": 0.0, "head_roll": 0.0,
                "right_hip_yaw": 0.0, "right_hip_roll": 0.0873, "right_hip_pitch": 0.4579, "right_knee": 0.0049, "right_ankle": -0.4530}
DEFAULT = np.array([DEFAULT_POSE[n] for n in NAV_JOINTS])


def brake_action() -> np.ndarray:
    return np.array(BRAKE)


class ResidualCommand:
    """Velocity command = request + residual, bounded, never faster than the request, slew-limited; a zero request, no frame or a frame
    older than `max_age` gives zero at once, past the slew. `previous` is the command sent last tick."""

    def __init__(self, dt: float, limits=LIMITS, slew=SLEW, max_age: float = MAX_AGE_S, max_lateral_ratio: float = LATERAL_RATIO):
        self.dt, self.max_age, self.max_lateral_ratio = dt, max_age, max_lateral_ratio
        self.limits, self.slew = np.array(limits, dtype=float), np.array(slew, dtype=float)
        self.previous = np.zeros(3)

    def reset(self) -> None:
        self.previous[:] = 0.0

    def process(self, requested, action, have_frame: bool, frame_age: float) -> np.ndarray:
        requested = np.asarray(requested, dtype=float)
        cmd = requested + np.clip(np.asarray(action, dtype=float), -1.0, 1.0) * self.limits
        cmd[0] = np.clip(cmd[0], 0.0, self.limits[0])
        cmd[1] = np.clip(cmd[1], -self.limits[1], self.limits[1])
        cmd[2] = np.clip(cmd[2], -self.limits[2], self.limits[2])
        cmd[:2] *= min(np.linalg.norm(requested[:2]) / max(np.linalg.norm(cmd[:2]), 1e-6), 1.0)
        step = self.slew * self.dt
        cmd = self.previous + np.clip(cmd - self.previous, -step, step)
        lateral = cmd[0] * self.max_lateral_ratio
        cmd[1] = max(min(cmd[1], lateral), -lateral)
        if not requested.any() or not have_frame or frame_age > self.max_age:
            cmd = np.zeros(3)
        self.previous = cmd.copy()
        return cmd


def _numbers(values, n: int, what: str) -> np.ndarray:
    a = np.asarray(values, dtype=float).reshape(-1)
    if a.shape != (n,):
        raise ValueError(f"{what}: {n} numbers expected, got {a.shape[0]}")
    if not np.isfinite(a).all():
        raise ValueError(f"{what}: not finite")
    return a


def _tick(frame: dict, valid: set) -> np.ndarray:
    """One frame as the model reads it: 64 ranges in metres, then 64 valid flags; an invalid return is 0 (a missing return is not
    free space, so its flag says so)."""
    mm = _numbers(frame["distance_mm"], ZONES, "frame distance_mm")
    status = np.asarray(frame["status"]).reshape(-1)
    if status.shape != (ZONES,):
        raise ValueError(f"frame status: {ZONES} numbers expected, got {status.shape[0]}")
    metres = mm / 1000.0
    ok = np.isin(status, list(valid)) & (metres >= MIN_RANGE_M) & (metres <= MAX_RANGE_M)
    return np.concatenate((np.where(ok, metres, 0.0), ok.astype(float)))


def observation(requested, ranges: list, body: dict, applied, valid: set, tick_s: float, previous_action, joint_velocity) -> np.ndarray:
    """NVIDIA's 1343 inputs (R1 section 1.2): gyro 3, projected gravity 3, joint positions less the default 14, joint velocities 14
    (the caller's, one tick late), previous action 3, requested velocity 3, zeros 10 (head and body pose commands), applied command 3,
    ten ticks of 64 ranges and 64 flags oldest first, ten frame ages. Raises ValueError for an input that is not finite or not as long
    as it must be."""
    imu = body["imu"]
    gyro, quat = _numbers(imu["gyro"], 3, "gyro"), _numbers(imu["quat"], 4, "quat")
    joints = _numbers(body["joints"], len(JOINTS), "joints")
    keep = [i for i, n in enumerate(JOINTS) if n != "mouth"]
    gravity = rotate((quat[0], -quat[1], -quat[2], -quat[3]), (0.0, 0.0, -1.0))
    req = _numbers([requested.vx, 0.0, requested.vyaw], 3, "requested")
    app = _numbers([applied.vx, 0.0, applied.vyaw], 3, "applied")
    ages = np.array([float(a) for _, a in ranges])
    if not np.isfinite(ages).all():
        raise ValueError("frame age: not finite")
    obs = np.zeros(OBS_DIM, dtype=np.float32)
    obs[0:3], obs[3:6] = gyro, gravity
    obs[6:20] = joints[keep] - DEFAULT
    obs[20:34] = joint_velocity
    obs[34:37], obs[37:40], obs[50:53] = previous_action, req, app
    for k in range(HISTORY):
        slot = HISTORY - 1 - k
        offset = k * tick_s
        fresh = [(a, f) for f, a in ranges if a >= offset - 1e-9]
        if fresh:
            age, frame = min(fresh, key=lambda c: c[0])
            obs[53 + slot * 128:53 + (slot + 1) * 128] = _tick(frame, valid)
            obs[1333 + slot] = age - offset
        else:
            obs[1333 + slot] = EMPTY_AGE_S
    return obs


class Learned:
    name = "learned"
    version = 1

    def __init__(self, profile, model, tick_s: float = 0.1):
        if profile.variant != "sim":
            raise ValueError(f"the learned local controller is the simulator's for now: the {profile.variant!r} robot refuses it (RFC-0025 R8)")
        self.path = Path(model).expanduser()
        data = self.path.read_bytes()
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.ident = f"learned@{self.sha256[:8]}"
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        opts.intra_op_num_threads = 1
        self.session = ort.InferenceSession(data, sess_options=opts, providers=["CPUExecutionProvider"])
        ins, outs = self.session.get_inputs(), self.session.get_outputs()
        if len(ins) != 1 or ins[0].shape[-1] != OBS_DIM:
            raise ValueError(f"{self.path}: the model must take one input {OBS_DIM} wide, it has {[(i.name, i.shape) for i in ins]}")
        if len(outs) != 1 or outs[0].shape[-1] != ACTION_DIM:
            raise ValueError(f"{self.path}: the model must give one output {ACTION_DIM} wide, it has {[(o.name, o.shape) for o in outs]}")
        self.input, self.output = ins[0], outs[0]
        self.valid = set(profile.sensors.tof8x8.valid_status)
        self.tick_s = tick_s
        self.residual = ResidualCommand(tick_s)
        self.last_error = None
        self.reset()

    def bind(self, profile) -> None:
        self.valid = set(profile.sensors.tof8x8.valid_status)

    def reset(self) -> None:
        self.residual.reset()
        self.previous_action = np.zeros(ACTION_DIM)
        self.joint_velocity = np.zeros(len(NAV_JOINTS))

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "ident": self.ident,
                "model": {"path": str(self.path), "sha256": self.sha256,
                          "input": {"name": self.input.name, "shape": list(self.input.shape)},
                          "output": {"name": self.output.name, "shape": list(self.output.shape)}}}

    def command(self, requested, ranges, body, applied):
        try:
            return self._command(requested, ranges, body, applied)
        except Exception as exc:        # noqa: BLE001 - whatever the model or an input does, the answer is the brake
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._brake(requested, applied)

    def _vectors(self, requested, applied):
        return (np.array([requested.vx, 0.0, requested.vyaw], dtype=float), np.array([applied.vx, 0.0, applied.vyaw], dtype=float))

    def _brake(self, requested, applied) -> Twist:
        """The residual (-1, 0, 0) through the same limits and slew; a plain stop when the request or the applied command is itself
        not a number."""
        req, app = self._vectors(requested, applied)
        self.previous_action = brake_action()
        if not (np.isfinite(req).all() and np.isfinite(app).all()):
            self.residual.reset()
            return Twist(0.0, 0.0)
        self.residual.previous = app
        cmd = self.residual.process(req, brake_action(), True, 0.0)
        return Twist(float(cmd[0]), float(cmd[2]))

    def _command(self, requested, ranges, body, applied) -> Twist:
        req, app = self._vectors(requested, applied)
        if not (np.isfinite(req).all() and np.isfinite(app).all()):
            return self._brake(requested, applied)
        self.residual.previous = app
        ages = [float(a) for _, a in ranges]
        if not np.isfinite(ages).all():
            raise ValueError("frame age: not finite")
        have = bool(ranges) and body is not None
        age = min(ages, default=0.0)
        if not have or age > MAX_AGE_S or not req.any():
            self.previous_action = np.zeros(ACTION_DIM)
            cmd = self.residual.process(req, np.zeros(ACTION_DIM), have, age)
            return Twist(float(cmd[0]), float(cmd[2]))
        obs = observation(requested, ranges, body, applied, self.valid, self.tick_s, self.previous_action, self.joint_velocity)
        out = self.session.run(None, {self.input.name: obs[None, :]})[0].reshape(-1)
        if out.shape != (ACTION_DIM,) or not np.isfinite(out).all():
            return self._brake(requested, applied)
        self.previous_action = np.clip(out.astype(float), -1.0, 1.0)
        velocities = _numbers(body["velocities"], len(JOINTS), "joint velocities")
        self.joint_velocity = velocities[[i for i, n in enumerate(JOINTS) if n != "mouth"]]
        cmd = self.residual.process(req, out, True, age)
        return Twist(float(cmd[0]), float(cmd[2]))
