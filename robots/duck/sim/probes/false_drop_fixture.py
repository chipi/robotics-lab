"""Write tests/fixtures/flat_false_stops.json: the challenge course's flat-floor runs (recorded before the tof calibration) in
which the cliff check, with the real duck's mounting, stopped for a drop that was not there: each run's depth frames (raw
readings and the state they were paired with) from LEAD_S before that stop to TAIL_S after. test_cliff.py replays them.

    uv run python sim/probes/false_drop_fixture.py /work/robotics-lab/data
"""

import json
import sys
from pathlib import Path

from runfile import keys
from runfile.mcapio import Follower

from duck_lab.nav import cliff
from duck_lab.replay import state_of

STOP_M, FRAMES_NEEDED, LEAD_S, TAIL_S = 0.6, 3, 3.0, 1.0
OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "flat_false_stops.json"


def main() -> None:
    data = Path(sys.argv[1])
    cliff.configure()
    runs = []
    for run_dir in sorted((data / "runs" / "duck").glob("ch*/*")):
        if json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text()).get("hazards"):
            continue
        records = Follower(run_dir, keep_raw=True).poll()
        if any(k == "event" and p.get("kind") == "calibration" for _, k, p in records):
            continue
        frames, streak, stop = [], 0, None
        for t, kind, p in records:
            if kind != "depth_frame" or "state" not in p or "derived" not in p:
                continue
            if stop is not None and t > stop + TAIL_S:
                break
            frames.append({"t": round(t, 3), "distance_mm": p["distance_mm"], "status": p["status"], "state": state_of(p)})
            pts = cliff.drop_points({"distance_mm": p["distance_mm"], "status": p["status"]}, state_of(p))
            streak = streak + 1 if pts else 0
            if stop is None and streak >= FRAMES_NEEDED and min(x[2] for x in pts) < STOP_M:
                stop = t
        if stop is not None:
            runs.append({"run": keys.key_of(data, run_dir), "stop_t": round(stop, 3),
                         "frames": [f for f in frames if f["t"] >= stop - LEAD_S]})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"why": __doc__.split("\n\n")[0], "stop_m": STOP_M, "frames_needed": FRAMES_NEEDED, "runs": runs},
                              separators=(",", ":")))
    print(f"{len(runs)} runs, {sum(len(r['frames']) for r in runs)} frames -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
