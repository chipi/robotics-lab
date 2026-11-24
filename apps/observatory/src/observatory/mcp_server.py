"""The Observatory's MCP server: an outside agent's read-only way into the recorded runs. It is a client of the HTTP API (CONTRACT.md,
/api/v1), like the pages, and has no path of its own; it speaks MCP over stdio (`observatory mcp`).

Read only is enforced where it cannot be forgotten: every call goes through `Api`, whose allow-list is GET routes and nothing else.
There is no way to start a video, rebuild the index or reach Mission Control's /control/ routes, whatever a tool asks, and a tool added
carelessly cannot reach them either.

Not covered, because the API has no read-only HTTP route for it: the anomaly findings and detectors (`observatory anomalies`, CLI only),
the archive's dry run (`observatory archive`, CLI only; this server never shells out), a diff of two runs (compare_runs returns both
summaries), and the heavy windows (frames, signals, the raw depth frame, the live stream)."""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_URL = "http://127.0.0.1:8070"
TIMEOUT_S = 15.0

_ID = r"[a-z0-9_-]+"        # a robot, scene or run name (runfile.keys.PART): no slash, no dot, so no way to another route
# (method, path under /api/v1) of every call this server may make. Nothing else is called, whatever a tool asks.
ALLOWED = [(m, re.compile("^" + p + "$")) for m, p in [
    ("GET", "/health"), ("GET", "/scenes"), ("GET", f"/scenes/{_ID}"), ("GET", "/runs"), ("GET", f"/runs/{_ID}/{_ID}/{_ID}"),
    ("GET", f"/runs/{_ID}/{_ID}/{_ID}/(events|state|semantic|presence)"),
    ("GET", "/robots"), ("GET", f"/robots/{_ID}"),
]]


class Refused(ToolError):
    """This server does not do that, whatever the agent asks."""


def q(value) -> str:
    """A value as one path segment: a slash in an id cannot make another route."""
    return quote(str(value), safe="")


class Api:
    def __init__(self, base_url: str = DEFAULT_URL):
        self.base = base_url.rstrip("/") + "/api/v1"

    def call(self, method: str, path: str, query: dict | None = None):
        if not any(m == method and rx.match(path) for m, rx in ALLOWED):
            raise Refused(f"refused: this server may not call {method} {path}")
        url = self.base + path + ("?" + "&".join(f"{k}={quote(str(v))}" for k, v in query.items() if v is not None) if query else "")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read()).get("error")
            except ValueError:
                err = None
            raise ToolError(f"{exc.code}: {err or exc.reason}") from None
        except urllib.error.URLError as exc:
            raise ToolError(f"unreachable: the Observatory at {self.base} did not answer ({exc.reason})") from None


def _run_path(robot: str, scene: str, run: str) -> str:
    return f"/runs/{q(robot)}/{q(scene)}/{q(run)}"


def build_server(base_url: str | None = None) -> MCPServer:
    api = Api(base_url or os.environ.get("OBSERVATORY_URL", DEFAULT_URL))
    mcp = MCPServer("observatory", instructions=(
        "The Observatory: the lab's recorded runs, read only. Start with get_health and list_runs, then get_run for a run's summary "
        "(robot, scene, verdict, status) and get_run_events for what happened. A run is named by robot, scene and run name (its key is "
        "robot/scene/run). You cannot start a video, rebuild the index, or control a robot. Anomaly findings and the archive are not "
        "available here (the `observatory anomalies` and `observatory archive` commands)."))

    @mcp.tool()
    def get_health() -> dict:
        """The index's status: ok, the number of runs it holds, the data folder, the cache size."""
        return api.call("GET", "/health")

    @mcp.tool()
    def list_runs(robot: str | None = None, scene: str | None = None, status: str | None = None, kind: str | None = None,
                  started_after_ns: int | None = None, started_before_ns: int | None = None) -> dict:
        """The runs from the index: key, robot, scene, kind, status, length, verdict, event count, start time. Filters: robot, scene,
        status (the API's); kind and the start time (nanoseconds since the epoch, after/before) are applied here."""
        runs = api.call("GET", "/runs", {"robot": robot, "scene": scene, "status": status})
        return {"runs": [r for r in runs if (kind is None or r["kind"] == kind)
                and (started_after_ns is None or (r["started_at_ns"] or 0) >= started_after_ns)
                and (started_before_ns is None or (r["started_at_ns"] or 0) < started_before_ns)]}

    @mcp.tool()
    def get_run(robot: str, scene: str, run: str) -> dict:
        """One run's summary: its record without the per-tick data (robot, scene, kind, times, verdict, epochs, segments, status)."""
        return api.call("GET", _run_path(robot, scene, run))

    @mcp.tool()
    def get_run_events(robot: str, scene: str, run: str, kinds: str | None = None) -> dict:
        """What happened in a run, when; `kinds` is a comma-separated list to keep."""
        return {"events": api.call("GET", _run_path(robot, scene, run) + "/events", {"kinds": kinds})}

    @mcp.tool()
    def get_run_state(robot: str, scene: str, run: str, t: float | None = None) -> dict:
        """A run at time t (default its end): belief, truth, distance, depth returns, the last event, the semantic map if it has one."""
        return api.call("GET", _run_path(robot, scene, run) + "/state", {"t": t})

    @mcp.tool()
    def get_run_presence(robot: str, scene: str, run: str) -> dict:
        """Per stream, the time spans or times a run has data for."""
        return api.call("GET", _run_path(robot, scene, run) + "/presence")

    @mcp.tool()
    def get_run_semantic(robot: str, scene: str, run: str, t_from: float | None = None, t_to: float | None = None) -> dict:
        """A run's semantic map: object snapshots and camera sightings in a time window (empty lists for a run with neither)."""
        return api.call("GET", _run_path(robot, scene, run) + "/semantic", {"from": t_from, "to": t_to})

    @mcp.tool()
    def compare_runs(a: str, b: str) -> dict:
        """Two runs' summaries side by side, `a` and `b` being run keys (robot/scene/run). The Observatory has no compare or diff
        route, so this does not compute a difference: it returns both summaries and says so."""
        def one(key: str) -> dict:
            parts = key.split("/")
            if len(parts) != 3:
                raise ToolError(f"{key!r} is not a run key (robot/scene/run)")
            return api.call("GET", _run_path(*parts))
        return {"a": one(a), "b": one(b), "note": "No compare route in the Observatory's API: these are the two summaries side by side, not a diff."}

    @mcp.tool()
    def list_scenes() -> dict:
        """The scenes with their runs, newest first."""
        return api.call("GET", "/scenes")

    @mcp.tool()
    def get_scene(scene: str) -> dict:
        """A scene as it really is, in the world frame: bounds, boxes, hazards."""
        return api.call("GET", f"/scenes/{q(scene)}")

    @mcp.tool()
    def list_robots() -> dict:
        """The robots that have a description: name, label, links, joints, meshes, simulator, backend."""
        return {"robots": api.call("GET", "/robots")}

    @mcp.tool()
    def get_robot(robot: str) -> dict:
        """One robot's description: links with their visuals, joints, missing meshes, stand height."""
        return api.call("GET", f"/robots/{q(robot)}")

    return mcp
