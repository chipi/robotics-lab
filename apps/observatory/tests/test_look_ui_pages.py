"""The look-and-feel guards of the shared UI kit (step 4.5, units U2 and U3) in headless Chromium: the pages load Inter from the shared
/lib/fonts; every libs/web module (outside vendor/) imports clean; status.js maps what the plan says and every status has a glyph and a word; the
badge shows glyph, word and the status colour; .num is tabular; a button is 24 px tall compact and 36 px regular; reduced motion zeroes the
durations (and setMotion overrides the system); a stale value is dimmed and says its age; mountTopBar fills the brand and nav and leaves STOP alone.
Run: cd apps/observatory && uv run python tests/test_look_ui_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
from observatory.shots import launch

check = Checks("LOOK UI PAGES")
LIB = Path(__file__).resolve().parents[3] / "libs" / "web"

# the plan's verdict mapping (docs/wip/LOOK-AND-FEEL-PLAN.md, "Frozen contracts"), written out value by value
VERDICTS = {
    "ok": ["reached", "done", "evaluated"], "info": ["running", "queued"],
    "neutral": ["ended", "no_frontier_left", "cancelled", "refused", "not_found"],
    "warn": ["timeout", "stalled"], "alert": ["stopped_by_guardrail", "trapped"], "error": ["failed", "interrupted"],
}
STATUSES = ["ok", "info", "warn", "alert", "error", "unknown", "stale", "neutral", "live"]

PAGE = """<!doctype html><html data-theme="dark"><head>
<link rel="stylesheet" href="/lib/tokens.css"><link rel="stylesheet" href="/lib/fonts/fonts.css"><link rel="stylesheet" href="/lib/ui.css">
</head><body>
<span id="badge" class="ui-badge" data-status="warn"><span class="ui-glyph" aria-hidden="true">G</span><span class="ui-word">W</span></span>
<span id="num" class="num">0123</span>
<button id="btn" class="ui-btn">Go</button><input id="inp" class="ui-input">
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
    check("STATUS is the contract's nine, in order", info["all"] == STATUSES, info["all"])
    check("every status has a glyph, and the glyphs differ", all(info["glyphs"]) and len(set(info["glyphs"])) == len(STATUSES), info["glyphs"])
    check("every status has a word, and the words differ", all(info["words"]) and len(set(info["words"])) == len(STATUSES), info["words"])
    check("statusVar names the status token", info["vars"] == [f"var(--status-{s})" for s in STATUSES], info["vars"])
    odd = page.evaluate(f"{st}.then(m => [m.statusOf('verdict', 'nonsense'), m.statusOf('nokind', 'reached'), m.statusOf('verdict', undefined), m.statusOf('verdict', 'constructor'),"
                        " m.statusOf('constructor', 'x'), m.statusOf('severity', 'bogus'), m.glyph('bogus'), m.label('bogus')])")
    check("an unknown value, kind or status maps to unknown", odd[:6] == ["unknown"] * 6 and odd[6:] == ["?", "unknown"], odd)
    others = page.evaluate(f"{st}.then(m => [m.statusOf('severity', 'critical'), m.statusOf('severity', 'major'), m.statusOf('severity', 'minor'), m.statusOf('severity', 'info'),"
                           " m.statusOf('event', 'cliff_stop'), m.statusOf('event', 'reflex_stop'), m.statusOf('event', 'reached'), m.statusOf('event', 'leg'),"
                           " m.statusOf('conn', 'live'), m.statusOf('conn', 'reconnecting')])")
    check("severity, event and conn map as the apps show them today", others == ["error", "error", "warn", "neutral", "error", "alert", "ok", "neutral", "live", "error"], others)

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

    b.close()
    httpd.shutdown()
check.done()
