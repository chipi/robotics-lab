"""A recorded run as the navigator's old log rows (ticks.jsonl, start.json), whichever way it is stored.

The corpus is MCAP now (runfile.mcapio); the probes that replay the explorer, the planner and the memory were written
against the log's rows. `load(run)` gives those rows back: from a folder that still has ticks.jsonl as they were, from
an MCAP run by undoing runfile/adapters/duck.py (every field of a row is in its record, the ones with no field of their
own in `raw`), so a probe's reading code is the same for both.

    start, rows = legacy_rows.load(Path(run))      # start: {"map", "truth", "scale"}; rows: dicts with "t" (the log's clock)

`start["map"]` and `start["truth"]` are the first tick's belief and truth (the epoch is the transform between them);
`start["scale"]` is the sim profile's odometry scale: the MCAP run does not carry the log's start.json.
"""

import json
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab.profile import load as load_profile


def _tick(p: dict, t: float) -> dict:
    r = {"t": p.get("t_src", t), "pose": p["belief"]}
    if p.get("truth") is not None:
        r["truth"] = p["truth"]
    if p.get("tilt") is not None:
        r["tilt"] = p["tilt"]
    r["vx"], r["vyaw"] = p["cmd"]
    if p.get("depth") is not None:
        r["depth"] = p["depth"]
    if p.get("truth_3d"):
        r["truth_z"], r["truth_quat"] = p["truth_3d"]["z"], p["truth_3d"]["quat"]
    return {**r, **(p.get("raw") or {})}


def row_of(kind: str, p: dict, t: float) -> dict | None:
    """The log row of one record, or None for a record the log had no row for (signals, depth frames, epochs, segments, the end)."""
    raw = p.get("raw") or {}
    if kind == "tick":
        return _tick(p, t)
    if kind == "event":
        r = {"event": p["kind"], "t": p.get("t_src", t), **raw}
        if "decision" in p:
            r["decision"] = p["decision"]
        if p["kind"] == "room":
            r.update(room=p.get("room"), votes=p.get("votes"))
        return r
    if kind == "plan":
        return {"event": "plan", "t": p.get("t_src", t), "path": p["path"], **raw}
    if kind == "world":
        g = p["grid"]
        return {"event": "world", "t": p.get("t_src", t), "grid": {"res_m": g["res"], "origin": g["origin"], "width": g["w"],
                                                              "height": g["h"], "cells": g["cells"]},
                "blocked": p["obstacles"], "drops": p["drops"], **raw}
    if kind == "objects":
        return {"event": "semantic", "t": p.get("t_src", t), "objects": p["objects"], "changes": p["changes"], **raw}
    if kind == "sighting":
        return {"event": "sighting", "t": p.get("t_src", t), "pose": p["pose"], "hfov_deg": p["hfov_deg"], "range_m": p["range_m"],
                "seen": p["seen"], **raw}
    return None


def load(run: Path) -> tuple:
    run = Path(run)
    if (run / "ticks.jsonl").exists():
        start = json.loads((run / "start.json").read_text()) if (run / "start.json").exists() else None
        return start, [json.loads(line) for line in (run / "ticks.jsonl").read_text().splitlines() if line.strip()]
    records = Follower(run, keep_raw=True).poll()
    rows = [r for t, k, p in records if (r := row_of(k, p, t)) is not None]
    first = next(r for r in rows if "pose" in r and "event" not in r and "truth" in r)
    scale = next((r["scale"] for r in rows if r.get("event") == "pick" and "scale" in r),
                 load_profile("sim").localisation.odometry.scale)
    return {"map": first["pose"], "truth": first["truth"], "scale": scale}, rows


def final_grid(run: Path, rows: list) -> tuple:
    """(grid, scale): mapd's last grid and the factor its res and origin still need (map_grid.json, as mapd wrote it: the
    start's scale), else the last `world` row's, which the navigator had scaled already (1.0)."""
    f = Path(run) / "map_grid.json"
    if f.exists():
        return json.loads(f.read_text()), None
    return next(r["grid"] for r in reversed(rows) if r.get("event") == "world"), 1.0
