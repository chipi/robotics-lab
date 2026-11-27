"""The duck's learned local controller `learned@<sha8>` (RFC-0025 section 3.7, R3): an ONNX policy that adds a residual to the follower's
command, in the simulator only for now (R8 decides the real duck).

The model is NVIDIA's navigation actor as the research read it (docs/wip/RESEARCH-R1-R2.md, section 1): one float input (1, 1343), one
output (1, 3), three residuals in [-1, 1] for forward, lateral and yaw. The 1343 are built from what the navigator holds (`observation`),
and the residual is applied the way `microduck-nav`'s `residual_action.py` does (itself NVIDIA's `MicroDuckWalkingAction.process_actions`
and `command_from_action`): limits (0.35, 0.12, 0.75), translation never faster than requested, slew, a zero request or a stale frame
gives zero. That logic is ported here, not imported. A non-finite input or output gives the brake: NVIDIA's guard warns on a far-off
input only and misses an infinite one (R1/C4).

The observation is checked slot by slot against what `microduck-nav` trains on (docs/wip/RESEARCH-R4-OBS-PARITY.md) and, for five
constructed states, against the vectors its own observation functions build (tests/fixtures/obs_parity.json, in test_local_controller.py).
What cannot match is listed there: the model is queried every navigator tick (0.1 s), not every 0.02 s control step, and the duck's
command has no lateral part.

Two deployment differences from training, both on purpose (docs/wip/HANDOVER-TRAINING-2026-11-26.md, "What R5 found"): the policy's depth
drops the floor returns training's sensor impairment drops (`far_floor`; the navigator's own planner, guards and map keep the full frame),
and a pure pivot request (vx 0, yaw at or over the profile's stand_turn.min_rad_s) passes to the walker as rules@1 would send it, the
model not asked, since the residual's yaw limit is under the walker's turn floor. A tick says which it did (`decision`).
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import onnxruntime as ort

from duck_lab.nav.follow import Twist
from duck_lab.nav.runlog import JOINTS
from duck_lab.plugins.tof8x8 import Tof8x8, rotate

OBS_DIM, ACTION_DIM = 1343, 3
HISTORY, ZONES = 10, 64
MIN_RANGE_M, MAX_RANGE_M = 0.12, 4.0       # a return outside it is invalid, judged on the optical-axis depth (microduck-nav observations.py)
EMPTY_AGE_S = 1.0                          # a tick with no frame: empty, aged 1 s, as at a training reset
MODEL_STEP_S = 0.02                        # the 50 Hz model's control step (decimation 4 of 5 ms) and policy step: the history's spacing
RATES = {50: (0.02, 0.12), 10: (0.1, 0.0)}   # --model-rate: Hz -> (policy step s, lateral limit m/s): M2a Mjlab-Nav-MicroDuck, M2b Mjlab-Nav-Deploy-MicroDuck
OBS_LAYOUT = "nav-1343-v1"                 # microduck-nav's nav_export.OBS_LAYOUT: the slot order observation() builds
LIMITS, SLEW, MAX_AGE_S, LATERAL_RATIO = (0.35, 0.12, 0.75), (1.0, 1.0, 3.0), 0.25, 0.35
BRAKE = (-1.0, 0.0, 0.0)
# Training drops a floor return with probability sigmoid((depth - midpoint) / width) and never one at or under 0.55 m (microduck-nav
# impairments.py:17,39,108-112); the midpoint is 0.556 m plus a per-episode offset of 0 to 0.13 m (impairments.py:54-59). The policy never saw a
# floor return past the midpoint, so the deployed input drops them where the probability reaches one half (depth at or past 0.556 m, offset 0).
FLOOR_VALIDITY_M = 0.556

NAV_JOINTS = tuple(n for n in JOINTS if n != "mouth")
DEFAULT_POSE = {"left_hip_yaw": 0.0, "left_hip_roll": -0.0873, "left_hip_pitch": -0.4579, "left_knee": -0.0049, "left_ankle": 0.4530,
                "neck_pitch": 0.3491, "head_pitch": 0.3491, "head_yaw": 0.0, "head_roll": 0.0,
                "right_hip_yaw": 0.0, "right_hip_roll": 0.0873, "right_hip_pitch": 0.4579, "right_knee": 0.0049, "right_ankle": -0.4530}
DEFAULT = np.array([DEFAULT_POSE[n] for n in NAV_JOINTS])


def _number(raw: dict, key: str, where: str, minimum: float, strict: bool) -> float:
    try:
        value = float(raw[key])
    except KeyError:
        raise ValueError(f"{where}: {key} is missing (it needs policy_step_s and lateral_limit)") from None
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {key} {raw[key]!r} is not a number") from None
    if not math.isfinite(value) or value < minimum or (strict and value == minimum):
        raise ValueError(f"{where}: {key} {raw[key]!r} is out of range (must be {'above' if strict else 'at least'} {minimum})")
    return value


def model_spec(path: Path, metadata: dict, model_rate: int | None = None) -> dict:
    """What the model was trained at: its task, policy step (s, the history's spacing) and lateral limit (m/s), and where that came from.
    The order is the ONNX metadata (microduck-nav's export writes it), a sidecar `<model>.onnx.json`, then `--model-rate` (50 or 10):
    the first that exists decides, and a flag that disagrees with it is refused, not ignored. A model with none of them is refused, never
    guessed: run at a rate it did not train at, it reads a history of the wrong length."""
    if model_rate is not None and model_rate not in RATES:
        raise ValueError(f"--model-rate {model_rate}: only {' and '.join(map(str, RATES))} Hz were trained")
    sidecar = Path(str(path) + ".json")
    if metadata:
        where, raw, source = f"{path} ONNX metadata", dict(metadata), "metadata"
    elif sidecar.is_file():
        where, source = f"sidecar {sidecar}", "sidecar"
        try:
            raw = json.loads(sidecar.read_text())
        except ValueError as exc:
            raise ValueError(f"{where}: not JSON ({exc})") from None
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: a JSON object expected")
    elif model_rate is not None:
        step, lateral = RATES[model_rate]
        return {"task": None, "policy_step_s": step, "lateral_limit": lateral, "obs_layout": OBS_LAYOUT, "source": "flag"}
    else:
        raise ValueError(f"{path}: the model does not say what rate it was trained at (no ONNX metadata, no sidecar {sidecar}) and "
                         f"--model-rate was not given: pass --model-rate 50 (Mjlab-Nav-MicroDuck) or 10 (Mjlab-Nav-Deploy-MicroDuck)")
    layout = raw.get("obs_layout", OBS_LAYOUT)
    if layout != OBS_LAYOUT:
        raise ValueError(f"{where}: obs_layout {layout!r}, this controller builds {OBS_LAYOUT!r}")
    spec = {"task": raw.get("task"), "policy_step_s": _number(raw, "policy_step_s", where, 0.0, True),
            "lateral_limit": _number(raw, "lateral_limit", where, 0.0, False), "obs_layout": layout, "source": source}
    if model_rate is not None and abs(RATES[model_rate][0] - spec["policy_step_s"]) > 1e-9:
        raise ValueError(f"{path}: --model-rate {model_rate} means a policy step of {RATES[model_rate][0]} s but the model's {source} says "
                         f"{spec['policy_step_s']} s: drop the flag or fix the {source}")
    return spec


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


def axial_factors(tof) -> np.ndarray:
    """What a reading (m) is multiplied by to be the depth along the optical axis, which is what the model trained on: each zone's
    beam x component for a sensor that reads along the beam (the simulator's), 1 for one that already reads along the axis."""
    if tof.range_kind == "axial":
        return np.ones(ZONES)
    return np.array([b[0] for b in tof.beams])


def far_floor(depth: np.ndarray, floor: np.ndarray) -> np.ndarray:
    """Which zones training's floor-validity impairment drops: a floor return (`floor`) at or past FLOOR_VALIDITY_M of optical-axis depth.
    A return that is not the floor, however far, is never dropped by it (impairments.py:113, `torch.where(floor_hit, floor_dropout, p)`)."""
    return np.asarray(floor, dtype=bool) & (np.asarray(depth, dtype=float) >= FLOOR_VALIDITY_M)


def floor_zones(tof, frame: dict, body: dict) -> np.ndarray:
    """Which zones of `frame` read the floor, by the navigator's own test (Tof8x8.depth_points: the return's height above the floor under the
    sensor's pose in `body` is under floor_margin_m + floor_margin_per_m x range, and not below the floor by extra_m). Training knows it
    exactly (the ray's hit at world z 0, impairments.py:99-101); the navigator can only estimate it, and a thing under that margin high reads as floor."""
    try:
        height, q = tof.sensor_pose(body)
    except (KeyError, TypeError, IndexError):
        raise ValueError("body: the sensor's pose is missing (odom position and the tof frame), so the floor returns cannot be told from the rest") from None
    mm = _numbers(frame["distance_mm"], ZONES, "frame distance_mm")
    out = np.zeros(ZONES, dtype=bool)
    for i, beam in enumerate(tof.beams):
        if mm[i] <= 0:
            continue
        r = tof.along_beam(mm[i], beam)
        d = rotate(q, beam)
        h = math.hypot(r * d[0], r * d[1])
        out[i] = -tof.extra_m <= height + r * d[2] < tof.floor_margin_m + tof.floor_margin_per_m * h
    return out


def _tick(frame: dict, valid: set, axial: np.ndarray, floor=None) -> np.ndarray:
    """One frame as the model reads it: 64 depths along the optical axis in metres, then 64 valid flags; an invalid return is 0 (a
    missing return is not free space, so its flag says so). `floor` (frame -> 64 bools, see floor_zones) turns on training's floor-validity
    impairment: the floor returns it drops are invalid, as in training."""
    mm = _numbers(frame["distance_mm"], ZONES, "frame distance_mm")
    status = np.asarray(frame["status"]).reshape(-1)
    if status.shape != (ZONES,):
        raise ValueError(f"frame status: {ZONES} numbers expected, got {status.shape[0]}")
    metres = (mm / 1000.0 * axial).astype(np.float32).astype(float)       # training judges its bounds in float32: 4.0 m must stay 4.0 m
    ok = np.isin(status, list(valid)) & (metres >= MIN_RANGE_M) & (metres <= MAX_RANGE_M)
    if floor is not None:
        ok &= ~far_floor(metres, floor(frame))
    return np.concatenate((np.where(ok, metres, 0.0), ok.astype(float)))


def observation(requested, ranges: list, body: dict, applied, valid: set, step_s: float, previous_action, joint_velocity,
                axial=None, floor=None) -> np.ndarray:
    """microduck-nav's 1343 inputs: gyro 3, projected gravity 3, joint positions less the default 14, joint velocities 14 (the caller's,
    one tick late), previous action 3, requested velocity 3, zeros 10 (head and body pose commands), applied command 3, ten steps of
    64 depths and 64 flags oldest first, ten frame ages. `step_s` spaces the ten steps: the model's control step, not the navigator's
    tick. `axial` (64 factors, see axial_factors) turns a sensor's readings into optical-axis depths; None for one that reads so. `floor` (frame -> 64 bools) drops the floor returns past training's validity range (_tick); None keeps every return. Raises
    ValueError for an input that is not finite or not as long as it must be."""
    axial = np.ones(ZONES) if axial is None else axial
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
        offset = k * step_s
        fresh = [(a, f) for f, a in ranges if a >= offset - 1e-9]
        if fresh:
            age, frame = min(fresh, key=lambda c: c[0])
            obs[53 + slot * 128:53 + (slot + 1) * 128] = _tick(frame, valid, axial, floor)
            obs[1333 + slot] = age - offset
        else:
            obs[1333 + slot] = EMPTY_AGE_S
    return obs


class Learned:
    name = "learned"
    version = 1

    def __init__(self, profile, model, tick_s: float = 0.1, model_rate: int | None = None):
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
        self.spec = model_spec(self.path, self.session.get_modelmeta().custom_metadata_map, model_rate)
        self.bind(profile)
        self.tick_s = tick_s
        self.residual = ResidualCommand(tick_s, limits=(LIMITS[0], self.spec["lateral_limit"], LIMITS[2]))
        self.last_error = None
        self.reset()

    def bind(self, profile) -> None:
        self.valid = set(profile.sensors.tof8x8.valid_status)
        self.tof = Tof8x8(profile)
        self.axial = axial_factors(self.tof)
        turn = profile.locomotion.get("stand_turn.min_rad_s")       # a turn on the spot under it never starts the walker (profile.json)
        self.pivot_min = float(turn) if turn else None

    def reset(self) -> None:
        self.residual.reset()
        self.previous_action = np.zeros(ACTION_DIM)
        self.joint_velocity = np.zeros(len(NAV_JOINTS))
        self.decision = "idle"      # what the last tick did: "pivot" (the request passed through), "model", "idle" (nothing to ask the model) or "brake"

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "ident": self.ident,
                "model": {"path": str(self.path), "sha256": self.sha256, "task": self.spec["task"], "policy_step_s": self.spec["policy_step_s"],
                          "lateral_limit": self.spec["lateral_limit"], "obs_layout": self.spec["obs_layout"], "spec_source": self.spec["source"],
                          "input": {"name": self.input.name, "shape": list(self.input.shape)},
                          "output": {"name": self.output.name, "shape": list(self.output.shape)}}}

    def command(self, requested, ranges, body, applied):
        try:
            return self._command(requested, ranges, body, applied)
        except Exception as exc:        # noqa: BLE001 - whatever the model or an input does, the answer is the brake
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._brake(requested, applied)

    def _remember_velocity(self, body, strict: bool = True) -> None:
        """The joint velocities of this tick, for the next one's observation (the model reads them one step late), kept on every tick
        and not only those the model runs on, so a tick after a pause does not read the pause's."""
        if body is None:
            return
        try:
            velocities = _numbers(body["velocities"], len(JOINTS), "joint velocities")
        except (KeyError, ValueError):
            if strict:
                raise
            return
        self.joint_velocity = velocities[[i for i, n in enumerate(JOINTS) if n != "mouth"]]

    def _vectors(self, requested, applied):
        return (np.array([requested.vx, 0.0, requested.vyaw], dtype=float), np.array([applied.vx, 0.0, applied.vyaw], dtype=float))

    def _brake(self, requested, applied) -> Twist:
        """The residual (-1, 0, 0) through the same limits and slew; a plain stop when the request or the applied command is itself
        not a number."""
        req, app = self._vectors(requested, applied)
        self.previous_action = brake_action()
        self.decision = "brake"
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
        if self.pivot_min and abs(req[0]) < 1e-9 and abs(req[2]) >= self.pivot_min:
            # The residual's yaw limit (0.75) is under the walker's turn floor, so a model pivot never starts the duck; training's clip is on
            # the residual and its sum (microduck-nav residual_action.py), the rules controller passes the follower's pivot through, so this does.
            self.decision = "pivot"
            self.previous_action = np.zeros(ACTION_DIM)
            self._remember_velocity(body, strict=False)
            self.residual.previous = np.array([0.0, 0.0, req[2]])
            return Twist(0.0, float(req[2]))
        self.residual.previous = app
        ages = [float(a) for _, a in ranges]
        if not np.isfinite(ages).all():
            raise ValueError("frame age: not finite")
        have = bool(ranges) and body is not None
        age = min(ages, default=0.0)
        if not have or age > MAX_AGE_S or not req.any():
            self.decision = "idle"
            self.previous_action = np.zeros(ACTION_DIM)
            self._remember_velocity(body, strict=False)
            cmd = self.residual.process(req, np.zeros(ACTION_DIM), have, age)
            return Twist(float(cmd[0]), float(cmd[2]))
        obs = observation(requested, ranges, body, applied, self.valid, self.spec["policy_step_s"], self.previous_action, self.joint_velocity, self.axial,
                          floor=lambda frame: floor_zones(self.tof, frame, body))
        self._remember_velocity(body)
        out = self.session.run(None, {self.input.name: obs[None, :]})[0].reshape(-1)
        if out.shape != (ACTION_DIM,) or not np.isfinite(out).all():
            return self._brake(requested, applied)
        self.previous_action = np.clip(out.astype(float), -1.0, 1.0)
        self.decision = "model"
        cmd = self.residual.process(req, out, True, age)
        return Twist(float(cmd[0]), float(cmd[2]))
