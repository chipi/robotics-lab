"""K36: room_rule.py's measurement again with the navigator's own function (`duck_lab.nav.anomaly.room_verdict` and `Returns`, the profile's
numbers) in place of the probe's own loop. Each recording is replayed in time order: every depth frame's derived points go into `Returns`
as `Navigator._on_frame` puts them, the latest `world` record is the map (its grid and remembered points), and at each "no room to turn"
refusal the verdict is the function's, called with the belief pose the refusal recorded. Printed as room_rule.py prints its table, to be
read against it (22 disagrees, 8 of them the map wrong).

    uv run python sim/probes/room_rule_navigator.py [RUN ...]       # default: every apartment run with depth frames
"""
import sys
from collections import Counter
from pathlib import Path

from runfile import mcapio

from duck_lab.nav import anomaly as anom
from duck_lab.profile import load
from map_range import distance

DATA = Path("/work/robotics-lab/data/runs/duck/apartment")
AN = load("sim").anomalies
rows = []
names = sys.argv[1:] or sorted(p.name for p in DATA.iterdir() if p.is_dir())
for name in names:
    recs = mcapio.read(DATA / name, keep_raw=True)
    if not any(k == "depth_frame" and p.get("derived") for t, k, p in recs):
        continue
    returns = anom.Returns(AN.room_disagrees_window_s)
    world = None
    for t, k, p in recs:
        if k == "depth_frame" and p.get("derived"):
            returns.add(t, p["derived"]["points"])
        elif k == "world":
            g = p["grid"]
            world = ({"res_m": g["res"], "origin": g["origin"], "width": g["w"], "height": g["h"], "cells": g["cells"]},
                     p.get("obstacles") or [])
        elif k == "event" and p.get("kind") == "refused":
            raw = p.get("raw") or {}
            dec = (p.get("decision") or {}).get("values") or {}
            if "no room to turn" not in (raw.get("why") or (p.get("decision") or {}).get("reason") or ""):
                continue
            pose, tr = raw.get("pose"), raw.get("truth")
            if not pose or not tr or "room_m" not in dec:
                continue
            wrong = distance(tr[0], tr[1]) - dec["room_m"] > 0.05
            v = "no map" if world is None else anom.room_verdict(
                pose, world[0], world[1], returns, t, look_deg=AN.room_disagrees_look_deg, near_m=AN.room_disagrees_near_m,
                see_m=AN.room_disagrees_see_m, agree_m=AN.room_disagrees_agree_m, floor_slack_m=AN.room_disagrees_floor_slack_m)
            rows.append(("map obstacle far" if v is None else v if isinstance(v, str) else v["verdict"], wrong))
print("refusals", len(rows))
c = Counter((v, "map wrong" if w else "map ok") for v, w in rows)
print("NAVIGATOR verdicts:")
for k, n in sorted(c.items()):
    print("  ", k, n)
