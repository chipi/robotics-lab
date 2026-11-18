"""Answers from the prepared data, without a browser: scenes, runs, events, the state at t."""

import bisect
import math

from miniview.se2 import compose


def load_run(catalog, run_id: str) -> tuple:
    catalog.scan_paths()
    if catalog.resolve(run_id) is None:
        named = catalog.candidates(run_id)
        if len(named) > 1:
            raise SystemExit(f"{len(named)} runs are called {run_id!r}; which of: " + ", ".join(sorted(named)))
        raise SystemExit(f"no run {run_id!r} under {catalog.data / 'runs'} (miniview import it first)")
    ld = catalog.get(run_id)
    return ld.data.run, ld.data.frames


def load_signals(catalog, run_id: str) -> dict:
    """The run's signals ({"t": [...], "v": {name: [...]}}); the run is already loaded (`load_run`)."""
    return catalog.get(run_id).data.sig


def load_semantic(catalog, run_id: str) -> dict:
    """The run's semantic map ({"objects": [...], "sightings": [...]}); the run is already loaded (`load_run`)."""
    return catalog.get(run_id).data.sem


def signals_at(sig: dict, t: float) -> dict | None:
    """The sample at or before t (the first one when t is earlier): its time, its number, and each signal's value in
    it (None where that sample had none)."""
    if not sig["t"]:
        return None
    i = max(0, bisect.bisect_right(sig["t"], t) - 1)
    return {"t": sig["t"][i], "index": i, "n": len(sig["t"]), "values": {k: col[i] for k, col in sig["v"].items()}}


def sensor_at(raw: list, t: float) -> dict | None:
    """The raw depth frame at or before t (the first one when t is earlier), with its number and the count: what the
    sensor reported, and which state it was paired with (ADR-0014). None when the run has no raw frames."""
    if not raw:
        return None
    i = max(0, bisect.bisect_right(raw, t, key=lambda f: f["t"]) - 1)
    return dict(raw[i], index=i, n=len(raw), next_t=raw[i + 1]["t"] if i + 1 < len(raw) else None)


def epoch_at(run: dict, t: float):
    current = None
    for e in run["epochs"]:
        if e["from_t"] <= t + 1e-9:
            current = e
    return tuple(current["map_to_world"]) if current else None


def tick_at(frames: dict, t: float) -> int:
    """The last tick at or before t (the first tick if t is earlier)."""
    return max(0, bisect.bisect_right(frames["t"], t) - 1)


SIGHTING_FRESH_S = 1.0       # a sighting is "current" this long; the pages' and the video's is the same (ADR-0019)


def semantic_at(run: dict, sem: dict | None, t: float) -> dict | None:
    """The semantic map at t (ADR-0019), as the pages show it: the snapshot of objects in force (the last at or before t), the
    camera's sighting if one is current (at or before t, not more than SIGHTING_FRESH_S old), and the last room event with its votes.
    None for a run that has no objects, sightings or room events at all."""
    objs, sightings = (sem or {}).get("objects", []), (sem or {}).get("sightings", [])
    rooms = [e for e in run["events"] if e["kind"] == "room"]
    areas = [e for e in run["events"] if e["kind"] == "area"]
    if not (objs or sightings or rooms or areas):
        return None
    snap = sighting = room = None
    i = bisect.bisect_right(objs, t + 1e-9, key=lambda r: r["t"])
    if i:
        snap = objs[i - 1]
    j = bisect.bisect_right(sightings, t + 1e-9, key=lambda r: r["t"])
    if j and t - sightings[j - 1]["t"] <= SIGHTING_FRESH_S:
        sighting = sightings[j - 1]
    for e in rooms:
        if e["t"] <= t + 1e-9:
            room = e
    area = next((e for e in reversed(areas) if e["t"] <= t + 1e-9), None)
    r3 = lambda v: round(v, 3)  # noqa: E731
    return {
        "objects_t": snap["t"] if snap else None,
        "objects": [{"kind": o["kind"], "id": o["id"], "x": r3(o["x"]), "y": r3(o["y"]), "confirmed": bool(o.get("confirmed")),
                     "landmark": o.get("landmark"), "confidence": o.get("confidence")} for o in snap["objects"]] if snap else [],
        "sighting": {"t": sighting["t"], "pose": [r3(v) for v in sighting["pose"]], "hfov_deg": sighting["hfov_deg"], "range_m": sighting["range_m"],
                 "seen": [{"kind": d["kind"], "range_m": d.get("range_m"), "confidence": d.get("confidence")} for d in sighting["seen"]]} if sighting else None,
        "room": {"t": room["t"], "name": room.get("room"), "votes": room.get("votes") or {}} if room else None,
        "area": {"t": area["t"], **(area.get("area") or {})} if area else None,
    }


def state(run: dict, frames: dict, t: float, sig: dict | None = None, sem: dict | None = None) -> dict:
    """The run at t. A run with signals adds `signals` (see `signals_at`), a run with a semantic map `semantic` (see
    `semantic_at`); a run with only signals has no pose, so the answer is the run's identity, the time and the signals."""
    out = _pose_state(run, frames, t) if frames["t"] else {"run": run["id"], "scene": run["scene"], "t": t, "tick": None,
                                                           "last_event": _last_event(run, t)}
    if sig is not None and sig["t"]:
        out["signals"] = signals_at(sig, t)
    semantic = semantic_at(run, sem, t)
    if semantic is not None:
        out["semantic"] = semantic
    return out


def _last_event(run: dict, t: float):
    last = None
    for e in run["events"]:
        if e["kind"] != "room" and e["t"] <= t + 1e-9:
            last = e
    return last


def _pose_state(run: dict, frames: dict, t: float) -> dict:
    i = tick_at(frames, t)
    m2w = epoch_at(run, frames["t"][i])
    belief_map = frames["belief"][i]
    belief_world = list(compose(m2w, tuple(belief_map))) if m2w else None
    truth = frames["truth"][i]
    distance = math.dist(belief_world[:2], truth[:2]) if belief_world and truth else None
    last = None
    for e in run["events"]:            # by the time asked: events can follow the last pose (explore12)
        if e["kind"] != "room" and e["t"] <= max(t, frames["t"][i]) + 1e-9:
            last = e
    depth_i = next((j for j in range(i, -1, -1) if frames["depth"][j]), None)
    kinds = {}
    if depth_i is not None:
        for p in frames["depth"][depth_i]:
            kinds[p[3]] = kinds.get(p[3], 0) + 1
    r = lambda v: [round(x, 3) for x in v] if v else None  # noqa: E731
    return {"run": run["id"], "scene": run["scene"], "t": frames["t"][i], "tick": i,
            "belief_map": r(belief_map), "belief_world": r(belief_world), "truth": r(truth),
            "belief_truth_distance_m": round(distance, 3) if distance is not None else None,
            "tilt_deg": frames["tilt"][i], "cmd": frames["cmd"][i],
            "depth": {"frame_tick": depth_i, "frame_t": frames["t"][depth_i] if depth_i is not None else None,
                      "returns": kinds},
            "plan_index": frames["plan_at"][i], "world_index": frames["world_at"][i], "last_event": last}


def events(run: dict, kinds=None) -> list:
    return [e for e in run["events"] if not kinds or e["kind"] in kinds]
