"""lab-go: one goal, the robot's navigator as a payload behind this runner (RFC-0021 step 6, RFC-0022).

    uv run lab-go 1.5 0.5 --out runs/go1 --miniview-data /work/robotics-lab/data     # a goal in the navigator's map
    uv run lab-go 1.5 0.5 ... --robot-socket GATE.sock --client me                    # through a gate (lab-gate)

The format 2 run (Observatory, ADR-0014) is the record, with the truth put in by this runner."""

import argparse
import json
import sys
import time
from pathlib import Path

from labrunner import robots
from labrunner.cli import add_args
from runfile.catalog import default_data


def main() -> None:
    """lab-go as a runner (RFC-0021 step 6): the navigator is a payload process given only the robot's sockets; this
    process has the host file and the truth, and writes the official run with the truth put in."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("x", type=float)
    ap.add_argument("y", type=float)
    ap.add_argument("--out", type=Path, help="the navigator's own files (default runs/<the run's name>)")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    ap.add_argument("--robot-socket", type=Path, help="the robot's socket: robotd's own (the host's, the default) or a gate's (lab-gate)")
    ap.add_argument("--client", help="the name to speak to a gate as (hello, then gate.acquire): needed with a gate's socket")
    add_args(ap)
    args = ap.parse_args()
    robots.select(args.robot)
    data = args.miniview_data or default_data()
    if data is None:
        ap.error("the run is the record: give --miniview-data (or OBSERVATORY_DATA)")
    # the runner's side, imported here: the navigator's module is also the payload's, which has no host and no truth
    import simhost
    from labrunner.remote import PayloadError, Remote
    from runfile import keys
    from runfile.truthcopy import TruthLog
    from simhost.truth import Sampler

    host = simhost.load(args.host)
    if host.truth_port is None:
        sys.exit(f"lab-go: {host.source} has no truth (truth_port is null): the runner needs it for the run")
    name = args.run or time.strftime("go-%Y%m%d-%H%M%S")
    out = args.out or Path("runs") / name
    out.mkdir(parents=True, exist_ok=True)
    key = keys.make_key(robots.get().NAME, args.scene, name)
    if keys.run_dir(Path(data), key).exists():
        sys.exit(f"lab-go: the run {key} exists in {data}: give another --run")
    truth_log = TruthLog(out / "truth.jsonl")
    sampler = nav = None
    code = 0
    try:
        sampler = Sampler(host, on_sample=lambda s: truth_log.add(s.wall_ns, s.pose, s.z, s.quat)).start()
        try:
            nav = Remote(host, out, args.scene, name, Path(data), key, truth_log, run={"kind": "go-to"},
                         robot=args.robot_socket, client=args.client)
        except PayloadError as exc:
            print(json.dumps({"status": "refused", "why": str(exc)}))
            code = 3
            return
        print(f"Observatory run {key} -> {keys.run_dir(Path(data), key)}", file=sys.stderr)
        result = nav.go_to((args.x, args.y), args.timeout)
        print(json.dumps(result))
        if "LeaseLost" in str(result.get("why") or ""):
            code = 4
    finally:
        if sampler is not None:
            sampler.stop()
        if nav is not None:
            nav.close()
            print(f"the official run's truth copy: {nav.copy.stats()}", file=sys.stderr)
        truth_log.close()
        if code:
            sys.exit(code)


if __name__ == "__main__":
    main()
