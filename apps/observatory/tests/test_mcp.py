"""The Observatory's MCP server (apps/observatory/src/observatory/mcp_server.py): read only, a client of the HTTP API through an
allow-list of GET routes, no path of its own. A real Observatory on a temporary data folder with two runs; every tool through the MCP
client (in-process), once over stdio (`observatory mcp`), and the must-fail checks: no tool reaches a non-GET route or a route outside
the list. Run: cd apps/observatory && uv run python tests/test_mcp.py"""

import asyncio
import json
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import Checks, T0_NS, catalog, make_run, scene, serve, tick
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from observatory.mcp_server import ALLOWED, Api, Refused, build_server

check = Checks("OBSERVATORY MCP")
HEAD = [(0.0, "epoch", {"map_to_world": [1.0, 0.0, 0.0]})]


async def tool(c, name, /, **args):
    r = await c.call_tool(name, args)
    text = r.content[0].text if r.content else ""
    try:
        return r.is_error, json.loads(text)
    except json.JSONDecodeError:
        return r.is_error, text


class Spy(BaseHTTPRequestHandler):
    """An upstream that records every request it gets: what the server calls, whatever the tool."""
    seen: list = []

    def log_message(self, *a):
        pass

    def _h(self):
        Spy.seen.append((self.command, self.path))
        body = b'[]' if self.path.split("?")[0].endswith("/runs") else b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = _h


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    cat = catalog(data)
    cat.put_scene(scene("room"))
    make_run(data, "duck/room/r1", HEAD + [tick(1.0, 0.0), tick(1.1, 0.03), (1.5, "event", {"kind": "trapped", "text": "trapped"}),
                                          (2.0, "end", {"verdict": "trapped"})], started_at_ns=T0_NS)
    make_run(data, "rover/room/r2", HEAD + [tick(1.0, 0.0), tick(1.1, 0.05), (2.0, "end", {"verdict": "done"})], started_at_ns=T0_NS + 100 * 10**9)
    httpd, URL = serve(cat)

    spy = ThreadingHTTPServer(("127.0.0.1", 0), Spy)
    spy.daemon_threads = True
    threading.Thread(target=spy.serve_forever, daemon=True).start()
    SPY = f"http://127.0.0.1:{spy.server_address[1]}"

    async def main():
        async with Client(build_server(URL)) as c:
            listed = (await c.list_tools()).tools
            names = {t.name for t in listed}
            check("the tools: runs, one run, its events, state, presence, semantic, compare, scenes, robots, health", {
                "list_runs", "get_run", "get_run_events", "get_run_state", "get_run_presence", "get_run_semantic", "compare_runs",
                "list_scenes", "get_scene", "list_robots", "get_robot", "get_health"} <= names, sorted(names))
            check("every tool says what it does", all(t.description for t in listed))
            check("no tool writes: nothing about video, index, archive, control, import, repair, compact",
                  not any(re.search(r"video|render|index|archive|control|import|repair|compact|delete|write|start|rebuild", n) for n in names), sorted(names))
            check("no tool is named for anomalies or the archive: they have no read-only HTTP route", not any(re.search("anomal|detector|archive", n) for n in names))

            err, j = await tool(c, "get_health")
            check("get_health: the index status", not err and j["ok"] is True and j["runs"] == 2, j)
            err, j = await tool(c, "list_runs")
            check("list_runs: both runs", not err and {r["key"] for r in j["runs"]} == {"duck/room/r1", "rover/room/r2"}, j)
            err, j = await tool(c, "list_runs", robot="duck")
            check("list_runs by robot", not err and [r["key"] for r in j["runs"]] == ["duck/room/r1"], j)
            err, j = await tool(c, "list_runs", scene="room", status="ended")
            check("list_runs by scene and status", not err and len(j["runs"]) == 2, j)
            err, j = await tool(c, "list_runs", kind="exploration")
            check("list_runs by kind", not err and len(j["runs"]) == 2, j)
            err, j = await tool(c, "list_runs", kind="nothing")
            check("list_runs by a kind nobody has: none", not err and j in ({"runs": []}, {"events": []}), j)
            err, j = await tool(c, "list_runs", started_after_ns=T0_NS + 50 * 10**9)
            check("list_runs by time (after)", not err and [r["key"] for r in j["runs"]] == ["rover/room/r2"], j)
            err, j = await tool(c, "list_runs", started_before_ns=T0_NS + 50 * 10**9)
            check("list_runs by time (before)", not err and [r["key"] for r in j["runs"]] == ["duck/room/r1"], j)
            err, j = await tool(c, "get_run", robot="duck", scene="room", run="r1")
            check("get_run: the summary with status", not err and j["status"] == "ended" and j["robot"]["name"] == "duck", j.get("status") if isinstance(j, dict) else j)
            err, j = await tool(c, "get_run_events", robot="duck", scene="room", run="r1")
            check("get_run_events", not err and any(e.get("kind") == "trapped" for e in j["events"]), j)
            err, j = await tool(c, "get_run_events", robot="duck", scene="room", run="r1", kinds="nothing")
            check("get_run_events filtered by kind", not err and j in ({"runs": []}, {"events": []}), j)
            err, j = await tool(c, "get_run_state", robot="duck", scene="room", run="r1", t=1.0)
            check("get_run_state at t", not err and isinstance(j, dict) and "belief_map" in j, j)
            err, j = await tool(c, "get_run_presence", robot="duck", scene="room", run="r1")
            check("get_run_presence", not err and isinstance(j, dict) and j, j)
            err, j = await tool(c, "get_run_semantic", robot="duck", scene="room", run="r1")
            check("get_run_semantic: empty for a run without a map", not err and j == {"objects": [], "sightings": []}, j)
            err, j = await tool(c, "compare_runs", a="duck/room/r1", b="rover/room/r2")
            check("compare_runs: both summaries side by side, and it says there is no diff route",
                  not err and j["a"]["key"] == "duck/room/r1" and j["b"]["key"] == "rover/room/r2" and "no compare" in j["note"].lower(), j)
            err, j = await tool(c, "compare_runs", a="duck/room", b="rover/room/r2")
            check("compare_runs: a key that is not robot/scene/run is an error", err, j)
            err, j = await tool(c, "list_scenes")
            check("list_scenes", not err and j["scenes"][0]["id"] == "room", j)
            err, j = await tool(c, "get_scene", scene="room")
            check("get_scene", not err and j["id"] == "room", j)
            err, j = await tool(c, "list_robots")
            check("list_robots: the descriptions", not err and any(r["name"] == "duck" for r in j["robots"]), j)
            err, j = await tool(c, "get_robot", robot="duck")
            check("get_robot: its description", not err and j["name"] == "duck" and j["links"], str(j)[:200])
            err, j = await tool(c, "get_run", robot="duck", scene="room", run="nope")
            check("an API error comes back as an error with its message", err and "no run" in j, j)
            err, j = await tool(c, "get_run", robot="duck", scene="room", run="r1/frames")
            check("an id with a slash cannot make another route", err, j)
            err, j = await tool(c, "get_run", robot="..", scene="room", run="r1")
            check("a dot-dot id is refused or not found, never another route", err, j)
            err, j = await tool(c, "post_video")
            check("there is no tool that starts a video", err and "Unknown tool" in str(j), j)

        # --- every tool, aimed at a spy: only GETs on listed routes ------------------------------------------
        async with Client(build_server(SPY)) as c:
            args = {"robot": "duck", "scene": "room", "run": "r1", "t": 1.0, "kinds": "a,b", "a": "duck/room/r1", "b": "rover/room/r2",
                    "started_after_ns": 1, "started_before_ns": 2, "kind": "x", "status": "ended"}
            for t in (await c.list_tools()).tools:
                props = t.input_schema.get("properties", {})
                await c.call_tool(t.name, {k: v for k, v in args.items() if k in props})
        check("every tool, called, made only GETs", Spy.seen and {m for m, _ in Spy.seen} == {"GET"}, sorted(set(Spy.seen))[:6])
        check("every call went to /api/v1 and to a listed route", all(any(rx.match(p.split("?")[0].removeprefix("/api/v1")) for m, rx in ALLOWED) for _, p in Spy.seen)
              and all(p.startswith("/api/v1/") for _, p in Spy.seen), Spy.seen)

    async def over_stdio():
        params = StdioServerParameters(command=sys.executable, args=["-m", "observatory.cli", "mcp", "--url", URL])
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            err, j = await tool(c, "get_health")
            check("over stdio (`observatory mcp`): the same tools and answers", "list_runs" in names and not err and j["runs"] == 2, names)
        async with Client(StdioServerParameters(command=sys.executable, args=["-m", "observatory.cli", "mcp", "--url", "http://127.0.0.1:9"])) as c:
            err, j = await tool(c, "get_health")
            check("with the Observatory down the error says so", err and "unreachable" in j, j)

    asyncio.run(main())
    asyncio.run(over_stdio())

    # --- the allow-list is the only way out: the guard, without MCP ------------------------------------------------
    api = Api(URL)
    for method, path in [("POST", "/runs/duck/room/r1/video"), ("PUT", "/runs/duck/room/r1"), ("DELETE", "/runs/duck/room/r1"),
                         ("POST", "/runs"), ("POST", "/health"), ("GET", "/control/api/v1/robots"), ("GET", "/videos/abc"),
                         ("GET", "/videos/abc/file"), ("GET", "/render"), ("GET", "/runs/duck/room/r1/live"),
                         ("GET", "/runs/duck/room/r1/frames"), ("GET", "/runs/duck/room/r1/signals"), ("GET", "/runs/duck/room/r1/sensor"),
                         ("GET", "/robots/duck/meshes/body.stl"), ("GET", "/watch/duck/room/r1"), ("GET", "/web/three/"), ("GET", "/"),
                         ("GET", "/runs/duck/room/r1/x/y"), ("GET", "/../etc/passwd"), ("get", "/health")]:
        try:
            api.call(method, path)
            ok = False
        except Refused as e:
            ok = "refused" in str(e)
        check(f"the allow-list refuses {method} {path}", ok)
    check("every allowed route is a GET", all(m == "GET" for m, _ in ALLOWED), [m for m, _ in ALLOWED])
    Spy.seen.clear()
    try:
        Api(SPY).call("POST", "/health")
    except Refused:
        pass
    check("a refused call never reaches the network", Spy.seen == [], Spy.seen)
    httpd.shutdown()

check.done()
