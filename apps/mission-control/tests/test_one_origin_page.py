"""One origin (RFC-0024 step 3, phase 5 item 4c unit C1) in headless Chromium: Mission Control's page, API and event stream through the Observatory's
address (/control/), beside the Observatory's own page. The real two servers, the Observatory told where Mission Control is (OBSERVATORY_CONTROL);
Mission Control asks for a token on actions only (question 4). What is checked: the page loads from /control/ with its relative addresses (style, scripts,
API, the body's script), its live stream comes through, STOP works with no token, an action asks for one and works with it, the body mounts, the
Observatory's 3D page loads from the same address, and neither page logs an error or fails a request.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
import json
import os
import shutil
import struct
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import DUCK_REGISTRATION, FAKE_FILE, check, finish, installation_file

from observatory.server import make_server
from observatory.shots import launch
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation
from runfile.catalog import Catalog

tmp = Path(tempfile.mkdtemp(prefix="mc-one-origin-"))
atexit.register(shutil.rmtree, tmp, True)
SHOTS = Path(os.environ.get("MC_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)


def box_stl(sx, sy, sz) -> bytes:
    v = [(x, y, z) for x in (-sx / 2, sx / 2) for y in (-sy / 2, sy / 2) for z in (0.0, sz)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    out = bytearray(80) + struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + struct.pack("<H", 0)
    return bytes(out)


reg = tmp / "duck-folder"
(reg / "meshes").mkdir(parents=True)
shutil.copy(DUCK_REGISTRATION, reg / "registration.json")
shutil.copy(DUCK_REGISTRATION.parent / "profile.json", reg / "profile.json")
(reg / "robot.urdf").write_text("""<robot name="standin">
  <link name="trunk"><visual><geometry><mesh filename="meshes/trunk.stl"/></geometry></visual></link>
  <link name="thigh"><visual><geometry><mesh filename="meshes/thigh.stl"/></geometry></visual></link>
  <joint name="left_hip_pitch" type="revolute"><parent link="trunk"/><child link="thigh"/><origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/>
    <limit lower="-1.5" upper="1.5"/></joint>
</robot>""")
(reg / "robot.json").write_text('{"label": "Stand-in", "stand_z": 0.05}')
(reg / "meshes" / "trunk.stl").write_bytes(box_stl(0.12, 0.12, 0.1))
(reg / "meshes" / "thigh.stl").write_bytes(box_stl(0.03, 0.03, 0.15))
os.environ[installation.ENV] = str(installation_file(tmp / "installation.json", {"duck": {"variant": "sim", "registration": str(reg / "registration.json")}}))

mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}), RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
_, TOKEN = mc.tokens.create("page")
control = serve(mc, "127.0.0.1", 0, require_tokens="actions")
threading.Thread(target=control.serve_forever, daemon=True).start()
mc.start()
os.environ["OBSERVATORY_CONTROL"] = f"http://127.0.0.1:{control.server_address[1]}"
cat = Catalog(tmp / "data", index=tmp / "index.sqlite")
obs = make_server(cat, "127.0.0.1", 0, follow=False)
threading.Thread(target=obs.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{obs.server_address[1]}"


def raw(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# --- the API through the Observatory's address, token for actions only ------------------------------------------------
st, b = raw("GET", "/control/api/v1/robots")
check("a read through /control needs no token", st == 200 and {r["id"] for r in b["robots"]} == {"duck-1", "fake-1"}, (st, b))
st, b = raw("POST", "/control/api/v1/robots/fake-1/lock", {})
check("an action through /control needs one: 401, Mission Control's own error", st == 401 and b["error"]["code"] == "unauthorized", (st, b))
st, b = raw("POST", "/control/api/v1/robots/fake-1/lock", {}, token=TOKEN)
check("with the token it works, and the lease is the token's client's", st == 200 and mc.get_robot("fake-1")["lock"]["holder"] == "page", (st, b))
raw("DELETE", "/control/api/v1/robots/fake-1/lock", {"session": b["lock"]["session"]}, token=TOKEN)
check("STOP needs none", raw("POST", "/control/api/v1/stop")[0] == 200)
check("the Observatory's own API stays its own: /api/v1/health there is the catalog's, /control/api/v1/health Mission Control's",
      "runs" in raw("GET", "/api/v1/health")[1] and raw("GET", "/control/api/v1/health")[1].get("service") == "mission-control")

errors, requests = [], []
with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text else None)
    page.on("response", lambda r: errors.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)
    page.on("requestfailed", lambda r: errors.append(f"failed: {r.url}") if "/events" not in r.url else None)
    page.on("request", lambda r: requests.append(r.url))

    def wait(js, timeout=8000):
        try:
            page.wait_for_function(js, timeout=timeout)
        except Exception:
            check(f"waited for {js[:90]}", False, "timed out")

    try:
        page.goto(BASE + "/control/")
        wait("window.__mc && window.__mc.ready")
        wait("document.querySelector('#robot-fake-1')?.getAttribute('data-online') === 'true'")
        check("Mission Control's page loads from the Observatory's address, its robots live over the stream that came through the proxy",
              page.url == BASE + "/control/" and page.locator("#robot-fake-1").get_attribute("data-online") == "true", page.url)
        check("its style and scripts came from /control/web/ and the library from /lib/ of the same origin",
              BASE + "/control/web/app.js" in requests and BASE + "/control/web/style.css" in requests and BASE + "/lib/tokens.css" in requests
              and BASE + "/control/api/v1/events" in "".join(u.split("?")[0] for u in requests), [u for u in requests if "control" in u][:6])
        check("the tokens of the one library reached the page (a coloured background, not the browser's white)",
              page.evaluate("getComputedStyle(document.body).backgroundColor") != "rgba(0, 0, 0, 0)")
        page.click("#stop-all")
        page.wait_for_timeout(300)
        check("STOP ALL works with no token, and asks for none", page.locator("#tokenbox").is_hidden())
        refused = page.evaluate("api('POST', '/robots/fake-1/lock', {}).then(() => 'worked', (e) => e.code)")
        check("an action with no token is refused and the page asks for the token", refused == "unauthorized" and page.locator("#token").is_visible(), refused)
        errors[:] = [e for e in errors if "401" not in e]       # the refusal is what was asked for: the browser logs it as a failed resource
        page.fill("#token", TOKEN)
        page.click("#token-set")
        worked = page.evaluate("api('POST', '/robots/fake-1/lock', {}).then((j) => j.ok, (e) => e.code)")
        check("with the token entered the action works", worked is True and page.locator("#tokenbox").is_hidden(), worked)

        page.goto(BASE + "/control/#robot/duck-1/body")
        wait("!document.getElementById('robot-page').hidden && !!window.__mc.body", 20000)
        wait("window.__mc.body?.state()?.drawn === 2", 20000)
        check("the robot page's body mounts under /control/: its script, the description and the meshes through the proxy, two parts drawn",
              page.locator("#rp-body canvas").count() == 1 and BASE + "/control/web/bodyview.js" in requests
              and any("/control/api/v1/robots/duck-1/meshes/" in u for u in requests), [u for u in requests if "mesh" in u or "bodyview" in u][:4])
        page.screenshot(path=str(SHOTS / "mc-one-origin-control.png"), full_page=True)

        page.goto(BASE + "/web/three/")
        page.wait_for_load_state("networkidle")
        check("the Observatory's own page loads from the same address", page.url.startswith(BASE + "/web/three/") and page.title().strip() != "", (page.url, page.title()))
        check("no script error, no console error and no failed request, on either page", errors == [], errors)
        page.screenshot(path=str(SHOTS / "mc-one-origin-observatory.png"))
        page.goto(BASE + "/control")
        wait("window.__mc && window.__mc.ready")
        check("/control with no slash lands on the page at /control/", page.url == BASE + "/control/", page.url)
    finally:
        browser.close()

obs.shutdown()
control.shutdown()
mc.close()
finish("test_one_origin_page")
