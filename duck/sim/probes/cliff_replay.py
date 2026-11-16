"""The cliff fix (calibration/sim.json "tof": the simulator's sensor has no pitch offset and reads along the ray), replayed
on the challenge course's recorded runs: the OLD cliff.py from git (the baseline worktree) beside the NEW one from the
working tree configured as the simulator now is, on every recorded depth frame and its paired state.

    eval "$(~/.claude/skills/replay-proven-fix/scripts/baseline_worktree.sh <rev before the fix>)"
    uv run python sim/probes/cliff_replay.py /work/robotics-lab/data "$BASELINE_DIR/duck/src/duck_lab/nav/cliff.py"

The corpus is the runs recorded before the fix (no `calibration` event): the old code can only reproduce those. A cliff stop
is the navigator's rule: a drop within STOP_M ahead in FRAMES_NEEDED frames in a row. Pass criteria (exit 1 when one fails):
  1. faithful: the old code reproduces every recorded frame's drop_points (else the replay says nothing);
  2. on flat floor (scenes with no drop): the new code makes no cliff stop;
  3. at a real drop: the new code still finds the drop in every run.
When the new code stops at a real drop is printed, not judged: each recorded run ends where the OLD code stopped (it stopped
there, or turned away), so a replay cannot see what the duck would have seen walking on. Whether it stops in time is the
closed loop's question: the challenges run again with the fix (duck-challenge 8 and 9, the judge's 0.15 m drop margin).
"""

import importlib.util
import json
import sys
from pathlib import Path

from miniview import keys
from miniview.mcapio import Follower

from duck_lab.replay import state_of

STOP_M, FRAMES_NEEDED = 0.6, 3
SIM_TOF = json.loads((Path(__file__).resolve().parents[2] / "calibration" / "sim.json").read_text())["tof"]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def first_stop(times: list, drops: list) -> float | None:
    """The navigator's rule (run.py, go_to): the streak counts consecutive frames with any drop point; it stops once the streak
    reaches FRAMES_NEEDED and the frame's nearest drop is nearer than STOP_M (while walking forward, which a replay of
    frames cannot see: every frame is taken as walking)."""
    streak = 0
    for t, d in zip(times, drops):
        streak = streak + 1 if d is not None else 0
        if streak >= FRAMES_NEEDED and d < STOP_M:
            return t
    return None


def main() -> None:
    data, old_path = Path(sys.argv[1]), Path(sys.argv[2])
    old = load(old_path, "cliff_old")
    new = load(Path(__file__).resolve().parents[2] / "src" / "duck_lab" / "nav" / "cliff.py", "cliff_new")
    # a third argument "<pitch offset deg>,<axial|radial>" tries another mounting than calibration/sim.json's
    offset, range_kind = (sys.argv[3].split(",") if len(sys.argv) > 3 else (SIM_TOF["pitch_offset_deg"], SIM_TOF["range"]))
    new.configure(float(offset), range_kind)
    print(f"the new code's mounting: {float(offset)} deg, {range_kind}")
    rows, unfaithful, frames_total, after_fix = [], 0, 0, 0
    for run_dir in sorted((data / "runs" / "duck").glob("ch*/*")):
        scene = run_dir.parent.name
        flat = not json.loads((data / "scenes" / scene / "scene.json").read_text()).get("hazards")
        records = Follower(run_dir, keep_raw=True).poll()
        if any(k == "event" and p.get("kind") == "calibration" for _, k, p in records):
            after_fix += 1      # recorded with the fix: the old code cannot reproduce it
            continue
        times, d_old, d_new, n_old, n_new = [], [], [], 0, 0
        for t, kind, p in records:
            if kind != "depth_frame" or "state" not in p or "derived" not in p:
                continue        # a frame the navigator derived nothing from (no pose yet): it decided nothing on it
            frames_total += 1
            fr, st = {"distance_mm": p["distance_mm"], "status": p["status"]}, state_of(p)
            po, pn = old.drop_points(fr, st), new.drop_points(fr, st)
            recorded = (p.get("derived") or {}).get("drop_points") or []
            # the recorded drop points are (ahead, left) after FrameView's placement; compare presence and count, the decision
            unfaithful += bool(po) != bool(recorded) or len(po) != len(recorded)
            times.append(t)
            d_old.append(min(x[2] for x in po) if po else None)
            d_new.append(min(x[2] for x in pn) if pn else None)
            n_old += bool(po)
            n_new += bool(pn)
        rows.append({"run": keys.key_of(data, run_dir), "challenge": scene.split("-")[0], "flat": flat, "drop_frames_old": n_old,
                     "drop_frames_new": n_new, "stop_old": first_stop(times, d_old), "stop_new": first_stop(times, d_new)})
    flat_rows, drop_rows = [r for r in rows if r["flat"]], [r for r in rows if not r["flat"]]
    print("challenge  runs  drop-frames old -> new   cliff stops old -> new")
    for ch in sorted({r["challenge"] for r in rows}):
        rs = [r for r in rows if r["challenge"] == ch]
        print(f"{ch:9s}  {len(rs):4d}  {sum(r['drop_frames_old'] for r in rs):7d} -> {sum(r['drop_frames_new'] for r in rs):<7d}"
              f"   {sum(r['stop_old'] is not None for r in rs):5d} -> {sum(r['stop_new'] is not None for r in rs)}")
    print(f"runs recorded with the fix, left out: {after_fix}")
    blind = [r for r in drop_rows if not r["drop_frames_new"]]
    flat_stops = [r for r in flat_rows if r["stop_new"] is not None]
    checks = [(f"faithful: the old code reproduces every recorded frame's drop decision ({frames_total} frames)",
               unfaithful == 0 and frames_total > 0, unfaithful),
              (f"flat floor: no cliff stop with the new code ({len(flat_rows)} runs)", flat_rows and not flat_stops, [r["run"] for r in flat_stops]),
              (f"real drops: the new code still finds the drop in every run ({len(drop_rows)} runs)", drop_rows and not blind,
               [r["run"] for r in blind])]
    for name, ok, detail in checks:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    both = [round(r["stop_new"] - r["stop_old"], 2) for r in drop_rows if r["stop_old"] is not None and r["stop_new"] is not None]
    print(f"real drops (not judged, see the docstring): the new code stops in {sum(r['stop_new'] is not None for r in drop_rows)} of "
          f"{len(drop_rows)} recorded runs; where both stop, it stops {min(both)} to {max(both)} s after the old" if both else "no stops to compare")
    Path("/tmp/claude-1000/-work-robotics-lab-main/383fa319-167e-4bf1-b893-9d2be48b8b84/scratchpad/cliff_replay.json").write_text(json.dumps(rows, indent=1))
    print("CLIFF REPLAY", "PASS" if all(ok for _, ok, _ in checks) else "FAIL")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
