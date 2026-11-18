"""Mission Control's page in headless Chromium (RFC-0014 step 1), the way the viewer's page tests do it: the real
server, a fake robot on the real clock, the page driven only by what a person does (tap the map, fill a
field, press a button) and checked against the API. At phone width and at desktop width, in dark and light.
No fixed sleeps: every wait is for a condition.

Needs Chromium and Playwright, which are the viewer's (control has no browser dependency), so it runs in the viewer's
environment with Mission Control and the gate on the path:
  make test-control-page          (cd viewer && PYTHONPATH=../control/src:../duck/src uv run --frozen python ../control/tests/test_page.py)"""

import copy
import json
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import FAKE_FILE, check, finish, robot_file

from miniview.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig

caps = copy.deepcopy(FAKE_FILE["capabilities"])
caps["drive"] = {"max_vx": 2.0, "max_vyaw": 6.0, "deadman_s": 0.5}  # quick, so a sweep takes seconds, not a minute
mc = MissionControl([RobotConfig(robot_file("fake-1", capabilities=caps, rates={"state_hz": 5.0, "map_hz": 2.0, "max_state_hz": 10.0}))],
                    state_dir=tempfile.mkdtemp(prefix="mc-page-"))
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
    wait(page, """([s, prev, isNew]) => { const e = document.getElementById('run-state'), d = document.getElementById('run-detail');
        return !!e && s.includes(e.textContent) && (!isNew || Number(d.dataset.run) > prev); }""", timeout, [states, seen_run[0], new])
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

    def stop_visible():
        return page.evaluate("""() => ['stop-robot', 'stop-all'].every((id) => {
            const r = document.getElementById(id).getBoundingClientRect();
            return r.top >= 0 && r.bottom <= window.innerHeight && r.left >= 0 && r.right <= window.innerWidth && r.height >= 44;
        })""")
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
    wait_state(page, ["reached", "not_found", "failed", "refused"], 60000)
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
    wait_state(page, ["reached", "refused", "failed"], 30000)
    check("go_to_area by form", get("/goal-runs")["runs"][0]["state"] == "reached")
    page.select_option("#g-kind", "explore")
    page.click("#g-run")
    wait_state(page, ["done", "refused", "failed"], 60000)
    check("explore by form: done", get("/goal-runs")["runs"][0]["state"] == "done")
    page.select_option("#g-kind", "inventory")
    page.click("#g-run")
    wait_state(page, ["done", "refused", "failed"], 90000)
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
    wait_state(page, ["reached", "failed"], 30000)
    check("Run on a library goal: a run linked to it", get("/goal-runs")["runs"][0]["goal_id"] == get("/goals")["goals"][0]["id"])
    page.select_option("#g-kind", "point")
    tap(page, 2.5, -2.0)
    page.click("#g-run")
    wait_state(page, ["reached", "failed"], 30000)
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

    # --- desktop width -------------------------------------------------------------------------------
    page.set_viewport_size({"width": 1500, "height": 900})
    page.emulate_media(color_scheme="dark")
    page.evaluate("delete document.documentElement.dataset.theme; localStorage.removeItem('mc-theme')")
    wait(page, "window.__mc.toScreen(0, 0)[0] > 0")
    boxes = page.evaluate("""() => Object.fromEntries(['robots', 'mapcard', 'runs'].map((id) => { const r = document.getElementById(id).getBoundingClientRect(); return [id, [r.left, r.right]]; }))""")
    check("at 1500 px three columns: robots left, the map in the middle, runs right", boxes["robots"][1] <= boxes["mapcard"][0] + 1 and boxes["mapcard"][1] <= boxes["runs"][0] + 1, boxes)
    check("no sideways scrolling at 1500 px", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
    check("STOP is still on screen", stop_visible())

    check("no script error and no console error in the whole session", errors == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_page")
