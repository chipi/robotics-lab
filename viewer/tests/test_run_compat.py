"""A run opens fully in all three viewers, kept compatible on purpose (ADR-0007 "Compatibility"):
Rerun (rerun mcap check, mcap convert), Lichtblick (the image `make viewers` runs, headless: no errors but the
transforms note, the run's real start date, the topics, and the topics draw when switched on), and miniview (the service
loads and serves the same file). The fixture is explore9 imported into a temp folder.
Needs duck/.venv (rerun-sdk: `make duck-sync`), Docker and Chromium. Run: make test-run-compat
or: cd viewer && uv run python tests/test_run_compat.py"""

import datetime
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from helpers import T0_NS, Checks, catalog, get, import_fixture, scene, serve, wait_until
from miniview.shots import launch

check = Checks("RUN COMPAT")
REPO = Path(__file__).resolve().parents[2]
RERUN = REPO / "duck" / ".venv" / "bin" / "rerun"
LICHTBLICK = os.environ.get("LICHTBLICK_IMAGE", "ghcr.io/lichtblick-suite/lichtblick:latest")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
FOXGLOVE_TOPICS = ["/belief/pose", "/truth/pose", "/tf", "/map", "/depth"]


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    return r.returncode, ANSI.sub("", r.stdout + r.stderr)


def entities(text):
    m = re.search(r"Entities: \{(.*?)\}", text, re.S)
    return {e.strip().rstrip(",") for e in m.group(1).split("\n") if e.strip()} if m else set()


with tempfile.TemporaryDirectory(prefix="compat-") as tmp:
    tmp = Path(tmp)
    os.chmod(tmp, 0o755)
    data = tmp / "data"
    run_dir = import_fixture(data)
    mcap = run_dir / "run.mcap"

    # ---- (a) Rerun ---------------------------------------------------------------------------------------------
    if not RERUN.exists():
        raise SystemExit(f"no {RERUN}: run `make duck-sync` (rerun-sdk lives in duck/.venv)")
    rc, out = run([RERUN, "mcap", "check", mcap])
    check("Rerun: `rerun mcap check` passes every channel", rc == 0 and "Issues" in out and not re.search(r"^(warn|error)", out, re.M | re.I), out[-300:])
    rrd = tmp / "run.rrd"
    rc, out = run([RERUN, "mcap", "convert", "-d", "protobuf", "--disable-raw-fallback", mcap, "-o", rrd])
    got = entities(out)
    check("Rerun: `mcap convert -d protobuf --disable-raw-fallback` decodes an entity for each Foxglove topic",
          rc == 0 and set(FOXGLOVE_TOPICS) <= got, sorted(got))
    rc, out = run([RERUN, "mcap", "convert", "-d", "foxglove", "--disable-raw-fallback", mcap, "-o", tmp / "f.rrd"])
    check("(recorded, not required) `-d foxglove` alone decodes no entity in this Rerun, for these channels or any protobuf ones",
          rc == 0 and not (set(FOXGLOVE_TOPICS) & entities(out)), sorted(entities(out)))
    rc, out = run([RERUN, "rrd", "print", rrd])
    rows = {m.group(2): int(m.group(1)) for m in re.finditer(r"with (\d+) rows .*? - (/\S+) - data columns: \[foxglove", out)}
    check("Rerun: the decoded rows are the run's (116 ticks of poses and depth, 16 maps, 1 transform)",
          rows == {"/belief/pose": 116, "/truth/pose": 116, "/depth": 116, "/map": 16, "/tf": 1}, rows)
    rc, out = run([RERUN, "rrd", "verify", rrd])
    check("Rerun: `rerun rrd verify` passes the converted file", rc == 0, out[-200:])

    # ---- (b) Lichtblick ----------------------------------------------------------------------------------------
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
            pg.wait_for_function("document.body.innerText.includes('Topics')", timeout=60000)
            pg.get_by_text("Topics", exact=True).first.click()
            pg.wait_for_function("document.body.innerText.includes('foxglove.PoseInFrame')", timeout=60000)
            topics = pg.locator("body").inner_text()
            check("Lichtblick: the topic list has the Foxglove topics with their schemas and the run's counts",
                  all(re.search(rf"{t}\s+foxglove\.\w+", topics) for t in FOXGLOVE_TOPICS) and re.search(r"/belief/pose\s+foxglove\.PoseInFrame\s+[\d.]+ Hz\s+116", topics), topics[:200])
            pg.get_by_text("Alerts", exact=False).first.click()
            pg.wait_for_function("document.body.innerText.includes('Transform topics detected')", timeout=30000)
            alerts = pg.locator("body").inner_text()
            alerts = alerts[alerts.index("Layouts") + len("Layouts"):alerts.index("Sync")]
            titles = [a for a in alerts.split("\n") if a.strip() and not a.startswith("Activating") and a.strip() not in ("3D", "Image", "Waiting for image messages…", "No topic selected")]
            check("Lichtblick: no alert but the note on transform topics", titles and all("Transform topics detected" in t or re.fullmatch(r"\d+x", t.strip()) for t in titles), alerts[:300])
            shown = "[...document.querySelectorAll('input')].map((i) => i.value).join(' ') + ' ' + document.body.innerText"
            pg.wait_for_function(f"({shown}).includes('{day}') || ({shown}).includes('1970')", timeout=30000)
            text = pg.evaluate(shown)
            check("Lichtblick: the timeline shows the run's real start date, not 1970", day in text and "1970" not in text, day)
            pg.get_by_text("Panel", exact=True).first.click()
            pg.locator("canvas").first.click(position={"x": 100, "y": 100})
            pg.wait_for_function("document.querySelectorAll('[data-testid=VisibilityToggle]').length === 4", timeout=30000)
            panel = pg.locator("[data-testid=settings-tree-editor]").inner_text()
            check("Lichtblick: the 3D panel's topic list has the four topics", all(t in panel for t in ("/belief/pose", "/truth/pose", "/map", "/depth")), panel[:300])
            pg.mouse.click(1300, 891)                                   # into the run, where the data is (it starts 31 s in)

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

check.done()
