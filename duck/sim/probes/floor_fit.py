"""Which sensor mounting puts the simulator's flat floor on the floor? Over the challenge course's flat-floor runs recorded
before the tof calibration existed (no `calibration` event: the same frames are in the later runs), every valid return of a
zone pointing at least DOWN_DEG below the horizontal is placed with each mounting (a pitch offset in 0.5 deg steps, readings
radial, and the real duck's 3 deg axial for comparison), and its height above the floor kept when within BAND of it. The
heights are binned by range (0.1 m); a mounting's misfit is the mean |median height| over the bins from 0.3 to 0.9 m. The
right mounting places the floor at 0 at every range: a wrong pitch offset tilts it (the error grows with range), a wrong
range kind scales it.

    uv run python sim/probes/floor_fit.py /work/robotics-lab/data

Exit 1 unless the simulator's calibration (calibration/sim.json "tof") has the smallest misfit.
"""

import json
import math
import sys
from pathlib import Path

from runfile.mcapio import Follower

from duck_lab.nav import cliff
from duck_lab.replay import state_of

DOWN_DEG, BAND, MIN_BIN = 12.0, 0.15, 200
BINS = [round(0.3 + 0.1 * i, 1) for i in range(7)]
MOUNTINGS = [(o / 2, "radial") for o in range(0, 9)] + [(3.0, "axial")]
SIM_TOF = json.loads((Path(__file__).resolve().parents[2] / "calibration" / "sim.json").read_text())["tof"]


def main() -> None:
    data = Path(sys.argv[1])
    heights = {m: {b: [] for b in BINS} for m in MOUNTINGS}
    runs = 0
    sin_down = math.sin(math.radians(DOWN_DEG))
    for run_dir in sorted((data / "runs" / "duck").glob("ch*/*")):
        if json.loads((data / "scenes" / run_dir.parent.name / "scene.json").read_text()).get("hazards"):
            continue
        records = Follower(run_dir, keep_raw=True).poll()
        if any(k == "event" and p.get("kind") == "calibration" for _, k, p in records):
            continue
        runs += 1
        for _, kind, p in records:
            if kind != "depth_frame" or "state" not in p:
                continue
            st = state_of(p)
            for m in MOUNTINGS:
                cliff.configure(*m)
                height, q = cliff.sensor_pose(st)
                for i, beam in enumerate(cliff.BEAMS):
                    if p["status"][i] not in cliff.VALID or p["distance_mm"][i] <= 0:
                        continue
                    d = cliff.rotate(q, beam)
                    if d[2] > -sin_down:
                        continue
                    r = cliff.along_beam(p["distance_mm"][i], beam)
                    z = height + r * d[2]
                    b = round(r, 1)
                    if abs(z) < BAND and b in heights[m]:
                        heights[m][b].append(z)
    cliff.configure()
    print(f"{runs} flat-floor runs; median height of the floor returns (mm) by range")
    print("  mounting          " + "".join(f"{b:>8.1f}m" for b in BINS) + "   misfit")
    misfit = {}
    for m in MOUNTINGS:
        med = {}
        for b, zs in heights[m].items():
            if len(zs) >= MIN_BIN:
                zs.sort()
                med[b] = zs[len(zs) // 2]
        misfit[m] = sum(abs(z) for z in med.values()) / len(med) if med else math.inf
        print(f"  {m[0]:3.1f} deg {m[1]:6s}   " + "".join(f"{med[b] * 1000:+9.1f}" if b in med else "        -" for b in BINS)
              + f"   {misfit[m] * 1000:5.1f}")
    sim = (float(SIM_TOF["pitch_offset_deg"]), SIM_TOF["range"])
    best = min(misfit, key=misfit.get)
    ok = runs > 0 and sim in misfit and misfit[sim] == misfit[best]
    print(f"best fit: {best[0]} deg {best[1]}; the simulator's calibration: {sim[0]} deg {sim[1]}")
    print("FLOOR FIT", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
