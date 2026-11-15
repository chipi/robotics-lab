"""Live, end to end (ADR-0005): a duck log grows; `import --follow` appends to the run's MCAP; the
service follows it; both pages, opened while the run runs, grow with it and say when it ended.
Needs the system Chromium and Playwright (the viewer's dev dependency).
Run: cd viewer && uv run python tests/test_live_page.py"""

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from miniview.catalog import Catalog
from miniview.importer import import_duck
from miniview.server import make_server
from miniview.shots import ARGS, CHROMIUM

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def write_log(log: Path, stop: threading.Event) -> None:
    """A navigator at 10 Hz for about 4 s, then trapped."""
    with open(log / "ticks.jsonl", "w") as fh:
        for i in range(40):
            t = 1.0 + i * 0.1
            fh.write(json.dumps({"t": round(t, 3), "pose": [0.01 * i, 0.0, 0.0], "truth": [0.01 * i, 0.0, 0.0],
                                 "vx": 0.1, "vyaw": 0.0, "depth": [[0.01 * i + 0.4, 0.0, 0.0, "o"]]}) + "\n")
            fh.flush()
            time.sleep(0.1)
        fh.write(json.dumps({"event": "trapped", "t": 5.2}) + "\n")
        fh.flush()
    stop.set()


with tempfile.TemporaryDirectory() as tmp:
    data, log = Path(tmp) / "data", Path(tmp) / "logs" / "explore99"
    log.mkdir(parents=True)
    (log / "start.json").write_text(json.dumps({"map": [0, 0, 0], "truth": [0, 0, 0], "scale": 1.0}))
    cat = Catalog(data)
    cat.put_scene({"id": "room", "name": "A room", "kind": "test", "bounds": [-2, 2, -2, 2], "boxes": [], "hazards": []})
    httpd = make_server(cat, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    written = threading.Event()
    (log / "ticks.jsonl").write_text("")
    imp = threading.Thread(target=import_duck, args=(log, "room", data),
                           kwargs={"follow": True, "idle_s": 20, "say": lambda *_: None}, daemon=True)
    imp.start()
    writer = threading.Thread(target=write_log, args=(log, written), daemon=True)
    writer.start()
    t_end = time.monotonic() + 10
    while time.monotonic() < t_end and cat.get("explore99") is None:
        time.sleep(0.2)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM, args=ARGS)
        pages = {}
        for lib in ("three", "deck"):
            pg = b.new_page(viewport={"width": 1200, "height": 800})
            pg.goto(f"{base}/web/{lib}/index.html")
            pg.wait_for_function("window.miniview !== undefined", timeout=30000)
            pg.evaluate("window.__ready = false")
            pg.evaluate("window.miniview.load('room', 'explore99')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pages[lib] = pg
        ticks = {"three": "+document.getElementById('runinfo').textContent.match(/(\\d+) ticks/)[1]",
                 "deck": "window.miniview.internals.S.D.n"}
        first = {lib: pg.evaluate(ticks[lib]) for lib, pg in pages.items()}
        check("both pages show the live run with its follow switch", all(
            pg.evaluate("!document.getElementById('follow').hidden") for pg in pages.values()), first)
        time.sleep(2.0)
        later = {lib: pg.evaluate(ticks[lib]) for lib, pg in pages.items()}
        check("the run grows on both pages while it runs", all(later[k] > first[k] for k in pages), (first, later))
        t_cursor = pages["three"].evaluate("window.miniview.state().t")
        check("Follow live keeps the newest tick in view (three.js)", t_cursor >= 1.0 + 0.1 * (later["three"] - 1) - 0.25,
              (t_cursor, later["three"]))
        written.wait(15)
        imp.join(15)
        time.sleep(2.5)
        for lib, pg in pages.items():
            info = pg.evaluate("document.getElementById('runinfo').textContent")
            check(f"{lib}: the run ends on the page (all 40 ticks, trapped, no follow switch)",
                  pg.evaluate(ticks[lib]) == 40 and "trapped" in info and pg.evaluate("document.getElementById('follow').hidden"),
                  info)
        b.close()
    httpd.shutdown()

print("LIVE PAGE", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
