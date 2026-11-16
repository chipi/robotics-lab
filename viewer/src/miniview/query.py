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
    return dict(raw[i], index=i, n=len(raw))


def epoch_at(run: dict, t: float):
    current = None
    for e in run["epochs"]:
        if e["from_t"] <= t + 1e-9:
            current = e
    return tuple(current["map_to_world"]) if current else None


def tick_at(frames: dict, t: float) -> int:
    """The last tick at or before t (the first tick if t is earlier)."""
    return max(0, bisect.bisect_right(frames["t"], t) - 1)


def state(run: dict, frames: dict, t: float, sig: dict | None = None) -> dict:
    """The run at t. A run with signals adds `signals` (see `signals_at`); a run with only signals has no pose, so
    the answer is the run's identity, the time and the signals."""
    out = _pose_state(run, frames, t) if frames["t"] else {"run": run["id"], "scene": run["scene"], "t": t, "tick": None,
                                                           "last_event": _last_event(run, t)}
    if sig is not None and sig["t"]:
        out["signals"] = signals_at(sig, t)
    return out


def _last_event(run: dict, t: float):
    last = None
    for e in run["events"]:
        if e["t"] <= t + 1e-9:
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
