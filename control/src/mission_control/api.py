"""The HTTP API (RFC-0014 §3.2): JSON over HTTP and one server-sent-events stream, standard library only.
Every client uses this and nothing else; `CONTRACT.md` beside the package is the written contract and
`tests/test_api.py` checks it. Replies are {"ok": true, ...} or {"ok": false, "error": {code, message}}."""

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .core import MissionControl
from .errors import ApiError, invalid, not_found

API = "/api/v1"
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

    def __init__(self, mc: MissionControl, args: dict, query: dict, body, headers, server):
        self.mc, self.args, self.query, self.body, self.headers, self.server = mc, args, query, body, headers, server

    def client(self) -> str:
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
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).acquire(c.body.get("client"))}


@route("POST", "/robots/{id}/lock/renew")
def lock_renew(c: Ctx):
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).renew(c.body.get("session"))}


@route("DELETE", "/robots/{id}/lock")
def lock_release(c: Ctx):
    c.mc.robot(c.args["id"]).release(c.body.get("session") or c.q("session"))
    return {"ok": True}


@route("POST", "/robots/{id}/lock/takeover")
def lock_takeover(c: Ctx):
    return {"ok": True, "lock": c.mc.robot(c.args["id"]).acquire(c.body.get("client"), takeover=True)}


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
    return 201, {"ok": True, "run": c.mc.run_goal(_int(c.args["id"], "goal"), c.body)}


@route("POST", "/goal-runs")
def adhoc_run(c: Ctx):
    return 201, {"ok": True, "run": c.mc.run_adhoc(c.body)}


@route("GET", "/goal-runs")
def runs_list(c: Ctx):
    goal = c.q("goal")
    return {"ok": True, "runs": c.mc.list_runs(robot=c.q("robot"), state=c.q("state"),
                                               goal_id=_int(goal, "goal") if goal is not None else None)}


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
    raise ApiError(501, "no_planner", "no planner is configured: goals are defined by hand, from the library or by an agent")


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
        since = int(c.q("since", mc.bus.seq))
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
            for r in ROUTES:
                m = r.regex.match(url.path.rstrip("/") or "/")
                if m and r.method == method:
                    break
            else:
                known = [r for r in ROUTES if r.regex.match(url.path.rstrip("/"))]
                if known:
                    raise ApiError(405, "method_not_allowed", f"{method} is not allowed here: {sorted({r.method for r in known})}")
                raise ApiError(404, "no_route", f"no such path {url.path}")
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            ctx = Ctx(self.server.mc, m.groupdict(), parse_qs(url.query), body, self.headers, self.server)
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

    def __init__(self, address, mc: MissionControl):
        super().__init__(address, Handler)
        self.mc = mc
        self.stopping = threading.Event()

    def shutdown(self) -> None:
        self.stopping.set()
        self.mc.bus.wake()
        super().shutdown()


def serve(mc: MissionControl, host: str = "127.0.0.1", port: int = 8060) -> Server:
    """Build the server; the caller runs `serve_forever` (in a thread, for a test)."""
    return Server((host, port), mc)
