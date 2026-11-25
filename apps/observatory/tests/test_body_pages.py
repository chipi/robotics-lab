"""The body on the watch page, coloured by each joint's worst state (RFC-0023 D4 and D12, RFC-0024 step 2), in headless Chromium: a
two-joint stand-in arm with generated meshes, a run whose anomalies name joints (joint_tracking minor on the elbow at 1.5 s,
joint_overload major on the shoulder at 2.5 s, a pose_jump that names none), and the watch page at three moments. A joint is coloured by
the worst anomaly naming it at or before the playhead (major and critical the error colour, minor the warn colour); a joint no anomaly names
keeps its own colour; the colours are the page's tokens. Also the shared library the page now loads from (/lib/): its tokens, its
three.js, and that the pages' old copies are gone. Needs the system Chromium and Playwright.
Then the component alone, on a bare page that imports it fresh: the styles (solid, x-ray, ghost), clone sharing geometry, parts(), highlight, isolate and the
keyboard inspector.
Run: cd apps/observatory && uv run python tests/test_body_pages.py"""

import atexit
from collections import defaultdict
import os
import shutil
import struct
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, TMP, True)
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, boot, catalog, make_run, scene, serve  # noqa: E402
from observatory.shots import launch  # noqa: E402

check = Checks("BODY PAGES")
SHOTS = Path(os.environ.get("BODY_SHOTS", Path.home() / ".cache" / "robotics-lab-tests"))
SHOTS.mkdir(parents=True, exist_ok=True)


def box_stl(sx, sy, sz, z0=0.0) -> bytes:
    v = [(x, y, z) for x in (-sx / 2, sx / 2) for y in (-sy / 2, sy / 2) for z in (z0, z0 + sz)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    out = bytearray(80) + struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + struct.pack("<H", 0)
    return bytes(out)


ARM = """<robot name="arm">
  <link name="base"><visual><geometry><mesh filename="meshes/base.stl"/></geometry><material name="b"><color rgba="0.6 0.6 0.65 1"/></material></visual></link>
  <link name="upper"><visual><geometry><mesh filename="meshes/upper.stl"/></geometry><material name="u"><color rgba="0.9 0.6 0.2 1"/></material></visual></link>
  <link name="fore"><visual><geometry><mesh filename="meshes/fore.stl"/></geometry><material name="f"><color rgba="0.2 0.6 0.9 1"/></material></visual></link>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
  <joint name="elbow" type="revolute"><parent link="upper"/><child link="fore"/>
    <origin xyz="0 0 0.15" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
(arm / "meshes").mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm", "stand_z": 0.05}')
for name, dims in (("base", (0.12, 0.12, 0.1)), ("upper", (0.03, 0.03, 0.15)), ("fore", (0.03, 0.03, 0.12))):
    (arm / "meshes" / f"{name}.stl").write_bytes(box_stl(*dims))


def anomaly(t, name, severity, joint=None):
    values = {"joint": joint, "margin_unit": "mA"} if joint else {"jump_m": 0.9, "margin_unit": "m"}
    raw = {"event": "anomaly", "anomaly": name, "source": "robot", "module": "body", "severity": severity, "detector": f"{name}_rule", "version": 1,
           "summary": f"{name}: made up for the test", "values": values, "margin": 0.1, "where": {"frame": "map", "belief": [0.0, 0.0]},
           "evidence": {}, "related": [], "duration_s": 0.4}
    return (t, "event", {"kind": "anomaly", "text": f"anomaly {name} ({severity})", "notable": True, "t_src": t, "raw": raw})


records = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
for k in range(41):
    records.append((round(0.1 * k, 3), "tick", {"belief": [0.02 * k, 0.0, 0.0], "truth": None, "tilt": None, "cmd": [0.3, 0.0], "depth": None,
                                              "t_src": round(0.1 * k, 3), "raw": {}}))
records += [anomaly(1.5, "joint_tracking", "minor", "elbow"), anomaly(2.5, "joint_overload", "major", "shoulder"), anomaly(3.0, "pose_jump", "critical"),
            (4.1, "end", {"verdict": "reached"})]
SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "joint_elbow", "kind": "number", "unit": "rad"}]
records += [(round(0.1 * k + 0.05, 3), "signals", {"values": {"joint_shoulder": 0.3, "joint_elbow": -0.2}, "t_src": round(0.1 * k + 0.05, 3)}) for k in range(40)]
records.sort(key=lambda r: r[0])

data = TMP / "data"
cat = catalog(data)
cat.put_scene(scene("room"))
make_run(data, "arm/room/r1", records, signals=SIGS)
cat.scan()
httpd, base = serve(cat, follow=False)


def status(path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


code, hdrs, css = status("/lib/tokens.css")
check("must fail: the shared design tokens are served at /lib/tokens.css", code == 200 and hdrs["Content-Type"].startswith("text/css") and b"--bg-app" in css, code)
code, hdrs, _ = status("/lib/vendor/three.module.js")
check("must fail: the one three.js is served from /lib/vendor/, cached for a day", code == 200 and "javascript" in hdrs["Content-Type"]
      and "max-age=86400" in hdrs["Cache-Control"], (code, hdrs.get("Cache-Control")))
check("must fail: the body component is served from /lib/body/", status("/lib/body/body.js")[0] == 200 and status("/lib/body/robot.js")[0] == 200)
check("must fail: the pages keep no second copy: the old vendor folder and the shell's body files are gone",
      status("/web/three/vendor/three.module.js")[0] == 404 and status("/web/shell/robotbody.js")[0] == 404 and status("/web/shell/robot.js")[0] == 404)
check("/lib/ does not read outside the library (a file that is there, a folder or two up)", status("/lib/../../apps/observatory/web/three/app.js")[0] == 404
      and status("/lib/%2e%2e/%2e%2e/apps/observatory/web/three/app.js")[0] == 404 and status("/web/three/app.js")[0] == 200
      and status("/lib/nope.js")[0] == 404 and status("/lib/")[0] == 404)

J = lambda bd: defaultdict(dict, (bd or {}).get("joints") or {})  # noqa: E731
RGB = "(name) => { const e = document.createElement('i'); e.style.color = `var(--${name})`; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; }"
HEX = "(c) => '#' + c.match(/\\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, '0')).join('')"
BODY = "window.miniview.internals.adapter.body()"

with sync_playwright() as p:
    b = launch(p)
    page = b.new_context(viewport={"width": 1500, "height": 900}, color_scheme="dark").new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") and "GL Driver Message" not in m.text and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.on("response", lambda r: logs.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
    try:
        boot(page, f"{base}/watch/arm/room/r1#t=1.0", timeout=30000)
        page.wait_for_function(f"{BODY}?.drawn === 3", timeout=20000)

        def at(t):
            page.evaluate("window.__ready = false")
            page.evaluate(f"window.miniview.setTime({t})")
            page.wait_for_function("window.__ready === true", timeout=20000)
            return page.evaluate(BODY)

        css_hex = lambda name: page.evaluate(f"(c) => ({HEX})(({RGB})(c))", name)  # noqa: E731
        err, warn = css_hex("error"), css_hex("warn")
        bd = at(1.0)
        own = {j: J(bd)[j].get("color") for j in ("shoulder", "elbow")}
        check("tokens: the error and the warn colours differ and are not a joint's own", len({err, warn, *own.values()}) == 4 and None not in own.values(), (err, warn, own))
        check("must fail: before any anomaly every joint is ok and keeps its own colour", bool(J(bd)) and all(J(bd)[j].get("state") == "ok" for j in own), bd and bd.get("joints"))
        bd = at(2.0)
        check("must fail: a minor joint_tracking naming the elbow turns the elbow the warn colour; the shoulder is still ok",
              J(bd)["elbow"] == {"state": "warn", "color": warn} and J(bd)["shoulder"].get("state") == "ok"
              and J(bd)["shoulder"].get("color") == own["shoulder"], J(bd))
        bd = at(2.6)
        check("must fail: a major joint_overload naming the shoulder turns the shoulder the error colour; the elbow keeps its warn (at or before the playhead)",
              J(bd)["shoulder"] == {"state": "error", "color": err} and J(bd)["elbow"] == {"state": "warn", "color": warn}, J(bd))
        page.screenshot(path=str(SHOTS / "obs-watch-body-error.png"))
        bd = at(3.5)
        check("must fail: a critical anomaly that names no joint colours none (pose_jump has no joint)",
              J(bd)["shoulder"].get("state") == "error" and J(bd)["elbow"].get("state") == "warn", J(bd))
        bd = at(1.0)
        check("must fail: back before the anomalies the colours go too (the playhead decides, not the order they were seen)",
              all(J(bd)[j].get("state") == "ok" and J(bd)[j].get("color") == own[j] for j in own), J(bd))
        bd = at(2.0)
        check("the pose is still the recorded one (joint values at the playhead): the shoulder's link is turned 0.3 rad",
              abs(bd["joint_upper_quat"][1] - __import__("math").sin(0.15)) < 1e-4, bd["joint_upper_quat"])
        page.emulate_media(color_scheme="light")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'", timeout=5000)
        bd = at(2.6)
        check("must fail: in the light theme the colours are the light theme's tokens",
              J(bd)["shoulder"].get("color") == css_hex("error") and J(bd)["elbow"].get("color") == css_hex("warn") and css_hex("error") != err, (J(bd), css_hex("error"), err))
        lib = b.new_context(viewport={"width": 900, "height": 700}, color_scheme="dark").new_page()
        meshes_asked = []
        lib.on("request", lambda r: meshes_asked.append(r.url) if ".stl" in r.url else None)
        lib.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
        lib.goto(f"{base}/lib/tokens.css")
        lib.set_content('<link rel=stylesheet href="/lib/tokens.css"><main id=m></main>')
        lib.wait_for_function("getComputedStyle(document.documentElement).getPropertyValue('--status-ok') !== ''")
        setup = """async (base) => {
          const THREE = await import('/lib/vendor/three.module.js'), B = await import('/lib/body/body.js');
          const desc = await (await fetch('/api/v1/robots/arm')).json();
          window.THREE = THREE; window.B = B; window.body = await B.createBody(THREE, desc, '/api/v1/');
          return { links: desc.links.map((l) => l.name), n: window.body.drawn() };
        }"""
        made = lib.evaluate(setup)
        asked = len(meshes_asked)
        check("component: createBody on a fresh page fetches each mesh once and draws three links", made["n"] == 3 and asked == 3, (made, meshes_asked))

        pr = lib.evaluate("""() => {
          const body = window.body, g = body.clone({ style: { mode: 'ghost', color: '#ff00ff' } });
          const m = (b) => b.links.upper.children[0];
          return { shared: m(g).geometry === m(body).geometry, meshes: Object.values(g.links).flatMap((l) => l.children).length,
                   mode: g.style().mode, op: m(g).material.opacity, tr: m(g).material.transparent, dw: m(g).material.depthWrite,
                   hex: '#' + m(g).material.color.getHexString(), solid: [m(body).material.opacity, m(body).material.depthWrite],
                   own: '#' + m(body).material.color.getHexString() };
        }""")
        check("must fail: clone({style: 'ghost'}) issues no second fetch and shares the geometries of the first body", len(meshes_asked) == asked and pr["shared"] and pr["meshes"] == 3, (len(meshes_asked), pr))
        check("must fail: the ghost is see-through, writes no depth, wears the colour asked; the body it came from stays solid",
              pr["mode"] == "ghost" and pr["tr"] and 0 < pr["op"] < 1 and pr["dw"] is False and pr["hex"] == "#ff00ff" and pr["solid"] == [1, True] and pr["own"] != "#ff00ff", pr)

        xr = lib.evaluate("""() => {
          const m = window.body.links.fore.children[0], was = [m.material.opacity, m.material.transparent, m.material.depthWrite];
          window.body.setStyle({ mode: 'xray' });
          const x = [m.material.opacity, m.material.transparent, m.material.depthWrite];
          window.body.setStyle({ mode: 'xray', opacity: 0.6 });
          const y = m.material.opacity;
          window.body.setStyle({ mode: 'solid' });
          return { was, x, y, back: [m.material.opacity, m.material.transparent, m.material.depthWrite] };
        }""")
        check("must fail: setStyle('xray') lowers the opacity and stops writing depth; an opacity asked replaces the default; solid restores both",
              xr["was"] == [1, False, True] and xr["x"][0] < 1 and xr["x"][1] is True and xr["x"][2] is False and xr["y"] == 0.6 and xr["back"] == [1, False, True], xr)

        ps = lib.evaluate("() => window.body.parts()")
        by = {p["link"]: p for p in ps}
        check("must fail: parts() lists the arm's links, root first, with the joint each hangs from and 12 triangles per box",
              [p["link"] for p in ps] == ["base", "upper", "fore"] and by["base"]["joint"] is None and by["base"]["parent"] is None and by["base"]["type"] == "root"
              and (by["upper"]["joint"], by["upper"]["parent"], by["upper"]["type"]) == ("shoulder", "base", "revolute")
              and (by["fore"]["joint"], by["fore"]["parent"]) == ("elbow", "upper") and all(p["triangles"] == 12 and p["meshes"] == 1 and p["state"] == "ok" for p in ps), ps)
        check("parts() sizes: each link's box in its own frame, in metres",
              all(abs(a - b) < 1e-5 for a, b in zip(by["upper"]["size"], [0.03, 0.03, 0.15])) and all(abs(a - b) < 1e-5 for a, b in zip(by["base"]["size"], [0.12, 0.12, 0.1])), by["upper"]["size"])

        hl = lib.evaluate("""() => {
          const b = window.body, hex = (l) => '#' + b.links[l].children[0].material.color.getHexString();
          const before = { upper: hex('upper'), fore: hex('fore') };
          b.highlight('upper', { color: '#00ff00' });
          const lit = { upper: hex('upper'), fore: hex('fore') };
          b.highlight(null);
          const off = { upper: hex('upper'), fore: hex('fore') };
          b.isolate('fore');
          const iso = Object.fromEntries(Object.entries(b.links).map(([n, g]) => [n, g.visible]));
          b.isolate(null);
          const all = Object.values(b.links).every((g) => g.visible);
          return { before, lit, off, iso, all };
        }""")
        check("must fail: highlight turns one link the colour asked and leaves the others; highlight(null) gives it back",
              hl["lit"]["upper"] == "#00ff00" and hl["lit"]["fore"] == hl["before"]["fore"] and hl["before"]["upper"] != "#00ff00" and hl["off"] == hl["before"], hl)
        check("must fail: isolate('fore') hides every other link; isolate(null) shows them all",
              hl["iso"] == {"base": False, "upper": False, "fore": True} and hl["all"], hl)

        col = lib.evaluate("() => window.B.tokenColors()")
        check("tokenColors keeps warn and error and gains the other status colours", all(col.get(k) for k in ("ok", "info", "warn", "alert", "error", "unknown", "stale", "neutral", "live")), col)

        lib.evaluate("""() => { window.picked = []; window.insp = null;
          return import('/lib/body/inspector.js').then((I) => { window.insp = I.mountInspector(document.getElementById('m'), window.body, { onSelect: (l, p) => window.picked.push([l, p.joint]) }); }); }""")
        lib.evaluate("() => window.insp.update({ shoulder: 0.3, elbow: -0.2 })")
        rows = lib.evaluate("() => [...document.querySelectorAll('.insp-row')].map((r) => [...r.children].slice(0, 3).map((c) => c.textContent))")
        check("must fail: the inspector lists the parts: link, joint, value (the root has no joint)",
              rows == [["base", "", "–"], ["upper", "shoulder", "0.300"], ["fore", "elbow", "-0.200"]], rows)
        lib.focus(".insp-list")
        active = lambda: lib.evaluate("() => document.getElementById(document.querySelector('.insp-list').getAttribute('aria-activedescendant')).dataset.link")  # noqa: E731
        first = active()
        lib.keyboard.press("ArrowDown")
        lib.keyboard.press("ArrowDown")
        lib.keyboard.press("ArrowDown")
        end = active()
        lib.keyboard.press("ArrowUp")
        check("must fail: arrow keys move the cursor (and stop at the ends); nothing is selected yet",
              (first, end, active()) == ("base", "fore", "upper") and lib.evaluate("() => window.picked.length") == 0
              and lib.evaluate("() => document.querySelectorAll('.insp-row[aria-selected=true]').length") == 0, (first, end, active()))
        lib.keyboard.press("Enter")
        check("must fail: Enter selects the part under the cursor: onSelect fires once with its link and joint, and the row is aria-selected",
              lib.evaluate("() => window.picked") == [["upper", "shoulder"]] and lib.evaluate("() => document.querySelector('.insp-row[aria-selected=true]').dataset.link") == "upper",
              lib.evaluate("() => window.picked"))
        lib.evaluate("() => window.insp.select('fore')")
        check("select(link) marks the row without calling onSelect",
              lib.evaluate("() => document.querySelector('.insp-row[aria-selected=true]').dataset.link") == "fore" and lib.evaluate("() => window.picked.length") == 1)
        lib.evaluate("() => { window.body.health({ elbow: { state: 'warn' } }, window.B.tokenColors()); window.insp.update({ shoulder: 0.3, elbow: -0.2 }); }")
        badge = lib.evaluate("() => { const b = document.querySelector('.insp-row[data-link=fore] .ui-badge'); return b && [b.dataset.status, b.textContent]; }")
        check("a joint that is not ok shows its status badge, glyph and word", badge is not None and badge[0] == "warn" and "warning" in badge[1], badge)

        errs = [m for m in logs if "favicon" not in m]
        check("no console errors or warnings, and no failed request", not errs, errs[:5])
    finally:
        httpd.shutdown()
        b.close()

check.done()
