"""The anomalies the robot recorded, in the pages (RFC-0019 §4.1), in headless Chromium, three.js and deck.gl: an alarms lane on the timeline
(one mark per anomaly, coloured by severity, the source told apart, a click seeks, hidden when the run has none), the inspector's record of
the anomaly at the playhead, the `anomalies` layer (a pin where the robot believed it was, through the epoch in the world frame; a ring where it
was, joined to it by a line; a click on a pin seeks), and a page opened at `#t=`. Needs the system Chromium and Playwright.
Run: cd apps/observatory && uv run python tests/test_anomaly_pages.py"""

import math
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, boot, catalog, make_run, serve, tick
from observatory.shots import launch

check = Checks("ANOMALY PAGES")
EPOCH = [0.5, -0.2, 0.3]                      # map -> world: a shift and a turn, so a pin drawn in the wrong frame shows
SCENE = {"id": "room", "name": "A room", "kind": "test", "bounds": [-1, 3, -1.5, 1.5], "boxes": [], "hazards": []}


def compose(a, b):
    c, s = math.cos(a[2]), math.sin(a[2])
    return [a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], a[2] + b[2]]


def anomaly(t, name, severity, source, belief, truth=None, margin=0.12, values=None, duration=0.4):
    raw = {"event": "anomaly", "anomaly": name, "source": source, "module": "mapd" if source == "robot" else "harness", "severity": severity,
           "detector": f"{name}_rule", "version": 1, "summary": f"{name}: made up for the test", "values": values or {"jump_m": 0.9, "margin_unit": "m"},
           "margin": margin, "where": {"frame": "map", "belief": belief}, "evidence": {}, "related": [], "duration_s": duration}
    if truth:
        raw["truth"] = truth
    return (t, "event", {"kind": "anomaly", "text": f"anomaly {name} ({severity}): {raw['summary']}", "notable": True, "t_src": t, "raw": raw})


B1, B2, B3, B4 = [0.2, 0.05], [0.6, -0.1], [1.0, 0.3], [1.4, 0.0]
TRUTH1, TRUTH2 = compose(EPOCH, [0.35, 0.1, 0.0]), compose(EPOCH, [0.7, -0.2, 0.0])
ANOMALIES = [anomaly(1.5, "pose_jump", "major", "robot", B1, TRUTH1), anomaly(2.2, "wall_graze", "critical", "harness", B2, TRUTH2),
             anomaly(3.0, "slow_leg", "minor", "robot", B3, margin=0.7, values={"speed_mps": 0.04, "margin_unit": "rad"}), anomaly(3.5, "odd_tilt", "info", "robot", B4)]
BELIEFS = {1.5: B1, 2.2: B2, 3.0: B3, 3.5: B4}


def records(with_anomalies=True):
    out = [(0.0, "epoch", {"map_to_world": EPOCH})]
    for k in range(30):
        b = [0.05 * k, 0.01 * k, 0.2]
        out.append(tick(round(1.0 + 0.1 * k, 3), b[0], belief=b, truth=compose(EPOCH, b), cmd=[0.3, 0.0], depth=[]))
    out.append((3.95, "end", {"verdict": "reached"}))
    return sorted(out + (ANOMALIES if with_anomalies else []), key=lambda r: r[0])


RGB = "(name) => { const e = document.createElement('i'); e.style.color = `var(--${name})`; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; }"
def rgb(h):
    """A pin's colour as getComputedStyle gives it. The three page's pins carry their token's CSS colour since U11 (a number before)."""
    if isinstance(h, str):
        h = h.strip()
        if h.startswith("rgb"):
            return h.replace("rgba", "rgb").rsplit(",", 1)[0] + ")" if h.count(",") == 3 else h
        h = h.lstrip("#")
        h = "".join(c + c for c in h) if len(h) in (3, 4) else h
        h = int(h[:6], 16)
    return f"rgb({(h >> 16) & 255}, {(h >> 8) & 255}, {h & 255})"
close = lambda a, b, tol=1e-3: a is not None and b is not None and all(abs(x - y) < tol for x, y in zip(a, b))  # noqa: E731

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(SCENE)
    make_run(data, "duck/room/anom1", records(), started_at_ns=1_800_000_000 * 10**9)
    make_run(data, "duck/room/clean1", records(False), started_at_ns=1_700_000_000 * 10**9)
    httpd, base = serve(cat, follow=False)

    def ready(page, t=60000):
        page.wait_for_function("window.__ready === true", timeout=t)

    def until(page, js, t=4000):
        """Wait for a condition a click should bring about; whether it came is the check's to say."""
        try:
            page.wait_for_function(js, timeout=t)
        except Exception:
            pass

    def call(page, js):
        page.evaluate("window.__ready = false")
        r = page.evaluate(js)
        ready(page)
        return r

    def open_page(b, url, width=1600, height=1000, scheme="dark"):
        page = b.new_context(viewport={"width": width, "height": height}, color_scheme=scheme).new_page()
        page.logs = []
        # a deck.gl pick reads pixels back; CI's software GL says so as a "GL Driver Message" performance note (2ccbaa1, job 137639994521)
        page.on("console", lambda m: page.logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") and "404" not in m.text
                and "GL Driver Message" not in m.text else None)
        page.on("pageerror", lambda e: page.logs.append(f"pageerror: {e}"))
        boot(page, url, "window.miniview !== undefined", 30000)
        ready(page)
        page.wait_for_function("window.miniview.state().run !== null", timeout=30000)
        page.evaluate("window.miniview.whenLoaded()")
        return page

    pins = "window.miniview.internals.adapter.anomalies()"

    with sync_playwright() as p:
        b = launch(p)
        for lib in ("three", "deck"):
            page = open_page(b, f"{base}/web/{lib}/#scene=room&run=duck/room/anom1&view=top")
            check(f"[{lib}] the page opens with no errors", not page.logs, page.logs)
            streams = {s["id"]: s for s in page.evaluate("window.miniview.internals.shell().M.run.streams")}
            check(f"[{lib}] the run lists the anomalies stream, counted, and it is on", streams["anomalies"]["count"] == 4
                  and "anomalies" not in page.evaluate("window.miniview.state().hidden"), streams["anomalies"])
            check(f"[{lib}] the stream is a row of the outliner", page.evaluate("window.miniview.internals.shell().M.run.streams.some((s) => s.id === 'anomalies')")
                  and "anomalies" in page.evaluate("[...document.querySelectorAll('#tree .row')].map((r) => r.dataset.id)"))

            # ---- the alarms lane ---------------------------------------------------------------------------------------
            marks = page.evaluate("[...document.querySelectorAll('#alane .mk.al')].map((m) => ({ cls: m.className, ev: +m.dataset.ev, left: m.style.left, color: getComputedStyle(m).color, radius: getComputedStyle(m.firstChild).borderRadius }))")
            err, warn, dim = (page.evaluate(f"({RGB})('{n}')") for n in ("status-error", "status-warn", "status-neutral"))
            pin_dim = page.evaluate(f"({RGB})('text-2')")     # the pins are drawn by the page adapters, which still use --text-2 for info; the lane takes the status colour
            check(f"[{lib}] must fail: one mark per anomaly on the alarms lane, the lane and its label shown, the events lane still there",
                  len(marks) == 4 and page.evaluate("!document.getElementById('alane').hidden && !document.getElementById('alabel').hidden")
                  and page.evaluate("document.querySelectorAll('#mlane .mk').length") >= 4, marks)
            check(f"[{lib}] must fail: marks are coloured by severity (critical and major the error colour, minor the warn colour, info the neutral status colour; U10 moved info from text-dim)",
                  [m["color"] for m in marks] == [err, err, warn, dim] and len({err, warn, dim}) == 3, ([m["color"] for m in marks], err, warn, dim))
            check(f"[{lib}] must fail: the source is told apart (the harness's mark has another shape than the robot's)",
                  marks[1]["cls"].split().count("harness") == 1 and "harness" not in marks[0]["cls"] and marks[1]["radius"] != marks[0]["radius"], marks)
            call(page, "window.miniview.setTime(0)")
            page.hover("#alane .mk.al.critical")
            tip = page.evaluate("document.getElementById('tip').textContent")
            check(f"[{lib}] a tooltip names the anomaly, its severity and its summary", not page.evaluate("document.getElementById('tip').hidden")
                  and "wall_graze" in tip and "critical" in tip and "made up for the test" in tip, tip)
            page.click("#alane .mk.al.minor")
            until(page, "Math.abs(window.miniview.state().t - 3.0) < 0.06")
            check(f"[{lib}] must fail: a click on a mark seeks to the anomaly's time", abs(page.evaluate("window.miniview.state().t") - 3.0) < 0.06, page.evaluate("window.miniview.state().t"))

            page.screenshot(path=str(Path(tempfile.gettempdir()) / f"obs-anomalies-{lib}.png"))

            # ---- the inspector ---------------------------------------------------------------------------------------
            call(page, "window.miniview.setTime(1.6)")
            insp = page.evaluate("document.querySelector('#inspBody .anomaly')?.innerText || ''")
            check(f"[{lib}] must fail: the inspector shows the anomaly at the playhead: name, severity, source, module, detector, summary",
                  all(s in insp for s in ("pose_jump", "major", "robot", "mapd", "pose_jump_rule", "made up for the test")), insp)
            check(f"[{lib}] ... its margin with its unit (metres by default), its duration and its values",
                  "0.120" in insp and "0.40" in insp and "jump_m" in insp and "0.900" in insp
                  and page.evaluate("[...document.querySelectorAll('#inspBody .anomaly .kv')].find((k) => k.querySelector('.k').textContent === 'Margin').querySelector('.u').textContent") == "m", insp)
            check(f"[{lib}] ... as a badge in the severity's status: its glyph the error colour, its word beside it", page.evaluate("(() => { const b = document.querySelector('#inspBody .anomaly .kv .ui-badge'); return b.dataset.status + '/' + getComputedStyle(b.querySelector('.ui-glyph')).color; })()") == "error/" + err)
            call(page, "window.miniview.setTime(3.1)")
            insp = page.evaluate("document.querySelector('#inspBody .anomaly')?.innerText || ''")
            check(f"[{lib}] a margin in another unit says it (radians), and the unit key is not listed as a value", "0.700" in insp and "rad" in insp and "margin_unit" not in insp and "speed_mps" in insp, insp)
            call(page, "window.miniview.setTime(1.2)")
            check(f"[{lib}] before the first anomaly the inspector has none", page.evaluate("!document.querySelector('#inspBody .anomaly')"))

            # ---- the layer, in the world frame ---------------------------------------------------------------------
            call(page, "window.miniview.setFrame('world')")
            a = page.evaluate(pins)
            by_t = {round(q["t"], 3): q for q in a["pins"]}
            check(f"[{lib}] the anomalies layer exists, is shown, and holds one pin per anomaly", a["visible"] and len(a["pins"]) == 4, a)
            want = {t: compose(EPOCH, [*bf, 0.0])[:2] for t, bf in BELIEFS.items()}
            check(f"[{lib}] must fail: the belief pin is in the world frame: the map-frame point through the epoch in force at the anomaly's time",
                  all(close(by_t[t]["belief"][:2], want[t]) for t in want), [(t, by_t[t]["belief"], want[t]) for t in want])
            check(f"[{lib}] ... and that is not where the map frame puts it (the epoch shows)", all(math.dist(by_t[t]["belief"][:2], BELIEFS[t]) > 0.1 for t in BELIEFS))
            check(f"[{lib}] a run with truth: a ring at the truth, in the world frame, for the anomalies that have one",
                  close(by_t[1.5]["truth"][:2], TRUTH1[:2]) and close(by_t[2.2]["truth"][:2], TRUTH2[:2]) and by_t[3.0]["truth"] is None, [by_t[t]["truth"] for t in by_t])
            if lib == "three":
                cols = [rgb(q["hex"]) for q in a["pins"]]
            else:
                cols = [f"rgb({q['color'][0]}, {q['color'][1]}, {q['color'][2]})" for q in a["pins"]]
            check(f"[{lib}] must fail: the pins are coloured by severity, as the lane's marks are", cols == [err, err, warn, pin_dim], (cols, err, warn, pin_dim))
            call(page, "window.miniview.setFrame('map')")
            a = page.evaluate(pins)
            by_t = {round(q["t"], 3): q for q in a["pins"]}
            check(f"[{lib}] must fail: in the map frame the belief pin is drawn as it is, and there is no truth ring",
                  all(close(by_t[t]["belief"][:2], BELIEFS[t]) for t in BELIEFS) and all(q["truth"] is None for q in a["pins"]), a)
            call(page, "window.miniview.setFrame('world')")
            call(page, "window.miniview.setVisible('anomalies', false)")
            check(f"[{lib}] the layer switches off alone, from the outliner's stream", page.evaluate(pins)["visible"] is False and "anomalies" in page.evaluate("window.miniview.state().hidden"))
            call(page, "window.miniview.setVisible('anomalies', true)")

            # ---- a click on a pin seeks ----------------------------------------------------------------------------
            call(page, "window.miniview.setTime(0)")
            a = page.evaluate(pins)
            px = page.evaluate(f"window.miniview.internals.adapter.project({[*[q for q in a['pins'] if abs(q['t'] - 2.2) < 1e-6][0]['belief'][:2], 0.05]})")
            page.mouse.click(px[0], px[1])
            until(page, "Math.abs(window.miniview.state().t - 2.2) < 0.06")
            check(f"[{lib}] must fail: a click on a pin seeks to its anomaly", abs(page.evaluate("window.miniview.state().t") - 2.2) < 0.06, (px, page.evaluate("window.miniview.state().t")))

            # ---- the light theme -----------------------------------------------------------------------------------
            page.click("#themeBtn")
            page.wait_for_function("window.miniview.config().theme === 'light'")
            ready(page)
            err_l = page.evaluate(f"({RGB})('status-error')")
            marks_l = page.evaluate("[...document.querySelectorAll('#alane .mk.al')].map((m) => getComputedStyle(m).color)")
            a = page.evaluate(pins)
            cols_l = [rgb(q["hex"]) for q in a["pins"]] if lib == "three" else [f"rgb({q['color'][0]}, {q['color'][1]}, {q['color'][2]})" for q in a["pins"]]
            check(f"[{lib}] in the light theme the marks and the pins take the light theme's colours (not the dark's)", err_l != err and marks_l[0] == err_l and cols_l[0] == err_l, (err, err_l, marks_l, cols_l))
            check(f"[{lib}] no page errors", not page.logs, page.logs)

            # ---- a run with no anomaly ------------------------------------------------------------------------------
            clean = open_page(b, f"{base}/web/{lib}/#scene=room&run=duck/room/clean1&view=top")
            check(f"[{lib}] must fail: a run with no anomaly has no alarms lane (it and its label are hidden), no inspector record, and its layer is missing",
                  clean.evaluate("document.getElementById('alane').hidden && document.getElementById('alabel').hidden && document.getElementById('alane').children.length === 0")
                  and not clean.evaluate("document.querySelector('#inspBody .anomaly')")
                  and {s["id"]: s for s in clean.evaluate("window.miniview.internals.shell().M.run.streams")}["anomalies"]["missing"] and not clean.logs, clean.logs)

            # ---- open at a moment (#t=) --------------------------------------------------------------------------
            for t_hash, want_t in (("2.2", 2.2), ("99", 3.9), ("-5", 1.0)):
                at = open_page(b, f"{base}/web/{lib}/#scene=room&run=duck/room/anom1&view=top&t={t_hash}")
                got = at.evaluate("window.miniview.state().t")
                check(f"[{lib}] must fail: a page opened at #t={t_hash} lands at {want_t} s (clamped to the run's span)", abs(got - want_t) < 0.06, got)
            at = open_page(b, f"{base}/web/{lib}/#scene=room&run=duck/room/anom1&view=top&frame=map&t=2.2")
            check(f"[{lib}] #t= combines with the other hash keys (frame=map)", at.evaluate("window.miniview.state().frame") == "map" and abs(at.evaluate("window.miniview.state().t") - 2.2) < 0.06)

            # ---- phone width ---------------------------------------------------------------------------------------
            ph = open_page(b, f"{base}/web/{lib}/#scene=room&run=duck/room/anom1&view=top", width=390, height=844)
            sw = ph.evaluate("[document.documentElement.scrollWidth, document.body.scrollWidth, innerWidth]")
            box = ph.evaluate("(() => { const r = document.querySelector('#alane .mk.al').getBoundingClientRect(); return [r.left, r.right, r.width]; })()")
            check(f"[{lib}] must fail: at 390 px there is no sideways scroll and the alarms lane's marks are on the screen", max(sw[:2]) <= sw[2] and 0 <= box[0] and box[1] <= 390 and box[2] > 0, (sw, box))
            check(f"[{lib}] ... and no console error", not ph.logs, ph.logs)

        # ---- the watch page opened at a moment ------------------------------------------------------------------
        w = open_page(b, f"{base}/watch/duck/room/anom1#t=2.2")
        st = w.evaluate("window.miniview.state()")
        check("must fail: the watch page opened at #t=2.2 lands at 2.2 s and does not follow the live end", abs(st["t"] - 2.2) < 0.06 and st["follow"] is False, (st["t"], st["follow"]))
        w0 = open_page(b, f"{base}/watch/duck/room/anom1")
        check("the watch page with no t follows, as it did", w0.evaluate("window.miniview.state().follow") is True)
        check("the watch page shows the alarms lane too, and no console error", w.evaluate("document.querySelectorAll('#alane .mk.al').length") == 4 and not w.logs, w.logs)
        b.close()
    httpd.shutdown()

check.done()
