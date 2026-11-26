"""The duck's real body on Mission Control's robot page (phase 5 unit A5), in headless Chromium: the real server over the duck's built
description (robots/duck/robot.urdf and its meshes/, which `make robots` writes). Every link that has a visual is drawn, every mesh the
description names is loaded once and none fails, the page logs no error; then an alarm naming a real joint turns that joint's meshes the
error colour and the not-ok list names it. Pictures at phone and desktop width, dark and light.

The built meshes are not in git. The folder is MC_ROBOT_FOLDER, else robots/duck in this checkout, else in the main checkout this one is a
worktree of; the installation named is this test's own (this machine's is never read). With no built meshes it prints SKIP and exits 0.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def built_folder() -> Path | None:
    candidates = []
    if os.environ.get("MC_ROBOT_FOLDER"):
        candidates.append(Path(os.environ["MC_ROBOT_FOLDER"]))
    candidates.append(REPO / "robots" / "duck")
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--git-common-dir"], capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            candidates.append((REPO / common).resolve().parent / "robots" / "duck")
    except (OSError, subprocess.SubprocessError):
        pass
    for c in candidates:
        if (c / "registration.json").is_file() and (c / "robot.urdf").is_file() and any((c / "meshes").glob("*.stl")):
            return c
    return None


FOLDER = built_folder()
if FOLDER is None:
    print("SKIP test_body_duck_page: no built duck meshes (robots/duck/meshes; `make robots` builds them, or name a robot folder in MC_ROBOT_FOLDER)")
    sys.exit(0)

from playwright.sync_api import sync_playwright

from common import check, finish, FAKE_FILE
from pageboot import boot

from observatory.shots import launch
from mission_control import description
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

desc = description.describe_folder(FOLDER, "duck-1")
if desc["meshes_missing"]:
    print(f"SKIP test_body_duck_page: {FOLDER} has {len(desc['meshes_missing'])} of its meshes missing ({desc['meshes_missing'][:3]}...); run `make robots`")
    sys.exit(0)

tmp = Path(tempfile.mkdtemp(prefix="mc-body-duck-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)

inst = tmp / "installation.json"
inst.write_text(json.dumps({"installation": 1, "robots": {"duck": {"variant": "sim", "registration": str(FOLDER / "registration.json")}}}))
os.environ[installation.ENV] = str(inst)
mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}), RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()

with_visuals = [l["name"] for l in desc["links"] if l["visuals"]]
n_visuals = sum(len(l["visuals"]) for l in desc["links"])
n_files = len({v["url"] for l in desc["links"] for v in l["visuals"]})
moving = [j for j in desc["joints"] if j["type"] != "fixed"]
target = next(j for j in moving if any(l["name"] == j["child"] and l["visuals"] for l in desc["links"]))
other = next(j for j in moving if j is not target and j["child"] in with_visuals)
print(f"duck: {len(desc['links'])} links, {len(with_visuals)} with visuals, {n_visuals} visuals, {n_files} mesh files, {len(moving)} moving joints; alarm on {target['name']}")

errors, requests, failed, meshes_ok = [], [], [], []

with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
    page.on("requestfailed", lambda r: failed.append(f"failed: {r.url} {r.failure}"))
    page.on("response", lambda r: (failed.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else meshes_ok.append(r.url) if "/meshes/" in r.url and r.status == 200 else None))
    page.on("request", lambda r: requests.append(r.url))
    css_hex = lambda name: page.evaluate("""(n) => { const e = document.createElement('i'); e.style.color = `var(--${n})`; document.body.append(e);
        const c = getComputedStyle(e).color; e.remove(); return '#' + c.match(/\\d+/g).slice(0, 3).map((x) => (+x).toString(16).padStart(2, '0')).join(''); }""", name)

    def wait(js, timeout=30000, arg=None):
        try:
            page.wait_for_function(js, arg=arg, timeout=timeout)
        except Exception:
            check(f"waited for {js[:90]}", False, "timed out")

    body = lambda: page.evaluate("window.__mc.body ? window.__mc.body.state() : {}") or {}
    try:
        boot(page, BASE + "/#robot/duck-1/body", f"window.__mc && window.__mc.body && window.__mc.body.state() && window.__mc.body.state().meshes === {n_visuals}")
        page.wait_for_timeout(500)
        b = body()
        check("every link with a visual is drawn", b.get("drawn") == len(with_visuals), (b.get("drawn"), len(with_visuals)))
        check("every visual of the description is a mesh in the scene", b.get("meshes") == n_visuals, (b.get("meshes"), n_visuals))
        check("each mesh file is fetched once and answered 200, none failed", len(meshes_ok) == n_files and len(set(meshes_ok)) == n_files and failed == [], (len(meshes_ok), n_files, failed))
        size = b.get("size") or [0, 0, 0]
        check("the body is a duck's size in metres, not millimetres or a speck (a hand to a metre in each direction)", all(0.02 < s < 1.0 for s in size) and max(size) > 0.1, size)
        check("the canvas is there with real size", page.evaluate("(document.querySelector('#rp-body canvas')?.getBoundingClientRect().height || 0) > 150"))
        check("no sideways scrolling on the robot page with the real body", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

        err, warn = css_hex("status-error"), css_hex("status-warn")
        own = {j["name"]: (b["joints"].get(j["name"]) or {}).get("color") for j in moving if j["child"] in with_visuals}
        check("with no alarm every moving joint is ok and keeps its mesh colour (not the error or warn colour)",
              all((b["joints"].get(k) or {}).get("state") == "ok" for k in own) and err not in own.values() and warn not in own.values(), own)
        page.screenshot(path=str(SHOTS / "a5-body-phone-dark-ok.png"), full_page=True)

        mc.bus.emit("anomaly", robot="duck-1", goal_run=1, watch=None, anomaly={"n": 1, "t": 1.0, "anomaly": "joint_overload", "source": "robot", "module": "body",
                    "severity": "major", "detector": "d", "summary": "overload for the test", "values": {"joint": target["name"]}})
        wait("(j) => window.__mc.body.state().joints[j] && window.__mc.body.state().joints[j].state === 'error'", arg=target["name"])
        b = body()
        check("an alarm naming a real joint turns it the error colour, the other joints stay as they were",
              b["joints"][target["name"]] == {"state": "error", "color": err} and b["joints"][other["name"]] == {"state": "ok", "color": own[other["name"]]}, b["joints"][target["name"]])
        check("and the page names it in words: the joint, its state, the alarm", any(target["name"] in t and "error" in t and "joint_overload" in t for t in page.locator("#rp-body-joints li").all_inner_texts()),
              page.locator("#rp-body-joints li").all_inner_texts())
        page.screenshot(path=str(SHOTS / "a5-body-phone-dark.png"), full_page=True)
        page.locator("#rp-body").screenshot(path=str(SHOTS / "a5-body-section-phone-dark.png"))

        page.emulate_media(color_scheme="light")
        wait("(arg) => window.__mc.body.state().joints[arg[0]].color === arg[1]", arg=[target["name"], css_hex("status-error")])
        page.wait_for_timeout(300)
        check("in the light theme the joint takes the light error colour", css_hex("status-error") != err, (css_hex("status-error"), err))
        page.screenshot(path=str(SHOTS / "a5-body-phone-light.png"), full_page=True)
        page.screenshot(path=str(SHOTS / "a5-body-section-phone-light.png"), clip=page.locator("#rp-body").bounding_box())

        page.set_viewport_size({"width": 1500, "height": 900})
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / "a5-body-desktop-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")
        wait("(arg) => window.__mc.body.state().joints[arg[0]].color === arg[1]", arg=[target["name"], err])
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / "a5-body-desktop-dark.png"), full_page=True)
        box = page.evaluate("(() => { const r = document.querySelector('#rp-body canvas').getBoundingClientRect(); return [r.width, r.height]; })()")
        check("desktop: the canvas fills its section and the page does not scroll sideways", box[0] > 300 and box[1] > 200 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), box)
        check("no failed request in the whole session", failed == [], failed)
        check("no script error and no console error in the whole session", errors == [], errors)
    finally:
        browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_body_duck_page")
