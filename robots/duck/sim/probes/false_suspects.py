"""Where false suspected drops come from. The run's forward-sensor frames replayed through side_drops.SuspectMemory (as
the navigator keeps it, without the glances' clearing); every suspected cell put in the world through the newest epoch
and judged against the scene: inside a drop (true) or not (false). For the false ones: the distance to the nearest wall
or box, the height of the below-floor returns that made them, how far they were from the sensor, and the belief's error
at the time (the truth is in each frame's paired tick).

    uv run python sim/probes/false_suspects.py /work/robotics-lab/data ch10 ch1 [--since run-20261117-07]
"""

import collections
import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab.nav.side_drops import SuspectMemory, cell_of
from duck_lab.profile import load as load_profile

_SD = load_profile("sim").sensors.tof8x8.side_drops

sys.path.insert(0, str(Path(__file__).resolve().parent))
from room_vs_truth import box_distance  # noqa: E402


def rects(scene):
    """The scene's drops as boxes for box_distance (below_seen.rects; that module runs on import)."""
    return [{"cx": (h["x0"] + h["x1"]) / 2, "cy": (h["y0"] + h["y1"]) / 2, "hx": (h["x1"] - h["x0"]) / 2,
             "hy": (h["y1"] - h["y0"]) / 2, "yaw": h["yaw"]} for h in scene.get("hazards") or []]


def main() -> None:
    data, args = Path(sys.argv[1]), sys.argv[2:]
    since = ""
    if "--since" in args:
        i = args.index("--since")
        since, args = args[i + 1], args[:i] + args[i + 2:]
    for prefix in args:
        n_true, false = 0, []
        for run_dir in sorted((data / "runs" / "duck").glob(f"{prefix}-s*/run-*")):
            if run_dir.name < since:
                continue
            scene = json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text())
            hz = rects(scene)
            walls = [b for b in scene.get("boxes", []) if b.get("z1", 1) > 0.02]
            mem, epoch, err, why = SuspectMemory(_SD.suspect_frames, _SD.suspect_ratio, _SD.clear_m), None, 0.0, collections.defaultdict(list)
            try:
                recs = list(Follower(run_dir, keep_raw=True).poll())
            except Exception:  # noqa: BLE001 - an unreadable recording is skipped, and said
                print(f"unreadable: {run_dir}")
                continue
            for t, k, p in recs:
                if k == "epoch":
                    epoch = p["map_to_world"]
                elif k == "tick" and epoch and p.get("belief") and p.get("truth"):
                    bx, by = p["belief"][:2]
                    c, s = math.cos(epoch[2]), math.sin(epoch[2])
                    err = math.dist((epoch[0] + c * bx - s * by, epoch[1] + s * bx + c * by), p["truth"][:2])
                elif k == "depth_frame":
                    der = p.get("derived") or {}
                    pts = [(q[0], q[1], {"b": "below", "f": "floor"}[q[3]]) for q in der.get("points") or []
                           if q[3] in "bf"]
                    pose = p.get("pose")
                    for q in der.get("points") or []:
                        if q[3] == "b" and pose:
                            why[cell_of(q[0], q[1])].append((q[2], math.dist(q[:2], pose[:2]), err))
                    mem.add_frame(pts)
            if not epoch:
                continue
            cs, sn = math.cos(epoch[2]), math.sin(epoch[2])
            for c in mem.suspected:
                x, y = c[0] * 0.05, c[1] * 0.05
                wx, wy = epoch[0] + cs * x - sn * y, epoch[1] + sn * x + cs * y
                inside = min((box_distance(wx, wy, h) for h in hz), default=math.inf)
                if inside < 0.05:
                    n_true += 1
                    continue
                wall = min((box_distance(wx, wy, b) for b in walls), default=math.inf)
                ev = why.get(c) or [(float("nan"), float("nan"), float("nan"))]
                false.append({"run": f"{run_dir.parent.name}/{run_dir.name}", "cell": (round(x, 2), round(y, 2)),
                              "drop_m": inside, "wall_m": wall,
                              "z_m": sorted(e[0] for e in ev)[len(ev) // 2], "range_m": sorted(e[1] for e in ev)[len(ev) // 2],
                              "belief_err_m": max(e[2] for e in ev), "returns": len(ev)})
        print(f"== {prefix}: suspected cells inside a drop {n_true}, outside {len(false)}")
        if false:
            walls_ = sorted(f["wall_m"] for f in false)
            print(f"   false ones: wall distance p50 {walls_[len(walls_) // 2]:.3f} m, within 0.3 m of a wall "
                  f"{sum(1 for w in walls_ if w <= 0.3)} of {len(walls_)}; "
                  f"belief error at the time p50 {sorted(f['belief_err_m'] for f in false)[len(false) // 2]:.3f} m")
            for title, key in (("nearest a wall", "wall_m"), ("farthest from a drop", "drop_m")):
                print(f"   {title}:")
                for f in sorted(false, key=lambda f: f[key], reverse=key == "drop_m")[:6]:
                    print(f"   {f['run']} {f['cell']}: {f['drop_m']:.2f} m from a drop, {f['wall_m']:.2f} m from a wall, "
                          f"below returns {f['returns']} at z {f['z_m']:+.3f} m, range {f['range_m']:.2f} m, belief off "
                          f"{f['belief_err_m']:.3f} m")


if __name__ == "__main__":
    main()
