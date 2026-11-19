"""Landmark relocalisation (RFC-0016 §4, RFC-0014 §3.5.4 as far as the simulator goes): a landmark seen again corrects the
duck's belief.

A landmark is an object of a kind with landmark value >= 0.7 that stays put (SemanticMap.is_landmark). Its anchor
(SemanticMap.anchors) is where it was kept: a site's map at the start of a run (SemanticMap.anchor_landmarks), or, in a
run without one, the mean of ANCHOR_N close sightings (ANCHOR_RANGE_M) that agree — a confirmed object's own position
follows the belief, so it is no anchor. When a sighting places a landmark, the placement is compared with its anchor: the
difference is the belief's error at that moment. One sighting is noisy (range 5 %, bearing 2 degrees in the simulated
camera), so the residuals of the last WINDOW_S seconds are collected, and only when MIN_N of them agree (SPREAD_M) is the
median taken as a correction, by GAIN of it and at most MAX_STEP_M a time (the Localizer's offset caps the total).
Corrections and refusals are the caller's to record, each with the numbers.

What it corrects is the belief's position, not its heading, and not mapd's grid: that stays where mapd built it.
"""

import math
from dataclasses import dataclass, field

from worldmodel.semantic_map import SemanticMap

MATCH_M = 1.0              # a sighting is of an anchor this close to where the belief places it; farther, no match
RANGE_M = 1.2              # only sightings from this near count: the placement's error grows with the range
ANCHOR_RANGE_M = 1.2       # ... and one that makes an anchor, nearer still
ANCHOR_N = 4               # close sightings, agreeing within ANCHOR_SPREAD_M, that make an anchor in a run
ANCHOR_SPREAD_M = 0.12
WINDOW_S = 6.0
MIN_N = 4                  # residuals that must agree before a correction
SPREAD_M = 0.12            # ... each within this of their median
DEADBAND_M = 0.15          # a median this small is noise
GAIN = 0.7
MAX_STEP_M = 0.3


@dataclass
class Relocaliser:
    semantic: SemanticMap
    window: list = field(default_factory=list)      # (t, oid, rx, ry): anchor minus where the belief placed it
    pending: dict = field(default_factory=dict)     # oid -> placements of close sightings, for an anchor in the making

    def _anchor_for(self, d, p) -> tuple | None:
        """(oid, anchor) of the one anchored landmark of d's kind within MATCH_M of the placement, else None."""
        sm = self.semantic
        near = [(oid, a) for oid, a in sm.anchors.items()
                if any(o.oid == oid and o.kind == d.kind and not o.gone for o in sm.objects)
                and math.dist(a, (p.x, p.y)) <= MATCH_M]
        return near[0] if len(near) == 1 else None

    def _collect(self, d, p) -> None:
        """A close sighting of a landmark with no anchor yet: its placement counts toward one."""
        sm = self.semantic
        if d.range_m > ANCHOR_RANGE_M:
            return
        near = [o for o in sm.confirmed() if o.kind == d.kind and o.oid not in sm.anchors
                and math.dist((o.x, o.y), (p.x, p.y)) <= MATCH_M]
        if len(near) != 1:
            return
        pts = self.pending.setdefault(near[0].oid, [])
        pts.append((p.x, p.y))
        del pts[:-ANCHOR_N]
        if len(pts) < ANCHOR_N:
            return
        mx, my = sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts)
        if max(math.dist(q, (mx, my)) for q in pts) <= ANCHOR_SPREAD_M:
            sm.anchors[near[0].oid] = (mx, my)
            del self.pending[near[0].oid]

    def observe(self, detections: list, pose: tuple, t: float) -> dict | None:
        """Collect the residuals of this sighting's landmarks; a decision dict when it corrects ("corrected": dx, dy) or
        refuses ("refused": why) the belief, None when there is nothing to say. Call before integrating the sighting."""
        sm = self.semantic
        for d in detections:
            if not sm.is_landmark(d.kind) or d.range_m > RANGE_M:
                continue
            p = d.part().moved(pose)
            hit = self._anchor_for(d, p)
            if hit is None:
                self._collect(d, p)
                continue
            oid, a = hit
            self.window.append((t, oid, a[0] - p.x, a[1] - p.y))
        self.window = [w for w in self.window if t - w[0] <= WINDOW_S]
        if len(self.window) < MIN_N:
            return None
        xs, ys = sorted(w[2] for w in self.window), sorted(w[3] for w in self.window)
        mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
        spread = max(math.hypot(w[2] - mx, w[3] - my) for w in self.window)
        info = {"n": len(self.window), "median": [round(mx, 3), round(my, 3)], "spread_m": round(spread, 3),
                "landmarks": sorted({w[1] for w in self.window})}
        if spread > SPREAD_M:
            self.window = self.window[-1:]
            return {"status": "refused", "why": f"residuals disagree by {spread:.2f} m (limit {SPREAD_M})", **info}
        self.window = []
        if math.hypot(mx, my) < DEADBAND_M:
            return None
        dx, dy = mx * GAIN, my * GAIN
        n = math.hypot(dx, dy)
        if n > MAX_STEP_M:
            dx, dy = dx * MAX_STEP_M / n, dy * MAX_STEP_M / n
        return {"status": "corrected", "dx": round(dx, 3), "dy": round(dy, 3), **info}
