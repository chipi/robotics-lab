"""Shared by the tests: checks, waiting for a condition (never a fixed sleep), the explore9 fixture, a service."""

import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from runfile import keys, mcapio
from observatory.importer import import_duck

_INDEX_DIR = Path(tempfile.mkdtemp(prefix="miniview-test-index-"))
atexit.register(shutil.rmtree, _INDEX_DIR, True)
atexit.register(shutil.rmtree, _INDEX_DIR, ignore_errors=True)
os.environ["MINIVIEW_INDEX"] = str(_INDEX_DIR / "default.sqlite")     # a test that forgets its own index never touches the real one
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "explore9"
T0_NS = 1_700_000_000 * 10**9


class Checks:
    def __init__(self, label: str):
        self.label, self.failures = label, []

    def __call__(self, name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
        if not cond:
            self.failures.append(name)

    def done(self):
        print(self.label, "FAIL " + ", ".join(self.failures) if self.failures else "PASS")
        sys.exit(1 if self.failures else 0)


def wait_until(cond, timeout: float = 10.0, every: float = 0.01, what: str = "condition"):
    """The value of cond() once it is truthy; a TimeoutError naming `what` otherwise."""
    end = time.monotonic() + timeout
    while True:
        v = cond()
        if v:
            return v
        if time.monotonic() > end:
            raise TimeoutError(f"timed out after {timeout} s waiting for {what}")
        time.sleep(every)


def import_fixture(data: Path, name: str = "explore9", robot: str = "duck", scene: str = "apartment") -> Path:
    """The fixture log (copied under `name` when that differs) imported into `data`; the run's folder."""
    src = data.parent / "logs" / name
    if not src.exists():
        shutil.copytree(FIXTURE, src)
    import_duck(src, scene, data, say=lambda *_: None, started_at_ns=T0_NS, robot=robot)
    return keys.run_dir(data, keys.make_key(robot, scene, name))


def catalog(data: Path, index: Path | None = None, **kw):
    """A catalog over `data` with an index of its own (outside the data, as in production); pass `index` to reuse one."""
    from runfile.catalog import Catalog

    n = len(list(_INDEX_DIR.glob("*.sqlite")))
    return Catalog(data, index=index or _INDEX_DIR / f"index-{n}.sqlite", **kw)


def tick(t, x, **kw):
    p = {"belief": [x, 0.0, 0.0], "truth": [x + 1.0, 0.0, 0.0], "tilt": None, "cmd": [0.3, 0.0],
         "depth": [[x + 0.4, 0.0, 0.0, "o"]], "t_src": t, "raw": {}}
    p.update(kw)
    return (t, "tick", p)


def run_record(key="duck/room/r1", started_at_ns=T0_NS, **kw):
    robot, scene, _ = keys.split_key(key)
    return mcapio.new_run(key, {"name": robot, "radius": 0.08, "height": 0.27}, scene, "exploration", started_at_ns,
                          "writer", **kw)


def make_run(data: Path, key: str, records, close: bool = True, **kw):
    """Write a run under data/runs/<key>; the recorder (open) or the final file's path (closed)."""
    rec = mcapio.Recorder(keys.run_dir(data, key), run_record(key, **kw))
    for r in records:
        rec.add(*r)
    return rec.close() if close else rec


# The left panel's sections are closed until a viewer opens them (UXS-001, 2026-11-16); a page test about the outliner's
# rows opens them all first, as a viewer would (test_explore_pages checks the closed default itself).
OPEN_SECTIONS = "window.miniview.state().sections.forEach((s) => window.miniview.setSection(s.id, true))"


# The lanes' data is one canvas (look-and-feel round 3). A page test counts the pixels drawn in each lane's band: [[stream id, pixels], ...]. It reads a copy made with
# willReadFrequently, so the page's own canvas context does not log the "multiple readback" warning that the console checks would take for an error.
LANE_PIXELS = """(() => { const cv = document.querySelector('#dlanes canvas.lanes-cv'), cr = cv.getBoundingClientRect(), k = cv.width / cr.width, c2 = document.createElement('canvas');
  c2.width = cv.width; c2.height = cv.height; const g = c2.getContext('2d', { willReadFrequently: true }); g.drawImage(cv, 0, 0);
  return [...document.querySelectorAll('#dlanes .dl[data-lane]:not(.missing)')].map((d) => { const r = d.getBoundingClientRect(), a = g.getImageData(0, Math.round((r.top - cr.top) * k), cv.width, Math.round(r.height * k)).data;
    let n = 0; for (let i = 3; i < a.length; i += 4) if (a[i] > 40) n++; return [d.dataset.lane, n]; }); })()"""


def boot(page, url, ready="window.miniview !== undefined && window.__ready === true", timeout=None, reload=False, _match="ERR_NETWORK_CHANGED"):
    """goto `url` (reload=True: and reload, for a hash-only change) and wait for `ready`; one reload when the wait times out after a request failed with `_match`."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    hits = []
    # Docker veth churn on this host makes Chromium abort in-flight module loads with ERR_NETWORK_CHANGED, which leaves the page dead
    on_fail = lambda r: hits.append(r.url) if _match in (r.failure or "") else None  # noqa: E731
    page.on("requestfailed", on_fail)
    try:
        page.goto(url)
        if reload:
            page.reload()
        try:
            page.wait_for_function(ready, timeout=timeout)
        except PlaywrightTimeout:
            if not hits:
                raise
            print(f"boot: retry after net::{_match} on {hits[0]}", file=sys.stderr)
            page.reload()
            page.wait_for_function(ready, timeout=timeout)
    finally:
        page.remove_listener("requestfailed", on_fail)


def open_lanes(page, missing=False, shut=False):
    """Open (or, with shut, fold) every section of the timeline's lanes, which are folded until a viewer opens them (look-and-feel round 3); with `missing`
    the line of streams a run lacks is opened too. One click at a time: a click rebuilds the lanes."""
    sels = ['#lanesL .lane-s[aria-expanded="%s"]' % ("true" if shut else "false")]
    if missing and not shut:
        sels.append('#lanesL .lane-m[aria-expanded="false"]')
    for sel in sels:
        while page.evaluate(f"!!document.querySelector('{sel}')"):
            page.evaluate(f"document.querySelector('{sel}').click()")


def scene(room="room"):
    return {"id": room, "name": "A room", "kind": "test", "bounds": [-1, 1, -1, 1], "boxes": [], "hazards": []}


def serve(cat, follow=True):
    from observatory.server import make_server

    httpd = make_server(cat, "127.0.0.1", 0, follow=follow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


STUB_ENGINE = '''
import json, os, sys, time
job = json.load(open(sys.argv[1]))
if os.environ.get("STUB_FAIL"):
    sys.stderr.write("stub engine: told to fail\\n")
    sys.exit(1)
gate, end = os.environ.get("STUB_GATE"), time.monotonic() + 30
while gate and not os.path.exists(gate) and time.monotonic() < end:
    time.sleep(0.02)
fr = job["track"]["frames"]
info = {"run": job["title"], "robot": job["robot"]["name"], "size": job["size"], "frames": len(fr), "t0": fr[0]["t"], "t1": fr[-1]["t"]}
open(job["out"], "wb").write(b"\\0\\0\\0\\x18ftypmp42STUB" + json.dumps(info).encode())
'''


def stub_engine(tmp: Path, kind: str = "ok") -> Path:
    """Point the video export's "mujoco" at a stand-in script (no MuJoCo, no rendering) that writes a tiny file whose body says what
    job it was given. kind: "ok"; "gated" (waits until the returned file exists: a job that is running as long as the test wants);
    "fail" (exits 1). The script and the python are chosen by VIDEO_MUJOCO_SCRIPT and VIDEO_MUJOCO_PYTHON, read at each job."""
    script = Path(tmp) / "stub_engine.py"
    script.write_text(STUB_ENGINE)
    gate = Path(tmp) / "gate"
    gate.unlink(missing_ok=True)
    os.environ["VIDEO_MUJOCO_SCRIPT"], os.environ["VIDEO_MUJOCO_PYTHON"] = str(script), sys.executable
    # the machine's own Blender (~/opt/blender, when installed) must not decide what a test sees: no Blender unless a test says
    os.environ["VIDEO_BLENDER"] = str(Path(tmp) / "no-blender")
    for k in ("STUB_GATE", "STUB_FAIL"):
        os.environ.pop(k, None)
    if kind == "gated":
        os.environ["STUB_GATE"] = str(gate)
    elif kind == "fail":
        os.environ["STUB_FAIL"] = "1"
    return gate


def get(base: str, path: str, headers=None, timeout: float = 10, body=None):
    """(status, parsed JSON body or text, response headers); HTTP errors come back as values, not raised. `body` (a JSON value)
    makes it a POST."""
    req = urllib.request.Request(base + path, headers=headers or {}, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, code, hdrs = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        body, code, hdrs = e.read(), e.code, e.headers
    try:
        return code, json.loads(body), hdrs
    except ValueError:
        return code, body.decode(errors="replace"), hdrs
