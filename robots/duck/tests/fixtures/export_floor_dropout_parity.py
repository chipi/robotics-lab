"""Writes tests/fixtures/floor_dropout_parity.json: random frames and, for each, the floor-validity impairment's own drop probability from
microduck-nav's `zone_dropout_probability` (src/microduck_nav/impairments.py:104-118), for test_local_controller.py to hold `far_floor` to.
Run, from a microduck-nav checkout's environment (it needs torch, which the duck's does not have):
  /work/microduck-nav/.venv/bin/python robots/duck/tests/fixtures/export_floor_dropout_parity.py
The calibration is the nominal one (midpoint offset 0, no episode draws) and the other dropouts are off, so the probability is the floor's alone.
Generated against microduck-nav at the commit named in the file."""

import json
import random
import subprocess
from pathlib import Path

import torch
from microduck_nav import impairments as imp

N, ZONES = 300, 64
rng = random.Random(7)
cfg = imp.ToFRandomization(invalid_zone_probability=0.0, near_floor_edge_impairment_probability=0.0)
cal = imp.Calibration(latency_frames=torch.zeros(1, dtype=torch.long), distance_bias=torch.zeros(1, 1), distance_scale=torch.ones(1, 1),
                      noise_std=torch.zeros(1, 1), floor_validity_midpoint_offset_m=torch.zeros(1, 1),
                      near_floor_edge_survival_probability=torch.ones(1, 1), zone_bias=torch.zeros(1, ZONES), edge_column=torch.full((1, 1), -1))
edges = [0.0, 0.12, 0.3, 0.55, 0.5549, 0.5551, 0.5559, 0.5561, 0.57, 0.6, 0.8, 1.2, 2.0, 3.9, 4.0]
frames = []
for _ in range(N):
    depth = [rng.choice(edges) if rng.random() < 0.3 else round(rng.uniform(0.0, 4.0), 4) for _ in range(ZONES)]
    floor = [rng.random() < 0.5 for _ in range(ZONES)]
    ideal, hit = torch.tensor([depth], dtype=torch.float32), torch.tensor([floor])
    p = imp.zone_dropout_probability(ideal, hit, cal, cfg)[0]
    frames.append({"depth_m": depth, "floor": floor, "drop_probability": [float(x) for x in p]})
repo = Path(imp.__file__).resolve().parents[2]
rev = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
out = Path(__file__).resolve().parent / "floor_dropout_parity.json"
out.write_text(json.dumps({"source": f"microduck-nav {rev} impairments.py zone_dropout_probability, nominal calibration, other dropouts off",
                           "midpoint_m": imp.ToFRandomization().floor_validity_transition_m[0], "frames": frames}) + "\n")
print(f"wrote {out}: {N} frames, {rev}")
