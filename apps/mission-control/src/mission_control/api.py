"""The HTTP API (RFC-0014 §3.2): JSON over HTTP and one server-sent-events stream, standard library only.
Every client uses this and nothing else; `CONTRACT.md` beside the package is the written contract and
`tests/test_api.py` checks it. Replies are {"ok": true, ...} or {"ok": false, "error": {code, message}}."""

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import profiles
from .auth import unauthorized
from .core import MissionControl
from .errors import ApiError, invalid, not_found

API = "/api/v1"
# What needs no token even when tokens are required: the health check, and STOP, which is open to everybody (RFC-0017 §3.4).
OPEN_ROUTES = ("health", "stop", "stop_all")
WEB = Path(__file__).resolve().parent / "web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml"}
MAX_BODY = 1_000_000
KEEPALIVE_S = 15.0
SSE_BATCH = 200


def _number(body: dict, key: str, default=None, *, required: bool = False) -> float:
    value = body.get(key, default)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid(f"{key} must be a number")
    return float(value)


def _int(text: str, what: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise not_found(what, text) from None


class Route:
    def __init__(self, method: str, pattern: str, fn):
        self.method, self.fn = method, fn
        self.regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", API + pattern) + "$")


ROUTES: list = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append(Route(method, pattern, fn))
        return fn
    return deco


class Ctx:
    """What a route function gets: the core, the path's parts, the query, the body."""

    def __init__(self, mc: MissionControl, args: dict, query: dict, body, headers, server, identity: str | None = None):
        self.mc, self.args, self.query, self.body, self.headers, self.server = mc, args, query, body, headers, server
        self.identity = identity            # the client a valid token names, else None

    def client(self) -> str:
        """Who is calling: what the token says, else (home-lab mode) what the caller says, else 'api'. A token's client cannot
        be overridden: it is how a client is held to the name it was given."""
        if self.identity:
            return self.identity
        name = self.body.get("client") if isinstance(self.body, dict) else None
        return str(name or self.headers.get("X-Client") or "api")

    def q(self, key: str, default=None):
        return self.query.get(key, [default])[0]


# --- robots ----------------------------------------------------------------------------------------

@route("GET", "/health")
def health(c: Ctx):
    return {"ok": True, "service": "mission-control", "robots": len(c.mc.robots)}


@route("GET", "/robots")
def robots(c: Ctx):
    return {"ok": True, "robots": c.mc.list_robots()}


@route("GET", "/robots/{id}")
def robot(c: Ctx):
    return {"ok": True, "robot": c.mc.get_robot(c.args["id"])}


@route("POST", "/robots/{id}/drive")
def drive(c: Ctx):
    rt = c.mc.robot(c.args["id"])
    vx, vyaw = _number(c.body, "vx", required=True), _number(c.body, "vyaw", 0.0)
    if not rt.online():
        raise ApiError(503, "robot_offline", f"{rt.cfg.id} is offline: nothing was queued", robot=rt.cfg.id)
    return {"ok": True, "drive": rt.drive(c.body.get("session"), vx, vyaw)}


@route("POST", "/robots/{id}/lock")
def lock_acquire(c: Ctx):
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).acquire(c.identity or c.body.get("client"))}


@route("POST", "/robots/{id}/lock/renew")
def lock_renew(c: Ctx):
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).renew(c.body.get("session"))}


@route("DELETE", "/robots/{id}/lock")
def lock_release(c: Ctx):
    c.mc.robot(c.args["id"]).release(c.body.get("session") or c.q("session"))
    return {"ok": True}


@route("POST", "/robots/{id}/lock/takeover")
def lock_takeover(c: Ctx):
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).acquire(c.identity or c.body.get("client"), takeover=True)}


@route("POST", "/robots/{id}/stop")
def stop(c: Ctx):
    return {"ok": True, "stop": c.mc.stop(c.args["id"], c.client())}


@route("POST", "/stop")
def stop_all(c: Ctx):
    return {"ok": True, "stop": c.mc.stop_all(c.client())}


@route("GET", "/robots/{id}/map")
def robot_map(c: Ctx):
    rt = c.mc.robot(c.args["id"])
    if not rt.cfg.capabilities.get("map"):
        raise ApiError(404, "no_map", f"{rt.cfg.id} has no map")
    return {"ok": True, "map": rt.adapter.map()}


@route("GET", "/robots/{id}/sighting")
def robot_sighting(c: Ctx):
    rt = c.mc.robot(c.args["id"])
    if not rt.cfg.capabilities.get("recognisers"):
        raise ApiError(404, "no_recogniser", f"{rt.cfg.id} has no recogniser")
    return {"ok": True, "sighting": rt.adapter.sighting()}


# --- a robot's profile versions (phase 5 step 1: profiles.py) ------------------------------------------

@route("GET", "/robots/{id}/profile")
def profile_view(c: Ctx):
    return {"ok": True, "profile": profiles.view(c.mc.robot(c.args["id"]))}


@route("POST", "/robots/{id}/profile")
def profile_save(c: Ctx):
    return 201, {"ok": True, "saved": profiles.save(c.mc.robot(c.args["id"]), c.body.get("profile"))}


@route("PUT", "/robots/{id}/profile/current")
def profile_use(c: Ctx):
    return {"ok": True, "profile": profiles.use(c.mc.robot(c.args["id"]), c.body.get("version"))}


@route("GET", "/robots/{id}/profile/export")
def profile_export(c: Ctx):
    n = c.q("version")
    return {"ok": True, "export": profiles.export(c.mc.robot(c.args["id"]), _int(n, "version") if n else None)}


@route("POST", "/robots/{id}/profile/import")
def profile_import(c: Ctx):
    return {"ok": True, "imported": profiles.import_(c.mc.robot(c.args["id"]), c.body.get("export"))}


@route("GET", "/robots/{id}/profile/diff")
def profile_diff(c: Ctx):
    a, b = c.q("a"), c.q("b")
    if not a or not b:
        raise invalid("diff needs ?a=<version>&b=<version>")
    return {"ok": True, "diff": profiles.compare(c.mc.robot(c.args["id"]), _int(a, "version"), _int(b, "version"),
                                                 c.q("notes") in ("1", "true"))}


@route("PUT", "/robots/{id}/site")
def robot_site(c: Ctx):
    return {"ok": True, "robot": c.mc.assign_site(c.args["id"], c.body.get("site"))}


# --- goals and goal runs -----------------------------------------------------------------------------

@route("GET", "/goals")
def goals_list(c: Ctx):
    return {"ok": True, "goals": c.mc.list_goals(c.q("folder"))}


@route("POST", "/goals")
def goals_create(c: Ctx):
    return 201, {"ok": True, "goal": c.mc.create_goal(c.body)}


@route("GET", "/goals/{id}")
def goal_get(c: Ctx):
    return {"ok": True, "goal": c.mc.get_goal(_int(c.args["id"], "goal"))}


@route("PUT", "/goals/{id}")
def goal_put(c: Ctx):
    return {"ok": True, "goal": c.mc.update_goal(_int(c.args["id"], "goal"), c.body)}


@route("DELETE", "/goals/{id}")
def goal_delete(c: Ctx):
    c.mc.retire_goal(_int(c.args["id"], "goal"))
    return {"ok": True}


@route("POST", "/goals/{id}/runs")
def goal_run(c: Ctx):
    return 201, {"ok": True, "run": c.mc.run_goal(_int(c.args["id"], "goal"), c.body, c.client())}


@route("POST", "/goal-runs")
def adhoc_run(c: Ctx):
    return 201, {"ok": True, "run": c.mc.run_adhoc(c.body, c.client())}


@route("GET", "/goal-runs")
def runs_list(c: Ctx):
    goal, parent = c.q("goal"), c.q("parent")
    return {"ok": True, "runs": c.mc.list_runs(robot=c.q("robot"), state=c.q("state"),
                                               goal_id=_int(goal, "goal") if goal is not None else None,
                                               parent=_int(parent, "goal run") if parent is not None else None)}


@route("GET", "/goal-runs/{id}")
def run_get(c: Ctx):
    return {"ok": True, "run": c.mc.get_run(_int(c.args["id"], "goal run"))}


@route("POST", "/goal-runs/{id}/cancel")
def run_cancel(c: Ctx):
    return {"ok": True, "run": c.mc.cancel_run(_int(c.args["id"], "goal run"))}


@route("POST", "/goal-runs/{id}/save")
def run_save(c: Ctx):
    return 201, {"ok": True, "goal": c.mc.save_run(_int(c.args["id"], "goal run"), c.body)}


@route("POST", "/plan")
def plan(c: Ctx):
    """Words in, goals out: proposals to confirm, nothing run (§3.4.5). The phrase matcher answers the simple ones with no model;
    an LLM is asked only when planner.json configured one."""
    return {"ok": True, "plan": c.mc.plan(c.body.get("text"), c.body.get("robot"), c.body.get("site"))}


# --- sites, areas, objects ---------------------------------------------------------------------------

@route("GET", "/sites")
def sites_list(c: Ctx):
    return {"ok": True, "sites": c.mc.sites.list()}


@route("POST", "/sites")
def sites_create(c: Ctx):
    return 201, {"ok": True, "site": c.mc.sites.create(c.body.get("name"), c.body.get("kind"))}


@route("GET", "/sites/{s}")
def site_get(c: Ctx):
    return {"ok": True, "site": c.mc.sites.get(c.args["s"])}


@route("PUT", "/sites/{s}")
def site_put(c: Ctx):
    return {"ok": True, "site": c.mc.sites.update(c.args["s"], c.body.get("name"), c.body.get("kind"))}


@route("DELETE", "/sites/{s}")
def site_delete(c: Ctx):
    c.mc.sites.retire(c.args["s"])
    return {"ok": True}


@route("POST", "/sites/{s}/export")
def site_export(c: Ctx):
    return {"ok": True, "bundle": c.mc.sites.export_site(c.args["s"])}


@route("POST", "/sites/{s}/import")
def site_import(c: Ctx):
    bundle = c.body.get("bundle", c.body)
    return {"ok": True, "imported": c.mc.sites.import_site(c.args["s"], bundle)}


@route("GET", "/sites/{s}/areas")
def areas_list(c: Ctx):
    return {"ok": True, "frame": "site", "areas": c.mc.sites.areas(c.args["s"])}


@route("POST", "/sites/{s}/areas")
def areas_create(c: Ctx):
    return 201, {"ok": True, "area": c.mc.sites.create_area(c.args["s"], c.body.get("name"), c.body.get("type"), c.body.get("outline"))}


@route("GET", "/sites/{s}/areas/at")
def area_at(c: Ctx):
    try:
        x, y = float(c.q("x")), float(c.q("y"))
    except (TypeError, ValueError):
        raise invalid("x and y are numbers, in metres in the site frame") from None
    area = c.mc.sites.area_at(c.args["s"], x, y)
    return {"ok": True, "frame": "site", "x": x, "y": y, "area": area, **({} if area else {"message": "none defined"})}


@route("GET", "/sites/{s}/areas/{a}")
def area_get(c: Ctx):
    return {"ok": True, "area": c.mc.sites.area(c.args["s"], c.args["a"])}


@route("PUT", "/sites/{s}/areas/{a}")
def area_put(c: Ctx):
    return {"ok": True, "area": c.mc.sites.update_area(c.args["s"], c.args["a"], c.body)}


@route("DELETE", "/sites/{s}/areas/{a}")
def area_delete(c: Ctx):
    c.mc.sites.delete_area(c.args["s"], c.args["a"])
    return {"ok": True}


@route("POST", "/sites/{s}/areas/{a}/merge")
def area_merge(c: Ctx):
    body = dict(c.body)
    other = body.pop("other", None)
    if not isinstance(other, str):
        raise invalid("body is {other, name?, type?, outline?}")
    return {"ok": True, "area": c.mc.sites.merge_areas(c.args["s"], c.args["a"], other, body)}


@route("POST", "/sites/{s}/areas/{a}/split")
def area_split(c: Ctx):
    return {"ok": True, "areas": c.mc.sites.split_area(c.args["s"], c.args["a"], c.body.get("line"), c.body.get("name"),
                                                       c.body.get("name_kept"))}


@route("GET", "/sites/{s}/objects")
def objects_list(c: Ctx):
    return {"ok": True, "frame": "site", "objects": c.mc.sites.objects(c.args["s"])}


@route("POST", "/sites/{s}/objects/{o}/label")
def object_label(c: Ctx):
    obj = c.mc.sites.label(c.args["s"], c.args["o"], c.body.get("label"))
    c.mc.bus.emit("object-named", site=c.args["s"], object=obj["id"], label=obj["label"])
    return {"ok": True, "object": obj}


@route("GET", "/sites/{s}/inventory")
def inventory(c: Ctx):
    return {"ok": True, "inventory": c.mc.sites.inventory(c.args["s"])}


@route("GET", "/sites/{s}/guardrails")
def guardrails_get(c: Ctx):
    return {"ok": True, "guardrails": c.mc.sites.guardrails(c.args["s"])}


@route("PUT", "/sites/{s}/guardrails")
def guardrails_put(c: Ctx):
    return {"ok": True, "guardrails": c.mc.sites.set_guardrails(c.args["s"], c.body.get("guardrails"))}


# --- tokens (§3.9) -------------------------------------------------------------------------------------

@route("GET", "/tokens")
def tokens_list(c: Ctx):
    return {"ok": True, "tokens": c.mc.tokens.list(), "required": c.server.require_tokens}


@route("POST", "/tokens")
def tokens_create(c: Ctx):
    """A new token for a client. The token is in this reply and nowhere else: only its hash is kept."""
    tid, token = c.mc.tokens.create(c.body.get("client"))
    return 201, {"ok": True, "token": {"id": tid, "client": c.body["client"].strip(), "token": token}}


@route("DELETE", "/tokens/{id}")
def token_revoke(c: Ctx):
    return {"ok": True, "token": c.mc.tokens.revoke(_int(c.args["id"], "token"))}


# --- the live stream ---------------------------------------------------------------------------------

@route("GET", "/events")
def events(c: Ctx):
    return ("stream", c)


def serve_events(h, c: Ctx) -> None:
    """GET /events?since=&state_hz=&robots=a,b&goal_run=: server-sent events, one per bus event, each with
    its sequence number as the SSE id. Without `since` the stream starts from now; `since=0` replays
    what the ring holds. `state_hz` lowers the state rate for this subscription, within what the
    robot's own rate allows (§3.2.2)."""
    mc, stopping = c.mc, c.server.stopping
    try:
        since = int(c.q("since", c.headers.get("Last-Event-ID") or mc.bus.seq))  # a browser's EventSource resumes with the header
        state_hz = float(c.q("state_hz")) if c.q("state_hz") is not None else None
        goal_run = int(c.q("goal_run")) if c.q("goal_run") is not None else None
        if state_hz is not None and state_hz <= 0:
            raise ValueError
    except ValueError:
        raise invalid("since and goal_run are whole numbers, state_hz a number above 0") from None
    wanted = set(c.q("robots").split(",")) if c.q("robots") else None
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.end_headers()
    last_state: dict = {}
    idle = 0.0
    seq = since
    h.wfile.write(b": connected\n\n")
    h.wfile.flush()
    while not stopping.is_set():
        batch, gap = mc.bus.since(seq, SSE_BATCH)
        if gap:
            h.wfile.write(f"event: gap\ndata: {json.dumps({'after': seq})}\n\n".encode())
        for e in batch:
            seq = e["seq"]
            if wanted is not None and e.get("robot") not in wanted:
                continue
            if goal_run is not None and e.get("goal_run") != goal_run:
                continue
            if e["kind"] == "state" and state_hz is not None:
                if e["t"] - last_state.get(e["robot"], -1e18) < 1.0 / state_hz - 1e-6:
                    continue
                last_state[e["robot"]] = e["t"]
            h.wfile.write(f"id: {e['seq']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n".encode())
        h.wfile.flush()
        if not batch:
            if mc.bus.wait(seq, 1.0):
                continue
            idle += 1.0
            if idle >= KEEPALIVE_S:
                idle = 0.0
                h.wfile.write(b": keepalive\n\n")
                h.wfile.flush()
        else:
            idle = 0.0


# --- the server --------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "mission-control/0.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path: str) -> None:
        """The page: index.html at / and the files of web/ under /web/. A name is one plain file name."""
        name = "index.html" if path == "/" else path[len("/web/"):]
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name) or not (WEB / name).is_file():
            raise ApiError(404, "no_route", f"no such file {path}")
        data = (WEB / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _identity(self, query: dict) -> str | None:
        """The client a valid token names. The token is `Authorization: Bearer ...`, or `?token=` (an EventSource sets no header)."""
        auth = self.headers.get("Authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else (query.get("token") or [None])[0]
        return self.server.mc.tokens.verify(token) if token else None

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "too_large", f"a body is at most {MAX_BODY} bytes")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ApiError(400, "bad_json", f"the body is not JSON: {exc}") from None
        if not isinstance(body, dict):
            raise ApiError(400, "bad_json", "the body is a JSON object")
        return body

    def _handle(self, method: str) -> None:
        url = urlsplit(self.path)
        try:
            if method == "GET" and (url.path == "/" or url.path.startswith("/web/")):
                self._static(url.path)
                return
            for r in ROUTES:
                m = r.regex.match(url.path.rstrip("/") or "/")
                if m and r.method == method:
                    break
            else:
                known = [r for r in ROUTES if r.regex.match(url.path.rstrip("/"))]
                if known:
                    raise ApiError(405, "method_not_allowed", f"{method} is not allowed here: {sorted({r.method for r in known})}")
                raise ApiError(404, "no_route", f"no such path {url.path}")
            query = parse_qs(url.query)
            identity = self._identity(query)
            if self.server.require_tokens and identity is None and r.fn.__name__ not in OPEN_ROUTES:
                raise unauthorized("this server wants a token: Authorization: Bearer mc_... (the event stream also takes ?token=)"
                                   if "Authorization" not in self.headers and "token" not in query else "that token is not valid (revoked or unknown)")
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            ctx = Ctx(self.server.mc, m.groupdict(), query, body, self.headers, self.server, identity)
            result = r.fn(ctx)
            if isinstance(result, tuple) and result and result[0] == "stream":
                serve_events(self, result[1])
                return
            status, payload = result if isinstance(result, tuple) else (200, result)
            self._send(status, payload)
        except ApiError as exc:
            self._send(exc.status, exc.to_json())
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            print(f"mission-control: {method} {self.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                self._send(500, {"ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}})
            except OSError:
                pass

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, mc: MissionControl, require_tokens: bool = False):
        super().__init__(address, Handler)
        self.mc = mc
        self.require_tokens = require_tokens
        self.stopping = threading.Event()

    def shutdown(self) -> None:
        self.stopping.set()
        self.mc.bus.wake()
        super().shutdown()


def serve(mc: MissionControl, host: str = "127.0.0.1", port: int = 8060, require_tokens: bool = False) -> Server:
    """Build the server; the caller runs `serve_forever` (in a thread, for a test)."""
    return Server((host, port), mc, require_tokens)
