"""Answers from the prepared data, without a browser: scenes, runs, events, the state at t."""

import bisect
import math

from miniview.se2 import compose


def load_run(catalog, run_id: str) -> tuple:
    ld = catalog.get(run_id)
    if ld is None:
        raise SystemExit(f"no run {run_id!r} under {catalog.data / 'runs'} (miniview import it first)")
    return ld.data.run, ld.data.frames


def epoch_at(run: dict, t: float):
    current = None
    for e in run["epochs"]:
        if e["from_t"] <= t + 1e-9:
            current = e
    return tuple(current["map_to_world"]) if current else None


def tick_at(frames: dict, t: float) -> int:
    """The last tick at or before t (the first tick if t is earlier)."""
    return max(0, bisect.bisect_right(frames["t"], t) - 1)


def state(run: dict, frames: dict, t: float) -> dict:
    i = tick_at(frames, t)
    m2w = epoch_at(run, frames["t"][i])
    belief_map = frames["belief"][i]
    belief_world = list(compose(m2w, tuple(belief_map))) if m2w else None
    truth = frames["truth"][i]
    distance = math.dist(belief_world[:2], truth[:2]) if belief_world and truth else None
    last = None
    for e in run["events"]:            # by the time asked: events can follow the last pose (explore12)
        if e["t"] <= max(t, frames["t"][i]) + 1e-9:
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
