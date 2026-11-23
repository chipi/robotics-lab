"""Mission Control's page in headless Chromium (RFC-0014 step 1), the way the viewer's page tests do it: the real
server, a fake robot on the real clock, the page driven only by what a person does (tap the map, fill a
field, press a button) and checked against the API. At phone width and at desktop width, in dark and light.
No fixed sleeps: every wait is for a condition.

Needs Chromium and Playwright, which are the viewer's (control has no browser dependency), so it runs in the viewer's
environment with Mission Control and the gate on the path:
  make test-control-page          (see the Makefile: it runs in the Observatory's environment)"""

import copy
import json
import atexit
import shutil
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import FAKE_FILE, check, finish, robot_file

from observatory.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

fs = copy.deepcopy(FAKE_FILE["factsheet"])
fs["physicalParameters"] = {"maximumSpeed": 2.0, "maximumAngularSpeed": 6.0}  # quick, so a sweep takes seconds, not a minute
STATE = tempfile.mkdtemp(prefix="mc-page-")
atexit.register(shutil.rmtree, STATE, True)
mc = MissionControl([RobotConfig(robot_file("fake-1", factsheet=fs, rates={"state_hz": 5.0, "map_hz": 2.0, "max_state_hz": 10.0}))],
                    state_dir=STATE)
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()


def get(path):
    with urllib.request.urlopen(BASE + "/api/v1" + path, timeout=10) as r:
        return json.loads(r.read())


def wait(page, js, timeout=25000, arg=None):
    page.wait_for_function(js, arg=arg, timeout=timeout)


def canvas_point(page, x, y):
    s = page.evaluate("([x, y]) => window.__mc.toScreen(x, y)", [x, y])
    return {"x": s[0], "y": s[1]}


def tap(page, x, y):
    page.locator("#map").click(position=canvas_point(page, x, y))


def run_state(page):
    return page.locator("#run-state").inner_text()


seen_run = [0]


def wait_state(page, states, timeout=30000, new=True):
    """Wait until the run the page shows is in one of `states`. By default it must be a run newer than the last one
    waited for, so the state of the run before cannot satisfy it."""
    try:
        wait(page, """([s, prev, isNew]) => { const e = document.getElementById('run-state'), d = document.getElementById('run-detail');
            return !!e && s.includes(e.textContent) && (!isNew || Number(d.dataset.run) > prev); }""", timeout, [states, seen_run[0], new])
    except Exception:
        # A timeout says nothing about why: say what the page and the service showed instead of the state waited for.
        runs = get("/goal-runs")["runs"]
        print(f"wait_state({states}) timed out: the page shows {page.locator('#run-state').inner_text()!r} for run "
              f"{page.locator('#run-detail').get_attribute('data-run')}; the service's newest runs "
              f"{[(r.get('id'), r.get('state'), r.get('why')) for r in runs[:3]]}", flush=True)
        raise
    seen_run[0] = int(page.locator("#run-detail").get_attribute("data-run"))


errors = []

with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark", accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    page.goto(BASE + "/")
    wait(page, "window.__mc && window.__mc.ready")

    # --- the first screen, at phone width ----------------------------------------------------------
    check("the robot list shows the robot, online, its lock free", page.locator("#robot-fake-1").get_attribute("data-online") == "true"
          and page.locator("#robot-fake-1 .lock").inner_text() == "free" and page.locator("#robot-fake-1 .online").inner_text() == "online")
    check("the event stream is live", page.locator("#conn").inner_text() == "live")
    check("no sideways scrolling at 390 px", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    def stop_visible(min_h=44):
        return page.evaluate("""(minH) => ['stop-robot', 'stop-all'].every((id) => {
            const r = document.getElementById(id).getBoundingClientRect();
            return r.top >= 0 && r.bottom <= window.innerHeight && r.left >= 0 && r.right <= window.innerWidth && r.height >= minH;
        })""", min_h)
    check("STOP and STOP ALL are on screen, at least 44 px high", stop_visible())
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    check("and still after scrolling to the end", stop_visible())
    page.evaluate("window.scrollTo(0, 0)")
    check("STOP names the robot it stops", page.locator("#stop-robot").inner_text() == "STOP fake-1")

    # --- the map -----------------------------------------------------------------------------------
    wait(page, "window.__mc.S.map !== null")
    page.locator("#map").scroll_into_view_if_needed()
    wait(page, "window.__mc.toScreen(0, 0)[0] > 0")
    colours = page.evaluate("""() => { const c = document.getElementById('map'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        const s = new Set(); for (let i = 0; i < d.length; i += 4 * 97) s.add(d[i] << 16 | d[i + 1] << 8 | d[i + 2]); return s.size; }""")
    check("the map is drawn: background, grid, the explored floor around the dock, the robot", colours >= 3, colours)
    check("the robot's map came from GET /robots/{id}/map", page.evaluate("window.__mc.S.map.kind") == "occupancy_grid")

    # --- a point goal by tapping the map -----------------------------------------------------------
    tap(page, 1.0, 0.5)
    x, y = float(page.input_value("#g-x")), float(page.input_value("#g-y"))
    check("tapping the map fills the point goal with the site-frame position", abs(x - 1.0) < 0.1 and abs(y - 0.5) < 0.1, (x, y))
    check("and says so", "Point goal at" in page.locator("#maphint").inner_text())
    page.click("#g-run")
    wait_state(page, ["reached"])
    pose = get("/robots/fake-1")["robot"]["status"]["pose"]
    run = get("/goal-runs")["runs"][0]
    check("Run now: a goal run on the robot that reaches the tapped point (the API's truth)", run["state"] == "reached"
          and abs(run["goal"]["params"]["x"] - x) < 1e-9 and ((pose["x"] - x) ** 2 + (pose["y"] - y) ** 2) ** 0.5 < 0.4, (run["state"], pose))
    check("the run's progress and decisions are on the page, from the event stream", "heading for" in page.locator("#decisions").inner_text()
          and page.locator("#run-progress").inner_text().startswith("elapsed"))
    check("Watch is there and disabled while run_key is null: nothing to open", page.locator("#watch").get_attribute("aria-disabled") == "true"
          and page.locator("#watch").get_attribute("href") == "#")
    check("the robot card follows: free again, the robot's pose moved", page.locator("#robot-fake-1 .lock").inner_text() == "free")
    # --- who holds the robot: one line on the robot's card, from the gate's who -----------------------------
    def send(method, path, body):
        req = urllib.request.Request(BASE + "/api/v1" + path, data=json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def holder_line():
        loc = page.locator("#robot-fake-1 .holder")
        return loc.inner_text() if loc.count() else None

    check("must fail: nobody holds the robot: its card says so on a line of its own (phone width)", holder_line() == "free", holder_line())
    a = send("POST", "/robots/fake-1/lock", {"client": "operator-a"})["lock"]
    wait(page, "document.querySelector('#robot-fake-1 .holder')?.textContent.includes('operator-a')")
    line = holder_line()
    check("must fail: held: the holder, since when, the lease and how long it has left", line is not None and "operator-a" in line
          and "since" in line and f"lease {a['lease_id']}" in line and "expires in" in line, line)
    check("the card is not wider than the phone, with the line on it", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    send("DELETE", "/robots/fake-1/lock", {"session": a["session"]})
    b = send("POST", "/robots/fake-1/lock", {"client": "operator-b"})["lock"]
    wait(page, "document.querySelector('#robot-fake-1 .holder')?.textContent.includes('operator-b')")
    check("must fail: the holder changes, the line follows: operator-b, no longer operator-a", "operator-a" not in holder_line()
          and f"lease {b['lease_id']}" in holder_line(), holder_line())
    send("DELETE", "/robots/fake-1/lock", {"session": b["session"]})
    wait(page, "document.querySelector('#robot-fake-1 .holder')?.textContent === 'free'")
    check("released: the line says free again", holder_line() == "free", holder_line())
    check("an empty field of a run is not written as 'null' (a bug a screenshot found)", "null" not in page.locator("#run-detail").inner_text())
    page.click("#watch", force=True)
    check("clicking the disabled Watch goes nowhere", page.url == BASE + "/")

    # --- a site, by the form ---------------------------------------------------------------------
    page.locator("summary", has_text="New site").click()
    page.fill("#site-name", "Home")
    page.fill("#site-kind", "apartment")
    page.click("#site-create")
    wait(page, "document.querySelectorAll('#site-sel option').length === 2")
    page.select_option("#site-sel", "home")
    wait(page, "window.__mc.S.site === 'home'")
    check("the robot is at the site the operator made and picked", get("/robots/fake-1")["robot"]["site"] == "home")

    # --- an area drawn by the operator -------------------------------------------------------------
    wait(page, "document.getElementById('area-list').textContent.includes('none defined')")  # the list is drawn after the site is loaded
    check("no area yet: it says none defined", "none defined" in page.locator("#area-list").inner_text())
    page.click("#area-draw")
    check("Draw an area opens the draft form", page.locator("#area-draft").is_visible() and page.locator("#area-draw").get_attribute("aria-pressed") == "true")
    check("Save is off until there are three corners", page.locator("#area-save").is_disabled())
    for cx, cy in ((2.0, 0.5), (3.9, 0.5), (3.9, 2.9), (2.0, 2.9)):
        tap(page, cx, cy)
    wait(page, "window.__mc.S.draft.length === 4")
    check("four corners tapped, Save is on", not page.locator("#area-save").is_disabled())
    page.fill("#area-name", "Kitchen")
    page.fill("#area-type", "kitchen")
    page.click("#area-save")
    wait(page, "window.__mc.S.areas.length === 1")
    areas = get("/sites/home/areas")["areas"]
    check("Save area: the operator's area is in the site, in the site frame", [a["name"] for a in areas] == ["Kitchen"] and areas[0]["type"] == "kitchen"
          and abs(areas[0]["outline"][2][0] - 3.9) < 0.1, areas)
    check("and listed on the page with its objects", page.locator("#area-list input").input_value() == "Kitchen")

    # --- goals by form, and the objects layer --------------------------------------------------------
    page.select_option("#g-kind", "go_to_object")
    page.fill("#g-obj", "fridge")
    page.check(".g-must[value=contact]")
    page.click("#g-run")
    wait_state(page, ["reached", "not_found", "failed", "timeout", "refused"], 60000)
    run = get("/goal-runs")["runs"][0]
    check("go_to_object by form: it explored, found the fridge and went to it", run["state"] == "reached" and run["result"]["object"]["kind"] == "fridge", (run["state"], run["reason"]))
    check("the run's guardrails are listed: contact", "contact" in page.locator("#run-detail").inner_text())
    wait(page, "window.__mc.S.objects.length >= 1")
    check("the objects layer holds what the run found, with the site's stable ids", page.evaluate("window.__mc.S.objects.some((o) => o.kind === 'fridge' && o.id.startsWith('obj-'))"))
    check("the fridge is in the operator's Kitchen, by geometry", "1 object" in page.locator("#area-list").inner_text())
    check("a run created no area: still the one the operator drew", len(get("/sites/home/areas")["areas"]) == 1)

    page.select_option("#g-kind", "go_to_area")
    page.select_option("#g-area", "kitchen")
    page.click("#g-run")
    wait_state(page, ["reached", "refused", "failed", "timeout"], 30000)
    check("go_to_area by form", get("/goal-runs")["runs"][0]["state"] == "reached")
    runs_before = len(get("/goal-runs")["runs"])
    page.fill("#say", "go to the kitchen")
    page.click("#say-go")
    wait(page, "document.querySelectorAll('#plan-out [data-plan]').length === 1")
    check("a goal in words: the planner's proposal is read back, and nothing has run", "go to the area kitchen" in page.locator("#plan-out").inner_text()
          and len(get("/goal-runs")["runs"]) == runs_before)
    page.click("#plan-out [data-action=run-plan]")
    wait_state(page, ["reached", "refused", "failed", "timeout"], 60000)
    check("only Run starts it: the run is the goal that was read back", get("/goal-runs")["runs"][0]["goal"]["kind"] == "go_to_area"
          and get("/goal-runs")["runs"][0]["goal"]["params"]["area"] == "kitchen" and len(get("/goal-runs")["runs"]) == runs_before + 1)
    page.fill("#say", "make me a sandwich")
    page.click("#say-go")
    wait(page, "!!document.getElementById('plan-none')")
    check("nothing matched: the page says so and there is no Run", "no goal matched" in page.locator("#plan-none").inner_text()
          and page.locator("#plan-out [data-action=run-plan]").count() == 0)
    page.select_option("#g-kind", "explore")
    page.click("#g-run")
    wait_state(page, ["done", "refused", "failed", "timeout"], 60000)
    check("explore by form: done", get("/goal-runs")["runs"][0]["state"] == "done")
    page.select_option("#g-kind", "inventory")
    page.click("#g-run")
    wait_state(page, ["done", "refused", "failed", "timeout"], 90000)
    inv = get("/goal-runs")["runs"][0]
    check("inventory by form: done, with the objects by area", inv["state"] == "done" and inv["result"]["areas"][0]["name"] == "Kitchen", inv["state"])
    wait(page, "window.__mc.S.objects.length === 4")
    check("the objects layer now holds all four", page.evaluate("window.__mc.S.objects.length") == 4)

    # --- the library --------------------------------------------------------------------------------
    page.select_option("#g-kind", "point")
    tap(page, -2.0, 1.0)
    page.fill("#g-name", "to the desk")
    page.fill("#g-folder", "tests/course")
    page.click("#g-save")
    wait(page, "document.querySelectorAll('#goal-list li').length === 1")
    check("Save to library: the goal is in its folder", "tests/course/" in page.locator("#goal-list").inner_text() and "to the desk" in page.locator("#goal-list").inner_text()
          and get("/goals?folder=tests")["goals"][0]["params"]["x"] < -1.5)
    page.locator("#goal-list [data-action=run]").click()
    wait_state(page, ["reached", "failed", "timeout"], 30000)
    check("Run on a library goal: a run linked to it", get("/goal-runs")["runs"][0]["goal_id"] == get("/goals")["goals"][0]["id"])
    page.select_option("#g-kind", "point")
    tap(page, 2.5, -2.0)
    page.click("#g-run")
    wait_state(page, ["reached", "failed", "timeout"], 30000)
    page.fill("#save-name", "to the plant")
    page.fill("#save-folder", "tests/course")
    page.click("#run-save")
    wait(page, "document.querySelectorAll('#goal-list li').length === 2")
    check("Save to library from an ad-hoc run: the run's goal is saved", {g["name"] for g in get("/goals")["goals"]} == {"to the desk", "to the plant"})

    # --- renaming and deleting an area ---------------------------------------------------------------
    page.fill("#area-list input", "Galley")
    page.press("#area-list input", "Enter")
    page.locator("#robots").click()  # leave the field: the change is committed
    wait(page, "window.__mc.S.areas[0].name === 'Galley'")
    check("rename an area", get("/sites/home/areas")["areas"][0]["name"] == "Galley")

    # --- export and import ----------------------------------------------------------------------------
    sofa = next(o for o in get("/sites/home/objects")["objects"] if o["kind"] == "sofa")
    urllib.request.urlopen(urllib.request.Request(BASE + f"/api/v1/sites/home/objects/{sofa['id']}/label", data=json.dumps({"label": "my sofa"}).encode(), method="POST"))
    with page.expect_download() as dl:
        page.click("#export")
    path = dl.value.path()
    exported = json.loads(Path(path).read_text())
    check("Export site downloads a file: the area and the named object", exported["format"] == "mission-control-site"
          and [a["name"] for a in exported["areas"]] == ["Galley"] and [o["label"] for o in exported["objects"]] == ["my sofa"], exported["areas"])
    page.locator("#area-list [data-action=delete]").click()
    check("Delete asks twice: the first press only arms it", page.locator("#area-list [data-action=delete]").inner_text() == "Sure?" and len(get("/sites/home/areas")["areas"]) == 1)
    page.evaluate("window.__mc.renderAreas()")
    check("a redraw of the list does not disarm it", page.locator("#area-list [data-action=delete]").inner_text() == "Sure?")
    page.locator("#area-list [data-action=delete]").click()
    wait(page, "window.__mc.S.areas.length === 0")
    check("delete an area", get("/sites/home/areas")["areas"] == [])
    page.set_input_files("#import-file", path)
    wait(page, "window.__mc.S.areas.length === 1")
    check("Import site brings the area back, and says what it did", get("/sites/home/areas")["areas"][0]["name"] == "Galley"
          and "Imported" in page.locator("#toast").inner_text())

    # --- STOP --------------------------------------------------------------------------------------
    tap(page, -3.5, -2.5)
    page.click("#g-run")
    wait_state(page, ["running"], 10000)
    page.click("#stop-all")
    wait_state(page, ["cancelled"], 10000, new=False)
    run = get("/goal-runs")["runs"][0]
    check("STOP ALL from the page: the run is cancelled, the robot stopped and free", run["state"] == "cancelled"
          and get("/robots/fake-1")["robot"]["lock"]["holder"] is None and "stopped" in page.locator("#toast").inner_text().lower())
    page.click("#g-run")
    wait_state(page, ["running"], 10000)
    page.click("#stop-robot")
    wait_state(page, ["cancelled"], 10000, new=False)
    check("and STOP on the one robot", get("/goal-runs")["runs"][0]["state"] == "cancelled" and "fake-1 stopped" in page.locator("#toast").inner_text())
    check("STOP is still on screen", stop_visible())

    # --- an offline robot ---------------------------------------------------------------------------
    mc.robots["fake-1"].adapter.robot.set_offline(True)
    wait(page, "document.getElementById('robot-fake-1').dataset.online === 'false'", 15000)
    check("an offline robot says so on its card", page.locator("#robot-fake-1 .online").inner_text() == "offline")
    page.click("#stop-robot")
    wait(page, "document.getElementById('toast').textContent.includes('cannot be confirmed')")
    check("STOP to it is sent and says it cannot be confirmed", "cannot be confirmed" in page.locator("#toast").inner_text())
    mc.robots["fake-1"].adapter.robot.set_offline(False)
    wait(page, "document.getElementById('robot-fake-1').dataset.online === 'true'", 15000)

    # --- light and dark -----------------------------------------------------------------------------
    def token():
        return page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg-app').trim()")
    check("dark follows the system", token() == "#1b1c1f", token())
    page.emulate_media(color_scheme="light")
    check("light follows the system, with the Observatory's tokens", token() == "#e4e6ea", token())
    page.click("#theme")
    check("the switch overrides the system", token() == "#1b1c1f" and page.evaluate("document.documentElement.dataset.theme") == "dark")
    page.click("#theme")
    check("and back", token() == "#e4e6ea")
    check("no sideways scrolling in light either", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "mc-page-phone-light.png"), full_page=True)

    # --- an alarm (RFC-0023 D5): an anomaly on the stream is a badge in the header; a click shows what, where, since when, and acts -
    check("no alarm badge before any anomaly", page.locator("#alarm").is_hidden())
    mc.bus.emit("anomaly", robot="fake-1", goal_run=seen_run[0], watch="http://127.0.0.1:8070/watch/fake/s/r#t=3.5",
                anomaly={"n": 1, "t": 3.5, "anomaly": "joint_overload", "source": "robot", "module": "body", "severity": "major",
                         "detector": "joint_current", "summary": "left_knee at 130 mA, at or over 120 mA for 1.0 s", "margin": 10,
                         "values": {"joint": "left_knee", "ma": 130, "margin_unit": "mA"}, "where": {"frame": "map", "belief": [1.2, 0.4]}})
    wait(page, "!document.getElementById('alarm').hidden")
    check("must fail: the badge counts the last minute's alarms and names the worst",
          page.locator("#alarm").inner_text() == "1 alarm, major", page.locator("#alarm").inner_text())
    page.click("#alarm")
    wait(page, "!document.getElementById('alarms').hidden && document.querySelector('#alarm-insp h3')")
    insp = page.locator("#alarm-insp").inner_text()
    check("must fail: the inspector says what, where, since when and by how much", "joint_overload" in insp and "left_knee at 130 mA" in insp
          and "3.5 s into the run" in insp and "10 mA past its limit" in insp and "1.2, 0.4" in insp, insp)
    check("must fail: it opens the Observatory at the alarm's moment",
          page.locator("#alarm-insp a", has_text="Observatory").get_attribute("href") == "http://127.0.0.1:8070/watch/fake/s/r#t=3.5")
    page.click("#alarm-stop")
    wait(page, "document.getElementById('toast').textContent.includes('fake-1')")
    check("must fail: its STOP stops the robot it is about", "fake-1" in page.locator("#toast").inner_text(), page.locator("#toast").inner_text())
    check("no sideways scrolling with the alarms open", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    page.screenshot(path=str(Path(tempfile.gettempdir()) / "mc-page-alarm-phone.png"), full_page=True)
    page.click("#alarm")

    # --- desktop width -------------------------------------------------------------------------------
    page.set_viewport_size({"width": 1500, "height": 900})
    page.emulate_media(color_scheme="dark")
    page.evaluate("delete document.documentElement.dataset.theme; localStorage.removeItem('mc-theme')")
    wait(page, "window.__mc.toScreen(0, 0)[0] > 0")
    boxes = page.evaluate("""() => Object.fromEntries(['robots', 'mapcard', 'runs'].map((id) => { const r = document.getElementById(id).getBoundingClientRect(); return [id, [r.left, r.right]]; }))""")
    check("at 1500 px three columns: robots left, the map in the middle, runs right", boxes["robots"][1] <= boxes["mapcard"][0] + 1 and boxes["mapcard"][1] <= boxes["runs"][0] + 1, boxes)
    check("no sideways scrolling at 1500 px", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    check("STOP is still on screen (in the top bar from 700 px: 40 px for a pointer)", stop_visible(40))

    check("no script error and no console error in the whole session", errors == [], errors)

    # --- a server that wants tokens ---------------------------------------------------------------------
    _, TOKEN = mc.tokens.create("page")
    srv2 = serve(mc, "127.0.0.1", 0, require_tokens=True)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    BASE2 = f"http://127.0.0.1:{srv2.server_address[1]}"
    page2 = browser.new_context(viewport={"width": 390, "height": 800}).new_page()
    page2.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page2.goto(BASE2 + "/")
    wait(page2, "!document.getElementById('tokenbox').hidden")
    check("with tokens required the page loads and asks for one", page2.locator("#token").is_visible())
    check("STOP ALL works before any token is entered", (page2.click("#stop-all"), True)[1])
    wait(page2, "document.getElementById('toast').textContent.toLowerCase().includes('stop')")
    page2.fill("#token", "mc_wrong")
    page2.click("#token-set")
    wait(page2, "!document.getElementById('tokenbox').hidden")
    check("a wrong token asks again", page2.locator("#token").is_visible())
    page2.fill("#token", TOKEN)
    page2.click("#token-set")
    wait(page2, "window.__mc.ready && document.getElementById('robot-fake-1') && document.getElementById('conn').textContent === 'live'", 25000)
    check("the right token: the robots load and the event stream is live", page2.locator("#robot-fake-1").get_attribute("data-online") == "true"
          and page2.locator("#tokenbox").is_hidden())
    check("and it is kept for the next visit", page2.evaluate("localStorage.getItem('mc-token')") == TOKEN)
    srv2.shutdown()
    srv2.server_close()
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_page")
