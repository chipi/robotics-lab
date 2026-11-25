"""Export video in both pages (ADR-0017), in headless Chromium, with a stand-in engine (no MuJoCo, no rendering): the control is
disabled with the reason as its tooltip when there is no render service, or none that can render the run's robot; enabled with one;
its panel starts a job, shows the status once a second, and then a <video> of the file with a download link; a failing engine's
error is in the panel.
Run: cd apps/observatory && uv run python tests/test_export_pages.py"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import boot, catalog, import_fixture, scene, serve, stub_engine
from observatory.shots import launch
from observatory.video import service

SHOTS = Path("/tmp/claude-1000/export")          # what the panel looks like, to look at
KEY, ROVER ="duck/apartment/explore9", "rover/apartment/explore9"
fails, lib = [], "?"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def run_page(b, base, key):
    ctx = b.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    logs, posts = [], []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.on("request", lambda r: posts.append(json.loads(r.post_data)) if r.method == "POST" else None)
    boot(page, f"{base}/web/{lib}/index.html", timeout=30000)
    page.evaluate("window.__ready = false")
    page.evaluate(f"window.miniview.load('apartment', '{key}')")
    page.wait_for_function("window.__ready === true", timeout=60000)
    return ctx, page, logs, posts


def settle_button(page, timeout=8000):
    """The button once the page has the render service's answer (it is disabled 'asking' until then)."""
    page.wait_for_function("(() => { const b = document.getElementById('exportBtn'); return b && !/asking/.test(b.title); })()", timeout=timeout)
    return page.evaluate("(() => { const b = document.getElementById('exportBtn'); return [b.disabled, b.title]; })()")


def wait_text(page, sel, pattern, timeout=15000):
    page.wait_for_function(f"new RegExp({json.dumps(pattern)}).test(document.querySelector({json.dumps(sel)})?.innerText || '')", timeout=timeout)


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    tmp = Path(tmp)
    data, state = tmp / "data", tmp / "state"
    import_fixture(data)
    import_fixture(data, "explore9", robot="rover")
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    svc = service.make_server(data, state, "127.0.0.1", 0)
    threading.Thread(target=svc.serve_forever, daemon=True).start()
    R = f"http://127.0.0.1:{svc.server_address[1]}"
    gate = stub_engine(tmp, "gated")
    b = launch(p)

    for lib in ("three", "deck"):
        os.environ.pop("MINIVIEW_RENDER", None)
        ctx, page, logs, posts = run_page(b, base, KEY)
        disabled, title = settle_button(page)
        check("no render service: Export video is disabled, its tooltip says no render service configured", disabled and "no render service configured" in title, (disabled, title))
        check("... and the button is in the top bar, labelled Export video", page.evaluate("document.querySelector('header.top #exportBtn')?.innerText") == "Export video")
        ctx.close()

        os.environ["MINIVIEW_RENDER"] = "http://127.0.0.1:1"
        ctx, page, logs, posts = run_page(b, base, KEY)
        disabled, title = settle_button(page)
        check("a render service that does not answer: disabled, the tooltip says so", disabled and "render service not answering" in title, (disabled, title))
        ctx.close()

        os.environ["MINIVIEW_RENDER"] = R
        ctx, page, logs, posts = run_page(b, base, ROVER)
        disabled, title = settle_button(page)
        check("a render service with no engine for the run's robot: disabled, the tooltip names the robot and why", disabled and "rover" in title and "mujoco" in title, (disabled, title))
        ctx.close()

        ctx, page, logs, posts = run_page(b, base, KEY)
        disabled, title = settle_button(page)
        check("a render service with an engine for the robot: Export video is enabled", not disabled, (disabled, title))
        t0 = json.loads(page.evaluate("fetch('/api/v1/runs/" + KEY + "').then((r) => r.text())"))["t0"]
        page.click("#exportBtn")
        page.wait_for_selector("#xp")
        check("its panel offers the engines that can render the robot, from the run's start, to its end, and two sizes",
              page.evaluate("[...document.querySelectorAll('#xEngine option')].map((o) => o.value)") == ["mujoco"]
              and abs(float(page.input_value("#xFrom")) - t0) < 0.01 and page.evaluate("[...document.querySelectorAll('#xSize option')].map((o) => o.value)") == ["1280x720", "960x540"])
        page.select_option("#xSize", "960x540")
        page.fill("#xFrom", f"{t0 + 1.0:.2f}")
        page.click("#xGo")
        wait_text(page, "#xStatus", "running")
        check("Start: the status shows the job running, and Start is disabled meanwhile", page.is_disabled("#xGo") and page.evaluate("document.querySelector('#xResult video') === null"))
        gate.touch()
        page.wait_for_selector("#xResult video", timeout=15000)
        job_id = page.evaluate("document.querySelector('#xResult video').getAttribute('src')").split("/")[-2]
        src = page.evaluate("document.querySelector('#xResult video').getAttribute('src')")
        href = page.evaluate("document.querySelector('#xResult a.dl').getAttribute('href')")
        got = page.evaluate(f"fetch('{src}').then(async (r) => [r.status, r.headers.get('content-type'), (await r.text()).slice(0, 12)])")
        check("done: a <video controls> of /api/v1/videos/{id}/file appears, with a download link to the same file",
              src == f"/api/v1/videos/{job_id}/file" and href == src and page.evaluate("document.querySelector('#xResult video').controls") is True
              and page.evaluate("document.querySelector('#xResult a.dl').hasAttribute('download')"), (src, href))
        check("... and that URL serves the video (200, video/mp4)", got[0] == 200 and got[1] == "video/mp4" and "ftypmp42" in got[2], got)
        check("the status says done and Start is enabled again", "done" in page.inner_text("#xStatus") and page.is_enabled("#xGo"))
        check("the request carried the engine, the size and the changed start, not an end that was left alone",
              posts == [{"engine": "mujoco", "size": "960x540", "from": round(t0 + 1.0, 2)}], posts)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"export-{lib}-dark.png"))
        page.evaluate("document.documentElement.dataset.theme = 'light'")
        page.screenshot(path=str(SHOTS / f"export-{lib}-light.png"))
        check("no page error", not [m for m in logs if "favicon.ico" not in m], logs[:3])
        ctx.close()

        stub_engine(tmp, "fail")
        ctx, page, logs, posts = run_page(b, base, KEY)
        settle_button(page)
        page.click("#exportBtn")
        page.wait_for_selector("#xp")
        page.click("#xGo")
        wait_text(page, "#xStatus", "Failed")
        check("an engine that fails: the panel shows the error (exit 1), no video, and Start is enabled again",
              "exit 1" in page.inner_text("#xStatus") and page.evaluate("document.querySelector('#xResult video') === null") and page.is_enabled("#xGo"), page.inner_text("#xStatus"))
        check("the whole run was asked for: no from, no to", posts == [{"engine": "mujoco", "size": "1280x720"}], posts)
        page.fill("#xFrom", "9999")
        page.click("#xGo")
        check("a start after the end is refused in the panel, with nothing sent", "not after To" in page.inner_text("#xStatus") and len(posts) == 1, (page.inner_text("#xStatus"), posts))
        ctx.close()
        gate = stub_engine(tmp, "gated")
    b.close()
    for h in (httpd, svc):
        h.shutdown()

print("EXPORT PAGES", "FAIL " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
