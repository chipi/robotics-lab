"""The raw depth frame, the IMU signals and the decisions of a duck run in both pages (ADR-0014), in headless Chromium: the inspector's
Moment shows the 8 x 8 frame at the playhead as an image coloured by distance (statuses that are not valid hatched), with its pairing;
`sensors.raw` is in the outliner and the timeline; the IMU and the navigator's values are signals (outliner, inspector, rows); the
last event shows the decision behind it; a run being written grows the frame count and the page follows the newest frame; a run with
no raw frames says so. Screenshots of what the page shows go to /tmp/claude-1000/replay/ (REPLAY_SHOTS=0 turns it off).
Run: cd viewer && uv run python tests/test_replay_pages.py"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import OPEN_SECTIONS, T0_NS, catalog, import_fixture, make_run, run_record, scene, serve, tick, wait_until
from miniview import keys
from miniview.mcapio import Recorder
from miniview.shots import launch

SHOTS = Path("/tmp/claude-1000/replay") if os.environ.get("REPLAY_SHOTS", "1") != "0" else None
KEY = "duck/apartment/native1"
SIGNALS = [{"name": "pitch_deg", "kind": "number", "unit": "deg"}, {"name": "roll_deg", "kind": "number", "unit": "deg"},
           {"name": "pitch_rate_dps", "kind": "number", "unit": "deg/s"}, {"name": "nearest_mm", "kind": "number", "unit": "mm"},
           {"name": "turning", "kind": "number"}]
DECISION = {"rule": "cliff_stop", "reason": "a drop ahead seen in 3 frames in a row",
            "values": {"drop_m": 0.491, "stop_m": 0.6, "streak": 3, "frames_needed": 3}}
fails, lib = [], "?"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def frame(k, t):
    """The k-th depth frame: distances that tell the frames apart (zone z of frame k reads 400 + 10 k + 30 z mm), zones 62 and 63 invalid."""
    status = [5] * 62 + [0, 12]
    return (t, "depth_frame", {"rows": 8, "cols": 8, "distance_mm": [400 + 10 * k + 30 * z for z in range(64)], "status": status, "seq": 1000 + k,
                               "frame_t_ns": 5_000_000_000 + k * 67_700_000, "state_t_ns": 5_000_000_000 + k * 67_700_000 - 12_000_000 + (k % 5) * 6_000_000,
                               "pair_dt_ms": -12.0 + (k % 5) * 6.0})


def records(n_ticks=40):
    out = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
    f = 0
    for i in range(n_ticks):
        t = round(1.0 + 0.1 * i, 3)
        while 1.0 + f / 14.8 < t - 1e-9:
            out.append(frame(f, round(1.0 + f / 14.8, 3)))
            f += 1
        out.append(tick(t, 0.02 * i))
        out.append((t, "signals", {"values": {"pitch_deg": 3.0 * math.sin(t), "roll_deg": -1.0 * math.cos(t), "pitch_rate_dps": 20.0 * math.cos(t),
                                              "nearest_mm": 600.0 - 5 * i, "turning": float(i % 7 == 0)}}))
        if i == 10:
            out.append((t + 0.01, "event", {"kind": "cliff_stop", "text": "cliff_stop drop_m 0.491", "notable": True, "t_src": t, "raw": {"zones": 8},
                                            "decision": DECISION}))
    out.append((1.0 + 0.1 * n_ticks, "end", {"verdict": "ended"}))
    return out


def api(base, path):
    import urllib.request

    return json.loads(urllib.request.urlopen(base + path).read())


def hsl_rgb(h, s, l_):
    """What canvas makes of hsl(h s% l%): rgb 0-255."""
    s, l_ = s / 100, l_ / 100
    c = (1 - abs(2 * l_ - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l_ - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return [round((v + m) * 255) for v in (r, g, b)]


def run_page(b, base, theme="dark"):
    ctx = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme=theme)
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.goto(f"{base}/web/{lib}/index.html")
    page.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
    return ctx, page, logs


def call(page, js, t=60000):
    page.evaluate("window.__ready = false")
    r = page.evaluate(js)
    page.wait_for_function("window.__ready === true", timeout=t)
    return r


def eventually(page, js, timeout=8000) -> bool:
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_frame(page, index, logs, timeout=8000):
    """Until the inspector shows raw frame `index` and state() says so; on a timeout, what the page had instead (CI 2026-11-16
    timed out here once, on the first frame, with nothing to go on)."""
    wait_raw(page, f"document.getElementById('rawcv') && document.getElementById('rawcv').dataset.i === '{index}' "
                   f"&& window.miniview.state().raw_frame && window.miniview.state().raw_frame.i === {index}", logs, f"raw frame {index}", timeout)


def wait_raw(page, js, logs, what, timeout=15000):
    """page.wait_for_function, and on a timeout what the inspector's raw frame had: the canvas, the request state (busy, last
    failure), the stream's count, the playhead, the inspector's text, the console."""
    try:
        page.wait_for_function(js, timeout=timeout)
    except Exception:
        seen = page.evaluate("(() => { const c = document.getElementById('rawcv'), i = window.miniview.internals, r = i.raw, "
                             "s = i.M.run?.streams?.find((x) => x.id === 'sensors.raw'); "
                             "return { canvas: c ? { ...c.dataset } : null, busy: r.busy, failed_ms_ago: isFinite(r.failed) ? performance.now() - r.failed : null, "
                             "key: r.key, run: i.M.runId, have: r.fr ? { i: r.fr.index, n: r.fr.n, t: r.fr.t, next_t: r.fr.next_t } : null, "
                             "stream: s ? { count: s.count, missing: s.missing } : null, t: i.M.t, status: i.M.run?.status, "
                             "inspector: (document.getElementById('inspBody')?.innerText || '').split('Raw depth frame')[1]?.slice(0, 160) }; })()")
        print(f"waiting for {what}: the page had {seen}; console: {logs[-8:]}", flush=True)
        raise


def shot(page, name, raw=False, scroll_to=None):
    """A screenshot of the page; with `raw` (or a selector) the inspector is scrolled to the raw frame (or that) first: it is far down the Moment."""
    if raw or scroll_to:
        page.evaluate(f"document.querySelector({json.dumps(scroll_to or '#rawcv')}).scrollIntoView({{block: 'center'}})")
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def pixels(page, coords):
    """The canvas's rgb at each (x, y), from one readback."""
    return page.evaluate("(coords) => { const c = document.getElementById('rawcv'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; "
                         "return coords.map(([x, y]) => [d[(y * c.width + x) * 4], d[(y * c.width + x) * 4 + 1], d[(y * c.width + x) * 4 + 2]]); }", coords)


def signed(v):
    return ("+" if v > 0 else "") + f"{v:.1f}"


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    tmp = Path(tmp)
    data = tmp / "data"
    make_run(data, KEY, records(), signals=SIGNALS)
    import_fixture(data)                                           # a run with no raw frames, in the same folder
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    live_dir = tmp / "live"
    live_cat = catalog(live_dir)
    live_cat.put_scene(scene("apartment"))
    live_httpd, live_base = serve(live_cat, follow=True)
    b = launch(p)
    run = api(base, f"/api/v1/runs/{KEY}")
    n_frames = sum(1 for r in records() if r[1] == "depth_frame")

    for lib in ("three", "deck"):
        ctx, page, logs = run_page(b, base)
        call(page, f"window.miniview.load('apartment', '{KEY}')")
        call(page, OPEN_SECTIONS)
        row = page.evaluate("(() => { const r = document.querySelector('#tree .row[data-id=\"sensors.raw\"]'); return r ? [r.classList.contains('missing'), r.innerText] : null; })()")
        check("the outliner has the stream sensors.raw, not missing, with the run's frame count", row and not row[0] and str(n_frames) in row[1].replace(",", ""), row)
        check("its row is in the timeline", eventually(page, "document.querySelector('#lanesL .lane-l[data-lane=\"sensors.raw\"]') !== null"))

        seen = []
        for t in (1.0, 2.5, 4.4):
            call(page, f"window.miniview.setTime({t})")
            want = api(base, f"/api/v1/runs/{KEY}/sensor?t={t}")
            wait_frame(page, want["index"], logs)
            st = page.evaluate("window.miniview.state().raw_frame")
            seen.append(st["i"])
            insp = page.evaluate("document.getElementById('inspBody').innerText").replace("\n", " ").replace("\u2212", "-")
            check(f"at t = {t}: the inspector shows the API's raw frame (number, time, valid zones, the state minus frame time); state() summarises it",
                  abs(st["t"] - want["t"]) < 1e-9 and st["pair_dt_ms"] == want["pair_dt_ms"]
                  and f"Raw frame {want['index'] + 1} of {want['n']}" in insp and "Valid zones 62 of 64" in insp
                  and f"State minus frame {signed(want['pair_dt_ms'])} ms" in insp and f"Nearest valid {min(want['distance_mm'][:62])} mm" in insp, (insp[-260:], st))
            # the image: zone z of frame k reads 400 + 10 k + 30 z mm, coloured hsl(240 d/4000 65% 38%); zones 62, 63 are hatched
            cell = 30
            zones = (0, 9, 37, 61)
            got = pixels(page, [[z % 8 * cell + 2, z // 8 * cell + 2] for z in zones] + [[z % 8 * cell + 2, z // 8 * cell + 2] for z in (62, 63)])
            want_rgb = [hsl_rgb(round(240 * min(want["distance_mm"][z] / 4000, 1)), 65, 38) for z in zones]
            check(f"... and the image is that frame: zones coloured by their distance (frame {want['index'] + 1}, read back from the canvas)",
                  all(abs(a_ - b_) <= 2 for g, w in zip(got, want_rgb) for a_, b_ in zip(g, w)), (got[:4], want_rgb))
            check("... the zones whose status is not valid are hatched dark, not coloured by their distance", all(max(px) < 140 for px in got[4:]), got[4:])
        check("moving the playhead moves the frame: three times, three different frames, later ones later", seen[0] < seen[1] < seen[2], seen)
        shot(page, f"raw-frame-{lib}-dark", raw=True)

        # the IMU and the navigator's values are signals: outliner, inspector, rows
        grp = page.evaluate("[...document.querySelectorAll('#tree .row[data-id^=\"signals.\"]')].map((r) => r.dataset.id)")
        check("the IMU and the navigator's values are in the outliner as signals", sorted(grp) == sorted(f"signals.{d['name']}" for d in SIGNALS), grp)
        call(page, "window.miniview.setTime(2.5)")
        sg = api(base, f"/api/v1/runs/{KEY}/state?t=2.5")["signals"]
        insp = page.evaluate("document.getElementById('inspBody').innerText").replace("−", "-").replace("\n", " ")
        check("the inspector's Signals give the IMU pitch, roll and pitch rate and the nearest return at the playhead, the API's values",
              f"pitch_deg {sg['values']['pitch_deg']:.2f}" in insp and f"pitch_rate_dps {sg['values']['pitch_rate_dps']:.2f}" in insp and f"nearest_mm {sg['values']['nearest_mm']:.0f}" in insp, insp[:400])
        check("and a row each in the timeline", page.evaluate("document.querySelectorAll('#lanesL .lane-l[data-lane^=\"signals.\"]').length") == len(SIGNALS))
        shot(page, f"imu-signals-{lib}-dark")

        # the decision: on the event, in the inspector and in the marker's tooltip
        call(page, "window.miniview.setTime(2.2)")
        insp = page.evaluate("document.getElementById('inspBody').innerText").replace("\n", " ")
        check("the last event shows the rule, why it fired and the values it compared",
              "cliff_stop" in insp and DECISION["reason"] in insp and "stop_m 0.6" in insp and "streak 3" in insp and "drop_m 0.491" in insp, insp[-320:])
        check("state().last_event carries the decision", page.evaluate("window.miniview.state().last_event.decision.rule") == "cliff_stop"
              and page.evaluate("window.miniview.state().last_event.decision.values.stop_m") == 0.6)
        page.hover("#mlane .mk")
        check("the marker's tooltip gives the reason", DECISION["reason"] in page.evaluate("document.getElementById('tip').innerText"), page.evaluate("document.getElementById('tip').innerText"))
        shot(page, f"decision-{lib}-dark", scroll_to=".decision")
        call(page, "window.miniview.setTime(2.5)")
        page.evaluate("document.documentElement.dataset.theme = 'light'")
        shot(page, f"raw-frame-{lib}-light", raw=True)
        check("no page error", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        ctx.close()

        # a frame request that fails is asked again: the inspector does not stay on "loading" (it did, until something else redrew it)
        ctx, page, logs = run_page(b, base)
        failed = []
        call(page, f"window.miniview.load('apartment', '{KEY}')")
        page.route("**/sensor?t=2.5*", lambda route: (failed.append(route.request.url), route.abort()) if not failed else route.continue_())
        call(page, "window.miniview.setTime(2.5)")
        want = api(base, f"/api/v1/runs/{KEY}/sensor?t=2.5")
        # only the inspector's canvas is watched: state() asks for the frame itself, which would hide a page that never does
        ok = eventually(page, f"document.getElementById('rawcv')?.dataset.i === '{want['index']}'")
        check("a frame request that failed is asked again, and the inspector shows the frame", len(failed) == 1 and ok,
              (failed, page.evaluate("document.getElementById('rawcv')?.dataset.i ?? 'no image'")))
        ctx.close()

        # a page that draws its inspector in its first half second still asks for the frame: CI's fast runner did, and the page
        # took the start of its clock for a failure 0 s ago, asked nothing, and said "loading" for good. The page's clock is
        # started again just before the playhead moves, which makes that moment come here on any machine.
        ctx, page, logs = run_page(b, base)
        call(page, f"window.miniview.load('apartment', '{KEY}')")
        asked = []
        page.on("request", lambda r: asked.append(r.url) if "/sensor?" in r.url else None)
        page.evaluate("(() => { const real = performance.now.bind(performance), base = real(); performance.now = () => real() - base; })()")
        call(page, "window.miniview.setTime(2.5)")
        ok = eventually(page, f"document.getElementById('rawcv')?.dataset.i === '{want['index']}'")
        check("a page in its first half second still asks for the frame, and the inspector shows it", ok and asked,
              (len(asked), page.evaluate("document.getElementById('rawcv')?.dataset.i ?? 'no image'")))
        ctx.close()

        # a frame request never answered is given up after 5 s and asked again (it held `busy` for good before)
        ctx, page, logs = run_page(b, base)
        held = []
        call(page, f"window.miniview.load('apartment', '{KEY}')")
        page.route("**/sensor?t=2.5*", lambda route: held.append(route) if not held else route.continue_())
        call(page, "window.miniview.setTime(2.5)")
        ok = eventually(page, f"document.getElementById('rawcv')?.dataset.i === '{want['index']}'", timeout=12000)
        check("a frame request never answered is given up and asked again, and the inspector shows the frame", len(held) == 1 and ok,
              (len(held), page.evaluate("document.getElementById('rawcv')?.dataset.i ?? 'no image'")))
        ctx.close()

        # a run with no raw frames: says so, no image
        ctx, page, logs = run_page(b, base)
        call(page, "window.miniview.load('apartment', 'duck/apartment/explore9')")
        call(page, "window.miniview.setTime(10)")
        insp = page.evaluate("document.getElementById('inspBody').innerText").replace("\n", " ")
        check("a run with no raw depth frames says so and shows no image", "Raw frame not in this run" in insp and page.evaluate("document.getElementById('rawcv') === null")
              and page.evaluate("document.querySelector('#tree .row[data-id=\"sensors.raw\"]')?.classList.contains('missing')") is not False, insp[-200:])
        check("no page error", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        ctx.close()

        # a run being written: frames arrive by record, the page follows the newest, and does not reconnect for them
        lkey = f"duck/apartment/live-{lib}"
        rec = Recorder(keys.run_dir(live_dir, lkey), run_record(lkey, signals=SIGNALS))
        rec.add(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})
        for r in records(10)[1:8]:
            rec.add(*r)
        wait_until(lambda: api(live_base, f"/api/v1/runs/{lkey}")["seq"] >= 7, 10, every=0.1, what="the live run's first records")
        ctx, page, logs = run_page(b, live_base)
        call(page, f"window.miniview.load('apartment', '{lkey}')")
        wait_raw(page, "document.getElementById('rawcv') !== null", logs, "the live run's first raw frame")
        n0 = api(live_base, f"/api/v1/runs/{lkey}/sensor")["n"]
        for r in records(10)[8:30]:
            rec.add(*r)
        n1 = sum(1 for r in records(10)[1:30] if r[1] == "depth_frame")
        wait_until(lambda: api(live_base, f"/api/v1/runs/{lkey}/sensor")["n"] == n1, 15, every=0.1, what="the service to read the new frames")
        page.wait_for_function(f"window.miniview.internals.M.run.streams.find((s) => s.id === 'sensors.raw').count === {n1}", timeout=15000)
        check("frames written while the page is open arrive by record: the stream's count is the file's", n1 > n0, (n0, n1))
        wait_raw(page, f"document.getElementById('rawcv') && document.getElementById('rawcv').dataset.i === '{n1 - 1}'", logs, "the live run's newest raw frame")
        check("following the live run, the inspector shows the newest frame", page.evaluate("window.miniview.state().follow") is True
              and page.evaluate("window.miniview.state().raw_frame.i") == n1 - 1, page.evaluate("window.miniview.state().raw_frame"))
        # The newest frame stays current while no newer one is known; state() went null 300 ms after each fetch (2026-11-16, deck run).
        page.wait_for_timeout(600)
        check("... and still does a while later, with no new frame", page.evaluate("window.miniview.state().raw_frame?.i") == n1 - 1,
              page.evaluate("window.miniview.state().raw_frame"))
        shot(page, f"raw-frame-live-{lib}-dark", raw=True)
        rec.add(rec.last_t, "end", {"verdict": "ended"})
        rec.close()
        check("no page error while it followed", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        ctx.close()
    b.close()
    for h in (httpd, live_httpd):
        h.shutdown()

print("REPLAY PAGES", "FAIL " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
