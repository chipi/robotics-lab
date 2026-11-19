"""Look before you step: the strip ahead and its unseen spots. Run: cd robots/duck && uv run python tests/test_step_check.py"""

import math
import sys

from duck_lab.plugins.tof8x8 import Tof8x8
from duck_lab.profile import load

SENSOR = Tof8x8(load("sim"))
FROM_M, TO_M, HALF_WIDTH_M = SENSOR.view.from_m, SENSOR.view.to_m, SENSOR.view.half_width_m
strip, unseen_ahead = SENSOR.strip, SENSOR.unseen_ahead

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def seen_box(x0, x1, y0, y1):
    return lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1


straight = [(x / 10, 0.0) for x in range(1, 11)]
s = strip(straight, (0.0, 0.0, 0.0))
xs = [p[0] for p in s]
check("the strip lies between FROM_M and TO_M along the path", s and min(xs) >= FROM_M - 1e-9 and max(xs) <= TO_M + 1e-9,
      (min(xs), max(xs)))
check("... and across the duck's width", max(abs(p[1]) for p in s) <= HALF_WIDTH_M + 1e-9 and
      max(abs(p[1]) for p in s) >= HALF_WIDTH_M - 0.05)
check("all seen floor: nothing to look at", unseen_ahead(straight, (0.0, 0.0, 0.0), seen_box(-1, 2, -1, 1)) is None)
check("unseen beyond the strip does not stop the duck",
      unseen_ahead(straight, (0.0, 0.0, 0.0), seen_box(-1, 0.45, -1, 1)) is None)
# b2 r2's corner: walking east along a hole's south edge, the hole's corner 5 cm to the left of the duck's way
hole = seen_box(-1, 2, -1, 0.07)                 # floor seen up to y 0.07; beyond it, never seen (the opening)
u = unseen_ahead(straight, (0.0, 0.0, 0.0), hole)
check("the stairwell corner: an unseen spot inside the duck's width, to look at", u is not None and u[1] > 0.07, u)
check("... the nearest one first", u is not None and abs(u[0] - FROM_M) < 1e-6, u)
check("a spot already looked at is skipped", unseen_ahead(straight, (0.0, 0.0, 0.0), hole, skip=[u]) != u)
bend = [(0.1, 0.0), (0.2, 0.0), (0.2, 0.1), (0.2, 0.2), (0.2, 0.3), (0.2, 0.4)]
sb = strip(bend, (0.0, 0.0, 0.0))
check("the strip follows a bend in the path", any(p[1] > 0.15 for p in sb) and all(p[0] <= 0.2 + HALF_WIDTH_M + 1e-9 for p in sb))
check("an empty path: nothing to check", strip([], (0.0, 0.0, 0.0)) == [])
check("a short path ending in the blind zone: nothing to check", strip([(0.1, 0.0)], (0.0, 0.0, 0.0)) == [])

print("STEP_CHECK", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
