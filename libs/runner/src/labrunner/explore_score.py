"""The scoreboard for exploring the apartment (stream A, docs/wip/EXPLORE-PROGRESS.md): one row per run, the batch's
summary, and the blockers ranked by the exploring they cost.

    python -m labrunner.explore_score runs/explore-b1-r1 runs/explore-b1-r2 runs/explore-b1-r3 [--md]

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

from labrunner.geometry import FOOTPRINT_M, LAYOUT, clearance, obstacles
from labrunner.frames import compose, inverse
from labrunner.rooms import ROOMS, room_of, score as rooms_score

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


FIND_M, FIND_FACING_DEG = 0.35, 45.0     # "go to the fridge" done: within this of its outline, facing it (RFC-0016)
MATCH_M = 0.6                           # a confirmed object this close to a real one of its kind is that one
ROOM_EDGE_M = 0.3                       # room naming is not scored this close to a room's walls (doorways)


def semantic_score(run: Path, rows: list) -> dict:
    """The semantic map against the truth (RFC-0016): objects confirmed, matched to a real object of their kind (world
    frame, through the start's map-to-world), their position error; rooms named, the share of the time the name was
    the room the duck was in; a "found" goal judged by where the duck stood and faced."""
    from worldmodel.objects import distance
    from worldmodel.semantic_map import centre
    from labrunner.sim_camera import SimCamera

    cam = SimCamera()
    out = {}
    sem = run / "semantic_map.json"
    start = run / "start.json"
    if sem.exists() and start.exists():
        st = json.loads(start.read_text())
        world_from_map = compose(st["truth"], inverse(st["map"]))
        conf = [o for o in json.loads(sem.read_text())["objects"] if o["confirmed"]]
        errs, false, found = [], [], set()
        for o in conf:
            wx, wy, _ = compose(world_from_map, (o["x"], o["y"], 0.0))
            real = [(math.dist((wx, wy), centre(parts)), oid) for oid, parts in cam.truth_objects(o["kind"])]
            if real and min(real)[0] <= MATCH_M:
                errs.append(min(real)[0])
                found.add(min(real)[1])
            else:
                false.append(o["kind"])
        # recall, the "find all objects" goal's score: the scene's objects found, by the room they stand in
        by_room = {}
        for oid, kind, parts in cam.objects:
            room = room_of(centre(parts)) or "?"
            n, f = by_room.get(room, (0, 0))
            by_room[room] = (n + 1, f + (oid in found))
        out["objects"] = {"confirmed": len(conf), "matched": len(errs), "false": false,
                          "mean_error_m": round(statistics.mean(errs), 3) if errs else None,
                          "kinds": sorted({o["kind"] for o in conf}), "found": len(found), "in_scene": len(cam.objects),
                          "by_room": {r: f"{f}/{n}" for r, (n, f) in sorted(by_room.items())}}
    # per tick: the room last named against the truth's, leaving out ticks within ROOM_EDGE_M of a room's walls (the
    # truth's room flips at the wall, the belief later: the doorway is not a mistake); time with no room named apart
    # the area type guess ("area_type"; "room" before the operator made areas his own, 2026-11-18) and, at a site with
    # areas, the operator's area the pose was in ("area"): each per tick against the truth's room, away from doorways
    said, named, right, none, events = None, 0, 0, 0, 0
    area, a_ticks, a_right, a_none, agrees, disagrees = None, 0, 0, 0, 0, 0
    for r in rows:
        ev = r.get("event")
        if ev in ("area_type", "room"):
            said, events = r.get("type", r.get("room")), events + 1
        elif ev == "area":
            area = r.get("type") or r.get("name")
            agrees += r.get("agrees") is True
            disagrees += r.get("agrees") is False
        elif "event" not in r and r.get("truth") and room_of(r["truth"], inset=ROOM_EDGE_M):
            if said is None:
                none += 1
            else:
                named += 1
                right += room_of(r["truth"]) == said
            if area is None:
                a_none += 1
            else:
                a_ticks += 1
                a_right += room_of(r["truth"]) == area
    ticks = named + none
    out["rooms_named"] = {"events": events, "named_share": round(named / ticks, 2) if ticks else None,
                          "right": round(right / named, 2) if named else None}
    if a_ticks or agrees or disagrees:
        out["areas"] = {"in_area_share": round(a_ticks / (a_ticks + a_none), 2) if a_ticks + a_none else None,
                        "right": round(a_right / a_ticks, 2) if a_ticks else None,
                        "guess_agreed": agrees, "guess_disagreed": disagrees}
    for r in rows:
        if r.get("event") != "found":
            continue
        truth = r.get("truth")
        real = cam.truth_objects(r["kind"])
        if not truth or not real:
            out["found"] = {"kind": r["kind"], "status": r["status"], "pass": False, "why": "no truth"}
            continue
        parts = min((p for _, p in real), key=lambda p: distance(p, truth[:2]))
        d = distance(parts, truth[:2])
        near = min((q for part in parts for q in part.outline(0.02)), key=lambda q: math.dist(q, truth[:2]))
        bearing = math.atan2(near[1] - truth[1], near[0] - truth[0])
        face = math.degrees(abs(math.atan2(math.sin(bearing - truth[2]), math.cos(bearing - truth[2]))))
        out["found"] = {"kind": r["kind"], "status": r["status"], "distance_m": round(d, 3), "facing_deg": round(face),
                        "pass": r["status"] == "reached" and d <= FIND_M and face <= FIND_FACING_DEG, "t": r["t"]}
    return out


def belief_score(run: Path, rows: list) -> dict:
    """The belief against the truth (the truth is used for scoring only): |belief - truth| over every tick, with the truth put
    into the map frame by the run's start, and what the fix gate and the landmarks did (events "fix" held or late,
    "relocalise" corrected or refused)."""
    start = json.loads((run / "start.json").read_text())
    map_from_world = compose(tuple(start["map"]), inverse(tuple(start["truth"])))
    errs = [math.dist(r["pose"][:2], compose(map_from_world, tuple(r["truth"]))[:2])
            for r in rows if "pose" in r and "truth" in r and "event" not in r]
    ev = [r for r in rows if r.get("event") in ("fix", "relocalise")]
    return {"mean_m": round(statistics.fmean(errs), 3) if errs else None, "max_m": round(max(errs), 3) if errs else None,
            "final_m": round(errs[-1], 3) if errs else None,
            "fixes_held": sum(1 for r in ev if r["event"] == "fix" and r["status"] == "held"),
            "fixes_late": sum(1 for r in ev if r["event"] == "fix" and r["status"] == "late"),
            "corrected": sum(1 for r in ev if r["event"] == "relocalise" and r["status"] == "corrected"),
            "refused": sum(1 for r in ev if r["event"] == "relocalise" and r["status"] == "refused")}


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
            "blockers": blockers, "semantic": semantic_score(run, rows), "belief": belief_score(run, rows)}


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
        b = o["belief"]
        print(f"    belief error: mean {b['mean_m']} m, max {b['max_m']} m, at the end {b['final_m']} m; fixes held "
              f"{b['fixes_held']}, taken late {b['fixes_late']}; landmarks corrected {b['corrected']}, refused {b['refused']}")
        s = o["semantic"]
        if "objects" in s:
            ob = s["objects"]
            print(f"    objects: {ob['confirmed']} confirmed, {ob['matched']} real (mean error {ob['mean_error_m']} m), "
                  f"false {ob['false'] or 'none'}; found {ob['found']} of the scene's {ob['in_scene']} "
                  f"({', '.join(f'{r} {v}' for r, v in ob['by_room'].items())})")
        rn = s["rooms_named"]
        if rn["events"]:
            print(f"    area type guessed: {rn['events']} changes; a guess in {int((rn['named_share'] or 0) * 100)}% of "
                  f"the time, right in {int(rn['right'] * 100) if rn['right'] is not None else '-'}% of that "
                  f"(away from doorways)")
        if "areas" in s:
            ar = s["areas"]
            print(f"    the operator's areas: in an area {int((ar['in_area_share'] or 0) * 100)}% of the time, the "
                  f"right one {int(ar['right'] * 100) if ar['right'] is not None else '-'}% of that; the guess agreed "
                  f"{ar['guess_agreed']}x, disagreed {ar['guess_disagreed']}x")
        if "found" in s:
            f = s["found"]
            print(f"    found {f['kind']}: {f['status']}, {f.get('distance_m')} m from it, facing off by "
                  f"{f.get('facing_deg')} deg: {'PASS' if f['pass'] else 'FAIL'}")
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
