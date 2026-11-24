"""A goal's guardrails (RFC-0014 §3.4.8, duck_lab/nav/guardrails.py): the keep-out points of a no-go area, the speed cap and
the clock (the navigator's `Guard`, which reads no truth), and each truth check (the runner's `TruthGuard`, RFC-0021 step 6)
against a stand-in truth and a small layout. No simulator.
Run: cd robots/duck && uv run python tests/test_guardrails.py"""

import threading
import time

from duck_lab.nav.guardrails import Guard, RobotSide, keepout_points
from labrunner.guard import TruthGuard

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

# --- the robot-side replacements for the truth guardrails (phase 5 B3): no truth, the robot's own sensors ---------------------------
CFG = {"fall_tilt_deg": 45.0, "fall_s": 0.5}
ALL = [{"name": "fall"}, {"name": "contact"}, {"name": "drop_clearance", "m": 0.8}]
ASKED = ["fall", "contact", "drop_clearance"]
WALKING = [3.0, -2.0]
rs = RobotSide(ALL, ASKED, CFG)
check("only what is asked and not enforced by the runner is checked here, in the truth guard's order",
      rs.names == ["fall", "contact", "drop_clearance"] and RobotSide(ALL, ["contact"], CFG).names == ["contact"]
      and RobotSide([{"name": "fall"}], ASKED, CFG).names == ["fall"] and RobotSide(ALL, [], CFG).names == [], rs.names)
check("must fail: a walking tilt, no mapd trouble and no drop near is no break", rs.check(0.0, WALKING, {"lost": None}, None) is None)
rs = RobotSide(ALL, ASKED, CFG)
check("must fail: the trunk past the tilt is not a fall until it has held fall_s", rs.check(0.0, [50.0, 0.0], {"lost": None}, None) is None
      and rs.check(0.4, [50.0, 0.0], {"lost": None}, None) is None)
f = rs.check(0.6, [50.0, 0.0], {"lost": None}, None)
check("must fail: held 0.5 s past 45 deg is a fall, naming the angle", f and f[0] == "fall" and "50" in f[1], f)
rs = RobotSide(ALL, ASKED, CFG)
rs.check(0.0, [50.0, 0.0], None, None)
rs.check(0.3, [5.0, 0.0], None, None)
check("must fail: a tilt that came back under the angle starts the hold again", rs.check(0.6, [50.0, 0.0], None, None) is None)
check("must fail: roll counts as well as pitch, either sign", RobotSide(ALL, ASKED, CFG).check(0.0, [0.0, -80.0], None, None) is None
      and (lambda r: (r.check(0.0, [0.0, -80.0], None, None), r.check(0.6, [0.0, -80.0], None, None))[1])(RobotSide(ALL, ASKED, CFG))[0] == "fall")
check("a tilt the robot does not report is not checked", RobotSide(ALL, ASKED, CFG).check(9.0, None, None, None) is None)
rs = RobotSide(ALL, ASKED, CFG)
rs.check(0.0, WALKING, {"lost": None}, None)
b = rs.check(1.0, WALKING, {"lost": "bumped"}, None)
check("must fail: mapd newly lost as bumped is a contact", b and b[0] == "contact" and "bumped" in b[1], b)
rs = RobotSide(ALL, ASKED, CFG)
rs.check(0.0, WALKING, {"lost": None}, None)
c = rs.check(1.0, WALKING, {"lost": "carried"}, None)
check("must fail: mapd newly lost as carried is a contact, said as a lift", c and c[0] == "contact" and "lifted" in c[1], c)
rs = RobotSide(ALL, ASKED, CFG)
rs.check(0.0, WALKING, {"lost": None}, None)
fe = rs.check(1.0, WALKING, {"lost": "fell"}, None)
check("must fail: mapd newly lost as fell is a fall", fe and fe[0] == "fall", fe)
rs = RobotSide(ALL, ASKED, CFG)
check("must fail: a duck already carried when the goal began is the baseline, not a contact of the goal's",
      rs.check(0.0, WALKING, {"lost": "carried"}, None) is None and rs.check(1.0, WALKING, {"lost": "carried"}, None) is None)
check("must fail: lost for another reason (boot, sat, contradiction) is no guardrail",
      all(RobotSide(ALL, ASKED, CFG).check(1.0, WALKING, {"lost": r}, None) is None for r in ("boot", "sat", "contradiction")) is True
      and (lambda r: (r.check(0.0, WALKING, {"lost": None}, None), r.check(1.0, WALKING, {"lost": "sat"}, None))[1])(RobotSide(ALL, ASKED, CFG)) is None)
check("mapd not asked yet (no account) is not a change", (lambda r: (r.check(0.0, WALKING, None, None), r.check(1.0, WALKING, {"lost": None}, None))[1])(RobotSide(ALL, ASKED, CFG)) is None)
check("must fail: a drop the cliff check has seen 1.0 m off is clear for 0.8 m", RobotSide(ALL, ASKED, CFG).check(0.0, WALKING, {"lost": None}, 1.0) is None)
d = RobotSide(ALL, ASKED, CFG).check(0.0, WALKING, {"lost": None}, 0.5)
check("must fail: 0.5 m from a seen drop is nearer than 0.8 m", d and d[0] == "drop_clearance" and "0.50" in d[1], d)
check("a drop not seen yet is not a break", RobotSide(ALL, ASKED, CFG).check(0.0, WALKING, {"lost": None}, None) is None)
check("a guardrail not asked is not checked: contact only, a fall's tilt and a near drop pass",
      (lambda r: (r.check(0.0, [80.0, 0.0], None, 0.1), r.check(9.0, [80.0, 0.0], None, 0.1))[1])(RobotSide([{"name": "contact"}], ASKED, CFG)) is None)
check("one a runner with the truth checks is not checked here: the same list, nothing not enforced",
      RobotSide(ALL, [], CFG).check(9.0, [80.0, 0.0], {"lost": "bumped"}, 0.1) is None)


class RobotNav(Nav):
    """The navigator as the guard reads it: tilt, mapd's account, the belief's pose and the drops its cliff check has seen."""

    def __init__(self, drops=(), pose=(0.0, 0.0, 0.0), mapd=None, tilt=None, edges=()):
        super().__init__()
        self.drops, self.edges, self._tilt_now = list(drops), list(edges), tilt
        self.localisation = type("L", (), {"seen": mapd, "pose": lambda s: pose})()

    def _tilt(self):
        return self._tilt_now


g = Guard(RobotNav(drops=[(0.3, 0.0), (2.0, 2.0)], mapd={"lost": None}), ALL, lambda *_: None, t0=100.0, robot=RobotSide(ALL, ASKED, CFG))
dd = g.check(now=101.0)
check("must fail: the guard hands the robot side the belief's distance to the nearest seen drop (0.3 m, under 0.8 m)", dd and dd[0] == "drop_clearance", dd)
de = Guard(RobotNav(edges=[(0.0, 0.5)], mapd={"lost": None}), ALL, lambda *_: None, t0=100.0, robot=RobotSide(ALL, ASKED, CFG)).check(now=101.0)
check("must fail: the edges a glance measured count as seen drops too (0.5 m off, under 0.8 m)", de and de[0] == "drop_clearance", de)
check("the guard with no robot side checks the clock only: the same nav, the same drop, no break",
      Guard(RobotNav(drops=[(0.3, 0.0)], mapd={"lost": None}), ALL, lambda *_: None, t0=100.0).check(now=101.0) is None)
g = Guard(RobotNav(mapd={"lost": None}), [{"name": "time_limit", "seconds": 30.0}, *ALL], lambda *_: None, t0=100.0, robot=RobotSide(ALL, ASKED, CFG))
check("the clock is said before the robot's checks", g.check(now=131.0)[0] == "time_limit")

# --- the robot-side checks beside a truth (phase 5 E2): recorded, never a break --------------------------------------------------
noted = []
shadow = RobotSide(ALL, ["fall", "contact", "drop_clearance"], CFG)
g = Guard(RobotNav(drops=[(0.3, 0.0)], mapd={"lost": None}, tilt=[60.0, 0.0]), ALL, lambda *_: None, t0=100.0, shadow=shadow, on_record=lambda n, d: noted.append(n))
check("must fail: a shadow guard returns no break (the referee judges) and says what it would have done, once per name",
      g.check(now=101.0) is None and g.check(now=101.7) is None and g.check(now=102.0) is None and sorted(noted) == ["drop_clearance", "fall"], noted)
quiet_said = []
Guard(RobotNav(mapd={"lost": None}, tilt=[3.0, 0.0]), ALL, lambda *_: None, t0=0.0, shadow=RobotSide(ALL, ASKED, CFG),
      on_record=lambda a, b: quiet_said.append(a)).check(now=1.0)
check("a shadow with nothing to say says nothing", quiet_said == [], quiet_said)

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
