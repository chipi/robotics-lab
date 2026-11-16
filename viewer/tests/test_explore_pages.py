"""The left panel by meaning and the Explore tab (UXS-001, RFC-0011, operator 2026-11-16), in headless Chromium, both pages: the
sections World, Body, Senses, Mind, Other values, closed until opened (the one holding the selected stream opens), the choice
remembered; the joints by chain with their technical names and their angle at the playhead, a switch to hide the angles;
Explore with a robot's body drawn from its description, posed as recorded (following the playhead) or by hand, parts picked
in the list or in the body, their details, isolate, hide, show all; and the pages' forward kinematics (shell/robot.js) where
MuJoCo puts every link of the duck (robots/duck/fk_fixture.json). A throwaway two-link arm with generated meshes: no duck
meshes needed. Screenshots to /tmp/claude-1000/explore-pages/ (EXPLORE_SHOTS=0 turns them off).
Run: cd viewer && uv run python tests/test_explore_pages.py"""

import json
import math
import os
import struct
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")
os.environ.setdefault("MINIVIEW_INDEX", str(TMP / "index.sqlite"))

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import T0_NS, catalog, scene, serve  # noqa: E402
from miniview import keys, kinematics, mcapio  # noqa: E402
from miniview.shots import launch  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHOTS = Path("/tmp/claude-1000/explore-pages") if os.environ.get("EXPLORE_SHOTS", "1") != "0" else None
fails, lib = [], "?"


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + f"[{lib}] " + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(f"{lib}: {name}")


def box_stl(sx, sy, sz, z0=0.0) -> bytes:
    """A binary STL of a box (12 triangles), from z0 up."""
    v = [(x, y, z) for x in (-sx / 2, sx / 2) for y in (-sy / 2, sy / 2) for z in (z0, z0 + sz)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    out = bytearray(80) + struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + struct.pack("<H", 0)
    return bytes(out)


ARM = """<robot name="arm">
  <link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry><material name="b"><color rgba="0.6 0.6 0.65 1"/></material></visual></link>
  <link name="upper"><visual><geometry><mesh filename="meshes/upper.stl"/></geometry><material name="u"><color rgba="0.9 0.6 0.2 1"/></material></visual></link>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
(arm / "meshes").mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm", "stand_z": 0.05}')
(arm / "meshes" / "base.stl").write_bytes(box_stl(0.12, 0.12, 0.1))
(arm / "meshes" / "upper.stl").write_bytes(box_stl(0.03, 0.03, 0.15))

# a run of the arm: a pose per tick (the spatial views), its joint and three other signals at 10 Hz
KEY = "arm/room/r1"
data = TMP / "data"
SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "pitch_deg", "kind": "number", "unit": "deg"},
        {"name": "roll_deg", "kind": "number", "unit": "deg"}, {"name": "battery_v", "kind": "number", "unit": "V"}]
rec = mcapio.Recorder(keys.run_dir(data, KEY), mcapio.new_run(KEY, {"name": "arm", "radius": 0.08, "height": 0.27}, "room", "exploration", T0_NS,
                                                              "writer", signals=SIGS))
rec.add(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})
shoulder = lambda t: round(0.6 * math.sin(t), 4)  # noqa: E731
for k in range(0, 51):
    t = k * 0.1
    rec.begin_tick(t, [0.02 * k, 0.0, 0.0])
    # the truth a metre aside, its whole pose (ADR-0016): 0.2 m up, turned 0.2 rad about x; the IMU's tilt for the belief's body
    rec.tick_truth([0.02 * k + 1.0, 0.5, 0.0], {"z": 0.2, "quat": [math.cos(0.1), math.sin(0.1), 0.0, 0.0]})
    rec.tick_tilt(2.0, -1.0)
    rec.end_tick()
    rec.begin_signals(t + 0.05, {"joint_shoulder": shoulder(t + 0.05), "pitch_deg": 1.0, "roll_deg": -0.5, "battery_v": 7.4})
    rec.end_tick()
rec.add(5.2, "end", {"status": "ended"})
rec.close()


def page_of(b, base):
    ctx = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
    page = ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text} {m.location.get('url')}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.on("response", lambda r: logs.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)
    page.goto(f"{base}/web/{lib}/index.html")
    page.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
    return ctx, page, logs


def call(page, js, t=60000):
    page.evaluate("window.__ready = false")
    r = page.evaluate(js)
    page.wait_for_function("window.__ready === true", timeout=t)
    return r


def shot(page, name):
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{lib}-{name}.png"))


def rows(page):
    return page.evaluate("[...document.querySelectorAll('#tree .row')].map((r) => r.dataset.id)")


with sync_playwright() as p:
    cat = catalog(data)
    cat.put_scene(scene("room"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    duck = kinematics.describe(kinematics.load(REPO / "robots" / "duck" / "robot.urdf"))
    fixture = json.loads((REPO / "robots" / "duck" / "fk_fixture.json").read_text())
    try:
        for lib in ("three", "deck"):
            ctx, page, logs = page_of(b, base)
            page.evaluate("localStorage.removeItem('miniview.left')")
            call(page, f"window.miniview.load('room', '{KEY}')")
            st = page.evaluate("window.miniview.state()")
            secs = {s["id"]: s for s in st["sections"]}
            check("the left panel's sections, in order: World, Body, Senses, Mind, Other values",
                  [s["name"] for s in st["sections"]] == ["World", "Body", "Senses", "Mind", "Other values"], [s["name"] for s in st["sections"]])
            check("what each holds: the joint in Body, the IMU's values in Senses, the belief in Mind, the rest in Other values",
                  "signals.joint_shoulder" in secs["sec.body"]["streams"] and {"signals.pitch_deg", "signals.roll_deg", "sensors.tilt"} <= set(secs["sec.senses"]["streams"])
                  and "belief.pose" in secs["sec.mind"]["streams"] and secs["sec.other"]["streams"] == ["signals.battery_v"]
                  and {"scene.boxes", "truth.pose"} <= set(secs["sec.world"]["streams"]), {k: v["streams"] for k, v in secs.items()})
            check("closed until opened: only the section holding the selected stream (Mind: the belief) is open",
                  [s["id"] for s in st["sections"] if s["open"]] == ["sec.mind"], [(s["id"], s["open"]) for s in st["sections"]])
            check("a closed section shows no rows", "signals.joint_shoulder" not in rows(page) and "sec.body" in rows(page))
            page.click('#tree .row[data-id="sec.body"] .name')
            check("clicking a section's header opens it: the 3D model row, the chain (named by its first part: the arm's one chain), the joint by its technical name",
                  page.evaluate("document.querySelector('#tree .row[data-id=\"sec.body\"]').getAttribute('aria-expanded')") == "true"
                  and {"body.model", "g.chain.upper", "signals.joint_shoulder"} <= set(rows(page))
                  and page.evaluate("document.querySelector('#tree .row[data-id=\"signals.joint_shoulder\"] .name').textContent") == "shoulder",
                  rows(page))
            call(page, "window.miniview.setTime(1.0)")
            want = f"{math.degrees(shoulder(0.95)):.1f}°"
            got = page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent")
            check("the joint's angle at the playhead, in degrees (the sample at or before t), shown (not only on hover)", got == want
                  and page.evaluate("getComputedStyle(document.querySelector('#tree [data-angle=\"shoulder\"]')).opacity") == "1", (got, want))
            check("the timeline names the joint's row as the outliner does",
                  page.evaluate("document.querySelector('#lanesL .lane-l[data-lane=\"signals.joint_shoulder\"]').innerText.trim()") == "shoulder")
            call(page, "window.miniview.setTime(3.0)")
            got3 = page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent")
            check("the angle follows the playhead", got3 == f"{math.degrees(shoulder(2.95)):.1f}°", got3)
            page.click('#tree [data-angles]')
            check("the switch hides the angles", page.evaluate("document.querySelector('#tree [data-angle=\"shoulder\"]').textContent") == ""
                  and page.evaluate("window.miniview.state().angles") is False)
            shot(page, "left-body-open")

            # remembered in this browser: a reload keeps Body open and the angles hidden
            page.reload()
            page.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
            call(page, f"window.miniview.load('room', '{KEY}')")
            st2 = page.evaluate("window.miniview.state()")
            check("the viewer's choice is remembered: Body open, the angles hidden",
                  [s["id"] for s in st2["sections"] if s["open"]] == ["sec.body", "sec.mind"] and st2["angles"] is False,
                  ([(s["id"], s["open"]) for s in st2["sections"]], st2["angles"]))
            call(page, "window.miniview.setAngles(true)")

            # Explore: the run's robot, posed as recorded
            page.click('#tree .row[data-id="body.model"]')
            page.wait_for_function("window.miniview.exploreState()?.robot === 'arm' && window.miniview.exploreState().drawn === 2", timeout=20000)
            xs = page.evaluate("window.miniview.exploreState()")
            check("the 3D model row opens Explore on the run's robot: both parts drawn, posed as recorded",
                  xs["kind"] == "robot body" and xs["pose"] == "recorded" and page.evaluate("window.miniview.state().tab") == "explore"
                  and page.evaluate("!document.getElementById('explore').hidden && document.getElementById('inspBody').hidden"), xs)
            call(page, "window.miniview.setTime(2.0)")
            xs = page.evaluate("window.miniview.exploreState()")
            q = xs["poses"]["upper"]["quat"]
            a = shoulder(1.95)
            check("as recorded: the joint's value at the playhead, the part where the kinematics put it (a turn about y)",
                  abs(xs["values"]["shoulder"] - a) < 1e-4 and abs(q[0] - math.cos(a / 2)) < 1e-6 and abs(q[2] - math.sin(a / 2)) < 1e-6
                  and xs["poses"]["upper"]["pos"] == [0, 0, 0.1], (xs["values"], q))
            snap = page.evaluate("window.miniview.exploreSnapshot()")
            check("the body is drawn (the canvas has an image)", isinstance(snap, str) and snap.startswith("data:image/png") and len(snap) > 3000, len(snap or ""))
            shot(page, "explore-recorded")

            page.click('#explore .xrow[data-link="upper"]')
            part = page.evaluate("document.getElementById('xpart').innerText")
            check("a part picked in the list: what moves it, its limits, what it hangs from",
                  page.evaluate("window.miniview.exploreState().selected") == "upper" and "moved by the joint shoulder" in part
                  and "-85.9° … 85.9°" in part and "base" in part, part)
            page.click('#explore [data-act="isolate"]')
            xs = page.evaluate("window.miniview.exploreState()")
            check("isolate: only the picked part", xs["isolated"] == "upper", xs["isolated"])
            page.click('#explore [data-act="focus"]')
            page.click('#explore [data-act="close"]')
            box = page.evaluate("(() => { const r = document.querySelector('#xbody canvas').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            page.mouse.click(*box)
            check("a part picked in the body (a click on the isolated upper arm, focused)", page.evaluate("window.miniview.exploreState().selected") == "upper",
                  page.evaluate("window.miniview.exploreState().selected"))
            page.click('#xall')
            # nothing isolated or hidden: a click picks the part that is in front, where each is
            picked = {}
            for link in ("upper", "base"):
                page.click('#explore [data-act="close"]') if page.query_selector('#explore [data-act="close"]') else None
                xy = page.evaluate(f"window.miniview.exploreScreenOf('{link}')")
                page.mouse.click(*xy)
                picked[link] = page.evaluate("window.miniview.exploreState().selected")
            check("with every part shown, a click on each part picks that part (the one in front)", picked == {"upper": "upper", "base": "base"}, picked)
            call(page, "window.miniview.exploreHide('base')")
            xs = page.evaluate("window.miniview.exploreState()")
            check("hide a part; show all brings everything back", xs["hidden"] == ["base"] and xs["isolated"] is None, xs)
            page.click('#xall')
            check("show all", page.evaluate("window.miniview.exploreState().hidden") == [])

            # by hand: from the recorded pose, a slider per joint
            page.click('#explore [data-pose="hand"]')
            xs = page.evaluate("window.miniview.exploreState()")
            check("by hand starts from the recorded pose", xs["pose"] == "hand" and abs(xs["values"]["shoulder"] - shoulder(1.95)) < 1e-4, xs["values"])
            page.evaluate("(() => { const s = document.querySelector('#explore input[data-hand=\"shoulder\"]'); s.value = '1.2'; s.dispatchEvent(new Event('input', { bubbles: true })); })()")
            xs = page.evaluate("window.miniview.exploreState()")
            check("a slider poses the joint, the playhead does not", abs(xs["values"]["shoulder"] - 1.2) < 1e-9
                  and abs(xs["poses"]["upper"]["quat"][2] - math.sin(0.6)) < 1e-6
                  and page.evaluate("document.querySelector('#explore [data-val=\"shoulder\"]').textContent") == "68.8°", xs["values"])
            call(page, "window.miniview.setTime(4.0)")
            check("by hand ignores the playhead", abs(page.evaluate("window.miniview.exploreState().values.shoulder") - 1.2) < 1e-9)
            check("a joint past its limit is drawn at the limit", page.evaluate("window.miniview.exploreJoint('shoulder', 3)")
                  and abs(page.evaluate("window.miniview.exploreState().poses.upper.quat[2]") - math.sin(0.75)) < 1e-6)
            shot(page, "explore-hand")
            page.click('#xwide')
            check("Expand gives the explorer more room", page.evaluate("document.getElementById('app').classList.contains('xwide')")
                  and page.evaluate("document.getElementById('insp').getBoundingClientRect().width") > 450)
            shot(page, "explore-wide")
            # the main view is narrower now: its legend may wrap, and nothing (the 3D labels) may be drawn over it
            # (pointer events on for everything while it looks: the corner and the labels have none, and elementFromPoint skips those)
            over = page.evaluate("""(() => { const l = document.getElementById('legend'); if (!l || !l.offsetParent) return 'no legend';
              const st = document.createElement('style'); st.textContent = '#app * { pointer-events: auto !important; }'; document.head.append(st);
              // the three.js page: a label where CSS2DRenderer puts them (inside a slot's label layer, a high z-index to sort by
              // depth), under the first legend item, so the check does not depend on where this scene's labels happen to fall
              const layer = document.querySelector('.slot .labels'), first = l.querySelector('span'), probe = document.createElement('div');
              if (layer && first) {
                const lb = layer.getBoundingClientRect(), fb = first.getBoundingClientRect();
                probe.textContent = '8.88'; probe.style.cssText = `position:absolute;z-index:9999;left:${fb.x - lb.x}px;top:${fb.y - lb.y}px;width:${fb.width}px;height:${fb.height}px`;
                layer.append(probe);
              }
              try {
                return [...l.querySelectorAll('span')].map((s) => { const b = s.getBoundingClientRect(); return [s, document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2)]; })
                  .filter(([, e]) => !l.contains(e)).map(([s, e]) => `${s.innerText} under ${e ? e.tagName + '.' + e.className : 'nothing'}`);
              } finally { st.remove(); probe.remove(); } })()""")
            check("the main view's legend is on top: no label is drawn over any of its items", over == [], over)
            page.click('#xwide')

            # the pages' forward kinematics are miniview.kinematics' and MuJoCo's: every link of the duck, for every fixture case
            worst = page.evaluate("""async ([desc, cases]) => {
              const { linkPoses } = await import('/web/shell/robot.js');
              let wp = 0, wq = 0;
              for (const c of cases) {
                const ours = linkPoses(desc, c.joints);
                for (const [n, want] of Object.entries(c.links)) {
                  const g = ours[n];
                  wp = Math.max(wp, ...g.pos.map((v, i) => Math.abs(v - want.pos[i])));
                  wq = Math.max(wq, Math.min(Math.max(...g.quat.map((v, i) => Math.abs(v - want.quat[i]))), Math.max(...g.quat.map((v, i) => Math.abs(v + want.quat[i])))));
                }
              }
              return [wp, wq];
            }""", [duck, fixture["cases"]])
            check(f"the pages' kinematics put every link of the duck where MuJoCo does ({len(fixture['cases'])} cases): within 1e-6 m and 1e-6",
                  worst[0] < 1e-6 and worst[1] < 1e-6, worst)

            # the Robot layer in the main 3D view (three.js page): the body where the truth was, or the belief, its joints at t
            if lib == "three":
                call(page, "window.miniview.setView('3d')")
                call(page, "window.miniview.setTime(2.0)")
                page.wait_for_function("window.miniview.internals.adapter.body()?.drawn === 2", timeout=20000)
                call(page, "window.miniview.setTime(2.0)")
                bd = page.evaluate("window.miniview.internals.adapter.body()")
                a = shoulder(1.95)
                near = lambda x, y, tol=1e-4: all(abs(p - q) < tol for p, q in zip(x, y))  # noqa: E731
                check("the Robot layer in the world frame: the trunk at the truth's whole pose (x, y, z and tilt), the joint at its value at t",
                      bd["visible"] and near(bd["pos"], [1.4, 0.5, 0.2]) and near(bd["quat"], [math.cos(0.1), math.sin(0.1), 0, 0])
                      and near(bd["joint_upper_quat"], [math.cos(a / 2), math.sin(a / 2)]), bd)
                call(page, "window.miniview.setFrame('map')")
                bd = page.evaluate("window.miniview.internals.adapter.body()")
                p_, r_ = math.radians(2.0) / 2, math.radians(-1.0) / 2
                want_q = [math.cos(p_) * math.cos(r_), math.cos(p_) * math.sin(r_), math.sin(p_) * math.cos(r_), -math.sin(p_) * math.sin(r_)]
                check("in the map frame (no truth there): at the belief, at the robot's standing height, tilted by the IMU",
                      bd["visible"] and near(bd["pos"], [0.4, 0.0, 0.05]) and near(bd["quat"], want_q), (bd, want_q))
                call(page, "window.miniview.setFrame('world')")
                page.click('#tree .row[data-id="body.model"] .eye')
                hidden = page.evaluate("window.miniview.internals.adapter.body().visible")
                page.click('#tree .row[data-id="body.model"] .eye')
                check("the 3D model row's eye hides the body and shows it again", hidden is False and page.evaluate("window.miniview.internals.adapter.body().visible") is True)
                shot(page, "robot-layer-3d")
                call(page, "window.miniview.setView('top')")

            errs = [m for m in logs if "favicon" not in m]
            check("no console errors or warnings", not errs, errs[:5])
            ctx.close()
    finally:
        httpd.shutdown()
        b.close()

print("EXPLORE-PAGES", "FAIL " + ", ".join(fails) if fails else "PASS")
raise SystemExit(1 if fails else 0)
