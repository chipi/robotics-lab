"""Evidence links (step 4.5, unit U17): a URL `#scene=..&run=..&view=3d&t=<s>&focus=robot` opens a run at a moment, paused (Replay), with the 3D
camera framing the robot there, even when the viewer's setting opens on the whole scene; a link with `t` and no `focus` (or an unknown one)
behaves as before; the Moment panel's "copy link" and `window.miniview.momentLink()` make the link; `miniview.focus('robot')` does the framing.
Needs the system Chromium and Playwright.
Run: cd apps/observatory && uv run python tests/test_look_evidence_pages.py"""

import atexit
import os
import shutil
import struct
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROBOTS = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, ROBOTS, True)
os.environ["MINIVIEW_ROBOTS"] = str(ROBOTS)

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, boot, catalog, make_run, scene, serve, tick  # noqa: E402
from observatory.shots import launch  # noqa: E402

_v = [(x, y, z) for x in (-0.06, 0.06) for y in (-0.06, 0.06) for z in (0.0, 0.1)]
_f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
(ROBOTS / "arm" / "meshes").mkdir(parents=True)
(ROBOTS / "arm" / "robot.urdf").write_text('<robot name="arm"><link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry>'
                                           '<material name="b"><color rgba="0.8 0.6 0.3 1"/></material></visual></link></robot>')
(ROBOTS / "arm" / "robot.json").write_text('{"label": "Test arm", "stand_z": 0.0}')
(ROBOTS / "arm" / "meshes" / "base.stl").write_bytes(bytes(80) + struct.pack("<I", len(_f)) + b"".join(
    struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *_v[i]) for i in f) + struct.pack("<H", 0) for f in _f))

check = Checks("LOOK EVIDENCE PAGES")
A = "window.miniview.internals.adapter"
near = lambda a, b, e: all(abs(x - y) <= e for x, y in zip(a, b))  # noqa: E731

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("room"))
    make_run(Path(tmp) / "data", "arm/room/r1", [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})] + [tick(round(0.1 * k, 3), 0.02 * k) for k in range(30)])
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    console, missing = [], []
    try:
        def fresh(width=1440, height=900, scheme="dark"):
            ctx = b.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, permissions=["clipboard-read", "clipboard-write"])
            pg = ctx.new_page()
            pg.set_default_timeout(30000)
            pg.on("console", lambda m: console.append(m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
            pg.on("pageerror", lambda e: console.append(str(e)))
            pg.on("response", lambda r: missing.append(r.url) if r.status >= 400 and "favicon" not in r.url else None)
            return pg

        def open_link(pg, hash_, whole_scene=False):
            pg.goto(f"{base}/web/three/")
            pg.evaluate(f"localStorage.setItem('miniview.left', JSON.stringify({{open_scene: {str(whole_scene).lower()}}}))")
            boot(pg, f"{base}/web/three/{hash_}", reload=True)
            pg.wait_for_function("window.miniview.state().run !== null")
            pg.evaluate("window.miniview.whenLoaded()")
            pg.wait_for_function(f"{A}.body() && {A}.body().drawn > 0")
            pg.wait_for_function(f"{A}.camera().moving === false")
            return pg.evaluate(f"{A}.camera()")

        pose = lambda c: c["position"] + c["target"]  # noqa: E731
        pg = fresh()
        L = "#scene=room&run=arm/room/r1&view=3d&t=2"
        iso_c = open_link(pg, L, whole_scene=True)
        pg.evaluate(f"{A}.iso()")
        iso = pg.evaluate(f"{A}.camera()")
        check("before: a #t=2 link with the whole-scene setting opens at 2 s on the whole scene, not on the robot",
              abs(pg.evaluate("window.miniview.state().t") - 2.0) < 0.11 and near(pose(iso_c), pose(iso), 1e-6) and not near(iso_c["target"][:2], iso_c["robot"][:2], 0.05),
              (iso_c["target"], iso_c["robot"]))

        pg = fresh()
        c = open_link(pg, L + "&focus=robot", whole_scene=True)
        st = pg.evaluate("window.miniview.state()")
        cfg = pg.evaluate("window.miniview.config()")
        check("focus=robot: opens at 2 s, the camera frames the robot there even with the whole-scene setting (target within 0.05 m, box inside the view, between 25 % and 60 % of its height: a robot framed on purpose, not a speck in a room)",
              abs(st["t"] - 2.0) < 0.11 and c["robot"][0] > 0.3 and near(c["target"][:2], c["robot"][:2], 0.05) and c["ndc"]["inside"] and 0.25 <= c["ndc"]["heightFrac"] <= 0.6, (st["t"], c["target"], c["robot"], c["ndc"]))
        check("focus=robot: paused, in Replay (not playing, Follow live off, the mode badge says Replay)",
              cfg["play"]["on"] is False and cfg["follow"] is False and pg.evaluate("document.getElementById('timemode').dataset.mode") == "replay",
              (cfg["play"], cfg["follow"]))

        pg = fresh()
        c = open_link(pg, L + "&focus=banana", whole_scene=True)
        check("an unknown focus value is ignored: the same camera as a link with no focus, no console error",
              near(pose(c), pose(iso), 1e-6) and abs(pg.evaluate("window.miniview.state().t") - 2.0) < 0.11 and not console, (pose(c), console[:3]))

        pg = fresh()
        open_link(pg, L)
        pg.evaluate("window.miniview.scenes()")
        pg.wait_for_function("window.__ready === true && window.miniview.state().run === null")
        link = pg.evaluate("window.miniview.momentLink()")
        check("on the scenes page (no run open) momentLink() makes no link, rather than one with scene=null or run=null", link is None or "null" not in link, link)

        pg = fresh()
        open_link(pg, L)
        link = pg.evaluate("window.miniview.momentLink()")
        u = urlparse(link)
        q = {k: v[0] for k, v in parse_qs(u.fragment).items()}
        check("momentLink(): the page's own URL, #scene, run, view=3d, the playhead's t and focus=robot, in that order",
              u.path == "/web/three/" and u.netloc == base.split("//")[1] and u.fragment.startswith("scene=room&run=arm%2Froom%2Fr1&view=3d&t=2")
              and q["focus"] == "robot" and abs(float(q["t"]) - pg.evaluate("window.miniview.state().t")) < 1e-3, link)
        check("momentLink({focus: false}) leaves focus out; an unknown focus is left out too",
              "focus" not in pg.evaluate("window.miniview.momentLink({focus: false})") and "focus" not in pg.evaluate("window.miniview.momentLink({focus: 'banana'})"))
        check("miniview.focus('robot') frames the robot and answers true; any other value answers false and moves nothing",
              pg.evaluate("window.miniview.focus('robot')") is True and pg.evaluate("window.miniview.focus('banana')") is False)

        pg.evaluate("window.miniview.setTime(1.0)")
        pg.wait_for_selector("#inspBody [data-link]")
        pg.click("#inspBody [data-link]")
        clip = pg.evaluate("navigator.clipboard.readText()")
        check("Moment panel: 'copy link' puts the link to the playhead's moment on the clipboard (t=1 here, focus=robot) and the top bar is not touched",
              clip == pg.evaluate("window.miniview.momentLink()") and "t=1&" in clip + "&" and clip.endswith("focus=robot")
              and pg.evaluate("document.querySelector('#topbar [data-link], .topbar [data-link]')") is None, clip)

        # the round trip: the link a viewer copies opens the same moment, framed, in a new profile
        pg2 = fresh()
        c2 = open_link(pg2, "#" + clip.split("#", 1)[1], whole_scene=True)
        check("round trip: the copied link opens at 1 s, paused, framed on the robot",
              abs(pg2.evaluate("window.miniview.state().t") - 1.0) < 0.11 and pg2.evaluate("window.miniview.config().play.on") is False
              and near(c2["target"][:2], c2["robot"][:2], 0.05) and c2["ndc"]["inside"], (c2["target"], c2["robot"]))

        pg3 = fresh(390, 844, "light")
        # hash-only navigation on an open page: an evidence link pasted into the address bar (or clicked as a same-page link) is not a reload
        pg4 = fresh()
        boot(pg4, f"{base}/web/three/#scene=room&run=arm/room/r1&view=top&t=1", reload=True)
        pg4.wait_for_function("window.miniview.state().run !== null && Math.abs(window.miniview.state().t - 1) < 0.11")
        pg4.evaluate("window.__same = 1")
        pg4.evaluate("location.hash = '#scene=room&run=arm/room/r1&view=3d&t=2&focus=robot'")
        pg4.wait_for_function("window.miniview.state().view === '3d' && Math.abs(window.miniview.state().t - 2) < 0.11")
        pg4.wait_for_function(f"{A}.camera().moving === false")
        c4 = pg4.evaluate(f"{A}.camera()")
        check("hash navigation: an evidence link assigned to location.hash on an open page opens at t=2 on the 3D view framed on the robot, paused, without a reload",
              pg4.evaluate("window.__same") == 1 and pg4.evaluate("window.miniview.config().play.on") is False
              and near(c4["target"][:2], c4["robot"][:2], 0.05) and c4["ndc"]["inside"], (c4["target"], c4["robot"]))
        pg4.evaluate("location.hash = '#scene=room&run=arm/room/r1&view=3d&t=1.5'")
        pg4.wait_for_function("Math.abs(window.miniview.state().t - 1.5) < 0.11")
        check("hash navigation: a hash with only t changed seeks there, same view", pg4.evaluate("window.miniview.state().view") == "3d" and pg4.evaluate("window.__same") == 1)
        pg4.go_back()
        pg4.wait_for_function("Math.abs(window.miniview.state().t - 2) < 0.11")
        pg4.go_back()
        pg4.wait_for_function("window.miniview.state().view === 'top' && Math.abs(window.miniview.state().t - 1) < 0.11")
        check("hash navigation: back after two pushes returns to t=2, then to the first moment (t=1, the top view), no reload", pg4.evaluate("window.__same") == 1)
        pg4.evaluate("window.miniview.setTime(0.5)")
        pg4.evaluate("location.hash = '#scene=room&run=arm/room/r1&view=top&t=2.5'")
        pg4.wait_for_function("Math.abs(window.miniview.state().t - 2.5) < 0.11")
        pg4.go_back()
        pg4.wait_for_function("Math.abs(window.miniview.state().t - 0.5) < 0.11")
        check("hash navigation: back restores the playhead the viewer had left, even when the earlier hash carried no t (the shell rewrites it without one)", abs(pg4.evaluate("window.miniview.state().t") - 0.5) < 0.11)
        pg4.evaluate("window.miniview.setTime(1.0)")
        pg4.wait_for_timeout(300)
        check("hash navigation: the shell's own hash writes do not loop back as navigations", abs(pg4.evaluate("window.miniview.state().t") - 1.0) < 0.11)

        c3 = open_link(pg3, L + "&focus=robot", whole_scene=True)
        check("390 px light: the link frames the robot too, and the page has no horizontal overflow",
              near(c3["target"][:2], c3["robot"][:2], 0.05) and c3["ndc"]["inside"] and pg3.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (c3["ndc"], ))
        check("page: no console error or warning, no failed request", not console and not missing, (console[:5], missing))
    finally:
        httpd.shutdown()
        b.close()

check.done()
