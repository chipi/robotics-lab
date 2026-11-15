"""`miniview serve`: the two pages and the API over the catalog (ADR-0005), standard library only.

    GET /api/v1/health
    GET /api/v1/scenes                      the scenes with their runs (index.json's shape)
    GET /api/v1/scenes/{id}                 a scene
    GET /api/v1/runs?scene=                 a scene's runs
    GET /api/v1/runs/{id}                   the run (run.json's shape, with status and seq)
    GET /api/v1/runs/{id}/frames?from=&to=  drawing data (frames.json's shape) for a time window
    GET /api/v1/runs/{id}/state?t=          the moment: belief, truth, distance, depth, last event
    GET /api/v1/runs/{id}/events?kinds=     what happened, when
    GET /api/v1/runs/{id}/presence          when each stream has data (the timeline's rows)
    GET /api/v1/runs/{id}/live?since=       Server-Sent Events: tick, plan, world, event, epoch,
                                            end, then status; resumes after `since` (a seq)
    GET /web/...                            the pages (three.js, deck.gl, the mockup)
"""

import bisect
import http.server
import json
import mimetypes
import threading
import time
import urllib.parse
from pathlib import Path

from miniview import query
from miniview.catalog import Catalog

WEB = Path(__file__).resolve().parents[2] / "web"
HEARTBEAT_S = 15.0


def window(frames: dict, t_from: float | None, t_to: float | None) -> dict:
    """The ticks in [t_from, t_to], with every plan and world (the per-tick indices refer to them)."""
    ts = frames["t"]
    lo = 0 if t_from is None else bisect.bisect_left(ts, t_from)
    hi = len(ts) if t_to is None else bisect.bisect_right(ts, t_to)
    out = {k: (v[lo:hi] if k not in ("plans", "worlds") else v) for k, v in frames.items()}
    out["i0"] = lo
    return out


def presence(run: dict, frames: dict) -> dict:
    """Per stream: the spans where it has data (gaps longer than 3 ticks split them) or the times of
    its records, for the timeline's data rows."""
    ts = frames["t"]
    dts = sorted(b - a for a, b in zip(ts, ts[1:]))
    gap = 3 * (dts[len(dts) // 2] if dts else 0.1)

    def spans(times):
        out = []
        for t in times:
            if out and t - out[-1][1] <= gap:
                out[-1][1] = t
            else:
                out.append([t, t])
        return out

    def depth_kind(k):
        return [t for t, d in zip(ts, frames["depth"]) if d and any(p[3] == k for p in d)]

    return {"t0": run["t0"], "t1": run["t1"], "streams": {
        "belief.pose": {"spans": spans(ts)},
        "truth.pose": {"spans": spans([t for t, x in zip(ts, frames["truth"]) if x])},
        "sensors.depth.floor": {"spans": spans(depth_kind("f"))},
        "sensors.depth.obstacle": {"spans": spans(depth_kind("o"))},
        "sensors.depth.overhead": {"spans": spans(depth_kind("v"))},
        "sensors.depth.below": {"times": depth_kind("b")},
        "sensors.tilt": {"spans": spans([t for t, x in zip(ts, frames["tilt"]) if x])},
        "world.grid": {"times": [w["t"] for w in frames["worlds"]]},
        "plan.path": {"times": [p["t"] for p in frames["plans"]]},
        "events": {"times": [e["t"] for e in run["events"]]},
    }}


class Handler(http.server.BaseHTTPRequestHandler):
    catalog: Catalog = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---- plumbing --------------------------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra=None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, separators=(",", ":")).encode(), "application/json")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts:
                self._send(302, b"", "text/plain", {"Location": "/web/three/"})
            elif parts[0] == "web":
                self._static(parts[1:])
            elif parts[:2] == ["api", "v1"]:
                self._api(parts[2:], q)
            else:
                self._error(404, "not found")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _static(self, rest: list) -> None:
        p = (WEB / "/".join(rest)).resolve()
        if p.is_dir():
            if not self.path.split("?")[0].endswith("/"):
                return self._send(301, b"", "text/plain", {"Location": self.path.split("?")[0] + "/"})
            p = p / "index.html"
        if WEB not in p.parents or not p.is_file():
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            ctype = "text/javascript"
        self._send(200, p.read_bytes(), ctype)

    # ---- the API ---------------------------------------------------------------------------------
    def _api(self, parts: list, q: dict) -> None:
        cat = self.catalog
        if parts == ["health"]:
            return self._json({"ok": True, "runs": len(cat.paths), "data": str(cat.data)})
        if parts == ["scenes"]:
            return self._json(cat.scenes_with_runs())
        if len(parts) == 2 and parts[0] == "scenes":
            sc = cat.scene(parts[1])
            return self._json(sc) if sc else self._error(404, f"no scene {parts[1]!r}")
        if parts == ["runs"]:
            scenes = cat.scenes_with_runs()["scenes"]
            return self._json([r for s in scenes if not q.get("scene") or s["id"] == q["scene"] for r in s["runs"]])
        if len(parts) >= 2 and parts[0] == "runs":
            ld = cat.get(parts[1])
            if ld is None:
                return self._error(404, f"no run {parts[1]!r}")
            what = parts[2] if len(parts) > 2 else ""
            if what == "live":
                return self._live(ld, int(q.get("since", 0) or 0))
            with ld.data.changed:                       # a consistent snapshot while the follower appends
                code, obj = self._run_answer(ld, what, q)
                body = json.dumps(obj, separators=(",", ":")).encode()
            return self._send(code, body, "application/json")
        self._error(404, "not found")

    def _run_answer(self, ld, what: str, q: dict) -> tuple:
        run, frames, cat = ld.data.run, ld.data.frames, self.catalog
        if what == "":
            return 200, dict(run, status=cat.status(ld), seq=ld.data.seq)
        if what == "frames":
            return 200, window(frames, _num(q, "from"), _num(q, "to"))
        if what == "events":
            return 200, query.events(run, set(q["kinds"].split(",")) if q.get("kinds") else None)
        if what in ("state", "presence") and not frames["t"]:
            return 409, {"error": "the run has no ticks yet"}
        if what == "state":
            t = _num(q, "t")
            return 200, query.state(run, frames, run["t1"] if t is None else t)
        if what == "presence":
            return 200, presence(run, frames)
        return 404, {"error": "not found"}

    def _live(self, ld, since: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        data, seq, beat = ld.data, since, time.monotonic()
        while True:
            items = data.since(seq)
            for s, t, kind, p in items:
                self.wfile.write(f"id: {s}\nevent: {kind}\ndata: {json.dumps(dict(p, t=t), separators=(',', ':'))}\n\n"
                                 .encode())
                seq = s
            status = self.catalog.status(ld)
            if items:
                self.wfile.write(f"event: status\ndata: {json.dumps({'status': status, 'seq': seq, 't1': data.run['t1']})}\n\n"
                                 .encode())
                self.wfile.flush()
                beat = time.monotonic()
            if status != "live" and not data.since(seq):
                self.wfile.write(f"event: status\ndata: {json.dumps({'status': status, 'seq': seq, 'done': True})}\n\n"
                                 .encode())
                self.wfile.flush()
                return
            if time.monotonic() - beat > HEARTBEAT_S:
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                beat = time.monotonic()
            with data.changed:
                data.changed.wait(timeout=1.0)


def _num(q: dict, k: str):
    try:
        return float(q[k]) if q.get(k) not in (None, "") else None
    except ValueError:
        return None


def make_server(catalog: Catalog, host: str = "127.0.0.1", port: int = 8070, follow: bool = True):
    catalog.scan()
    handler = type("BoundHandler", (Handler,), {"catalog": catalog})
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    if follow:
        threading.Thread(target=catalog.follow_forever, daemon=True).start()
    return httpd
