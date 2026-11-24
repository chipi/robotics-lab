"""Mission Control's robot page, Calibration (RFC-0023 D11, phase 5 item 4a unit A3) in headless Chromium, as test_settings_page.py does it:
the real server, pointer robots to the duck's profile behind the fake adapter (whose calibration is arithmetic over the clock) and a
writable version store under a test installation. Calibration lists a card per procedure with the value now and the measured lines below
it; the card opens the same side drawer as Settings (Esc and the scrim close it, the focus goes back): the step guide, the parameters, a
run that is polled while it runs and can be cancelled, then what it measured beside the value now and what keeping it changes, kept as the
next settings version. A robot whose runner has no truth asks for the operator's tape; a value outside its bounds cannot be kept. Every
number goes through the calibration API. Phone width has no sideways scrolling and 44 px controls.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
from contextlib import contextmanager
import json
import os
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import check, finish, installation_file

from observatory.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation
from runfile.profilestore import Store

tmp = Path(tempfile.mkdtemp(prefix="mc-calibration-page-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)
REPO_FILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
STATE = tmp / "inst-state"
FOLDER = STATE / "profiles" / "duck"
Store(STATE / "profiles").seed("duck", REPO_FILE)
inst = tmp / "installation.json"
installation_file(inst, {"duck": {"variant": "sim", "profile": str(FOLDER)}}, state=str(STATE))
os.environ[installation.ENV] = str(inst)


def duck(rid, **adapter):
    return RobotConfig({"id": rid, "robot": "duck", "variant": "sim", "adapter": {"type": "fake", **adapter}})


mc = MissionControl([duck("duck-1"), duck("duck-tape", calibration={"truth": False})], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def get(path):
    with urllib.request.urlopen(BASE + "/api/v1" + path, timeout=10) as r:
        return json.loads(r.read())


def wait(page, js, timeout=8000, arg=None):
    page.wait_for_function(js, arg=arg, timeout=timeout)


errors = []


@contextmanager
def soft(label):
    try:
        yield
    except Exception as exc:
        check(f"{label}: completed", False, f"{type(exc).__name__}: {str(exc).splitlines()[0]}")


with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    no_scroll = lambda: page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    drawer = lambda: page.locator("#drawer-root .scrim:not([hidden])")
    active = lambda: page.evaluate("document.activeElement.id")
    card = lambda: page.locator("[data-procedure=odometry_scale]")
    card_status = lambda: page.locator("[data-procedure=odometry_scale] [data-cal-status]").inner_text()

    def open_page(n, rid="duck-1"):
        page.goto(BASE + f"/?visit={n}#robot/{rid}/calibration")
        wait(page, "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
        wait(page, "!!document.querySelector('[data-procedure=odometry_scale]')")

    def close_drawer():
        if drawer().count():
            page.keyboard.press("Escape")
            wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")

    def open_drawer():
        close_drawer()
        page.click("#cal-open-odometry_scale")
        page.locator("#cal-drawer").wait_for()

    def set_seconds(v):
        page.fill("#cal-seconds", str(v))

    open_page(1)

    # --- the tab: a card per procedure, the measured lines under it -----------------------------------------------------------------
    with soft("Calibration tab"):
        check("must fail: one card, odometry_scale, with the value now (0.91) and what it sets", card().count() == 1
              and "now 0.91" in card().inner_text() and "localisation.odometry.scale" in card().inner_text(), card().inner_text())
        check("must fail: the Calibrate button is on, and says no run yet", page.locator("#cal-open-odometry_scale").is_enabled() and card_status() == "no run yet", card_status())
        rows = page.eval_on_selector_all("#cal-table tr[data-path]", "(els) => els.map((e) => [e.dataset.path, e.dataset.layer])")
        check("the measured lines are still listed below it (the base and the sim variant)", ["joints.limits", "sim"] in rows and ["localisation.odometry", "sim"] in rows, rows)
        check("no sideways scrolling on Calibration at 390 px", no_scroll())

    # --- the drawer: the guide, the parameters; Esc and the scrim close it -------------------------------------------------------------
    with soft("the drawer"):
        open_drawer()
        steps = page.eval_on_selector_all("#cal-steps li", "(els) => els.map((e) => [e.dataset.step, e.dataset.status])")
        check("must fail: the guide has the four steps, none done yet", steps == [["place", "todo"], ["walk", "todo"], ["measure", "todo"], ["keep", "todo"]], steps)
        check("must fail: the parameters are the navigator's defaults (8 s, 0.3 m/s) and Start is on, Keep is not offered",
              page.input_value("#cal-seconds") == "8" and page.input_value("#cal-speed_mps") == "0.3" and page.locator("#cal-start").is_enabled() and page.locator("#cal-keep").count() == 0)
        check("the guide says the walk is blind and who does each step", "blind" in page.locator("#cal-steps").inner_text() and "runner" in page.locator("#cal-steps").inner_text())
        page.keyboard.press("Escape")
        wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")
        check("must fail: Esc closes it and the focus goes back to the button that opened it", drawer().count() == 0 and active() == "cal-open-odometry_scale", active())

    # --- a run, cancelled; then one that is measured -------------------------------------------------------------------------------------
    with soft("a run"):
        open_drawer()
        set_seconds(2)
        page.click("#cal-start")
        wait(page, "document.querySelector('#cal-live')?.textContent.includes('walking')")
        steps = page.eval_on_selector_all("#cal-steps li", "(els) => els.map((e) => e.dataset.status)")
        check("must fail: while it runs: place done, the walk now, the parameters off, Cancel offered and Start not", steps == ["done", "now", "todo", "todo"]
              and page.locator("#cal-seconds").is_disabled() and page.locator("#cal-cancel").is_visible() and page.locator("#cal-start").count() == 0, steps)
        check("the card behind says it runs", card_status() == "running", card_status())
        page.click("#cal-cancel")
        wait(page, "document.querySelector('#cal-reason')?.textContent.includes('cancelled')")
        check("must fail: a cancel ends it cancelled, with its reason; the button becomes Run again and the parameters come back",
              page.locator("#cal-start").inner_text() == "Run again" and page.locator("#cal-seconds").is_enabled() and page.locator("#cal-keep").count() == 0)
        page.click("#cal-start")
        wait(page, "document.querySelector('#cal-value')?.textContent === '0.909'", timeout=10000)
        check("must fail: done: the odometry read 0.66 m, the reference 0.6 m by the simulator's truth, measured 0.909 beside now 0.91",
              page.locator("#cal-result").inner_text().count("0.66 m") == 1 and page.locator("#cal-ref").inner_text() == "0.6 m"
              and "simulator's truth" in page.locator("#cal-result").inner_text() and page.locator("#cal-now").inner_text() == "0.91",
              page.locator("#cal-result").inner_text())
        steps = page.eval_on_selector_all("#cal-steps li", "(els) => els.map((e) => e.dataset.status)")
        writes = page.eval_on_selector_all("#cal-writes [data-path]", "(els) => els.map((e) => e.dataset.path)")
        check("must fail: the steps are done but Keep; what keeping changes is listed (the 0.3 entry and scale); Keep as version 2 is on",
              steps == ["done", "done", "done", "now"] and writes == ["localisation.odometry.by_speed.0.3", "localisation.odometry.scale"]
              and page.locator("#cal-keep").inner_text() == "Keep as version 2" and page.locator("#cal-keep").is_enabled(), (steps, writes))
        page.screenshot(path=str(SHOTS / "rp-calibration-drawer-phone-dark.png"))
        close_drawer()
        check("the card behind says measured: 0.909", card_status() == "measured: 0.909", card_status())

    # --- keep --------------------------------------------------------------------------------------------------------------------------------------
    with soft("keep"):
        open_drawer()
        page.click("#cal-keep")
        wait(page, "document.querySelector('#cal-drawer .calbody')?.textContent.includes('Kept as version 2')")
        check("must fail: kept as version 2: the store holds it, the sim variant's scale is 0.909 and Mission Control runs it",
              get("/robots/duck-1/profile")["profile"]["current"] == 2
              and json.loads((FOLDER / "2.json").read_text())["variants"]["sim"]["localisation"]["odometry"]["scale"] == 0.909)
        wait(page, "document.querySelector('[data-procedure=odometry_scale]')?.textContent.includes('now 0.909')")
        check("must fail: the card says kept as version 2, and now 0.909; the Settings tab carries v2", card_status() == "kept as version 2"
              and page.locator("#tab-settings-badge").inner_text() == "v2", card_status())
        check("Keep is gone for a kept run, and the run can be repeated", page.locator("#cal-keep").count() == 0 and page.locator("#cal-start").inner_text() == "Run again")
        close_drawer()
        # the table repaints after the keep; under load (60 and more) it was read before it had (2026-11-24)
        wait(page, "document.querySelector(\"#cal-table tr[data-path='localisation.odometry'][data-layer=sim]\")?.textContent.includes('odometry_scale')")
        row = page.locator("#cal-table tr[data-path='localisation.odometry'][data-layer=sim]").inner_text()
        check("must fail: the measured table's sim row for the odometry is the new line: this year's date, by odometry_scale",
              "Mission Control's calibration procedure odometry_scale" in row and "odometry_scale" in row.split("\t")[3], row)

    # --- no runner truth: the operator's tape ---------------------------------------------------------------------------------------------------------
    with soft("the tape"):
        open_page(2, "duck-tape")
        open_drawer()
        set_seconds(2)
        page.click("#cal-start")
        wait(page, "!!document.getElementById('cal-tape')", timeout=10000)
        check("must fail: without a truth the run waits for the tape: no value, no Keep, the third step now",
              page.locator("#cal-value").inner_text() == "none" and page.locator("#cal-keep").count() == 0
              and page.eval_on_selector_all("#cal-steps li", "(els) => els.map((e) => e.dataset.status)") == ["done", "done", "now", "todo"])
        check("the card says it waits for the tape", card_status() == "waiting for the tape", card_status())
        page.fill("#cal-tape", "0.1")
        page.click("#cal-tape-use")
        wait(page, "document.getElementById('cal-value')?.textContent === '0.152'")
        check("must fail: a tape of 0.1 m gives 0.152, outside 0.5 to 1.5: said, and Keep is off",
              "outside 0.5 to 1.5" in page.locator("#cal-implausible").inner_text() and page.locator("#cal-keep").is_disabled())
        page.fill("#cal-tape", "0.57")
        page.click("#cal-tape-use")
        wait(page, "document.getElementById('cal-value')?.textContent === '0.864'")
        check("must fail: 0.57 m gives 0.864 by the operator's tape, and Keep as version 3 is on",
              "operator's tape" in page.locator("#cal-result").inner_text() and page.locator("#cal-implausible").count() == 0
              and page.locator("#cal-keep").inner_text() == "Keep as version 3" and page.locator("#cal-keep").is_enabled())
        page.click("#cal-keep")
        wait(page, "document.querySelector('#cal-drawer .calbody')?.textContent.includes('Kept as version 3')")
        check("kept as version 3", json.loads((FOLDER / "3.json").read_text())["variants"]["sim"]["localisation"]["odometry"]["scale"] == 0.864)
        close_drawer()

    # --- phone and desktop ------------------------------------------------------------------------------------------------------------------------------------
    with soft("phone"):
        open_page(3)
        open_drawer()
        check("must fail: on a phone the drawer is as wide as the screen, no sideways scrolling, its controls 44 px tall", page.evaluate(
            "() => { const d = document.querySelector('#cal-drawer .drawer').getBoundingClientRect(); const ok = [...document.querySelectorAll('#cal-drawer .dhead button, #cal-drawer .dfoot button, #cal-drawer .frow input')].every((e) => e.getBoundingClientRect().height >= 44); return Math.round(d.width) === window.innerWidth && ok; }")
              and no_scroll())
        close_drawer()
        page.emulate_media(color_scheme="light")
        check("light: no sideways scrolling", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-calibration-phone-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")

    with soft("desktop"):
        page.set_viewport_size({"width": 1440, "height": 960})
        open_drawer()
        check("must fail: desktop: the drawer is a 480 px side panel over a scrim", page.evaluate(
            "() => { const d = document.querySelector('#cal-drawer .drawer').getBoundingClientRect(); return Math.round(d.width) === 480 && Math.round(d.right) === window.innerWidth; }") and no_scroll())
        page.screenshot(path=str(SHOTS / "rp-calibration-drawer-desktop-dark.png"))
        page.mouse.click(5, 400)
        wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")
        check("the scrim closes it (on a phone the drawer is the whole screen)", drawer().count() == 0)
        page.screenshot(path=str(SHOTS / "rp-calibration-desktop-dark.png"))
        page.set_viewport_size({"width": 390, "height": 800})

    with soft("tabs"):
        open_drawer()
        page.click("#tab-settings", force=True)
        page.keyboard.press("Escape")
        close_drawer()
        page.click("#tab-settings")
        wait(page, "!document.getElementById('rp-settings').hidden")
        check("a drawer of Calibration does not stay open on another tab", drawer().count() == 0)

    check("no script error and no console error in the whole session (a 4xx the page was told about is not one)", [e for e in errors if "status of 4" not in e] == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_calibration_page")
