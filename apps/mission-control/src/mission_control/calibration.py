"""A robot's calibration through Mission Control (phase 5 item 4a unit A3, RFC-0023 D11): a guided procedure, run by the robot's navigator
(contract 1.3, libs/runner/CONTRACT.md), measured against a reference, and kept as the next settings version or discarded.

Three parties each hold one part. The navigator drives the motion and reports what the robot's own sensors said (`measured`). The
reference, what the floor says, is its runner's (the simulator's truth) or the operator's tape. Mission Control holds the meaning: the
step guide, which setting a procedure sets, how a measurement and a reference become its value, and the profile it is written into.
So a procedure is defined here by its id, and the navigator lists which of them it drives.

One run per robot is kept, in memory: an unkept measurement is lost with the process, a kept one is in its profile version's `measured`
line. Everything is read from the navigator when asked (the page polls): Mission Control has no thread of its own for it."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from runfile.navcontract import CALIBRATION_ENDS, ContractError
from runfile.profile import merge_variant

from . import profiles
from .errors import ApiError, conflict, invalid, not_found

PHASES = ("running", "needs_tape", "measured", "kept", "refused", "cancelled", "interrupted", "failed")


@dataclass(frozen=True)
class Step:
    id: str
    who: str            # robot, runner, operator
    text: str


@dataclass(frozen=True)
class Procedure:
    id: str
    title: str
    what: str
    sets: str           # the profile path under the running variant that a kept value goes to
    bounds: tuple       # a value outside is not plausible: the robot was probably blocked or the tape misread; it is not kept
    steps: tuple


def _odometry_scale(measured: dict, reference_m: float) -> float:
    return reference_m / measured["odom_m"]


PROCEDURES = {p.id: p for p in (
    Procedure(
        "odometry_scale", "Odometry scale",
        "How much longer the robot's odometry reads than the floor it walked. The navigator scales its odometry, mapd's poses and its grid "
        "by this factor, so the map and the belief are in true metres.",
        "localisation.odometry.scale", (0.5, 1.5),
        (Step("place", "operator", "Clear about 3 m of flat floor ahead of the robot, and stand clear. It walks straight and blind: no cliff or "
                                   "wall check runs during a calibration."),
         Step("walk", "robot", "The robot stands, walks straight for the seconds below at the speed below, and stands again. Mission Control "
                               "does not hold it: the navigator does, and STOP ends it."),
         Step("measure", "runner", "The reference: in the simulator the runner reads where the robot went (the truth). On a real robot "
                                   "measure from where it started to where it stands with a tape, and enter it."),
         Step("keep", "operator", "Compare the measured value with the current one. Keep it as the next settings version (it applies from "
                                  "the next goal), or discard it."))),
)}
RULES = {"odometry_scale": _odometry_scale}
_lock = threading.Lock()        # one calibration call at a time: the page polls while a request starts, cancels or keeps


def _navigator(rt):
    nav = rt.navigator
    if nav is None or not hasattr(nav, "calibration_list"):
        raise ApiError(404, "no_calibration", f"{rt.cfg.id}'s navigator does not calibrate")
    return nav


def _ask(rt, method: str, *args):
    """A call of the navigator, its failures said as the API's: not answering, or answering outside the contract."""
    try:
        return getattr(_navigator(rt), method)(*args)
    except (OSError, RuntimeError, ContractError, KeyError) as exc:
        raise ApiError(503, "navigator_unreachable", f"{rt.cfg.id}'s navigator did not answer: {exc}") from None


def _path(rt):
    """The running profile's value by path: a robot whose file holds the robot itself has no profile to calibrate (404 no_profile)."""
    profiles._robot(rt)
    return rt.cfg.profile.get


def _writes(odo: dict, speed: float, value: float) -> list:
    """(path, now, to) of what a kept value changes under localisation.odometry: the table's entry at the speed walked, and `scale` when that
    is the speed it was measured at (the profile's rule: `scale` is the table's value at at_speed_mps, within 1 %). With no table, `scale`."""
    table, at = odo.get("by_speed"), odo.get("at_speed_mps")
    if not table:
        return [("localisation.odometry.scale", odo.get("scale"), value)]
    key = next((k for k in table if abs(float(k) - speed) < 1e-9), f"{speed:g}")
    out = [(f"localisation.odometry.by_speed.{key}", table.get(key), value)]
    if at is not None and abs(at - speed) < 1e-9:
        out.append(("localisation.odometry.scale", odo.get("scale"), value))
    return out


def _poll(rt, run: dict) -> None:
    if run["nav"].get("state") not in CALIBRATION_ENDS:
        run["nav"] = _ask(rt, "calibration_status")
        if run["nav"].get("state") == "idle":        # a navigator that was restarted since the start: it knows no run
            run["nav"] = {"state": "failed", "reason": "the navigator reports no calibration running: it was probably restarted"}


def _phase(run: dict) -> str:
    if run["kept"]:
        return "kept"
    state = run["nav"].get("state")
    if state == "running" or state == "idle":
        return "running"
    if state != "done":
        return state
    return "measured" if _reference(run) else "needs_tape"


def _reference(run: dict) -> dict | None:
    ref = run["nav"].get("reference")
    if ref:
        return ref
    return {"by": "operator", "distance_m": run["tape_m"]} if run["tape_m"] else None


def _run_view(rt, run: dict | None) -> dict | None:
    if run is None:
        return None
    _poll(rt, run)
    proc, nav, phase = PROCEDURES[run["procedure"]], run["nav"], _phase(run)
    ref, measured = _reference(run), nav.get("measured")
    value = round(RULES[proc.id](measured, ref["distance_m"]), 3) if measured and ref else None
    get = _path(rt)
    current = get(proc.sets)
    plausible = None if value is None else proc.bounds[0] <= value <= proc.bounds[1]
    writes = run["kept"]["writes"] if run["kept"] else \
        [{"path": p, "from": a, "to": b} for p, a, b in _writes(get("localisation.odometry") or {}, run["params"]["speed_mps"], value)] \
        if value is not None else []
    status = {"running": ("done", "now", "todo", "todo"), "needs_tape": ("done", "done", "now", "todo"), "measured": ("done", "done", "done", "now"),
              "kept": ("done", "done", "done", "done")}.get(phase)
    steps = [{"id": s.id, "who": s.who, "text": s.text, "status": status[i] if status else "todo"} for i, s in enumerate(proc.steps)]
    return {"n": run["n"], "procedure": proc.id, "phase": phase, "state": nav.get("state"), "step": nav.get("step"), "reason": nav.get("reason"),
            "params": run["params"], "measured": measured, "reference": ref, "value": value, "current": current, "bounds": list(proc.bounds),
            "plausible": plausible, "writes": writes, "kept": run["kept"], "steps": steps}


def view(rt) -> dict:
    """The robot's procedures (each: its guide, what it sets and the value now, whether the navigator drives it, its default parameters) and
    its run, if any."""
    with _lock:
        nav, why = _navigator(rt), None
        try:
            driven = {p["id"]: p for p in nav.calibration_list()}
        except (OSError, RuntimeError, ContractError) as exc:
            driven, why = {}, f"the navigator did not answer: {exc}"
        get = _path(rt)
        procs = []
        for p in PROCEDURES.values():
            d = driven.get(p.id)
            procs.append({"id": p.id, "title": p.title, "what": p.what, "sets": p.sets, "current": get(p.sets), "bounds": list(p.bounds),
                          "steps": [{"id": s.id, "who": s.who, "text": s.text} for s in p.steps], "available": d is not None,
                          "why_not": None if d is not None else why or "this robot's navigator does not drive it (contract 1.3 or later does)",
                          "params": d["params"] if d else None})
        _, store_why = profiles._store(rt.cfg.robot) if rt.cfg.robot else (None, "this robot's file holds the robot itself: it has no profile")
        return {"robot": rt.cfg.id, "variant": rt.cfg.variant, "procedures": procs, "run": _run_view(rt, rt.calibration),
                "writable": store_why is None, "why_not": store_why}


def start(rt, body) -> dict:
    procedure = body.get("procedure") if isinstance(body, dict) else None
    params = (body.get("params") if isinstance(body, dict) else None) or {}
    if procedure not in PROCEDURES:
        raise not_found("calibration procedure", procedure)
    if not isinstance(params, dict):
        raise invalid("params: an object")
    with _lock:
        _navigator(rt)
        profiles._robot(rt)        # before the navigator is asked: with no profile there is nowhere to keep a value, and it must not be left walking
        refusal = rt.cfg.real_run_refusal()        # a calibration walks blind: no wall, cliff or contact check, so it is a real run in the strictest sense
        if refusal:
            raise conflict("real_runs_not_allowed", refusal)
        if rt.active is not None:
            raise conflict("robot_busy", f"goal run {rt.active.id} holds this robot")
        if rt.calibration is not None and _phase(rt.calibration) == "running":
            raise conflict("calibration_running", "a calibration is running: cancel it first")
        reply = _ask(rt, "calibration_start", procedure, params)
        err = reply.get("error")
        if err:
            code = err.get("code")
            if code == "bad_params":
                raise invalid(err.get("message", "bad parameters"), code="bad_params")
            if code == "unknown_procedure":
                raise not_found("calibration procedure", procedure)
            raise conflict(code or "refused", err.get("message", str(err)), **({"holder": err["holder"]} if err.get("holder") else {}))
        rt.calibration_n += 1
        rt.calibration = {"n": rt.calibration_n, "procedure": procedure, "params": reply["params"], "nav": {"state": "running"}, "tape_m": None,
                          "kept": None}
        return _run_view(rt, rt.calibration)


def _current(rt) -> dict:
    run = rt.calibration
    if run is None:
        raise ApiError(404, "no_calibration_run", "no calibration has been run on this robot")
    return run


def cancel(rt) -> dict:
    with _lock:
        run = _current(rt)
        if _phase(run) == "running":
            _ask(rt, "calibration_cancel")
        return _run_view(rt, run)


def reference(rt, body) -> dict:
    """The operator's tape: where the runner has no truth, the distance the robot went, measured on the floor."""
    d = body.get("distance_m") if isinstance(body, dict) else None
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not d > 0:
        raise invalid("distance_m: the distance the robot walked, in metres, above 0")
    with _lock:
        run = _current(rt)
        _poll(rt, run)
        if run["nav"].get("state") != "done":
            raise conflict("not_done", "the robot has not finished walking")
        if run["nav"].get("reference"):
            raise conflict("reference_by_truth", "the runner measured this walk by the truth: a tape is not asked for")
        if run["kept"]:
            raise conflict("already_kept", f"this run is kept as version {run['kept']['version']}")
        run["tape_m"] = float(d)
        return _run_view(rt, run)


def discard(rt) -> dict:
    with _lock:
        run = rt.calibration
        if run is not None and _phase(run) == "running":
            raise conflict("calibration_running", "a calibration is running: cancel it first")
        rt.calibration = None
        return {"robot": rt.cfg.id, "discarded": run["n"] if run else None}


def keep(rt, body=None) -> dict:
    """The measured value as the next version of the robot's profile, in the variant it runs: the setting, and its `measured` line says
    how (a new version applies from the next goal). Refused while no value is known, for one outside its bounds, and for a robot that
    cannot write versions here."""
    with _lock:
        run = _current(rt)
        v = _run_view(rt, run)
        if v["kept"]:
            raise conflict("already_kept", f"this run is already kept as version {v['kept']['version']}")
        if v["value"] is None:
            raise conflict("no_value", "nothing is measured yet" if v["phase"] == "running" else f"this run has no value ({v['phase']})")
        proc = PROCEDURES[run["procedure"]]
        if not v["plausible"]:
            raise conflict("implausible", f"{v['value']:g} is outside {proc.bounds[0]:g} to {proc.bounds[1]:g}: the robot was probably blocked "
                           f"or the tape misread. Run it again; nothing is written", value=v["value"])
        raw, current = profiles.start_from(rt)
        variant = rt.cfg.variant
        odo = (merge_variant(raw, variant).get("localisation") or {}).get("odometry") or {}
        block = raw.setdefault("variants", {}).setdefault(variant, {}).setdefault("localisation", {}).setdefault("odometry", {})
        old_note, writes = block.get("measured"), _writes(odo, run["params"]["speed_mps"], v["value"])
        for path, _, to in writes:
            leaf = path.removeprefix("localisation.odometry.")
            if leaf.startswith("by_speed."):
                table = block.get("by_speed") or dict(odo.get("by_speed") or {})
                table[leaf.removeprefix("by_speed.")] = to
                block["by_speed"] = table
            else:
                block[leaf] = to
        ref, p = v["reference"], run["params"]
        by = "the simulator's truth, read by the runner" if ref["by"] == "truth" else "the operator's tape"
        day = time.strftime("%Y-%m-%d", time.gmtime(rt.wall()))
        line = (f"{day}, Mission Control's calibration procedure odometry_scale (run {v['n']}, replacing version {current or 'the robot file'}): "
                f"the robot walked straight at {p['speed_mps']:g} m/s for {p['seconds']:g} s; the odometry read {v['measured']['odom_m']:g} m, "
                f"{by} {ref['distance_m']:g} m; reference over odometry {v['value']:g}.")
        block["measured"] = f"{line} Before this: {old_note}" if old_note else line
        block.setdefault("why", "the navigator scales the robot's odometry, mapd's poses and its grid by this factor so the map and the belief "
                                "are in true metres; measured by the calibration procedure named in `measured`")
        saved = profiles.save(rt, raw)
        run["kept"] = {"version": saved["version"], "applies": saved["applies"],
                       "writes": [{"path": p, "from": a, "to": b} for p, a, b in writes]}
        return _run_view(rt, run)
