"""Landmark relocalisation (RFC-0016 §4, RFC-0014 §3.5.4 as far as the simulator goes): a landmark seen again corrects the
duck's belief.

A landmark is an object of a kind with landmark value >= 0.7 that stays put (SemanticMap.is_landmark). Its anchor
(SemanticMap.anchors) is where it was kept: a site's map at the start of a run (SemanticMap.anchor_landmarks), or, in a
run without one, the mean of anchor_n close sightings (anchor_range_m) that agree — a confirmed object's own position
follows the belief, so it is no anchor. When a sighting places a landmark, the placement is compared with its anchor: the
difference is the belief's error at that moment. One sighting is noisy (range 5 %, bearing 2 degrees in the simulated
camera), so the residuals of the last window_s seconds are collected, and only when min_n of them agree (spread_m) is the
median taken as a correction, by gain of it and at most max_step_m a time (the Localizer's offset caps the total).
Corrections and refusals are the caller's to record, each with the numbers.

What it corrects is the belief's position, not its heading, and not mapd's grid: that stays where mapd built it.

The numbers are the robot's, the profile's `localisation.landmarks` block (any object with these attributes), passed as `numbers`;
DUCK_LANDMARKS is the duck's, the default for the callers that predate profiles (K32: it goes when a second robot uses this):
  match_m        a sighting is of an anchor this close to where the belief places it; farther, no match
  range_m        only sightings from this near count: the placement's error grows with the range
  anchor_range_m ... and one that makes an anchor, nearer still
  anchor_n       close sightings, agreeing within anchor_spread_m, that make an anchor in a run
  window_s, min_n  residuals that must agree before a correction, each within spread_m of their median
  deadband_m     a median this small is noise
  gain, max_step_m
"""

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

from worldmodel.semantic_map import SemanticMap

DUCK_LANDMARKS = SimpleNamespace(match_m=1.0, range_m=1.2, anchor_range_m=1.2, anchor_n=4, anchor_spread_m=0.12, window_s=6.0,
                                 min_n=4, spread_m=0.12, deadband_m=0.15, gain=0.7, max_step_m=0.3)


@dataclass
class Relocaliser:
    semantic: SemanticMap
    window: list = field(default_factory=list)      # (t, oid, rx, ry): anchor minus where the belief placed it
    pending: dict = field(default_factory=dict)     # oid -> placements of close sightings, for an anchor in the making
    numbers: object = field(default_factory=lambda: DUCK_LANDMARKS)

    def _anchor_for(self, d, p) -> tuple | None:
        """(oid, anchor) of the one anchored landmark of d's kind within match_m of the placement, else None."""
        sm = self.semantic
        near = [(oid, a) for oid, a in sm.anchors.items()
                if any(o.oid == oid and o.kind == d.kind and not o.gone for o in sm.objects)
                and math.dist(a, (p.x, p.y)) <= self.numbers.match_m]
        return near[0] if len(near) == 1 else None

    def _collect(self, d, p) -> None:
        """A close sighting of a landmark with no anchor yet: its placement counts toward one."""
        sm, k = self.semantic, self.numbers
        if d.range_m > k.anchor_range_m:
            return
        near = [o for o in sm.confirmed() if o.kind == d.kind and o.oid not in sm.anchors
                and math.dist((o.x, o.y), (p.x, p.y)) <= k.match_m]
        if len(near) != 1:
            return
        pts = self.pending.setdefault(near[0].oid, [])
        pts.append((p.x, p.y))
        del pts[:-k.anchor_n]
        if len(pts) < k.anchor_n:
            return
        mx, my = sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts)
        if max(math.dist(q, (mx, my)) for q in pts) <= k.anchor_spread_m:
            sm.anchors[near[0].oid] = (mx, my)
            del self.pending[near[0].oid]

    def observe(self, detections: list, pose: tuple, t: float) -> dict | None:
        """Collect the residuals of this sighting's landmarks; a decision dict when it corrects ("corrected": dx, dy) or
        refuses ("refused": why) the belief, None when there is nothing to say. Call before integrating the sighting."""
        sm, k = self.semantic, self.numbers
        for d in detections:
            if not sm.is_landmark(d.kind) or d.range_m > k.range_m:
                continue
            p = d.part().moved(pose)
            hit = self._anchor_for(d, p)
            if hit is None:
                self._collect(d, p)
                continue
            oid, a = hit
            self.window.append((t, oid, a[0] - p.x, a[1] - p.y))
        self.window = [w for w in self.window if t - w[0] <= k.window_s]
        if len(self.window) < k.min_n:
            return None
        xs, ys = sorted(w[2] for w in self.window), sorted(w[3] for w in self.window)
        mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
        spread = max(math.hypot(w[2] - mx, w[3] - my) for w in self.window)
        info = {"n": len(self.window), "median": [round(mx, 3), round(my, 3)], "spread_m": round(spread, 3),
                "landmarks": sorted({w[1] for w in self.window})}
        if spread > k.spread_m:
            self.window = self.window[-1:]
            return {"status": "refused", "why": f"residuals disagree by {spread:.2f} m (limit {k.spread_m})", **info}
        self.window = []
        if math.hypot(mx, my) < k.deadband_m:
            return None
        dx, dy = mx * k.gain, my * k.gain
        n = math.hypot(dx, dy)
        if n > k.max_step_m:
            dx, dy = dx * k.max_step_m / n, dy * k.max_step_m / n
        return {"status": "corrected", "dx": round(dx, 3), "dy": round(dy, 3), **info}

    def probe(self, detections: list, pose: tuple, t: float, window: list) -> list:
        """Would these sightings sit on their anchors if the duck were at `pose`? `window` (the caller's, not the relocaliser's)
        and the residuals of this sighting's anchored landmarks, the last window_s seconds of them. A pose that is only a
        hypothesis (a held loop closure's frame, K26) changes nothing here: no anchor is made, the relocaliser's own window stays."""
        sm, k = self.semantic, self.numbers
        out = list(window)
        for d in detections:
            if not sm.is_landmark(d.kind) or d.range_m > k.range_m:
                continue
            p = d.part().moved(pose)
            hit = self._anchor_for(d, p)
            if hit is not None:
                out.append((t, hit[0], hit[1][0] - p.x, hit[1][1] - p.y))
        return [w for w in out if t - w[0] <= k.window_s]

    def agreement(self, window: list, agree_m: float) -> dict | None:
        """What a probe's window says of its hypothesis: None until min_n residuals; "refused" when they disagree with each
        other by over spread_m; else "agrees" when their median is within agree_m of the anchors (the hypothesis puts the
        landmarks where they were kept), "disagrees" when it is not."""
        k = self.numbers
        if len(window) < k.min_n:
            return None
        xs, ys = sorted(w[2] for w in window), sorted(w[3] for w in window)
        mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
        spread = max(math.hypot(w[2] - mx, w[3] - my) for w in window)
        info = {"n": len(window), "median": [round(mx, 3), round(my, 3)], "spread_m": round(spread, 3),
                "landmarks": sorted({w[1] for w in window}), "agree_m": agree_m}
        if spread > k.spread_m:
            return {"status": "refused", **info}
        return {"status": "agrees" if math.hypot(mx, my) <= agree_m else "disagrees", **info}
