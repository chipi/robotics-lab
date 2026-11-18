"""The MCP server (RFC-0014 §3.2, §3.8, §3.9; control/src/mission_control/mcp_server.py), driven as an MCP client would
drive it: in-process for the tools, and once over stdio as a subprocess for the transport. Behind it a real Mission Control
on the real clock with the fake robot. The refusals are tested as hard as the tools: no firing (O21), no takeover, no
areas, no real robot, and that the allow-list is the only way out of the process.
Run: cd control && uv run python tests/test_mcp.py"""

import asyncio
import copy
import json
import sys
import tempfile
import threading
import time
import urllib.request

from common import FAKE_FILE, check, finish, robot_file

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mission_control.api import serve
from mission_control.core import MissionControl
from mission_control.mcp_server import ALLOWED, Api, Refused, build_server
from mission_control.robots import RobotConfig

caps = copy.deepcopy(FAKE_FILE["capabilities"])
caps["drive"] = {"max_vx": 2.0, "max_vyaw": 6.0, "deadman_s": 0.5}
mc = MissionControl([RobotConfig(robot_file("fake-1", capabilities=caps, rates={"state_hz": 5.0, "map_hz": 2.0, "max_state_hz": 10.0}))],
                    state_dir=tempfile.mkdtemp(prefix="mc-mcp-"))
srv = serve(mc, "127.0.0.1", 0)
URL = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
mc.start()
time.sleep(0.5)


def http(method, path, body=None, client="operator"):
    req = urllib.request.Request(URL + "/api/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json", "X-Client": client})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


async def tool(c, name, /, **args):
    """(is_error, parsed JSON or text)."""
    r = await c.call_tool(name, args)
    text = r.content[0].text if r.content else ""
    try:
        return r.is_error, json.loads(text)
    except json.JSONDecodeError:
        return r.is_error, text


async def run_done(c, run_id, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _, j = await tool(c, "get_run", run_id=run_id)
        if j["run"]["state"] not in ("queued", "running"):
            return j["run"]
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not end")


async def main():
    async with Client(build_server(URL)) as c:
        listed = (await c.list_tools()).tools
        names = {t.name for t in listed}
        check("the agent gets tools for robots, the lock, goals, runs, sites and STOP", {
            "list_robots", "get_robot", "get_robot_map", "get_sighting", "acquire_lock", "drive", "stop_robot", "stop_all", "list_goals",
            "get_goal", "create_goal", "run_goal", "run_adhoc_goal", "list_runs", "get_run", "cancel_run", "save_run", "list_sites",
            "get_site", "list_areas", "area_at", "list_objects", "get_inventory", "get_site_guardrails", "export_site", "label_object"} <= names, sorted(names))
        check("every tool says what it does", all(t.description for t in listed))
        check("there is no tool that fires, takes over, draws or deletes an area, makes a site or imports one (O21, RFC-0017 §3.5.7, §3.5.3)",
              not any(re.search(r"fire|shoot|takeover|take_over|create_area|update_area|delete_area|merge|split|import|create_site|delete_site", n) for n in names), sorted(names))
        check("no tool lets the agent choose the client it speaks as", all("client" not in json.dumps(t.input_schema) for t in listed))
        for bad in ("fire", "shoot", "takeover", "take_over", "create_area", "delete_area", "import_site", "create_site", "plan"):
            err, msg = await tool(c, bad)
            check(f"calling '{bad}' is an error: there is no such tool", err and "Unknown tool" in str(msg), msg)

        # --- robots, read ---------------------------------------------------------------------------
        err, j = await tool(c, "list_robots")
        check("list_robots", not err and j["robots"][0]["id"] == "fake-1" and j["robots"][0]["online"] is True, j)
        err, j = await tool(c, "get_robot", robot_id="fake-1")
        check("get_robot: capabilities and status", not err and j["robot"]["capabilities"]["navigator"] and j["robot"]["status"]["pose"]["frame"] == "site")
        err, j = await tool(c, "get_robot_map", robot_id="fake-1")
        check("get_robot_map", not err and j["map"]["kind"] == "occupancy_grid")
        err, j = await tool(c, "get_sighting", robot_id="fake-1")
        check("get_sighting", not err and "hfov_deg" in j["sighting"])
        err, j = await tool(c, "get_robot", robot_id="nope")
        check("an API error comes back as an error with its code and message, for the agent to read", err and "not_found" in j and "no robot nope" in j, j)
        err, j = await tool(c, "get_robot", robot_id="fake-1/fire")
        check("an id with a slash cannot make another route", err, j)

        # --- the lock and driving -----------------------------------------------------------------------
        err, j = await tool(c, "acquire_lock", robot_id="fake-1")
        sess = j["lock"]["session"]
        check("acquire_lock: a session, in the agent's own name", not err and http("GET", "/robots/fake-1")["robot"]["lock"]["holder"] == "mcp-agent", j)
        other = http("POST", "/robots/fake-1/lock", {"client": "script"})
        check("another client is refused while the agent holds it", other["ok"] is False and other["error"]["code"] == "held" and other["error"]["holder"] == "mcp-agent")
        err, j = await tool(c, "drive", robot_id="fake-1", session=sess, vx=0.5, vyaw=0.0)
        time.sleep(0.4)
        check("drive moves the robot", not err and http("GET", "/robots/fake-1")["robot"]["status"]["pose"]["x"] > 0.05, j)
        err, j = await tool(c, "renew_lock", robot_id="fake-1", session=sess)
        check("renew_lock", not err)
        err, j = await tool(c, "stop_robot", robot_id="fake-1")
        check("stop_robot: confirmed, with the agent's name in the log", not err and j["stop"]["confirmed"] is True
              and any(e["kind"] == "stop" and e["client"] == "mcp-agent" for e in mc.bus.since(0, 100000)[0]), j)
        err, j = await tool(c, "drive", robot_id="fake-1", session=sess, vx=0.5)
        check("STOP latched: the agent's next drive is refused with why", err and "lease_ended" in j and "stopped_by mcp-agent" in j, j)
        err, j = await tool(c, "acquire_lock", robot_id="fake-1")
        sess = j["lock"]["session"]
        tk = http("POST", "/robots/fake-1/lock/takeover", {"client": "operator-laptop"})
        err, j = await tool(c, "drive", robot_id="fake-1", session=sess, vx=0.1)
        check("the operator's takeover ends the agent's control, and the agent is told", tk["ok"] and err and "taken_over_by operator-laptop" in j, j)
        http("DELETE", "/robots/fake-1/lock", {"session": tk["lock"]["session"]})
        err, j = await tool(c, "acquire_lock", robot_id="fake-1")
        http("POST", "/robots/fake-1/stop")
        http("POST", "/robots/fake-1/lock", {"client": "script"})
        err, j = await tool(c, "acquire_lock", robot_id="fake-1")
        check("a robot another client holds is refused to the agent, naming the holder: it cannot take it", err and "held" in j and "script" in j, j)
        err, j = await tool(c, "stop_robot", robot_id="fake-1")
        check("but STOP needs no lock and is never refused", not err and j["stop"]["confirmed"] is True)

        # --- goals and runs --------------------------------------------------------------------------------
        err, j = await tool(c, "create_goal", goal={"name": "to the door", "folder": "agent", "kind": "point", "params": {"x": 1.0, "y": 0.5}, "must_not": ["contact"]})
        gid = j["goal"]["id"]
        check("create_goal", not err and j["goal"]["folder"] == "agent" and j["goal"]["must_not"] == [{"name": "contact"}], j)
        err, j = await tool(c, "create_goal", goal={"name": "x", "kind": "fetch", "params": {}})
        check("a goal of an unknown kind is an error naming the code", err and "unknown_kind" in j, j)
        err, j = await tool(c, "list_goals", folder="agent")
        check("list_goals by folder", not err and [g["id"] for g in j["goals"]] == [gid])
        err, j = await tool(c, "get_goal", goal_id=gid)
        check("get_goal", not err and j["goal"]["name"] == "to the door")
        err, j = await tool(c, "run_goal", goal_id=gid, robot_id="fake-1")
        run_id = j["run"]["id"]
        check("run_goal starts a run on the simulator target", not err and j["run"]["target"] == "sim" and j["run"]["state"] == "running", j)
        run = await run_done(c, run_id)
        check("get_run follows it to the end: reached, with decisions and the merged guardrails", run["state"] == "reached" and run["decisions"]
              and run["guardrails"][0]["name"] == "contact", run["state"])
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "point", "params": {"x": 9.0, "y": 0.0}, "expect": "refuse"}, robot_id="fake-1")
        check("a goal the navigator refuses is a run in the state refused, with the reason, as expected", not err and j["run"]["state"] == "refused"
              and j["run"]["as_expected"] is True and "outside the world" in j["run"]["reason"], j)
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "point", "params": {"x": 3.5, "y": -2.0}}, robot_id="fake-1")
        long_id = j["run"]["id"]
        err, j = await tool(c, "cancel_run", run_id=long_id)
        check("cancel_run: cancelled", not err and j["run"]["state"] == "cancelled")
        err, j = await tool(c, "save_run", run_id=long_id, name="far corner", folder="agent")
        check("save_run puts the run's goal in the library", not err and j["goal"]["name"] == "far corner")
        err, j = await tool(c, "list_runs", robot_id="fake-1", state="cancelled")
        check("list_runs filters", not err and [r["id"] for r in j["runs"]] == [long_id])

        # --- the real robot is the operator's to allow -------------------------------------------------------
        before = len(http("GET", "/goal-runs")["runs"])
        err, j = await tool(c, "run_goal", goal_id=gid, robot_id="fake-1", target="real")
        check("a real target is refused by default, before it reaches Mission Control", err and "simulator only" in j and len(http("GET", "/goal-runs")["runs"]) == before, j)
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "point", "params": {"x": 0, "y": 0}}, robot_id="fake-1", target="moon")
        check("any target but sim is refused", err and "refused" in j, j)
        async with Client(build_server(URL, allow_real=True)) as real:
            err, j = await tool(real, "run_goal", goal_id=gid, robot_id="fake-1", target="real")
            check("when the operator allows it the guard lets it through and the API still protects (the fake is not real)", err and "not a real robot" in j, j)

        # --- sites, areas, objects: read, and naming --------------------------------------------------------
        http("POST", "/sites", {"name": "Home", "kind": "apartment"})
        http("PUT", "/robots/fake-1/site", {"site": "home"})
        http("POST", "/sites/home/areas", {"name": "Kitchen", "outline": [[2.0, 0.5], [3.9, 0.5], [3.9, 2.9], [2.0, 2.9]]})
        err, j = await tool(c, "list_sites")
        check("list_sites", not err and [s["id"] for s in j["sites"]] == ["home"])
        err, j = await tool(c, "get_site", site="home")
        check("get_site", not err and j["site"]["counts"]["areas"] == 1)
        err, j = await tool(c, "list_areas", site="home")
        check("list_areas: the operator's area", not err and [a["name"] for a in j["areas"]] == ["Kitchen"])
        err, j = await tool(c, "area_at", site="home", x=3.0, y=1.0)
        check("area_at", not err and j["area"]["id"] == "kitchen")
        err, j = await tool(c, "area_at", site="home", x=-3.0, y=-1.0)
        check("area_at: none defined", not err and j["area"] is None)
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "inventory", "params": {"areas": []}}, robot_id="fake-1", site="home")
        run = await run_done(c, j["run"]["id"], 90)
        check("the agent sets an inventory goal and follows it: done", run["state"] == "done", (run["state"], run["reason"]))
        err, j = await tool(c, "list_objects", site="home")
        fridge = next(o for o in j["objects"] if o["kind"] == "fridge")
        check("list_objects: stable ids, the fridge in the operator's kitchen", not err and len(j["objects"]) == 4 and fridge["area"] == "kitchen", fridge)
        err, j = await tool(c, "get_inventory", site="home")
        check("get_inventory", not err and j["inventory"]["areas"][0]["objects"][0]["kind"] == "fridge")
        err, j = await tool(c, "get_site_guardrails", site="home")
        check("get_site_guardrails", not err and j["guardrails"] == [])
        err, j = await tool(c, "export_site", site="home")
        check("export_site is read only", not err and j["bundle"]["format"] == "mission-control-site")
        err, j = await tool(c, "label_object", site="home", object_id=fridge["id"], label="the cold box")
        check("label_object names an object (RFC-0014 §3.5.2: the MCP tool is the same call)", not err and j["object"]["label"] == "the cold box")
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "go_to_object", "params": {"label": "the cold box"}}, robot_id="fake-1", site="home")
        run = await run_done(c, j["run"]["id"], 60)
        check("and the label works in a goal", run["state"] == "reached" and run["result"]["object"]["label"] == "the cold box", (run["state"], run["reason"]))
        check("nothing the agent did created an area: still the operator's one", len(http("GET", "/sites/home/areas")["areas"]) == 1)

        # --- STOP-all while a goal runs, with the lock held by someone else -----------------------------------
        http("DELETE", "/robots/fake-1/lock", {"session": "x"})
        err, j = await tool(c, "run_adhoc_goal", goal={"kind": "point", "params": {"x": -3.5, "y": -2.5}}, robot_id="fake-1")
        run_id = j["run"]["id"]
        time.sleep(0.5)
        err, j = await tool(c, "stop_all")
        run = await run_done(c, run_id, 10)
        check("stop_all: the run is cancelled, every robot reported", not err and j["stop"]["all_confirmed"] is True and run["state"] == "cancelled" and "stopped by mcp-agent" in run["reason"], (run["state"], run["reason"]))


async def over_stdio():
    params = StdioServerParameters(command=sys.executable, args=["-m", "mission_control.cli", "mcp", "--url", URL])
    async with Client(params) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        err, j = await tool(c, "list_robots")
        check("over stdio, as a client launches it: the same tools and the same answers", "stop_all" in names and not err and j["robots"][0]["id"] == "fake-1", names)
        err, j = await tool(c, "stop_all")
        check("and STOP-all over stdio", not err and j["stop"]["all_confirmed"] is True)
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "mission_control.cli", "mcp", "--url", "http://127.0.0.1:9"])) as c:
        err, j = await tool(c, "list_robots")
        check("with Mission Control down the error says so", err and "unreachable" in j, j)


import re

asyncio.run(main())
asyncio.run(over_stdio())

# --- the allow-list is the only way out: the guard, without MCP --------------------------------------------
api = Api(URL)
for method, path in (("POST", "/robots/fake-1/fire"), ("POST", "/robots/fake-1/lock/takeover"), ("POST", "/sites/home/areas"), ("PUT", "/sites/home/areas/kitchen"),
                     ("DELETE", "/sites/home/areas/kitchen"), ("POST", "/sites/home/areas/kitchen/merge"), ("POST", "/sites/home/import"), ("POST", "/sites"),
                     ("DELETE", "/sites/home"), ("PUT", "/sites/home/guardrails"), ("PUT", "/robots/fake-1/site"), ("POST", "/plan"), ("GET", "/robots/fake-1/skills/fire"),
                     ("POST", "/robots/a/b/stop"), ("GET", "/events")):
    try:
        api.call(method, path, {})
        check(f"the guard refuses {method} {path}", False)
    except Refused as exc:
        check(f"the guard refuses {method} {path}", "refused" in str(exc))
check("every allowed route is one a tool uses: 29 routes, none a write on areas, sites, imports, takeovers or fire", len(ALLOWED) == 29
      and not any(("area" in rx.pattern and m != "GET") or "takeover" in rx.pattern or "fire" in rx.pattern or "import" in rx.pattern for m, rx in ALLOWED), len(ALLOWED))

srv.shutdown()
srv.server_close()
mc.close()
finish("test_mcp")
