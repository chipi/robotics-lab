"""Replay a recorded run's perception offline, and say whether the log is complete for it (ADR-0014).

    uv run duck-replay duck/apartment/explore13 --miniview-data /work/robotics-lab/data
    uv run duck-replay /path/to/data/runs/duck/apartment/explore13

For every depth frame in the run, the navigator's own code (`FrameView`: the sensor plugin's `depth_points`, `drop_points`,
`blocking_ahead`) is run again on the recorded raw distances and statuses and the paired state, the points are placed
with the recorded pose, and the result is compared with what the navigator derived and logged. A difference means the
navigator used something that is not in the file. Also checked: every tick's `/depth` is a recorded frame's points, the
frames' sensor times only grow, and each frame's pairing is what it says (its state time minus its own). Exit 0 and
`REPLAY PASS` when nothing differs. A run recorded before the file kept what the replay needs (no depth frames; points an older rule
chose and classed, shown by its calibration event not naming the profile) ends `REPLAY N/A` and exit 0, with why (`predates()`).
"""

import argparse
import sys
from pathlib import Path

from runfile import keys
from runfile.catalog import default_data
from runfile.mcapio import FINAL, LIVE, Follower

from duck_lab.plugins.tof8x8 import Tof8x8
from duck_lab.profile import load as load_profile

TOL = 1e-9
SAMPLE = 5            # how many differences are shown, not only counted


def state_of(rec: dict) -> dict:
    """The robot state as the sensor reads it, rebuilt from what the frame record kept of it."""
    s = rec["state"]
    return {"imu": {"quat": s["quat"]}, "odom": {"position": [0.0, 0.0, s["odom_z"]], "yaw": 0.0},
            "frames": {"tof": s["tof"]}}


def _same(a, b) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    return a == b


def calibration_of(records: list) -> dict:
    """The sensor's mounting the run was recorded with (its `calibration` event), else the real duck's defaults: a run from
    before the event existed was recorded with those."""
    for _, k, p in records:
        if k == "event" and p.get("kind") == "calibration" and isinstance((p.get("raw") or {}).get("tof"), dict):
            return p["raw"]["tof"]
    return {"pitch_offset_deg": 3.0, "range_kind": "axial"}


def profile_of(records: list):
    """The robot's profile as the run had it: the environment its `calibration` event names, else the real duck's (a run from
    before the event named it was recorded by a navigator that read its numbers from constants, which are the profile's)."""
    for _, k, p in records:
        if k == "event" and p.get("kind") == "calibration":
            return load_profile(((p.get("raw") or {}).get("profile") or {}).get("variant"))
    return load_profile(None)


def replay(records: list) -> dict:
    """The report for a run's records (read with keep_raw), with the sensor configured as the run was."""

    profile = profile_of(records)
    sensor = Tof8x8(profile, mount=calibration_of(records))
    frames = [(t, p) for t, k, p in records if k == "depth_frame"]
    ticks = [p for _, k, p in records if k == "tick"]
    rep = {"frames": len(frames), "replayed": 0, "no_state": 0, "no_pose": 0, "diffs": [], "pair_dt_ms": [],
           "pair_mismatch": 0, "time_back": 0, "seq_gaps": 0, "ticks": len(ticks), "ticks_with_depth": 0, "ticks_untraced": 0,
           "points": 0, "drop_frames": 0, "blocked_frames": 0}
    seen = set()
    last_ns, last_seq = None, None
    for t, p in frames:
        if last_ns is not None and p["frame_t_ns"] < last_ns:
            rep["time_back"] += 1
        last_ns = p["frame_t_ns"]
        if p.get("seq") is not None:
            if last_seq is not None and p["seq"] != last_seq + 1:
                rep["seq_gaps"] += 1
            last_seq = p["seq"]
        if p.get("pair_dt_ms") is not None:
            rep["pair_dt_ms"].append(p["pair_dt_ms"])
            if p.get("state_t_ns") is None or abs((p["state_t_ns"] - p["frame_t_ns"]) / 1e6 - p["pair_dt_ms"]) > 1e-3:
                rep["pair_mismatch"] += 1
        if "state" not in p:
            rep["no_state"] += 1
            continue
        if "derived" not in p:
            rep["no_pose"] += 1
            continue
        d = p["derived"]
        fv = sensor.derive({"rows": p["rows"], "cols": p["cols"], "distance_mm": p["distance_mm"], "status": p["status"]},
                           state_of(p), None, tuple(p["pose"]))
        rep["replayed"] += 1
        rep["points"] += len(d["points"])
        rep["drop_frames"] += bool(d.get("drop_points"))
        rep["blocked_frames"] += d.get("block_m") is not None
        seen.add(tuple(tuple(q) for q in d["points"]))
        for what, got, want in (("points", fv.points, d["points"]), ("drop_points", [list(x) for x in fv.drops], d.get("drop_points", [])),
                                ("block_m", fv.block, d.get("block_m"))):
            if not _same(got, want):
                rep["diffs"].append({"t": t, "seq": p.get("seq"), "what": what, "replayed": got, "recorded": want})
    for p in ticks:
        if p.get("depth"):
            rep["ticks_with_depth"] += 1
            if tuple(tuple(q) for q in p["depth"]) not in seen:
                rep["ticks_untraced"] += 1
    return rep


def verdict(rep: dict) -> bool:
    return (rep["frames"] > 0 and rep["replayed"] > 0 and not rep["diffs"] and not rep["ticks_untraced"]
            and not rep["pair_mismatch"] and not rep["time_back"])


def _older_points(d: dict) -> bool:
    """A `points` difference where every recorded point is in the same place as one the present code gives, in the same order:
    the present code gives some more points, or some of them another kind (floor, obstacle, below)."""
    if d["what"] != "points":
        return False
    rep, rec = d["replayed"], d["recorded"]
    i = 0
    for q in rec:
        while i < len(rep) and not _same(rep[i][:3], q[:3]):
            i += 1
        if i == len(rep):
            return False
        i += 1
    return len(rep) != len(rec) or any(p[3] != q[3] for p, q in zip(rep, rec))


def predates(records: list, rep: dict) -> str | None:
    """Why a run that does not pass cannot be held to the present code, or None when it can: it was recorded before the file
    kept what the replay needs, which the file shows by what it lacks.
    - it has no depth frames (the navigator did not log them yet), or none with a pose and a paired state: nothing to replay;
    - its `calibration` event does not name the robot's profile (the navigator did not name it yet) and every frame that
      differs differs only as `_older_points` says: no recorded point moved, the present code keeps more of the returns or
      classes some differently (an older rule decided which returns became points, and of what kind; a `block_m` that differs
      with them follows). A run that names its profile, or whose points moved, or whose ticks, pairings or clock do not check
      out, is a failure, not an old run."""
    if not rep["frames"]:
        return "the file has no depth frames: the navigator did not log them when it was recorded, so there is nothing to replay"
    if not rep["replayed"]:
        return (f"none of its {rep['frames']} depth frames has a pose and a paired state ({rep['no_pose']} no pose, {rep['no_state']} no state): "
                "the navigator derived nothing from them (a run cut short before its first fix), so there is nothing to replay")
    cal = next((p for _, k, p in records if k == "event" and p.get("kind") == "calibration"), None)
    named = bool(((cal or {}).get("raw") or {}).get("profile"))
    older = [d for d in rep["diffs"] if _older_points(d)]
    rest = [d for d in rep["diffs"] if d["what"] != "block_m" and not _older_points(d)]
    if older and not rest and not named and not rep["ticks_untraced"] and not rep["pair_mismatch"] and not rep["time_back"]:
        return (f"its calibration event does not name the robot's profile, and the {len({d['seq'] for d in older})} frames that differ "
                "differ only in which returns became points and of what kind (floor, obstacle, below), no recorded point moved: "
                "it was recorded under an older rule for them")
    return None


def resolve(arg: str, data: Path | None) -> Path:
    p = Path(arg)
    if p.is_dir() and ((p / FINAL).exists() or (p / LIVE).exists()):
        return p
    if data is None:
        raise SystemExit(f"{arg} is not a run folder, and there is no data folder (--miniview-data or OBSERVATORY_DATA) to look the key up in")
    d = keys.run_dir(data, arg)
    if not ((d / FINAL).exists() or (d / LIVE).exists()):
        raise SystemExit(f"no run {arg!r} under {data}")
    return d


def report_lines(rep: dict) -> list:
    dts = sorted(abs(x) for x in rep["pair_dt_ms"])
    out = [f"frames {rep['frames']}: replayed {rep['replayed']} ({rep['points']} points; {rep['drop_frames']} with drop points, "
           f"{rep['blocked_frames']} with an obstacle in the corridor), no state {rep['no_state']}, no pose {rep['no_pose']}"]
    if dts:
        out.append(f"pairing: state time minus frame time, |dt| median {dts[len(dts) // 2]:.1f} ms, p95 {dts[int(len(dts) * 0.95)]:.1f} ms, "
                   f"max {dts[-1]:.1f} ms; inconsistent pairings {rep['pair_mismatch']}")
    out.append(f"sensor clock: frames going back in time {rep['time_back']}, gaps in seq {rep['seq_gaps']}")
    out.append(f"ticks with depth {rep['ticks_with_depth']} of {rep['ticks']}: not a recorded frame's points {rep['ticks_untraced']}")
    out.append(f"differences between the replayed and the recorded: {len(rep['diffs'])}")
    for d in rep["diffs"][:SAMPLE]:
        out.append(f"  t={d['t']} seq={d['seq']} {d['what']}: replayed {str(d['replayed'])[:100]} recorded {str(d['recorded'])[:100]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="the run's key (duck/<scene>/<run>) or its folder")
    ap.add_argument("--miniview-data", type=Path, default=None, help="the lab's data folder (default $OBSERVATORY_DATA)")
    args = ap.parse_args()
    data = args.miniview_data or default_data()
    d = resolve(args.run, data)
    f = Follower(d, keep_raw=True)
    records = f.poll()
    print(f"{args.run}: {len(records)} records" + (f", {f.partials} partial and {len(f.errors)} bad messages not read" if f.partials or f.errors else ""))
    rep = replay(records)
    for line in report_lines(rep):
        print(line)
    ok = verdict(rep)
    old = None if ok else predates(records, rep)
    if old:
        print(f"REPLAY N/A: {old}")
        sys.exit(0)
    print("REPLAY PASS" if ok else "REPLAY FAIL" + ("" if rep["frames"] else " (the run has no depth frames)"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
