"""The same named screenshots of both apps, every run (docs/wip/LOOK-AND-FEEL-PLAN.md, U-SHOTS), so the operator can
compare before and after the look-and-feel work.

It starts its own Observatory (a temp data folder, one fixed duck run with the duck's real body, belief apart from truth, a map, a
plan, anomalies and decisions, depth frames) and its own Mission Control (the fake robot, the duck's description, behind the
Observatory's /control/ as in production), on free ports. Nothing on 8060/8070 is touched. Then it takes each view in dark and light,
at 1440x900 and 390x844, named <app>-<view>-<theme>-<width>.png.

    cd apps/observatory && uv run --frozen python ../../scripts/look_shots.py --out DIR [--html] [--only TEXT[,TEXT...]]
    cd apps/observatory && uv run --frozen python ../../scripts/look_shots.py --compare BEFORE AFTER --out DIR

Runs in the Observatory's environment (Playwright and Chromium as the page tests use them); installs nothing.
The duck's meshes (robots/duck/meshes, `make robots`) are needed for the body shots; without them those are listed, not faked."""

import argparse
import atexit
import html
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "apps/observatory/tests", REPO / "apps/mission-control/tests", REPO / "apps/mission-control/src", REPO / "libs/gate/src", REPO / "libs/missions/src"):
    sys.path.insert(0, str(p))

CACHE = Path.home() / ".cache" / "robotics-lab-tests"
THEMES = ("dark", "light")
SIZES = {1440: (1440, 900), 390: (390, 844)}
FREEZE = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
T_MOMENT = 2.6                                   # the moment every Observatory run shot is taken at (#t=)
KEY, SCENE_ID, SCENE_KEY = "duck/room/shots1", "room", "duck/room/shots1"

# (app, view, widths it is taken at, the page the view needs): the list is the contract; a name is never reused for another view
VIEWS = [
    ("observatory", "runs", (1440, 390)), ("observatory", "3d", (1440, 390)), ("observatory", "map", (1440, 390)),
    ("observatory", "eye", (1440, 390)), ("observatory", "chase", (1440, 390)), ("observatory", "watch", (1440, 390)),
    ("observatory", "explore", (1440, 390)),
    ("control", "overview", (1440, 390)), ("control", "robot", (1440, 390)), ("control", "body", (1440, 390)),
    ("control", "drawer", (390,)),
]
NOT_COVERED = [
    "observatory-3d: the camera is the page's own default orbit (the page has no camera setter); it is the same every run, not a pose of ours",
    "control-drawer at 1440: asked for on the phone only",
    "a live (still recording) run, a real robot, the semantic-object layer and the video export: no fixture draws them here",
]


# ---- the fixture run ------------------------------------------------------------------------------------------------------------------

def build_data(data: Path, joints: list) -> None:
    from helpers import catalog, make_run, tick

    qmul = lambda a, b: (a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],  # noqa: E731
                         a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0])
    qz = lambda a: (math.cos(a / 2), 0.0, 0.0, math.sin(a / 2))  # noqa: E731
    qy = lambda a: (math.cos(a / 2), 0.0, math.sin(a / 2), 0.0)  # noqa: E731
    epoch = [0.5, -0.2, 0.3]
    res, origin, w, h = 0.1, [-0.5, -1.0], 40, 25
    plan = [[0.0, 0.0], [0.5, 0.0], [1.0, 0.1], [1.5, 0.1]]
    cells = "".join("." if (-0.3 <= origin[1] + (j + 0.5) * res <= 0.3 and origin[0] + (i + 0.5) * res < 1.5) else "?" for j in range(h) for i in range(w))
    cells = "".join("#" if (i == 30 and 3 <= j <= 12) else c for j in range(h) for i in range(w) for c in [cells[j * w + i]])
    belief = lambda k: [0.05 * k, 0.01 * k, 0.02 * k]  # noqa: E731
    points = lambda k: [[round(belief(k)[0] + 0.5, 3), round(belief(k)[1], 3), 0.0, "f"], [round(belief(k)[0] + 0.6, 3), round(belief(k)[1] + 0.1, 3), 0.3, "o"]]  # noqa: E731

    def anomaly(t, name, severity, joint=None):
        values = {"joint": joint, "margin_unit": "mA"} if joint else {"jump_m": 0.9, "margin_unit": "m"}
        raw = {"event": "anomaly", "anomaly": name, "source": "robot", "module": "body", "severity": severity, "detector": f"{name}_rule", "version": 1,
               "summary": f"{name}: made up for the screenshots", "values": values, "margin": 0.1, "where": {"frame": "map", "belief": [0.3, 0.0]},
               "evidence": {}, "related": [], "duration_s": 0.4}
        return (t, "event", {"kind": "anomaly", "text": f"anomaly {name} ({severity})", "notable": True, "t_src": t, "raw": raw})

    rec = [(0.0, "epoch", {"map_to_world": epoch}),
           (0.9, "world", {"grid": {"res": res, "origin": origin, "w": w, "h": h, "cells": cells}, "obstacles": [[1.1, 0.35]], "drops": [[1.4, 0.7]]}),
           (0.95, "plan", {"path": plan})]
    for k in range(30):
        t = round(1.0 + 0.1 * k, 3)
        b = belief(k)
        rec.append(tick(t, b[0], belief=b, truth=[b[0] + epoch[0] + 0.03, b[1] + epoch[1] - 0.02, b[2] + epoch[2]], cmd=[0.3, 0.05 * (k % 3)], depth=points(k),
                        truth_3d={"z": 0.12, "quat": list(qmul(qz(b[2] + epoch[2]), qy(0.03)))}))
        if k % 2 == 0:
            q = qmul(qz(0.4 + 0.02 * k), qy(0.05 + 0.002 * k))
            rec.append((round(t + 0.01, 3), "depth_frame", {
                "rows": 8, "cols": 8, "distance_mm": [300 + 20 * i for i in range(64)], "status": [5] * 64, "seq": k, "frame_t_ns": 1_000_000_000 + k,
                "state_t_ns": 1_000_000_000 + k - 1000, "pair_dt_ms": -0.001, "t_src": round(t + 0.01, 3), "derived": {"points": points(k)},
                "state": {"quat": list(q), "odom_z": 0.118 + 0.0005 * k, "tof": {"pos": [0.08, 0.02, 0.11], "quat": list(qy(0.2 + 0.001 * k))}}, "pose": b}))
        if joints:      # a run declares its signals; with no joints it has none, and a signals record would be refused
            rec.append((round(t + 0.05, 3), "signals", {"values": {f"joint_{j}": round(0.25 * math.sin(0.7 * k + i), 4) for i, j in enumerate(joints)},
                                                         "t_src": round(t + 0.05, 3)}))
    dec = lambda rule, reason, **v: {"rule": rule, "reason": reason, "values": v}  # noqa: E731
    rec += [(1.55, "event", {"kind": "tight_pivot", "text": "tight_pivot room_m 0.156", "notable": True, "t_src": 1.55, "raw": {},
                             "decision": dec("tight_pivot", "no clear floor for an arc", room_m=0.156, min_room_m=0.11)}),
            (2.35, "event", {"kind": "refused", "text": "refused why no room", "notable": True, "t_src": 2.35, "raw": {},
                             "decision": dec("refused", "no room to turn", room_m=0.106, min_room_m=0.11)}),
            anomaly(2.0, "joint_tracking", "minor", joints[0] if joints else None), anomaly(2.7, "joint_overload", "major", joints[-1] if joints else None),
            anomaly(3.2, "pose_jump", "critical"), (3.95, "end", {"verdict": "reached"})]
    rec.sort(key=lambda r: r[0])
    sigs = [{"name": f"joint_{j}", "kind": "number", "unit": "rad"} for j in joints]
    cat = catalog(data)
    cat.put_scene({"id": SCENE_ID, "name": "A room", "kind": "test", "bounds": [-1, 3, -1.5, 1.5], "boxes": [{"name": "table", "cx": 1.0, "cy": -0.7, "z0": 0.0, "z1": 0.4, "hx": 0.2, "hy": 0.2, "yaw": 0.0}],
                   "hazards": [{"name": "pit", "kind": "drop", "x0": 1.2, "x1": 1.8, "y0": 0.4, "y1": 0.9, "yaw": 0.0, "depth": 0.3}]})
    make_run(data, KEY, rec, started_at_ns=1_800_000_000 * 10**9, signals=sigs)
    make_run(data, "duck/room/shots0", [(0.0, "epoch", {"map_to_world": epoch})] + [tick(round(1.0 + 0.1 * k, 3), 0.04 * k) for k in range(20)] + [(3.1, "end", {"verdict": "reached"})],
             started_at_ns=1_700_000_000 * 10**9)
    cat.scan()


# ---- the shots ------------------------------------------------------------------------------------------------------------------------

def settle(page, ms=250):
    page.evaluate("document.fonts.ready")
    page.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.wait_for_timeout(ms)


def go_obs(page, base, hash_="", path="/web/three/"):
    page.goto(f"{base}{path}#{hash_}" if hash_ else f"{base}{path}")
    page.wait_for_function("window.miniview !== undefined", timeout=30000)
    page.wait_for_function("window.__ready === true", timeout=30000)


def obs_run(page, base, view, frame="world", path="/web/three/"):
    go_obs(page, base, f"scene={SCENE_ID}&run={KEY}&view={view}&frame={frame}&t={T_MOMENT}", path)
    page.wait_for_function("window.miniview.state().run !== null", timeout=30000)
    page.evaluate("window.miniview.whenLoaded()")
    page.evaluate(f"window.miniview.setTime({T_MOMENT})")
    page.wait_for_function("window.__ready === true", timeout=30000)
    if view == "3d":
        # the page's default camera (11 m away) is its fixed pose; the same wheel steps over the stage close in on the robot, the same each run
        box = page.locator("#stage").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        for _ in range(4):
            page.mouse.wheel(0, -400)
            settle(page, 150)
        page.mouse.move(2, 2)                       # off the stage: the cursor readout is part of the pane while the pointer is over it
        settle(page, 100)
    if view in ("eye", "watch"):
        page.wait_for_function("(() => { const e = window.miniview.state().eye; return !!e && !e.pending; })()", timeout=15000)


def take_observatory(page, view, base, mc_base, desc):
    if view == "runs":
        go_obs(page, base)
        page.wait_for_selector("#scenespage tr[data-run]", timeout=15000)
    elif view == "3d":
        obs_run(page, base, "3d")
    elif view == "map":
        obs_run(page, base, "top", "map")
    elif view in ("eye", "chase"):
        obs_run(page, base, view)
    elif view == "watch":
        obs_run(page, base, "watch", path=f"/watch/{KEY}")
    elif view == "explore":
        obs_run(page, base, "3d")
        page.evaluate("window.__ready = false")
        page.evaluate("window.miniview.explore()")
        page.wait_for_function("window.__ready === true", timeout=30000)
        if desc:
            page.wait_for_function("(() => { const s = window.miniview.exploreState(); return !!s && s.shown !== false; })()", timeout=30000)


def take_control(page, view, base, mc_base, desc):
    n_visuals = desc["n_visuals"] if desc else 0
    wait_ready = lambda: page.wait_for_function("window.__mc && window.__mc.ready", timeout=30000)  # noqa: E731
    if view == "overview":
        page.goto(f"{base}/control/")
        wait_ready()
        page.wait_for_function("document.querySelector('#robot-fake-1')?.getAttribute('data-online') === 'true'", timeout=15000)
    elif view == "robot":
        page.goto(f"{base}/control/#robot/duck-1")
        wait_ready()
        page.wait_for_function("!document.getElementById('robot-page').hidden && document.querySelectorAll('#rp-parts [data-part]').length === 3", timeout=15000)
    elif view == "body":
        page.goto(f"{base}/control/#robot/duck-1/body")
        wait_ready()
        page.wait_for_function("!document.getElementById('robot-page').hidden && !!window.__mc.body", timeout=30000)
        if n_visuals:
            page.wait_for_function(f"window.__mc.body.state() && window.__mc.body.state().meshes === {n_visuals}", timeout=60000)
    elif view == "drawer":
        page.goto(f"{base}/control/#robot/duck-1/settings")
        wait_ready()
        page.wait_for_function("!!document.querySelector('#st-blocks [data-block]')", timeout=15000)
        page.click("#st-history-open")
        page.locator("#st-history").wait_for()
        page.wait_for_selector("#drawer-root .scrim:not([hidden])", timeout=10000)


def shoot(browser, app, view, width, theme, base, mc_base, desc, out: Path, errors: list) -> str:
    name = f"{app}-{view}-{theme}-{width}.png"
    w, h = SIZES[width]
    ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=theme, reduced_motion="reduce", device_scale_factor=1)
    ctx.add_init_script(f"try {{ localStorage.setItem('miniview.theme', '{theme}'); localStorage.setItem('mc-theme', '{theme}'); }} catch (e) {{}}")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: errors.append(f"{name}: pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"{name}: console: {m.text[:160]}") if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("response", lambda r: errors.append(f"{name}: http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
    try:
        (take_observatory if app == "observatory" else take_control)(page, view, base, mc_base, desc)
        page.add_style_tag(content=FREEZE)
        settle(page)
        # a picture is taken once the page has stopped changing under it (the fake robot's map fills in over a second or two)
        shot = page.screenshot()
        for _ in range(10):
            page.wait_for_timeout(500)
            again = page.screenshot()
            if again == shot:
                break
            shot = again
        else:
            errors.append(f"{name}: still changing after 5 s; the last picture is kept")
        (out / name).write_bytes(shot)
    finally:
        ctx.close()
    return name


# ---- the guides' walkthroughs (docs/guides): one PNG per step, dark, 1440 wide, in --out/guides/<app>/ -----------------------------------------
# A walkthrough is one page driven in order, because a step (a run under way, a STOP) needs the one before it; --only filters what is written,
# never what is driven. The names are the guides' own: a guide links NN-name.png, so a name is never reused for another view.

GUIDE_SHOTS = {
    "mission-control": ["01-robot-list", "02-robot-readiness", "03-robot-body", "04-robot-modules", "05-robot-settings", "06-site-and-area", "07-goal-form",
                        "08-run-under-way", "09-run-reached", "10-stop"],
    "observatory": ["01-runs", "02-run-3d", "03-belief-truth", "04-timeline-scrub", "05-map-frame", "06-alarms-decisions", "07-eye", "08-signals", "09-watch",
                    "10-explore", "11-shared-address"],
}
GUIDE_LIMITS = [
    "mission-control 08-10: the fake robot writes no Observatory run (its run_key is None), so the run's Watch link is shown disabled; the link itself is not shown live",
    "observatory: a live (still recording) run, a real robot's run, Export video (needs the render service) and comparing runs are not shown",
]


def guide_control(page, snap, mc_base, desc):
    ready = lambda: page.wait_for_function("window.__mc && window.__mc.ready", timeout=30000)  # noqa: E731
    page.goto(f"{mc_base}/")
    ready()
    page.wait_for_function("document.querySelector('#robot-fake-1')?.getAttribute('data-online') === 'true'", timeout=15000)
    snap("01-robot-list")

    page.goto(f"{mc_base}/#robot/duck-1")
    ready()
    page.wait_for_function("!document.getElementById('robot-page').hidden && document.querySelectorAll('#rp-parts [data-part]').length === 3", timeout=15000)
    snap("02-robot-readiness")
    page.click("#tab-body")
    page.wait_for_function("!!window.__mc.body", timeout=30000)
    if desc:
        page.wait_for_function(f"window.__mc.body.state() && window.__mc.body.state().meshes === {desc['n_visuals']}", timeout=60000)
    snap("03-robot-body")
    page.click("#tab-modules")
    page.wait_for_selector("#rp-modules-body [data-plugin]", timeout=15000)
    snap("04-robot-modules")
    page.click("#tab-settings")
    page.wait_for_selector("#st-blocks [data-block]", timeout=15000)
    # the notice at the top names this run's scratch folder; the picture says <scratch> instead of a path on the machine that took it
    scrub = "(() => { const w = document.createTreeWalker(document.getElementById('rp-settings-body'), NodeFilter.SHOW_TEXT); for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeValue = n.nodeValue.replace(/\\/[^ ]*look-shots-[a-z0-9_]+/g, '<scratch>'); })()"
    snap("05-robot-settings", before=lambda: page.evaluate(scrub))
    page.click("#rp-back")
    page.wait_for_function("document.getElementById('robot-page').hidden", timeout=10000)

    page.click("#robot-duck-1")
    page.click("#maphint ~ details summary, details summary:has-text('New site')")
    page.fill("#site-name", "Test flat")
    page.fill("#site-kind", "apartment")
    page.click("#site-create")
    page.wait_for_selector("#site-sel option:has-text('Test flat')", state="attached", timeout=10000)
    page.select_option("#site-sel", index=1)
    page.wait_for_function("document.querySelector('#area-draw') && !document.querySelector('#area-list').textContent.includes('Pick a site')", timeout=10000)
    page.click("#area-draw")
    box = page.locator("#map").bounding_box()
    # the map is 8 m wide on the fake's world; corners of a "Kitchen" at the right of the dock
    for fx, fy in ((0.60, 0.25), (0.85, 0.25), (0.85, 0.55), (0.60, 0.55)):
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
    page.fill("#area-name", "Kitchen")
    page.fill("#area-type", "kitchen")
    snap("06-site-and-area", before=lambda: page.locator("#area-draft").scroll_into_view_if_needed())
    page.click("#area-save")
    page.wait_for_selector("#area-list [data-area]", timeout=10000)

    page.mouse.click(box["x"] + box["width"] * 0.74, box["y"] + box["height"] * 0.66)
    page.wait_for_function("document.getElementById('g-x').value !== ''", timeout=5000)
    snap("07-goal-form")
    page.click("#g-run")
    page.wait_for_selector("#run-list .run", timeout=10000)
    page.wait_for_function("(() => { const t = document.querySelector('#run-progress'); return !!t && /elapsed\\s*[1-9]/.test(t.textContent); })()", timeout=15000)
    snap("08-run-under-way", quick=True)
    page.wait_for_function("/reached|stalled|timeout|failed|cancelled/.test(document.querySelector('#run-state')?.textContent || '')", timeout=60000)
    snap("09-run-reached")

    page.mouse.click(box["x"] + box["width"] * 0.12, box["y"] + box["height"] * 0.15)
    page.click("#g-run")
    page.wait_for_function("/Run #2/.test(document.querySelector('#run-detail')?.textContent || '') && /running/.test(document.querySelector('#run-state')?.textContent || '')", timeout=15000)
    page.wait_for_function("(() => { const t = document.querySelector('#run-progress'); return !!t && /elapsed\\s*[1-9]/.test(t.textContent); })()", timeout=15000)
    page.click("#stop-robot")
    page.wait_for_function("/cancelled|stopped|interrupted/.test(document.querySelector('#run-state')?.textContent || '')", timeout=15000)
    snap("10-stop")


def guide_observatory(page, snap, base, desc):
    # the page keeps its view, tab and frame across a change of the URL's hash, so each step starts from a blank document, as a reader opening the link would
    def run(view, frame="world", path="/web/three/"):
        page.goto("about:blank")
        obs_run(page, base, view, frame, path)

    go_obs(page, base)
    page.wait_for_selector("#scenespage tr[data-run]", timeout=15000)
    snap("01-runs")
    run("3d")
    snap("02-run-3d")
    run("top")
    snap("03-belief-truth", before=lambda: page.locator("#inspBody").get_by_text("Error", exact=True).first.scroll_into_view_if_needed())
    run("3d")
    page.evaluate("window.miniview.setTime(1.4)")
    snap("04-timeline-scrub")
    run("top", "map")
    snap("05-map-frame")
    run("3d")
    page.evaluate("window.miniview.setTime(2.4)")
    page.click("#tabDecided")
    page.locator("#alane .mk.al").nth(1).click()
    snap("06-alarms-decisions")
    run("eye")
    snap("07-eye")
    page.click("#sigBtn")
    page.wait_for_selector("#sigview:not([hidden])", timeout=10000)
    snap("08-signals")
    run("watch", path=f"/watch/{KEY}")
    snap("09-watch")
    if desc:
        run("3d")
        page.evaluate("window.__ready = false")
        page.evaluate("window.miniview.explore()")
        page.wait_for_function("window.__ready === true", timeout=30000)
        page.wait_for_function("(() => { const s = window.miniview.exploreState(); return !!s && s.shown !== false; })()", timeout=30000)
        snap("10-explore")
    page.goto(f"{base}/control/")
    page.wait_for_function("window.__mc && window.__mc.ready", timeout=30000)
    snap("11-shared-address")


def take_guides(browser, which, base, mc_base, desc, out: Path, only: str | None, errors: list, taken: list) -> None:
    for app, flow, url in (("mission-control", guide_control, mc_base), ("observatory", guide_observatory, base)):
        if which and app not in which:
            continue
        folder = out / "guides" / app
        folder.mkdir(parents=True, exist_ok=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", reduced_motion="reduce", device_scale_factor=1)
        ctx.add_init_script("try { localStorage.setItem('miniview.theme', 'dark'); localStorage.setItem('rl.theme', 'dark'); localStorage.setItem('mc-theme', 'dark'); } catch (e) {}")
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda e, a=app: errors.append(f"guide {a}: pageerror: {e}"))
        page.on("console", lambda m, a=app: errors.append(f"guide {a}: console: {m.text[:160]}") if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.on("response", lambda r, a=app: errors.append(f"guide {a}: http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)

        def snap(name, before=None, quick=False, a=app, folder=folder):
            if only and not any(o in f"{a}-{name}" for o in only.split(",")):
                return
            if before:
                before()
            page.add_style_tag(content=FREEZE)
            settle(page, 50 if quick else 250)
            shot = page.screenshot()
            for _ in range(0 if quick else 10):
                page.wait_for_timeout(500)
                again = page.screenshot()
                if again == shot:
                    break
                shot = again
            else:
                if not quick:
                    errors.append(f"guide {a}/{name}: still changing after 5 s; the last picture is kept")
            (folder / f"{name}.png").write_bytes(shot)
            taken.append(f"guides/{a}/{name}.png")
            print("took", taken[-1], flush=True)

        try:
            flow(page, snap, url, desc)
        finally:
            ctx.close()


def take_all(out: Path, only: str | None, skip_light_wide_flat: bool, html_index: bool, guides: str | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="look-shots-", dir=CACHE))
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["OBSERVATORY_ROBOTS"] = str(REPO / "robots")
    duck = REPO / "robots" / "duck"
    os.environ["OBSERVATORY_INDEX"] = str(tmp / "index.sqlite")

    from playwright.sync_api import sync_playwright
    from common import FAKE_FILE, installation_file
    from mission_control import description
    from mission_control.api import serve
    from mission_control.core import MissionControl
    from mission_control.robots import RobotConfig
    from observatory import kinematics
    from observatory.server import make_server
    from observatory.shots import launch
    from runfile import installation
    from runfile.catalog import Catalog

    meshes_built = (duck / "robot.urdf").is_file() and any((duck / "meshes").glob("*.stl"))
    joints = [j.name for j in kinematics.load(duck / "robot.urdf").joints.values() if j.type != "fixed"] if meshes_built else []
    if not meshes_built:
        print(f"WARNING: no duck meshes in {duck}: the body and joint views differ from a set taken with them", flush=True)
    data = tmp / "data"
    build_data(data, joints)

    desc = None
    skipped, errors, taken = [], [], []
    os.environ[installation.ENV] = str(installation_file(tmp / "installation.json", {"duck": {"variant": "sim"}}, state=str(tmp / "inst-state")))
    mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}), RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
    control = obs = None
    try:
        control = serve(mc, "127.0.0.1", 0)
        threading.Thread(target=control.serve_forever, daemon=True).start()
        mc.start()
        os.environ["OBSERVATORY_CONTROL"] = f"http://127.0.0.1:{control.server_address[1]}"
        obs = make_server(Catalog(data, index=tmp / "catalog.sqlite"), "127.0.0.1", 0, follow=False)
        threading.Thread(target=obs.serve_forever, daemon=True).start()
        base, mc_base = f"http://127.0.0.1:{obs.server_address[1]}", os.environ["OBSERVATORY_CONTROL"]
        print(f"observatory {base}  mission control {mc_base}  (temp {tmp})")
        if meshes_built:
            d = description.describe_folder(duck, "duck-1")
            desc = None if d["meshes_missing"] else {"n_visuals": sum(len(l["visuals"]) for l in d["links"])}
        if desc is None:
            skipped.append("control-body and observatory-explore: the duck's meshes are not built (robots/duck/meshes; `make robots`), so no body to draw")

        with sync_playwright() as p:
            browser = launch(p)
            try:
                if guides is not None:
                    take_guides(browser, [g for g in guides.split(",") if g], base, mc_base, desc, out, only, errors, taken)
                for app, view, widths in ([] if guides is not None else VIEWS):
                    for width in widths:
                        for theme in THEMES:
                            name = f"{app}-{view}-{theme}-{width}.png"
                            if only and not any(o in name for o in only.split(",")):
                                continue
                            if skip_light_wide_flat and theme == "light" and width == 1440 and view not in ("3d", "map", "eye", "chase", "watch", "body", "explore"):
                                skipped.append(f"{name}: dropped by --slim")
                                continue
                            if desc is None and (view == "body" or view == "explore"):
                                continue
                            taken.append(shoot(browser, app, view, width, theme, base, mc_base, desc, out, errors))
                            print("took", taken[-1], flush=True)
            finally:
                browser.close()
    finally:
        for srv in (obs, control):
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        mc.close()
    rev = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    if guides is not None:
        print(f"{len(taken)} guide shots in {out / 'guides'}; {len(errors)} page errors")
        for e in errors:
            print("  page error:", e)
        for s in GUIDE_LIMITS:
            print("  not shown:", s)
        return 1 if errors else 0
    (out / "shots.json").write_text(json.dumps({"commit": rev, "taken": taken, "skipped": skipped, "not_covered": NOT_COVERED, "page_errors": errors}, indent=1))
    if html_index:
        write_index(out, taken)
    print(f"{len(taken)} shots in {out}; {len(skipped)} skipped; {len(errors)} page errors")
    for e in errors:
        print("  page error:", e)
    for s in skipped:
        print("  skipped:", s)
    return 0


# ---- the pages ------------------------------------------------------------------------------------------------------------------------

CSS = ("body{font:14px system-ui,sans-serif;margin:16px;background:#fafafa;color:#111}h1{font-size:18px}h2{font-size:14px;margin:24px 0 6px;font-family:monospace}"
       "img{max-width:100%;border:1px solid #888;display:block}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.one{max-width:1500px}"
       ".miss{color:#a00}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}")


def names_in(d: Path) -> list:
    return sorted(p.name for p in d.glob("*.png"))


def write_index(out: Path, names: list) -> None:
    body = "".join(f'<section><h2>{html.escape(n)}</h2><img src="{html.escape(n)}" alt="{html.escape(n)}" loading="lazy"></section>' for n in names)
    (out / "index.html").write_text(f'<!doctype html><meta charset="utf-8"><title>look shots</title><style>{CSS}</style><h1>Screenshots ({len(names)})</h1>'
                                    f'<div class="grid">{body}</div>')


def compare(before: Path, after: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    b, a = set(names_in(before)), set(names_in(after))
    rows, miss = [], []
    for n in sorted(a | b):
        if n in a and n in b:
            for side, d in (("before", before), ("after", after)):
                shutil.copy(d / n, out / f"{side}-{n}")
            rows.append(f'<section><h2>{html.escape(n)}</h2><div class="pair"><div>before<img src="before-{html.escape(n)}" loading="lazy"></div>'
                        f'<div>after<img src="after-{html.escape(n)}" loading="lazy"></div></div></section>')
        else:
            miss.append(f'<li class="miss">{html.escape(n)}: only in {"before" if n in b else "after"}</li>')
    (out / "index.html").write_text(f'<!doctype html><meta charset="utf-8"><title>before and after</title><style>{CSS}</style>'
                                    f'<h1>Before and after ({len(a & b)} paired)</h1>{"<h2>Not paired</h2><ul>" + "".join(miss) + "</ul>" if miss else ""}{"".join(rows)}')
    print(f"{len(a & b)} paired, {len(miss)} not paired: {out / 'index.html'}")
    return 0


def fixture_data(dest: Path) -> int:
    from observatory import kinematics

    duck = REPO / "robots" / "duck"
    joints = [j.name for j in kinematics.load(duck / "robot.urdf").joints.values() if j.type != "fixed"] if (duck / "robot.urdf").is_file() else []
    tmp = Path(tempfile.mkdtemp(prefix="look-shots-", dir=CACHE))
    atexit.register(shutil.rmtree, tmp, True)
    os.environ["OBSERVATORY_INDEX"] = str(tmp / "index.sqlite")
    build_data(dest, joints)
    print(f"fixture data in {dest}: runs {KEY} and duck/room/shots0, scene {SCENE_ID}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="the folder the pictures go to (required except with --fixture-data)")
    ap.add_argument("--html", action="store_true", help="also write index.html in --out")
    ap.add_argument("--only", help="take only the shots whose name contains this text (a comma-separated list: any of them)")
    ap.add_argument("--slim", action="store_true", help="drop the 1440 light shots of the flat (non-3D) views, to keep the folder small")
    ap.add_argument("--guides", nargs="?", const="mission-control,observatory", metavar="APPS",
                    help="take the guides' walkthrough shots (docs/guides) into --out/guides/<app>/, dark, 1440 wide; APPS is a comma list of mission-control, observatory (default both); --only filters by <app>-<step>")
    ap.add_argument("--fixture-data", type=Path, metavar="DIR", help="write the fixture data folder (a duck run and a scene) into DIR and stop: a scratch Observatory can serve it (docs/guides/observatory.md)")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), type=Path)
    a = ap.parse_args()
    if not a.out and not a.fixture_data:
        ap.error("--out is required")
    if a.compare:
        return compare(a.compare[0], a.compare[1], a.out)
    if a.fixture_data:
        return fixture_data(a.fixture_data)
    return take_all(a.out, a.only, a.slim, a.html, a.guides)


if __name__ == "__main__":
    sys.exit(main())
