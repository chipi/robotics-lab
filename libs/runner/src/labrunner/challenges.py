"""The challenges (RFC-0008 §3, ADR-0015): each a function from a seed to a scene in its own frame, the duck's start at
the origin facing +x. The ranges are first guesses (ADR-0015), to tune when they run. Every edge of the start's floor
that is not the challenge's drop is walled: the only drop is the one being tested.
"""

import math
import random
from dataclasses import replace

from labrunner.scene import TOF_RANGE_M, TRUNK_START, Box, Scene, moved, slab, wall

START_JITTER = (0.05, math.radians(10))     # ±m, ±rad


def _walled(name: str, x0: float, x1: float, y0: float, y1: float, z0: float = 0.0, skip=()) -> list:
    """Walls around x0..x1 × y0..y1; `skip` names the sides left open ("w", "e", "s", "n")."""
    sides = {"s": (x0, y0, x1, y0), "e": (x1, y0, x1, y1), "n": (x1, y1, x0, y1), "w": (x0, y1, x0, y0)}
    return [Box(**{**wall(f"{name}_{k}", *p).__dict__, "z0": z0}) for k, p in sides.items() if k not in skip]


def corridor(seed: int, rng: random.Random) -> Scene:
    w, gx = rng.uniform(0.7, 0.9), rng.uniform(2.0, 2.8)
    return Scene(f"ch1-s{seed}", f"Straight corridor, {w:.2f} m wide", _walled("corr", -0.6, 3.2, -w / 2, w / 2),
                 [slab("floor", -0.6, 3.2, -w / 2, w / 2)], (gx, 0.0), "reach", 60.0, notes={"width_m": round(w, 3)})


def doorway(seed: int, rng: random.Random) -> Scene:
    gap, off = (0.80, 0.50, 0.42)[seed % 3], rng.uniform(-0.1, 0.1)
    boxes = _walled("room", -0.6, 3.0, -1.2, 1.2) + [wall("door_s", 1.2, -1.2, 1.2, off - gap / 2),
                                                      wall("door_n", 1.2, off + gap / 2, 1.2, 1.2)]
    return Scene(f"ch2-s{seed}", f"Doorway {gap * 100:.0f} cm", boxes, [slab("floor", -0.6, 3.0, -1.2, 1.2)],
                 (2.2, rng.uniform(-0.3, 0.3)), "reach", 60.0, notes={"gap_m": gap, "offset_m": round(off, 3)})


def corner_in_doorway(seed: int, rng: random.Random) -> Scene:
    gap, inside, side = 0.6, rng.uniform(0.05, 0.2), rng.choice((-1, 1))
    edge = side * (gap / 2 - inside)                  # the box's side nearest the gap's middle, inside the gap's line
    box_y = edge + side * 0.15
    boxes = _walled("room", -0.6, 3.0, -1.2, 1.2) + [wall("door_s", 1.2, -1.2, 1.2, -gap / 2), wall("door_n", 1.2, gap / 2, 1.2, 1.2),
                                                      Box("box", 1.40, box_y, 0.15, 0.15, 0.0, 0.4)]
    return Scene(f"ch3-s{seed}", "A box corner just inside a doorway", boxes, [slab("floor", -0.6, 3.0, -1.2, 1.2)],
                 (2.4, side * 0.6), "reach", 75.0, notes={"inside_m": round(inside, 3), "side": side})


def box_in_open(seed: int, rng: random.Random) -> Scene:
    """A box across the straight line to the goal, deep enough that its back is not seen from the start: the planner meets
    the unseen cells beside and behind it (trial 7)."""
    cx, cy = rng.uniform(1.0, 1.4), rng.uniform(-0.15, 0.15)
    hx, hy = rng.uniform(0.15, 0.3), rng.uniform(0.15, 0.3)
    goal = (cx + hx + rng.uniform(0.6, 0.8), rng.uniform(-0.2, 0.2))
    boxes = _walled("room", -0.6, 3.0, -1.2, 1.2) + [Box("box", cx, cy, hx, hy, 0.0, 0.4)]
    return Scene(f"ch4-s{seed}", "A box in the open, its back unseen", boxes, [slab("floor", -0.6, 3.0, -1.2, 1.2)], goal,
                 "reach", 75.0, notes={"box_m": [round(2 * hx, 3), round(2 * hy, 3)], "box_at": [round(cx, 3), round(cy, 3)]})


def dead_end(seed: int, rng: random.Random) -> Scene:
    """The start inside a dead-end corridor narrower than challenge 5's, its closed end just ahead; the corridor opens behind
    into a room with the goal beside the mouth: out without walking backwards (trials 7, 8). A dead end the duck walks into
    from outside does not work as a test: the depth sensor reaches 4 m, so its closed end is on the map before it enters."""
    w, end, length = rng.uniform(0.45, 0.55), TRUNK_START[0] + rng.uniform(0.2, 0.3), rng.uniform(0.9, 1.1)
    mouth = end - length
    corr = [wall("dead_s", mouth, -w / 2, end, -w / 2), wall("dead_n", mouth, w / 2, end, w / 2),
            wall("dead_e", end, -w / 2, end, w / 2)]
    room = _walled("room", mouth - 1.8, mouth, -1.2, 1.2, skip=("e",)) + [wall("room_e1", mouth, -1.2, mouth, -w / 2),
                                                                          wall("room_e2", mouth, w / 2, mouth, 1.2)]
    goal = (mouth - rng.uniform(0.6, 0.9), rng.choice((-1, 1)) * rng.uniform(0.5, 0.8))
    floors = [slab("floor", mouth - 1.8, mouth, -1.2, 1.2), slab("corridor", mouth, end, -w / 2, w / 2)]
    return Scene(f"ch6-s{seed}", "Dead-end corridor", room + corr, floors, goal, "reach", 120.0,
                 notes={"width_m": round(w, 3), "end_ahead_m": round(end - TRUNK_START[0], 3), "length_m": round(length, 3)})


def wedged(seed: int, rng: random.Random) -> Scene:
    """The start facing into a room's corner, a wall close ahead and one close beside, the goal behind in the open: boxed-in
    recovery (trial 4). The clearances keep the footprint (0.083 m) off both walls, the start's jitter included."""
    ahead, aside, side = rng.uniform(0.2, 0.25), rng.uniform(0.2, 0.25), rng.choice((-1, 1))
    x1, y_wall = TRUNK_START[0] + ahead, side * aside             # from the trunk, where contacts are judged
    y0, y1 = (y_wall - 2.6, y_wall) if side > 0 else (y_wall, y_wall + 2.6)
    boxes = _walled("room", x1 - 3.2, x1, y0, y1)
    goal = (-rng.uniform(1.5, 2.0), -side * rng.uniform(0.3, 0.8))
    return Scene(f"ch7-s{seed}", "Start wedged in a corner", boxes, [slab("floor", x1 - 3.2, x1, y0, y1)], goal, "reach", 90.0,
                 notes={"ahead_m": round(ahead, 3), "aside_m": round(aside, 3), "side": side})


def u_turn(seed: int, rng: random.Random) -> Scene:
    back = rng.uniform(1.2, 1.8)
    return Scene(f"ch5-s{seed}", "U-turn in a 60 cm corridor", _walled("corr", -2.2, 0.6, -0.3, 0.3),
                 [slab("floor", -2.2, 0.6, -0.3, 0.3)], (-back, 0.0), "reach", 75.0, notes={"goal_behind_m": round(back, 3)})


def _step_down(cid: str, name: str, seed: int, angle: float, depth: float) -> Scene:
    """The start's floor ends at an edge through (1, 0) whose normal is `angle` from the heading; the goal is 0.8 m past it, on
    a floor `depth` lower. Built in the edge's frame and turned into the challenge's."""
    edge = (1.0, 0.0, angle)

    def turned(b: Box) -> Box:
        return b.moved(edge)
    near = 1.0 * math.cos(angle) + 0.6                # far enough behind the edge for the start (and its jitter) to be on it
    up, low = slab("upper", -near, 0.0, -1.5, 1.5), slab("lower", 0.0, 1.6, -1.5, 1.5, top=-depth)
    boxes = _walled("upper", -near, 0.0, -1.5, 1.5, skip=("e",)) + _walled("lower", 0.0, 1.6, -1.5, 1.5, z0=-depth, skip=("w",))
    gx, gy = 1.0 + 0.8 * math.cos(angle), 0.8 * math.sin(angle)
    return Scene(f"{cid}-s{seed}", name, [turned(b) for b in boxes], [turned(up), turned(low)], (gx, gy), "refuse", 60.0,
                 notes={"depth_m": round(depth, 3), "angle_deg": round(math.degrees(angle), 1)})


def step_down(seed: int, rng: random.Random) -> Scene:
    return _step_down("ch8", "Step down, head-on", seed, 0.0, rng.uniform(0.1, 0.3))


def step_down_diagonal(seed: int, rng: random.Random) -> Scene:
    a = math.radians(rng.uniform(30, 60)) * rng.choice((-1, 1))
    return _step_down("ch9", "Step down, approached diagonally", seed, a, rng.uniform(0.1, 0.3))


def ledge(seed: int, rng: random.Random) -> Scene:
    """Walking along a ledge: the start's floor ends in a drop running beside the way to the goal, 0.4-0.6 m from it, on
    one side; the other side is walled 0.8 m out, room enough to keep a drop's margin. The drop is seen only by the
    sensor's side beams, if at all (trial 8): drop memory and side beams (RFC-0008 §3)."""
    off, depth, side = rng.uniform(0.4, 0.6), rng.uniform(0.1, 0.3), rng.choice((-1, 1))
    x0, x1, wall_y, edge_y = -0.6, 3.2, -side * 0.8, side * off
    up_lo, up_hi = sorted((wall_y, edge_y))
    low_lo, low_hi = sorted((edge_y, edge_y + side * 1.2))
    up_skip = ("n",) if side > 0 else ("s",)                  # the edge's side of the start's floor is the drop
    low_skip = ("s",) if side > 0 else ("n",)
    boxes = _walled("upper", x0, x1, up_lo, up_hi, skip=up_skip) + _walled("lower", x0, x1, low_lo, low_hi, z0=-depth, skip=low_skip)
    floors = [slab("upper", x0, x1, up_lo, up_hi), slab("lower", x0, x1, low_lo, low_hi, top=-depth)]
    return Scene(f"ch10-s{seed}", "Walking along a ledge", boxes, floors, (rng.uniform(2.4, 2.8), 0.0), "reach", 90.0,
                 notes={"ledge_m": round(off, 3), "depth_m": round(depth, 3), "side": side})


def passage_by_hole(seed: int, rng: random.Random) -> Scene:
    """A narrow passage beside a hole: a pit running from the passage to the room's wall on one side, a block from the
    passage to the room's wall on the other, so the passage is the only way to the goal. It is 0.65-0.8 m from the
    block's face to the pit's edge, wide enough for a drop's margin (0.45 m) plus a wall's (0.12 m), with the duck's line
    0.3-0.4 m from the edge: drop zones against passage width (trial 6)."""
    w, e, side = rng.uniform(0.65, 0.8), rng.uniform(0.3, 0.4), rng.choice((-1, 1))
    depth, length, hx0 = rng.uniform(0.1, 0.3), rng.uniform(0.8, 1.0), rng.uniform(0.8, 1.0)
    hx1, x0, x1, y_room = hx0 + length, -0.6, hx0 + length + 1.4, 1.2
    edge, face = side * e, -side * (w - e)                        # the pit's edge and the block's face, across the way
    pit_lo, pit_hi = sorted((edge, side * y_room))
    blk_lo, blk_hi = sorted((face, -side * y_room))
    pass_lo, pass_hi = sorted((edge, -side * y_room))              # the upper floor beside the pit, under the block too
    floors = [slab("floor_w", x0, hx0, -y_room, y_room), slab("floor_e", hx1, x1, -y_room, y_room),
              slab("floor_passage", hx0, hx1, pass_lo, pass_hi), slab("pit", hx0, hx1, pit_lo, pit_hi, top=-depth)]
    block = Box("block", (hx0 + hx1) / 2, (blk_lo + blk_hi) / 2, length / 2, (blk_hi - blk_lo) / 2, 0.0, 0.4)
    boxes = _walled("room", x0, x1, -y_room, y_room) + [block]
    return Scene(f"ch11-s{seed}", "A narrow passage beside a hole", boxes, floors, (x1 - 0.6, rng.uniform(-0.2, 0.2)),
                 "reach", 90.0, notes={"passage_m": round(w, 3), "edge_m": round(e, 3), "depth_m": round(depth, 3), "side": side})


def table_edge(seed: int, rng: random.Random) -> Scene:
    """A table edge with no return at all: the start's floor ends 0.9-1.1 m ahead, met at 0-45 deg, and the floor beyond
    is out of the sensor's range, so every beam that crosses the edge returns "no target" instead of a floor below. The
    goal is down there: a refusal. A real table over a dark carpet, or a stairwell, can look like this; the cliff check
    has only below-floor returns to go by (RFC-0008 §3, challenge 12)."""
    angle, near = math.radians(rng.uniform(0, 45)) * rng.choice((-1, 1)), rng.uniform(0.9, 1.1)
    edge = (near, 0.0, angle)

    def turned(b: Box) -> Box:
        return b.moved(edge)
    back = near * math.cos(angle) + 0.6                # behind the edge far enough for the start (and its jitter)
    depth = TOF_RANGE_M + 0.5
    up, low = slab("table", -back, 0.0, -1.5, 1.5), slab("below", 0.0, 1.6, -1.5, 1.5, top=-depth)
    boxes = _walled("table", -back, 0.0, -1.5, 1.5, skip=("e",))
    gx, gy = near + 0.8 * math.cos(angle), 0.8 * math.sin(angle)
    return Scene(f"ch12-s{seed}", "A table edge with no return", [turned(b) for b in boxes], [turned(up), turned(low)],
                 (gx, gy), "refuse", 60.0,
                 notes={"edge_m": round(near, 3), "angle_deg": round(math.degrees(angle), 1), "depth_m": depth})


def _room(goal_x: float) -> list:
    """A walled room from behind the start to past the goal, 3 m across: room to go round what is on the way."""
    return _walled("room", -0.6, goal_x + 0.6, -1.5, 1.5)


def overhang(seed: int, rng: random.Random) -> Scene:
    """A low overhang: a shelf 0.6 m deep right across the straight way to the goal, 1.0-1.3 m ahead. Its underside is
    above the duck's head (0.32-0.40 m: walk under it, it is not a wall) or below it (0.15-0.22 m: go round), by seed
    (RFC-0008 §3: overhead classification)."""
    high = seed % 2 == 0
    under = rng.uniform(0.32, 0.40) if high else rng.uniform(0.15, 0.22)
    x, goal_x = rng.uniform(1.0, 1.3), rng.uniform(2.6, 3.0)
    shelf = Box("shelf", x + 0.3, rng.uniform(-0.1, 0.1), 0.3, 0.5, under, under + 0.03)
    return Scene(f"ch13-s{seed}", "A low overhang", _room(goal_x) + [shelf], [slab("floor", -0.6, goal_x + 0.6, -1.5, 1.5)],
                 (goal_x, rng.uniform(-0.2, 0.2)), "reach", 90.0, notes={"underside_m": round(under, 3), "walk_under": high})


def thin_legs(seed: int, rng: random.Random) -> Scene:
    """A thin pole, or a chair's legs: legs 2-4 cm across on the way to the goal, one pole or four in a 0.38 m square
    under a seat above the duck's head, by seed: small obstacles for an 8x8 sensor (RFC-0008 §3)."""
    goal_x, x, y = rng.uniform(2.4, 2.8), rng.uniform(1.0, 1.4), rng.uniform(-0.1, 0.1)
    w = rng.uniform(0.02, 0.04)
    if seed % 2 == 0:
        legs = [Box("leg", x, y, w / 2, w / 2, 0.0, 0.5)]
    else:
        legs = [Box(f"leg{i}", x + dx, y + dy, w / 2, w / 2, 0.0, 0.42) for i, (dx, dy) in
                enumerate(((-0.19, -0.19), (0.19, -0.19), (0.19, 0.19), (-0.19, 0.19)))]
        legs.append(Box("seat", x, y, 0.22, 0.22, 0.42, 0.45))
    return Scene(f"ch14-s{seed}", "A thin pole, a chair's legs", _room(goal_x) + legs,
                 [slab("floor", -0.6, goal_x + 0.6, -1.5, 1.5)], (goal_x, rng.uniform(-0.2, 0.2)), "reach", 90.0,
                 notes={"legs": 1 if seed % 2 == 0 else 4, "leg_m": round(w, 3)})


def small_boxes(seed: int, rng: random.Random) -> Scene:
    """A field of small boxes: 6-10 boxes 8-20 cm across and 5-25 cm tall scattered between the start and the goal, at
    least 0.45 m apart, none within 0.3 m of the start or the goal: replanning and the reflex (RFC-0008 §3)."""
    goal_x, goal_y = rng.uniform(2.6, 3.0), rng.uniform(-0.3, 0.3)
    want, centres, tries = rng.randint(6, 10), [], 0
    while len(centres) < want and tries < 2000:
        tries += 1
        c = (rng.uniform(0.4, goal_x - 0.2), rng.uniform(-1.2, 1.2))
        if math.dist(c, (0.0, 0.0)) > 0.3 and math.dist(c, (goal_x, goal_y)) > 0.3 and \
                all(math.dist(c, o) >= 0.45 for o in centres):
            centres.append(c)
    boxes = [Box(f"small{i}", cx, cy, rng.uniform(0.04, 0.1), rng.uniform(0.04, 0.1), 0.0, rng.uniform(0.05, 0.25),
                 rng.uniform(-math.pi, math.pi)) for i, (cx, cy) in enumerate(centres)]
    return Scene(f"ch15-s{seed}", "A field of small boxes", _room(goal_x) + boxes,
                 [slab("floor", -0.6, goal_x + 0.6, -1.5, 1.5)], (goal_x, goal_y), "reach", 90.0, notes={"boxes": len(boxes)})


def threshold(seed: int, rng: random.Random) -> Scene:
    """A threshold or bump that tilts the duck: a bar 0.5-1.0 cm high and 4 cm deep across a 0.8 m corridor, 0.8-1.2 m
    ahead, stepped over on the way to the goal 1.4-1.8 m beyond it. A raised floor strip, not an obstacle: the duck
    walks on it. Tests false drops from pitch (RFC-0008 §3, trial 12). Heights within what the walking crosses
    (docs/wip/STEPS.md: 1 cm 2/3 at 0.3 m/s, 4/5 at 0.4; 1.5 cm 1/3 and 0/5; the operator 2026-11-18: challenges follow
    the robot's capability); 1.5 cm and up is a later challenge, "too high to cross: stop, do not fall"."""
    x, h, beyond = rng.uniform(0.8, 1.2), rng.uniform(0.005, 0.01), rng.uniform(1.4, 1.8)
    end = x + beyond + 0.6
    # edge to edge, not a bar laid on a floor running under it: the simulator tripped the duck on that build (1 cm: 0/3
    # crossed against 2/3 in pieces, docs/wip/STEPS.md), which was most of this challenge's 0/10
    floors = [slab("floor", -0.6, x - 0.02, -0.4, 0.4), slab("threshold", x - 0.02, x + 0.02, -0.4, 0.4, top=h),
              slab("floor_beyond", x + 0.02, end, -0.4, 0.4)]
    return Scene(f"ch16-s{seed}", "A threshold to step over", _walled("corr", -0.6, end, -0.4, 0.4), floors,
                 (x + beyond, 0.0), "reach", 75.0, notes={"height_m": round(h, 3), "at_m": round(x, 3)})


def _strips(xs: list, tops: list, y0: float = -0.4, y1: float = 0.4, names=None) -> list:
    """Floor pieces across the corridor meeting edge to edge: xs the edges (n+1), tops the n tops."""
    names = names or [f"floor_{i}" for i in range(len(tops))]
    return [slab(n, a, b, y0, y1, top=t) for n, a, b, t in zip(names, xs, xs[1:], tops)]


def floor_things(seed: int, rng: random.Random) -> Scene:
    """Things on the floor, walked over (RFC-0008 §3 challenge 17): a cable, a rug or a book, 0.8-1.2 m ahead, the goal
    1.4-1.8 m beyond. Heights within what the walking crosses (under 1 cm, docs/wip/STEPS.md); every floor in pieces
    meeting edge to edge. A cable: a bar 0.5-0.8 cm high and 2 cm deep across the way. A rug: a raised strip 0.5-1.0 cm,
    0.5-0.7 m long, the whole width (on it, across it, off it). A book: 0.8-1.0 cm, 15 x 22 cm, lying on the way."""
    x, beyond = rng.uniform(0.8, 1.2), rng.uniform(1.4, 1.8)
    end, kind = x + beyond + 0.6, rng.choice(["cable", "rug", "book"])
    if kind == "cable":
        h, d = rng.uniform(0.005, 0.008), 0.02
        floors = _strips([-0.6, x, x + d, end], [0.0, h, 0.0], names=["floor", "cable", "floor_beyond"])
    elif kind == "rug":
        h, d = rng.uniform(0.005, 0.01), rng.uniform(0.5, 0.7)
        floors = _strips([-0.6, x, x + d, end], [0.0, h, 0.0], names=["floor", "rug", "floor_beyond"])
    else:
        h, d, w = rng.uniform(0.008, 0.01), 0.15, 0.22
        yc = rng.uniform(-0.1, 0.1)
        floors = [slab("floor", -0.6, x, -0.4, 0.4), slab("floor_beyond", x + d, end, -0.4, 0.4),
                  slab("floor_s", x, x + d, -0.4, yc - w / 2), slab("floor_n", x, x + d, yc + w / 2, 0.4),
                  slab("book", x, x + d, yc - w / 2, yc + w / 2, top=h)]
    return Scene(f"ch17-s{seed}", f"A {kind} on the floor", _walled("corr", -0.6, end, -0.4, 0.4), floors,
                 (x + beyond, 0.0), "reach", 75.0, notes={"kind": kind, "height_m": round(h, 4), "at_m": round(x, 3)})


def step_up_down(seed: int, rng: random.Random) -> Scene:
    """A step up and a step down (challenge 18): up 0.5-1.0 cm onto a platform 0.8-1.2 m long, then down 0.5-1.5 cm
    (STEPS.md: up 3/3 at both, down 3/3 to 2 cm), the goal on the far side."""
    x, up, length, down, beyond = (rng.uniform(0.7, 1.0), rng.uniform(0.005, 0.01), rng.uniform(0.8, 1.2),
                                   rng.uniform(0.005, 0.015), rng.uniform(0.6, 0.9))
    x2, end = x + length, x + length + beyond + 0.5
    floors = _strips([-0.6, x, x2, end], [0.0, up, up - down], names=["floor", "platform", "step_beyond"])
    # walls down to the lowest floor: a gap under them is a hole the depth sensor sees through (challenge 20's first build)
    walls = _walled("corr", -0.6, end, -0.4, 0.4, z0=min(0.0, up - down))
    return Scene(f"ch18-s{seed}", "A step up and a step down", walls, floors,
                 (x2 + beyond, 0.0), "reach", 90.0, notes={"up_m": round(up, 4), "down_m": round(down, 4)})


def flight(up: bool):
    def build(seed: int, rng: random.Random) -> Scene:
        """A short flight of three small steps, up (challenge 19: 0.5 cm risers; STEPS.md: about 70 % of risers cleared,
        a flight 1/3) or down (challenge 20: 1.0-2.0 cm risers; 3/3), 0.25 m treads, the goal on top or at the bottom."""
        x, beyond = rng.uniform(0.7, 1.0), rng.uniform(0.6, 0.9)
        h = 0.005 if up else rng.uniform(0.01, 0.02)
        sign, tread = (1 if up else -1), 0.25
        xs = [-0.6] + [x + i * tread for i in range(4)] + [x + 3 * tread + beyond + 0.5]
        tops = [0.0] + [sign * (i + 1) * h for i in range(4)]
        tops[4] = tops[3]
        floors = _strips(xs, tops, names=["floor", "step1", "step2", "step3", "step_top"])
        cid = "19" if up else "20"
        return Scene(f"ch{cid}-s{seed}", f"A short flight of small steps, {'up' if up else 'down'}",
                     _walled("corr", -0.6, xs[-1], -0.4, 0.4, z0=min(tops)), floors, (x + 3 * tread + beyond, 0.0), "reach", 90.0,
                     notes={"riser_m": round(h, 4), "steps": 3})
    build.__name__ = "flight_up" if up else "flight_down"
    return build


def _gap(a: tuple, b: tuple) -> float:
    """The distance between two axis-aligned rectangles (cx, cy, hx, hy); a point is one with no half-sides."""
    return math.hypot(max(abs(a[0] - b[0]) - a[2] - b[2], 0.0), max(abs(a[1] - b[1]) - a[3] - b[3], 0.0))


def _scatter(rng: random.Random, n: int, x0: float, x1: float, y0: float, y1: float, away: list = (), off: list = (),
             name: str = "box") -> list:
    """n boxes (0.24-0.5 m a side, 0.3-0.45 m tall, axis-aligned) in x0..x1 × y0..y1, at least 0.5 m from its edges (room
    to pass between a box and a wall), 0.6 m from each other and from every rectangle in `off`, and `r` from every
    (x, y, r) in `away`. Fewer than n if the room has no room for them."""
    out, tries = [], 0
    while len(out) < n and tries < 2000:
        tries += 1
        hx, hy = rng.uniform(0.12, 0.25), rng.uniform(0.12, 0.25)
        cx, cy = rng.uniform(x0 + 0.5 + hx, x1 - 0.5 - hx), rng.uniform(y0 + 0.5 + hy, y1 - 0.5 - hy)
        rect = (cx, cy, hx, hy)
        if all(_gap(rect, (ax, ay, 0.0, 0.0)) >= r for ax, ay, r in away) and all(_gap(rect, o) >= 0.6 for o in off) \
                and all(_gap(rect, (b.cx, b.cy, b.hx, b.hy)) >= 0.6 for b in out):
            out.append(Box(f"{name}{len(out)}", round(cx, 4), round(cy, 4), hx, hy, 0.0, rng.uniform(0.3, 0.45)))
    return out


def _around_hole(x0: float, x1: float, y0: float, y1: float, hole: tuple, depth: float) -> list:
    """The room's floor in pieces round a rectangular hole (hxa, hxb, hya, hyb) in it or against a wall, edge to edge, and the
    hole's own floor `depth` lower, named so the scene's drops() has it."""
    hxa, hxb, hya, hyb = hole
    floors = [slab("stairwell", hxa, hxb, hya, hyb, top=-depth)]
    if hxa > x0 + 1e-9:
        floors.append(slab("west", x0, hxa, y0, y1))
    if x1 > hxb + 1e-9:
        floors.append(slab("east", hxb, x1, y0, y1))
    if hya > y0 + 1e-9:
        floors.append(slab("south", hxa, hxb, y0, hya))
    if y1 > hyb + 1e-9:
        floors.append(slab("north", hxa, hxb, hyb, y1))
    return floors


def ten_goals(seed: int, rng: random.Random) -> Scene:
    """Localization drift (challenge 21): one walled room about 3 × 3 m, the start inside, up to three boxes, a stairwell-like
    hole 0.6-0.8 m a side against a wall, and ten goals to visit in turn on one reset, each 1 m or more from the one before
    and 0.3 m from every other goal. What failed before (explore b10a: a 0.9 m jump of the belief while pivoting in place
    beside an obstacle; the side drops) is what the goals ask for: four goals 0.25-0.4 m from a box (a pivot beside it,
    leaving and arriving), two 0.55-0.7 m from the hole (the planner's zone and its glances), four in the open. All goals
    0.45 m from the walls and 0.55 m from the hole. Judged by truth at each goal; the belief's error, in position and in
    heading, at each is the drift."""
    w, h = rng.uniform(2.9, 3.3), rng.uniform(2.9, 3.3)
    x0, y0 = -w * rng.uniform(0.35, 0.65), -h * rng.uniform(0.35, 0.65)
    x1, y1 = x0 + w, y0 + h
    hw, hl, depth = rng.uniform(0.6, 0.8), rng.uniform(0.6, 0.8), rng.uniform(1.0, 2.7)
    far = sorted("snwe", key=lambda s_: -{"s": -y0, "n": y1, "w": -x0, "e": x1}[s_])[:2]     # the two walls farthest from the start
    for _ in range(200):                     # the hole against one of them, at least 0.6 m from the start
        side = rng.choice(far)
        if side in "sn":
            hxa = rng.uniform(x0 + 0.5, x1 - 0.5 - hw)
            hole = (hxa, hxa + hw, y0 if side == "s" else y1 - hl, y0 + hl if side == "s" else y1)
        else:
            hya = rng.uniform(y0 + 0.5, y1 - 0.5 - hl)
            hole = (x0 if side == "w" else x1 - hw, x0 + hw if side == "w" else x1, hya, hya + hl)
        hrect = ((hole[0] + hole[1]) / 2, (hole[2] + hole[3]) / 2, (hole[1] - hole[0]) / 2, (hole[3] - hole[2]) / 2)
        if _gap((0.0, 0.0, 0.0, 0.0), hrect) >= 0.6:
            break
    else:
        raise RuntimeError(f"challenge 21, seed {seed}: no place for the hole")
    for _ in range(20):                      # two boxes at least: the goals beside them need something to be beside
        boxes = _scatter(rng, 3, x0, x1, y0, y1, away=[(0.0, 0.0, 0.7)], off=[hrect])
        if len(boxes) >= 2:
            break
    rects = [(b.cx, b.cy, b.hx, b.hy) for b in boxes]

    def draw():
        order = ["box"] * 4 + ["drop"] * 2 + ["open"] * 4
        rng.shuffle(order)
        goals, prev = [], (0.0, 0.0)
        for kind in order:
            for _ in range(1500):
                c = (rng.uniform(x0 + 0.45, x1 - 0.45), rng.uniform(y0 + 0.45, y1 - 0.45))
                near_box = min((_gap((*c, 0.0, 0.0), r) for r in rects), default=math.inf)
                near_hole = _gap((*c, 0.0, 0.0), hrect)
                if math.dist(c, prev) < 1.0 or any(math.dist(c, g) < 0.3 for g, _ in goals) or near_hole < 0.55 or near_box < 0.25:
                    continue
                if (kind == "box" and near_box > 0.4) or (kind == "drop" and near_hole > 0.7) or \
                        (kind == "open" and (near_box < 0.4 or near_hole < 0.7)):
                    continue
                goals.append(((round(c[0], 3), round(c[1], 3)), kind))
                prev = c
                break
            else:
                return None
        return goals
    for _ in range(300):                     # a greedy draw can dead-end in a corner: start it again
        goals = draw()
        if goals:
            break
    else:
        raise RuntimeError(f"challenge 21, seed {seed}: no ten goals fit the room")
    walls = _walled("room", x0, x1, y0, y1, z0=-depth)
    return Scene(f"ch21-s{seed}", "Ten goals in a row, one reset", walls + boxes, _around_hole(x0, x1, y0, y1, hole, depth),
                 goals[0][0], "reach", 60.0, mode="sequence", goals=tuple(g for g, _ in goals),
                 notes={"room_m": [round(w, 2), round(h, 2)], "boxes": len(boxes), "time_s_per_goal": 60.0,
                        "goal_kinds": [k for _, k in goals], "hole_side": side, "depth_m": round(depth, 2)})


def one_room_with_a_drop(seed: int, rng: random.Random) -> Scene:
    """Exploring coverage, and trapped near a drop (challenge 22): one walled room about 3 × 3.5 m, the start 0.5-0.8 m
    from a stairwell-like hole in the floor (1-2.7 m deep, 0.8-1.0 m wide, 0.6-0.9 m long) against one wall, and up to three
    boxes. The explorer runs (not go_to) for 5 minutes; the room's floor the map should know is the room's reachable
    floor (floor.py). The hole is on the start's left or right by seed."""
    w, h = rng.uniform(2.8, 3.2), rng.uniform(3.3, 3.7)
    d, hw, hl, depth, s = rng.uniform(0.5, 0.8), rng.uniform(0.8, 1.0), rng.uniform(0.6, 0.9), rng.uniform(1.0, 2.7), rng.choice((-1, 1))
    hxa = -rng.uniform(0.2, 0.5)
    hxb = hxa + hw
    x0 = -rng.uniform(1.2, 1.8)
    x1 = max(x0 + w, hxb + 0.7)                # no sliver of floor between the hole and the east wall
    yn = d + hl
    ys = yn - h

    def ys_(a: float, b: float) -> tuple:     # y edges of the side the hole is on (mirrored for s = -1), low first
        return tuple(sorted((a * s, b * s)))
    floors = [slab("south", x0, x1, *ys_(ys, d)), slab("nw", x0, hxa, *ys_(d, yn)), slab("ne", hxb, x1, *ys_(d, yn)),
              slab("stairwell", hxa, hxb, *ys_(d, yn), top=-depth)]
    # walls down to the lowest floor, the hole's too: a gap under a wall is a hole the depth sensor sees through
    walls = _walled("room", x0, x1, *ys_(ys, yn), z0=-depth)
    hole = (hxa, hxb, *ys_(d, yn))
    boxes = _scatter(rng, 3, x0, x1, *ys_(ys, d), away=[(0.0, 0.0, 0.7)],
                     off=[((hole[0] + hole[1]) / 2, (hole[2] + hole[3]) / 2, (hole[1] - hole[0]) / 2, (hole[3] - hole[2]) / 2)])
    room = Box("room", (x0 + x1) / 2, (ys_(ys, yn)[0] + ys_(ys, yn)[1]) / 2, (x1 - x0) / 2, h / 2, 0.0, 0.0)
    return Scene(f"ch22-s{seed}", "One room, explored, a drop by the start", walls + boxes, floors, (0.0, 0.0), "explore", 300.0,
                 mode="explore", areas=(room,),
                 notes={"room_m": [round(x1 - x0, 2), round(h, 2)], "hole_from_start_m": round(d, 3), "hole_m": [round(hw, 2), round(hl, 2)],
                        "depth_m": round(depth, 2), "side": s, "boxes": len(boxes)})


def _mirrored(b: Box) -> Box:
    return replace(b, cx=-b.cx, yaw=round(-b.yaw, 5))


def two_rooms(seed: int, rng: random.Random) -> Scene:
    """Frontier choice and crossing a door (challenge 23): two walled rooms about 2.4-3 m a side, the start in one, joined
    by a door 0.6-0.8 m wide in the wall between them, or by a corridor 0.4-0.8 m long of that width, one to three
    boxes in each (the start's room, with the door's mouth and the start kept clear, often fits one or two). The door is
    ahead of the start or behind it by seed (the scene is mirrored), and anywhere along its wall. The explorer runs for 8 minutes; both rooms' reachable floor should be known, and the door crossed."""
    wa, ha = rng.uniform(2.4, 2.9), rng.uniform(2.4, 3.0)
    wb, hb = rng.uniform(2.4, 3.0), rng.uniform(2.4, 3.0)
    gap, length = rng.uniform(0.6, 0.8), rng.choice((0.0, rng.uniform(0.4, 0.8)))
    ax0 = -rng.uniform(0.9, 1.3)
    ay0 = -ha * rng.uniform(0.35, 0.65)
    ax1, ay1 = ax0 + wa, ay0 + ha
    door = rng.uniform(ay0 + 0.5 + gap / 2, ay1 - 0.5 - gap / 2)
    bx0 = ax1 + length
    bx1 = bx0 + wb
    by0 = door - gap / 2 - rng.uniform(0.5, hb - gap - 0.5)      # the door is at least 0.5 m from B's corners
    by1 = by0 + hb
    walls = _walled("wa", ax0, ax1, ay0, ay1, skip=("e",)) + _walled("wb", bx0, bx1, by0, by1, skip=("w",))
    walls += [wall("wa_e1", ax1, ay0, ax1, door - gap / 2), wall("wa_e2", ax1, door + gap / 2, ax1, ay1),
              wall("wb_w1", bx0, by0, bx0, door - gap / 2), wall("wb_w2", bx0, door + gap / 2, bx0, by1)]
    floors = [slab("a", ax0, ax1, ay0, ay1), slab("b", bx0, bx1, by0, by1)]
    if length:
        t = 0.02                               # the corridor's walls stand outside the door's gap: the gap is its clear width
        walls += [wall("pass_s", ax1, door - gap / 2 - t, bx0, door - gap / 2 - t), wall("pass_n", ax1, door + gap / 2 + t, bx0, door + gap / 2 + t)]
        floors.append(slab("pass", ax1, bx0, door - gap / 2, door + gap / 2))
    for r_start, r_door in ((0.7, 0.9), (0.6, 0.7), (0.5, 0.6)):       # the start's room must hold a box; the clearances give a little
        boxes = _scatter(rng, 3, ax0, ax1, ay0, ay1, away=[(0.0, 0.0, r_start), (ax1, door, r_door)], name="a_box")
        if boxes:
            break
    boxes += _scatter(rng, 3, bx0, bx1, by0, by1, away=[(bx0, door, 0.9)], name="b_box")
    areas = (Box("room_a", (ax0 + ax1) / 2, (ay0 + ay1) / 2, wa / 2, ha / 2, 0.0, 0.0),
             Box("room_b", (bx0 + bx1) / 2, (by0 + by1) / 2, wb / 2, hb / 2, 0.0, 0.0))
    ahead = rng.random() < 0.5
    walls, boxes, floors, areas = ((walls, boxes, floors, areas) if ahead else
                                   ([_mirrored(b) for b in walls], [_mirrored(b) for b in boxes], [_mirrored(b) for b in floors],
                                    tuple(_mirrored(b) for b in areas)))
    return Scene(f"ch23-s{seed}", "Two rooms through a door", walls + boxes, floors, (0.0, 0.0), "explore", 480.0, mode="explore",
                 areas=areas, notes={"door_m": round(gap, 3), "corridor_m": round(length, 3), "door_ahead": ahead,
                                     "rooms_m": [[round(wa, 2), round(ha, 2)], [round(wb, 2), round(hb, 2)]],
                                     "boxes": len(boxes)})


CHALLENGES = {"1": corridor, "2": doorway, "3": corner_in_doorway, "4": box_in_open, "5": u_turn, "6": dead_end, "7": wedged, "8": step_down, "9": step_down_diagonal, "10": ledge, "11": passage_by_hole, "12": table_edge,
              "13": overhang, "14": thin_legs, "15": small_boxes, "16": threshold, "17": floor_things, "18": step_up_down,
              "19": flight(True), "20": flight(False), "21": ten_goals, "22": one_room_with_a_drop, "23": two_rooms}


def build(challenge: str, seed: int) -> Scene:
    """The challenge's scene for this seed, as the duck meets it: drawn, then moved by the start's jitter."""
    rng = random.Random(f"{challenge}-{seed}")
    scene = CHALLENGES[challenge](seed, rng)
    d, a = START_JITTER
    return moved(scene, (rng.uniform(-d, d), rng.uniform(-d, d), rng.uniform(-a, a)))
