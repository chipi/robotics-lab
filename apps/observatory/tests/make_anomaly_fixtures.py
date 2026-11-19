"""Cut the anomaly detectors' fixtures out of real recordings (RFC-0019): slices of a navigator log (ticks.jsonl, start.json),
trimmed to the fields a detector reads. Run once, by hand, where the recordings are; the slices are committed, this script is
how they were made. Read-only on the sources.

    cd apps/observatory && uv run python tests/make_anomaly_fixtures.py [RUNS_ROOT]

RUNS_ROOT holds the navigator's own logs (default /work/robotics-lab/explore/duck/runs; the gate12 runs and b11 are under
/work/robotics-lab/mission-control/robots/duck/runs). What each slice is for is in tests/fixtures/anomalies/README.md.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "fixtures" / "anomalies"
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/work/robotics-lab/explore/duck/runs")
GATE12 = Path("/work/robotics-lab/mission-control/robots/duck/runs")
TICK_KEEP = ("pose", "vx", "vyaw", "tilt", "t", "truth")
EVENTS = {"glance", "refused", "leg", "trapped", "no_frontier_left", "tight_pivot", "stalled"}


def cut(name: str, src: Path, t0: float, t1: float, world: str = "none", start: bool = True) -> None:
    """Rows of src with t0 <= t <= t1: ticks trimmed, the named events whole; `world`: "none", "all" (every world row in the
    window), "first" (the first one at or after t0), "last" (the last one at or before t1, wherever it came)."""
    rows, last_world = [], None
    for line in (src / "ticks.jsonl").open():
        r = json.loads(line)
        t = r.get("t")
        if not isinstance(t, (int, float)):
            continue
        ev = r.get("event")
        if ev == "world":
            if t <= t1:
                last_world = r
            if t0 <= t <= t1 and world in ("all", "first") and not (world == "first" and any(x.get("event") == "world" for x in rows)):
                rows.append(r)
            continue
        if not t0 <= t <= t1:
            continue
        if ev is None:
            rows.append({k: r[k] for k in TICK_KEEP if k in r})
        elif ev in EVENTS:
            rows.append(r)
    if world == "last" and last_world is not None:
        rows.append(last_world)
    rows.sort(key=lambda r: r["t"])
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "ticks.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    if start and (src / "start.json").exists():
        (d / "start.json").write_text((src / "start.json").read_text())
    print(f"{name}: {len(rows)} rows, {(d / 'ticks.jsonl').stat().st_size} bytes")


if __name__ == "__main__":
    cut("graze_b10b_r2", ROOT / "explore-b10b-r2", 184.0, 192.0)
    cut("stall_ch17_s1", GATE12 / "gate12-ch17/ch17-s1/run-20261118-235632", 20.0, 33.0)
    cut("odometry_before_ch11_s1", ROOT / "gate3-ch11/ch11-s1/run-20261118-002645", 0.0, 1e9)
    cut("odometry_after_ch11_s1", ROOT / "gate4-ch11/ch11-s1/run-20261118-005452", 0.0, 1e9)
    cut("edge_b11_r2", GATE12 / "explore-b11-r2", 20.0, 42.0, world="last")
    cut("dock_b9_r2", ROOT / "explore-b9-r2", 28.0, 31.0, world="first")
    cut("nothing_left_b11_r1", GATE12 / "explore-b11-r1", 1030.0, 1041.0, world="last")
