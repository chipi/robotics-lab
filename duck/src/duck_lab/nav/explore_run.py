"""Explore the apartment: survey, go to the nearest frontier, repeat (RFC-0002 phase 2, "the brain
explores"). The simulator's truth is logged for scoring only; the brain never reads it.

    uv run duck-explore --minutes 20 --out runs/explore
"""

import argparse
import json
import math
import threading
import time
from pathlib import Path

from duck_lab.nav.explore import frontiers, pick
from duck_lab.nav.follow import Twist
from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, LETHAL_COST, CostGrid, EmptyMap, clearance
from duck_lab.nav.run import PIVOT_DROP_M, PIVOT_OBSTACLE_M, Navigator

SURVEY_STEPS = 4            # a full turn in 90 deg steps: the depth sensor sees a 45 deg wedge
SURVEY_STEP_RAD = math.pi / 2
KICK_RAD_S, HOLD_RAD_S, KICK_S = 1.2, 0.8, 1.0   # PHASE0-SPIKE.md: no start below ~1.1 rad/s
GO_TIMEOUT_S = 60.0
CLEAR_M = 0.5          # a boxed-in start forgets remembered obstacle points this close (as the planner's escape)
MAX_REFUSALS = 6       # refusals in a row before the run stops as trapped
# The test harness's kill switch, not the brain's: the simulator's truth aborts the run when the duck
# comes within GUARD_M of the staircase opening or its trunk drops - so a failing cliff check ends in an
# abort, not another fall. The brain never reads it.
STAIRS = (-0.40, 0.00, -1.40, -0.70)
GUARD_M = 0.05


def stairs_distance(p) -> float:
    x0, x1, y0, y1 = STAIRS
    return math.hypot(max(x0 - p[0], 0, p[0] - x1), max(y0 - p[1], 0, p[1] - y1))


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


class Explorer:
    def __init__(self, nav: Navigator, out: Path):
        self.nav = nav
        self.out = out
        self.failed = []          # frontier targets that failed: avoided from then on
        self.events = []

    def note(self, **e) -> None:
        e["t"] = round(time.monotonic() - self.nav._t0, 1)
        self.events.append(e)
        self.nav.record(**e)

    def yaw(self) -> float:
        s = self.nav.state.latest
        return s["odom"]["yaw"] if s else 0.0

    def turn(self, angle: float) -> bool:
        """Turn on the spot by about angle (odometry yaw), unless a remembered drop is too close."""
        pose = self.nav.loc.pose()
        if pose and any(math.dist(pose[:2], d) < PIVOT_DROP_M for d in self.nav.drops):
            self.note(event="no_survey_turn", why="drop within turn clearance")
            return False
        if pose:
            try:
                room = clearance(self.nav.grid().with_blocked(self.nav.blocked), pose[:2], PIVOT_OBSTACLE_M)
            except EmptyMap:
                room = PIVOT_OBSTACLE_M
            if room < PIVOT_OBSTACLE_M:
                self.note(event="no_survey_turn", why=f"obstacle {room:.2f} m away")
                return False
        start, began = self.yaw(), time.monotonic()
        while time.monotonic() - began < 8.0:
            done = wrap(self.yaw() - start)
            if abs(done) >= abs(angle) - math.radians(8):
                break
            rate = KICK_RAD_S if time.monotonic() - began < KICK_S else HOLD_RAD_S
            self.nav.move(Twist(0.0, math.copysign(rate, angle)))
            time.sleep(0.1)
        self.nav.move(Twist())
        return True

    def survey(self) -> None:
        for _ in range(SURVEY_STEPS):
            self.nav.survey()
            if not self.turn(SURVEY_STEP_RAD):
                break
        self.nav.survey()

    def run(self, minutes: float) -> dict:
        end = time.monotonic() + minutes * 60
        legs = 0
        # A full survey is 4 x 90 deg, ~30 s; a leg is ~5 s. Trial 4 surveyed after every leg and spent
        # 85% of its time turning on the spot, so the survey now runs only when no frontier is in sight.
        self.survey()
        surveyed_here, cleared_here, refusals = True, False, 0
        while time.monotonic() < end:
            if self.nav.abort:
                self.note(event="aborted", why=self.nav.abort)
                break
            grid = self.nav.mapd.call("map.grid", {"res_m": 0.05})
            pose = self.nav.loc.pose()
            try:
                # covering() as the navigator does: a drop beyond mapd's grid still grows its zone into it
                # (trial 6 picked a goal the navigator then scored lethal).
                costs = self.nav.grid()
                costs = costs.covering([pose[:2]] + self.nav.blocked + self.nav.drops).with_blocked(self.nav.blocked)
                costs = costs.with_blocked(self.nav.drops, DROP_LETHAL_M, DROP_INFLATE_M)
            except EmptyMap:
                self.survey()
                continue

            def reachable(goal, costs=costs):
                c = costs.cell(*goal)
                if costs.inside(*c) and costs.at(*c) >= LETHAL_COST:
                    return False
                # Floor the depth sensor saw, not only mapd's "free": mapd draws a stairwell as free
                # (upstream #599) and trial 10 picked a target inside one.
                return self.nav.floor_seen_near(goal)

            avoid = self.failed + self.nav.drops
            target = pick(frontiers(grid, self.nav.scale), pose, avoid, ok=reachable)
            if target is None:
                if not surveyed_here:
                    self.survey()
                    surveyed_here = True
                    continue
                self.note(event="no_frontier_left", legs=legs)
                break
            surveyed_here = False
            legs += 1
            out = self.nav.go_to(target, min(GO_TIMEOUT_S, end - time.monotonic()))
            self.note(event="leg", n=legs, target=[round(v, 2) for v in target], status=out["status"],
                      why=out.get("why"))
            if out.get("why") == "start boxed in" and not cleared_here:
                gone = self.nav.forget_blocked_near(pose, CLEAR_M)
                self.note(event="cleared", points=gone)
                cleared_here = True
                continue          # the same frontier again: the start was the problem, not the target
            if out["status"] != "reached":
                self.failed.append(target)
                refusals = refusals + 1 if out["status"] == "refused" else 0
                if refusals >= MAX_REFUSALS:
                    # Trial 4: one boxed-in start refused 37 frontiers in a second and ended the run as
                    # "no frontier left". A run of refusals says the duck is stuck, not that the map is done.
                    self.note(event="trapped", legs=legs, refusals=refusals)
                    break
                continue
            refusals, cleared_here = 0, False
            self.failed.append(target)   # reached frontiers are not picked twice either
        grid = self.nav.mapd.call("map.grid", {"res_m": 0.05})
        (self.out / "map_grid.json").write_text(json.dumps(grid))
        return {"legs": legs, "minutes": round((time.monotonic() - (end - minutes * 60)) / 60, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=Path("runs/explore"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    nav = Navigator(log=args.out / "ticks.jsonl")

    def guard():
        while not nav.abort:
            p = nav.body.pose()
            if stairs_distance(p) < GUARD_M or nav.body.height < 0.06:
                nav.abort = f"truth guard: {stairs_distance(p):.2f} m from the staircase, trunk {nav.body.height:.3f} m"
            time.sleep(0.05)

    threading.Thread(target=guard, daemon=True).start()
    try:
        if nav.loc.pose() is None and not nav.fix():
            nav.survey()
        (args.out / "start.json").write_text(json.dumps({"map": nav.loc.pose(), "truth": nav.body.pose(),
                                                          "scale": nav.scale}))
        result = Explorer(nav, args.out).run(args.minutes)
        print(json.dumps(result))
    finally:
        nav.close()


if __name__ == "__main__":
    main()
