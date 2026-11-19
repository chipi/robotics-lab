"""The robot's eye, what it decided and the watch page (RFC-0013 prototype), in headless Chromium: the eye camera stands at the
depth sensor's recorded pose at the playhead (checked against an independent computation of the navigator's geometry, in the
world frame through the run's epoch), and at an estimate where a run records no frame state; the cone's darkness and the HUD; the
gaps stream (the unknown cells within 0.45 m of the plan in force, checked against an independent count) and its switch; real
hazards over the model; the Decided tab (the events with their rule, the one at the playhead marked, a click seeks); the watch
URLs (a run, `latest`, the errors), the watch page's layout, and the links between the explorer and the watch page at the same
moment. The live follow of the watch page is in test_live_page.py. Needs the system Chromium and Playwright.
Screenshots to /tmp/claude-1000/eye-pages/ (EYE_SHOTS=0 turns them off).
Run: cd apps/observatory && uv run python tests/test_eye_pages.py"""

import math
import os
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import Checks, catalog, get, make_run, serve, tick
from observatory.shots import launch

check = Checks("EYE PAGES")
SHOTS = Path("/tmp/claude-1000/eye-pages") if os.environ.get("EYE_SHOTS", "1") != "0" else None
EPOCH = [0.5, -0.2, 0.3]                      # map -> world: a shift and a turn, so a missing transform shows
TOF_PITCH_OFFSET_DEG = 3.0                    # duck_lab.nav.cliff's default, the one eye.js applies
MOUNT = ([0.08, 0.0, 0.11], 9.0)              # eye.js NOMINAL_MOUNT: where the sensor sits on the trunk, its pitch in degrees
TICKS = 30
SCENE = {"id": "room", "name": "A room", "kind": "test", "bounds": [-1, 3, -1.5, 1.5], "boxes": [],
         "hazards": [{"name": "pit", "kind": "drop", "x0": 1.2, "x1": 1.8, "y0": 0.4, "y1": 0.9, "depth": 0.3}]}
PLAN = [[0.0, 0.0], [0.5, 0.0], [1.0, 0.1], [1.5, 0.1]]
RES, ORIGIN, W, H = 0.1, [-0.5, -1.0], 40, 25


def qmul(a, b):
    return (a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
            a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0])


def rot(q, v):
    r = qmul(qmul(q, (0.0, *v)), (q[0], -q[1], -q[2], -q[3]))
    return r[1:]


qz = lambda a: (math.cos(a / 2), 0.0, 0.0, math.sin(a / 2))  # noqa: E731
qy = lambda a: (math.cos(a / 2), 0.0, math.sin(a / 2), 0.0)  # noqa: E731


def grid_cells():
    return "".join("." if (-0.3 <= ORIGIN[1] + (j + 0.5) * RES <= 0.3 and ORIGIN[0] + (i + 0.5) * RES < 1.5) else "?" for j in range(H) for i in range(W))


def expected_gaps(margin=0.45):
    """The unknown cells whose centre is within `margin` of the plan, and the other unknown cells (point to segment distances)."""
    gap = fog = 0
    for k, c in enumerate(grid_cells()):
        if c != "?":
            continue
        x, y = ORIGIN[0] + (k % W + 0.5) * RES, ORIGIN[1] + (k // W + 0.5) * RES
        best = 1e9
        for (ax, ay), (bx, by) in zip(PLAN, PLAN[1:]):
            dx, dy = bx - ax, by - ay
            u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            best = min(best, math.hypot(x - ax - u * dx, y - ay - u * dy))
        gap, fog = (gap + 1, fog) if best <= margin else (gap, fog + 1)
    return gap, fog


def belief(k):
    return [0.05 * k, 0.01 * k, 0.02 * k]


def state_of(k):
    """The state a depth frame was paired with: the IMU's tilt and a heading that is not the belief's, the sensor mounted on the trunk."""
    q = qmul(qz(0.4 + 0.02 * k), qy(0.05 + 0.002 * k))
    return {"quat": list(q), "odom_z": 0.118 + 0.0005 * k, "tof": {"pos": [0.08, 0.02, 0.11], "quat": list(qy(0.2 + 0.001 * k))}}


def points(k):
    """What the cliff check made of frame k, in map metres: a floor return and an obstacle (the tick's `depth` and the frame's `derived.points`)."""
    b = belief(k)
    return [[round(b[0] + 0.5, 3), round(b[1], 3), 0.0, "f"], [round(b[0] + 0.6, 3), round(b[1] + 0.1, 3), 0.3, "o"]]


def frame(k, with_state):
    t = round(1.0 + 0.1 * k + 0.01, 3)
    p = {"rows": 8, "cols": 8, "distance_mm": [300 + 20 * i for i in range(64)], "status": [5] * 64, "seq": k, "frame_t_ns": 1_000_000_000 + k,
         "state_t_ns": 1_000_000_000 + k - 1000, "pair_dt_ms": -0.001, "t_src": t, "derived": {"points": points(k)}}
    if with_state:
        p.update(state=state_of(k), pose=belief(k))
    return (t, "depth_frame", p)


def decision(rule, reason, **values):
    return {"rule": rule, "reason": reason, "values": values}


def records(with_state):
    out = [(0.0, "epoch", {"map_to_world": EPOCH}),
           (0.9, "world", {"grid": {"res": RES, "origin": ORIGIN, "w": W, "h": H, "cells": grid_cells()}, "obstacles": [], "drops": []}),
           (0.95, "plan", {"path": PLAN})]
    for k in range(TICKS):
        t = round(1.0 + 0.1 * k, 3)
        b = belief(k)
        out.append(tick(t, b[0], belief=b, truth=[b[0] + EPOCH[0], b[1] + EPOCH[1], b[2] + EPOCH[2]], cmd=[0.3, 0.05 * (k % 3)],
                        depth=points(k),
                        truth_3d={"z": 0.12, "quat": list(qmul(qz(b[2] + EPOCH[2]), qy(0.03)))}))
        if k % 2 == 0:
            out.append(frame(k, with_state))
    out += [(1.55, "event", {"kind": "tight_pivot", "text": "tight_pivot room_m 0.156", "notable": True, "t_src": 1.55, "raw": {},
                             "decision": decision("tight_pivot", "no clear floor for an arc", room_m=0.156, min_room_m=0.11)}),
            (2.35, "event", {"kind": "refused", "text": "refused why no room", "notable": True, "t_src": 2.35, "raw": {},
                             "decision": decision("refused", "no room to turn", room_m=0.106, min_room_m=0.11)}),
            (2.65, "event", {"kind": "invariant", "text": "invariant why 0.150 m from a drop's edge", "notable": True, "t_src": 2.65, "raw": {}}),
            (3.95, "end", {"verdict": "reached"})]
    return sorted(out, key=lambda r: r[0])


def attention_records():
    """The same run with what RFC-0012's first trigger makes the navigator do: a cliff stop, then a glance at the drop it stopped for (the
    recording writes a glance as not notable, as the first ones were), then a second glance that finds the floor."""
    rs = [r for r in records(True) if r[1] != "end"]
    rs += [(1.55, "event", {"kind": "cliff_stop", "text": "cliff_stop drop_m 0.538", "notable": True, "t_src": 1.55, "raw": {},
                            "decision": decision("cliff_stop", "a drop ahead seen in 3 frames in a row", drop_m=0.538, stop_m=0.6, zones=3, streak=3)}),
           (2.35, "event", {"kind": "glance", "text": "", "notable": False, "t_src": 2.35, "raw": {},
                            "decision": decision("glance", "a suspected drop near the way: looked at it with the head and saw its edge", bearing_deg=-7, distance_m=0.611,
                                                 status="drop", edge_m=0.545, time_s=0.6)}),
           (3.3, "event", {"kind": "glance", "text": "", "notable": False, "t_src": 3.3, "raw": {},
                           "decision": decision("glance", "a suspected drop near the way: looked at it with the head, nothing seen", bearing_deg=-2, distance_m=0.672,
                                                status="floor", edge_m=None, time_s=0.5)}),
           (3.95, "end", {"verdict": "reached"})]
    return sorted(rs, key=lambda r: r[0])


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(SCENE)
    make_run(data, "duck/room/eye1", records(True), started_at_ns=1_800_000_000 * 10**9)            # frames with their state: the newest run
    make_run(data, "duck/room/eye0", records(False), started_at_ns=1_700_000_000 * 10**9)           # frames without it: the eye is estimated
    make_run(data, "duck/room/eye2", attention_records(), started_at_ns=1_600_000_000 * 10**9)     # the oldest: with a cliff stop and glances
    httpd, base = serve(cat, follow=False)

    # ---- the watch URLs ---------------------------------------------------------------------------------------------
    def status(path):
        code, body, hdrs = get(base, path)
        return code, body, hdrs

    for path in ("/watch/duck/room/eye1", "/watch/duck/room/latest"):
        code, body, hdrs = status(path)
        check(f"GET {path} is the watch page", code == 200 and hdrs["Content-Type"].startswith("text/html") and '<base href="/web/three/">' in body and "Content-Security-Policy" in hdrs, code)
    check("a run that does not exist is a 404, a scene with no run for `latest` too",
          status("/watch/duck/room/nope")[0] == 404 and status("/watch/duck/nowhere/latest")[0] == 404 and status("/watch/duck/room")[0] == 404)
    check("a part that is not a name is a 400", status("/watch/Duck/room/eye1")[0] == 400 and status("/watch/duck/room/a%20b")[0] == 400)
    check("the watch page's files are the explorer's (one app.js, the same shell)", urllib.request.urlopen(f"{base}/web/three/app.js").status == 200)
    streams = {s["id"]: s for s in get(base, "/api/v1/runs/duck/room/eye1")[1]["streams"]}
    check("the run lists the gaps stream (one per map, it has a plan)", streams["world.gaps"]["count"] == 1 and not streams["world.gaps"]["missing"], streams["world.gaps"])
    code, fr, _ = get(base, "/api/v1/runs/duck/room/eye1/sensor?t=2.05")
    check("/sensor serves the paired state and the pose (the eye's inputs) but not the derived points",
          code == 200 and fr["state"] == state_of(10) and fr["pose"] == belief(10) and "derived" not in fr and abs(fr["t"] - 2.01) < 1e-6, str(fr)[:160])

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

    def open_page(b, url, *, whole=True):
        page = b.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="dark").new_page()
        page.logs = []
        page.on("console", lambda m: page.logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") and "404" not in m.text else None)
        page.on("pageerror", lambda e: page.logs.append(f"pageerror: {e}"))
        page.goto(url)
        page.wait_for_function("window.miniview !== undefined", timeout=30000)
        ready(page)
        page.wait_for_function("window.miniview.state().run !== null", timeout=30000)
        if whole:
            page.evaluate("window.miniview.whenLoaded()")
        return page

    def eye_at(page, t, source, frame_t):
        call(page, f"window.miniview.setTime({t})")
        page.wait_for_function(f"(() => {{ const e = window.miniview.state().eye; return e && e.source === '{source}' && Math.abs(e.frame_t - {frame_t}) < 1e-6; }})()", timeout=15000)
        return page.evaluate("window.miniview.state().eye")

    def near(a, b, tol):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    with sync_playwright() as p:
        b = launch(p)
        page = open_page(b, f"{base}/web/three/#scene=room&run=duck/room/eye1&view=eye")
        check("the eye view opens from the URL, in the world frame, with no page errors", page.evaluate("window.miniview.state().view") == "eye"
              and page.evaluate("window.miniview.state().frame") == "world" and not page.logs, page.logs)

        # ---- the eye at the recorded sensor pose ---------------------------------------------------------------
        def expected_eye(k):
            st, pose = state_of(k), belief(k)
            c, s = math.cos(EPOCH[2]), math.sin(EPOCH[2])
            wx, wy, wyaw = EPOCH[0] + c * pose[0] - s * pose[1], EPOCH[1] + s * pose[0] + c * pose[1], pose[2] + EPOCH[2]
            q = st["quat"]
            yaw_imu = math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
            trunk = qmul(qz(wyaw - yaw_imu), q)
            off = rot(trunk, st["tof"]["pos"])
            sensor = qmul(qmul(trunk, st["tof"]["quat"]), qy(math.radians(TOF_PITCH_OFFSET_DEG)))
            return [wx + off[0], wy + off[1], st["odom_z"] + off[2]], rot(sensor, (1, 0, 0)), rot(sensor, (0, 0, 1))

        for k, t in ((10, 2.05), (4, 1.45), (20, 3.05)):
            e = eye_at(page, t, "recorded", round(1.0 + 0.1 * k + 0.01, 3))
            pos, fwd, up = expected_eye(k)
            check(f"the eye at t={t} is at the sensor's recorded pose (frame {k}): position, direction and up within 2 mm / 0.1 degree",
                  near(e["position"], pos, 2e-3) and near(e["forward"], fwd, 2e-3) and near(e["up"], up, 2e-3) and e["fov"] == 75, (e, pos, fwd))
        # the camera really renders from there: it is not the explorer's orbit camera, and the eye moves with the playhead
        e2 = page.evaluate("window.miniview.state().eye")
        call(page, "window.miniview.setTime(1.45)")
        page.wait_for_function(f"Math.abs(window.miniview.state().eye.frame_t - {round(1.0 + 0.1 * 4 + 0.01, 3)}) < 1e-6", timeout=15000)
        check("the eye moves with the playhead", not near(page.evaluate("window.miniview.state().eye")["position"], e2["position"], 1e-3))

        # ---- the cone, the HUD ---------------------------------------------------------------------------------
        eye_at(page, 2.05, 'recorded', 2.01)
        view = page.evaluate("window.miniview.internals.adapter.eyeView()")
        side = view["h"] * math.tan(math.radians(22.5)) / math.tan(math.radians(view["fov"] / 2))
        box = page.evaluate("(() => { const r = document.querySelector('#eyecone i').getBoundingClientRect(); return [r.width, r.height]; })()")
        check("outside the sensor's 45 degree cone the view is darkened: the clear square is the cone's size in this camera",
              page.evaluate("!document.getElementById('eyecone').hidden") and abs(box[0] - side) < 1.5 and abs(box[1] - side) < 1.5, (box, side))
        hud = page.evaluate("document.getElementById('hudtxt').textContent")
        mom = page.evaluate("window.miniview.internals.shell().M.fr.cmd[window.miniview.state().tick]")
        check("the HUD says the pace (the tick's command), what was decided, the numbers it compared, the returns, where the pose came from",
              f"{mom[0]:.2f} m/s" in hud and "tight_pivot" in hud and "room_m" in hud and "0.156" in hud and "min_room_m" in hud and "0.11" in hud
              and "floor" in hud and "obstacle" in hud and "recorded" in hud, hud)
        check("the 8 x 8 distances are drawn", page.evaluate("[document.getElementById('hudcv').width, document.getElementById('hudcv').height]") == [8, 8])
        shot(page, "eye")

        # ---- the returns where the cliff check put them ------------------------------------------------------------
        check("the playhead is on tick 10, the frame the eye was placed from", page.evaluate("window.miniview.state().tick") == 10)
        c, sn = math.cos(EPOCH[2]), math.sin(EPOCH[2])
        want = {"f": [], "o": [], "v": [], "b": []}
        for x, y, z, kind in points(10):                                          # the frame's derived.points, through the run's epoch
            want[kind].append([EPOCH[0] + c * x - sn * y, EPOCH[1] + sn * x + c * y, z])
        drawn = page.evaluate("window.miniview.internals.adapter.returns(10)")
        check("each return is drawn where the cliff check put it (the frame's derived.points, through the epoch), with its class",
              {k: len(v) for k, v in drawn.items()} == {k: len(v) for k, v in want.items()}
              and all(near(a, w, 1e-4) for k in want for a, w in zip(drawn[k], want[k])), (drawn, want))
        check("a return is not where the map frame alone would put it (the epoch shows)", not near(drawn["f"][0], points(10)[0][:3], 0.05), drawn["f"])
        check("the HUD alerts on what the robot did, not on every event: a refusal and a tight pivot raise none",
              all(page.evaluate(f"(window.miniview.setTime({t}), window.miniview.state().alerts)") == [] for t in (1.6, 2.4)))

        # ---- an estimate where the run records no frame state ----------------------------------------------------
        page0 = open_page(b, f"{base}/web/three/#scene=room&run=duck/room/eye0&view=eye")
        e = eye_at(page0, 2.05, "estimated", 2.0)
        tq = qmul(qz(0.2 + EPOCH[2]), qy(0.03))
        off = rot(tq, MOUNT[0])
        tx, ty = 0.05 * 10 + EPOCH[0], 0.01 * 10 + EPOCH[1]
        pos, fwd = [tx + off[0], ty + off[1], 0.12 + off[2]], rot(qmul(tq, qy(math.radians(MOUNT[1]))), (1, 0, 0))
        check("a run whose frames carry no state: the eye is estimated from the truth's pose and the nominal mount, and the HUD says so",
              near(e["position"], pos, 2e-3) and near(e["forward"], fwd, 2e-3) and "estimated" in page0.evaluate("document.getElementById('hudtxt').textContent"), (e, pos, fwd))

        # ---- the chase camera ------------------------------------------------------------------------------------
        call(page, "window.miniview.setView('chase')")
        check("the chase view opens (no eye, no HUD), in the world frame", page.evaluate("window.miniview.state().view") == "chase"
              and page.evaluate("window.miniview.state().eye") is None and page.evaluate("document.getElementById('eyehud').hidden"))
        shot(page, "chase")

        # ---- the gaps --------------------------------------------------------------------------------------------
        call(page, "window.miniview.setView('3d')")
        call(page, "window.miniview.setTime(2.05)")
        gap, fog = expected_gaps()
        page.wait_for_function("window.miniview.internals.adapter.gaps().gap > 0", timeout=15000)
        got = page.evaluate("window.miniview.internals.adapter.gaps()")
        check("the gaps are the unknown cells within 0.45 m of the plan in force, the rest of the unknown is fog", got["gap"] == gap and got["fog"] == fog and got["visible"],
              (got, gap, fog))
        check("the page's own rule agrees (gapCells, the margin 0.45 m)", page.evaluate(
            f"import('/web/shell/gaps.js').then((m) => [m.GAP_MARGIN_M, m.gapCells({{res: {RES}, origin: {ORIGIN}, w: {W}, h: {H}, cells: '{grid_cells()}'}}, {PLAN}).gap.length])") == [0.45, gap])
        check("a narrower margin finds fewer gaps (the count is the margin's, not a constant)", expected_gaps(0.2)[0] < gap)
        check("the stream is in the World model group, listed and on", "world.gaps" in page.evaluate("window.miniview.internals.shell().M.run.streams.map((s) => s.id)")
              and "world.gaps" not in page.evaluate("window.miniview.state().hidden"))
        call(page, "window.miniview.setVisible('world.gaps', false)")
        check("the gaps switch off like any stream, and back on", page.evaluate("window.miniview.state().hidden").count("world.gaps") == 1
              and page.evaluate("window.miniview.internals.adapter.gaps().visible") is False)
        call(page, "window.miniview.setVisible('world.gaps', true)")
        check("... and back on", page.evaluate("window.miniview.internals.adapter.gaps().visible") is True and "world.gaps" not in page.evaluate("window.miniview.state().hidden"))
        sh = "window.miniview.internals.shell()"
        check("the real hazards over the model are an option, off in the explorer", page.evaluate(f"{sh}.shown('hazards.top')") is False)
        call(page, "window.miniview.setOverlay('hazards_top', true)")
        check("... on with the overlay, and gone when the scene's hazards are hidden", page.evaluate(f"{sh}.shown('hazards.top')") is True
              and page.evaluate("window.miniview.config().overlays.hazards_top") is True)
        call(page, "window.miniview.setVisible('scene.hazards', false)")
        check("... (hidden with them)", page.evaluate(f"{sh}.shown('hazards.top')") is False)
        call(page, "window.miniview.setVisible('scene.hazards', true)")
        call(page, "window.miniview.setOverlay('coords', false)")
        shot(page, "3d-gaps")

        # ---- what it decided -------------------------------------------------------------------------------------
        call(page, "window.miniview.setTime(2.0)")
        page.click("#tabDecided")
        rows = page.evaluate("[...document.querySelectorAll('#inspBody .dec')].map((r) => ({t: +r.dataset.t, rule: r.querySelector('.dr').textContent, cls: r.className, txt: r.textContent}))")
        check("the Decided tab lists the events with their rule, then the verdict, with their times",
              [(r["rule"], round(r["t"], 2)) for r in rows] == [("tight_pivot", 1.55), ("refused", 2.35), ("invariant", 2.65), ("verdict", 3.9)], rows)
        check("a decision shows its reason and the values it compared; the judge's rows are marked",
              "no clear floor for an arc" in rows[0]["txt"] and "room_m 0.156" in rows[0]["txt"] and "min_room_m 0.11" in rows[0]["txt"]
              and "judge" in rows[2]["cls"] and "judge" in rows[3]["cls"], rows[0])
        now = lambda: page.evaluate("[...document.querySelectorAll('#inspBody .dec')].filter((r) => r.classList.contains('now')).map((r) => +r.dataset.t)")  # noqa: E731
        check("the one at or before the playhead is marked", now() == [1.55] and page.evaluate("window.miniview.state().decided") == {"n": 3, "now": 1.55}, now())
        page.click("#inspBody .dec:nth-child(3)")
        page.wait_for_function("Math.abs(window.miniview.state().t - 2.35) < 1e-6", timeout=10000)
        check("a click on a decision seeks to it, and the mark follows", now() == [2.35] and page.evaluate("window.miniview.state().follow") is False, now())
        call(page, "window.miniview.setTime(1.2)")
        check("before the first decision none is marked", now() == [] and page.evaluate("window.miniview.state().decided")["now"] is None)
        shot(page, "decided")
        b_state_logs = list(page.logs)

        # ---- the attention alert: what the robot did (a cliff stop, a glance), from the recorded events --------------
        att = open_page(b, f"{base}/web/three/#scene=room&run=duck/room/eye2&view=eye")

        def alerts(t):
            call(att, f"window.miniview.setTime({t})")
            return (att.evaluate("window.miniview.state().alerts.map((a) => [a.kind, a.phase])"),
                    att.evaluate("[...document.querySelectorAll('#hudtxt .alert')].map((a) => a.textContent)"))

        check("nothing the robot did, no alert", alerts(1.2) == ([], []))
        st, txt = alerts(1.6)
        check("a cliff stop: STOPPED, with the recorded reason and the numbers", st == [["cliff_stop", "stopped"]] and len(txt) == 1
              and all(w in txt[0] for w in ("STOPPED", "a drop ahead seen in 3 frames in a row", "0.538", "0.60", "3 frames in a row")), (st, txt))
        st, txt = alerts(2.0)
        check("during the glance (its event comes when it ends): the stop and LOOKING, with the bearing and the distance, no result yet",
              st == [["cliff_stop", "stopped"], ["glance", "looking"]] and "LOOKING" in txt[1] and "saw" not in txt[1] and "−7°" in txt[1] and "0.61 m ahead" in txt[1] and "edge" not in txt[1], (st, txt))
        st, txt = alerts(2.4)
        check("after it: LOOKED, what it saw and where the edge is, from the glance's values",
              st == [["cliff_stop", "stopped"], ["glance", "looked"]] and "LOOKED" in txt[1] and "saw drop" in txt[1] and "edge 0.545 m" in txt[1], (st, txt))
        shot(att, "attention")
        st, txt = alerts(3.0)
        check("at most the two newest: the first glance's result and the second glance under way", st == [["glance", "looked"], ["glance", "looking"]], (st, txt))
        st, txt = alerts(3.5)
        check("a glance that found only floor says so and has no edge", st[-1] == ["glance", "looked"] and "saw floor" in txt[-1] and "edge" not in txt[-1], (st, txt))
        check("the alert goes after 4 s (the pure rule): held to 4 s after the event, gone after",
              att.evaluate("import('/web/shell/eye.js').then((m) => { const ev = [{kind: 'cliff_stop', t: 1.55}]; return [m.attentionAt(ev, 5.5).length, m.attentionAt(ev, 5.6).length, m.attentionAt(ev, 1.5).length]; })") == [1, 0, 0])
        att.click("#tabDecided")
        check("the Decided tab lists the glances, though the recording wrote them as not notable, with their decision's reason",
              att.evaluate("[...document.querySelectorAll('#inspBody .dec .dr')].map((e) => e.textContent)") == ["tight_pivot", "cliff_stop", "refused", "glance", "invariant", "glance", "verdict"]
              and "saw its edge" in att.evaluate("document.querySelector('#inspBody .dec:nth-child(5)').textContent"))

        # ---- the links, both ways, at the same moment --------------------------------------------------------------
        call(page, "window.miniview.setTime(2.05)")
        wl = page.evaluate("document.getElementById('watchLink').getAttribute('href')")
        check("the explorer links to the watch page at the playhead", wl == "/watch/duck/room/eye1#t=2.05" and page.evaluate("!document.getElementById('watchLink').hidden"), wl)
        w = open_page(b, base + wl, whole=False)
        w.wait_for_function("Math.abs(window.miniview.state().t - 2.05) < 1e-6", timeout=15000)
        ws = w.evaluate("window.miniview.state()")
        check("the watch page opens at that moment: the run, the watch view, follow off (a moment was named), the decisions beside it",
              ws["run"] == "duck/room/eye1" and ws["view"] == "watch" and ws["follow"] is False and ws["tab"] == "decided" and ws["decided"]["n"] == 3, (ws["run"], ws["view"], ws["tab"]))
        check("the watch page is the eye with the top view inset, the HUD, the real hazards over the model, no left panel",
              w.evaluate("document.querySelectorAll('#stage .slot').length") == 2 and w.evaluate("[...document.querySelectorAll('#stage .slot .cap')].map((c) => c.textContent)") == ["world · eye", "world · top"]
              and w.evaluate("!document.getElementById('eyehud').hidden") and w.evaluate("document.querySelector('.app').classList.contains('watch')")
              and w.evaluate("getComputedStyle(document.getElementById('left')).display") == "none" and w.evaluate("window.miniview.config().overlays.hazards_top") is True)
        check("the timeline marks the events", w.evaluate("document.querySelectorAll('#mlane .mk').length") == 3)
        w.wait_for_function("(() => { const e = window.miniview.state().eye; return e && e.source === 'recorded' && Math.abs(e.frame_t - 2.01) < 1e-6; })()", timeout=15000)
        check("the eye of the watch page is the recorded sensor pose too", near(w.evaluate("window.miniview.state().eye")["position"], expected_eye(10)[0], 2e-3))
        el = w.evaluate("document.getElementById('exploreLink').getAttribute('href')")
        check("the watch page links to the explorer at the same moment, on the eye",
              el == "/web/three/#scene=room&run=duck%2Froom%2Feye1&view=eye&frame=world&t=2.05" and w.evaluate("!document.getElementById('exploreLink').hidden")
              and w.evaluate("document.getElementById('watchLink').hidden"), el)
        shot(w, "watch")
        back = open_page(b, base + el, whole=False)
        back.wait_for_function("Math.abs(window.miniview.state().t - 2.05) < 1e-6", timeout=15000)
        check("... and the explorer opens there: the same run, the eye, the same time", back.evaluate("window.miniview.state().view") == "eye"
              and back.evaluate("window.miniview.state().run") == "duck/room/eye1" and back.evaluate("document.querySelector('.app').classList.contains('watch')") is False)

        # `latest` is the scene's newest run
        lw = open_page(b, f"{base}/watch/duck/room/latest", whole=False)
        check("/watch/<robot>/<scene>/latest opens the scene's newest run", lw.evaluate("window.miniview.state().run") == "duck/room/eye1", lw.evaluate("window.miniview.state().run"))
        check("no page errors on any page", not (page.logs or b_state_logs or w.logs or back.logs or lw.logs or page0.logs or att.logs), (page.logs, w.logs, back.logs, lw.logs, page0.logs, att.logs))
        b.close()
    httpd.shutdown()

check.done()
