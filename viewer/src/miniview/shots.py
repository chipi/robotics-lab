"""Pictures from the real page, headless: the agent's face uses the operator's page (ADR-0003).

Starts the service (API and pages) on a free port (its own thread, stopped at the end), opens the page in
Chromium with software GL through Playwright, drives it only through `window.miniview` (CONTRACT.md)
and screenshots the page. Playwright is the viewer's dev dependency; Chromium is the system's when it
is there, else Playwright's own (`uv run playwright install --with-deps chromium`).
"""

import os
import threading
from pathlib import Path

SYSTEM_CHROMIUM = "/usr/bin/chromium"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"]


def chromium_path() -> str | None:
    """The Chromium to launch: MINIVIEW_CHROMIUM when set and non-empty; else the system's, but not in CI
    (on a runner /usr/bin/chromium can be a snap wrapper that fails headless) and only if it exists; else
    None, which is Playwright's bundled Chromium."""
    env = os.environ.get("MINIVIEW_CHROMIUM", "").strip()
    if env:
        return env
    if os.environ.get("CI", "").lower() != "true" and Path(SYSTEM_CHROMIUM).exists():
        return SYSTEM_CHROMIUM
    return None


def launch(p):
    """Every test and picture launches Chromium through here (software GL, no sandbox)."""
    return p.chromium.launch(executable_path=chromium_path(), args=ARGS)


class _Server:
    """The real service (API and pages) on a free port, over the given catalog."""

    def __init__(self, catalog):
        from miniview.server import make_server

        self.httpd = make_server(catalog, "127.0.0.1", 0, follow=False)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _call(page, js: str, timeout_ms: int = 30000) -> None:
    """Run one window.miniview call and wait for the page to say it has drawn."""
    page.evaluate("window.__ready = false")
    page.evaluate(js)
    page.wait_for_function("window.__ready === true", timeout=timeout_ms)


def pictures(catalog, lib: str, scene: str, run: str, shots: list, size=(1400, 900)) -> list:
    """shots: dicts with t, out (Path) and optional view, frame, hidden (stream ids), modes
    ({stream: [mode, seconds]}), relations ({name: bool}), crop (a CSS selector: only that element,
    e.g. "#stage" for the view alone). Returns the paths written."""
    from playwright.sync_api import sync_playwright

    written = []
    with _Server(catalog) as srv, sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
        page.goto(f"http://127.0.0.1:{srv.port}/web/{lib}/index.html")
        page.wait_for_function("window.miniview !== undefined", timeout=30000)
        _call(page, f"window.miniview.load({scene!r}, {run!r})", 60000)
        for s in shots:
            _call(page, f"window.miniview.setView({s.get('view', 'top')!r})")
            _call(page, f"window.miniview.setFrame({s.get('frame', 'world')!r})")
            for sid in s.get("hidden", []):
                _call(page, f"window.miniview.setVisible({sid!r}, false)")
            for sid, (mode, seconds) in s.get("modes", {}).items():
                _call(page, f"window.miniview.setTimeMode({sid!r}, {mode!r}, {seconds})")
            for name, on in s.get("relations", {}).items():
                _call(page, f"window.miniview.setRelation({name!r}, {'true' if on else 'false'})")
            _call(page, f"window.miniview.setTime({float(s['t'])})")
            Path(s["out"]).parent.mkdir(parents=True, exist_ok=True)
            if s.get("crop"):
                page.locator(s["crop"]).screenshot(path=str(s["out"]))
            else:
                page.screenshot(path=str(s["out"]))
            written.append(Path(s["out"]))
            for sid in s.get("hidden", []):                      # back to the defaults for the next shot
                _call(page, f"window.miniview.setVisible({sid!r}, true)")
        browser.close()
    return written


def sheet(images: list, captions: list, out: Path, cols: int) -> Path:
    """Several PNGs on one sheet (the filmstrip), laid out by Chromium — no imaging library needed."""
    from playwright.sync_api import sync_playwright
    import base64

    cells = []
    for img, cap in zip(images, captions):
        b64 = base64.b64encode(Path(img).read_bytes()).decode()
        cells.append(f'<figure><img src="data:image/png;base64,{b64}"><figcaption>{cap}</figcaption></figure>')
    html = ("<style>body{margin:0;background:#fff;font:13px monospace}"
            f".g{{display:grid;grid-template-columns:repeat({cols},1fr);gap:4px;padding:4px}}"
            "figure{margin:0}img{width:100%;display:block;border:1px solid #ccc}"
            "figcaption{padding:2px 4px;color:#333}</style>"
            f'<div class="g">{"".join(cells)}</div>')
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1800, "height": 600})
        page.set_content(html)
        page.wait_for_function("[...document.images].every((i) => i.complete)", timeout=30000)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.locator(".g").screenshot(path=str(out))
        browser.close()
    return out
