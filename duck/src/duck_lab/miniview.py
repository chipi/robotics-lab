"""miniview: a robot run, as a picture, at one moment — small enough for an AI to use. Meant for any
robot (it lives in the duck package until a shared one exists); it reads the navigator's run log.

Rerun's slice we use, as commands that return pictures: a time cursor (--at), a 3D camera (--view 3d,
--az, --el, --around) or the top view, layers to switch (--layers, Rerun's entity tree), and a
filmstrip under the main view (--film N over --span seconds) or a sheet of moments (--strip):

    uv run miniview runs/explore12 --events                       # what happened, and when
    uv run miniview runs/explore12 --at 79.7 --around 1.2         # a top-down PNG at t = 79.7 s
    uv run miniview runs/explore12 --at 79.7 --layers truth,depth # only what is named
    uv run miniview runs/explore12 --strip 74 80 6 --around 1.2   # six moments on one sheet
    uv run miniview runs/explore12 --at 80 --view 3d --around 1.2 --film 5 --span 4

Layers: apartment, map, memory, depth, plan, belief, truth (all by default).

The picture, in the simulator's world frame: the apartment as it is (grey: walls and furniture; magenta
outline: the stairwell), mapd's grid at that moment (dark cells occupied, light green free), the
navigator's memory (orange: obstacle points; magenta: drops), the depth returns of the last --window
seconds (green floor, red obstacle, blue overhead, magenta below the floor), the plan being followed
(yellow), the duck where the brain believed it was (blue, with its heading) and where it was (green,
truth), with both tracks, and the latest event as the caption. Data and transforms as duck-world
(world.py); the SVG is drawn here and rasterized by Chromium, so nothing new to install.
"""

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from duck_lab.nav.frames import compose, inverse
from duck_lab.world import ENDS, LAYOUT, STAIRS, apply

LAYERS = ("apartment", "map", "memory", "depth", "plan", "belief", "truth")
# Walls and furniture are drawn to this height only (a dollhouse cutaway), so they do not hide the
# duck; a floor grid shows what lies below the floor (the 3D view without it put below-floor returns
# visually "inside" whatever stood behind them).
CUTAWAY_M = 0.5
GRID_M = 0.5
COLOURS = {"f": "#3cc85a", "o": "#e63228", "v": "#3c78e6", "b": "#e600e6"}
PX = 900          # picture width in pixels


def load(run: Path) -> list:
    """The run's records in order, each with a world-frame transform ("_t") and a run time ("_rt")."""
    start = json.loads((run / "start.json").read_text()) if (run / "start.json").exists() else None
    t_wm = compose(tuple(start["truth"]), inverse(tuple(start["map"]))) if start else None
    fresh, offset, last_t, out = t_wm is None, 0.0, 0.0, []
    for line in open(run / "ticks.jsonl"):
        r = json.loads(line)
        if "t" not in r:
            continue
        if r["t"] < last_t - 1.0:
            offset += last_t + 1.0
        last_t = r["t"]
        if fresh and "pose" in r and "truth" in r and not r.get("event"):
            t_wm, fresh = compose(tuple(r["truth"]), inverse(tuple(r["pose"]))), False
        if r.get("event") in ENDS and r.get("goal") is not None and start is None:
            fresh = True
        r["_rt"], r["_t"] = round(offset + r["t"], 3), t_wm
        out.append(r)
    return out


def events(rows: list) -> str:
    keep = [r for r in rows if r.get("event") and r["event"] not in ("plan", "plan_kept", "world", "reached")]
    lines = []
    for r in keep:
        detail = {k: v for k, v in r.items() if k in ("why", "status", "n", "target", "drop_m", "room_m",
                                                         "nearest_mm", "start_cost", "points", "legs")}
        truth = r.get("truth")
        where = f" truth ({truth[0]:.2f},{truth[1]:.2f})" if truth else ""
        lines.append(f"{r['_rt']:8.2f}  {r['event']:<22}{where}  {json.dumps(detail) if detail else ''}")
    return "\n".join(lines)


def scene(rows: list, at: float, window: float, layers=LAYERS) -> dict:
    """What there is to draw at `at`, in the world frame: lists of lines, polygons and points with styles."""
    upto = [r for r in rows if r["_rt"] <= at and r["_t"] is not None]
    if not upto:
        raise SystemExit(f"nothing before t = {at}")
    now = next((r for r in reversed(upto) if "pose" in r and not r.get("event")), upto[-1])
    t = now["_t"]
    world = next((r for r in reversed(upto) if r.get("event") == "world" and r["_t"] == t), None)
    plan = next((r for r in reversed(upto) if r.get("event") == "plan" and r["_t"] == t), None)
    last_ev = next((r for r in reversed(upto) if r.get("event") not in (None, "plan", "plan_kept", "world")), None)
    ticks = [r for r in upto if "pose" in r and not r.get("event") and r["_t"] == t]
    lines, polys, points = [], [], []        # (pts, colour, width) / (pts, fill, opacity) / (xyz, r_m, colour)

    def box(cx, cy, z0, z1, hx, hy, yaw, colour, width=1.0):
        c, s = math.cos(yaw), math.sin(yaw)
        corners = [(cx + c * a - s * b, cy + s * a + c * b) for a, b in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
        for z in (z0, z1):
            lines.append(([(x, y, z) for x, y in corners + corners[:1]], colour, width))
        for x, y in corners:
            lines.append(([(x, y, z0), (x, y, z1)], colour, width))

    if "apartment" in layers:
        for g in json.loads(LAYOUT.read_text())["geoms"]:
            if not g.get("collides") or str(g.get("name", "")).startswith("floor") or g.get("type") not in ("box", "cylinder"):
                continue
            hx, hy = (g["size"][0], g["size"][1]) if g["type"] == "box" else (g["size"][0], g["size"][0])
            hz = g["size"][2] if g["type"] == "box" else g["size"][1]
            z0, z1 = g["pos"][2] - hz, min(g["pos"][2] + hz, CUTAWAY_M)
            if z0 < z1:
                box(g["pos"][0], g["pos"][1], z0, z1, hx, hy, g.get("yaw", 0.0), "#8a8a96")
        x0, x1, y0, y1 = STAIRS
        box((x0 + x1) / 2, (y0 + y1) / 2, -0.3, 0.0, (x1 - x0) / 2, (y1 - y0) / 2, 0.0, "#c000c0", 2.0)
    k = -4.0                                                    # the floor grid
    while k <= 4.0 + 1e-9:
        lines.append(([(k, -3.0, 0.0), (k, 3.0, 0.0)], "#e2e2e8", 0.6))
        if -3.0 <= k <= 3.0:
            lines.append(([(-4.0, k, 0.0), (4.0, k, 0.0)], "#e2e2e8", 0.6))
        k += GRID_M
    if world and "map" in layers:
        g = world["grid"]
        res, (ox, oy), w = g["res_m"], g["origin"], g["width"]
        hr = res / 2
        for i, cell in enumerate(g["cells"]):
            if cell == "?":
                continue
            x, y = apply(t, (ox + (i % w + 0.5) * res, oy + (i // w + 0.5) * res))
            z = 0.06 if cell == "#" else 0.0
            sq = [(x - hr, y - hr, z), (x + hr, y - hr, z), (x + hr, y + hr, z), (x - hr, y + hr, z)]
            polys.append((sq, "#505050" if cell == "#" else "#cdeccd", 0.75))
    if world and "memory" in layers:
        points += [((*apply(t, b), 0.10), 0.008, "#ff9600") for b in world["blocked"]]
        points += [((*apply(t, d), 0.0), 0.010, "#e600e6") for d in world["drops"]]
    if "depth" in layers:
        for r in ticks:
            if r.get("depth") and at - window <= r["_rt"] <= at:
                points += [((*apply(t, d), d[2]), 0.009, COLOURS.get(d[3], "#000")) for d in r["depth"]]
    if plan and "plan" in layers:
        lines.append(([(*apply(t, q), 0.03) for q in plan["path"]], "#e6b400", 2.5))
    ducks = []
    for key, colour, layer in (("pose", "#4682ff", "belief"), ("truth", "#28b45a", "truth")):
        if layer not in layers:
            continue
        track = [(*(apply(t, r["pose"]) if key == "pose" else r["truth"][:2]), 0.01) for r in ticks]
        if len(track) > 1:
            lines.append((track, colour, 1.5))
        if key in now:
            x, y, yaw = compose(t, tuple(now["pose"])) if key == "pose" else now["truth"][:3]
            ducks.append((x, y, yaw, colour))
            ring = [(x + 0.083 * math.cos(a), y + 0.083 * math.sin(a)) for a in [k * math.pi / 8 for k in range(17)]]
            for z in (0.0, 0.272):
                lines.append(([(px_, py_, z) for px_, py_ in ring], colour, 2.0))
            for k in (0, 4, 8, 12):
                lines.append(([(*ring[k], 0.0), (*ring[k], 0.272)], colour, 1.0))
            lines.append(([(x, y, 0.15), (x + 0.18 * math.cos(yaw), y + 0.18 * math.sin(yaw), 0.15)], colour, 3.0))
    caption = f"t = {at:.2f} s"
    if last_ev:
        caption += f"   last event {last_ev['_rt']:.2f} s: {last_ev['event']} {last_ev.get('why') or ''}"
    focus = now["truth"][:2] if "truth" in now else (0.0, 0.0)
    return {"lines": lines, "polys": polys, "points": points, "caption": caption, "focus": focus}


def camera(view: str, focus, around, w: int, h: int, az_deg: float, el_deg: float):
    """A projection (x, y, z) -> (u, v, depth, pixels per metre there), or None behind the camera."""
    if view == "top":
        if around:
            x0, x1, y0, y1 = focus[0] - around, focus[0] + around, focus[1] - around, focus[1] + around
        else:
            x0, x1, y0, y1 = -4.1, 4.1, -3.1, 3.1
        scale = min(w / (x1 - x0), h / (y1 - y0))

        def top(p):
            return (p[0] - x0) * scale, (y1 - p[1]) * scale, -p[2], scale
        return top
    dist = 2.6 * (around or 3.2)
    tx, ty, tz = (focus[0], focus[1], 0.1) if around else (0.0, 0.0, 0.0)
    az, el = math.radians(az_deg), math.radians(el_deg)
    cx, cy, cz = (tx + dist * math.cos(el) * math.cos(az), ty + dist * math.cos(el) * math.sin(az), tz + dist * math.sin(el))
    fx, fy, fz = tx - cx, ty - cy, tz - cz
    n = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / n, fy / n, fz / n
    rx, ry, rz = fy, -fx, 0.0                               # forward × up(0,0,1)
    n = math.hypot(rx, ry)
    rx, ry = rx / n, ry / n
    ux, uy, uz = ry * fz - rz * fy, rz * fx - rx * fz, rx * fy - ry * fx
    focal = w / (2 * math.tan(math.radians(50) / 2))

    def persp(p):
        vx, vy, vz = p[0] - cx, p[1] - cy, p[2] - cz
        zc = vx * fx + vy * fy + vz * fz
        if zc < 0.05:
            return None
        return (w / 2 + focal * (vx * rx + vy * ry + vz * rz) / zc, h / 2 - focal * (vx * ux + vy * uy + vz * uz) / zc,
                zc, focal / zc)
    return persp


def render(sc: dict, view: str, around, w: int, h: int, az: float = -120.0, el: float = 40.0) -> str:
    """One frame as an <svg> of w x h (plus a caption line), painter-sorted far to near."""
    proj = camera(view, sc["focus"], around, w, h, az, el)
    items = []
    for pts, fill, op in sc["polys"]:
        pp = [proj(p) for p in pts]
        if None in pp:
            continue
        d = sum(q[2] for q in pp) / len(pp)
        items.append((d, f'<polygon points="{" ".join(f"{q[0]:.1f},{q[1]:.1f}" for q in pp)}" fill="{fill}" '
                         f'fill-opacity="{op}"/>'))
    for pts, colour, width in sc["lines"]:
        pp = [proj(p) for p in pts]
        if None in pp:
            continue
        d = sum(q[2] for q in pp) / len(pp) - 0.01
        items.append((d, f'<polyline points="{" ".join(f"{q[0]:.1f},{q[1]:.1f}" for q in pp)}" fill="none" '
                         f'stroke="{colour}" stroke-width="{width}"/>'))
    for p, r_m, colour in sc["points"]:
        q = proj(p)
        if q is None:
            continue
        items.append((q[2] - 0.02, f'<circle cx="{q[0]:.1f}" cy="{q[1]:.1f}" r="{max(1.2, r_m * q[3]):.1f}" fill="{colour}"/>'))
    items.sort(key=lambda it: -it[0])
    body = "\n".join(s for _, s in items)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h + 30}" style="background:#fafafa;'
            f'font-family:monospace"><svg x="0" y="0" width="{w}" height="{h}">{body}</svg>'
            f'<text x="8" y="{h + 20}" font-size="{13 if w > 500 else 10}" fill="#222">{sc["caption"][:int(w / 7.5)]}</text></svg>')


def svg_at(rows: list, at: float, around, window: float, layers=LAYERS, px: int = PX, view: str = "top",
           az: float = -120.0, el: float = 40.0) -> str:
    h = int(px * (0.75 if view == "top" and not around else (1.0 if view == "top" else 0.62)))
    return render(scene(rows, at, window, layers), view, around, px, h, az, el)


def composite(rows: list, at: float, around, window: float, layers, view: str, n: int, span: float,
              az: float, el: float) -> str:
    """Rerun's layout in miniature: the main view at `at`, a filmstrip of n frames over the `span`
    seconds before it underneath (the timeline, scrubbed)."""
    main = svg_at(rows, at, around, window, layers, PX, view, az, el)
    mh = int(main.split('height="', 1)[1].split('"', 1)[0])
    tile = PX // n
    frames = [svg_at(rows, at - span + span * i / max(n - 1, 1), around, window, layers, tile, view, az, el)
              for i in range(n)]
    th = int(frames[0].split('height="', 1)[1].split('"', 1)[0])
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PX}" height="{mh + th}" style="background:#fafafa">',
           f'<svg x="0" y="0" width="{PX}" height="{mh}">{main.split(">", 1)[1].rsplit("</svg>", 1)[0]}</svg>']
    for i, f in enumerate(frames):
        out.append(f'<svg x="{i * tile}" y="{mh}" width="{tile}" height="{th}">{f.split(">", 1)[1].rsplit("</svg>", 1)[0]}'
                   f'<rect x="0" y="0" width="{tile}" height="{th}" fill="none" stroke="#999"/></svg>')
    out.append("</svg>")
    return "\n".join(out)


def strip(rows: list, t0: float, t1: float, n: int, around, window: float, layers, view: str = "top",
          az: float = -120.0, el: float = 40.0) -> str:
    """n moments from t0 to t1 side by side, two rows when there are more than four: scrubbing."""
    times = [t0 + (t1 - t0) * i / max(n - 1, 1) for i in range(n)]
    cols = n if n <= 4 else math.ceil(n / 2)
    tile = 420
    frames = [svg_at(rows, t, around, window, layers, tile, view, az, el) for t in times]
    h = int(frames[0].split('height="', 1)[1].split('"', 1)[0])
    rows_n = math.ceil(n / cols)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols * tile}" height="{rows_n * h}" '
           f'style="background:#fafafa">']
    for i, f in enumerate(frames):
        inner = f.split(">", 1)[1].rsplit("</svg>", 1)[0]
        # A nested <svg> is its own viewport: it clips what lies outside the tile (a <g> does not).
        out.append(f'<svg x="{(i % cols) * tile}" y="{(i // cols) * h}" width="{tile}" height="{h}">{inner}'
                   f'<rect x="0" y="0" width="{tile}" height="{h}" fill="none" stroke="#999"/></svg>')
    out.append("</svg>")
    return "\n".join(out)


def to_png(svg: str, png: Path) -> None:
    browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not browser:
        raise SystemExit("no Chromium to rasterize with; use --svg")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "view.svg"
        src.write_text(svg)
        w = int(svg.split('width="', 1)[1].split('"', 1)[0])
        h = int(svg.split('height="', 1)[1].split('"', 1)[0])
        subprocess.run([browser, "--headless=new", "--no-sandbox", f"--window-size={w},{h}",
                        f"--screenshot={png.resolve()}", src.as_uri()], capture_output=True, timeout=60, check=False)
    if not png.exists():
        raise SystemExit(f"Chromium did not write {png}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path, help="a run directory with ticks.jsonl")
    ap.add_argument("--events", action="store_true", help="list what happened, and when")
    ap.add_argument("--at", type=float, help="the moment (s, the run's time) to draw")
    ap.add_argument("--around", type=float, help="draw this many metres around the duck, not the whole apartment")
    ap.add_argument("--window", type=float, default=1.0, help="depth returns of the last this-many seconds")
    ap.add_argument("-o", "--out", type=Path, help="the PNG (default: RUN/view-<t>.png)")
    ap.add_argument("--svg", action="store_true", help="write the SVG instead of a PNG")
    ap.add_argument("--layers", default=",".join(LAYERS), help="comma-separated: " + ", ".join(LAYERS))
    ap.add_argument("--strip", nargs=3, type=float, metavar=("T0", "T1", "N"), help="N moments from T0 to T1")
    ap.add_argument("--view", choices=("top", "3d"), default="top", help="top-down, or a 3D camera")
    ap.add_argument("--az", type=float, default=-120.0, help="3D camera: the direction it looks from (deg)")
    ap.add_argument("--el", type=float, default=40.0, help="3D camera: its height above the floor (deg)")
    ap.add_argument("--film", type=int, default=0, help="a filmstrip of this many frames under the main view")
    ap.add_argument("--span", type=float, default=4.0, help="the filmstrip's seconds before --at")
    args = ap.parse_args()
    layers = tuple(x.strip() for x in args.layers.split(",") if x.strip())
    unknown = [x for x in layers if x not in LAYERS]
    if unknown:
        ap.error(f"unknown layers {unknown}; known: {', '.join(LAYERS)}")
    rows = load(args.run)
    if args.strip:
        t0, t1, n = args.strip
        svg = strip(rows, t0, t1, int(n), args.around, args.window, layers, args.view, args.az, args.el)
        name = f"strip-{t0:.1f}-{t1:.1f}"
    elif args.events or args.at is None:
        print(events(rows))
        return
    elif args.film:
        svg = composite(rows, args.at, args.around, args.window, layers, args.view, args.film, args.span,
                        args.az, args.el)
        name = f"view-{args.at:.1f}-film"
    else:
        svg = svg_at(rows, args.at, args.around, args.window, layers, PX, args.view, args.az, args.el)
        name = f"view-{args.at:.1f}"
    if args.svg:
        out = args.out or args.run / f"{name}.svg"
        out.write_text(svg)
    else:
        out = args.out or args.run / f"{name}.png"
        to_png(svg, out)
    print(out)


if __name__ == "__main__":
    main()
