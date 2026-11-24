"""The look-and-feel guards of the shell modules (step 4.5): U7 the layout store (libs/web/layout/store.js) in headless Chromium: save, load, list,
remove; an export imported into a fresh browser context; every kind of bad import refused with the current layout untouched; unknown keys dropped;
a blob of another version ignored; storage that throws or is absent degrades to memory without a throw; miniview.left migrated once.
Sections follow one another on the same page and server: add the next unit's section before the final `finish` block.
Run: cd apps/observatory && uv run python tests/test_look_shell_pages.py"""

import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, scene, serve
from observatory.shots import launch

check = Checks("LOOK SHELL PAGES")

STORE = "import('/lib/layout/store.js')"
MAKE = """async ([app, pre]) => {
  localStorage.clear();
  for (const [k, v] of Object.entries(pre || {})) localStorage.setItem(k, v);
  const { createLayoutStore } = await import('/lib/layout/store.js');
  window.S = createLayoutStore({ app });
  return true;
}"""
# runs fn(S) and returns its value, or {err: message} when it threw
RUN = """async (src) => { try { return { v: await (new Function('S', 'return (' + src + ')'))(window.S) }; } catch (e) { return { err: String(e.message || e) }; } }"""


def run(page, src):
    return page.evaluate(RUN, src)


def make(page, app="observatory", pre=None):
    page.evaluate(MAKE, [app, pre])


def obs_state(**panels):
    return {"panels": {"left": True, "right": True, "open": {}, "angles": True, **panels}, "widths": {"left": 280, "right": 320}}


def doc(**over):
    d = {"app": "observatory", "version": 1, "name": "wide", "state": obs_state(left=False)}
    d.update(over)
    return json.dumps(d)


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    cat = catalog(Path(tmp) / "data")
    cat.put_scene(scene("apartment"))
    cat.scan()
    httpd, base = serve(cat, follow=False)
    b = launch(p)
    page = b.new_page()
    page.set_default_timeout(8000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/web/three/")

    # ---- U7: the layout store ------------------------------------------------------------------------------------------------------------
    make(page)
    check("a fresh store has no layouts and no current one; get() is the defaults", run(page, "[S.list(), S.current(), S.get()]")["v"] == [[], None, obs_state()])
    check("save returns the name and makes it current", run(page, f"[S.save('mine', {json.dumps(obs_state(left=False))}), S.current(), S.list()]")["v"] == ["mine", "mine", ["mine"]])
    check("get() is the current layout", run(page, "S.get().panels.left")["v"] is False)
    run(page, f"S.save('b', {json.dumps(obs_state(right=False))})")
    r = run(page, "[S.load('mine').panels.left, S.current(), S.get().panels.left, S.list()]")["v"]
    check("load returns that layout and makes it current; list is sorted", r == [False, "mine", False, ["b", "mine"]], r)
    check("loading a name that is not saved throws and keeps the current one", "no saved layout" in run(page, "S.load('nope')").get("err", "") and run(page, "S.current()")["v"] == "mine")
    check("remove of the current layout clears current and get() falls back to the defaults", run(page, "[S.remove('mine'), S.current(), S.get().panels.left, S.list()]")["v"] == [True, None, True, ["b"]])
    check("remove of an unsaved name is false", run(page, "S.remove('zzz')")["v"] is False)
    persisted = page.evaluate("[localStorage.getItem('rl.layouts.observatory'), localStorage.getItem('rl.layout.current.observatory')]")
    check("the keys are rl.layouts.<app> and rl.layout.current.<app>", json.loads(persisted[0])["version"] == 1 and persisted[1] is None, persisted)
    check("a new store over the same storage sees the layouts", page.evaluate("import('/lib/layout/store.js').then((m) => m.createLayoutStore({app: 'observatory'}).list())") == ["b"])
    check("the two apps do not share layouts", page.evaluate("import('/lib/layout/store.js').then((m) => m.createLayoutStore({app: 'control'}).list())") == [])
    check("a bad name or app is refused", all(run(page, f"S.save({n}, {json.dumps(obs_state())})").get("err") for n in ("''", "'  '", "7", "'x'.repeat(61)", "'__proto__'"))
          and "app must be" in page.evaluate("import('/lib/layout/store.js').then((m) => { try { m.createLayoutStore({app: 'x'}); return 'ok'; } catch (e) { return e.message; } })"))

    ev = page.evaluate("""async () => {
      const { createLayoutStore } = await import('/lib/layout/store.js');
      const s = createLayoutStore({ app: 'observatory' }), seen = [];
      const off = s.onChange((cur) => seen.push(cur));
      s.save('a', s.get()); s.load('a'); s.remove('a'); off(); s.save('c', s.get());
      return seen;
    }""")
    check("onChange fires on save, load and remove, and stops after the returned off()", ev == ["a", "a", None], ev)

    # export, then import into a fresh browser context (new localStorage)
    make(page)
    run(page, f"S.save('wide', {json.dumps(obs_state(left=False, open={'a': True}))})")
    text = run(page, "S.exportJSON()")["v"]
    d = json.loads(text)
    check("exportJSON names the app, the version and the layout; the current one is the default", (d["app"], d["version"], d["name"]) == ("observatory", 1, "wide") and d["state"]["panels"]["open"] == {"a": True}, d)
    check("export of an unsaved name throws", "no saved layout" in run(page, "S.exportJSON('zzz')").get("err", ""))
    fresh = b.new_context().new_page()
    fresh.goto(base + "/web/three/")
    make(fresh)
    got = fresh.evaluate(RUN, f"[S.importJSON({json.dumps(text)}), S.current(), S.get()]")["v"]
    check("a fresh context imports the export: same name, current, same state", got == ["wide", "wide", d["state"]], got)
    got2 = fresh.evaluate(RUN, f"[S.importJSON({json.dumps(text)}), S.list()]")["v"]
    check("importing a name that exists keeps both (the new one is renamed)", got2 == ["wide 2", ["wide", "wide 2"]], got2)
    fresh.context.close()

    # bad imports: each refused with a clear error and the saved layouts and current one untouched
    make(page)
    run(page, f"S.save('keep', {json.dumps(obs_state(left=False))})")
    before = page.evaluate("[localStorage.getItem('rl.layouts.observatory'), localStorage.getItem('rl.layout.current.observatory')]")
    bad_state = obs_state()
    bad_state["panels"]["left"] = "yes"
    wide_widths = obs_state()
    wide_widths["widths"]["left"] = "280"
    nan_state = json.loads(json.dumps(obs_state()))
    big_open = {f"k{i}": True for i in range(300)}
    cases = {
        "not JSON": ("{nope", "not valid JSON"),
        "not an object": ("[1, 2]", "not a layout file"),
        "wrong app": (doc(app="control"), "not observatory"),
        "no app": (doc(app=None), "not observatory"),
        "newer version": (doc(version=2), "version 2"),
        "older version": (doc(version=0), "version 0"),
        "version as text": (doc(version="1"), 'version "1"'),
        "no name": (doc(name=""), "layout name"),
        "name not text": (doc(name=5), "layout name"),
        "wrong type (boolean as text)": (doc(state=bad_state), "panels.left must be a boolean"),
        "wrong type (number as text)": (doc(state=wide_widths), "widths.left must be a number"),
        "state not an object": (doc(state=[1]), "must be an object"),
        "state missing": (doc(state=None), "must be an object"),
        "free map holds an object": (doc(state={**obs_state(), "panels": {**obs_state()["panels"], "open": {"a": {"x": 1}}}}), "panels.open.a"),
        "free map too large": (doc(state={**obs_state(), "panels": {**obs_state()["panels"], "open": big_open}}), "more than 200 keys"),
        "over the size cap": ("{" + '"app":"observatory","pad":"' + "x" * 70000 + '"}', "larger than 64 KB"),
    }
    for label, (payload, want) in cases.items():
        r = run(page, f"S.importJSON({json.dumps(payload)})")
        after = page.evaluate("[localStorage.getItem('rl.layouts.observatory'), localStorage.getItem('rl.layout.current.observatory')]")
        check(f"bad import refused ({label}): a clear error, nothing written", want in r.get("err", "") and after == before, r)
    check("a non-text import is refused", "is text" in run(page, "S.importJSON(42)").get("err", ""))
    check("the current layout is untouched after all of them", run(page, "[S.current(), S.list(), S.get().panels.left]")["v"] == ["keep", ["keep"], False])

    # unknown keys dropped (top level, nested, and in a saved layout), missing keys filled from the defaults
    st = obs_state(left=False)
    st["extra"] = {"x": 1}
    st["panels"]["bogus"] = 1
    st["widths"]["top"] = 9
    del st["widths"]["right"]
    page_name = run(page, f"S.importJSON({json.dumps(doc(name='dirty', state=st))})")["v"]
    got = run(page, "S.get()")["v"]
    check("unknown keys are dropped on import and a missing one takes its default", page_name == "dirty" and got == {"panels": obs_state(left=False)["panels"], "widths": {"left": 280, "right": 320}}, got)
    page.evaluate("(blob) => localStorage.setItem('rl.layouts.observatory', blob)", json.dumps({"version": 1, "layouts": {"x": st, "bad": {"panels": 1}}}))
    page.evaluate("import('/lib/layout/store.js').then((m) => { window.S = m.createLayoutStore({app: 'observatory'}); })")
    r = run(page, "[S.list(), (S.load('x'), S.get())]")["v"]
    check("a saved layout is conformed on read: unknown dropped, a wrong-shaped one skipped", r[0] == ["x"] and "bogus" not in r[1]["panels"] and "extra" not in r[1], r)
    pol = doc(name="p", state=obs_state(open={"a": True})).replace('"a": true', '"__proto__": true')
    r = run(page, f"[S.importJSON({json.dumps(pol)}), Object.keys(S.get().panels.open), ({{}}).polluted === undefined, Object.getPrototypeOf(S.get().panels.open) === Object.prototype]")["v"]
    check("a __proto__ key in a free map is dropped and does not reach the prototype", r == ["p", [], True, True], r)

    # a blob of another version is ignored, not read and not overwritten with garbage
    make(page, pre={"rl.layouts.observatory": json.dumps({"version": 2, "layouts": {"future": obs_state()}}), "rl.layout.current.observatory": "future"})
    check("a stored blob of another version is ignored: no layouts, no current, get() is the defaults", run(page, "[S.list(), S.current(), S.get()]")["v"] == [[], None, obs_state()])
    make(page, pre={"rl.layouts.observatory": "{not json", "rl.layout.current.observatory": "x"})
    check("a stored blob that does not parse is ignored", run(page, "[S.list(), S.current()]")["v"] == [[], None])

    # storage that throws or is absent degrades to memory
    deg = page.evaluate("""async () => {
      const { createLayoutStore } = await import('/lib/layout/store.js');
      const boom = () => { throw new DOMException('quota', 'QuotaExceededError'); };
      const out = {};
      for (const [label, storage] of [['setItem throws', { getItem: () => null, setItem: boom, removeItem: boom }],
                                      ['everything throws', { getItem: boom, setItem: boom, removeItem: boom }], ['null', null]]) {
        try {
          const s = createLayoutStore({ app: 'observatory', storage });
          const st = s.get();
          s.save('m', st); const cur = s.current(), list = s.list(), exp = JSON.parse(s.exportJSON()).name;
          const imp = s.importJSON(s.exportJSON()); s.remove('m');
          out[label] = [cur, list, exp, imp, s.list(), s.durable];
        } catch (e) { out[label] = 'threw ' + e.message; }
      }
      return out;
    }""")
    want = ["m", ["m"], "m", "m 2", ["m 2"], False]
    for label, r in deg.items():
        check(f"storage that fails ({label}) degrades to memory without a throw", r == want, r)

    # the legacy miniview.left (the shell's open sections and the joint-angle switch) is read once into the Observatory's panels
    legacy = {"open": {"sec1": True, "sec2": False}, "angles": False}
    make(page, pre={"miniview.left": json.dumps(legacy)})
    r = run(page, "[S.list(), S.current(), S.get()]")["v"]
    check("miniview.left migrates into the panels state as the default layout", r[0] == ["default"] and r[1] == "default" and r[2]["panels"]["open"] == legacy["open"] and r[2]["panels"]["angles"] is False and r[2]["widths"] == obs_state()["widths"], r)
    page.evaluate("localStorage.setItem('miniview.left', JSON.stringify({open: {late: true}, angles: true}))")
    run(page, "S.remove('default')")
    again = page.evaluate("import('/lib/layout/store.js').then((m) => { const s = m.createLayoutStore({app: 'observatory'}); return [s.list(), s.get().panels.open]; })")
    check("... once: after the layout is removed a new store does not migrate again", again == [[], {}], again)
    make(page, "control", pre={"miniview.left": json.dumps(legacy)})
    check("Mission Control does not read miniview.left", run(page, "S.list()")["v"] == [])
    make(page, pre={"miniview.left": "{nope"})
    check("a legacy value that does not parse is ignored", run(page, "[S.list(), S.get()]")["v"] == [[], obs_state()])
    make(page, pre={"miniview.left": json.dumps({"open": {"a": {"x": 1}}, "angles": "no"})})
    check("a legacy value of the wrong shape migrates nothing", run(page, "S.list()")["v"] == [])

    check("no page error while the store ran", not errors, errors)

    b.close()
    httpd.shutdown()
check.done()
