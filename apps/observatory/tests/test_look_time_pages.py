"""The pure time modules of the shared UI kit (step 4.5, unit U6) in headless Chromium: libs/web/time/timemodel.js (live following, seek away
to replay with behind_s, goLive, a growing range, jumps by mark and kind, speeds, loop, tick, one change event per change) and freshness.js
(its thresholds at the boundaries).
Run: cd apps/observatory && uv run python tests/test_look_time_pages.py"""

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
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

    check("no page error", not errs, errs)
    b.close()
    httpd.shutdown()
check.done()
