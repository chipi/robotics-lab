"""Phase 2's score (RFC-0002 §3.4): all six rooms visited; each room's area on the map within ±25 %.

    uv run duck-rooms runs/explore1

Rooms are the apartment's rooms between their walls (sim/apartment_layout.json). Five match their floor
boxes exactly; the corridor's floor boxes are a 40 cm carpet strip, so the corridor is taken between its
walls (x -1.0..0.5), staircase opening excluded.

- Visited: the simulator's truth was inside the room (with the trunk at least 15 cm in from its walls).
- Area on the map: the map's segmentation (segment() below, from the duck's own map) — each segment
  is matched to the room holding most of its cells (truth frame), and its area (free + occupied cells)
  compared with the room's.
"""

import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path

from duck_lab.nav.frames import compose, inverse

ROOMS = {   # x0, x1, y0, y1 (world), from the walls in apartment_layout.json
    "kitchen": (-4.0, -1.0, 0.5, 3.0),
    "living": (-4.0, -1.0, -3.0, 0.5),
    "office": (0.5, 4.0, -1.0, 1.0),
    "bedroom": (0.5, 4.0, 1.0, 3.0),
    "bath": (0.5, 4.0, -3.0, -1.0),
    "corridor": (-1.0, 0.5, -3.0, 3.0),
}
STAIRS = (-0.4, 0.0, -1.4, -0.7)
INSET_M = 0.15
DOOR_HALF_M = 0.42        # segments are cut where free space is narrower than a doorway (0.8 m)


def room_of(p, inset=0.0):
    for name, (x0, x1, y0, y1) in ROOMS.items():
        if x0 + inset <= p[0] <= x1 - inset and y0 + inset <= p[1] <= y1 - inset:
            return name
    return None


def room_area(name):
    x0, x1, y0, y1 = ROOMS[name]
    a = (x1 - x0) * (y1 - y0)
    if name == "corridor":
        a -= (STAIRS[1] - STAIRS[0]) * (STAIRS[3] - STAIRS[2])
    return a


def segment(grid: dict) -> list:
    """Rooms from the map alone: free cells farther than DOOR_HALF_M from anything not free are room
    cores (doorways and walls cut them apart); every known cell joins the nearest core. Returns a
    list of segments, each a list of (cx, cy) cells."""
    w, h, cells = grid["width"], grid["height"], grid["cells"]
    res = grid["res_m"]
    dist = [math.inf] * (w * h)
    q = deque()
    for i, c in enumerate(cells):
        if c != ".":
            dist[i] = 0
            q.append(i)
    while q:                                   # grid-step distance to the nearest non-free cell
        i = q.popleft()
        x, y = i % w, i // w
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and dist[ny * w + nx] > dist[i] + 1:
                dist[ny * w + nx] = dist[i] + 1
                q.append(ny * w + nx)
    core = [i for i in range(w * h) if cells[i] == "." and dist[i] * res > DOOR_HALF_M]
    label = [-1] * (w * h)
    n = 0
    for s in core:                              # connected cores
        if label[s] != -1:
            continue
        label[s] = n
        q = deque([s])
        while q:
            i = q.popleft()
            x, y = i % w, i // w
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                j = ny * w + nx
                if 0 <= nx < w and 0 <= ny < h and label[j] == -1 and cells[j] == "." and dist[j] * res > DOOR_HALF_M:
                    label[j] = n
                    q.append(j)
        n += 1
    q = deque(i for i in range(w * h) if label[i] != -1)   # grow cores over every known cell
    while q:
        i = q.popleft()
        x, y = i % w, i // w
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            j = ny * w + nx
            if 0 <= nx < w and 0 <= ny < h and label[j] == -1 and cells[j] != "?":
                label[j] = label[i]
                q.append(j)
    segs = [[] for _ in range(n)]
    for i, l in enumerate(label):
        if l != -1:
            segs[l].append((i % w, i // w))
    return segs


def score(run: Path) -> dict:
    start = json.loads((run / "start.json").read_text())
    world_from_map = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
    scale = start["scale"]
    visited, first_seen = set(), {}
    for line in open(run / "ticks.jsonl"):
        r = json.loads(line)
        if "truth" in r:
            name = room_of(r["truth"], INSET_M)
            if name and name not in visited:
                visited.add(name)
                first_seen[name] = r["t"]
    grid = json.loads((run / "map_grid.json").read_text())
    res, (ox, oy) = grid["res_m"] * scale, (grid["origin"][0] * scale, grid["origin"][1] * scale)
    areas = {}
    for seg in segment(grid):
        votes = {}
        for cx, cy in seg:
            p = compose(world_from_map, (ox + (cx + 0.5) * res, oy + (cy + 0.5) * res, 0.0))
            name = room_of(p)
            if name:
                votes[name] = votes.get(name, 0) + 1
        if votes:
            name = max(votes, key=votes.get)
            areas[name] = areas.get(name, 0.0) + len(seg) * res * res
    rows = {}
    for name in ROOMS:
        a = areas.get(name)
        rows[name] = {"visited": name in visited, "first_at_s": first_seen.get(name),
                      "map_area_m2": round(a, 2) if a else None, "true_area_m2": round(room_area(name), 2),
                      "within_25pct": a is not None and abs(a / room_area(name) - 1) <= 0.25}
    met = all(r["visited"] and r["within_25pct"] for r in rows.values())
    return {"rooms": rows, "visited": len(visited), "areas_ok": sum(r["within_25pct"] for r in rows.values()),
            "bar": "MET" if met else "NOT MET"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    args = ap.parse_args()
    out = score(args.run)
    for name, r in out["rooms"].items():
        print(f"{name:9s} visited {'yes' if r['visited'] else 'no ':3s} (at {r['first_at_s']} s)  "
              f"map {r['map_area_m2']} m2 vs {r['true_area_m2']} m2  {'ok' if r['within_25pct'] else 'off'}")
    print(f"PHASE2 rooms visited {out['visited']}/6, areas within 25 % {out['areas_ok']}/6 - bar {out['bar']}")
    sys.exit(0 if out["bar"] == "MET" else 1)


if __name__ == "__main__":
    main()
