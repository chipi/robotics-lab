"""miniview — runs into the lab's data folder, the service for the pages, answers for the agent
(RFC-0009, ADR-0004, ADR-0005). The data folder is MINIVIEW_DATA or --data: there is no default in the code
(the compose file and the Makefile default to /work/robotics-lab/data). The index is MINIVIEW_INDEX (default
/work/robotics-lab/state/miniview/index.sqlite); while a service holds it, the commands read it and write nothing.

    uv run miniview scene apartment --layout ../duck/sim/apartment_layout.json
    uv run miniview import ../duck/runs/explore12 ../duck/runs/phase1-run18 --scene apartment
    uv run miniview import ../duck/runs/explore13 --scene apartment --follow   # a run while it runs
    uv run miniview import --robot nxt ../apps/nxt-web/runs/run-20261114-145402.csv      # an nxt-web recording (ADR-0013)
    uv run miniview repair duck/apartment/explore13   # close a run whose writer died (verdict stopped)
    uv run miniview compact duck/apartment/explore13  # close a finished run whose live file was not compacted
    uv run miniview index                  # rebuild index.sqlite from the run files
    uv run miniview serve                  # http://127.0.0.1:8070/  (the API under /api/v1)
    uv run miniview render-serve           # http://127.0.0.1:8071/  the render service (ADR-0017); serve finds it by MINIVIEW_RENDER

The agent's face (UXS-001 "The commands"): answers from the data, pictures from the real page.

    uv run miniview scenes                              # the scenes and their runs
    uv run miniview runs apartment                      # a scene's runs
    uv run miniview events explore12 [--kinds a,b]      # what happened, when
    uv run miniview state explore12 --at 79.0 [--json]  # belief, truth, distance, depth, semantic map, last event
    uv run miniview objects find-fridge-2 --at 12.0 [--json]  # the semantic map: objects, room, the current sighting (ADR-0019)
    uv run miniview sensor explore12 --at 79.0 [--json]  # the raw 8x8 depth frame at t, and the state it was paired with
    uv run miniview frame explore12 --at 79.0 --view three --hide sensors.depth -o f.png
    uv run miniview film explore12 --at 79.6 --span 1.0 --n 5 -o film.png
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from runfile import keys, mcapio
from miniview import query
from runfile.catalog import Catalog, default_data
from miniview.importer import import_duck
from miniview.scenes import from_mujoco_layout


def _cat(args, owner: bool = False) -> Catalog:
    """The catalog the command works on. While a service holds the index the catalog reads it and writes nothing to it:
    one index, the service's (ADR-0012). `owner`: the command is the one that holds or rebuilds the index."""
    cat = Catalog(args.data)
    if not owner and cat.index.held_elsewhere():
        cat.read_only = True
        print("note: a service holds the index; reading it, writing nothing to it", file=sys.stderr)
    return cat


def cmd_scene(args) -> None:
    scene = from_mujoco_layout(Path(args.layout), args.id, args.name)
    p = _cat(args).put_scene(scene)
    print(f"scene {args.id}: {len(scene['boxes'])} boxes, {len(scene['hazards'])} hazards -> {p}")


def cmd_import(args) -> None:
    data = _cat(args).data
    if args.robot == "nxt":
        from runfile.adapters import nxt

        if args.follow:
            raise SystemExit("--follow is for the duck's log; nxt-web writes its runs live itself (ADR-0013)")
        for f in args.logs:
            nxt.import_csv(Path(f), data, args.scene or nxt.SCENE, tz=args.tz, sprocket=args.sprocket_diameter,
                           track=args.track_width, config_path=Path(args.config) if args.config else None)
    else:
        for log_dir in args.logs:
            import_duck(Path(log_dir), args.scene or "apartment", data, follow=args.follow, idle_s=args.idle)
    if not args.follow:
        _cat(args).scan()


def cmd_repair(args) -> None:
    cat = _cat(args)
    cat.scan_paths()
    key = cat.resolve(args.run)
    if key is None:
        cands = [k for k in cat.paths if k.rsplit("/", 1)[-1] == args.run]
        raise SystemExit(f"no run {args.run!r}" + (f"; which of {', '.join(cands)}?" if cands else ""))
    d = _live_run_dir(cat, key)
    print(f"{key}: closed as stopped -> {mcapio.compact(d, stopped=True)}")


def _live_run_dir(cat: Catalog, key: str) -> Path:
    """The run's folder, once its live file has no writer: not alive here, and not grown lately (a lock from another host
    cannot be checked, so a file that grew in the last STOPPED_AFTER_S seconds is taken as written)."""
    import time

    from runfile.catalog import STOPPED_AFTER_S

    d = keys.run_dir(cat.data, key)
    if not (d / mcapio.LIVE).exists():
        raise SystemExit(f"{key}: no live file, nothing to close")
    if mcapio.writer_alive(d):
        raise SystemExit(f"{key}: its writer is alive ({d / mcapio.LOCK}); not touching it")
    if time.time() - (d / mcapio.LIVE).stat().st_mtime < STOPPED_AFTER_S:
        raise SystemExit(f"{key}: its file grew in the last {STOPPED_AFTER_S:.0f} s; its writer may be alive (on another host?)")
    return d


def cmd_compact(args) -> None:
    cat = _cat(args, owner=True)
    cat.scan_paths()
    key = cat.resolve(args.run)
    if key is None:
        raise SystemExit(f"no run {args.run!r}")
    d = _live_run_dir(cat, key)
    try:
        print(f"{key}: compacted -> {mcapio.compact(d, require_end=True)}")
    except ValueError as e:
        raise SystemExit(str(e)) from None


def cmd_index(args) -> None:
    cat = _cat(args, owner=True)
    pid = cat.index.held_elsewhere()
    if pid:
        raise SystemExit(f"a service holds the index {cat.index.path} (pid {pid}); not rebuilding it under the service")
    cat.index.clear()
    cat.scan()
    idx = cat.scenes_with_runs()
    print(f"index: {len(idx['scenes'])} scenes, {sum(len(s['runs']) for s in idx['scenes'])} runs -> {cat.index.path}")


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
        print(f"{r['key']:<34} {r['kind']:<16} {r['length_s']:>7.1f} s  {r['status']:<8} {r['verdict']:<14} "
              f"{r['events']} events" + (f"  ERROR {r['error']}" if r["error"] else ""))


def cmd_events(args) -> None:
    kinds = set(args.kinds.split(",")) if args.kinds else None
    if args.all:
        cat = _cat(args)
        cat.scan()
        rows = cat.index.events_across(kinds)
        if args.json:
            print(json.dumps([{"run": k, "t": t, "kind": kd, "text": x} for k, t, kd, x in rows], indent=1))
            return
        for k, t, _kd, x in rows:
            print(f"{k:<34} {t:8.2f}  {x}")
        return
    if not args.run:
        raise SystemExit("name a run, or --all for every run")
    run, _ = query.load_run(_cat(args), args.run)
    evs = query.events(run, kinds)
    if args.json:
        print(json.dumps(evs, indent=1))
        return
    for e in evs:
        print(f"{e['t']:8.2f}  {e['text']}")


def cmd_state(args) -> None:
    cat = _cat(args)
    run, frames = query.load_run(cat, args.run)
    st = query.state(run, frames, args.at, query.load_signals(cat, args.run), query.load_semantic(cat, args.run))
    if args.json:
        print(json.dumps(st, indent=1))
        return
    sg = st.get("signals")
    sig_line = ("  signals at " + f"{sg['t']:.2f} s (sample {sg['index'] + 1} of {sg['n']}): "
                + ", ".join(f"{k} {v}" for k, v in sg["values"].items() if v is not None)) if sg else None
    if st["tick"] is None:                                  # a run with signals and no pose
        print(f"{st['run']} at t = {st['t']:.2f} s, scene {st['scene']} (no pose: {run.get('no_pose') or 'not in this run'})")
        print(sig_line or "  no signals yet")
        print(f"  last event {st['last_event']}")
        return
    print(f"{st['run']} at t = {st['t']:.2f} s (tick {st['tick']}), scene {st['scene']}")
    print(f"  belief (world) {st['belief_world']}   truth {st['truth']}   distance {st['belief_truth_distance_m']} m")
    print(f"  belief (map)   {st['belief_map']}   tilt {st['tilt_deg']}   cmd {st['cmd']}")
    d = st["depth"]
    print(f"  depth frame at {d['frame_t']} s: {d['returns']}  (f floor, o obstacle, v overhead, b below the floor)")
    if sig_line:
        print(sig_line)
    sm = st.get("semantic")
    if sm:
        objs = sm["objects"]
        print(f"  objects ({len(objs)}, {sum(o['confirmed'] for o in objs)} confirmed): "
              + (", ".join(f"{o['kind']} {o['id']}{'' if o['confirmed'] else '?'} ({o['x']}, {o['y']})" for o in objs) or "none yet"))
        lk = sm["sighting"]
        print("  sighting: " + (f"at {lk['t']} s saw " + (", ".join(f"{d['kind']} {d['range_m']} m {d['confidence']}" for d in lk["seen"]) or "nothing") if lk else "none current"))
        rm = sm["room"]
        print("  room: " + (f"{rm['name']} {rm['votes']}" if rm else "not told yet"))
    print(f"  last event {st['last_event']}")


def cmd_objects(args) -> None:
    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    sm = query.semantic_at(run, query.load_semantic(cat, args.run), args.at)
    if args.json:
        print(json.dumps(sm, indent=1))
        return
    if sm is None:
        print(f"{run['id']}: no semantic map (no objects, sightings or room events)")
        return
    print(f"{run['id']} at t = {args.at:.2f} s: " + (f"objects as of {sm['objects_t']} s" if sm["objects_t"] is not None else "no objects yet"))
    for o in sm["objects"]:
        print(f"  {o['id']:<16} {o['kind']:<12} ({o['x']}, {o['y']})  {'confirmed' if o['confirmed'] else 'not yet'}  landmark {o['landmark']}  confidence {o['confidence']}")
    rm, lk = sm["room"], sm["sighting"]
    print("  room: " + (f"{rm['name']} {rm['votes']} (told at {rm['t']} s)" if rm else "not told yet"))
    print("  sighting: " + (f"at {lk['t']} s from {lk['pose']}, {lk['hfov_deg']} deg to {lk['range_m']} m, saw "
                        + (", ".join(f"{d['kind']} {d['range_m']} m {d['confidence']}" for d in lk["seen"]) or "nothing") if lk else "none current"))


def _shot(args, t, out) -> dict:
    return {"t": t, "out": out, "view": args.view, "frame": args.frame,
            "hidden": [h for h in (args.hide or "").split(",") if h]}


def cmd_frame(args) -> None:
    from miniview.shots import pictures

    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    out = Path(args.out or f"{args.run.replace('/', '_')}-{args.at:.1f}-{args.view}.png")
    pictures(cat, args.lib, run["scene"], run["key"], [_shot(args, args.at, out)])
    print(out)


def cmd_film(args) -> None:
    from miniview.shots import pictures, sheet

    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    times = [args.at - args.span + args.span * i / max(args.n - 1, 1) for i in range(args.n)]
    out = Path(args.out or f"{args.run.replace('/', '_')}-{args.at:.1f}-film.png")
    with tempfile.TemporaryDirectory() as tmp:
        # The view alone in each tile (#stage: the page's view area, CONTRACT.md), so it reads at sheet size.
        shots = [dict(_shot(args, t, Path(tmp) / f"{i}.png"), crop="#stage") for i, t in enumerate(times)]
        imgs = pictures(cat, args.lib, run["scene"], run["key"], shots)
        sheet(imgs, [f"t = {t:.2f} s" for t in times], out, cols=min(args.n, 3))
    print(out)


VALID_STATUS = (5, 9)      # the depth sensor's "range valid" statuses (ST VL53L5CX)


def cmd_sensor(args) -> None:
    cat = _cat(args)
    run, _ = query.load_run(cat, args.run)
    fr = query.sensor_at(cat.get(args.run).data.raw, args.at)
    if fr is None:
        raise SystemExit(f"{run['key']}: no raw depth frames in this run (the navigator writes them from RFC-0008 step 0; "
                         "an imported ticks.jsonl has none); `miniview state` shows the returns by kind")
    if args.json:
        print(json.dumps(fr, indent=1))
        return
    rows, cols, st = fr["rows"], fr["cols"], fr["status"]
    print(f"{run['key']} at t = {args.at:.2f} s: depth frame {fr['index'] + 1} of {fr['n']}, recorded at t = {fr['t']:.3f} s "
          f"(sensor clock {fr['frame_t_ns']} ns, seq {fr.get('seq', '?')})")
    pair = fr.get("pair_dt_ms")
    print("  paired with the state at " + (f"{fr['state_t_ns']} ns ({pair:+.1f} ms from the frame)" if pair is not None else "none"))
    print(f"  distance_mm, row 0 (top) first; '*' = status not valid ({', '.join(map(str, VALID_STATUS))} are):")
    for r in range(rows):
        print("   " + " ".join(f"{fr['distance_mm'][r * cols + c]:5d}" + ("*" if st[r * cols + c] not in VALID_STATUS else " ")
                                for c in range(cols)))
    print("  status:")
    for r in range(rows):
        print("   " + " ".join(f"{st[r * cols + c]:3d}" for c in range(cols)))


def cmd_serve(args) -> None:
    from miniview.server import make_server

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cat = _cat(args, owner=True)
    httpd = make_server(cat, args.host, args.port)
    print(f"miniview at http://{args.host}:{args.port}/ (API /api/v1), data {cat.data}, index {cat.index.path}", flush=True)
    httpd.serve_forever()


def cmd_video(args) -> None:
    from miniview import video
    if not args.data:
        raise SystemExit("no data folder: MINIVIEW_DATA or --data")
    w, h = (int(v) for v in args.size.lower().split("x"))
    insets = tuple(i.strip() for i in (args.inset or "").split(",") if i.strip())
    print(video.export(Path(args.data), args.run, args.engine, Path(args.out), args.fps, (w, h), args.t_from, args.t_to,
                       insets, args.inset_size, tuple(x.strip() for x in (args.hide or "").split(",") if x.strip()),
                       args.intro or 0.0))


def cmd_render_serve(args) -> None:
    from miniview.video import service

    state = args.state or os.environ.get("MINIVIEW_STATE")
    if not args.data:
        raise SystemExit("no data folder: MINIVIEW_DATA or --data")
    if not state:
        raise SystemExit("no state folder for the videos: MINIVIEW_STATE or --state")
    service.serve(Path(args.data), Path(state), args.host, args.port)


def main() -> None:
    ap =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(default_data() or "") or None, help="the lab's data folder (MINIVIEW_DATA)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scene", help="write a scene from a simulator layout")
    p.add_argument("id")
    p.add_argument("--layout", required=True)
    p.add_argument("--name", default="The simulated apartment")
    p.set_defaults(fn=cmd_scene)
    p = sub.add_parser("import", help="a robot's log into the data folder as MCAP")
    p.add_argument("logs", nargs="+", help="the duck's run folders, or with --robot nxt nxt-web's run-*.csv files")
    p.add_argument("--robot", default="duck", choices=("duck", "nxt"))
    p.add_argument("--scene", help="the run's scene (default: apartment for the duck, unmapped for the NXT)")
    p.add_argument("--follow", action="store_true", help="follow a log still being written (a live run)")
    p.add_argument("--idle", type=float, default=60.0, help="with --follow: end after this many quiet seconds")
    p.add_argument("--tz", help="--robot nxt: the IANA time zone of the machine that recorded (the file name's time is local to it); default: this machine's")
    p.add_argument("--sprocket-diameter", type=float, help="--robot nxt: the drive sprockets' diameter in metres (odometry); default: the config's odom_sprocket_diameter_m")
    p.add_argument("--track-width", type=float, help="--robot nxt: the effective track width in metres (odometry); default: the config's odom_track_width_m")
    p.add_argument("--config", help="--robot nxt: nxt-web's config.json (default: the one beside the recording's folder); the old MCAP's own config wins")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("repair", help="close a run whose writer died: compact it, verdict stopped")
    p.add_argument("run", help="the run's key (robot/scene/run), or its name when only one run has it")
    p.set_defaults(fn=cmd_repair)
    p = sub.add_parser("compact", help="close a finished run whose live file was not compacted (it has its end record)")
    p.add_argument("run", help="the run's key, or its name when only one run has it")
    p.set_defaults(fn=cmd_compact)
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
    p.add_argument("run", nargs="?")
    p.add_argument("--all", action="store_true", help="every run (from the index), not one")
    p.add_argument("--kinds", "--kind", dest="kinds", help="comma-separated event kinds")
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
    p = sub.add_parser("objects", help="the semantic map at a moment: the objects, the room, the camera's current sighting (ADR-0019)")
    p.add_argument("run")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_objects)
    p = sub.add_parser("sensor", help="the raw depth frame at a moment, and the state it was paired with")
    p.add_argument("run")
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sensor)
    p = sub.add_parser("serve", help="the pages and the API (ADR-0005)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8070)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("video", help="a run rendered as a video by an engine, with the robot's model (ADR-0017)")
    p.add_argument("run")
    p.add_argument("--engine", default="mujoco")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--size", default="1280x720", help="WIDTHxHEIGHT")
    p.add_argument("--from", dest="t_from", type=float)
    p.add_argument("--to", dest="t_to", type=float)
    p.add_argument("--inset", help="small views in the bottom corners: eye (the robot's camera), top (the room from above), hud (the status lines), comma-separated")
    p.add_argument("--inset-size", type=float, default=0.28, help="an inset's side as a share of the video's height")
    p.add_argument("--intro", type=float, help="instead of the run: SECONDS of the camera circling the robot as it stands at "
                                                "the start (an opening to join in front of the run's video)")
    p.add_argument("--hide", help="layers to leave out, comma-separated: truth (the real room's faint outline on the map), map (the "
                                  "discovered map), objects (their dots on the map), labels (their names in the view), trail, wedge")
    p.set_defaults(fn=cmd_video)
    p = sub.add_parser("render-serve", help="the render service: runs to videos for the pages, one job at a time (ADR-0017)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8071)
    p.add_argument("--state", help="where the videos go, in videos/ (MINIVIEW_STATE)")
    p.set_defaults(fn=cmd_render_serve)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
