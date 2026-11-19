"""The left panel by meaning and the Explore tab (UXS-001, RFC-0011, operator 2026-11-16), in headless Chromium, both pages: the
sections World, Body, Senses, Mind, Other values, closed until opened (the one holding the selected stream opens), the choice
remembered; the joints by chain with their technical names and their angle at the playhead, a switch to hide the angles;
Explore with a robot's body drawn from its description, posed as recorded (following the playhead) or by hand, parts picked
in the list or in the body, their details, isolate, hide, show all; and the pages' forward kinematics (shell/robot.js) where
MuJoCo puts every link of the duck (robots/duck/fk_fixture.json). A throwaway two-link arm with generated meshes: no duck
meshes needed. Screenshots to /tmp/claude-1000/explore-pages/ (EXPLORE_SHOTS=0 turns them off).
Run: cd apps/observatory && uv run python tests/test_explore_pages.py"""

import json
import math
import os
import struct
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")
os.environ.setdefault("MINIVIEW_INDEX", str(TMP / "index.sqlite"))

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import T0_NS, catalog, make_run, scene, serve  # noqa: E402
from runfile import keys, mcapio
from observatory import kinematics  # noqa: E402
from observatory.shots import launch  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
SHOTS = Path("/tmp/claude-1000/explore-pages") if os.environ.get("EXPLORE_SHOTS", "1") != "0" else None
fails, lib = [], "?"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def box_stl(sx, sy, sz, z0=0.0) -> bytes:
    """A binary STL of a box (12 triangles), from z0 up."""
    v = [(x, y, z) for x in (-sx / 2, sx / 2) for y in (-sy / 2, sy / 2) for z in (z0, z0 + sz)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    out = bytearray(80) + struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + struct.pack("<H", 0)
    return bytes(out)


ARM = """<robot name="arm">
  <link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry><material name="b"><color rgba="0.6 0.6 0.65 1"/></material></visual></link>
  <link name="upper"><visual><geometry><mesh filename="meshes/upper.stl"/></geometry><material name="u"><color rgba="0.9 0.6 0.2 1"/></material></visual></link>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
(arm / "meshes").mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm", "stand_z": 0.05}')
(arm / "meshes" / "base.stl").write_bytes(box_stl(0.12, 0.12, 0.1))
(arm / "meshes" / "upper.stl").write_bytes(box_stl(0.03, 0.03, 0.15))

# a run of the arm: a pose per tick (the spatial views), its joint and three other signals at 10 Hz
KEY = "arm/room/r1"
data = TMP / "data"
SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "pitch_deg", "kind": "number", "unit": "deg"},
        {"name": "roll_deg", "kind": "number", "unit": "deg"}, {"name": "battery_v", "kind": "number", "unit": "V"}]
rec = mcapio.Recorder(keys.run_dir(data, KEY), mcapio.new_run(KEY, {"name": "arm", "radius": 0.08, "height": 0.27}, "room", "exploration", T0_NS,
                                                              "writer", signals=SIGS))
rec.add(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})
shoulder = lambda t: round(0.6 * math.sin(t), 4)  # noqa: E731
for k in range(0, 51):
    t = k * 0.1
    rec.begin_tick(t, [0.02 * k, 0.0, 0.0])
    # the truth a metre aside, its whole pose (ADR-0016): 0.2 m up, turned 0.2 rad about x; the IMU's tilt for the belief's body
    rec.tick_truth([0.02 * k + 1.0, 0.5, 0.0], {"z": 0.2, "quat": [math.cos(0.1), math.sin(0.1), 0.0, 0.0]})
    rec.tick_tilt(2.0, -1.0)
    rec.end_tick()
    rec.begin_signals(t + 0.05, {"joint_shoulder": shoulder(t + 0.05), "pitch_deg": 1.0, "roll_deg": -0.5, "battery_v": 7.4})
    rec.end_tick()
rec.add(5.2, "end", {"status": "ended"})
rec.close()


# a run that sees and maps (the Depth frame and Map kinds): six depth frames, each written just before the tick that uses it, which
# carries what the navigator derived from it (the frames differ in what the cells and points can say, below); two world grids, a plan,
# a cabinet and the operator's two areas. The first run above has none of these.
D_KEY = "arm/room/d1"
GW, GH, RES, ORIGIN = 12, 8, 0.1, [-0.2, -0.3]
KIND_AT = "fovb"
AREAS = [{"id": "a1", "name": "Kitchen", "type": "kitchen", "polygon": [[0.2, -0.2], [0.9, -0.2], [0.9, 0.4], [0.2, 0.4]]},
         {"id": "a2", "name": "Hall", "type": None, "polygon": [[-0.2, -0.2], [0.2, -0.2], [0.2, 0.4], [-0.2, 0.4]]}]
CABINET = {"id": "cabinet_1", "kind": "cabinet", "x": 0.6, "y": 0.2, "n": 3, "confirmed": True, "landmark": 0.8, "permanence": "fixed",
           "confidence": 0.9, "parts": [[0.6, 0.2, 0.1, 0.15, 0.3, 0.0, 0.7]]}
PLAN = [[0.0, 0.0], [0.4, 0.0], [0.8, 0.2]]


def cells(second):
    """Row-major from the lowest y: unknown along the top row and the first column, occupied along the last column (and, in the second grid, a wall)."""
    out = []
    for j in range(GH):
        for i in range(GW):
            out.append("?" if (j == GH - 1 or i == 0) else "#" if (i == GW - 1 or (second and j == 5 and 3 <= i <= 6)) else ".")
    return "".join(out)


def status_of(j):
    st = [5] * 64
    if j == 1:
        st[0:4] = [0, 0, 0, 0]
        st[63] = 255                    # no target, and no point was made for it
    if j == 2:
        st[63] = 255                    # no target, and the cliff check put a "below" point where the floor should have been
    return st


def distances_of(j):
    return [300 + 20 * i + 100 * j for i in range(64)]


def points_of(j):
    st = status_of(j)
    if j == 3:
        return [[0.5, 0.0, 0.0, "f"], [0.6, 0.1, 0.3, "o"]]         # two points for 64 valid zones: they cannot be told apart
    return [[round(0.4 + 0.01 * i + 0.05 * j, 3), round(-0.2 + 0.005 * i, 3), round(0.01 * (i % 4), 3), KIND_AT[i % 4]]
            for i in range(64) if st[i] == 5 or (j == 2 and i == 63)]


def d_records():
    out = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]}),
           (0.0, "event", {"kind": "site", "text": "", "notable": False, "t_src": 0.0, "raw": {}, "site": {"id": "home", "name": "Home", "kind": "apartment", "areas": AREAS}}),
           (0.05, "world", {"grid": {"res": RES, "origin": ORIGIN, "w": GW, "h": GH, "cells": cells(False)}, "obstacles": [[0.25, 0.05]], "drops": []}),
           (0.05, "plan", {"path": PLAN}),
           (1.0, "objects", {"objects": [CABINET], "changes": [["new", "cabinet_1"]]}),
           (2.0, "world", {"grid": {"res": RES, "origin": ORIGIN, "w": GW, "h": GH, "cells": cells(True)}, "obstacles": [[0.5, 0.1], [0.52, 0.12]], "drops": [[0.75, -0.15]]})]
    uses = {2 + 5 * j: j for j in range(6) if j != 4}                 # frame 4 is the one no tick carries points for
    for j in range(6):
        t = round(0.18 + 0.5 * j, 3)
        out.append((t, "depth_frame", {"rows": 8, "cols": 8, "distance_mm": distances_of(j), "status": status_of(j), "seq": j, "frame_t_ns": 1_000_000_000 + j,
                                       "state_t_ns": 1_000_000_000 + j - 1000, "pair_dt_ms": -0.001, "t_src": t, "derived": {"points": points_of(j)}}))
        k = 2 + 5 * j
        out.append((round(0.1 * k, 3), "tick", {"belief": [0.02 * k, 0.0, 0.1], "truth": None, "tilt": None, "cmd": [0.3, 0.0],
                                                "depth": points_of(uses[k]) if k in uses else None, "t_src": round(0.1 * k, 3), "raw": {}}))
    for k in range(31):
        if k not in range(2, 30, 5):
            out.append((round(0.1 * k, 3), "tick", {"belief": [0.02 * k, 0.0, 0.1], "truth": None, "tilt": None, "cmd": [0.3, 0.0], "depth": None, "t_src": round(0.1 * k, 3), "raw": {}}))
    out.append((3.2, "end", {"verdict": "reached"}))
    return sorted(out, key=lambda r: r[0])


make_run(data, D_KEY, d_records())


def page_of(b, base, width=1600, height=1000, scheme="dark"):
    ctx = b.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.on("response", lambda r: logs.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)
    page.goto(f"{base}/web/{lib}/index.html")
    page.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
    return ctx, page, logs


def call(page, js, t=60000):
    page.evaluate("window.__ready = false")
    r = page.evaluate(js)
    page.wait_for_function("window.__ready === true", timeout=t)
    return r


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{lib}-{name}.png"))


def rows(page):
    return page.evaluate("[...document.querySelectorAll('#tree .row')].map((r) => r.dataset.id)")


def click_xy(page, js):
    """A real click at a client point the page names (its canvas scrolled into view first: on a phone it is below the fold)."""
    page.evaluate("window.miniview.exploreView().canvas().scrollIntoView({ block: 'center' })")
    xy = page.evaluate(js)
    page.mouse.click(*xy)


def hexrgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def token(page, name):
    return hexrgb(page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()"))


def close_to(a, b, tol=3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def wait_x(page, expr, t=15000):
    page.wait_for_function("(() => { const s = window.miniview.exploreState(); return !!s && (" + expr + "); })()", timeout=t)


# pixels are read from a copy made for reading (the page's own canvas is not asked to read back again and again)
COPY = """(() => { const c = window.miniview.exploreView().canvas(), s = document.createElement('canvas'); s.width = c.width; s.height = c.height;
  const g = s.getContext('2d', { willReadFrequently: true }); g.drawImage(c, 0, 0); return g; })()"""


def rgb_at(page, x, y):
    return page.evaluate(f"([x, y]) => [...{COPY}.getImageData(x, y, 1, 1).data].slice(0, 3)", [x, y])


def colours(page):
    return page.evaluate(f"""() => {{ const g = {COPY}, d = g.getImageData(0, 0, g.canvas.width, g.canvas.height).data, seen = new Set();
      for (let i = 0; i < d.length; i += 28) seen.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]); return seen.size; }}""")


def at_canvas(page, sx, sy):
    """The canvas pixel under a client point."""
    return page.evaluate("([x, y]) => { const b = window.miniview.exploreView().canvas().getBoundingClientRect(); return [Math.round(x - b.left), Math.round(y - b.top)]; }", [sx, sy])


def depth_checks(page, tag):
    call(page, "window.miniview.setTime(0.3)")
    call(page, "window.miniview.exploreKind('depth')")
    wait_x(page, "s.shown && s.index === 0")
    opts = page.evaluate("[...document.querySelectorAll('#xwhat option')].map((o) => [o.value, o.textContent, o.disabled])")
    check(f"{tag}: the selector offers the depth frame and the map, enabled, no longer 'later'",
          ["depth", "Depth frame", False] in opts and ["map", "Map", False] in opts and not any("later" in o[1] for o in opts), opts)
    s = page.evaluate("window.miniview.exploreState()")
    check(f"{tag}: Depth frame at 0.3 s: the frame in force (the first, at 0.18 s), its 8 x 8 distances as recorded, the kinds derived from it, the tick that used it",
          s["kind"] == "depth frame" and (s["rows"], s["cols"], s["index"], s["n"]) == (8, 8, 0, 6) and s["distance_mm"] == distances_of(0)
          and s["derived"] and s["tickT"] == 0.2 and s["kinds"] == [KIND_AT[i % 4] for i in range(64)], {k: s[k] for k in ("kind", "index", "n", "derived", "derivedWhy", "tickT")})
    check(f"{tag}: it draws something (the canvas holds many colours) and a scale, and says which frame it is",
          colours(page) > 8 and page.evaluate("!!document.querySelector('#xdepth .xbar') && document.querySelector('#xdepth .xticks').innerText.includes('4 m')")
          and "frame 1 of 6" in page.evaluate("document.querySelector('#xdepth [data-x=info]').textContent"), colours(page))
    shot(page, f"{tag}-depth-distance")

    click_xy(page, "window.miniview.exploreView().screenOfCell(2, 3)")
    s = page.evaluate("window.miniview.exploreState()")
    want = points_of(0)[19]
    txt = page.evaluate("document.querySelector('#xdepth [data-x=cell]').innerText")
    check(f"{tag}: a click on a cell (row 2, column 3) reports its values: distance, status, kind, its point in the map frame",
          s["cell"] == {"row": 2, "col": 3, "mm": 680, "status": 5, "valid": True, "kind": "below the floor", "point": {"x": want[0], "y": want[1], "height": want[2]}, "why": None}
          and all(x in txt for x in ("row 2, column 3", "680 mm", "5 (range valid)", "below the floor", f"x {want[0]} m, y {want[1]} m, height {want[2]} m")), (s["cell"], txt))

    page.click('#xdepth [data-color="kind"]')
    cell = page.evaluate("window.miniview.exploreView().canvas().width / 8")
    got = [rgb_at(page, int(c * cell + 3), 3) for c in range(4)]
    want_c = [token(page, v) for v in ("--c-floor", "--c-ob", "--c-over", "--c-drop")]
    check(f"{tag}: coloured by the derived kind: floor, obstacle, overhead, below, in the colours the 3D scene uses",
          page.evaluate("window.miniview.exploreState().color") == "kind" and all(close_to(g, w) for g, w in zip(got, want_c)), (got, want_c))
    n_scale = page.evaluate("document.querySelector('#xdepth [data-x=scale]').innerText")
    check(f"{tag}: the kind legend counts the cells of each kind (16 each)", all(f"{n} 16" in n_scale for n in ("floor", "obstacle", "overhead", "below the floor")), n_scale)
    shot(page, f"{tag}-depth-kind")
    page.click('#xdepth [data-color="distance"]')
    check(f"{tag}: back to distances: the cell is the distance's colour, not the kind's", not close_to(rgb_at(page, 3, 3), want_c[0], 20) and page.evaluate("window.miniview.exploreState().color") == "distance")

    # the playhead: frame 2 (1.18 s) has a no-target zone the cliff check put a point at; the cell picked stays picked
    call(page, "window.miniview.setTime(1.3)")
    wait_x(page, "s.shown && s.index === 2")
    s = page.evaluate("window.miniview.exploreState()")
    want = points_of(2)[19]
    check(f"{tag}: it follows the playhead: at 1.3 s frame 3 of 6, the cell picked is still picked and shows this frame's values",
          s["tickT"] == 1.2 and s["cell"]["row"] == 2 and s["cell"]["col"] == 3 and s["cell"]["mm"] == distances_of(2)[19]
          and s["cell"]["point"] == {"x": want[0], "y": want[1], "height": want[2]}, s["cell"])
    click_xy(page, "window.miniview.exploreView().screenOfCell(7, 7)")
    s = page.evaluate("window.miniview.exploreState()")
    want = points_of(2)[63]
    check(f"{tag}: a no-target zone (status 255) with a 'below' point: its status named, its kind below the floor, its point",
          s["cell"]["status"] == 255 and not s["cell"]["valid"] and s["cell"]["kind"] == "below the floor" and s["cell"]["point"]["x"] == want[0]
          and "255 (no target)" in page.evaluate("document.querySelector('#xdepth [data-x=cell]').innerText"), s["cell"])
    page.evaluate("window.miniview.exploreView().setColor('kind')")

    call(page, "window.miniview.setTime(0.9)")
    wait_x(page, "s.shown && s.index === 1")
    click_xy(page, "window.miniview.exploreView().screenOfCell(0, 0)")
    s = page.evaluate("window.miniview.exploreState()")
    check(f"{tag}: a zone with a status that is not valid: no kind, no point, its status said; it is hatched, not coloured",
          s["cell"]["status"] == 0 and not s["cell"]["valid"] and s["cell"]["kind"] is None and s["cell"]["point"] is None
          and "0 (not valid)" in page.evaluate("document.querySelector('#xdepth [data-x=cell]').innerText"), s["cell"])
    click_xy(page, "window.miniview.exploreView().screenOfCell(1, 0)")
    s = page.evaluate("window.miniview.exploreState()")
    want = points_of(1)[4]
    check(f"{tag}: the points are assigned to the valid zones in order: the fifth valid zone (row 1, column 0, after four not valid) has the fifth point",
          s["derived"] and s["cell"]["point"] == {"x": want[0], "y": want[1], "height": want[2]} and s["cell"]["kind"] == {"f": "floor", "o": "obstacle", "v": "overhead", "b": "below the floor"}[want[3]], s["cell"])

    call(page, "window.miniview.setTime(1.9)")
    wait_x(page, "s.shown && s.index === 3")
    s = page.evaluate("window.miniview.exploreState()")
    check(f"{tag}: a frame whose derived points cannot be assigned to zones (2 points for 64 valid zones): no kinds, the reason said, the kind switch off, coloured by distance",
          not s["derived"] and "2 derived points for 64 valid zones" in s["derivedWhy"] and s["color"] == "distance" and page.evaluate("document.querySelector('#xdepth [data-color=kind]').disabled")
          and "not derived" in page.evaluate("document.querySelector('#xdepth [data-x=cell]').innerText"), (s["derivedWhy"], s["color"]))
    call(page, "window.miniview.setTime(2.4)")
    wait_x(page, "s.shown && s.index === 4")
    s = page.evaluate("window.miniview.exploreState()")
    check(f"{tag}: a frame no tick used (the next tick carries no points): no kinds, and it says so", not s["derived"] and "no tick" in s["derivedWhy"], s["derivedWhy"])
    call(page, "window.miniview.setTime(2.9)")
    wait_x(page, "s.shown && s.index === 5")
    check(f"{tag}: the last frame again has its kinds", page.evaluate("window.miniview.exploreState().derived"))


def map_checks(page, tag, light=False):
    call(page, "window.miniview.setTime(0.3)")
    call(page, "window.miniview.exploreKind('map')")
    wait_x(page, "s.shown && s.worldN === 1")
    s = page.evaluate("window.miniview.exploreState()")
    c = {k: cells(False).count(k) for k in "?.#"}
    check(f"{tag}: Map at 0.3 s: the grid in force (1 of 2), its size and cell counts, the obstacle memory, the plan, the belief pose, the operator's areas, no objects yet",
          s["kind"] == "map" and (s["worldN"], s["worldCount"], s["w"], s["h"], s["res"]) == (1, 2, GW, GH, RES) and s["counts"] == c and s["obstacles"] == 1 and s["drops"] == 0
          and s["plan"] == 3 and s["belief"] == [0.06, 0.0, 0.1] and s["areas"] == ["Kitchen", "Hall"] and s["objects"] == 0, s)
    check(f"{tag}: it draws something and says which map it is", colours(page) > 8 and "map 1 of 2" in page.evaluate("document.querySelector('#xmap [data-x=info]').textContent")
          and f"{c['.']} free, {c['#']} occupied, {c['?']} unknown" in page.evaluate("document.querySelector('#xmap [data-x=info]').textContent"), colours(page))
    shot(page, f"{tag}-map")

    def shown_at(x, y):
        sx, sy = page.evaluate(f"window.miniview.exploreView().screenOfPoint({x}, {y})")
        return rgb_at(page, *at_canvas(page, sx, sy))

    free, occ, plan = token(page, "--c-free"), token(page, "--c-occ"), token(page, "--c-plan")
    on_plan = lambda: any(close_to(shown_at(0.3, d), plan, 70) for d in (-0.004, 0.0, 0.004))  # noqa: E731  (a thin antialiased line: any of three samples across it, near the plan colour)
    check(f"{tag}: a free cell is the theme's free colour, an occupied one its occupied colour, the plan runs over the grid in the plan colour",
          close_to(shown_at(0.45, -0.15), free) and close_to(shown_at(0.95, -0.05), occ) and on_plan(), (shown_at(0.45, -0.15), free, shown_at(0.95, -0.05), occ, [shown_at(0.3, d) for d in (-0.004, 0.0, 0.004)]))

    def click_at(x, y):
        click_xy(page, f"window.miniview.exploreView().screenOfPoint({x}, {y})")
        return page.evaluate("window.miniview.exploreState().cell")

    got = click_at(0.45, -0.15)
    check(f"{tag}: a click on a cell reports its value and its coordinates in the map frame (cell 6, 1: free, centre 0.45, -0.15)",
          got["inside"] and (got["i"], got["j"], got["value"], got["name"], got["x"], got["y"]) == (6, 1, ".", "free", 0.45, -0.15)
          and "free" in page.evaluate("document.querySelector('#xmap [data-x=cell]').innerText"), got)
    got = click_at(0.25, 0.05)
    check(f"{tag}: a click on the cell with the obstacle memory's point says it has one", got["inside"] and (got["i"], got["j"]) == (4, 3) and got["obstacle_points"] == 1 and got["drop_points"] == 0, got)
    got = click_at(0.95, -0.05)
    check(f"{tag}: an occupied cell (11, 2)", got["inside"] and (got["i"], got["j"], got["value"], got["name"]) == (11, 2, "#", "occupied"), got)
    got = click_at(0.4, -0.37)
    check(f"{tag}: a click outside the grid says so and gives the point", not got["inside"] and abs(got["x"] - 0.4) < 0.01 and "Outside the grid" in page.evaluate("document.querySelector('#xmap [data-x=cell]').innerText"), got)

    k0 = page.evaluate("window.miniview.exploreState().view")
    page.click('#xmap [data-zoom="in"]')
    k1 = page.evaluate("window.miniview.exploreState().view")
    check(f"{tag}: zoom in (the button) enlarges by a quarter, about the centre", abs(k1["k"] / k0["k"] - 1.25) < 1e-6 and abs(k1["cx"] - k0["cx"]) < 1e-9, (k0, k1))
    cx = page.evaluate("(() => { const b = window.miniview.exploreView().canvas().getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()")
    page.mouse.move(*cx)
    page.mouse.wheel(0, -300)
    page.wait_for_function(f"window.miniview.exploreState().view.k > {k1['k'] * 1.05}", timeout=5000)
    k2 = page.evaluate("window.miniview.exploreState().view")
    check(f"{tag}: the wheel zooms too", k2["k"] > k1["k"] * 1.05, (k1, k2))
    page.mouse.move(*cx)
    page.mouse.down()
    page.mouse.move(cx[0] + 60, cx[1] + 30, steps=4)
    page.mouse.up()
    k3 = page.evaluate("window.miniview.exploreState().view")
    check(f"{tag}: dragging pans (the map follows the pointer) and does not pick a cell",
          abs((k3["cx"] - k2["cx"]) * k3["k"] + 60) < 1.5 and abs((k3["cy"] - k2["cy"]) * k3["k"] - 30) < 1.5 and page.evaluate("window.miniview.exploreState().cell.inside") is False, (k2, k3))
    got = click_at(0.35, 0.15)
    check(f"{tag}: after zooming and panning a click still lands on the cell under it (cell 5, 4, free)", got["inside"] and (got["i"], got["j"], got["value"]) == (5, 4, "."), got)
    page.click('#xmap [data-zoom="fit"]')
    k4 = page.evaluate("window.miniview.exploreState().view")
    check(f"{tag}: Fit brings the whole map back", abs(k4["k"] - k0["k"]) < 1e-6 and abs(k4["cx"] - k0["cx"]) < 1e-9 and abs(k4["cy"] - k0["cy"]) < 1e-9, (k0, k4))
    page.click('#xmap [data-layer="plan"]')
    check(f"{tag}: a layer switches off (the plan): its line is gone from the canvas", page.evaluate("window.miniview.exploreState().layers.plan") is False and not on_plan(), [shown_at(0.3, d) for d in (-0.004, 0.0, 0.004)])
    page.click('#xmap [data-layer="plan"]')

    call(page, "window.miniview.setTime(2.5)")
    wait_x(page, "s.shown && s.worldN === 2")
    s = page.evaluate("window.miniview.exploreState()")
    c2 = {k: cells(True).count(k) for k in "?.#"}
    check(f"{tag}: it follows the playhead: at 2.5 s the second grid, its obstacle memory and drop, the belief where it is, the cabinet",
          s["counts"] == c2 and s["obstacles"] == 2 and s["drops"] == 1 and s["belief"] == [0.5, 0.0, 0.1] and s["objects"] == 1 and s["worldT"] == 2.0, s)
    got = click_at(0.75, -0.15)
    check(f"{tag}: the cell with the drop says so", got["inside"] and got["drop_points"] == 1, got)
    shot(page, f"{tag}-map-later")


def empty_checks(page, tag):
    call(page, f"window.miniview.load('room', '{KEY}')")
    call(page, "window.miniview.exploreKind('depth')")
    s = page.evaluate("window.miniview.exploreState()")
    msg = page.evaluate("(() => { const m = document.querySelector('#xdepth [data-x=msg]'); return [m.hidden, m.textContent]; })()")
    check(f"{tag}: a run without depth frames: Depth frame says so, plainly, and draws no grid", not s["shown"] and msg[0] is False and "no depth frames" in msg[1]
          and page.evaluate("document.querySelector('#xdepth [data-x=wrap]').hidden"), (s["why"], msg))
    call(page, "window.miniview.exploreKind('map')")
    s = page.evaluate("window.miniview.exploreState()")
    msg = page.evaluate("(() => { const m = document.querySelector('#xmap [data-x=msg]'); return [m.hidden, m.textContent]; })()")
    check(f"{tag}: a run without a world grid: Map says so, plainly", not s["shown"] and msg[0] is False and "no world grid" in msg[1] and page.evaluate("document.querySelector('#xmap [data-x=wrap]').hidden"), (s["why"], msg))
    call(page, "window.miniview.exploreKind('robot')")
    page.wait_for_function("window.miniview.exploreState()?.drawn === 2", timeout=20000)
    xs = page.evaluate("window.miniview.exploreState()")
    check(f"{tag}: back to the robot's body: its panel is shown again and the body drawn", xs["kind"] == "robot body" and page.evaluate("!document.getElementById('xrobot').hidden && document.getElementById('xdepth').hidden && document.getElementById('xmap').hidden"), xs["kind"])


with sync_playwright() as p:
    cat = catalog(data)
    cat.put_scene(scene("room"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    duck = kinematics.describe(kinematics.load(REPO / "robots" / "duck" / "robot.urdf"))
    fixture = json.loads((REPO / "robots" / "duck" / "fk_fixture.json").read_text())
    try:
        for lib in ("three", "deck"):
            ctx, page, logs = page_of(b, base)
            page.evaluate("localStorage.removeItem('miniview.left')")
            call(page, f"window.miniview.load('room', '{KEY}')")
            st = page.evaluate("window.miniview.state()")
            secs = {s["id"]: s for s in st["sections"]}
            check("the left panel's sections, in order: World, Body, Senses, Mind, Other values",
                  [s["name"] for s in st["sections"]] == ["World", "Body", "Senses", "Mind", "Other values"], [s["name"] for s in st["sections"]])
            check("what each holds: the joint in Body, the IMU's values in Senses, the belief in Mind, the rest in Other values",
                  "signals.joint_shoulder" in secs["sec.body"]["streams"] and {"signals.pitch_deg", "signals.roll_deg", "sensors.tilt"} <= set(secs["sec.senses"]["streams"])
                  and "belief.pose" in secs["sec.mind"]["streams"] and secs["sec.other"]["streams"] == ["signals.battery_v"]
                  and {"scene.boxes", "truth.pose"} <= set(secs["sec.world"]["streams"]), {k: v["streams"] for k, v in secs.items()})
            check("closed until opened: only the section holding the selected stream (Mind: the belief) is open",
                  [s["id"] for s in st["sections"] if s["open"]] == ["sec.mind"], [(s["id"], s["open"]) for s in st["sections"]])
            check("a closed section shows no rows", "signals.joint_shoulder" not in rows(page) and "sec.body" in rows(page))
            page.click('#tree .row[data-id="sec.body"] .name')
            check("clicking a section's header opens it: the 3D model row, the chain (named by its first part: the arm's one chain), the joint by its technical name",
                  page.evaluate("document.querySelector('#tree .row[data-id=\"sec.body\"]').getAttribute('aria-expanded')") == "true"
                  and {"body.model", "g.chain.upper", "signals.joint_shoulder"} <= set(rows(page))
                  and page.evaluate("document.querySelector('#tree .row[data-id=\"signals.joint_shoulder\"] .name').textContent") == "shoulder",
                  rows(page))
            call(page, "window.miniview.setTime(1.0)")
            want = f"{math.degrees(shoulder(0.95)):.1f}°"
            got = page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent")
            check("the joint's angle at the playhead, in degrees (the sample at or before t), shown (not only on hover)", got == want
                  and page.evaluate("getComputedStyle(document.querySelector('#tree [data-angle=\"shoulder\"]')).opacity") == "1", (got, want))
            check("the timeline names the joint's row as the outliner does",
                  page.evaluate("document.querySelector('#lanesL .lane-l[data-lane=\"signals.joint_shoulder\"]').innerText.trim()") == "shoulder")
            call(page, "window.miniview.setTime(3.0)")
            got3 = page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent")
            check("the angle follows the playhead", got3 == f"{math.degrees(shoulder(2.95)):.1f}°", got3)
            page.click('#tree [data-angles]')
            check("the switch hides the angles", page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent") == ""
                  and page.evaluate("window.miniview.state().angles") is False)
            shot(page, "left-body-open")

            # remembered in this browser: a reload keeps Body open and the angles hidden
            page.reload()
            page.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
            call(page, f"window.miniview.load('room', '{KEY}')")
            st2 = page.evaluate("window.miniview.state()")
            check("the viewer's choice is remembered: Body open, the angles hidden",
                  [s["id"] for s in st2["sections"] if s["open"]] == ["sec.body", "sec.mind"] and st2["angles"] is False,
                  ([(s["id"], s["open"]) for s in st2["sections"]], st2["angles"]))
            call(page, "window.miniview.setAngles(true)")

            # Explore: the run's robot, posed as recorded
            page.click('#tree .row[data-id="body.model"]')
            page.wait_for_function("window.miniview.exploreState()?.robot === 'arm' && window.miniview.exploreState().drawn === 2", timeout=20000)
            xs = page.evaluate("window.miniview.exploreState()")
            check("the 3D model row opens Explore on the run's robot: both parts drawn, posed as recorded",
                  xs["kind"] == "robot body" and xs["pose"] == "recorded" and page.evaluate("window.miniview.state().tab") == "explore"
                  and page.evaluate("!document.getElementById('explore').hidden && document.getElementById('inspBody').hidden"), xs)
            call(page, "window.miniview.setTime(2.0)")
            xs = page.evaluate("window.miniview.exploreState()")
            q = xs["poses"]["upper"]["quat"]
            a = shoulder(1.95)
            check("as recorded: the joint's value at the playhead, the part where the kinematics put it (a turn about y)",
                  abs(xs["values"]["shoulder"] - a) < 1e-4 and abs(q[0] - math.cos(a / 2)) < 1e-6 and abs(q[2] - math.sin(a / 2)) < 1e-6
                  and xs["poses"]["upper"]["pos"] == [0, 0, 0.1], (xs["values"], q))
            snap = page.evaluate("window.miniview.exploreSnapshot()")
            check("the body is drawn (the canvas has an image)", isinstance(snap, str) and snap.startswith("data:image/png") and len(snap) > 3000, len(snap or ""))
            shot(page, "explore-recorded")

            page.click('#explore .xrow[data-link="upper"]')
            part = page.evaluate("document.getElementById('xpart').innerText")
            check("a part picked in the list: what moves it, its limits, what it hangs from",
                  page.evaluate("window.miniview.exploreState().selected") == "upper" and "moved by the joint shoulder" in part
                  and "-85.9° … 85.9°" in part and "base" in part, part)
            page.click('#explore [data-act="isolate"]')
            xs = page.evaluate("window.miniview.exploreState()")
            check("isolate: only the picked part", xs["isolated"] == "upper", xs["isolated"])
            page.click('#explore [data-act="focus"]')
            page.click('#explore [data-act="close"]')
            box = page.evaluate("(() => { const r = document.querySelector('#xbody canvas').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            page.mouse.click(*box)
            check("a part picked in the body (a click on the isolated upper arm, focused)", page.evaluate("window.miniview.exploreState().selected") == "upper",
                  page.evaluate("window.miniview.exploreState().selected"))
            page.click('#xall')
            # nothing isolated or hidden: a click picks the part that is in front, where each is
            picked = {}
            for link in ("upper", "base"):
                page.click('#explore [data-act="close"]') if page.query_selector('#explore [data-act="close"]') else None
                xy = page.evaluate(f"window.miniview.exploreScreenOf('{link}')")
                page.mouse.click(*xy)
                picked[link] = page.evaluate("window.miniview.exploreState().selected")
            check("with every part shown, a click on each part picks that part (the one in front)", picked == {"upper": "upper", "base": "base"}, picked)
            call(page, "window.miniview.exploreHide('base')")
            xs = page.evaluate("window.miniview.exploreState()")
            check("hide a part; show all brings everything back", xs["hidden"] == ["base"] and xs["isolated"] is None, xs)
            page.click('#xall')
            check("show all", page.evaluate("window.miniview.exploreState().hidden") == [])

            # by hand: from the recorded pose, a slider per joint
            page.click('#explore [data-pose="hand"]')
            xs = page.evaluate("window.miniview.exploreState()")
            check("by hand starts from the recorded pose", xs["pose"] == "hand" and abs(xs["values"]["shoulder"] - shoulder(1.95)) < 1e-4, xs["values"])
            page.evaluate("(() => { const s = document.querySelector('#explore input[data-hand=\"shoulder\"]'); s.value = '1.2'; s.dispatchEvent(new Event('input', { bubbles: true })); })()")
            xs = page.evaluate("window.miniview.exploreState()")
            check("a slider poses the joint, the playhead does not", abs(xs["values"]["shoulder"] - 1.2) < 1e-9
                  and abs(xs["poses"]["upper"]["quat"][2] - math.sin(0.6)) < 1e-6
                  and page.evaluate("document.querySelector('#explore [data-val=\"shoulder\"]').textContent") == "68.8°", xs["values"])
            call(page, "window.miniview.setTime(4.0)")
            check("by hand ignores the playhead", abs(page.evaluate("window.miniview.exploreState().values.shoulder") - 1.2) < 1e-9)
            check("a joint past its limit is drawn at the limit", page.evaluate("window.miniview.exploreJoint('shoulder', 3)")
                  and abs(page.evaluate("window.miniview.exploreState().poses.upper.quat[2]") - math.sin(0.75)) < 1e-6)
            shot(page, "explore-hand")
            page.click('#xwide')
            check("Expand gives the explorer more room", page.evaluate("document.getElementById('app').classList.contains('xwide')")
                  and page.evaluate("document.getElementById('insp').getBoundingClientRect().width") > 450)
            shot(page, "explore-wide")
            # the main view is narrower now: its legend may wrap, and nothing (the 3D labels) may be drawn over it
            # (pointer events on for everything while it looks: the corner and the labels have none, and elementFromPoint skips those)
            over = page.evaluate("""(() => { const l = document.getElementById('legend'); if (!l || !l.offsetParent) return 'no legend';
              const st = document.createElement('style'); st.textContent = '#app * { pointer-events: auto !important; }'; document.head.append(st);
              // the three.js page: a label where CSS2DRenderer puts them (inside a slot's label layer, a high z-index to sort by
              // depth), under the first legend item, so the check does not depend on where this scene's labels happen to fall
              const layer = document.querySelector('.slot .labels'), first = l.querySelector('span'), probe = document.createElement('div');
              if (layer && first) {
                const lb = layer.getBoundingClientRect(), fb = first.getBoundingClientRect();
                probe.textContent = '8.88'; probe.style.cssText = `position:absolute;z-index:9999;left:${fb.x - lb.x}px;top:${fb.y - lb.y}px;width:${fb.width}px;height:${fb.height}px`;
                layer.append(probe);
              }
              try {
                return [...l.querySelectorAll('span')].map((s) => { const b = s.getBoundingClientRect(); return [s, document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2)]; })
                  .filter(([, e]) => !l.contains(e)).map(([s, e]) => `${s.innerText} under ${e ? e.tagName + '.' + e.className : 'nothing'}`);
              } finally { st.remove(); probe.remove(); } })()""")
            check("the main view's legend is on top: no label is drawn over any of its items", over == [], over)
            page.click('#xwide')

            # the pages' forward kinematics are observatory.kinematics' and MuJoCo's: every link of the duck, for every fixture case
            worst = page.evaluate("""async ([desc, cases]) => {
              const { linkPoses } = await import('/web/shell/robot.js');
              let wp = 0, wq = 0;
              for (const c of cases) {
                const ours = linkPoses(desc, c.joints);
                for (const [n, want] of Object.entries(c.links)) {
                  const g = ours[n];
                  wp = Math.max(wp, ...g.pos.map((v, i) => Math.abs(v - want.pos[i])));
                  wq = Math.max(wq, Math.min(Math.max(...g.quat.map((v, i) => Math.abs(v - want.quat[i]))), Math.max(...g.quat.map((v, i) => Math.abs(v + want.quat[i])))));
                }
              }
              return [wp, wq];
            }""", [duck, fixture["cases"]])
            check(f"the pages' kinematics put every link of the duck where MuJoCo does ({len(fixture['cases'])} cases): within 1e-6 m and 1e-6",
                  worst[0] < 1e-6 and worst[1] < 1e-6, worst)

            # the Robot layer in the main 3D view (three.js page): the body where the truth was, or the belief, its joints at t
            if lib == "three":
                call(page, "window.miniview.setView('3d')")
                call(page, "window.miniview.setTime(2.0)")
                page.wait_for_function("window.miniview.internals.adapter.body()?.drawn === 2", timeout=20000)
                call(page, "window.miniview.setTime(2.0)")
                bd = page.evaluate("window.miniview.internals.adapter.body()")
                a = shoulder(1.95)
                near = lambda x, y, tol=1e-4: all(abs(p - q) < tol for p, q in zip(x, y))  # noqa: E731
                check("the Robot layer in the world frame: the trunk at the truth's whole pose (x, y, z and tilt), the joint at its value at t",
                      bd["visible"] and near(bd["pos"], [1.4, 0.5, 0.2]) and near(bd["quat"], [math.cos(0.1), math.sin(0.1), 0, 0])
                      and near(bd["joint_upper_quat"], [math.cos(a / 2), math.sin(a / 2)]), bd)
                check("with the body shown no marker fills its cylinder; the truth's (the body stands in for it) drops its outline, the belief's keeps it",
                      bd["cylinders"] == {"truth": [False, False], "belief": [False, True]}, bd["cylinders"])
                call(page, "window.miniview.setFrame('map')")
                bd = page.evaluate("window.miniview.internals.adapter.body()")
                check("in the map frame it stands in for the belief's marker: no fill, no outline", bd["cylinders"]["belief"] == [False, False], bd["cylinders"])
                p_, r_ = math.radians(2.0) / 2, math.radians(-1.0) / 2
                want_q = [math.cos(p_) * math.cos(r_), math.cos(p_) * math.sin(r_), math.sin(p_) * math.cos(r_), -math.sin(p_) * math.sin(r_)]
                check("in the map frame (no truth there): at the belief, at the robot's standing height, tilted by the IMU",
                      bd["visible"] and near(bd["pos"], [0.4, 0.0, 0.05]) and near(bd["quat"], want_q), (bd, want_q))
                call(page, "window.miniview.setFrame('world')")
                page.click('#tree .row[data-id="body.model"] .eye')
                off = page.evaluate("window.miniview.internals.adapter.body()")
                page.click('#tree .row[data-id="body.model"] .eye')
                check("the 3D model row's eye hides the body and shows it again", off["visible"] is False and page.evaluate("window.miniview.internals.adapter.body().visible") is True)
                check("with the body hidden, every marker has its cylinder back (fill and outline)", off["cylinders"] == {"truth": [True, True], "belief": [True, True]}, off["cylinders"])
                shot(page, "robot-layer-3d")
                call(page, "window.miniview.setView('top')")

            # the Depth frame and Map kinds on a run that sees and maps, the empty messages on the run that does not, then both on a phone in the light theme
            call(page, f"window.miniview.load('room', '{D_KEY}')")
            depth_checks(page, "dark")
            map_checks(page, "dark")
            empty_checks(page, "dark")
            ctx2, page2, logs2 = page_of(b, base, 390, 800, "light")
            call(page2, f"window.miniview.load('room', '{D_KEY}')")
            check("the phone page is in the light theme (the viewport token is the light one)", token(page2, "--bg-viewport") == [246, 247, 249], token(page2, "--bg-viewport"))
            depth_checks(page2, "phone, light")
            map_checks(page2, "phone, light")
            over = page2.evaluate("[document.documentElement.scrollWidth, innerWidth, window.miniview.exploreView('map').canvas().getBoundingClientRect().right, window.miniview.exploreView('depth').canvas().getBoundingClientRect().right]")
            check("at phone width nothing is wider than the screen (no sideways scroll, both canvases inside it)", over[0] <= over[1] + 1 and over[2] <= over[1] + 1 and over[3] <= over[1] + 1, over)
            errs2 = [m for m in logs2 if "favicon" not in m]
            check("the phone page: no console errors or warnings", not errs2, errs2[:5])
            ctx2.close()

            errs = [m for m in logs if "favicon" not in m]
            check("no console errors or warnings", not errs, errs[:5])
            ctx.close()
    finally:
        httpd.shutdown()
        b.close()

print("EXPLORE-PAGES", "FAIL " + ", ".join(fails) if fails else "PASS")
raise SystemExit(1 if fails else 0)
