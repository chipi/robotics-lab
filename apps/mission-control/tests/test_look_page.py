"""Mission Control's look-and-feel guards (step 4.5, unit U-STOP) in headless Chromium, set up as test_calibration_page.py is: STOP and
STOP ALL are one tap and never under another layer. With each drawer open (the Settings edit drawer, History and compare, the Calibration
drawer) and with the toast showing, at phone and at desktop width: the element at the centre of each STOP button is that button, a real
click on it makes its API call, and on a phone the drawer ends above the STOP bar instead of running under it.

U19 (the restyle on the shared tokens and kit): style.css holds no hex; the top bar's brand is brand.js's; a state is a status badge (glyph and word); a robot
whose state is old dims its values and says how old, and disables the actions that need a fresh state, while STOP, STOP ALL and the alarm panel's stop
stay enabled and fire on the first click; a kit module that fails to load leaves the page and STOP usable; the overview fetches no three.js; reduced motion
zeroes the chevron's transition.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
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
    page.evaluate("window.__mc.S.robots[0].state_at = Date.now() - 40000; window.__mc.tickFreshness();")
    wait(page, "document.querySelector('#robot-duck-1 [data-age]')?.textContent.includes('offline')")
    check("a robot silent for 30 s or more is offline, its Run disabled", page.evaluate("window.__mc.freshOf(window.__mc.S.robots[0]) === 'offline' && document.getElementById('g-run').disabled"))
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
    heavy = [u for u in seen if "/lib/vendor/" in u or "three" in u.lower() or "bodyview" in u]
    check("the overview fetches no three.js, vendor module or body view", heavy == [], heavy)
    check("the overview loads the kit's status, brand and motion modules", all(any(u.endswith(f"/lib/{m}.js") for u in seen) for m in ("status", "brand", "motion")), seen)
    light.close()

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
