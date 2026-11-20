"""The scenario runner's parts, no simulator (ADR-0015): each challenge's scene from its seed, the start's jitter as a moved
world, the three outputs of a scene, and the judge's invariants and verdicts. Run: cd robots/duck && uv run python tests/test_challenge.py"""

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
check("the step-downs are refusals, the explorations are their own, the rest are reaches",
      {ch: build(ch, 1).right for ch in CHALLENGES} == {"1": "reach", "2": "reach", "3": "reach", "4": "reach", "5": "reach", "6": "reach", "7": "reach", "8": "refuse", "9": "refuse", "10": "reach", "11": "reach", "12": "refuse", "13": "reach", "14": "reach", "15": "reach", "16": "reach", "17": "reach", "18": "reach", "19": "reach", "20": "reach", "21": "reach", "22": "explore", "23": "explore"})
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
check("challenge 16: a threshold 0.5-1.0 cm high (what the walking crosses, STEPS.md) across the corridor, a floor "
      "(stepped over, not touched), the goal beyond",
      all(0.005 <= b.z1 <= 0.01 and b.cx < sc.goal[0] and not sc.drops() for b, sc in zip(bars, c16)), [round(b.z1, 3) for b in bars])
floors16 = sorted(c16[0].floors, key=lambda f: f.cx)
check("challenge 16: the floor in pieces meeting edge to edge at the bar (a bar laid on a floor tripped the duck)",
      len(floors16) == 3 and all(abs((a.cx + a.hx) - (b.cx - b.hx)) < 1e-9 for a, b in zip(floors16, floors16[1:])),
      [(round(f.cx - f.hx, 3), round(f.cx + f.hx, 3)) for f in floors16])

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

# ---- challenges 17-20: walking over, up and down (heights from docs/wip/STEPS.md) ----------------------------------------
def edge_to_edge(sc):
    """Every floor piece meets its neighbours: no gap, no overlap (a bar laid on a floor tripped the duck)."""
    rows = sorted(sc.floors, key=lambda f: (f.cx - f.hx, f.cy))
    xs = sorted({round(f.cx - f.hx, 9) for f in rows} | {round(f.cx + f.hx, 9) for f in rows})
    return all(any(abs(f.cx - f.hx - x) < 1e-9 for f in rows) for x in xs[:-1])


c17 = [CHALLENGES["17"](s, random.Random(f"17-{s}")) for s in range(30)]
check("challenge 17: a cable, a rug or a book (each drawn among 30 seeds), under 1 cm (what the walking crosses), no "
      "drop, the goal beyond, the floor in pieces", {sc.notes["kind"] for sc in c17} == {"cable", "rug", "book"}
      and all(0.005 <= sc.notes["height_m"] <= 0.01 and not sc.drops() and sc.goal[0] > sc.notes["at_m"] + 1.0
              and edge_to_edge(sc) for sc in c17), [(sc.notes["kind"], sc.notes["height_m"]) for sc in c17[:6]])
books = [sc for sc in c17 if sc.notes["kind"] == "book"]
check("challenge 17's book: the floor around it fills the corridor (no hole beside the book)",
      all(abs(sum((f.hy * 2) for f in sc.floors if abs(f.cx - (sc.notes["at_m"] + 0.075)) < 1e-3) - 0.8) < 1e-9 for sc in books))
c18 = [CHALLENGES["18"](s, random.Random(f"18-{s}")) for s in range(10)]
check("challenge 18: up 0.5-1.0 cm onto a platform, down 0.5-1.5 cm off it; a step down is no drop",
      all(0.005 <= sc.notes["up_m"] <= 0.01 and 0.005 <= sc.notes["down_m"] <= 0.015 and not sc.drops() and edge_to_edge(sc)
          for sc in c18), [(sc.notes["up_m"], sc.notes["down_m"]) for sc in c18[:4]])
c19 = [CHALLENGES["19"](s, random.Random(f"19-{s}")) for s in range(10)]
c20 = [CHALLENGES["20"](s, random.Random(f"20-{s}")) for s in range(10)]
check("challenge 19: three 0.5 cm risers up; challenge 20: three 1-2 cm risers down, neither a drop, the goal on the "
      "last tread", all(sc.notes["riser_m"] == 0.005 and not sc.drops() and edge_to_edge(sc) for sc in c19)
      and all(0.01 <= sc.notes["riser_m"] <= 0.02 and not sc.drops() and edge_to_edge(sc) for sc in c20)
      and all(abs(sc.floor_top(sc.goal) - (-3 * sc.notes["riser_m"])) < 1e-3 for sc in c20))
check("challenges 17-20: every wall reaches down to the lowest floor (a gap under a wall is a hole the depth sensor sees "
      "through: challenge 20's first build refused 9 of 10 on it)",
      all(min(b.z0 for b in sc.boxes if b.name.startswith("corr_")) <= min(f.z1 for f in sc.floors) + 1e-9
          for sc in c17 + c18 + c19 + c20))
down = c20[0]
jd = Judge(down)
low = 0.116 - 3 * down.notes["riser_m"]
check("judge: standing on the flight's last tread (trunk 0.116 m above it, under 0.06 m above 0) is no fall",
      jd.check(1.0, (*down.goal, 0.0), low) is None and round(jd.lowest, 3) == 0.116, (low, jd.lowest, jd.broken))
check("judge: on the bottom tread, a trunk 0.03 m above it is a fall", Judge(down).check(1.0, (*down.goal, 0.0), low - 0.086)["rule"] == "fall")
check("judge: on a 1 cm bar (under 6 cm deep, walked over) the fall is judged from the floor around it",
      c16[0].floor_top((next(f for f in c16[0].floors if f.name == "threshold").cx, 0.0)) == 0.0)

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

# (The reset's refusal of a duck-sim that asks sudo moved with the reset: tests/test_simhost.py.)

# ---- challenges 21-23: ten goals in a row, a room with a drop, two rooms (RFC-0008) -----------------------------------------
from duck_lab.challenge import explore, floor, sequence  # noqa: E402
from duck_lab.challenge.challenges import _walled  # noqa: E402
from duck_lab.nav.frames import compose  # noqa: E402


def rect_gap(p, b: Box) -> float:
    """p's distance to an axis-aligned box's footprint."""
    return math.hypot(max(abs(p[0] - b.cx) - b.hx, 0.0), max(abs(p[1] - b.cy) - b.hy, 0.0))


def extent(sc: Scene) -> tuple:
    """x0, x1, y0, y1 of the floors (axis-aligned, before the start's jitter)."""
    return (min(f.cx - f.hx for f in sc.floors), max(f.cx + f.hx for f in sc.floors),
            min(f.cy - f.hy for f in sc.floors), max(f.cy + f.hy for f in sc.floors))


def room_of_floors(sc: Scene) -> Box:
    x0, x1, y0, y1 = extent(sc)
    return Box("room", (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, 0.0, 0.0)


def overlap(a: Box, b: Box) -> bool:
    return min(a.cx + a.hx, b.cx + b.hx) - max(a.cx - a.hx, b.cx - b.hx) > 1e-9 and \
        min(a.cy + a.hy, b.cy + b.hy) - max(a.cy - a.hy, b.cy - b.hy) > 1e-9


def pieces_fit(sc: Scene, areas) -> bool:
    """The floors in pieces: none over another, and every point of every area (0.1 m in from its edge) on one."""
    clean = not any(overlap(a, b) for i, a in enumerate(sc.floors) for b in sc.floors[i + 1:])
    full = all(any(inside((a.cx + dx, a.cy + dy), f) for f in sc.floors)
               for a in areas for dx in [x * 0.1 for x in range(int(-a.hx / 0.1) + 1, int(a.hx / 0.1))]
               for dy in [y * 0.1 for y in range(int(-a.hy / 0.1) + 1, int(a.hy / 0.1))])
    return clean and full


WALLS = ("room", "wa", "wb", "pass_")
P21 = [CHALLENGES["21"](s, random.Random(f"21-{s}")) for s in range(20)]
P22 = [CHALLENGES["22"](s, random.Random(f"22-{s}")) for s in range(20)]
P23 = [CHALLENGES["23"](s, random.Random(f"23-{s}")) for s in range(20)]
hole21 = [sc.drops()[0] for sc in P21]
check("challenge 21: one room 2.9-3.3 m a side, two or three boxes, the start clear of them (0.7 m)",
      all(2.9 <= sc.notes["room_m"][0] <= 3.3 and 2.9 <= sc.notes["room_m"][1] <= 3.3 and 2 <= sc.notes["boxes"] <= 3
          and all(rect_gap((0.0, 0.0), b) >= 0.7 - 1e-6 for b in sc.boxes if b.name.startswith("box")) for sc in P21))
check("challenge 21: a stairwell-like hole against a wall (one drop, 1-2.7 m down, 0.6-0.8 m a side, 0.6 m or more from the "
      "start), the floor in pieces edge to edge round it, walls to its floor",
      all(len(sc.drops()) == 1 and h.name == "stairwell" and 1.0 <= -h.z1 <= 2.7 and 0.6 - 1e-6 <= 2 * h.hx <= 0.8 + 1e-6
          and 0.6 - 1e-6 <= 2 * h.hy <= 0.8 + 1e-6 and rect_gap((0.0, 0.0), h) >= 0.6 - 1e-6
          and pieces_fit(sc, [room_of_floors(sc)])
          and min(b.z0 for b in sc.boxes if b.name.startswith("room_")) <= h.z1 + 1e-9
          for sc, h in zip(P21, hole21)))
check("challenge 21: ten goals, each 1 m or more from the one before (the first from the start), 0.3 m from each other, "
      "0.45 m in from the walls, 0.25 m from every box, 0.55 m from the hole",
      all(len(sc.goals) == 10 and all(math.dist(a, b) >= 1.0 - 1e-6 for a, b in zip([(0.0, 0.0)] + list(sc.goals), sc.goals))
          and all(math.dist(a, b) >= 0.3 - 1e-6 for i, a in enumerate(sc.goals) for b in sc.goals[i + 1:])
          and all(extent(sc)[0] + 0.45 - 1e-6 <= g[0] <= extent(sc)[1] - 0.45 + 1e-6 and extent(sc)[2] + 0.45 - 1e-6 <= g[1] <= extent(sc)[3] - 0.45 + 1e-6
                  for g in sc.goals)
          and all(rect_gap(g, b) >= 0.25 - 1e-6 for g in sc.goals for b in sc.boxes if b.name.startswith("box"))
          and all(rect_gap(g, h) >= 0.55 - 1e-6 for g in sc.goals) for sc, h in zip(P21, hole21)), [len(sc.goals) for sc in P21])
check("challenge 21: what failed is what the goals ask for: four beside a box (0.25-0.4 m from its outline), two by the "
      "hole (0.55-0.7 m from its edge), four in the open (0.4 m from boxes, 0.7 m from the hole)",
      all([k for k in sc.notes["goal_kinds"]].count("box") == 4 and sc.notes["goal_kinds"].count("drop") == 2
          and sc.notes["goal_kinds"].count("open") == 4
          and all(min(rect_gap(g, b) for b in sc.boxes if b.name.startswith("box")) <= 0.4 + 2e-3 for g, k in zip(sc.goals, sc.notes["goal_kinds"]) if k == "box")
          and all(rect_gap(g, h) <= 0.7 + 2e-3 for g, k in zip(sc.goals, sc.notes["goal_kinds"]) if k == "drop")
          and all(min(rect_gap(g, b) for b in sc.boxes if b.name.startswith("box")) >= 0.4 - 2e-3 and rect_gap(g, h) >= 0.7 - 2e-3
                  for g, k in zip(sc.goals, sc.notes["goal_kinds"]) if k == "open") for sc, h in zip(P21, hole21)))
check("challenge 21: a sequence, its first goal the scene's goal, 60 s a goal", all(sc.mode == "sequence" and sc.goal == sc.goals[0] and sc.time_s == 60.0 for sc in P21))
b21 = [build("21", s) for s in range(1, 6)]
check("challenge 21: with the start's jitter every goal is on the floor the duck can reach (a goal it can stand on)",
      all(all(min(math.dist(g, p) for p in floor.reachable(sc)) <= 0.05 for g in sc.goals) for sc in b21))

hole = [next(f for f in sc.floors if f.name == "stairwell") for sc in P22]
check("challenge 22: one drop, named so the scene's drops() has it, a floor 1-2.7 m below 0 (a stairwell, not a step)",
      all(sc.drops() == [h] and 1.0 <= -h.z1 <= 2.7 and sc.drops()[0].name == "stairwell" for sc, h in zip(P22, hole)))
check("challenge 22: the hole's nearest edge 0.5-0.8 m from the start, 0.8-1.0 m wide, 0.6-0.9 m long, either side",
      all(0.5 - 1e-6 <= rect_gap((0.0, 0.0), h) <= 0.8 + 1e-6 and 0.8 - 1e-6 <= 2 * h.hx <= 1.0 + 1e-6 and 0.6 - 1e-6 <= 2 * h.hy <= 0.9 + 1e-6
          for h in hole) and {sc.notes["side"] for sc in P22} == {-1, 1})
check("challenge 22: one room about 3 x 3.5 m, two or three boxes, an explorer's budget of 5 minutes, one area (the room)",
      all(2.8 <= sc.notes["room_m"][0] <= 3.3 and 3.3 <= sc.notes["room_m"][1] <= 3.7 and 2 <= sc.notes["boxes"] <= 3
          and sc.mode == "explore" and sc.time_s == 300.0 and [a.name for a in sc.areas] == ["room"] for sc in P22),
      [sc.notes["room_m"] for sc in P22[:3]])
check("challenge 22: the floors in pieces (the room's floor round the hole, the hole), edge to edge, none over another",
      all(pieces_fit(sc, sc.areas) and len(sc.floors) == 4 for sc in P22))
check("challenge 22: every wall reaches down to the lowest floor (the hole's floor): no gap under a wall",
      all(min(b.z0 for b in sc.boxes if b.name.startswith("room_")) <= min(f.z1 for f in sc.floors) + 1e-9 for sc in P22))
check("challenge 22: no box within 0.6 m of the hole",
      all(math.hypot(max(abs(b.cx - h.cx) - b.hx - h.hx, 0.0), max(abs(b.cy - h.cy) - b.hy - h.hy, 0.0)) >= 0.6 - 1e-6
          for sc, h in zip(P22, hole) for b in sc.boxes if b.name.startswith("box")))

check("challenge 23: two rooms, a door 0.6-0.8 m wide in the wall between them or at the end of a corridor 0.4-0.8 m long, "
      "the explorer's budget 8 minutes, one area per room (the start's first)",
      all(0.6 <= sc.notes["door_m"] <= 0.8 and (sc.notes["corridor_m"] == 0.0 or 0.4 <= sc.notes["corridor_m"] <= 0.8)
          and sc.mode == "explore" and sc.time_s == 480.0 and [a.name for a in sc.areas] == ["room_a", "room_b"] for sc in P23))
check("challenge 23: the seeds draw a plain door and a corridor, the door ahead of the start and behind it",
      {sc.notes["corridor_m"] == 0.0 for sc in P23} == {True, False} and {sc.notes["door_ahead"] for sc in P23} == {True, False})
check("challenge 23: the start in the first room, 1-3 boxes in each room (each in its own), the start clear of them (0.5 m)",
      all(inside((0.0, 0.0), sc.areas[0]) and not inside((0.0, 0.0), sc.areas[1])
          and all(1 <= sum(b.name.startswith(p) and inside((b.cx, b.cy), a) for b in sc.boxes) <= 3
                  for p, a in zip(("a_box", "b_box"), sc.areas))
          and all(rect_gap((0.0, 0.0), b) >= 0.5 - 1e-6 for b in sc.boxes if b.name.startswith("a_box")) for sc in P23))
check("challenge 23: the floors in pieces, edge to edge: each room's floor, the corridor's, none over another",
      all(pieces_fit(sc, sc.areas) and len(sc.floors) == (3 if sc.notes["corridor_m"] else 2) for sc in P23))
check("challenge 23: every wall reaches the floor's level", all(min(b.z0 for b in sc.boxes if b.name.startswith(WALLS)) <= min(f.z1 for f in sc.floors) + 1e-9
                                                                 for sc in P23))
door_ok = []
for sc in P23[:10]:
    pts = floor.reachable(sc)
    door_ok.append(all(sum(floor.in_area(p, a) for p in pts) > 1000 for a in sc.areas))
check("challenge 23: both rooms are on the floor the duck can reach from its start (the door is passable at its footprint)", all(door_ok), door_ok)

# the floor the duck could stand on, and the map against it
ring = _walled("pocket", 0.4, 1.0, 0.4, 1.0)
yard = Scene("y", "y", ring, [slab("floor", -1, 1, -1, 1)], (0, 0), "explore", 10.0, mode="explore", areas=(Box("room", 0, 0, 1, 1, 0, 0),))
inside_ring = [p for p in floor.lattice(layout(yard)).values() if 0.5 <= p[0] <= 0.9 and 0.5 <= p[1] <= 0.9]
check("reachable floor: a pocket walled all round is standable floor but not reachable from the start",
      len(inside_ring) > 20 and not any(0.45 < p[0] < 0.95 and 0.45 < p[1] < 0.95 for p in floor.reachable(yard)),
      (len(inside_ring), len(floor.reachable(yard))))
flat = Scene("f", "f", [], [slab("floor", -1, 1, -1, 1)], (0, 0), "explore", 10.0, mode="explore", areas=(Box("room", 0, 0, 1, 1, 0, 0),))
pts = floor.reachable(flat)
check("reachable floor: an open 2 x 2 m floor is 1600 lattice cells of 5 cm", len(pts) == 1600, len(pts))
check("reachable floor: the layout-level function (floors in, points out) is the scene's own",
      sorted(floor.reachable_floor(layout(flat))) == sorted(pts))

# not challenge-only (the apartment scoreboard's coverage later): the apartment's layout and its rooms through the same functions
from duck_lab.nav.evaluate import LAYOUT  # noqa: E402
from duck_lab.nav.rooms import ROOMS, room_of  # noqa: E402

apartment = json.loads(LAYOUT.read_text())
walk = floor.reachable_floor(apartment, (0.05, 0.0), step=0.1)
rooms = {n: (lambda p, n=n: room_of(p) == n) for n in ROOMS}
heard = floor.coverage_by(walk, lambda p: p[0] > 0.0, rooms)           # a stand-in map: everything east of the dock
check("the apartment's layout: a floor to stand on from the dock, no point inside the stairwell (the stairs' opening), and "
      "each room's share of a stand-in map told apart",
      len(walk) > 500 and not any(-0.40 <= p[0] <= 0.0 and -1.40 <= p[1] <= -0.70 for p in walk)
      and heard["regions"]["office"] == 1.0 and heard["regions"]["kitchen"] == 0.0, (len(walk), heard["regions"]))


def grid_of(x0, y0, w, h, res, known) -> dict:
    """A mapd grid of w x h cells from (x0, y0) in map metres; `known(x, y)` says whether the cell at its centre is."""
    cells = "".join("." if known(x0 + (i + 0.5) * res, y0 + (j + 0.5) * res) else "?" for j in range(h) for i in range(w))
    return {"res_m": res, "origin": [x0, y0], "width": w, "height": h, "cells": cells}


at0 = {"map": (0.0, 0.0, 0.0), "truth": (0.0, 0.0, 0.0), "scale": 1.0}
half = grid_of(-1, -1, 40, 40, 0.05, lambda x, y: x < 0)
cov = floor.coverage(flat, half, at0)
check("coverage: a map that knows the west half of the floor knows half of it", abs(cov["all"] - 0.5) < 0.02 and abs(cov["areas"]["room"] - 0.5) < 0.02, cov)
check("coverage: a map that knows nothing scores 0, one that knows everything 1",
      floor.coverage(flat, grid_of(-1, -1, 40, 40, 0.05, lambda x, y: False), at0)["all"] == 0.0
      and floor.coverage(flat, grid_of(-1, -1, 40, 40, 0.05, lambda x, y: True), at0)["all"] == 1.0)
# the map's frame is not the world's: mapd's origin is its first stop (here 1 m along the world's x)
shifted = {"map": (1.0, 0.0, 0.0), "truth": (0.0, 0.0, 0.0), "scale": 1.0}
check("coverage: the world's floor is read through the run's start (map pose against truth pose)",
      floor.coverage(flat, grid_of(0, -1, 40, 40, 0.05, lambda x, y: True), shifted)["all"] == 1.0
      and floor.coverage(flat, grid_of(-1, -1, 40, 40, 0.05, lambda x, y: True), shifted)["all"] < 0.6)
check("coverage: the odometry scale puts the grid's raw metres right (0.5: 0.1 m cells are 5 cm)",
      floor.coverage(flat, grid_of(-2, -2, 40, 40, 0.1, lambda x, y: True), {**at0, "scale": 0.5})["all"] == 1.0)
walled = grid_of(-1, -1, 40, 40, 0.05, lambda x, y: True)
walled["cells"] = "#" * len(walled["cells"])
check("coverage: an occupied cell is known too", floor.coverage(flat, walled, at0)["all"] == 1.0)
sc22 = P22[2]                     # before the start's jitter: the boxes are axis-aligned
h22 = sc22.drops()[0]
pts22 = floor.reachable(sc22)
check("coverage: the reachable floor keeps the drop's lethal zone (0.35 m) out of what is asked, and never the hole itself",
      all(rect_gap(p, h22) >= 0.35 - 1e-6 for p in pts22) and not any(inside(p, h22) for p in pts22), len(pts22))
all_known = grid_of(-6, -6, 240, 240, 0.05, lambda x, y: True)
check("coverage: a 22 scene's map that knows everything scores 1, one that knows only x < 0 scores between",
      floor.coverage(sc22, all_known, at0)["areas"]["room"] == 1.0
      and 0.1 < floor.coverage(sc22, grid_of(-6, -6, 240, 240, 0.05, lambda x, y: x < 0), at0)["areas"]["room"] < 0.9)
c23 = build("23", 3)
two = floor.coverage(c23, grid_of(-6, -6, 240, 240, 0.05, lambda x, y: inside((x, y), c23.areas[0])), at0)
check("coverage: two rooms are scored apart: a map of the first room only is all but the quantizing of its edge cells (over 0.98) for it and 0 for the second",
      two["areas"]["room_a"] > 0.98 and two["areas"]["room_b"] == 0.0 and 0.3 < two["all"] < 0.7, two)
bands = [floor.edge_band(sc, 0.2) for sc in [build(ch, s) for ch in ("21", "22", "23") for s in range(1, 11)]]
check("the bar: the floor within 0.2 m of a wall, a box or the drop is 15-40 % of the reachable floor, the slack a bar of "
      f"{explore.COVERAGE_BAR:.0%} leaves (seen {min(bands):.2f}-{max(bands):.2f})", 0.15 <= min(bands) and max(bands) <= 0.40, bands)

# the sequence (challenge 21) on a stand-in navigator: no simulator
j21 = Scene("s", "s", [Box("wall", 0.0, 1.45, 3.0, 0.02, 0.0, 0.5)], [slab("floor", -1.5, 1.5, -1.5, 1.5)], (1.0, 0.0), "reach", 60.0,
            mode="sequence", goals=((1.0, 0.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)), notes={"goal_kinds": ["open", "box", "drop", "box"]})


class StandIn:
    """go_to walks the truth to the goal (map frame = world frame: the start's transform is the identity) and the belief drifts
    by `drift` m along x and 3 degrees of heading more on each goal; `fail` maps a goal's number to (status, why, miss)."""

    def __init__(self, drift=0.02, fail=None):
        self.t, self.b, self.drift, self.fail, self.calls, self.rows = [0.05, 0.0, 0.0], [0.05, 0.0, 0.0], drift, fail or {}, [], []
        self.body = type("B", (), {"pose": lambda s_: tuple(self.t)})()
        self.loc = type("L", (), {"pose": lambda s_: tuple(self.b)})()

    def go_to(self, goal, timeout_s):
        n = len(self.calls) + 1
        self.calls.append((goal, timeout_s))
        status, why, miss = self.fail.get(n, ("reached", None, 0.0))
        self.t[:2] = [goal[0] + miss, goal[1]]
        self.b[:2] = [goal[0] + n * self.drift, goal[1]]
        self.b[2] = self.t[2] - math.radians(3 * n)
        return {"status": status, **({"why": why} if why else {})}

    def record(self, **row):
        self.rows.append(row)


nav = StandIn()
rows = sequence.run(nav, j21)
jj = Judge(j21)
v = sequence.verdict(jj, j21, rows)
check("sequence: every goal is gone to in order, each within the scene's time, and none is left out",
      [tuple(round(x, 3) for x in c[0]) for c in nav.calls] == list(j21.goals) and all(c[1] == 60.0 for c in nav.calls), nav.calls)
check("sequence: all reached by truth, nothing broken: PASS, four goals reached", v["pass"] and v["reached"] == 4 and v["status"] == "reached", v["failed"])
check("sequence: the belief's error is recorded at each goal (0.02 m more at each here), the mean and the largest in the verdict",
      [r["belief_error_m"] for r in rows] == [0.02, 0.04, 0.06, 0.08] and v["belief_error_m"] == {"mean": 0.05, "max": 0.08, "last": 0.08}, v["belief_error_m"])
check("sequence: the heading's error too (belief yaw against the truth's, 3 degrees more at each here, either sign), and the "
      "kind of place each goal is, in the rows and in the verdict",
      [r["heading_error_deg"] for r in rows] == [3.0, 6.0, 9.0, 12.0] and v["heading_error_deg"] == {"mean": 7.5, "max": 12.0, "last": 12.0}
      and [r["kind"] for r in rows] == ["open", "box", "drop", "box"], (v["heading_error_deg"], [r["kind"] for r in rows]))
check("sequence: each goal is an event in the run, with its number and its truth error",
      [(r["event"], r["n"]) for r in nav.rows] == [("goal", i) for i in (1, 2, 3, 4)])
nav = StandIn(fail={3: ("timeout", None, 0.4)})
rows = sequence.run(nav, j21)
v = sequence.verdict(Judge(j21), j21, rows)
check("sequence: a goal not reached stops the sequence there (no fourth goal from where nobody planned), FAIL naming goal 3 of 4",
      len(nav.calls) == 3 and not v["pass"] and v["reached"] == 2 and v["failed"] == ["goal 3 of 4: timeout"], (len(nav.calls), v["failed"]))
nav = StandIn(fail={2: ("reached", None, 0.4)})
v = sequence.verdict(Judge(j21), j21, sequence.run(nav, j21))
check("sequence: said reached 0.4 m from the goal is not reached (over 0.25 m by truth): FAIL with the distance",
      not v["pass"] and v["failed"] == ["goal 2 of 4: said reached 0.40 m from it (over 0.25 m)"], v["failed"])
nav = StandIn(fail={1: ("refused", "no path on the map", 0.0)})
v = sequence.verdict(Judge(j21), j21, sequence.run(nav, j21))
check("sequence: a refusal at the first goal names its reason", v["failed"] == ["goal 1 of 4: refused: no path on the map"] and v["reached"] == 0, v["failed"])
nav = StandIn()
rows = sequence.run(nav, j21)
jb = Judge(j21)
jb.check(2.0, (0.0, 1.40, 0.0), 0.116)
v = sequence.verdict(jb, j21, rows)
check("sequence: every goal reached but a contact on the way: FAIL (safety is part of the pass)",
      not v["pass"] and v["reached"] == 4 and v["failed"][0].startswith("contact at 2.0 s"), v["failed"])
check("sequence: a verdict is JSON", json.loads(json.dumps(v)) == v)
mv = moved(j21, (0.0, 0.0, math.pi / 2))
check("a start turned +90°: a sequence's goals and an exploration's areas move with the world",
      all(abs(g[0] - e[0]) < 1e-3 and abs(g[1] - e[1]) < 1e-3 for g, e in zip(mv.goals, [(0.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]))
      and abs(moved(sc22, (0.0, 0.0, math.pi / 2)).areas[0].yaw - (sc22.areas[0].yaw - math.pi / 2)) < 1e-3)

# the exploration's verdict (challenges 22, 23), from the files a run leaves: start.json, map_grid.json, ticks.jsonl
sc = build("23", 3)
b0, b1 = sc.areas


def verdict_for(grid, end, entered, why=None, judge=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "start.json").write_text(json.dumps(at0))
        (d / "map_grid.json").write_text(json.dumps(grid))
        (d / "ticks.jsonl").write_text(json.dumps({"t": 1.0, "pose": [0, 0, 0], "truth": [0, 0, 0]}) + "\n")
        trail = explore.Trail(sc)
        for a in entered:
            trail.see(7.0, (a.cx, a.cy))
        return explore.verdict(sc, judge or Judge(sc), trail, {"end": end, "end_s": 30.0, "legs": 5, "why": why}, d)


full = grid_of(-6, -6, 240, 240, 0.05, lambda x, y: True)
v = verdict_for(full, "no_frontier_left", [b0, b1])
check("exploration verdict: both rooms known, the door crossed, ended with no frontier left, nothing broken: PASS",
      v["pass"] and v["coverage"]["areas"] == {"room_a": 1.0, "room_b": 1.0} and v["end"] == "no_frontier_left", v["failed"])
v = verdict_for(full, "no_frontier_left", [b0])
check("exploration verdict: the second room never entered is a fail, the door named", not v["pass"] and v["failed"] == ["never entered room_b: the door not crossed"], v["failed"])
v = verdict_for(grid_of(-6, -6, 240, 240, 0.05, lambda x, y: inside((x, y), b0)), "no_frontier_left", [b0, b1])
check("exploration verdict: the second room not mapped is a fail with its share and the bar", not v["pass"] and len(v["failed"]) == 1
      and v["failed"][0] == f"coverage of room_b 0%, under {explore.COVERAGE_BAR:.0%}", v["failed"])
v = verdict_for(full, "trapped", [b0, b1], why="6 refusals in a row")
check("exploration verdict: ended trapped is a fail even with the rooms mapped", not v["pass"] and v["failed"] == ["ended trapped: 6 refusals in a row"], v["failed"])
v = verdict_for(full, "time", [b0, b1])
check("exploration verdict: the budget running out with both rooms known passes, the end said", v["pass"] and v["end"] == "time")
jf = Judge(sc)
jf.check(1.0, (0.0, 0.0, 0.0), 0.02)
v = verdict_for(full, "aborted", [b0, b1], judge=jf)
check("exploration verdict: a fall is said once (the abort it caused is not a second failure)", not v["pass"] and len(v["failed"]) == 1 and v["failed"][0].startswith("fall"), v["failed"])
check("exploration verdict: JSON, with the belief's error and the coverage", json.loads(json.dumps(v)) == v and "mean" in v["belief_error_m"])
trail = explore.Trail(sc)
trail.see(1.0, (0.0, 0.0))
trail.see(2.0, (b1.cx, b1.cy))
trail.see(3.0, (0.0, 0.0))
check("the trail: an area is entered once, at the first time", trail.entered == {"room_a": 1.0, "room_b": 2.0}, trail.entered)

print("test_challenge", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
