"""Mission Control's robot page, Modules, Settings and its two drawers (RFC-0023 D3 and D10, phase 5 item 4a units A2 and A4a) in headless
Chromium, as test_robot_page.py does it: the real server, a pointer robot to the duck's profile behind the fake adapter and a version store
under a test installation. Modules lists the profile's four plugins as collapsible rows; Settings lists the blocks, shows a block group by
group (base, the running variant, the other), edits a copy in a drawer and saves it as the next version (from the next goal; Esc and Cancel
close it, the focus goes back), shows the server's refusal at the field, compares two versions in the History drawer, makes one current,
exports one (a download) and imports an edited file. Every number goes through the profile API. Phone width has no sideways scrolling.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
from contextlib import contextmanager
import copy
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
from runfile.profile import checksum
from runfile.profilestore import Store

tmp = Path(tempfile.mkdtemp(prefix="mc-settings-page-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)
REPO_FILE = Path(__file__).resolve().parents[3] / "robots" / "duck" / "profile.json"
REPO = json.loads(REPO_FILE.read_text())
STATE = tmp / "inst-state"
FOLDER = STATE / "profiles" / "duck"
inst = tmp / "installation.json"


def write_installation(profile):
    installation_file(inst, {"duck": {"variant": "sim", **({"profile": str(profile)} if profile else {})}}, state=str(STATE))


write_installation(None)
os.environ[installation.ENV] = str(inst)
mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}),
                     RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()
CRUISE = "locomotion.cruise_mps"


def get(path):
    with urllib.request.urlopen(BASE + "/api/v1" + path, timeout=10) as r:
        return json.loads(r.read())


def put_current(n):
    req = urllib.request.Request(BASE + "/api/v1/robots/duck-1/profile/current", data=json.dumps({"version": n}).encode(), method="PUT", headers={"Content-Type": "application/json"})
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
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark", accept_downloads=True)
    page = ctx.new_page()
    page.set_default_timeout(5000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
    no_scroll = lambda: page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    versions = lambda: sorted(page.eval_on_selector_all("#st-versions li[data-version]", "(els) => els.map((e) => Number(e.dataset.version))"))
    current = lambda: get("/robots/duck-1/profile")["profile"]["current"]
    listed = lambda: [x["version"] for x in get("/robots/duck-1/profile")["profile"]["versions"]]
    field = lambda path: page.locator(f"#st-form input[data-path='{path}']")
    err = lambda path: page.locator(f"#st-form [data-error-for='{path}']")
    drawer = lambda: page.locator("#drawer-root .scrim:not([hidden])")
    active = lambda: page.evaluate("document.activeElement.id")

    def open_page(n, hash_="robot/duck-1"):
        page.goto(BASE + f"/?visit={n}#{hash_}")
        wait(page, "window.__mc && window.__mc.ready && !document.getElementById('robot-page').hidden")
        wait(page, "document.querySelectorAll('#rp-parts [data-part]').length === 3")

    def tab(name):
        page.click(f"#tab-{name}")
        wait(page, f"!document.getElementById('rp-{name}').hidden")

    def settings():
        tab("settings")
        wait(page, "!!document.querySelector('#st-blocks [data-block]')")

    def block(name):
        page.click(f"#st-blocks [data-block='{name}']")
        wait(page, f"document.querySelector('#st-pane h2')?.textContent === '{name}'")

    def close_drawer():
        if drawer().count():
            page.keyboard.press("Escape")
            wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")

    def open_edit(blk, layer=None):
        close_drawer()
        settings()
        block(blk)
        page.click("#st-edit-open")
        page.locator("#st-edit").wait_for()
        if layer:
            b = page.locator(f"#st-edit-layer [data-layer={layer}]")
            if b.get_attribute("aria-pressed") != "true":
                b.click()
                wait(page, f"document.querySelector('#st-edit-layer [data-layer={layer}]').getAttribute('aria-pressed') === 'true'")

    def open_history():
        close_drawer()
        settings()
        page.click("#st-history-open")
        page.locator("#st-history").wait_for()

    def edit(path, value):
        field(path).fill(str(value))

    def say():
        return page.locator("#st-status").inner_text()

    def diff_is(a, b):
        wait(page, f"document.querySelector('#st-diff-out')?.textContent.includes('Version {a} to version {b}')")

    open_page(1)

    # --- Modules: the profile's four plugins, one collapsible row each --------------------------------------------------
    with soft("Modules"):
        tab("modules")
        wait(page, "document.querySelectorAll('#rp-modules [data-plugin]').length === 4")
        names = page.eval_on_selector_all("#rp-modules [data-plugin]", "(els) => els.map((e) => [e.dataset.plugin, e.querySelector('b').textContent])")
        check("must fail: Modules lists the profile's four plugins, each with its name and version", names == [[k, v] for k, v in REPO["plugins"].items()], names)
        heads = page.locator("#rp-modules button[data-collapse]")
        check("must fail: each is a row with a head button that says whether it is open and names its body", heads.count() == 4
              and all(h.get_attribute("aria-expanded") in ("true", "false") and h.get_attribute("aria-controls") for h in heads.all()))
        check("must fail: each says plainly that its live state is not reported (no source reaches Mission Control)",
              all("live state not reported" in page.locator(f"#rp-modules [data-plugin={k}]").inner_text() for k in REPO["plugins"]))
        loco_head = page.locator("#rp-modules [data-plugin=locomotion] button[data-collapse]")
        if loco_head.get_attribute("aria-expanded") == "true":
            loco_head.click()
            check("must fail: a row closes: its values are hidden", loco_head.get_attribute("aria-expanded") == "false" and page.locator("#rp-modules [data-plugin=locomotion] .kvgrid").is_hidden())
        for k in REPO["plugins"]:
            hd = page.locator(f"#rp-modules [data-plugin={k}] button[data-collapse]")
            if hd.get_attribute("aria-expanded") != "true":
                hd.click()
        loco = page.locator("#rp-modules [data-plugin=locomotion]").inner_text()
        check("must fail: each says which block it answers for and shows that block's values (the running variant's)", "answers for locomotion" in loco and "cruise_mps" in loco and "0.3" in loco, loco)
        check("must fail: the row of a block the running variant overrides says how many values, and shows them in the warn colour",
              "sim changes" in page.locator("#rp-modules [data-plugin=localisation] .badge").inner_text() and page.locator("#rp-modules [data-plugin=localisation] .kvgrid .ovr").count() >= 1)
        check("the values are in three columns on a desktop-wide row, one on a phone", page.evaluate(
            "getComputedStyle(document.querySelector('#rp-modules .kvgrid')).gridTemplateColumns.split(' ').length") == 1)
        page.screenshot(path=str(SHOTS / "rp-modules-phone-dark.png"), full_page=True)
        check("no sideways scrolling with the modules listed", no_scroll())
        page.click("#rp-modules [data-plugin=locomotion] a")
        wait(page, "!document.getElementById('rp-settings').hidden")
        wait(page, "document.querySelector('#st-blocks [data-block=locomotion]')?.getAttribute('aria-current') === 'true'")
        check("must fail: 'All of locomotion in Settings' goes to the Settings tab with that block chosen", page.url.endswith("#robot/duck-1/settings")
              and page.locator("#st-pane h2").inner_text() == "locomotion", page.url)

    # --- Settings: a store that cannot be written (the installation does not name it) -------------------------------
    with soft("Settings, not writable"):
        settings()
        open_history()
        check("must fail: no versions yet: History says the robot's own file runs", "own file" in page.locator("#st-versions").inner_text().lower() and versions() == [],
              page.locator("#st-versions").inner_text())
        close_drawer()
        check("must fail: Esc closed it, and the focus went back to the button that opened it", drawer().count() == 0 and active() == "st-history-open", active())
        check("must fail: why it cannot be written is shown, and Edit, Save and Import are off",
              "robots.duck.profile" in page.locator("#st-writable").inner_text() and page.locator("#st-save").is_disabled() and page.locator("#st-import-file").is_disabled()
              and page.locator("#st-edit-open").is_disabled(), page.locator("#st-writable").inner_text())

    write_installation(FOLDER)
    Store(STATE / "profiles").seed("duck", REPO_FILE)     # the operator's step: a store the installation names holds the robot's own file as version 1
    open_page(2)

    # --- Settings: the blocks, and a version block by block, base beside the running variant and the other ------------
    with soft("Settings, a version by block"):
        settings()
        check("the toolbar says which version is shown, which variant runs, and has History, Import and Export", page.locator("#st-version").input_value() == "1"
              and "runs the sim variant" in page.locator("#st-runs").inner_text() and page.locator("#st-history-open").is_visible() and page.locator("#st-export").is_visible()
              and page.locator("label.stfile").inner_text() == "Import")
        tunable = page.eval_on_selector_all("#st-blocks [data-block]", "(els) => els.map((e) => e.dataset.block)")
        check("must fail: the block list has the tunable blocks, then the identity blocks (read only) after their own heading",
              {"locomotion", "joints", "sensors", "localisation"} <= set(tunable) and tunable[-5:] == ["factsheet", "control", "capabilities", "plugins", "subsystems"]
              and "identity, edited in the file" in page.locator("#st-blocks").inner_text().lower() and "read only" in page.locator("#st-blocks [data-block=factsheet]").inner_text(), tunable)
        check("must fail: a tunable block with overrides of the running variant has a count badge, one without has none",
              page.locator("#st-blocks [data-block=localisation] .badge").count() == 1 and page.locator("#st-blocks [data-block=footprint] .badge").count() == 0)
        check("on a phone the block list is a horizontal list above the table", page.evaluate(
            "() => { const n = document.getElementById('st-blocks').getBoundingClientRect(), t = document.getElementById('st-pane').getBoundingClientRect(); return getComputedStyle(document.getElementById('st-blocks')).flexDirection === 'row' && n.bottom <= t.top + 1; }"))
        block("localisation")
        row = page.locator("#st-pane tr[data-path='odometry.scale']")
        cells = {c: row.locator(f"[data-col={c}]").inner_text() for c in ("base", "sim", "real")}
        check("must fail: the variants side by side: odometry scale base 1.0, sim 0.91 (overridden), real the same as base",
              cells["base"] == "1" and cells["sim"] == "0.91" and cells["real"] == "=", cells)
        check("must fail: the running variant's column is named and comes first after base, and the number it overrides is marked",
              "running" in page.locator("#st-pane [data-col-head=sim]").first.inner_text().lower() and row.get_attribute("data-overridden") == "sim"
              and page.eval_on_selector_all("#st-pane [data-group='localisation.odometry'] thead th", "(els) => els.map((e) => e.dataset.colHead || e.textContent)")[1:4] == ["base", "sim", "real"],
              row.get_attribute("data-overridden"))
        measured = (((REPO.get("variants") or {}).get("sim") or {}).get("localisation") or {}).get("odometry", {}).get("measured", "")
        line = " ".join(page.locator("#st-pane [data-measured-for='localisation.odometry']").all_inner_texts())
        check("must fail: a group's measured line is under its table, with its layer", "Measured (sim)" in line and measured[:30] in line, line)
        gh = page.locator("#st-pane [data-group='localisation.odometry'] button[data-collapse]")
        gh.click()
        check("must fail: a group is a collapsible card: closed, its table is hidden", gh.get_attribute("aria-expanded") == "false" and row.is_hidden())
        gh.click()
        page.check("#st-only-overridden")
        paths = page.eval_on_selector_all("#st-pane tr[data-path]", "(els) => els.map((e) => e.dataset.path)")
        check("must fail: only what a variant changes leaves just the overridden numbers", paths and all(r.get_attribute("data-overridden") for r in page.locator("#st-pane tr[data-path]").all()) and "odometry.scale" in paths, paths)
        page.uncheck("#st-only-overridden")
        check("must fail: a summary says how many numbers the running variant overrides", "overrides" in page.locator("#st-summary").inner_text(), page.locator("#st-summary").inner_text())
        block("factsheet")
        check("must fail: an identity block is read, not edited: its values, and no Edit button", page.locator("#st-pane [data-locked=factsheet] tr").count() > 1 and page.locator("#st-edit-open").count() == 0)
        block("locomotion")
        check("a tunable block has its Edit button, named for it", page.locator("#st-edit-open").inner_text().strip() == "Edit locomotion")
        check("no sideways scrolling with a block's tables at 390 px", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-settings-phone-dark-view.png"), full_page=True)

    # --- edit a copy, save: a new version from the next goal ---------------------------------------------------------
    with soft("edit and save"):
        open_edit("locomotion")
        check("must fail: the edit drawer takes the focus, and says which block it edits", page.evaluate("document.querySelector('#st-edit').contains(document.activeElement)")
              and "locomotion" in page.locator("#st-edit-title").inner_text())
        check("must fail: the layer control is Base, Sim, Real and opens on the running variant", page.locator("#st-edit-layer button").all_inner_texts() == ["Base", "Sim", "Real"]
              and page.locator("#st-edit-layer [aria-pressed=true]").inner_text() == "Sim")
        check("must fail: Tab stays inside the drawer", all((page.keyboard.press("Tab"), page.evaluate("document.querySelector('#st-edit').contains(document.activeElement)"))[1] for _ in range(40)))
        page.click("#st-edit-layer [data-layer=base]")
        f = field(CRUISE)
        check("must fail: the form has the number with its unit, its value, and the block's measured and why",
              f.input_value() == "0.3" and "m/s" in page.locator(f"#st-form [data-unit-for='{CRUISE}']").inner_text()
              and page.locator("#st-form [data-notes='locomotion'] textarea[data-note=why]").count() == 1)
        check("must fail: the footer says what a save does and names the version it makes",
              page.locator("#st-save-note").inner_text() == "Saved as version 2. It applies from the next goal, never during one." and page.locator("#st-save").inner_text() == "Save as version 2"
              and page.locator("#st-cancel").inner_text() == "Cancel")
        edit(CRUISE, 0.25)
        page.click("#st-save")
        wait(page, "document.querySelectorAll('#st-versions li[data-version]').length === 2")
        wait(page, "!document.querySelector('#drawer-root .scrim:not([hidden])')")
        check("must fail: a save makes a new version: 1 (seeded) and 2, and 2 is current", versions() == [1, 2] and listed() == [1, 2] and current() == 2, (versions(), current()))
        check("must fail: the drawer closed, and the focus is back on the button that opened it", drawer().count() == 0 and active() == "st-edit-open", active())
        check("the saved version is marked as from the next goal, and says current",
              "from the next goal" in page.locator("#st-versions li[data-version='2']").inner_text() and page.locator("#st-versions li[data-version='2']").get_attribute("data-current") == "true")
        check("the API holds the edited number", get("/robots/duck-1/profile")["profile"]["profile"]["locomotion"]["cruise_mps"] == 0.25)
        check("must fail: the strip and the Settings tab follow: version 2", "version 2" in page.locator("#rp-facts").inner_text() and page.locator("#tab-settings-badge").inner_text() == "v2",
              page.locator("#rp-facts").inner_text())
        check("and the table behind shows the new number", page.locator("#st-pane tr[data-path='cruise_mps'] [data-col=base]").inner_text() == "0.25")

    # --- Esc closes the drawer without saving; Cancel too -------------------------------------------------------------------
    with soft("Esc and Cancel"):
        open_edit("locomotion", "base")
        edit(CRUISE, 0.1)
        page.keyboard.press("Escape")
        check("must fail: Esc closes the edit drawer, gives the focus back, and saves nothing", drawer().count() == 0 and active() == "st-edit-open" and listed() == [1, 2], (active(), listed()))
        page.click("#st-edit-open")
        check("must fail: a drawer opened again has the saved value, not the abandoned edit", field(CRUISE).input_value() == "0.25", field(CRUISE).input_value())
        edit(CRUISE, 0.1)
        page.click("#st-cancel")
        check("Cancel closes it the same way", drawer().count() == 0 and active() == "st-edit-open" and listed() == [1, 2])

    # --- an invalid edit: the server's reason, at the field ---------------------------------------------------------------
    with soft("invalid edit"):
        open_edit("locomotion", "base")
        edit(CRUISE, -1)
        edit("locomotion.slowest_mps", 0.2)
        page.click("#st-save")
        err(CRUISE).wait_for()
        e = err(CRUISE).inner_text()
        check("must fail: an invalid number shows the server's message at its field (the validator's own words)", "must be a number above 0" in e, e)
        check("must fail: the field is marked invalid for the screen reader, the other fields have no error, and the drawer stays open",
              field(CRUISE).get_attribute("aria-invalid") == "true" and page.locator("#st-form [data-error-for]:not(:empty)").count() == 1 and drawer().count() == 1)
        check("must fail: nothing was saved: still versions 1 and 2, 2 current", listed() == [1, 2] and current() == 2, listed())
        check("no sideways scrolling with an error shown", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-settings-phone-dark-error.png"))
        edit(CRUISE, 0.25)
        page.click("#st-save")
        wait(page, "document.querySelector('#st-status').textContent.length > 0")
        check("must fail: a save that changes nothing is refused by the server, said in the status, no new version", "nothing to save" in say() and listed() == [1, 2], say())

    # --- a variant's own number: the sim layer ------------------------------------------------------------------------------
    with soft("the sim layer"):
        open_edit("localisation", "sim")
        check("must fail: the sim layer shows the sim's own value, marked as an override", field("localisation.odometry.scale").input_value() == "0.91"
              and "set" in (field("localisation.odometry.scale").get_attribute("class") or "").split(), field("localisation.odometry.scale").input_value())
        inherited = page.locator("#st-form input[placeholder^='= base']")
        check("must fail: a number the variant does not set is empty, with the base it inherits as its placeholder", inherited.count() > 0 and inherited.first.input_value() == ""
              and "set" not in (inherited.first.get_attribute("class") or "").split(), inherited.count())
        edit("localisation.odometry.scale", 0.9)
        page.click("#st-save")
        err("localisation.odometry.scale").wait_for()
        check("must fail: the validator's refusal of a sim number (the table it must agree with) shows at that field, in the sim layer",
              "by_speed" in err("localisation.odometry.scale").inner_text() and listed() == [1, 2], err("localisation.odometry.scale").inner_text())
        open_edit("joints", "sim")
        check("the sim layer shows the sim's own current limit", field("joints.limits.current_ma").input_value() == "120", field("joints.limits.current_ma").input_value())
        check("a variant layer has measured and why for each group", page.locator("#st-form [data-notes='joints.limits'] textarea").count() == 2)
        edit("joints.limits.current_ma", 150)
        page.click("#st-save")
        wait(page, "document.querySelectorAll('#st-versions li[data-version]').length === 3")
        pr = get("/robots/duck-1/profile")["profile"]["profile"]
        check("must fail: it writes the variant's number and leaves the base alone", pr["variants"]["sim"]["joints"]["limits"]["current_ma"] == 150
              and pr["joints"]["limits"]["current_ma"] == 900 and listed() == [1, 2, 3])

    # --- History and compare ----------------------------------------------------------------------------------------------------
    with soft("history and diff"):
        open_history()
        check("must fail: History lists the versions, newest first, marks the current one, and offers Make current on the others only",
              page.eval_on_selector_all("#st-versions li[data-version]", "(els) => els.map((e) => Number(e.dataset.version))") == [3, 2, 1]
              and page.locator("#st-versions li[data-current=true]").count() == 1 and page.locator("#st-versions li[data-version='3'] .cur").inner_text() == "current"
              and page.locator("#st-versions button[data-act=use]").count() == 2 and page.locator("#st-versions button[data-act=view]").count() == 3)
        check("must fail: the drawer opens on a comparison of the last two versions, and shows it", page.locator("#st-diff-a").input_value() == "2" and page.locator("#st-diff-b").input_value() == "3")
        diff_is(2, 3)
        check("must fail: the diff of 2 and 3 shows the sim number, by its path in variants", page.locator("#st-diff-out [data-path='variants.sim.joints.limits.current_ma']").count() == 1)
        page.select_option("#st-diff-a", "1")
        page.select_option("#st-diff-b", "2")
        diff_is(1, 2)
        row = page.locator("#st-diff-out [data-path]")
        check("must fail: the diff of 1 and 2 shows the one changed field, from 0.3 to 0.25",
              row.count() == 1 and row.first.get_attribute("data-path") == CRUISE and "0.3" in row.first.inner_text() and "0.25" in row.first.inner_text(), row.first.inner_text())
        check("no sideways scrolling with the History drawer open", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-settings-history-phone-dark.png"))
        close_drawer()

    # --- a change of a note alone ---------------------------------------------------------------------------------------------
    with soft("a note alone"):
        open_edit("locomotion", "base")
        page.fill("#st-form [data-notes='locomotion'] textarea[data-note=why]", "walked slower on the rug")
        page.click("#st-save")
        wait(page, "document.querySelectorAll('#st-versions li[data-version]').length === 4")
        open_history()
        page.select_option("#st-diff-a", "3")
        page.select_option("#st-diff-b", "4")
        wait(page, "document.querySelector('#st-diff-out').textContent.includes('note')")
        check("must fail: two versions that differ only in a note: the diff says so and does not read as the same", "only" in page.locator("#st-diff-out").inner_text().lower()
              and page.locator("#st-diff-out [data-path]").count() == 0, page.locator("#st-diff-out").inner_text())
        page.check("#st-diff-notes")
        wait(page, "!!document.querySelector('#st-diff-out [data-path=\"locomotion.why\"]')")
        check("... and with notes it shows the note", "walked slower on the rug" in page.locator("#st-diff-out").inner_text())
        page.uncheck("#st-diff-notes")
        close_drawer()

    # --- view an older version --------------------------------------------------------------------------------------------------
    with soft("view a version"):
        open_history()
        page.locator("#st-versions li[data-version='1'] button[data-act=view]").click()
        wait(page, "document.querySelector('#st-shown').textContent.startsWith('Version 1')")
        back = active()
        block("locomotion")
        wait(page, "document.querySelector('#st-pane [data-path=\"cruise_mps\"] [data-col=base]')?.textContent === '0.3'")
        check("must fail: viewing version 1 shows its number, not the current's, closes the drawer and puts the version in the toolbar",
              page.locator("#st-shown").inner_text().startswith("Version 1") and drawer().count() == 0 and page.locator("#st-version").input_value() == "1" and back == "st-history-open", back)
        page.select_option("#st-version", "2")
        wait(page, "document.querySelector('#st-shown').textContent.startsWith('Version 2')")
        check("the version select in the toolbar shows another version", page.locator("#st-pane tr[data-path='cruise_mps'] [data-col=base]").inner_text() == "0.25")

    # --- set current -----------------------------------------------------------------------------------------------------------------
    with soft("set current"):
        open_history()
        page.locator("#st-versions li[data-version='1'] button[data-act=use]").click()
        wait(page, "document.querySelector('#st-versions li[data-version=\"1\"]')?.dataset.current === 'true'")
        check("must fail: choosing version 1 makes it current, in the API too, marked from the next goal", current() == 1
              and "from the next goal" in page.locator("#st-versions li[data-version='1']").inner_text()
              and page.locator("#st-versions li[data-current=true]").count() == 1, current())
        check("must fail: the current version has no Make current button", page.locator("#st-versions li[data-version='1'] button[data-act=use]").count() == 0)
        close_drawer()

    # --- export: a download ---------------------------------------------------------------------------------------------------------------
    with soft("export"):
        page.select_option("#st-version", "2")
        wait(page, "document.querySelector('#st-shown').textContent.startsWith('Version 2')")
        with page.expect_download() as dl:
            page.click("#st-export")
        d = dl.value
        body = json.loads(Path(d.path()).read_text())
        want = get("/robots/duck-1/profile/export?version=2")["export"]
        check("must fail: Export downloads the shown version as the API's export JSON", body == want and body["version"] == 2 and body["profile"]["locomotion"]["cruise_mps"] == 0.25
              and d.suggested_filename.endswith(".json") and "duck" in d.suggested_filename, d.suggested_filename)

    # --- import --------------------------------------------------------------------------------------------------------------------------------
    with soft("import"):
        n = len(listed())
        edited = copy.deepcopy(want)
        edited["profile"]["locomotion"]["cruise_mps"] = 0.22
        edited["checksum"] = checksum(edited["profile"])
        f = tmp / "edited.json"
        f.write_text(json.dumps(edited))
        page.set_input_files("#st-import-file", str(f))
        wait(page, f"document.querySelectorAll('#st-versions li[data-version]').length === {n + 1}")
        got = get("/robots/duck-1/profile")["profile"]
        check("must fail: an edited file imported makes a new version, current, with the edited number", got["current"] == n + 1 and got["profile"]["locomotion"]["cruise_mps"] == 0.22
              and "from the next goal" in page.locator(f"#st-versions li[data-version='{n + 1}']").inner_text(), (n, got["current"]))
        bad = copy.deepcopy(edited)
        bad["profile"]["locomotion"]["cruise_mps"] = 0.21
        f2 = tmp / "tampered.json"
        f2.write_text(json.dumps(bad))
        page.set_input_files("#st-import-file", str(f2))
        wait(page, "document.querySelector('#st-status').textContent.includes('does not match')")
        check("must fail: a file changed without its checksum is refused with the server's words, nothing written", len(listed()) == n + 1, say())
        f3 = tmp / "notjson.json"
        f3.write_text("{not json")
        page.set_input_files("#st-import-file", str(f3))
        wait(page, "document.querySelector('#st-status').textContent.includes('not JSON')")
        check("must fail: a file that is not JSON is said so in the page", "not JSON" in say(), say())

    # --- a robot with no profile -----------------------------------------------------------------------------------------------------------------------
    with soft("no profile"):
        page.evaluate("location.hash = '#robot/fake-1/modules'")
        wait(page, "document.getElementById('rp-title').textContent.includes('Fake robot') && !document.getElementById('rp-modules').hidden")
        check("must fail: a robot with no profile: Modules says so, and lists no plugin", "no profile" in page.locator("#rp-modules").inner_text().lower() and page.locator("#rp-modules [data-plugin]").count() == 0)
        page.evaluate("location.hash = '#robot/fake-1/settings'")
        wait(page, "!document.getElementById('rp-settings').hidden")
        check("must fail: Settings and Calibration say so, and there are no drawers", "no profile" in page.locator("#rp-settings").inner_text().lower() and page.locator("#st-versions").count() == 0
              and "no profile" in page.locator("#rp-calibration").inner_text().lower() and page.locator("#drawer-root *").count() == 0)
        page.evaluate("location.hash = '#robot/nope/settings'")
        wait(page, "document.getElementById('rp-title').textContent.includes('nope')")
        page.evaluate("location.hash = '#robot/duck-1/settings'")
        wait(page, "!!document.querySelector('#st-versions') && !!document.querySelector('#st-blocks [data-block]')")
        check("and back on the duck (after a wrong id too) Settings is built again", page.locator("#st-pane h2").count() == 1 and page.locator("#rp-modules-body").inner_text() != "")

    # --- the form is not thrown away by the page's own refresh ----------------------------------------------------------------------------------
    with soft("refresh keeps the form"):
        open_edit("locomotion", "base")
        edit(CRUISE, 0.28)
        page.evaluate("() => window.__mc.renderRobotPage()")
        check("must fail: the page's own refresh does not throw away what is being typed", field(CRUISE).input_value() == "0.28", field(CRUISE).input_value())
        put_current(4)                                  # another client (the CLI, a second tab) makes version 4 current
        page.evaluate("() => refreshRobot('duck-1')")
        wait(page, "document.querySelector('#st-versions li[data-version=\"4\"]')?.dataset.current === 'true'")
        check("must fail: a version made current elsewhere is picked up, and still the typed number stays", field(CRUISE).input_value() == "0.28", field(CRUISE).input_value())
        close_drawer()

    # --- phone width: the drawer is the whole screen ---------------------------------------------------------------------------------------------------
    with soft("phone"):
        page.set_viewport_size({"width": 390, "height": 844})
        open_edit("locomotion", "sim")
        check("must fail: on a phone the drawer is as wide as the screen, with no sideways scrolling, and its controls are 44 px tall", page.evaluate(
            "() => { const d = document.querySelector('#st-edit .drawer').getBoundingClientRect(); const ok = [...document.querySelectorAll('#st-edit .dhead button, #st-edit .seg button, #st-edit .dfoot button, #st-edit .frow input')].every((e) => e.getBoundingClientRect().height >= 44); return Math.round(d.width) === window.innerWidth && ok; }")
              and no_scroll())
        page.screenshot(path=str(SHOTS / "rp-settings-drawer-phone-dark.png"))
        close_drawer()
        page.emulate_media(color_scheme="light")
        check("light: no sideways scrolling", no_scroll())
        page.screenshot(path=str(SHOTS / "rp-settings-phone-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")

    # --- desktop ---------------------------------------------------------------------------------------------------------------------------------------------------
    with soft("desktop"):
        page.set_viewport_size({"width": 1440, "height": 960})
        settings()
        block("locomotion")
        check("must fail: desktop: no sideways scrolling, the block list left of the groups", no_scroll() and page.evaluate(
            "() => { const a = document.getElementById('st-blocks').getBoundingClientRect(), b = document.getElementById('st-pane').getBoundingClientRect(); return a.right <= b.left + 1 && getComputedStyle(document.getElementById('st-blocks')).flexDirection === 'column'; }"))
        page.screenshot(path=str(SHOTS / "rp-settings-desktop-dark.png"))
        open_edit("locomotion", "sim")
        check("must fail: desktop: the drawer is a right-hand side panel over a scrim", page.evaluate(
            "() => { const d = document.querySelector('#st-edit .drawer').getBoundingClientRect(); return Math.round(d.width) === 480 && Math.round(d.right) === window.innerWidth; }"))
        page.screenshot(path=str(SHOTS / "rp-settings-drawer-desktop-dark.png"))
        page.emulate_media(color_scheme="light")
        page.screenshot(path=str(SHOTS / "rp-settings-drawer-desktop-light.png"))
        close_drawer()
        page.screenshot(path=str(SHOTS / "rp-settings-desktop-light.png"))
        page.emulate_media(color_scheme="dark")
        page.set_viewport_size({"width": 390, "height": 800})

    check("no script error and no console error in the whole session (a 4xx the page was told about is not one)", [e for e in errors if "status of 4" not in e] == [], errors)
    browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_settings_page")
