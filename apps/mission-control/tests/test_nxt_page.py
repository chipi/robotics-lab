"""The NXT on Mission Control's robot page (phase 5 item 4d, unit D4), in headless Chromium: the registered NXT (robots/nxt-shooterbot) behind
a pointer robot file, the real server, nxt-web --fake as its connector (the installation's `connections.nxt-web` names its address; never a
real brick: --fake, a scratch data folder, a free loopback port). Parts, Body (the built Shooterbot description: every mesh loaded, none
failed), Modules and Settings open for it, in the sim variant and in the real one, and the page logs no error.

The built meshes are not in git (`make robots-lego` writes them; it needs the LDraw library in ~/opt/ldraw). The folder is MC_ROBOT_FOLDER,
else robots/nxt-shooterbot in this checkout, else in the main checkout this one is a worktree of; with no built meshes it prints SKIP and
exits 0. The installation named is this test's own (this machine's is never read).

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
import json
import os
import shutil
import socket
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
    candidates.append(REPO / "robots" / "nxt-shooterbot")
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--git-common-dir"], capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            candidates.append((REPO / common).resolve().parent / "robots" / "nxt-shooterbot")
    except (OSError, subprocess.SubprocessError):
        pass
    for c in candidates:
        if (c / "registration.json").is_file() and (c / "robot.urdf").is_file() and any((c / "meshes").glob("*.stl")):
            return c
    return None


FOLDER = built_folder()
if FOLDER is None:
    print("SKIP test_nxt_page: no built NXT meshes (robots/nxt-shooterbot/meshes; `make robots-lego` builds them, or name a robot folder in MC_ROBOT_FOLDER)")
    sys.exit(0)

from playwright.sync_api import sync_playwright

from common import FAKE_FILE, check, finish

from observatory.shots import launch
from mission_control import description
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

desc = description.describe_folder(FOLDER, "nxt-1")
if desc["meshes_missing"]:
    print(f"SKIP test_nxt_page: {FOLDER} has {len(desc['meshes_missing'])} of its meshes missing ({desc['meshes_missing'][:3]}...); run `make robots-lego`")
    sys.exit(0)

NXT_WEB = os.environ.get("NXT_WEB", str(REPO / "apps" / "nxt-web" / ".venv" / "bin" / "nxt-web"))
if not Path(NXT_WEB).exists():
    print(f"FAIL test_nxt_page: {NXT_WEB} is missing (make nxt-sync)")
    sys.exit(1)

tmp = Path(tempfile.mkdtemp(prefix="mc-nxt-page-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
NXT_URL = f"http://127.0.0.1:{PORT}"
proc = subprocess.Popen([NXT_WEB, "--fake", "--host", "127.0.0.1", "--port", str(PORT), "--config", str(tmp / "config.json")],
                        env=dict(os.environ, NXT_LAB_DATA=str(tmp), MINIVIEW_DATA=str(tmp / "miniview")), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def stop_nxt_web():
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


atexit.register(stop_nxt_web)

POINTER = json.loads((REPO / "apps" / "mission-control" / "robots.nxt-registered" / "nxt-1.json").read_text())
with_visuals = [l["name"] for l in desc["links"] if l["visuals"]]
n_visuals = sum(len(l["visuals"]) for l in desc["links"])
n_files = len({v["url"] for l in desc["links"] for v in l["visuals"]})
print(f"nxt: {len(desc['links'])} links, {len(with_visuals)} with visuals, {n_visuals} visuals, {n_files} mesh files, {len(desc['joints'])} joints; nxt-web --fake at {NXT_URL}")

errors, failed, meshes_ok = [], [], []
PARTS = {"sim": ["nxt-web"], "real": ["nxt-web", "robotd-lite"]}
SENSORS = {"sim": ["ultrasonic"], "real": ["ultrasonic", "colour"]}

with sync_playwright() as p:
    browser = launch(p)
    try:
        for n, variant in enumerate(("sim", "real")):
            inst = tmp / f"installation-{variant}.json"
            inst.write_text(json.dumps({"installation": 1, "robots": {"nxt-shooterbot": {
                "registration": str(FOLDER / "registration.json"), "variant": variant, "placement": "workstation", "connections": {"nxt-web": NXT_URL}}}}))
            os.environ[installation.ENV] = str(inst)
            mc = MissionControl([RobotConfig(POINTER), RobotConfig(FAKE_FILE)], state_dir=tmp / f"state-{variant}")
            srv = serve(mc, "127.0.0.1", 0)
            BASE = f"http://127.0.0.1:{srv.server_address[1]}"
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            mc.start()
            ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark")
            page = ctx.new_page()
            page.set_default_timeout(15000)
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            page.on("console", lambda m: errors.append("console: " + m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
            page.on("requestfailed", lambda r: failed.append(f"failed: {r.url} {r.failure}"))
            page.on("response", lambda r: (failed.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else meshes_ok.append(r.url) if "/meshes/" in r.url and r.status == 200 else None))

            def wait(js, timeout=30000, arg=None):
                try:
                    page.wait_for_function(js, arg=arg, timeout=timeout)
                except Exception:
                    check(f"[{variant}] waited for {js[:90]}", False, "timed out")

            def tab(name):
                page.click(f"#tab-{name}")
                wait(f"!document.getElementById('rp-{name}').hidden")

            try:
                # --- the robot is on the page and the page names it ------------------------------------------------------------------
                page.goto(BASE + "/")
                wait("window.__mc && window.__mc.ready")
                check(f"[{variant}] the NXT has a card with a link to its page", page.locator("a[data-robot='nxt-1']").count() == 1)
                page.click("a[data-robot='nxt-1']")
                wait("!document.getElementById('robot-page').hidden")
                wait("document.querySelectorAll('#rp-parts [data-part]').length > 0")
                check(f"[{variant}] the page names the robot and its variant", "NXT Shooterbot" in page.locator("#rp-title").inner_text() and variant in page.locator("#rp-facts").inner_text(),
                      (page.locator("#rp-title").inner_text(), page.locator("#rp-facts").inner_text()))
                check(f"[{variant}] STOP names the NXT", page.locator("#stop-robot").inner_text() == "STOP nxt-1")

                # --- Parts: the profile's subsystems, which differ by variant ---------------------------------------------------------
                parts = page.eval_on_selector_all("#rp-parts [data-part]", "(els) => els.map((e) => e.dataset.part)")
                check(f"[{variant}] Parts lists the profile's subsystems for this variant", parts == PARTS[variant], parts)
                check(f"[{variant}] Parts has no 'no profile' or 'no parts' message", "No profile" not in page.locator("#rp-parts-body").inner_text() and "lists no parts" not in page.locator("#rp-parts-body").inner_text())

                # --- Body: the built Shooterbot description --------------------------------------------------------------------------
                tab("body")
                wait(f"window.__mc && window.__mc.body && window.__mc.body.state() && window.__mc.body.state().meshes === {n_visuals}")
                page.wait_for_timeout(500)
                b = page.evaluate("window.__mc.body.state()")
                check(f"[{variant}] every link with a visual is drawn, every visual is a mesh in the scene", b.get("drawn") == len(with_visuals) and b.get("meshes") == n_visuals, (b.get("drawn"), b.get("meshes"), n_visuals))
                size = b.get("size") or [0, 0, 0]
                check(f"[{variant}] the body is a small tracked robot's size in metres (about 0.18 x 0.18 x 0.10)", 0.1 < max(size) < 0.4 and min(size) > 0.02, size)
                check(f"[{variant}] the canvas is there with real size", page.evaluate("(document.querySelector('#rp-body canvas')?.getBoundingClientRect().height || 0) > 150"))
                check(f"[{variant}] no sideways scrolling with the real body", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
                joints = page.eval_on_selector_all("#rp-joints-body [data-joint]", "(els) => els.map((e) => [e.dataset.joint, e.dataset.state, e.querySelectorAll('td')[1].textContent])")
                check(f"[{variant}] the joint table names the description's joints (tracks, idlers, shooter), none with an angle: the NXT reports none",
                      [j[0] for j in joints] == [j["name"] for j in desc["joints"]] and all(j[1] == "ok" and j[2] == "-" for j in joints), joints)
                page.screenshot(path=str(SHOTS / f"d4-body-phone-dark-{variant}.png"), full_page=True)

                # --- Modules: the one plugin, a label, with the two numbers ------------------------------------------------------------
                tab("modules")
                wait("document.querySelectorAll('#rp-modules-body [data-plugin]').length > 0")
                mods = page.eval_on_selector_all("#rp-modules-body [data-plugin]", "(els) => els.map((e) => [e.dataset.plugin, e.innerText])")
                check(f"[{variant}] Modules lists the one plugin, nxt-tracks@1, for locomotion", [m[0] for m in mods] == ["locomotion"] and "nxt-tracks@1" in mods[0][1], mods)
                check(f"[{variant}] it shows the two speeds from the profile", all(s in mods[0][1] for s in ("cruise_mps", "0.3", "yaw_max_rad_s", "1.5")), mods[0][1])
                page.screenshot(path=str(SHOTS / f"d4-modules-phone-dark-{variant}.png"), full_page=True)

                # --- Settings: the profile and its blocks -------------------------------------------------------------------------------
                tab("settings")
                wait("!!document.querySelector('#st-blocks [data-block]')")
                blocks = page.eval_on_selector_all("#st-blocks [data-block]", "(els) => els.map((e) => e.dataset.block)")
                check(f"[{variant}] Settings lists the profile's blocks, including locomotion with the two numbers", "locomotion" in blocks and "footprint" in blocks, blocks)
                page.click("#st-blocks [data-block='locomotion']")
                wait("document.querySelector('#st-pane h2')?.textContent === 'locomotion'")
                pane = page.locator("#st-pane").inner_text()
                check(f"[{variant}] its pane shows cruise_mps and yaw_max_rad_s with their values", all(s in pane for s in ("cruise_mps", "0.3", "yaw_max_rad_s", "1.5")), pane[:300])
                check(f"[{variant}] no sideways scrolling in Settings", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
                page.screenshot(path=str(SHOTS / f"d4-settings-phone-dark-{variant}.png"), full_page=True)

                # --- what the server says for the same robot ------------------------------------------------------------------------------
                api = lambda path: json.loads(page.evaluate("(p) => fetch('/api/v1' + p).then((r) => r.text())", path))
                wait("() => (window.__mc.S.robots.find((x) => x.id === 'nxt-1') || {}).online === true")
                r = api("/robots/nxt-1")["robot"]
                check(f"[{variant}] the robot's sensors are the variant's", [x["id"] for x in r["capabilities"]["sensors"]] == SENSORS[variant], r["capabilities"]["sensors"])
                prof = api("/robots/nxt-1/profile")["profile"]
                check(f"[{variant}] the profile view runs the variant and the registered file", prof["variant"] == variant and prof["running"]["path"].endswith("robots/nxt-shooterbot/profile.json"), (prof["variant"], prof["running"]["path"]))
                check(f"[{variant}] the address is the installation's connection: the robot is online through nxt-web --fake at {NXT_URL}, which the code names nowhere",
                      r["online"] is True and NXT_URL != "http://127.0.0.1:8000", r["online"])
            finally:
                ctx.close()
                srv.shutdown()
                srv.server_close()
                mc.close()
        check("each mesh file is fetched and answered 200, none failed, in both variants", len(meshes_ok) >= 2 * n_files and failed == [], (len(meshes_ok), n_files, failed))
        check("no script error and no console error in the whole session", errors == [], errors)
    finally:
        browser.close()
finish("test_nxt_page")
