"""The local-controller seam (RFC-0025 section 3.7, R3): a fifth plugin interface between the follower and the guards. `rules@1` hands the
follower's command back as it is (the default, both profiles); `learned@<sha8>` runs an ONNX residual policy with NVIDIA's observation and
`microduck-nav`'s residual action (limits, never faster than asked, slew, stale gives zero), brakes on a non-finite input, and is refused on
a real robot. The guards stay above it. A tiny random-weight ONNX is written here, by hand, so no extra package is needed. No simulator.
Run: cd robots/duck && uv run python tests/test_local_controller.py"""

import argparse
import atexit
import collections
import hashlib
import io
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import numpy as np

from duck_lab import payload, plugins
from duck_lab.nav import run as nav_run
from duck_lab.nav import server
from duck_lab.nav.follow import Twist
from duck_lab.nav.run import Navigator
from duck_lab.nav.runlog import JOINTS
from duck_lab.nav.side_drops import SuspectMemory
from duck_lab.plugins import interfaces
from duck_lab.plugins.learned import DEFAULT, MODEL_STEP_S, NAV_JOINTS, Learned, ResidualCommand, axial_factors, brake_action, observation
from duck_lab.plugins.rules import Rules
from duck_lab.plugins.tof8x8 import Tof8x8
from duck_lab.profile import load
from runfile import build
from runfile.profile import validate_profile

failures = []


def check(name, cond, detail=""):
    shown = str(detail)[:300]
    print(("PASS " if cond else "FAIL ") + name + (f"  [{shown}]" if shown else ""))
    if not cond:
        failures.append(name)


SIM, REAL = load("sim"), load(None)
tmp = Path(tempfile.mkdtemp(prefix="local-controller-"))
atexit.register(shutil.rmtree, tmp, True)
NS = 1_000_000_000


# ---- a tiny ONNX, written by hand (protobuf wire format): obs (1, 1343) -> MatMul(W) -> Add(b) -> action (1, 3) --------------------
def varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def vi(num, n):
    return varint(num << 3) + varint(n)


def ld(num, data):
    return varint(num << 3 | 2) + varint(len(data)) + data


def text(num, s):
    return ld(num, s.encode())


def tensor(name, dims, values):
    return b"".join(vi(1, d) for d in dims) + vi(2, 1) + text(8, name) + ld(9, struct.pack(f"<{len(values)}f", *values))


def value_info(name, dims):
    shape = b"".join(ld(1, vi(1, d)) for d in dims)
    return text(1, name) + ld(2, ld(1, vi(1, 1) + ld(2, shape)))


def write_onnx(path, weights, bias, input_name="obs", output_name="action", width=1343, meta=None):
    nodes = ld(1, text(1, input_name) + text(1, "w") + text(2, "mm") + text(4, "MatMul")) + \
        ld(1, text(1, "mm") + text(1, "b") + text(2, output_name) + text(4, "Add"))
    graph = nodes + text(2, "g") + ld(5, tensor("w", [width, 3], weights)) + ld(5, tensor("b", [1, 3], bias)) + \
        ld(11, value_info(input_name, [1, width])) + ld(12, value_info(output_name, [1, 3]))
    props = b"".join(ld(14, text(1, k) + text(2, v)) for k, v in (meta or {}).items())
    path.write_bytes(vi(1, 8) + text(2, "test") + ld(7, graph) + ld(8, text(1, "") + vi(2, 17)) + props)
    return path


rng = random.Random(0)
RANDOM = write_onnx(tmp / "random.onnx", [rng.uniform(-0.05, 0.05) for _ in range(1343 * 3)], [0.0, 0.0, 0.0])
PUSH = write_onnx(tmp / "push.onnx", [0.0] * (1343 * 3), [1.0, 1.0, 1.0], input_name="observations", output_name="residuals")
SHORT = write_onnx(tmp / "short.onnx", [0.0] * (10 * 3), [0.0, 0.0, 0.0], width=10)

# ---- the interface, and rules@1 as the identity ---------------------------------------------------------------------------------
check("a fifth interface: LocalController, in the plugins' INTERFACES", plugins.INTERFACES.get("local_controller") is interfaces.LocalController)
check("rules@1 is registered", plugins.REGISTRY.get("rules@1") is Rules)
for variant, p in (("sim", SIM), ("real", REAL)):
    check(f"the {variant} profile names rules@1 for the local controller", p.plugins.data.get("local_controller") == "rules@1", p.plugins.data)
    loaded = plugins.load(p)
    check(f"... and loads it as a LocalController ({variant})", isinstance(loaded["local_controller"], interfaces.LocalController)
          and loaded["local_controller"].ident == "rules@1", loaded.get("local_controller"))
raw = json.loads((Path(SIM.meta["path"])).read_text())
old = json.loads(json.dumps(raw))
del old["plugins"]["local_controller"]
check("a stored profile that names none still validates (absent means rules@1)", validate_profile(old) is not None)
tw = Twist(0.21, -0.4)
ctrl = Rules(SIM)
check("rules@1 returns the follower's command itself, whatever it is handed",
      ctrl.command(tw, [({"distance_mm": [1] * 64}, 0.0)], {"imu": {}}, Twist(9.0, 9.0)) is tw and ctrl.command(Twist(), [], None, Twist()) == Twist())
check("rules@1's identity string and record", ctrl.ident == "rules@1" and ctrl.describe()["ident"] == "rules@1")


# ---- a navigator from the duck's real plugins, its sockets replaced (as test_anomaly does) ----------------------------------------
class Rpc:
    def __init__(self, grid=None):
        self.calls, self.grid, self.status = [], grid, {"state": {}}

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "map.grid":
            return dict(self.grid)
        if method == "map.status":
            return self.status
        return {}


def make_grid(width, height, res=0.05):
    return {"res_m": res, "origin": [0.0, 0.0], "width": width, "height": height, "cells": "." * (width * height)}


def navigator(controller=None, pose=(1.0, 2.5, 0.0), nearest_mm=600, cap=None, profile=REAL):
    nav = Navigator.__new__(Navigator)
    nav.robot, nav.mapd = Rpc(), Rpc(make_grid(100, 100))
    nav.configure(profile)
    nav.localisation.bind(nav.mapd)
    nav._t0, nav._log, nav.body, nav.state = time.monotonic(), io.StringIO(), None, types.SimpleNamespace(latest=None, _thread=None)
    nav._states, nav._fv, nav.sense, nav._logging_failed = collections.deque(maxlen=40), None, {}, False
    nav.blocked, nav._seen, nav._low, nav._drop_streak, nav._drop_frame, nav._depth, nav._block = [], set(), {}, 0, None, None, None
    nav.floor_seen, nav.glanced, nav.step_looked, nav.drops, nav.edges, nav._moves = set(), [], [], [], [], []
    sd = nav.profile.sensors.tof8x8.side_drops
    nav.suspects = SuspectMemory(sd.suspect_frames, sd.suspect_ratio, sd.clear_m)
    nav._map_raw, nav.fix_fault, nav.fault_grid, nav.frames_on, nav._world_key = None, None, False, True, None
    nav.abort, nav.semantic, nav.room, nav.area, nav.area_agrees = None, None, None, None, None
    nav._sem_lock, nav._closing, nav._closure_window = threading.Lock(), threading.Event(), []
    nav.range._nearest_mm = nearest_mm
    nav.range.unseen_ahead = lambda *a, **k: None
    nav.localisation.on_odom(NS, pose)
    nav.loc.on_fix(NS, pose)
    nav.speed_cap = cap
    if controller is not None:
        nav.controller = controller
    return nav


def rows(nav):
    return [json.loads(line) for line in nav._log.getvalue().splitlines()]


def sent(nav):
    return [p for m, p in nav.robot.calls if m == "robot.move"]


class Push:
    """A controller that pushes forward whatever it is told, and notes what it was handed."""
    name, version, ident = "push", 1, "push@1"

    def __init__(self, vx=0.3, vyaw=0.0):
        self.out, self.seen = Twist(vx, vyaw), []

    def bind(self, profile): pass
    def reset(self): self.seen.append("reset")
    def describe(self): return {"name": "push", "ident": self.ident}

    def command(self, requested, ranges, body, applied):
        self.seen.append((requested, list(ranges), body, applied))
        return self.out


plain = navigator()
check("a navigator built with no override has rules@1 as its controller", plain.controller.ident == "rules@1", plain.controller)
out = plain.go_to((4.0, 2.5), 1.0)
tick = [r for r in rows(plain) if "applied" in r]
check("rules@1: a tick records requested and applied only, as before (no `local`), the two equal when nothing caps them",
      tick and all("local" not in r and r["requested"]["vx"] == r["applied"]["vx"] for r in tick), tick[:1])
check("rules@1: the calibration event is the one it was (no controller entry)", "local_controller" not in json.dumps([r for r in rows(plain) if r.get("event") == "calibration"]))

# ---- the guards stay above it ----------------------------------------------------------------------------------------------------
push = Push(0.3)
nav = navigator(push, nearest_mm=100)        # a return inside the emergency distance: the reflex must fire
nav.go_to((4.0, 2.5), 1.5)
ev = [r.get("event") for r in rows(nav)]
check("the controller pushes 0.3 m/s forward, a return 0.1 m ahead: the reflex fires", "reflex_stop" in ev, collections.Counter(ev))
check("... and no forward command was ever sent", sent(nav) and all(c["vx"] == 0.0 for c in sent(nav)), sent(nav)[:3])
check("the controller was handed the follower's command, the range history and the last applied command",
      any(isinstance(s, tuple) and s[0].vx > 0 and s[3] == Twist() for s in push.seen), push.seen[:2])

nav = navigator(Push(0.25), cap=0.1)
nav.go_to((4.0, 2.5), 1.0)
tick = [r for r in rows(nav) if r.get("applied", {}).get("vx") not in (None,) and r["requested"]["vx"] > 0]
check("a controller that is not rules@1: the tick records the follower's command as requested, the controller's as local, the capped one as applied",
      tick and all(r["local"] == {"vx": 0.25, "vyaw": 0.0} and r["applied"]["vx"] == 0.1 and r["requested"]["vx"] == 0.3 for r in tick), tick[:1])
check("the speed cap still applies to what the controller asked for", all(c["vx"] <= 0.1 + 1e-9 for c in sent(nav)), sent(nav)[:3])
nxt = [s for s in nav.controller.seen if isinstance(s, tuple)]
check("the next tick's `applied` is what was sent (0.1), not what the controller asked", any(abs(s[3].vx - 0.1) < 1e-9 for s in nxt[1:]), [s[3] for s in nxt[:4]])
check("a goal's start resets the controller", nav.controller.seen[0] == "reset", nav.controller.seen[:1])

# ---- the residual action: microduck-nav's hand cases (test_c5_residual_action.py), ported ------------------------------------------
DT = 0.02


def term(prev=None, dt=DT):
    t = ResidualCommand(dt=dt)
    t.previous = np.array(prev if prev is not None else [0.0, 0.0, 0.0], dtype=np.float64)
    return t


def run(t, requested, action, age=0.0, have=True):
    return t.process(np.array(requested, dtype=np.float64), np.array(action, dtype=np.float64), have, age)


t = ResidualCommand(dt=DT)
check("the defaults are the contract: limits (0.35, 0.12, 0.75), slew (1, 1, 3), 0.25 s, lateral 0.35 of forward",
      list(t.limits) == [0.35, 0.12, 0.75] and list(t.slew) == [1.0, 1.0, 3.0] and t.max_age == 0.25 and t.max_lateral_ratio == 0.35)
norm = math.hypot(0.35, 0.12)
scale = 0.3 / norm
c = run(term(prev=[0.35 * scale, 0.12 * scale, 0.75]), [0.3, 0.0, 0.5], [1.0, 1.0, 1.0])
check("each axis is clamped and the speed cap scales translation to the request",
      abs(c[0] - 0.35 * scale) < 1e-6 and abs(c[1] - 0.12 * scale) < 1e-6 and abs(c[2] - 0.75) < 1e-6 and abs(math.hypot(c[0], c[1]) - 0.3) < 1e-6, c)
check("an action is clipped to [-1, 1]", np.array_equal(run(term(prev=[0.2, 0, 0]), [0.2, 0, 0], [5.0, 0, 0]), run(term(prev=[0.2, 0, 0]), [0.2, 0, 0], [1.0, 0, 0])))
check("never faster than requested when unslewed", all(math.hypot(*run(term(prev=[0.15, 0, 0]), [0.15, 0, 0], [f, l, 0.0])[:2]) <= 0.15 + 1e-6
                                                       for f in (-1.0, 0.0, 0.4, 1.0) for l in (-1.0, 0.0, 1.0)))
check("no reverse", run(term(prev=[0, 0, 0]), [0.1, 0, 0], [-1.0, 0, 0])[0] == 0.0)
check("forward slews at 1 m/s^2: 0.02 in one 20 ms step", abs(run(term(), [0.3, 0, 0], [0, 0, 0])[0] - 0.02) < 1e-9)
check("yaw slews at 3 rad/s^2: 0.06 in one step", abs(run(term(), [0.2, 0, 0.75], [0, 0, 0])[2] - 0.06) < 1e-9)
t = term()
for _ in range(10):
    c = run(t, [0.2, 0, 0], [0, 0, 0])
check("the request is reached after ten ticks", abs(c[0] - 0.2) < 1e-6, c)
check("a brake slews down, not jumps: 0.3 to 0.28", abs(run(term(prev=[0.3, 0, 0]), [0.3, 0, 0], [-1.0, 0, 0])[0] - 0.28) < 1e-9)
check("a slewed speed can exceed a lowered request: 0.3 held at 0.28 against a 0.1 request", abs(run(term(prev=[0.3, 0, 0]), [0.1, 0, 0], [0, 0, 0])[0] - 0.28) < 1e-9)
c = run(term(prev=[0.1, 0.12, 0.0]), [0.1, 0, 0], [0, 1.0, 0])
check("lateral stays inside 0.35 of forward", abs(c[1]) <= 0.35 * c[0] + 1e-7 and run(term(prev=[0, 0, 0]), [0, 0.1, 0], [0, 0, 0])[1] == 0.0, c)
t = term(prev=[0.3, 0.1, 0.5])
check("a zero request stops at once, even while moving, and the next one restarts from zero",
      run(t, [0, 0, 0], [1, 1, 1]).tolist() == [0.0, 0.0, 0.0] and abs(run(t, [0.2, 0, 0], [0, 0, 0])[0] - 0.02) < 1e-9)
check("a frame older than 0.25 s, or none, stops at once",
      run(term(prev=[0.3, 0, 0]), [0.3, 0, 0], [0, 0, 0], age=0.26).tolist() == [0.0, 0.0, 0.0]
      and run(term(prev=[0.3, 0, 0]), [0.3, 0, 0], [0, 0, 0], have=False).tolist() == [0.0, 0.0, 0.0])
check("exactly 0.25 s is still fresh", abs(run(term(prev=[0.3, 0, 0]), [0.3, 0, 0], [0, 0, 0], age=0.25)[0] - 0.3) < 1e-9)
t = term(prev=[0.3, 0, 0])
run(t, [0.3, 0, 0], [0, 0, 0], age=1.0)
check("after a stop the next command restarts from zero", abs(run(t, [0.3, 0, 0], [0, 0, 0], age=0.0)[0] - 0.02) < 1e-9)


def deployed(action, requested, prev, have, age, dt):
    """NVIDIA's command_from_action (nav_pad.py:104-116) as microduck-nav's test states it."""
    lim, slew = np.array([0.35, 0.12, 0.75]), np.array([1.0, 1.0, 3.0])
    cmd = requested + np.clip(action, -1.0, 1.0) * lim
    cmd = np.clip(cmd, [0.0, -lim[1], -lim[2]], lim)
    req_speed, speed = np.linalg.norm(requested[:2]), max(np.linalg.norm(cmd[:2]), 1e-6)
    cmd[:2] *= min(req_speed / speed, 1.0)
    cmd = prev + np.clip(cmd - prev, -slew * dt, slew * dt)
    cmd[1] = np.clip(cmd[1], -0.35 * cmd[0], 0.35 * cmd[0])
    if not requested.any() or not have or age > 0.25:
        cmd[:] = 0.0
    return cmd


g = np.random.default_rng(0)
worst = 0.0
for _ in range(300):
    rq = np.array([g.uniform(0, 0.35), g.uniform(-0.1, 0.1), g.uniform(-0.75, 0.75)])
    ac, pv, age = g.uniform(-1.5, 1.5, 3), np.array([g.uniform(0, 0.35), g.uniform(-0.12, 0.12), g.uniform(-0.75, 0.75)]), float(g.uniform(0, 0.4))
    worst = max(worst, float(np.abs(term(prev=pv).process(rq, ac, True, age) - deployed(ac, rq, pv, True, age, DT)).max()))
check("300 random cases equal the deployment function's", worst < 1e-9, worst)
check("the brake is a full back-off with no steering residual", list(brake_action()) == [-1.0, 0.0, 0.0])


# ---- the observation: NVIDIA's 1343 -----------------------------------------------------------------------------------------------
def frame(mm=1000, status=5, seq=0):
    return {"rows": 8, "cols": 8, "distance_mm": [mm] * 64, "status": [status] * 64, "t_ns": seq, "seq": seq}


def body_state(gyro=(0.1, 0.2, 0.3), quat=(1.0, 0.0, 0.0, 0.0), vel=0.0):
    return {"imu": {"quat": list(quat), "gyro": list(gyro)}, "joints": [0.01 * i for i in range(len(JOINTS))], "velocities": [vel] * len(JOINTS)}


valid = set(SIM.sensors.tof8x8.valid_status)
o = observation(Twist(0.25, 0.4), [(frame(1000), 0.0)], body_state(), Twist(0.1, 0.2), valid, step_s=0.1, previous_action=np.array([0.5, -0.5, 0.25]),
                joint_velocity=np.zeros(14))
check("the vector is 1343 floats, all finite", o.shape == (1343,) and np.isfinite(o).all(), o.shape)
check("0-2 the gyro, 3-5 the gravity in the body frame (down, level)", o[0:3].tolist() == [np.float32(0.1), np.float32(0.2), np.float32(0.3)]
      and np.allclose(o[3:6], [0.0, 0.0, -1.0], atol=1e-6), o[:6])
check("6-19 fourteen joints less the default pose, the mouth dropped (left hip roll 0.01 - (-0.0873); right hip yaw is the 10th of robotd's 15)",
      abs(o[7] - 0.0973) < 1e-6 and abs(o[6 + 9] - 0.10) < 1e-6 and abs(o[6 + 13] - (0.14 + 0.4530)) < 1e-6, o[6:20])
check("34-36 the previous action, 37-39 the request (vx, 0, vyaw), 40-49 zeros, 50-52 the applied command",
      o[34:37].tolist() == [0.5, -0.5, 0.25] and np.allclose(o[37:40], [0.25, 0.0, 0.4]) and not o[40:50].any() and np.allclose(o[50:53], [0.1, 0.0, 0.2]), o[34:53])
check("the newest tick is last: its 64 ranges in metres (1.0) then its 64 valid flags (1.0)",
      np.allclose(o[53 + 9 * 128:53 + 9 * 128 + 64], 1.0) and np.allclose(o[53 + 9 * 128 + 64:53 + 10 * 128], 1.0), o[53 + 9 * 128:53 + 9 * 128 + 4])
check("the nine ticks before it have no frame: zeros, not valid, aged 1 s", not o[53:53 + 9 * 128].any() and np.allclose(o[1333:1342], 1.0) and abs(o[1342]) < 1e-9, o[1333:])
bad = frame(5000, status=5)
bad["distance_mm"][1] = 100
bad["status"][2] = 255
o = observation(Twist(0.25, 0), [(bad, 0.0)], body_state(), Twist(), valid, step_s=0.1, previous_action=np.zeros(3), joint_velocity=np.zeros(14))
last = o[53 + 9 * 128:53 + 10 * 128]
check("a return under 0.12 m, over 4 m or with a no-target status is written 0 and its flag 0 (a missing return is not free space)",
      last[0] == 0 and last[64] == 0 and last[1] == 0 and last[65] == 0 and last[2] == 0 and last[66] == 0, last[:3])
hist = [(frame(1000 + 100 * k, seq=k), 0.05 + 0.1 * (4 - k)) for k in range(5)]
o = observation(Twist(0.25, 0), hist, body_state(), Twist(), valid, step_s=0.1, previous_action=np.zeros(3), joint_velocity=np.zeros(14))
ages = o[1333:1343]
check("a history of frames 0.1 s apart fills the ticks oldest first, each with its own age (0.05 s for the newest)",
      abs(ages[9] - 0.05) < 1e-6 and abs(ages[8] - 0.05) < 1e-6 and ages[:5].min() >= 0 and abs(o[53 + 9 * 128] - 1.4) < 1e-5, (ages, o[53 + 9 * 128]))

# ---- parity with microduck-nav's training observation (R4): the golden vectors the training code builds, rebuilt here ----------------
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "obs_parity.json").read_text())
DEPLOY = json.loads((Path(__file__).parent / "fixtures" / "obs_parity_deploy.json").read_text())


def golden_frame(axial_m, profile, golden=GOLDEN):
    """A training frame (optical-axis metres, 0 where the zone gave nothing) as this profile's sensor would report it."""
    t = profile.sensors.tof8x8
    factor = np.array(golden["zone_axial_factor"]) if t.mount.range_kind == "radial" else np.ones(64)
    mm = np.array(axial_m) / factor * 1000.0
    status = [t.valid_status[0] if m > 0 else t.no_target_status for m in axial_m]
    return {"rows": 8, "cols": 8, "distance_mm": mm.tolist(), "status": status, "t_ns": 0, "seq": 0}


for golden, label in ((GOLDEN, "50 Hz"), (DEPLOY, "10 Hz")):
    for profile in (SIM, REAL):
        kind = profile.sensors.tof8x8.mount.range_kind
        axial = axial_factors(Tof8x8(profile))
        for st in golden["states"]:
            enc = [p + b for p, b in zip(st["joint_pos"], st["backlash"])]
            enc.insert(JOINTS.index("mouth"), 0.0)
            vel = list(st["joint_vel"])
            vel.insert(JOINTS.index("mouth"), 0.0)
            body = {"imu": {"quat": st["quat"], "gyro": st["gyro"]}, "joints": enc, "velocities": vel}
            ranges = [(golden_frame(f["axial_m"], profile, golden), f["age_s"]) for f in st["frames"]]
            got = observation(Twist(st["requested"][0], st["requested"][2]), ranges, body, Twist(st["applied"][0], st["applied"][2]),
                              set(profile.sensors.tof8x8.valid_status), step_s=golden["step_s"], previous_action=np.array(st["previous_action"]),
                              joint_velocity=np.array(st["joint_vel"]), axial=axial)
            want = np.array(st["observation"])
            worst = int(np.abs(got - want).argmax())
            check(f"parity with the training observation at {label}, {st['name']} state, {kind} ranges: all 1343 within 1e-6",
                  np.abs(got - want).max() <= golden["tolerance"], f"worst slot {worst}: {got[worst]} vs {want[worst]}")

# ---- the learned controller ------------------------------------------------------------------------------------------------------------
check("the model's control step is the training env's step_dt (50 Hz), the history's spacing", abs(MODEL_STEP_S - GOLDEN["step_s"]) < 1e-9, GOLDEN["step_s"])
check("the 14 joints are the training env's, in its order, less the mouth", list(NAV_JOINTS) == GOLDEN["joints"], (NAV_JOINTS, GOLDEN["joints"]))
check("their default pose is the training env's", np.allclose(DEFAULT, GOLDEN["default_pose"], atol=1e-6), (DEFAULT, GOLDEN["default_pose"]))
check("the simulator's radial ranges become optical-axis depths by the training grid's own factors, the real duck's (axial) are left alone",
      np.allclose(Learned(SIM, RANDOM, model_rate=50).axial, GOLDEN["zone_axial_factor"], atol=1e-6) and np.allclose(axial_factors(Tof8x8(REAL)), 1.0))

sha = hashlib.sha256(RANDOM.read_bytes()).hexdigest()
ln = Learned(SIM, RANDOM, model_rate=50)
check("it names itself learned@<8 of the model's sha256>", ln.ident == f"learned@{sha[:8]}" and isinstance(ln, interfaces.LocalController), ln.ident)
d = ln.describe()
check("it records the model's full sha256 and its input and output", d["model"]["sha256"] == sha and d["model"]["input"] == {"name": "obs", "shape": [1, 1343]}
      and d["model"]["output"] == {"name": "action", "shape": [1, 3]} and d["ident"] == ln.ident, d)
check("the input's name is read from the file, not assumed", Learned(SIM, PUSH, model_rate=50).describe()["model"]["input"]["name"] == "observations")
try:
    Learned(SIM, SHORT, model_rate=50)
    wrong = False
except ValueError as e:
    wrong = "1343" in str(e)
check("a model whose input is not 1343 wide is refused, naming it", wrong)
try:
    Learned(SIM, tmp / "missing.onnx", model_rate=50)
    gone = False
except (OSError, ValueError):
    gone = True
check("a model file that is not there is refused", gone)

ln = Learned(SIM, RANDOM, model_rate=50)
applied, outs = Twist(), []
for i in range(6):
    body = body_state(vel=0.01 * i)
    rngs = [(frame(800 + 20 * k + i), 0.04 + 0.066 * (3 - k)) for k in range(4)]
    out = ln.command(Twist(0.3, 0.2), rngs, body, applied)
    outs.append(out)
    applied = out
check("a random-weight model runs six ticks: finite, never faster than asked (0.3), no reverse, within the yaw limit",
      all(isinstance(x, Twist) and math.isfinite(x.vx) and math.isfinite(x.vyaw) and 0.0 <= x.vx <= 0.3 + 1e-9 and abs(x.vyaw) <= 0.75 for x in outs), outs)
check("... slewed from standing: no tick jumps more than 0.1 m/s (1 m/s^2 over a 0.1 s tick)",
      all(abs(b.vx - a.vx) <= 0.1 + 1e-9 for a, b in zip([Twist()] + outs, outs)), outs)
push = Learned(SIM, PUSH, model_rate=50)
out = push.command(Twist(0.3, 0.0), [(frame(), 0.0)], body_state(), Twist(0.3, 0.0))
check("a model that pushes every residual to +1 cannot go faster than the follower: vx stays at or under 0.3", 0.0 < out.vx <= 0.3 + 1e-9, out)
check("no frame at all: zero (the model is not run on nothing)", ln.command(Twist(0.3, 0.2), [], body_state(), Twist(0.2, 0.0)) == Twist(0.0, 0.0))
check("a frame older than 0.25 s: zero", ln.command(Twist(0.3, 0.2), [(frame(), 0.3)], body_state(), Twist(0.2, 0.0)) == Twist(0.0, 0.0))
check("a stopped follower (zero request): zero", ln.command(Twist(0.0, 0.0), [(frame(), 0.0)], body_state(), Twist(0.2, 0.0)) == Twist(0.0, 0.0))
ln.command(Twist(0.0, 0.0), [(frame(), 0.0)], body_state(vel=0.7), Twist())
check("the joint velocities are kept on a tick the model does not run on, so the first tick after a pause is not a stale one", np.allclose(ln.joint_velocity, 0.7), ln.joint_velocity)
check("no robot state: zero", ln.command(Twist(0.3, 0.0), [(frame(), 0.0)], None, Twist(0.2, 0.0)) == Twist(0.0, 0.0))

# ---- the model's rate and lateral limit travel with the model: metadata, then a sidecar, then --model-rate; none is refused -----------
import duck_lab.plugins.learned as learned_mod
from duck_lab.nav import controller_args

META_10 = {"task": "Mjlab-Nav-Deploy-MicroDuck", "policy_step_s": "0.1", "lateral_limit": "0.0", "obs_layout": "nav-1343-v1"}
META_50 = {"task": "Mjlab-Nav-MicroDuck", "policy_step_s": "0.02", "lateral_limit": "0.12", "obs_layout": "nav-1343-v1"}
bare = write_onnx(tmp / "bare.onnx", [0.0] * (1343 * 3), [0.0, 0.0, 0.0])


def refused_with(*words, **kw):
    try:
        Learned(SIM, kw.pop("model", bare), **kw)
    except ValueError as e:
        return all(w in str(e) for w in words)
    return False


check("a model with no metadata, no sidecar and no --model-rate is refused, saying what to give (never guessed)", refused_with("rate", "--model-rate", ".onnx.json"))
for rate, step, lat in ((50, 0.02, 0.12), (10, 0.1, 0.0)):
    sp = Learned(SIM, bare, model_rate=rate).spec
    check(f"--model-rate {rate}: policy step {step} s, lateral limit {lat}, from the flag",
          sp["policy_step_s"] == step and sp["lateral_limit"] == lat and sp["source"] == "flag" and sp["task"] is None, sp)
check("--model-rate 25 is refused (only 50 and 10 were trained)", refused_with("50", "10", model_rate=25))
side = write_onnx(tmp / "side.onnx", [0.0] * (1343 * 3), [0.0, 0.0, 0.0])
sidecar = Path(str(side) + ".json")
sidecar.write_text(json.dumps({"task": "Mjlab-Nav-Deploy-MicroDuck", "policy_step_s": 0.1, "lateral_limit": 0.0, "obs_layout": "nav-1343-v1"}))
sp = Learned(SIM, side).spec
check("a sidecar <model>.onnx.json is read: the task, 0.1 s, lateral 0", sp == {"task": "Mjlab-Nav-Deploy-MicroDuck", "policy_step_s": 0.1,
      "lateral_limit": 0.0, "obs_layout": "nav-1343-v1", "source": "sidecar"}, sp)
check("... and the same rate on the flag is fine; the sidecar comes before it", Learned(SIM, side, model_rate=10).spec["source"] == "sidecar")
check("a flag that disagrees with the sidecar is refused, not silently dropped", refused_with("50", "0.1", model=side, model_rate=50))
sidecar.write_text(json.dumps({"policy_step_s": 0.02}))
check("a sidecar without lateral_limit is refused, naming the key", refused_with("lateral_limit", model=side))
sidecar.write_text("{not json")
check("a sidecar that is not JSON is refused", refused_with("sidecar", model=side))
sidecar.write_text(json.dumps({"policy_step_s": -0.1, "lateral_limit": 0.0}))
check("a sidecar with a step that is not positive is refused", refused_with("policy_step_s", model=side))
sidecar.write_text(json.dumps({"policy_step_s": 0.1, "lateral_limit": 0.0, "obs_layout": "nav-9999-v9"}))
check("a sidecar for another observation layout is refused", refused_with("obs_layout", model=side))
meta = write_onnx(tmp / "meta.onnx", [0.0] * (1343 * 3), [0.0, 0.0, 0.0], meta=META_10)
Path(str(meta) + ".json").write_text(json.dumps({"policy_step_s": 0.02, "lateral_limit": 0.12}))
sp = Learned(SIM, meta, model_rate=10).spec
check("ONNX metadata comes first: it wins over a sidecar that says 50 Hz", sp["policy_step_s"] == 0.1 and sp["lateral_limit"] == 0.0 and sp["source"] == "metadata"
      and sp["task"] == "Mjlab-Nav-Deploy-MicroDuck", sp)
check("a flag that disagrees with the metadata is refused", refused_with("50", model=meta, model_rate=50))
half = write_onnx(tmp / "half.onnx", [0.0] * (1343 * 3), [0.0, 0.0, 0.0], meta={"policy_step_s": "0.1"})
check("metadata with a step and no lateral limit is refused, not completed from a sidecar or a flag", refused_with("lateral_limit", model=half, model_rate=10))
m50 = write_onnx(tmp / "m50.onnx", [0.0] * (1343 * 3), [0.0, 0.0, 0.0], meta=META_50)
check("metadata of the 50 Hz task: 0.02 s, lateral 0.12", Learned(SIM, m50).spec["policy_step_s"] == 0.02 and Learned(SIM, m50).spec["lateral_limit"] == 0.12)

ten, fifty = Learned(SIM, meta), Learned(SIM, m50)
check("the residual takes the lateral limit from the model: 0 for the 10 Hz one, 0.12 for the 50 Hz one", ten.residual.limits[1] == 0.0 and fifty.residual.limits[1] == 0.12
      and list(ten.residual.limits[[0, 2]]) == [0.35, 0.75], (ten.residual.limits, fifty.residual.limits))
steps, real_observation = [], learned_mod.observation
learned_mod.observation = lambda *a, **kw: (steps.append(a[5]), real_observation(*a, **kw))[1]
try:
    for ctrl in (ten, fifty):
        ctrl.command(Twist(0.3, 0.0), [(frame(), 0.0)], body_state(), Twist(0.2, 0.0))
finally:
    learned_mod.observation = real_observation
check("the history is spaced by the model's own step: 0.1 s for the 10 Hz model, 0.02 s for the 50 Hz one", steps == [0.1, 0.02], steps)
d = ten.describe()["model"]
check("describe records the task, the rate, the lateral limit, the layout and where they came from", d["task"] == "Mjlab-Nav-Deploy-MicroDuck" and d["policy_step_s"] == 0.1
      and d["lateral_limit"] == 0.0 and d["obs_layout"] == "nav-1343-v1" and d["spec_source"] == "metadata", d)

ap = argparse.ArgumentParser()
controller_args.add_args(ap)
a = ap.parse_args(["--local-controller", "learned", "--model", str(RANDOM), "--model-rate", "10"])
check("--model-rate 10 goes into the controller's setting", controller_args.setting(a, ap) == {"name": "learned", "model": str(RANDOM), "model_rate": 10}, controller_args.setting(a, ap))
check("... and a setting with no rate has no model_rate key", "model_rate" not in controller_args.setting(ap.parse_args(["--local-controller", "learned", "--model", str(RANDOM)]), ap))
check("a setting's model_rate reaches Learned through plugins.local_controller", plugins.local_controller(SIM, {"name": "learned", "model": str(bare), "model_rate": 10}).spec["policy_step_s"] == 0.1)
try:
    ap.parse_args(["--model-rate", "25"])
    odd = False
except SystemExit:
    odd = True
check("--model-rate takes 50 or 10 only", odd)

# ---- a non-finite input gives the brake ----------------------------------------------------------------------------------------------
INF, NAN = float("inf"), float("nan")
push = Learned(SIM, PUSH, model_rate=50)
fresh = [(frame(), 0.0)]
cases = {
    "a NaN gyro": (Twist(0.3, 0.0), fresh, body_state(gyro=(NAN, 0, 0)), Twist(0.2, 0.0)),
    "an infinite joint velocity": (Twist(0.3, 0.0), fresh, body_state(vel=INF), Twist(0.2, 0.0)),
    "an infinite range (NVIDIA's guard misses it)": (Twist(0.3, 0.0), [({**frame(), "distance_mm": [INF] * 64}, 0.0)], body_state(), Twist(0.2, 0.0)),
    "a NaN frame age": (Twist(0.3, 0.0), [(frame(), NAN)], body_state(), Twist(0.2, 0.0)),
}
for name, args in cases.items():
    out = push.command(*args)
    check(f"{name}: the brake (the model pushes forward; the output backs off the applied 0.2 by one slew step, to 0.1)",
          abs(out.vx - 0.1) < 1e-9 and math.isfinite(out.vyaw), out)
out = push.command(Twist(0.3, 0.0), fresh, body_state(gyro=(NAN, 0, 0)), Twist(0.05, 0.0))
check("... and a brake from a crawl reaches zero, never reverses", out.vx == 0.0, out)
check("a NaN request or applied command: a plain stop", push.command(Twist(NAN, 0.0), fresh, body_state(), Twist()) == Twist(0.0, 0.0)
      and push.command(Twist(0.3, 0.0), fresh, body_state(), Twist(NAN, 0.0)) == Twist(0.0, 0.0))
nan_model = write_onnx(tmp / "nan.onnx", [0.0] * (1343 * 3), [NAN, 0.0, 0.0])
out = Learned(SIM, nan_model, model_rate=50).command(Twist(0.3, 0.0), fresh, body_state(), Twist(0.2, 0.0))
check("a model whose output is not finite: the brake too", abs(out.vx - 0.1) < 1e-9, out)

# ---- the navigator uses it: the order, the history, the identity -----------------------------------------------------------------------
lnav = navigator(Learned(SIM, RANDOM, model_rate=50))
check("a navigator told to use it reports learned@<sha8>", lnav.controller.ident == f"learned@{sha[:8]}")
lnav.range._nearest_mm = 600
lnav.go_to((4.0, 2.5), 1.0)
tick = [r for r in rows(lnav) if r.get("applied") and r["requested"]["vx"] > 0]
check("a learned run's ticks carry requested, local and applied", tick and all({"requested", "local", "applied"} <= set(r) for r in tick), tick[:1])

# ---- selection and the refusal on a real robot ----------------------------------------------------------------------------------------
STUB = {"robot": "/nonexistent/robot.sock", "depth": "/nonexistent/tof.sock", "map": "/nonexistent/map.sock"}
real = {k: getattr(nav_run, k) for k in ("Rpc", "StateStream")}
real_open = Tof8x8.open
Tof8x8.open = lambda self, path: None
for k in real:
    setattr(nav_run, k, lambda *a, **kw: type("Stub", (), {"close": lambda self: None, "latest": None})())
SETTING = {"name": "learned", "model": str(RANDOM), "model_rate": 50}
try:
    nav = Navigator(STUB, log=tmp / "ticks.jsonl", calibration="sim", local_controller=SETTING)
    check("Navigator(local_controller=...) in the simulator builds the learned controller", nav.controller.ident == f"learned@{sha[:8]}", nav.controller.ident)
    nav._log.flush()
    cal = [json.loads(x) for x in (tmp / "ticks.jsonl").read_text().splitlines() if '"calibration"' in x]
    check("... and the run's calibration event names it and the model's checksum and input",
          cal and cal[0]["local_controller"]["model"]["sha256"] == sha and cal[0]["local_controller"]["ident"] == f"learned@{sha[:8]}", cal)
    check("... and the calibration event carries the model's rate and lateral limit (here from the flag: 50 Hz, 0.12)",
          cal and cal[0]["local_controller"]["model"]["policy_step_s"] == 0.02 and cal[0]["local_controller"]["model"]["lateral_limit"] == 0.12
          and cal[0]["local_controller"]["model"]["spec_source"] == "flag", cal and cal[0].get("local_controller"))
    plain_nav = Navigator(STUB, log=tmp / "plain.jsonl", calibration="sim")
    plain_nav._log.flush()
    cal = [json.loads(x) for x in (tmp / "plain.jsonl").read_text().splitlines() if '"calibration"' in x]
    check("with no override the calibration event has no controller entry and the controller is rules@1",
          plain_nav.controller.ident == "rules@1" and cal and "local_controller" not in cal[0], cal and sorted(cal[0]))
    try:
        Navigator(STUB, calibration=None, local_controller=SETTING)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: a real robot refuses it in the navigator (and closes what it opened)", refused)
    try:
        Learned(REAL, RANDOM, model_rate=50)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: the plugin itself refuses a real profile", refused)
    try:
        payload.Payload(STUB, tmp / "real", tmp / "data", "apartment", "real", None, local_controller=SETTING)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: the payload for the real duck refuses it", refused and not (tmp / "real").exists())
    cli = subprocess.run([sys.executable, "-m", "duck_lab.payload", "--robot", "r", "--depth", "d", "--map", "m", "--listen", str(tmp / "p.sock"),
                          "--out", str(tmp / "cli"), "--data", str(tmp / "cli-data"), "--scene", "apartment", "--name", "n", "--variant", "real",
                          "--local-controller", "learned", "--model", str(RANDOM)], capture_output=True, text=True, timeout=120)
    check("must fail: duck-payload --variant real --local-controller learned is refused at the command line, naming the simulator",
          cli.returncode == 2 and "simulator" in cli.stderr and not (tmp / "cli").exists(), (cli.returncode, cli.stderr[-200:]))
    cli = subprocess.run([sys.executable, "-m", "duck_lab.payload", "--robot", "r", "--depth", "d", "--map", "m", "--listen", str(tmp / "p.sock"),
                          "--out", str(tmp / "cli2"), "--data", str(tmp / "cli-data"), "--scene", "apartment", "--name", "n", "--variant", "sim",
                          "--local-controller", "learned"], capture_output=True, text=True, timeout=120)
    check("must fail: --local-controller learned with no --model is refused", cli.returncode == 2 and "--model" in cli.stderr, cli.stderr[-200:])
    try:
        server.NavServer(STUB, tmp / "data2", tmp / "out2", variant=None, local_controller=SETTING)
        refused = False
    except ValueError as e:
        refused = "simulator" in str(e)
    check("must fail: the navigator API's server for the real duck refuses it", refused)
    srv = server.NavServer(STUB, tmp / "data3", tmp / "out3", local_controller=SETTING)
    check("... and in the simulator keeps it for every goal's navigator", srv.local_controller == SETTING, srv.local_controller)
finally:
    for k, v in real.items():
        setattr(nav_run, k, v)
    Tof8x8.open = real_open

# ---- the build identity ---------------------------------------------------------------------------------------------------------------
check("the build's ctrl part: rules@1 with no override, learned@<sha8> with one",
      build.controller(None) == "rules@1" and build.controller(SETTING) == f"learned@{sha[:8]}" and build.controller({"name": "rules"}) == "rules@1",
      (build.controller(None), build.controller(SETTING)))
b = build.identity("0123456789ab", build.controller(SETTING), "ce894d30", "0daab160", "off", 0)
check("... and the string carries it", f"+ctrl@learned@{sha[:8]}+walker@" in b["id"] and b["ctrl"] == f"learned@{sha[:8]}", b["id"])
check("a model file that cannot be read is unknown, not a guess", build.controller({"name": "learned", "model": str(tmp / "no.onnx")}) == "learned@unknown")

print()
print("LOCAL CONTROLLER", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
