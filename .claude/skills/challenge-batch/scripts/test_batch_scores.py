"""python3 -m unittest discover -s .claude/skills/challenge-batch/scripts"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("batch_scores.py")


def tick(t, x, y, yaw, rvx, rvyaw):
    return {"t": t, "pose": [x, y, yaw], "requested": {"vx": rvx, "vyaw": rvyaw}, "applied": {"vx": rvx, "vyaw": rvyaw}}


def write_run(root, scene, passed, ticks):
    d = root / scene / "run-1"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"scene": scene, "pass": passed, "failed": [] if passed else ["stalled"],
                                               "build": {"id": "duck@abc-learned@x-s1", "dirty": False}}))
    (d / "ticks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ticks))


def score(root):
    out = root / "scores.jsonl"
    subprocess.run([sys.executable, str(SCRIPT), str(root), "--min-items", "1", "--out", str(out)], capture_output=True, check=False)
    return {r["item_id"]: r for r in map(json.loads, out.read_text().splitlines())}


class FailureMetrics(unittest.TestCase):
    def test_stand_still_and_pivot_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, "walks", True, [tick(i / 10, i * 0.02, 0, 0, 0.2, 0) for i in range(60)])
            write_run(root, "stands", False, [tick(i / 10, 0.001 * (i % 2), 0, 0, 0.2, 0) for i in range(60)])
            write_run(root, "pivot_stalls", False, [tick(i / 10, 0, 0, 0.001 * i, 0.0, 1.2) for i in range(60)])
            write_run(root, "pivot_turns", True, [tick(i / 10, 0, 0, 0.08 * i, 0.0, 1.2) for i in range(40)]
                      + [tick(4 + i / 10, i * 0.02, 0, 3.12, 0.2, 0) for i in range(30)])
            rows = score(root)
        self.assertEqual({k: (r["stand_still"], r["pivot_fail"]) for k, r in rows.items()},
                         {"walks": (0, 0), "stands": (1, 0), "pivot_stalls": (1, 1), "pivot_turns": (0, 0)})


if __name__ == "__main__":
    unittest.main()
