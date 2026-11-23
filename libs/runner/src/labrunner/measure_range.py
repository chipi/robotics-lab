"""Does the depth sensor report range along each zone's beam (radial) or straight ahead along its axis (axial)? (phase 5 item 4b unit B9;
K34, RANGE.md, REAL-DUCK.md section 2.) mapd assumes axial, the simulator is radial, the real VL53L5CX is not known. Read-only: it
asks the depth socket for frames (`tof.stream`) and sends nothing else; it never moves the robot or its head.

    lab-measure-range --socket ~/.cache/duck-real/duck-tof.sock --tape-m 0.5       # the real duck, through lab-link's forward
    lab-measure-range                                                                # the simulator's depth socket (the host file)
    lab-measure-range --frames-file frames.json                                      # frames saved by robots/duck/sim/probes/tof_rows.py

The setup: the duck standing still, its head held where it will walk, and a FLAT, VERTICAL, matt board or wall square to the duck, big
enough to fill the zones you give with --rows and --cols (the sensor looks about 3 degrees down and is 45 degrees square: at 0.5 m the
view is about 0.4 m by 0.4 m). Repeat at 0.25, 0.5 and 0.75 m (REAL-DUCK.md): near is the best test, the models part by up to 12 % of range
at the corners. A zone that sees the floor or the side of the board belongs outside --rows and --cols.

How it decides: a flat wall at horizontal distance D, the sensor pitched down p and turned psi to it, puts zone i at a range the geometry
fixes. Radial, the zone reports that range along its beam; axial, the range's component along the sensor's axis (the beam's cosine less).
For each model D, p and psi are fitted (D in closed form, p and psi by a grid and a finer one around the best) to the zones' median over
the frames, and the model that leaves the smaller residual is the answer. A pitch or a yaw error tilts the readings the same way on both
sides of the middle; the models differ by a part that is the same on both sides (the beams' cosine), so tilting cannot fake one for the
other. It says "inconclusive" instead of choosing when the wall was not flat enough (the best fit leaves a large residual) or the two fit
about equally well (too far, or too few zones).

The numbers to paste into the profile's `measured`: the verdict, the residuals, each model's fitted pitch and D, and the median frame (so a
later look can re-fit offline with --frames-file)."""

from __future__ import annotations

import argparse
import json
import math
import socket
import statistics
import sys
import time
from pathlib import Path

# The sensor, as robots/duck/profile.json `sensors.tof8x8` has it (the runner imports no robot's package, RFC-0022). valid_status is the
# VL53L5CX's "range valid" pair the simulator copies.
FOV_DEG, ROWS, COLS = 45.0, 8, 8
VALID = (5, 9)

PITCH_RANGE_DEG = (-8.0, 12.0)     # the sensor's total pitch against the wall: the head's, plus the mount's offset beyond it
YAW_RANGE_DEG = (-12.0, 12.0)      # the board not square to the duck
COARSE_DEG, FINE_DEG, FINE_SPAN_DEG = 0.5, 0.05, 0.5
RATIO_MIN = 1.5                    # the worse model's residual over the better's before a verdict is given
FLAT_MAX = 0.04                    # the better model's residual may be this share of D: more and the wall was not flat or the zones not all wall
MIN_ZONES = 24                     # fewer valid zones in the window and the fit has too little to part the models


def beams(fov_deg: float = FOV_DEG, rows: int = ROWS, cols: int = COLS) -> list:
    """Each zone's unit beam in the sensor's frame (x along its axis, y left, z up), row 0 at the top; the same as the navigator's
    Tof8x8._beams, which this must agree with (a test checks the corners)."""
    half = math.radians(fov_deg / 2 - fov_deg / cols / 2)
    step = 2 * half / (cols - 1)
    out = []
    for i in range(rows * cols):
        el = half - (i // cols) * step
        az = half - (i % cols) * step
        out.append((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    return out


def wall_ranges(kind: str, d_m: float, pitch_deg: float, yaw_deg: float, beam_list: list) -> list:
    """What each zone would report (mm) against a flat vertical wall d_m ahead of the sensor, the sensor pitched down pitch_deg and the
    wall turned yaw_deg away from square; kind is radial (the range along the beam) or axial (its part along the sensor's axis)."""
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    out = []
    for bx, by, bz in beam_list:
        x = bx * cp + bz * sp                     # pitch down: the beam's forward part tilts toward the floor
        z = -bx * sp + bz * cp
        xw = x * cy - by * sy                     # then yaw about the vertical: the wall's normal is the world x
        r = d_m / xw if xw > 1e-6 else math.inf
        out.append(1000.0 * (r if kind == "radial" else r * bx))
    return out


def _fit_at(kind: str, readings: list, idx: list, beam_list: list, pitch: float, yaw: float) -> tuple:
    """(rms residual mm, D m) of one model at one pitch and yaw. The readings are linear in D, so D is the least squares scale."""
    g = wall_ranges(kind, 1.0, pitch, yaw, [beam_list[i] for i in idx])
    if any(math.isinf(v) for v in g):
        return math.inf, 0.0
    num = sum(readings[i] * gi for i, gi in zip(idx, g))
    den = sum(gi * gi for gi in g)
    d_m = num / den                                # g is the reading at D = 1 m, so the scale is D in metres
    rms = math.sqrt(sum((readings[i] - d_m * gi) ** 2 for i, gi in zip(idx, g)) / len(idx))
    return rms, d_m


def fit(kind: str, readings: list, idx: list, beam_list: list) -> dict:
    """The best pitch, yaw and D of one model over the zones in idx: a coarse grid, then a fine one around its best."""
    best = (math.inf, 0.0, 0.0, 0.0)
    def sweep(p_lo, p_hi, y_lo, y_hi, step):
        nonlocal best
        p = p_lo
        while p <= p_hi + 1e-9:
            y = y_lo
            while y <= y_hi + 1e-9:
                rms, d = _fit_at(kind, readings, idx, beam_list, p, y)
                if rms < best[0]:
                    best = (rms, d, p, y)
                y += step
            p += step
    sweep(*PITCH_RANGE_DEG, *YAW_RANGE_DEG, COARSE_DEG)
    _, _, p0, y0 = best
    sweep(p0 - FINE_SPAN_DEG, p0 + FINE_SPAN_DEG, y0 - FINE_SPAN_DEG, y0 + FINE_SPAN_DEG, FINE_DEG)
    rms, d, p, y = best
    return {"rms_mm": round(rms, 2), "d_m": round(d, 4), "pitch_deg": round(p, 2), "yaw_deg": round(y, 2)}


def median_frame(frames: list, min_share: float = 0.5) -> tuple:
    """(per-zone median distance mm or None, the frames' count): a zone counts when it was valid in at least min_share of the frames."""
    med = []
    for i in range(len(frames[0]["distance_mm"])):
        v = [f["distance_mm"][i] for f in frames if f["status"][i] in VALID and f["distance_mm"][i] > 0]
        med.append(statistics.median(v) if len(v) >= min_share * len(frames) else None)
    return med, len(frames)


def window(rows: tuple, cols: tuple, n_rows: int = ROWS, n_cols: int = COLS) -> list:
    """The zone indices in rows lo..hi and columns lo..hi (inclusive, 0-based, row 0 at the top)."""
    return [r * n_cols + c for r in range(rows[0], rows[1] + 1) for c in range(cols[0], cols[1] + 1)]


def verdict_of(radial: dict, axial: dict, zones: int) -> tuple:
    """(verdict, why): radial, axial or inconclusive. The same rule for every distance, so three runs can be compared."""
    lo, hi = sorted((radial["rms_mm"], axial["rms_mm"]))
    best_kind = "radial" if radial["rms_mm"] <= axial["rms_mm"] else "axial"
    best = radial if best_kind == "radial" else axial
    if zones < MIN_ZONES:
        return "inconclusive", f"only {zones} valid zones in the window; at least {MIN_ZONES} are needed to part the models"
    if best["rms_mm"] > FLAT_MAX * best["d_m"] * 1000.0:
        return "inconclusive", (f"the better fit ({best_kind}) still leaves {best['rms_mm']} mm rms, over {FLAT_MAX:.0%} of its "
                                f"{best['d_m'] * 1000:.0f} mm: the wall was not flat or the window held more than the wall")
    if hi < RATIO_MIN * max(lo, 0.5):
        return "inconclusive", f"the models fit about equally ({radial['rms_mm']} and {axial['rms_mm']} mm rms): nearer, or a wider window"
    return best_kind, f"{best_kind} leaves {lo} mm rms, the other {hi} mm"


def analyse(frames: list, rows: tuple = (0, ROWS - 1), cols: tuple = (0, COLS - 1), tape_m: float | None = None) -> dict:
    beam_list = beams()
    med, n_frames = median_frame(frames)
    idx = [i for i in window(rows, cols) if med[i] is not None]
    readings = [m if m is not None else 0.0 for m in med]
    radial, axial = fit("radial", readings, idx, beam_list), fit("axial", readings, idx, beam_list)
    verdict, why = verdict_of(radial, axial, len(idx))
    out = {"kind": "range_model", "frames": n_frames, "zones_used": len(idx), "rows": list(rows), "cols": list(cols),
           "radial": radial, "axial": axial, "verdict": verdict, "why": why,
           "median_mm": [None if m is None else round(m) for m in med]}
    if tape_m is not None:
        out["tape_m"] = tape_m
        for k in ("radial", "axial"):               # the sensor's face is not the duck's nose: a few cm of offset is normal, not an error
            out[k]["d_minus_tape_mm"] = round(out[k]["d_m"] * 1000.0 - tape_m * 1000.0, 1)
    return out


def residual_map(frames: list, model: dict, kind: str) -> list:
    """Each zone's median minus the model's reading, mm, as rows of columns: where a wall is not flat or a zone is not wall."""
    med, _ = median_frame(frames)
    fitted = wall_ranges(kind, model["d_m"], model["pitch_deg"], model["yaw_deg"], beams())
    return [[None if med[r * COLS + c] is None else round(med[r * COLS + c] - fitted[r * COLS + c])
             for c in range(COLS)] for r in range(ROWS)]


def table(result: dict, frames: list) -> str:
    lines = [f"depth sensor range model: {result['frames']} frames, {result['zones_used']} zones (rows {result['rows']}, "
             f"columns {result['cols']})" + (f", board at {result['tape_m']} m by tape" if "tape_m" in result else ""),
             f"{'model':<8}{'rms mm':>9}{'D mm':>9}{'pitch deg':>11}{'yaw deg':>9}" + (f"{'D - tape mm':>13}" if "tape_m" in result else "")]
    for k in ("radial", "axial"):
        m = result[k]
        lines.append(f"{k:<8}{m['rms_mm']:>9.2f}{m['d_m'] * 1000:>9.0f}{m['pitch_deg']:>11.2f}{m['yaw_deg']:>9.2f}"
                     + (f"{m['d_minus_tape_mm']:>13.1f}" if "tape_m" in result else ""))
    lines.append(f"verdict: {result['verdict']} ({result['why']})")
    best = "radial" if result["radial"]["rms_mm"] <= result["axial"]["rms_mm"] else "axial"
    lines.append("median frame, mm (row 0 at the top):")
    for r in range(ROWS):
        lines.append("  " + " ".join(f"{'-' if result['median_mm'][r * COLS + c] is None else result['median_mm'][r * COLS + c]:>5}" for c in range(COLS)))
    lines.append(f"{best} fit's residual per zone, mm (the zones that stand out are not part of the wall):")
    for row in residual_map(frames, result[best], best):
        lines.append("  " + " ".join(f"{'-' if v is None else v:>5}" for v in row))
    return "\n".join(lines)


def read_frames(path: Path, n: int, timeout_s: float = 30.0) -> list:
    """n frames from a depth socket's tof.stream (read-only)."""
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5.0)
    s.connect(str(path))
    f = s.makefile("rw")
    f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
    f.flush()
    frames, end = [], time.monotonic() + timeout_s
    try:
        while len(frames) < n:
            if time.monotonic() > end:
                raise SystemExit(f"{len(frames)} of {n} frames in {timeout_s:.0f} s from {path}: is the link up (lab-link check)?")
            line = f.readline()
            if not line:
                raise SystemExit(f"{path} closed after {len(frames)} frames")
            msg = json.loads(line)
            if msg.get("method") == "tof.frame":
                frames.append(msg["params"])
    finally:
        s.close()
    return frames


def _span(text: str) -> tuple:
    lo, _, hi = text.partition("-")
    return int(lo), int(hi or lo)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--socket", type=Path, help="the depth socket (default: the simulator host file's)")
    ap.add_argument("--frames-file", type=Path, help='frames saved as {"frames": [...]} instead of a live socket')
    ap.add_argument("--frames", type=int, default=30, help="frames to take (default 30: the noise averages out, the head stays put)")
    ap.add_argument("--rows", default="0-7", help="the zone rows that see the wall, e.g. 0-5 (row 0 is the top)")
    ap.add_argument("--cols", default="0-7")
    ap.add_argument("--tape-m", type=float, help="the board's distance from the sensor by tape, to show the fit's offset beside it")
    ap.add_argument("--json", action="store_true", help="print JSON, for the profile's `measured` notes, instead of the table")
    a = ap.parse_args(argv)
    rows, cols = _span(a.rows), _span(a.cols)
    if a.frames_file:
        frames = json.loads(a.frames_file.read_text())["frames"]
    else:
        path = a.socket
        if path is None:
            import simhost
            path = simhost.load().sockets["depth"]
        frames = read_frames(path, a.frames)
    result = analyse(frames, rows, cols, a.tape_m)
    print(json.dumps(result, indent=1) if a.json else table(result, frames))
    return 0 if result["verdict"] != "inconclusive" else 2


if __name__ == "__main__":
    sys.exit(main())
