"""Live, end to end (ADR-0005, ADR-0011): a duck log grows; `import --follow` appends to the run's file; the service
follows it; both pages, opened while the run runs, grow with it by record (no re-download of the run), say when it ended,
and Follow live is a mode that any change of time turns off. No fixed sleeps: every wait is for a condition.
Needs the system Chromium and Playwright (the viewer's dev dependency).
Run: cd apps/observatory && uv run python tests/test_live_page.py"""

import json
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, get, scene, serve, wait_until
from observatory.importer import import_duck
from observatory.shots import launch

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


FRIDGE = {"id": "fridge_1", "kind": "fridge", "x": 1.5, "y": 0.5, "n": 6, "confirmed": True, "landmark": 1.0, "permanence": "fixed", "first_t": 3.0, "last_t": 3.9,
          "confidence": 0.9, "sources": ["sim_camera"], "evidence": [], "parts": [[1.5, 0.5, 0.3, 0.25, 0.4, 0.0, 1.7]]}
CABINET = {"id": "cabinet_1", "kind": "cabinet", "x": 0.5, "y": -0.5, "n": 1, "confirmed": False, "landmark": 0.5, "permanence": "fixed", "first_t": 3.5, "last_t": 3.5,
           "confidence": 0.6, "sources": ["sim_camera"], "evidence": [], "parts": [[0.5, -0.5, 0.25, 0.25, 0.0, 0.0, 0.6]]}
SEEN = {"kind": "fridge", "x": 1.0, "y": 0.4, "radius": 0.4, "z0": 0.0, "z1": 1.7, "range_m": 1.08, "confidence": 0.8, "source": "sim_camera"}
# the navigator's rows for the semantic map (RFC-0016), as it writes them, at the time of the newest tick of the first batches (3.9 s)
SEMANTIC_ROWS = [{"event": "semantic", "t": 3.9, "changes": [["new", "cabinet_1"], ["confirmed", "fridge_1"]], "objects": [CABINET, FRIDGE]},
                 {"event": "sighting", "t": 3.9, "pose": [0.2, 0.0, 0.0], "hfov_deg": 60, "range_m": 3.0, "seen": [SEEN]},
                 {"event": "room", "t": 3.9, "room": "kitchen", "votes": {"kitchen": 0.4, "office": 0.1}}]
ANOMALY_ROW = {"event": "anomaly", "t": 3.9, "anomaly": "joint_overload", "source": "robot", "module": "body", "severity": "major", "detector": "current_held",
               "version": 1, "summary": "right_knee 400 mA for 1.0 s", "values": {"current_ma": 400, "margin_unit": "mA"}, "margin": 280,
               "where": {"frame": "map", "belief": [0.29, 0.0]}, "evidence": {}, "related": [], "duration_s": 1.0}


def write_rows(log: Path, rows: list) -> None:
    with open(log / "ticks.jsonl", "a") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
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

        # the semantic map arriving on the live stream (ADR-0019): objects and sighting records for a run that had none when the pages opened it
        write_rows(log, SEMANTIC_ROWS)
        sem_state = "window.miniview.state().semantic"
        for lib, q in pages.items():
            q.wait_for_function(f"{sem_state} && {sem_state}.sighting && {sem_state}.room", timeout=15000)
        wp.wait_for_function(f"{sem_state} && {sem_state}.sighting && {sem_state}.room", timeout=15000)
        api = get(base, f"/api/v1/runs/{KEY}/state?t=3.9")[1].get("semantic")
        for lib, q in [*pages.items(), ("watch", wp)]:
            st = q.evaluate(sem_state)
            check(f"{lib}: the objects, the current sighting and the room that arrived live are in state().semantic, as the API's /state has them",
                  st == api and [o["id"] for o in st["objects"]] == ["cabinet_1", "fridge_1"] and [o["confirmed"] for o in st["objects"]] == [False, True]
                  and st["sighting"]["seen"] == [{"kind": "fridge", "range_m": 1.08, "confidence": 0.8}] and st["room"]["name"] == "kitchen", (st, api))
            streams = {x["id"]: x for x in q.evaluate("window.miniview.internals.shell().M.run.streams")}
            check(f"{lib}: the two semantic streams are now counted and no longer missing (one snapshot, one sighting)",
                  streams["semantic.objects"]["count"] == 1 and streams["semantic.sighting"]["count"] == 1 and not streams["semantic.objects"]["missing"] and not streams["semantic.sighting"]["missing"],
                  [streams["semantic.objects"], streams["semantic.sighting"]])
        drawn = "(() => { const s = window.miniview.internals.adapter.semantic(); return !!s && s.objects === 2 && s.sighting !== null; })()"
        pages["three"].wait_for_function(drawn, timeout=15000)               # the page draws a moment after the record (it batches what arrives)
        wp.wait_for_function(drawn, timeout=15000)
        sem3 = pages["three"].evaluate("window.miniview.internals.adapter.semantic()")
        check("the 3D page draws them live: two objects, one confirmed and labelled, the sighting with what it saw",
              sem3["objects"] == 2 and sem3["confirmed"] == 1 and sem3["labels"] == ["fridge"] and sem3["sighting"]["seen"][0]["kind"] == "fridge"
              and sem3["objectsVisible"] and sem3["sightingVisible"] and len(sem3["labelPx"]) == 2, sem3)
        wsem = wp.evaluate("window.miniview.internals.adapter.semantic()")
        check("the watch page draws them too", wsem["objects"] == 2 and wsem["sighting"] is not None, wsem)
        pages["three"].wait_for_function("[...document.querySelectorAll('#legend span')].some((e) => e.textContent === 'Detection')", timeout=10000)
        check("the legend of the 3D page gains the semantic entries once the records arrive",
              {"Object", "Landmark", "Field of view", "Detection"} <= set(pages["three"].evaluate("[...document.querySelectorAll('#legend span')].map((e) => e.textContent)")))
        check("the deck page, which draws no semantic map, keeps its legend free of the semantic entries (and says so: no `semantic()` in its adapter)",
              {"Object", "Landmark", "Field of view", "Detection"}.isdisjoint(pages["deck"].evaluate("[...document.querySelectorAll('#legend span')].map((e) => e.textContent)"))
              and pages["deck"].evaluate("window.miniview.internals.adapter.semantic === undefined"))
        check("the run's file has them: the service's /semantic lists the snapshot and the sighting",
              (lambda r: [len(r["objects"]), len(r["sightings"])])(get(base, f"/api/v1/runs/{KEY}/semantic")[1]) == [1, 1])
        check("the room event went through the live path as an event with its room and votes",
              [(e["room"], e["votes"]) for e in get(base, f"/api/v1/runs/{KEY}")[1]["events"] if e["kind"] == "room"] == [("kitchen", {"kitchen": 0.4, "office": 0.1})])

        # an anomaly arriving on the live stream (RFC-0019): the run had none when the pages opened it; the alarms lane and the layer gain it
        check("before the anomaly the alarms lane is hidden on both pages",
              all(q.evaluate("document.getElementById('alane').hidden && !document.querySelector('#alane .mk.al')") for q in pages.values()))
        write_rows(log, [ANOMALY_ROW])
        for lib, q in pages.items():
            q.wait_for_function("document.querySelectorAll('#alane .mk.al').length === 1", timeout=15000)
            q.wait_for_function("(window.miniview.internals.adapter.anomalies() || { pins: [] }).pins.length === 1", timeout=15000)
            a = q.evaluate("window.miniview.internals.adapter.anomalies()")
            check(f"{lib}: the anomaly that arrived live is one mark on the shown alarms lane and one pin at the belief, at its time",
                  q.evaluate("!document.getElementById('alane').hidden && !document.getElementById('alabel').hidden") and a["visible"]
                  and abs(a["pins"][0]["t"] - 3.9) < 0.01 and all(abs(u - v) < 1e-6 for u, v in zip(a["pins"][0]["belief"][:2], ANOMALY_ROW["where"]["belief"])), a)
        check("the service keeps its record with the event",
              [e["anomaly"]["anomaly"] for e in get(base, f"/api/v1/runs/{KEY}")[1]["events"] if e["kind"] == "anomaly"] == ["joint_overload"])

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
        check("the watch page shows the run end: the room event, the anomaly, the event and the verdict in the decisions, status ended",
              wp.evaluate("window.miniview.state().status") == "ended" and wp.evaluate("[...document.querySelectorAll('#inspBody .dec .dr')].map((e) => e.textContent)") == ["room", "anomaly", "trapped", "verdict"],
              wp.evaluate("[...document.querySelectorAll('#inspBody .dec .dr')].map((e) => e.textContent)"))
        for lib, q in pages.items():
            q.wait_for_function("window.miniview.internals.M.pres.t1 === window.miniview.internals.M.run.t1", timeout=20000)
        check("a run that is not live is not followed: the pages asked for no frames after the first windows",
              {lib: len(r) for lib, r in frames_requests.items()} == initial)
        b.close()
    httpd.shutdown()

check.done()
