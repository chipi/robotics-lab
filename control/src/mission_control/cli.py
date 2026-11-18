"""mission-control serve: the API on one address, the robots from files, the state in one folder.

Defaults are loopback and the folders in the environment, so nothing here is tied to a host
(RFC-0014 §3.13); to listen on the tailnet pass its address as --host (§3.9: the tailnet is the
authentication in v1)."""

import argparse
import os
import signal
import sys
from pathlib import Path

from .api import serve
from .core import MissionControl
from .planner import load_planner
from .robots import ConfigError, load_robot_files


def _terminate(*_):
    raise KeyboardInterrupt


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mission-control", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the API")
    s.add_argument("--robots", type=Path, default=os.environ.get("MC_ROBOTS", "robots"),
                   help="folder of robot files, one <id>.json each (env MC_ROBOTS)")
    s.add_argument("--state", type=Path, default=os.environ.get("MC_STATE", "state"),
                   help="folder for the SQLite store and the gates' logs (env MC_STATE)")
    s.add_argument("--host", default=os.environ.get("MC_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("MC_PORT", "8060")))
    s.add_argument("--planner", type=Path, default=os.environ.get("MC_PLANNER"),
                   help="the LLM planner's settings (default planner.json beside the robot files; none: no LLM) (env MC_PLANNER)")
    m = sub.add_parser("mcp", help="the MCP server for an agent, over stdio, a client of a running API")
    m.add_argument("--url", default=os.environ.get("MC_URL", "http://127.0.0.1:8060"), help="Mission Control's address (env MC_URL)")
    m.add_argument("--client", default=os.environ.get("MC_MCP_CLIENT", "mcp-agent"), help="the name the agent's calls carry")
    m.add_argument("--allow-real", action="store_true", default=os.environ.get("MC_MCP_ALLOW_REAL") == "1",
                   help="let the agent run goals on a real robot (env MC_MCP_ALLOW_REAL=1); the operator must be in the room")
    args = p.parse_args(argv)

    if args.cmd == "mcp":
        from .mcp_server import build_server  # the MCP SDK is only needed here

        build_server(args.url, args.client, args.allow_real).run("stdio")
        return 0

    if not args.robots.is_dir():
        print(f"mission-control: no robots folder {args.robots}", file=sys.stderr)
        return 2
    try:
        configs = load_robot_files(args.robots)
    except ConfigError as exc:
        print(f"mission-control: {exc}", file=sys.stderr)
        return 2
    llm = load_planner(args.planner or args.robots / "planner.json")     # none: the LLM is off; the phrase matcher is always there
    mc = MissionControl(configs, state_dir=args.state, planner=llm)
    server = serve(mc, args.host, args.port)
    mc.start()
    signal.signal(signal.SIGTERM, _terminate)
    print(f"mission-control: {len(configs)} robot(s), http://{args.host}:{args.port}/api/v1/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        mc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
