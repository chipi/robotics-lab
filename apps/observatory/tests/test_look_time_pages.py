"""The pure time modules of the shared UI kit (step 4.5, unit U6) in headless Chromium: libs/web/time/timemodel.js (live following, seek away
to replay with behind_s, goLive, a growing range, jumps by mark and kind, speeds, loop, tick, one change event per change) and freshness.js
(its thresholds at the boundaries). Then (U14) the Observatory's time on a page: Live and Replay named, the marks by kind, jumps by kind, the linked cursor.
Run: cd apps/observatory && uv run python tests/test_look_time_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, boot, catalog, make_run, scene, serve, tick
from observatory.shots import launch

check = Checks("LOOK TIME PAGES")

# each scenario is a function of the module; it returns plain data the checks below read
RUN = """async (body) => {
  const { createTimeModel, SPEEDS } = await import('/lib/time/timemodel.js');
  const { freshness } = await import('/lib/time/freshness.js');
  return await (new Function('createTimeModel', 'SPEEDS', 'freshness', 'return (' + body + ')(createTimeModel, SPEEDS, freshness)'))(createTimeModel, SPEEDS, freshness);
}"""


def run(page, body):
    return page.evaluate(RUN, body)


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(8000)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(base + "/web/three/")

    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); const s = m.state; return {s}; }""")["s"]
    check("live starts at the edge, atEdge, behind 0, canLive", r["mode"] == "live" and r["t"] == 10 and r["atEdge"] and r["behind_s"] == 0 and r["canLive"], r)
    r = run(page, """(M) => { const m = M({t0: 2, t1: 10}); return m.state; }""")
    check("replay starts at t0, paused, speed 1, no loop", r["mode"] == "replay" and r["t"] == 2 and not r["playing"] and r["speed"] == 1 and not r["loop"], r)

    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(4, {source: 'user'}); return m.state; }""")
    check("a seek away from the edge leaves live: replay, behind_s 6, not atEdge", r["mode"] == "replay" and r["t"] == 4 and r["behind_s"] == 6 and not r["atEdge"], r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(10); const a = m.state.mode; m.seek(4, {source: 'follow'}); return [a, m.state.mode]; }""")
    check("a seek to the edge stays live, and source 'follow' never leaves live", r == ["live", "live"], r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(-5); const lo = m.state.t; m.seek(99); return [lo, m.state.t]; }""")
    check("seek clamps to [t0, t1]", r == [0, 10], r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(4); const ok = m.goLive(); return [ok, m.state]; }""")
    check("goLive returns to following the edge", r[0] is True and r[1]["mode"] == "live" and r[1]["t"] == 10 and r[1]["behind_s"] == 0, r)
    r = run(page, """(M) => { const m = M({mode: 'replay', t0: 0, t1: 10}); m.seek(4); const ok = m.goLive(); return [ok, m.state]; }""")
    check("a finished run: goLive is a no-op returning false, canLive false", r[0] is False and r[1]["mode"] == "replay" and r[1]["t"] == 4 and r[1]["canLive"] is False and r[1]["behind_s"] == 0, r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(4); m.finish(); const a = m.state; const ok = m.goLive(); return [a, ok]; }""")
    check("finish(): a growing run ends, canLive false, time stays, goLive false", r[0]["canLive"] is False and r[0]["mode"] == "replay" and r[0]["t"] == 4 and r[1] is False, r)

    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.setRange(0, 15); return m.state; }""")
    check("setRange while following: t follows the new edge", r["t"] == 15 and r["mode"] == "live" and r["behind_s"] == 0, r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(4); m.setRange(0, 15); return m.state; }""")
    check("setRange while behind: t stays, behind_s grows", r["t"] == 4 and r["mode"] == "replay" and r["behind_s"] == 11, r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10}); m.seek(9); m.setRange(0, 5); return m.state.t; }""")
    check("setRange shrinking clamps t", r == 5, r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10}); const e = []; for (const a of [[0, -1], [NaN, 3]]) { try { m.setRange(...a); e.push('ok'); } catch { e.push('throw'); } } return e; }""")
    check("setRange refuses a bad range", r == ["throw", "throw"], r)

    MARKS = "[{t: 1, kind: 'a'}, {t: 3, kind: 'b'}, {t: 5, kind: 'a'}, {t: 7, kind: 'b'}, {t: 99, kind: 'a'}]"
    r = run(page, f"""(M) => {{ const m = M({{t0: 0, t1: 10}}), k = {MARKS}, o = [m.jump(k, 1), m.jump(k, 1), m.jump(k, -1), m.jump(k, -1), m.jump(k, -1)]; return o; }}""")
    check("jump next/prev steps mark to mark and stays at the first (a mark outside the range is ignored)", r == [1, 3, 1, 1, 1], r)
    r = run(page, f"""(M) => {{ const m = M({{t0: 0, t1: 10}}), k = {MARKS}; return [1,1,1,1,1].map(() => m.jump(k, 1)); }}""")
    check("jump next stays at the last mark", r == [1, 3, 5, 7, 7], r)
    r = run(page, f"""(M) => {{ const m = M({{t0: 0, t1: 10}}), k = {MARKS}; const f = [m.jump(k, 1, 'b'), m.jump(k, 1, 'b'), m.jump(k, 1, 'b')]; return [f, m.jump(k, -1, 'a'), m.jump(k, 'prev', 'b')]; }}""")
    check("jump by kind skips the other kinds; 'next'/'prev' words work", r == [[3, 7, 7], 5, 3], r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); const t = m.jump([{t: 2, kind: 'a'}], -1); return [t, m.state.mode, m.state.behind_s, m.jump([], 1), m.jump(null, -1)]; }""")
    check("jump back from live goes to replay; no marks keeps t", r == [2, "replay", 8, 2, 2], r)

    r = run(page, """(M, S) => { const m = M({t0: 0, t1: 10}); const a = [.25, .5, 1, 2, 4, 8].map((v) => [m.setSpeed(v), m.state.speed]); const bad = [3, 0, '2', NaN].map((v) => m.setSpeed(v)); return {S, a, bad, speed: m.state.speed}; }""")
    check("SPEEDS is the contract's six", r["S"] == [0.25, 0.5, 1, 2, 4, 8], r["S"])
    check("setSpeed accepts each, refuses others (false, unchanged)", all(ok and sp == v for (ok, sp), v in zip(r["a"], r["S"])) and r["bad"] == [False] * 4 and r["speed"] == 8, r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10, speed: 3, loop: 1}); const a = m.state; m.setLoop(false); return [a.speed, a.loop, m.state.loop]; }""")
    check("an unknown initial speed becomes 1; setLoop sets", r == [1, True, False], r)

    r = run(page, """(M) => { const m = M({t0: 0, t1: 10}); m.tick(1); const idle = m.state.t; m.play(); m.setSpeed(2); m.tick(1.5); const a = m.state.t; m.pause(); m.tick(1); return [idle, a, m.state.t, m.state.playing]; }""")
    check("tick advances t by dt*speed only while playing", r == [0, 3, 3, False], r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10, playing: true}); m.seek(9.5); m.tick(2); return m.state; }""")
    check("tick stops at t1 without loop, and pauses", r["t"] == 10 and r["playing"] is False, r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10, playing: true, loop: true}); m.seek(9.5); m.tick(2); return m.state; }""")
    check("tick with loop wraps to t0 + the overshoot and keeps playing", abs(r["t"] - 1.5) < 1e-9 and r["playing"] is True, r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10}); m.seek(10); m.play(); return m.state; }""")
    check("play at the end starts over from t0", r["t"] == 0 and r["playing"] is True, r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10, playing: true}); m.tick(5); return m.state; }""")
    check("tick in live has nothing to advance: t stays at the edge", r["t"] == 10 and r["mode"] == "live", r)
    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); m.seek(8); m.play(); m.tick(5); const a = m.state; m.setRange(0, 20); return [a.t, a.playing, a.mode, m.state.t]; }""")
    check("a live run replayed from behind plays to the edge and stops there (stays replay)", r == [10, False, "replay", 10], r)

    r = run(page, """(M) => { const m = M({mode: 'live', t0: 0, t1: 10}); const ev = []; const off = m.on('change', (s) => ev.push(s.t));
      m.seek(4); m.seek(4); m.setSpeed(2); m.setSpeed(2); m.setLoop(true); m.setLoop(true); m.play(); m.play(); m.pause(); m.pause(); m.tick(1); m.goLive(); m.goLive(); m.setRange(0, 12); m.setRange(0, 12);
      const n = ev.length; off(); m.seek(1); return [n, ev.length]; }""")
    check("change fires once per change (seek, speed, loop, play, pause, goLive, setRange) and never for a no-op; off() stops it", r == [7, 7], r)
    r = run(page, """(M) => { const m = M({t0: 0, t1: 10}); const ev = []; m.on('change', (s) => ev.push(s)); m.play(); m.seek(5); m.tick(1); return [ev.length, ev.at(-1).t, ev.at(-1).playing]; }""")
    check("the event carries the new state", r == [3, 6, True], r)
    r = run(page, """(M) => { try { M({t0: 0, t1: 1}).on('nope', () => {}); return 'ok'; } catch { return 'throw'; } }""")
    check("an unknown event name throws", r == "throw", r)

    r = run(page, """(M, S, F) => [F(0), F(4.999), F(5), F(29.999), F(30), F(1e6), F(null), F(undefined), F(NaN), F('x'), F(-1)]""")
    check("freshness at the boundaries: <5 fresh, [5,30) stale, >=30 offline; none/NaN offline", r == ["fresh", "fresh", "stale", "stale", "offline", "offline", "offline", "offline", "offline", "offline", "fresh"], r)
    r = run(page, """(M, S, F) => [F(2, {staleAfterS: 2}), F(1.9, {staleAfterS: 2}), F(9, {offlineAfterS: 9}), F(8.9, {offlineAfterS: 9})]""")
    check("freshness thresholds are options", r == ["stale", "fresh", "offline", "stale"], r)

    # ---- U14: Observatory time: Live and Replay named, marks by kind, jumps by kind, the linked cursor --------------------------------------
    HEAD = [(0.0, "epoch", {"map_to_world": [0.0, 0.0, 0.0]})]

    def ev(t, kind):
        return (t, "event", {"kind": kind, "text": f"{kind} at {t}"})

    def inorder(rows):
        return sorted(rows, key=lambda r: r[0])

    def ticks_between(a, b):
        return [tick(round(1.0 + 0.1 * i, 3), 0.05 * i) for i in range(a, b)]

    data2 = Path(tmp) / "data2"
    cat2 = catalog(data2)
    cat2.put_scene(scene("room"))
    marks = [ev(1.5, "cliff_stop"), ev(2.0, "reached"), ev(2.5, "tight_pivot"), ev(3.0, "cliff_stop"), ev(3.5, "reached")]
    make_run(data2, "duck/room/replay1", HEAD + inorder(ticks_between(0, 40) + marks) + [(5.0, "end", {"verdict": "ended"})])
    rec = make_run(data2, "duck/room/live1", HEAD + inorder(ticks_between(0, 20) + marks[:2]), close=False)
    httpd2, base2 = serve(cat2)
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.set_default_timeout(15000)
    errs2 = []
    pg.on("pageerror", lambda e: errs2.append(str(e)))
    boot(pg, base2 + "/web/three/")

    def load(key):
        pg.evaluate(f"window.miniview.load('room', '{key}')")
        pg.wait_for_function("window.__ready === true")

    TM = """(() => { const e = document.getElementById('timemode'); return e && { mode: e.dataset.mode, text: e.textContent.replace(/\\s+/g, ' ').trim(),
      go: !document.getElementById('tm-golive').hidden, behind: document.getElementById('tm-behind').textContent }; })()"""
    KINDS = "[...document.querySelectorAll('#mlane .mk')].reduce((o, m) => { o[m.dataset.kind] = (o[m.dataset.kind] || 0) + 1; return o; }, {})"
    T = "window.miniview.state().t"

    load("duck/room/replay1")
    r = pg.evaluate(TM)
    check("a finished run is named Replay: the mode says so, there is no way back to live", r and r["mode"] == "replay" and "Replay" in r["text"] and not r["go"], r)
    check("the time mode is in the script's state: replay, cannot go live", pg.evaluate("window.miniview.state().time") == {"mode": "replay", "can_live": False, "behind_s": 0},
          pg.evaluate("window.miniview.state().time"))

    r = pg.evaluate(KINDS)
    check("every event is a mark on the scrubber, carrying its kind", r == {"cliff_stop": 2, "reached": 2, "tight_pivot": 1}, r)
    r = pg.evaluate("[...document.querySelectorAll('#mlane .mk')].map((m) => [m.dataset.kind, m.getAttribute('aria-label') || '', m.classList.contains('stop')])")
    check("a mark says its kind to a screen reader, and a stop-like kind has its own shape",
          all(k and k in a and " s" in a for k, a, _ in r) and {k: s for k, _, s in r} == {"cliff_stop": True, "reached": False, "tight_pivot": False}, r)

    seq = [pg.evaluate("(a) => window.miniview.jump(...a)", a) for a in ([1, "cliff_stop"], [1, "cliff_stop"], [1, "cliff_stop"], [-1, "cliff_stop"])]
    check("jump to the next mark of a kind and back, staying at the last one", [round(x, 2) for x in seq] == [1.5, 3.0, 3.0, 1.5], seq)
    seq = [pg.evaluate("(a) => window.miniview.jump(...a)", a) for a in ([1], [1], [-1, "reached"], [-1, "reached"])]
    check("jump with no kind steps every kind; a kind with nothing before stays put", [round(x, 2) for x in seq] == [2.0, 2.5, 2.0, 2.0], seq)
    check("a jump moves the playhead", abs(pg.evaluate(T) - 2.0) < 1e-6)

    pg.evaluate("window.miniview.setTime(1.0)")
    pg.click("#kindsBtn")
    pg.click('[data-k="cliff_stop"]')
    pg.keyboard.press("Escape")
    check("a kind hidden in the Events list is skipped by a jump", round(pg.evaluate("window.miniview.jump(1)"), 2) == 2.0)
    pg.click("#kindsBtn")
    pg.click('[data-k="cliff_stop"]')
    pg.keyboard.press("Escape")

    pg.evaluate("window.miniview.setTime(1.0)")
    pg.click("#jkind")
    pg.click('[data-jkind="reached"]')
    check("the kind button shows the kind chosen", pg.inner_text("#jkind").strip().startswith("reached"), pg.inner_text("#jkind"))
    pg.click("#jnext")
    t_a = pg.evaluate(T)
    pg.keyboard.press(".")
    t_b = pg.evaluate(T)
    pg.click("#jprev")
    t_c = pg.evaluate(T)
    check("the next and previous buttons and the . key jump by the chosen kind", [round(t_a, 2), round(t_b, 2), round(t_c, 2)] == [2.0, 3.5, 2.0], [t_a, t_b, t_c])
    pg.click("#jkind")
    pg.click('[data-jkind=""]')

    # the same popover with the keyboard alone: Enter on the button opens it, the focus moves into it, Tab walks its items, Enter chooses, Esc closes it
    pg.focus("#jkind")
    pg.keyboard.press("Enter")
    pg.wait_for_function("!!document.querySelector('.pop [data-jkind]')")
    check("the jump-kind popover opens with Enter on its button", True)
    check("... and the focus is inside it", pg.evaluate("!!document.activeElement.closest('.pop')"), pg.evaluate("document.activeElement.outerHTML.slice(0, 80)"))
    pg.keyboard.press("Tab")
    pg.keyboard.press("Tab")
    pg.keyboard.press("Enter")
    kb_kind = pg.inner_text("#jkind").strip()
    check("Tab and Enter choose a kind, and the popover closes", kb_kind not in ("any", "") and not pg.evaluate("!!document.querySelector('.pop')"), kb_kind)
    pg.focus("#jkind")
    pg.keyboard.press("Enter")
    pg.wait_for_function("!!document.querySelector('.pop [data-jkind]')")
    was_playing = pg.evaluate("window.miniview.internals.M.play.on")
    pg.keyboard.press("Tab")
    pg.keyboard.press(" ")
    check("Space on a popover's item chooses it and does not play or pause the run", pg.inner_text("#jkind").strip() != kb_kind and pg.evaluate("window.miniview.internals.M.play.on") == was_playing,
          (pg.inner_text("#jkind"), was_playing))
    pg.focus("#jkind")
    pg.keyboard.press("Enter")
    pg.wait_for_function("!!document.querySelector('.pop')")
    pg.keyboard.press("Escape")
    check("Esc closes the popover", not pg.evaluate("!!document.querySelector('.pop')"))
    check("... and the focus is back on the button", pg.evaluate("document.activeElement.id") == "jkind", pg.evaluate("document.activeElement.id"))
    pg.click("#jkind")
    pg.click('[data-jkind=""]')

    # the linked cursor: a click on the scrubber moves what the 3D view draws (the trail runs up to the playhead), not only the number
    def scrub_to(t):
        x = pg.evaluate("""(t) => { const r = document.getElementById('overlay').getBoundingClientRect(), run = window.miniview.internals.M.run,
          pad = Math.max(0.05, 0.012 * (run.t1 - run.t0)), a = run.t0 - pad, b = run.t1 + pad; return [r.left + ((t - a) / (b - a)) * r.width, r.top + r.height / 2]; }""", t)
        pg.mouse.move(*x)
        pg.mouse.down()
        pg.mouse.up()

    trail = "window.miniview.internals.adapter.bodies().trail.count"
    scrub_to(1.5)
    s1, n1 = pg.evaluate("window.miniview.state()"), pg.evaluate(trail)
    scrub_to(4.0)
    s2, n2 = pg.evaluate("window.miniview.state()"), pg.evaluate(trail)
    check("scrubbing moves the playhead and the robot with it", abs(s1["t"] - 1.5) < 0.1 and abs(s2["t"] - 4.0) < 0.1 and s2["belief"][0] > s1["belief"][0] + 0.5,
          (s1["t"], s2["t"], s1["belief"], s2["belief"]))
    check("scrubbing moves what the 3D view draws: the trail grows with the playhead", n2 > n1 > 0, (n1, n2))

    # a run opened after the viewer has moved the playhead by hand opens where Follow live left it: Replay, with the way back
    load("duck/room/live1")
    r = pg.evaluate(TM)
    check("a live run opened with Follow live off is Replay at its start, and offers the way back", r["mode"] == "replay" and r["go"] and not pg.evaluate("window.miniview.state().follow"), r)

    # a live run on a fresh page: named Live; a seek away is Replay, with how far behind and the way back
    pg.close()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.set_default_timeout(15000)
    pg.on("pageerror", lambda e: errs2.append(str(e)))
    boot(pg, base2 + "/web/three/")
    load("duck/room/live1")
    pg.wait_for_function("document.getElementById('timemode')?.dataset.mode === 'live'")
    r = pg.evaluate(TM)
    check("a run being written is named Live, at the edge, with no way back to offer", r["mode"] == "live" and "Live" in r["text"] and not r["go"], r)
    check("Live is its own status badge (the live glyph, never the error colour)", pg.evaluate("document.querySelector('#timemode .ui-badge')?.dataset.status") == "live")
    pg.evaluate("window.miniview.setTime(1.2)")
    r = pg.evaluate(TM)
    check("a seek away from the edge leaves Live for Replay and offers the way back, with how far behind", r["mode"] == "replay" and r["go"] and "behind" in r["behind"], r)
    b0 = float(r["behind"].split()[0])
    for rr in ticks_between(20, 30):
        rec.add(*rr)
    pg.wait_for_function(f"parseFloat(document.getElementById('tm-behind').textContent) > {b0 + 0.5}")
    r = pg.evaluate(TM)
    check("the run grows while the viewer is behind: the gap grows", float(r["behind"].split()[0]) > b0 + 0.5, (b0, r))
    pg.click("#tm-golive")
    pg.wait_for_function("document.getElementById('timemode').dataset.mode === 'live'")
    s = pg.evaluate("window.miniview.state()")
    check("Return to live follows the edge again: Follow live on, the playhead at the end",
          s["follow"] is True and abs(s["t"] - s["t_range"][1]) < 1e-6 and pg.evaluate("document.getElementById('tm-badge').getAttribute('aria-pressed') === 'true'"), (s["follow"], s["t"], s["t_range"]))
    pg.evaluate("window.miniview.jump(-1)")
    check("a jump back from live leaves Live", pg.evaluate(TM)["mode"] == "replay")
    pg.click("#tm-badge")
    check("the badge is the Follow live switch: a button that says Live and is pressed (the old checkbox is gone)",
          pg.evaluate("(() => { const b = document.getElementById('tm-badge'); return b.tagName === 'BUTTON' && b.getAttribute('aria-pressed') === 'true' && b.textContent.includes('Live'); })()")
          and pg.evaluate("!document.getElementById('follow-on') && !document.getElementById('follow')"))
    check("the badge has an accessible name that says what a press does", "stop following" in pg.evaluate("document.getElementById('tm-badge').title").lower(), pg.evaluate("document.getElementById('tm-badge').title"))
    pg.focus("#tm-badge")
    pg.keyboard.press("Enter")
    s = pg.evaluate("window.miniview.state()")
    check("Enter on the focused badge stops following: Replay, the badge not pressed, the run not played", s["follow"] is False and pg.evaluate(TM)["mode"] == "replay"
          and pg.evaluate("document.getElementById('tm-badge').getAttribute('aria-pressed')") == "false" and pg.evaluate("window.miniview.config().play.on") is False, s)
    pg.keyboard.press("Space")
    s = pg.evaluate("window.miniview.state()")
    check("Space on the focused badge follows live again (and does not start playback)", s["follow"] is True and pg.evaluate(TM)["mode"] == "live" and pg.evaluate("window.miniview.config().play.on") is False, s)

    ANIMATED = "[...document.querySelectorAll('#timemode, #timemode *')].map((e) => getComputedStyle(e)).filter((c) => c.animationName !== 'none' && parseFloat(c.animationDuration) > 0).length"
    pg.emulate_media(reduced_motion="no-preference")
    check("(setup) Live pulses its glyph when motion is allowed", pg.evaluate(ANIMATED) > 0, pg.evaluate(ANIMATED))
    pg.emulate_media(reduced_motion="reduce")
    r = pg.evaluate(ANIMATED)
    check("under reduced motion the time mode runs no animation", r == 0, r)
    pg.emulate_media(reduced_motion="no-preference")

    rec.add(4.0, "end", {"verdict": "ended"})
    rec.close()
    pg.wait_for_function("document.getElementById('timemode').dataset.mode === 'replay' && window.miniview.state().status !== 'live'")
    r = pg.evaluate(TM)
    check("when the run ends it can no longer go live: Replay, no way back", r["mode"] == "replay" and not r["go"] and pg.evaluate("window.miniview.state().time.can_live") is False, r)
    check("no page error in the time section", not errs2, errs2)
    pg.close()
    httpd2.shutdown()

    check("no page error", not errs, errs)
    b.close()
    httpd.shutdown()
check.done()
