"""Mission Control's robot page (RFC-0023 D3, phase 5 item 4a unit A1) in headless Chromium, as test_page.py does it: the real server,
the page driven by what a person does and checked against the API. A pointer robot to the duck's profile behind the fake adapter
(its Parts come from the profile) beside the fake robot that holds itself (no profile). Six tabs in the address (the sixth, Actions, for a robot that has a catalogue), collapsible cards, the Readiness card and the header verdict that follows it,
Calibration. Phone width, desktop, dark and light.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
from contextlib import contextmanager
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import FAKE_FILE, check, finish, installation_file
from pageboot import boot

from observatory.shots import launch
from mission_control import alarms as alarms_mod
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
TABS = ["Overview", "Body", "Modules", "Settings", "Calibration", "Actions"]


class Bare:
    """An adapter of a robot that reads no facts and names no actions (the fake with those two left out): the page offers it neither."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name in ("facts", "actions"):
            raise AttributeError(name)
        return getattr(self._inner, name)


mc.robots["fake-1"].adapter = Bare(mc.robots["fake-1"].adapter)


def get(path):
    with urllib.request.urlopen(BASE + "/api/v1" + path, timeout=10) as r:
        return json.loads(r.read())


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
    boot(page, BASE + "/", "window.__mc && window.__mc.ready")
    no_scroll = lambda: page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    # One verdict: the header chip follows the Readiness card's overall status (ok, warn, error, unknown). duck-1's profile declares no guardrail (a warning), so its idle
    # baseline is "warn" with exactly the guardrails row as its reason; its battery is ok (the server's rule, 100 %).
    IDLE = "warn"
    NO_GUARDRAIL = "none declared"

    def fit(pg=None):
        pg = pg or page
        wait(pg, "!!document.querySelector('#verdict[data-status]') && !!document.querySelector('#readiness-checks')")
        rows_ = pg.locator("#readiness-checks li[data-status=error], #readiness-checks li[data-status=warn]").all_inner_texts()
        return pg.locator("#verdict").get_attribute("data-status"), [t for t in rows_ if NO_GUARDRAIL not in t]

    def fit_is(want, timeout=8000, pg=None):
        wait(pg or page, "([w]) => document.querySelector('#verdict')?.dataset.status === w", timeout, [want])

    # --- the robot page opens from the robot's card, and goes back -----------------------------------------------
    with soft("the page opens from the card"):
        link = page.locator("a[data-robot='duck-1']")
        check("must fail: the robot's card has a link to its page", link.count() == 1, link.count())
        link.click()
        wait(page, "!document.getElementById('robot-page').hidden")
        check("must fail: it opens the robot's page and hides the overview's panels", page.locator("#robot-page").is_visible()
              and page.locator("main.page").is_hidden() and page.url.endswith("#robot/duck-1"))
        check("must fail: six tabs, in order, in a tablist; Overview is the selected one and its panel the only one shown",
              page.locator("[role=tablist]").count() == 1
              and [t.split("\n")[0].strip() for t in page.eval_on_selector_all("[role=tab]", "(els) => els.map((e) => e.textContent)")] == TABS
              and page.eval_on_selector_all("[role=tab]", "(els) => els.map((e) => e.getAttribute('aria-selected'))") == ["true", "false", "false", "false", "false", "false"]
              and page.eval_on_selector_all("[role=tabpanel]", "(els) => els.map((e) => e.hidden)") == [False, True, True, True, True, True])
        check("each tab is a real button that names its panel", page.eval_on_selector_all("[role=tab]", "(els) => els.every((e) => e.tagName === 'BUTTON' && document.getElementById(e.getAttribute('aria-controls'))?.getAttribute('aria-labelledby') === e.id)"))
        check("must fail: the page names the robot and goes back", "Microduck" in page.locator("#rp-title").inner_text() and page.locator("#rp-back").count() == 1)
        check("STOP is still the robot's: it names the robot whose page is open", page.locator("#stop-robot").inner_text() == "STOP duck-1")
        check("must fail: on a phone STOP and STOP ALL are pinned at the bottom, 56 px tall, and STOP is first", page.evaluate("""() => {
            const a = document.getElementById('stop-robot').getBoundingClientRect(), b = document.getElementById('stop-all').getBoundingClientRect();
            return a.height === 56 && b.height === 56 && a.bottom <= window.innerHeight && b.bottom <= window.innerHeight && a.left < b.left && a.top > window.innerHeight - 100; }"""))
        check("touch targets are at least 44 px on the phone: the tabs, the section heads, the back button, the picker", page.evaluate(
            "() => ['.tab', '#rp-readiness-head', '#rp-back', '#rp-picker', '#theme'].every((s) => [...document.querySelectorAll(s)].every((e) => e.getBoundingClientRect().height >= 44 || !e.offsetParent))"))
        check("no sideways scrolling on the robot page at 390 px", no_scroll())
        TABS_WHOLE = """() => { const w = innerWidth; return [...document.querySelectorAll('.tabs .tab')].filter((e) => e.offsetParent).map((e) => { const r = e.getBoundingClientRect();
            return { t: e.textContent.trim(), ok: r.left >= 0 && r.right <= w && e.scrollWidth <= e.clientWidth + 1 }; }); }"""
        for w in (390, 320):
            page.set_viewport_size({"width": w, "height": 800})
            whole = page.evaluate(TABS_WHOLE)
            check(f"at {w} px every tab is on screen with its whole label (Overview, Body, Modules, Settings, Calibration, Actions: none clipped, none behind a scroll)",
                  len(whole) == 6 and all(t["ok"] for t in whole), whole)
        page.set_viewport_size({"width": 390, "height": 800})

    # --- tabs: the selected one is in the address, so reload and back keep it ------------------------------------------
    with soft("tabs"):
        page.click("#tab-settings")
        wait(page, "!document.getElementById('rp-settings').hidden")
        check("must fail: a tab click selects it, shows its panel only and writes it in the address", page.url.endswith("#robot/duck-1/settings")
              and page.locator("#tab-settings").get_attribute("aria-selected") == "true" and page.locator("#tab-overview").get_attribute("aria-selected") == "false"
              and page.locator("#rp-overview").is_hidden() and page.locator("#rp-settings").is_visible(), page.url)
        check("only the selected tab is in the tab order", page.eval_on_selector_all("[role=tab]", "(els) => els.map((e) => e.tabIndex)") == [-1, -1, -1, 0, -1, -1])
        page.reload()
        wait(page, "window.__mc && window.__mc.ready && !document.getElementById('rp-settings').hidden")
        check("must fail: a reload keeps the tab", page.locator("#tab-settings").get_attribute("aria-selected") == "true" and page.url.endswith("#robot/duck-1/settings"))
        page.go_back()
        wait(page, "!document.getElementById('rp-overview').hidden")
        check("must fail: back goes to the tab before", page.locator("#tab-overview").get_attribute("aria-selected") == "true" and page.locator("#rp-settings").is_hidden(), page.url)
        page.focus("#tab-overview")
        page.keyboard.press("ArrowRight")
        wait(page, "!document.getElementById('rp-body').hidden")
        check("must fail: the arrow keys move between the tabs, and the focus goes with the selection", page.locator("#tab-body").get_attribute("aria-selected") == "true"
              and page.evaluate("document.activeElement.id") == "tab-body" and page.url.endswith("#robot/duck-1/body"), page.url)
        page.keyboard.press("End")
        wait(page, "!document.getElementById('rp-actions').hidden")
        check("End goes to the last tab, Home to the first", page.locator("#tab-actions").get_attribute("aria-selected") == "true")
        page.keyboard.press("Home")
        wait(page, "!document.getElementById('rp-overview').hidden")
        page.evaluate("location.hash = '#robot/duck-1/nonsense'")
        check("an address with a tab that does not exist shows Overview", page.locator("#tab-overview").get_attribute("aria-selected") == "true")
        page.evaluate("location.hash = '#robot/duck-1'")

    # --- a card opens and closes ------------------------------------------------------------------------------------------
    with soft("collapsible cards"):
        wait(page, "!!document.querySelector('#readiness-checks li')")
        head = page.locator("#rp-readiness-head")
        check("a card's head is a button that says it is open, and names what it controls", head.get_attribute("aria-expanded") == "true"
              and head.get_attribute("aria-controls") == "rp-readiness-body" and page.locator("#rp-readiness-body").is_visible())
        head.click()
        check("must fail: one press closes it: aria-expanded false and its body hidden", head.get_attribute("aria-expanded") == "false" and page.locator("#rp-readiness-body").is_hidden())
        page.keyboard.press("Enter")
        check("must fail: it works from the keyboard, and opens again", head.get_attribute("aria-expanded") == "true" and page.locator("#rp-readiness-body").is_visible())
        head.click()
        page.evaluate("() => window.__mc.renderRobotPage()")
        check("a repaint of the page does not reopen what was closed, nor take the focus", head.get_attribute("aria-expanded") == "false" and page.evaluate("document.activeElement.id") == "rp-readiness-head")
        head.click()

    # --- Calibration -------------------------------------------------------------------------------------------------------------
    with soft("Calibration"):
        page.click("#tab-calibration")
        wait(page, "document.querySelectorAll('#cal-table tr[data-path]').length > 0")
        rows = page.eval_on_selector_all("#cal-table tr[data-path]", "(els) => els.map((e) => [e.dataset.path, e.dataset.layer])")
        check("must fail: Calibration lists what the profile says was measured: the dict, the layer, when, by whom", ["joints.limits", "sim"] in rows and ["sensors.tof8x8.mount", "sim"] in rows, rows)
        row = page.locator("#cal-table tr[data-path='joints.limits'][data-layer=sim]").inner_text()
        check("... with the date and the script from the measured line", "2026-" in row and ".py" in row, row)
        wait(page, "!!document.querySelector('[data-procedure=odometry_scale]')")
        check("Calibration offers odometry_scale above the measured lines (test_calibration_page.py is the procedure's own)",
              page.locator("[data-procedure=odometry_scale]").count() == 1 and page.locator("#cal-open-odometry_scale").is_enabled())
        check("no sideways scrolling on Calibration at 390 px", no_scroll())
        page.click("#tab-overview")

    # --- Overview: the one verdict, and why --------------------------------------------------------------------------
    with soft("Overview"):
        f, reasons = fit()
        reasons_rows = page.locator("#readiness-checks li[data-status=unknown]").evaluate_all("(els) => els.map((e) => e.dataset.check)")
        check("must fail: online and free: no error, the guardrails warning, the battery ok from the server's rule, and the header says check first in words", f == IDLE and reasons == []
              and reasons_rows == [] and page.locator("#readiness-checks li[data-check=battery]").get_attribute("data-status") == "ok" and "check first" in page.locator("#verdict").inner_text().lower() and page.locator("#readiness-checks li[data-check=guardrails]").get_attribute("data-status") == "warn", (f, reasons, reasons_rows))
        # the header follows the card on the next render: wait for it before comparing
        wait(page, "(() => { const v = document.getElementById('verdict'), o = document.getElementById('readiness-overall'); return v.dataset.status === o.dataset.status && v.innerText.trim() === o.innerText.trim(); })()")
        check("the header verdict is the card's own: the same status and the same word", page.locator("#verdict").get_attribute("data-status") == page.locator("#readiness-overall").get_attribute("data-status")
              and page.locator("#verdict").inner_text().strip() == page.locator("#readiness-overall").inner_text().strip(), (page.locator("#verdict").inner_text(), page.locator("#readiness-overall").inner_text()))
        check("there is one verdict list: the old 'Why it is fit to go' card and its checks are gone", page.locator("[data-panel=fit]").count() == 0 and page.locator("#fit-checks").count() == 0 and page.locator("#fit").count() == 0)
        check("and the variant it runs and the settings version are on the page, in the strip", "sim" in page.locator("#rp-facts").inner_text() and "settings" in page.locator("#rp-facts").inner_text() and page.locator("#verdict").is_visible())

        duck.set_offline(True)
        fit_is("error")
        f, reasons = fit()
        check("must fail: offline: not ready, and the reason is offline", f == "error" and any("offline" in r for r in reasons) and "not ready" in page.locator("#verdict").inner_text().lower(), reasons)
        duck.set_offline(False)
        fit_is(IDLE)

        a = send("POST", "/robots/duck-1/lock", {"client": "operator-a"})["lock"]
        wait(page, "document.querySelector('#readiness-checks [data-check=free]')?.dataset.status === 'warn'")      # the baseline is warn too: wait for the holder row itself
        f, reasons = fit()
        check("must fail: held by someone else: check first (a warning, not an error), and the reason names who", f == "warn" and any("operator-a" in r and "held" in r for r in reasons), (f, reasons))
        check("must fail: the strip shows the holder line: who, since, the lease, what is left", all(s in page.locator("#rp-holder").inner_text() for s in
              ("operator-a", "since", f"lease {a['lease_id']}", "expires in")), page.locator("#rp-holder").inner_text())
        send("DELETE", "/robots/duck-1/lock", {"session": a["session"]})
        wait(page, "document.querySelector('#readiness-checks [data-check=free]')?.dataset.status === 'ok'")
        check("released: back to the baseline and the holder line says nobody", page.locator("#rp-holder").inner_text() == "nobody", page.locator("#rp-holder").inner_text())

        duck.inject("fall", True)
        fit_is("error")
        f, reasons = fit()
        check("must fail: a fall flag on the robot's status is a reason", any("fall" in r for r in reasons), reasons)
        duck.inject("fall", False)
        fit_is(IDLE)

        def anomaly(sev, name):
            mc.bus.emit("anomaly", robot="duck-1", goal_run=1, watch=None, anomaly={"n": 1, "t": 1.0, "anomaly": name, "source": "robot", "module": "body",
                        "severity": sev, "detector": "d", "summary": f"{name} for the test"})

        anomaly("minor", "joint_tracking")
        wait(page, "window.__mc.S.alarms.length === 1")
        check("a minor alarm alone does not make the robot not ready", fit()[0] == IDLE)
        anomaly("critical", "joint_overload")
        fit_is("error")
        f, reasons = fit()
        check("must fail: a critical alarm in the last minute: the reason names it", any("critical" in r and "joint_overload" in r for r in reasons), reasons)
        al = page.locator("#rp-alarms-body").inner_text().lower()
        check("must fail: the Alarms card lists the last minute's alarms of this robot by their word, and counts them", "critical" in al and "minor" in al and "joint_overload" in al
              and page.locator("#rp-alarms-sum").inner_text() == "2 alarms", (al, page.locator("#rp-alarms-sum").inner_text()))
        check("must fail: a failed check says so in words, not only in colour, and the summary counts the passes", "error" in page.locator("#readiness-checks li[data-check=alarms]").inner_text().lower()
              and page.locator("#rp-readiness-sum").inner_text() == "7 of 9" and "not ready" in page.locator("#verdict").inner_text().lower())
        page.evaluate("() => { for (const x of window.__mc.S.alarms) x.at -= 61; window.__mc.renderRobotPage(); }")
        fit_is(IDLE)
        check("must fail: an alarm older than a minute is no longer a reason", fit() == (IDLE, []))
        duck.set_offline(True)
        anomaly("major", "motor_hot")
        wait(page, "window.__mc.S.alarms.length === 3")
        wait(page, "document.querySelectorAll('#readiness-checks li[data-status=error]').length === 2")
        f, reasons = fit()
        check("must fail: every reason is listed, not only the first: offline and the alarm", len(reasons) == 2 and any("offline" in r for r in reasons)
              and any("motor_hot" in r for r in reasons), reasons)
        duck.set_offline(False)
        page.evaluate("() => { for (const x of window.__mc.S.alarms) x.at -= 61; window.__mc.renderRobotPage(); }")
        fit_is(IDLE)

    # --- a page opened after the alarm: the server's last minute (shortened to 3 s here) is in the verdict at once ----------------
    with soft("Overview, opened after an alarm"):
        alarms_mod.WINDOW_S = 3
        page.wait_for_timeout(3500)
        mc.bus.emit("anomaly", robot="duck-1", goal_run=1, watch=None, anomaly={"n": 9, "t": 1.0, "anomaly": "joint_overload", "source": "robot", "module": "body",
                    "severity": "major", "detector": "d", "summary": "overload before the page opened", "values": {"joint": "left_knee"}})
        late = ctx.new_page()
        late.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        boot(late, BASE + "/#robot/duck-1", "window.__mc && window.__mc.ready")
        fit_is("error", pg=late)
        reasons = late.locator("#readiness-checks li[data-status=error]").all_inner_texts()
        check("must fail: opened after a major alarm: Overview says not ready, with the alarm as the reason", "not ready" in late.locator("#verdict").inner_text().lower()
              and len(reasons) == 1 and "major" in reasons[0] and "joint_overload" in reasons[0] and "overload before the page opened" in reasons[0], reasons)
        wait(late, "[...document.querySelectorAll('#rp-body-joints li')].some((e) => e.textContent.includes('left_knee'))")     # the joint list waits for body.js and the description: two requests after the verdict
        check("and the Alarms card lists it, and the joint is named under the Body card", "joint_overload" in late.locator("#rp-alarms-body").inner_text()
              and any("left_knee" in t and "error" in t for t in late.locator("#rp-body-joints li").all_inner_texts()), late.locator("#rp-alarms-body").inner_text())
        fit_is(IDLE, 12000, pg=late)
        wait(late, "document.querySelectorAll('#readiness-checks li[data-status=error]').length === 0 && document.getElementById('rp-alarms-sum').textContent === 'none'")
        check("must fail: after the window it is back to the baseline", late.locator("#readiness-checks li[data-status=error]").count() == 0 and late.locator("#rp-alarms-sum").inner_text() == "none")
        # one render reads one clock: with a clock that moves on every read, an alarm at the window's edge is either in both the verdict and the Alarms card
        # or in neither, whatever read it falls between (CI red on 46bbaad: the verdict was the baseline while the card still counted the alarm)
        split = late.evaluate("""() => { const real = Date.now, t0 = real(), S = window.__mc.S, keep = S.alarms.slice(), W = 3, out = [];
          try {
            for (let j = 0; j < 400; j++) {
              let k = 0;
              Date.now = () => t0 + 500 * k++;
              S.alarms = [{ robot: 'duck-1', goal_run: 1, watch: null, at: t0 / 1000 - W + 0.5 * j + 0.25,
                            a: { n: 900 + j, t: 1, anomaly: 'joint_overload', severity: 'major', summary: 'at the edge', values: {} } }];
              window.__mc.renderRobotPage();
              const counted = document.getElementById('rp-alarms-sum').textContent !== 'none', verdict = document.querySelector('#verdict').dataset.status === 'error';
              if (counted !== verdict) out.push({ j, counted, verdict });
            }
          } finally { Date.now = real; S.alarms = keep; window.__mc.renderRobotPage(); }
          return out; }""")
        check("must fail: at the window's edge the verdict and the Alarms card agree, read on one clock", split == [], split[:3])
        late.close()
        # the window stays 3 s: restored to 60 it would take the alarm back into the later tests

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
        wait(page, "document.querySelector('#readiness-checks [data-check=profile]')?.dataset.status === 'neutral'")      # this robot's own file: neutral, not ok
        check("must fail: and Overview has no error and nothing but the baseline (no guardrail declared), with the profile line saying none", fit() == (IDLE, []))
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
        boot(page, BASE + "/?visit=1#robot/duck-1", "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
        wait(page, "document.querySelectorAll('#rp-parts [data-part]').length === 3")
        check("must fail: opening #robot/<id> directly lands on the robot page, loaded", fit()[0] == IDLE)

    # --- light, and desktop -----------------------------------------------------------------------------------------------
    with soft("light and desktop"):
        boot(page, BASE + "/?visit=2#robot/duck-1", "window.__mc && window.__mc.ready && document.querySelectorAll('#rp-parts [data-part]').length === 3")
        page.emulate_media(color_scheme="light")
        check("light: the robot page follows the system, no sideways scrolling", page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--surface-0').trim()") == "#e4e6ea" and no_scroll())
        page.screenshot(path=str(SHOTS / "mc-robot-page-phone-light.png"), full_page=True)
        page.set_viewport_size({"width": 1500, "height": 900})
        page.emulate_media(color_scheme="dark")
        check("desktop: no sideways scrolling, and Overview and Parts sit side by side", no_scroll() and page.evaluate(
            "() => { const a = document.getElementById('rp-readiness-head').closest('.card').getBoundingClientRect(), b = document.getElementById('rp-parts').getBoundingClientRect(); return a.right <= b.left + 1; }"))
        page.screenshot(path=str(SHOTS / "mc-robot-page-desktop-dark.png"), full_page=True)
        check("desktop: STOP ALL (outlined) and STOP duck-1 (solid) are in the top bar, always visible, with the picker and the live chip", page.evaluate(
            "() => { const t = document.querySelector('header.top').getBoundingClientRect(), ids = ['stop-all', 'stop-robot', 'rp-picker', 'conn']; return ids.every((i) => { const r = document.getElementById(i).getBoundingClientRect(); return r.top >= t.top - 1 && r.bottom <= t.bottom + 1; }); }")
              and page.locator("#stop-robot").inner_text() == "STOP duck-1")
        page.set_viewport_size({"width": 1440, "height": 960})
        page.screenshot(path=str(SHOTS / "rp-overview-desktop-dark.png"))
        page.emulate_media(color_scheme="light")
        page.screenshot(path=str(SHOTS / "rp-overview-desktop-light.png"))
        page.emulate_media(color_scheme="dark")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(SHOTS / "rp-overview-phone-dark.png"))
        page.set_viewport_size({"width": 390, "height": 800})
        check("and at 390 px again, the sections are one column", page.evaluate(
            "() => { const a = document.getElementById('rp-readiness-head').closest('.card').getBoundingClientRect(), b = document.getElementById('rp-parts').getBoundingClientRect(); return b.top >= a.bottom - 1; }"))

    # --- RFC-0032 phase 1: Facts and "Driven by" on the Overview, the read-only Actions tab; a robot with none shows none --------------------
    with soft("facts, driven by and the Actions tab"):
        boot(page, BASE + "/?visit=3#robot/duck-1", "window.__mc && window.__mc.ready && !document.getElementById('rp-robotfacts').hidden")
        page.set_viewport_size({"width": 1440, "height": 960})
        card = page.locator("#rp-robotfacts")
        check("the Facts card is on the Overview: identity, software and the interface from the robot, and 'read N s ago'",
              card.is_visible() and "fake-0001" in page.locator("#rp-robotfacts [data-fact=identity]").inner_text()
              and "fake-robot 1.0.0" in page.locator("#rp-robotfacts [data-fact=software]").inner_text()
              and "model_api 1" in page.locator("#rp-robotfacts [data-fact=interface]").inner_text()
              and re.fullmatch(r"read \d+ s ago", page.locator("#rp-robotfacts-sum").inner_text()), page.locator("#rp-robotfacts").inner_text())
        page.screenshot(path=str(SHOTS / "rp-facts-desktop-dark.png"))
        at0 = get("/robots/duck-1/facts")["facts"]["read_at"]
        time.sleep(1.6)
        wait(page, "!document.getElementById('rp-robotfacts-sum').textContent.startsWith('read 0 s')")
        page.locator("#rp-robotfacts-refresh").click()
        wait(page, "document.getElementById('rp-robotfacts-sum').textContent === 'read 0 s ago'")
        check("Refresh reads the robot again: the server's read_at is newer, and the card says 'read 0 s ago'", get("/robots/duck-1/facts")["facts"]["read_at"] > at0)
        check("the card has a Refresh button of the page's kind, in the card's head", page.locator("#rp-robotfacts-refresh").inner_text() == "Refresh"
              and page.evaluate("document.getElementById('rp-robotfacts-refresh').closest('.shead') !== null"))

        page.click("#tab-actions")
        wait(page, "!document.getElementById('rp-actions').hidden")
        row = page.locator("#rp-actions [data-action=wave]")
        check("the Actions tab lists the catalogue: the action, its kind, whether it is irreversible, its length, and where it was named",
              page.url.endswith("#robot/duck-1/actions") and page.locator("#tab-actions").get_attribute("aria-selected") == "true"
              and [c.strip() for c in row.locator("td").all_inner_texts()] == ["wave", "motion", "no", "2 s", "HARD", "robot"], row.inner_text())
        check("it is read only, and says that running actions comes in phase 2: no button runs anything",
              "running actions comes in phase 2" in page.locator("[data-actions-note]").inner_text() and page.locator("#rp-actions button").count() == 0)
        page.screenshot(path=str(SHOTS / "rp-actions-desktop-dark.png"))
        page.emulate_media(color_scheme="light")
        page.screenshot(path=str(SHOTS / "rp-actions-desktop-light.png"))
        check("light theme: the table and the note are readable (text is not the background)", page.evaluate(
            "() => { const t = document.querySelector('#rp-actions td.k'), c = getComputedStyle(t).color, b = getComputedStyle(document.body).backgroundColor; return c !== b; }"))
        page.set_viewport_size({"width": 390, "height": 800})
        check("no sideways scrolling on the Actions tab at 390 px", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-actions-phone-light.png"))
        page.emulate_media(color_scheme="dark")
        page.focus("#tab-overview")
        page.keyboard.press("End")
        wait(page, "!document.getElementById('rp-actions').hidden")
        check("End reaches the Actions tab, the last, and Home the first", page.locator("#tab-actions").get_attribute("aria-selected") == "true")
        page.keyboard.press("Home")
        wait(page, "!document.getElementById('rp-overview').hidden")

        # a robot whose adapter reads neither: no card, no tab, and the keys skip it
        page.evaluate("location.hash = '#robot/fake-1'")
        wait(page, "document.getElementById('rp-picker').value === 'fake-1' && document.getElementById('rp-robotfacts').hidden === true")
        check("fake-1 reads no facts and names no actions: no Facts card, no Actions tab", page.locator("#rp-robotfacts").is_hidden() and page.locator("#tab-actions").is_hidden())
        page.focus("#tab-overview")
        page.keyboard.press("End")
        wait(page, "!document.getElementById('rp-calibration').hidden")
        check("the arrow keys skip the tab it does not have: End is Calibration", page.locator("#tab-calibration").get_attribute("aria-selected") == "true")
        page.evaluate("location.hash = '#robot/duck-1'")
        wait(page, "document.getElementById('rp-picker').value === 'duck-1'")
        page.set_viewport_size({"width": 1440, "height": 960})

        # who drives: red when it is not ours, on the robot's card too (this raises the gate's own alarm, so it runs last)
        check("a robot nobody is named for shows no 'driven by'", page.locator(".drivenby").count() == 0)
        duck.control = {"source": "mission-control", "autonomous": False}
        wait(page, "document.querySelectorAll('#rp-facts .drivenby[data-ours=true]').length === 1")
        check("driven by the gate's own name: 'ours', not red", "mission-control (ours)" in page.locator("#rp-facts .drivenby").inner_text()
              and page.locator("#rp-facts .drivenby").get_attribute("data-bad") == "false" and "bad" not in (page.locator("#rp-facts .drivenby b").get_attribute("class") or ""))
        duck.control = {"source": "pad", "autonomous": False}
        wait(page, "document.querySelectorAll('#rp-facts .drivenby[data-bad=true]').length === 1")
        wait(page, "document.querySelector('#rp-facts .drivenby')?.textContent.includes('move.source') && document.querySelectorAll('#robot-list .drivenby[data-bad=true]').length === 1")      # the notice comes with the state after the first one
        check("driven by a pad: 'not ours', in the error colour and with the word, on the robot's page and on its card, with the gate's notice",
              "pad (not ours)" in page.locator("#rp-facts .drivenby").inner_text() and "move.source" in page.locator("#rp-facts .drivenby").inner_text()
              and page.evaluate("() => { const b = document.querySelector('#rp-facts .drivenby b'); return b.classList.contains('bad') && getComputedStyle(b).color !== getComputedStyle(document.body).color; }")
              and page.locator("#robot-list .drivenby[data-robot=duck-1][data-bad=true]").count() == 1,
              page.locator("#rp-facts .drivenby").inner_text())
        page.screenshot(path=str(SHOTS / "rp-driven-by-desktop-dark.png"))
        duck.control = {"source": "mission-control", "autonomous": True}
        wait(page, "document.querySelector('#rp-facts .drivenby b')?.textContent.includes('autonomous')")
        check("the robot's own autonomy on is red too, even under our name", page.locator("#rp-facts .drivenby").get_attribute("data-bad") == "true")
        duck.control = None
        wait(page, "document.querySelector('#rp-facts .drivenby b')?.textContent === 'not named'")
        check("when the robot names nobody again, 'not named' stays beside the gate's notice, no longer red", page.locator("#rp-facts .drivenby").get_attribute("data-bad") == "false")

    check("no script error and no console error in the whole session", errors == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_robot_page")
