"""helpers.boot in headless Chromium: a page whose module load is aborted is retried once only when the failure text matches; any other timeout raises
at once. route.abort cannot make ERR_NETWORK_CHANGED, so the matcher is injected (`_match`) and the abort is net::ERR_FAILED.
Run: cd apps/observatory && uv run python tests/test_boot_helper.py"""

import contextlib
import io
import tempfile
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from helpers import Checks, boot, catalog, scene, serve
from observatory.shots import launch

check = Checks("BOOT HELPER")

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    url = f"{base}/web/three/"

    def page_aborting_once():
        pg, aborted = b.new_page(), []

        def handler(route):
            if aborted:
                return route.continue_()
            aborted.append(route.request.url)
            route.abort()

        pg.route("**/web/three/views.js", handler)
        return pg, aborted

    pg, aborted = page_aborting_once()
    try:
        boot(pg, url, timeout=3000)
        raised = False
    except PlaywrightTimeout:
        raised = True
    check("a module aborted with other text than the match: no retry, the timeout raises", raised and len(aborted) == 1 and not pg.evaluate("window.__ready === true"), aborted)
    pg.close()

    pg, aborted = page_aborting_once()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        boot(pg, url, timeout=5000, _match="ERR_FAILED")
    check("a matching failure: one reload, the page comes up ready", pg.evaluate("window.__ready === true") and len(aborted) == 1, aborted)
    check("the retry is named on stderr with the failed URL", "boot: retry after net::ERR_FAILED on" in err.getvalue() and aborted[0] in err.getvalue(), err.getvalue())
    pg.close()

    pg = b.new_page()
    pg.route("**/web/three/views.js", lambda route: route.abort())
    try:
        boot(pg, url, timeout=3000, _match="ERR_FAILED")
        raised = False
    except PlaywrightTimeout:
        raised = True
    check("a failure that repeats on the retry raises", raised)
    pg.close()
    b.close()
    httpd.shutdown()
check.done()
