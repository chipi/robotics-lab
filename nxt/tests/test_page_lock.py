"""nxt-web's own page takes the control lock (RFC-0017, step 4 of the lock): it acquires it to drive, keeps it alive, shows who holds it,
gives it back, and its STOP stays open. Headless Chromium against nxt-web --fake (the simulated brick, a free loopback port, a data
folder of this test's own); never a real brick.

Needs Chromium and Playwright, which are the viewer's, so it runs in the viewer's environment:
  make test-nxt-page      (cd viewer && uv run --frozen python ../nxt/tests/test_page_lock.py)"""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from miniview.shots import launch

NXT_DIR = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(NXT_DIR / ".venv" / "bin" / "nxt-web"))
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="nxt-page-"))
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"
proc = subprocess.Popen([NXT_WEB, "--fake", "--host", "127.0.0.1", "--port", str(PORT), "--config", str(tmp / "config.json")],
                        env=dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "miniview")), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def tracks():
    st = api("/api/status")[1]
    return st["left"], st["right"]


def holder():
    return api("/api/lock")[1]["holder"]


def wait(page, js, timeout=15000):
    page.wait_for_function(js, timeout=timeout)


def until(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


try:
    def up():
        try:
            return api("/api/status")[1].get("connected")
        except OSError:
            return False
    check("nxt-web --fake is up", until(up))
    errors = []
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_context(viewport={"width": 900, "height": 800}).new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        wait(page, "document.getElementById('lock-state').textContent.includes('free')")
        check("the page shows the control lock, free, with Take control", page.locator("#lock-take").is_visible() and page.locator("#lock-release").is_hidden())

        # drive takes the lock by itself
        box = page.locator("[data-dir=fwd]").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        check("holding a direction takes the lock and drives", until(lambda: holder() == "nxt-page" and tracks() == (50, 50)), (holder(), tracks()))
        wait(page, "document.getElementById('lock-state').textContent.includes('you')")
        check("the page says you hold it, and offers Release", page.locator("#lock-release").is_visible() and page.locator("#lock-take").is_hidden())
        page.mouse.up()
        check("letting go stops the tracks and keeps the lock", until(lambda: tracks() == (0, 0)) and holder() == "nxt-page", (tracks(), holder()))
        check("the lock's log says who took it", any(e["kind"] == "lock acquired" and e.get("client") == "nxt-page" for e in api("/api/events?since=0")[1]["events"]))

        # keepalive: no command for longer than a keepalive period still leaves most of the lease
        time.sleep(8.0)
        left = api("/api/lock")[1]["expires_in_s"]
        check("the page keeps the lease alive while idle (a lease of 20 s, 8 s of silence, still more than 14 s left)", left > 14, left)

        # release
        page.click("#lock-release")
        check("Release gives it back", until(lambda: holder() is None))
        wait(page, "document.getElementById('lock-state').textContent.includes('free')")

        # another client holds it
        other = api("/api/lock", {"action": "acquire", "client": "phone"})[1]
        wait(page, "document.getElementById('lock-state').textContent.includes('phone')")
        check("the page shows who holds it", "phone" in page.locator("#lock-state").inner_text() and page.locator("#lock-take").is_disabled())
        wait(page, "[...document.querySelectorAll('.pad [data-dir]')].every((b) => b.disabled)")
        check("the direction buttons are off while another client holds it", page.evaluate("[...document.querySelectorAll('.pad [data-dir]')].every((b) => b.disabled)"))
        code, r = api("/api/drive", {"left": 50, "right": 50})
        check("and a drive with no session is refused at nxt-web", code == 409 and r["lock"] == "held" and tracks() == (0, 0), (code, r))
        api("/api/lock", {"action": "release", "session": other["session"]})
        wait(page, "document.getElementById('lock-state').textContent.includes('free')")

        # STOP: the page's STOP is open and ends its lease
        page.click("#lock-take")
        check("Take control takes it", until(lambda: holder() == "nxt-page"))
        page.click("#stop")
        check("the page's STOP ends its lease", until(lambda: holder() is None))
        wait(page, "document.getElementById('lock-state').textContent.includes('free')")
        check("and the page knows it is no longer the holder", page.locator("#lock-take").is_visible())

        # a lease ended by somebody else's STOP is shown
        page.click("#lock-take")
        until(lambda: holder() == "nxt-page")
        api("/api/stop", {"client": "bystander"})
        wait(page, "document.getElementById('toast').textContent.includes('Control ended')")
        check("a STOP from anyone ends it and the page says why", "stopped_by bystander" in page.locator("#toast").inner_text(), page.locator("#toast").inner_text())
        check("no script error", errors == [], errors)
        browser.close()

    # no lease, no motion, from any client
    st, r = api("/api/drive", {"left": 50, "right": 50})
    check("with nobody holding it, a drive is refused: no lease, no motion", st == 409 and r["lock"] == "no_lease" and tracks() == (0, 0), (st, r))
finally:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()

if failures:
    print(f"FAIL test_page_lock: {len(failures)} failed: {failures}")
    sys.exit(1)
print("PASS test_page_lock")
