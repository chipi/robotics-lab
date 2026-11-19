"""The MCP server (RFC-0014 §3.2, §3.8, §3.9): an outside agent's way in. It is a client of the HTTP API, like the page,
and has no path of its own; it speaks MCP over stdio (`mission-control mcp`).

What an agent may do is what the RFC gives it: watch (robots, status, map, runs, sites, areas, objects), set and run
goals, drive under the exclusive lock, name an object, and STOP, with the same limits as the operator. What it may
not do is not a tool here, and cannot be reached by one that is added carelessly: every call goes through `Api`, whose
allow-list is the only set of routes this process will call.

- **No firing** (O21, §3.8): there is no fire tool, and no allowed route could fire.
- **No takeover** (RFC-0017 §3.5.7): an agent is on no takeover list; no tool and no allowed route takes a robot another
  client holds. It has one client name (`mcp-agent`, or MC_MCP_CLIENT) and cannot choose another.
- **No areas, no sites, no import** (§3.5.3: only the operator draws and deletes areas): read-only, plus naming an object,
  which §3.5.2 gives the MCP tool.
- **No real robots by default** (§3.8, RFC-0002 §3.5: a real run needs the operator in the room): `target` is `sim`
  unless the operator started this server with MC_MCP_ALLOW_REAL=1.
- **STOP is never refused and never needs the lock.**"""

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

def q(value) -> str:
    """A value as one path segment: a slash in an id cannot make another route."""
    return quote(str(value), safe="")


DEFAULT_URL = "http://127.0.0.1:8060"
DEFAULT_CLIENT = "mcp-agent"
TIMEOUT_S = 15.0

_ID = r"[^/]+"
# (method, path) of every call this server may make. Nothing else is called, whatever a tool asks.
ALLOWED = [(m, re.compile("^" + p + "$")) for m, p in [
    ("GET", "/robots"), ("GET", f"/robots/{_ID}"), ("GET", f"/robots/{_ID}/map"), ("GET", f"/robots/{_ID}/sighting"),
    ("POST", f"/robots/{_ID}/lock"), ("POST", f"/robots/{_ID}/lock/renew"), ("DELETE", f"/robots/{_ID}/lock"),
    ("POST", f"/robots/{_ID}/drive"), ("POST", f"/robots/{_ID}/stop"), ("POST", "/stop"),
    ("GET", "/goals"), ("POST", "/goals"), ("GET", f"/goals/{_ID}"), ("POST", f"/goals/{_ID}/runs"),
    ("POST", "/goal-runs"), ("GET", "/goal-runs"), ("GET", f"/goal-runs/{_ID}"),
    ("POST", f"/goal-runs/{_ID}/cancel"), ("POST", f"/goal-runs/{_ID}/save"),
    ("GET", "/sites"), ("GET", f"/sites/{_ID}"), ("GET", f"/sites/{_ID}/areas"), ("GET", f"/sites/{_ID}/areas/at"),
    ("GET", f"/sites/{_ID}/areas/{_ID}"), ("GET", f"/sites/{_ID}/objects"), ("GET", f"/sites/{_ID}/inventory"),
    ("GET", f"/sites/{_ID}/guardrails"), ("POST", f"/sites/{_ID}/export"), ("POST", f"/sites/{_ID}/objects/{_ID}/label"),
]]


class Refused(ToolError):
    """This server does not do that, whatever the agent asks."""


class Api:
    def __init__(self, base_url: str = DEFAULT_URL, client: str = DEFAULT_CLIENT, allow_real: bool = False, token: str | None = None):
        self.base = base_url.rstrip("/") + "/api/v1"
        self.client = client
        self.allow_real = allow_real
        self.token = token             # when Mission Control wants tokens: the token names this agent, and its name is the token's

    def call(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        if not any(m == method and rx.match(path) for m, rx in ALLOWED):
            raise Refused(f"refused: an agent may not call {method} {path}")
        url = self.base + path + ("?" + "&".join(f"{k}={quote(str(v))}" for k, v in query.items() if v is not None) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "X-Client": self.client, **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err = json.loads(exc.read())["error"]
            raise ToolError(f"{err['code']}: {err['message']}") from None
        except urllib.error.URLError as exc:
            raise ToolError(f"unreachable: Mission Control at {self.base} did not answer ({exc.reason})") from None

    def target(self, target: str) -> str:
        if target != "sim" and not self.allow_real:
            raise Refused("refused: an agent runs goals on the simulator only; a real robot needs the operator in the room "
                          "(start this server with MC_MCP_ALLOW_REAL=1 to allow it)")
        return target


def build_server(base_url: str | None = None, client: str | None = None, allow_real: bool | None = None, token: str | None = None) -> MCPServer:
    api = Api(base_url or os.environ.get("MC_URL", DEFAULT_URL), client or os.environ.get("MC_MCP_CLIENT", DEFAULT_CLIENT),
              os.environ.get("MC_MCP_ALLOW_REAL") == "1" if allow_real is None else allow_real, token or os.environ.get("MC_TOKEN"))
    mcp = MCPServer("mission-control", instructions=(
        "Mission Control: the operator's robots, goals, sites and areas. Read first (list_robots, get_robot, list_sites), "
        "then set a goal with run_goal or run_adhoc_goal and follow it with get_run. stop_robot and stop_all are always allowed. "
        "You cannot fire, take a robot from another client, draw areas, or run on a real robot."))

    # --- robots ----------------------------------------------------------------------------------------
    @mcp.tool()
    def list_robots() -> dict:
        """The robots: id, label, kind, whether each is online (measured from its last answer), who holds its lock."""
        return api.call("GET", "/robots")

    @mcp.tool()
    def get_robot(robot_id: str) -> dict:
        """One robot: its capabilities (what it can do), its status (pose, battery, mode), its site, the goal run on it."""
        return api.call("GET", f"/robots/{q(robot_id)}")

    @mcp.tool()
    def get_robot_map(robot_id: str) -> dict:
        """The robot's occupancy grid in the site frame (-1 unknown, 0 free, 100 occupied), if it has a map."""
        return api.call("GET", f"/robots/{q(robot_id)}/map")

    @mcp.tool()
    def get_sighting(robot_id: str) -> dict:
        """The robot's latest camera record: what it recognised, ahead and left of it, if it has a recogniser."""
        return api.call("GET", f"/robots/{q(robot_id)}/sighting")

    # --- the lock and driving --------------------------------------------------------------------------
    @mcp.tool()
    def acquire_lock(robot_id: str) -> dict:
        """Take the exclusive control lock of a robot to drive it. Refused, naming the holder, while another client holds it
        (a goal run holds it too). Returns a session to send with every drive. The lease ends after 20 s of silence."""
        return api.call("POST", f"/robots/{q(robot_id)}/lock", {"client": api.client})

    @mcp.tool()
    def renew_lock(robot_id: str, session: str) -> dict:
        """Keep the lease."""
        return api.call("POST", f"/robots/{q(robot_id)}/lock/renew", {"session": session})

    @mcp.tool()
    def release_lock(robot_id: str, session: str) -> dict:
        """Let the robot go: it is stopped, then free."""
        return api.call("DELETE", f"/robots/{q(robot_id)}/lock", {"session": session})

    @mcp.tool()
    def drive(robot_id: str, session: str, vx: float, vyaw: float = 0.0) -> dict:
        """Drive: forward speed vx in m/s, turn rate vyaw in rad/s. The command lasts the robot's deadman time (0.5 s), so
        send it again to keep going; the robot's own limits apply."""
        return api.call("POST", f"/robots/{q(robot_id)}/drive", {"vx": vx, "vyaw": vyaw, "session": session})

    @mcp.tool()
    def stop_robot(robot_id: str) -> dict:
        """STOP one robot. Always accepted, needs no lock; it ends whoever's lease and latches. `confirmed` says whether the
        robot answered."""
        return api.call("POST", f"/robots/{q(robot_id)}/stop", {"client": api.client})

    @mcp.tool()
    def stop_all() -> dict:
        """STOP every robot at once. Always accepted; a silent robot is reported and the others still stop."""
        return api.call("POST", "/stop", {"client": api.client})

    # --- goals and runs ----------------------------------------------------------------------------------
    @mcp.tool()
    def list_goals(folder: str | None = None) -> dict:
        """The goal library, all of it or one folder (and its subfolders)."""
        return api.call("GET", "/goals", query={"folder": folder})

    @mcp.tool()
    def get_goal(goal_id: int) -> dict:
        """One library goal."""
        return api.call("GET", f"/goals/{goal_id}")

    @mcp.tool()
    def create_goal(goal: dict) -> dict:
        """Define a goal in the library: {name, folder?, kind, params, done_when?, must_not?, expect?, budget?}. Kinds: point
        {x, y}; go_to_object {kind | label | id, area?}; go_to_area {area}; explore {area} or {site: true}; inventory {areas?}.
        must_not lists guardrails (contact, fall, stuck, time_limit {seconds}, max_speed {mps}, drop_clearance {m}); a goal
        adds to the robot's and the site's and never loosens them."""
        return api.call("POST", "/goals", goal)

    @mcp.tool()
    def run_goal(goal_id: int, robot_id: str, site: str | None = None, target: str = "sim") -> dict:
        """Run a library goal on one robot. A goal the robot cannot take comes back as a run in the state `refused`, with
        the reason. Follow it with get_run."""
        body = {"robots": [robot_id], "target": api.target(target)}
        if site:
            body["site"] = site
        return api.call("POST", f"/goals/{goal_id}/runs", body)

    @mcp.tool()
    def run_adhoc_goal(goal: dict, robot_id: str, site: str | None = None, target: str = "sim") -> dict:
        """Run a goal that is not in the library (same shape as create_goal's); nothing is saved. Follow it with get_run."""
        body = {"goal": goal, "robots": [robot_id], "target": api.target(target)}
        if site:
            body["site"] = site
        return api.call("POST", "/goal-runs", body)

    @mcp.tool()
    def list_runs(robot_id: str | None = None, state: str | None = None, goal_id: int | None = None) -> dict:
        """Goal runs, newest first, optionally of one robot, in one state, or of one library goal."""
        return api.call("GET", "/goal-runs", query={"robot": robot_id, "state": state, "goal": goal_id})

    @mcp.tool()
    def get_run(run_id: int) -> dict:
        """One goal run: state, reason, progress, result, the guardrails it ran with, and the navigator's decisions."""
        return api.call("GET", f"/goal-runs/{run_id}")

    @mcp.tool()
    def cancel_run(run_id: int) -> dict:
        """Cancel a running goal: the navigator stops and the robot is stopped."""
        return api.call("POST", f"/goal-runs/{run_id}/cancel")

    @mcp.tool()
    def save_run(run_id: int, name: str, folder: str = "") -> dict:
        """Put the goal of a run in the library."""
        return api.call("POST", f"/goal-runs/{run_id}/save", {"name": name, "folder": folder})

    # --- sites, areas, objects: read, and naming an object ---------------------------------------------
    @mcp.tool()
    def list_sites() -> dict:
        """The sites the operator keeps."""
        return api.call("GET", "/sites")

    @mcp.tool()
    def get_site(site: str) -> dict:
        """One site: name, kind, frame, counts."""
        return api.call("GET", f"/sites/{q(site)}")

    @mcp.tool()
    def list_areas(site: str) -> dict:
        """The operator's areas of a site, each with its outline and the ids of the objects in it. Only the operator draws them."""
        return api.call("GET", f"/sites/{q(site)}/areas")

    @mcp.tool()
    def area_at(site: str, x: float, y: float) -> dict:
        """Which area holds a point of the site frame (metres), or none defined."""
        return api.call("GET", f"/sites/{q(site)}/areas/at", query={"x": x, "y": y})

    @mcp.tool()
    def list_objects(site: str) -> dict:
        """The site's objects: stable id, kind, label, position, area, confidence."""
        return api.call("GET", f"/sites/{q(site)}/objects")

    @mcp.tool()
    def get_inventory(site: str) -> dict:
        """The confirmed objects by area."""
        return api.call("GET", f"/sites/{q(site)}/inventory")

    @mcp.tool()
    def get_site_guardrails(site: str) -> dict:
        """The site's guardrails, including its no-go areas."""
        return api.call("GET", f"/sites/{q(site)}/guardrails")

    @mcp.tool()
    def export_site(site: str) -> dict:
        """The site, its areas, its named objects and its guardrails as one document (read only)."""
        return api.call("POST", f"/sites/{q(site)}/export")

    @mcp.tool()
    def label_object(site: str, object_id: str, label: str) -> dict:
        """Name an object ("this is my desk"). The label works in goals: go_to_object {label}."""
        return api.call("POST", f"/sites/{q(site)}/objects/{q(object_id)}/label", {"label": label})

    return mcp
