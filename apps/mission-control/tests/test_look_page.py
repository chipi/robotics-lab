"""Mission Control's look-and-feel guards (step 4.5, unit U-STOP) in headless Chromium, set up as test_calibration_page.py is: STOP and
STOP ALL are one tap and never under another layer. With each drawer open (the Settings edit drawer, History and compare, the Calibration
drawer) and with the toast showing, at phone and at desktop width: the element at the centre of each STOP button is that button, a real
click on it makes its API call, and on a phone the drawer ends above the STOP bar instead of running under it.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
from contextlib import contextmanager
import os
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

    check("no script error and no console error in the whole session (a 4xx the page was told about is not one)", [e for e in errors if "status of 4" not in e] == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_look_page")
