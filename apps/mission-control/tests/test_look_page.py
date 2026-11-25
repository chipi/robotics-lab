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
        check(f"{label}: completed", False, f"{type(exc).__name__}: {str(exc).splitlines()[0]}")


WEB = Path(__file__).resolve().parents[1] / "src" / "mission_control" / "web"
FAKE = mc.robots["duck-1"].adapter.robot
STOPS = {"stop-robot": "/robots/duck-1/stop", "stop-all": "/stop"}
errors = []

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
