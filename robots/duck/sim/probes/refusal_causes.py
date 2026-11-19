"""What blocked each refusal in a run: the nearest obstacle (mapd cell or remembered point) to the
duck at each "no room to turn" / "refused", and whether it is real (by the layout) or a phantom.

    .venv/bin/python sim/probes/refusal_causes.py runs/explore9
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phantoms import PHANTOM_M, nearest, world  # noqa: E402  (phantoms.py reads argv[1] too)

rows = [json.loads(l) for l in open(Path(sys.argv[1]) / "ticks.jsonl")]
latest = None
for r in rows:
    if r.get("event") == "world":
        latest = r
    if r.get("event") != "refused" or latest is None or "pose" not in r:
        continue
    g = latest["grid"]
    res, (ox, oy), w = g["res_m"], g["origin"], g["width"]
    cells = [("mapd", (ox + (i % w + 0.5) * res, oy + (i // w + 0.5) * res)) for i, c in enumerate(g["cells"]) if c == "#"]
    pts = [("memory", tuple(b)) for b in latest["blocked"]]
    pose = r["pose"][:2]
    src, p = min(cells + pts, key=lambda sp: math.dist(sp[1], pose))
    d_real, name = nearest(world(p))
    verdict = "PHANTOM" if d_real > PHANTOM_M + (res / 2 if src == "mapd" else 0) else f"real ({name})"
    print(f"t {r['t']:7.2f} {r.get('why', 'no path'):24s} nearest {src} at {math.dist(p, pose):.2f} m: {verdict}"
          f"  truth duck {r.get('truth', [0, 0])[:2]}")
