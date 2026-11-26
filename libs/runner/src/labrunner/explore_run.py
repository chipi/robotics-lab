"""lab-explore: the apartment's exploration, the robot's navigator as a payload behind this runner (RFC-0021 step 6,
RFC-0022). The navigator gets the robot's sockets and the camera's; this process has the host file and the truth, serves
the camera, keeps the drop guard (the scene's drops, runfile.scenefile) and writes the official run with the truth put in.

    uv run lab-explore --minutes 20 --out runs/explore13 --miniview-data /work/robotics-lab/data   # the run is the record
    uv run lab-explore --find fridge --site home --minutes 6 ...                                     # objects, a site

Reset the simulator first (it starts where the robot stands). The format 2 run (Observatory, ADR-0014) is the record."""

import argparse
import json
import sys
import threading
from pathlib import Path

from labrunner import robots
from labrunner.cli import add_args
from labrunner.guard import GUARD_M, drop_distance
from labrunner.remote import add_controller_args, add_impairment_arg, controller_setting
from runfile import scenefile
from runfile.catalog import default_data
from worldmodel.objects import load_kinds


def main() -> None:
    """The exploration as a runner (RFC-0021 step 6): the navigator is a payload process (the robot's) given the
    robot's sockets and the camera's; this process has the host file and the truth, serves the camera, keeps the truth
    guard, and writes the official run with the truth put in."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=Path("runs/explore"))
    ap.add_argument("--host", help="the host file (RFC-0021; default $ROBOTICS_LAB_HOST, else ~/.config/robotics-lab/host.json)")
    ap.add_argument("--find", metavar="KIND", help="explore until an object of this kind is found, then go to it "
                    "(RFC-0016; kinds: libs/worldmodel/src/worldmodel/kinds.json), e.g. fridge")
    ap.add_argument("--inventory", action="store_true", help="the goal is to find all objects: explore, then say what "
                    "is where (inventory.json is written whenever the objects are on)")
    ap.add_argument("--no-objects", action="store_true", help="no simulated camera and no semantic map")
    ap.add_argument("--site", help="a site's id: start from its map, save it back at the end (duck-site create first)")
    ap.add_argument("--sites", type=Path, help="the sites' folder (default: the navigator's own)")
    ap.add_argument("--object-costs", action="store_true", help="confirmed objects join the cost map (off by default)")
    ap.add_argument("--no-relocalise", action="store_true", help="landmarks do not correct the belief (the run before relocalisation)")
    ap.add_argument("--fix-fault", help="T,DX,DY: from T s on, mapd's pose is shifted by (DX, DY) m, a persistent jump like explore-b10a-r1 (a test)")
    ap.add_argument("--frame-fault", help="T,DX,DY: as --fix-fault, and mapd's grid shifts with its pose (its frame jumped as a "
                    "whole: pose and grid come from one graph, mapping-design §5) (a test)")
    ap.add_argument("--no-frames", action="store_true", help="the grid stays in mapd's frame and the memory does not move with the "
                    "belief's (the run before RFC-0016 §6's frame fix; a test)")
    ap.add_argument("--no-fix-gate", action="store_true", help="every mapd fix is taken (the run before the fix gate)")
    ap.add_argument("--payload", help="another navigator's command, keeping the payload contract (default: ours)")
    add_impairment_arg(ap)
    add_controller_args(ap)
    add_args(ap)
    args = ap.parse_args()
    robots.select(args.robot)
    if args.find and args.find not in load_kinds():
        ap.error(f"no kind {args.find!r}; the kinds: {', '.join(sorted(load_kinds()))}")
    if (args.find or args.inventory) and args.no_objects:
        ap.error("--find and --inventory need the objects (drop --no-objects)")
    if args.fix_fault and args.frame_fault:
        ap.error("--fix-fault and --frame-fault are one fault: give one")
    data = args.miniview_data or default_data()
    if data is None:
        ap.error("the run is the record: give --miniview-data (or OBSERVATORY_DATA)")
    try:
        scene = scenefile.load(args.scene)
    except scenefile.SceneError as e:
        ap.error(f"the drop guard needs the scene's description: {e}")
    # the runner's, not the explorer's: the explorer also runs inside a payload, which has no host and no truth
    import shlex
    import simhost
    from labrunner.camera import CameraServer
    from labrunner.remote import Remote
    from runfile import keys
    from runfile.truthcopy import TruthLog
    from simhost.truth import Sampler

    host = simhost.load(args.host)
    if host.truth_port is None:
        sys.exit(f"lab-explore: {host.source} has no truth (truth_port is null): the runner needs it for the guard and the run")
    if args.depth_impairment is not None and robots.variant(host) != "sim":
        sys.exit(f"lab-explore: --depth-impairment is the simulator's: this host runs the {robots.variant(host)!r} robot, whose frames are not impaired")
    local_controller = controller_setting(args, ap)
    if local_controller and robots.variant(host) != "sim":
        sys.exit(f"lab-explore: --local-controller learned is the simulator's for now: this host runs the {robots.variant(host)!r} robot (RFC-0025 R8)")
    args.out.mkdir(parents=True, exist_ok=True)
    name = args.run or args.out.name
    key = keys.make_key(robots.get().NAME, args.scene, name)
    if keys.run_dir(Path(data), key).exists():
        sys.exit(f"lab-explore: the run {key} exists in {data}: give another --run or --out")
    extra = (["--sites", str(args.sites)] if args.sites else []) + (["--no-fix-gate"] if args.no_fix_gate else []) + \
        (["--no-frames"] if args.no_frames else []) + (["--fix-fault", args.fix_fault] if args.fix_fault else []) + \
        (["--frame-fault", args.frame_fault] if args.frame_fault else [])
    truth_log = TruthLog(args.out / "truth.jsonl")
    camera = sampler = nav = None
    route = {"checks": 0, "max": None}
    try:
        if not args.no_objects:
            camera = CameraServer(host, host.sockets["camera"]).start()
        sampler = Sampler(host).start()
        nav = Remote(host, args.out, args.scene, name, Path(data), key, truth_log, run={"kind": "exploration"}, scene_file=scene.path,
                     payload=shlex.split(args.payload) if args.payload else None, camera=camera.path if camera else None,
                     extra=extra, depth_impairment=args.depth_impairment, local_controller=local_controller)
        print(f"Observatory run {key} -> {keys.run_dir(Path(data), key)}", file=sys.stderr)
        guarded = threading.Event()

        def watch(s) -> None:
            truth_log.add(s.wall_ns, s.pose, s.z, s.quat)
            if sampler.samples % 40 == 1:
                n = nav.truth_connections(host.truth_port)
                if n is not None:
                    route["checks"] += 1
                    route["max"] = max(route["max"] or 0, n)
            # the test harness's kill switch (GUARD_M, above): the runner's, by the truth; the brain never reads it
            d = drop_distance(scene, s.pose)
            if not guarded.is_set() and (d < GUARD_M or s.z < 0.06):
                guarded.set()
                why = f"truth guard: {d:.2f} m from a drop, trunk {s.z:.3f} m"
                nav.break_goal("truth_guard", why)
                nav.record(event="truth_guard", why=why)
        sampler.on_sample = watch
        pose = nav.localise()
        (args.out / "start.json").write_text(json.dumps({"map": list(pose) if pose else None, "truth": list(sampler.latest.pose),
                                                          "scale": nav.scale}))
        if pose is None:
            sys.exit("lab-explore: no pose on the map after the survey")
        opts = {} if args.no_objects else {"objects": True, "find": args.find, "site": args.site,
                                           "object_costs": args.object_costs, "relocalise": not args.no_relocalise}
        result = nav.explore(args.minutes, **opts)
        print(json.dumps(result))
        inv = result.get("inventory")
        if args.inventory and inv:
            print(f"INVENTORY {inv['objects']} objects: " + "; ".join(f"{room}: {', '.join(kinds)}" for room, kinds in inv["rooms"].items()))
        if result.get("site"):
            print(f"SITE {result['site']['id']}: {result['site']['objects']} objects saved to {result['site']['folder']}")
    finally:
        if sampler is not None:
            sampler.stop()
        if nav is not None:
            nav.close()
            print(f"the official run's truth copy: {nav.copy.stats()}", file=sys.stderr)
        if camera is not None:
            print(f"camera: {camera.looks} looks served", file=sys.stderr)
            camera.stop()
        truth_log.close()
        print(f"the payload's connections to the truth's port: {route}", file=sys.stderr)


if __name__ == "__main__":
    main()
