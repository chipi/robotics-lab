"""The scenario runner's parts, no simulator (ADR-0015): each challenge's scene from its seed, the start's jitter as a moved
world, the three outputs of a scene, and the judge's invariants and verdicts. Run: cd duck && uv run python tests/test_challenge.py"""

import json
import math
import sys
import tempfile
from pathlib import Path

from duck_lab.challenge.challenges import CHALLENGES, build
from duck_lab.challenge.judge import DROP_MARGIN_M, Judge
from duck_lab.challenge.scene import TRUNK_START, Box, Scene, layout, miniview_scene, mjcf, moved, slab
from duck_lab.nav.evaluate import FOOTPRINT_M, footprint_distance

failures = []


def inside(p, b: Box) -> bool:
    """p within box b's footprint (its yaw included)."""
    c, s = math.cos(-b.yaw), math.sin(-b.yaw)
    dx, dy = p[0] - b.cx, p[1] - b.cy
    return abs(c * dx - s * dy) <= b.hx and abs(s * dx + c * dy) <= b.hy


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


# ---- scenes from seeds ---------------------------------------------------------------------------------------------
for ch in CHALLENGES:
    a, b = build(ch, 3), build(ch, 3)
    check(f"challenge {ch}: the same seed is the same scene", a == b)
    c = build(ch, 4)
    check(f"challenge {ch}: another seed varies it", (c.boxes, c.floors, c.goal) != (a.boxes, a.floors, a.goal))
    check(f"challenge {ch}: its id is the challenge and the seed, a valid miniview scene id", a.id == f"ch{ch}-s3", a.id)
    on_start = any(abs(f.z1) < 1e-6 and inside((0.0, 0.0), f) for f in a.floors)
    clear = min((footprint_distance(TRUNK_START, g) for g in Judge(a).obs), default=math.inf)
    check(f"challenge {ch}: the duck starts on the start's floor (level 0), clear of every box", on_start and clear > FOOTPRINT_M,
          (on_start, round(clear, 3)))
check("doorways: the seed cycles 80, 50 and 42 cm", [build("2", s).notes["gap_m"] for s in (0, 1, 2)] == [0.8, 0.5, 0.42])
check("the step-downs are refusals, the rest are reaches",
      {ch: build(ch, 1).right for ch in CHALLENGES} == {"1": "reach", "2": "reach", "3": "reach", "4": "reach", "5": "reach", "6": "reach", "7": "reach", "8": "refuse", "9": "refuse", "10": "reach", "11": "reach", "12": "refuse", "13": "reach", "14": "reach", "15": "reach", "16": "reach"})
import random  # noqa: E402

blocks, goal_clear = [], []
for s in range(20):
    sc = CHALLENGES["4"](s, random.Random(f"4-{s}"))     # before the start's jitter: the start at the origin facing +x
    bx = next(b for b in sc.boxes if b.name == "box")
    blocks.append(abs(bx.cy) < bx.hy and bx.cx - bx.hx > 0.5)
    goal_clear.append(sc.goal[0] - (bx.cx + bx.hx) >= 0.6)
check("a box in the open: it stands across the straight line to the goal, at least 0.5 m ahead, in every seed", all(blocks), blocks)
check("a box in the open: the goal is 0.6 m or more behind it", all(goal_clear), goal_clear)
in_corr, walled_in = [], []
for s in range(20):
    sc = CHALLENGES["6"](s, random.Random(f"6-{s}"))
    end = next(b for b in sc.boxes if b.name == "dead_e")
    side = next(b for b in sc.boxes if b.name == "dead_n")
    mouth = side.cx - side.hx
    in_corr.append(mouth < -0.5 and 0.2 <= end.cx - TRUNK_START[0] <= 0.3 and 2 * side.cy <= 0.55)     # in the corridor, the end just ahead
    walled_in.append(sc.goal[0] < mouth - 0.5 and abs(sc.goal[1]) > side.cy)           # the goal in the room, beside the mouth
check("a dead end: the start inside a corridor 0.55 m or narrower, its closed end 0.2-0.3 m ahead, the mouth behind",
      all(in_corr), in_corr)
check("a dead end: the goal is out of the corridor, in the room beside its mouth", all(walled_in), walled_in)
# The pivot gate's budget (docs/wip/CLEARANCE-MODEL.md): footprint 0.083 + belief error in the kick ~0.013 + kick creep
# ~0.01, under the 0.11 m gate; a wall nearer than this at the start is a right refusal, not a wedge to get out of.
PIVOT_BUDGET_M = 0.13
wedge = []
for s in range(20):
    sc = build("7", s)                                    # with the start's jitter
    near = sorted(footprint_distance(TRUNK_START, g) for g in Judge(sc).obs)[:2]
    wedge.append(PIVOT_BUDGET_M <= near[0] and near[1] < 0.35)
check("wedged: in every seed two walls within 0.35 m of the trunk, neither inside the pivot's budget (jitter included)",
      all(wedge), wedge)
along = []
for s in range(20):
    sc = CHALLENGES["10"](s, random.Random(f"10-{s}"))
    low = sc.drops()[0]
    edge = low.cy - low.hy if low.cy > 0 else low.cy + low.hy      # the drop's edge nearest the duck's line (y = 0)
    along.append(0.4 <= abs(edge) <= 0.6 and low.cx - low.hx <= 0.0 and low.cx + low.hx >= sc.goal[0]
                 and abs(sc.goal[1]) + DROP_MARGIN_M < abs(edge))
check("a ledge: a drop 0.4-0.6 m beside the whole way from the start to the goal, the goal clear of its margin",
      all(along), along)
gapless, only_way = [], []
for s in range(20):
    sc = CHALLENGES["11"](s, random.Random(f"11-{s}"))
    pit, block = sc.drops()[0], next(b for b in sc.boxes if b.name == "block")
    xs = [-0.55 + 0.05 * i for i in range(int((pit.cx + pit.hx + 1.3) / 0.05))]
    gapless.append(all(any(inside((x, y), f) for f in sc.floors) for x in xs for y in [-1.15 + 0.05 * j for j in range(47)]))
    across = [-1.15 + 0.01 * j for j in range(231)]                           # across the room at the pit's middle
    free = [y for y in across if not inside((pit.cx, y), pit) and not inside((pit.cx, y), block)]
    width = (max(free) - min(free)) if free else 0.0
    only_way.append(0.64 <= width + 0.02 <= 0.81 and min(free) <= 0.0 <= max(free))
check("a passage by a hole: the floors cover the room with no gap (the pit is the only lower floor)", all(gapless), gapless)
check("a passage by a hole: across the pit, only the passage (0.65-0.8 m, the duck's line in it) is neither pit nor block",
      all(only_way), only_way)
check("a step-down has exactly one lower floor, 0.1-0.3 m down", all(len(build(ch, s).drops()) == 1 and 0.1 <= -build(ch, s).drops()[0].z1 <= 0.3
                                                                     for ch in ("8", "9", "10", "11") for s in range(5)))

# challenge 12: a table edge with no return. Past the edge the floor is out of the sensor's range (4 m), so every beam
# that crosses it returns "no target" (the simulator's status 255): the drop the cliff check must stop for without one
# below-floor return (RFC-0008 §3).
from duck_lab.challenge.scene import TOF_RANGE_M  # noqa: E402

t12 = [build("12", s) for s in range(10)]
check("challenge 12: one lower floor, beyond the sensor's range, and the goal on it (a refusal)",
      all(len(sc.drops()) == 1 and -sc.drops()[0].z1 > TOF_RANGE_M and inside(sc.goal, sc.drops()[0]) for sc in t12),
      [(round(sc.drops()[0].z1, 2), sc.goal) for sc in t12[:2]])
check("challenge 12: the edge 0.9-1.1 m ahead, met at 0-45 deg", all(0.9 <= sc.notes["edge_m"] <= 1.1 and
                                                                      0 <= abs(sc.notes["angle_deg"]) <= 45 for sc in t12))

# challenges 13-16 (RFC-0008 §3), before the start's jitter: the start at the origin facing +x
from duck_lab.nav.evaluate import OVERHEAD_CLEAR_M  # noqa: E402

c13 = [CHALLENGES["13"](s, random.Random(f"13-{s}")) for s in range(10)]
shelves = [next(b for b in sc.boxes if b.name == "shelf") for sc in c13]
check("challenge 13: a shelf across the straight way, its underside above the duck's head or below it, both drawn",
      all(sh.cx - sh.hx < sc.goal[0] and abs(sh.cy) < sh.hy for sh, sc in zip(shelves, c13))
      and {sh.z0 > OVERHEAD_CLEAR_M for sh in shelves} == {True, False}, [round(sh.z0, 2) for sh in shelves])
c14 = [CHALLENGES["14"](s, random.Random(f"14-{s}")) for s in range(10)]
check("challenge 14: legs 2-4 cm across on the way to the goal, a pole or a chair's four, both drawn",
      all(all(0.02 <= 2 * b.hx <= 0.04 and 0.02 <= 2 * b.hy <= 0.04 for b in sc.boxes if b.name.startswith("leg"))
          for sc in c14) and {sum(b.name.startswith("leg") for b in sc.boxes) for sc in c14} == {1, 4})
c15 = [CHALLENGES["15"](s, random.Random(f"15-{s}")) for s in range(10)]
small = [[b for b in sc.boxes if b.name.startswith("small")] for sc in c15]
check("challenge 15: 6-10 small boxes, 0.45 m apart or more, none within 0.3 m of the start or the goal",
      all(6 <= len(bs) <= 10 and all(math.dist((a.cx, a.cy), (b.cx, b.cy)) >= 0.45 for i, a in enumerate(bs) for b in bs[i + 1:])
          and all(math.dist((b.cx, b.cy), (0.0, 0.0)) > 0.3 and math.dist((b.cx, b.cy), sc.goal) > 0.3 for b in bs)
          for bs, sc in zip(small, c15)), [len(bs) for bs in small])
c16 = [CHALLENGES["16"](s, random.Random(f"16-{s}")) for s in range(10)]
bars = [next(f for f in sc.floors if f.name == "threshold") for sc in c16]
check("challenge 16: a threshold 1-3 cm high across the corridor, a floor (stepped over, not touched), the goal beyond",
      all(0.01 <= b.z1 <= 0.03 and b.cx < sc.goal[0] and not sc.drops() for b, sc in zip(bars, c16)), [round(b.z1, 3) for b in bars])

# ---- the start's jitter: the world moves, the duck stays at the origin ----------------------------------------------
base = Scene("t", "t", [Box("box", 1.0, 0.0, 0.1, 0.1, 0.0, 0.3)], [slab("floor", -1, 2, -1, 1)], (2.0, 0.0), "reach", 10.0)
m = moved(base, (0.0, 0.0, math.pi / 2))         # the duck starts facing +y in the challenge's frame
check("a start turned +90°: what was ahead on +x is now on the duck's right (-y)",
      abs(m.boxes[0].cx) < 1e-6 and abs(m.boxes[0].cy + 1.0) < 1e-6 and abs(m.goal[0]) < 1e-6 and abs(m.goal[1] + 2.0) < 1e-6, (m.boxes[0], m.goal))
m2 = moved(base, (0.5, 0.0, 0.0))                 # the duck starts 0.5 m further along +x
check("a start 0.5 m ahead: everything comes 0.5 m closer", abs(m2.boxes[0].cx - 0.5) < 1e-6 and abs(m2.goal[0] - 1.5) < 1e-6)
check("the jitter is kept with the scene", m2.jitter == (0.5, 0.0, 0.0))

# ---- the three outputs ------------------------------------------------------------------------------------------------
sc = build("9", 2)
mv = miniview_scene(sc)
drop = sc.drops()[0]
check("miniview: the boxes, and the lower floor as a drop hazard turned by its yaw with its depth",
      len(mv["boxes"]) == len(sc.boxes) and len(mv["hazards"]) == 1 and mv["hazards"][0]["yaw"] == drop.yaw
      and mv["hazards"][0]["depth"] == round(-drop.z1, 3) and mv["kind"] == "challenge", mv["hazards"])
lay = layout(sc)
check("layout: the floors as floor_* (the evaluation leaves them out of contacts), the boxes by name",
      sum(g["name"].startswith("floor_") for g in lay["geoms"]) == len(sc.floors) and len(lay["geoms"]) == len(sc.floors) + len(sc.boxes))
with tempfile.TemporaryDirectory() as tmp:
    up = Path(tmp) / "up"
    (up / "assets").mkdir(parents=True)
    (up / "scene_backlash.xml").write_text('<mujoco model="scene">\n    <include file="robot_groundcontact_backlash.xml" />\n    <worldbody>\n'
                                           '        <geom name="floor" size="0 0 0.05" pos="0 0 0" type="plane" material="groundplane" />\n'
                                           '    </worldbody>\n    <keyframe><key name="SIT" qpos="0"/></keyframe>\n</mujoco>\n')
    p = mjcf(sc, Path(tmp) / "scenarios", up)
    xml = p.read_text()
    check("mjcf: in the scenario's own folder, with `assets` linked to upstream's", p.parent.name == sc.id and (p.parent / "assets").resolve() == (up / "assets").resolve())
    check("mjcf: the full-collision robot by absolute path, no floor plane, a geom per slab and box, the keyframes kept",
          f'<include file="{up / "robot_allcollisions_backlash.xml"}" />' in xml and 'type="plane"' not in xml
          and xml.count('type="box"') == len(sc.floors) + len(sc.boxes) and 'name="SIT"' in xml)
    (up / "scene_backlash.xml").write_text("<mujoco/>")
    try:
        mjcf(sc, Path(tmp) / "other", up)
        changed = False
    except RuntimeError:
        changed = True
    check("mjcf: an upstream scene of another shape is refused, not half-replaced", changed)

# ---- the judge -------------------------------------------------------------------------------------------------------
corridor = moved(Scene("c", "c", [Box("wall_n", 1.0, 0.4, 1.5, 0.02, 0.0, 0.5)], [slab("floor", -0.5, 2.5, -0.4, 0.4),
                                                                                    slab("low", 2.5, 3.5, -0.4, 0.4, top=-0.2)],
                       (2.0, 0.0), "reach", 30.0), (0.0, 0.0, 0.0))
j = Judge(corridor)
check("judge: a sample in the clear breaks nothing", j.check(1.0, (0.5, 0.0, 0.0), 0.116) is None)
br = j.check(2.0, (1.0, 0.33, 0.0), 0.116)
check("judge: the trunk within the footprint of a wall is a contact, named, with its time", br and br["rule"] == "contact" and br["t"] == 2.0
      and "wall_n" in br["why"], br)
check("judge: only the first broken invariant is said", j.check(3.0, (1.0, 0.35, 0.0), 0.116) is None and j.broken["t"] == 2.0)
j2 = Judge(corridor)
br2 = j2.check(1.0, (2.5 - DROP_MARGIN_M + 0.05, 0.0, 0.0), 0.116)
check(f"judge: nearer than {DROP_MARGIN_M} m to a drop's edge breaks the margin", br2 and br2["rule"] == "drop_margin", br2)
j3 = Judge(corridor)
check("judge: a trunk below the fall height is a fall, before anything else", j3.check(1.0, (3.0, 0.0, 0.0), 0.02)["rule"] == "fall")
j4 = Judge(corridor)
check("judge: leaving the scene's bounds", j4.check(1.0, (0.5, 3.0, 0.0), 0.116)["rule"] == "bounds")

ok = Judge(corridor)
v = ok.verdict({"status": "reached", "time_s": 9.0}, (1.9, 0.05, 0.0))
check("verdict reach: said reached, within 0.25 m by truth, nothing broken: PASS", v["pass"] and v["failed"] == [], v)
v = ok.verdict({"status": "reached"}, (1.5, 0.0, 0.0))
check("verdict reach: said reached 0.5 m away: FAIL with the distance", not v["pass"] and "0.50 m" in v["failed"][0], v["failed"])
v = ok.verdict({"status": "timeout"}, (1.0, 0.0, 0.0))
check("verdict reach: a timeout fails", not v["pass"] and v["failed"][0].startswith("timeout"), v["failed"])
ref = Judge(moved(Scene("r", "r", [], [slab("floor", -0.5, 1.0, -1, 1), slab("low", 1.0, 2.0, -1, 1, top=-0.2)], (1.8, 0.0), "refuse", 30.0), (0, 0, 0)))
check("verdict refuse: refused with a reason: PASS", ref.verdict({"status": "refused", "why": "drop ahead"}, (0.6, 0.0, 0.0))["pass"])
check("verdict refuse: a timeout is not a refusal", not ref.verdict({"status": "timeout"}, (0.6, 0.0, 0.0))["pass"])
v = ref.verdict({"status": "stalled", "why": "15 s without getting closer"}, (0.6, 0.0, 0.0))
check("verdict refuse: a stall is not a refusal either (it gave up), and says why it stopped", not v["pass"] and "stalled where refusing was right (15 s" in v["failed"][0], v["failed"])
ref.check(5.0, (0.95, 0.0, 0.0), 0.116)
v = ref.verdict({"status": "refused", "why": "drop ahead"}, (0.95, 0.0, 0.0))
check("verdict refuse: the right refusal, but too near the edge on the way: FAIL, the margin named", not v["pass"] and "drop_margin" in v["failed"][0], v["failed"])
check("a verdict is JSON (it is written to result.json)", json.loads(json.dumps(v)) == v)

# The runner never calls a duck-sim that asks sudo with no terminal (docs/wip/DUCK-SIM-FOR-AGENTS.md).
from duck_lab.nav import simreset  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "scripts").mkdir()
    sim_script = Path(tmp) / "scripts" / "duck-sim"
    simreset.REPO = Path(tmp)
    sim_script.write_text('        if sudo systemctl is-active --quiet "$name" 2>/dev/null; then\n')
    try:
        simreset.duck_sim()
        refused = ""
    except RuntimeError as e:
        refused = str(e)
    check("an unpatched duck-sim (sudo on every down) is refused, the patch named", "duck-sim-sudo-free-down.patch" in refused, refused)
    sim_script.write_text('        if systemctl is-active --quiet "$name" 2>/dev/null; then\n')
    check("a patched duck-sim is used", simreset.duck_sim() == str(sim_script))

print("test_challenge", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
