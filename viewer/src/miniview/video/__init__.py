"""A run as a video, with any rendering engine (ADR-0017): the run becomes a *track* (at each frame's time, the robot's
whole pose and its joint angles, interpolated between samples), handed with the run's scene and the robot's model to
an engine that draws it. Robot-generic: the robot's model comes from robots.json, the joints from the run's `joint_*`
signals (ADR-0016), the pose from the truth (its whole pose when the run has it). Engines live in `engines/` and run in
a Python that has their library (MuJoCo's, Blender's), not this one.

    miniview video duck/ch1-s1/run-20261116-121335 --engine mujoco -o ch1.mp4
"""

import bisect
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from miniview import keys
from miniview.mcapio import Follower
from miniview.se2 import compose

HERE = Path(__file__).resolve().parent
ROBOTS = json.loads((HERE / "robots.json").read_text())
ENGINES = {"mujoco": HERE / "engines" / "mujoco_engine.py", "blender": HERE / "engines" / "blender_engine.py"}
REPO = HERE.parents[3]


def engine_script(engine: str) -> Path | None:
    """The engine's script; VIDEO_<ENGINE>_SCRIPT replaces it (the render service's tests point it at a stub)."""
    env = os.environ.get(f"VIDEO_{engine.upper()}_SCRIPT")
    return Path(env) if env else ENGINES.get(engine)


def python_of(model: dict) -> str:
    return os.environ.get(model["python_env"], model["python"]) if model.get("python_env") else model["python"]


def program(engine: str, model: dict) -> str:
    """The program the engine runs in: Blender's own binary (VIDEO_BLENDER, else the registry's), else the model's Python."""
    if engine == "blender":
        return os.path.expanduser(os.environ.get(model.get("blender_env", ""), model.get("blender", "blender")))
    return python_of(model)


def command(engine: str, model: dict, job: Path) -> list:
    """How the engine runs: Blender runs its script itself (its own Python, with bpy); the others with the model's Python."""
    if engine == "blender":
        # --python-exit-code: a script that fails exits non-zero (Blender's own default is 0, a failure reported as success)
        return [program(engine, model), "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(engine_script(engine)),
                "--", str(job)]
    return [program(engine, model), str(engine_script(engine)), str(job)]


def _quat_yaw(yaw: float) -> list:
    return [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]


def _nlerp(a: list, b: list, f: float) -> list:
    if sum(x * y for x, y in zip(a, b)) < 0:
        b = [-x for x in b]
    q = [x + (y - x) * f for x, y in zip(a, b)]
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return [x / n for x in q]


def _at(ts: list, t: float) -> tuple:
    """(i, f): t lies between sample i and i + 1, f of the way (clamped to the ends)."""
    if t <= ts[0]:
        return 0, 0.0
    if t >= ts[-1]:
        return len(ts) - 1, 0.0
    i = bisect.bisect_right(ts, t) - 1
    return i, (t - ts[i]) / (ts[i + 1] - ts[i]) if ts[i + 1] > ts[i] else 0.0


def _tilt_with_yaw(imu: list, yaw: float) -> list:
    """The IMU's roll and pitch, with the given heading instead of its own (an IMU's heading drifts; the map's does not)."""
    w, x, y, z = imu
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    cr, sr, cp, sp, cy, sy = (math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2),
                              math.cos(yaw / 2), math.sin(yaw / 2))
    return [cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy]


def _hud_at(t: float, cmd_t: list, cmds: list, dec_t: list, decisions: list, dep_t: list, depths: list) -> dict:
    """What the Eye's HUD shows at t (web/shell/shell.js paintHud): the command, the last decision (its rule, reason and
    values, how long ago), the newest depth frame's classes and its raw zones. *_t: the lists' times, ascending."""
    out = {"t": round(t, 2)}
    k = bisect.bisect_right(cmd_t, t) - 1
    if k >= 0:
        out["cmd"] = cmds[k][1]
    k = bisect.bisect_right(dec_t, t) - 1
    if k >= 0:
        dt, d = decisions[k]
        out["doing"] = {"rule": d.get("rule"), "reason": d.get("reason"), "ago": round(t - dt, 1),
                        "values": d.get("values") or {}}
    k = bisect.bisect_right(dep_t, t) - 1
    if k >= 0:
        out["depth"] = depths[k][1]
    return out


LOOK_FRESH_S = 1.0      # a camera look is "current" for this long (the navigator looks every 0.5 s)


class _Semantic:
    """The semantic map's records (RFC-0016) placed for the video. Objects and looks are in the robot's MAP frame; the video renders
    the WORLD when the run has truth, so each is moved by the run's epoch (map_to_world) in force at its own time (`place`); a run with
    no truth is drawn in the map frame as it is. A detection is relative to the robot: it is placed from the robot's pose in the frame
    being drawn (the truth's, as the simulated camera saw it), not from the belief."""

    def __init__(self, source: str, epochs: list, objs: list, looks: list, rooms: list):
        self.world = source == "truth"
        self.ep_t = [e[0] for e in epochs]
        self.epochs = [e[1] for e in epochs]
        self.rooms, self.looks = rooms, looks
        self.snapshots = [{"t": t, "items": [self._item(t, o) for o in rec["objects"]]} for t, rec in objs]
        self.obj_t = [s["t"] for s in self.snapshots]
        self.room_t = [r[0] for r in rooms]
        self.look_t = [x[0] for x in looks]
        self.has = bool(objs or looks or rooms)

    def place(self, t: float, pose) -> list:
        if not (self.world and self.epochs):
            return [float(v) for v in pose]
        return list(compose(self.epochs[max(bisect.bisect_right(self.ep_t, t) - 1, 0)], tuple(pose)))

    def _item(self, t: float, o: dict) -> dict:
        parts = []
        for x, y, hx, hy, yaw, z0, z1 in o.get("parts", []):
            wx, wy, wyaw = self.place(t, (x, y, yaw))
            parts.append([round(wx, 4), round(wy, 4), hx, hy, round(wyaw, 4), z0, z1])
        return {"id": o["id"], "kind": o["kind"], "confirmed": bool(o.get("confirmed")), "landmark": o.get("landmark") or 0.0, "parts": parts}

    def at(self, t: float, pos, quat) -> tuple:
        """(snapshot index or None, the current look placed or None, the HUD's three entries) for a frame at t, the robot at pos with heading from quat."""
        k = bisect.bisect_right(self.obj_t, t) - 1
        hud = {}
        if self.snapshots:
            items = self.snapshots[k]["items"] if k >= 0 else []
            hud["objects"] = {"confirmed": sum(i["confirmed"] for i in items), "total": len(items)}
        if self.rooms:
            r = bisect.bisect_right(self.room_t, t) - 1
            hud["room"] = {"name": self.rooms[r][1].get("room"), "votes": self.rooms[r][1].get("votes") or {}} if r >= 0 else None
        look = None
        if self.looks:
            j = bisect.bisect_right(self.look_t, t) - 1
            hud["sees"] = None if j < 0 else []
            if j >= 0 and t - self.look_t[j] <= LOOK_FRESH_S:
                lt, lk = self.looks[j]
                w_, x_, y_, z_ = quat
                yaw = math.atan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_))
                c, s = math.cos(yaw), math.sin(yaw)
                seen = []
                for d in lk["seen"]:
                    rx, ry = d["x"], d["y"]
                    seen.append({"kind": d["kind"], "confidence": d.get("confidence"), "range_m": d.get("range_m", math.hypot(rx, ry)),
                                 "radius": d.get("radius"), "z0": d.get("z0"), "z1": d.get("z1"), "rel": [rx, ry],
                                 "world": [round(pos[0] + c * rx - s * ry, 4), round(pos[1] + s * rx + c * ry, 4)]})
                look = {"pose": [round(v, 4) for v in self.place(lt, lk["pose"])], "hfov_deg": lk["hfov_deg"], "range_m": lk["range_m"], "seen": seen}
                hud["sees"] = [{k: d[k] for k in ("kind", "range_m", "confidence")} for d in seen]
        return (k if k >= 0 else None), look, hud


def track(run_dir: Path, fps: float = 30.0, t_from: float | None = None, t_to: float | None = None, stand_z: float = 0.1,
          hud: bool = False, semantic: bool = False) -> dict:
    """The run as frames: {"run", "fps", "source", "frame", "map", "frames": [{t, pos: [x, y, z], quat: [w, x, y, z],
    joints: {name: rad}}]}.

    Where the robot was: the truth when the run has it (the simulator; with its whole pose, ADR-0016, else standing at
    `stand_z` with its heading), in the world frame. A run from the field has no truth: then the robot's belief on its own
    map, its tilt from the IMU's signals (qw..qz) and its heading from the belief, standing at `stand_z`, in the map frame;
    `map` is then the robot's last map grid, the only picture of the room there is. Joints come from the `joint_*` signals
    (ADR-0016) on both; a joint never sampled is left out (the engine holds the model's own pose for it).

    semantic=True adds what the semantic map's overlays need (RFC-0016, ADR-0018): `semantic` {"objects": the snapshots with their
    parts in the track's frame}, and per frame `obj_i` (the snapshot in force), `look` (the current camera look, its detections placed
    from the robot's pose in the frame) and, with hud=True, the HUD's sees / room / objects entries. A run without objects, looks or
    rooms gets none of it."""
    truth, belief, sig_t, sig_v, imu_t, imu_v, run, grid = [], [], [], [], [], [], None, None
    cmds, decisions, depths = [], [], []          # for the HUD (hud=True)
    epochs, objs, looks, rooms = [], [], [], []   # for the semantic overlays (semantic=True)
    for t, kind, p in Follower(Path(run_dir), keep_raw=hud).poll():
        if semantic:
            if kind == "epoch":
                epochs.append((t, tuple(p["map_to_world"])))
            elif kind == "objects":
                objs.append((t, p))
            elif kind == "look":
                looks.append((t, p))
            elif kind == "event" and p.get("kind") == "room":
                rooms.append((t, p))
        if hud and kind == "tick" and p.get("cmd") is not None:
            cmds.append((t, p["cmd"]))
        if hud and kind == "event" and isinstance(p.get("decision"), dict) and p.get("kind") != "room":     # the room is its own line
            decisions.append((t, p["decision"]))
        if hud and kind == "depth_frame" and p.get("distance_mm"):
            classes = [q[3] for q in ((p.get("derived") or {}).get("points") or [])]
            depths.append((t, {"rows": p.get("rows", 8), "cols": p.get("cols", 8), "mm": p["distance_mm"],
                               "status": p.get("status", []), "counts": {c: classes.count(c) for c in "fovb"}}))
        if kind == "run":
            run = p
        elif kind == "tick":
            if p.get("truth"):
                x, y, yaw = p["truth"]
                full = p.get("truth_3d")
                truth.append((t, [x, y, full["z"] if full else stand_z], full["quat"] if full else _quat_yaw(yaw)))
            belief.append((t, p["belief"]))
        elif kind == "world" and p.get("grid"):
            grid = p["grid"]
        elif kind == "signals":
            v = p["values"]
            js = {k.removeprefix("joint_"): x for k, x in v.items() if k.startswith("joint_") and x is not None}
            if js:
                sig_t.append(t)
                sig_v.append(js)
            if all(v.get(k) is not None for k in ("qw", "qx", "qy", "qz")):
                imu_t.append(t)
                imu_v.append([v["qw"], v["qx"], v["qy"], v["qz"]])
    if truth:
        poses, source, frame = truth, "truth", "world"
    else:
        poses, source, frame = [], "belief", "map"
        for t, (x, y, yaw) in belief:
            q = _quat_yaw(yaw)
            if imu_t:
                q = _tilt_with_yaw(imu_v[_at(imu_t, t)[0]], yaw)
            poses.append((t, [x, y, stand_z], q))
    out = {"run": run, "fps": fps, "source": source, "frame": frame, "map": grid if source == "belief" else None, "frames": []}
    if not poses:
        return out
    sem = _Semantic(source, epochs, objs, looks, rooms) if semantic else None
    if sem and sem.has:
        out["semantic"] = {"objects": sem.snapshots}
    pt = [p[0] for p in poses]
    cmd_t, dec_t, dep_t = [c[0] for c in cmds], [d[0] for d in decisions], [d[0] for d in depths]
    t0 = max(pt[0], t_from if t_from is not None else pt[0])
    t1 = min(pt[-1], t_to if t_to is not None else pt[-1])
    frames = []
    for k in range(int((t1 - t0) * fps) + 1):
        t = t0 + k / fps
        i, f = _at(pt, t)
        a, b = poses[i], poses[min(i + 1, len(poses) - 1)]
        frame = {"t": round(t, 4), "pos": [x + (y - x) * f for x, y in zip(a[1], b[1])], "quat": _nlerp(a[2], b[2], f), "joints": {}}
        if sig_t:
            j, g = _at(sig_t, t)
            ja, jb = sig_v[j], sig_v[min(j + 1, len(sig_v) - 1)]
            frame["joints"] = {n: v + (jb.get(n, v) - v) * g for n, v in ja.items()}
        if hud:
            frame["hud"] = _hud_at(t, cmd_t, cmds, dec_t, decisions, dep_t, depths)
        if sem and sem.has:
            obj_i, look, extra = sem.at(t, frame["pos"], frame["quat"])
            frame["obj_i"], frame["look"] = obj_i, look
            if hud:
                frame["hud"].update(extra)
        frames.append(frame)
    out["frames"] = frames
    return out


def export(data: Path, key: str, engine: str, out: Path, fps: float = 30.0, size: tuple = (1280, 720),
           t_from: float | None = None, t_to: float | None = None, insets: tuple = (), inset_frac: float = 0.28) -> Path:
    """The run `key` of the data folder rendered by `engine` to `out` (a video file). Raises for a robot with no model for that
    engine, a run with no truth, or an engine that fails (its own message). insets: small squares in the bottom corners,
    "eye" (the robot's own camera, robots.json eye_camera), "top" (the room from above, the robot and its trail), each
    inset_frac of the video's height, and "hud" (the Eye's HUD: what it does, why, its pace, its depth frame) top-left
    (the MuJoCo engine; others ignore them)."""
    robot, scene_id, _ = keys.split_key(key)
    model = ROBOTS.get(robot, {}).get(engine)
    if not model:
        raise SystemExit(f"no {engine} model for the robot {robot!r} in {HERE / 'robots.json'}")
    tr = track(keys.run_dir(Path(data), key), fps, t_from, t_to, model.get("stand_z", 0.1), hud="hud" in insets,
               semantic=bool({"eye", "top", "hud"} & set(insets)))
    if not tr["frames"]:
        raise SystemExit(f"{key} has no poses to draw (no truth and no belief in the time asked)")
    scene_p = Path(data) / "scenes" / (tr["run"] or {}).get("scene", scene_id) / "scene.json"
    scene = json.loads(scene_p.read_text()) if scene_p.exists() else {"boxes": [], "hazards": [], "bounds": [-2, 2, -2, 2]}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="video-") as tmp:
        job = Path(tmp) / "job.json"
        rb = dict(model, name=robot)
        if rb.get("urdf"):
            rb["urdf"] = str((REPO / rb["urdf"]).resolve())        # the description, from the repository's robots/
        job.write_text(json.dumps({"track": tr, "scene": scene, "robot": rb, "size": list(size), "insets": list(insets),
                                   "inset_frac": inset_frac,
                                   "out": str(Path(out).resolve()), "title": key}))
        r = subprocess.run(command(engine, model, job))
        if r.returncode != 0:
            raise SystemExit(f"the {engine} engine failed (exit {r.returncode})")
        if not Path(out).is_file() or Path(out).stat().st_size == 0:
            raise SystemExit(f"the {engine} engine exited 0 but wrote no video at {out}")
    return Path(out)
