"""The two-press confirm (step 4.5, unit U8) in headless Chromium: arm then confirm within the window runs onConfirm once; a timeout, Escape and blur
disarm and restore the label; Enter and Space work twice; arm() throws for a button in [data-stop] or .stops; the armed label is announced in an
aria-live region; the armed look is an outline, not STOP's fill; reduced motion zeroes its transition; --z-stop is above drawer, palette and toast.
Run: cd apps/observatory && uv run python tests/test_look_confirm_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
from observatory.shots import launch

check = Checks("LOOK CONFIRM PAGES")

PAGE = """<!doctype html><html data-theme="dark"><head>
<link rel="stylesheet" href="/lib/tokens.css"><link rel="stylesheet" href="/lib/ui.css"><link rel="stylesheet" href="/lib/confirm.css">
</head><body>
<button id="go" class="ui-btn">Delete</button><button id="other">Other</button>
<button id="stop1" data-stop>STOP</button>
<span class="stops"><button id="stop2">Halt</button></span>
<div data-stop><span><button id="stop3">Inner</button></span></div>
</body></html>"""

SETUP = """async () => {
  const { arm } = await import('/lib/confirm.js');
  window.arm = arm; window.hits = 0; window.cfg = (ms) => ({ ms, onConfirm: () => { window.hits++; } });
  return true;
}"""
LABEL = "document.getElementById('go').textContent"
LIVE = "(document.querySelector('[aria-live]') || {}).textContent"
ARMED = "document.getElementById('go').hasAttribute('data-armed')"

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(8000)
    page.goto(base + "/web/three/")
    page.set_content(PAGE)
    page.wait_for_load_state("load")
    page.evaluate(SETUP)

    def fresh(ms=6000):
        page.evaluate("window.hits = 0")
        page.evaluate(f"(() => {{ window.off = window.arm(document.getElementById('go'), window.cfg({ms})); }})()")

    def done():
        page.evaluate("window.off && window.off(); window.off = null; document.getElementById('go').textContent = 'Delete'")

    fresh()
    page.click("#go")
    check("first press arms: the label changes, data-armed is set, onConfirm has not run",
          page.evaluate(LABEL) == "Press again to confirm" and page.evaluate(ARMED) and page.evaluate("window.hits") == 0, page.evaluate(LABEL))
    check("the armed label is announced in an aria-live region", page.evaluate(LIVE) == "Press again to confirm", page.evaluate(LIVE))
    live = page.evaluate("(() => { const l = document.querySelector('[aria-live]'); return [l.getAttribute('aria-live'), l.getAttribute('role')]; })()")
    check("the region is polite and role=status", live == ["polite", "status"], live)
    page.evaluate("Promise.all(document.getAnimations().map((a) => a.finished)).then(() => true)")   # the armed colours arrive by transition
    s = page.evaluate("(() => { const c = getComputedStyle(document.getElementById('go')); const p = (v) => { const d = document.createElement('i'); d.style.color = v; document.body.append(d); const r = getComputedStyle(d).color; d.remove(); return r; };"
                      " return {w: c.outlineWidth, oc: c.outlineColor === p('var(--status-alert)'), bg: c.backgroundColor === p('var(--status-alert-soft)'), notStop: c.backgroundColor !== p('var(--danger-solid)')}; })()")
    check("armed styling: a --status-alert outline on the -soft ground, not STOP's fill", s["w"] == "2px" and s["oc"] and s["bg"] and s["notStop"], s)
    page.click("#go")
    check("the second press within the window confirms once and restores the label",
          page.evaluate("window.hits") == 1 and page.evaluate(LABEL) == "Delete" and not page.evaluate(ARMED), [page.evaluate("window.hits"), page.evaluate(LABEL)])
    check("the announcement is cleared", page.evaluate(LIVE) == "", page.evaluate(LIVE))
    page.click("#go")
    page.click("#go")
    page.click("#go")
    check("a third press arms again; one confirm per armed pair", page.evaluate("window.hits") == 2 and page.evaluate(ARMED), page.evaluate("window.hits"))
    done()

    fresh(150)
    page.click("#go")
    page.wait_for_function("!document.getElementById('go').hasAttribute('data-armed')")
    page.click("#go")
    check("a timeout disarms and restores the label; the next press arms again, it does not confirm",
          page.evaluate("window.hits") == 0 and page.evaluate(ARMED), page.evaluate("window.hits"))
    done()

    fresh()
    page.click("#go")
    page.keyboard.press("Escape")
    check("Escape disarms and restores the label", not page.evaluate(ARMED) and page.evaluate(LABEL) == "Delete" and page.evaluate("window.hits") == 0, page.evaluate(LABEL))
    page.keyboard.press("Enter")
    check("... and Enter on the still-focused button arms again, it does not confirm", page.evaluate(ARMED) and page.evaluate("window.hits") == 0)
    done()

    fresh()
    page.click("#go")
    page.focus("#other")
    check("blur disarms", not page.evaluate(ARMED) and page.evaluate(LABEL) == "Delete" and page.evaluate("window.hits") == 0, page.evaluate(LABEL))
    done()

    for key in ("Enter", "Space"):
        fresh()
        page.focus("#go")
        page.keyboard.press(key)
        armed = page.evaluate(ARMED)
        page.keyboard.press(key)
        check(f"{key} twice: arms, then confirms once", armed and page.evaluate("window.hits") == 1 and not page.evaluate(ARMED), page.evaluate("window.hits"))
        done()

    fresh()
    page.evaluate("window.off()")
    page.click("#go")
    check("the returned function removes the behaviour: a press does nothing", not page.evaluate(ARMED) and page.evaluate("window.hits") == 0)
    page.evaluate("window.off = null")

    for sel in ("#stop1", "#stop2", "#stop3"):
        msg = page.evaluate("(sel) => { try { window.arm(document.querySelector(sel), window.cfg(100)); return null; } catch (e) { return String(e.message); } }", sel)
        check(f"arm() throws for {sel} (is or sits inside [data-stop] / .stops)", bool(msg) and "STOP" in msg, msg)

    # reduced motion: the armed transition rides --dur-base, which tokens.css zeroes
    fresh()
    page.click("#go")
    tr = "getComputedStyle(document.getElementById('go')).transitionDuration"
    page.emulate_media(reduced_motion="no-preference")
    page.evaluate("document.getElementById('go').offsetWidth")
    check("armed transition uses --dur-base (0.16s)", "0.16s" in page.evaluate(tr), page.evaluate(tr))
    page.emulate_media(reduced_motion="reduce")
    check("prefers-reduced-motion zeroes the armed transition", set(page.evaluate(tr).split(", ")) == {"0s"}, page.evaluate(tr))
    done()

    z = page.evaluate("(() => { const s = getComputedStyle(document.documentElement); const g = (n) => parseInt(s.getPropertyValue(n)); return {stop: g('--z-stop'), drawer: g('--z-drawer'), palette: g('--z-palette'), toast: g('--z-toast')}; })()")
    check("--z-stop is above --z-drawer, --z-palette and --z-toast", z["stop"] > max(z["drawer"], z["palette"], z["toast"]), z)

    b.close()
    httpd.shutdown()

check.done()
