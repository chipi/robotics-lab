"""The Observatory's signals (step 4.5, U15) in headless Chromium: threshold bands on a signal plot (the limits a robot's description gives a
joint: a warn band near each limit, an error band beyond it, each with a glyph and a word), state-duration bars (a text signal, and a numeric
one that only takes a few whole values, drawn as coloured spans with their durations), and the token ramps (no hand-made colour in the plots
or in the depth colour scale), in both themes and under reduced motion.
Run: cd apps/observatory && uv run python tests/test_look_signals_pages.py"""

import atexit
import os
import re
import shutil
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, TMP, True)
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, boot, catalog, make_run, scene, serve, tick  # noqa: E402
from observatory.shots import launch  # noqa: E402

check = Checks("LOOK SIGNALS PAGES")
SHELL = Path(__file__).resolve().parents[1] / "web" / "shell"
SHOTS = Path(os.environ["U15_SHOTS"]) if os.environ.get("U15_SHOTS") else None      # a folder to leave screenshots in

ARM = """<robot name="arm">
  <link name="base"/><link name="upper"/><link name="fore"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
  <joint name="elbow" type="revolute"><parent link="upper"/><child link="fore"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
arm.mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm"}')

SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "load", "kind": "number", "unit": "A"},
        {"name": "lock", "kind": "number"}, {"name": "mode", "kind": "text"}]
N = 40
records = []
for k in range(N):
    t = round(0.1 * k, 3)
    # the shoulder rises from 0 to 1.65: through the warn band (1.35 to 1.5) and past the limit
    records.append((t, "signals", {"values": {"joint_shoulder": round(1.65 * k / (N - 1), 4), "load": round(0.3 + (0.37 * k) % 0.7, 3),
                                              "lock": 1 if 10 <= k < 25 else 0, "mode": "idle" if k < 8 else "drive" if k < 30 else "idle"}, "t_src": t}))
records.append((4.1, "end", {"verdict": "recorded"}))

# a run with a pose as well (ticks beside the samples); the elbow has no unit and only ever reads 0 or 1 rad: an angle, not a state
SIGS2 = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "joint_elbow", "kind": "number"}]
records2 = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
for k in range(30):
    t = round(0.1 * k, 3)
    records2.append(tick(t, 0.02 * k))
    records2.append((t, "signals", {"values": {"joint_shoulder": round(1.65 * k / 29, 4), "joint_elbow": float(k % 2)}, "t_src": t}))
records2.append((3.1, "end", {"verdict": "recorded"}))

data = TMP / "data"
cat = catalog(data)
cat.put_scene(scene("room"))
make_run(data, "arm/room/r1", records, signals=SIGS)
make_run(data, "arm/room/r2", records2, signals=SIGS2)
cat.scan()
httpd, base = serve(cat, follow=False)

with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    boot(pg, base + "/web/three/")
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true")
    pg.wait_for_function("document.querySelectorAll('#sigview .sg').length === 4")

    def SG(name):
        return f"document.querySelector('#sigview .sg[data-sig=\"signals.{name}\"]')"

    def overlaps(page, plot):
        return page.evaluate(f"""(() => {{ const b = [...{plot}.querySelectorAll('.tbl')].map((t) => [t.textContent, t.getBoundingClientRect()]), out = [];
          for (let i = 0; i < b.length; i++) for (let j = i + 1; j < b.length; j++) {{ const p = b[i][1], q = b[j][1];
            if (p.left < q.right && q.left < p.right && p.top < q.bottom && q.top < p.bottom) out.push([b[i][0], b[j][0]]); }}
          return out; }})()""")

    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(SHOTS / "observatory-signals-dark-1440.png"))
    bands = pg.evaluate(f"[...{SG('joint_shoulder')}.querySelectorAll('rect.tband')].map((r) => [r.dataset.status, r.dataset.side, +r.getAttribute('y'), +r.getAttribute('height')])")

    # ---- threshold bands
    check("a joint signal draws a warn band and an error band at each limit its description gives (four bands)",
          sorted((s, d) for s, d, *_ in bands) == [("error", "lower"), ("error", "upper"), ("warn", "lower"), ("warn", "upper")], bands)
    ys = {(s, d): (y, h) for s, d, y, h in bands}
    check("the bands sit in order down the plot: error above the upper limit, warn just inside it, then the lower side",
          len(ys) == 4 and ys[("error", "upper")][0] < ys[("warn", "upper")][0] < ys[("warn", "lower")][0] < ys[("error", "lower")][0], ys)
    lab = pg.evaluate(f"[...{SG('joint_shoulder')}.querySelectorAll('.tbl')].map((t) => [t.dataset.status, t.textContent])")
    check("a band is never colour alone: each status has a label with its glyph and its word",
          {s for s, _ in lab} >= {"warn", "error"} and all(re.search(r"[▲✕]", tx) and re.search(r"near|beyond", tx) for _, tx in lab), lab)
    lims = pg.evaluate(f"[...{SG('joint_shoulder')}.querySelectorAll('line.tlim')].map((l) => l.dataset.limit)")
    check("the limit lines say the limit", lims == ["1.5", "-1.5"], lims)
    check("no two limit labels of a plot overlap (the four at the right edge once piled up)", not overlaps(pg, SG('joint_shoulder')), overlaps(pg, SG('joint_shoulder')))
    rng = pg.evaluate(f"[...{SG('joint_shoulder')}.querySelectorAll('.sg-r span')].map((s) => parseFloat(s.textContent.replace('−', '-')))")
    check("the plot's range reaches past both limits, so the error bands can be seen", len(rng) == 2 and rng[0] > 1.5 and rng[1] < -1.5, rng)
    check("the band is the status colour from the tokens, not a hand-made one",
          pg.evaluate(f"(() => {{ const a = [...{SG('joint_shoulder')}.querySelectorAll('rect.tband')]; return a.length > 0 && a.every((r) => r.getAttribute('fill') === `var(--status-${{r.dataset.status}}-soft)`); }})()"))
    check("a signal with no limits (a current) and a text signal draw no band", pg.evaluate(f"{SG('load')}.querySelectorAll('.tband').length") == 0
          and pg.evaluate(f"{SG('mode')}.querySelectorAll('.tband').length") == 0)

    # ---- state-duration bars
    mode = pg.evaluate(f"[...{SG('mode')}.querySelectorAll('rect.band')].map((r) => [r.dataset.state, r.getAttribute('fill'), r.querySelector('title')?.textContent])")
    check("a text signal is one coloured span per state (idle, drive, idle)", [m[0] for m in mode] == ["idle", "drive", "idle"], mode)
    check("a span says its state and how long it lasted", len(mode) == 3 and (mode[1][2] or "").startswith("drive") and "2.2 s" in (mode[1][2] or "") and "0.8 s" in (mode[0][2] or ""), mode)
    check("the same state has the same colour, a different state another, both from the categorical ramp",
          len(mode) == 3 and mode[0][1] == mode[2][1] and mode[0][1] != mode[1][1] and all(re.fullmatch(r"var\(--ramp-cat-[1-8]\)", m[1] or "") for m in mode), mode)
    lock = pg.evaluate(f"({SG('lock')}.dataset.form) + '|' + {SG('lock')}.querySelectorAll('path.line').length + '|' + [...{SG('lock')}.querySelectorAll('rect.band')].map((r) => r.dataset.state).join(',')")
    check("a numeric signal that only takes a few whole values (a lock) is drawn as spans, not a line", lock == "state|0|0,1,0", lock)
    check("a continuous signal keeps its line", pg.evaluate(f"{SG('load')}.querySelectorAll('path.line').length") == 1 and pg.evaluate(f"{SG('load')}.dataset.form") == "line")

    # ---- ramps
    handmade = pg.evaluate("""[...document.querySelectorAll('#sigview svg *')].flatMap((e) => ['fill', 'stroke'].map((a) => [e.getAttribute(a), e.tagName + '.' + a]))
      .filter(([v]) => v && /^(#|hsl|rgb)/i.test(v))""")
    check("no plot colour in the signals view is a hex, hsl or rgb literal: all are token variables", not handmade, handmade[:3])
    swatch = pg.evaluate(f"({SG('joint_shoulder')}.querySelector('i.sw').style.background)")
    line = pg.evaluate(f"({SG('joint_shoulder')}.querySelector('path.line').getAttribute('stroke'))")
    check("a signal's line and its swatch are one categorical ramp colour", re.fullmatch(r"var\(--ramp-cat-[1-8]\)", line or "") and swatch.replace(" ", "") == (line or "").replace(" ", ""), (line, swatch))
    RES = "(v) => { const e = document.createElement('i'); e.style.color = v; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; }"
    DRIVE = f"getComputedStyle({SG('mode')}.querySelector('rect.band[data-state=drive]')).fill"
    drive_fill = pg.evaluate(DRIVE)
    want = pg.evaluate(RES, mode[1][1]) if len(mode) == 3 else None
    check("a band's drawn colour is the ramp token's value", drive_fill == want, (drive_fill, want))
    pg.click("#themeBtn")
    pg.wait_for_function("document.documentElement.dataset.theme === 'light'")
    light_fill = pg.evaluate(DRIVE)
    check("switching theme changes the ramp colour with the tokens", light_fill != drive_fill, (drive_fill, light_fill))

    LIB = """async () => { const m = await import('/web/shell/sigviz.js'); const rgb = (s) => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
      const lum = (c) => { const [r, g, b] = c.map((v) => v / 255); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
      const sc = m.seqScale(), steps = [0, 0.25, 0.5, 0.75, 1].map((f) => sc(f)), v = (n) => { const e = document.createElement('i'); e.style.color = `var(--ramp-seq-${n})`; document.body.append(e);
        const c = getComputedStyle(e).color; e.remove(); return c; };
      return { first: sc(0), last: sc(1), t1: v(1), t9: v(9), lums: steps.map((s) => lum(rgb(s))), inkOnDark: m.inkOn('rgb(20 20 30)'), inkOnLight: m.inkOn('rgb(250 250 250)') }; }"""
    r = pg.evaluate(LIB)
    norm = lambda s: re.findall(r"\d+", s)[:3]  # noqa: E731
    check("the sequential scale runs from the ramp's first stop to its ninth", norm(r["first"]) == norm(r["t1"]) and norm(r["last"]) == norm(r["t9"]), r)
    d = [b_ - a for a, b_ in zip(r["lums"], r["lums"][1:])]
    check("the scale is monotone in lightness", all(x > 0 for x in d) or all(x < 0 for x in d), r["lums"])
    check("the ink on a cell is chosen by the cell's lightness: light on dark, dark on light", r["inkOnDark"] != r["inkOnLight"] and r["inkOnDark"] == "#ffffff" and r["inkOnLight"] == "#000000", r)
    pg.click("#themeBtn")
    pg.wait_for_function("document.documentElement.dataset.theme === 'dark'")

    lit = {f.name: len(re.findall(r"hsl\(", f.read_text())) for f in SHELL.glob("*.js") if "hsl(" in f.read_text()}
    check("no shell module builds a colour with hsl(): the depth colour scales and the signal colours use the ramps", not lit, lit)

    # ---- reduced motion
    pg.emulate_media(reduced_motion="reduce")
    anim = pg.evaluate("[...document.querySelectorAll('#sigview, #sigview *')].map((e) => getComputedStyle(e)).filter((c) => (c.animationName !== 'none' && parseFloat(c.animationDuration) > 0) || parseFloat(c.transitionDuration) > 0).length")
    check("under reduced motion the signals view runs no animation or transition", anim == 0, anim)
    pg.emulate_media(reduced_motion="no-preference")

    # ---- a phone width keeps the bands
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.evaluate("window.miniview.setTime(1.0)")
    n = pg.evaluate("document.querySelectorAll('#sigview .tband').length")
    if SHOTS:
        pg.click("#themeBtn")
        pg.wait_for_function("document.documentElement.dataset.theme === 'light'")
        pg.screenshot(path=str(SHOTS / "observatory-signals-light-390.png"))
        pg.click("#themeBtn")
    check("on a phone width the bands are still drawn", n == 4, n)
    pg.set_viewport_size({"width": 1440, "height": 900})

    # ---- a run with a pose: the Signals view opens beside its other views, and the joints get their bands there too
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r2')")
    pg.wait_for_function("window.__ready === true && window.miniview.state().run === 'arm/room/r2'")
    check("a run with a pose opens on its 3D views, the Signals view closed", pg.evaluate("document.getElementById('sigview').hidden") is True)
    check("... and has a Signals switch in the viewport header, not pressed", pg.evaluate("(() => { const b = document.getElementById('sigBtn'); return !!b && !b.hidden && b.getAttribute('aria-pressed') === 'false'; })()"))
    pg.click("#sigBtn")
    pg.wait_for_function("document.querySelectorAll('#sigview .sg').length === 2")
    check("state() of a run with a pose says the Signals view is shown (signals_view)", pg.evaluate("window.miniview.state().signals_view") is True)
    check("the switch opens the Signals view over the viewport and says so",
          pg.evaluate("!document.getElementById('sigview').hidden && document.getElementById('sigBtn').getAttribute('aria-pressed') === 'true'"))
    check("the top bar's view buttons (Top, Three, 3D) stay, to get back", pg.evaluate("document.querySelectorAll('#layoutSeg button[data-view]').length >= 3 && getComputedStyle(document.getElementById('layoutSeg')).display !== 'none'"))
    check("the joint of a run with a pose has its four bands and limit lines", pg.evaluate(f"{SG('joint_shoulder')}.querySelectorAll('rect.tband').length") == 4
          and pg.evaluate(f"{SG('joint_shoulder')}.querySelectorAll('line.tlim').length") == 2)
    el = pg.evaluate(f"({SG('joint_elbow')}.dataset.form) + '|' + {SG('joint_elbow')}.querySelectorAll('rect.tband').length + '|' + {SG('joint_elbow')}.querySelectorAll('path.line').length")
    check("a joint with no unit that only reads 0 and 1 is an angle: a line with its bands, not state spans", el == "line|4|1", el)
    check("the same four limit labels do not overlap in the pose run's view either", not overlaps(pg, SG('joint_shoulder')) and not overlaps(pg, SG('joint_elbow')),
          (overlaps(pg, SG('joint_shoulder')), overlaps(pg, SG('joint_elbow'))))
    if SHOTS:
        pg.screenshot(path=str(SHOTS / "observatory-signals-pose-dark-1440.png"))
    pg.evaluate("window.miniview.setTime(1.0)")
    check("the playhead moves the plots' readout as it does in a run with no pose", pg.evaluate("document.getElementById('sigview').dataset.t") == "1")
    pg.click("#sigBtn")
    check("... and that it is not, after the second press", pg.evaluate("window.miniview.state().signals_view") is False)
    check("a second press closes the view and gives the viewport back",
          pg.evaluate("document.getElementById('sigview').hidden && document.getElementById('sigBtn').getAttribute('aria-pressed') === 'false'"))
    HEAD_FIT = """(() => { const h = document.querySelector('.vhead'), hr = h.getBoundingClientRect(), bad = [];
      for (const e of h.children) { const r = e.getBoundingClientRect(); if (!r.width || getComputedStyle(e).display === 'none') continue;
        if (r.right > hr.right + 0.5 || r.left < hr.left - 0.5 || r.right > innerWidth + 0.5) bad.push([e.id || e.className, Math.round(r.left), Math.round(r.right)]);
        if (e.tagName === 'BUTTON' && r.width < 24 - 0.5 && innerWidth < 600) bad.push([e.id, 'narrow', r.width]); }
      const vt = document.getElementById('vt'), tr = vt.getBoundingClientRect();
      return { bad, header: [hr.left, hr.right], title: tr.width, titleText: vt.textContent, overflow: document.documentElement.scrollWidth - innerWidth,
               oneLine: tr.top >= hr.top - 0.5 && tr.bottom <= hr.bottom + 0.5 }; })()"""
    for w in (1440, 390):
        pg.set_viewport_size({"width": w, "height": 844})
        pg.evaluate("window.miniview.state()")
        r = pg.evaluate(HEAD_FIT)
        check(f"at {w} px, with the Signals switch showing, every control of the viewport header lies inside it and the window, and the title is not squeezed out or wrapped out of the header",
              pg.evaluate("!document.getElementById('sigBtn').hidden") and not r["bad"] and r["title"] >= 60 and r["oneLine"] and r["overflow"] <= 1, r)
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.evaluate("window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true && window.miniview.state().run === 'arm/room/r1'")
    check("a run with samples and no pose has no switch: its Signals view is the viewport", pg.evaluate("document.getElementById('sigBtn').hidden") is True)

    check("no page error", not errs, errs)
    b.close()
httpd.shutdown()
check.done()
