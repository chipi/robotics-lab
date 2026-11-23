"""simhost: this machine's host file and the simulator's reset (RFC-0021).

    simhost show                                   # the host file read, and what it resolves to
    simhost init --microduck /work/pollen/microduck --microduck-rl /work/pollen/microduck_rl
    simhost reset [SCENE]                          # the duck at its dock, mapd fresh (~40 s)
    simhost down

Every command takes --host FILE (else $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)."""

import argparse
import json
import sys

from simhost import host as H
from simhost import kinds as K
from simhost import simulator as R


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="simhost", description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", help="the host file (default: $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the host file as read, with the sockets it names")
    i = sub.add_parser("init", help="write this machine's host file")
    i.add_argument("--microduck", required=True, help="Pollen's microduck checkout")
    i.add_argument("--microduck-rl", required=True, help="Pollen's microduck_rl checkout")
    i.add_argument("--robot", default="duck-a")
    i.add_argument("--state", default="~/.cache/duck-sim", help="duck-sim's own folder (its sockets and pidfiles)")
    i.add_argument("--truth-port", type=int, default=7801, help="the body server's port; 0 for a host with no truth")
    i.add_argument("--cargo-bin", default="~/.cargo/bin")
    i.add_argument("--force", action="store_true", help="replace an existing host file")
    r = sub.add_parser("reset", help="the duck at its dock with an empty map")
    r.add_argument("scene", nargs="?", help=f"the kind's own scene (the duck's default: {R.DEFAULT_SCENE}; the NXT's: a scene.json, default the host's)")
    d = sub.add_parser("down", help="the simulator and mapd stopped")
    d.add_argument("scene", nargs="?", help="as for reset")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "init":
            out = H.where(a.host)
            if out.exists() and not a.force:
                print(f"{out} exists (--force replaces it):\n{out.read_text()}", file=sys.stderr)
                return 1
            d = {"host": H.VERSION, "kind": "pollen-duck-sim", "robot": a.robot,
                 "pollen": {"microduck": a.microduck, "microduck_rl": a.microduck_rl}, "state": a.state,
                 "truth_port": a.truth_port or None, "cargo_bin": a.cargo_bin}
            H.parse(d, out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(d, indent=2) + "\n")
            print(f"wrote {out}")
            return 0
        host = H.load(a.host)
        if a.cmd == "show":
            print(f"# {host.source}")
            print(json.dumps(host.as_json(), indent=2))
        elif a.cmd == "reset":
            K.reset(host, *([a.scene] if a.scene else []))
            print("standing, mapd listening")
        elif a.cmd == "down":
            K.down(host, *([a.scene] if a.scene else []))
            print("down")
        return 0
    except H.HostError as e:
        print(f"simhost: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
