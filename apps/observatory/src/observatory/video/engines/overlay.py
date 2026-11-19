"""What the MuJoCo engine draws of the robot's semantic map (RFC-0016) over a frame: the HUD's lines, the object footprints and the
camera's wedge in the top inset, and each current detection as a labelled box in the eye inset. Plain Python (no MuJoCo, no
numpy), so a test imports it from the engine's folder; the engine imports it as a sibling (its folder is on sys.path when it
runs as a script).

The job's `semantic` part (observatory.video.track) gives the geometry in the track's frame (the world, or the robot's map when the run
has no truth): `objects` snapshots {t, items: [{id, kind, confirmed, landmark, parts: [[x, y, hx, hy, yaw, z0, z1]]}]}, and per
frame `hud` {sees, room, objects} for the lines, `obj_i` the snapshot in force, `sighting` the current sighting.
"""

import math

LANDMARK_MIN = 0.7          # an object is a landmark from this landmark value on (the operator, 2026-11-18); the pages' is `LANDMARK_MIN` in web/shell/semantic.js
CONFIRMED_RGB, UNCONFIRMED_RGB, LANDMARK_RGB, SEEN_RGB, WEDGE_RGB = (90, 200, 120), (170, 170, 180), (255, 190, 40), (255, 90, 200), (80, 160, 255)


def hud_lines(hud: dict, cols: int) -> list:
    """[(text, (r, g, b))] for the Eye's SEES, ROOM and OBJECTS lines (web/shell/shell.js paintHud shows the same three);
    none for a run with no semantic map (`hud` has no "room", "sees" or "objects")."""
    if not ({"sees", "room", "objects"} & set(hud)):
        return []
    out = []
    sees = hud.get("sees")
    if sees is None:
        out.append(("SEES  no sighting yet", (200, 200, 200)))
    elif not sees:
        out.append(("SEES  nothing in view", (200, 200, 200)))
    else:
        txt = " · ".join(f"{s['kind']} {s['range_m']:.1f} m {round(100 * s['confidence'])}%" if s.get("range_m") is not None and s.get("confidence") is not None
                         else str(s["kind"]) for s in sees)
        for i, ln in enumerate(wrap(txt, cols, 2)):
            out.append((("SEES  " if i == 0 else "      ") + ln, SEEN_RGB))
    room = hud.get("room")
    if room is None:
        out.append(("ROOM  not told yet", (200, 200, 200)))
    else:
        votes = room.get("votes") or {}
        v = " · ".join(f"{k} {x:.2f}" for k, x in sorted(votes.items(), key=lambda kv: -kv[1]))
        name = room.get("name") or "unnamed"
        out.append((f"ROOM  {name}" + (f" ({v})" if v else ""), (255, 255, 255)))
    o = hud.get("objects")
    if o is not None:
        out.append((f"OBJECTS {o['confirmed']} confirmed · {o['total'] - o['confirmed']} not yet", CONFIRMED_RGB))
    return out


def wrap(text: str, n: int, lines: int) -> list:
    words, out, cur = str(text).split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n and cur:
            out.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    out.append(cur)
    return out[:lines] if len(out) <= lines else out[:lines - 1] + [out[lines - 1][: n - 1] + "…"]


def rect(x: float, y: float, hx: float, hy: float, yaw: float) -> list:
    """The four corners of a box in plan."""
    c, s = math.cos(yaw), math.sin(yaw)
    return [(x + c * i * hx - s * j * hy, y + s * i * hx + c * j * hy) for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def top_to_px(side: int, look_at: tuple, distance: float, fovy_deg: float = 45.0):
    """World (x, y) on the floor to pixels in the top inset: straight down over `look_at`, +y up in the image (the engine's top camera,
    a free camera at `distance` with MuJoCo's vertical field of view `fovy_deg`; 89.9 degrees down is taken as 90)."""
    half = distance * math.tan(math.radians(fovy_deg) / 2)
    return lambda x, y: (side / 2 + (x - look_at[0]) / half * side / 2, side / 2 - (y - look_at[1]) / half * side / 2)


def eye_projector(pos, forward, side: int, fovy_deg: float):
    """World point -> (px, py, depth) for a square image seen from `pos` looking along `forward`, vertical field of view `fovy_deg`,
    no roll (the up direction is the world's z, as for MuJoCo's free camera). None for a camera looking straight up or down."""
    fx, fy, fz = forward
    n = math.hypot(fx, fy)
    if n < 1e-6:
        return None
    right = (fy / n, -fx / n, 0.0)
    up = (right[1] * fz - right[2] * fy, right[2] * fx - right[0] * fz, right[0] * fy - right[1] * fx)
    k = side / 2 / math.tan(math.radians(fovy_deg) / 2)

    def project(q):
        v = (q[0] - pos[0], q[1] - pos[1], q[2] - pos[2])
        z = v[0] * fx + v[1] * fy + v[2] * fz
        if z <= 0.02:
            return None
        return (side / 2 + k * (v[0] * right[0] + v[1] * right[1]) / z, side / 2 - k * (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / z, z)
    return project


def seen_box(project, s: dict):
    """A detection as the 2D box it covers in the image: its footprint (a square of its radius, at `world`) from z0 to z1, projected.
    (left, top, right, bottom, depth) or None when it is behind the camera."""
    wx, wy = s["world"]
    r = s.get("radius") or 0.1
    z0, z1 = s.get("z0") or 0.0, s.get("z1") if s.get("z1") is not None else 0.3
    pts = [project((wx + i * r, wy + j * r, z)) for i in (-1, 1) for j in (-1, 1) for z in (z0, z1)]
    pts = [p for p in pts if p]
    if len(pts) < 8:                      # a corner behind the camera: the box does not project whole
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys), min(p[2] for p in pts)


def wedge(pose, hfov_deg: float, range_m: float, steps: int = 12) -> list:
    """The camera's field of view on the floor: the apex and an arc, as plan points (pose is x, y, yaw)."""
    x, y, yaw = pose
    h = math.radians(hfov_deg) / 2
    return [(x, y)] + [(x + range_m * math.cos(yaw - h + 2 * h * k / steps), y + range_m * math.sin(yaw - h + 2 * h * k / steps)) for k in range(steps + 1)]


def object_rgb(o: dict) -> tuple:
    return LANDMARK_RGB if o.get("landmark", 0) >= LANDMARK_MIN else CONFIRMED_RGB if o.get("confirmed") else UNCONFIRMED_RGB


def draw_top(img, snapshot, sighting, px, font) -> None:
    """The semantic map on the top inset (a PIL RGB image): each object's parts as a footprint (confirmed solid, the others faint,
    landmarks in their own colour) with its kind, and the camera's wedge. `px` is top_to_px's function."""
    from PIL import ImageDraw
    over = ImageDraw.Draw(img, "RGBA")
    if sighting and sighting.get("pose"):
        over.polygon([px(*p) for p in wedge(sighting["pose"], sighting["hfov_deg"], sighting["range_m"])], fill=WEDGE_RGB + (60,), outline=WEDGE_RGB + (255,))
    for o in (snapshot or {}).get("items", []):
        rgb, solid = object_rgb(o), o.get("confirmed")
        for x, y, hx, hy, yaw, _z0, _z1 in o["parts"]:
            over.polygon([px(*c) for c in rect(x, y, hx, hy, yaw)], fill=rgb + ((150 if solid else 40),), outline=rgb + (255 if solid else 120,))
        if solid and o["parts"]:
            cx, cy = px(o["parts"][0][0], o["parts"][0][1])
            over.text((cx + 3, cy - 4), o["kind"], font=font, fill=(255, 255, 255, 255))


def draw_eye(img, sighting, project, font) -> list:
    """Each current detection of `sighting` as a labelled box in the eye inset (a PIL RGB image); the labels drawn: ["cabinet 74%", ...]."""
    from PIL import ImageDraw
    drawn = []
    if not sighting or project is None:
        return drawn
    over = ImageDraw.Draw(img, "RGBA")
    for s in sighting.get("seen", []):
        box = seen_box(project, s)
        if box is None:
            continue
        label = f"{s['kind']} {round(100 * s['confidence'])}%" if s.get("confidence") is not None else s["kind"]
        over.rectangle(box[:4], outline=SEEN_RGB + (255,), width=2)
        over.text((box[0] + 2, max(0, box[1] - 12)), label, font=font, fill=SEEN_RGB + (255,))
        drawn.append(label)
    return drawn
