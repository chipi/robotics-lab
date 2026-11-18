"""Replay landmark relocalisation on a recorded run (RFC-0016 §4): its sightings (each with the belief's pose and the truth) go
through the Relocaliser as they were, the corrections it would have made are added to the later poses, and the belief's
error against the truth is compared with and without them. Open loop: the run's own belief kept moving as it did, so a
correction here shifts every later pose by the offset (translation only), and nothing the correction would have changed
in the navigator's choices.

Run: cd duck && uv run python sim/probes/reloc_replay.py <run folder with ticks.jsonl, start.json> [seconds between lines]"""

import json
import math
import sys
from pathlib import Path

from duck_lab.nav.frames import OFFSET_HALF_S, OFFSET_MAX_M, compose, inverse
from duck_lab.world_model.objects import load_kinds
from duck_lab.world_model.relocalise import Relocaliser
from duck_lab.world_model.semantic_map import Detection, SemanticMap


def replay(run: Path, every: float = 60.0, quiet: bool = False) -> dict:
    rows = [json.loads(line) for line in (run / "ticks.jsonl").read_text().splitlines()]
    st = json.loads((run / "start.json").read_text())
    map_from_world = compose(tuple(st["map"]), inverse(tuple(st["truth"])))
    sm = SemanticMap(load_kinds())
    rel = Relocaliser(sm)
    off, last_t = (0.0, 0.0), 0.0
    out = {"corrections": [], "refusals": [], "series": []}
    for r in rows:
        if r.get("event") != "sighting":
            continue
        k = 0.5 ** ((r["t"] - last_t) / OFFSET_HALF_S)
        off, last_t = (off[0] * k, off[1] * k), r["t"]
        truth_on_map = compose(map_from_world, tuple(r["truth"]))
        pose = (r["pose"][0] + off[0], r["pose"][1] + off[1], r["pose"][2])
        found = [Detection(s["kind"], s["x"], s["y"], s["radius"], s["z0"], s["z1"], s["range_m"], s["confidence"], s["source"])
                 for s in r["seen"]]
        before = math.dist(r["pose"][:2], truth_on_map[:2])
        d = rel.observe(found, pose, r["t"])
        if d:
            if d["status"] == "corrected":
                nx, ny = off[0] + d["dx"], off[1] + d["dy"]
                n = math.hypot(nx, ny)
                if n > OFFSET_MAX_M:
                    nx, ny = nx * OFFSET_MAX_M / n, ny * OFFSET_MAX_M / n
                off = (nx, ny)
                out["corrections"].append((r["t"], d))
                pose = (r["pose"][0] + off[0], r["pose"][1] + off[1], r["pose"][2])
            else:
                out["refusals"].append((r["t"], d))
        sm.integrate(found, pose, r["t"])
        out["series"].append((r["t"], before, math.dist(pose[:2], truth_on_map[:2])))
    return out


def summarise(out: dict, every: float = 60.0) -> str:
    lines, last = [], -1e9
    for t, b, a in out["series"]:
        if t - last >= every:
            lines.append(f"t={t:6.0f}  belief err {b:.2f} m  corrected {a:.2f} m")
            last = t
    s = out["series"]
    lines.append(f"{len(out['corrections'])} corrections, {len(out['refusals'])} refusals; mean err "
                 f"{sum(b for _, b, _ in s) / len(s):.3f} -> {sum(a for _, _, a in s) / len(s):.3f} m; "
                 f"max {max(b for _, b, _ in s):.2f} -> {max(a for _, _, a in s):.2f} m")
    return "\n".join(lines)


if __name__ == "__main__":
    res = replay(Path(sys.argv[1]))
    print(summarise(res, float(sys.argv[2]) if len(sys.argv) > 2 else 60.0))
