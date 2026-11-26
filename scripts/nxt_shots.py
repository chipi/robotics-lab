"""The screenshots of docs/guides/nxt-web.md: nxt-web's page, headless, against `nxt-web --fake` (the simulated brick).

Starts its own nxt-web on a loopback port (default 18210) with a temp config and data folder, so nothing of the operator's config, runs or
recordings is touched, and never opens USB or Bluetooth (--fake never does; the Auto / USB / Bluetooth buttons in Setup are not clicked).
Takes the dark theme at 1440 wide, in the order of the guide's walkthrough.

    cd apps/observatory && uv run --frozen python ../../scripts/nxt_shots.py --out ../../docs/assets/screenshots/guides/nxt-web [--port N]

Runs in the Observatory's environment (Playwright and Chromium, as nxt-web's page test uses them); installs nothing."""

import argparse
import atexit
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from observatory.shots import launch

REPO = Path(__file__).resolve().parents[1]
NXT_WEB = os.environ.get("NXT_WEB", str(REPO / "apps/nxt-web/.venv/bin/nxt-web"))
FREEZE = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", type=int, default=18210)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="nxt-shots-"))
    atexit.register(shutil.rmtree, tmp, True)
    base = f"http://127.0.0.1:{args.port}"
    proc = subprocess.Popen([NXT_WEB, "--fake", "--host", "127.0.0.1", "--port", str(args.port), "--config", str(tmp / "config.json"),
                             "--miniview-data", str(tmp / "data")],
                            cwd=tmp, env=dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "data")),
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    taken = []

    def shot(page, name):
        page.wait_for_timeout(700)
        path = args.out / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        taken.append(path)
        print(f"{name}.png  {path.stat().st_size // 1024} KB")

    try:
        end = time.monotonic() + 20
        while True:
            try:
                urllib.request.urlopen(base + "/api/status", timeout=2).read()
                break
            except OSError:
                if time.monotonic() > end or proc.poll() is not None:
                    print("nxt-web --fake did not start")
                    return 1
                time.sleep(0.2)

        (tmp / "hello.rxe").write_bytes(b"\x00" * 800)
        with sync_playwright() as p:
            browser = launch(p)
            page = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark").new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/")
            page.add_style_tag(content=FREEZE)
            page.wait_for_function("document.getElementById('lock-state').textContent.includes('free')")
            page.wait_for_function("document.querySelectorAll('#drive-readings > *').length > 0")
            shot(page, "01-open")

            page.click("#lock-take")
            page.wait_for_function("document.getElementById('lock-state').textContent.includes('you')")
            box = page.locator("[data-dir=fwd]").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.wait_for_timeout(1500)
            shot(page, "02-drive")
            page.mouse.up()
            page.wait_for_timeout(300)

            page.click("nav [data-tab=sensors]")
            page.wait_for_timeout(1500)
            page.select_option("#window", index=0)
            shot(page, "03-sensors")

            page.click("#rec")
            page.wait_for_timeout(3000)
            page.click("#rec")
            page.wait_for_function("document.querySelectorAll('#runs tr').length > 0")
            page.wait_for_timeout(500)
            shot(page, "04-recording")

            page.click("nav [data-tab=programs]")
            page.wait_for_function("document.querySelectorAll('#files tr').length > 0")
            page.set_input_files("#upload-file", str(tmp / "hello.rxe"))
            page.click("#upload")
            page.wait_for_function("[...document.querySelectorAll('#files tr')].some(r => r.textContent.includes('hello.rxe'))")
            shot(page, "05-programs")

            page.click("[data-view='runlog.txt']")
            page.wait_for_function("document.getElementById('viewer').hidden === false")
            shot(page, "06-viewer")
            page.click("#viewer-close")
            page.add_style_tag(content=".toast{display:none!important}")

            page.click("nav [data-tab=setup]")
            page.wait_for_function("document.querySelectorAll('#diag tr').length > 0")
            shot(page, "07-setup")

            page.click("nav [data-tab=drive]")
            page.click("#estop")
            page.wait_for_timeout(500)
            shot(page, "08-stop")
            browser.close()
        if errors:
            print("page errors:", errors)
            return 1
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    big = [p.name for p in taken if p.stat().st_size > 400 * 1024]
    if big:
        print("over 400 KB:", big)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
