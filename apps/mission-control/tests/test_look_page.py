"""Mission Control's look-and-feel guards (step 4.5, unit U-STOP) in headless Chromium, set up as test_calibration_page.py is: STOP and
STOP ALL are one tap and never under another layer. With each drawer open (the Settings edit drawer, History and compare, the Calibration
drawer) and with the toast showing, at phone and at desktop width: the element at the centre of each STOP button is that button, a real
click on it makes its API call, and on a phone the drawer ends above the STOP bar instead of running under it.

U20 (confirm for dangerous actions that are not STOP): an area's Delete needs two presses (the first arms and announces, the second calls),
a timeout or Escape disarms without a call, confirm.js and confirm.css load on the first press and not on the overview, STOP and STOP ALL stay one press.

U19 (the restyle on the shared tokens and kit): style.css holds no hex; the top bar's brand is brand.js's; a state is a status badge (glyph and word); a robot
whose state is old dims its values and says how old, and disables the actions that need a fresh state, while STOP, STOP ALL and the alarm panel's stop
stay enabled and fire on the first click; a kit module that fails to load leaves the page and STOP usable; the overview fetches no three.js; reduced motion
zeroes the chevron's transition.

U22 (panels and layouts on the robot page, libs/web/layout/store.js): a panel hidden, a card folded and a size set persist across a reload (rl.layouts.control),
Reset returns the default, a saved layout loads and deletes, and STOP and STOP ALL stay uncovered and one press with the menu open, every panel hidden and the
joints column at its widest, at phone and desktop width; the overview fetches neither layout.js nor the store.

U23 (the readiness card, readiness.js): named checks from the fields GET /robots/{id} carries, each a status badge (glyph and word); a field the view does not carry
reads unknown and never ok; the verdict follows the worst check; the card is a layout panel (hide, fold); the overview fetches readiness.js not at all.

U24 (evidence links, libs/web/evidence.js): where a run or a moment is shown, a link "Open in the Observatory at this moment" built with the one shared format
(an alarm, the robot page's alarm rows, the readiness alarm check, a goal run's result), only behind the Observatory at /control/; evidence.js loads when a link is
rendered and not on the overview.

U25 (the palette's verbs, palette-verbs.js on libs/web/palette): Ctrl/Cmd+K and a top-bar button open it, never from a key typed in an input, and the overview fetches
no palette module until then; STOP and STOP ALL are listed first and run on the first Enter, unconfirmed; navigation (overview, each robot, each tab), panels
and layouts (through layout.js and the store), the theme; a verb that fails shows its error in the toast; no verb starts a goal, takes over, takes a lease or
moves a robot; with the palette open nothing covers STOP, on a phone and on the desktop.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
import json
import urllib.request
from contextlib import contextmanager
import os
import re
import shutil
import tempfile
import threading
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import check, finish, installation_file

from observatory.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation
from runfile.profilestore import Store

tmp = Path(tempfile.mkdtemp(prefix="mc-look-page-"))
atexit.register(shutil.rmtree, tmp, True)
REPO_FILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
STATE = tmp / "inst-state"
FOLDER = STATE / "profiles" / "duck"
Store(STATE / "profiles").seed("duck", REPO_FILE)
inst = tmp / "installation.json"
installation_file(inst, {"duck": {"variant": "sim", "profile": str(FOLDER)}}, state=str(STATE))
os.environ[installation.ENV] = str(inst)

mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}})], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def wait(page, js, timeout=8000, arg=None):
    page.wait_for_function(js, arg=arg, timeout=timeout)


@contextmanager
def soft(label):
    try:
        yield
    except Exception as exc:
        here = [f.lineno for f in traceback.extract_tb(exc.__traceback__) if f.filename == __file__]
        check(f"{label}: completed", False, f"{type(exc).__name__}: {str(exc).splitlines()[0]} (test lines {here[-3:]})")


WEB = Path(__file__).resolve().parents[1] / "src" / "mission_control" / "web"
FAKE = mc.robots["duck-1"].adapter.robot
STOPS = {"stop-robot": "/robots/duck-1/stop", "stop-all": "/stop"}
errors = []
SHOTS_U24 = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests")) / "u24-shots"
SHOTS_U24.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    drawer = lambda: page.locator("#drawer-root .scrim:not([hidden])")

    def hit(sid):
        """What is on top at the centre of the button: the button or one of its children, else the id/class of what covers it."""
        return page.evaluate("""(id) => { const b = document.getElementById(id), r = b.getBoundingClientRect();
            const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return e && (e === b || b.contains(e)) ? 'button' : (e ? e.tagName + '#' + e.id + '.' + e.className : 'nothing'); }""", sid)

    def close_drawer():
        if drawer().count():
            page.keyboard.press("Escape")
            wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")

    def open_page():
        page.goto(BASE + "/#robot/duck-1")
        wait(page, "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
        wait(page, "document.getElementById('stop-robot').textContent === 'STOP duck-1'")

    def tab(name):
        page.click(f"#tab-{name}")
        wait(page, f"!document.getElementById('rp-{name}').hidden")

    def open_edit():
        tab("settings")
        wait(page, "!!document.querySelector('#st-blocks [data-block]')")
        page.click("#st-blocks [data-block='locomotion']")
        wait(page, "document.querySelector('#st-pane h2')?.textContent === 'locomotion'")
        page.click("#st-edit-open")
        page.locator("#st-edit").wait_for()

    def open_history():
        tab("settings")
        wait(page, "!!document.querySelector('#st-blocks [data-block]')")
        page.click("#st-history-open")
        page.locator("#st-history").wait_for()

    def open_calibration():
        tab("calibration")
        wait(page, "!!document.querySelector('#cal-open-odometry_scale')")
        page.click("#cal-open-odometry_scale")
        page.locator("#cal-drawer").wait_for()

    def check_stop(where, view):
        for sid, route in STOPS.items():
            covered = hit(sid)
            check(f"{view}, {where}: nothing covers {sid} at its centre", covered == "button", covered)
            with soft(f"{view}, {where}: a click on {sid}"):
                with page.expect_request(lambda r, route=route: r.method == "POST" and r.url.endswith("/api/v1" + route), timeout=4000):
                    page.click("#" + sid, timeout=4000)
                check(f"{view}, {where}: a click on {sid} posts {route}", True)
            wait(page, "!document.getElementById('toast').hidden")   # the answer's toast is up; STOP is still on top of it
            toast = hit(sid)
            check(f"{view}, {where}: the toast does not cover {sid}", toast == "button", toast)

    for view, size in (("phone 390x844", {"width": 390, "height": 844}), ("desktop 1440x900", {"width": 1440, "height": 900})):
        page.set_viewport_size(size)
        open_page()
        with soft(f"{view}: no drawer"):
            check_stop("no drawer", view)
        for name, opener, did in (("settings edit drawer", open_edit, "st-edit"), ("history drawer", open_history, "st-history"),
                                  ("calibration drawer", open_calibration, "cal-drawer")):
            with soft(f"{view}: {name}"):
                close_drawer()
                opener()
                check(f"{view}: the {name} is open", drawer().count() == 1 and drawer().get_attribute("id") == did)
                check(f"{view}, {name}: nothing covers STOP before any toast", all(hit(s) == "button" for s in STOPS), [hit(s) for s in STOPS])
                fixed = page.evaluate("getComputedStyle(document.querySelector('.stops')).position === 'fixed'")
                if fixed:
                    gap = page.evaluate("document.querySelector('.stops').getBoundingClientRect().top - document.querySelector('#drawer-root .scrim:not([hidden]) .drawer').getBoundingClientRect().bottom")
                    check(f"{view}, {name}: the drawer ends above the STOP bar, so no drawer button is under it", gap >= 0, gap)
                check_stop(name, view)
                close_drawer()

    open_page()
    loaded = page.evaluate("document.fonts.load('400 14px Inter').then(l => l.length)")
    check("the page loads Inter from the shared /lib/fonts, not a system fallback", loaded > 0, loaded)
    family = page.evaluate("getComputedStyle(document.body).fontFamily")
    check("the body font-family starts with Inter", family.startswith("Inter"), family)
    robots_words = page.evaluate("[...document.querySelectorAll('header.top *')].filter((e) => e.children.length === 0 && e.offsetParent && e.textContent.trim() === 'Robots').length")
    check("on the robot page the word Robots is in the top bar once (the nav item; the crumb is the way back and the robot's name)", robots_words == 1, robots_words)

    # --- U19: the restyle ----------------------------------------------------------------------------------------------------
    css = re.sub(r"/\*.*?\*/", "", (WEB / "style.css").read_text(), flags=re.S)
    check("style.css holds no hex colour (every colour is a token)", re.findall(r"#[0-9a-fA-F]{3,8}(?![\w-])", css) == [], re.findall(r"#[0-9a-fA-F]{3,8}(?![\w-])", css))
    OLD = ("bg-app bg-header bg-panel bg-viewport bg-field bg-hover bg-selected bg-shead bg-shead-hover border border-strong border-hover text text-dim text-faint on-accent "
           "ok warn error hair hair-2 hair-3 scrim shadow c-belief c-truth ui mono").split()
    old = [n for n in OLD if re.search(r"var\(--" + re.escape(n) + r"[,)]", css)]
    check("style.css uses no old alias of the token file", old == [], old)

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(BASE + "/")
    wait(page, "window.__mc && window.__mc.ready && document.getElementById('conn').textContent === 'live'")
    check("the page is density regular, 14 px base", page.evaluate("document.documentElement.dataset.density === 'regular' && getComputedStyle(document.body).fontSize === '14px'"))
    wait(page, "!!document.querySelector('header .ui-brand')")
    check("the top bar's brand is brand.js's link", page.evaluate("(() => { const a = document.querySelector('header [data-slot=brand] a.ui-brand'); return !!a && a.textContent === 'Mission Control'; })()"))
    brand = page.evaluate("""() => { const a = document.querySelector('header [data-slot=brand] a.ui-brand'), m = a && a.querySelector('.ui-brand-mark');
        const p = document.createElement('i'); p.style.background = 'linear-gradient(135deg, var(--data-belief), var(--data-truth))'; document.body.append(p);
        const want = getComputedStyle(p).backgroundImage; p.remove(); const c = m && getComputedStyle(m);
        return {href: a && a.getAttribute('href'), mark: !!m, w: c && c.width, h: c && c.height, bg: c && c.backgroundImage, want}; }""")
    check("on its own port the brand link goes to '/' (not /control/, which does not exist there)", brand["href"] == "/", brand)
    check("the brand carries the kit's mark: 12 px, the belief-to-truth gradient (the same as the Observatory's)",
          brand["mark"] and brand["w"] == "12px" and brand["h"] == "12px" and brand["bg"] == brand["want"] and "gradient" in brand["bg"], brand)
    check("the theme control sits in the theme slot and STOP stays outside every slot", page.evaluate(
        "!!document.querySelector('[data-slot=theme] #theme') && !document.querySelector('[data-slot] .stops, [data-slot] .stop') && !!document.querySelector('header > .stops #stop-robot')"))
    same = page.evaluate("""() => { const s = document.getElementById('stop-robot'), p = document.createElement('i'); p.style.background = 'var(--danger-solid)'; p.style.color = 'var(--text-on-solid)';
        document.body.append(p); const a = getComputedStyle(s), b = getComputedStyle(p), r = [a.backgroundColor === b.backgroundColor, a.color === b.color]; p.remove(); return r; }""")
    check("STOP is --text-on-solid on --danger-solid", same == [True, True], same)
    live = page.evaluate("(() => { const b = document.getElementById('connbox'); return [b.dataset.status, b.firstElementChild.textContent, b.textContent]; })()")
    check("the connection chip is a live badge: the live status, its dot and the word", live[0] == "live" and live[1] == "\u25cf" and live[2].endswith("live"), live)

    # a run's state is a status badge: glyph and word, the id on the word
    page.fill("#g-x", "0.4")
    page.fill("#g-y", "0.0")
    page.click("#g-run")
    wait(page, "!!document.getElementById('run-state')")
    got = page.evaluate("""() => { const w = document.getElementById('run-state'), b = w.parentElement;
        return [w.textContent, b.dataset.status, b.querySelector('.ui-glyph').textContent, b.querySelector('.ui-glyph').getAttribute('aria-hidden')]; }""")
    want = {"running": "info", "queued": "info", "reached": "ok", "done": "ok"}.get(got[0])
    check("a run's state is a badge: the word is its text, the status is statusOf's, the glyph is aria-hidden", want is not None and got[1] == want and got[2] != "" and got[3] == "true", got)
    wait(page, "document.getElementById('run-state').textContent === 'reached'", 20000)
    check("a correct end (reached) is the ok status", page.evaluate("document.getElementById('run-state').parentElement.dataset.status") == "ok")

    # the primary button is the kit's solid style: --accent fill, --accent-on text, --accent-hover under the pointer
    prim = lambda: page.evaluate("""() => { const probe = (v) => { const d = document.createElement('i'); d.style.color = v; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
        const s = getComputedStyle(document.getElementById('g-run'));
        return {bg: s.backgroundColor, fg: s.color, accent: probe('var(--accent)'), on: probe('var(--accent-on)'), hover: probe('var(--accent-hover)')}; }""")
    pr = prim()
    check("Run now is a solid primary button: --accent fill, --accent-on text", pr["bg"] == pr["accent"] and pr["fg"] == pr["on"], pr)
    page.hover("#g-run")
    page.wait_for_timeout(300)
    pr = prim()
    check("... and --accent-hover under the pointer", pr["bg"] == pr["hover"], pr)
    page.mouse.move(0, 0)

    # a goal in the library, so there is a library Run to disable
    page.fill("#g-name", "stale-check")
    page.click("#g-save")
    page.locator("#goal-list [data-action=run]").first.wait_for()

    # --- a robot whose state is old (the stream stopped): values dim and labelled, actions that need a fresh state disabled, STOP never ---------------
    wait(page, "window.__mc.freshOf(window.__mc.S.robots[0]) === 'fresh'")
    check("a fresh robot: no age shown, the Run buttons enabled",
          page.evaluate("!document.querySelector('[data-age]') && [...document.querySelectorAll('[data-needs-fresh]')].every((b) => !b.disabled) && document.getElementById('goal-fresh').hidden"))
    page.evaluate("window.__mc.S.es.close(); window.__mc.S.robots[0].state_at = Date.now() - 12000; window.__mc.tickFreshness();")
    wait(page, "!!document.querySelector('#robot-duck-1 .ui-stale-age')")
    stale = page.evaluate("""() => { const v = document.querySelector('#robot-duck-1 .ui-stale-value'), k = document.querySelector('#robot-duck-1 .kv');
        return {opacity: getComputedStyle(v).opacity, age: document.querySelector('#robot-duck-1 [data-age]').textContent, fresh: k.dataset.fresh}; }""")
    check("a stale robot's values are dimmed", float(stale["opacity"]) < 1, stale)
    check("a stale robot says it is stale and how old", stale["fresh"] == "stale" and "stale" in stale["age"] and "12 s" in stale["age"], stale)
    gone = page.evaluate("""() => ({run: document.getElementById('g-run').disabled, title: document.getElementById('g-run').title, note: document.getElementById('goal-fresh').textContent,
        shown: !document.getElementById('goal-fresh').hidden, lib: [...document.querySelectorAll('#goal-list [data-action=run]')].map((b) => b.disabled),
        stop: [document.getElementById('stop-robot').disabled, document.getElementById('stop-all').disabled]})""")
    check("stale: Run now and the library's Run are disabled, with the reason on the button and beside it", gone["run"] and gone["lib"] and all(gone["lib"]) and "stale" in gone["title"] and "stale" in gone["note"] and gone["shown"], gone)
    check("stale: STOP and STOP ALL are not disabled", gone["stop"] == [False, False], gone)
    for sid, route in STOPS.items():
        with soft(f"stale: a click on {sid}"):
            with page.expect_request(lambda r, route=route: r.method == "POST" and r.url.endswith("/api/v1" + route), timeout=4000):
                page.click("#" + sid, timeout=4000)
            check(f"stale: the first click on {sid} posts {route}", True)
    # one synchronous step: the fake robot keeps sending state, and one landing between a back-date and a read re-renders the card (CI, ea2dcf7)
    off = page.evaluate("""(() => { const mc = window.__mc, r = mc.S.robots[0]; r.state_at = Date.now() - 40000; mc.tickFreshness();
        const e = document.querySelector('#robot-duck-1 [data-age]');
        return {status: e && e.dataset.status, text: e && e.textContent, fresh: mc.freshOf(r), run: document.getElementById('g-run').disabled}; })()""")
    glyphs = page.evaluate("import('/lib/status.js').then((m) => [m.glyph('offline'), m.glyph('stale')])")
    check("an offline robot's age is the offline status: its own glyph (not stale's clock) and word", off["status"] == "offline" and (off["text"] or "").startswith(glyphs[0])
          and glyphs[0] != glyphs[1] and "stale" not in (off["text"] or ""), [off, glyphs])
    check("a robot silent for 30 s or more is offline, its Run disabled", off["fresh"] == "offline" and off["run"], off)
    with soft("offline: a click on stop-robot"):
        with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/v1/robots/duck-1/stop"), timeout=4000):
            page.click("#stop-robot", timeout=4000)
        check("offline: the first click on STOP posts", True)
    page.evaluate("window.__mc.S.robots[0].state_at = Date.now(); window.__mc.tickFreshness();")
    check("a fresh state enables them again", page.evaluate("[...document.querySelectorAll('[data-needs-fresh]')].every((b) => !b.disabled) && document.getElementById('goal-fresh').hidden"))

    # the real thing, not a set-back stamp: the robot stops answering, the server says offline
    page.goto(BASE + "/")
    wait(page, "window.__mc && window.__mc.ready && window.__mc.freshOf(window.__mc.S.robots[0]) === 'fresh'")
    FAKE.set_offline(True)
    try:
        wait(page, "window.__mc.freshOf(window.__mc.S.robots[0]) === 'offline' && document.getElementById('g-run').disabled", 10000)
        check("the robot goes offline on the server: the page shows it and disables Run", True)
        with soft("offline robot: a click on stop-all"):
            with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/v1/stop"), timeout=4000):
                page.click("#stop-all", timeout=4000)
            check("offline robot: the first click on STOP ALL posts", True)
    except Exception as exc:
        check("the robot goes offline on the server: the page shows it and disables Run", False, str(exc).splitlines()[0])
    finally:
        FAKE.set_offline(False)
    wait(page, "window.__mc.freshOf(window.__mc.S.robots[0]) === 'fresh' && !document.getElementById('g-run').disabled", 10000)

    # a kit module that fails to load leaves the page, STOP and the plain chip as they are
    broken = ctx.new_page()
    broken.route(re.compile(r".*/lib/(brand|status)\.js$"), lambda r: r.abort())
    broken.goto(BASE + "/")
    broken.wait_for_function("window.__mc && window.__mc.ready && document.getElementById('conn').textContent === 'live'", timeout=8000)
    check("kit failed to load: no brand link, the static brand stays, STOP and STOP ALL are visible and enabled", broken.evaluate(
        "!document.querySelector('.ui-brand') && document.querySelector('[data-slot=brand]').textContent === 'Mission Control' && ['stop-robot', 'stop-all'].every((i) => { const b = document.getElementById(i), r = b.getBoundingClientRect(); return !b.disabled && r.width > 0 && r.height > 0; })"))
    with soft("kit failed: a click on stop-robot"):
        with broken.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/v1/robots/duck-1/stop"), timeout=4000):
            broken.click("#stop-robot", timeout=4000)
        check("kit failed to load: STOP still posts on the first click", True)
    broken.close()

    # the overview is light: no three.js, no vendor module
    light = ctx.new_page()
    seen = []
    light.on("request", lambda r: seen.append(r.url))
    light.set_viewport_size({"width": 390, "height": 844})
    light.goto(BASE + "/")
    light.wait_for_function("window.__mc && window.__mc.ready", timeout=8000)
    light.wait_for_timeout(1200)
    heavy = [u for u in seen if "/lib/vendor/" in u or "three" in u.lower() or "bodyview" in u or "/lib/stage/" in u or "/lib/body/inspector" in u]
    check("the overview fetches no three.js, vendor module, stage, inspector or body view", heavy == [], heavy)
    check("the overview loads the kit's status, brand and motion modules", all(any(u.endswith(f"/lib/{m}.js") for u in seen) for m in ("status", "brand", "motion")), seen)
    light.close()

    # --- U20: a dangerous action that is not STOP needs two presses; confirm.js loads on the first one ---------------------------------------
    def call(method, path, body=None):
        req = urllib.request.Request(BASE + "/api/v1" + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))

    site = call("POST", "/sites", {"name": "Home", "kind": "home"})["site"]["id"]
    call("PUT", "/robots/duck-1/site", {"site": site})
    outline = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    for nm in ("Hall", "Pantry"):
        call("POST", f"/sites/{site}/areas", {"name": nm, "type": None, "outline": outline})
    n_areas = lambda: len(call("GET", f"/sites/{site}/areas")["areas"])

    for view, size in (("phone 390x844", {"width": 390, "height": 844}), ("desktop 1440x900", {"width": 1440, "height": 900})):
        arm_page = ctx.new_page()
        arm_page.set_viewport_size(size)
        reqs, calls = [], []
        arm_page.on("request", lambda r: reqs.append(r.url))
        arm_page.on("request", lambda r: calls.append((r.method, r.url)) if r.method in ("POST", "DELETE", "PUT") else None)
        arm_page.goto(BASE + "/")
        arm_page.wait_for_function("window.__mc && window.__mc.ready && window.__mc.S.areas.length === 2", timeout=8000)
        arm_page.wait_for_timeout(800)
        check(f"{view}: the overview has not fetched confirm.js or confirm.css", not [u for u in reqs if "/lib/confirm." in u], [u for u in reqs if "confirm" in u])
        check(f"{view}: STOP and STOP ALL are not armed and carry no confirm", arm_page.evaluate("[...document.querySelectorAll('#stop-robot, #stop-all, #alarm-stop')].every((b) => !b.hasAttribute('data-armed') && !b._dangerous)"))
        for sid, route in STOPS.items():
            with arm_page.expect_request(lambda r, route=route: r.method == "POST" and r.url.endswith("/api/v1" + route), timeout=4000):
                arm_page.click("#" + sid, timeout=4000)
            check(f"{view}: one press on {sid} posts {route} with confirm.js still unfetched", not [u for u in reqs if "/lib/confirm." in u])
        arm_page.wait_for_function("!document.getElementById('toast').hidden")

        del_btn = lambda: arm_page.locator("#area-list [data-action=delete]").first
        is_del = lambda r: r.method == "DELETE" and "/areas/" in r.url
        del_btn().click()
        arm_page.wait_for_function("document.querySelector('#area-list [data-action=delete]').hasAttribute('data-armed')")
        check(f"{view}: the first press on an area's Delete arms it and loads confirm.js and confirm.css",
              any(u.endswith("/lib/confirm.js") for u in reqs) and any(u.endswith("/lib/confirm.css") for u in reqs), reqs[-6:])
        check(f"{view}: armed, the button says so and the polite region announces it",
              del_btn().inner_text() == "Sure?" and arm_page.evaluate("document.querySelector('.ui-confirm-live')?.textContent") == "Sure?")
        check(f"{view}: the first press made no DELETE call and deleted nothing", not [c for c in calls if c[0] == "DELETE"] and n_areas() == 2, calls)
        arm_page.evaluate("window.__mc.renderAreas()")
        check(f"{view}: a redraw of the list does not disarm it", del_btn().get_attribute("data-armed") is not None)
        with arm_page.expect_request(is_del, timeout=4000):
            del_btn().click()
        arm_page.wait_for_function("window.__mc.S.areas.length === 1")
        check(f"{view}: the second press made the DELETE call, once", len([c for c in calls if c[0] == "DELETE"]) == 1 and n_areas() == 1, calls)

        # a timeout disarms without a call: the 6 s is arm()'s default, the page passes no other
        del_btn().click()
        arm_page.wait_for_function("document.querySelector('#area-list [data-action=delete]').hasAttribute('data-armed')")
        arm_page.wait_for_function("!document.querySelector('#area-list [data-action=delete]').hasAttribute('data-armed')", timeout=8000)
        check(f"{view}: after the timeout the button is disarmed and says Delete", del_btn().inner_text() == "Delete")
        check(f"{view}: a timeout made no call", len([c for c in calls if c[0] == "DELETE"]) == 1 and n_areas() == 1, calls)

        # Escape disarms, and a drawer open does not change STOP: one press
        del_btn().click()
        arm_page.wait_for_function("document.querySelector('#area-list [data-action=delete]').hasAttribute('data-armed')")
        arm_page.keyboard.press("Escape")
        check(f"{view}: Escape disarms without a call", del_btn().get_attribute("data-armed") is None and n_areas() == 1)

        # Cancel run is one tap: it stops a run, like STOP, and loses no data
        check(f"{view}: Cancel run is not armed", arm_page.evaluate("!document.getElementById('run-cancel') || !document.getElementById('run-cancel')._dangerous"))
        arm_page.close()
        if view.startswith("phone"):
            call("POST", f"/sites/{site}/areas", {"name": "Hall", "type": None, "outline": outline})

    # STOP with a drawer open (settings edit drawer) still fires on one press, confirm.js unfetched
    drawer_reqs = []
    dp = ctx.new_page()
    dp.on("request", lambda r: drawer_reqs.append(r.url))
    dp.set_viewport_size({"width": 390, "height": 844})
    dp.goto(BASE + "/#robot/duck-1")
    dp.wait_for_function("window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden", timeout=8000)
    dp.click("#tab-settings")
    dp.wait_for_function("!!document.querySelector('#st-blocks [data-block]')")
    dp.click("#st-history-open")
    dp.locator("#st-history").wait_for()
    with dp.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/v1/robots/duck-1/stop"), timeout=4000):
        dp.click("#stop-robot", timeout=4000)
    check("a drawer open: STOP posts on one press, and confirm.js is not fetched", not [u for u in drawer_reqs if "/lib/confirm." in u])
    dp.close()

    # --- U22: panels and layouts: saved in this browser (libs/web/layout/store.js), restored on a reload, reset to the default ---------------------
    LS = "JSON.parse(localStorage.getItem('rl.layouts.control') || 'null')"
    PANEL_IDS = ("fit", "alarms", "parts", "body", "readiness", "joints")
    ALL = list(PANEL_IDS)

    def setrange(page_, rid, px):
        page_.evaluate("([i, v]) => { const r = document.getElementById(i); r.value = v; r.dispatchEvent(new Event('input', {bubbles: true})); r.dispatchEvent(new Event('change', {bubbles: true})); }", [rid, str(px)])

    for view, size in (("phone 390x844", {"width": 390, "height": 844}), ("desktop 1440x900", {"width": 1440, "height": 900})):
        lctx = browser.new_context(viewport=size, color_scheme="dark")
        lp = lctx.new_page()
        lp.set_default_timeout(5000)
        lp.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        lp.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
        lreqs = []
        lp.on("request", lambda r: lreqs.append(r.url))

        def lhit(sid):
            return lp.evaluate("""(id) => { const b = document.getElementById(id), r = b.getBoundingClientRect();
                const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return e && (e === b || b.contains(e)) ? 'button' : (e ? e.tagName + '#' + e.id + '.' + e.className : 'nothing'); }""", sid)

        def lopen(tab_name="overview"):
            lp.goto(BASE + "/#robot/duck-1" + ("" if tab_name == "overview" else "/" + tab_name))
            wait(lp, "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
            wait(lp, "document.getElementById('stop-robot').textContent === 'STOP duck-1'")
            wait(lp, "!!document.querySelector('#rp-layout-menu')")      # layout.js is mounted

        def shown():
            return lp.evaluate("(ids) => ids.filter((i) => !document.querySelector(`[data-panel=${i}]`).hidden)", list(PANEL_IDS))

        def stops_clear(label):
            check(f"{view}, {label}: nothing covers STOP or STOP ALL", all(lhit(s) == "button" for s in STOPS), [lhit(s) for s in STOPS])

        with soft(f"{view}: layouts"):
            lopen()
            check(f"{view}: the layout menu is loaded by the robot page, and starts shut", lp.locator("#rp-layout-menu").is_hidden() and any(u.endswith("/lib/layout/store.js") for u in lreqs), lreqs[-5:])
            check(f"{view}: no layout saved yet: every panel is shown and nothing is stored", shown() == ALL and lp.evaluate(LS) is None, shown())
            lp.click("#rp-layout")
            check(f"{view}: the Layout button opens the menu and says so", lp.locator("#rp-layout-menu").is_visible() and lp.get_attribute("#rp-layout", "aria-expanded") == "true")
            stops_clear("menu open")
            check(f"{view}: the default layout: overview cards all shown, joints column 340 px, cards 420 px", lp.evaluate("""() => ['fit', 'alarms', 'parts', 'body', 'readiness'].every((i) => !document.querySelector(`[data-panel=${i}]`).hidden)
                && document.getElementById('robot-page').style.getPropertyValue('--rp-joints-w') === '340px' && document.getElementById('robot-page').style.getPropertyValue('--rp-card-min') === '420px'"""))

            # hide two panels, fold a third, size the cards: it persists across a reload
            lp.uncheck("#lay-show-alarms")
            lp.uncheck("#lay-show-parts")
            setrange(lp, "lay-w-cards", 560)
            lp.click("#lay-close")
            lp.click("#rp-fit-head")
            check(f"{view}: hiding panels hides them now", shown() == ["fit", "body", "readiness", "joints"], shown())
            saved = lp.evaluate(LS)
            check(f"{view}: the change is in rl.layouts.control under the name default, and the layout in use is default",
                  saved and saved["layouts"]["default"]["panels"]["open"].get("hidden:alarms") is True and saved["layouts"]["default"]["panels"]["open"].get("fit") is False
                  and saved["layouts"]["default"]["widths"].get("cards") == 560 and lp.evaluate("localStorage.getItem('rl.layout.current.control')") == "default", saved)
            lp.reload()
            wait(lp, "window.__mc && window.__mc.ready && !!document.querySelector('#rp-layout-menu')")
            check(f"{view}: after a reload the hidden panels are still hidden", shown() == ["fit", "body", "readiness", "joints"], shown())
            got = lp.evaluate("[document.getElementById('rp-fit-head').getAttribute('aria-expanded'), document.getElementById('robot-page').style.getPropertyValue('--rp-card-min')]")
            check(f"{view}: after a reload the folded card is still folded, the size is kept", got == ["false", "560px"], got)
            stops_clear("two panels hidden, after a reload")

            # every panel hidden: the page says so, the menu brings them back, and STOP is clear throughout
            lp.click("#rp-layout")
            for pid in ("fit", "body", "readiness"):
                lp.uncheck(f"#lay-show-{pid}")
            check(f"{view}: every overview panel hidden: the page says so", lp.locator("#rp-layout-empty").is_visible() and shown() == ["joints"], shown())
            stops_clear("every overview panel hidden, menu open")
            lp.click("#lay-close")
            stops_clear("every overview panel hidden, menu shut")

            # a named layout, then a reset to the default, then the named one back
            lp.click("#rp-layout")
            lp.fill("#lay-name", "bare")
            lp.click("#lay-save")
            check(f"{view}: Save as keeps it under its name and puts it in use", lp.evaluate("[localStorage.getItem('rl.layout.current.control'), Object.keys(" + LS + ".layouts).sort()]") == ["bare", ["bare", "default"]])
            lp.click("#lay-reset")
            check(f"{view}: Reset to default shows every panel and the default sizes", shown() == ALL and lp.evaluate("""document.getElementById('robot-page').style.getPropertyValue('--rp-card-min') === '420px'
                && document.getElementById('rp-fit-head').getAttribute('aria-expanded') === 'true'"""), shown())
            lp.reload()
            wait(lp, "window.__mc && window.__mc.ready && !!document.querySelector('#rp-layout-menu')")
            check(f"{view}: the reset survives a reload", shown() == ALL and lp.evaluate("document.getElementById('robot-page').style.getPropertyValue('--rp-card-min') === '420px'"), shown())
            lp.click("#rp-layout")
            lp.select_option("#lay-list", "bare")
            check(f"{view}: choosing the saved layout brings it back, and it is the one in use", shown() == ["joints"] and lp.evaluate("localStorage.getItem('rl.layout.current.control')") == "bare")
            stops_clear("the saved layout loaded, menu open")
            lp.click("#lay-delete")
            check(f"{view}: Delete removes the saved layout and the default is back", shown() == ALL and lp.evaluate(LS + ".layouts.bare === undefined"))
            lp.click("#lay-close")

            # the Body tab: the joints card hidden and the column widest; the STOP buttons stay clear and the layout is the one for the tab
            lp.click("#tab-body")
            wait(lp, "!document.getElementById('rp-body').hidden")
            lp.click("#rp-layout")
            setrange(lp, "lay-w-joints", 560)
            stops_clear("the Body tab, joints column at 560 px, menu open")
            lp.uncheck("#lay-show-joints")
            check(f"{view}: the joints card hidden leaves the body column alone in its grid", lp.evaluate("document.querySelector('.bodygrid').classList.contains('solo') && document.querySelector('[data-panel=joints]').hidden"))
            stops_clear("the Body tab, joints hidden, menu open")
            lp.reload()
            wait(lp, "window.__mc && window.__mc.ready && !!document.querySelector('#rp-layout-menu')")
            check(f"{view}: the hidden joints card stays hidden after a reload", shown() == ["fit", "alarms", "parts", "body", "readiness"] and lp.evaluate("document.querySelector('[data-panel=joints]').hidden"), shown())
            stops_clear("the Body tab, joints hidden, after a reload")
            lp.click("#rp-layout")
            lp.click("#lay-reset")
            check(f"{view}: reset shows the joints card again", lp.evaluate("!document.querySelector('[data-panel=joints]').hidden && !document.querySelector('.bodygrid').classList.contains('solo')"))
            lp.keyboard.press("Escape")
            check(f"{view}: Escape closes the menu and the focus goes back to the Layout button", lp.locator("#rp-layout-menu").is_hidden() and lp.evaluate("document.activeElement.id") == "rp-layout")

        # STOP with a panel arrangement saved, on a freshly loaded page: still one press, and the menu code has not been asked to confirm anything
        with soft(f"{view}: STOP with the layout menu open"):
            lopen()
            lp.click("#rp-layout")
            for sid, route in STOPS.items():
                with lp.expect_request(lambda r, route=route: r.method == "POST" and r.url.endswith("/api/v1" + route), timeout=4000):
                    lp.click("#" + sid, timeout=4000)
                check(f"{view}, menu open: one press on {sid} posts {route}", True)

        # --- U23: the readiness card: named checks from what GET /robots/{id} carries; a missing field reads unknown, never ok -------------------
        with soft(f"{view}: readiness"):
            lopen()
            wait(lp, "!!document.querySelector('#readiness-checks li')")
            check(f"{view}: the readiness card is a panel of the overview: shown, folds, and sits in the layout menu", lp.locator("[data-panel=readiness]").is_visible()
                  and lp.get_attribute("#rp-readiness-head", "aria-controls") == "rp-readiness-body" and lp.locator("#lay-show-readiness").count() == 1)
            ids = lp.evaluate("[...document.querySelectorAll('#readiness-checks li')].map((l) => l.dataset.check)")
            check(f"{view}: it names its checks", ids == ["online", "gate", "free", "link", "battery", "flags", "alarms", "guardrails", "profile"], ids)
            rows = lp.evaluate("""[...document.querySelectorAll('#readiness-checks li')].map((l) => {
                const b = l.querySelector('.ui-badge'), g = b && b.querySelector('.ui-glyph');
                return [l.dataset.check, l.dataset.status, b && b.dataset.status, g ? g.textContent.trim() : '', b ? b.innerText.replace(g ? g.textContent : '', '').trim() : ''];
            })""")
            check(f"{view}: each check shows a glyph and a word beside its colour, the word the status's own", rows and all(r[1] == r[2] and r[3] and r[4] and r[4] != r[3] for r in rows), rows)
            by = {r[0]: r for r in rows}
            check(f"{view}: the simulated robot is online, its gate answers, nobody holds it, its battery and flags are fine", all(by[k][1] == "ok" for k in ("online", "gate", "free", "battery", "flags")), rows)
            ov = lp.evaluate("[document.getElementById('readiness-overall').dataset.status, document.getElementById('rp-readiness-sum').innerText]")
            check(f"{view}: the card says its verdict in one badge and counts the passes in its head", ov[0] in ("ok", "warn", "error", "unknown") and "of 9" in ov[1], ov)
            # a flag set, a low battery, a holder: each shows as its own status, in words; the verdict follows the worst
            got = lp.evaluate("""() => {
                const mc = window.__mc, r = mc.S.robots.find((x) => x.id === 'duck-1'), keep = JSON.stringify([r.status, r.lock]);
                r.status = {...r.status, flags: {...r.status.flags, near_drop: true}, battery_pct: 12};
                r.lock = {...r.lock, holder: 'someone', unreachable: false};
                mc.renderRobotPage();
                const out = Object.fromEntries([...document.querySelectorAll('#readiness-checks li')].map((l) => [l.dataset.check, l.dataset.status + ' | ' + l.innerText]));
                out.overall = document.getElementById('readiness-overall').dataset.status + ' | ' + document.getElementById('readiness-overall').innerText;
                [r.status, r.lock] = JSON.parse(keep); mc.renderRobotPage();
                return out;
            }""")
            check(f"{view}: a set flag is an error that names the flag", got["flags"].startswith("error") and "near_drop" in got["flags"], got["flags"])
            check(f"{view}: a low battery is an error with its value", got["battery"].startswith("error") and "12" in got["battery"], got["battery"])
            check(f"{view}: a holder is a warning that names the holder", got["free"].startswith("warn") and "someone" in got["free"], got["free"])
            check(f"{view}: the verdict follows the worst check, in words", got["overall"].startswith("error") and "not ready" in got["overall"].lower(), got["overall"])
            # a field the view does not carry: unknown, in words, and never counted as a pass
            miss = lp.evaluate("""async () => {
                const m = await import(new URL('web/readiness.js', location.href).href), fit = [];
                const names = (r) => Object.fromEntries(m.checks(r, fit).map((c) => [c.id, c.status]));
                return {empty: names({id: 'x'}),
                    held: names({id: 'x', online: true, lock: {holder: null}, status: {battery_pct: 40, link: 'usb', flags: {}}, alarms: {worst: null}, guardrails: [{name: 'g'}], profile: null}),
                    bare: names({id: 'x', guardrails: []}),
                    nolock: names({id: 'x', online: false, lock: {unreachable: true}}),
                    over: m.overall(m.checks({id: 'x'}, fit))};
            }""")
            check(f"{view}: a robot view with none of the fields: every check reads unknown", set(miss["empty"].values()) == {"unknown"} and len(miss["empty"]) == 9, miss["empty"])
            check(f"{view}: and the verdict is unknown, not ok", miss["over"]["status"] == "unknown", miss["over"])
            check(f"{view}: fields present read as themselves: an own-file profile is neutral, no declared guardrail a warning", miss["held"]["online"] == "ok" and miss["held"]["free"] == "ok"
                  and miss["held"]["link"] == "ok" and miss["held"]["profile"] == "neutral" and miss["held"]["guardrails"] == "ok" and miss["bare"]["guardrails"] == "warn", (miss["held"], miss["bare"]))
            check(f"{view}: an unreachable gate is an error and says nothing about who holds it", miss["nolock"]["gate"] == "error" and miss["nolock"]["free"] == "unknown" and miss["nolock"]["online"] == "error", miss["nolock"])
            stops_clear("readiness card shown")
            lp.click("#rp-readiness-head")
            check(f"{view}: the card folds on one press and the fold is part of the layout", lp.get_attribute("#rp-readiness-head", "aria-expanded") == "false" and lp.locator("#rp-readiness-body").is_hidden()
                  and lp.evaluate(LS)["layouts"]["default"]["panels"]["open"].get("readiness") is False)
            if lp.locator("#rp-layout-menu").is_hidden():      # lopen() did not reload: the menu may still be open from the block above
                lp.click("#rp-layout")
            lp.click("#lay-reset")
            lp.click("#lay-close")
            check(f"{view}: reset opens it again", lp.get_attribute("#rp-readiness-head", "aria-expanded") == "true")
        lctx.close()

    # the overview does not fetch the layout module or the store, and a stored layout does not change that
    olay = ctx.new_page()
    oreqs = []
    olay.on("request", lambda r: oreqs.append(r.url))
    olay.set_viewport_size({"width": 390, "height": 844})
    olay.goto(BASE + "/")
    olay.wait_for_function("window.__mc && window.__mc.ready", timeout=8000)
    olay.wait_for_timeout(800)
    check("the phone overview fetches neither layout.js nor the layout store nor readiness.js", not [u for u in oreqs if "layout" in u or "readiness" in u], [u for u in oreqs if "layout" in u or "readiness" in u])
    olay.close()

    # --- U25: the palette's verbs (libs/web/palette, loaded on first use) ----------------------------------------------------------------
    for view, size in (("phone 390x844", {"width": 390, "height": 844}), ("desktop 1440x900", {"width": 1440, "height": 900})):
        pctx = browser.new_context(viewport=size, color_scheme="dark")
        pp = pctx.new_page()
        pp.set_default_timeout(5000)
        pp.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        pp.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
        preqs = []
        pp.on("request", lambda r: preqs.append(r.url))
        posts = []
        pp.on("request", lambda r: posts.append(r.url.split("/api/v1")[-1]) if r.method == "POST" else None)

        def phit(sid):
            return pp.evaluate("""(id) => { const b = document.getElementById(id), r = b.getBoundingClientRect();
                const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return e && (e === b || b.contains(e)) ? 'button' : (e ? e.tagName + '#' + e.id + '.' + e.className : 'nothing'); }""", sid)

        def popen_page(hash_=""):
            pp.goto(BASE + "/" + hash_)
            wait(pp, "window.__mc && window.__mc.ready")
            wait(pp, "document.getElementById('stop-robot').textContent === 'STOP duck-1'")

        def rows():
            return pp.evaluate("[...document.querySelectorAll('.pal-row')].map((r) => [r.dataset.verb, r.dataset.danger, r.querySelector('.pal-title').textContent])")

        def palette_open():
            return pp.evaluate("!!document.querySelector('.pal') && !document.querySelector('.pal').hidden")

        def ask(text):
            pp.keyboard.type(text)
            pp.wait_for_timeout(60)

        def palette_via_key():
            wait(pp, "document.activeElement.tagName !== 'INPUT'")      # a palette just closed leaves the focus on its hidden input until the next layout: a key then would count as typed
            pp.keyboard.press("Control+k")
            wait(pp, "!!document.querySelector('.pal') && !document.querySelector('.pal').hidden && document.querySelectorAll('.pal-row').length > 0")

        def palette_close():
            if palette_open():
                pp.focus(".pal-input")        # a tap on STOP leaves the focus outside the box, where Escape does not reach it
                pp.keyboard.press("Escape")
                wait(pp, "document.querySelector('.pal').hidden")

        with soft(f"{view}: palette, lazy load"):
            popen_page()
            pp.wait_for_timeout(600)
            check(f"{view}: the overview fetches no palette module and no palette style before it is used", not [u for u in preqs if "palette" in u], [u for u in preqs if "palette" in u])
            check(f"{view}: the top bar has a palette button, static HTML, outside the STOP bar",
                  pp.evaluate("(() => { const b = document.getElementById('palette-btn'); return !!b && !b.closest('.stops') && b.getAttribute('aria-label') === 'Command palette' && /Control\\+K/.test(b.getAttribute('aria-keyshortcuts') || ''); })()"))
            # a key typed in an input never opens it, and does not load it
            pp.focus("#say")
            pp.keyboard.press("Control+k")
            pp.wait_for_timeout(400)
            check(f"{view}: Ctrl+K typed in an input opens nothing and loads nothing", not [u for u in preqs if "palette" in u] and not palette_open(), [u for u in preqs if "palette" in u])
            pp.evaluate("document.activeElement.blur()")
            palette_via_key()
            got = [u.rsplit("/", 1)[-1] for u in preqs if "palette" in u]
            check(f"{view}: Ctrl+K loads palette-verbs.js, palette.js, registry.js and palette.css on first use, and opens", {"palette-verbs.js", "palette.js", "registry.js", "palette.css"} <= set(got) and palette_open(), got)
            check(f"{view}: opening it on the overview fetches no layout store, layout.js or readiness.js", not [u for u in preqs if "layout" in u or "readiness" in u], [u for u in preqs if "layout" in u or "readiness" in u])
            pp.keyboard.press("Escape")
            wait(pp, "document.querySelector('.pal').hidden")
            pp.click("#palette-btn")
            wait(pp, "!document.querySelector('.pal').hidden")
            check(f"{view}: the top-bar button opens it too", palette_open())
            palette_close()
            check(f"{view}: closed, focus returns to the palette button", pp.evaluate("document.activeElement.id") == "palette-btn")

        with soft(f"{view}: palette, STOP first and unconfirmed"):
            popen_page()
            palette_via_key()
            r = rows()
            check(f"{view}: STOP and STOP ALL are the first two verbs, danger stop", [x[:2] for x in r[:2]] == [["stop.robot", "stop"], ["stop.all", "stop"]], r[:3])
            check(f"{view}: the STOP rows have no confirm button", pp.locator(".pal-row[data-danger=stop] .pal-confirm").count() == 0)
            n = len(posts)
            pp.keyboard.press("Enter")
            wait(pp, "!document.getElementById('toast').hidden")
            check(f"{view}: one Enter on the first row posts the robot's stop, once", posts[n:] == ["/robots/duck-1/stop"], posts[n:])
            palette_via_key()
            ask("stop all")
            check(f"{view}: typed 'stop all', STOP ALL is first", rows()[0][0] == "stop.all", rows()[:2])
            n = len(posts)
            pp.keyboard.press("Enter")
            wait(pp, "document.getElementById('toast').textContent.includes('stopped')")
            check(f"{view}: one Enter runs STOP ALL, posting /stop once", posts[n:] == ["/stop"], posts[n:])
            check(f"{view}: and the palette is closed", not palette_open())

        with soft(f"{view}: palette, verbs of the overview"):
            popen_page()
            palette_via_key()
            ids = [x[0] for x in rows()]
            check(f"{view}: the overview lists navigation and the theme, and no panel or layout verb", "nav.overview" in ids and "nav.robot.duck-1" in ids and "nav.tab.duck-1.body" in ids and "theme.toggle" in ids
                  and not [i for i in ids if i.startswith(("panel.", "layout."))], ids)
            before = pp.evaluate("document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')")
            ask("theme")
            pp.keyboard.press("Enter")
            pp.wait_for_timeout(100)
            after = pp.evaluate("document.documentElement.dataset.theme")
            check(f"{view}: the theme verb switches the theme", after in ("light", "dark") and after != before, (before, after))
            pp.evaluate("localStorage.removeItem('mc-theme'); delete document.documentElement.dataset.theme")
            palette_via_key()
            ask("duck-1 body")
            check(f"{view}: 'duck-1 body' finds the robot's Body tab first", rows()[0][0] == "nav.tab.duck-1.body", rows()[:3])
            pp.keyboard.press("Enter")
            wait(pp, "location.hash === '#robot/duck-1/body' && !document.getElementById('rp-body').hidden")
            check(f"{view}: and Enter opens it", True)
            palette_via_key()
            ask("overview")
            check(f"{view}: 'overview' finds the way back to the robots", rows()[0][0] == "nav.overview", rows()[:3])
            pp.keyboard.press("Enter")
            wait(pp, "location.hash === '' && document.getElementById('robot-page').hidden")
            check(f"{view}: and Enter goes there", True)
            palette_via_key()
            ask("open duck-1")
            pp.keyboard.press("Enter")
            wait(pp, "location.hash === '#robot/duck-1'")
            check(f"{view}: 'open duck-1' opens the robot's page", True)

        with soft(f"{view}: palette, panels and layouts"):
            popen_page("#robot/duck-1")
            pp.evaluate("localStorage.removeItem('rl.layouts.control'); localStorage.removeItem('rl.layout.current.control')")
            pp.reload()
            wait(pp, "window.__mc && window.__mc.ready && !!document.querySelector('#rp-layout-menu')")
            palette_via_key()
            ids = [x[0] for x in rows()]
            check(f"{view}: on a robot page the palette lists hide, fold and layout verbs", {"panel.hide.readiness", "panel.fold.parts", "layout.save", "layout.reset"} <= set(ids)
                  and "panel.show.readiness" not in ids and "panel.unfold.parts" not in ids, ids)
            ask("hide readiness")
            pp.keyboard.press("Enter")
            wait(pp, "document.querySelector('[data-panel=readiness]').hidden")
            check(f"{view}: 'Hide Readiness' hides the card, through the layout store", pp.evaluate("JSON.parse(localStorage.getItem('rl.layouts.control')).layouts.default.panels.open['hidden:readiness']") is True)
            palette_via_key()
            ids = [x[0] for x in rows()]
            check(f"{view}: hidden, the palette offers Show and no longer Hide", "panel.show.readiness" in ids and "panel.hide.readiness" not in ids, ids)
            ask("show readiness")
            pp.keyboard.press("Enter")
            wait(pp, "!document.querySelector('[data-panel=readiness]').hidden")
            check(f"{view}: 'Show Readiness' shows it again", True)
            palette_via_key()
            ask("fold parts")
            pp.keyboard.press("Enter")
            wait(pp, "document.getElementById('rp-parts-head').getAttribute('aria-expanded') === 'false'")
            check(f"{view}: 'Fold Parts' folds the card and the fold is part of the layout", pp.evaluate("JSON.parse(localStorage.getItem('rl.layouts.control')).layouts.default.panels.open.parts") is False)
            palette_via_key()
            ask("save layout")
            pp.keyboard.press("Enter")
            wait(pp, "!!JSON.parse(localStorage.getItem('rl.layouts.control')).layouts['Layout 1']")
            check(f"{view}: 'Save layout' saves the arrangement under a new name and says so", pp.evaluate("document.getElementById('toast').textContent").startswith("Saved as Layout 1"))
            palette_via_key()
            ask("reset layout")
            pp.keyboard.press("Enter")
            wait(pp, "document.getElementById('rp-parts-head').getAttribute('aria-expanded') === 'true'")
            check(f"{view}: 'Reset layout' returns the default arrangement", True)
            palette_via_key()
            ask("load layout 1")
            check(f"{view}: the saved layout is a verb of its own", rows()[0][0] == "layout.load.Layout 1", rows()[:3])
            pp.keyboard.press("Enter")
            wait(pp, "document.getElementById('rp-parts-head').getAttribute('aria-expanded') === 'false'")
            check(f"{view}: loading it brings the fold back", True)
            # a verb that fails says so on the page, not only in the console: the layout is deleted behind the palette's back
            palette_via_key()
            ask("load layout 1")
            pp.evaluate("""() => { const k = 'rl.layouts.control', b = JSON.parse(localStorage.getItem(k)); delete b.layouts['Layout 1']; localStorage.setItem(k, JSON.stringify(b)); }""")
            pp.keyboard.press("Enter")
            wait(pp, "!document.getElementById('toast').hidden && document.getElementById('toast').classList.contains('err')")
            msg = pp.evaluate("document.getElementById('toast').textContent")
            check(f"{view}: a verb that fails shows its error in the toast", "Layout 1" in msg, msg)
            pp.evaluate("localStorage.removeItem('rl.layouts.control'); localStorage.removeItem('rl.layout.current.control')")

        with soft(f"{view}: palette over the STOP bar"):
            popen_page("#robot/duck-1")
            palette_via_key()
            check(f"{view}: with the palette open nothing covers STOP or STOP ALL", all(phit(s) == "button" for s in STOPS), [phit(s) for s in STOPS])
            z = pp.evaluate("[+getComputedStyle(document.querySelector('.pal')).zIndex, +getComputedStyle(document.querySelector('.stops')).zIndex]")
            check(f"{view}: the palette sits below STOP in z-order", z[0] < z[1], z)
            n = len(posts)
            with pp.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/v1/stop"), timeout=4000):
                pp.click("#stop-all", timeout=4000)
            check(f"{view}: a tap on STOP ALL with the palette open posts /stop", posts[n:] == ["/stop"], posts[n:])
            palette_close()

        with soft(f"{view}: palette verbs, what they are"):
            popen_page()
            spec = pp.evaluate("""async () => {
                const m = await import(new URL('web/palette-verbs.js', location.href).href);
                const app = { robots: () => [{id: 'a', label: 'A'}, {id: 'b', label: 'B'}], route: () => ({id: 'a', tab: 'overview'}), tabs: ['overview', 'body', 'modules', 'settings', 'calibration'],
                    hashOf: (id, t) => '#robot/' + id + (t ? '/' + t : ''), stopRobotId: () => 'a', layout: () => null, pathname: () => '/control/', observatoryHref: () => '/', go() {}, visit() {}, stop() {}, stopAll() {}, theme() {}, themeNow: () => 'dark', toast() {} };
                const off = { ...app, pathname: () => '/' };
                return {on: m.verbSpecs(app).map((v) => [v.id, v.title, v.danger, v.api ?? null, v.mcp ?? null]), off: m.verbSpecs(off).map((v) => v.id)};
            }""")
            ids = [v[0] for v in spec["on"]]
            check(f"{view}: STOP and STOP ALL come first, as the only danger-stop verbs", [v[2] for v in spec["on"][:2]] == ["stop", "stop"] and [v[2] for v in spec["on"]].count("stop") == 2, spec["on"][:3])
            check(f"{view}: no other verb is dangerous: none needs a confirm, none is a robot action", all(v[2] in ("none", "stop") for v in spec["on"]))
            bad = [v[:2] for v in spec["on"] if re.search(r"goal|takeover|take over|lease|lock|run now|explore|inventory|drive|move|dock", v[0] + " " + v[1], re.I)]
            check(f"{view}: no verb starts a goal, takes over, takes a lease or moves a robot", bad == [], bad)
            check(f"{view}: no verb mirrors an API route or an MCP tool", all(v[3] is None and v[4] is None for v in spec["on"]))
            check(f"{view}: each robot has an open verb and each tab a verb", {"nav.robot.a", "nav.robot.b", "nav.tab.a.body", "nav.tab.b.calibration", "nav.tab.a.settings", "nav.tab.b.modules"} <= set(ids), ids)
            check(f"{view}: the Observatory link is a verb under /control/ and absent on a port of its own", "nav.observatory" in ids and "nav.observatory" not in spec["off"], (ids, spec["off"]))
        pctx.close()

    # --- U24: evidence links: "open in the Observatory at this moment", one format for both apps (libs/web/evidence.js) ----------------------------
    RUN_KEY = "duck/room/mc7-1700"
    WATCH = f"http://127.0.0.1:8070/watch/{RUN_KEY}"
    MOMENT = f"{BASE}/web/three/#scene=room&run=duck%2Froom%2Fmc7-1700&view=3d&t=3.5&focus=robot"
    ANOMALY = {"n": 1, "t": 3.5, "anomaly": "joint_overload", "source": "robot", "module": "body", "severity": "major", "detector": "joint_current",
               "summary": "left_knee at 130 mA, at or over 120 mA for 1.0 s", "margin": 10, "values": {"joint": "left_knee", "ma": 130, "margin_unit": "mA"}}
    SYNTH_RUN = {"id": 7, "goal_id": None, "goal": {"name": "explore", "folder": "", "kind": "explore", "params": {}}, "robot": "duck-1", "site": None, "target": None,
                 "state": "reached", "reason": None, "progress": {"elapsed_s": 12.5}, "result": {"area_m2": 3}, "broken": None, "guardrails": [], "conditions": {},
                 "run_key": RUN_KEY, "watch": WATCH, "expect": None, "as_expected": None, "decisions": [], "anomalies": [], "created_at": 0, "started_at": 0, "ended_at": 0}

    with soft("evidence: the shared module"):
        sctx = browser.new_context(viewport={"width": 1440, "height": 900})
        sp = sctx.new_page()
        sp.goto(BASE + "/")
        got = sp.evaluate("""async () => {
            const m = await import('/lib/evidence.js'), loc = {origin: 'http://o', pathname: '/web/three/'};
            const a = {loc, scene: 's', run: 'a/s/r 1', view: '3d', t: 1.23456, focus: 'robot'};
            return {names: Object.keys(m).sort(), link: m.momentLink(a), nofocus: m.momentLink({...a, focus: 'other'}), href: m.evidenceHref({origin: 'http://o', runKey: 'duck/room/r1', t: 2}),
                    notime: m.evidenceHref({origin: 'http://o', runKey: 'duck/room/r1', t: null}), short: m.evidenceHref({origin: 'http://o', runKey: 'room/r1', t: 2}),
                    none: m.evidenceHref({origin: 'http://o', runKey: null, t: 2}),
                    parsed: m.parseMoment(new URL(m.evidenceHref({origin: 'http://o', runKey: 'duck/room/r1', t: 2.25})).hash), junk: m.parseMoment('#t=abc&focus=nope')};
        }""")
        check("/lib/evidence.js is served and exports the builder, the parser, the focus list and copyText", {"momentLink", "parseMoment", "FOCUS", "copyText", "evidenceHref"} <= set(got["names"]), got["names"])
        check("the link is `#scene&run&view&t&focus` in that order, the run URL-encoded, t to 3 decimals", got["link"] == "http://o/web/three/#scene=s&run=a%2Fs%2Fr+1&view=3d&t=1.235&focus=robot", got["link"])
        check("an unknown focus is left out", got["nofocus"] == "http://o/web/three/#scene=s&run=a%2Fs%2Fr+1&view=3d&t=1.235", got["nofocus"])
        check("a run key is robot/scene/run: its scene is the middle part", got["href"] == "http://o/web/three/#scene=room&run=duck%2Froom%2Fr1&view=3d&t=2&focus=robot", got["href"])
        check("no time reads as the run's start", got["notime"].endswith("&t=0&focus=robot"), got["notime"])
        check("a key that is not robot/scene/run, or no key, makes no link", got["short"] is None and got["none"] is None, (got["short"], got["none"]))
        check("the parser reads what the builder wrote, and ignores what is not a time or a focus", got["parsed"] == {"t": 2.25, "focus": "robot"} and got["junk"] == {"t": None, "focus": None}, (got["parsed"], got["junk"]))
        sctx.close()

    for view, size, scheme in (("phone 390x844", {"width": 390, "height": 844}, "light"), ("desktop 1440x900", {"width": 1440, "height": 900}, "dark")):
        for under in (False, True):
            where = "behind the Observatory at /control/" if under else "on its own port"
            ectx = browser.new_context(viewport=size, color_scheme=scheme)
            ep = ectx.new_page()
            ep.set_default_timeout(5000)
            ep.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            ep.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
            ereqs = []
            ep.on("request", lambda r: ereqs.append(r.url))
            if under:      # the page's address is /control/...; its requests go to the same server without the prefix, as the Observatory's proxy does
                ep.route(re.compile(r"/control/"), lambda r: r.continue_(url=r.request.url.replace("/control/", "/", 1)))
            runs_live = [False]
            ep.route(re.compile(r"/api/v1/goal-runs(\?|/)"), lambda r: r.fulfill(json={"ok": True, "runs": [SYNTH_RUN]} if "?" in r.request.url else {"ok": True, "run": SYNTH_RUN})
                     if runs_live[0] else r.fallback())
            root = BASE + ("/control/" if under else "/")
            evidence_fetched = lambda: [u for u in ereqs if u.endswith("/lib/evidence.js")]

            with soft(f"{view}, {where}: evidence"):
                ep.goto(root)
                wait(ep, "window.__mc && window.__mc.ready")
                ep.wait_for_timeout(300)
                check(f"{view}, {where}: the phone overview with no run and no alarm fetches evidence.js not at all", evidence_fetched() == [], evidence_fetched())
                mc.bus.emit("anomaly", robot="duck-1", goal_run=7, watch=WATCH + "#t=3.5", anomaly=ANOMALY)
                wait(ep, "!document.getElementById('alarm').hidden")
                ep.click("#alarm")
                wait(ep, "!document.getElementById('alarms').hidden && !!document.querySelector('#alarm-insp h3')")
                if under:
                    wait(ep, "!!document.querySelector('#alarm-insp a.evidence')")
                    a = ep.locator("#alarm-insp a.evidence")
                    check(f"{view}, {where}: the alarm's moment links to the Observatory's 3D view at its time, framing the robot", a.count() == 1 and a.get_attribute("href") == MOMENT, a.get_attribute("href"))
                    check(f"{view}, {where}: the link says what it does and opens in a new tab safely", a.inner_text().strip() == "Open in the Observatory at this moment" and a.get_attribute("target") == "_blank"
                          and "noopener" in (a.get_attribute("rel") or ""))
                    check(f"{view}, {where}: it is the only Observatory link in the alarm's inspector", ep.locator("#alarm-insp a", has_text="Observatory").count() == 1)
                    rt = ep.evaluate("""async (h) => { const m = await import('/lib/evidence.js'); return m.parseMoment(new URL(h).hash); }""", MOMENT)
                    check(f"{view}, {where}: the parser reads the link back to the alarm's time and the robot focus", rt == {"t": 3.5, "focus": "robot"}, rt)
                    ep.evaluate("""() => { const t = document.getElementById('alarm-insp'); t.__seen = [...t.querySelectorAll('a.evidence')].map((a) => getComputedStyle(a).color); }""")
                else:
                    ep.wait_for_timeout(300)
                    check(f"{view}, {where}: there is no evidence link (the Observatory is not at this origin) and evidence.js is not fetched",
                          ep.locator("a.evidence").count() == 0 and evidence_fetched() == [], (ep.locator("a.evidence").count(), evidence_fetched()))
                    check(f"{view}, {where}: the alarm still opens its watch page at the configured address",
                          ep.locator("#alarm-insp a", has_text="Observatory").get_attribute("href") == WATCH + "#t=3.5")
                ep.click("#alarm")      # close the panel again

            with soft(f"{view}, {where}: evidence on the robot page"):
                ep.goto(root + "#robot/duck-1")
                wait(ep, "!document.getElementById('robot-page').hidden && document.getElementById('stop-robot').textContent === 'STOP duck-1'")
                wait(ep, "!!document.querySelector('#rp-alarms-body .alarmrows li')")
                wait(ep, "!!document.querySelector('#readiness-checks li')")
                if under:
                    wait(ep, "!!document.querySelector('#rp-alarms-body a.evidence') && !!document.querySelector('#readiness-checks [data-check=alarms] a.evidence')")
                    row = ep.locator("#rp-alarms-body a.evidence")
                    check(f"{view}, {where}: the robot page's alarm row has the same link", row.count() == 1 and row.get_attribute("href") == MOMENT, row.get_attribute("href"))
                    rd = ep.locator("#readiness-checks [data-check=alarms] a.evidence")
                    li = ep.locator("#readiness-checks [data-check=alarms]")
                    check(f"{view}, {where}: the readiness card's alarm check has it, beside its status glyph and word", rd.get_attribute("href") == MOMENT and li.get_attribute("data-status") == "error"
                          and li.locator(".ui-badge .ui-glyph").count() == 1, (rd.get_attribute("href"), li.get_attribute("data-status")))
                    check(f"{view}, {where}: no sideways scrolling with the links shown", ep.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
                    check(f"{view}, {where}: STOP and STOP ALL are still on top", ep.evaluate("""() => ['stop-robot', 'stop-all'].every((id) => { const b = document.getElementById(id), r = b.getBoundingClientRect();
                        const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e === b || b.contains(e); })"""))
                    ep.screenshot(path=str(SHOTS_U24 / f"mc-robot-alarm-evidence-{'phone-light' if size['width'] < 600 else 'desktop-dark'}.png"), full_page=True)
                else:
                    ep.wait_for_timeout(300)
                    check(f"{view}, {where}: the robot page shows no evidence link and does not fetch evidence.js", ep.locator("a.evidence").count() == 0 and evidence_fetched() == [], evidence_fetched())

            with soft(f"{view}, {where}: evidence on a goal run"):
                runs_live[0] = True
                ep.goto(root)
                wait(ep, "window.__mc && window.__mc.ready")
                wait(ep, "!!document.querySelector('#run-detail[data-run=\"7\"]')")
                if under:
                    wait(ep, "!!document.querySelector('#run-detail a.evidence')")
                    g = ep.locator("#run-detail a.evidence")
                    want = f"{BASE}/web/three/#scene=room&run=duck%2Froom%2Fmc7-1700&view=3d&t=12.5&focus=robot"
                    check(f"{view}, {where}: a finished goal run's result links to the Observatory at the run's last moment (its elapsed time)", g.count() == 1 and g.get_attribute("href") == want, g.get_attribute("href"))
                    ep.screenshot(path=str(SHOTS_U24 / f"mc-run-evidence-{'phone-light' if size['width'] < 600 else 'desktop-dark'}.png"), full_page=True)
                    ep.evaluate("location.hash = '#robot/duck-1'")
                    wait(ep, "!document.getElementById('robot-page').hidden && !!document.querySelector('#readiness-checks li')")
                    ep.evaluate("""() => { const mc = window.__mc, r = mc.S.robots.find((x) => x.id === 'duck-1'); r.lock = {...r.lock, holder: 'someone', unreachable: false}; r.goal_run = 7; mc.renderRobotPage(); }""")
                    f = ep.locator("#readiness-checks [data-check=free] a.evidence")
                    f.wait_for()
                    check(f"{view}, {where}: a robot held by a goal run links that run at its start", f.get_attribute("href") == f"{BASE}/web/three/#scene=room&run=duck%2Froom%2Fmc7-1700&view=3d&t=0&focus=robot", f.get_attribute("href"))
                else:
                    ep.wait_for_timeout(300)
                    check(f"{view}, {where}: a goal run shows no evidence link, only its Watch link", ep.locator("a.evidence").count() == 0 and ep.locator("#watch").get_attribute("href") == WATCH and evidence_fetched() == [])
            ectx.close()

    # reduced motion: the chevron's transition is gone
    def chevron_ms(reduced):
        c2 = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", reduced_motion="reduce" if reduced else "no-preference")
        p2 = c2.new_page()
        p2.goto(BASE + "/#robot/duck-1")
        p2.wait_for_function("window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden", timeout=8000)
        v = p2.evaluate("getComputedStyle(document.querySelector('.shead .chev')).transitionDuration")
        c2.close()
        return v
    full, reduced = chevron_ms(False), chevron_ms(True)
    check("motion allowed: the chevron turns over a --dur-fast transition", full not in ("0s", ""), full)
    check("reduced motion: the chevron's transition is zero", reduced == "0s", reduced)

    check("no script error and no console error in the whole session (a 4xx the page was told about is not one)", [e for e in errors if "status of 4" not in e] == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_look_page")
