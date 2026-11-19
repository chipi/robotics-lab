"""The semantic map in the pages (RFC-0016), in headless Chromium: the objects in the 3D scene (each part a box from its bottom to its
top, in the map frame moved through the run's epoch, a confirmed one labelled with its kind, a landmark in its own colour), the
current sighting (the field of view on the floor from the belief pose, what it saw placed from that pose), and the Eye's panel
(SEES, ROOM and the objects confirmed, at the playhead; the room is not what the robot is "doing"). A sighting is current for one second.
Needs the system Chromium and Playwright. Screenshots to /tmp/claude-1000/semantic-pages/ (SEMANTIC_SHOTS=0 turns them off).
Run: cd apps/observatory && uv run python tests/test_semantic_pages.py"""

import math
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, get, make_run, serve, tick
from miniview.shots import launch

check = Checks("SEMANTIC PAGES")
SHOTS = Path("/tmp/claude-1000/semantic-pages") if os.environ.get("SEMANTIC_SHOTS", "1") != "0" else None
EPOCH = [0.5, -0.2, 0.3]                      # map -> world: a shift and a turn, so a missing transform shows
SCENE = {"id": "room", "name": "A room", "kind": "test", "bounds": [-1, 3, -1.5, 1.5], "boxes": [], "hazards": []}
FRIDGE = {"id": "fridge_1", "kind": "fridge", "x": 1.5, "y": 0.5, "n": 6, "confirmed": True, "landmark": 0.7, "permanence": "fixed",
          "confidence": 0.9, "parts": [[1.5, 0.5, 0.3, 0.25, 0.4, 0.0, 1.7], [1.8, 0.5, 0.1, 0.1, 0.0, 0.0, 0.3]]}
CABINET = {"id": "cabinet_1", "kind": "cabinet", "x": 0.5, "y": -0.5, "n": 1, "confirmed": False, "landmark": 0.69, "permanence": "fixed",
           "confidence": 0.6, "parts": [[0.5, -0.5, 0.25, 0.25, 0.0, 0.0, 0.6]]}
SIGHTING_POSE = [0.5, 0.1, 0.2]
SEEN = {"kind": "fridge", "x": 1.0, "y": 0.4, "radius": 0.4, "z0": 0.0, "z1": 1.7, "range_m": 1.08, "confidence": 0.8, "source": "sim_camera"}


def compose(a, b):
    c, s = math.cos(a[2]), math.sin(a[2])
    return [a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], a[2] + b[2]]


def decision(rule, reason, **values):
    return {"rule": rule, "reason": reason, "values": values}


def records():
    out = [(0.0, "epoch", {"map_to_world": EPOCH})]
    for k in range(30):
        b = [0.05 * k, 0.01 * k, 0.2]
        out.append(tick(round(1.0 + 0.1 * k, 3), b[0], belief=b, truth=compose(EPOCH, b), cmd=[0.3, 0.0], depth=[]))
    out += [(1.2, "event", {"kind": "tight_pivot", "text": "tight_pivot room_m 0.156", "notable": True, "t_src": 1.2, "raw": {},
                            "decision": decision("tight_pivot", "no clear floor for an arc", room_m=0.156)}),
            (1.5, "objects", {"objects": [CABINET], "changes": [["new", "cabinet_1"]]}),
            (2.0, "objects", {"objects": [CABINET, FRIDGE], "changes": [["new", "fridge_1"], ["confirmed", "fridge_1"]]}),
            (2.0, "sighting", {"pose": SIGHTING_POSE, "hfov_deg": 60.0, "range_m": 3.0, "seen": [SEEN]}),
            (2.5, "sighting", {"pose": [0.6, 0.12, 0.2], "hfov_deg": 60.0, "range_m": 3.0, "seen": []}),
            (2.6, "event", {"kind": "room", "text": "room kitchen", "notable": False, "t_src": 2.6, "raw": {}, "room": "kitchen",
                            "votes": {"office": 0.1, "kitchen": 0.4}, "decision": decision("room", "the objects near say: kitchen", votes=0.4)}),
            (3.95, "end", {"verdict": "reached"})]
    return sorted(out, key=lambda r: r[0])


# the site the run works at, with two of the operator's areas (RFC-0016 rev. 3), in the map frame
SITE = (1.0, "event", {"kind": "site", "text": "", "notable": False, "t_src": 1.0, "raw": {},
                       "site": {"id": "home", "name": "Home", "kind": "apartment",
                                "areas": [{"id": "area_1", "name": "Kitchen", "type": "kitchen", "polygon": [[0, -1], [1, -1], [1, 1], [0, 1]]},
                                          {"id": "area_2", "name": "Hall", "type": None, "polygon": [[1, -1], [2, -1], [2, 1], [1, 1]]}]}})

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(SCENE)
    make_run(data, "duck/room/sem1", sorted(records() + [SITE], key=lambda r: r[0]), started_at_ns=1_800_000_000 * 10**9)
    make_run(data, "duck/room/old1", [r for r in records() if r[1] not in ("objects", "sighting") and not (r[1] == "event" and r[2]["kind"] == "room")],
             started_at_ns=1_700_000_000 * 10**9)
    httpd, base = serve(cat, follow=False)

    def shot(page, name):
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f"{name}.png"))

    def ready(page, t=60000):
        page.wait_for_function("window.__ready === true", timeout=t)

    def call(page, js):
        page.evaluate("window.__ready = false")
        r = page.evaluate(js)
        ready(page)
        return r

    def open_page(b, url):
        page = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="dark").new_page()
        page.logs = []
        page.on("console", lambda m: page.logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") and "404" not in m.text else None)
        page.on("pageerror", lambda e: page.logs.append(f"pageerror: {e}"))
        page.goto(url)
        page.wait_for_function("window.miniview !== undefined", timeout=30000)
        ready(page)
        page.wait_for_function("window.miniview.state().run !== null", timeout=30000)
        page.evaluate("window.miniview.whenLoaded()")
        return page

    sem = "window.miniview.internals.adapter.semantic()"
    hud = "document.getElementById('hudtxt').textContent"

    with sync_playwright() as p:
        b = launch(p)
        page = open_page(b, f"{base}/web/three/#scene=room&run=duck/room/sem1&view=3d")
        check("the page opens with no errors", not page.logs, page.logs)
        streams = {s["id"]: s for s in page.evaluate("window.miniview.internals.shell().M.run.streams")}
        check("the run lists the semantic streams, counted, and they are on", streams["semantic.objects"]["count"] == 2 and streams["semantic.sighting"]["count"] == 2
              and not {"semantic.objects", "semantic.sighting"} & set(page.evaluate("window.miniview.state().hidden")), streams["semantic.objects"])

        # ---- before anything was recognised ------------------------------------------------------------------------
        call(page, "window.miniview.setTime(1.1)")
        s = page.evaluate(sem)
        check("before the first snapshot there are no objects drawn and no sighting", s["objects"] == 0 and s["sighting"] is None and s["labels"] == [], s)
        check("the site's areas are drawn from the start, each with its name", s["areas"] == ["Kitchen", "Hall"]
              and streams["semantic.areas"]["count"] == 2, (s, streams.get("semantic.areas")))

        # ---- the objects: parts as boxes, a confirmed one labelled, in the world frame through the epoch -----------------
        call(page, "window.miniview.setTime(1.6)")
        s = page.evaluate(sem)
        check("one unconfirmed object: drawn, not counted as confirmed, no label", s["objects"] == 1 and s["confirmed"] == 0 and s["labels"] == [], s)
        call(page, "window.miniview.setTime(2.05)")
        s = page.evaluate(sem)
        check("the newer snapshot replaces it: two objects, one confirmed, labelled with its kind", s["objects"] == 2 and s["confirmed"] == 1 and s["labels"] == ["fridge"], s)
        check("a landmark is an object whose landmark value is 0.7 or more: the fridge (0.7) is one, the cabinet (0.69) is not", s["landmarks"] == ["fridge_1"], s["landmarks"])
        check("both are shown (the streams are on) in the world frame", s["objectsVisible"] and s["sightingVisible"] and page.evaluate("window.miniview.state().frame") == "world", s)

        # ---- the camera's sighting ---------------------------------------------------------------------------------------
        sighting = s["sighting"]
        want_map = compose(SIGHTING_POSE, [SEEN["x"], SEEN["y"], 0.0])               # the detection is relative to the pose
        want_world = compose(EPOCH, want_map)
        got = sighting["seen"][0]
        check("the sighting is the one at the playhead: its pose, field of view and range", sighting["t"] == 2.0 and sighting["pose"] == SIGHTING_POSE and sighting["hfov_deg"] == 60 and sighting["range_m"] == 3.0, sighting)
        check("what it saw is placed from the sighting's pose, through the epoch, and labelled with its kind and confidence",
              got["kind"] == "fridge" and got["label"] == "fridge 80%" and all(abs(a - w) < 1e-6 for a, w in zip(got["world"], want_world[:2]))
              and all(abs(a - w) < 1e-6 for a, w in zip(got["map"], want_map[:2])), (got, want_world))
        check("a detection placed with the map frame alone would be elsewhere (the epoch shows)", math.dist(got["world"], got["map"]) > 0.1, got)
        shot(page, "3d")

        # ---- labels are readable at the default zoom: a fixed size on the screen, not in metres ---------------------------
        px = s["labelPx"]
        check("at the default view (11 m away) the labels, the confirmed fridge's and the detection's, are about 20 px tall", len(px) == 2 and all(18 <= v <= 22 for v in px), px)
        call(page, "window.miniview.setView('top')")
        px_top = page.evaluate(sem)["labelPx"]
        check("in the top view (another zoom, a parallel projection) they are the same size on the screen", len(px_top) == 2 and all(18 <= v <= 22 for v in px_top), px_top)
        call(page, "window.miniview.setView('3d')")

        # ---- the legend names what is drawn --------------------------------------------------------------------------------
        legend = lambda: page.evaluate("[...document.querySelectorAll('#legend span')].map((e) => e.textContent)")  # noqa: E731
        names = legend()
        check("the legend has the objects (confirmed, not yet, landmark), the field of view and the detections", {"Object", "Object, not yet", "Landmark", "Field of view", "Detection"} <= set(names), names)
        dots = page.evaluate("Object.fromEntries([...document.querySelectorAll('#legend span')].map((e) => [e.textContent, getComputedStyle(e.querySelector('i')).backgroundColor]))")
        check("... each in the colour the scene draws it in (green, amber, blue, magenta), the one not yet confirmed faint",
              dots["Object"] == "rgb(46, 158, 91)" and dots["Landmark"] == "rgb(232, 154, 0)" and dots["Field of view"] == "rgb(60, 120, 230)" and dots["Detection"] == "rgb(214, 43, 168)"
              and page.evaluate("getComputedStyle([...document.querySelectorAll('#legend span')].find((e) => e.textContent === 'Object, not yet').querySelector('i')).opacity") == "0.4", dots)
        call(page, "window.miniview.setVisible('semantic.sighting', false)")
        check("switching the sighting off takes its two entries away, the objects' stay", {"Field of view", "Detection"}.isdisjoint(legend()) and "Landmark" in legend(), legend())
        call(page, "window.miniview.setVisible('semantic.sighting', true)")
        call(page, "window.miniview.setVisible('semantic.objects', false)")
        check("switching the objects off takes theirs away, the sighting's stay", {"Object", "Object, not yet", "Landmark"}.isdisjoint(legend()) and "Detection" in legend(), legend())
        call(page, "window.miniview.setVisible('semantic.objects', true)")

        # ---- the page's state() has the semantic map as the API's /state does ---------------------------------------------------
        call(page, "window.miniview.setTime(2.05)")
        ps = page.evaluate("window.miniview.state().semantic")
        api = get(base, "/api/v1/runs/duck/room/sem1/state?t=2.05")[1]["semantic"]
        check("state().semantic at 2.05 s is the API's /state `semantic` for that time, value for value", ps == api and len(ps["objects"]) == 2 and ps["sighting"]["seen"][0]["kind"] == "fridge", (ps, api))
        call(page, "window.miniview.setTime(2.9)")
        ps = page.evaluate("window.miniview.state().semantic")
        api = get(base, "/api/v1/runs/duck/room/sem1/state?t=2.9")[1]["semantic"]
        check("... at 2.9 s too (the sighting that saw nothing, the room with its votes)", ps == api and ps["room"]["name"] == "kitchen" and ps["sighting"]["seen"] == [], (ps, api))
        st = page.evaluate("window.miniview.state()")
        api_st = get(base, "/api/v1/runs/duck/room/sem1/state?t=2.9")[1]
        check("state().last_event skips room events, as the API's does: the tight pivot, not `room kitchen`", st["last_event"]["kind"] == api_st["last_event"]["kind"] == "tight_pivot", (st["last_event"], api_st["last_event"]))

        # ---- a sighting is current for a second ---------------------------------------------------------------------------
        call(page, "window.miniview.setTime(2.9)")
        s = page.evaluate(sem)
        check("0.9 s after the sighting at 2.5 s (which saw nothing): that sighting is current and shows nothing", s["sighting"] is not None and s["sighting"]["t"] == 2.5 and s["sighting"]["seen"] == [], s["sighting"])
        call(page, "window.miniview.setTime(3.8)")
        check("1.3 s after the last sighting: no current sighting, the objects stay", page.evaluate(sem)["sighting"] is None and page.evaluate(sem)["objects"] == 2)

        # ---- the streams switch like any ------------------------------------------------------------------------------
        call(page, "window.miniview.setTime(2.05)")
        call(page, "window.miniview.setVisible('semantic.objects', false)")
        s = page.evaluate(sem)
        check("the objects switch off alone, the sighting stays", s["objectsVisible"] is False and s["sightingVisible"] is True
              and "semantic.objects" in page.evaluate("window.miniview.state().hidden"), s)
        call(page, "window.miniview.setVisible('semantic.objects', true)")
        call(page, "window.miniview.setVisible('semantic.sighting', false)")
        check("the sighting switches off alone", page.evaluate(sem)["sightingVisible"] is False and page.evaluate(sem)["objectsVisible"] is True)
        call(page, "window.miniview.setVisible('semantic.sighting', true)")

        # ---- the Eye's panel ------------------------------------------------------------------------------------------
        call(page, "window.miniview.setView('eye')")
        call(page, "window.miniview.setTime(1.1)")
        h = page.evaluate(hud)
        check("before any sighting, snapshot or room the Eye says so", "no sighting yet" in h and "not told yet" in h and "0 confirmed" in h, h)
        call(page, "window.miniview.setTime(2.05)")
        h = page.evaluate(hud)
        check("at 2.05 s: SEES the fridge with its range and confidence, the objects confirmed, no room yet",
              "SEES" in h and "fridge 1.1 m 80%" in h and "1 confirmed" in h and "1 not yet" in h and "not told yet" in h, h)
        call(page, "window.miniview.setTime(2.9)")
        h = page.evaluate(hud)
        check("at 2.9 s: the sighting saw nothing, the room is told with its votes, strongest first",
              "nothing in view" in h and "kitchen" in h and h.index("kitchen 0.40") < h.index("office 0.10"), h)
        check("the room is not what the robot is DOING: that stays the last decision, the pivot", "DOING" in h and "tight_pivot" in h and "room_m" in h, h)
        shot(page, "eye")

        # ---- a run from before --------------------------------------------------------------------------------------------
        old = open_page(b, f"{base}/web/three/#scene=room&run=duck/room/old1&view=eye")
        call(old, "window.miniview.setTime(2.05)")
        oh = old.evaluate(hud)
        check("a run with no semantic map: no SEES, ROOM or OBJECTS in the Eye, nothing drawn, no errors",
              "SEES" not in oh and "ROOM" not in oh and "OBJECTS" not in oh and "DOING" in oh and old.evaluate(sem)["objects"] == 0 and not old.logs, (oh, old.logs))
        check("a run with no semantic map: no `semantic` in state(), no semantic entries in the legend",
              "semantic" not in old.evaluate("window.miniview.state()") and {"Object", "Landmark", "Field of view", "Detection"}.isdisjoint(old.evaluate("[...document.querySelectorAll('#legend span')].map((e) => e.textContent)")))
        check("... and its semantic streams are missing, so hidden", {"semantic.objects", "semantic.sighting"} <= {s["id"] for s in old.evaluate("window.miniview.internals.shell().M.run.streams") if s["missing"]})
        check("no page errors on any page", not (page.logs or old.logs), (page.logs, old.logs))
        b.close()
    httpd.shutdown()

check.done()
