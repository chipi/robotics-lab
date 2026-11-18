"""Explore the apartment: survey, go to the nearest frontier, repeat (RFC-0002 phase 2, "the brain
explores"). The simulator's truth is logged for scoring only; the brain never reads it.

    uv run duck-explore --minutes 20 --out runs/explore
    uv run duck-explore --minutes 20 --out runs/explore13 --miniview-data /work/robotics-lab/data   # a live miniview run too

The format 2 run (miniview, ADR-0014) is the record; ticks.jsonl is kept during the transition.
"""

import argparse
import json
import math
import threading
import time
from pathlib import Path

from duck_lab.nav.explore import frontiers, pick, without_retired
from duck_lab.nav.follow import Twist
from duck_lab.nav.grid import DROP_INFLATE_M, DROP_LETHAL_M, LETHAL_COST, CostGrid, EmptyMap, clearance
from duck_lab.nav.run import PIVOT_DROP_M, PIVOT_OBSTACLE_M, Navigator, decision
from duck_lab.nav.runlog import add_args, open_from_args
from duck_lab.nav.run import CALIBRATION
from duck_lab.world_model.objects import load_kinds
from duck_lab.nav.sim_camera import SimCamera

SURVEY_STEPS = 4            # a full turn in 90 deg steps: the depth sensor sees a 45 deg wedge
SURVEY_STEP_RAD = math.pi / 2
KICK_RAD_S, HOLD_RAD_S, KICK_S = 1.2, 0.8, 1.0   # PHASE0-SPIKE.md: no start below ~1.1 rad/s
GO_TIMEOUT_S = 60.0
CLEAR_M = 0.5          # a boxed-in start forgets remembered obstacle points this close (as the planner's escape)
MAX_REFUSALS = 6       # refusals in a row before the run stops as trapped
RETIRE_M = 0.6         # a target with no path on the map retires the frontier within this of it
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
        self.retired = []         # frontier cells near a target with no path: those cells only (explore.without_retired)
        self.find = None          # a kind of object to find and go to (RFC-0016: "go to the fridge"); None: explore
        self.find_failed = set()  # objects found but out of reach
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
            self.note(event="no_survey_turn", why="drop within turn clearance",
                      decision=decision("no_survey_turn", "a remembered drop within turn clearance", drop_clear_m=PIVOT_DROP_M))
            return False
        if pose:
            try:
                room = clearance(self.nav.grid().with_points(self.nav.blocked + self.nav.semantic_points()), pose[:2],
                                 PIVOT_OBSTACLE_M)
            except EmptyMap:
                room = PIVOT_OBSTACLE_M
            if room < PIVOT_OBSTACLE_M:
                self.note(event="no_survey_turn", why=f"obstacle {room:.2f} m away",
                          decision=decision("no_survey_turn", "an obstacle within turn clearance", room_m=round(room, 3),
                                            min_room_m=PIVOT_OBSTACLE_M))
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

    def go_to_object(self, obj, pose: tuple, costs) -> dict:
        """Go and stand in front of a found object: the approach point (semantic_map.approach, on cells the cost map
        does not block), then turn to face it. A "found" event with the outcome (its truth is the judge's)."""
        def free(p):     # not lethal, and room to turn there (the hold-off lesson: a stand with no room is a trap)
            c = costs.cell(*p)
            return (not costs.inside(*c) or costs.at(*c) < LETHAL_COST) and \
                clearance(costs, p, PIVOT_OBSTACLE_M) >= PIVOT_OBSTACLE_M
        with self.nav._sem_lock:
            stand = self.nav.semantic.approach(obj, pose, free)
            summary = obj.summary()
        if stand is None:
            self.note(event="found", kind=obj.kind, object=summary, status="refused", why="nowhere free to stand",
                      decision=decision("found", f"a {obj.kind} is known, but nowhere near it is free"))
            return {"status": "refused", "why": "nowhere free to stand"}
        out = self.nav.go_to(stand[:2], GO_TIMEOUT_S)
        if out["status"] == "reached":
            now = self.nav.loc.pose()
            if now is not None:
                self.turn(wrap(stand[2] - now[2]))
        self.note(event="found", kind=obj.kind, object=summary, stand=[round(v, 3) for v in stand],
                  status=out["status"], why=out.get("why"),
                  decision=decision("found", f"went to the {obj.kind}", status=out["status"], object=obj.oid))
        return {"status": out["status"], "object": obj.oid, "stand": [round(v, 3) for v in stand], "why": out.get("why")}

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
                seen = self.nav.blocked + self.nav.semantic_points()
                costs = costs.covering([pose[:2]] + seen + self.nav.drops).with_points(seen)
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

            if self.find and self.nav.semantic is not None:
                with self.nav._sem_lock:
                    obj = self.nav.semantic.find(self.find, pose)
                if obj is not None and obj.oid not in self.find_failed:
                    out = self.go_to_object(obj, pose, costs)
                    if out["status"] == "reached":
                        return {"legs": legs, "found": out,
                                "minutes": round((time.monotonic() - (end - minutes * 60)) / 60, 1)}
                    self.find_failed.add(obj.oid)    # that one was out of reach: keep exploring for another

            avoid = self.failed + self.nav.drops
            blocked = list(self.nav.blocked)
            clusters = without_retired(frontiers(grid, self.nav.scale, obstacles=blocked), self.retired)
            target = pick(clusters, pose, avoid, ok=reachable)
            # The choice's inputs, so a replay of it is faithful (sim/probes/frontier_replay.py; the "world" events
            # are the navigator's grid at its plans, not the map read here).
            self.note(event="pick", grid={k: grid[k] for k in ("res_m", "origin", "width", "height", "cells")},
                      scale=self.nav.scale, pose=[round(v, 4) for v in pose],
                      avoid=[[round(v, 3) for v in a[:2]] for a in avoid],
                      obstacles=[[round(v, 3) for v in b[:2]] for b in blocked],
                      retired=[[round(v, 3) for v in r] for r in self.retired],
                      target=[round(v, 3) for v in target] if target else None)
            if target is None:
                if not surveyed_here:
                    self.survey()
                    surveyed_here = True
                    continue
                self.note(event="no_frontier_left", legs=legs,
                          decision=decision("no_frontier_left", "no reachable frontier after a survey", legs=legs))
                break
            surveyed_here = False
            legs += 1
            out = self.nav.go_to(target, min(GO_TIMEOUT_S, end - time.monotonic()))
            self.note(event="leg", n=legs, target=[round(v, 2) for v in target], status=out["status"],
                      why=out.get("why"))
            if out.get("why") == "start boxed in" and not cleared_here:
                gone = self.nav.forget_blocked_near(pose, CLEAR_M)
                self.note(event="cleared", points=gone,
                          decision=decision("cleared", "the start was boxed in: obstacle points near it forgotten", points=gone,
                                            radius_m=CLEAR_M))
                cleared_here = True
                continue          # the same frontier again: the start was the problem, not the target
            if out["status"] != "reached":
                self.failed.append(target)
                unreachable = out["status"] == "refused" and out.get("why") == "no path on the map"
                if unreachable and clusters:
                    # That stretch of the frontier is out of reach, not only this point of it (b2 r3: six targets in
                    # the same stairwell frontier, within 0.5 m of each other, refused in one second, and the run ended
                    # "trapped" at the dock). Only the stretch near it: the whole cluster ran along the corridor in b4
                    # (124 and 201 points retired by one refusal) and took the ways north and south with it.
                    near = min(clusters, key=lambda c: min(math.dist(p, target) for p in c))
                    self.retired.extend(p for p in near if math.dist(p, target) <= RETIRE_M)
                # A run of refusals says the duck is stuck; a target with no path says only that the target is out of
                # reach (b2 r3, b3 r2: "trapped" at the dock, free to walk north).
                if not unreachable:
                    refusals = refusals + 1 if out["status"] == "refused" else 0
                if refusals >= MAX_REFUSALS:
                    # Trial 4: one boxed-in start refused 37 frontiers in a second and ended the run as
                    # "no frontier left". A run of refusals says the duck is stuck, not that the map is done.
                    self.note(event="trapped", legs=legs, refusals=refusals,
                              decision=decision("trapped", f"{refusals} refusals in a row", legs=legs, refusals=refusals,
                                                max_refusals=MAX_REFUSALS))
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
    ap.add_argument("--find", metavar="KIND", help="explore until an object of this kind is found, then go to it "
                    "(RFC-0016; kinds: duck_lab/world_model/kinds.json), e.g. fridge")
    ap.add_argument("--no-objects", action="store_true", help="no simulated camera and no semantic map")
    ap.add_argument("--object-costs", action="store_true", help="confirmed objects join the cost map (off by default)")
    add_args(ap)
    args = ap.parse_args()
    if args.find and args.find not in load_kinds():
        ap.error(f"no kind {args.find!r}; the kinds: {', '.join(sorted(load_kinds()))}")
    if args.find and args.no_objects:
        ap.error("--find needs the objects (drop --no-objects)")
    args.out.mkdir(parents=True, exist_ok=True)
    runlog = open_from_args(args, args.out.name, "exploration", args.out)
    nav = Navigator(log=args.out / "ticks.jsonl", runlog=runlog)

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
        if not args.no_objects:
            cal = json.loads((CALIBRATION / "sim.json").read_text()).get("camera", {})
            nav.enable_objects(SimCamera(config=cal), load_kinds(), costs=args.object_costs)
        explorer = Explorer(nav, args.out)
        explorer.find = args.find
        result = explorer.run(args.minutes)
        print(json.dumps(result))
    finally:
        nav.close()
        if nav.semantic is not None:
            with nav._sem_lock:
                (args.out / "semantic_map.json").write_text(json.dumps(nav.semantic.to_json(), indent=1))
        if runlog:
            runlog.finish()


if __name__ == "__main__":
    main()
