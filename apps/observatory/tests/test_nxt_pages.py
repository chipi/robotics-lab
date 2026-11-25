"""An NXT run in both pages (ADR-0013), in headless Chromium: a run with signals and no pose shows the Signals view (a chart per
numeric signal, a band per text signal, the playhead, a click or drag seeks), the section Other values in the outliner with an eye
per signal, the values at t in the inspector, a row per signal in the timeline; a run with a pose from odometry keeps the
spatial views and shows its signals beside them; a run being written follows live; a duck run has none of it. Screenshots of
what the page shows go to /tmp/claude-1000/nxt-runs/ (NXT_SHOTS=0 turns it off).
Run: cd apps/observatory && uv run python tests/test_nxt_pages.py"""

import json
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import FIXTURE, LANE_PIXELS, OPEN_SECTIONS, T0_NS, boot, catalog, import_fixture, open_lanes, scene, serve, wait_until
from runfile import keys
from runfile.adapters import nxt
from runfile.mcapio import Recorder
from observatory.shots import launch

FIX = Path(__file__).resolve().parent / "fixtures" / "nxt"
CSV_A, CSV_B = "run-20261114-094243", "run-20261114-145402"
A, B = f"nxt/unmapped/{CSV_A}", f"nxt/unmapped/{CSV_B}"
SHOTS = Path("/tmp/claude-1000/nxt-runs") if os.environ.get("NXT_SHOTS", "1") != "0" else None
fails, lib = [], "?"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def run_page(b, base, theme="dark", shots=None):
    ctx = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme=theme)
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    boot(page, f"{base}/web/{lib}/index.html", timeout=30000)
    return ctx, page, logs


def call(page, js, t=60000):
    page.evaluate("window.__ready = false")
    r = page.evaluate(js)
    page.wait_for_function("window.__ready === true", timeout=t)
    return r


def eventually(page, js, timeout=8000) -> bool:
    """True once the expression is truthy in the page (the page answers in a frame or two, never at once); False after the timeout."""
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def span_of(run):
    pad = max(0.05, 0.012 * (run["t1"] - run["t0"]))
    return run["t0"] - pad, run["t1"] + pad


def api(base, path):
    import urllib.request

    return json.loads(urllib.request.urlopen(base + path).read())


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    tmp = Path(tmp)
    shutil.copytree(FIX, tmp / "nxt")
    data, data_odom = tmp / "data", tmp / "data-odom"
    for d, kw in ((data, {}), (data_odom, {"sprocket": 0.043, "track": 0.12})):
        for name in (CSV_A, CSV_B):
            nxt.import_csv(tmp / "nxt" / "runs" / f"{name}.csv", d, tz="Europe/Zurich", say=lambda *_: None, **kw)
    import_fixture(data)                                     # a duck run in the same data folder: it must look as before
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    odom_cat = catalog(data_odom)
    odom_httpd, odom_base = serve(odom_cat, follow=False)
    live_dir = tmp / "data-live"
    cols = {"power_left": "number", "tacho_B": "number", "tacho_C": "number", "s3_color_name": "text"}
    live_cat = catalog(live_dir)
    live_httpd, live_base = serve(live_cat, follow=True)
    b = launch(p)
    run = api(base, f"/api/v1/runs/{A}")
    sig = api(base, f"/api/v1/runs/{A}/signals")
    SIGS = [d["name"] for d in run["signals"]]
    shown = [s for s in run["streams"] if s["id"].startswith("signals.") and not s["missing"]]

    for lib in ("three", "deck"):
        ctx, page, logs = run_page(b, base)
        rows = page.evaluate("[...document.querySelectorAll('#scenespage tr[data-run]')].map((r) => r.dataset.run)")
        check("the scenes page lists the scene `unmapped` with the NXT runs although it has no scene.json",
              {A, B} <= set(rows) and "unmapped" in page.evaluate("document.getElementById('scenespage').innerText"), rows)
        call(page, f"window.miniview.load('unmapped', '{A}')")
        call(page, OPEN_SECTIONS)
        check("the run opens: the workbench shows, the Signals view takes the viewport, no layout/frame buttons",
              page.evaluate("!document.getElementById('app').classList.contains('scenes') && document.getElementById('app').classList.contains('signals-only')")
              and page.evaluate("getComputedStyle(document.getElementById('sigview')).display !== 'none'")
              and page.evaluate("getComputedStyle(document.getElementById('layoutSeg')).display === 'none' && getComputedStyle(document.getElementById('frameSeg')).display === 'none'"))
        chip = page.evaluate("document.getElementById('runinfo').textContent").replace("\xa0", " ")
        verdict = page.evaluate("document.getElementById('runVerdict').textContent")      # the Run button shows it, not the chip (round 1)
        check("the status chip says robot, kind, length and the samples; the Run button the verdict", "nxt" in chip and "recording" in chip
              and f"{run['samples']} samples" in chip and "recorded" in verdict, (chip, verdict))

        # the outliner: the section Other values, a row per signal with an eye
        grp = page.evaluate("document.querySelector('#tree .row[data-id=\"sec.other\"]') !== null")
        sig_rows = page.evaluate("[...document.querySelectorAll('#tree .row[data-id^=\"signals.\"]')].map((r) => [r.dataset.id, !!r.querySelector('.eye')])")
        check("the outliner has the section Other values with a row and an eye for each signal the run has values for",
              grp and sorted(i for i, _ in sig_rows) == sorted(s["id"] for s in shown) and all(e for _, e in sig_rows), sig_rows)
        n_missing = page.evaluate("window.miniview.internals.M.run.streams.filter((s) => s.missing).length")
        check("the streams the run lacks are hidden behind 'Show them' (a run that is its signals), and the footer says how many (the scene's two included: no layout)",
              n_missing == sum(1 for s in run["streams"] if s["missing"]) + 2 and page.evaluate("document.querySelector('#tree .tfoot').innerText").startswith(f"{n_missing} streams missing")
              and page.evaluate("document.querySelector('#tree .row[data-id=\"belief.pose\"]') === null"))
        page.evaluate("document.getElementById('hm').click()")
        check("'Show them' lists the pose streams as missing, with the reason the run gives", page.evaluate("document.querySelector('#tree .row[data-id=\"belief.pose\"]')?.classList.contains('missing')")
              and "no wheel geometry" in page.evaluate("document.querySelector('#tree .row[data-id=\"belief.pose\"]').title"), page.evaluate("document.querySelector('#tree .row[data-id=\"belief.pose\"]')?.title"))
        page.evaluate("document.getElementById('hm').click()")

        # the Signals view: a chart per numeric signal, a band per text signal
        charts = page.evaluate("[...document.querySelectorAll('#sigview .sg')].map((c) => [c.dataset.sig, c.dataset.kind, c.querySelector('path.line')?.getAttribute('d')?.length ?? 0, c.querySelectorAll('rect.band').length])")
        want_text = {s["id"] for s in shown if s.get("kind") == "text"}
        check("the Signals view has one chart (a line) per numeric signal and one band row per text signal, all drawn",
              sorted(c[0] for c in charts) == sorted(s["id"] for s in shown)
              and all((c[3] >= 1) if c[0] in want_text else c[2] > 20 or (c[0] == "signals.s3_color" and c[3] >= 1) for c in charts), charts)
        check("a unitless numeric signal with a few whole values (the colour index) is drawn as state spans (U15), the quantities keep their line",
              [c[3] > 0 for c in charts if c[0] == "signals.s3_color"] == [True] and all(c[2] > 20 for c in charts if c[0] in ("signals.tacho_A", "signals.s4_ultrasonic", "signals.power_left")), charts)
        check("the colour-name band has a stretch for each colour in the run (yellow, then black)", [c[3] for c in charts if c[0] == "signals.s3_color_name"] == [2], charts)

        # the values at t, in the inspector and in the chart labels, are the API's (the sample at or before t)
        def at(t):
            call(page, f"window.miniview.setTime({t})")
            return page.evaluate("window.miniview.state()")

        for t in (0.0, 21.3, 55.9):
            st = at(t)
            exp = api(base, f"/api/v1/runs/{A}/state?t={st['t']}")["signals"]
            insp = page.evaluate("document.getElementById('inspBody').innerText").replace("−", "-").replace("\n", " ")
            lab = page.evaluate("Object.fromEntries([...document.querySelectorAll('#sigview .sg')].map((c) => [c.dataset.sig, c.querySelector('.val').textContent]))")
            ok_state = st["signals"]["t"] == exp["t"] and st["signals"]["values"] == exp["values"]
            ok_insp = f"sample {exp['index'] + 1} of {exp['n']}" in insp and f"tacho_B {exp['values']['tacho_B']:.0f}" in insp and f"s3_color_name {exp['values']['s3_color_name']}" in insp
            ok_lab = lab["signals.tacho_B"].replace("−", "-") == str(exp["values"]["tacho_B"]).rstrip("0").rstrip(".") and lab["signals.s3_color_name"] == exp["values"]["s3_color_name"]
            check(f"at t = {t}: state(), the inspector's Moment and the charts' labels give the API's values for the sample at or before it", ok_state and ok_insp and ok_lab, (exp["index"], lab.get("signals.tacho_B")))
        st = at(21.3)
        check("the inspector's Moment names the time and the sample ('sample K of N') instead of a tick", "Sample" in page.evaluate("document.getElementById('inspBody').innerText")
              and page.evaluate("document.getElementById('kn').textContent") == f"of {run['samples']}" and page.evaluate("document.querySelector('#tfK .u').textContent") == "sample")

        # the playhead is drawn at t on every chart
        a0, a1 = span_of(run)
        xs = page.evaluate("[...document.querySelectorAll('#sigview .sg')].map((c) => [+c.querySelector('line.ph').getAttribute('x1'), +c.querySelector('svg').getAttribute('width')])")
        check("the playhead is at t on every chart, over the shared time axis",
              all(abs(x - (21.3 - a0) / (a1 - a0) * w) < 1.0 for x, w in xs) and len({round(w) for _, w in xs}) == 1, xs[:2])

        # a click on a chart seeks; a drag scrubs
        def plot_box(name):
            return page.evaluate(f"(() => {{ const r = document.querySelector('#sigview .sg[data-sig=\"{name}\"] .sg-p').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }})()")

        x, y, w, h = plot_box("signals.tacho_B")
        t_want = a0 + 0.25 * (a1 - a0)
        page.mouse.click(x + 0.25 * w, y + h / 2)
        wait_until(lambda: abs(page.evaluate("window.miniview.state().t") - t_want) < 0.02 * (a1 - a0), 5, what="the click to seek")
        check("a click on a chart moves the playhead there: state().t is the time under the pointer, the follow switch is off",
              abs(page.evaluate("window.miniview.state().t") - t_want) < 0.02 * (a1 - a0) and page.evaluate("window.miniview.state().follow") is False, page.evaluate("window.miniview.state().t"))
        x, y, w, h = plot_box("signals.power_right")
        page.mouse.move(x + 0.2 * w, y + h / 2)
        page.mouse.down()
        page.mouse.move(x + 0.7 * w, y + h / 2, steps=5)
        page.mouse.up()
        t_drag = a0 + 0.7 * (a1 - a0)
        wait_until(lambda: abs(page.evaluate("window.miniview.state().t") - t_drag) < 0.02 * (a1 - a0), 5, what="the drag to seek")
        check("a drag across a chart scrubs to where it ends, and every chart's playhead follows",
              all(abs(x_ - (page.evaluate("window.miniview.state().t") - a0) / (a1 - a0) * w_) < 1.0 for x_, w_ in page.evaluate("[...document.querySelectorAll('#sigview .sg')].map((c) => [+c.querySelector('line.ph').getAttribute('x1'), +c.querySelector('svg').getAttribute('width')])")))

        # an eye hides a signal: its chart goes, its row dims; the group's eye hides them all
        call(page, "window.miniview.setVisible('signals.tacho_A', false)")
        check("hiding a signal removes its chart (the outliner's eye and setVisible do the same)", page.evaluate("document.querySelector('#sigview .sg[data-sig=\"signals.tacho_A\"]') === null")
              and page.evaluate("document.querySelectorAll('#sigview .sg').length") == len(shown) - 1)
        page.evaluate("document.querySelector('#tree .row[data-id=\"signals.tacho_A\"] .eye').click()")
        check("the eye in the outliner brings it back", page.evaluate("document.querySelector('#sigview .sg[data-sig=\"signals.tacho_A\"]') !== null"))
        page.evaluate("document.querySelector('#tree .row[data-id=\"sec.other\"] .eye').click()")
        check("the group's eye hides every chart, and the view says why it is empty",
              page.evaluate("document.querySelectorAll('#sigview .sg').length") == 0 and "No signal is shown" in page.evaluate("document.getElementById('sigview').innerText"))
        page.evaluate("document.querySelector('#tree .row[data-id=\"sec.other\"] .eye').click()")
        check("and brings them all back", page.evaluate("document.querySelectorAll('#sigview .sg').length") == len(shown))

        # the timeline: a data row per signal, no row for the streams the run lacks
        open_lanes(page)
        lanes = page.evaluate("[...document.querySelectorAll('#lanesL .lane-l')].map((l) => l.dataset.lane)")
        spans = [n for _, n in page.evaluate(LANE_PIXELS)]      # drawn pixels per lane
        check("the timeline has a data row for each signal with its presence, and none for a missing stream",
              sorted(lanes) == sorted(s["id"] for s in shown) and all(n >= 1 for n in spans) and len(spans) == len(lanes) and page.evaluate("document.querySelectorAll('#lanesL .lane-l.missing').length") == 0, lanes)
        check("the timeline's data bar spans the samples", page.evaluate("document.querySelector('#ruler .data') !== null"))
        # selecting a signal (the outliner, a timeline row) highlights its chart and describes it in the properties
        page.evaluate("document.querySelector('#tree .row[data-id=\"signals.tacho_C\"]').click()")
        check("selecting a signal in the outliner selects its chart and shows its properties (kind, unit, records)",
              page.evaluate("document.querySelector('#sigview .sg.sel')?.dataset.sig") == "signals.tacho_C"
              and "number" in page.evaluate("document.getElementById('props').innerText") and "deg" in page.evaluate("document.getElementById('props').innerText"))
        # stepping: the arrow keys move by sample
        before = page.evaluate("window.miniview.state().signals.i")
        page.keyboard.press("ArrowRight")
        wait_until(lambda: page.evaluate("window.miniview.state().signals.i") == before + 1, 5, what="a step to the next sample")
        check("the right arrow steps to the next sample", page.evaluate("window.miniview.state().signals.i") == before + 1)
        check("and the inspector says which sample it is", eventually(page, f"document.getElementById('inspBody').innerText.includes('sample {before + 2} of')"))
        call(page, "window.miniview.setTime(1e9)")
        st = page.evaluate("window.miniview.state()")
        check("seeking past the end stops at the last sample", st["t"] == run["t1"] and st["signals"]["i"] == run["samples"] - 1, st["t"])
        check("the page logged no error", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        shot(page, f"nxt-signals-{lib}-dark")
        ctx.close()

        # the light theme
        ctx, page, logs = run_page(b, base, "light")
        call(page, f"window.miniview.load('unmapped', '{A}')")
        call(page, "window.miniview.setTime(21.3)")
        STROKE = "getComputedStyle(document.querySelector('#sigview path.line')).stroke"
        light_stroke = page.evaluate(STROKE)
        check("the light theme: the page says so, the lines are a categorical ramp colour of the theme (a token, not a literal)",
              page.evaluate("document.documentElement.dataset.theme") == "light" and re.fullmatch(r"var\(--ramp-cat-[1-8]\)", page.evaluate("document.querySelector('#sigview path.line').getAttribute('stroke')") or ""))
        page.evaluate("document.getElementById('themeBtn').click()")
        page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        check("switching to dark draws the signals in the dark theme's ramp colour", page.evaluate(STROKE) != light_stroke, (light_stroke, page.evaluate(STROKE)))
        page.evaluate("document.getElementById('themeBtn').click()")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'")
        shot(page, f"nxt-signals-{lib}-light")
        ctx.close()

        # the second recording: events, and the events' markers
        ctx, page, logs = run_page(b, base)
        call(page, f"window.miniview.load('unmapped', '{B}')")
        call(page, "window.miniview.setTime(3.0)")
        check("a recording with events has a marker for each on the timeline", page.evaluate("document.querySelectorAll('#mlane .mk').length") == 6)
        insp = page.evaluate("document.getElementById('inspBody').innerText").replace("\n", " ")
        check("the inspector's Last event is the drive before t, with its text", "drive" in insp and "left 40 right -40" in insp, insp[-160:])
        check("state() names the last event at t (the drive that turned the robot) and the signals", page.evaluate("window.miniview.state().last_event.kind") == "drive"
              and page.evaluate("window.miniview.state().signals.values.s3_color_name") == "green")
        ctx.close()

        # a run with a pose from the odometry keeps the spatial views and has its signals beside them
        ctx, page, logs = run_page(b, odom_base)
        call(page, f"window.miniview.load('unmapped', '{A}')")
        call(page, OPEN_SECTIONS)
        st = page.evaluate("window.miniview.state()")
        oapi = api(odom_base, f"/api/v1/runs/{A}")
        call(page, "window.miniview.setTime(21.3)")
        st = page.evaluate("window.miniview.state()")
        fr = api(odom_base, f"/api/v1/runs/{A}/frames")
        i = st["tick"]
        check("with odometry the run has ticks and the spatial views, not the Signals view",
              oapi["ticks"] == 281 and not page.evaluate("document.getElementById('app').classList.contains('signals-only')")
              and page.evaluate("document.getElementById('sigview').hidden") and st["loaded"]["ticks"] == 281, (oapi["ticks"], st["loaded"]))
        check("the pose on the page is the API's belief for that tick, in the world frame (identity map to world)",
              all(abs(a_ - b_) < 5e-4 for a_, b_ in zip(st["belief"], fr["belief"][i])) and st["truth"] is None, (st["belief"], fr["belief"][i]))
        open_lanes(page)                    # the signals' lanes are under "Other values", folded while the selected stream (the pose) lives elsewhere
        check("the signals of a run with a pose are in the state(), the inspector and the timeline too",
              st["signals"]["values"]["tacho_B"] is not None and "Signals" in page.evaluate("document.getElementById('inspBody').innerText")
              and "tacho_B" in page.evaluate("document.getElementById('inspBody').innerText")
              and page.evaluate("document.querySelectorAll('#tree .row[data-id^=\"signals.\"]').length") >= 6
              and page.evaluate("document.querySelectorAll('#lanesL .lane-l[data-lane^=\"signals.\"]').length") >= 6)
        chip = page.evaluate("document.getElementById('runinfo').textContent").replace("\xa0", " ")
        check("the chip counts the ticks and the samples", "281 ticks" in chip and "281 samples" in chip, chip)
        px = page.evaluate("window.miniview.internals.adapter.project([window.miniview.state().belief[0], window.miniview.state().belief[1], 0])")
        check("the robot is drawn: the adapter projects its pose into the stage", px is not None and 0 < px[0] < 1600 and 0 < px[1] < 1000, px)
        call(page, "window.miniview.setTime(2.0)")
        check("scene streams are missing (no layout), the belief ones are not",
              page.evaluate("document.querySelector('#tree .row[data-id=\"scene.boxes\"]')?.classList.contains('missing')") and not page.evaluate("document.querySelector('#tree .row[data-id=\"belief.pose\"]').classList.contains('missing')"))
        shot(page, f"nxt-odometry-{lib}-dark")
        ctx.close()

        # a run being written: the page follows it
        ctx, page, logs = run_page(b, live_base)
        lkey = f"nxt/unmapped/run-live-{lib}"
        live_rec = Recorder(keys.run_dir(live_dir, lkey), nxt.run_record(lkey, T0_NS, "writer", cols, None))
        for i in range(4):
            nxt.write_sample(live_rec, 0.5 * i, {"power_left": 50, "tacho_B": 100 * i, "tacho_C": 100 * i, "s3_color_name": "blue"})
        wait_until(lambda: api(live_base, f"/api/v1/runs/{lkey}")["samples"] == 4, 10, every=0.1, what="the live run's samples")
        call(page, f"window.miniview.load('unmapped', '{lkey}')")
        st = page.evaluate("window.miniview.state()")
        check("a live run opens in the Signals view following its newest sample", st["status"] == "live" and st["follow"] and st["signals"]["n"] == 4 and st["t"] == 1.5
              and page.evaluate("document.getElementById('tm-badge').disabled") is False, st["status"])
        for i in range(4, 8):
            nxt.write_sample(live_rec, 0.5 * i, {"power_left": 50, "tacho_B": 100 * i, "tacho_C": 100 * i, "s3_color_name": "red" if i > 5 else "blue"})
        page.wait_for_function("window.miniview.state().signals && window.miniview.state().signals.n === 8", timeout=15000)
        page.wait_for_function("window.miniview.state().t === 3.5", timeout=15000)
        check("samples written while the page is open arrive by record, the playhead follows the newest, the charts grow",
              page.evaluate("window.miniview.state().loaded.samples") == 8 and page.evaluate("document.querySelectorAll('#sigview .sg').length") == 4
              and page.evaluate("document.querySelector('#sigview .sg[data-sig=\"signals.s3_color_name\"]').querySelectorAll('rect.band').length") == 2)
        live_rec.add(live_rec.last_t, "end", {"verdict": "recorded"})
        live_rec.close()
        page.wait_for_function("window.miniview.state().status === 'ended'", timeout=15000)
        check("when the run ends the page says so and the follow switch goes away", eventually(page, "document.getElementById('tm-badge').disabled === true")
              and page.evaluate("document.getElementById('st-live').textContent").startswith("ended"), page.evaluate("document.getElementById('st-live').textContent"))
        check("the live page logged no error", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        ctx.close()

        # a duck run looks as before: no Signals view, no Other values (it has no signals)
        ctx, page, logs = run_page(b, base)
        call(page, "window.miniview.load('apartment', 'duck/apartment/explore9')")
        check("a duck run: no Signals view, no section Other values, the spatial views, its chip still counts ticks",
              page.evaluate("document.getElementById('sigview').hidden") and not page.evaluate("document.getElementById('app').classList.contains('signals-only')")
              and page.evaluate("document.querySelector('#tree .row[data-id=\"sec.other\"]') === null")
              and "116 ticks" in page.evaluate("document.getElementById('runinfo').textContent").replace("\xa0", " ")
              and "samples" not in page.evaluate("document.getElementById('runinfo').textContent"))
        ctx.close()
    b.close()
    for h in (httpd, odom_httpd, live_httpd):
        h.shutdown()

print("NXT PAGES", "FAIL " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
