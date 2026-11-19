"""The MuJoCo engine of the video export (ADR-0017): a job (a track, a scene, a robot model, a size, an output file) to a
video. Runs in a Python that has MuJoCo (the robot's `python` in robots.json), not Observatory's:

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

sys.path.insert(0, str(Path(__file__).resolve().parent))      # the engine runs as a script: its sibling modules are imported by name
import overlay  # noqa: E402

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


_wrap = overlay.wrap


def _overlay_image(img, draw):
    """img (an RGB array) drawn on by draw(PIL image), as an array again."""
    from PIL import Image
    im = Image.fromarray(img)
    draw(im)
    return np.asarray(im.convert("RGB"))


def _val(v) -> str:
    return f"{v:.3g}" if isinstance(v, float) else str(v)


MAP_UNKNOWN, MAP_FREE, MAP_OCC = (24, 27, 33), (70, 96, 128), (236, 238, 244)


TRUTH_LINE, TRUTH_DROP = (88, 96, 112), (120, 70, 130)


def _truth_layer(img, scene: dict, px) -> None:
    """The real room, faint, under the discovered map (the operator, 2026-11-19: a reference for what was found): every box's
    footprint as a thin grey outline, every drop as a thin purple one."""
    from PIL import ImageDraw
    g = ImageDraw.Draw(img)
    for b in scene.get("boxes", []):
        g.polygon([px(*c) for c in overlay.rect(b["cx"], b["cy"], b["hx"], b["hy"], b.get("yaw", 0.0))], outline=TRUTH_LINE)
    for hz in scene.get("hazards", []):
        cx, cy, hx, hy = (hz["x0"] + hz["x1"]) / 2, (hz["y0"] + hz["y1"]) / 2, (hz["x1"] - hz["x0"]) / 2, (hz["y1"] - hz["y0"]) / 2
        g.polygon([px(*c) for c in overlay.rect(cx, cy, hx, hy, hz.get("yaw", 0.0))], outline=TRUTH_DROP)


def _map_image(grid: dict, size: int, px, scene: dict | None = None, show_map: bool = True) -> "object":
    """The robot's discovered map as a PIL image `size` px square: unknown dark, free floor blue-grey, occupied white; each cell
    placed in the frame being drawn through grid["to_frame"] (map to world) and drawn by `px` (frame metres -> pixels); the real
    room faint on top when `scene` is given (its outlines only, so the discovered map stays readable)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), MAP_UNKNOWN)
    if not show_map:
        if scene:
            _truth_layer(img, scene, px)
        return img
    g = ImageDraw.Draw(img)
    res, (ox, oy), gw = grid["res"], grid["origin"], grid["w"]
    tx, ty, tyaw = grid.get("to_frame", [0.0, 0.0, 0.0])
    c, s_ = math.cos(tyaw), math.sin(tyaw)
    half = max(1, int(round(abs(px(res, 0)[0] - px(0, 0)[0]) / 2 + 0.5)))
    for k, ch in enumerate(grid["cells"]):
        if ch not in ".#":
            continue
        mx, my = ox + (k % gw + 0.5) * res, oy + (k // gw + 0.5) * res
        x, y = px(tx + c * mx - s_ * my, ty + s_ * mx + c * my)
        g.rectangle([x - half, y - half, x + half, y + half], fill=MAP_FREE if ch == "." else MAP_OCC)
    if scene:
        _truth_layer(img, scene, px)
    return img


def _cam_projector(cam, w: int, h: int, fovy_deg: float):
    """World point -> (x, y) pixels in the main view (a free camera: lookat, distance, azimuth, elevation), None behind it."""
    az, el = math.radians(cam.azimuth), math.radians(cam.elevation)
    fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    pos = np.array(cam.lookat) - fwd * cam.distance
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    f = (h / 2) / math.tan(math.radians(fovy_deg) / 2)

    def project(x: float, y: float, z: float):
        v = np.array([x, y, z]) - pos
        d = float(v @ fwd)
        if d < 0.1:
            return None
        return w / 2 + f * float(v @ right) / d, h / 2 - f * float(v @ up) / d
    return project


def _labels(frame, snap, project, font, near_m: float, pos) -> None:
    """The objects the robot has confirmed, labelled over themselves in the main view (landmarks in their own colour), within
    near_m of the robot; in place."""
    from PIL import Image, ImageDraw
    base = Image.fromarray(frame).convert("RGBA")
    over = ImageDraw.Draw(base, "RGBA")
    for o in (snap or {}).get("items", []):
        if not o.get("confirmed") or not o["parts"]:
            continue
        x, y = o["parts"][0][0], o["parts"][0][1]
        top = max(pt[6] for pt in o["parts"])
        if math.dist((x, y), pos[:2]) > near_m:
            continue
        q = project(x, y, top + 0.04)
        if q is None or not (0 <= q[0] < frame.shape[1] and 0 <= q[1] < frame.shape[0]):
            continue
        rgb = overlay.object_rgb(o)
        tw = over.textlength(o["kind"], font=font)
        over.rounded_rectangle([q[0] - tw / 2 - 5, q[1] - 22, q[0] + tw / 2 + 5, q[1] - 3], 4, fill=(12, 14, 18, 170), outline=rgb + (255,))
        over.text((q[0] - tw / 2, q[1] - 20), o["kind"], font=font, fill=rgb + (255,))
        over.ellipse([q[0] - 3, q[1] - 3, q[0] + 3, q[1] + 3], fill=rgb + (255,))
    frame[:] = np.asarray(base.convert("RGB"))


def _hud(frame, hud: dict, robot: str, scene: str, font, fsize: int, side: int = 0) -> None:
    """The Eye's HUD (web/shell/shell.js paintHud), in place. Top-left, a panel of FIXED size so it never jumps as lines wrap:
    the robot and time, its pace, what it is doing and why (two lines kept), what it sees (two lines kept), the room, the
    objects. Bottom-left, beside the eye inset (side px square) and as tall, the newest depth frame's 8 x 8 zones, so what the
    robot senses is grouped (the operator, 2026-11-19). The rule's numbers and the frame's class counts are left to the
    Observatory's pages."""
    import colorsys
    from PIL import Image, ImageDraw
    h, w = frame.shape[:2]
    pw = int(w * 0.36)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    cols = max(24, int((pw - 20) / max(1.0, measure.textlength("M", font=font))) - 7)   # the font's own width; "DOING " in front
    blank = ("", (0, 0, 0))
    lines = [(f"{robot.upper()} · {scene} · t {hud['t']:.0f} s", (255, 214, 102))]
    c = hud.get("cmd")
    lines.append((f"PACE  {c[0]:.2f} m/s · turn {c[1]:+.2f} rad/s" if c else "PACE  —", (230, 235, 240)))
    d = hud.get("doing")
    doing = ([(("DOING " if i == 0 else "      ") + ln, (255, 255, 255))
              for i, ln in enumerate(_wrap(f"{d.get('rule')} · {d.get('reason')}", cols, 2))] if d
             else [("DOING nothing decided yet", (200, 200, 200))])
    lines += (doing + [blank, blank])[:2]                 # two lines kept, filled or not
    sem = overlay.hud_lines(hud, cols)                    # SEES (one or two) / ROOM / OBJECTS; none for a run without a semantic map
    if sem:
        sees = [x for x in sem if not x[0].startswith(("ROOM", "OBJECTS"))]
        rest = [x for x in sem if x[0].startswith(("ROOM", "OBJECTS"))]
        lines += (sees + [blank, blank])[:2] + rest
    fit = []
    for txt, col in lines:                                # a line that would run past the panel is cut, never drawn outside it
        while txt and measure.textlength(txt, font=font) > pw - 20:
            txt = txt[:-2].rstrip() + "…"
        fit.append((txt, col))
    lh = int(fsize * 1.35)
    panel = Image.new("RGBA", (pw, 10 + lh * len(fit) + 6), (12, 14, 18, 175))
    g = ImageDraw.Draw(panel)
    for i, (txt, col) in enumerate(fit):
        if txt:
            g.text((10, 6 + i * lh), txt, font=font, fill=col + (255,))
    base = Image.fromarray(frame).convert("RGBA")
    base.alpha_composite(panel, (8, 8))
    dp = hud.get("depth")
    if dp:
        gh = side if side else dp["rows"] * max(5, h // 64) + 16 + lh
        cell = max(4, (gh - 16 - lh) // dp["rows"])
        gw = dp["cols"] * cell + 16
        grid = Image.new("RGBA", (gw, gh), (12, 14, 18, 200))
        gd = ImageDraw.Draw(grid)
        gd.text((8, 4), "DEPTH 8×8", font=font, fill=(210, 215, 222, 255))
        for k, mm in enumerate(dp["mm"]):
            ok = dp["status"][k] in RAW_VALID if k < len(dp["status"]) else True
            if ok:
                r, gg, b = colorsys.hls_to_rgb(240 / 360 * min(max(mm, 0) / 4000, 1), 0.45, 0.65)
                col = (int(r * 255), int(gg * 255), int(b * 255), 255)
            else:
                col = (44, 46, 52, 255)
            cx, cy = 8 + (k % dp["cols"]) * cell, 8 + lh + (k // dp["cols"]) * cell
            gd.rectangle([cx, cy, cx + cell - 2, cy + cell - 2], fill=col)
        x0 = 8 + side + 2 + 8 if side else 8                # beside the eye inset (its 2 px border), bottom-left
        base.alpha_composite(grid, (x0, h - gh - 8))
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
    cam.distance, cam.elevation = 2.4, -66.0            # high enough to see over the furniture what the robot finds (was 1.3, -40)
    # Insets (the operator, 2026-11-17): the duck's own view (the model's head camera) and the room from above, as small
    # squares in the bottom corners.
    insets = [i for i in job.get("insets", []) if i in ("eye", "top", "hud")]
    side = max(64, int(h * float(job.get("inset_frac", 0.28))))
    map_side = int(side * 1.45)                 # the discovered map is the bigger inset (the operator, 2026-11-19)
    hide = set(job.get("hide") or [])           # layers left out (--hide): truth, map, objects, labels, trail, wedge
    dt = 1.0 / float(tr.get("fps") or 30.0)
    follow, turn = 1 - 0.85 ** (30 * dt), 1 - 0.95 ** (30 * dt)   # the camera's smoothing per second, as at 30 fps whatever the rate
    grids = tr.get("grids") or []
    map_cache = {}
    small = mujoco.Renderer(m, height=side, width=side) if {"eye", "top"} & set(insets) else None
    fsize = max(9, h // 54)                     # smaller than the first build's h // 40 (the operator, 2026-11-19)
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
    global_fovy = float(m.vis.global_.fovy)
    eye_fovy = global_fovy
    if eye_cam is not None:
        eye_fovy = float(m.cam_fovy[eye_cam.fixedcamid])
    sem_objects = (tr.get("semantic") or {}).get("objects") or []
    main_font = _font(max(12, h // 44))
    lfont = _font(max(9, side // 26)) if {"eye", "top"} & set(insets) and ("semantic" in tr or any(f.get("sighting") for f in tr["frames"])) else None
    top_cam = None
    if "top" in insets:
        top_cam = mujoco.MjvCamera()
        top_cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        top_cam.lookat[:], top_cam.distance = _square_top(job)
        top_cam.elevation, top_cam.azimuth = -89.9, 90.0          # straight down, +y up in the image
    if job.get("intro_s"):
        # An introduction instead of the run (the operator, 2026-11-19: "a few cameras around the duck in 3D to present it"):
        # the camera circles the robot as it stands in the run's first frame, close and low, at the track's frame rate, no
        # overlays. Joined in front of the run's video afterwards.
        f0 = tr["frames"][0]
        d.qpos[:] = home
        d.qpos[free:free + 3] = f0["pos"]
        d.qpos[free + 3:free + 7] = f0["quat"]
        for n, a in f0["joints"].items():
            if n in joint_adr:
                d.qpos[joint_adr[n]] = a
        mujoco.mj_forward(m, d)
        n = max(2, int(float(job["intro_s"]) * float(tr["fps"])))
        intro = []
        for k in range(n):
            u = k / (n - 1)
            cam.lookat[:] = [f0["pos"][0], f0["pos"][1], 0.13]
            cam.distance = 0.75 - 0.15 * math.sin(math.pi * u)      # in a little at the middle of the turn
            cam.elevation = -12.0 - 10.0 * u
            cam.azimuth = 200.0 + 360.0 * u
            renderer.update_scene(d, cam)
            intro.append(renderer.render().copy())
        renderer.close()
        if small is not None:
            small.close()
        mediapy.write_video(job["out"], intro, fps=tr["fps"])
        print(f"intro {job['out']}: {len(intro)} frames at {tr['fps']:g} fps, {w}x{h}", flush=True)
        return
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
        look = target if look is None else look + follow * (target - look)        # the camera follows, smoothly
        w_, x_, y_, z_ = f["quat"]
        yaw = math.degrees(math.atan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_)))
        heading = yaw if heading is None else heading + turn * (((yaw - heading + 180) % 360) - 180)   # behind it, turning slowly
        cam.lookat[:] = look
        cam.azimuth = heading + 150.0
        renderer.update_scene(d, cam)
        frame = renderer.render().copy()
        if sem_objects and lfont is not None and f.get("obj_i") is not None and "labels" not in hide:
            _labels(frame, sem_objects[f["obj_i"]], _cam_projector(cam, w, h, global_fovy), main_font, 4.0, f["pos"])
        if eye_cam is not None:
            # From the head camera's pose, EYE_AHEAD_M in front of it: the camera itself sits inside the head's shell and
            # rendered the shell (the first test showed grey where the stairwell was).
            cid = eye_cam.fixedcamid
            # A MuJoCo camera looks along its -z. The duck's head_camera does not: at the STAND keyframe with the trunk at the identity,
            # its -z is world -x, the way behind the robot (its cam position is +0.064 m in front of the trunk's origin, and every
            # sensor of the robot looks along +x), so the model says which axis the robot looks along (robots.json eye_axis, default -z).
            fwd = (1.0 if rb.get("eye_axis") == "+z" else -1.0) * d.cam_xmat[cid].reshape(3, 3)[:, 2]
            free_eye = mujoco.MjvCamera()
            free_eye.type = mujoco.mjtCamera.mjCAMERA_FREE
            free_eye.distance = 1.0
            free_eye.lookat[:] = d.cam_xpos[cid] + fwd * (EYE_AHEAD_M + free_eye.distance)
            free_eye.azimuth = math.degrees(math.atan2(fwd[1], fwd[0]))
            free_eye.elevation = math.degrees(math.asin(max(-1.0, min(1.0, fwd[2]))))
            # rendered with the head camera's own field of view (a free camera takes the model's global one), so the boxes drawn over
            # it, projected with the same pinhole, land on what they name
            m.vis.global_.fovy = eye_fovy
            small.update_scene(d, free_eye)
            img = small.render().copy()
            m.vis.global_.fovy = global_fovy
            if f.get("sighting") and lfont is not None:
                # the detections are placed from the trunk (the pose the simulated camera saw them from); the camera is the head's
                # pose from the model at this frame, the free camera's position and direction as built above
                pos = d.cam_xpos[cid] + fwd * EYE_AHEAD_M
                img = _overlay_image(img, lambda im: overlay.draw_eye(im, f["sighting"], overlay.eye_projector(pos, fwd, side, eye_fovy), lfont))
            _paste(frame, img, "bl")
        if top_cam is not None and grids:
            # the robot's discovered map, as it was at this frame's time: what the robot knows, not the room
            if not trail or math.dist(trail[-1], f["pos"][:2]) > 0.1:
                trail.append(tuple(f["pos"][:2]))
            look, dist = _square_top(job)
            half = dist * math.tan(math.radians(45.0 / 2)) / 1.1 * 1.05
            mpx = lambda x, y: (map_side / 2 + (x - look[0]) / half * map_side / 2, map_side / 2 - (y - look[1]) / half * map_side / 2)  # noqa: E731
            gi = f.get("grid_i")
            if gi not in map_cache:
                map_cache.clear()
                map_cache[gi] = (_map_image(grids[gi], map_side, mpx, None if "truth" in hide or tr.get("frame") == "map" else job.get("scene"),
                                            "map" not in hide) if gi is not None else None)
            from PIL import Image, ImageDraw
            img = (map_cache[gi].copy() if map_cache[gi] is not None else Image.new("RGB", (map_side, map_side), MAP_UNKNOWN))
            dr = ImageDraw.Draw(img, "RGBA")
            if f.get("sighting") and f["sighting"].get("pose") and "wedge" not in hide:
                dr.polygon([mpx(*q) for q in overlay.wedge(f["sighting"]["pose"], f["sighting"]["hfov_deg"], f["sighting"]["range_m"])],
                           fill=overlay.WEDGE_RGB + (45,), outline=overlay.WEDGE_RGB + (160,))
            if len(trail) > 1 and "trail" not in hide:
                dr.line([mpx(*q) for q in trail[-600:]], fill=(255, 200, 80, 200), width=2)
            snap = sem_objects[f["obj_i"]] if sem_objects and f.get("obj_i") is not None else None
            for o in (snap or {}).get("items", []) if "objects" not in hide else []:
                if o.get("confirmed") and o["parts"]:
                    cx, cy = mpx(o["parts"][0][0], o["parts"][0][1])
                    dr.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=overlay.object_rgb(o) + (255,))
            rx, ry = mpx(*f["pos"][:2])
            w_, x_, y_, z_ = f["quat"]
            yr = math.atan2(2 * (w_ * z_ + x_ * y_), 1 - 2 * (y_ * y_ + z_ * z_))
            dr.ellipse([rx - 5, ry - 5, rx + 5, ry + 5], fill=(240, 70, 60, 255))
            dr.line([rx, ry, rx + 11 * math.cos(yr), ry - 11 * math.sin(yr)], fill=(240, 70, 60, 255), width=2)
            _paste(frame, np.asarray(img), "br")
        elif top_cam is not None:
            if not trail or math.dist(trail[-1], f["pos"][:2]) > 0.1:
                trail.append(tuple(f["pos"][:2]))
            small.update_scene(d, top_cam)
            for p in trail[-400:]:
                _mark(small, (p[0], p[1], 0.02), 0.03, (0.35, 0.55, 0.95, 1))
            _mark(small, (f["pos"][0], f["pos"][1], 0.05), 0.09, (0.95, 0.25, 0.2, 1))
            img = small.render().copy()
            if sem_objects and lfont is not None and (f.get("obj_i") is not None or f.get("sighting")):
                snap = sem_objects[f["obj_i"]] if f.get("obj_i") is not None else None
                px = overlay.top_to_px(side, top_cam.lookat, top_cam.distance, global_fovy)
                img = _overlay_image(img, lambda im: overlay.draw_top(im, snap, f.get("sighting"), px, lfont))
            _paste(frame, img, "br")
        if font is not None and f.get("hud"):
            _hud(frame, f["hud"], rb.get("name", "robot"), scene_name, font, fsize, side if eye_cam is not None else 0)
        frames.append(frame)
    renderer.close()
    if small is not None:
        small.close()
    mediapy.write_video(job["out"], frames, fps=tr["fps"])
    print(f"video {job['out']}: {len(frames)} frames at {tr['fps']:g} fps, {w}x{h}, joints {len(joint_adr)} of the model's, "
          f"pose from the {tr.get('source', 'truth')}", flush=True)


if __name__ == "__main__":
    render(json.loads(Path(sys.argv[1]).read_text()))
