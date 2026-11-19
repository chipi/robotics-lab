"""What the recovery would do at each recorded "no room to turn" refusal (nav/recovery.py): from the refusal's own record (the pose,
the depth sensor's nearest return, the remembered drops and obstacle points near), the motion recovery.choose picks for the
first attempt. Open loop: it says which refusals have a motion to try and which only get the survey, not whether the motion
frees the duck.

    .venv/bin/python sim/probes/recovery_replay.py /work/robotics-lab/mission-control/duck/runs/explore-b11-r{2,3,4,5}
"""

import json
import sys
from pathlib import Path

from duck_lab.nav import recovery

for run in map(Path, sys.argv[1:]):
    print(f"== {run.name}")
    rows = [json.loads(line) for line in open(run / "ticks.jsonl") if '"event": "refused"' in line]
    for r in rows:
        if "no room to turn" not in (r.get("why") or r["decision"]["reason"]):
            continue
        pose = tuple(r["pose"])
        drops = [tuple(d) for d in r.get("drops", [])]
        blocked = [tuple(b) for b in r.get("blocked", [])]
        haz = recovery.hazard(pose, drops, blocked)
        front = recovery.drop_ahead(pose, drops)
        mm = r.get("nearest_mm")
        now, ahead = recovery.projected_room(pose, blocked, recovery.CREEP_M)
        gains = recovery.creep_gains_room(now, ahead, 0.17)
        print(f"t {r['t']:6.1f} room {r.get('room_m')} nearest_mm {mm} nearest drop {r.get('nearest_drop_m')}: "
              f"drop in front {front}, hazard {haz[1] if haz else None}, points: room {now:.3f} -> {ahead:.3f} m ahead -> "
              f"{recovery.choose(0, mm, front, haz, gains)}")
