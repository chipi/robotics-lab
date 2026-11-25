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

from helpers import Checks, catalog, make_run, scene, serve  # noqa: E402
from observatory.shots import launch  # noqa: E402

check = Checks("LOOK SIGNALS PAGES")
SHELL = Path(__file__).resolve().parents[1] / "web" / "shell"
SHOTS = Path(os.environ["U15_SHOTS"]) if os.environ.get("U15_SHOTS") else None      # a folder to leave screenshots in

ARM = """<robot name="arm">
  <link name="base"/><link name="upper"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
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

data = TMP / "data"
cat = catalog(data)
cat.put_scene(scene("room"))
make_run(data, "arm/room/r1", records, signals=SIGS)
cat.scan()
httpd, base = serve(cat, follow=False)

with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/web/three/")
    pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true")
    pg.wait_for_function("document.querySelectorAll('#sigview .sg').length === 4")

    def SG(name):
        return f"document.querySelector('#sigview .sg[data-sig=\"signals.{name}\"]')"

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
    check("the ink on a cell is chosen by the cell's lightness: light on dark, dark on light", r["inkOnDark"] != r["inkOnLight"] and "255" in r["inkOnDark"] and "0 0 0" in r["inkOnLight"], r)
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

    check("no page error", not errs, errs)
    b.close()
httpd.shutdown()
check.done()
