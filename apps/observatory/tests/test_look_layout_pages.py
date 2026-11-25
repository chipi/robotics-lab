"""The Observatory's panels and layouts (step 4.5, U16) in headless Chromium: the Layout button in the viewport header (not the top bar) opens Mission
Control's menu at compact density; the left column, the streams, the properties and the inspector can be hidden, the streams and properties folded, the two
columns resized and the splitter moved (by pointer or arrow keys); the arrangement is saved as named layouts in rl.layouts.observatory (save, load,
delete, reset, export and import as JSON, a refused import leaving what was saved); a reload keeps it; the legacy miniview.left is read once; the sections
and the joint-angle switch the shell kept there now live in the layout and follow a loaded one; the menu is keyboard-operable and the shell's keys do not
reach it; reduced motion and a phone width are honoured.
Run: cd apps/observatory && uv run python tests/test_look_layout_pages.py"""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, TMP, True)
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, boot, catalog, make_run, scene, serve  # noqa: E402
from observatory.shots import launch  # noqa: E402

check = Checks("LOOK LAYOUT PAGES")
SHOTS = Path(os.environ["U16_SHOTS"]) if os.environ.get("U16_SHOTS") else None      # a folder to leave screenshots in

ARM = """<robot name="arm">
  <link name="base"/><link name="upper"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
arm.mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm"}')

SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "load", "kind": "number", "unit": "A"}]
records = [(round(0.1 * k, 3), "signals", {"values": {"joint_shoulder": round(0.04 * k, 4), "load": 0.3 + 0.01 * k}, "t_src": round(0.1 * k, 3)}) for k in range(30)]
records.append((3.1, "end", {"verdict": "recorded"}))

data = TMP / "data"
cat = catalog(data)
cat.put_scene(scene("room"))
make_run(data, "arm/room/r1", records, signals=SIGS)
cat.scan()
httpd, base = serve(cat, follow=False)

KEYS = "[localStorage.getItem('rl.layouts.observatory'), localStorage.getItem('rl.layout.current.observatory')]"
LAYOUTS = "JSON.parse(localStorage.getItem('rl.layouts.observatory') || 'null')"


def box(pg, sel):
    return pg.evaluate(f"(() => {{ const e = document.querySelector('{sel}'); if (!e) return null; const r = e.getBoundingClientRect(); const c = getComputedStyle(e); return {{x: r.x, y: r.y, w: r.width, h: r.height, display: c.display}}; }})()")


def opened(pg, w=1440, h=900, pre=None):
    pg.set_viewport_size({"width": w, "height": h})
    boot(pg, base + "/web/three/")
    if pre:
        pg.evaluate(pre)
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true")


def menu(pg, on=True):
    if pg.evaluate("document.querySelector('#lay-menu').hidden") == on:
        pg.click("#layBtn")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    opened(pg)

    # ---- the button and the menu
    check("a Layout button sits in the viewport header, not the top bar",
          pg.evaluate("!!document.querySelector('.vhead #layBtn') && !document.querySelector('#topbar #layBtn')"))
    check("the menu is closed to begin with, and the button says so", pg.evaluate("document.querySelector('#lay-menu').hidden && document.querySelector('#layBtn').getAttribute('aria-expanded') === 'false'"))
    pg.click("#layBtn")
    check("a click opens the menu, the button says so, and the focus moves into it",
          pg.evaluate("!document.querySelector('#lay-menu').hidden && document.querySelector('#layBtn').getAttribute('aria-expanded') === 'true' && document.querySelector('#lay-menu').contains(document.activeElement)"))
    m = box(pg, "#lay-menu")
    check("the menu fits the window", m and m["x"] >= 0 and m["y"] >= 0 and m["x"] + m["w"] <= 1440 and m["y"] + m["h"] <= 900, m)
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(SHOTS / "observatory-layout-menu-dark-1440.png"))
    pg.keyboard.press("Escape")
    check("Escape closes the menu and gives the focus back to the button", pg.evaluate("document.querySelector('#lay-menu').hidden && document.activeElement.id === 'layBtn'"))
    check("nothing is stored until a viewer changes something", pg.evaluate(KEYS) == [None, None], pg.evaluate(KEYS))

    # ---- hide, fold, resize
    left0 = box(pg, "#left")
    view0 = box(pg, "#stage")
    check("the left column is 280 px and the inspector 280 px by default", left0 and abs(left0["w"] - 280) < 2 and abs(box(pg, "#insp")["w"] - 280) < 2, (left0, box(pg, "#insp")))
    menu(pg)
    pg.uncheck("#lay-show-left")
    check("hiding the left column removes it and the viewport takes its room", box(pg, "#left")["display"] == "none" and box(pg, "#stage")["w"] > view0["w"] + 270, (box(pg, "#left"), box(pg, "#stage"), view0))
    check("the timeline keeps its transport (its first column is the left width)", box(pg, "#tl .transport")["w"] > 200, box(pg, "#tl .transport"))
    saved = pg.evaluate(LAYOUTS)
    cur = pg.evaluate("localStorage.getItem('rl.layout.current.observatory')")
    check("the change is saved as the default layout, which is now the one in use", cur == "default" and saved["layouts"]["default"]["panels"]["left"] is False, [cur, saved])
    pg.check("#lay-show-left")
    pg.uncheck("#lay-show-right")
    check("hiding the inspector removes it and the viewport takes its room", box(pg, "#insp")["display"] == "none" and box(pg, "#stage")["w"] > view0["w"] + 270, (box(pg, "#insp"), box(pg, "#stage")))
    pg.check("#lay-show-right")
    pg.uncheck("#lay-show-streams")
    check("hiding the streams leaves the properties the whole column", box(pg, ".left > .region")["display"] == "none" and box(pg, "#props")["h"] > 0.9 * box(pg, "#left")["h"], (box(pg, "#tree"), box(pg, "#props")))
    pg.check("#lay-show-streams")
    pg.uncheck("#lay-show-props")
    check("hiding the properties leaves the streams the whole column", box(pg, "#props")["display"] == "none" and box(pg, ".left > .region")["h"] > 0.8 * box(pg, "#left")["h"], (box(pg, "#props"), box(pg, "#tree")))
    pg.check("#lay-show-props")
    pg.check("#lay-fold-streams")
    check("folding the streams leaves their header only and gives the rest to the properties", box(pg, "#tree")["display"] == "none" and box(pg, "#left .rhead")["h"] > 0 and box(pg, "#props")["h"] > 0.8 * box(pg, "#left")["h"], (box(pg, "#tree"), box(pg, "#props")))
    pg.uncheck("#lay-fold-streams")
    pg.check("#lay-fold-props")
    check("folding the properties leaves a strip under the streams", box(pg, "#props")["h"] < 80 and box(pg, ".left > .region")["h"] > 0.6 * box(pg, "#left")["h"], (box(pg, "#props"), box(pg, "#tree")))
    pg.uncheck("#lay-fold-props")

    pg.fill("#lay-w-left", "360")
    pg.dispatch_event("#lay-w-left", "input"); pg.dispatch_event("#lay-w-left", "change")
    pg.fill("#lay-w-right", "400")
    pg.dispatch_event("#lay-w-right", "input"); pg.dispatch_event("#lay-w-right", "change")
    check("the left column and the inspector take the widths the sliders say", abs(box(pg, "#left")["w"] - 360) < 2 and abs(box(pg, "#insp")["w"] - 400) < 2, (box(pg, "#left"), box(pg, "#insp")))
    check("the timeline's header column follows the left width", abs(box(pg, "#tl .transport")["w"] - 360) < 2, box(pg, "#tl .transport"))
    check("the widths are saved", pg.evaluate(LAYOUTS)["layouts"]["default"]["widths"] == {"left": 360, "right": 400}, pg.evaluate(LAYOUTS))
    pg.keyboard.press("Escape")

    # ---- the splitter
    h0 = box(pg, "#left .region")["h"]
    pg.focus("#split")
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowDown")
    h1 = box(pg, "#left .region")["h"]
    check("the splitter is a focusable separator the arrow keys move", pg.evaluate("document.querySelector('#split').getAttribute('role')") == "separator" and h1 > h0 + 40, (h0, h1))
    check("the splitter's place is saved in the layout", abs(pg.evaluate(LAYOUTS)["layouts"]["default"]["panels"]["open"]["split"] - h1) < 2, pg.evaluate(LAYOUTS))
    sp = box(pg, "#split")
    pg.mouse.move(sp["x"] + 100, sp["y"] + 2); pg.mouse.down(); pg.mouse.move(sp["x"] + 100, sp["y"] - 80, steps=4); pg.mouse.up()
    h2 = box(pg, "#left .region")["h"]
    check("dragging the splitter moves it and the layout keeps where it was left", h2 < h1 - 40 and abs(pg.evaluate(LAYOUTS)["layouts"]["default"]["panels"]["open"]["split"] - h2) < 2, (h1, h2, pg.evaluate(LAYOUTS)))

    # ---- a reload keeps it
    pg.reload()
    pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    check("a reload keeps the widths and the splitter", abs(box(pg, "#left")["w"] - 360) < 2 and abs(box(pg, "#insp")["w"] - 400) < 2 and abs(box(pg, "#left .region")["h"] - h2) < 2,
          (box(pg, "#left"), box(pg, "#insp"), box(pg, "#left .region"), h2))

    # ---- named layouts: save, load, delete, reset
    menu(pg)
    pg.fill("#lay-name", "wide")
    pg.click("#lay-save")
    check("Save as keeps the arrangement under a name and uses it", pg.evaluate(KEYS)[1] == "wide" and "wide" in pg.evaluate(LAYOUTS)["layouts"], pg.evaluate(KEYS))
    check("the list offers the default layout and the saved one", pg.evaluate("[...document.querySelectorAll('#lay-list option')].map((o) => o.textContent)") == ["Default layout", "wide"])
    pg.click("#lay-reset")
    check("Reset puts the defaults back: the columns are 280 px, the splitter is the shell's again",
          abs(box(pg, "#left")["w"] - 280) < 2 and abs(box(pg, "#insp")["w"] - 280) < 2 and pg.evaluate("document.querySelector('#left').style.getPropertyValue('--split')") == "", (box(pg, "#left"), box(pg, "#insp")))
    check("... and every panel is shown", pg.evaluate("[...document.querySelectorAll('#lay-menu input[type=checkbox]')].filter((c) => c.id.startsWith('lay-show')).every((c) => c.checked)")
          and pg.evaluate("[...document.querySelectorAll('#lay-menu input[type=checkbox]')].filter((c) => c.id.startsWith('lay-fold')).every((c) => !c.checked)"))
    check("a reset leaves the saved layouts alone", "wide" in pg.evaluate(LAYOUTS)["layouts"])
    pg.select_option("#lay-list", "wide")
    check("choosing a saved layout loads it", abs(box(pg, "#left")["w"] - 360) < 2 and pg.evaluate(KEYS)[1] == "wide", box(pg, "#left"))
    pg.select_option("#lay-list", "")
    check("choosing the default layout resets", abs(box(pg, "#left")["w"] - 280) < 2)
    pg.select_option("#lay-list", "wide")
    pg.click("#lay-delete")
    check("Delete removes the layout in use and the default is back", "wide" not in pg.evaluate(LAYOUTS)["layouts"] and abs(box(pg, "#left")["w"] - 280) < 2, pg.evaluate(KEYS))
    pg.fill("#lay-name", "   ")
    pg.click("#lay-save")
    check("a name that is empty is refused with a message", "layout name" in pg.inner_text("#lay-status"), pg.inner_text("#lay-status"))

    # ---- export and import
    pg.fill("#lay-w-left", "320"); pg.dispatch_event("#lay-w-left", "input"); pg.dispatch_event("#lay-w-left", "change")
    pg.fill("#lay-name", "mine"); pg.click("#lay-save")
    pg.click("#lay-export")
    ex = json.loads(pg.input_value("#lay-json"))
    check("Export puts the layout in use in the box as JSON for this app", ex["app"] == "observatory" and ex["name"] == "mine" and ex["state"]["widths"]["left"] == 320 and ex["version"] == 1, ex)
    pg.click("#lay-import")
    check("Importing a layout whose name is taken saves it under the next free name and uses it", pg.evaluate(KEYS)[1] == "mine 2" and "mine 2" in pg.evaluate(LAYOUTS)["layouts"], pg.evaluate(KEYS))
    before = pg.evaluate(KEYS)
    for label, text, word in [("another app's layout", json.dumps({**ex, "app": "control"}), "control"), ("text that is not JSON", "{nope", "JSON"),
                              ("a layout of the wrong shape", json.dumps({**ex, "state": {"panels": 1, "widths": {}}}), "panels")]:
        pg.fill("#lay-json", text)
        pg.click("#lay-import")
        check(f"importing {label} is refused with a message and writes nothing", word in pg.inner_text("#lay-status") and pg.evaluate(KEYS) == before, [pg.inner_text("#lay-status"), pg.evaluate(KEYS) == before])
    pg.keyboard.press("Escape")

    # ---- the sections and the angle switch live in the layout now
    secs = pg.evaluate("window.miniview.state().sections.map((s) => s.id)")
    check("the run has sections to test with", len(secs) >= 2, secs)
    pg.evaluate(f"window.miniview.setSection({json.dumps(secs[0])}, true)")
    pg.evaluate("window.miniview.setSection(%s, false)" % json.dumps(secs[1]))
    open_saved = pg.evaluate(LAYOUTS)["layouts"][pg.evaluate(KEYS)[1]]["panels"]["open"]
    check("opening and closing a section is saved in the layout in use, beside the panel keys", open_saved.get(secs[0]) is True and open_saved.get(secs[1]) is False and not pg.evaluate("localStorage.getItem('miniview.left')"), open_saved)
    pg.evaluate("window.miniview.setAngles(false)")
    check("the joint-angle switch is saved in the layout too", pg.evaluate(LAYOUTS)["layouts"][pg.evaluate(KEYS)[1]]["panels"]["angles"] is False)
    menu(pg)
    pg.fill("#lay-name", "tidy"); pg.click("#lay-save")
    pg.select_option("#lay-list", "")
    check("choosing the default layout closes the sections", not {s["id"]: s["open"] for s in pg.evaluate("window.miniview.state()")["sections"]}[secs[0]])
    pg.select_option("#lay-list", "tidy")
    st = pg.evaluate("window.miniview.state()")
    check("loading a layout sets the sections and the angle switch the shell shows", {s["id"]: s["open"] for s in st["sections"]}[secs[0]] is True and st["angles"] is False,
          [{s["id"]: s["open"] for s in st["sections"]}, st["angles"]])
    pg.click("#lay-reset")
    st = pg.evaluate("window.miniview.state()")
    check("a reset closes the sections again and turns the angles back on", not {s["id"]: s["open"] for s in st["sections"]}[secs[0]] and st["angles"] is True, [{s["id"]: s["open"] for s in st["sections"]}, st["angles"]])
    pg.keyboard.press("Escape")

    # ---- the keyboard
    menu(pg)
    pg.focus("#lay-reset")
    play0 = pg.evaluate("document.querySelector('#playBtn').title")
    pg.keyboard.press("Space")
    check("Space on a button in the menu presses it and does not play the run", pg.evaluate("document.querySelector('#playBtn').title") == play0 and "default" in pg.inner_text("#lay-status"), [play0, pg.inner_text("#lay-status")])
    pg.focus("#lay-show-left")
    pg.keyboard.press("Space")
    check("Space on a check box toggles it", box(pg, "#left")["display"] == "none")
    pg.keyboard.press("Space")
    pg.keyboard.press("Escape")
    pg.focus("#layBtn")
    pg.keyboard.press("Enter")
    check("Enter on the button opens the menu", pg.evaluate("!document.querySelector('#lay-menu').hidden"))
    pg.keyboard.press("Escape")

    # ---- reduced motion
    pg.emulate_media(reduced_motion="reduce")
    menu(pg)
    anim = pg.evaluate("[document.querySelector('#lay-menu'), ...document.querySelectorAll('#lay-menu *'), document.querySelector('#left'), document.querySelector('.app')].map((e) => getComputedStyle(e)).filter((c) => parseFloat(c.transitionDuration) > 0 || (c.animationName !== 'none' && parseFloat(c.animationDuration) > 0)).length")
    check("under reduced motion the menu and the columns run no animation or transition", anim == 0, anim)
    pg.emulate_media(reduced_motion="no-preference")
    pg.keyboard.press("Escape")

    # ---- the legacy miniview.left, once
    ctx2 = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg2 = ctx2.new_page()
    pg2.set_default_timeout(15000)
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    boot(pg2, base + "/web/three/")
    pg2.evaluate("localStorage.setItem('miniview.left', JSON.stringify({open: {'%s': true}, angles: false}))" % secs[0])
    pg2.reload()
    pg2.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg2.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg2.wait_for_function("window.__ready === true")
    st2 = pg2.evaluate("window.miniview.state()")
    check("miniview.left migrates once: its open section and its angle switch show in the shell", {s["id"]: s["open"] for s in st2["sections"]}[secs[0]] is True and st2["angles"] is False,
          [{s["id"]: s["open"] for s in st2["sections"]}, st2["angles"]])
    check("... as the default layout in use", pg2.evaluate(KEYS)[1] == "default" and pg2.evaluate(LAYOUTS)["layouts"]["default"]["panels"]["angles"] is False, pg2.evaluate(KEYS))
    ctx2.close()

    # ---- a layout from before this unit (no hidden keys, no split) loads as it was
    ctx3 = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg3 = ctx3.new_page()
    pg3.set_default_timeout(15000)
    boot(pg3, base + "/web/three/")
    pg3.evaluate("""localStorage.setItem('rl.layouts.observatory', JSON.stringify({version: 1, layouts: {old: {panels: {left: true, right: true, open: {}, angles: true}, widths: {left: 280, right: 320}}}}));
                    localStorage.setItem('rl.layout.current.observatory', 'old')""")
    pg3.reload()
    pg3.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg3.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg3.wait_for_function("window.__ready === true")
    check("a layout saved with the store's own defaults (inspector 320 px) is applied as saved", abs(box(pg3, "#insp")["w"] - 320) < 2, box(pg3, "#insp"))
    ctx3.close()

    # ---- a phone
    ctx4 = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light", is_mobile=True, has_touch=True)
    pg4 = ctx4.new_page()
    pg4.set_default_timeout(15000)
    pg4.on("pageerror", lambda e: errs.append(str(e)))
    opened(pg4, 390, 844)
    pg4.click("#layBtn")
    mm = box(pg4, "#lay-menu")
    check("on a phone the menu fits the width and the height of the window", mm and mm["x"] >= 0 and mm["x"] + mm["w"] <= 390 and mm["y"] + mm["h"] <= 844, mm)
    if SHOTS:
        pg4.screenshot(path=str(SHOTS / "observatory-layout-menu-light-390.png"))
    pg4.uncheck("#lay-show-left")
    check("on a phone hiding the left column removes it from the page", box(pg4, "#left")["display"] == "none")
    check("... and the page does not scroll sideways", pg4.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), pg4.evaluate("document.documentElement.scrollWidth"))
    ctx4.close()

    check("no page error", not errs, errs)
    b.close()
httpd.shutdown()
check.done()
