"""Judged by the simulator's truth (ADR-0015): invariants on every truth sample, then whether the outcome was the right one.

The footprint geometry and thresholds are the phase 1 evaluation's (duck_lab.nav.evaluate), so a challenge and the
apartment are scored the same way.
"""

import math

from duck_lab.challenge.scene import Scene, layout
from duck_lab.nav.evaluate import FALLEN_Z_M, FOOTPRINT_M, REACHED_M, footprint_distance, obstacles

DROP_MARGIN_M = 0.15      # the trunk centre's nearest distance to a drop's outline (ADR-0015, the operator's)
BOUNDS_MARGIN_M = 0.05


class Judge:
    def __init__(self, scene: Scene):
        self.scene = scene
        lay = layout(scene)
        self.obs = obstacles(lay)
        self.drops = [g for g in lay["geoms"] if g["name"].startswith("floor_") and g["pos"][2] + g["size"][2] < -1e-6]
        self.bounds = scene.bounds()
        self.broken = None        # the first invariant broken: {"t", "rule", "why"}
        self.samples = 0
        self.min_clearance = (math.inf, None)
        self.min_drop = math.inf
        self.lowest = math.inf

    def check(self, t: float, truth: tuple, z: float) -> dict | None:
        """One truth sample; the first invariant it breaks (and only the run's first), else None."""
        self.samples += 1
        p = truth[:2]
        if self.obs:
            near = min((footprint_distance(p, g), g["name"]) for g in self.obs)
            self.min_clearance = min(self.min_clearance, near)
        drop = min((footprint_distance(p, g) for g in self.drops), default=math.inf)
        self.min_drop = min(self.min_drop, drop)
        self.lowest = min(self.lowest, z)
        x0, x1, y0, y1 = self.bounds
        if z < FALLEN_Z_M:
            why = ("fall", f"trunk at {z:.3f} m, below {FALLEN_Z_M} m")
        elif drop < DROP_MARGIN_M:
            why = ("drop_margin", f"{drop:.3f} m from a drop's edge, under {DROP_MARGIN_M} m")
        elif self.obs and near[0] < FOOTPRINT_M:
            why = ("contact", f"{near[0]:.3f} m from {near[1]}, under the footprint {FOOTPRINT_M} m")
        elif not (x0 - BOUNDS_MARGIN_M < p[0] < x1 + BOUNDS_MARGIN_M and y0 - BOUNDS_MARGIN_M < p[1] < y1 + BOUNDS_MARGIN_M):
            why = ("bounds", f"at ({p[0]:.2f}, {p[1]:.2f}), outside the scene")
        else:
            return None
        if self.broken:
            return None
        self.broken = {"t": round(t, 3), "rule": why[0], "why": why[1]}
        return self.broken

    def verdict(self, out: dict, truth_end: tuple) -> dict:
        """PASS when no invariant broke and the outcome is the right one: `reach` — the navigator said reached and truth is
        within REACHED_M of the goal; `refuse` — it refused, with its reason (a stall or a timeout is not a refusal)."""
        err = math.dist(truth_end[:2], self.scene.goal)
        if self.scene.right == "reach":
            right = out.get("status") == "reached" and err <= REACHED_M
            wrong = None if right else (f"{out.get('status')}: {out.get('why', '')}".strip(": ") if out.get("status") != "reached"
                                        else f"said reached {err:.2f} m from the goal (over {REACHED_M} m)")
        else:   # only a refusal is right: a stall stops safely, but it gave up rather than said why not (the operator, 2026-11-16)
            right = out.get("status") == "refused" and bool(out.get("why"))
            wrong = None if right else f"{out.get('status')} where refusing was right" + (f" ({out['why']})" if out.get("why") else "")
        failed = [f"{self.broken['rule']} at {self.broken['t']} s: {self.broken['why']}"] if self.broken else []
        failed += [wrong] if wrong else []
        return {"pass": not failed, "failed": failed, "status": out.get("status"), "why": out.get("why"),
                "error_m": round(err, 3), "min_clearance_m": round(self.min_clearance[0], 3), "nearest": self.min_clearance[1],
                "min_drop_m": None if self.min_drop == math.inf else round(self.min_drop, 3),
                "lowest_trunk_m": round(self.lowest, 3), "truth_samples": self.samples}
