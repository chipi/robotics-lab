"""The service (ADR-0005): the API over a data folder, and a live run followed while it is written.
Run: cd viewer && uv run python tests/test_server.py"""

import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from helpers import make_run
from miniview.catalog import Catalog
from miniview.server import make_server

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


from helpers import tick

HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]

with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    cat = Catalog(data)
    cat.put_scene({"id": "room", "name": "A room", "kind": "test", "bounds": [-1, 1, -1, 1], "boxes": [], "hazards": []})
    make_run(data, "duck/room/done1",
             HEAD + [tick(1.0, 0.0), tick(1.1, 0.03), (1.2, "plan", {"path": [[0, 0], [1, 0]]}), tick(1.2, 0.06),
                  (2.5, "event", {"kind": "trapped", "text": "trapped"}), (2.5, "end", {"verdict": "trapped"})])
    httpd = make_server(cat, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return json.loads(r.read())

    check("health", get("/api/v1/health")["ok"])
    sc = get("/api/v1/scenes")["scenes"]
    check("scenes with their runs", sc[0]["id"] == "room" and sc[0]["runs"][0]["id"] == "done1"
          and sc[0]["runs"][0]["status"] == "ended", sc)
    r = get("/api/v1/runs/done1")
    check("the run: status, verdict, span over every record", r["status"] == "ended" and r["verdict"] == "trapped"
          and r["t0"] == 1.0 and r["t1"] == 2.5, {k: r[k] for k in ("status", "verdict", "t0", "t1")})
    w = get("/api/v1/runs/done1/frames?from=1.05&to=1.15")
    check("frames for a time window", w["t"] == [1.1] and w["i0"] == 1 and len(w["plans"]) == 1, w["t"])
    s = get("/api/v1/runs/done1/state?t=2.6")
    check("state after the last tick: the last pose, the last event", s["tick"] == 2 and s["last_event"]["kind"] == "trapped", s)
    check("events filtered by kind", [e["kind"] for e in get("/api/v1/runs/done1/events?kinds=trapped")] == ["trapped"])
    pr = get("/api/v1/runs/done1/presence")["streams"]
    check("presence: spans and times", pr["belief.pose"]["spans"] == [[1.0, 1.2]] and pr["plan.path"]["times"] == [1.2], pr["belief.pose"])
    page = urllib.request.urlopen(base + "/web/three/", timeout=10)
    check("the pages are served", page.status == 200 and b"<html" in page.read().lower())
    rows = cat.db.execute("select count(*) from ticks where run = 'duck/room/done1'").fetchone()[0]
    check("the database has a row per tick", rows == 3, rows)

    # A live run: written while the service runs; a page's live stream sees each record.
    rec = make_run(data, "duck/room/live1", [tick(1.0, 0.0)], close=False)
    t_end = time.monotonic() + 10
    while time.monotonic() < t_end and not any(r["id"] == "live1" for r in get("/api/v1/runs")):
        time.sleep(0.2)
    lr = get("/api/v1/runs/live1")
    check("a run being written is listed as live", lr["status"] == "live" and lr["ticks"] == 1, lr.get("status"))
    got, seen = [], threading.Event()

    def listen():
        with urllib.request.urlopen(f"{base}/api/v1/runs/live1/live?since={lr['seq']}", timeout=20) as resp:
            ev = None
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: ") and ev:
                    got.append((ev, json.loads(line[6:])))
                    if ev == "status" and got[-1][1].get("done"):
                        seen.set()
                        return

    th = threading.Thread(target=listen, daemon=True)
    th.start()
    time.sleep(0.5)
    t_write = time.monotonic()
    rec.add(*tick(1.1, 0.03))
    while time.monotonic() - t_write < 5 and not any(k == "tick" for k, _ in got):
        time.sleep(0.02)
    latency = time.monotonic() - t_write
    check("a new tick reaches the live stream within a second", any(k == "tick" and d["t"] == 1.1 for k, d in got)
          and latency < 1.0, f"{latency:.2f} s")
    rec.add(2.0, "event", {"kind": "trapped", "text": "trapped"})
    rec.add(2.0, "end", {"verdict": "trapped"})
    rec.close()
    seen.wait(10)
    kinds = [k for k, _ in got]
    check("the event and the end arrive, then the stream closes as ended",
          "event" in kinds and "end" in kinds and seen.is_set() and got[-1][1]["status"] == "ended", kinds)
    check("after the end the run reads as ended", get("/api/v1/runs/live1")["status"] == "ended")
    httpd.shutdown()

print("SERVER", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
