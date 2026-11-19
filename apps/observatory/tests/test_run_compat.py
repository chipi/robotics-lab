"""A run opens fully in Rerun and in miniview, kept compatible on purpose (ADR-0007 "Compatibility"): Rerun (rerun mcap
check, mcap convert, rrd verify, the rows decoded) and miniview (the service loads and serves the same file). The fixture is
explore9 imported into a temp folder; an NXT run (ADR-0013) also has a signal plotted in a Rerun time series view from a
blueprint. Lichtblick's checks (its image, headless: alerts, start date, topics, the 3D panel, the NXT signal in
Raw Messages and a Plot panel) are skipped unless COMPAT_LICHTBLICK=1: its UI's timing failed CI runs that were not
ours (the operator, 2026-11-16). Needs robots/duck/.venv (rerun-sdk: `make duck-sync`), Chromium, and Docker for Lichtblick. Run: make test-run-compat
or: cd apps/observatory && uv run python tests/test_run_compat.py"""

import base64
import datetime
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from mcap.reader import make_reader
from playwright.sync_api import sync_playwright

from helpers import T0_NS, Checks, catalog, get, import_fixture, scene, serve, wait_until
from runfile.adapters import nxt
from miniview.shots import launch

check = Checks("RUN COMPAT")
REPO = Path(__file__).resolve().parents[3]
RERUN = REPO / "robots" / "duck" / ".venv" / "bin" / "rerun"
# Lichtblick is not tested unless COMPAT_LICHTBLICK=1 (the operator, 2026-11-16: driving its UI failed CI runs for
# reasons in its UI, not in our files). The checks are kept for when that is fixed.
LICHTBLICK_ON = os.environ.get("COMPAT_LICHTBLICK") == "1"
# Pinned by digest (the version this was written against: it checked 2026-11-16); how to bump it is in ADR-0007 "Compatibility".
LICHTBLICK = os.environ.get("LICHTBLICK_IMAGE", "ghcr.io/lichtblick-suite/lichtblick@sha256:25333a8f57737c8c5866abf75670b8dcf2ed6c2cb5ce3d64f3c63f210a5177e9")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
FRIDGE_SLICE = Path(__file__).resolve().parent / "fixtures" / "find-fridge-slice"
FOXGLOVE_TOPICS = ["/belief/pose", "/truth/pose", "/tf", "/map", "/depth"]


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    return r.returncode, ANSI.sub("", r.stdout + r.stderr)


def entities(text):
    m = re.search(r"Entities: \{(.*?)\}", text, re.S)
    return {e.strip().rstrip(",") for e in m.group(1).split("\n") if e.strip()} if m else set()


def lb_wait(pg, js, timeout=30000):
    """pg.wait_for_function for a Lichtblick page; on a timeout, the page's visible text, so a failure in CI says what was
    there instead (CI 2026-11-16: the transforms note did not show, twice in four runs, with nothing to go on)."""
    try:
        pg.wait_for_function(js, timeout=timeout)
    except Exception:
        text = re.sub(r"\n+", " | ", pg.locator("body").inner_text())
        print(f"waited {timeout / 1000:.0f} s for {js[:90]!r}; the page showed: {text[:1500]}", flush=True)
        raise


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Rerun draws on a canvas: the line is found by its colour in a screenshot (the blueprint makes it pure red), decoded by the
# browser, as no image library is a dependency here.
LINE_STATS = """async (png) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + png; await img.decode();
  const c = new OffscreenCanvas(img.width, img.height), g = c.getContext('2d'); g.drawImage(img, 0, 0);
  const d = g.getImageData(0, 0, img.width, img.height).data, cols = new Map();
  for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
    const k = (y * img.width + x) * 4;
    if (d[k] > 200 && d[k + 1] < 60 && d[k + 2] < 60) cols.set(x, Math.min(cols.get(x) ?? 1e9, y));
  }
  const xs = [...cols.keys()].sort((a, b) => a - b), w = img.width, ys = (f) => xs.filter(f).map((x) => cols.get(x));
  const mean = (a) => a.reduce((s, v) => s + v, 0) / Math.max(a.length, 1);
  return { columns: xs.length, span: xs.length ? (xs[xs.length - 1] - xs[0]) / w : 0,
           left_y: mean(ys((x) => x < w * 0.3)), right_y: mean(ys((x) => x > w * 0.7)) };
}"""


def rerun_plot(browser, rrd, app, entity, component, field, shot):
    """`field` of the struct on `entity` in Rerun's web viewer, plotted by a blueprint: the red line's columns (screen x
    with a red pixel), its horizontal span (a fraction of the width) and its mean screen y on the left and on the right."""
    rbl = rrd.with_name(f"{field}.rbl")
    rc, out = run([REPO / "robots" / "duck" / ".venv" / "bin" / "python", Path(__file__).with_name("rerun_blueprint.py"), app, rbl, entity, component, field])
    assert rc == 0, out
    web, grpc = free_port(), free_port()
    # bin/rerun is a wrapper that starts the viewer as a child: its own process group, so stopping the group stops both
    proc = subprocess.Popen([str(RERUN), str(rrd), str(rbl), "--web-viewer", "--bind", "127.0.0.1", "--web-viewer-port", str(web), "--port", str(grpc)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        def up():
            try:
                return urllib.request.urlopen(f"http://127.0.0.1:{web}", timeout=1).status == 200
            except OSError:
                return False

        wait_until(up, 30, every=0.2, what="Rerun's web viewer")
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(f"http://127.0.0.1:{web}/?url=rerun%2Bhttp://127.0.0.1:{grpc}/proxy")
        stats = {}
        for _ in range(60):                         # the viewer loads the recording, then draws: until the line stops growing
            pg.wait_for_timeout(500)
            png = pg.screenshot()
            now = pg.evaluate(LINE_STATS, base64.b64encode(png).decode())
            if now["columns"] and now == stats:
                break
            stats = now
        shot.write_bytes(png)
        pg.close()
        return stats
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


def plot_tooltip(pg, x_frac):
    """Hover Lichtblick's Plot panel at a fraction of its width: (seconds since midnight UTC, value) from its tooltip."""
    cv = pg.locator("canvas").last.bounding_box()
    pg.mouse.move(cv["x"] + x_frac * cv["width"] - 20, cv["y"] + 0.5 * cv["height"])
    pg.mouse.move(cv["x"] + x_frac * cv["width"], cv["y"] + 0.5 * cv["height"], steps=8)    # the chart's hover wants movement over it
    pg.wait_for_function("[...document.querySelectorAll('[role=tooltip],[class*=ooltip]')].some((e) => /\\d\\d:\\d\\d:\\d\\d\\.\\d+/.test(e.innerText))", timeout=10000)
    texts = pg.evaluate("[...document.querySelectorAll('[role=tooltip],[class*=ooltip]')].map((e) => e.innerText)")
    m = next(m for m in (re.search(r"(\d+):(\d\d):(\d\d\.\d+) (AM|PM)", t) for t in texts) if m)
    v = next(float(t.split("\n")[0].replace(",", "")) for t in texts if re.fullmatch(r"-?[\d.,]+", t.split("\n")[0].strip()))
    h = int(m.group(1)) % 12 + (12 if m.group(4) == "PM" else 0)
    return h * 3600 + int(m.group(2)) * 60 + float(m.group(3)), v, texts


with tempfile.TemporaryDirectory(prefix="compat-") as tmp:
    tmp = Path(tmp)
    os.chmod(tmp, 0o755)
    data = tmp / "data"
    run_dir = import_fixture(data)
    mcap = run_dir / "run.mcap"

    # ---- (a) Rerun ---------------------------------------------------------------------------------------------
    if not RERUN.exists():
        raise SystemExit(f"no {RERUN}: run `make duck-sync` (rerun-sdk lives in robots/duck/.venv)")
    rc, out = run([RERUN, "mcap", "check", mcap])
    check("Rerun: `rerun mcap check` passes every channel", rc == 0 and "Issues" in out and not re.search(r"^(warn|error)", out, re.M | re.I), out[-300:])
    rrd = tmp / "run.rrd"
    rc, out = run([RERUN, "mcap", "convert", "-d", "protobuf", "--disable-raw-fallback", mcap, "-o", rrd])
    got = entities(out)
    check("Rerun: `mcap convert -d protobuf --disable-raw-fallback` decodes an entity for each Foxglove topic",
          rc == 0 and set(FOXGLOVE_TOPICS) <= got, sorted(got))
    rc, out = run([RERUN, "rrd", "print", rrd])
    rows = {m.group(2): int(m.group(1)) for m in re.finditer(r"with (\d+) rows .*? - (/\S+) - data columns: \[foxglove", out)}
    check("Rerun: the decoded rows are the run's (116 ticks of poses and depth, 16 maps, 1 transform)",
          rows == {"/belief/pose": 116, "/truth/pose": 116, "/depth": 116, "/map": 16, "/tf": 1}, rows)
    rc, out = run([RERUN, "rrd", "verify", rrd])
    check("Rerun: `rerun rrd verify` passes the converted file", rc == 0, out[-200:])

    # ---- (a2) a run with the semantic map (ADR-0019): our own JSON kinds, no Foxglove mapping, must not trip Rerun ----
    shutil.copytree(FRIDGE_SLICE, data.parent / "logs" / "fridge1")
    fridge_mcap = import_fixture(data, "fridge1") / "run.mcap"
    rc, out = run([RERUN, "mcap", "check", fridge_mcap])
    check("Rerun, a run with objects and sightings: `rerun mcap check` passes every channel", rc == 0 and "Issues" in out and not re.search(r"^(warn|error)", out, re.M | re.I), out[-300:])
    with open(fridge_mcap, "rb") as fh:
        summ = make_reader(fh).get_summary()
        sem_topics = {ch.topic: (summ.schemas[ch.schema_id].name, summ.statistics.channel_message_counts[ch.id]) for ch in summ.channels.values()
                      if ch.topic in ("/miniview/objects", "/miniview/sighting")}
    check("the file carries both kinds on their own JSON topics, counted (10 snapshots, 17 sightings)",
          sem_topics == {"/miniview/objects": ("miniview.objects", 10), "/miniview/sighting": ("miniview.sighting", 17)}, sem_topics)
    fridge_rrd = tmp / "fridge.rrd"
    rc, out = run([RERUN, "mcap", "convert", "-d", "protobuf", "--disable-raw-fallback", fridge_mcap, "-o", fridge_rrd])
    got = entities(out)
    check("Rerun, a run with objects and sightings: `mcap convert` still decodes the Foxglove topics", rc == 0 and {"/belief/pose", "/truth/pose", "/tf"} <= got, sorted(got))
    rc, out = run([RERUN, "rrd", "verify", fridge_rrd])
    check("Rerun, a run with objects and sightings: `rerun rrd verify` passes the converted file", rc == 0, out[-200:])

    # ---- (b) Lichtblick: skipped unless COMPAT_LICHTBLICK=1 (ADR-0007 "Compatibility") ------------------------
    if LICHTBLICK_ON:
        served = tmp / "served"
        served.mkdir()
        shutil.copy(mcap, served / "run.mcap")
        os.chmod(served, 0o755)
        os.chmod(served / "run.mcap", 0o644)
        cid = subprocess.check_output(["docker", "run", "-d", "--rm", "-p", "127.0.0.1::8080", "-v", f"{served}:/src/runs:ro", LICHTBLICK], text=True).strip()
        try:
            port = subprocess.check_output(["docker", "port", cid, "8080/tcp"], text=True).split(":")[-1].strip()
            base = f"http://127.0.0.1:{port}"

            def up():
                try:
                    return urllib.request.urlopen(base, timeout=2).status == 200
                except Exception:
                    return False

            wait_until(up, 60, every=0.3, what="Lichtblick to answer")
            with sync_playwright() as p:
                b = launch(p)
                pg = b.new_page(viewport={"width": 1500, "height": 950})
                pg.goto(f"{base}/?ds=remote-file&ds.url={base}/runs/run.mcap")
                day = datetime.datetime.fromtimestamp(T0_NS / 1e9, datetime.timezone.utc).strftime("%Y-%m-%d")
                lb_wait(pg, "document.body.innerText.includes('Topics')", timeout=60000)
                pg.get_by_text("Topics", exact=True).first.click()
                lb_wait(pg, "document.body.innerText.includes('foxglove.PoseInFrame')", timeout=60000)
                topics = pg.locator("body").inner_text()
                check("Lichtblick: the topic list has the Foxglove topics with their schemas and the run's counts",
                      all(re.search(rf"{t}\s+foxglove\.\w+", topics) for t in FOXGLOVE_TOPICS) and re.search(r"/belief/pose\s+foxglove\.PoseInFrame\s+[\d.]+ Hz\s+116", topics), topics[:200])
                pg.get_by_text("Alerts", exact=False).first.click()
                lb_wait(pg, "document.body.innerText.includes('Transform topics detected')", timeout=30000)
                alerts = pg.locator("body").inner_text()
                alerts = alerts[alerts.index("Layouts") + len("Layouts"):alerts.index("Sync")]
                titles = [a for a in alerts.split("\n") if a.strip() and not a.startswith("Activating") and a.strip() not in ("3D", "Image", "Waiting for image messages…", "No topic selected")]
                check("Lichtblick: no alert but the note on transform topics", titles and all("Transform topics detected" in t or re.fullmatch(r"\d+x", t.strip()) for t in titles), alerts[:300])
                shown = "[...document.querySelectorAll('input')].map((i) => i.value).join(' ') + ' ' + document.body.innerText"
                lb_wait(pg, f"({shown}).includes('{day}') || ({shown}).includes('1970')", timeout=30000)
                text = pg.evaluate(shown)
                check("Lichtblick: the timeline shows the run's real start date, not 1970", day in text and "1970" not in text, day)
                pg.get_by_text("Panel", exact=True).first.click()
                pg.locator("canvas").first.click(position={"x": 100, "y": 100})
                lb_wait(pg, "document.querySelectorAll('[data-testid=VisibilityToggle]').length === 4", timeout=30000)
                panel = pg.locator("[data-testid=settings-tree-editor]").inner_text()
                check("Lichtblick: the 3D panel's topic list has the four topics", all(t in panel for t in ("/belief/pose", "/truth/pose", "/map", "/depth")), panel[:300])
                bar = pg.locator("[class*=scrubberWrapper]").first.bounding_box()      # the timeline; 87% of the way in is where the data is
                pg.mouse.click(bar["x"] + 0.87 * bar["width"], bar["y"] + bar["height"] / 2)

                def stage():
                    prev = pg.locator("canvas").first.screenshot()
                    for _ in range(40):
                        pg.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
                        cur = pg.locator("canvas").first.screenshot()
                        if cur == prev:
                            return cur
                        prev = cur
                    raise TimeoutError("the 3D canvas never settled")

                frames = [stage()]
                for i, name in enumerate(("/belief/pose", "/depth", "/map", "/truth/pose")):
                    pg.locator("[data-testid=VisibilityToggle]").nth(i).click()
                    frames.append(stage())
                changed = [a != b_ for a, b_ in zip(frames, frames[1:])]
                check("Lichtblick: switching on /belief/pose, /depth, /map, /truth/pose each changes what the 3D panel draws", all(changed), changed)
                b.close()
        finally:
            subprocess.run(["docker", "stop", cid], capture_output=True)

    else:
        print("SKIP Lichtblick, explore9: not tested unless COMPAT_LICHTBLICK=1 (ADR-0007 Compatibility: its UI's timing failed CI runs that were not ours)", flush=True)
    # ---- (c) miniview ------------------------------------------------------------------------------------------
    cat = catalog(data)
    cat.put_scene(scene("apartment"))
    httpd, base = serve(cat, follow=False)
    code, r, _ = get(base, "/api/v1/runs/duck/apartment/explore9")
    check("miniview: the same file loads and serves: 116 ticks, ended, trapped, real start", code == 200 and r["ticks"] == 116 and r["status"] == "ended"
          and r["verdict"] == "trapped" and r["started_at_ns"] == T0_NS, {k: r[k] for k in ("ticks", "status", "verdict")})
    code, w, _ = get(base, "/api/v1/runs/duck/apartment/explore9/frames?from=33&to=35")
    check("miniview: a window of it carries poses, depth and the plans and maps it refers to", code == 200 and w["t"] and w["depth"][0] is not None and w["plans"] and w["worlds"])
    httpd.shutdown()

    # ---- (d) an NXT run (ADR-0013): signals on /nxt/signals, and a pose from the odometry ---------------------------------
    nxt_csv = Path(__file__).resolve().parent / "fixtures" / "nxt" / "runs" / "run-20261114-094243.csv"
    nkey = "nxt/unmapped/run-20261114-094243"
    nxt_data = tmp / "nxt-data"
    nxt.import_csv(nxt_csv, nxt_data, tz="Europe/Zurich", sprocket=0.043, track=0.12, started_at_ns=T0_NS, say=lambda *_: None)
    bare_data = tmp / "nxt-bare"
    nxt.import_csv(nxt_csv, bare_data, tz="Europe/Zurich", started_at_ns=T0_NS, say=lambda *_: None)
    n_mcap, bare_mcap = nxt_data / "runs" / nkey / "run.mcap", bare_data / "runs" / nkey / "run.mcap"
    first = [float(x) for x in nxt_csv.read_text().splitlines()[1].split(",")[1:4]]       # power_left, power_right, tacho_A of the first sample
    for label, f, pose in (("with odometry", n_mcap, True), ("without wheel geometry", bare_mcap, False)):
        rc, out = run([RERUN, "mcap", "check", f])
        check(f"Rerun, NXT run {label}: `rerun mcap check` passes every channel", rc == 0 and "Issues" in out and not re.search(r"^(warn|error)", out, re.M | re.I), out[-300:])
        rrd = tmp / f"nxt-{pose}.rrd"
        rc, out = run([RERUN, "mcap", "convert", "-d", "protobuf", "--disable-raw-fallback", f, "-o", rrd])
        got = entities(out)
        check(f"Rerun, NXT run {label}: the protobuf decoder gives an entity for /nxt/signals" + (" and for the pose and the transform" if pose else ""),
              rc == 0 and "/nxt/signals" in got and (({"/belief/pose", "/tf"} <= got) if pose else not ({"/belief/pose"} & got)), sorted(got))
        rc, out = run([RERUN, "rrd", "print", rrd])
        rows = {m.group(2): int(m.group(1)) for m in re.finditer(r"with (\d+) rows .*? - (/\S+) - data columns: \[(?:foxglove|miniview)", out)}
        check(f"Rerun, NXT run {label}: one row per sample on /nxt/signals" + (", one pose per sample" if pose else ""),
              rows.get("/nxt/signals") == 281 and (rows.get("/belief/pose") == 281 and rows.get("/tf") == 1 if pose else "/belief/pose" not in rows), rows)
        rc, out = run([RERUN, "rrd", "print", "-vvv", rrd])
        sch = re.search(r'type: List\(Struct\("power_left": Float64, "power_right": Float64, "tacho_A": Float64, "tacho_B": Float64, "tacho_C": Float64, '
                        r'"s3_color": Float64, "s3_color_name": Utf8, "s4_ultrasonic": Float64(?:, "program": Utf8)?\)\)', out)
        row0 = re.search(r"\[\{power_left: ([-\d.]+), power_right: ([-\d.]+), tacho_A: ([-\d.]+)", out)
        check(f"Rerun, NXT run {label}: each signal is a named Float64 or Utf8 column of the decoded struct (plottable by name), with the first sample's values",
              sch is not None and row0 is not None and [float(x) for x in row0.groups()] == first, (bool(sch), row0.groups() if row0 else None, first))
        rc, out = run([RERUN, "rrd", "verify", rrd])
        check(f"Rerun, NXT run {label}: `rerun rrd verify` passes the converted file", rc == 0, out[-200:])

    # Rerun: a blueprint maps .tacho_B of the decoded struct to a line; a field that does not exist draws none
    rrd = tmp / "nxt-plot.rrd"
    rc, out = run([RERUN, "mcap", "convert", "-d", "protobuf", "--disable-raw-fallback", "--application-id", "nxt_compat", n_mcap, "-o", rrd])
    with sync_playwright() as p:
        b = launch(p)
        line = rerun_plot(b, rrd, "nxt_compat", "/nxt/signals", "miniview.Signals:message", "tacho_B", tmp / "rerun-plot.png")
        none = rerun_plot(b, rrd, "nxt_compat", "/nxt/signals", "miniview.Signals:message", "no_such_signal", tmp / "rerun-none.png")
        b.close()
    rows = [r.split(",") for r in nxt_csv.read_text().splitlines()[1:]]
    rises = float(rows[-1][4]) > float(rows[0][4])           # tacho_B, the 5th column
    check("Rerun, NXT run: a time series view plots /nxt/signals .tacho_B by name across the run, rising as the CSV does (and a field that is not there draws nothing)",
          rc == 0 and line["columns"] > 300 and line["span"] > 0.8 and rises and line["left_y"] > line["right_y"] + 100 and none["columns"] == 0,
          (line, none, rises))

    # Lichtblick: skipped unless COMPAT_LICHTBLICK=1
    if LICHTBLICK_ON:
        served = tmp / "served-nxt"
        served.mkdir()
        shutil.copy(n_mcap, served / "run.mcap")
        os.chmod(served, 0o755)
        os.chmod(served / "run.mcap", 0o644)
        cid = subprocess.check_output(["docker", "run", "-d", "--rm", "-p", "127.0.0.1::8080", "-v", f"{served}:/src/runs:ro", LICHTBLICK], text=True).strip()
        try:
            port = subprocess.check_output(["docker", "port", cid, "8080/tcp"], text=True).split(":")[-1].strip()
            base = f"http://127.0.0.1:{port}"

            def lb_up():
                try:
                    return urllib.request.urlopen(base, timeout=2).status == 200
                except Exception:
                    return False

            wait_until(lb_up, 60, every=0.3, what="Lichtblick to answer")
            nhttpd, nbase = serve(catalog(nxt_data), follow=False)
            with sync_playwright() as p:
                b = launch(p)
                pg = b.new_page(viewport={"width": 1500, "height": 950}, timezone_id="UTC")   # the Plot tooltip says clock time
                pg.goto(f"{base}/?ds=remote-file&ds.url={base}/runs/run.mcap")
                lb_wait(pg, "document.body.innerText.includes('Topics')", timeout=60000)
                pg.get_by_text("Topics", exact=True).first.click()
                lb_wait(pg, "document.body.innerText.includes('miniview.Signals')", timeout=60000)
                topics = pg.locator("body").inner_text()
                check("Lichtblick, NXT run: the topic list has /nxt/signals with its schema and the run's 281 samples, beside the pose",
                      re.search(r"/nxt/signals\s+miniview\.Signals\s+[\d.]+ Hz\s+281", topics) is not None and re.search(r"/belief/pose\s+foxglove\.PoseInFrame\s+[\d.]+ Hz\s+281", topics) is not None, topics[:200])
                pg.get_by_text("Alerts", exact=False).first.click()
                lb_wait(pg, "document.body.innerText.includes('Transform topics detected')", timeout=30000)
                alerts = pg.locator("body").inner_text()
                alerts = alerts[alerts.index("Layouts") + len("Layouts"):alerts.index("Sync")]
                titles = [a for a in alerts.split("\n") if a.strip() and not a.startswith("Activating") and a.strip() not in ("3D", "Image", "Waiting for image messages…", "No topic selected")]
                check("Lichtblick, NXT run: no alert but the note on transform topics", titles and all("Transform topics detected" in t or re.fullmatch(r"\d+x", t.strip()) for t in titles), alerts[:300])
                # Lichtblick's Raw Messages panel (the third panel of the default layout): the message at the playhead, decoded by name from the descriptor in the file
                pg.get_by_placeholder("/some/topic.msgs[0].field").first.click()
                pg.keyboard.type("/nxt/signals")
                pg.keyboard.press("Enter")
                lb_wait(pg, "document.body.innerText.includes('miniview.Signals @')", timeout=30000)
                bar = pg.locator("[class*=scrubberWrapper]").first.bounding_box()
                pg.mouse.click(bar["x"] + 0.5 * bar["width"], bar["y"] + bar["height"] / 2)
                lb_wait(pg, "(() => { const m = /miniview\\.Signals @ (\\d+\\.\\d+)/.exec(document.body.innerText); return m && +m[1] > 1700000010; })()", timeout=30000)
                text = pg.locator("body").inner_text()
                msg = text[text.index("miniview.Signals @"):]
                at = float(re.match(r"miniview\.Signals @ (\d+\.\d+)", msg).group(1)) - T0_NS / 1e9
                shown = {m.group(1): m.group(2) for m in re.finditer(r"\n(power_left|power_right|tacho_A|tacho_B|tacho_C|s3_color|s3_color_name|s4_ultrasonic)\n(\S+)", msg)}
                code, st, _ = get(nbase, f"/api/v1/runs/{nkey}/state?t={at + 1e-4}")
                want = st["signals"]["values"]
                check("Lichtblick, NXT run: the Raw Messages panel decodes the /nxt/signals message at the playhead by name, with the values miniview reads for that sample",
                      code == 200 and abs(st["signals"]["t"] - at) < 1e-3 and set(shown) == {k for k, v in want.items() if v is not None}
                      and all(shown[k] == (f'"{v}"' if isinstance(v, str) else f"{v:g}") for k, v in want.items() if v is not None), (shown, want))
                # A signal on a chart: Raw Messages' "Plot this value on a line chart" on tacho_B opens a Plot panel with that path;
                # its tooltip at two places gives the time and value under the cursor, which must be a sample miniview serves.
                label = pg.get_by_text("tacho_B", exact=True).first.bounding_box()
                pg.mouse.move(label["x"] + label["width"] + 30, label["y"] + label["height"] / 2)
                pg.locator("[aria-label='Plot this value on a line chart']").first.click()
                lb_wait(pg, "document.body.innerText.includes('/nxt/signals.tacho_B')", timeout=15000)
                day0 = (T0_NS / 1e9) % 86400
                for frac in (0.3, 0.7):
                    sec, val, texts = plot_tooltip(pg, frac)
                    t = sec - day0
                    code, w, _ = get(nbase, f"/api/v1/runs/{nkey}/signals?from={t - 0.3}&to={t + 0.3}")
                    near = [v for v in w["v"]["tacho_B"] if v is not None] if code == 200 else []
                    check(f"Lichtblick, NXT run: a Plot panel draws /nxt/signals.tacho_B; at {frac:.0%} of it the value is a sample miniview serves at that time",
                          0 < t < 60 and val in near, (round(t, 3), val, near, texts))
                pg.screenshot(path=str(tmp / "lichtblick-plot.png"))
                b.close()
            nhttpd.shutdown()
        finally:
            subprocess.run(["docker", "stop", cid], capture_output=True)

    else:
        print("SKIP Lichtblick, NXT run: not tested unless COMPAT_LICHTBLICK=1 (ADR-0007 Compatibility: its UI's timing failed CI runs that were not ours)", flush=True)

    # ---- (e) miniview serves the NXT run from the same file ----------------------------------------------------------------
    cat = catalog(nxt_data)
    httpd, base = serve(cat, follow=False)
    code, r, _ = get(base, f"/api/v1/runs/{nkey}")
    check("miniview, NXT run: the same file loads and serves: 281 ticks of pose and 281 samples, ended, recorded, real start",
          code == 200 and r["ticks"] == 281 and r["samples"] == 281 and r["status"] == "ended" and r["verdict"] == "recorded" and r["started_at_ns"] == T0_NS, {k: r.get(k) for k in ("ticks", "samples", "status")})
    code, w, _ = get(base, f"/api/v1/runs/{nkey}/signals?from=10&to=11")
    check("miniview, NXT run: a window of its signals", code == 200 and w["t"] and w["v"]["tacho_B"][0] is not None)
    httpd.shutdown()

check.done()
