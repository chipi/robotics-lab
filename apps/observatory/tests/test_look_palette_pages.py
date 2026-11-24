"""The command palette (step 4.5, unit U9) in headless Chromium: verbs register and list (STOP first), the fuzzy filter, arrow keys and Enter, a
dangerous verb needs a second Enter (confirm.js), STOP runs on the first Enter, Esc closes and focus returns to the opener, Ctrl/Cmd+K opens but not
from a typed-in input, the ARIA wiring, its stylesheet has no hex, the modules import clean, reduced motion zeroes its animation.
Runs in the Observatory page tests (it needs Playwright and Chromium, like the other libs/web page checks). Run: cd apps/observatory && uv run --frozen python tests/test_look_palette_pages.py"""

import functools
import http.server
import os
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libs" / "web"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


# static: no hex in the stylesheet, every var() it uses is a token
css = re.sub(r"/\*.*?\*/", "", (LIB / "palette" / "palette.css").read_text(), flags=re.S)
check("palette.css has no hex colour", not re.findall(r"(?<![\w-])#[0-9a-fA-F]{3,8}(?![\w-])", css), re.findall(r"#[0-9a-fA-F]{3,8}", css))
tokens = (LIB / "tokens.css").read_text()
unknown = sorted({v for v in re.findall(r"var\((--[\w-]+)", css) if f"{v}:" not in tokens})
check("every var() in palette.css is a token of tokens.css", not unknown, unknown)
check("palette.css sits at --z-palette", "z-index: var(--z-palette)" in css)

from playwright.sync_api import sync_playwright  # noqa: E402

PAGE = """<!doctype html><html data-theme="dark"><head>
<link rel="stylesheet" href="/lib/tokens.css"><link rel="stylesheet" href="/lib/ui.css"><link rel="stylesheet" href="/lib/confirm.css"><link rel="stylesheet" href="/lib/palette/palette.css">
</head><body><button id="opener">Open</button><input id="typed"><button id="stop" data-stop>STOP</button></body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.path = self.path.removeprefix("/lib")
        super().do_GET()

    def log_message(self, *a):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(LIB)))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"

SYSTEM = "/usr/bin/chromium"
exe = os.environ.get("OBSERVATORY_CHROMIUM", "").strip() or (SYSTEM if os.environ.get("CI", "").lower() != "true" and Path(SYSTEM).exists() else None)

SETUP = """async () => {
  const { createRegistry } = await import('/lib/palette/registry.js');
  const { createPalette } = await import('/lib/palette/palette.js');
  window.reg = createRegistry(); window.ran = [];
  const v = (id, title, o = {}) => reg.register({ id, title, section: o.section ?? 'Go', run: () => { ran.push(id); }, ...o });
  v('nav.robots', 'Go to Robots', { keywords: ['fleet'] });
  v('theme.toggle', 'Toggle theme', { section: 'View', hotkey: 'T' });
  v('goal.cancel', 'Cancel the goal', { danger: 'confirm', section: 'Goal' });
  v('hidden', 'Hidden verb', { when: (c) => c.show });
  v('robot.stop', 'STOP the robot', { danger: 'stop', section: 'Robot' });
  window.ctx = { show: false };
  window.mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, x) => mem.set(k, x) };
  window.pal = createPalette({ registry: reg, storage, context: () => ctx });
  return true;
}"""
OPTIONS = "[...document.querySelectorAll('.pal-row')].map((r) => r.dataset.verb)"
ACTIVE = "document.querySelector('.pal-row.is-active')?.dataset.verb"
OPEN = "!!document.querySelector('.pal') && !document.querySelector('.pal').hidden"
ARMED = "!!document.querySelector('.pal-confirm[data-armed]')"
FOCUS = "document.activeElement.id"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"])
    page = b.new_page()
    page.set_default_timeout(8000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    page.evaluate(SETUP)

    check("both modules import clean and the page has no script error", not errors, errors)
    listed = page.evaluate("reg.list(ctx).map((v) => v.id)")
    check("list(ctx): STOP first, when() false is left out, registration order after", listed == ["robot.stop", "nav.robots", "theme.toggle", "goal.cancel"], listed)
    page.evaluate("ctx.show = true")
    check("list(ctx) follows the context", "hidden" in page.evaluate("reg.list(ctx).map((v) => v.id)"))
    page.evaluate("ctx.show = false")
    err = page.evaluate("""(() => { const out = []; for (const bad of [{id: 'x', title: 't', run() {}, danger: 'maybe'}, {id: 'nav.robots', title: 't', run() {}}, {id: 'y', title: 't'}]) { try { reg.register(bad); out.push('ok'); } catch (e) { out.push(e.constructor.name); } } return out; })()""")
    check("register refuses a bad danger, a duplicate id and a missing run", err == ["RangeError", "Error", "TypeError"], err)
    page.evaluate("(() => { reg.register({id: 'tmp', title: 'Temp', run: () => {}}); reg.unregister('tmp'); })()")
    check("unregister removes a verb", "tmp" not in page.evaluate("reg.list(ctx).map((v) => v.id)") and page.evaluate("reg.get('tmp')") is None)
    fz = page.evaluate("import('/lib/palette/palette.js').then(({fuzzy}) => [fuzzy('gtr', 'Go to Robots') > 0, fuzzy('xyz', 'Go to Robots'), fuzzy('rob', 'Go to Robots') > fuzzy('rbs', 'Go to Robots')])")
    check("fuzzy: a subsequence matches, a stranger does not, a run beats a gap", fz == [True, -1, True], fz)

    page.focus("#opener")
    page.keyboard.press("Control+k")
    check("Ctrl+K opens the palette and puts focus in its input", page.evaluate(OPEN) and page.evaluate("document.activeElement.classList.contains('pal-input')"))
    check("the open list has STOP first, then the rest", page.evaluate(OPTIONS) == ["robot.stop", "nav.robots", "theme.toggle", "goal.cancel"], page.evaluate(OPTIONS))
    aria = page.evaluate("""(() => { const q = (s) => document.querySelector(s); const i = q('.pal-input'); return {
      dlg: q('.pal-box').getAttribute('role'), modal: q('.pal-box').getAttribute('aria-modal'), lb: q('.pal-list').getAttribute('role'),
      opts: [...document.querySelectorAll('.pal-row')].every((r) => r.getAttribute('role') === 'option' && r.id),
      combo: i.getAttribute('role'), controls: i.getAttribute('aria-controls') === q('.pal-list').id,
      active: i.getAttribute('aria-activedescendant') === q('.pal-row.is-active').id, sel: q('.pal-row.is-active').getAttribute('aria-selected'),
      live: q('.pal-status').getAttribute('role'), label: !!q('.pal-box').getAttribute('aria-label') }; })()""")
    check("ARIA: dialog, listbox, option, combobox, aria-activedescendant on the active option, a live status",
          aria == {"dlg": "dialog", "modal": "true", "lb": "listbox", "opts": True, "combo": "combobox", "controls": True, "active": True, "sel": "true", "live": "status", "label": True}, aria)
    z = page.evaluate("[getComputedStyle(document.querySelector('.pal')).zIndex, getComputedStyle(document.documentElement).getPropertyValue('--z-palette').trim(), getComputedStyle(document.documentElement).getPropertyValue('--z-stop').trim()]")
    check("it sits at --z-palette, below --z-stop", z[0] == z[1] and int(z[1]) < int(z[2]), z)

    page.keyboard.press("ArrowDown")
    check("ArrowDown moves the active option and aria-activedescendant", page.evaluate(ACTIVE) == "nav.robots" and page.evaluate("document.querySelector('.pal-input').getAttribute('aria-activedescendant') === document.querySelector('.pal-row.is-active').id"))
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")
    check("ArrowUp wraps to the last option", page.evaluate(ACTIVE) == "goal.cancel", page.evaluate(ACTIVE))

    page.fill(".pal-input", "flt")
    check("typing filters by keyword (fleet)", page.evaluate(OPTIONS) == ["nav.robots"], page.evaluate(OPTIONS))
    page.fill(".pal-input", "zzzz")
    check("no match: no options, a status says so, no activedescendant",
          page.evaluate(OPTIONS) == [] and "No matching" in page.evaluate("document.querySelector('.pal-status').textContent") and page.evaluate("!document.querySelector('.pal-input').hasAttribute('aria-activedescendant')"))
    page.keyboard.press("Enter")
    check("Enter with no match runs nothing", page.evaluate("ran") == [] and page.evaluate(OPEN))
    page.fill(".pal-input", "theme")
    page.keyboard.press("Enter")
    check("Enter runs the verb, closes, and returns focus to the opener",
          page.evaluate("ran") == ["theme.toggle"] and not page.evaluate(OPEN) and page.evaluate(FOCUS) == "opener", [page.evaluate("ran"), page.evaluate(FOCUS)])
    check("a run verb is remembered under rl.palette.recent", page.evaluate("JSON.parse(mem.get('rl.palette.recent'))") == ["theme.toggle"])

    page.keyboard.press("Control+k")
    check("recent verbs come first after STOP on an empty query", page.evaluate(OPTIONS)[:2] == ["robot.stop", "theme.toggle"], page.evaluate(OPTIONS))
    page.keyboard.press("Escape")
    check("Esc closes and focus returns to the opener", not page.evaluate(OPEN) and page.evaluate(FOCUS) == "opener")

    page.evaluate("ran.length = 0")
    page.keyboard.press("Control+k")
    page.fill(".pal-input", "cancel")
    page.keyboard.press("Enter")
    check("a confirm verb: the first Enter arms it, nothing runs, the palette stays open", page.evaluate(ARMED) and page.evaluate("ran") == [] and page.evaluate(OPEN), page.evaluate("ran"))
    check("the armed state is announced by confirm.js", "confirm" in (page.evaluate("document.querySelector('.ui-confirm-live')?.textContent") or "").lower())
    page.keyboard.press("Escape")
    check("the first Esc only cancels the confirm", page.evaluate(OPEN) and not page.evaluate(ARMED) and page.evaluate("ran") == [])
    page.keyboard.press("Enter")
    page.keyboard.type("c")
    check("typing disarms a pending confirm", not page.evaluate(ARMED) and page.evaluate("ran") == [])
    page.fill(".pal-input", "")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowDown")
    check("moving off a pending confirm disarms it", not page.evaluate(ARMED) and page.evaluate("ran") == [])
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    check("the second Enter runs the confirm verb once and closes", page.evaluate("ran") == ["goal.cancel"] and not page.evaluate(OPEN), page.evaluate("ran"))
    page.evaluate("ran.length = 0")
    page.keyboard.press("Control+k")
    page.fill(".pal-input", "cancel")
    page.click(".pal-confirm")
    page.click(".pal-confirm")
    check("the mouse: two presses on the confirm button run it once", page.evaluate("ran") == ["goal.cancel"], page.evaluate("ran"))

    page.evaluate("ran.length = 0")
    page.keyboard.press("Control+k")
    check("STOP has no confirm button", page.evaluate("!document.querySelector('.pal-row[data-danger=stop] .pal-confirm')"))
    check("STOP is the active option on open", page.evaluate(ACTIVE) == "robot.stop", page.evaluate(ACTIVE))
    page.keyboard.press("Enter")
    check("STOP runs on the first Enter, unconfirmed", page.evaluate("ran") == ["robot.stop"] and not page.evaluate(OPEN), page.evaluate("ran"))
    page.keyboard.press("Control+k")
    page.fill(".pal-input", "o")
    check("with a filter, a matching STOP verb is still first", page.evaluate(OPTIONS)[0] == "robot.stop", page.evaluate(OPTIONS))
    page.keyboard.press("Escape")

    page.focus("#typed")
    page.keyboard.press("Control+k")
    check("Ctrl+K typed in an input does not open it", not page.evaluate(OPEN))
    page.focus("#opener")
    page.keyboard.press("Meta+k")
    check("Cmd+K opens it", page.evaluate(OPEN))
    page.keyboard.press("Control+k")
    check("Ctrl+K inside the palette closes it", not page.evaluate(OPEN))
    page.keyboard.press("Control+k")
    page.click(".pal-scrim", position={"x": 5, "y": 5})
    check("a click on the scrim closes it and focus returns", not page.evaluate(OPEN) and page.evaluate(FOCUS) == "opener")
    page.keyboard.press("Control+k")
    page.keyboard.press("Tab")
    check("Tab keeps focus in the palette", page.evaluate("document.activeElement.classList.contains('pal-input')"))
    page.keyboard.press("Escape")

    page.keyboard.press("Control+k")
    page.evaluate("(() => { reg.register({id: 'late', title: 'Late verb', run: () => {}}); })()")
    check("a verb registered while open appears", "late" in page.evaluate(OPTIONS), [page.evaluate(OPEN), page.evaluate(OPTIONS)])
    page.keyboard.press("Escape")

    page.evaluate("document.documentElement.dataset.motion = 'reduce'")
    page.keyboard.press("Control+k")
    d = page.evaluate("getComputedStyle(document.querySelector('.pal-box')).animationDuration")
    check("reduced motion: the open animation lasts 0 s", d == "0s", d)
    page.keyboard.press("Escape")
    page.evaluate("document.documentElement.dataset.motion = 'full'")
    page.keyboard.press("Control+k")
    d = page.evaluate("getComputedStyle(document.querySelector('.pal-box')).animationDuration")
    check("full motion: the animation uses --dur-base", d != "0s", d)
    page.keyboard.press("Escape")

    page.evaluate("pal.dispose()")
    page.focus("#opener")
    page.keyboard.press("Control+k")
    check("dispose removes the key and the dialog", not page.evaluate("!!document.querySelector('.pal')"))
    b.close()

httpd.shutdown()
print("test_palette " + ("FAIL " + ", ".join(failures) if failures else "PASS"))
sys.exit(1 if failures else 0)
