"""A simulated camera with object recognition (RFC-0016 §3.3), the stand-in until a real camera and detector exist.
It sits with the simulator's truth (Body), not in the brain's world_model package: it reads the scene
(sim/apartment_layout.json; which geoms make one object, sim/apartment_objects.json) and the duck's true pose.

It reports what a camera on the duck would recognise: the objects with a part inside the field of view and range and
not hidden behind a wall (the layout's walls only: a rug or a landmark hides nothing), each with a probability falling
to half at the range limit. A report is a semantic_map.Detection — a kind, and the object as a disc relative to the duck
(the centre of its parts with range and bearing noise, the radius that covers them, its height band) — with no name
and no world coordinate, so the truth reaches the brain only through this sensor model and the brain places it with
its own belief, as a real camera's. Fidelity: calibration/<robot>.json "camera".
"""

import json
import math
import random
from pathlib import Path

from duck_lab.world_model.objects import part_from_geom
from duck_lab.world_model.semantic_map import Detection, centre

SIM_DIR = Path(__file__).resolve().parents[3] / "sim"
DEFAULTS = {"hfov_deg": 60.0, "range_m": 3.0, "p_detect": 0.8, "range_noise": 0.05, "bearing_noise_deg": 2.0,
            "period_s": 0.5}


def _segment_hits_box(a: tuple, b: tuple, g: dict) -> bool:
    """Whether the segment a-b crosses a box geom's footprint (slab test in the box's frame)."""
    c, s = math.cos(-g.get("yaw", 0.0)), math.sin(-g.get("yaw", 0.0))
    ox, oy = g["pos"][0], g["pos"][1]
    ax, ay = c * (a[0] - ox) - s * (a[1] - oy), s * (a[0] - ox) + c * (a[1] - oy)
    bx, by = c * (b[0] - ox) - s * (b[1] - oy), s * (b[0] - ox) + c * (b[1] - oy)
    t0, t1 = 0.0, 1.0
    for p, d, h in ((ax, bx - ax, g["size"][0]), (ay, by - ay, g["size"][1])):
        if abs(d) < 1e-12:
            if abs(p) > h:
                return False
            continue
        u, v = (-h - p) / d, (h - p) / d
        t0, t1 = max(t0, min(u, v)), min(t1, max(u, v))
        if t0 > t1:
            return False
    return True


class SimCamera:
    def __init__(self, layout: Path = SIM_DIR / "apartment_layout.json", objects: Path = SIM_DIR / "apartment_objects.json",
                 config: dict = None, seed: int = None):
        geoms = {g["name"]: g for g in json.loads(Path(layout).read_text())["geoms"]}
        self.cfg = {**DEFAULTS, **{k: v for k, v in (config or {}).items() if k in DEFAULTS}}
        self.walls = [g for n, g in geoms.items() if n.startswith("w") and g["type"] == "box"]
        self.objects = [(oid, o["kind"], [part_from_geom(geoms[p]) for p in o["parts"]])
                        for oid, o in json.loads(Path(objects).read_text())["objects"].items()]
        self.rng = random.Random(seed)

    def visible(self, truth: tuple, parts) -> float | None:
        """The range to the nearest part in view and not behind a wall, None when none is."""
        best = None
        half = math.radians(self.cfg["hfov_deg"]) / 2
        for q in parts:
            r = math.dist(truth[:2], (q.x, q.y))
            if r > self.cfg["range_m"] or r < 0.05:
                continue
            bearing = math.atan2(q.y - truth[1], q.x - truth[0]) - truth[2]
            if abs(math.atan2(math.sin(bearing), math.cos(bearing))) > half:
                continue
            if any(_segment_hits_box(truth[:2], (q.x, q.y), w) for w in self.walls):
                continue
            best = r if best is None else min(best, r)
        return best

    def detect(self, truth: tuple) -> list:
        """The objects recognised from the duck's true pose (world x, y, yaw), relative to the duck."""
        out = []
        c, s = math.cos(-truth[2]), math.sin(-truth[2])
        for _, kind, parts in self.objects:
            r = self.visible(truth, parts)
            p = self.cfg["p_detect"] * (1.0 - 0.5 * r / self.cfg["range_m"]) if r is not None else 0.0
            if r is None or self.rng.random() > p:
                continue
            wx, wy = centre(parts)
            radius = max(math.dist((wx, wy), (q.x, q.y)) + math.hypot(q.hx, q.hy) for q in parts)
            dx, dy = wx - truth[0], wy - truth[1]
            rx, ry = c * dx - s * dy, s * dx + c * dy
            rr = math.hypot(rx, ry) * (1.0 + self.rng.gauss(0.0, self.cfg["range_noise"]))
            b = math.atan2(ry, rx) + math.radians(self.rng.gauss(0.0, self.cfg["bearing_noise_deg"]))
            # its confidence is its own chance of seeing the object there; no evidence (no image): a real camera's
            # detector adds the frame and the box (RFC-0016 §4)
            out.append(Detection(kind, rr * math.cos(b), rr * math.sin(b), round(radius, 3),
                                 min(q.z0 for q in parts), max(q.z1 for q in parts), r, round(p, 2), "sim_camera"))
        return out

    def truth_objects(self, kind: str) -> list:
        """The scene's objects of a kind, for the judge (not the brain): [(id, parts in the world)]."""
        return [(oid, parts) for oid, k, parts in self.objects if k == kind]
