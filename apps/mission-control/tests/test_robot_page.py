"""Mission Control's robot page (RFC-0023 D3, phase 5 item 4a unit A1) in headless Chromium, as test_page.py does it: the real server,
the page driven by what a person does and checked against the API. A pointer robot to the duck's profile behind the fake adapter
(its Parts come from the profile) beside the fake robot that holds itself (no profile). Phone width, desktop, dark and light.

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

from common import FAKE_FILE, check, finish, installation_file

from observatory.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

tmp = Path(tempfile.mkdtemp(prefix="mc-robot-page-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)
REPO = json.loads((Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json").read_text())
os.environ[installation.ENV] = str(installation_file(tmp / "installation.json", {"duck": {"variant": "sim"}}))
mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}),
                     RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()
duck = mc.robots["duck-1"].adapter.robot
SECTIONS = ["overview", "parts", "modules", "settings", "calibration", "body"]


def send(method, path, body):
    req = urllib.request.Request(BASE + "/api/v1" + path, data=json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
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
    page.goto(BASE + "/")
    wait(page, "window.__mc && window.__mc.ready")
    no_scroll = lambda: page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    def fit():
        wait(page, "!!document.querySelector('#fit[data-fit]')")
        return page.locator("#fit").get_attribute("data-fit"), page.locator("#fit-reasons li").all_inner_texts()

    def fit_is(want, timeout=8000):
        wait(page, "([w]) => document.querySelector('#fit')?.dataset.fit === w", timeout, [want])

    # --- the robot page opens from the robot's card, and goes back -----------------------------------------------
    with soft("the page opens from the card"):
        link = page.locator("a[data-robot='duck-1']")
        check("must fail: the robot's card has a link to its page", link.count() == 1, link.count())
        link.click()
        wait(page, "!document.getElementById('robot-page').hidden")
        check("must fail: it opens the robot's page and hides the overview's panels", page.locator("#robot-page").is_visible()
              and page.locator("main.page").is_hidden() and page.url.endswith("#robot/duck-1"))
        check("must fail: the six sections, in order, each with an icon in its header",
              page.eval_on_selector_all("#robot-page > section", "(els) => els.map((e) => e.id)") == ["rp-" + s for s in SECTIONS]
              and page.eval_on_selector_all("#robot-page > section > h2", "(hs) => hs.map((h) => !!h.querySelector('svg'))") == [True] * 6
              and [t.strip().lower() for t in page.eval_on_selector_all("#robot-page > section > h2", "(hs) => hs.map((h) => h.textContent)")] == SECTIONS)
        check("must fail: the page names the robot and goes back", "Microduck" in page.locator("#rp-title").inner_text() and page.locator("#rp-back").count() == 1)
        check("the placeholders say next, and Settings links to what exists (the profile in the API)",
              all("next" in page.locator(f"#rp-{s}").inner_text().lower() for s in ("modules", "calibration"))
              and "/api/v1/robots/duck-1/profile" in page.locator("#rp-settings a").get_attribute("href"))
        check("STOP is still the robot's: it names the robot whose page is open", page.locator("#stop-robot").inner_text() == "STOP duck-1")
        check("no sideways scrolling on the robot page at 390 px", no_scroll())

    # --- Overview: fit to go, and why not -------------------------------------------------------------------------
    with soft("Overview"):
        f, reasons = fit()
        check("must fail: online and free: fit to go, with no reason against", f == "true" and reasons == [] and "fit to go" in page.locator("#fit").inner_text().lower(), (f, reasons))
        check("and the profile and variant it runs are on the page", "duck" in page.locator("#rp-overview").inner_text() and "sim" in page.locator("#rp-overview").inner_text())

        duck.set_offline(True)
        fit_is("false")
        f, reasons = fit()
        check("must fail: offline: not fit, and the reason is offline", f == "false" and any("offline" in r for r in reasons) and "not fit" in page.locator("#fit").inner_text().lower(), reasons)
        duck.set_offline(False)
        fit_is("true")

        a = send("POST", "/robots/duck-1/lock", {"client": "operator-a"})["lock"]
        fit_is("false")
        f, reasons = fit()
        check("must fail: held by someone else: the reason names who", any("operator-a" in r and "held" in r for r in reasons), reasons)
        check("must fail: Parts shows the holder line: who, since, the lease, what is left", all(s in page.locator("#rp-holder").inner_text() for s in
              ("operator-a", "since", f"lease {a['lease_id']}", "expires in")), page.locator("#rp-holder").inner_text())
        send("DELETE", "/robots/duck-1/lock", {"session": a["session"]})
        fit_is("true")
        check("released: fit again and the holder line says free", page.locator("#rp-holder").inner_text() == "free", page.locator("#rp-holder").inner_text())

        duck.inject("fall", True)
        fit_is("false")
        f, reasons = fit()
        check("must fail: a fall flag on the robot's status is a reason", any("fall" in r for r in reasons), reasons)
        duck.inject("fall", False)
        fit_is("true")

        def anomaly(sev, name):
            mc.bus.emit("anomaly", robot="duck-1", goal_run=1, watch=None, anomaly={"n": 1, "t": 1.0, "anomaly": name, "source": "robot", "module": "body",
                        "severity": sev, "detector": "d", "summary": f"{name} for the test"})

        anomaly("minor", "joint_tracking")
        wait(page, "window.__mc.S.alarms.length === 1")
        check("a minor alarm alone does not make the robot unfit", fit()[0] == "true")
        anomaly("critical", "joint_overload")
        fit_is("false")
        f, reasons = fit()
        check("must fail: a critical alarm in the last minute: the reason names it", any("critical" in r and "joint_overload" in r for r in reasons), reasons)
        page.evaluate("() => { for (const x of window.__mc.S.alarms) x.at -= 61; window.__mc.renderRobotPage(); }")
        fit_is("true")
        check("must fail: an alarm older than a minute is no longer a reason", fit() == ("true", []))
        duck.set_offline(True)
        anomaly("major", "motor_hot")
        wait(page, "window.__mc.S.alarms.length === 3")
        wait(page, "document.querySelectorAll('#fit-reasons li').length === 2")
        f, reasons = fit()
        check("must fail: every reason is listed, not only the first: offline and the alarm", len(reasons) == 2 and any("offline" in r for r in reasons)
              and any("motor_hot" in r for r in reasons), reasons)
        duck.set_offline(False)
        page.evaluate("() => { for (const x of window.__mc.S.alarms) x.at -= 61; window.__mc.renderRobotPage(); }")
        fit_is("true")

    # --- Parts: the profile's subsystems -----------------------------------------------------------------------------
    with soft("Parts"):
        names = page.eval_on_selector_all("#rp-parts [data-part]", "(els) => els.map((e) => e.dataset.part)")
        check("must fail: Parts lists the profile's subsystems, in its order", names == [s["name"] for s in REPO["subsystems"]], names)
        robotd = page.locator("#rp-parts [data-part=robotd]").inner_text()
        check("must fail: each with what it is and how it is checked", "the motors" in robotd and "socket" in robotd and "robot" in robotd, robotd)
        check("and its state, which Mission Control does not know yet, says so", "not reported" in robotd, robotd)
        check("no sideways scrolling with the parts listed", no_scroll())
        page.screenshot(path=str(SHOTS / "mc-robot-page-phone-dark.png"), full_page=True)

    # --- a robot that holds itself has no profile; a wrong id is a message ---------------------------------------------
    with soft("no profile, no robot"):
        page.evaluate("location.hash = '#robot/fake-1'")
        wait(page, "document.getElementById('rp-title').textContent.includes('Fake robot')")
        check("must fail: a robot with no profile: Parts says so instead of listing parts", "no profile" in page.locator("#rp-parts").inner_text().lower()
              and page.locator("#rp-parts [data-part]").count() == 0, page.locator("#rp-parts").inner_text())
        check("must fail: and Overview is fit with the profile line saying none", page.locator("#fit").get_attribute("data-fit") == "true")
        page.evaluate("location.hash = '#robot/nope'")
        wait(page, "document.getElementById('rp-title').textContent.includes('nope')")
        check("must fail: an id that is no robot says so, and still goes back", "no robot" in page.locator("#rp-title").inner_text().lower() and page.locator("#rp-back").count() == 1)

    # --- back to the overview --------------------------------------------------------------------------------------------
    with soft("back to the overview"):
        page.click("#rp-back")
        wait(page, "document.getElementById('robot-page').hidden")
        check("must fail: back: the overview's panels are there, the robot page is gone, and the address has no route",
              page.locator("main.page").is_visible() and page.locator("#robot-page").is_hidden() and "#robot" not in page.url)
        check("the map is drawn again after being hidden", page.evaluate("document.getElementById('map').getBoundingClientRect().width > 100"))

    # --- the address is the page: a direct visit ------------------------------------------------------
    with soft("a direct visit"):
        page.goto(BASE + "/?visit=1#robot/duck-1")
        wait(page, "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
        wait(page, "document.querySelectorAll('#rp-parts [data-part]').length === 3")
        check("must fail: opening #robot/<id> directly lands on the robot page, loaded", fit()[0] == "true")

    # --- light, and desktop -----------------------------------------------------------------------------------------------
    with soft("light and desktop"):
        page.goto(BASE + "/?visit=2#robot/duck-1")
        wait(page, "window.__mc && window.__mc.ready && document.querySelectorAll('#rp-parts [data-part]').length === 3")
        page.emulate_media(color_scheme="light")
        check("light: the robot page follows the system, no sideways scrolling", page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg-app').trim()") == "#e4e6ea" and no_scroll())
        page.screenshot(path=str(SHOTS / "mc-robot-page-phone-light.png"), full_page=True)
        page.set_viewport_size({"width": 1500, "height": 900})
        page.emulate_media(color_scheme="dark")
        check("desktop: no sideways scrolling, and Overview and Parts sit side by side", no_scroll() and page.evaluate(
            "() => { const a = document.getElementById('rp-overview').getBoundingClientRect(), b = document.getElementById('rp-parts').getBoundingClientRect(); return a.right <= b.left + 1; }"))
        page.screenshot(path=str(SHOTS / "mc-robot-page-desktop-dark.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 800})
        check("and at 390 px again, the sections are one column", page.evaluate(
            "() => { const a = document.getElementById('rp-overview').getBoundingClientRect(), b = document.getElementById('rp-parts').getBoundingClientRect(); return b.top >= a.bottom - 1; }"))

    check("no script error and no console error in the whole session", errors == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_robot_page")
