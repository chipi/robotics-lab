"""The scoreboard for exploring the apartment (stream A, docs/wip/EXPLORE-PROGRESS.md): one row per run, the batch's
summary, and the blockers ranked by the exploring they cost.

    python -m duck_lab.nav.explore_score runs/explore-b1-r1 runs/explore-b1-r2 runs/explore-b1-r3 [--md]

Per run, from its ticks.jsonl, start.json and map_grid.json (the simulator's truth is used for scoring only):
- rooms visited (rooms.score: the truth inside a room) and each room's map area within 25 % (phase 2's bar);
- coverage: the share of each room's floor the map knows (free or occupied cells, truth frame);
- how it ended (the last of trapped / no_frontier_left / aborted, else the time ran out) and when;
- safety by truth: contacts (trunk centre nearer an obstacle's outline than evaluate.FOOTPRINT_M), falls (aborted);
- legs by outcome, and every leg that did not reach its target as a blocker: its kind (status and reason, numbers
  removed), the room it happened in, and the seconds it took (from the previous leg's end).
"""

import argparse
import json
import math
import re
import statistics
from pathlib import Path

from duck_lab.nav.evaluate import FOOTPRINT_M, LAYOUT, clearance, obstacles
from duck_lab.nav.frames import compose, inverse
from duck_lab.nav.rooms import ROOMS, room_of, score as rooms_score

ENDS = ("trapped", "no_frontier_left", "aborted")


def kind(status: str, why) -> str:
    return status + (": " + re.sub(r"\s*\(.*?\)|[-\d.]+\s*(m|s)\b", "", str(why)).strip(" :") if why else "")


def coverage(run: Path) -> dict:
    start = json.loads((run / "start.json").read_text())
    world_from_map = compose(tuple(start["truth"]), inverse(tuple(start["map"])))
    grid = json.loads((run / "map_grid.json").read_text())
    s = start["scale"]
    res, (ox, oy) = grid["res_m"] * s, (grid["origin"][0] * s, grid["origin"][1] * s)
    known = {}
    for i, c in enumerate(grid["cells"]):
        if c == "?":
            continue
        cx, cy = i % grid["width"], i // grid["width"]
        name = room_of(compose(world_from_map, (ox + (cx + 0.5) * res, oy + (cy + 0.5) * res, 0.0)))
        if name:
            known[name] = known.get(name, 0) + 1
    out = {}
    for name, (x0, x1, y0, y1) in ROOMS.items():
        out[name] = round(min(1.0, known.get(name, 0) * res * res / ((x1 - x0) * (y1 - y0))), 2)
    return out


def score_run(run: Path, obs: list) -> dict:
    rows = [json.loads(line) for line in open(run / "ticks.jsonl")]
    rooms = rooms_score(run)
    end, end_t, last_t, prev_leg_t = "time", None, 0.0, 0.0
    legs, blockers, contacts, walked, prev = {}, [], 0, 0.0, None
    in_contact, after_reflex, reflex_kept, looks, glance_s, glance_t = False, False, 0, 0, 0.0, None
    for r in rows:
        t = r.get("t", last_t)
        last_t = max(last_t, t)
        ev = r.get("event")
        # a reflex stop the plan did not answer: the navigator walks the same way into the same obstacle again
        if ev == "reflex_stop":
            after_reflex = True
        elif ev == "plan_kept" and after_reflex:
            reflex_kept, after_reflex = reflex_kept + 1, False
        elif ev in ("plan", "leg"):
            after_reflex = False
        if ev == "step_look":
            looks += 1
            glance_t = t
        elif ev == "glance" and glance_t is not None:
            glance_s, glance_t = glance_s + (t - glance_t), None
        if ev in ENDS:
            end, end_t = ev, t
        if ev == "leg":
            legs[r["status"]] = legs.get(r["status"], 0) + 1
            if r["status"] != "reached":
                where = room_of(r["truth"]) if r.get("truth") else None
                blockers.append({"kind": kind(r["status"], r.get("why")), "room": where, "s": round(t - prev_leg_t, 1)})
            prev_leg_t = t
        if "truth" in r and "event" not in r:
            p = r["truth"][:2]
            if prev:
                walked += math.dist(p, prev)
            prev = p
            near = clearance(p, obs)[0] < FOOTPRINT_M
            contacts += near and not in_contact
            in_contact = near
    return {"run": run.name, "visited": rooms["visited"], "areas_ok": rooms["areas_ok"], "bar": rooms["bar"],
            "rooms": [n for n, v in rooms["rooms"].items() if v["visited"]], "coverage": coverage(run),
            "end": end, "minutes": round((end_t or last_t) / 60, 1), "walked_m": round(walked, 1),
            "contacts": contacts, "falls": int(end == "aborted"), "legs": legs, "reflex_kept": reflex_kept,
            "looks": looks, "look_min": round(glance_s / 60, 1),
            "blockers": blockers}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--md", action="store_true", help="also print the batch's row for EXPLORE-PROGRESS.md")
    args = ap.parse_args()
    obs = obstacles(json.loads(LAYOUT.read_text()))
    out = [score_run(r, obs) for r in args.runs]
    for o in out:
        cov = " ".join(f"{n[:4]} {int(v * 100)}%" for n, v in o["coverage"].items())
        print(f"{o['run']}: rooms {o['visited']}/6 ({', '.join(o['rooms'])}), areas ok {o['areas_ok']}/6, "
              f"ended {o['end']} at {o['minutes']} min, walked {o['walked_m']} m, contacts {o['contacts']}, "
              f"falls {o['falls']}, legs {o['legs']}, reflex stops answered by the same plan {o['reflex_kept']}, "
              f"looks before stepping {o['looks']} ({o['look_min']} min)")
        print(f"    coverage: {cov}")
    cost = {}
    for o in out:
        for b in o["blockers"]:
            c = cost.setdefault(b["kind"], {"n": 0, "s": 0.0, "rooms": set(), "ended": 0})
            c["n"] += 1
            c["s"] += b["s"]
            c["rooms"].add(b["room"] or "?")
        if o["blockers"] and o["end"] in ENDS:
            cost.setdefault(o["blockers"][-1]["kind"], {"n": 0, "s": 0.0, "rooms": set(), "ended": 0})["ended"] += 1
    print("blockers, by exploring time lost:")
    for k, c in sorted(cost.items(), key=lambda kv: (-kv[1]["ended"], -kv[1]["s"])):
        print(f"    {k}: {c['n']}x, {round(c['s'] / 60, 1)} min, ended {c['ended']} run(s), in {', '.join(sorted(c['rooms']))}")
    visited = [o["visited"] for o in out]
    safe = sum(o["contacts"] for o in out) == 0 and sum(o["falls"] for o in out) == 0
    print(f"BATCH runs {len(out)}: rooms visited median {statistics.median(visited)} best {max(visited)}, "
          f"areas ok best {max(o['areas_ok'] for o in out)}/6, contacts {sum(o['contacts'] for o in out)}, "
          f"falls {sum(o['falls'] for o in out)}, bar {'MET' if all(o['bar'] == 'MET' for o in out) and safe else 'NOT MET'}")
    if args.md:
        top = max(cost.items(), key=lambda kv: (kv[1]["ended"], kv[1]["s"]))[0] if cost else "-"
        print(f"| {len(out)} | {statistics.median(visited)} / {max(visited)} | {max(o['areas_ok'] for o in out)}/6 | "
              f"{sum(o['contacts'] for o in out)} / {sum(o['falls'] for o in out)} | {top} |")


if __name__ == "__main__":
    main()
