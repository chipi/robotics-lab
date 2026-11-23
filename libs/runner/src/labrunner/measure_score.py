"""The score sheet: the same numbers from recorded runs of the simulated duck and of the real one, side by side (phase 5 item 4b unit B9;
RFC-0002 phase 5: "the same score sheet, simulator vs real, with the commanded/measured speed gain as the first comparison"). Read-only:
it opens finished format 2 runs and changes nothing.

    lab-score-sheet --sim /work/robotics-lab/data/runs/duck/ch10-s1 --real ~/real-runs/duck/room-a      # a folder: every run in it
    lab-score-sheet --sim DIR ... --real DIR ... --json                                                 # JSON for the profile's `measured` notes

An arm is the runs under the paths given (a run folder holds run.mcap; a run still being written is skipped and said). What it scores, per arm:

- the goals' outcomes (each segment's `outcome`: reached, refused, stuck ...), the time and the belief's path length of a reached one;
- events per run that mean trouble: stuck, stalled, reflex_stop, cliff_stop, guardrail, refused, recovery;
- the trunk's tilt (the IMU's, so the real duck has it too): its p99 and largest, in degrees;
- the speed gain, first: straight walking at a constant commanded speed, measured speed over commanded, by commanded speed. Measured two
  ways: by the navigator's belief (the odometry with mapd's corrections: what the duck knows, in both arms) and by the simulator's truth
  (the simulated arm only; a real run has none). The belief path ignores a one-tick jump over STEP_MAX_M, which is a position fix, not a
  step. 1.0 is a duck that walks the speed it is asked; STATUS.md has the simulator walking about 0.13 m/s when asked 0.3.

The real duck has no truth, so its gain by truth is "-" until a tape-measured walk fills it: `lab-measure-walk --tape` records one, and
the odometry scale it gives is what the calibration card keeps. Not scored here: a contact (needs the scene and the truth), a fall by
truth, and the time of a goal that never ended."""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
import sys
from pathlib import Path

STEP_MAX_M = 0.15          # a belief step over this in one tick is a fix, not odometry (probes/odom_by_speed.py)
GAP_MAX_S = 0.5            # ticks further apart than this are two stretches
STRAIGHT_RAD_S = 0.3       # turning at most this is straight enough for a speed (probes/scale_by_speed.py)
MIN_ASKED_MPS = 0.05
SKIP_S, MIN_LEG_S = 1.0, 1.0   # the first second of a leg is the walk getting up to speed; a leg shorter than a second after it is not a speed
TROUBLE = ("stuck", "stalled", "reflex_stop", "cliff_stop", "guardrail", "refused", "recovery")


def legs(ticks: list) -> list:
    """The straight, constant-command stretches of a run: [(asked m/s, belief m/s, truth m/s or None)], one per leg. `ticks` is [(t, payload)].
    A leg is cut at a change of the command, a turn, or a gap; its first SKIP_S is dropped; each speed is path over time of the pairs that
    were not a fix, so a fix does not count as a step nor its time as walking."""
    out, leg = [], []

    def close():
        if leg:
            speed = _leg_speed(leg)
            if speed is not None:
                out.append(speed)
        leg.clear()

    prev = None
    for t, p in ticks:
        cmd = p.get("cmd")
        ok = bool(cmd) and cmd[0] > MIN_ASKED_MPS and abs(cmd[1]) <= STRAIGHT_RAD_S and p.get("belief") is not None
        if not ok or (prev is not None and (t - prev[0] > GAP_MAX_S or abs(cmd[0] - prev[1]) > 0.01)):
            close()
        if ok:
            leg.append((t, p))
            prev = (t, cmd[0])
        else:
            prev = None
    close()
    return out


def _leg_speed(leg: list):
    t0 = leg[0][0] + SKIP_S
    pairs = [(a, b) for a, b in zip(leg, leg[1:]) if a[0] >= t0]
    if not pairs or pairs[-1][1][0] - pairs[0][0][0] < MIN_LEG_S:
        return None
    asked = leg[0][1]["cmd"][0]
    dist = dt = tdist = tdt = 0.0
    for (ta, a), (tb, b) in pairs:
        step = math.dist(a["belief"][:2], b["belief"][:2])
        if step > STEP_MAX_M:
            continue
        dist, dt = dist + step, dt + (tb - ta)
        if a.get("truth") and b.get("truth"):
            tdist, tdt = tdist + math.dist(a["truth"][:2], b["truth"][:2]), tdt + (tb - ta)
    if dt < MIN_LEG_S:
        return None
    return round(asked, 2), dist / dt, (tdist / tdt if tdt >= MIN_LEG_S else None)


def summarise_run(records: list) -> dict:
    """What one run says: its segments (outcome, seconds, belief path), the trouble events, the tilts, the legs."""
    ticks = [(t, p) for t, k, p in records if k == "tick"]
    segments = [p for _, k, p in records if k == "segment"]
    events = collections.Counter(p.get("kind") for _, k, p in records if k == "event")
    out_segments = []
    for s in segments:
        path = 0.0
        pts = [p["belief"] for t, p in ticks if s["t_start"] <= t <= s["t_end"] and p.get("belief") is not None]
        for a, b in zip(pts, pts[1:]):
            d = math.dist(a[:2], b[:2])
            if d <= STEP_MAX_M:
                path += d
        out_segments.append({"outcome": s.get("outcome"), "seconds": s["t_end"] - s["t_start"], "path_m": path})
    tilts = [max(abs(p["tilt"][0]), abs(p["tilt"][1])) for _, p in ticks if p.get("tilt")]
    return {"segments": out_segments, "events": dict(events), "tilt_deg": tilts, "legs": legs(ticks)}


def _p(values: list, q: float):
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))] if s else None


def arm_stats(runs: list) -> dict:
    """One arm's score from its runs' summaries; a number that nothing in the arm could give is None, and the sheet prints '-'."""
    segs = [s for r in runs for s in r["segments"]]
    outcomes = collections.Counter(s["outcome"] for s in segs)
    reached = [s for s in segs if s["outcome"] == "reached"]
    events = collections.Counter()
    for r in runs:
        events.update(r["events"])
    tilts = [t for r in runs for t in r["tilt_deg"]]
    by_speed = collections.defaultdict(lambda: ([], []))
    for r in runs:
        for asked, belief, truth in r["legs"]:
            by_speed[asked][0].append(belief / asked)
            if truth is not None:
                by_speed[asked][1].append(truth / asked)
    return {"runs": len(runs), "goals": len(segs), "outcomes": dict(outcomes),
            "reached_share": len(reached) / len(segs) if segs else None,
            "seconds_p50": statistics.median(s["seconds"] for s in reached) if reached else None,
            "path_m_p50": statistics.median(s["path_m"] for s in reached) if reached else None,
            "trouble_per_run": {k: events[k] / len(runs) for k in TROUBLE if events[k]} if runs else {},
            "tilt_deg_p99": _p(tilts, 0.99), "tilt_deg_max": max(tilts) if tilts else None,
            "gain": {f"{a:.2f}": {"legs": len(b), "belief_p50": statistics.median(b) if b else None,
                                  "truth_p50": statistics.median(t) if t else None}
                     for a, (b, t) in sorted(by_speed.items())}}


def run_dirs(paths: list) -> list:
    out = []
    for p in map(Path, paths):
        out += [p] if (p / "run.mcap").exists() else sorted(f.parent for f in p.rglob("run.mcap"))
    return out


def load_arm(paths: list, warn=print) -> list:
    from runfile.mcapio import Follower, lock_info, writer_alive
    runs = []
    for d in run_dirs(paths):
        if lock_info(d) is not None and writer_alive(d):
            warn(f"skipped, still being written: {d}")
            continue
        try:
            runs.append(summarise_run(Follower(d).poll()))
        except Exception as exc:  # noqa: BLE001 - an unreadable recording is said and left out, not a stop
            warn(f"unreadable, skipped: {d} ({type(exc).__name__}: {exc})")
    return runs


def _f(v, digits=2, unit=""):
    return "-" if v is None else f"{v:.{digits}f}{unit}"


def rows(sim: dict | None, real: dict | None) -> list:
    """The sheet as (metric, sim, real, real over sim) text rows, the speed gain first."""
    def get(arm, key):
        return arm.get(key) if arm else None

    out = []
    speeds = sorted(set((sim or {}).get("gain", {})) | set((real or {}).get("gain", {})))
    for sp in speeds:
        for src in ("belief", "truth"):
            a = ((sim or {}).get("gain", {}).get(sp) or {}).get(f"{src}_p50")
            b = ((real or {}).get("gain", {}).get(sp) or {}).get(f"{src}_p50")
            na = ((sim or {}).get("gain", {}).get(sp) or {}).get("legs", 0)
            nb = ((real or {}).get("gain", {}).get(sp) or {}).get("legs", 0)
            out.append((f"speed gain at {sp} m/s, by {src} (measured / asked, p50)", _f(a, 3) + f" ({na} legs)", _f(b, 3) + f" ({nb} legs)",
                        _f(b / a, 2) if a and b else "-"))
    for label, key, digits in (("runs", "runs", 0), ("goals", "goals", 0), ("reached share", "reached_share", 2),
                               ("reached: seconds p50", "seconds_p50", 1), ("reached: belief path m p50", "path_m_p50", 2),
                               ("trunk tilt deg p99", "tilt_deg_p99", 1), ("trunk tilt deg max", "tilt_deg_max", 1)):
        a, b = get(sim, key), get(real, key)
        out.append((label, _f(a, digits), _f(b, digits), _f(b / a, 2) if a and b else "-"))
    for kind in TROUBLE:
        a, b = ((arm or {}).get("trouble_per_run", {}).get(kind) for arm in (sim, real))
        if a or b:
            out.append((f"{kind} per run", _f(a or 0.0), _f(b or 0.0), "-"))
    out.append(("outcomes", json.dumps((sim or {}).get("outcomes", {})), json.dumps((real or {}).get("outcomes", {})), ""))
    return out


def table(sim: dict | None, real: dict | None) -> str:
    r = rows(sim, real)
    w = max(len(x[0]) for x in r)
    w1 = max(len(x[1]) for x in r + [("", "simulator", "", "")])
    w2 = max(len(x[2]) for x in r + [("", "", "real duck", "")])
    lines = [f"{'metric':<{w}}  {'simulator':<{w1}}  {'real duck':<{w2}}  real/sim"]
    lines += [f"{m:<{w}}  {a:<{w1}}  {b:<{w2}}  {c}" for m, a, b, c in r]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", nargs="*", default=[], type=Path, help="run folders, or folders holding runs, of the simulated duck")
    ap.add_argument("--real", nargs="*", default=[], type=Path, help="the same, of the real duck")
    ap.add_argument("--json", action="store_true", help="print JSON, for the profile's `measured` notes, instead of the table")
    a = ap.parse_args(argv)
    if not (a.sim or a.real):
        ap.error("give --sim or --real (or both) run folders")
    sim = arm_stats(load_arm(a.sim)) if a.sim else None
    real = arm_stats(load_arm(a.real)) if a.real else None
    print(json.dumps({"simulator": sim, "real": real}, indent=1) if a.json else table(sim, real))
    return 0


if __name__ == "__main__":
    sys.exit(main())
