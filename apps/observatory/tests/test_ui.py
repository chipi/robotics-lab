"""The workbench in a real browser, both pages (three.js and deck.gl), self-contained: it writes the scene from the
committed layout (duck/sim/apartment_layout.json), generates a synthetic duck log that exercises every stream kind
(and a gap without ticks), imports it, serves it and drives the pages through the UI and `window.miniview`.
Needs Chromium and Playwright (CI: `uv run playwright install --with-deps chromium`; MINIVIEW_CHROMIUM overrides).
Run: cd apps/observatory && uv run python tests/test_ui.py"""

import base64
import json
import math
import re
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import OPEN_SECTIONS, catalog

from miniview.importer import import_duck
from miniview.scenes import from_mujoco_layout
from miniview.server import make_server
from miniview.shots import launch

LAYOUT = Path(__file__).resolve().parents[3] / "duck" / "sim" / "apartment_layout.json"
GAP = (40.0, 44.0)         # no ticks between these run times
T0, T1, DT = 10.0, 70.0, 0.125
fails = []
lib = "?"
EXTERNAL = []
CAM, PROBE = {}, {}      # per page: where the 3D camera puts known world points, the pixel over a box top


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def skip(name, why):
    print(f"SKIP [{lib}] {name}  [{why}]")


# ---- the synthetic duck run ---------------------------------------------------------------------------------
def pose(t):
    x, y = 1.2 * math.sin(0.2 * t), 0.8 * math.sin(0.4 * t)
    dx, dy = 0.24 * math.cos(0.2 * t), 0.32 * math.cos(0.4 * t)
    return x, y, math.atan2(dy, dx)


def grid_event(t, k):
    w, h = 20, 16
    cells = "".join("#" if i in (0, w - 1) or j in (0, h - 1) else ("?" if (i + j + k) % 7 == 0 else ".")
                    for j in range(h) for i in range(w))
    return {"event": "world", "t": t, "grid": {"res_m": 0.1, "origin": [-1.0, -0.8], "width": w, "height": h, "cells": cells},
            "blocked": [[0.5 + 0.01 * k, 0.2], [0.6, 0.25]], "drops": [[-0.2, -1.0]]}


def write_log(log: Path, name: str, t0: float, t1: float, gap=None) -> None:
    log.mkdir(parents=True)
    (log / "start.json").write_text(json.dumps({"map": [0, 0, 0], "truth": [0, 0, 0]}))
    lines, n = [], int(round((t1 - t0) / DT))
    for i in range(n + 1):
        t = round(t0 + i * DT, 3)
        if gap and gap[0] < t < gap[1]:
            continue
        x, y, yaw = pose(t)
        c, s = math.cos(yaw), math.sin(yaw)
        depth = [[x + d * c - la * s, y + d * s + la * c, 0.0, "f"] for d in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8) for la in (-0.05, 0.05)]
        depth += [[x + 0.9 * c - la * s, y + 0.9 * s + la * c, 0.1, "o"] for la in (-0.1, 0.0, 0.1)]
        if i % 5 == 0:
            depth.append([x + 0.5 * c, y + 0.5 * s, -0.3, "b"])
        r = {"t": t, "pose": [round(x, 4), round(y, 4), round(yaw, 4)], "truth": [round(x + 0.03, 4), round(y - 0.02, 4), round(yaw + 0.02, 4)],
             "vx": 0.3, "vyaw": 0.1, "depth": depth}
        if i % 7 == 0:
            r["tilt"] = [1.5, -0.5]
        lines.append((t, r))
    for k, t in enumerate(range(int(t0) + 2, int(t1), 5)):
        lines.append((float(t), grid_event(float(t), k)))
    for t in range(int(t0) + 1, int(t1), 4):
        x, y, _ = pose(t)
        lines.append((float(t) + 0.01, {"event": "plan", "t": float(t) + 0.01, "path": [[x, y], [x + 0.3, y], [x + 0.6, y + 0.3], [x + 0.9, y + 0.3]]}))
    ev = [(t0 + 10.0, {"event": "reflex_stop", "nearest_mm": 120}), (t0 + 20.5, {"event": "cliff_stop", "drop_m": 0.4}),
          (t0 + 25.0, {"event": "leg", "status": "started"}), (t0 + 40.0, {"event": "tight_pivot"}), (t0 + 45.0, {"event": "refused", "why": "no route"}),
          (t1 - 3.0, {"event": "leg", "status": "started"}), (t1 + 0.5, {"event": "trapped"})]
    for t, e in ev:
        lines.append((round(t, 3), dict(e, t=round(t, 3))))
    lines.sort(key=lambda p: p[0])
    (log / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for _, r in lines))


# ---- helpers for one page ------------------------------------------------------------------------------------
def run_page(b, base, rid, other):
    global lib
    ctx = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    EXTERNAL.clear()
    page.on("request", lambda r: EXTERNAL.append(r.url) if not r.url.startswith(("http://127.0.0.1", "data:", "blob:")) else None)

    def call(js, t=60000):
        page.evaluate("window.__ready = false")
        r = page.evaluate(js)
        page.wait_for_function("window.__ready === true", timeout=t)
        return r

    def ev(js):
        return page.evaluate(js)

    def state():
        return ev("window.miniview.state()")

    def helper(png: bytes, body: str):
        pg = ctx.new_page()
        pg.set_content(f'<canvas id=c></canvas><img id=i src="data:image/png;base64,{base64.b64encode(png).decode()}">')
        pg.wait_for_function("document.getElementById('i').complete")
        v = pg.evaluate("() => { const i = document.getElementById('i'), c = document.getElementById('c'); c.width = i.width; c.height = i.height;"
                        "const g = c.getContext('2d'); g.drawImage(i, 0, 0); const d = g.getImageData(0, 0, c.width, c.height).data;" + body + "}")
        pg.close()
        return v

    def pixel(png, x, y):
        return helper(png, f"return Array.from(d.slice(({y} * c.width + {x}) * 4, ({y} * c.width + {x}) * 4 + 4));")

    def count_colour(png, rgb, tol=28):
        return helper(png, f"let n = 0; for (let k = 0; k < d.length; k += 4) if (Math.abs(d[k] - {rgb[0]}) < {tol} && Math.abs(d[k+1] - {rgb[1]}) < {tol} && Math.abs(d[k+2] - {rgb[2]}) < {tol}) n++; return n;")

    def settle(timeout=15.0):
        """The stage's picture once two frames in a row are the same: zoom, resize and theme changes have finished."""
        end, prev = time.monotonic() + timeout, page.locator("#stage").screenshot()
        while True:
            page.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
            cur = page.locator("#stage").screenshot()
            if cur == prev:
                return cur
            if time.monotonic() > end:
                raise TimeoutError("the stage never settled")
            prev = cur

    def stage_png():
        return settle()

    def readout_xy(px, py):
        page.mouse.move(px, py)
        page.mouse.move(px + 1, py + 1)
        txt = ev("document.getElementById('readout').textContent").replace("−", "-")
        m = re.match(r"x (\S+)\s+y (\S+) m", txt)
        return (float(m.group(1)), float(m.group(2))) if m and "—" not in txt.split(" m")[0] else None

    def wait_selection(present, timeout=8000):
        """deck.gl answers a click asynchronously, and a loaded machine slowly: wait for the outcome, not a fixed time."""
        try:
            page.wait_for_function(f"(window.miniview.state().selection !== null) === {'true' if present else 'false'}", timeout=timeout)
        except Exception:  # noqa: BLE001
            pass

    def click_until_selected(x, y):
        page.mouse.click(x, y)
        wait_selection(True)

    def stage_box():
        return ev("(() => { const r = document.getElementById('stage').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")

    page.goto(f"{base}/web/{lib}/index.html")
    page.wait_for_function("window.miniview !== undefined", timeout=30000)
    page.wait_for_function("window.__ready === true", timeout=30000)
    check("no run in the URL: the scenes page, with its runs", ev("document.getElementById('app').classList.contains('scenes') && document.querySelectorAll('#scenespage tr[data-run]').length >= 2"))
    call(f"window.miniview.load('apartment', '{rid}')")
    run = json.loads(urllib.request.urlopen(f"{base}/api/v1/runs/duck/apartment/{rid}").read())
    fr = json.loads(urllib.request.urlopen(f"{base}/api/v1/runs/duck/apartment/{rid}/frames").read())
    t0, t1, nt = run["t0"], run["t1"], len(fr["t"])
    miss = sorted(s["id"] for s in run["streams"] if s["missing"])
    evt = sorted({e["t"] for e in run["events"]})
    evt_shown = sorted({e["t"] for e in run["events"] if e["kind"] != "leg"})    # leg events start hidden
    TA = 58.0
    call(f"window.miniview.setTime({TA})")
    check("the workbench shows after load()", ev("!document.getElementById('app').classList.contains('scenes')"))
    chip = ev("document.getElementById('runinfo').textContent").replace("\xa0", " ")
    check("status chip: robot, kind, verdict, length, ticks", "trapped" in chip and f"{nt} ticks" in chip, chip)
    st = state()
    last = [e for e in run["events"] if e["t"] <= max(TA, fr["t"][st["tick"]]) + 1e-9][-1]
    check("state(): t, belief, truth, distance, last_event", st["t"] == TA and len(st["belief"]) == 3 and len(st["truth"]) == 3
          and abs(st["distance"] - math.hypot(0.03, 0.02)) < 1e-3 and st["last_event"]["kind"] == last["kind"], json.dumps(st)[:200])

    # time-tick field and inspector: 1-based "tick K of N"; state().tick stays the 0-based index
    kin, kn = ev("document.getElementById('kin').value"), ev("document.getElementById('kn').textContent")
    insp = ev("document.getElementById('inspBody').innerText").replace("\n", " ")
    check("tick shows as 'tick K of N' (1-based) in the field and the inspector; state().tick is 0-based",
          kin == str(st["tick"] + 1) and kn == f"of {nt}" and f"{st['tick'] + 1} of {nt}" in insp, (kin, kn, st["tick"]))

    # fonts: served by the service (no CDN): loaded when the page says it is ready, and no request leaves the machine
    f = ev("""(async () => { await document.fonts.ready; return [document.fonts.check('12px Inter'), document.fonts.check('11px "JetBrains Mono"'),
      [...document.fonts].some(f => f.family === 'Inter' && f.status === 'loaded'), [...document.fonts].some(f => f.family === 'JetBrains Mono' && f.status === 'loaded'),
      getComputedStyle(document.body).fontFamily]; })()""")
    check("Inter and JetBrains Mono are loaded from the service when the page says it is ready", f[:4] == [True, True, True, True], f)
    check("no request left this machine (no CDN at runtime)", not EXTERNAL, EXTERNAL[:3])

    # outliner (its sections opened, as a viewer would)
    call(OPEN_SECTIONS)
    nrows = ev("document.querySelectorAll('#tree .row:not(.section)').length")
    check("outliner has rows with 22px height, under section headers of 26px", nrows >= 14 and ev("document.querySelector('#tree .row:not(.section)').getBoundingClientRect().height") == 22
          and ev("document.querySelector('#tree .row.section').getBoundingClientRect().height") == 26, nrows)
    check("the outliner header's filter and collapse buttons sit inside the left column", ev("(() => { const l = document.getElementById('left').getBoundingClientRect(), c = document.getElementById('collapseBtn').getBoundingClientRect(); return c.right <= l.right + 0.5 && c.left >= l.left; })()"))
    page.click("#tree .row[data-id='sensors.depth.obstacle'] .eye")
    check("clicking an eye hides the stream (state().hidden)", "sensors.depth.obstacle" in state()["hidden"])
    check("an eye click does not select the row", ev("document.querySelector('#tree .row[aria-selected=true]').dataset.id") == "belief.pose")
    page.click("#tree .row[data-id='sensors.depth.obstacle'] .eye")
    check("clicking again shows it", "sensors.depth.obstacle" not in state()["hidden"])
    page.click("#tree .row[data-id='sensors.depth'] .eye")
    st = state()
    inh = ev("document.querySelector('#tree .row[data-id=\"sensors.depth.floor\"]').classList.contains('inh')")
    check("hiding Depth hides its kinds, dims them, keeps their own state", {"sensors.depth.floor", "sensors.depth.obstacle"} <= set(st["hidden"]) and inh
          and ev("window.miniview.config().on['sensors.depth.floor'] !== false"), st["hidden"])
    page.click("#tree .row[data-id='sensors.depth'] .eye")
    check("and showing it again restores them", state()["hidden"] == [])
    page.click("#tree .row[data-id='sensors.depth.floor'] .eye")
    icons = {ev(f"document.querySelector('#tree .row[data-id=\"{i}\"] .eye').innerHTML") for i in ("sensors.depth", "g.world", "sensors.depth.floor")}
    check("group eye is tri-state (three different icons: on, mixed, off)", len(icons) == 3)
    page.click("#tree .row[data-id='sensors.depth.floor'] .eye")
    rows_missing = sorted(ev("[...document.querySelectorAll('#tree .row.missing')].map(r => r.dataset.id)"))
    check("missing streams are dimmed rows with a disabled eye", rows_missing == [m for m in miss if m != "events"] and ev("document.querySelector('#tree .row.missing .eye').disabled"), (rows_missing, miss))
    page.click("#filterBtn")
    page.uncheck("#fm")
    page.keyboard.press("Escape")
    check("filter hides missing streams", ev("document.querySelectorAll('#tree .row.missing').length") == 0)
    page.click("#filterBtn")
    page.check("#fm")
    page.keyboard.press("Escape")

    # properties of the selected row
    page.click("#tree .row[data-id='belief.track'] .name")
    head = ev("document.querySelector('#props .phead').innerText")
    check("selecting a row fills the properties panel (header, id, frame, records)", "Track" in head and "belief.track" in head and "map" in head and f"{nt} records" in head, head.replace("\n", " | "))
    secs = ev("[...document.querySelectorAll('#props .sec')].map(s => s.dataset.sec)")
    check("properties sections: Time, Display, Source, Relations", secs == ["time", "display", "source", "rel"], secs)
    page.click("#props [data-mode='window']")
    check("segmented control changes the mode (belief.track -> window)", ev("window.miniview.config().modes['belief.track'].mode") == "window")
    check("the Window field is enabled and a band shows on the timeline", ev("document.getElementById('winf').getAttribute('aria-disabled')") == "false" and ev("document.querySelectorAll('.wband').length") == 1)
    page.fill("#winv", "3.5")
    page.press("#winv", "Enter")
    check("typing the window length sets it", ev("window.miniview.config().modes['belief.track'].n") == 3.5)
    page.click("#props [data-mode='upto']")
    check("Up to t sets upto", ev("window.miniview.config().modes['belief.track'].mode") == "upto")
    page.click("#props [data-vv='front']")
    check("In-views toggle wired (setViewVisible)", ev("window.miniview.config().vv.front['belief.track']") is False)
    page.click("#props [data-vv='front']")
    page.click("#tree .row[data-id='sensors.depth'] .name")
    page.click("#props [data-mode='window']")
    check("group time mode applies to every kind", all(ev(f"window.miniview.config().modes['sensors.depth.{k}'].mode") == "window" for k in ("floor", "obstacle", "below")))
    page.click("#props [data-mode='at']")

    # display: point size and line width change the drawing
    page.click("#tree .row[data-id='sensors.depth.floor'] .name")
    call(f"window.miniview.setTime({TA})")
    floor = (60, 200, 90)
    n_small = count_colour(stage_png(), floor)
    page.click("#pszv")
    page.fill("#pszv", "14")
    page.press("#pszv", "Enter")
    n_big = count_colour(stage_png(), floor)
    check("Display > Point size changes the drawn points", n_big > n_small * 1.5 and n_small > 0, (n_small, n_big))
    page.click("#pszv")
    page.fill("#pszv", "4")
    page.press("#pszv", "Enter")
    page.click("#tree .row[data-id='belief.track'] .name")
    blue = (79, 140, 255)
    n_thin = count_colour(stage_png(), blue)
    page.click("#lszv")
    page.fill("#lszv", "9")
    page.press("#lszv", "Enter")
    n_thick = count_colour(stage_png(), blue)
    check("Display > Line width changes the drawn track", n_thick > n_thin * 1.3 and n_thin > 0, (n_thin, n_thick))
    page.click("#lszv")
    page.fill("#lszv", "2")
    page.press("#lszv", "Enter")
    check("the colour swatch stays in Display", ev("document.querySelector('#props .swatch i') !== null"))

    # playback: the first test here waits for the stop (a fixed sleep once failed by 60 ms)
    t_a = state()["t"]
    page.click("#playBtn")
    page.wait_for_function(f"window.miniview.state().t > {t_a + 0.6}", timeout=15000)
    page.click("#playBtn")
    t_b = state()["t"]
    check("play advances t", t_b > t_a + 0.5, (t_a, t_b))
    page.wait_for_function("window.miniview.config().play.on === false", timeout=5000)
    t_p = state()["t"]
    page.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))")
    check("pause stops it (the time is the same three frames later)", state()["t"] == t_p and t_p >= t_b, (t_b, t_p, state()["t"]))
    page.keyboard.press("Space")
    page.wait_for_function(f"window.miniview.state().t > {t_b + 0.05}", timeout=15000)
    page.keyboard.press("Space")
    check("Space toggles play", state()["t"] > t_b)
    call("window.miniview.setTime(20)")
    page.click("#speedBtn")
    page.click(".pop [data-speed='4']")
    t_a, w_a = state()["t"], ev("performance.now()")
    page.click("#playBtn")
    page.wait_for_function(f"window.miniview.state().t > {t_a + 1.2}", timeout=15000)
    page.click("#playBtn")
    t_c, w_c = state()["t"], ev("performance.now()")
    check("speed menu: 4x advances faster than real time (run seconds per wall second, measured in the page)",
          (t_c - t_a) / ((w_c - w_a) / 1000) > 1.8, round((t_c - t_a) / ((w_c - w_a) / 1000), 2))
    page.click("#speedBtn")
    page.click(".pop [data-speed='1']")
    call(f"window.miniview.setTime({t1 - 0.5})")
    page.click("#speedBtn")
    page.click(".pop [data-speed='8']")
    page.click("#loopBtn")
    page.click("#playBtn")
    page.wait_for_function(f"window.miniview.state().t < {t1 - 5}", timeout=15000)       # it reached the end and wrapped
    wrapped, still = state()["t"], ev("window.miniview.config().play.on")
    page.click("#playBtn")
    check("loop: playing past the end wraps to the start and keeps playing", still and wrapped < t0 + 10, (wrapped, still))
    page.click("#loopBtn")
    page.click("#speedBtn")
    page.click(".pop [data-speed='1']")
    call(f"window.miniview.setTime({t1 - 0.3})")
    page.click("#playBtn")
    page.wait_for_function("window.miniview.config().play.on === false", timeout=8000)
    check("without loop, play stops at the end (waited for the stop, not a fixed sleep)", ev("window.miniview.config().play.on") is False and state()["t"] == t1, (state()["t"], t1))
    sp = ev("(() => { const r = document.getElementById('split').getBoundingClientRect(); return [r.left + r.width / 2, r.top + 2]; })()")
    h0 = ev("document.getElementById('tree').getBoundingClientRect().height")
    page.mouse.move(sp[0], sp[1])
    page.mouse.down()
    page.mouse.move(sp[0], sp[1] - 150, steps=5)
    page.mouse.up()
    check("the splitter between outliner and properties drags", ev("document.getElementById('tree').getBoundingClientRect().height") < h0 - 100)
    call(f"window.miniview.setTime({TA})")

    # keyboard
    call("window.miniview.setTime(30)")
    page.keyboard.press("ArrowRight")
    a = state()["tick"]
    page.keyboard.press("ArrowLeft")
    check("arrow keys step a tick", a == state()["tick"] + 1)
    t = state()["t"]
    page.keyboard.press("Shift+ArrowRight")
    check("Shift+arrow steps 1 s", abs(state()["t"] - (t + 1)) < 1e-6)
    page.keyboard.press("Home")
    check("Home -> run start", state()["t"] == t0)
    page.keyboard.press("End")
    check("End -> run end", state()["t"] == t1)
    call(f"window.miniview.setTime({evt_shown[1] + 0.5})")
    page.keyboard.press(".")
    n1 = state()["t"]
    page.keyboard.press(",")
    n2 = state()["t"]
    check(". and , seek to the next / previous event", n1 == evt_shown[2] and n2 == evt_shown[1], (n1, n2, evt_shown[:4]))
    page.keyboard.press("2")
    check("key 2 -> Three layout", state()["view"] == "three")
    page.keyboard.press("3")
    check("key 3 -> 3D layout", state()["view"] == "3d")
    page.keyboard.press("1")
    check("key 1 -> Top layout", state()["view"] == "top")
    page.keyboard.press("w")
    check("key W -> map frame", state()["frame"] == "map")
    page.keyboard.press("w")
    check("key W again -> world", state()["frame"] == "world")
    page.click("#tree .row[data-id='plan.path'] .name")
    page.keyboard.press("h")
    check("H hides the selected", "plan.path" in state()["hidden"])
    page.keyboard.press("Shift+H")
    hid = state()["hidden"]
    check("Shift+H isolates the selected", "belief.pose" in hid and "plan.path" not in hid, hid)
    page.keyboard.press("Alt+h")
    check("Alt+H shows all", state()["hidden"] == [])
    page.keyboard.press("/")
    page.keyboard.type("obst")
    rows = ev("[...document.querySelectorAll('#tree .row')].map(r => r.dataset.id)")
    check("/ focuses the search and filters the list", "sensors.depth.obstacle" in rows and "world.obstacles" in rows and "belief.pose" not in rows, rows)
    page.fill("#q", "")
    page.keyboard.press("Escape")
    page.keyboard.press("?")
    check("? opens the help overlay", page.query_selector(".help") is not None)
    page.keyboard.press("Escape")
    check("Esc closes the help overlay", page.query_selector(".help") is None)
    page.click("#runBtn")
    check("the run popover lists the runs with kind, verdict, length, events", ev("document.querySelector('.pop').innerText").count("explore") >= 2)
    page.keyboard.press("Escape")
    check("Esc closes popovers", page.query_selector(".pop") is None)

    # timeline: data rows, hatched gaps, markers, seeking
    call(f"window.miniview.setTime({TA})")
    nrows_dl = ev("document.querySelectorAll('#dlanes .dl').length")
    spans, pts = ev("document.querySelectorAll('#dlanes .sp').length"), ev("document.querySelectorAll('#dlanes .pt').length")
    miss_dl = ev("document.querySelectorAll('#dlanes .dl.missing').length")
    labels = ev("[...document.querySelectorAll('#lanesL .lane-l')].map(l => l.textContent)")
    check("data rows render from /presence (rows, spans, point marks, missing rows)", nrows_dl == len(labels) and nrows_dl >= 8 and spans >= 4 and pts > 10 and miss_dl == len([m for m in miss if m != "events"]), (nrows_dl, spans, pts, miss_dl, labels))
    gaps = ev("[...document.querySelectorAll('#dlanes .gap')].map(g => g.title)")
    nums = [[float(x) for x in re.findall(r"\d+\.\d+", g)] for g in gaps]
    check("hatched bands mark where the run has no depth frames", len(gaps) == 1 and nums[0][0] <= GAP[0] + 0.3 and nums[0][1] >= GAP[1] - 0.3 and ev("getComputedStyle(document.querySelector('#dlanes .gap')).backgroundImage").startswith("repeating-linear-gradient"), gaps)
    page.click("#lanesBtn")
    check("Rows switch -> compact timeline without data rows", ev("document.getElementById('lanes').hidden") and ev("document.querySelectorAll('#dlanes .gap').length") == 0)
    page.click("#lanesBtn")
    check("markers by kind (triangles for stops)", ev("document.querySelectorAll('#mlane .mk.stop').length") > 0 and ev("document.querySelectorAll('#mlane .mk:not(.stop)').length") > 0)
    n_before = ev("document.querySelectorAll('#mlane .mk').length")
    page.click("#kindsBtn")
    page.check("[data-k='leg']")
    page.keyboard.press("Escape")
    check("event kind filter menu shows/hides markers", ev("document.querySelectorAll('#mlane .mk').length") > n_before, n_before)
    box = ev("(() => { const r = document.getElementById('dlanes').getBoundingClientRect(); return [r.left, r.top, r.width]; })()")
    page.mouse.click(box[0] + box[2] * 0.5, box[1] + 30)
    tt = state()["t"]
    check("click on the strip seeks", abs(tt - (t0 + t1) / 2) < 3, tt)
    page.mouse.move(box[0] + box[2] * 0.3, box[1] + 30)
    page.mouse.down()
    page.mouse.move(box[0] + box[2] * 0.6, box[1] + 30, steps=5)
    page.mouse.up()
    check("drag on the strip scrubs", state()["t"] > tt + 4, (tt, state()["t"]))
    page.fill("#tin", "30")
    page.press("#tin", "Enter")
    check("time field: type to seek", state()["t"] == 30)
    page.fill("#kin", "5")
    page.press("#kin", "Enter")
    check("tick field: type a 1-based tick to seek", state()["tick"] == 4, state()["tick"])
    page.click("#tPrev")
    page.click("#tNext")
    page.click("#tLast")
    page.click("#tFirst")
    check("transport buttons: first / last / prev / next", state()["t"] == t0)

    # inspector
    call(f"window.miniview.setTime({TA})")
    insp = ev("document.getElementById('inspBody').innerText")
    check("Moment tab: belief, truth, error, command, depth, plan, last event", all(w in insp for w in ("Belief", "Truth", "Heading error", "Forward", "Floor returns", "Plan made at", last["kind"])), insp[:80].replace("\n", " "))
    nxt = min(e for e in evt if e > TA + 1e-6)
    page.click("#inspBody [data-seek]:not([disabled]) >> nth=1")
    check("event next button seeks", abs(state()["t"] - nxt) < 1e-6, (state()["t"], nxt))
    page.click("#tabSel")
    check("Selection tab: empty state text", "Nothing picked" in ev("document.getElementById('inspBody').innerText"))
    total = sum(len(d) for d in fr["depth"] if d)
    mid, acc = None, 0                  # the middle depth return, as the page names it: tick * 100000 + its place in the tick
    for k, d in enumerate(fr["depth"]):
        if d and acc + len(d) > total // 2:
            mid = k * 100000 + (total // 2 - acc)
            break
        acc += len(d or [])
    call(f"window.miniview.select({{kind: 'depth', index: {mid}}})")
    check("select() fills the Selection tab", "x" in ev("document.getElementById('inspBody').innerText") and state()["selection"] is not None, json.dumps(state()["selection"])[:160])
    call("window.miniview.select(null)")
    call("window.miniview.select({kind: 'belief', index: 0})")
    check("select({kind:'belief'}) (deck's old name) -> a robot", state()["selection"]["stream"] == "belief.pose")
    call("window.miniview.select(null)")
    page.click("#tabMoment")

    # real clicks: calibrate screen <-> world through the cursor readout, then click where things are
    call("window.miniview.setView('top')")
    call("window.miniview.setFrame('map')")
    call(f"window.miniview.setTime({TA})")
    sb = stage_box()
    a_ = readout_xy(sb[0] + 400, sb[1] + 300)
    b_ = readout_xy(sb[0] + 700, sb[1] + 500)
    ppm = 300 / (b_[0] - a_[0])
    check("scale bar: 1 m, as long as 1 m is on the screen (top view)", ev("document.getElementById('scale').hidden") is False and ev("document.getElementById('scale').dataset.m") == "1"
          and abs(float(ev("document.querySelector('#scale i').getBoundingClientRect().width")) - ppm) < 0.03 * ppm + 1.5, (ppm, ev("document.getElementById('scale').dataset.px")))

    def to_px(wx, wy):
        return sb[0] + 400 + (wx - a_[0]) / (b_[0] - a_[0]) * 300 + 1, sb[1] + 300 + (wy - a_[1]) / (b_[1] - a_[1]) * 200 + 1

    st = state()
    click_until_selected(*to_px(st["belief_map"][0], st["belief_map"][1]))
    sel = state()["selection"]
    check("a real click on the robot selects it (map frame)", sel is not None and sel["stream"] == "belief.pose", sel)
    check("and the inspector switched to the Selection tab with its values", ev("document.getElementById('tabSel').getAttribute('aria-selected')") == "true" and "Yaw" in ev("document.getElementById('inspBody').innerText"))
    call(f"window.miniview.select({{kind: 'depth', index: {mid}}})")
    dp = state()["selection"]
    call("window.miniview.select(null)")
    call(f"window.miniview.setTime({dp['t']})")
    click_until_selected(*to_px(dp["position"][0], dp["position"][1]))
    sel = state()["selection"]
    check("a real click on a depth return selects it", sel is not None and sel["kind"] == "depth" and sel["stream"] == dp["stream"], repr(sel) + " wanted " + json.dumps(dp))
    page.mouse.click(sb[0] + 40, sb[1] + 120)
    wait_selection(False)
    check("a click on nothing clears the selection", state()["selection"] is None)
    call("window.miniview.setFrame('world')")
    call(f"window.miniview.setTime({TA})")

    # zoom: the scale bar follows
    sb = stage_box()
    page.mouse.move(sb[0] + sb[2] / 2, sb[1] + sb[3] / 2)
    page.mouse.wheel(0, -500)
    settle()
    a2 = readout_xy(sb[0] + 400, sb[1] + 300)
    b2 = readout_xy(sb[0] + 700, sb[1] + 500)
    ppm2 = 300 / (b2[0] - a2[0])
    m2, px2 = float(ev("document.getElementById('scale').dataset.m")), float(ev("document.getElementById('scale').dataset.px"))
    check("scale bar stays correct when zooming", ppm2 > ppm * 1.2 and abs(px2 - m2 * ppm2) < 0.03 * px2 + 1.5, (ppm, ppm2, m2, px2))
    page.click("#fitBtn")

    # layouts
    for v in ("three", "3d", "front", "top"):
        call(f"window.miniview.setView('{v}')")
        check(f"setView({v}) -> {v}", state()["view"] == v)
    sb = stage_box()
    page.mouse.move(sb[0] + sb[2] / 2, sb[1] + sb[3] / 2)
    page.mouse.move(sb[0] + sb[2] / 2 + 3, sb[1] + sb[3] / 2 + 3)
    ro = ev("document.getElementById('readout').textContent")
    check("cursor world coordinates in the top view", re.match(r"x \S+\s+y \S+ m", ro) and "world" in ro and "—" not in ro, ro)
    # the readout names the two axes of the view: front and back show y and z, left and right x and z
    for v, ax in (("front", "y"), ("back", "y"), ("left", "x"), ("right", "x")):
        call(f"window.miniview.setView('{v}')")
        page.mouse.move(sb[0] + sb[2] / 2, sb[1] + sb[3] / 2)
        page.mouse.move(sb[0] + sb[2] / 2 + 2, sb[1] + sb[3] / 2 + 2)
        ro = ev("document.getElementById('readout').textContent")
        check(f"cursor readout in the {v} view names {ax} and z", re.match(rf"{ax} -?\S+\s+z \S+ m", ro.replace("−", "-")) is not None, ro)
    fills = {}
    for v in ("top", "front", "back", "left", "right", "3d"):
        call(f"window.miniview.setView('{v}')")
        fills[v] = ev(f"window.miniview.internals.adapter.fillsDrawn('{v}')")
    check("the boxes' faint faces are drawn from above and in 3D, and only outlines in the four side views",
          fills == {"top": True, "front": False, "back": False, "left": False, "right": False, "3d": True}, fills)
    call("window.miniview.setView('3d')")
    page.mouse.move(sb[0] + sb[2] / 2, sb[1] + sb[3] / 2)
    page.mouse.move(sb[0] + sb[2] / 2 + 1, sb[1] + sb[3] / 2 + 1)
    ro = ev("document.getElementById('readout').textContent").replace("−", "-")
    m = re.match(r"x (\S+)\s+y (\S+) m", ro)
    check("cursor readout in 3D: the point of the floor under the pointer (the view's centre is the scene's centre)", m is not None and "—" not in ro and abs(float(m.group(1))) < 1.0 and abs(float(m.group(2))) < 1.0, ro)
    check("no scale bar in the 3D view", ev("document.getElementById('scale').hidden") is True)

    def grid_clear_of_bottom(tag):
        """the grid numbers lie just outside the scene's footprint: their lowest point must clear the legend (when shown) and the stage's bottom edge"""
        low = max(ev(f"window.miniview.internals.adapter.project([{x}, {y}, 0])")[1] for x in (-4.4, 4.4) for y in (-3.4, 3.4))
        top = ev("(() => { const l = document.getElementById('legend'); return l.offsetParent ? l.getBoundingClientRect().top : null; })()")
        bottom = ev("document.getElementById('stage').getBoundingClientRect().bottom")
        check(f"3D view {tag}: the grid numbers do not reach the legend or the bottom edge", low < (top if top is not None else bottom) - 4 and low < bottom - 30, (round(low), top, round(bottom)))
    grid_clear_of_bottom("at 1600 px")
    page.set_viewport_size({"width": 960, "height": 900})
    settle()
    grid_clear_of_bottom("at 960 px")
    page.set_viewport_size({"width": 1600, "height": 1000})
    settle()
    CAM[lib] = ev("[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [3, 2, 0], [-3, -2, 0]].map((p) => window.miniview.internals.adapter.project(p))")
    scene = json.loads(urllib.request.urlopen(f"{base}/api/v1/scenes/apartment").read())
    big = max((b for b in scene["boxes"] if b["z0"] < 0.5), key=lambda b: b["hx"] * b["hy"])
    bx, by = ev(f"window.miniview.internals.adapter.project([{big['cx']}, {big['cy']}, {min(big['z1'], 0.5)}])")
    call("window.miniview.setTime(%s)" % TA)
    settle()
    shot = page.screenshot()
    PROBE[lib] = (pixel(shot, int(bx), int(by)), pixel(shot, 290, 500)[:3])

    # the Three layout: top on the left, front over side on the right; captions below the viewport header
    call("window.miniview.setView('three')")
    sel_panes = ".slot" if lib == "three" else "#tags .pane-box"
    sel_caps = ".slot .cap" if lib == "three" else "#tags .pane-tag"
    rects = ev(f"[...document.querySelectorAll('{sel_panes}')].map(e => {{ const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }})")
    sb = stage_box()
    ok = len(rects) == 3 and rects[0][0] < rects[1][0] - 50 and abs(rects[1][0] - rects[2][0]) < 3 and rects[1][1] < rects[2][1] - 50 and rects[0][3] > sb[3] * 0.9 and abs(rects[0][2] - rects[1][2]) < 5
    check("Three layout: three panes, top on the left, front and side stacked on the right", ok, rects)
    caps = ev(f"[...document.querySelectorAll('{sel_caps}')].map(e => [e.textContent, e.getBoundingClientRect().top])")
    vb = ev("document.querySelector('.vhead').getBoundingClientRect().bottom")
    check("pane captions name the views and do not sit under the viewport header", [c[0].split(" · ")[1] for c in caps] == ["top", "front", "right"] and all(c[1] >= vb for c in caps), (caps, vb))
    if lib == "deck":
        ids = ev("window.miniview.internals.adapter.deck().getViewports().map(v => v.id)")
        check("deck.gl has exactly those three viewports", ids == ["top", "front", "right"], ids)
    check("scale bar in the Three layout (the top pane)", ev("document.getElementById('scale').hidden") is False)
    call("window.miniview.setView('top')")

    # overlays, fit, gizmo, map-frame dimming, scene picker, wordmark -> scenes page
    call("window.miniview.setView('3d')")
    g3 = ev("document.getElementById('gizmo').querySelectorAll('circle').length")
    call("window.miniview.setView('top')")
    gt = ev("document.getElementById('gizmo').querySelectorAll('circle').length")
    check("axis gizmo: top view shows x and y with z as a dot; 3D view draws all three", g3 >= 4 and gt >= 3, (g3, gt))
    page.click("#ovBtn")
    page.uncheck("[data-ov='legend']")
    page.uncheck("[data-ov='gizmo']")
    page.uncheck("[data-ov='coords']")
    check("overlays popover: legend, gizmo and coordinate system switch off", ev("document.getElementById('legend').style.display") == "none" and ev("document.getElementById('gizmo').style.display") == "none" and ev("window.miniview.internals.M.ov.coords") is False)
    page.check("[data-ov='legend']")
    page.check("[data-ov='gizmo']")
    page.check("[data-ov='coords']")
    page.uncheck("[data-ov='rel']")
    check("overlays popover: belief <-> truth line is the relation flag", ev("window.miniview.config().rel.belief_truth") is False)
    page.check("[data-ov='rel']")
    page.keyboard.press("Escape")
    call("window.miniview.setFrame('map')")
    na = ev("[...document.querySelectorAll('#tree .row.na')].map(r => r.dataset.id)")
    check("map frame: scene and truth rows are dimmed (not drawn there)", set(na) == {"scene.boxes", "scene.hazards", "truth.pose", "truth.track"}, na)
    page.click("#tabMoment")
    check("map frame: the Moment tab says truth is hidden", "hidden in the map frame" in ev("document.getElementById('inspBody').innerText"))
    call("window.miniview.setFrame('world')")
    page.click("#sceneBtn")
    check("scene popover lists the scenes", "apartment" in ev("document.querySelector('.pop').innerText"))
    page.keyboard.press("Escape")
    page.click("#scenes-link")
    check("the wordmark opens the scenes page", ev("document.getElementById('app').classList.contains('scenes')"))
    check("on the scenes page the chrome says no run is open (no run chip, no layout or frame buttons)",
          ev("document.getElementById('runName').textContent") == "choose a run" and ev("document.getElementById('st-run').textContent") == "no run open"
          and all(ev(f"getComputedStyle(document.getElementById('{i}')).display") == "none" for i in ("layoutSeg", "frameSeg", "runinfo")))
    page.click(f"#scenespage tr[data-run='duck/apartment/{other}']")
    page.wait_for_function(f"window.__ready === true && location.hash.includes('{other}')", timeout=30000)
    check("a scenes-page row opens that run", ev("window.miniview.state().run") == f"duck/apartment/{other}" and ev("document.getElementById('runinfo').textContent").find("ticks") > 0, ev("location.hash"))
    call(f"window.miniview.load('apartment', '{rid}')")
    call(f"window.miniview.setTime({TA})")

    def sweep_playhead(tag):
        """the time label stays inside the strip for any time (a sweep across the run, ends included)"""
        bad = []
        for k in range(21):
            tt_ = t0 + (t1 - t0) * k / 20
            call(f"window.miniview.setTime({tt_})")
            ok = ev("(() => { const h = document.querySelector('#ph .head').getBoundingClientRect(), r = document.getElementById('ruler').getBoundingClientRect(); return h.left >= r.left - 0.5 && h.right <= r.right + 0.5; })()")
            if not ok:
                bad.append(round(tt_, 2))
        check(f"{tag}: the playhead's time label stays inside the strip over a 21-point sweep of the run", not bad, bad)

    sweep_playhead("1600 px wide")
    # narrow windows: no horizontal page scroll, the viewport first, the timeline right under it
    for w in (960, 700, 400):
        page.set_viewport_size({"width": w, "height": 900})
        settle()
        sw = ev("[document.documentElement.scrollWidth, innerWidth]")
        g = ev("(() => { const r = (i) => document.getElementById(i).getBoundingClientRect(); return [r('stage').top, r('tl').top, r('ruler').width, r('ruler').left]; })()")
        check(f"{w} px wide: no horizontal page scroll; the viewport, then the timeline, with a usable ruler",
              sw[0] <= sw[1] and g[0] < g[1] and g[2] > w * 0.6 and g[3] >= 0, (sw, g))
        sweep_playhead(f"{w} px wide")
        if w == 400:
            hidden = ev("getComputedStyle(document.getElementById('legend')).display") == "none"
            page.click("#ovBtn")
            keys = ev("[...document.querySelectorAll('.pop .lg span')].map(e => e.textContent)")
            page.keyboard.press("Escape")
            check("400 px wide: the legend is hidden in the viewport and the colour keys are in the overlays popover", hidden and "Belief" in keys and len(keys) >= 4, keys)
    page.set_viewport_size({"width": 1600, "height": 1000})
    settle()
    page.click("#ovBtn")
    check("wide: the legend shows in the viewport and the overlays popover does not repeat it", ev("getComputedStyle(document.getElementById('legend')).display") != "none" and page.query_selector(".pop .lg") is None)
    page.keyboard.press("Escape")
    call(f"window.miniview.setTime({TA})")

    # theme
    tok_dark = ev("getComputedStyle(document.documentElement).getPropertyValue('--bg-viewport').trim()")
    px_dark = pixel(page.locator("#stage").screenshot(), 3, 500)
    page.click("#themeBtn")
    settle()
    tok_light = ev("getComputedStyle(document.documentElement).getPropertyValue('--bg-viewport').trim()")
    px_light = pixel(page.locator("#stage").screenshot(), 3, 500)
    check("theme switch flips the tokens; the renderer's clear colour follows (pixel in the viewport)", tok_dark == "#202125" and tok_light == "#f6f7f9"
          and px_dark[:3] == [0x20, 0x21, 0x25] and px_light[:3] == [0xf6, 0xf7, 0xf9], (tok_dark, tok_light, px_dark, px_light))
    check("the choice is remembered (localStorage)", ev("localStorage.getItem('miniview.theme')") == "light")
    page.reload()
    page.wait_for_function("window.__ready === true", timeout=30000)
    check("and applied after a reload", ev("document.documentElement.dataset.theme") == "light")
    ev("localStorage.removeItem('miniview.theme')")
    page.close()
    ctx.close()
    ctx2 = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="light")
    p2 = ctx2.new_page()
    p2.goto(f"{base}/web/{lib}/index.html")
    p2.wait_for_function("window.__ready === true", timeout=30000)
    check("follows prefers-color-scheme: light when nothing is stored", p2.evaluate("document.documentElement.dataset.theme") == "light")
    ctx2.close()
    bad = [log for log in logs if "favicon.ico" not in log and not ("fonts.g" in log and "net::ERR" in log)]
    check("no console errors other than the favicon 404", not bad, bad[:5])


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(from_mujoco_layout(LAYOUT, "apartment", "The simulated apartment"))
    for rid, a, b_, gap in (("explore12", T0, T1, GAP), ("explore9", 5.0, 12.0, None)):
        write_log(Path(tmp) / "logs" / rid, rid, a, b_, gap)
        import_duck(Path(tmp) / "logs" / rid, "apartment", data, say=lambda *_: None)
    httpd = make_server(cat, "127.0.0.1", 0, follow=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    with sync_playwright() as p:
        browser = launch(p)
        for lib in ("three", "deck"):
            run_page(browser, base, "explore12", "explore9")
        browser.close()
    httpd.shutdown()

lib = "both"
if len(CAM) == 2:
    d = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(CAM["three"], CAM["deck"]))
    check("the two pages' 3D cameras put the same world points at the same pixels", d < 3, round(d, 2))
    (pt, bg_t), (pd, bg_d) = PROBE["three"], PROBE["deck"]
    diff = max(abs(a - b) for a, b in zip(pt[:3], pd[:3]))
    check("the box fill over the same box top in 3D has the same colour on both pages (within 14 per channel) and is not the background",
          diff <= 14 and max(abs(a - b) for a, b in zip(pt[:3], bg_t)) > 4 and max(abs(a - b) for a, b in zip(pd[:3], bg_d)) > 4, (pt, pd, bg_t))

print("UI PASS" if not fails else "UI FAIL " + "; ".join(fails))
sys.exit(1 if fails else 0)
