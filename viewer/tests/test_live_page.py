"""Live, end to end (ADR-0005, ADR-0011): a duck log grows; `import --follow` appends to the run's file; the service
follows it; both pages, opened while the run runs, grow with it by record (no re-download of the run), say when it ended,
and Follow live is a mode that any change of time turns off. No fixed sleeps: every wait is for a condition.
Needs the system Chromium and Playwright (the viewer's dev dependency).
Run: cd viewer && uv run python tests/test_live_page.py"""

import json
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, get, scene, serve, wait_until
from miniview.importer import import_duck
from miniview.shots import launch

check = Checks("LIVE PAGE")
KEY = "duck/room/explore99"
TICKS_RE = "+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]"


def write_ticks(log: Path, a: int, b: int) -> None:
    with open(log / "ticks.jsonl", "a") as fh:
        for i in range(a, b):
            t = 1.0 + i * 0.1
            fh.write(json.dumps({"t": round(t, 3), "pose": [0.01 * i, 0.0, 0.0], "truth": [0.01 * i, 0.0, 0.0],
                                 "vx": 0.1, "vyaw": 0.0, "depth": [[0.01 * i + 0.4, 0.0, 0.0, "o"]]}) + "\n")
        fh.flush()


with tempfile.TemporaryDirectory() as tmp:
    data, log = Path(tmp) / "data", Path(tmp) / "logs" / "explore99"
    log.mkdir(parents=True)
    (log / "start.json").write_text(json.dumps({"map": [0, 0, 0], "truth": [0, 0, 0], "scale": 1.0}))
    (log / "ticks.jsonl").write_text("")
    cat = catalog(data)
    cat.put_scene(scene("room"))
    httpd, base = serve(cat)
    imp = threading.Thread(target=import_duck, args=(log, "room", data), kwargs={"follow": True, "idle_s": 150, "say": lambda *_: None}, daemon=True)
    imp.start()
    write_ticks(log, 0, 10)
    wait_until(lambda: get(base, f"/api/v1/runs/{KEY}")[1].get("ticks") == 10 if get(base, f"/api/v1/runs/{KEY}")[0] == 200 else False, 15, what="the live run to have 10 ticks")

    with sync_playwright() as p:
        b = launch(p)
        pages, frames_requests = {}, {}
        for lib in ("three", "deck"):
            pg = b.new_page(viewport={"width": 1200, "height": 800})
            frames_requests[lib] = []
            pg.on("request", lambda r, lib=lib: frames_requests[lib].append(r.url) if "/frames" in r.url else None)
            pg.goto(f"{base}/web/{lib}/index.html")
            pg.wait_for_function("window.miniview !== undefined", timeout=30000)
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pg.evaluate(f"window.miniview.load('room', '{KEY}')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pages[lib] = pg
        ticks = lambda pg: pg.evaluate(TICKS_RE)  # noqa: E731
        # the watch page (RFC-0013), opened on `latest` while the run runs: the scene's newest run, followed
        wp = b.new_page(viewport={"width": 1200, "height": 800})
        wp.goto(f"{base}/watch/duck/room/latest")
        wp.wait_for_function("window.miniview !== undefined", timeout=30000)
        wp.wait_for_function("window.miniview.state().run !== null && window.__ready === true", timeout=30000)
        ws = wp.evaluate("window.miniview.state()")
        check("/watch/duck/room/latest opens the live run in the watch view, following it", ws["run"] == KEY and ws["status"] == "live" and ws["follow"] is True
              and ws["view"] == "watch" and wp.evaluate("!document.getElementById('follow').hidden"), (ws["run"], ws["status"], ws["follow"], ws["view"]))
        check("both pages show the live run with its follow switch, following", all(
            pg.evaluate("!document.getElementById('follow').hidden") and pg.evaluate("window.miniview.state().follow") for pg in pages.values()),
              {lib: ticks(pg) for lib, pg in pages.items()})
        check("the page's state says which run, that it is live, its seq, and that it follows",
              all((lambda s: s["run"] == KEY and s["status"] == "live" and s["seq"] > 10 and s["follow"] is True)(pg.evaluate("window.miniview.state()")) for pg in pages.values()))
        initial = {lib: len(r) for lib, r in frames_requests.items()}
        check("the run was loaded by window: a frames request with a time bound, never the whole run in one",
              all(n >= 1 and all("to=" in u for u in frames_requests[lib]) for lib, n in initial.items()), frames_requests["three"])

        # typing into a field while the live run refreshes the panels: the field survives
        pg = pages["three"]
        pg.evaluate("window.miniview.setTimeMode('belief.track', 'window', 2)")
        pg.click('#tree .row[data-id="belief.track"]')
        pg.click("#winv")
        pg.keyboard.type("7")
        write_ticks(log, 10, 20)
        for lib, q in pages.items():
            q.wait_for_function("(+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]) >= 20", timeout=15000)
        kept = pg.evaluate("[document.activeElement && document.activeElement.id, document.getElementById('winv').value]")
        pg.keyboard.press("Enter")
        n = pg.evaluate("window.miniview.config().modes['belief.track'].n")
        check("a field being typed in survives the live refreshes, and Enter applies it", kept == ["winv", "7"] and n == 7, (kept, n))

        # following: the newest tick stays in view; the run grows by record, not by re-download
        write_ticks(log, 20, 30)
        for lib, q in pages.items():
            q.wait_for_function("(+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]) >= 30", timeout=15000)
            q.wait_for_function("window.miniview.state().t >= 1.0 + 0.1 * 29 - 0.01", timeout=15000)
        check("Follow live keeps the newest tick in view on both pages", all(pg.evaluate("window.miniview.state().t") >= 3.89 for pg in pages.values()),
              {lib: pg.evaluate("window.miniview.state().t") for lib, pg in pages.items()})
        wp.wait_for_function("(+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]) >= 30 && window.miniview.state().t >= 1.0 + 0.1 * 29 - 0.01", timeout=15000)
        check("the watch page follows the live run: the newest tick is in view, the eye is drawn from it", wp.evaluate("window.miniview.state().t") >= 3.89
              and wp.evaluate("window.miniview.state().follow") is True and wp.evaluate("window.miniview.state().eye") is not None, wp.evaluate("window.miniview.state().t"))
        check("the run grew by 20 ticks and the pages asked for no frames again",
              {lib: len(r) for lib, r in frames_requests.items()} == initial, {lib: len(r) for lib, r in frames_requests.items()})
        check("the live stream's seq on the page is the server's", all(
            pg.evaluate("window.miniview.state().seq") == get(base, f"/api/v1/runs/{KEY}")[1]["seq"] for pg in pages.values()))

        # a change of time, by script, turns Follow live off; the run goes on growing, the playhead stays
        for lib, q in pages.items():
            q.evaluate("window.miniview.setTime(2.0)")
            check(f"{lib}: setTime by script turns Follow live off, and the switch shows it",
                  q.evaluate("window.miniview.state().follow") is False and not q.evaluate("document.getElementById('follow-on').checked"))
        write_ticks(log, 30, 36)
        for lib, q in pages.items():
            q.wait_for_function("(+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]) >= 36", timeout=15000)
            t = q.evaluate("window.miniview.state().t")
            check(f"{lib}: with Follow live off the script's time is not overridden by the run growing", abs(t - 2.0) < 1e-9, t)
        # a change by hand (a click on the first-tick button) does the same, and the switch turns it on again
        pg = pages["deck"]
        pg.click("#follow-on")
        pg.wait_for_function("window.miniview.state().t >= 1.0 + 0.1 * 35 - 0.01", timeout=15000)
        check("turning the switch on follows the newest tick again", pg.evaluate("window.miniview.state().follow") is True)
        pg.click("#tFirst")
        check("a click on 'first tick' turns Follow live off", pg.evaluate("window.miniview.state().follow") is False
              and abs(pg.evaluate("window.miniview.state().t") - 1.0) < 1e-6)

        # the end
        with open(log / "ticks.jsonl", "a") as fh:
            fh.write(json.dumps({"event": "trapped", "t": 5.0}) + "\n")
        imp.join(30)
        for lib, q in pages.items():
            q.wait_for_function("document.getElementById('runinfo').textContent.includes('trapped')", timeout=20000)
            q.wait_for_function("document.getElementById('follow').hidden", timeout=20000)
            info = q.evaluate("document.getElementById('runinfo').textContent")
            check(f"{lib}: the run ends on the page (all 36 ticks, trapped, no follow switch), status ended", ticks(q) == 36 and "trapped" in info
                  and q.evaluate("window.miniview.state().status") == "ended", info)
        wp.wait_for_function("document.getElementById('runinfo').textContent.includes('trapped') && document.getElementById('follow').hidden", timeout=20000)
        check("the watch page shows the run end: the event and the verdict in the decisions, status ended",
              wp.evaluate("window.miniview.state().status") == "ended" and wp.evaluate("[...document.querySelectorAll('#inspBody .dec .dr')].map((e) => e.textContent)") == ["trapped", "verdict"],
              wp.evaluate("[...document.querySelectorAll('#inspBody .dec .dr')].map((e) => e.textContent)"))
        for lib, q in pages.items():
            q.wait_for_function("window.miniview.internals.M.pres.t1 === window.miniview.internals.M.run.t1", timeout=20000)
        check("a run that is not live is not followed: the pages asked for no frames after the first windows",
              {lib: len(r) for lib, r in frames_requests.items()} == initial)
        b.close()
    httpd.shutdown()

check.done()
