"""Stuck detection (nav/stuck.py): walking commanded, the belief getting almost nowhere."""

import sys

from duck_lab.nav.stuck import MIN_SAMPLES, StuckWatch

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def walk(watch, seconds, speed, walking=True, hz=10):
    out = None
    for i in range(int(seconds * hz) + 1):
        t = i / hz
        out = watch.update(t, walking, (speed * t, 0.0)) or out
    return out


check("walking at 0.13 m/s (0.3 asked): not stuck", walk(StuckWatch(), 6.0, 0.13) is None)
check("a tight arc at 0.08 m/s: not stuck", walk(StuckWatch(), 6.0, 0.08) is None)
# ch16-s1 2026-11-17 at the bar: 0.3 asked, the belief 1-2 cm a second
at_bar = walk(StuckWatch(), 6.0, 0.015)
check("at the bar: 0.3 m/s asked, the belief 1.5 cm a second: stuck, with the evidence",
      at_bar is not None and at_bar["moved_m"] < 0.05 and at_bar["seconds"] >= 2.7, at_bar)
check("standing (not walking): never stuck", walk(StuckWatch(), 6.0, 0.0, walking=False) is None)
w = StuckWatch()
for i in range(MIN_SAMPLES - 1):
    w.update(i * 0.1, True, (0.0, 0.0))
check("too few samples: no verdict", w.update(0.95, True, (0.0, 0.0)) is None)
w2 = StuckWatch()
walk(w2, 2.0, 0.0)
w2.update(2.1, False, (0.0, 0.0))
check("a stop clears the window: the next stretch starts fresh", len(w2.samples) == 0)

print("STUCK", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
