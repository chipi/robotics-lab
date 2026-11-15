"""miniview — prepare runs and scenes for the pages, index them, serve them (RFC-0009 v0.1).

    uv run miniview prepare ../duck/runs/explore12 ../duck/runs/phase1-run18
    uv run miniview scene apartment --layout ../duck/sim/apartment_layout.json
    uv run miniview index
    uv run miniview serve                 # http://127.0.0.1:8095/web/three/  and  /web/deck/

The agent's face (UXS-001 "The commands"): answers from the data, pictures from the real page.

    uv run miniview scenes                              # the scenes and their runs
    uv run miniview runs apartment                      # a scene's runs
    uv run miniview events explore12 [--kinds a,b]      # what happened, when
    uv run miniview state explore12 --at 79.0 [--json]  # belief, truth, distance, depth, last event
    uv run miniview frame explore12 --at 79.0 --view three --hide sensors.depth -o f.png
    uv run miniview film explore12 --at 79.6 --span 1.0 --n 5 -o film.png
"""

import argparse
import functools
import http.server
import json
from pathlib import Path

from miniview import query
from miniview.adapters import duck
from miniview.scenes import from_mujoco_layout

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "site" / "data"


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


def cmd_prepare(args) -> None:
    for run_dir in args.runs:
        run, frames = duck.prepare(Path(run_dir), args.scene)
        out = DATA / "runs" / run["id"]
        _write(out / "run.json", run)
        _write(out / "frames.json", frames)
        print(f"{run['id']}: {run['ticks']} ticks, {len(frames['plans'])} plans, {len(frames['worlds'])} worlds, "
              f"{len(run['events'])} events, {len(run['epochs'])} epochs -> {out}")


def cmd_scene(args) -> None:
    scene = from_mujoco_layout(Path(args.layout), args.id, args.name)
    _write(DATA / "scenes" / f"{args.id}.json", scene)
    print(f"scene {args.id}: {len(scene['boxes'])} boxes, {len(scene['hazards'])} hazards")


def cmd_index(args) -> None:
    scenes = {}
    for p in sorted((DATA / "scenes").glob("*.json")):
        s = json.loads(p.read_text())
        scenes[s["id"]] = {"id": s["id"], "name": s.get("name", s["id"]), "kind": s.get("kind", ""), "runs": []}
    for p in sorted((DATA / "runs").glob("*/run.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        r = json.loads(p.read_text())
        entry = {"id": r["id"], "robot": r["robot"]["name"], "kind": r.get("kind", ""),
                 "length_s": round(r["t1"] - r["t0"], 1), "verdict": r.get("verdict", ""), "events": len(r["events"])}
        scenes.setdefault(r["scene"], {"id": r["scene"], "name": r["scene"], "kind": "", "runs": []})["runs"].append(entry)
    _write(DATA / "index.json", {"format": 1, "scenes": list(scenes.values())})
    print(f"index: {len(scenes)} scenes, {sum(len(s['runs']) for s in scenes.values())} runs")


def _index() -> dict:
    p = DATA / "index.json"
    if not p.exists():
        raise SystemExit("no index yet: miniview index")
    return json.loads(p.read_text())


def cmd_scenes(args) -> None:
    idx = _index()
    if args.json:
        print(json.dumps(idx["scenes"], indent=1))
        return
    for sc in idx["scenes"]:
        print(f"{sc['id']:<14} {sc.get('kind', ''):<10} {len(sc['runs'])} runs  {sc.get('name', '')}")


def cmd_runs(args) -> None:
    sc = next((s for s in _index()["scenes"] if s["id"] == args.scene), None)
    if sc is None:
        raise SystemExit(f"no scene {args.scene!r}")
    if args.json:
        print(json.dumps(sc["runs"], indent=1))
        return
    for r in sc["runs"]:
        print(f"{r['id']:<16} {r['kind']:<18} {r['length_s']:>7.1f} s  {r['verdict']:<16} {r['events']} events")


def cmd_events(args) -> None:
    run, _ = query.load_run(DATA, args.run)
    kinds = set(args.kinds.split(",")) if args.kinds else None
    evs = query.events(run, kinds)
    if args.json:
        print(json.dumps(evs, indent=1))
        return
    for e in evs:
        print(f"{e['t']:8.2f}  {e['text']}")


def cmd_state(args) -> None:
    run, frames = query.load_run(DATA, args.run)
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

    run, _ = query.load_run(DATA, args.run)
    out = Path(args.out or f"{args.run}-{args.at:.1f}-{args.view}.png")
    pictures(ROOT, args.lib, run["scene"], args.run, [_shot(args, args.at, out)])
    print(out)


def cmd_film(args) -> None:
    from miniview.shots import pictures, sheet
    import tempfile

    run, _ = query.load_run(DATA, args.run)
    times = [args.at - args.span + args.span * i / max(args.n - 1, 1) for i in range(args.n)]
    out = Path(args.out or f"{args.run}-{args.at:.1f}-film.png")
    with tempfile.TemporaryDirectory() as tmp:
        # The view alone in each tile (#stage: the page's view area, CONTRACT.md), so it reads at sheet size.
        shots = [dict(_shot(args, t, Path(tmp) / f"{i}.png"), crop="#stage") for i, t in enumerate(times)]
        imgs = pictures(ROOT, args.lib, run["scene"], args.run, shots)
        sheet(imgs, [f"t = {t:.2f} s" for t in times], out, cols=min(args.n, 3))
    print(out)


def cmd_sensor(args) -> None:
    raise SystemExit("the raw depth frame is not in these runs yet: the navigator logs it from "
                     "RFC-0008 step 1 (replay logging); `miniview state` shows the returns by kind")


def cmd_serve(args) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"serving {ROOT} at http://127.0.0.1:{args.port}/web/three/ and /web/deck/")
        httpd.serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="prepare runs for the pages")
    p.add_argument("runs", nargs="+")
    p.add_argument("--scene", default="apartment")
    p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("scene", help="write a scene from a simulator layout")
    p.add_argument("id")
    p.add_argument("--layout", required=True)
    p.add_argument("--name", default="The simulated apartment")
    p.set_defaults(fn=cmd_scene)
    p = sub.add_parser("index", help="list scenes and their runs for the pages")
    p.set_defaults(fn=cmd_index)
    for name, fn, hlp in (("scenes", cmd_scenes, "the scenes and their runs"),):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
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
    p = sub.add_parser("serve", help="serve the pages and the data")
    p.add_argument("--port", type=int, default=8095)
    p.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
