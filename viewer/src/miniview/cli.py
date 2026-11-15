"""miniview — runs into the lab's data folder, the service for the pages, answers for the agent
(RFC-0009, ADR-0004, ADR-0005). The data folder is MINIVIEW_DATA or --data (default
/work/robotics-lab/data).

    uv run miniview scene apartment --layout ../duck/sim/apartment_layout.json
    uv run miniview import ../duck/runs/explore12 ../duck/runs/phase1-run18 --scene apartment
    uv run miniview import ../duck/runs/explore13 --scene apartment --follow   # a run while it runs
    uv run miniview index                  # rebuild index.sqlite from the run files
    uv run miniview serve                  # http://127.0.0.1:8070/  (the API under /api/v1)

The agent's face (UXS-001 "The commands"): answers from the data, pictures from the real page.

    uv run miniview scenes                              # the scenes and their runs
    uv run miniview runs apartment                      # a scene's runs
    uv run miniview events explore12 [--kinds a,b]      # what happened, when
    uv run miniview state explore12 --at 79.0 [--json]  # belief, truth, distance, depth, last event
    uv run miniview frame explore12 --at 79.0 --view three --hide sensors.depth -o f.png
    uv run miniview film explore12 --at 79.6 --span 1.0 --n 5 -o film.png
"""

import argparse
import json
import tempfile
from pathlib import Path

from miniview import query
from miniview.catalog import DEFAULT_DATA, Catalog
from miniview.importer import import_duck
from miniview.scenes import from_mujoco_layout


def _cat(args) -> Catalog:
    return Catalog(Path(args.data))


def cmd_scene(args) -> None:
    scene = from_mujoco_layout(Path(args.layout), args.id, args.name)
    p = _cat(args).put_scene(scene)
    print(f"scene {args.id}: {len(scene['boxes'])} boxes, {len(scene['hazards'])} hazards -> {p}")


def cmd_import(args) -> None:
    for log_dir in args.logs:
        import_duck(Path(log_dir), args.scene, Path(args.data), follow=args.follow, idle_s=args.idle)
    if not args.follow:
        _cat(args).scan()


def cmd_index(args) -> None:
    cat = _cat(args)
    for table in ("runs", "streams", "epochs", "events", "ticks"):
        cat.db.execute(f"delete from {table}")
    cat.db.commit()
    cat.scan()
    idx = cat.scenes_with_runs()
    print(f"index: {len(idx['scenes'])} scenes, {sum(len(s['runs']) for s in idx['scenes'])} runs -> "
          f"{cat.data / 'index.sqlite'}")


def cmd_scenes(args) -> None:
    cat = _cat(args)
    cat.scan()
    idx = cat.scenes_with_runs()
    if args.json:
        print(json.dumps(idx["scenes"], indent=1))
        return
    for sc in idx["scenes"]:
        print(f"{sc['id']:<14} {sc.get('kind', ''):<10} {len(sc['runs'])} runs  {sc.get('name', '')}")


def cmd_runs(args) -> None:
    cat = _cat(args)
    cat.scan()
    sc = next((s for s in cat.scenes_with_runs()["scenes"] if s["id"] == args.scene), None)
    if sc is None:
        raise SystemExit(f"no scene {args.scene!r}")
    if args.json:
        print(json.dumps(sc["runs"], indent=1))
        return
    for r in sc["runs"]:
        print(f"{r['id']:<16} {r['kind']:<18} {r['length_s']:>7.1f} s  {r['status']:<8} {r['verdict']:<16} "
              f"{r['events']} events")


def cmd_events(args) -> None:
    run, _ = query.load_run(_cat(args), args.run)
    evs = query.events(run, set(args.kinds.split(",")) if args.kinds else None)
    if args.json:
        print(json.dumps(evs, indent=1))
        return
    for e in evs:
        print(f"{e['t']:8.2f}  {e['text']}")


def cmd_state(args) -> None:
    run, frames = query.load_run(_cat(args), args.run)
    st = query.state(run, frames, args.at)
    if args.json:
        print(json.dumps(st, indent=1))
        return
    print(f"{st['run']} at t = {st['t']:.2f} s (tick {st['tick']}), scene {st['scene']}")
    print(f"  belief (world) {st['belief_world']}   truth {st['truth']}   distance {st['belief_truth_distance_m']} m")
    print(f"  belief (map)   {st['belief_map']}   tilt {st['tilt_deg']}   cmd {st['cmd']}")
    d = st["depth"]
    print(f"  depth frame at {d['frame_t']} s: {d['returns']}  (f floor, o obstacle, v overhead, b below the floor)")
    print(f"  last event {st['last_event']}")


def _shot(args, t, out) -> dict:
    return {"t": t, "out": out, "view": args.view, "frame": args.frame,
            "hidden": [h for h in (args.hide or "").split(",") if h]}


def cmd_frame(args) -> None:
    from miniview.shots import pictures

    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    out = Path(args.out or f"{args.run}-{args.at:.1f}-{args.view}.png")
    pictures(cat, args.lib, run["scene"], args.run, [_shot(args, args.at, out)])
    print(out)


def cmd_film(args) -> None:
    from miniview.shots import pictures, sheet

    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    times = [args.at - args.span + args.span * i / max(args.n - 1, 1) for i in range(args.n)]
    out = Path(args.out or f"{args.run}-{args.at:.1f}-film.png")
    with tempfile.TemporaryDirectory() as tmp:
        # The view alone in each tile (#stage: the page's view area, CONTRACT.md), so it reads at sheet size.
        shots = [dict(_shot(args, t, Path(tmp) / f"{i}.png"), crop="#stage") for i, t in enumerate(times)]
        imgs = pictures(cat, args.lib, run["scene"], args.run, shots)
        sheet(imgs, [f"t = {t:.2f} s" for t in times], out, cols=min(args.n, 3))
    print(out)


def cmd_sensor(args) -> None:
    raise SystemExit("the raw depth frame is not in these runs yet: the navigator logs it from "
                     "RFC-0008 step 1 (replay logging); `miniview state` shows the returns by kind")


def cmd_serve(args) -> None:
    from miniview.server import make_server

    httpd = make_server(_cat(args), args.host, args.port)
    print(f"miniview at http://{args.host}:{args.port}/ (API /api/v1), data {args.data}", flush=True)
    httpd.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="the lab's data folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scene", help="write a scene from a simulator layout")
    p.add_argument("id")
    p.add_argument("--layout", required=True)
    p.add_argument("--name", default="The simulated apartment")
    p.set_defaults(fn=cmd_scene)
    p = sub.add_parser("import", help="a robot's log into the data folder as MCAP")
    p.add_argument("logs", nargs="+")
    p.add_argument("--scene", default="apartment")
    p.add_argument("--follow", action="store_true", help="follow a log still being written (a live run)")
    p.add_argument("--idle", type=float, default=60.0, help="with --follow: end after this many quiet seconds")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("index", help="rebuild index.sqlite from the run files")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("scenes", help="the scenes and their runs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scenes)
    p = sub.add_parser("runs", help="a scene's runs")
    p.add_argument("scene")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_runs)
    p = sub.add_parser("events", help="what happened in a run, when")
    p.add_argument("run")
    p.add_argument("--kinds", help="comma-separated event kinds")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_events)
    p = sub.add_parser("state", help="the state of a run at a moment")
    p.add_argument("run")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_state)
    for name, fn, hlp in (("frame", cmd_frame, "a picture of a moment, from the page"),
                          ("film", cmd_film, "a moment with the frames before it, on one sheet")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("run")
        p.add_argument("--at", type=float, required=True)
        p.add_argument("--view", default="top", choices=("top", "front", "back", "left", "right", "three", "3d"))
        p.add_argument("--frame", default="world", choices=("world", "map"))
        p.add_argument("--hide", help="comma-separated stream ids to hide")
        p.add_argument("--lib", default="three", choices=("three", "deck"))
        p.add_argument("-o", "--out")
        if name == "film":
            p.add_argument("--span", type=float, default=2.0)
            p.add_argument("--n", type=int, default=5)
        p.set_defaults(fn=fn)
    p = sub.add_parser("sensor", help="the raw depth frame at a moment (not yet in the runs)")
    p.add_argument("run")
    p.add_argument("--at", type=float, required=True)
    p.set_defaults(fn=cmd_sensor)
    p = sub.add_parser("serve", help="the pages and the API (ADR-0005)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8070)
    p.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
