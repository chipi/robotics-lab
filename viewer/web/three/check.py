"""Screenshots and numbers for the three.js miniview page (v0.2). Needs `miniview serve --port 8095`.
Drives the page only through window.miniview."""
import json
import pathlib
import time

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8095/web/three/"
SHOTS = pathlib.Path(__file__).parent / "shots"
SHOTS.mkdir(exist_ok=True)
T = 79.0  # explore12 is shorter than this: the page clamps to its end


def call(page, js):
    """Run one miniview call and wait for __ready, as a command would."""
    return page.evaluate(
        "async (js) => { window.__ready = false; const r = await eval(js);"
        " await new Promise((ok) => { const w = () => (window.__ready ? ok() : setTimeout(w, 10)); w(); }); return r; }", js)


def shot(page, name):
    page.screenshot(path=SHOTS / f"v2-{name}.png")


with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/chromium",
                          args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"])
    page = b.new_page(viewport={"width": 1400, "height": 900})
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    t0 = time.time()
    page.goto(URL)
    page.wait_for_function("window.__ready === true", timeout=120000)
    shot(page, "scenes")
    print("scenes page ready (s):", round(time.time() - t0, 2))

    call(page, "miniview.load('apartment', 'explore12')")
    print("loaded explore12 (s):", round(time.time() - t0, 2))
    call(page, f"miniview.setTime({T})")
    s = call(page, "miniview.state()")
    print("t after setTime:", s["t"], "range", s["t_range"], "tick", s["tick"])
    shot(page, "default")

    call(page, "miniview.setTimeMode('sensors.depth', 'window', 0.5)")
    shot(page, "depth-window")

    call(page, "miniview.setFrame('map')")
    shot(page, "map")
    call(page, "miniview.setFrame('world')")

    call(page, "miniview.setTimeMode('sensors.depth', 'at')")
    call(page, "miniview.setView('three')")
    for v in ("front", "right"):
        call(page, f"miniview.setViewVisible('{v}', 'sensors.depth', false)")
    shot(page, "three-depth-off-sides")

    # select a depth point: the first point of the first drawn kind, found through the page's own state
    call(page, "miniview.setView('top')")
    call(page, "miniview.setViewVisible('front', 'sensors.depth', true); miniview.setViewVisible('right', 'sensors.depth', true)")
    call(page, "miniview.select({kind: 'depth', index: 3000})")
    shot(page, "selection")
    print("state after select(depth 3000):", json.dumps(call(page, "miniview.state()"), indent=1))

    # a real click: robot, then cell, then a depth point, in the top view
    call(page, "miniview.select(null)")
    box = page.locator("#stage").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    print("click at the centre ->", json.dumps(page.evaluate("miniview.state().selection")))
    shot(page, "click-centre")
    # a real click on a drawn green floor return (screen position read off the default screenshot)
    page.mouse.click(860, 435)
    print("click on a floor return ->", json.dumps(page.evaluate("miniview.state().selection")))
    shot(page, "click-depth")
    # a real click on the belief robot (the blue ring near the origin's right)
    call(page, "miniview.setFrame('map')")
    page.mouse.click(819, 403)
    print("click on the robot (map frame) ->", json.dumps(page.evaluate("miniview.state().selection")))
    shot(page, "click-robot-map")
    call(page, "miniview.load()")
    page.click("tr[data-run=explore9]")
    page.wait_for_function("window.__ready === true && location.hash.includes('explore9')")
    print("scenes page click -> hash:", page.evaluate("location.hash"))
    print("console:", logs)
    page.close()

    page = b.new_page(viewport={"width": 1400, "height": 900})
    page.goto(URL + "#scene=apartment&run=phase1-run18")
    t0 = time.time()
    page.wait_for_function("window.__ready === true", timeout=120000)
    print("phase1-run18 load to ready (s):", round(time.time() - t0, 2))
    for view in ["top", "three", "3d"]:
        call(page, f"miniview.setView('{view}')")
        ms = page.evaluate("""() => {
          const s = miniview.state(), [a, b] = s.t_range, n = 200;
          const t0 = performance.now();
          for (let k = 0; k < n; k++) miniview.setTime(a + (b - a) * k / (n - 1), true);
          return (performance.now() - t0) / n;
        }""")
        print(f"scrub 200 updates, view={view}: {ms:.2f} ms per update (incl. render + 1px readback)")
    b.close()
