"""The page's run store (ADR-0011), in a real browser, both pages: a run loaded by window then by record, renderers that
take appends, a seq gap that reconnects, an epoch that redraws, load() that rejects, an event kind with pattern
characters. No fixed sleeps. Run: cd viewer && uv run python tests/test_store_page.py"""

import json
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, make_run, scene, serve, tick, wait_until
from miniview.shots import launch

check = Checks("STORE PAGE")
HEAD = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
ODD = "odd(kind[x"          # not a valid regular expression
COUNT_JS = """(() => { const a = window.miniview.internals.adapter, c = { setRun: 0, append: 0, ranges: [] };
  const sr = a.setRun.bind(a), ap = a.append.bind(a);
  a.setRun = (...x) => { c.setRun++; return sr(...x); };
  a.append = (r) => { c.append++; c.ranges.push([r.i0, r.i1]); return ap(r); };
  window.__calls = c; return true; })()"""


def long_run():
    """200 s at 10 Hz: 2000 ticks, a plan every 10 s, a map every 20 s, an event at 100 s."""
    recs = list(HEAD)
    for i in range(2000):
        t = round(i * 0.1, 3)
        recs.append(tick(t, 0.001 * i))
        if i % 100 == 50:
            recs.append((t, "plan", {"path": [[0, 0], [1, 0.001 * i]]}))
        if i % 200 == 60:
            recs.append((t, "world", {"grid": {"res": 0.1, "origin": [-1.0, -1.0], "w": 4, "h": 4, "cells": "??..#?.." * 2},
                                      "obstacles": [[0.5, 0.5]], "drops": []}))
        if i == 1000:
            recs.append((t, "event", {"kind": "cliff_stop", "text": "cliff_stop drop_m 0.4"}))
    return recs


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(scene("room"))
    make_run(data, "duck/room/long1", long_run())
    make_run(data, "duck/room/odd1", HEAD + [tick(1.0, 0.0), (1.5, "event", {"kind": ODD, "text": ODD + " with text after it"}), tick(2.0, 0.1)])
    make_run(data, "duck/room/dup", HEAD + [tick(1.0, 0.0)])
    make_run(data, "rover/room/dup", HEAD + [tick(1.0, 0.5)])
    lives = {lib: make_run(data, f"duck/room/live_{lib}", HEAD + [tick(1.0, 0.0), tick(1.1, 0.1)], close=False) for lib in ("three", "deck")}
    httpd, base = serve(cat)

    with sync_playwright() as p:
        b = launch(p)
        for lib in ("three", "deck"):
            pg = b.new_page(viewport={"width": 1200, "height": 800})
            errors, frames = [], []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("request", lambda r: frames.append(r.url) if "/frames" in r.url else None)
            pg.goto(f"{base}/web/{lib}/index.html")
            pg.wait_for_function("window.miniview !== undefined", timeout=30000)
            pg.wait_for_function("window.__ready === true", timeout=30000)
            S = lambda: pg.evaluate("window.miniview.state()")   # noqa: E731
            L = lambda name: f"[{lib}] {name}"                    # noqa: E731

            live = lives[lib]
            # ---- the state before any run, and load() that rejects ------------------------------------------------
            s0 = S()
            check(L("on the scenes page, state() names no run"), s0["run"] is None and s0["status"] is None and s0["seq"] is None and "follow" in s0, s0)
            pg.evaluate(COUNT_JS)
            res = pg.evaluate("window.miniview.load('room', 'duck/room/long1').then(() => 'ok').catch((e) => 'rejected: ' + e.message)")
            check(L("load() opens a run by key"), res == "ok" and S()["run"] == "duck/room/long1", res)
            bad = {"unknown scene": "window.miniview.load('nowhere', 'duck/room/long1')", "unknown run": "window.miniview.load('room', 'nope')",
                   "unknown key": "window.miniview.load('room', 'duck/room/nope')", "ambiguous name": "window.miniview.load('room', 'dup')"}
            out = {k: pg.evaluate(f"{js}.then(() => 'resolved').catch((e) => 'rejected: ' + e.message)") for k, js in bad.items()}
            check(L("load() rejects an unknown scene, an unknown run, an unknown key, an ambiguous name (and says which)"),
                  all(v.startswith("rejected: ") for v in out.values()) and "duck/room/dup" in out["ambiguous name"] and "rover/room/dup" in out["ambiguous name"], out)
            check(L("a rejected load() leaves the open run as it was (it never opens another)"), S()["run"] == "duck/room/long1", S()["run"])
            check(L("a name that only one run has opens that run, by key"),
                  pg.evaluate("window.miniview.load('room', 'odd1').then(() => window.miniview.state().run)") == "duck/room/odd1")

            # ---- by window, then in the background; the renderer takes appends, no rebuild ---------------------------------
            pg.evaluate(COUNT_JS)
            held, release, seen = [], threading.Event(), []

            def gate(route, request):
                seen.append(request.url)
                if len(seen) == 1:
                    return route.continue_()
                held.append(1)
                release.wait(30)                                  # the later windows wait until the test says so
                route.continue_()

            pg.route("**/duck/room/long1/frames?*", gate)
            frames.clear()
            pg.evaluate("window.miniview.load('room', 'duck/room/long1')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            st = S()
            check(L("the page draws from the first window: ticks up to 60 s (+ the 30 s lookahead rounds to its window) are in, the rest of the run is not yet"),
                  0 < st["loaded"]["ticks"] < 2000 and st["loaded"]["of"] == 2000 and not st["loaded"]["complete"], st["loaded"])
            check(L("the state at the playhead is already right (tick 0 at t = 0)"), st["tick"] == 0 and st["t"] == 0.0, (st["tick"], st["t"]))
            calls = pg.evaluate("window.__calls")
            check(L("the renderer was given the run once (setRun), not rebuilt for each window"), calls["setRun"] == 1, calls)
            wait_until(lambda: len(held) >= 1, 10, what="the background window to be requested")
            check(L("the rest comes in the background, one window at a time, each bounded in time"),
                  all("to=" in u for u in seen) and any("from=" in u for u in seen), seen)
            release.set()
            pg.evaluate("window.miniview.whenLoaded()")
            pg.wait_for_function("window.miniview.state().loaded.complete === true", timeout=30000)
            calls = pg.evaluate("window.__calls")
            ranges = calls["ranges"]
            check(L("each window reached the renderer as an append of the next ticks, in order, without a hole"),
                  calls["setRun"] == 1 and calls["append"] >= 2 and ranges[0][0] == st["loaded"]["ticks"] and all(a[1] == b[0] or b[0] == b[1] or a[1] == a[0] for a, b in zip(ranges, ranges[1:]))
                  and max(r[1] for r in ranges) == 2000, calls)
            check(L("the whole run is loaded: 2000 ticks, 20 plans, 10 maps' worth of frames"), pg.evaluate("window.miniview.whenLoaded().then((x) => x.ticks)") == 2000)
            pg.evaluate("window.miniview.setTime(150.0)")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            s = S()
            check(L("setTime() far into the run: the tick, the plan and the map in force there are right"),
                  s["tick"] == 1500 and abs(s["t"] - 150.0) < 1e-9 and abs(s["belief"][0] - 1.5) < 1e-6, (s["tick"], s["belief"]))
            pg.unroute("**/duck/room/long1/frames?*")
            for sid in ("belief.track", "truth.track", "sensors.depth.obstacle", "sensors.depth.floor"):
                pg.evaluate(f"window.miniview.setTimeMode('{sid}', 'upto')")
            pg.evaluate("window.miniview.setTime(150.0)")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            appended = pg.locator("#stage").screenshot()
            pg.evaluate("(() => { const i = window.miniview.internals; i.adapter.setRun(i.M.run, i.M.fr); i.adapter.draw(true); })()")
            pg.evaluate("window.miniview.setTime(150.0)")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            rebuilt = pg.locator("#stage").screenshot()
            check(L("what was drawn from appended windows is pixel for pixel what a full build of the same run draws (tracks up to t, depth, plan, map)"),
                  appended == rebuilt and len(appended) > 5000, (len(appended), len(rebuilt)))

            # ---- a seek beyond what is loaded waits for it ------------------------------------------------------------------
            pg.evaluate("window.miniview.load('room', 'duck/room/long1')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pg.evaluate("window.miniview.setTime(190.0)")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            s = S()
            check(L("a script seek past the loaded part resolves with the tick there, not the last loaded one"), s["tick"] == 1900 and abs(s["belief"][0] - 1.9) < 1e-6, (s["tick"], s["loaded"]))

            # ---- event kinds are text, never a pattern ---------------------------------------------------------------------
            pg.evaluate("window.miniview.load('room', 'duck/room/odd1')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pg.evaluate("window.miniview.setTime(1.7)")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pg.click("#tabMoment")
            body = pg.evaluate("document.getElementById('inspBody').innerText")
            check(L("an event kind with pattern characters shows its text, and no page error"), ODD in body and "with text after it" in body and not errors, (body[:200], errors))

            # ---- live: by record, with a seq gap that reconnects, an epoch that redraws ----------------------------------------
            pg.evaluate(f"window.miniview.load('room', 'duck/room/live_{lib}')")
            pg.wait_for_function("window.__ready === true", timeout=30000)
            pg.evaluate(COUNT_JS)
            nframes = len([u for u in frames if f"live_{lib}" in u])
            live.add(*tick(1.2, 0.2))
            pg.wait_for_function("window.miniview.state().loaded.ticks === 3", timeout=15000)
            calls = pg.evaluate("window.__calls")
            check(L("a live tick is an append of one tick to the renderer, no rebuild"), calls["setRun"] == 0 and calls["ranges"][-1] == [2, 3], calls)
            check(L("... and no request for frames"), len([u for u in frames if f"live_{lib}" in u]) == nframes)
            seq = S()["seq"]
            gap = pg.evaluate(f"""(() => {{ const st = window.miniview.internals.store, es = st.es;
              es.dispatchEvent(new MessageEvent('tick', {{ data: JSON.stringify({{ t: 9.0, belief: [9, 0, 0], truth: null, tilt: null, cmd: [0, 0], depth: null }}), lastEventId: String(st.seq + 5) }}));
              return {{ ticks: st.ticks, url: st.es.url, reconnected: st.es !== es }}; }})()""")
            check(L("a record whose seq skips ahead is not applied; the page reconnects from the last seq it holds"),
                  gap["ticks"] == 3 and gap["reconnected"] and gap["url"].endswith(f"since={seq}"), gap)
            live.add(*tick(1.3, 0.3))
            pg.wait_for_function("window.miniview.state().loaded.ticks === 4", timeout=15000)
            check(L("after the reconnect the stream carries on in order"), S()["seq"] == seq + 1 and not errors, (S()["seq"], seq))
            pg.evaluate("window.miniview.setTime(1.3)")
            x0 = pg.evaluate("window.miniview.state().belief[0]")
            live.add(1.3, "epoch", {"map_to_world": [5.0, 0.0, 0.0]})          # an epoch that governs ticks already drawn
            pg.wait_for_function("window.miniview.state().belief[0] > 4", timeout=15000)
            calls = pg.evaluate("window.__calls")
            check(L("an epoch behind drawn ticks: what depends on it is drawn again (belief in the world frame moved by the epoch)"),
                  calls["setRun"] == 1 and abs(pg.evaluate("window.miniview.state().belief[0]") - (x0 + 5.0)) < 1e-6, (calls, x0))
            check(L("no page error through all of it"), not errors, errors)
            live.add(5.0, "end", {"verdict": "trapped"})
            live.close()
            pg.close()
        b.close()
    httpd.shutdown()

check.done()
