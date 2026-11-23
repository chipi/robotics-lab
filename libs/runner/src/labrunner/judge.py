"""Judged by the simulator's truth (ADR-0015): invariants on every truth sample, then whether the outcome was the right one.

The footprint geometry and thresholds are the phase 1 evaluation's (labrunner.geometry), so a challenge and the
apartment are scored the same way.
"""

import math

from labrunner.scene import Scene, layout
from labrunner import geometry
from labrunner.geometry import footprint_distance, obstacles


class Judge:
    def __init__(self, scene: Scene, profile=None):
        """`profile`: the robot's profile it judges by (its footprint, fall height, margins, reach), else labrunner.geometry's."""
        p = profile if profile is not None else geometry.profile()
        self.footprint, self.fallen_z, self.reached = p.footprint.radius_m, p.judge.fall_z_m, p.judge.reached_m
        self.drop_margin = p.judge.drop_margin_m      # the trunk centre's nearest distance to a drop's outline (ADR-0015, the operator's)
        self.bounds_margin = p.judge.bounds_margin_m
        self.scene = scene
        lay = layout(scene)
        self.obs = obstacles(lay, overhead_clear_m=p.footprint.overhead_clear_m)
        self.drops = [g for g in lay["geoms"] if g["name"].startswith("floor_") and not g["name"].startswith("floor_step")
                      and g["pos"][2] + g["size"][2] < -1e-6]
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
        z -= self.scene.floor_top(p)      # above the floor it is on (a flight down, a step up)
        self.lowest = min(self.lowest, z)
        x0, x1, y0, y1 = self.bounds
        m = self.bounds_margin
        if z < self.fallen_z:
            why = ("fall", f"trunk {z:.3f} m above its floor, below {self.fallen_z} m")
        elif drop < self.drop_margin:
            why = ("drop_margin", f"{drop:.3f} m from a drop's edge, under {self.drop_margin} m")
        elif self.obs and near[0] < self.footprint:
            why = ("contact", f"{near[0]:.3f} m from {near[1]}, under the footprint {self.footprint} m")
        elif not (x0 - m < p[0] < x1 + m and y0 - m < p[1] < y1 + m):
            why = ("bounds", f"at ({p[0]:.2f}, {p[1]:.2f}), outside the scene")
        else:
            return None
        if self.broken:
            return None
        self.broken = {"t": round(t, 3), "rule": why[0], "why": why[1]}
        return self.broken

    def verdict(self, out: dict, truth_end: tuple) -> dict:
        """PASS when no invariant broke and the outcome is the right one: `reach` — the navigator said reached and truth is
        within the profile's `judge.reached_m` of the goal; `refuse` — it refused, with its reason (a stall or a timeout is not a refusal)."""
        err = math.dist(truth_end[:2], self.scene.goal)
        if self.scene.right == "reach":
            right = out.get("status") == "reached" and err <= self.reached
            wrong = None if right else (f"{out.get('status')}: {out.get('why', '')}".strip(": ") if out.get("status") != "reached"
                                        else f"said reached {err:.2f} m from the goal (over {self.reached} m)")
        else:   # only a refusal is right: a stall stops safely, but it gave up rather than said why not (the operator, 2026-11-16)
            right = out.get("status") == "refused" and bool(out.get("why"))
            wrong = None if right else f"{out.get('status')} where refusing was right" + (f" ({out['why']})" if out.get("why") else "")
        failed = self.broken_failures() + ([wrong] if wrong else [])
        return {"pass": not failed, "failed": failed, "status": out.get("status"), "why": out.get("why"),
                "error_m": round(err, 3), **self.stats()}

    def broken_failures(self) -> list:
        return [f"{self.broken['rule']} at {self.broken['t']} s: {self.broken['why']}"] if self.broken else []

    def stats(self) -> dict:
        """What the truth samples said, whatever the challenge's outcome."""
        return {"min_clearance_m": round(self.min_clearance[0], 3), "nearest": self.min_clearance[1],
                "min_drop_m": None if self.min_drop == math.inf else round(self.min_drop, 3),
                "lowest_trunk_m": round(self.lowest, 3), "truth_samples": self.samples}
