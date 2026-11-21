"""A goal's guardrails (RFC-0014 §3.4.8, duck_lab/nav/guardrails.py): the keep-out points of a no-go area, the speed cap and
the clock (the navigator's `Guard`, which reads no truth), and each truth check (the runner's `TruthGuard`, RFC-0021 step 6)
against a stand-in truth and a small layout. No simulator.
Run: cd robots/duck && uv run python tests/test_guardrails.py"""

import threading
import time

from duck_lab.nav.guardrails import Guard, TruthGuard, keepout_points

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


class Nav:
    def __init__(self):
        self.speed_cap = None
        self.keepout = []


def box(name, x, y, hx=0.2, hy=0.2):
    return {"name": name, "type": "box", "pos": [x, y, 0.2], "size": [hx, hy, 0.2], "yaw": 0.0, "collides": True}


LAYOUT = ([box("sofa", 2.0, 0.0)], [box("stairs", -2.0, 0.0, 0.3, 0.3)])
NO_GO = {"name": "no_go_area", "area": "stairwell", "outline": [[1.0, -1.0], [1.5, -1.0], [1.5, 1.0], [1.0, 1.0]]}
STANDING = 0.116


def guard(nav, rails, broke=None):
    return Guard(nav, rails, (broke or (lambda n, d: None)), t0=100.0)


def at(x, y):
    return (x, y, 0.0)


# --- keep-out points -------------------------------------------------------------------------------
pts = keepout_points([(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)])
check("a no-go area's keep-out is points over it, 5 cm apart", 100 < len(pts) < 400 and (0.25, 0.25) in [(round(x, 2), round(y, 2)) for x, y in pts], len(pts))
thin = keepout_points([(0, 0), (1.0, 0), (1.0, 0.02), (0, 0.02)])
check("a thin area still blocks: its outline is points too", len(thin) >= 20 and max(p[0] for p in thin) >= 0.99, len(thin))

# --- arming ------------------------------------------------------------------------------------------
nav = Nav()
g = guard(nav, [{"name": "max_speed", "mps": 0.2}, {"name": "max_speed", "mps": 0.15}, NO_GO])
g.arm()
g.stop()
check("the speed cap is the strictest of the list", nav.speed_cap == 0.15)
check("the no-go area's points are the planner's obstacles", len(nav.keepout) > 100 and all(1.0 - 1e-6 <= x <= 1.5 + 1e-6 for x, _ in nav.keepout))
nav = Nav()
guard(nav, [{"name": "contact"}]).arm()
check("no speed cap and no keep-out when the list has none", nav.speed_cap is None and nav.keepout == [])

# --- the navigator's checks: the clock only --------------------------------------------------------------
g = guard(Nav(), [{"name": "time_limit", "seconds": 30.0}])
check("time_limit: not yet, then spent", g.check(now=120.0) is None and g.check(now=131.0)[0] == "time_limit")
check("the navigator lists as checked only what it can check: no truth one",
      Guard(Nav(), [{"name": "contact"}, {"name": "time_limit", "seconds": 5.0}, {"name": "stuck"}, NO_GO], lambda *_: None).checked
      == ["time_limit", "stuck", "no_go_area"])

# --- the runner's checks, by the truth ---------------------------------------------------------------------
t = TruthGuard([{"name": "fall"}], layout=LAYOUT)
check("fall: standing is fine", t.check(at(0, 0), STANDING) is None)
check("fall: the trunk down is a fall", t.check(at(0, 0), 0.03)[0] == "fall")
t = TruthGuard([{"name": "contact"}], layout=LAYOUT)
check("contact: 0.8 m from the sofa is clear", t.check(at(1.0, 0.0), STANDING) is None)
c = t.check(at(1.75, 0.0), STANDING)
check("contact: the trunk centre within 8.3 cm of the sofa's outline, a part can touch it", c and c[0] == "contact" and "sofa" in c[1], c)
check("contact: 0.2 m from the outline is clear", t.check(at(1.6, 0.0), STANDING) is None)
t = TruthGuard([{"name": "drop_clearance", "m": 0.5}], layout=LAYOUT)
check("drop_clearance: 0.7 m from the drop's outline is clear for 0.5 m", t.check(at(-1.0, 0.0), STANDING) is None)
d = t.check(at(-1.5, 0.0), STANDING)
check("drop_clearance: 0.2 m from the drop is nearer than 0.5 m", d and d[0] == "drop_clearance" and "stairs" in d[1], d)
t = TruthGuard([NO_GO], layout=LAYOUT)
check("no_go_area: outside it is fine", t.check(at(0.5, 0.0), STANDING) is None)
n = t.check(at(1.2, 0.3), STANDING)
check("no_go_area: the robot inside it is a break, naming the area", n and n[0] == "no_go_area" and "stairwell" in n[1], n)
t = TruthGuard([{"name": "contact"}, {"name": "fall"}, {"name": "time_limit", "seconds": 10.0}, {"name": "max_speed", "mps": 0.2}],
               layout=LAYOUT)
check("the runner lists as checked only the truth ones", t.checked == ["contact", "fall"], t.checked)
check("a fall is said before a contact", t.check(at(1.75, 0.0), 0.03)[0] == "fall")

# --- the navigator's watchdog thread --------------------------------------------------------------------------
broke, seen = threading.Event(), []


def on_break(name, detail):
    seen.append((name, detail))
    broke.set()


g = Guard(Nav(), [{"name": "time_limit", "seconds": 0.3}], on_break)
g.arm()
time.sleep(0.1)
check("the watchdog says nothing while the time is not spent", not seen)
check("and breaks the run once, when it is", broke.wait(2.0) and len(seen) == 1 and seen[0][0] == "time_limit", seen)
time.sleep(0.2)
check("the watchdog ends after a break: no second report", len(seen) == 1)
g.stop()

print()
print("GUARDRAILS", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
