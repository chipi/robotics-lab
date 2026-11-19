"""A recorded session (record_session.py) with the simulator's truth for its odometry: state.jsonl's odom position (x, y) and yaw
replaced by the truth's, interpolated to each state's t_ns, so that maploc's replay bench places every frame where the
simulator had the robot and the only error left in the grid is the sensor model. tof.jsonl is copied as it is.

    uv run python sim/probes/truth_odometry.py SESSION OUT_DIR
"""

import bisect
import json
import math
import shutil
import sys
from pathlib import Path


def yaw_of(quat) -> float:
    w, x, y, z = quat
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def main() -> None:
    session, out = Path(sys.argv[1]), Path(sys.argv[2])
    truth = [json.loads(line) for line in (session / "truth.jsonl").read_text().splitlines()]
    ts = [r["t_ns"] for r in truth]
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(session / "tof.jsonl", out / "tof.jsonl")
    shutil.copy(session / "truth.jsonl", out / "truth.jsonl")
    n = 0
    with open(out / "state.jsonl", "w") as fh:
        for line in (session / "state.jsonl").read_text().splitlines():
            rec = json.loads(line)
            t = rec["params"]["t_ns"]
            i = min(max(bisect.bisect_left(ts, t), 1), len(ts) - 1)
            a, b = truth[i - 1], truth[i]
            k = 0.0 if b["t_ns"] == a["t_ns"] else min(max((t - a["t_ns"]) / (b["t_ns"] - a["t_ns"]), 0.0), 1.0)
            ya, yb = yaw_of(a["quat"]), yaw_of(b["quat"])
            odom = rec["params"]["odom"]
            odom["position"][0] = a["trunk"][0] + k * (b["trunk"][0] - a["trunk"][0])
            odom["position"][1] = a["trunk"][1] + k * (b["trunk"][1] - a["trunk"][1])
            odom["yaw"] = ya + k * math.atan2(math.sin(yb - ya), math.cos(yb - ya))
            fh.write(json.dumps(rec) + "\n")
            n += 1
    print(f"{n} state samples with the truth's x, y, yaw -> {out}")


if __name__ == "__main__":
    main()
