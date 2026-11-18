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
    args = p.parse_args(argv)

    if not args.robots.is_dir():
        print(f"mission-control: no robots folder {args.robots}", file=sys.stderr)
        return 2
    try:
        configs = load_robot_files(args.robots)
    except ConfigError as exc:
        print(f"mission-control: {exc}", file=sys.stderr)
        return 2
    mc = MissionControl(configs, state_dir=args.state)
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
