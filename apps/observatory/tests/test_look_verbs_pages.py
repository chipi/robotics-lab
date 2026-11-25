"""The Observatory's palette verbs (step 4.5, U18) in headless Chromium: Ctrl/Cmd+K and a viewport-header button open the command palette, which is
loaded only then (no palette request on first paint) and never from a key typed in an input; `/` keeps its search job. The verbs: the views and frame,
the 3D camera (presets, fit scene, fit robot, follow modes, only on the 3D view), time (play and pause, return to live, next and previous event by
kind, start and end), panels and layouts (web/shell/layout.js `act`), theme, open a scene or a run from the shell's lists, copy the link to this
moment, overlays and streams. The list is rebuilt from the state when it is shown; an error reaches the viewer as a visible message; no verb is
dangerous and none acts on a robot (the Observatory has no STOP).
Run: cd apps/observatory && uv run --frozen python tests/test_look_verbs_pages.py"""

import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, boot, catalog, make_run, scene, serve, tick
from observatory.shots import launch

check = Checks("LOOK VERBS PAGES")
SHOTS = Path(os.environ["U18_SHOTS"]) if os.environ.get("U18_SHOTS") else None

HEAD = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]


def ev(t, kind):
    return (t, "event", {"kind": kind, "text": f"{kind} at {t}"})


def ticks_between(a, b):
    return [tick(round(1.0 + 0.1 * i, 3), 0.05 * i) for i in range(a, b)]


def inorder(rows):
    return sorted(rows, key=lambda r: r[0])


marks = [ev(1.5, "cliff_stop"), ev(2.0, "reached"), ev(2.5, "tight_pivot"), ev(3.0, "cliff_stop"), ev(3.5, "reached")]

IDS = "[...document.querySelectorAll('.pal-row')].map((r) => r.dataset.verb)"
TITLES = "[...document.querySelectorAll('.pal-row .pal-title')].map((r) => r.textContent)"
OPEN = "!!document.querySelector('.pal') && !document.querySelector('.pal').hidden"
MSG = "(() => { const m = document.getElementById('verbmsg'); return m && !m.hidden ? {text: m.textContent, role: m.getAttribute('role')} : null; })()"

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(scene("room"))
    cat.put_scene(scene("hall"))
    make_run(data, "duck/room/replay1", HEAD + inorder(ticks_between(0, 40) + marks) + [(5.0, "end", {"verdict": "ended"})])
    make_run(data, "duck/room/replay2", HEAD + ticks_between(0, 10) + [(2.5, "end", {"verdict": "ended"})])
    make_run(data, "duck/hall/h1", HEAD + ticks_between(0, 10) + [(2.5, "end", {"verdict": "ended"})])
    rec = make_run(data, "duck/room/live1", HEAD + inorder(ticks_between(0, 20) + marks[:2]), close=False)
    httpd, base = serve(cat)
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    errs, reqs = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("request", lambda r: reqs.append(r.url))

    def ready():
        pg.wait_for_function("window.__ready === true")

    def load(key, scene_id="room"):
        pg.evaluate(f"window.miniview.load('{scene_id}', '{key}')")
        ready()

    def open_pal():
        pg.evaluate("document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+k")
        pg.wait_for_function(OPEN)

    def ids():
        return pg.evaluate(IDS)

    def run_verb(vid):
        open_pal()
        pg.click(f'.pal-row[data-verb="{vid}"]')
        pg.wait_for_function(f"!({OPEN})")
        ready()

    def close_pal():
        if pg.evaluate(OPEN):
            pg.keyboard.press("Escape")

    boot(pg, base + "/web/three/")
    load("duck/room/replay1")

    # ---- the opener, and loading only on first use
    check("no palette module or stylesheet is requested by the first paint", not any("/palette/" in u or "verbs.js" in u for u in reqs), [u for u in reqs if "palette" in u or "verbs" in u])
    check("a palette button sits in the viewport header, not in the top bar",
          pg.evaluate("!!document.querySelector('.vhead #paletteBtn') && !document.querySelector('#topbar #paletteBtn')"))
    check("the button names the palette and its shortcut for a screen reader",
          pg.evaluate("(() => { const b = document.getElementById('paletteBtn'); return /command palette/i.test(b.getAttribute('aria-label')) && /Control\\+K/.test(b.getAttribute('aria-keyshortcuts') || ''); })()"))
    pg.focus("#q")
    pg.keyboard.press("Control+k")
    check("Ctrl+K typed in the search input does not open it, and loads nothing", not pg.evaluate("!!document.querySelector('.pal')") and not any("verbs.js" in u for u in reqs))
    pg.keyboard.press("/")
    check("`/` keeps its job: the stream search takes the focus", pg.evaluate("document.activeElement.id") == "q")
    pg.evaluate("document.activeElement.blur(); window.miniview.scenes()")
    ready()
    pg.keyboard.press("Control+k")
    pg.wait_for_function(OPEN)
    check("Ctrl+K from the page opens it, with the focus in its input", pg.evaluate("document.activeElement.classList.contains('pal-input')"))
    check("the module and its stylesheet were requested then", any("verbs.js" in u for u in reqs) and any("palette.css" in u for u in reqs))
    check("with no run open the list offers scenes and no time, camera or link verbs", "scene.open.room" in ids() and not any(i.startswith(("time.", "cam.", "link.")) for i in ids()), ids())
    check("every verb is plain: none is dangerous, none is a STOP or acts on a robot",
          pg.evaluate("[...document.querySelectorAll('.pal-row')].every((r) => r.dataset.danger === 'none' && !/stop|take|drive|goal|halt/i.test(r.textContent))"), ids())
    pg.keyboard.press("Escape")
    check("Esc closes it", not pg.evaluate(OPEN))
    load("duck/room/replay1")
    pg.click("#paletteBtn")
    pg.wait_for_function(OPEN)
    check("the button opens it too", True)
    pg.keyboard.press("Escape")
    pg.focus("#q")
    pg.keyboard.press("Meta+k")
    check("Cmd+K typed in an input does not open it either", not pg.evaluate(OPEN))
    pg.evaluate("document.activeElement.blur()")
    pg.keyboard.press("Meta+k")
    pg.wait_for_function(OPEN)
    check("Cmd+K opens it", True)
    pg.keyboard.press("Escape")

    # ---- open a scene or a run
    open_pal()
    pg.keyboard.type("hall")
    check("typing finds a scene by name and its run", "scene.open.hall" in ids() and "run.open.duck/hall/h1" in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("run.open.duck/room/replay1")
    check("Open run loads that run", pg.evaluate("window.miniview.state().run") == "duck/room/replay1", pg.evaluate("window.miniview.state().run"))
    run_verb("scene.open.hall")
    check("Open scene loads the scene's run", pg.evaluate("window.miniview.state().scene") == "hall", pg.evaluate("window.miniview.state().scene"))
    load("duck/room/replay1")

    # ---- views and frame
    open_pal()
    check("the views the page offers are verbs (Top, Three, 3D, Eye, Chase), the current one is left out",
          {"view.three", "view.3d", "view.eye", "view.chase"} <= set(ids()) and "view.top" not in ids(), ids())
    check("the frame verb offers the other one", "frame.map" in ids() and "frame.world" not in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("view.three")
    check("View: Three sets the view", pg.evaluate("window.miniview.state().view") == "three")
    run_verb("view.chase")
    check("View: Chase sets the chase camera", pg.evaluate("window.miniview.state().view") == "chase")
    open_pal()
    check("in the chase view the map frame is not offered (the page places that camera in the world)", "frame.map" not in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("view.top")
    run_verb("frame.map")
    check("Frame: Map sets the map frame", pg.evaluate("window.miniview.state().frame") == "map")
    run_verb("frame.world")
    check("Frame: World sets it back", pg.evaluate("window.miniview.state().frame") == "world")
    pg.evaluate("window.miniview.setView('top')")

    # ---- the 3D camera: only on the 3D view
    open_pal()
    check("no camera verb on the top view", not any(i.startswith("cam.") for i in ids()), ids())
    pg.keyboard.press("Escape")
    run_verb("view.3d")
    ready()
    open_pal()
    cam_ids = [i for i in ids() if i.startswith("cam.")]
    want = {"cam.view.iso", "cam.view.top", "cam.view.front", "cam.view.side", "cam.fit-scene", "cam.fit-robot",
            "cam.follow.off", "cam.follow.position", "cam.follow.heading", "cam.follow.pose"}
    check("on the 3D view: presets, fit scene, fit robot and the follow modes are verbs", want <= set(cam_ids), cam_ids)
    pg.keyboard.press("Escape")
    CAM = "window.miniview.internals.adapter.camera()"

    def camera():
        pg.wait_for_function(f"!({CAM}).moving")
        return pg.evaluate(CAM)

    c0 = camera()
    run_verb("cam.view.top")
    c1 = camera()
    check("Camera: Top moves the 3D camera (it looks down)", c1["position"] != c0["position"] and abs(c1["position"][2]) > abs(c1["position"][0]) * 3, (c0["position"], c1["position"]))
    run_verb("cam.fit-scene")
    c2 = camera()
    run_verb("cam.fit-robot")
    c3 = camera()
    check("Fit scene and Fit robot frame different things: the robot's box fills more of the view after Fit robot",
          c3["ndc"]["areaFrac"] > c2["ndc"]["areaFrac"], (c2["ndc"]["areaFrac"], c3["ndc"]["areaFrac"]))
    run_verb("cam.follow.heading")
    check("Camera follow: Heading sets the follow mode", pg.evaluate(CAM)["follow"] == "heading", pg.evaluate(CAM)["follow"])
    run_verb("cam.follow.off")
    check("Camera follow: Off clears it", pg.evaluate(CAM)["follow"] == "off")
    run_verb("view.fit")
    c4 = camera()
    check("View: Fit puts the camera back where the view starts", c4["position"] == c0["position"] and c4["position"] != c3["position"], (c0["position"], c3["position"], c4["position"]))
    # a verb that presses a control the page no longer has says so, in the message line, instead of doing nothing
    open_pal()
    pg.evaluate("document.querySelector('#camCtl [data-cam=\"fit-scene\"]').remove()")
    pg.click('.pal-row[data-verb="cam.fit-scene"]')
    pg.wait_for_function(MSG + " !== null")
    m = pg.evaluate(MSG)
    check("a camera verb whose button is gone reports it as an alert", m and m["role"] == "alert" and "not on the page" in m["text"], m)
    pg.evaluate("window.miniview.setView('top')")

    # ---- time
    pg.evaluate("window.miniview.setTime(1.0)")
    open_pal()
    check("with a run open: Play, jumps (any and by kind), start and end are verbs, and no Pause while paused",
          {"time.play", "time.next", "time.prev", "time.next.cliff_stop", "time.prev.reached", "time.next.tight_pivot", "time.start", "time.end"} <= set(ids()) and "time.pause" not in ids(), ids())
    check("no 'return to live' on a finished run", "time.live" not in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("time.play")
    pg.wait_for_function("window.miniview.internals.M.play.on === true")
    open_pal()
    check("the list is rebuilt from the state: while playing it offers Pause and not Play", "time.pause" in ids() and "time.play" not in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("time.pause")
    pg.wait_for_function("window.miniview.internals.M.play.on === false")
    check("Pause pauses", True)
    pg.evaluate("window.miniview.setTime(1.0)")
    run_verb("time.next.reached")
    check("Next event of a kind lands on it", abs(pg.evaluate("window.miniview.state().t") - 2.0) < 1e-6, pg.evaluate("window.miniview.state().t"))
    run_verb("time.next")
    check("Next event (any) steps every kind", abs(pg.evaluate("window.miniview.state().t") - 2.5) < 1e-6, pg.evaluate("window.miniview.state().t"))
    run_verb("time.prev.cliff_stop")
    check("Previous event of a kind goes back to it", abs(pg.evaluate("window.miniview.state().t") - 1.5) < 1e-6, pg.evaluate("window.miniview.state().t"))
    run_verb("time.end")
    t1 = pg.evaluate("window.miniview.state().t_range[1]")
    check("Seek to the end", abs(pg.evaluate("window.miniview.state().t") - t1) < 1e-6)
    run_verb("time.start")
    check("Seek to the start", abs(pg.evaluate("window.miniview.state().t") - pg.evaluate("window.miniview.state().t_range[0]")) < 1e-6)

    # ---- return to live
    load("duck/room/live1")
    pg.evaluate("window.miniview.setTime(1.2)")
    open_pal()
    check("on a live run left behind, 'return to live' is a verb", "time.live" in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("time.live")
    pg.wait_for_function("document.getElementById('timemode').dataset.mode === 'live'")
    check("Return to live follows the edge again", pg.evaluate("window.miniview.state().follow") is True)
    open_pal()
    check("at the live edge it is no longer offered", "time.live" not in ids(), ids())
    pg.keyboard.press("Escape")
    load("duck/room/replay1")

    # ---- panels and layouts
    open_pal()
    check("panels: each panel can be hidden, the streams and properties folded",
          {"panel.hide.left", "panel.hide.right", "panel.hide.streams", "panel.hide.props", "panel.fold.streams", "panel.fold.props", "layout.save", "layout.reset"} <= set(ids()), ids())
    pg.keyboard.press("Escape")
    run_verb("panel.hide.left")
    check("Hide panel: Left column hides it", pg.evaluate("getComputedStyle(document.getElementById('left')).display") == "none")
    open_pal()
    check("the list follows the layout: Show replaces Hide", "panel.show.left" in ids() and "panel.hide.left" not in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("panel.show.left")
    check("Show panel brings it back", pg.evaluate("getComputedStyle(document.getElementById('left')).display") != "none")
    run_verb("panel.fold.props")
    check("Fold panel: Properties", pg.evaluate("document.getElementById('app').classList.contains('lay-fold-props')"))
    run_verb("panel.unfold.props")
    check("Unfold panel: Properties", not pg.evaluate("document.getElementById('app').classList.contains('lay-fold-props')"))
    run_verb("panel.hide.right")
    run_verb("layout.save")
    check("Save layout names it and says so", (pg.evaluate(MSG) or {}).get("text", "").startswith("Saved as Layout 1"), pg.evaluate(MSG))
    names = pg.evaluate("Object.keys(JSON.parse(localStorage.getItem('rl.layouts.observatory')).layouts)")
    check("... the store holds it (rl.layouts.observatory)", "Layout 1" in names, names)
    run_verb("layout.reset")
    check("Reset layout to default restores the panel", pg.evaluate("!document.getElementById('app').classList.contains('lay-no-right')"))
    open_pal()
    check("a saved layout is a verb", "layout.load.Layout 1" in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb("layout.load.Layout 1")
    check("Load layout applies it (the inspector is hidden again)", pg.evaluate("document.getElementById('app').classList.contains('lay-no-right')"))
    run_verb("layout.reset")

    # ---- theme
    open_pal()
    check("theme verb names the other theme", "Switch to light theme" in pg.evaluate(TITLES), pg.evaluate(TITLES))
    pg.keyboard.press("Escape")
    run_verb("theme.toggle")
    check("Switch theme flips it", pg.evaluate("document.documentElement.dataset.theme") == "light")
    open_pal()
    check("... and the verb now offers dark", "Switch to dark theme" in pg.evaluate(TITLES))
    pg.keyboard.press("Escape")
    run_verb("theme.toggle")
    check("... and back", pg.evaluate("document.documentElement.dataset.theme") == "dark")

    # ---- overlays and streams
    open_pal()
    check("overlay verbs say what they do now", "Hide the coordinate system and grid" in pg.evaluate(TITLES), pg.evaluate(TITLES))
    ov_ids = [i for i in ids() if i.startswith("overlay.")]
    check("overlays: coords, gizmo, legend and the floor are verbs", {"overlay.coords", "overlay.gizmo", "overlay.legend"} <= set(ov_ids), ov_ids)
    pg.keyboard.press("Escape")
    before = pg.evaluate("window.miniview.config().overlays.coords")
    run_verb("overlay.coords")
    check("an overlay verb toggles the overlay", pg.evaluate("window.miniview.config().overlays.coords") == (not before))
    run_verb("overlay.coords")
    open_pal()
    check("the belief to truth line is on by default and the verb says what it does now", "Hide the belief to truth line" in pg.evaluate(TITLES), pg.evaluate(TITLES))
    pg.keyboard.press("Escape")
    run_verb("overlay.rel")
    check("... and it turns the line off", pg.evaluate("window.miniview.internals.M.rel.belief_truth") is False)
    open_pal()
    check("... then offers to show it", "Show the belief to truth line" in pg.evaluate(TITLES), pg.evaluate(TITLES))
    pg.keyboard.press("Escape")
    run_verb("overlay.rel")
    check("... and back on again", pg.evaluate("window.miniview.internals.M.rel.belief_truth") is True)
    open_pal()
    st = [i for i in ids() if i.startswith("stream.")]
    check("streams of the run are verbs", len(st) >= 2 and any(i.startswith("stream.hide.") for i in st), st)
    pg.keyboard.press("Escape")
    sid = st[0].split(".", 2)[2] if st else ""
    run_verb(st[0])
    check("Hide stream turns it off", pg.evaluate("(id) => window.miniview.config().on[id]", sid) is False, sid)
    open_pal()
    check("... and the list now offers to show it", f"stream.show.{sid}" in ids(), ids())
    pg.keyboard.press("Escape")
    run_verb(f"stream.show.{sid}")
    check("Show stream turns it on", pg.evaluate("(id) => window.miniview.config().on[id]", sid) is not False)

    # ---- the link to this moment
    pg.evaluate("window.miniview.setTime(2.0)")
    run_verb("link.copy")
    clip = pg.evaluate("navigator.clipboard.readText()")
    check("Copy link puts the evidence link for this moment on the clipboard", clip == pg.evaluate("window.miniview.momentLink()") and "run=duck%2Froom%2Freplay1" in clip and "t=2" in clip, clip)
    check("... and says it was copied", "copied" in (pg.evaluate(MSG) or {}).get("text", "").lower(), pg.evaluate(MSG))
    pg.evaluate("(() => { navigator.clipboard.writeText = () => Promise.reject(new Error('denied')); })()")
    run_verb("link.copy")
    m = pg.evaluate(MSG)
    check("a refused clipboard is a visible alert that carries the link", m and m["role"] == "alert" and "#scene=" in m["text"], m)

    # the palette lists its verbs when it opens; a run closed behind it leaves link.copy with nothing to link
    open_pal()
    pg.evaluate("window.miniview.scenes()")
    pg.click('.pal-row[data-verb="link.copy"]')
    pg.wait_for_function(MSG + " !== null")
    m = pg.evaluate(MSG)
    check("Copy link with no run open is an alert that says so", m and m["role"] == "alert" and "no run open" in m["text"], m)
    run_verb("nav.scenes")
    check("Go to all scenes and runs closes the run and shows the list", pg.evaluate("window.miniview.internals.M.runId") is None and pg.evaluate("document.getElementById('app').classList.contains('scenes')"))
    load("duck/room/replay1")

    # ---- an error is shown, not only logged
    pg.evaluate("(() => { window.miniview.setView = () => { throw new Error('the view broke'); }; })()")
    run_verb("view.three")
    m = pg.evaluate(MSG)
    check("a verb that throws shows its message to the viewer (role alert), not only in the console", m and m["role"] == "alert" and "the view broke" in m["text"], m)
    pg.wait_for_function("document.getElementById('verbmsg').hidden", timeout=12000)
    check("the message goes away by itself", True)

    # ---- the opened palette on a phone, light
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.evaluate("localStorage.removeItem('rl.theme'); localStorage.removeItem('miniview.theme')")
    pg.emulate_media(color_scheme="light")
    pg.reload()
    pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.miniview.load('room', 'duck/room/replay1')")
    ready()
    bx = pg.evaluate("(() => { const r = document.getElementById('paletteBtn').getBoundingClientRect(), l = document.getElementById('layBtn').getBoundingClientRect(); return [r.width, r.height, r.left, r.right, l.width, l.height]; })()")
    check("on a phone the button is on screen and the size of the header's other icon buttons", bx[2] >= 0 and bx[3] <= 390 and abs(bx[0] - bx[4]) < 1 and abs(bx[1] - bx[5]) < 1, bx)
    check("(setup) the phone shot is on the light theme", pg.evaluate("document.documentElement.dataset.theme") == "light")
    pg.click("#paletteBtn")
    pg.wait_for_function(OPEN)
    box = pg.evaluate("(() => { const r = document.querySelector('.pal-box').getBoundingClientRect(); return [r.left, r.right, r.bottom]; })()")
    check("on a phone the palette fits the width and the height", box[0] >= 0 and box[1] <= 390 and box[2] <= 844, box)
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(SHOTS / "observatory-palette-light-390.png"))
    pg.keyboard.press("Escape")
    check("on a phone the page does not scroll sideways", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))

    # ---- the shot on the desktop, dark
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.evaluate("localStorage.removeItem('rl.theme'); localStorage.removeItem('miniview.theme')")
    pg.emulate_media(color_scheme="dark")
    pg.reload()
    pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.miniview.load('room', 'duck/room/replay1')")
    ready()
    pg.evaluate("window.miniview.setView('3d')")
    ready()
    open_pal()
    if SHOTS:
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(SHOTS / "observatory-palette-dark-1440.png"))
    pg.keyboard.press("Escape")

    check("no page error", not errs, errs)
    b.close()
    httpd.shutdown()
check.done()
