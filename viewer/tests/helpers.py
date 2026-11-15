"""Shared by the tests: checks, waiting for a condition (never a fixed sleep), the explore9 fixture, a service."""

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from miniview import keys, mcapio
from miniview.importer import import_duck

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


def scene(room="room"):
    return {"id": room, "name": "A room", "kind": "test", "bounds": [-1, 1, -1, 1], "boxes": [], "hazards": []}


def serve(cat, follow=True):
    from miniview.server import make_server

    httpd = make_server(cat, "127.0.0.1", 0, follow=follow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def get(base: str, path: str, headers=None, timeout: float = 10):
    """(status, parsed JSON body or text, response headers); HTTP errors come back as values, not raised."""
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, code, hdrs = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        body, code, hdrs = e.read(), e.code, e.headers
    try:
        return code, json.loads(body), hdrs
    except ValueError:
        return code, body.decode(errors="replace"), hdrs
