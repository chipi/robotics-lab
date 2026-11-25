"""The Observatory's timeline lanes (look-and-feel round 3) in headless Chromium: lanes grouped by section (World, Body, Senses, Mind), each section a header
lane that folds to one summary lane (the union of its streams' presence, its worst event), the fold kept in the layout store; the data inside the bars (a
sparkline for a signal, the sample density for a stream, so a gap is a hole); the streams a run lacks folded into one line per section; the events and alarms
lane on top; the lanes an event concerns lit while the playhead is on it and the rest receding; a muted tone per section from the tokens; reduced motion and
a phone width.
Run: cd apps/observatory && uv run python tests/test_look_lanes_pages.py"""

import atexit
import os
import re
import shutil
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
atexit.register(shutil.rmtree, TMP, True)
os.environ["MINIVIEW_ROBOTS"] = str(TMP / "robots")

from playwright.sync_api import TimeoutError as PWTimeout  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import Checks, boot, catalog, make_run, scene, serve, tick  # noqa: E402
from observatory.shots import launch  # noqa: E402

check = Checks("LOOK LANES PAGES")
SHOTS = Path(os.environ["LANES_SHOTS"]) if os.environ.get("LANES_SHOTS") else None
WEB = Path(__file__).resolve().parents[1] / "web" / "shell"

ARM = """<robot name="arm">
  <link name="base"/><link name="upper"/>
  <joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 1 0"/><limit lower="-1.5" upper="1.5"/></joint>
</robot>"""
arm = TMP / "robots" / "arm"
arm.mkdir(parents=True)
(arm / "robot.urdf").write_text(ARM)
(arm / "robot.json").write_text('{"label": "Test arm"}')

N = 45                                   # ticks and samples, every 0.1 s: t = 0 .. 4.4
DEPTH_GAP = (1.6, 2.4)                   # no depth return in these ticks
LOAD_GAP = (1.5, 2.5)                    # the `load` signal has no value in these samples
LO_T, HI_T = 0.5, 3.5                    # the shoulder's lowest and highest samples


def shoulder(k):
    if k <= 5:
        return -0.9 * k / 5
    if k <= 35:
        return -0.9 + (1.45 + 0.9) * (k - 5) / 30
    return 1.45 - 0.95 * (k - 35) / 9


def anomaly(t, name, severity, source, belief):
    raw = {"event": "anomaly", "anomaly": name, "source": source, "module": "mapd", "severity": severity, "detector": f"{name}_rule", "version": 1,
           "summary": f"{name}: made up for the test", "values": {}, "margin": 0.1, "where": {"frame": "map", "belief": belief}, "evidence": {}, "related": [], "duration_s": 0.2}
    return (t, "event", {"kind": "anomaly", "text": f"anomaly {name} ({severity})", "notable": True, "t_src": t, "raw": raw})


def event(t, kind):
    return (t, "event", {"kind": kind, "text": f"{kind} at {t}", "notable": True, "t_src": t, "raw": {}})


records = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]
for k in range(N):
    t = round(0.1 * k, 3)
    in_gap = DEPTH_GAP[0] - 1e-9 <= t <= DEPTH_GAP[1] + 1e-9
    depth = [] if in_gap else [[0.05 * k + 0.4, 0.0, 0.0, "o"], [0.05 * k + 0.2, 0.1, 0.0, "f"]]
    records.append(tick(t, 0.05 * k, belief=[0.05 * k, 0.0, 0.0], truth=[0.05 * k + 0.02, 0.0, 0.0], depth=depth))
    vals = {"joint_shoulder": round(shoulder(k), 4)}
    if not (LOAD_GAP[0] - 1e-9 <= t <= LOAD_GAP[1] + 1e-9):
        vals["load"] = round(0.3 + 0.006 * k, 4)
    records.append((t, "signals", {"values": vals, "t_src": t}))
records += [event(1.5, "cliff_stop"), event(3.0, "reached"), anomaly(3.9, "pose_jump", "major", "robot", [0.2, 0.0]), (4.5, "end", {"verdict": "reached"})]
records.sort(key=lambda r: r[0])
SIGS = [{"name": "joint_shoulder", "kind": "number", "unit": "rad"}, {"name": "load", "kind": "number", "unit": "A"}]

data = TMP / "data"
cat = catalog(data)
cat.put_scene(scene("room"))
make_run(data, "arm/room/r1", records, signals=SIGS)
cat.scan()
httpd, base = serve(cat, follow=False)

LAYOUT = "(() => { const s = JSON.parse(localStorage.getItem('rl.layouts.observatory') || 'null'); const c = localStorage.getItem('rl.layout.current.observatory'); return s && s.layouts[c] ? s.layouts[c].panels.open : {}; })()"
# the highest and the last non-transparent pixel of a row's drawing at a time's column (three columns wide): the lanes are one canvas, a row is a band of it
PIX = """(a) => {
  const [rowSel, t, thr] = a, row = document.querySelector(rowSel), cv = document.querySelector('#dlanes canvas.lanes-cv');
  if (!row || !cv) return null;
  const [t0, t1] = window.miniview.state().t_range, pad = Math.max(0.05, 0.012 * (t1 - t0)), cr = cv.getBoundingClientRect(), rr = row.getBoundingClientRect();
  const k = cv.width / cr.width, x = Math.round(((t - (t0 - pad)) / (t1 - t0 + 2 * pad)) * cr.width * k), y0 = Math.round((rr.top - cr.top) * k), h = Math.round(rr.height * k);
  const c2 = document.createElement('canvas'); c2.width = cv.width; c2.height = cv.height;     // a copy made for reading: the page's own context stays quiet
  const g = c2.getContext('2d', { willReadFrequently: true }); g.drawImage(cv, 0, 0);
  const d = g.getImageData(Math.max(0, x - 1), y0, 3, h).data;
  let a_ = 0, top = -1;
  for (let y = 0; y < h; y++) { let m = 0; for (let c = 0; c < 3; c++) m = Math.max(m, d[(y * 3 + c) * 4 + 3]); if (m > thr) { a_ = Math.max(a_, m); if (top < 0) top = y; } }
  return { a: a_, top: top < 0 ? null : top / k, h: rr.height };
}"""
ST = "window.miniview.state()"


def px(pg, row, t, thr=40):
    return pg.evaluate(PIX, [row, t, thr])


def opened(pg, w=1440, h=900, pre=None):
    pg.set_viewport_size({"width": w, "height": h})
    boot(pg, base + "/web/three/")
    if pre:
        pg.evaluate(pre)
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true")
    try:
        pg.wait_for_function("document.querySelectorAll('#lanesL .lane-s').length > 0", timeout=3000)
    except PWTimeout:
        pass                                     # the checks below say what is missing


def ready_lanes(pg, n=1):
    pg.wait_for_function(f"document.querySelectorAll('#dlanes canvas.lanes-cv').length === {n}")


def fold(pg, sec, want):
    cur = pg.evaluate(f"document.querySelector('#lanesL .lane-s[data-fold=\"{sec}\"]').getAttribute('aria-expanded') === 'true'")
    if cur != want:
        pg.click(f"#lanesL .lane-s[data-fold='{sec}']")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.set_default_timeout(15000)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    opened(pg)
    t0, t1 = pg.evaluate(ST + ".t_range")

    # ---- sections: a header lane each, folded except where the selected stream lives
    heads = pg.evaluate("[...document.querySelectorAll('#lanesL .lane-s')].map((h) => [h.dataset.fold, h.querySelector('.nm').textContent, h.getAttribute('aria-expanded')])")
    check("each outliner section is a header lane: World, Body, Senses, Mind (and Other values for the loose signal)",
          [h[1] for h in heads][:4] == ["World", "Body", "Senses", "Mind"] and heads[-1][1] == "Other values", heads)
    exp = {h[0]: h[2] for h in heads}
    check("the sections are folded except the one the selected stream (belief.pose) lives in",
          exp["sec.mind"] == "true" and all(v == "false" for k, v in exp.items() if k != "sec.mind"), exp)
    check("a folded section shows no stream lanes; an open one shows its own",
          pg.evaluate("!document.querySelector('#lanesL .lane-l[data-lane=\"sensors.depth.floor\"]') && !document.querySelector('#lanesL .lane-l[data-lane=\"signals.joint_shoulder\"]')")
          and pg.evaluate("!!document.querySelector('#lanesL .lane-l[data-lane=\"belief.pose\"]')"))
    check("one canvas draws the data of every lane (not a node per sample)", pg.evaluate("document.querySelectorAll('#dlanes canvas').length") == 1
          and pg.evaluate("document.querySelectorAll('#dlanes *').length") < 60)
    check("nothing is stored until a viewer folds or opens a section", pg.evaluate(LAYOUT) == {}, pg.evaluate(LAYOUT))

    # ---- the fold is kept in the layout store (open map, key lane:<section>) and survives a reload
    fold(pg, "sec.senses", True)
    fold(pg, "sec.mind", False)
    check("opening Senses shows its streams; folding Mind hides its", pg.evaluate("!!document.querySelector('#lanesL .lane-l[data-lane=\"sensors.depth.floor\"]') && !document.querySelector('#lanesL .lane-l[data-lane=\"belief.pose\"]')"))
    op = pg.evaluate(LAYOUT)
    check("the fold is saved in the layout store, not a key of its own", op.get("lane:sec.senses") is True and op.get("lane:sec.mind") is False, op)
    check("a header says whether it is open (aria-expanded) and a click flips it back", pg.evaluate("document.querySelector('#lanesL .lane-s[data-fold=\"sec.senses\"]').getAttribute('aria-expanded')") == "true")
    pg.reload()
    pg.wait_for_function("window.miniview !== undefined && window.__ready === true")
    pg.evaluate("window.__ready = false; window.miniview.load('room', 'arm/room/r1')")
    pg.wait_for_function("window.__ready === true && document.querySelectorAll('#lanesL .lane-s').length > 0")
    exp = pg.evaluate("Object.fromEntries([...document.querySelectorAll('#lanesL .lane-s')].map((h) => [h.dataset.fold, h.getAttribute('aria-expanded')]))")
    check("after a reload Senses is still open and Mind still folded", exp["sec.senses"] == "true" and exp["sec.mind"] == "false", exp)
    pg.focus("#lanesL .lane-s[data-fold='sec.world']")
    pg.keyboard.press("Enter")
    check("a header is a button: the keyboard opens it", pg.evaluate("document.querySelector('#lanesL .lane-s[data-fold=\"sec.world\"]').getAttribute('aria-expanded')") == "true")
    pg.keyboard.press("Space")
    check("... and Space folds it again", pg.evaluate("document.querySelector('#lanesL .lane-s[data-fold=\"sec.world\"]').getAttribute('aria-expanded')") == "false")

    # ---- the linked cursor still works, and a lane click selects its stream (and the outliner's click selects the lane)
    pg.evaluate("window.miniview.setTime(2.0)")
    ph = pg.evaluate("document.getElementById('ph').getBoundingClientRect().left")
    cr = pg.evaluate("(() => { const r = document.querySelector('#dlanes canvas.lanes-cv').getBoundingClientRect(); return [r.left, r.width]; })()")
    t0, t1 = pg.evaluate(ST + ".t_range")
    pad = max(0.05, 0.012 * (t1 - t0))
    want = cr[0] + (2.0 - (t0 - pad)) / (t1 - t0 + 2 * pad) * cr[1]
    check("the lanes and the playhead share one time axis (the canvas column of t is the playhead's)", abs(ph - want) < 1.6, (ph, want))
    fold(pg, "sec.body", True)
    pg.click("#lanesL .lane-l[data-lane='signals.joint_shoulder']")
    check("clicking a lane selects its stream in the outliner", pg.evaluate("document.querySelector('#tree .row[aria-selected=\"true\"]')?.dataset.id") == "signals.joint_shoulder")
    check("the selected lane is marked in both columns", pg.evaluate("document.querySelectorAll('#lanesL .lane-l.sel').length") == 1 and pg.evaluate("document.querySelectorAll('#dlanes .dl.sel').length") == 1)
    pg.evaluate("window.miniview.setSection('sec.senses', true)")
    pg.click("#tree .row[data-id='sensors.depth.floor'] .name")
    check("selecting a stream in the outliner selects its lane", pg.evaluate("document.querySelector('#lanesL .lane-l.sel')?.dataset.lane") == "sensors.depth.floor")

    # ---- the data inside the bars
    fold(pg, "sec.senses", True)
    fold(pg, "sec.body", True)
    fold(pg, "sec.mind", True)
    pg.wait_for_timeout(100)
    row = "#dlanes .dl[data-lane='signals.joint_shoulder']"
    hi, mid, lo = px(pg, row, HI_T, 90), px(pg, row, 2.0, 90), px(pg, row, LO_T, 90)
    check("a signal's lane draws its values: the line is high where the value is high and low where it is low",
          hi and lo and mid and hi["top"] is not None and lo["top"] is not None and hi["top"] < mid["top"] < lo["top"] and lo["top"] - hi["top"] > 6, (hi, mid, lo))
    fold(pg, "sec.other", True)
    row = "#dlanes .dl[data-lane='signals.load']"
    inside, hole, after = px(pg, row, 1.0), px(pg, row, 2.0), px(pg, row, 3.0)
    check("a signal that has no value for a while is a hole in its lane, not a bar across it",
          inside and inside["a"] > 0 and after["a"] > 0 and hole["a"] == 0, (inside, hole, after))
    row = "#dlanes .dl[data-lane='sensors.depth.floor']"
    a, g_, c = px(pg, row, 1.0), px(pg, row, 2.0), px(pg, row, 3.2)
    check("a sensor lane draws its sample density: a dropout in the returns is a hole in it", a and a["a"] > 0 and c["a"] > 0 and g_["a"] == 0, (a, g_, c))
    hgt = px(pg, row, 1.0)["top"], px(pg, row, 1.0)["h"]
    check("... as bars that stand on the lane (their top is inside it, not a full-height band)", hgt[0] is not None and 0 <= hgt[0] < hgt[1], hgt)
    # the summary lane of Senses is the union of its streams: present where either has data, a hole where neither does
    pg.evaluate("document.querySelector('#lanesL .lane-s[data-fold=\"sec.senses\"]').click()")
    fold(pg, "sec.senses", False)
    sm = "#dlanes .dl.sec[data-sec='sec.senses']"
    s1, s2, s3 = px(pg, sm, 0.5), px(pg, sm, 3.4), px(pg, sm, 2.0)
    check("a folded section is one summary lane covering its streams' spans, with a hole where none of them has data",
          s1["a"] > 0 and s2["a"] > 0 and s3["a"] == 0, (s1, s2, s3))
    fold(pg, "sec.mind", True)
    m = px(pg, "#dlanes .dl.sec[data-sec='sec.mind']", 2.0)
    check("a summary lane follows the run's own spans (Mind has the belief pose all through the gap)", m["a"] > 0, m)
    fold(pg, "sec.mind", False)

    # ---- the worst event of a section sits on its summary lane, with a glyph and a word in the label
    lab = pg.evaluate("[...document.querySelectorAll('#lanesL .lane-s')].map((h) => [h.dataset.fold, h.getAttribute('aria-label'), h.querySelector('.flag')?.dataset.status || null, h.querySelector('.flag .ui-glyph')?.textContent || null])")
    senses = [x for x in lab if x[0] == "sec.senses"][0]
    check("the section a stop concerns carries its worst status: a glyph and a word, never colour alone",
          senses[2] == "error" and senses[3] == "✕" and "error" in senses[1] and "cliff_stop" in senses[1], senses)
    body = [x for x in lab if x[0] == "sec.body"][0]
    check("a joint that comes within its limits is flagged on its own lane and on its section (warn: a triangle and its word)",
          body[2] == "warn" and body[3] == "▲" and "warning" in body[1], body)

    # ---- the streams the run lacks: one line per section
    fold(pg, "sec.senses", True)
    fold(pg, "sec.mind", True)
    miss = pg.evaluate("[...document.querySelectorAll('#lanesL .lane-m')].map((m) => [m.dataset.miss, +m.dataset.n, m.textContent.trim(), m.getAttribute('aria-expanded')])")
    check("the streams a run lacks are one quiet line per section, with their number", miss and all(re.fullmatch(rf"{n} streams? not in this run", t) for _, n, t, _ in miss) and all(e == "false" for *_, e in miss), miss)
    check("... and no lane of its own while it is folded", pg.evaluate("document.querySelectorAll('#lanesL .lane-l.missing').length") == 0 and pg.evaluate("document.querySelectorAll('#dlanes .dl.missing').length") == 0)
    sen = [m for m in miss if m[0] == "sec.senses"][0]
    pg.click("#lanesL .lane-m[data-miss='sec.senses']")
    check("a click lists them: one dim lane each, saying why it is missing", pg.evaluate("document.querySelectorAll('#lanesL .lane-l.missing[data-sec=\"sec.senses\"]').length") == sen[1] >= 2
          and pg.evaluate("document.querySelectorAll('#dlanes .dl.missing').length") == sen[1], sen)
    check("... and the choice is kept in the layout store", pg.evaluate(LAYOUT).get("lanemiss:sec.senses") is True, pg.evaluate(LAYOUT))
    pg.click("#lanesL .lane-m[data-miss='sec.senses']")

    # ---- the events and alarms lane is on top, above the sections; its marks, jumps and keys work
    order = pg.evaluate("(() => { const y = (s) => document.querySelector(s).getBoundingClientRect().top; return [y('#mlane'), y('#alane'), y('#lanes')]; })()")
    check("the events lane and the alarms lane sit above the section lanes", order[0] < order[2] and order[1] < order[2], order)
    kinds = pg.evaluate("[...document.querySelectorAll('#mlane .mk')].map((m) => m.dataset.kind).sort()")
    check("every event is a mark by kind on the events lane", kinds == ["anomaly", "cliff_stop", "reached"], kinds)
    al = pg.evaluate("[...document.querySelectorAll('#alane .mk.al')].map((m) => ({ g: m.querySelector('.g')?.textContent, label: m.getAttribute('aria-label'), role: m.getAttribute('role') }))")
    check("an alarm is emphasised with its status glyph and a label that says its severity and its status", len(al) == 1 and al[0]["g"] == "✕" and "major" in al[0]["label"] and "error" in al[0]["label"], al)
    pg.evaluate("window.miniview.setTime(0.2)")
    j = pg.evaluate("window.miniview.jump(1, 'cliff_stop')")
    pg.evaluate("window.miniview.setTime(0.2)")
    pg.keyboard.press(".")
    k1 = pg.evaluate(ST + ".t")
    pg.keyboard.press(".")
    k2 = pg.evaluate(ST + ".t")
    pg.keyboard.press(",")
    k3 = pg.evaluate(ST + ".t")
    check("the jump API and the , . keys still land on the marks", abs(j - 1.5) < 1e-6 and abs(k1 - 1.5) < 1e-6 and abs(k2 - 3.0) < 1e-6 and abs(k3 - 1.5) < 1e-6, (j, k1, k2, k3))

    # ---- the lanes an event concerns are lit while the playhead is on it, the rest recede
    fold(pg, "sec.senses", True)
    fold(pg, "sec.body", True)
    fold(pg, "sec.mind", True)
    pg.evaluate("window.miniview.setTime(1.5)")
    near = pg.evaluate("""(() => { const q = (s) => [...document.querySelectorAll(s)].map((e) => e.dataset.lane || e.dataset.fold);
      return { near: document.getElementById('lanes').dataset.near ?? null, hl: q('#lanesL .hl'), rec: q('#lanesL .rec'), hlR: q('#dlanes .hl').length, mark: document.querySelector('#mlane .mk.near')?.dataset.kind ?? null }; })()""")
    check("on a stop, the lanes it concerns (the depth returns, the belief pose, the Senses and Mind headers) are lit",
          near["near"] is not None and {"sensors.depth.floor", "sensors.depth.obstacle", "belief.pose", "sec.senses", "sec.mind"} <= set(near["hl"]) and near["hlR"] >= 5, near)
    check("... the lanes it does not concern recede (the joint, the Body header), and its mark says it is the one", {"signals.joint_shoulder", "sec.body"} <= set(near["rec"]) and not set(near["rec"]) & set(near["hl"]) and near["mark"] == "cliff_stop", near)
    pg.evaluate("window.miniview.setTime(0.8)")
    far = pg.evaluate("({ near: document.getElementById('lanes').dataset.near ?? null, hl: document.querySelectorAll('#lanesL .hl').length, rec: document.querySelectorAll('#lanesL .rec').length })")
    check("away from every event nothing is lit and nothing recedes", far == {"near": None, "hl": 0, "rec": 0}, far)
    pg.evaluate("window.miniview.setTime(3.0)")
    moves = pg.evaluate("({ hl: [...document.querySelectorAll('#lanesL .hl')].map((e) => e.dataset.lane || e.dataset.fold), rec: [...document.querySelectorAll('#lanesL .rec')].map((e) => e.dataset.lane || e.dataset.fold) })")
    check("on a motion event (reached) the belief pose and the joints are lit and the depth lanes recede", {"belief.pose", "signals.joint_shoulder"} <= set(moves["hl"]) and "sensors.depth.floor" in moves["rec"], moves)

    # ---- tone: a muted tone per section from the tokens; colour for attention
    tones = pg.evaluate("[...document.querySelectorAll('#lanesL .lane-s')].map((h) => h.style.getPropertyValue('--tone').trim())")
    check("each section has its own tone, taken from the categorical ramp tokens (no literal colour)", len(set(tones[:4])) == 4 and all(t.startswith("var(--ramp-cat-") for t in tones[:4]), tones)
    css = (WEB / "shell.css").read_text()
    block = css[css.index("/* lanes */"):css.index("/* end lanes */")]
    src = (WEB / "lanes.js").read_text()
    lit = re.compile(r"#[0-9a-fA-F]{3,8}\b|\bhsla?\(|\boklch\(|\blab\(")
    check("no hex, hsl, oklch or lab literal in lanes.js or in its stylesheet block", not lit.findall(src) and not lit.findall(block), (lit.findall(src)[:3], lit.findall(block)[:3]))

    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
        pg.evaluate("window.miniview.setTime(1.5)")
        pg.screenshot(path=str(SHOTS / "lanes-dark-1440.png"))
    check("no console or page error", not errs, errs)

    # ---- reduced motion, and a transition that does follow the motion token when motion is full
    pg.evaluate("document.documentElement.dataset.motion = 'full'")
    full = pg.evaluate("getComputedStyle(document.querySelector('#dlanes .dl')).transitionDuration")
    pg.evaluate("document.documentElement.dataset.motion = 'reduce'")
    red = pg.evaluate("[...document.querySelectorAll('#lanesL .lane-l, #lanesL .lane-s, #dlanes .dl')].map((e) => getComputedStyle(e).transitionDuration + '/' + getComputedStyle(e).animationName)")
    check("the lanes' fades take the motion token's time, and none under reduced motion",
          full not in ("0s", "") and all(set(x.split("/")[0].split(", ")) == {"0s"} and x.endswith("/none") for x in red), (full, set(red)))
    ctx.close()

    # ---- light
    cl = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
    lp = cl.new_page()
    lp.set_default_timeout(15000)
    opened(lp)
    fold(lp, "sec.body", True)
    fold(lp, "sec.senses", True)
    lp.wait_for_timeout(100)
    row = "#dlanes .dl[data-lane='signals.joint_shoulder']"
    hi, lo = px(lp, row, HI_T, 90), px(lp, row, LO_T, 90)
    check("light theme: the same lanes draw, the sparkline still follows the data", hi["top"] is not None and lo["top"] is not None and hi["top"] < lo["top"], (hi, lo))
    if SHOTS:
        lp.evaluate("window.miniview.setTime(1.5)")
        lp.screenshot(path=str(SHOTS / "lanes-light-1440.png"))
    cl.close()

    # ---- a phone: no sideways scroll, the lanes inside the screen, their names on the lanes
    cp = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", is_mobile=True, device_scale_factor=2)
    pp = cp.new_page()
    pp.set_default_timeout(15000)
    opened(pp, 390, 844)
    pp.wait_for_timeout(150)
    ph_ = pp.evaluate("""(() => { const cv = document.querySelector('#dlanes canvas.lanes-cv').getBoundingClientRect();
      const names = [...document.querySelectorAll('#dlanes .dl.sec .dl-name')].map((n) => { const r = n.getBoundingClientRect(); return [n.textContent.trim(), r.left >= 0 && r.right <= 390 && r.width > 0, getComputedStyle(n).display]; });
      return { sw: document.documentElement.scrollWidth, cw: cv.width, cl: cv.left, names }; })()""")
    check("at 390 px there is no sideways scroll and the lanes fit the screen", ph_["sw"] <= 390 and ph_["cl"] >= 0 and ph_["cl"] + ph_["cw"] <= 390.5, ph_)
    check("... the section names are on their lanes (the label column is gone)", [n[0] for n in ph_["names"]][:4] == ["World", "Body", "Senses", "Mind"] and all(n[1] and n[2] != "none" for n in ph_["names"]), ph_["names"])
    pp.evaluate("document.querySelector('#dlanes .dl.sec[data-sec=\"sec.senses\"] .dl-name').click()")
    check("a tap on a section name on the lane opens it", pp.evaluate("document.querySelector('#dlanes .dl[data-lane=\"sensors.depth.floor\"] .dl-name')?.textContent.trim()") not in (None, ""))
    check("... and the page still does not scroll sideways", pp.evaluate("document.documentElement.scrollWidth") <= 390)
    if SHOTS:
        pp.screenshot(path=str(SHOTS / "lanes-dark-390.png"), full_page=False)
    cp.close()
    b.close()

check.done()
