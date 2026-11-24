"""The Observatory's look-and-feel guards (step 4.5, unit U2) in headless Chromium: the pages load Inter from the shared /lib/fonts, so
the font is the same one Mission Control loads, not a system fallback.
Run: cd apps/observatory && uv run python tests/test_look_ui_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
from observatory.shots import launch

check = Checks("LOOK UI PAGES")

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(8000)
    for path in ("/web/three/", "/web/deck/"):
        page.goto(base + path)
        loaded = page.evaluate("document.fonts.load('400 14px Inter').then(l => l.length)")
        check(f"{path}: the page loads Inter from the shared /lib/fonts", loaded > 0, loaded)
        family = page.evaluate("getComputedStyle(document.body).fontFamily")
        check(f"{path}: the body font-family starts with Inter", family.startswith("Inter"), family)
    b.close()
    httpd.shutdown()
check.done()
