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
EYE_AHEAD_M = 0.04        # the eye inset's camera, ahead of the head camera (out of the head's shell)
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


def _square_top(job: dict) -> tuple:
    """The top view's look-at point and distance: straight down over the scene's bounds (the whole room), or the track's
    own extent when the scene has none."""
    b = (job.get("scene") or {}).get("bounds")
    if not b:
        xs = [f["pos"][0] for f in job["track"]["frames"]]
        ys = [f["pos"][1] for f in job["track"]["frames"]]
        b = [min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1]
    cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
    half = max(b[1] - b[0], b[3] - b[2]) / 2
    return np.array([cx, cy, 0.0]), half / math.tan(math.radians(45.0 / 2)) * 1.1


def _mark(renderer, pos, radius: float, rgba) -> None:
    """A sphere drawn into the renderer's scene after update_scene (the top view's duck and its trail)."""
    scn = renderer.scene
    if scn.ngeom < scn.maxgeom:
        mujoco.mjv_initGeom(scn.geoms[scn.ngeom], mujoco.mjtGeom.mjGEOM_SPHERE, np.array([radius, 0, 0]),
                            np.array(pos, dtype=float), np.eye(3).flatten(), np.array(rgba, dtype=np.float32))
        scn.ngeom += 1


def _paste(frame, inset, corner: str, border: int = 2) -> None:
    """inset into frame's corner ("bl" bottom-left, "br" bottom-right), framed with a light border, in place."""
    h, w = frame.shape[:2]
    s = inset.shape[0]
    y0 = h - s - 8
    x0 = 8 if corner == "bl" else w - s - 8
    frame[y0 - border:y0 + s + border, x0 - border:x0 + s + border] = 235
    frame[y0:y0 + s, x0:x0 + s] = inset


HUD_FONTS = ("/usr/share/fonts/liberation/LiberationMono-Regular.ttf", "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
RAW_VALID = (5, 9)                 # the depth sensor's valid zone statuses, as the Eye's canvas reads them


def _font(size: int):
    from PIL import ImageFont
    for p in HUD_FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(text: str, n: int, lines: int) -> list:
    words, out, cur = str(text).split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n and cur:
            out.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    out.append(cur)
    return out[:lines] if len(out) <= lines else out[:lines - 1] + [out[lines - 1][: n - 1] + "…"]


def _val(v) -> str:
    return f"{v:.3g}" if isinstance(v, float) else str(v)


def _hud(frame, hud: dict, robot: str, scene: str, font, fsize: int) -> None:
    """The Eye's HUD (web/shell/shell.js paintHud) as a dark panel top-left, in place: the robot, the time, its pace, what
    it is doing and why with the values the rule compared, the newest depth frame's classes, and its 8 x 8 zones."""
    import colorsys
    from PIL import Image, ImageDraw
    h, w = frame.shape[:2]
    pw, cols = int(w * 0.46), max(24, int(w * 0.46 / (fsize * 0.6)) - 12)
    lines = [(f"{robot.upper()} · EYE", (255, 214, 102))]
    lines.append((f"{scene} · t {hud['t']:.1f} s · REPLAY", (210, 215, 222)))
    c = hud.get("cmd")
    lines.append((f"PACE  {c[0]:.2f} m/s · turn {c[1]:+.2f} rad/s" if c else "PACE  —", (230, 235, 240)))
    d = hud.get("doing")
    if d:
        for i, ln in enumerate(_wrap(f"{d.get('rule')} · {d.get('reason')} · {d['ago']:.1f} s ago", cols, 3)):
            lines.append((("DOING " if i == 0 else "      ") + ln, (255, 255, 255)))
        vals = " · ".join(f"{k} {_val(v)}" for k, v in (d.get("values") or {}).items())
        for i, ln in enumerate(_wrap(vals, cols, 2) if vals else []):
            lines.append((("NUMBERS " if i == 0 else "        ") + ln, (170, 180, 192)))
    else:
        lines.append(("DOING nothing decided yet", (200, 200, 200)))
    dp = hud.get("depth")
    if dp:
        n = dp["counts"]
        lines.append((f"FRAME floor {n.get('f', 0)} · obstacle {n.get('o', 0)} · overhead {n.get('v', 0)} · below "
                      f"{n.get('b', 0)}", (210, 215, 222)))
    lh = int(fsize * 1.35)
    ph = 10 + lh * len(lines) + 8
    cell = max(5, int(ph / 12))
    grid_w = (dp["cols"] * cell + 10) if dp else 0
    panel = Image.new("RGBA", (pw + grid_w, ph), (12, 14, 18, 190))
    g = ImageDraw.Draw(panel)
    for i, (txt, col) in enumerate(lines):
        g.text((10, 6 + i * lh), txt, font=font, fill=col + (255,))
    if dp:
        x0, y0 = pw, (ph - dp["rows"] * cell) // 2
        for k, mm in enumerate(dp["mm"]):
            ok = dp["status"][k] in RAW_VALID if k < len(dp["status"]) else True
            if ok:
                r, gg, b = colorsys.hls_to_rgb(240 / 360 * min(max(mm, 0) / 4000, 1), 0.45, 0.65)
                col = (int(r * 255), int(gg * 255), int(b * 255), 255)
            else:
                col = (44, 46, 52, 255)
            cx, cy = x0 + (k % dp["cols"]) * cell, y0 + (k // dp["cols"]) * cell
            g.rectangle([cx, cy, cx + cell - 2, cy + cell - 2], fill=col)
    base = Image.fromarray(frame).convert("RGBA")
    base.alpha_composite(panel, (8, 8))
    frame[:] = np.asarray(base.convert("RGB"))


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
    # Insets (the operator, 2026-11-17): the duck's own view (the model's head camera) and the room from above, as small
    # squares in the bottom corners.
    insets = [i for i in job.get("insets", []) if i in ("eye", "top", "hud")]
    side = max(64, int(h * float(job.get("inset_frac", 0.28))))
    small = mujoco.Renderer(m, height=side, width=side) if {"eye", "top"} & set(insets) else None
    fsize = max(10, h // 40)
    font = _font(fsize) if "hud" in insets else None
    scene_name = (job.get("title") or "").split("/")[1] if "/" in (job.get("title") or "") else ""
    eye_cam = None
    if "eye" in insets:
        cid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_CAMERA, rb.get("eye_camera", ""))
        if cid >= 0:
            eye_cam = mujoco.MjvCamera()
            eye_cam.type, eye_cam.fixedcamid = mujoco.mjtCamera.mjCAMERA_FIXED, cid
        else:
            print(f"no eye camera {rb.get('eye_camera')!r} in the model: the eye inset is left out", flush=True)
    top_cam = None
    if "top" in insets:
        top_cam = mujoco.MjvCamera()
        top_cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        top_cam.lookat[:], top_cam.distance = _square_top(job)
        top_cam.elevation, top_cam.azimuth = -89.9, 90.0          # straight down, +y up in the image
    trail = []
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
        frame = renderer.render().copy()
        if eye_cam is not None:
            # From the head camera's pose, EYE_AHEAD_M in front of it: the camera itself sits inside the head's shell and
            # rendered the shell (the first test showed grey where the stairwell was).
            cid = eye_cam.fixedcamid
            fwd = -d.cam_xmat[cid].reshape(3, 3)[:, 2]                  # a MuJoCo camera looks along its -z
            free_eye = mujoco.MjvCamera()
            free_eye.type = mujoco.mjtCamera.mjCAMERA_FREE
            free_eye.distance = 1.0
            free_eye.lookat[:] = d.cam_xpos[cid] + fwd * (EYE_AHEAD_M + free_eye.distance)
            free_eye.azimuth = math.degrees(math.atan2(fwd[1], fwd[0]))
            free_eye.elevation = math.degrees(math.asin(max(-1.0, min(1.0, fwd[2]))))
            small.update_scene(d, free_eye)
            _paste(frame, small.render(), "bl")
        if top_cam is not None:
            if not trail or math.dist(trail[-1], f["pos"][:2]) > 0.1:
                trail.append(tuple(f["pos"][:2]))
            small.update_scene(d, top_cam)
            for p in trail[-400:]:
                _mark(small, (p[0], p[1], 0.02), 0.03, (0.35, 0.55, 0.95, 1))
            _mark(small, (f["pos"][0], f["pos"][1], 0.05), 0.09, (0.95, 0.25, 0.2, 1))
            _paste(frame, small.render(), "br")
        if font is not None and f.get("hud"):
            _hud(frame, f["hud"], rb.get("name", "robot"), scene_name, font, fsize)
        frames.append(frame)
    renderer.close()
    if small is not None:
        small.close()
    mediapy.write_video(job["out"], frames, fps=tr["fps"])
    print(f"video {job['out']}: {len(frames)} frames at {tr['fps']:g} fps, {w}x{h}, joints {len(joint_adr)} of the model's, "
          f"pose from the {tr.get('source', 'truth')}", flush=True)


if __name__ == "__main__":
    render(json.loads(Path(sys.argv[1]).read_text()))
