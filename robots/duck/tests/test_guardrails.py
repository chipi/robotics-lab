"""A goal's guardrails in the navigator (RFC-0014 §3.4.8, duck_lab/nav/guardrails.py): the keep-out points of a no-go area, the speed
cap, and each check against a stand-in truth (a body with a pose and a height) and a small layout. No simulator.
Run: cd robots/duck && uv run python tests/test_guardrails.py"""

import threading
import time

from duck_lab.nav.guardrails import Guard, keepout_points

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:200]}]" if detail else ""))
    if not cond:
        failures.append(name)


class Body:
    def __init__(self):
        self.xy, self.height = (0.0, 0.0), 0.116

    def pose(self):
        return (self.xy[0], self.xy[1], 0.0)


class Nav:
    def __init__(self, body=True):
        self.body = Body() if body else None
        self.speed_cap = None
        self.keepout = []


def box(name, x, y, hx=0.2, hy=0.2):
    return {"name": name, "type": "box", "pos": [x, y, 0.2], "size": [hx, hy, 0.2], "yaw": 0.0, "collides": True}


LAYOUT = ([box("sofa", 2.0, 0.0)], [box("stairs", -2.0, 0.0, 0.3, 0.3)])
NO_GO = {"name": "no_go_area", "area": "stairwell", "outline": [[1.0, -1.0], [1.5, -1.0], [1.5, 1.0], [1.0, 1.0]]}


def guard(nav, rails, broke=None):
    return Guard(nav, rails, (broke or (lambda n, d: None)), t0=100.0, layout=LAYOUT)


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

# --- the checks --------------------------------------------------------------------------------------
nav = Nav()
g = guard(nav, [{"name": "time_limit", "seconds": 30.0}])
check("time_limit: not yet, then spent", g.check(now=120.0) is None and g.check(now=131.0)[0] == "time_limit")
nav = Nav()
g = guard(nav, [{"name": "fall"}])
check("fall: standing is fine", g.check(now=100.0) is None)
nav.body.height = 0.03
check("fall: the trunk down is a fall", g.check(now=100.0)[0] == "fall")
nav = Nav()
g = guard(nav, [{"name": "contact"}])
nav.body.xy = (1.0, 0.0)
check("contact: 0.8 m from the sofa is clear", g.check(now=100.0) is None)
nav.body.xy = (1.75, 0.0)
c = g.check(now=100.0)
check("contact: the trunk centre within 8.3 cm of the sofa's outline, a part can touch it", c and c[0] == "contact" and "sofa" in c[1], c)
nav.body.xy = (1.6, 0.0)
check("contact: 0.2 m from the outline is clear", g.check(now=100.0) is None)
nav = Nav()
g = guard(nav, [{"name": "drop_clearance", "m": 0.5}])
nav.body.xy = (-1.0, 0.0)
check("drop_clearance: 0.7 m from the drop's outline is clear for 0.5 m", g.check(now=100.0) is None)
nav.body.xy = (-1.5, 0.0)
d = g.check(now=100.0)
check("drop_clearance: 0.2 m from the drop is nearer than 0.5 m", d and d[0] == "drop_clearance" and "stairs" in d[1], d)
nav = Nav()
g = guard(nav, [NO_GO])
nav.body.xy = (0.5, 0.0)
check("no_go_area: outside it is fine", g.check(now=100.0) is None)
nav.body.xy = (1.2, 0.3)
n = g.check(now=100.0)
check("no_go_area: the robot inside it is a break, naming the area", n and n[0] == "no_go_area" and "stairwell" in n[1], n)
nav = Nav()
g = guard(nav, [{"name": "contact"}, {"name": "fall"}, {"name": "time_limit", "seconds": 10.0}])
nav.body.xy = (1.75, 0.0)
check("the time limit is checked first", g.check(now=200.0)[0] == "time_limit")
check("without a truth (a real robot) only the clock is checked, and the truth ones are not listed as checked",
      (lambda n: Guard(n, [{"name": "contact"}, {"name": "time_limit", "seconds": 5.0}], lambda *_: None, t0=0.0, layout=LAYOUT).checked)(Nav(body=False)) == ["time_limit"])
check("a guard with a truth lists all of them as checked", Guard(Nav(), [{"name": "contact"}, {"name": "stuck"}], lambda *_: None, layout=LAYOUT).checked == ["contact", "stuck"])

# --- the watchdog thread --------------------------------------------------------------------------------
nav = Nav()
broke, seen = threading.Event(), []


def on_break(name, detail):
    seen.append((name, detail))
    broke.set()


g = Guard(nav, [NO_GO], on_break, layout=LAYOUT)
g.arm()
time.sleep(0.2)
check("the watchdog says nothing while the robot is outside", not seen)
nav.body.xy = (1.2, 0.0)
check("and breaks the run once, when it enters", broke.wait(2.0) and len(seen) == 1 and seen[0][0] == "no_go_area", seen)
time.sleep(0.2)
check("the watchdog ends after a break: no second report", len(seen) == 1)
g.stop()

print()
print("GUARDRAILS", "FAIL " + ", ".join(failures) if failures else "PASS")
raise SystemExit(1 if failures else 0)
