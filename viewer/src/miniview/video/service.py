"""`miniview render-serve`: the render service of the video export (ADR-0017), standard library only. It renders runs to videos
for miniview's pages, one job at a time, in its own process: an engine needs its own Python and library, and miniview stays
read-only. It reads the runs from the data folder (read-only) and writes the videos to <state>/videos/.

    GET  /engines        {"engines": [{"name", "available", "why", "robots"}]}
    POST /jobs           {"run": key, "engine", "from"?, "to"?, "size"?: "1280x720"} -> 202 {"id"}; 409 while a job runs
    GET  /jobs/{id}      {"id", "run", "engine", "status": queued|running|done|failed, "error", "file"}
    GET  /jobs/{id}/file the finished video (video/mp4)

Errors are JSON ({"error": ...}). Loopback by default: there is no authentication, the service runs what the robot's
robots.json names.
"""

import http.server
import json
import logging
import re
import shutil
import threading
import urllib.parse
import uuid
from pathlib import Path

from runfile import keys
from miniview import video

log = logging.getLogger("miniview.render")
SIZE = re.compile(r"^(\d{2,5})x(\d{2,5})$")
MAX_BODY = 65536
def engines() -> list:
    """Every engine the service knows of: its name, whether it can render now, why not, and the robots it can render."""
    out = []
    for name in video.ENGINES:
        robots, whys = [], []
        script = video.engine_script(name)
        if script is None or not Path(script).is_file():
            whys.append(f"the {name} engine script is not there")
        else:
            for robot, models in video.ROBOTS.items():
                model = models.get(name)
                if not model:
                    continue
                prog = video.program(name, model)       # the model's Python, or Blender's binary for blender
                if Path(prog).is_file():
                    robots.append(robot)
                else:
                    whys.append(f"{robot}: the {name} program {prog} does not exist")
        out.append({"name": name, "available": bool(robots), "why": None if robots else (whys[0] if whys else f"no robot has a {name} model"),
                    "robots": robots})
    return out


class HttpError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def _number(req: dict, k: str):
    v = req.get(k)
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
        raise HttpError(400, f"{k}: {v!r} is not a finite number")
    return float(v)


class Jobs:
    """The jobs by id; one runs at a time."""

    def __init__(self, data: Path, state: Path):
        self.data, self.videos = Path(data), Path(state) / "videos"
        self.lock = threading.Lock()
        self.jobs = {}

    def start(self, req: dict) -> dict:
        key, engine = req.get("run"), req.get("engine")
        try:
            robot = keys.split_key(key)[0]
        except ValueError as e:
            raise HttpError(400, str(e)) from None
        listed = engines()
        found = next((e for e in listed if e["name"] == engine), None)
        if found is None:
            raise HttpError(400, f"no engine {engine!r}; the engines are {', '.join(e['name'] for e in listed)}")
        if not found["available"]:
            raise HttpError(503, f"the {engine} engine is not available: {found['why']}")
        if robot not in found["robots"]:
            raise HttpError(400, f"the {engine} engine has no model for the robot {robot!r}")
        if not keys.run_dir(self.data, key).is_dir():
            raise HttpError(404, f"no run {key!r}")
        t_from, t_to = _number(req, "from"), _number(req, "to")
        if t_from is not None and t_to is not None and t_from > t_to:
            raise HttpError(400, f"from {t_from} is after to {t_to}")
        m = SIZE.match(str(req.get("size") or "1280x720"))
        if not m:
            raise HttpError(400, f"size {req.get('size')!r}: WIDTHxHEIGHT, like 1280x720")
        size = (int(m[1]), int(m[2]))
        with self.lock:
            if any(j["status"] in ("queued", "running") for j in self.jobs.values()):
                raise HttpError(409, "a video is being rendered; one at a time")
            jid = uuid.uuid4().hex[:10]
            out = self.videos / f"{key.replace('/', '-')}-{engine}-{jid}.mp4"
            job = {"id": jid, "run": key, "engine": engine, "status": "queued", "error": None, "file": None}
            self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, engine, out, size, t_from, t_to), daemon=True).start()
        return job

    def _run(self, job: dict, engine: str, out: Path, size: tuple, t_from, t_to) -> None:
        job["status"] = "running"
        try:
            video.export(self.data, job["run"], engine, out, size=size, t_from=t_from, t_to=t_to)
            if not out.is_file():
                raise RuntimeError(f"the {engine} engine finished and wrote no file")
            job["file"] = out.name
            job["status"] = "done"
        except BaseException as e:      # export ends a failure with SystemExit(message)
            job["error"] = str(e.code) if isinstance(e, SystemExit) and e.code is not None else (str(e) or type(e).__name__)
            job["status"] = "failed"
            log.warning("job %s failed: %s", job["id"], job["error"])


class Handler(http.server.BaseHTTPRequestHandler):
    jobs: Jobs = None
    protocol_version = "HTTP/1.1"
    timeout = 30.0

    def log_message(self, *a):
        pass

    def version_string(self):
        return "miniview-render"

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _guarded(self, fn) -> None:
        try:
            parts = [urllib.parse.unquote(p) for p in urllib.parse.urlsplit(self.path).path.split("/") if p]
            fn(parts)
        except HttpError as e:
            self._json({"error": e.msg}, e.code)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            eid = uuid.uuid4().hex[:10]
            log.exception("request %s failed (error id %s)", self.path, eid)
            self._json({"error": f"internal error (id {eid})", "id": eid}, 500)

    def do_GET(self):
        self._guarded(self._get)

    do_HEAD = do_GET

    def do_POST(self):
        self._guarded(self._post)

    def _get(self, parts: list) -> None:
        if parts == ["engines"]:
            return self._json({"engines": engines()})
        if parts[:1] == ["jobs"] and (len(parts) == 2 or (len(parts) == 3 and parts[2] == "file")):
            job = self.jobs.jobs.get(parts[1])
            if job is None:
                raise HttpError(404, f"no job {parts[1]!r}")
            if len(parts) == 2:
                return self._json(job)
            if job["status"] != "done":
                raise HttpError(409, f"the job is {job['status']}, there is no video")
            path = self.jobs.videos / job["file"]
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
            self.end_headers()
            if self.command != "HEAD":
                with path.open("rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            return
        raise HttpError(404, "not found")

    def _post(self, parts: list) -> None:
        if parts != ["jobs"]:
            raise HttpError(404, "not found")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self.close_connection = True
            raise HttpError(400, "the request is too large")
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise HttpError(400, "the body is not JSON") from None
        if not isinstance(req, dict):
            raise HttpError(400, "the body is not a JSON object")
        self._json({"id": self.jobs.start(req)["id"]}, 202)


def make_server(data: Path, state: Path, host: str = "127.0.0.1", port: int = 8071):
    handler = type("BoundHandler", (Handler,), {"jobs": Jobs(data, state)})
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def serve(data: Path, state: Path, host: str, port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    httpd = make_server(data, state, host, port)
    print(f"miniview render service at http://{host}:{port}/, data {data} (read only), videos in {Path(state) / 'videos'}", flush=True)
    httpd.serve_forever()
