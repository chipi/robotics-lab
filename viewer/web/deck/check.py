"""Drive the deck.gl miniview page (v0.2) headless, ONLY through window.miniview, and save shots/v2-*.png.
Run with viewer/.venv/bin/python, the server on 8096 (cd viewer && .venv/bin/miniview serve --port 8096)."""
import json, pathlib
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8096/web/deck/"
HERE = pathlib.Path(__file__).parent
SHOTS = HERE / "shots"
SHOTS.mkdir(exist_ok=True)
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"]
T = 79.0

# a depth point of kind "o" (obstacle) in the newest depth frame at or before T, by its place in the file
f = json.load(open(HERE.parent.parent / "site/data/runs/explore12/frames.json"))
tick = max(i for i, t in enumerate(f["t"]) if t <= T and f["depth"][i])
before = sum(len(d) for d in f["depth"][:tick] if d)
pt = next(k for k, p in enumerate(f["depth"][tick]) if p[3] == "o")
DEPTH_INDEX = before + pt

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/chromium", args=ARGS)
    page = b.new_page(viewport={"width": 1400, "height": 860})
    errs = []
    page.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    page.goto(BASE)
    page.wait_for_function("window.__ready === true", timeout=60000)

    def call(js):
        page.evaluate("window.__ready = false")  # the page sets it itself; this only guards the wait below
        r = page.evaluate(f"(async () => {{ const r = miniview.{js}; return r; }})()")
        page.wait_for_function("window.__ready === true", timeout=60000)
        page.wait_for_timeout(250)
        return r

    def shot(name):
        page.screenshot(path=str(SHOTS / f"v2-{name}.png"))

    call("scenes()")
    shot("scenes")
    call("load('apartment', 'explore12')")
    call(f"setTime({T})")
    shot("default")
    call("setTimeMode('sensors.depth', 'window', 0.5)")
    shot("depth-window")
    call("setTimeMode('sensors.depth', 'at')")
    call("setFrame('map')")
    shot("map")
    call("setFrame('world')")
    call("setView('three')")
    for v in ("front", "right"):
        call(f"setViewVisible('{v}', 'sensors.depth', false)")
    shot("three")
    call("setView('top')")
    call(f"select({{kind: 'depth', index: {DEPTH_INDEX}}})")
    shot("selection")
    print("state after the selection:", json.dumps(page.evaluate("miniview.state()"), indent=1))
    call("select({kind: 'belief', index: 0})")
    print("belief selection:", json.dumps(page.evaluate("miniview.state().selection")))
    print("relation depth_pose ->", page.evaluate("miniview.setRelation('depth_pose', true)"))
    print("console:", *errs[:15], sep="\n  ")
    b.close()
