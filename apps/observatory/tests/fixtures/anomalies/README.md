# Anomaly fixtures

Slices of real navigator logs (`ticks.jsonl`, `start.json`), cut by `../../make_anomaly_fixtures.py`
and read by `../../test_anomalies.py` (RFC-0019). Tick rows keep only pose, truth, speed, tilt and
time; the events the detectors read are whole; a `world` row is whole.

| Slice | Source (run, window) | The anomaly it was |
| --- | --- | --- |
| `graze_b10b_r2` | explore-b10b-r2, 184-192 s | a graze on `kit_stool2`: 0.0709 m, then a contact, from 187.7 s |
| `stall_ch17_s1` | gate12 ch17 seed 1 (`run-20261118-235632`), 20-33 s | a stall at a bar: walking, 0.067 m in 3 s from 27.1 s |
| `odometry_before_ch11_s1` | gate3 ch11 seed 1 (`run-20261118-002645`), whole | odometry 0.89 of the truth, before the odometry fix |
| `odometry_after_ch11_s1` | gate4 ch11 seed 1 (`run-20261118-005452`), whole | the same challenge after the fix: in the band |
| `edge_b11_r2` | explore-b11-r2, 20-42 s, and its last map | the stairwell's rim placed 0.27 m (median) off, then refusals, then "trapped" |
| `dock_b9_r2` | explore-b9-r2, 28-31 s and the first map (t = 30.9 s) | the 3-cell cluster by the dock: the cube `obj_3`, a phantom only if the truth lacks it |
| `nothing_left_b11_r1` | explore-b11-r1, 1030-1041 s and the last map | "nothing left to explore" with the kitchen 0.10 and the bedroom 0.38 covered |
