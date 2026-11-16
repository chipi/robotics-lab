"""`miniview serve`: the two pages and the API over the catalog (ADR-0005, ADR-0010), standard library only.

    GET /api/v1/health
    GET /api/v1/scenes                                the scenes with their runs (index.json's shape)
    GET /api/v1/scenes/{id}                           a scene
    GET /api/v1/runs?robot=&scene=&status=            the runs, newest first (from the index)
    GET /api/v1/runs/{robot}/{scene}/{run}            the run (run.json's shape, with status and seq)
        .../frames?from=&to=                          drawing data for a time window, with only the plans and maps its
                                                      ticks refer to, keyed by index
        .../signals?from=&to=                         a robot's named values over a time window, columnar (ADR-0013)
        .../sensor?t=                                 the raw depth frame at or before t, with the state it was paired with (ADR-0014)
        .../state?t=                                  the moment: belief, truth, distance, depth, signals, last event
        .../events?kinds=                             what happened, when
        .../presence                                  when each stream has data (the timeline's rows)
        .../live?since=                               Server-Sent Events, one per record, named by its kind, id = seq;
                                                      then `status`; resumes after `since` or Last-Event-ID
    GET /api/v1/robots                                the robots with a description, and what each has (RFC-0011 §3.4)
    GET /api/v1/robots/{robot}                        its description: links, visuals (mesh URLs), joints from the root out
        .../meshes/{file}.stl                         a mesh of the description
    GET /web/...                                      the pages (three.js, deck.gl), the shell, the fonts
    GET /api/v1/render                                the render service's engines (MINIVIEW_RENDER), or {"available": false, "why"}
    POST /api/v1/runs/{robot}/{scene}/{run}/video     a video of the run: {"engine", "from"?, "to"?, "size"?} -> 202 {"id"}
    GET /api/v1/videos/{id}  and  .../file            the job's progress; the finished video (the render service's, passed through)

Errors are JSON ({"error": ...}): 400 bad input, 404, 405, 409 (no ticks yet, a broken run), 500 with an id that is
also in the log. gzip for JSON over 1 KB when accepted; static files carry an ETag.
"""

import bisect
import gzip
import http.server
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from miniview import keys, query, robots
from miniview.catalog import Catalog

log = logging.getLogger("miniview")
WEB = Path(__file__).resolve().parents[2] / "web"
HEARTBEAT_S = 15.0
REQUEST_TIMEOUT_S = 30.0
STREAM_TIMEOUT_S = 60.0     # a live stream whose client stops reading is dropped after this long (a write that blocks)
GZIP_OVER = 1024
PER_TICK = ("t", "belief", "truth", "tilt", "cmd", "depth", "plan_at", "world_at")
ONE_DAY = "public, max-age=86400"
JOB_ID = re.compile(r"^[0-9a-f]{6,32}$")
# the pages load only from their own origin (the libraries are vendored, the fonts served, no CDN); inline scripts and
# styles are the import map and the shell's own, eval is what deck.gl's shaders need
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'self'")


class HttpError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def render_open(method: str, path: str, body: dict | None = None, timeout: float = 5.0):
    """The render service's response (MINIVIEW_RENDER, read at each request) to be used as a context manager. Its own errors come
    back as HttpError with its code and reason; one that does not answer is a 503 saying so."""
    base = os.environ.get("MINIVIEW_RENDER", "").rstrip("/")
    if not base:
        raise HttpError(503, "no render service configured")
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error") or e.reason
        except (ValueError, AttributeError):
            msg = e.reason
        raise HttpError(e.code, str(msg)) from None
    except (urllib.error.URLError, OSError) as e:
        raise HttpError(503, f"render service not answering: {getattr(e, 'reason', e)}") from None


def render_json(method: str, path: str, body: dict | None = None, timeout: float = 5.0):
    try:
        with render_open(method, path, body, timeout) as r:
            return json.loads(r.read())
    except (ValueError, OSError) as e:      # an answer that is not JSON, or a connection lost while reading it
        raise HttpError(503, f"render service not answering: {e}") from None


def number(q: dict, k: str) -> float | None:
    """A finite number from the query, None when absent; HttpError 400 for anything else."""
    v = q.get(k)
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except ValueError:
        raise HttpError(400, f"{k}: {v!r} is not a number") from None
    if not math.isfinite(x):
        raise HttpError(400, f"{k}: {v!r} is not a finite number")
    return x


def integer(q: dict, k: str, default: int = 0) -> int:
    v = q.get(k)
    if v in (None, ""):
        return default
    try:
        x = int(v)
    except ValueError:
        raise HttpError(400, f"{k}: {v!r} is not a whole number") from None
    if x < 0:
        raise HttpError(400, f"{k}: {v!r} is negative")
    return x


def window(f: dict, n: int, t_from: float | None, t_to: float | None) -> dict:
    """The ticks of [t_from, t_to] out of the first n, with only the plans and worlds those ticks refer to, by index.
    `f` is the run's live lists; the first n ticks are whole (the caller took n under the run's lock)."""
    ts = f["t"]
    lo = 0 if t_from is None else bisect.bisect_left(ts, t_from, 0, n)
    hi = n if t_to is None else bisect.bisect_right(ts, t_to, 0, n)
    out = {k: f[k][lo:hi] for k in PER_TICK}
    out["plans"] = {str(i): f["plans"][i] for i in sorted({i for i in out["plan_at"] if i >= 0})}
    out["worlds"] = {str(i): f["worlds"][i] for i in sorted({i for i in out["world_at"] if i >= 0})}
    out["i0"], out["ticks"] = lo, n
    return out


def signals_window(sig: dict, n: int, t_from: float | None, t_to: float | None) -> dict:
    """The signals ticks of [t_from, t_to] out of the first n: `i0` is the first one's number in the run, `v` the values per
    signal (null where a tick carried none)."""
    ts = sig["t"]
    lo = 0 if t_from is None else bisect.bisect_left(ts, t_from, 0, n)
    hi = n if t_to is None else bisect.bisect_right(ts, t_to, 0, n)
    return {"i0": lo, "n": n, "t": ts[lo:hi], "v": {k: col[lo:hi] for k, col in sig["v"].items()}}


def presence(run: dict, frames: dict, sig: dict | None = None, raw: list | None = None) -> dict:
    """Per stream: the spans where it has data (gaps longer than 3 ticks split them) or the times of
    its records, for the timeline's data rows."""
    ts = frames["t"]

    def spans(times, ts=ts):
        dts = sorted(b - a for a, b in zip(ts, ts[1:]))
        gap = 3 * (dts[len(dts) // 2] if dts else 0.1)
        out = []
        for t in times:
            if out and t - out[-1][1] <= gap:
                out[-1][1] = t
            else:
                out.append([t, t])
        return out

    def depth_kind(k):
        return [t for t, d in zip(ts, frames["depth"]) if d and any(p[3] == k for p in d)]

    sigs = {}
    if sig:
        for name, col in sig["v"].items():
            sigs[f"signals.{name}"] = {"spans": spans([t for t, x in zip(sig["t"], col) if x is not None], sig["t"])}
    return {"t0": run["t0"], "t1": run["t1"], "streams": {
        **sigs,
        "belief.pose": {"spans": spans(ts)},
        "truth.pose": {"spans": spans([t for t, x in zip(ts, frames["truth"]) if x])},
        "sensors.depth.floor": {"spans": spans(depth_kind("f"))},
        "sensors.depth.obstacle": {"spans": spans(depth_kind("o"))},
        "sensors.depth.overhead": {"spans": spans(depth_kind("v"))},
        "sensors.depth.below": {"times": depth_kind("b")},
        "sensors.tilt": {"spans": spans([t for t, x in zip(ts, frames["tilt"]) if x])},
        "sensors.raw": {"spans": spans([f["t"] for f in raw or ()], [f["t"] for f in raw or ()])},
        "world.grid": {"times": [w["t"] for w in frames["worlds"]]},
        "plan.path": {"times": [p["t"] for p in frames["plans"]]},
        "events": {"times": [e["t"] for e in run["events"]]},
    }}


class Handler(http.server.BaseHTTPRequestHandler):
    catalog: Catalog = None
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_S
    # one thread per connection, unbounded: a non-goal on a loopback service for one operator (ADR-0010)

    def log_message(self, *a):
        pass

    def version_string(self):
        return "miniview"

    # ---- plumbing --------------------------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra=None, cache: str = "no-store", gz: bool = False) -> None:
        headers = dict(extra or {})
        if gz and len(body) > GZIP_OVER and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            headers["Content-Encoding"] = "gzip"
        if gz:
            headers["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200, extra=None) -> None:
        self._send(code, json.dumps(obj, separators=(",", ":")).encode(), "application/json", extra, gz=True)

    def _error(self, code: int, msg: str, **more) -> None:
        self._json(dict(more, error=msg), code)

    def _not_allowed(self):
        self._json({"error": f"{self.command} is not allowed here", "allow": "GET, HEAD"}, 405, {"Connection": "close", "Allow": "GET, HEAD"})
        self.close_connection = True       # the body of the request, if any, was not read

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._guarded(self._route)

    def do_POST(self):
        parts = [p for p in urllib.parse.urlsplit(self.path).path.split("/") if p]
        if len(parts) == 7 and parts[:3] == ["api", "v1", "runs"] and parts[6] == "video":     # the only POST there is
            self._guarded(self._start_video)
        else:
            self._not_allowed()

    def _route(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, errors="strict").items()}
        parts = [urllib.parse.unquote(p, errors="strict") for p in url.path.split("/") if p]
        if not parts:
            self._send(302, b"", "text/plain", {"Location": "/web/three/"})
        elif parts[0] == "web":
            self._static(parts[1:])
        elif parts[:2] == ["api", "v1"]:
            self._api(parts[2:], q)
        else:
            raise HttpError(404, "not found")

    def _guarded(self, fn) -> None:
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except HttpError as e:
            self._error(e.code, e.msg)
        except UnicodeDecodeError:
            self._error(400, "the URL is not valid UTF-8")
        except Exception:
            eid = uuid.uuid4().hex[:10]
            log.exception("request %s failed (error id %s)", self.path, eid)
            try:
                self._error(500, f"internal error (id {eid})", id=eid)
            except OSError:
                self.close_connection = True

    def _static(self, rest: list) -> None:
        p = (WEB / "/".join(rest)).resolve()
        if p != WEB and WEB not in p.parents:               # before anything that says what is there
            raise HttpError(404, "not found")
        if p.is_dir():
            if not self.path.split("?")[0].endswith("/"):
                return self._send(301, b"", "text/plain", {"Location": self.path.split("?")[0] + "/"})
            p = p / "index.html"
        if not p.is_file():
            raise HttpError(404, "not found")
        cache = ONE_DAY if ("vendor" in p.relative_to(WEB).parts or p.relative_to(WEB).parts[0] == "fonts") else "no-cache"
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            ctype = "text/javascript"
        elif p.suffix == ".woff2":
            ctype = "font/woff2"
        self._file(p, ctype, cache, {"Content-Security-Policy": CSP} if p.suffix == ".html" else {})

    def _file(self, p: Path, ctype: str, cache: str = "no-cache", extra: dict | None = None) -> None:
        """A file with an ETag (304 when the client has it)."""
        st = p.stat()
        etag = f'"{st.st_size:x}-{st.st_mtime_ns:x}"'
        if self.headers.get("If-None-Match") == etag:
            return self._send(304, b"", "text/plain", {"ETag": etag}, cache)
        self._send(200, p.read_bytes(), ctype, {"ETag": etag, **(extra or {})}, cache)

    # ---- the API ---------------------------------------------------------------------------------
    def _api(self, parts: list, q: dict) -> None:
        cat = self.catalog
        if parts == ["health"]:
            return self._json({"ok": True, "runs": len(cat.paths), "data": str(cat.data), "cache_mb": round(cat.cache_used() / 1048576, 1)})
        if parts == ["scenes"]:
            return self._json(cat.scenes_with_runs())
        if len(parts) == 2 and parts[0] == "scenes":
            sc = cat.scene(parts[1]) if keys.PART.match(parts[1]) else None
            if sc is None:
                raise HttpError(404, f"no scene {parts[1]!r}")
            return self._json(sc)
        if parts == ["runs"]:
            return self._json(cat.list_runs(q.get("robot"), q.get("scene"), q.get("status")))
        if len(parts) >= 4 and parts[0] == "runs":
            try:
                key = keys.make_key(*parts[1:4])
            except ValueError as e:
                raise HttpError(400, str(e)) from None
            what = parts[4] if len(parts) > 4 else ""
            if len(parts) > 5 or what not in ("", "frames", "signals", "sensor", "state", "events", "presence", "live"):
                raise HttpError(404, "not found")
            ld = cat.get(key)
            if ld is None:
                raise HttpError(404, f"no run {key!r}")
            if ld.error and what:
                raise HttpError(409, f"the run is broken: {ld.error}")
            if what == "live":
                return self._live(ld, q)
            return self._run_answer(ld, what, q)
        if parts == ["robots"]:
            return self._json(robots.listing())
        if len(parts) == 2 and parts[0] == "robots":
            desc = robots.description(parts[1])
            if desc is None:
                raise HttpError(404, f"no robot {parts[1]!r}")
            return self._json(desc)
        if len(parts) > 2 and parts[0] == "robots":
            p = robots.mesh(parts[1], parts[2:])
            if p is None:
                raise HttpError(404, "no such mesh")
            return self._file(p, "model/stl")
        if parts == ["render"]:
            return self._render()
        if parts[:1] == ["videos"] and len(parts) in (2, 3) and (len(parts) == 2 or parts[2] == "file"):
            if not JOB_ID.match(parts[1]):
                raise HttpError(404, f"no video {parts[1]!r}")
            return self._video_file(parts[1]) if len(parts) == 3 else self._json(render_json("GET", f"/jobs/{parts[1]}"))
        raise HttpError(404, "not found")

    # ---- the render service (ADR-0017): miniview passes through, writes nothing -------------------------------
    def _render(self) -> None:
        try:
            return self._json(render_json("GET", "/engines", timeout=3))
        except HttpError as e:
            self._json({"available": False, "why": e.msg if e.code == 503 else f"render service not answering: {e.msg}"})

    def _start_video(self) -> None:
        parts = [urllib.parse.unquote(p, errors="strict") for p in urllib.parse.urlsplit(self.path).path.split("/") if p]
        try:
            key = keys.make_key(*parts[3:6])
        except ValueError as e:
            raise HttpError(400, str(e)) from None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= 65536:
            self.close_connection = True
            raise HttpError(400, "the request body is missing or too large")
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise HttpError(400, "the body is not JSON") from None
        if not isinstance(req, dict):
            raise HttpError(400, "the body is not a JSON object")
        self._json(render_json("POST", "/jobs", dict(req, run=key)), 202)

    def _video_file(self, jid: str) -> None:
        with render_open("GET", f"/jobs/{jid}/file", timeout=30) as r:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", r.headers["Content-Length"])
            self.send_header("Content-Disposition", r.headers.get("Content-Disposition", "inline"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(r, self.wfile)

    def _snapshot(self, ld):
        """(run copy, n ticks, seq) taken under the run's lock; what is served is built after it is released."""
        d = ld.data
        with d.changed:
            run = dict(d.run, epochs=list(d.run["epochs"]), events=list(d.run["events"]),
                       segments=list(d.run["segments"]))
            return run, len(d.frames["t"]), d.seq

    def _run_answer(self, ld, what: str, q: dict) -> None:
        cat, f = self.catalog, ld.data.frames
        run, n, seq = self._snapshot(ld)
        if what == "":
            return self._json(dict(run, status=cat.status(ld), seq=seq))
        if what == "frames":
            t_from, t_to = number(q, "from"), number(q, "to")
            if t_from is not None and t_to is not None and t_from > t_to:
                raise HttpError(400, f"from {t_from} is after to {t_to}")
            return self._json(window(f, n, t_from, t_to))
        if what == "signals":
            t_from, t_to = number(q, "from"), number(q, "to")
            if t_from is not None and t_to is not None and t_from > t_to:
                raise HttpError(400, f"from {t_from} is after to {t_to}")
            return self._json(signals_window(ld.data.sig, run["samples"], t_from, t_to))
        if what == "sensor":
            t = number(q, "t")
            with ld.data.changed:
                raw = ld.data.raw
                fr = query.sensor_at(raw, run["t1"] if t is None else t)
            if fr is None:
                raise HttpError(404, "the run has no raw depth frames")
            return self._json(fr)
        if what == "events":
            return self._json(query.events(run, set(q["kinds"].split(",")) if q.get("kinds") else None))
        if n == 0 and run["samples"] == 0:
            raise HttpError(409, "the run has no ticks yet")
        frames = {k: (v[:n] if k in PER_TICK else list(v)) for k, v in f.items()}
        sig = {"t": ld.data.sig["t"][:run["samples"]], "v": {k: c[:run["samples"]] for k, c in ld.data.sig["v"].items()}}
        if what == "state":
            t = number(q, "t")
            return self._json(query.state(run, frames, run["t1"] if t is None else t, sig))
        with ld.data.changed:
            raw = list(ld.data.raw)
        return self._json(presence(run, frames, sig, raw))

    @staticmethod
    def _ev(name: str, data, eid=None) -> bytes:
        head = f"id: {eid}\n" if eid is not None else ""
        return f"{head}event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()

    def _live(self, ld, q: dict) -> None:
        last_id = self.headers.get("Last-Event-ID")
        try:
            if last_id not in (None, ""):                # a reconnect: the id the client last saw is current, `since` is its first URL's
                seq = int(last_id)
                if seq < 0:
                    raise ValueError
            else:
                seq = integer(q, "since", 0)
        except ValueError:
            raise HttpError(400, f"Last-Event-ID: {last_id!r} is not a whole number") from None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command == "HEAD":
            return
        self.connection.settimeout(STREAM_TIMEOUT_S)       # a client that stops reading is dropped, not waited for
        data, cat, beat = ld.data, self.catalog, time.monotonic()
        gen = data.generation
        with cat.lock:
            ld.pins += 1                                 # an open stream keeps its run in memory
        try:
            while True:
                with data.changed:                       # look and wait under one lock: a notify cannot slip between
                    if data.generation != gen or seq > data.seq:
                        items, reset = [], True
                    else:
                        items, reset = data.since(seq), False
                        if not items and cat.status(ld) == "live" and not ld.error:
                            data.changed.wait(timeout=1.0)
                            if data.generation != gen:
                                continue
                            items = data.since(seq)
                    t1, generation = data.run["t1"], data.generation
                if reset:                                # the file was rewritten: the client starts over
                    self.wfile.write(self._ev("rewritten", {"seq": data.seq, "generation": data.generation}))
                    self.wfile.flush()
                    return
                out = [self._ev(kind, dict(p, t=t), s_) for s_, t, kind, p in items]    # one write for what this wake-up found
                if items:
                    seq = items[-1][0]
                status = cat.status(ld)
                if items:
                    out.append(self._ev("status", {"status": status, "seq": seq, "t1": t1, "generation": generation}))
                    beat = time.monotonic()
                if status != "live" and not data.since(seq):
                    out.append(self._ev("status", {"status": status, "seq": seq, "t1": t1, "generation": generation, "done": True,
                                                   **({"error": ld.error} if ld.error else {})}))
                    self.wfile.write(b"".join(out))
                    self.wfile.flush()
                    return
                if time.monotonic() - beat > HEARTBEAT_S:
                    out.append(b": heartbeat\n\n")
                    beat = time.monotonic()
                if out:
                    self.wfile.write(b"".join(out))
                    self.wfile.flush()
        finally:
            with cat.lock:
                ld.pins -= 1


def make_server(catalog: Catalog, host: str = "127.0.0.1", port: int = 8070, follow: bool = True):
    if follow:
        catalog.index.hold()
    catalog.scan()
    handler = type("BoundHandler", (Handler,), {"catalog": catalog})
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    if follow:
        threading.Thread(target=catalog.follow_forever, daemon=True).start()
    return httpd
