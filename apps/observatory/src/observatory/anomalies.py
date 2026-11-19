"""Found anomalies (RFC-0019 section 3.2): detectors over one recording, each a function that returns records.

A detector reads a `Run` (the records of one run, events whole: `mcapio.read(..., keep_raw=True)`) and, when it
needs the real world, a `Truth` (the simulator's layout, passed as data: no robot code is imported). It returns anomaly
records in the shape of RFC-0019 section 2.1, source "analysis". Nothing here writes into a run; the derived index takes
the results later, keyed by run, detector and version.

Every detector has an id, a version (the rules below: change a rule, bump the version), its rule in words, what it
needs, and whether it is on the default track. A detector earns the default track by staying quiet on the clean runs
(RFC-0019 section 3.2, PHASE3-PREP B2); the rest run only when asked (`experimental`) and say so.
"""

import bisect
import math
import re
import statistics
from collections import deque

from runfile.se2 import compose, inverse
from runfile.store import build

SEVERITIES = ("info", "minor", "major", "critical")

# the rules' numbers, each from the runs it was read from (PHASE3-PREP B2); `cfg` overrides them per call
DEFAULTS = {
    "near_miss_m": 0.090,          # truth clearance under this without contact (quiet on b9 r2, b10b r1/r3, b11 r1)
    "robot_radius_m": 0.083,       # clearance under this is a contact (the judge's FOOTPRINT_M), a run's robot record wins
    "overhead_m": 0.30,            # an obstacle whose underside is higher than this passes over the duck's head
    "mapd_ceiling_m": 0.40,        # mapd's own ceiling: a return higher than this is overhead
    "dither_window_s": 3.0, "dither_net_m": 0.12, "walking_vx": 0.1,
    "odom_low": 0.95, "odom_high": 1.05, "odom_min_walk_m": 2.0, "odom_leg_min_m": 0.5,
    "odom_legs_out": None,         # legs outside the band that fire it alone: off (3 fired on b10b r1, a clean run: mapd's fixes inflate legs)
    "odom_jump_m": 0.15,           # a belief step this long in one tick is a fix, not odometry
    "belief_warn_m": 0.20, "belief_major_m": 0.35, "heading_deg": 20.0,
    "phantom_cells": 3, "phantom_far_m": 0.30,
    "missed_samples": 3, "missed_near_m": 0.15, "missed_step_m": 0.05,
    "edge_off_m": 0.25, "edge_within_s": 5.0,
    "cover_min": 0.5, "cover_step_m": 0.1,
    "raster_m": 0.025,
}


# ---- the real world: the simulator's layout as data ------------------------------------------------------------------

def footprint_distance(x: float, y: float, g: dict) -> float:
    """2D distance from (x, y) to a geom's footprint (a box with yaw; anything else is a circle of size[0])."""
    dx, dy = x - g["pos"][0], y - g["pos"][1]
    if g["type"] == "box":
        c, s = math.cos(-g.get("yaw", 0.0)), math.sin(-g.get("yaw", 0.0))
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return math.hypot(max(abs(lx) - g["size"][0], 0.0), max(abs(ly) - g["size"][1], 0.0))
    return max(math.hypot(dx, dy) - g["size"][0], 0.0)


def underside(g: dict) -> float:
    z = g["pos"][2]
    if g["type"] == "box":
        return z - g["size"][2]
    if g["type"] == "cylinder":
        return z - g["size"][1]
    if g["type"] == "capsule":
        return z - g["size"][1] - g["size"][0]
    return z - g["size"][0]


def perimeter(g: dict, step: float) -> list:
    """Points along a geom's footprint outline, `step` apart."""
    cx, cy = g["pos"][0], g["pos"][1]
    if g["type"] == "box":
        c, s = math.cos(g.get("yaw", 0.0)), math.sin(g.get("yaw", 0.0))
        hx, hy = g["size"][0], g["size"][1]
        pts = []
        for (ax, ay), (bx, by) in (((-hx, -hy), (hx, -hy)), ((hx, -hy), (hx, hy)), ((hx, hy), (-hx, hy)), ((-hx, hy), (-hx, -hy))):
            n = max(1, math.ceil(math.hypot(bx - ax, by - ay) / step))
            for k in range(n):
                u = k / n
                lx, ly = ax + u * (bx - ax), ay + u * (by - ay)
                pts.append((cx + c * lx - s * ly, cy + s * lx + c * ly))
        return pts
    r = g["size"][0]
    n = max(8, math.ceil(2 * math.pi * r / step))
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


class Truth:
    """The simulator's layout: geoms with type, pos, size, yaw, collides (sim/apartment_layout.json, which holds the free
    bodies too). Several layouts merge into one."""

    def __init__(self, layouts: list, overhead_m: float = DEFAULTS["overhead_m"], ceiling_m: float = DEFAULTS["mapd_ceiling_m"]):
        self.geoms = [g for lay in layouts for g in lay["geoms"]]
        # what the duck can walk into (the judge's rule): not the floors, not the stairs' treads, markers included
        self.obstacles = [g for g in self.geoms if self._solid(g) and underside(g) <= overhead_m]
        # what a depth return can really come from, for a map to be compared with: also the stairs' risers, up to mapd's ceiling
        self.outline = [g for g in self.geoms if self._solid(g, stairs=True) and underside(g) <= ceiling_m]
        stairs = [g for g in self.geoms if g["name"].startswith("stair")]
        self.hole = (min(g["pos"][0] - g["size"][0] for g in stairs), max(g["pos"][0] + g["size"][0] for g in stairs),
                     min(g["pos"][1] - g["size"][1] for g in stairs), max(g["pos"][1] + g["size"][1] for g in stairs)) if stairs else None
        self.rooms = {g["name"].removeprefix("floor_"): g for g in self.geoms
                      if g["name"].startswith("floor_") and not g.get("collides") and g["type"] == "box"}
        self.floors = [g for g in self.geoms if g["name"].startswith("floor") and g.get("collides") and g["type"] == "box"]
        self._raster = {}

    @staticmethod
    def _solid(g: dict, stairs: bool = False) -> bool:
        name = g["name"]
        marker = name.startswith("lm_")
        if (not g.get("collides") and not marker) or g["type"] == "plane" or name.startswith("floor"):
            return False
        return stairs or not name.startswith("stair")

    @classmethod
    def from_layouts(cls, layouts: list, **kw) -> "Truth":
        for lay in layouts:
            if not isinstance(lay, dict) or not isinstance(lay.get("geoms"), list):
                raise ValueError("a layout is an object with a list of geoms")
        return cls(layouts, **kw)

    def clearance(self, x: float, y: float) -> tuple:
        """(distance to the nearest obstacle's footprint, its name)."""
        best, name = math.inf, None
        for g in self.obstacles:
            d = footprint_distance(x, y, g)
            if d < best:
                best, name = d, g["name"]
        return best, name

    def outline_distance(self, x: float, y: float) -> float:
        return min((footprint_distance(x, y, g) for g in self.outline), default=math.inf)

    def hole_distance(self, x: float, y: float) -> float:
        """0 inside the stairwell, else the distance to it."""
        x0, x1, y0, y1 = self.hole
        return math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1))

    def components(self, res: float, radius: float):
        """A labelled raster of where the duck's centre can be (inside a floor, `radius` clear of every obstacle and of the
        stairwell): (label of a point, or None) as a function, cached per (res, radius)."""
        key = (res, radius)
        if key in self._raster:
            return self._raster[key]
        x0 = min(g["pos"][0] - g["size"][0] for g in self.floors)
        x1 = max(g["pos"][0] + g["size"][0] for g in self.floors)
        y0 = min(g["pos"][1] - g["size"][1] for g in self.floors)
        y1 = max(g["pos"][1] + g["size"][1] for g in self.floors)
        w, h = math.ceil((x1 - x0) / res), math.ceil((y1 - y0) / res)
        free = bytearray(w * h)
        for g in self.floors:
            for cy in range(max(0, int((g["pos"][1] - g["size"][1] - y0) / res)), min(h, int((g["pos"][1] + g["size"][1] - y0) / res) + 1)):
                for cx in range(max(0, int((g["pos"][0] - g["size"][0] - x0) / res)), min(w, int((g["pos"][0] + g["size"][0] - x0) / res) + 1)):
                    free[cy * w + cx] = 1
        for g in self.obstacles:
            reach = max(g["size"][0], g["size"][1]) * (1.5 if g["type"] == "box" else 1.0) + radius
            for cy in range(max(0, int((g["pos"][1] - reach - y0) / res)), min(h, int((g["pos"][1] + reach - y0) / res) + 1)):
                for cx in range(max(0, int((g["pos"][0] - reach - x0) / res)), min(w, int((g["pos"][0] + reach - x0) / res) + 1)):
                    if free[cy * w + cx] and footprint_distance(x0 + (cx + .5) * res, y0 + (cy + .5) * res, g) < radius:
                        free[cy * w + cx] = 0
        if self.hole:
            hx0, hx1, hy0, hy1 = self.hole
            for cy in range(max(0, int((hy0 - radius - y0) / res)), min(h, int((hy1 + radius - y0) / res) + 1)):
                for cx in range(max(0, int((hx0 - radius - x0) / res)), min(w, int((hx1 + radius - x0) / res) + 1)):
                    if self.hole_distance(x0 + (cx + .5) * res, y0 + (cy + .5) * res) < radius:
                        free[cy * w + cx] = 0
        label = [0] * (w * h)
        n = 0
        for i in range(w * h):
            if free[i] and not label[i]:
                n += 1
                label[i] = n
                q = deque([i])
                while q:
                    j = q.popleft()
                    cx, cy = j % w, j // w
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and free[ny * w + nx] and not label[ny * w + nx]:
                            label[ny * w + nx] = n
                            q.append(ny * w + nx)

        def at(x: float, y: float):
            cx, cy = int((x - x0) / res), int((y - y0) / res)
            return label[cy * w + cx] or None if 0 <= cx < w and 0 <= cy < h else None
        self._raster[key] = at
        return at


# ---- one recording ---------------------------------------------------------------------------------------------------

class Run:
    """The records of a run in the shapes the detectors read. `records`: (t, kind, payload) with events whole."""

    def __init__(self, records: list):
        self.data = build(records)
        d = self.data
        self.run = d.run
        f = d.frames
        self.t, self.belief, self.truth, self.cmd = f["t"], f["belief"], f["truth"], f["cmd"]
        self.worlds = f["worlds"]
        self.segments = d.run["segments"]
        self.epochs = d.run["epochs"]
        self.has_truth = any(p is not None for p in self.truth)
        radius = (d.run.get("robot") or {}).get("radius")
        self.radius = radius if isinstance(radius, (int, float)) and radius > 0 else DEFAULTS["robot_radius_m"]
        self.events = []
        for _seq, t, kind, p in d.log:
            if kind == "event":
                self.events.append({**(p.get("raw") or {}), "t": t, "kind": p["kind"], "text": p.get("text", ""), "decision": p.get("decision")})
        self._epoch_t = [e["from_t"] for e in self.epochs]

    @property
    def key(self) -> str:
        return self.run.get("key") or ""

    def m2w(self, t: float):
        """The map-to-world transform in force at t (the identity when the run has none)."""
        i = bisect.bisect_right(self._epoch_t, t + 1e-9) - 1
        return tuple(self.epochs[max(i, 0)]["map_to_world"]) if self.epochs else (0.0, 0.0, 0.0)

    def belief_world(self, i: int):
        return compose(self.m2w(self.t[i]), tuple(self.belief[i]))

    def to_world(self, t: float, x: float, y: float) -> tuple:
        p = compose(self.m2w(t), (x, y, 0.0))
        return p[0], p[1]

    def to_map(self, t: float, x: float, y: float) -> tuple:
        p = compose(inverse(self.m2w(t)), (x, y, 0.0))
        return p[0], p[1]

    def tick_at(self, t: float) -> int:
        return max(0, min(len(self.t) - 1, bisect.bisect_right(self.t, t) - 1))

    def where(self, i: int) -> dict:
        w = {"frame": "world"}
        if self.belief and 0 <= i < len(self.t):
            b = self.belief_world(i)
            w["belief"] = [round(b[0], 3), round(b[1], 3)]
            tr = self.truth[i]
            if tr:
                w["truth"] = [round(tr[0], 3), round(tr[1], 3)]
        return w


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _record(det: "Detector", anomaly: str, module: str, severity: str, t: float, t_end: float, summary: str, values: dict,
            margin=None, where=None, evidence=None, related=None) -> dict:
    return {"anomaly": anomaly, "source": "analysis", "module": module, "severity": severity, "detector": det.id,
            "version": det.version, "t": round(t, 3), "t_end": round(t_end, 3), "where": where or {}, "summary": summary,
            "values": values, "margin": None if margin is None else round(margin, 4), "evidence": evidence or {},
            "related": related or []}


def _episodes(flags: list, times: list, gap_s: float) -> list:
    """(first index, last index) runs of true flags; two runs closer than gap_s are one."""
    out = []
    for i, on in enumerate(flags):
        if not on:
            continue
        if out and times[i] - times[out[-1][1]] <= gap_s:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


# ---- the detectors ---------------------------------------------------------------------------------------------------

def near_miss(det, run: Run, truth, cfg: dict) -> list:
    """Truth clearance (the trunk centre's distance to the nearest obstacle's footprint) under near_miss_m. The duck's radius
    is the contact line: an episode that goes under it has a contact, which is the judge's outcome and is linked, not
    reported again."""
    thr, radius = cfg["near_miss_m"], run.radius
    clear = []
    for i, tr in enumerate(run.truth):
        clear.append(truth.clearance(tr[0], tr[1]) if tr else (math.inf, None))
    out = []
    for a, b in _episodes([c[0] < thr for c in clear], run.t, 1.0):
        i = min(range(a, b + 1), key=lambda k: clear[k][0])
        c, name = clear[i]
        contact = next((k for k in range(a, b + 1) if clear[k][0] < radius), None)
        related = [f"contact@{run.t[contact]:.1f}"] if contact is not None else []
        out.append(_record(det, "near_miss", "navigator", "critical" if contact is not None else "minor", run.t[a], run.t[b],
                           f"{c:.3f} m from {name}" + (", then touched it" if contact is not None else ", without touching it"),
                           {"clearance_m": round(c, 4), "obstacle": name, "contact": contact is not None, "radius_m": radius},
                           thr - c, run.where(i), {"t": [run.t[a], run.t[b]]}, related))
    return out


def dithering(det, run: Run, truth, cfg: dict) -> list:
    """Walking (the commanded forward speed at or over walking_vx the whole window) with a net belief displacement under
    dither_net_m in dither_window_s. Pivots are not walking."""
    n, win, net, vx = len(run.t), cfg["dither_window_s"], cfg["dither_net_m"], cfg["walking_vx"]
    still = [0]
    for c in run.cmd:
        still.append(still[-1] + (0 if c and c[0] >= vx else 1))
    flags, nets = [False] * n, [None] * n
    j = 0
    for i in range(n):
        while j < n - 1 and run.t[j] - run.t[i] < win:
            j += 1
        if run.t[j] - run.t[i] < win or still[j + 1] - still[i]:
            continue
        d = math.dist(run.belief[i][:2], run.belief[j][:2])
        nets[i] = d
        flags[i] = d < net
    out = []
    for a, b in _episodes(flags, run.t, 0.5):
        i = min((k for k in range(a, b + 1) if nets[k] is not None), key=lambda k: nets[k])
        end = min(n - 1, bisect.bisect_left(run.t, run.t[b] + win))
        out.append(_record(det, "dithering", "navigator", "minor", run.t[a], run.t[end],
                           f"walking, and moved {nets[i]:.2f} m in {win:.0f} s", {"net_m": round(nets[i], 3), "window_s": win},
                           net - nets[i], run.where(i), {"t": [run.t[a], run.t[end]]}))
    return out


def odometry_scale(det, run: Run, truth, cfg: dict) -> list:
    """While walking, the belief's path length over the truth's, over the run and per leg. A belief step longer than
    odom_jump_m in one tick is a fix, not odometry, and is left out with the truth step beside it."""
    n, vx, jump = len(run.t), cfg["walking_vx"], cfg["odom_jump_m"]
    steps = []                                                    # (t, belief step, truth step)
    for i in range(n - 1):
        if not run.truth[i] or not run.truth[i + 1] or not (run.cmd[i] and run.cmd[i][0] >= vx) or run.t[i + 1] - run.t[i] > 0.5:
            continue
        b = math.dist(run.belief[i][:2], run.belief[i + 1][:2])
        if b > jump:
            continue
        steps.append((run.t[i + 1], b, math.dist(run.truth[i][:2], run.truth[i + 1][:2])))
    walked = sum(s[2] for s in steps)
    if walked < cfg["odom_min_walk_m"]:
        return []
    ratio = sum(s[1] for s in steps) / walked
    ends = [e["t"] for e in run.events if e["kind"] == "leg"] or [s["t_end"] for s in run.segments]
    legs, lo = [], run.t[0] if run.t else 0.0
    for hi in ends + ([run.t[-1]] if ends and run.t and ends[-1] < run.t[-1] else []):
        part = [s for s in steps if lo < s[0] <= hi]
        d = sum(s[2] for s in part)
        if d >= cfg["odom_leg_min_m"]:
            legs.append(sum(s[1] for s in part) / d)
        lo = hi
    low, high = cfg["odom_low"], cfg["odom_high"]
    out_legs = sum(1 for r in legs if not low <= r <= high)
    run_out = not low <= ratio <= high
    if not run_out and not (cfg["odom_legs_out"] and out_legs >= cfg["odom_legs_out"]):
        return []
    margin = (low - ratio if ratio < low else ratio - high) if run_out else None
    return [_record(det, "odometry_scale", "odometry", "major" if run_out else "minor", run.t[0], run.t[-1],
                    f"the belief walked {ratio:.3f} of the truth over {walked:.1f} m ({out_legs} of {len(legs)} legs outside {low}-{high})",
                    {"ratio": round(ratio, 4), "walked_m": round(walked, 2), "legs": len(legs), "legs_out": out_legs,
                     "leg_ratios": [round(r, 3) for r in legs]}, margin, {"frame": "world"})]


def belief_vs_truth(det, run: Run, truth, cfg: dict) -> list:
    """The 95th percentile over the run of the belief's distance from the truth (warn belief_warn_m, major belief_major_m)
    and of its heading error (heading_deg)."""
    idx = [i for i, tr in enumerate(run.truth) if tr]
    if len(idx) < 20:
        return []
    errs, yaws = [], []
    for i in idx:
        b = run.belief_world(i)
        tr = run.truth[i]
        errs.append(math.dist(b[:2], tr[:2]))
        yaws.append(abs(math.degrees(_wrap(b[2] - tr[2]))))

    def p95(v):
        return statistics.quantiles(v, n=20, method="inclusive")[-1]
    out = []
    p, py = p95(errs), p95(yaws)
    worst = max(range(len(idx)), key=lambda k: errs[k])
    if p > cfg["belief_warn_m"]:
        a = b = worst
        while a > 0 and errs[a - 1] > cfg["belief_warn_m"]:
            a -= 1
        while b < len(idx) - 1 and errs[b + 1] > cfg["belief_warn_m"]:
            b += 1
        out.append(_record(det, "belief_off_truth", "localizer", "major" if p > cfg["belief_major_m"] else "minor",
                           run.t[idx[a]], run.t[idx[b]], f"the belief was {p:.2f} m from the truth at the 95th percentile (worst {errs[worst]:.2f} m)",
                           {"p95_m": round(p, 4), "max_m": round(errs[worst], 4), "median_m": round(statistics.median(errs), 4)},
                           p - cfg["belief_warn_m"], run.where(idx[worst]), {"t": [run.t[idx[a]], run.t[idx[b]]]}))
    if py > cfg["heading_deg"]:
        k = max(range(len(idx)), key=lambda k: yaws[k])
        out.append(_record(det, "heading_off_truth", "localizer", "minor", run.t[idx[k]], run.t[idx[k]],
                           f"the belief's heading was {py:.0f} degrees from the truth at the 95th percentile (worst {yaws[k]:.0f})",
                           {"p95_deg": round(py, 2), "max_deg": round(yaws[k], 2)}, py - cfg["heading_deg"], run.where(idx[k])))
    return out


_WALL = re.compile("#")


def _wall_cells(world: dict) -> list:
    g = world["grid"]
    return [(m.start() % g["w"], m.start() // g["w"]) for m in _WALL.finditer(g["cells"])]


def _clusters(cells: list) -> list:
    todo, out = set(cells), []
    while todo:
        seed = todo.pop()
        comp, q = [seed], deque([seed])
        while q:
            cx, cy = q.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (cx + dx, cy + dy)
                    if nb in todo:
                        todo.discard(nb)
                        comp.append(nb)
                        q.append(nb)
        out.append(comp)
    return out


def phantom_obstacle(det, run: Run, truth, cfg: dict) -> list:
    """An occupied cluster of phantom_cells or more of the map's cells, every cell over phantom_far_m from any real outline
    (the layout's solid geoms, stairs included). Followed across the run's map snapshots: one record per place."""
    tracks = []                                      # {"c": (x, y), "t0", "t1", "cells", "far", "n"}
    prev, matched = None, []
    for w in run.worlds:
        g = w["grid"]
        if g["cells"] == prev:                       # the same map again (the memory moved, the grid did not): the same clusters
            for tr in matched:
                tr.update(t1=w["t"], n=tr["n"] + 1)
            continue
        prev, matched = g["cells"], []
        res, (ox, oy) = g["res"], g["origin"]
        for comp in _clusters(_wall_cells(w)):
            if len(comp) < cfg["phantom_cells"]:
                continue
            pts = [run.to_world(w["t"], ox + (cx + .5) * res, oy + (cy + .5) * res) for cx, cy in comp]
            far = min(truth.outline_distance(x, y) for x, y in pts)
            if far <= cfg["phantom_far_m"]:
                continue
            c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            tr = next((t for t in tracks if math.dist(t["c"], c) < 0.25), None)
            if tr is None:
                tr = {"c": c, "t0": w["t"], "t1": w["t"], "cells": len(comp), "far": far, "n": 1}
                tracks.append(tr)
            else:
                tr.update(t1=w["t"], cells=max(tr["cells"], len(comp)), far=min(tr["far"], far), n=tr["n"] + 1)
            matched.append(tr)
    return [_record(det, "phantom_obstacle", "mapd", "minor", t["t0"], t["t1"],
                    f"{t['cells']} occupied cells at ({t['c'][0]:.2f}, {t['c'][1]:.2f}), {t['far']:.2f} m from any real outline",
                    {"cells": t["cells"], "nearest_outline_m": round(t["far"], 3), "snapshots": t["n"]}, t["far"] - cfg["phantom_far_m"],
                    {"belief": [round(t["c"][0], 3), round(t["c"][1], 3)], "frame": "world"}) for t in tracks]


def missed_obstacle(det, run: Run, truth, cfg: dict) -> list:
    """In the run's last map: an obstacle with missed_samples or more outline samples in cells the map knows and no occupied
    cell within missed_near_m of any of them."""
    if not run.worlds:
        return []
    w = run.worlds[-1]
    g = w["grid"]
    res, (ox, oy), W, H, cells = g["res"], g["origin"], g["w"], g["h"], g["cells"]
    occ = set(_wall_cells(w))
    reach = math.ceil(cfg["missed_near_m"] / res)
    out = []
    for geom in truth.obstacles:
        missing = []
        for px, py in perimeter(geom, cfg["missed_step_m"]):
            mx, my = run.to_map(w["t"], px, py)
            cx, cy = math.floor((mx - ox) / res), math.floor((my - oy) / res)
            if not (0 <= cx < W and 0 <= cy < H) or cells[cy * W + cx] == "?":
                continue
            if not any(math.hypot((ox + (x + .5) * res) - mx, (oy + (y + .5) * res) - my) <= cfg["missed_near_m"]
                       for x in range(cx - reach, cx + reach + 1) for y in range(cy - reach, cy + reach + 1) if (x, y) in occ):
                missing.append((px, py))
        if len(missing) >= cfg["missed_samples"]:
            out.append(_record(det, "missed_obstacle", "mapd", "minor", w["t"], w["t"],
                               f"{geom['name']}: {len(missing)} outline samples in known cells with no occupied cell within {cfg['missed_near_m']} m",
                               {"obstacle": geom["name"], "samples_missing": len(missing)}, len(missing) - cfg["missed_samples"],
                               {"truth": [round(geom["pos"][0], 3), round(geom["pos"][1], 3)], "frame": "world"}))
    return out


def misplaced_edge(det, run: Run, truth, cfg: dict) -> list:
    """A glance that saw an edge whose rim points (the navigator's, mapped to the world) have a median over edge_off_m from
    the stairwell, followed within edge_within_s by a refusal or a trap."""
    out = []
    for e in run.events:
        rim = e.get("rim_points") if e["kind"] == "glance" else None
        if not rim:
            continue
        pts = [run.to_world(e["t"], p[0], p[1]) for p in rim]
        dists = [truth.hole_distance(x, y) for x, y in pts]
        med = statistics.median(dists)
        after = [x for x in run.events if x["kind"] in ("refused", "trapped") and e["t"] <= x["t"] <= e["t"] + cfg["edge_within_s"]]
        if med > cfg["edge_off_m"] and after:
            mid = sorted(pts, key=lambda p: truth.hole_distance(*p))[len(pts) // 2]
            out.append(_record(det, "misplaced_edge", "drops", "major", e["t"], after[-1]["t"],
                               f"the rim was placed {med:.2f} m from the stairwell (worst {max(dists):.2f} m); {after[0]['kind']} {after[0]['t'] - e['t']:.1f} s later",
                               {"median_m": round(med, 3), "max_m": round(max(dists), 3), "rim_points": len(pts)}, med - cfg["edge_off_m"],
                               {"belief": [round(mid[0], 3), round(mid[1], 3)], "frame": "world"}, {"events": [f"glance@{e['t']:.1f}"]},
                               [f"{after[0]['kind']}@{after[0]['t']:.1f}"]))
    return out


def wrong_refusal(det, run: Run, truth, cfg: dict) -> list:
    """A leg refused where a path existed by truth: the truth pose and the goal in one component of the floor the duck's centre
    can occupy (inside a floor, a radius from every obstacle and from the stairwell)."""
    at = truth.components(cfg["raster_m"], run.radius)
    out = []
    for e in run.events:
        if e["kind"] != "leg" or e.get("status") != "refused" or not e.get("target") or not e.get("truth"):
            continue
        gx, gy = run.to_world(e["t"], e["target"][0], e["target"][1])
        a, b = at(e["truth"][0], e["truth"][1]), at(gx, gy)
        if a is not None and a == b:
            out.append(_record(det, "wrong_refusal", "planner", "minor", e["t"], e["t"],
                               f"refused ({e.get('why')}) a goal that a path reached by truth",
                               {"why": e.get("why"), "goal": [round(gx, 3), round(gy, 3)]}, None,
                               {"truth": [round(e["truth"][0], 3), round(e["truth"][1], 3)], "frame": "world"}))
    return out


def area_uncovered(det, run: Run, truth, cfg: dict) -> list:
    """At "nothing left to explore": a room of the layout whose floor the last map covers under cover_min (the share of its
    floor, on a cover_step_m lattice, in cells the map knows)."""
    ends = [e for e in run.events if e["kind"] == "no_frontier_left"]
    if not ends or not run.worlds:
        return []
    w = run.worlds[-1]
    g = w["grid"]
    res, (ox, oy), W, H, cells = g["res"], g["origin"], g["w"], g["h"], g["cells"]
    out = []
    for name, room in sorted(truth.rooms.items()):
        hx, hy, step = room["size"][0], room["size"][1], cfg["cover_step_m"]
        pts = [(room["pos"][0] - hx + (i + .5) * step, room["pos"][1] - hy + (j + .5) * step)
               for i in range(int(2 * hx / step)) for j in range(int(2 * hy / step))]
        known = 0
        for px, py in pts:
            mx, my = run.to_map(w["t"], px, py)
            cx, cy = math.floor((mx - ox) / res), math.floor((my - oy) / res)
            known += 0 <= cx < W and 0 <= cy < H and cells[cy * W + cx] != "?"
        share = known / len(pts) if pts else 1.0
        if share < cfg["cover_min"]:
            out.append(_record(det, "area_uncovered", "explorer", "major", ends[0]["t"], ends[0]["t"],
                               f"said nothing was left to explore with the {name} {share:.0%} covered",
                               {"room": name, "covered": round(share, 3)}, cfg["cover_min"] - share,
                               {"truth": [round(room["pos"][0], 3), round(room["pos"][1], 3)], "frame": "world"}))
    return out


class Detector:
    def __init__(self, id: str, version: int, fn, rule: str, needs: tuple, default: bool, note: str = ""):
        self.id, self.version, self.fn, self.rule, self.needs, self.default, self.note = id, version, fn, rule, needs, default, note

    def applies(self, run: Run, truth) -> str | None:
        """None when it can run on this run with this truth; otherwise why not. `needs`: "truth" (the simulator's pose in the
        run), "layout" (the simulator's layout, passed in), "worlds" (the map snapshots)."""
        if "truth" in self.needs and not run.has_truth:
            return "the run has no truth pose (a real robot's, or a recording without the simulator's)"
        if "layout" in self.needs and truth is None:
            return "needs the simulator's layout (--layout)"
        if "worlds" in self.needs and not run.worlds:
            return "the run has no map snapshots"
        return None


# `default`: quiet on the clean runs (PHASE3-PREP B2); `quiet`: what was measured, for the documentation and the footer
DETECTORS = {d.id: d for d in (
    Detector("near_miss", 1, near_miss, "truth clearance under 0.090 m (the contact line is the robot's radius)", ("truth", "layout"), True),
    Detector("dithering", 1, dithering, "walking with a net belief displacement under 0.12 m in 3 s", (), True),
    Detector("odometry_scale", 1, odometry_scale, "walking belief/truth path ratio outside 0.95-1.05 over the run", ("truth",), True),
    Detector("phantom_obstacle", 1, phantom_obstacle, "an occupied cluster of 3+ map cells, all over 0.30 m from any real outline", ("layout", "worlds"), True),
    Detector("misplaced_edge", 1, misplaced_edge, "a glance's rim median over 0.25 m from the stairwell, a refusal or trap within 5 s", ("layout",), True),
    Detector("belief_vs_truth", 1, belief_vs_truth, "p95 of belief-truth distance over 0.20 m (major over 0.35 m), of heading error over 20 degrees",
             ("truth",), False, "not quiet at 0.20 m: b9 r2 p95 0.28 m"),
    Detector("missed_obstacle", 1, missed_obstacle, "3+ outline samples in known cells with no occupied cell within 0.15 m", ("layout", "worlds"), False,
             "not quiet: fires on the clean runs (walls, table and stool legs)"),
    Detector("wrong_refusal", 1, wrong_refusal, "a refused leg whose goal a path reached by truth", ("truth", "layout"), False,
             "not quiet: fires on the clean runs (the planner's margins are wider than truth's)"),
    Detector("area_uncovered", 1, area_uncovered, "'nothing left to explore' with a room of the layout under 50 % covered", ("layout", "worlds"), False,
             "fires on b11 r1, a clean run: a true positive (kitchen, bedroom)"),
)}


def analyse(run: Run, truth, detectors=None, min_severity: str = "info", cfg: dict | None = None, experimental: bool = False) -> dict:
    """Run the detectors asked for (default: the default track, plus the experimental ones when asked) over one run.
    {"anomalies": [...sorted by time...], "ran": [ids], "not_applied": {id: why}, "not_run": {id: why it was not run}}."""
    cfg = {**DEFAULTS, **(cfg or {})}
    asked = list(detectors) if detectors else [d.id for d in DETECTORS.values() if d.default or experimental]
    unknown = [d for d in asked if d not in DETECTORS]
    if unknown:
        raise ValueError(f"no detector {unknown[0]!r}; the detectors are " + ", ".join(DETECTORS))
    if min_severity not in SEVERITIES:
        raise ValueError(f"severity {min_severity!r}: one of " + ", ".join(SEVERITIES))
    floor = SEVERITIES.index(min_severity)
    found, ran, skipped = [], [], {}
    for id_ in asked:
        det = DETECTORS[id_]
        why = det.applies(run, truth)
        if why:
            skipped[id_] = why
            continue
        ran.append(id_)
        found += [a for a in det.fn(det, run, truth, cfg) if SEVERITIES.index(a["severity"]) >= floor]
    found.sort(key=lambda a: (a["t"], a["detector"]))
    return {"anomalies": found, "ran": ran, "not_applied": skipped,
            "not_run": {d.id: ("not selected (--detector named others)" if detectors and d.default else "not selected" if d.default
                               else "experimental: not quiet on the clean runs; --experimental or --detector NAME runs them")
                        for d in DETECTORS.values() if d.id not in asked}}
