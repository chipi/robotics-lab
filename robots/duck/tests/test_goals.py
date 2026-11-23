"""Phase 1's fixed goals (sim/phase1_goals.json): what duck-eval measures against, unchanged unless on purpose."""

import json
import sys

from labrunner.evaluate import draw_goals
from labrunner import geometry
from labrunner.geometry import clearance, obstacles

GOAL_CLEARANCE_M = geometry.profile().footprint.goal_clearance_m
GOALS = geometry.goals_path()
LAYOUT = geometry.layout_path()

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


layout = json.loads(LAYOUT.read_text())
fixed = [tuple(g) for g in json.loads(GOALS.read_text())["goals"]]
check("20 fixed goals", len(fixed) == 20, len(fixed))
drawn = draw_goals(layout, 20, 1)
# If this fails, the layout changed: the yardstick would move. Decide on purpose, then re-freeze the file.
check("the file equals today's draw from the layout (seed 1)", fixed == drawn,
      [g for g in fixed if g not in drawn] + [g for g in drawn if g not in fixed])
obs = obstacles(layout, landmarks=False)
tight = [(g, round(clearance(g[:2], obs)[0], 3)) for g in fixed if clearance(g[:2], obs)[0] < GOAL_CLEARANCE_M]
check(f"every goal keeps {GOAL_CLEARANCE_M} m from everything in the layout, the free bodies included", not tight, tight)

print("GOALS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
