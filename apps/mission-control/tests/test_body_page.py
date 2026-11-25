"""The robot's body on Mission Control's robot page (RFC-0024 step 2, RFC-0023 D4), live, in headless Chromium: the real server, the page
driven by what the robot does. A stand-in registration folder with a two-joint description and tiny generated meshes (no duck meshes
needed), the fake robot reporting joint angles in its state. The body mounts in the Body section from the description Mission Control
serves, is posed from the robot's live joints, and each joint is coloured by its worst live alarm naming it (joint_overload,
joint_tracking, motor_hot: major and critical the error colour, minor the warn colour, else its own colour). Also what Mission Control
serves for it: the description, the meshes, the shared library (/lib/), and that the overview does not load three.js.

Runs in the viewer's environment (see test_page.py): make test-control-page"""

import atexit
from collections import defaultdict
import json
import math
import os
import shutil
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import DUCK_REGISTRATION, FAKE_FILE, check, finish, installation_file
from pageboot import boot

from observatory import kinematics
from observatory.shots import launch
from mission_control import alarms as alarms_mod, description
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.robots import RobotConfig
from runfile import installation

tmp = Path(tempfile.mkdtemp(prefix="mc-body-page-"))
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


URDF = """<robot name="standin">
  <link name="trunk"><visual><geometry><mesh filename="meshes/trunk.stl"/></geometry><material name="a"><color rgba="0.6 0.6 0.65 1"/></material></visual></link>
  <link name="thigh"><visual><geometry><mesh filename="meshes/thigh.stl"/></geometry><material name="b"><color rgba="0.9 0.6 0.2 1"/></material></visual></link>
  <link name="shin"><visual><geometry><mesh filename="meshes/shin.stl"/></geometry><material name="c"><color rgba="0.2 0.6 0.9 1"/></material></visual></link>
  <joint name="left_hip_pitch" type="revolute"><parent link="trunk"/><child link="thigh"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
  <joint name="left_knee" type="revolute"><parent link="thigh"/><child link="shin"/>
    <origin xyz="0 0 0.15" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
reg = tmp / "duck-folder"
(reg / "meshes").mkdir(parents=True)
shutil.copy(DUCK_REGISTRATION, reg / "registration.json")
shutil.copy(DUCK_REGISTRATION.parent / "profile.json", reg / "profile.json")
(reg / "robot.urdf").write_text(URDF)
(reg / "robot.json").write_text('{"label": "Stand-in", "stand_z": 0.05}')
for name, dims in (("trunk", (0.12, 0.12, 0.1)), ("thigh", (0.03, 0.03, 0.15)), ("shin", (0.03, 0.03, 0.12))):
    (reg / "meshes" / f"{name}.stl").write_bytes(box_stl(*dims))
(reg / "secret.txt").write_text("not a mesh")
(tmp / "outside.stl").write_bytes(box_stl(0.1, 0.1, 0.1))       # an .stl beside the robot's folder, not in it

os.environ[installation.ENV] = str(installation_file(tmp / "installation.json", {"duck": {"variant": "sim", "registration": str(reg / "registration.json")}}))
mc = MissionControl([RobotConfig({"id": "duck-1", "robot": "duck", "variant": "sim", "adapter": {"type": "fake"}}), RobotConfig(FAKE_FILE)], state_dir=tmp / "state")
srv = serve(mc, "127.0.0.1", 0)
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()
duck = mc.robots["duck-1"].adapter.robot


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


# --- what Mission Control serves for the body -------------------------------------------------------------------------
st, hd, raw = get("/api/v1/robots/duck-1/description")
desc = json.loads(raw).get("description") if st == 200 else None
check("must fail: GET /robots/{id}/description: the robot's links and joints from its description, root first", st == 200 and desc is not None
      and desc["root"] == "trunk" and [j["name"] for j in desc["joints"]] == ["left_hip_pitch", "left_knee"] and [l["name"] for l in desc["links"]] == ["trunk", "thigh", "shin"], st)
check("must fail: each visual has a URL under the API, and none is missing", desc is not None and desc["meshes_missing"] == []
      and all(v["url"].startswith("robots/duck-1/meshes/") for l in desc["links"] for v in l["visuals"]), desc and desc["links"][0])
mesh_url = desc["links"][0]["visuals"][0]["url"] if desc else "robots/duck-1/meshes/trunk.stl"
st, hd, raw = get("/api/v1/" + mesh_url)
check("must fail: a mesh is served as a binary STL, as the Observatory serves it", st == 200 and hd["Content-Type"] == "model/stl" and raw == (reg / "meshes" / "trunk.stl").read_bytes(), (st, hd.get("Content-Type")))
check("a mesh outside the description's folder, or not an .stl, is a 404", get("/api/v1/robots/duck-1/meshes/..%2Fsecret.txt")[0] == 404 and get("/api/v1/robots/duck-1/meshes/..%2F..%2Fprofile.json")[0] == 404
      and get("/api/v1/robots/duck-1/meshes/..%2Foutside.stl")[0] == 404 and get("/api/v1/robots/duck-1/meshes/nope.stl")[0] == 404 and get("/api/v1/robots/duck-1/meshes/%2Fetc%2Fpasswd")[0] == 404)
st, hd, raw = get("/api/v1/robots/fake-1/description")
check("must fail: a robot whose file holds the robot itself has no description: `description` is null, not an error", st == 200 and json.loads(raw) == {"ok": True, "description": None}, raw[:100])
check("an unknown robot is a 404, and a mesh of a robot with no description is too", get("/api/v1/robots/nope/description")[0] == 404 and get("/api/v1/robots/nope/meshes/x.stl")[0] == 404
      and get("/api/v1/robots/fake-1/meshes/trunk.stl")[0] == 404)
st, hd, raw = get("/lib/tokens.css")
check("must fail: the shared tokens are served at /lib/tokens.css", st == 200 and hd["Content-Type"].startswith("text/css") and b"--bg-app" in raw, st)
st, hd, raw = get("/lib/vendor/three.module.js")
check("must fail: the one three.js is served at /lib/vendor/three.module.js as JavaScript", st == 200 and "javascript" in hd["Content-Type"], (st, hd.get("Content-Type")))
check("must fail: the body component is served at /lib/body/body.js", get("/lib/body/body.js")[0] == 200 and get("/lib/body/robot.js")[0] == 200)
check("/lib/ does not read outside the library (a file that is there, a folder or two up)", get("/lib/../../apps/mission-control/src/mission_control/web/app.js")[0] == 404
      and get("/lib/%2e%2e/%2e%2e/apps/mission-control/src/mission_control/web/app.js")[0] == 404 and get("/web/app.js")[0] == 200 and get("/lib/")[0] == 404 and get("/lib/nope.js")[0] == 404)
duck.joints = {"left_hip_pitch": 0.5, "left_knee": -0.3}
for _ in range(100):
    st, hd, raw = get("/api/v1/robots/duck-1")
    joints = json.loads(raw)["robot"]["status"].get("joints") if st == 200 else None
    if joints:
        break
    time.sleep(0.1)
check("must fail: the robot's status carries its joint angles by name when it reports them", joints == {"left_hip_pitch": 0.5, "left_knee": -0.3}, joints)
check("and a robot that reports none has no joints key", "joints" not in json.loads(get("/api/v1/robots/fake-1")[2])["robot"]["status"])

# the reader is Mission Control's own (apps do not import each other): it must give what the Observatory's gives, on the real duck and the stand-in
REPO = Path(__file__).resolve().parents[3]
for folder_, label in ((REPO / "robots" / "duck", "the real duck"), (reg, "the stand-in")):
    ours = description.describe_folder(folder_, "x")
    theirs = kinematics.describe(kinematics.load(folder_ / "robot.urdf"))
    strip = lambda d: {**d, "links": [{**l, "visuals": [{k: v for k, v in vis.items() if k not in ("url",)} for vis in l["visuals"]]} for l in d["links"]]}  # noqa: E731
    same = (ours["root"], ours["joints"], strip(ours)["links"]) == (theirs["root"], theirs["joints"], theirs["links"])
    check(f"the description of {label} is the Observatory's, link for link and joint for joint", same,
          [k for k in ("root", "joints", "links") if ours[k] != theirs[k] and k != "links"])

errors, requests = [], []

with sync_playwright() as p:
    browser = launch(p)
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
    page.on("response", lambda r: errors.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
    page.on("request", lambda r: requests.append(r.url))
    css_hex = lambda name: page.evaluate("""(n) => { const e = document.createElement('i'); e.style.color = `var(--${n})`; document.body.append(e);
        const c = getComputedStyle(e).color; e.remove(); return '#' + c.match(/\\d+/g).slice(0, 3).map((x) => (+x).toString(16).padStart(2, '0')).join(''); }""", name)

    def wait(js, timeout=8000, arg=None):
        try:
            page.wait_for_function(js, arg=arg, timeout=timeout)
        except Exception:
            check(f"waited for {js[:90]}", False, "timed out")

    body = lambda: page.evaluate("window.__mc.body ? window.__mc.body?.state() : {}") or {}
    quat = lambda b, n: ((b.get("links") or {}).get(n) or {}).get("quat") or [9, 9, 9, 9]
    J = lambda b: defaultdict(dict, (b or {}).get("joints") or {})
    try:
        boot(page, BASE + "/", "window.__mc && window.__mc.ready")
        check("must fail: the overview loads no three.js (the phone page stays light)", not any("/lib/vendor/" in u for u in requests), [u for u in requests if "/lib/" in u])
        boot(page, BASE + "/#robot/duck-1", "!document.getElementById('robot-page').hidden && document.querySelectorAll('#rp-joints-body tr[data-joint]').length === 2")
        page.wait_for_timeout(500)
        check("must fail: the robot page's Overview loads no three.js either: its Body card reads the joints from the shared rule only", not any("/lib/vendor/" in u or "bodyview" in u for u in requests)
              and "All 2 joints ok" in page.locator("#rp-body-sum").inner_text() and page.locator("#rp-body canvas").count() == 0, page.locator("#rp-body-sum").inner_text())
        boot(page, BASE + "/#robot/duck-1/body", "!document.getElementById('robot-page').hidden && !!window.__mc.body", timeout=20000)
        wait("window.__mc.body?.state()?.drawn === 3", 20000)
        check("must fail: the body mounts in the Body section: a canvas inside it, three parts drawn", page.locator("#rp-body canvas").count() == 1
              and page.evaluate("(document.querySelector('#rp-body canvas')?.getBoundingClientRect().height || 0) > 150") and body().get("drawn") == 3, body())
        check("it loaded three.js from the shared library only", any("/lib/vendor/three.module.js" in u for u in requests) and not any("/web/three" in u or "cdn" in u.lower() for u in requests))
        check("no sideways scrolling on the robot page with the body in it", page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

        wait("window.__mc.body?.state()?.pose && Math.abs(window.__mc.body?.state()?.pose.left_hip_pitch - 0.5) < 1e-4")
        b0 = body()
        check("must fail: posed from the robot's live joints: the thigh turned the hip's 0.5 rad about y, the shin 0.5 - 0.3 below it",
              abs(quat(b0, "thigh")[2] - math.sin(0.25)) < 1e-4 and abs(quat(b0, "shin")[2] - math.sin(0.1)) < 1e-4, b0.get("links"))
        duck.joints = {"left_hip_pitch": -0.4, "left_knee": 0.2}
        wait("Math.abs(window.__mc.body?.state()?.links?.thigh?.quat?.[2] - Math.sin(-0.2)) < 1e-4", 8000)
        check("must fail: and it follows the next state", abs(quat(body(), "thigh")[2] - math.sin(-0.2)) < 1e-4, body().get("links"))

        own = {k: J(b0)[k].get("color") for k in ("left_hip_pitch", "left_knee")}
        err, warn = css_hex("error"), css_hex("warn")
        check("must fail: with no alarm every joint is ok and keeps its own colour", all(J(b0).get(k, {}).get("state") == "ok" for k in own) and len({err, warn, *own.values()}) == 4, (own, err, warn))

        def anomaly(robot, sev, name, joint, n=1):
            mc.bus.emit("anomaly", robot=robot, goal_run=1, watch=None, anomaly={"n": n, "t": 1.0, "anomaly": name, "source": "robot", "module": "body", "severity": sev,
                        "detector": "d", "summary": f"{name} for the test", "values": {"joint": joint}})

        anomaly("duck-1", "minor", "joint_tracking", "left_hip_pitch")
        wait("window.__mc.body?.state()?.joints?.left_hip_pitch?.state === 'warn'")
        b = body()
        check("must fail: a minor joint_tracking naming the hip turns it the warn colour; the knee is still ok",
              J(b)["left_hip_pitch"] == {"state": "warn", "color": warn} and J(b)["left_knee"] == {"state": "ok", "color": own["left_knee"]}, J(b))
        anomaly("duck-1", "major", "joint_overload", "left_knee", 2)
        wait("window.__mc.body?.state()?.joints?.left_knee?.state === 'error'")
        b = body()
        check("must fail: a major joint_overload naming the knee turns it the error colour; the hip keeps its warn",
              J(b)["left_knee"] == {"state": "error", "color": err} and J(b)["left_hip_pitch"].get("state") == "warn", J(b))
        listed = page.locator("#rp-body-joints li").all_inner_texts()
        check("must fail: never colour alone: the joints that are not ok are listed with their state and what said so",
              any("left_knee" in t and "error" in t and "joint_overload" in t for t in listed) and any("left_hip_pitch" in t and "warn" in t for t in listed), listed)
        page.screenshot(path=str(SHOTS / "mc-body-phone-dark.png"), full_page=True)
        page.locator("#rp-body").screenshot(path=str(SHOTS / "mc-body-section-phone-dark.png"))

        anomaly("fake-1", "critical", "joint_overload", "left_hip_pitch", 3)
        anomaly("duck-1", "critical", "pose_jump", None, 4)
        anomaly("duck-1", "info", "joint_overload", "left_hip_pitch", 5)
        page.wait_for_timeout(300)
        wait("window.__mc.S.alarms.length === 5")
        b = body()
        check("must fail: another robot's alarm, one that names no joint and an info one colour nothing", J(b)["left_hip_pitch"].get("state") == "warn" and J(b)["left_knee"].get("state") == "error", J(b))
        page.evaluate("() => { for (const x of window.__mc.S.alarms) x.at -= 61; window.__mc.renderRobotPage(); }")
        wait("window.__mc.body?.state()?.joints?.left_knee?.state === 'ok'")
        b = body()
        check("must fail: an alarm older than a minute no longer colours the joint (its own colour is back)",
              all(J(b)[k] == {"state": "ok", "color": own[k]} for k in own) and page.locator("#rp-body-joints li").count() == 0, J(b))

        # the same joint named by a fresh alarm, then the light theme and the desktop width
        anomaly("duck-1", "major", "motor_hot", "left_knee", 6)
        wait("window.__mc.body?.state()?.joints?.left_knee?.state === 'error'")
        page.emulate_media(color_scheme="light")
        wait("(arg) => window.__mc.body?.state()?.joints?.left_knee?.color === arg", 8000, css_hex("error"))
        check("must fail: in the light theme the error colour is the light token", css_hex("error") != err and J(body())["left_knee"].get("color") == css_hex("error"), (css_hex("error"), err))
        page.screenshot(path=str(SHOTS / "mc-body-phone-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")
        page.set_viewport_size({"width": 1500, "height": 900})
        wait("(arg) => window.__mc.body?.state()?.joints?.left_knee?.color === arg", 8000, css_hex("error"))
        page.wait_for_timeout(300)
        box = page.evaluate("(() => { const r = document.querySelector('#rp-body canvas')?.getBoundingClientRect(); return r ? [r.width, r.height] : [0, 0]; })()")
        check("desktop: the canvas fills its section and the page does not scroll sideways", box[0] > 300 and box[1] > 200 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), box)
        page.locator("#rp-body").screenshot(path=str(SHOTS / "mc-body-section-desktop-dark.png"))
        page.screenshot(path=str(SHOTS / "mc-body-desktop-dark.png"), full_page=True)

        # a robot with no description says so and loads nothing more
        page.set_viewport_size({"width": 390, "height": 800})
        page.evaluate("location.hash = '#robot/fake-1/body'")
        wait("document.getElementById('rp-title').textContent.includes('Fake robot')")
        wait("document.getElementById('rp-body').textContent.toLowerCase().includes('no 3d model')")
        check("must fail: a robot with no description: the Body section says there is no model, and has no canvas", page.locator("#rp-body canvas").count() == 0
              and "no 3d model" in page.locator("#rp-body").inner_text().lower(), page.locator("#rp-body").inner_text())
        page.evaluate("location.hash = '#robot/duck-1/body'")
        wait("window.__mc.body?.state()?.drawn === 3")
        check("and back on the duck the body is drawn again, once", page.locator("#rp-body canvas").count() == 1)

        # --- U22: the body view keeps working in whatever the layout does to the joints card beside it --------------------------------------
        page.set_viewport_size({"width": 1500, "height": 900})
        wait("window.__mc.body?.state()?.drawn === 3")
        page.click("#rp-layout")
        page.uncheck("#lay-show-joints")
        page.wait_for_timeout(300)
        solo = page.evaluate("(() => { const r = document.querySelector('#rp-body canvas')?.getBoundingClientRect(); return r ? [r.width, r.height] : [0, 0]; })()")
        check("must fail: with the joints card hidden the body view takes the whole row and still draws its three links", solo[0] > 900 and solo[1] > 200
              and page.evaluate("window.__mc.body.state().drawn") == 3 and page.locator("#rp-body canvas").count() == 1, solo)
        page.check("#lay-show-joints")
        page.evaluate("() => { const r = document.getElementById('lay-w-joints'); r.value = 560; r.dispatchEvent(new Event('input', {bubbles: true})); r.dispatchEvent(new Event('change', {bubbles: true})); }")
        page.wait_for_timeout(300)
        wide = page.evaluate("(() => { const r = document.querySelector('#rp-body canvas')?.getBoundingClientRect(); return r ? [r.width, r.height] : [0, 0]; })()")
        check("must fail: a joints column of 560 px narrows the body view, which redraws at its new size and keeps its toolbar", 300 < wide[0] < solo[0] and wide[1] > 200
              and page.locator("#rp-body-view .bodytools button").count() == 7, [wide, solo])
        page.click("#lay-reset")
        page.click("#lay-close")
        page.wait_for_timeout(200)
        check("and a reset puts the joints card and the 340 px column back", page.evaluate("!document.querySelector('[data-panel=joints]').hidden && getComputedStyle(document.querySelector('.bodygrid')).gridTemplateColumns.split(' ').length === 2"))

        # --- U21: the shared stage, the camera presets, Fit robot, x-ray and the inspector -------------------------------------------------
        cam = lambda: page.evaluate("window.__mc.body.state().camera")
        settled = lambda: wait("window.__mc.body.state().camera.moving === false")
        unit = lambda c: (lambda off: [x / (math.hypot(*off) or 1) for x in off])([a - b for a, b in zip(c["position"], c["target"])])
        close = lambda a, b, tol=2e-3: all(abs(x - y) < tol for x, y in zip(a, b))
        page.set_viewport_size({"width": 1200, "height": 800})
        wait("window.__mc.body?.state()?.drawn === 3")
        stg = body().get("stage") or {}
        check("must fail: the body stands on the shared stage: floor in the scene, grid, contact shadow with some opacity", stg.get("floor") is True and stg.get("grid") is True
              and stg.get("shadow") is True and (stg.get("shadowOpacity") or 0) > 0, stg)
        check("must fail: theme lights (hemisphere and sun), NeutralToneMapping, and the camera draws the stage layer", sorted(stg.get("lights") or []) == ["DirectionalLight", "HemisphereLight"]
              and stg.get("neutral") is True and stg.get("cameraSeesStage") is True, stg)
        check("must fail: the stage's colours are the page's --scene tokens", bool((stg.get("tokens") or {}).get("floor")) and stg["tokens"]["floor"] == page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--scene-floor').trim()"), stg.get("tokens"))
        check("must fail: the toolbar offers Iso, Top, Front, Side, Fit robot, X-ray and Inspector", page.locator("#rp-body-view .bodytools button").all_inner_texts()
              == ["Iso", "Top", "Front", "Side", "Fit robot", "X-ray", "Inspector"], page.locator("#rp-body-view .bodytools button").all_inner_texts())
        iso = [-5.5, -7.5, 6.5]
        iso = [x / math.hypot(*iso) for x in iso]
        for name, axis in (("iso", iso), ("top", [0, 0, 1]), ("front", [1, 0, 0]), ("side", [0, -1, 0]), ("iso", iso)):
            page.click(f"#rp-body-view [data-preset={name}]")
            settled()
            c = cam()
            check(f"must fail: the {name} preset puts the camera on its axis, z up, the robot in view", close(unit(c), axis) and close(c["up"], [0, 0, 1], 1e-3) and c["preset"] == name
                  and c["ndc"]["inside"] is True and page.locator(f"#rp-body-view [data-preset={name}]").get_attribute("aria-pressed") == "true", c)
        page.mouse.move(600, 450)
        for _ in range(6):
            page.mouse.wheel(0, -600)
        page.wait_for_timeout(200)
        zoomed = cam()
        check("must fail: zoomed in until the robot spills out of the view, the preset is let go", zoomed["ndc"]["inside"] is False and zoomed["preset"] is None, zoomed)
        page.click("#rp-body-view [data-act=fit]")
        settled()
        fit = cam()
        check("must fail: Fit robot frames the whole robot: every corner of its box in view, and it fills the pane", fit["ndc"]["inside"] is True and fit["ndc"]["height"] > 0.3, fit)

        check("must fail: x-ray is off at first, solid", body()["xray"] is False and body()["style"] == "solid")
        page.click("#rp-body-view [data-act=xray]")
        check("must fail: the x-ray toggle makes the body see-through, and says it is on", body()["xray"] is True and body()["style"] == "xray"
              and page.locator("#rp-body-view [data-act=xray]").get_attribute("aria-pressed") == "true", body().get("style"))
        page.click("#rp-body-view [data-act=xray]")
        check("must fail: a second press makes it solid again", body()["xray"] is False and body()["style"] == "solid")

        check("the inspector is closed and not mounted at first", body()["inspector"] == {"open": False, "rows": 0, "selected": None}, body()["inspector"])
        page.keyboard.press("Escape")
        check("Escape with the inspector closed does nothing", body()["inspector"]["open"] is False)
        page.keyboard.press("i")
        check("must fail: i opens the inspector: a row for each of the three links", body()["inspector"]["open"] is True and body()["inspector"]["rows"] == 3
              and page.locator("#rp-body-view .bodyinsp .insp-row").count() == 3, body()["inspector"])
        shin = page.locator("#rp-body-view .bodyinsp .insp-row[data-link=shin]")
        shin.click()
        check("must fail: choosing a part in the inspector marks it", body()["inspector"]["selected"] == "shin" and shin.get_attribute("aria-selected") == "true", body()["inspector"])
        page.set_viewport_size({"width": 390, "height": 800})
        page.wait_for_timeout(200)
        check("on a phone the open inspector and the toolbar sit under STOP and STOP ALL: nothing covers them", page.evaluate("""() => ['stop-robot', 'stop-all'].every((id) => { const b = document.getElementById(id), r = b.getBoundingClientRect();
            const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return e === b || b.contains(e); })"""))
        page.keyboard.press("Escape")
        check("must fail: Escape closes the inspector and lets the part go", body()["inspector"] == {"open": False, "rows": 3, "selected": None}, body()["inspector"])
        page.evaluate("() => { const i = document.createElement('input'); i.id = 'u21-probe'; document.body.append(i); i.focus(); }")
        page.keyboard.type("i")
        check("must fail: an i typed in a text field does not open the inspector, and lands in the field", body()["inspector"]["open"] is False
              and page.evaluate("document.getElementById('u21-probe').value") == "i", body()["inspector"])
        page.evaluate("document.getElementById('u21-probe').remove()")
        page.click("#rp-body-view [data-act=inspector]")
        check("the Inspector button opens it too", body()["inspector"]["open"] is True)
        page.keyboard.press("Escape")
        check("and Escape closes it again", body()["inspector"]["open"] is False)

        page.evaluate("location.hash = '#robot/duck-1'")
        wait("document.querySelectorAll('#rp-body canvas').length === 0")
        page.keyboard.press("i")
        check("with the Body tab left, the i key does nothing (the listener went with the view)", page.evaluate("window.__mc.body.state()") is None)
        page.evaluate("location.hash = '#robot/duck-1/body'")
        wait("window.__mc.body?.state()?.drawn === 3")

        # a page opened after the alarm: the server's last minute (shortened to 3 s here) seeds it, so the joint is coloured at once
        alarms_mod.WINDOW_S = 3
        page.wait_for_timeout(3500)
        mc.bus.emit("anomaly", robot="duck-1", goal_run=1, watch=None, anomaly={"n": 7, "t": 1.0, "anomaly": "joint_overload", "source": "robot", "module": "body",
                    "severity": "major", "detector": "d", "summary": "overload before the page opened", "values": {"joint": "left_hip_pitch"}})
        late = ctx.new_page()
        late.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        boot(late, BASE + "/#robot/duck-1/body", "window.__mc && window.__mc.ready && window.__mc.body?.state()?.drawn === 3", timeout=20000)
        lj = lambda: late.evaluate("window.__mc.body.state().joints") or {}
        late.wait_for_function("window.__mc.body.state().joints?.left_hip_pitch?.state === 'error'", timeout=8000)
        check("must fail: opened after a major joint_overload: the joint's row says error, and the mesh has the error colour, with no live event since the page opened",
              late.locator("#rp-joints-body tr[data-joint=left_hip_pitch]").get_attribute("data-state") == "error"
              and lj()["left_hip_pitch"] == {"state": "error", "color": err} and lj()["left_knee"]["state"] == "ok", lj())
        check("and the page's window is the server's (3 s), and the alarm is counted once (the worst overall and the worst of its joint are one)",
              late.evaluate("window.__mc.S.alarms.length") == 1, late.evaluate("window.__mc.S.alarms.length"))
        late.evaluate("window.__mc.loadRobots()")
        late.wait_for_timeout(500)
        check("a reload of the robot's view does not count it twice", late.evaluate("window.__mc.S.alarms.length") == 1)
        late.wait_for_function("window.__mc.body.state().joints?.left_hip_pitch?.state === 'ok'", timeout=12000)
        check("must fail: after the window the joint is ok again and its own colour is back", lj()["left_hip_pitch"]["color"] == own["left_hip_pitch"], lj())
        late.close()
        alarms_mod.WINDOW_S = 60
        check("no script error and no console error in the whole session", errors == [], errors)
    finally:
        browser.close()

srv.shutdown()
srv.server_close()
mc.close()
finish("test_body_page")
