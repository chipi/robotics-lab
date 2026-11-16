"""Is this record what its kind says? (ADR-0008) One function per kind; each returns an error text or None.
A bad record is skipped and counted by the run, never applied half way."""

import math

from miniview import keys, signals


class BrokenRun(Exception):
    """A run that cannot be read at all (ADR-0008): not MCAP, no valid run record, a key that is not its folder's."""


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _nums(v, n: int | None = None) -> bool:
    return isinstance(v, (list, tuple)) and (n is None or len(v) == n) and all(_num(x) for x in v)


def _run(p):
    if p.get("format") != 2:
        return f"format {p.get('format')!r}, expected 2"
    try:
        keys.split_key(p.get("key"))
    except ValueError as e:
        return str(e)
    for k in ("uuid", "scene", "kind", "started_at_source"):
        if not isinstance(p.get(k), str) or not p[k]:
            return f"{k} missing or not text"
    if not isinstance(p.get("robot"), dict) or not isinstance(p["robot"].get("name"), str):
        return "robot missing or without a name"
    if not isinstance(p.get("started_at_ns"), int) or isinstance(p["started_at_ns"], bool) or not 0 < p["started_at_ns"] < 2**63:
        return "started_at_ns missing, or not an integer from 1 to 2**63 - 1"
    if not isinstance(p.get("writer"), dict):
        return "writer missing"
    if p.get("signals") is not None:
        err = signals.check_decl(p["signals"])
        if err:
            return err
    if p.get("no_pose") is not None and not isinstance(p["no_pose"], str):
        return "no_pose is not text"
    if p.get("odometry") is not None and not isinstance(p["odometry"], dict):
        return "odometry is not an object"
    return None


def _epoch(p):
    return None if _nums(p.get("map_to_world"), 3) else "map_to_world is not three finite numbers"


def _tick(p):
    if not _nums(p.get("belief"), 3):
        return "belief is not three finite numbers"
    if p.get("truth") is not None and not _nums(p["truth"], 3):
        return "truth is not null or three finite numbers"
    if p.get("cmd") is not None and not _nums(p["cmd"], 2):
        return "cmd is not null or two finite numbers"
    if p.get("tilt") is not None and not _nums(p["tilt"]):
        return "tilt is not null or finite numbers"
    d = p.get("depth")
    if d is not None and not (isinstance(d, list) and all(isinstance(x, (list, tuple)) and len(x) == 4 and _nums(x[:3])
                                                          and isinstance(x[3], str) and len(x[3]) == 1 for x in d)):
        return "depth is not null or points [x, y, z, kind]"
    return None


def _signals(p):
    v = p.get("values")
    if not isinstance(v, dict) or not v:
        return "values is not a non-empty object"
    for name, x in v.items():
        if not isinstance(name, str):
            return "a signal name is not text"
        if not isinstance(x, str) and not _num(x):
            return f"signal {name!r} is neither text nor a finite number"
    return None


def _plan(p):
    path = p.get("path")
    return None if isinstance(path, list) and all(_nums(x, 2) for x in path) else "path is not a list of [x, y]"


def _world(p):
    g = p.get("grid")
    if not isinstance(g, dict):
        return "grid missing"
    if not (_num(g.get("res")) and g["res"] > 0 and _nums(g.get("origin"), 2)):
        return "grid res or origin invalid"
    w, h = g.get("w"), g.get("h")
    if not (isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0):
        return "grid size invalid"
    if not isinstance(g.get("cells"), str) or len(g["cells"]) != w * h:
        return f"grid cells: {len(g.get('cells') or '')} for {w} x {h}"
    for k in ("obstacles", "drops"):
        if not isinstance(p.get(k), list) or not all(_nums(x) for x in p[k]):
            return f"{k} is not a list of coordinates"
    return None


def _event(p):
    if not (isinstance(p.get("kind"), str) and isinstance(p.get("text"), str)):
        return "kind or text missing"
    d = p.get("decision")
    if d is not None and not (isinstance(d, dict) and isinstance(d.get("rule"), str) and isinstance(d.get("reason"), str)
                              and isinstance(d.get("values"), dict)):
        return "decision is not {rule, reason, values}"
    return None


def _depth_frame(p):
    rows, cols = p.get("rows"), p.get("cols")
    if not (isinstance(rows, int) and isinstance(cols, int) and not isinstance(rows, bool) and 0 < rows <= 64 and 0 < cols <= 64):
        return "rows or cols invalid"
    n = rows * cols
    d, s = p.get("distance_mm"), p.get("status")
    if not (isinstance(d, list) and len(d) == n and all(isinstance(x, int) and not isinstance(x, bool) for x in d)):
        return f"distance_mm is not {n} whole numbers"
    if not (isinstance(s, list) and len(s) == n and all(isinstance(x, int) and 0 <= x < 256 for x in s)):
        return f"status is not {n} bytes"
    if not isinstance(p.get("frame_t_ns"), int):
        return "frame_t_ns missing"
    for k in ("state_t_ns", "pair_dt_ms"):
        if p.get(k) is not None and not _num(p[k]):
            return f"{k} is not a finite number"
    return None


def _segment(p):
    if not (isinstance(p.get("index"), int) and _num(p.get("t_start")) and _num(p.get("t_end"))):
        return "index, t_start or t_end invalid"
    if p.get("goal") is not None and not _nums(p["goal"]):
        return "goal is not finite numbers"
    return None


def _end(p):
    return None if isinstance(p.get("verdict"), str) else "verdict missing"


CHECKS = {"run": _run, "epoch": _epoch, "tick": _tick, "signals": _signals, "plan": _plan, "world": _world, "event": _event,
          "depth_frame": _depth_frame, "segment": _segment, "end": _end}


def check(t, kind: str, p, last_t: float) -> str | None:
    """None when the record is good, else why not. `last_t` is the latest time applied so far."""
    fn = CHECKS.get(kind)
    if fn is None:
        return f"unknown kind {kind!r}"
    if not isinstance(p, dict):
        return "payload is not an object"
    if not _num(t):
        return f"time {t!r} is not a finite number"
    if t < last_t - 1e-9:
        return f"time goes back: {t} after {last_t}"
    try:
        return fn(p)
    except Exception as e:   # a record can be any shape: whatever it breaks, it is only bad
        return f"{type(e).__name__}: {e}"
