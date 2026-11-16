"""The MuJoCo engine of the video export (ADR-0017): a job (a track, a scene, a robot model, a size, an output file) to a
video. Runs in a Python that has MuJoCo (the robot's `python` in robots.json), not miniview's:

    <mujoco python> mujoco_engine.py job.json

The render scene is the robot's model in a room: the scene's boxes and drops (a run in the world frame, as the simulator
has it), or the robot's own map, its occupied cells as low blocks (a run in the map frame: from the field, where the
room is only what the robot saw). Each frame poses the model from the track (the free joint's position and orientation,
each named joint's angle; joints the track lacks hold the model's home pose) and renders off-screen, the camera
following the trunk.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import mediapy  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402

BOX_RGBA = "0.78 0.78 0.80 0.45"         # see-through: a wall between the camera and the robot must not hide it
DROP_RGBA = "0.30 0.10 0.32 1"
MAP_RGBA = "0.55 0.45 0.35 1"
FLOOR = '<geom name="floor" size="0 0 0.05" pos="0 0 0" type="plane" material="groundplane" />'


def _box(name: str, cx: float, cy: float, hx: float, hy: float, z0: float, z1: float, yaw: float, rgba: str) -> str:
    hz = max((z1 - z0) / 2, 0.0005)
    return (f'<geom name="{name}" type="box" size="{hx:.4f} {hy:.4f} {hz:.4f}" pos="{cx:.4f} {cy:.4f} {z0 + hz:.4f}" '
            f'quat="{math.cos(yaw / 2):.6f} 0 0 {math.sin(yaw / 2):.6f}" rgba="{rgba}" contype="0" conaffinity="0"/>')


def room(job: dict) -> list:
    """The room's geoms: the scene's boxes and its drops (drawn dark on the floor) in the world frame, or the robot's map's
    occupied cells (map frame)."""
    tr = job["track"]
    if tr.get("frame") == "map":
        g, out = tr.get("map"), []
        if g:
            res, (ox, oy), w, cells = g["res"], g["origin"], g["w"], g["cells"]
            for k, c in enumerate(cells):
                if c == "#":
                    r, col = divmod(k, w)
                    out.append(_box(f"map{k}", ox + (col + 0.5) * res, oy + (r + 0.5) * res, res / 2, res / 2, 0.0, 0.12, 0.0, MAP_RGBA))
        return out
    sc = job["scene"]
    out = [_box(f"b{i}", b["cx"], b["cy"], b["hx"], b["hy"], b["z0"], b["z1"], b.get("yaw", 0.0), BOX_RGBA) for i, b in enumerate(sc.get("boxes", []))]
    for i, h in enumerate(sc.get("hazards", [])):
        out.append(_box(f"h{i}", (h["x0"] + h["x1"]) / 2, (h["y0"] + h["y1"]) / 2, (h["x1"] - h["x0"]) / 2, (h["y1"] - h["y0"]) / 2,
                        0.0005, 0.0015, h.get("yaw", 0.0), DROP_RGBA))
    return out


def build(job: dict, work: Path) -> mujoco.MjModel:
    """The render scene: the robot's keyframes file with the robot included by absolute path, `assets` linked, the floor plane
    kept and the room added, the off-screen buffer as large as the video."""
    rb = job["robot"]
    root = Path(os.environ.get(rb.get("model_root_env", ""), rb["model_root"]))
    if not (work / "assets").exists():
        os.symlink(root / "assets", work / "assets")
    text = (root / rb["keyframes_from"]).read_text()
    text = re.sub(r'<include file="[^"]+" />', f'<include file="{root / rb["model"]}" />', text, count=1)
    if FLOOR not in text:
        raise SystemExit(f"{rb['keyframes_from']} has no floor plane where the engine expects one")
    w, h = job["size"]
    text = text.replace(FLOOR, FLOOR + "\n        " + "\n        ".join(room(job)))
    text = re.sub(r"<global ", f'<global offwidth="{w}" offheight="{h}" ', text, count=1)
    (work / "render.xml").write_text(text)
    return mujoco.MjModel.from_xml_path(str(work / "render.xml"))


def render(job: dict) -> None:
    import tempfile
    tr, rb = job["track"], job["robot"]
    with tempfile.TemporaryDirectory(prefix="render-") as tmp:
        m = build(job, Path(tmp))
    d = mujoco.MjData(m)
    key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, rb.get("home_keyframe", ""))
    home = m.key_qpos[key].copy() if key >= 0 else m.qpos0.copy()
    free = m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, rb["free_joint"])]
    joint_adr = {}
    for n in {n for f in tr["frames"] for n in f["joints"]}:
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, n)
        if j >= 0:
            joint_adr[n] = m.jnt_qposadr[j]
    w, h = job["size"]
    renderer = mujoco.Renderer(m, height=h, width=w)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.distance, cam.elevation = 1.3, -40.0
    look, heading = None, None
    frames = []
    for f in tr["frames"]:
        d.qpos[:] = home
        d.qpos[free:free + 3] = f["pos"]
        d.qpos[free + 3:free + 7] = f["quat"]
        for n, a in f["joints"].items():
            if n in joint_adr:
                d.qpos[joint_adr[n]] = a
        mujoco.mj_forward(m, d)
        target = np.array([f["pos"][0], f["pos"][1], 0.08])
        look = target if look is None else look + 0.15 * (target - look)        # the camera follows, smoothly
        w_, x_, y_, z_ = f["quat"]
        yaw = math.degrees(math.atan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_)))
        heading = yaw if heading is None else heading + 0.05 * (((yaw - heading + 180) % 360) - 180)   # behind it, turning slowly
        cam.lookat[:] = look
        cam.azimuth = heading + 150.0
        renderer.update_scene(d, cam)
        frames.append(renderer.render())
    renderer.close()
    mediapy.write_video(job["out"], frames, fps=tr["fps"])
    print(f"video {job['out']}: {len(frames)} frames at {tr['fps']:g} fps, {w}x{h}, joints {len(joint_adr)} of the model's, "
          f"pose from the {tr.get('source', 'truth')}", flush=True)


if __name__ == "__main__":
    render(json.loads(Path(sys.argv[1]).read_text()))
