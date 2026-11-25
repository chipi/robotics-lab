"""The look-and-feel guards of the shared UI kit (step 4.5, units U2 and U3) in headless Chromium: the pages load Inter from the shared
/lib/fonts; every libs/web module (outside vendor/) imports clean; status.js maps what the plan says and every status has a glyph and a word; the
badge shows glyph, word and the status colour; .num is tabular; a button is 24 px tall compact and 36 px regular; reduced motion zeroes the
durations (and setMotion overrides the system); a stale value is dimmed and says its age; mountTopBar fills the brand and nav and leaves STOP alone.
U10 (the Observatory restyle): shell.css has no hex and uses no old token name; the page is compact; at 1440 px no top-bar control is clipped or
wraps, even with long names; a runs list of 5 benign and 1 abnormal verdict shows exactly one coloured verdict (glyph and word, never colour alone);
the live indicator is --status-live, not the error colour; under reduced motion .live-dot has no animation; the theme is read from the legacy
miniview.theme and written to rl.theme.
Run: cd apps/observatory && uv run python tests/test_look_ui_pages.py"""

import re
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, T0_NS, boot, catalog, make_run, scene, serve, tick
from observatory.shots import launch

check = Checks("LOOK UI PAGES")
LIB = Path(__file__).resolve().parents[3] / "libs" / "web"
SHELL_CSS = Path(__file__).resolve().parents[1] / "web" / "shell" / "shell.css"
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]
# the names the tokens kept as aliases until U26: shell.css must use the new ones
OLD_NAMES = ["--bg-app", "--bg-viewport", "--bg-panel", "--bg-header", "--bg-field", "--bg-hover", "--bg-selected", "--bg-shead", "--bg-shead-hover", "--bg-press",
             "--border", "--border-strong", "--border-hover", "--text", "--text-dim", "--text-faint", "--on-accent", "--warn", "--error", "--ok", "--hair",
             "--hair-2", "--hair-3", "--hair-4", "--hair-5", "--veil", "--shadow", "--scrim", "--tip-bg", "--range-bar", "--range-knob", "--check-border",
             "--c-belief", "--c-truth", "--c-plan", "--c-obst", "--c-drop", "--c-floor", "--c-ob", "--c-over", "--c-box", "--c-occ", "--c-free", "--c-x", "--c-y",
             "--c-z", "--c-gap", "--draw-grid", "--draw-label", "--draw-rel", "--draw-sel", "--box-fill", "--gap-hatch", "--ui", "--mono"]

# the plan's verdict mapping (docs/wip/LOOK-AND-FEEL-PLAN.md, "Frozen contracts"), written out value by value
VERDICTS = {
    "ok": ["reached", "done", "evaluated"], "info": ["running", "queued"],
    "neutral": ["ended", "no_frontier_left", "cancelled", "refused", "not_found", "stopped"],
    "warn": ["timeout", "stalled"], "alert": ["stopped_by_guardrail", "trapped"], "error": ["failed", "interrupted"],
}
STATUSES = ["ok", "info", "warn", "alert", "error", "unknown", "stale", "neutral", "live", "offline"]

PAGE = """<!doctype html><html data-theme="dark"><head>
<link rel="stylesheet" href="/lib/tokens.css"><link rel="stylesheet" href="/lib/fonts/fonts.css"><link rel="stylesheet" href="/lib/ui.css">
</head><body>
<span id="badge" class="ui-badge" data-status="warn"><span class="ui-glyph" aria-hidden="true">G</span><span class="ui-word">W</span></span>
<span id="num" class="num">0123</span>
<button id="btn" class="ui-btn">Go</button><button id="btnp" class="ui-btn ui-btn--primary">Run</button><input id="inp" class="ui-input">
<span id="stale" class="ui-stale"><span class="ui-stale-value num">12.4</span><span class="ui-stale-age">5 s ago</span></span>
<div id="probe" style="transition-duration: var(--dur-base)"></div>
<header id="bar" class="ui-topbar"><span data-slot="brand"></span><nav data-slot="nav"></nav><span data-slot="theme"></span>
<span class="stops"><button id="stop" data-stop>STOP</button></span></header>
</body></html>"""

EVAL_ALL = """async (names) => {
  const out = [];
  for (const n of names) {
    const errs = [];
    const onErr = (e) => errs.push(String(e.message || e.reason));
    addEventListener('error', onErr); addEventListener('unhandledrejection', onErr);
    try { await import('/lib/' + n); } catch (e) { errs.push(String(e)); }
    removeEventListener('error', onErr); removeEventListener('unhandledrejection', onErr);
    out.push([n, errs]);
  }
  return out;
}"""

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(8000)
    console = []
    page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console.append(str(e)))
    for path in ("/web/three/", "/web/deck/"):
        page.goto(base + path)
        loaded = page.evaluate("document.fonts.load('400 14px Inter').then(l => l.length)")
        check(f"{path}: the page loads Inter from the shared /lib/fonts", loaded > 0, loaded)
        family = page.evaluate("getComputedStyle(document.body).fontFamily")
        check(f"{path}: the body font-family starts with Inter", family.startswith("Inter"), family)

    # every libs/web module outside vendor/ imports without an error (later units reuse this check, so a new module is covered by being there)
    mods = sorted(str(f.relative_to(LIB)) for f in LIB.rglob("*.js") if "vendor" not in f.relative_to(LIB).parts)
    check("libs/web has modules to import (status, motion, brand at least)", {"status.js", "motion.js", "brand.js"} <= set(mods), mods)
    page.goto(base + "/web/three/")
    console.clear()
    for name, errs in page.evaluate(EVAL_ALL, mods):
        check(f"lib/{name}: imports without an error", not errs, errs)
    check("no console error while the modules imported", not console, console)

    # the kit page: the same origin, so /lib/ resolves
    page.set_content(PAGE)
    page.wait_for_load_state("load")
    settle = "Promise.all(document.getAnimations().filter((a) => a.effect.getComputedTiming().iterations !== Infinity).map((a) => a.finished)).then(() => true)"   # a control restyled by a late stylesheet or a theme change transitions first
    page.evaluate(settle)
    st ="import('/lib/status.js')"
    values = [v for vs in VERDICTS.values() for v in vs]
    table = page.evaluate(f"{st}.then(m => Object.fromEntries({values!r}.map(v => [v, m.statusOf('verdict', v)])))")
    want = {v: s for s, vs in VERDICTS.items() for v in vs}
    check("statusOf('verdict', v) equals the plan's mapping, value by value", table == want, {k: v for k, v in table.items() if want.get(k) != v})
    gs = page.evaluate(f"{st}.then(m => Object.fromEntries({values!r}.map(v => [v, m.statusOf('goal_state', v)])))")
    check("goal_state uses the verdict mapping", gs == want)
    info = page.evaluate(f"{st}.then(m => ({{all: m.STATUS, glyphs: m.STATUS.map(s => m.glyph(s)), words: m.STATUS.map(s => m.label(s)), vars: m.STATUS.map(s => m.statusVar(s))}}))")
    check("STATUS is the contract's ten, in order", info["all"] == STATUSES, info["all"])
    check("every status has a glyph, and the glyphs differ", all(info["glyphs"]) and len(set(info["glyphs"])) == len(STATUSES), info["glyphs"])
    check("every status has a word, and the words differ", all(info["words"]) and len(set(info["words"])) == len(STATUSES), info["words"])
    check("statusVar names the status token", info["vars"] == [f"var(--status-{s})" for s in STATUSES], info["vars"])
    odd = page.evaluate(f"{st}.then(m => [m.statusOf('verdict', 'nonsense'), m.statusOf('nokind', 'reached'), m.statusOf('verdict', undefined), m.statusOf('verdict', 'constructor'),"
                        " m.statusOf('constructor', 'x'), m.statusOf('severity', 'bogus'), m.glyph('bogus'), m.label('bogus')])")
    check("an unknown value, kind or status maps to unknown", odd[:6] == ["unknown"] * 6 and odd[6:] == ["?", "unknown"], odd)
    others = page.evaluate(f"{st}.then(m => [m.statusOf('severity', 'critical'), m.statusOf('severity', 'major'), m.statusOf('severity', 'minor'), m.statusOf('severity', 'info'),"
                           " m.statusOf('event', 'cliff_stop'), m.statusOf('event', 'reflex_stop'), m.statusOf('event', 'reached'), m.statusOf('event', 'leg'),"
                           " m.statusOf('conn', 'live'), m.statusOf('conn', 'reconnecting'), m.statusOf('conn', 'lost'), m.statusOf('conn', 'offline'), m.statusOf('conn', 'online')])")
    check("severity, event and conn map as the apps show them today (reconnecting is an error; lost and offline are the offline status)", others == ["error", "error", "warn", "neutral", "error", "alert", "ok", "neutral", "live", "error", "offline", "offline", "ok"], others)

    # the badge: glyph, word, and the colours of the status token
    for theme in ("dark", "light"):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        for s in STATUSES:
            r = page.evaluate("""async (s) => {
              const m = await import('/lib/status.js'), b = document.getElementById('badge');
              b.dataset.status = s; b.querySelector('.ui-glyph').textContent = m.glyph(s); b.querySelector('.ui-word').textContent = m.label(s);
              const probe = (v) => { const d = document.createElement('i'); d.style.color = v; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
              const g = getComputedStyle(b.querySelector('.ui-glyph')), w = getComputedStyle(b.querySelector('.ui-word')), cs = getComputedStyle(b);
              return {glyph: b.querySelector('.ui-glyph').textContent, word: b.querySelector('.ui-word').textContent,
                      glyphOk: g.color === probe(`var(--status-${s})`), wordOk: w.color === probe(`var(--status-${s}-on)`), bgOk: cs.backgroundColor === probe(`var(--status-${s}-soft)`)};
            }""", s)
            check(f"badge {s} ({theme}): a glyph, a word, the glyph in --status-{s}, the word in -on, the ground -soft",
                  bool(r["glyph"] and r["word"]) and r["glyphOk"] and r["wordOk"] and r["bgOk"], r)
    page.evaluate("document.documentElement.dataset.theme = 'dark'")

    f = page.evaluate("(() => { const c = getComputedStyle(document.getElementById('num')); return [c.fontVariantNumeric, c.fontFamily]; })()")
    check(".num computes tabular-nums and the --font-num face", "tabular-nums" in f[0] and f[1].startswith("Inter"), f)

    # density: the control height is the token's
    for density, h in (("compact", 24), ("regular", 36)):
        page.evaluate(f"document.documentElement.dataset.density = '{density}'")
        got = page.evaluate("[document.getElementById('btn').getBoundingClientRect().height, document.getElementById('inp').getBoundingClientRect().height]")
        check(f"density {density}: a button and an input are {h} px tall", got == [h, h], got)
    page.evaluate(settle)
    bc = page.evaluate("getComputedStyle(document.getElementById('inp')).borderTopColor")
    want_bc = page.evaluate("(() => { const d = document.createElement('i'); d.style.color = 'var(--control-border)'; document.body.append(d); return getComputedStyle(d).color; })()")
    check("an input's border is --control-border", bc == want_bc, [bc, want_bc])

    # motion: the system's reduced-motion, the page's choice over it
    dur = "getComputedStyle(document.getElementById('probe')).transitionDuration"
    btn_dur = "getComputedStyle(document.getElementById('btn')).transitionDuration"
    page.emulate_media(reduced_motion="no-preference")
    check("no reduced-motion request: --dur-base resolves to 0.16s", page.evaluate(dur) == "0.16s", page.evaluate(dur))
    page.emulate_media(reduced_motion="reduce")
    check("prefers-reduced-motion: reduce zeroes --dur-base", page.evaluate(dur) == "0s", page.evaluate(dur))
    check("... and a button's transitions with it", set(page.evaluate(btn_dur).split(", ")) == {"0s"}, page.evaluate(btn_dur))
    mo = "import('/lib/motion.js')"
    check("reducedMotion() is true under the system's request", page.evaluate(f"{mo}.then(m => m.reducedMotion())") is True)
    check("ms('--dur-base') is 0 under it", page.evaluate(f"{mo}.then(m => m.ms('--dur-base'))") == 0)
    full = page.evaluate(f"{mo}.then(m => {{ m.setMotion('full'); return [m.reducedMotion(), m.ms('base'), document.documentElement.dataset.motion, localStorage.getItem('rl.motion')]; }})")
    check("setMotion('full') overrides the system: durations back, data-motion and rl.motion written", full == [False, 160, "full", "full"], full)
    check("... in CSS too", page.evaluate(dur) == "0.16s", page.evaluate(dur))
    auto = page.evaluate(f"{mo}.then(m => {{ m.setMotion('auto'); return [m.reducedMotion(), document.documentElement.dataset.motion ?? null, localStorage.getItem('rl.motion')]; }})")
    check("setMotion('auto') hands it back to the system", auto == [True, None, "auto"], auto)
    page.emulate_media(reduced_motion="no-preference")
    red = page.evaluate(f"{mo}.then(m => {{ m.setMotion('reduce'); return [m.reducedMotion(), m.ms('--dur-slow')]; }})")
    check("setMotion('reduce') forces it with no system request", red == [True, 0] and page.evaluate(dur) == "0s", red)
    seen = page.evaluate(f"{mo}.then(m => {{ const got = []; const off = m.onChange((r) => got.push(r)); m.setMotion('full'); off(); m.setMotion('reduce'); return got; }})")
    check("onChange reports a change once, and its stop function stops it", seen == [False], seen)
    check("setMotion refuses a mode that is not one of the three", page.evaluate(f"{mo}.then(m => {{ try {{ m.setMotion('fast'); return false; }} catch (e) {{ return e instanceof RangeError; }} }})") is True)
    page.evaluate(f"{mo}.then(m => m.setMotion('auto'))")

    # a solid primary button: --accent fill, --accent-on text, --accent-hover under the pointer
    prim = lambda: page.evaluate("""(() => { const probe = (v) => { const d = document.createElement('i'); d.style.color = v; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
      const s = getComputedStyle(document.getElementById('btnp'));
      return {bg: s.backgroundColor, fg: s.color, accent: probe('var(--accent)'), on: probe('var(--accent-on)'), hover: probe('var(--accent-hover)')}; })()""")
    page.evaluate(settle)
    pr = prim()
    check("a primary button is a solid --accent fill with --accent-on text", pr["bg"] == pr["accent"] and pr["fg"] == pr["on"], pr)
    page.hover("#btnp")
    page.evaluate(settle)
    pr = prim()
    check("... and --accent-hover under the pointer", pr["bg"] == pr["hover"] and pr["hover"] != pr["accent"], pr)
    page.mouse.move(0, 0)

    # a stale value: the value dimmed, the age said
    sv = page.evaluate("""(() => { const v = getComputedStyle(document.querySelector('#stale .ui-stale-value')), a = document.querySelector('#stale .ui-stale-age');
      return {opacity: +v.opacity, age: a.textContent, shown: a.getBoundingClientRect().width > 0}; })()""")
    check("a stale value is dimmed and shows its age", sv["opacity"] < 1 and sv["age"] == "5 s ago" and sv["shown"], sv)

    # the top bar fills brand and nav and leaves STOP alone
    before = page.evaluate("(() => { const s = document.getElementById('stop'); window.__stop = s; return [s.parentNode.outerHTML, [...s.parentNode.parentNode.children].indexOf(s.parentNode)]; })()")
    res = page.evaluate("""import('/lib/brand.js').then((m) => {
      const bar = document.getElementById('bar'), stop = document.getElementById('stop');
      m.mountTopBar(bar, {app: 'observatory', nav: [{label: 'Runs', href: '/runs', current: true}, {label: 'Robots', href: '/robots'}]});
      const cs = getComputedStyle(stop), host = stop.parentNode;
      return {brand: bar.querySelector('[data-slot=brand]').textContent, href: bar.querySelector('[data-slot=brand] a').getAttribute('href'),
              nav: [...bar.querySelectorAll('[data-slot=nav] a')].map((a) => a.textContent + ':' + (a.getAttribute('aria-current') || '')),
              same: stop === window.__stop && stop.isConnected, html: host.outerHTML, index: [...host.parentNode.children].indexOf(host),
              visible: cs.display !== 'none' && cs.visibility !== 'hidden' && stop.getBoundingClientRect().width > 0 && !stop.hidden && !stop.disabled,
              apps: Object.entries(m.APPS).map(([k, v]) => k + ':' + v.name + ':' + v.href)};
    })""")
    check("mountTopBar fills the brand slot with the app's name and address", res["brand"] == "miniview" and res["href"] == "/", [res["brand"], res["href"]])
    check("... and the nav slot, the current page marked", res["nav"] == ["Runs:page", "Robots:"], res["nav"])
    check("... and leaves the [data-stop] node as it was: the same node, same markup, same place, not hidden",
          res["same"] and res["html"] == before[0] and res["index"] == before[1] and res["visible"], [res["same"], res["index"], before[1], res["visible"]])
    mark = page.evaluate("""(() => { const m = document.querySelector('#bar [data-slot=brand] a.ui-brand .ui-brand-mark'); if (!m) return null; const c = getComputedStyle(m);
      const p = document.createElement('i'); p.style.background = 'linear-gradient(135deg, var(--data-belief), var(--data-truth))'; p.style.width = p.style.height = '12px'; document.body.append(p);
      const want = getComputedStyle(p).backgroundImage; p.remove();
      return {w: c.width, h: c.height, bg: c.backgroundImage, want, hidden: m.getAttribute('aria-hidden')}; })()""")
    check("the brand link carries the kit's mark: 12 px, the belief-to-truth gradient, hidden from a screen reader",
          mark is not None and mark["w"] == "12px" and mark["h"] == "12px" and mark["bg"] == mark["want"] and "gradient" in mark["bg"] and mark["hidden"] == "true", mark)
    hrefs = page.evaluate("""import('/lib/brand.js').then((m) => {
      const run = (app, path) => { history.replaceState(null, '', path); const d = document.createElement('div'); d.innerHTML = '<span data-slot="brand"></span><nav data-slot="nav"></nav>';
        m.mountTopBar(d, {app}); return d.querySelector('[data-slot=brand] a').getAttribute('href'); };
      const out = [run('control', '/'), run('control', '/control/'), run('control', '/control'), run('observatory', '/web/three/'), run('observatory', '/control/')];
      history.replaceState(null, '', '/web/three/'); return out; })""")
    check("the brand link resolves in both deployments: Mission Control is '/' on its own port and '/control/' behind the Observatory; the Observatory is '/'",
          hrefs == ["/", "/control/", "/control/", "/", "/"], hrefs)
    check("APPS is the contract's", res["apps"] == ["control:Mission Control:/control/", "observatory:miniview:/"], res["apps"])
    guard = page.evaluate("""import('/lib/brand.js').then((m) => {
      const mk = (html) => { const d = document.createElement('div'); d.innerHTML = html; return d; };
      const run = (el, o) => { try { m.mountTopBar(el, o); return 'no error'; } catch (e) { return e.message; } };
      const inStop = mk('<div class="stops"><span data-slot="brand"></span></div><nav data-slot="nav"></nav>');
      const holds = mk('<span data-slot="brand"><button data-stop>STOP</button></span><nav data-slot="nav"></nav>');
      const stopTheme = mk('<span data-slot="brand"></span><nav data-slot="nav"></nav><span data-slot="theme"></span>');
      const btn = document.createElement('button'); btn.setAttribute('data-stop', ''); stopTheme.append(btn);
      return [run(inStop, {app: 'control'}), run(holds, {app: 'control'}), holds.querySelector('[data-stop]') !== null, run(stopTheme, {app: 'control', themeControl: btn}),
              stopTheme.contains(btn), run(mk('<nav data-slot="nav"></nav>'), {app: 'control'}), run(mk(''), {app: 'nope'})];
    })""")
    check("mountTopBar refuses a slot that is, holds or sits in STOP, and leaves it in place", all("STOP" in guard[i] for i in (0, 1, 3)) and guard[2] is True and guard[4] is True, guard)
    check("... a missing slot and an unknown app", "no [data-slot" in guard[5] and "unknown app" in guard[6], guard[5:])
    theme_ok = page.evaluate("""import('/lib/brand.js').then((m) => {
      const d = document.createElement('div'); d.innerHTML = '<span data-slot="brand"></span><nav data-slot="nav"></nav><span data-slot="theme"></span>';
      const t = document.createElement('button'); m.mountTopBar(d, {app: 'control', themeControl: t}); return d.querySelector('[data-slot=theme]').firstChild === t;
    })""")
    check("a theme control the caller hands over goes into the theme slot", theme_ok is True)

    # ---- U10: the Observatory restyle -----------------------------------------------------------------------------
    css = SHELL_CSS.read_text()
    check("shell.css has no hex colour", not re.findall(r"#[0-9a-fA-F]{3,8}\b", css), re.findall(r"#[0-9a-fA-F]{3,8}\b", css)[:5])
    used = sorted({n for n in OLD_NAMES if re.search(re.escape(n) + r"(?![\w-])", css.replace("--left", "").replace("--right", ""))})
    check("shell.css uses no old token name (the aliases until U26)", not used, used)

    long_scene = {**scene("apartment_with_a_rather_long_name"), "name": "An apartment with a rather long name indeed"}
    LONG = "duck/apartment_with_a_rather_long_name/exploration_run_with_a_long_identifier_0042"
    VERDICT_RUNS = [("ended1", "ended"), ("ended2", "ended"), ("ended3", "ended"), ("cancel", "cancelled"), ("nofront", "no_frontier_left"), ("trap", "trapped")]
    with tempfile.TemporaryDirectory() as tmp2:
        cat2 = catalog(Path(tmp2) / "data")
        cat2.put_scene(long_scene)
        cat2.put_scene(scene("room"))
        make_run(Path(tmp2) / "data", LONG, HEAD + [tick(1.0, 0.0), tick(1.1, 0.1), (2.0, "end", {"verdict": "reached"})])
        for rid, v in VERDICT_RUNS:
            make_run(Path(tmp2) / "data", f"duck/room/{rid}", HEAD + [tick(1.0, 0.0), (2.0, "end", {"verdict": v})])
        live = make_run(Path(tmp2) / "data", "duck/room/livenow", HEAD + [tick(1.0, 0.0)], close=False)
        # the run info's longest text, longer than the screenshots' fixture (30 ticks): a real run has hundreds of ticks and a duration of minutes
        RICH_N = 600
        RICH = HEAD + [r for k in range(RICH_N) for r in (tick(round(1.0 + 0.1 * k, 3), 0.001 * k), (round(1.05 + 0.1 * k, 3), "signals", {"values": {"joint_a": 0.001 * k}, "t_src": round(1.05 + 0.1 * k, 3)}))] + [(round(1.5 + 0.1 * RICH_N, 3), "end", {"verdict": "reached"})]
        make_run(Path(tmp2) / "data", "duck/room/rich", RICH, signals=[{"name": "joint_a", "kind": "number", "unit": "rad"}])
        cat2.scan()
        httpd2, base2 = serve(cat2, follow=False)
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.set_default_timeout(8000)
        boot(pg, base2 + "/web/three/index.html", timeout=30000)
        check("the page is compact: data-density=\"compact\" on <html>", pg.evaluate("document.documentElement.dataset.density") == "compact")
        check("the page links the kit's ui.css", pg.evaluate("[...document.styleSheets].some((s) => (s.href || '').endsWith('/lib/ui.css'))"))

        # the runs list: five benign verdicts and one abnormal, one coloured verdict (a glyph and a word with it)
        rows = pg.evaluate("""[...document.querySelectorAll('#scenespage tr[data-run]')].filter((r) => r.dataset.scene === 'room').map((r) => {
          const b = r.querySelector('.ui-badge'); return [r.dataset.run.split('/').pop(), b ? b.dataset.status : null, b ? b.textContent.trim() : r.cells[4].textContent.trim()]; })""")
        by = {r[0]: r for r in rows}
        coloured = [r for r in rows if r[1] not in ("neutral", None, "live", "ok")]
        check("the runs list shows 5 benign and 1 abnormal verdict as exactly one coloured badge", [r[0] for r in coloured] == ["trap"], rows)
        check("... a correct end is neutral, the trap is an alert with its glyph and word", by["ended1"][1] == "neutral" and by["trap"][1] == "alert"
              and "trapped" in by["trap"][2] and by["trap"][2] != "trapped", by)
        reached = pg.evaluate("[...document.querySelectorAll('#scenespage tr[data-run]')].filter((r) => r.dataset.run.endsWith('0042')).map((r) => r.querySelector('.ui-badge')?.dataset.status)")
        check("... reached reads as ok", reached == ["ok"], reached)

        # the live indicator is --status-live, with the live glyph, never the error colour
        li = pg.evaluate("""(() => {
          const probe = (v) => { const d = document.createElement('i'); d.style.color = v; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c; };
          const dot = document.querySelector('#scenespage .live-dot, #scenespage .ui-badge[data-status="live"] .ui-glyph');
          const bd = document.querySelector('#scenespage .ui-badge[data-status="live"]');
          if (!dot || !bd) return null;
          const c = getComputedStyle(dot);
          return {dot: dot.className, colour: c.color, bg: c.backgroundColor, live: probe('var(--status-live)'), error: probe('var(--status-error)'), glyph: bd.textContent.trim()}; })()""")
        check("the live run is a live badge with the live glyph and word", li is not None and li["glyph"].startswith("●") and "live" in li["glyph"], li)
        check("... its colour is --status-live and not the error colour", li is not None and li["live"] in (li["colour"], li["bg"]) and li["error"] not in (li["colour"], li["bg"]), li)
        # reduced motion: the live glyph's pulse stops
        anim = "[...document.querySelectorAll('#scenespage .ui-badge[data-status=live] .ui-glyph, .live-dot')].map((e) => { const c = getComputedStyle(e); return [c.animationName, c.animationDuration]; })"
        pg.emulate_media(reduced_motion="no-preference")
        moving = pg.evaluate(anim)
        pg.emulate_media(reduced_motion="reduce")
        still = pg.evaluate(anim)
        check("with no request the live dot pulses; under reduced motion its animation is none or 0 s",
              any(n != "none" and d not in ("0s",) for n, d in moving) and all(n == "none" or d in ("0s", "0ms") for n, d in still), [moving, still])
        pg.emulate_media(reduced_motion="no-preference")

        # a run open at 1440: the top bar, no control clipped or wrapped, even with long names (the run info, which has no fixed width, may shorten with an ellipsis)
        pg.evaluate(f"window.miniview.load('apartment_with_a_rather_long_name', {LONG!r})")
        pg.wait_for_function("window.__ready === true", timeout=30000)
        bar = pg.evaluate("""(() => {
          const top = document.querySelector('header.top'), W = innerWidth, out = [];
          for (const e of top.querySelectorAll('button, a, label, .chip, .seg, select')) {
            const r = e.getBoundingClientRect(); if (!r.width || e.closest('[hidden]') || getComputedStyle(e).display === 'none') continue;
            out.push({id: e.id || e.textContent.trim().slice(0, 14), left: r.left, right: r.right, h: r.height, clipped: !e.classList.contains('chip') && e.scrollWidth > e.clientWidth + 1});
          }
          return {W, bar: top.getBoundingClientRect().height, out}; })()""")
        bad = [o for o in bar["out"] if o["right"] > bar["W"] + 0.5 or o["left"] < -0.5 or o["h"] > 30 or o["clipped"]]
        check("at 1440 px no top-bar control is clipped, off screen or wrapped, with long scene, run and robot names", not bad and len(bar["out"]) > 8 and bar["bar"] <= 40, [bad, bar["bar"]])
        lap = pg.evaluate("""(() => { const kids = [...document.querySelector('header.top').children].filter((e) => e.getBoundingClientRect().width > 0 && getComputedStyle(e).display !== 'none')
          .map((e) => [e.id || e.dataset.slot || e.className, e.getBoundingClientRect()]).sort((x, y) => x[1].left - y[1].left);
          const bad = []; for (let i = 1; i < kids.length; i++) if (kids[i][1].left < kids[i - 1][1].right - 0.5) bad.push([kids[i - 1][0], kids[i][0]]);
          const nav = document.querySelector('[data-slot=nav]'), link = nav.querySelector('a');
          if (link.getBoundingClientRect().right > nav.getBoundingClientRect().right + 0.5) bad.push(['nav', 'its link overflows']);
          return bad; })()""")
        check("... and no two top-bar items overlap, the Scenes link stays inside its slot", not lap, lap)
        pg.evaluate("window.miniview.load('room', 'duck/room/rich')")
        pg.wait_for_function("window.__ready === true && document.getElementById('runinfo').textContent.includes('samples')", timeout=30000)
        info = pg.evaluate("(() => { const e = document.getElementById('runinfo'), g = document.querySelector('.top > .grow'); return {text: e.textContent, scroll: e.scrollWidth, client: e.clientWidth, spare: g.getBoundingClientRect().width}; })()")
        check("at 1440 px the run info shows in full (ticks and samples, no ellipsis) for a run of 600 ticks and 600 samples (a minute at 10 Hz), with 24 px or more to spare in the bar",
              "600 samples" in info["text"] and info["scroll"] <= info["client"] and info["spare"] >= 24, info)
        probe_tn = pg.evaluate("""(() => ['tin', 'kin'].map((id) => getComputedStyle(document.getElementById(id)).fontVariantNumeric.includes('tabular-nums')))()""")
        check("the time and tick readouts use tabular figures", all(probe_tn), probe_tn)
        shell_btn = pg.evaluate("document.getElementById('exportBtn').getBoundingClientRect().height")
        check("a top-bar button is a compact control tall (24 px)", shell_btn == 24, shell_btn)

        # the theme: the legacy key is read, rl.theme is written, and both keep working
        pg.evaluate("localStorage.clear(); localStorage.setItem('miniview.theme', 'light')")
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
        check("the legacy miniview.theme is read", pg.evaluate("document.documentElement.dataset.theme") == "light")
        pg.click("#themeBtn")
        keys = pg.evaluate("[document.documentElement.dataset.theme, localStorage.getItem('rl.theme'), localStorage.getItem('miniview.theme')]")
        check("the switch writes rl.theme (and the legacy key, so an older page still works)", keys == ["dark", "dark", "dark"], keys)
        pg.evaluate("localStorage.clear(); localStorage.setItem('rl.theme', 'light')")
        pg.reload()
        pg.wait_for_function("window.miniview !== undefined && window.__ready === true", timeout=30000)
        check("rl.theme is read first", pg.evaluate("document.documentElement.dataset.theme") == "light")
        pg.close()
        httpd2.shutdown()
        live.close()

    b.close()
    httpd.shutdown()
check.done()
