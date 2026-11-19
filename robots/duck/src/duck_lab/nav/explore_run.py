"""Explore the apartment: survey, go to the nearest frontier, repeat (RFC-0002 phase 2, "the brain
explores"). The simulator's truth is logged for scoring only; the brain never reads it.

    uv run duck-explore --minutes 20 --out runs/explore
    uv run duck-explore --minutes 20 --out runs/explore13 --miniview-data /work/robotics-lab/data   # a live Observatory run too

The format 2 run (Observatory, ADR-0014) is the record; ticks.jsonl is kept during the transition.
"""

import argparse
import json
import math
import threading
import time
from pathlib import Path

from duck_lab.nav.explore import STANDOFF_M, frontiers, pick, without_retired
from duck_lab.nav.follow import Twist
from duck_lab.nav.frames import move_xy
from duck_lab.nav.grid import LETHAL_COST, CostGrid, EmptyMap, clearance, plan
from duck_lab.nav import anomaly as anom, recovery
from duck_lab.nav.run import Navigator, decision
from duck_lab.nav.runlog import add_args, open_from_args
from worldmodel.objects import load_kinds
from duck_lab.site_cli import SITES
from worldmodel.site import Site
from duck_lab.nav.sim_camera import SimCamera

GO_TIMEOUT_S = 60.0
CLEAR_M = 0.5          # a boxed-in start forgets remembered obstacle points this close (as the planner's escape)
MAX_REFUSALS = 6       # refusals in a row before the run stops as trapped
RETIRE_M = 0.6         # a target with no path on the map retires the frontier within this of it
FIND_RETRY_LEGS = 5    # an object found but out of reach is tried again after this many more legs
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
        self.reached = []         # frontier targets reached: the frontier within STANDOFF_M of each is done
        self.find = None          # a kind of object to find and go to (RFC-0016: "go to the fridge"); None: explore
        self.find_failed = {}     # objects found but out of reach -> the leg count when it was last tried
        self.events = []
        self.attempts = 0         # recoveries in a row since a leg was reached
        self.within = None        # a test of a point (xy -> bool) the frontiers must pass (explore {area}, RFC-0014 §3.4.1), else the whole map
        an = getattr(nav, "anomalies", None)  # refusals in a row at one pose (RFC-0019's refusal_burst), the profile's limits
        self.burst = anom.RefusalBurst(an.refusal_burst_n, an.refusal_burst_moved_m) if an else anom.RefusalBurst()
        nav.on_move = self.move_frame

    def watch_burst(self, out: dict, pose: tuple, legs: int) -> None:
        """A leg's outcome: refusals at one pose with no motion between (b11 r2: six in 0.45 s, then "trapped") are one anomaly, said
        when the streak reaches the profile's refusal_burst_n; any other outcome ends the streak."""
        if out["status"] != "refused":
            self.burst.reset()
            return
        n = self.burst.refused(pose[:2])
        if n:
            self.nav.anomaly("refusal_burst", f"{n} legs refused in a row at one pose: {out.get('why')}", margin=n - self.burst.n,
                             values={"refusals": n, "why": out.get("why"), "legs": legs, "limit": self.burst.n, "moved_max_m": self.burst.moved_m,
                                     "max_refusals": MAX_REFUSALS, "margin_unit": "refusals"})

    def move_frame(self, d: tuple) -> None:
        """The belief's frame moved (the navigator moved its memory): the frontier targets' bookkeeping moves with it."""
        for lst in (self.failed, self.retired, self.reached):
            lst[:] = [move_xy(d, p) for p in lst]

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
        if pose and any(math.dist(pose[:2], d) < self.nav.pivot_drop_m for d in self.nav.drops):
            self.note(event="no_survey_turn", why="drop within turn clearance",
                      decision=decision("no_survey_turn", "a remembered drop within turn clearance", drop_clear_m=self.nav.pivot_drop_m))
            return False
        if pose:
            try:
                room = clearance(self.nav.grid().with_points(self.nav.blocked + self.nav.semantic_points()), pose[:2],
                                 self.nav.pivot_obstacle_m)
            except EmptyMap:
                room = self.nav.pivot_obstacle_m
            if room < self.nav.pivot_obstacle_m:
                self.note(event="no_survey_turn", why=f"obstacle {room:.2f} m away",
                          decision=decision("no_survey_turn", "an obstacle within turn clearance", room_m=round(room, 3),
                                            min_room_m=self.nav.pivot_obstacle_m))
                return False
        start, began = self.yaw(), time.monotonic()
        while time.monotonic() - began < 8.0:
            done = wrap(self.yaw() - start)
            if abs(done) >= abs(angle) - math.radians(8):
                break
            rate = self.nav.loco.kick_rad_s if time.monotonic() - began < self.nav.loco.kick_s else self.nav.loco.hold_rad_s
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
                clearance(costs, p, self.nav.pivot_obstacle_m) >= self.nav.pivot_obstacle_m
        with self.nav._sem_lock:
            stands = self.nav.semantic.approaches(obj, pose, free)
            summary = obj.summary()
        # the nearest stand the planner can reach (find-fridge-4: the nearest one was in unmapped space, "no path on
        # the map", and the fridge was never tried again)
        stand = next((s for s in stands if plan(costs, pose[:2], s[:2]) is not None), None)
        if stand is None:
            why = "nowhere free to stand" if not stands else f"no way to any of {len(stands)} places to stand"
            self.note(event="found", kind=obj.kind, object=summary, status="refused", why=why,
                      decision=decision("found", f"a {obj.kind} is known, but {why}", stands=len(stands)))
            return {"status": "refused", "why": why}
        out = self.nav.go_to(stand[:2], GO_TIMEOUT_S)
        if out["status"] == "reached":
            now = self.nav.loc.pose()
            if now is not None:
                self.turn(wrap(stand[2] - now[2]))
        self.note(event="found", kind=obj.kind, object=summary, stand=[round(v, 3) for v in stand],
                  status=out["status"], why=out.get("why"),
                  decision=decision("found", f"went to the {obj.kind}", status=out["status"], object=obj.oid))
        return {"status": out["status"], "object": obj.oid, "stand": [round(v, 3) for v in stand], "why": out.get("why")}

    def recovered(self, out: dict) -> bool:
        """A refusal that is about the pose, not the target (no room to turn; a start in a lethal cell): the same pose refuses
        every target, and six of them in half a second ended four of b11's five runs. A recovery there first (creep, arc away, a
        survey: Navigator.recover); True when one was made, and the refusal does not count. Only when recovery.MAX_ATTEMPTS in
        a row (no leg reached between) have not freed the duck does the refusal count toward "trapped"."""
        why = out.get("why") or ""
        if out.get("status") != "refused" or self.attempts >= recovery.MAX_ATTEMPTS:
            return False
        if not (why.startswith("no room to turn") or why == "start boxed in" or out.get("start_lethal")):
            return False
        self.nav.recover(self.attempts)
        self.attempts += 1
        return True

    def leave_drop(self) -> None:
        """A run that starts within recovery.START_MARGIN_M of a remembered drop goes first to a place away from the nearest one
        (recovery.away_target: seen floor, not lethal, room to turn), not to the nearest frontier: the pose beside a drop refuses
        every turn. Not tied to a site: any run, any place."""
        pose = self.nav.loc.pose()
        if pose is None:
            return
        try:
            costs = self.nav.grid()
        except EmptyMap:
            return
        seen = self.nav.blocked + self.nav.semantic_points()
        costs = costs.covering([pose[:2]] + seen + self.nav.drops + self.nav.edges).with_points(seen)
        costs = costs.with_blocked(self.nav.drops, self.nav.drop_lethal_m, self.nav.drop_inflate_m).with_blocked(self.nav.edges, self.nav.edge_lethal_m,
                                                                                               self.nav.edge_inflate_m)

        def ok(p):
            c = costs.cell(*p)
            return self.nav.floor_seen_near(p) and (not costs.inside(*c) or costs.at(*c) < LETHAL_COST) and \
                clearance(costs, p, self.nav.pivot_obstacle_m) >= self.nav.pivot_obstacle_m

        away = recovery.away_target(pose, self.nav.hazards(), ok)
        if away is None:
            return
        out = self.nav.go_to(away, GO_TIMEOUT_S)
        self.note(event="leave_drop", target=[round(v, 3) for v in away], status=out["status"], why=out.get("why"),
                  decision=decision("leave_drop", "the run started beside a drop: first to a place away from it",
                                    status=out["status"], start_margin_m=recovery.START_MARGIN_M))

    def survey(self) -> None:
        for _ in range(self.nav.profile.looking.survey_steps):
            self.nav.survey()
            if not self.turn(math.radians(self.nav.profile.looking.survey_step_deg)):
                break
        self.nav.survey()

    def run(self, minutes: float) -> dict:
        end = time.monotonic() + minutes * 60
        legs = 0
        # A full survey is 4 x 90 deg, ~30 s; a leg is ~5 s. Trial 4 surveyed after every leg and spent
        # 85% of its time turning on the spot, so the survey now runs only when no frontier is in sight.
        self.survey()
        self.leave_drop()
        surveyed_here, cleared_here, refusals = True, False, 0
        while time.monotonic() < end:
            if self.nav.abort:
                self.note(event="aborted", why=self.nav.abort)
                break
            grid = self.nav.mapd_grid()      # scaled, in the belief's frame: the frontiers are places the planner goes to
            moved_at = len(self.nav._moves)
            pose = self.nav.loc.pose()
            try:
                # covering() as the navigator does: a drop beyond mapd's grid still grows its zone into it
                # (trial 6 picked a goal the navigator then scored lethal).
                costs = self.nav.grid()
                seen = self.nav.blocked + self.nav.semantic_points()
                costs = costs.covering([pose[:2]] + seen + self.nav.drops).with_points(seen)
                costs = costs.with_blocked(self.nav.drops, self.nav.drop_lethal_m, self.nav.drop_inflate_m)
            except EmptyMap:
                self.survey()
                continue

            def reachable(goal, costs=costs):
                if self.within is not None and not self.within(goal):
                    return False
                c = costs.cell(*goal)
                if costs.inside(*c) and costs.at(*c) >= LETHAL_COST:
                    return False
                # Floor the depth sensor saw, not only mapd's "free": mapd draws a stairwell as free
                # (upstream #599) and trial 10 picked a target inside one.
                return self.nav.floor_seen_near(goal)

            if self.find and self.nav.semantic is not None:
                with self.nav._sem_lock:
                    obj = self.nav.semantic.find(self.find, pose)
                # an object out of reach is tried again after FIND_RETRY_LEGS more legs: the map grows meanwhile
                # (find-fridge-4 crossed the only fridge off for good at 119 s and explored on for 20 min)
                if obj is not None and legs >= self.find_failed.get(obj.oid, -FIND_RETRY_LEGS) + FIND_RETRY_LEGS:
                    out = self.go_to_object(obj, pose, costs)
                    if out["status"] == "reached":
                        return {"legs": legs, "found": out,
                                "minutes": round((time.monotonic() - (end - minutes * 60)) / 60, 1)}
                    self.find_failed[obj.oid] = legs

            avoid = self.failed + self.nav.drops
            blocked = list(self.nav.blocked)
            clusters = without_retired(frontiers(grid, 1.0, obstacles=blocked), self.retired)
            # a reached target takes out only the frontier where it stood (b8 r1, r2: the 0.4 m discs of 15 reached
            # targets covered every frontier left; with STANDOFF_M, 66 and 81 cells usable at the same pick)
            clusters = without_retired(clusters, self.reached, STANDOFF_M)
            target = pick(clusters, pose, avoid, ok=reachable)
            if len(self.nav._moves) != moved_at:
                continue          # the memory moved while this was worked out (the costs read its own grid): again, in one frame
            # The choice's inputs, so a replay of it is faithful (sim/probes/frontier_replay.py; the "world" events
            # are the navigator's grid at its plans, not the map read here).
            self.note(event="pick", grid={k: grid[k] for k in ("res_m", "origin", "width", "height", "cells")},
                      scale=1.0, pose=[round(v, 4) for v in pose],
                      avoid=[[round(v, 3) for v in a[:2]] for a in avoid],
                      obstacles=[[round(v, 3) for v in b[:2]] for b in blocked],
                      retired=[[round(v, 3) for v in r] for r in self.retired],
                      reached=[[round(v, 3) for v in r] for r in self.reached],
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
            moves = len(self.nav._moves)
            out = self.nav.go_to(target, min(GO_TIMEOUT_S, end - time.monotonic()))
            for d in self.nav._moves[moves:]:      # the leg moved the memory: its target, a place in the world, moved with it
                target = move_xy(d, target)[:2]
            pose = self.nav.loc.pose() or pose
            self.note(event="leg", n=legs, target=[round(v, 2) for v in target], status=out["status"],
                      why=out.get("why"))
            self.watch_burst(out, pose, legs)
            if out.get("why") == "start boxed in" and not cleared_here:
                gone = self.nav.forget_blocked_near(pose, CLEAR_M)
                self.note(event="cleared", points=gone,
                          decision=decision("cleared", "the start was boxed in: obstacle points near it forgotten", points=gone,
                                            radius_m=CLEAR_M))
                cleared_here = True
                continue          # the same frontier again: the start was the problem, not the target
            if out["status"] != "reached":
                if self.recovered(out):
                    continue          # a refusal at the pose: recovered from, not counted, the target not failed
                self.failed.append(target)
                unreachable = out["status"] == "refused" and out.get("why") == "no path on the map" and not out.get("start_lethal")
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
            refusals, cleared_here, self.attempts = 0, False, 0
            self.reached.append(target)  # not picked twice; it takes out only the frontier where it stood
            # stand still for mapd at the frontier just reached: mapd maps only at stops, and without one the frontier
            # stayed on its map, next to a target never picked again (b8: "no frontier left" at 3.3 and 3.7 min)
            self.nav.survey()
        grid = self.nav.mapd.call("map.grid", {"res_m": 0.05})
        (self.out / "map_grid.json").write_text(json.dumps(grid))
        if self.find:
            # the goal's outcome in the run itself, not only by its absence (RFC-0016 rev. 3; RFC-0014 `not_found`)
            with self.nav._sem_lock:
                known = self.nav.semantic.find(self.find) if self.nav.semantic is not None else None
            why = "known but never reached" if known is not None else "never seen"
            self.note(event="found", kind=self.find, status="not_found", why=why,
                      decision=decision("found", f"no {self.find}: {why}", legs=legs))
        return {"legs": legs, "minutes": round((time.monotonic() - (end - minutes * 60)) / 60, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=Path("runs/explore"))
    ap.add_argument("--find", metavar="KIND", help="explore until an object of this kind is found, then go to it "
                    "(RFC-0016; kinds: libs/worldmodel/src/worldmodel/kinds.json), e.g. fridge")
    ap.add_argument("--inventory", action="store_true", help="the goal is to find all objects: explore, then say what "
                    "is where (inventory.json is written whenever the objects are on)")
    ap.add_argument("--no-objects", action="store_true", help="no simulated camera and no semantic map")
    ap.add_argument("--site", help="a site's id: start from its map, save it back at the end (duck-site create first)")
    ap.add_argument("--sites", type=Path, default=SITES, help=f"the sites' folder (default {SITES})")
    ap.add_argument("--object-costs", action="store_true", help="confirmed objects join the cost map (off by default)")
    ap.add_argument("--no-relocalise", action="store_true", help="landmarks do not correct the belief (the run before relocalisation)")
    ap.add_argument("--fix-fault", help="T,DX,DY: from T s on, mapd's pose is shifted by (DX, DY) m, a persistent jump like explore-b10a-r1 (a test)")
    ap.add_argument("--frame-fault", help="T,DX,DY: as --fix-fault, and mapd's grid shifts with its pose (its frame jumped as a "
                    "whole: pose and grid come from one graph, mapping-design §5) (a test)")
    ap.add_argument("--no-frames", action="store_true", help="the grid stays in mapd's frame and the memory does not move with the "
                    "belief's (the run before RFC-0016 §6's frame fix; a test)")
    ap.add_argument("--no-fix-gate", action="store_true", help="every mapd fix is taken (the run before the fix gate)")
    add_args(ap)
    args = ap.parse_args()
    if args.find and args.find not in load_kinds():
        ap.error(f"no kind {args.find!r}; the kinds: {', '.join(sorted(load_kinds()))}")
    if (args.find or args.inventory) and args.no_objects:
        ap.error("--find and --inventory need the objects (drop --no-objects)")
    args.out.mkdir(parents=True, exist_ok=True)
    runlog = open_from_args(args, args.out.name, "exploration", args.out)
    nav = Navigator(log=args.out / "ticks.jsonl", runlog=runlog)
    if args.no_fix_gate:
        nav.loc.max_jump_m = None
    if args.fix_fault and args.frame_fault:
        ap.error("--fix-fault and --frame-fault are one fault: give one")
    if args.fix_fault or args.frame_fault:
        nav.fix_fault = tuple(float(v) for v in (args.fix_fault or args.frame_fault).split(","))
        nav.fault_grid = bool(args.frame_fault)
    nav.frames_on = not args.no_frames

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
        site = None
        if not args.no_objects:
            cal = nav.profile.get("sensors.camera", {})
            if args.site:
                # the site's map from earlier runs: its objects are known before they are seen again (the run starts at
                # the dock, the site frame, so its map frame is the site's; RFC-0016 rev. 3)
                site = Site.load(args.sites, args.site, load_kinds())
                nav.record(event="site", id=site.sid, name=site.name, kind=site.kind,
                           objects=len(site.semantic.objects), areas=[a.to_json() for a in site.areas])
            nav.enable_objects(SimCamera(config=cal), load_kinds(), costs=args.object_costs,
                               semantic=site.semantic if site else None,
                               area_at=site.area_at if site and site.areas else None, relocalise=not args.no_relocalise)
        explorer = Explorer(nav, args.out)
        explorer.find = args.find
        result = explorer.run(args.minutes)
        print(json.dumps(result))
    finally:
        nav.close()
        if nav.semantic is not None:
            with nav._sem_lock:
                (args.out / "semantic_map.json").write_text(json.dumps(nav.semantic.to_json(), indent=1))
                inventory = nav.semantic.inventory(nav._map_raw)
            (args.out / "inventory.json").write_text(json.dumps(inventory, indent=1))
            # the inventory in the run too (RFC-0016 rev. 3): the Observatory and Mission Control read runs, not files
            nav.record(event="inventory", objects=inventory["objects"], rooms=inventory["rooms"],
                       decision=decision("inventory", f"{inventory['objects']} objects found",
                                         objects=inventory["objects"]))
            if args.inventory:
                print(f"INVENTORY {inventory['objects']} objects: " + "; ".join(
                    f"{room}: {', '.join(o['kind'] for o in objs)}" for room, objs in inventory["rooms"].items()))
            if site is not None:
                with nav._sem_lock:
                    site.save()       # the run worked on the site's own map: its ids stay, the new objects join
                print(f"SITE {site.sid}: {len(site.semantic.objects)} objects saved to {site.folder}")
        if runlog:
            runlog.finish()


if __name__ == "__main__":
    main()
