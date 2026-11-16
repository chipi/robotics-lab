"""The challenges (RFC-0008 §3, ADR-0015): each a function from a seed to a scene in its own frame, the duck's start at
the origin facing +x. The ranges are first guesses (ADR-0015), to tune when they run. Every edge of the start's floor
that is not the challenge's drop is walled: the only drop is the one being tested.
"""

import math
import random

from duck_lab.challenge.scene import TRUNK_START, Box, Scene, moved, slab, wall

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
    ahead, aside, side = rng.uniform(0.16, 0.22), rng.uniform(0.14, 0.2), rng.choice((-1, 1))
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


CHALLENGES = {"1": corridor, "2": doorway, "3": corner_in_doorway, "4": box_in_open, "5": u_turn, "6": dead_end, "7": wedged, "8": step_down, "9": step_down_diagonal}


def build(challenge: str, seed: int) -> Scene:
    """The challenge's scene for this seed, as the duck meets it: drawn, then moved by the start's jitter."""
    rng = random.Random(f"{challenge}-{seed}")
    scene = CHALLENGES[challenge](seed, rng)
    d, a = START_JITTER
    return moved(scene, (rng.uniform(-d, d), rng.uniform(-d, d), rng.uniform(-a, a)))
