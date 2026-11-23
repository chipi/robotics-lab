"""The duck's explorer: survey, go to the nearest frontier, repeat (RFC-0002 phase 2, "the brain explores"). It runs in
the navigator's process, as the payload's explore goal (duck_lab.payload) or a Mission Control goal (duck_lab.nav.server);
its runner is `lab-explore` (labrunner.explore_run, RFC-0022), which has the simulator's truth; the explorer never does.
"""

import json
import math
import time
from pathlib import Path

from duck_lab.nav.explore import STANDOFF_M, frontiers, pick, rim_unseen, without_retired
from duck_lab.nav.follow import Twist
from duck_lab.nav.frames import move_xy
from duck_lab.nav.grid import LETHAL_COST, CostGrid, EmptyMap, clearance, plan
from duck_lab.nav import anomaly as anom, recovery
from duck_lab.nav.run import FLOOR_CELL_M, Navigator, decision

# the events that end an exploration before its time (its runner reads them): a stop is named by what stopped it
ENDS = ("trapped", "no_frontier_left", "stopped_by_guardrail", "cancelled")
GO_TIMEOUT_S = 60.0
CLEAR_M = 0.5          # a boxed-in start forgets remembered obstacle points this close (as the planner's escape)
MAX_REFUSALS = 6       # refusals in a row before the run stops as trapped
RETIRE_M = 0.6         # a target with no path on the map retires the frontier within this of it
FIND_RETRY_LEGS = 5    # an object found but out of reach is tried again after this many more legs


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

    def avoid(self) -> list:
        """The points a target keeps AVOID_M from: failed targets and the navigator's hazards, the planner's own set (drops, measured
        edges, suspected drops). Drops alone left a 44-point rim unavoided (challenge 22, no cliff stop)."""
        return self.failed + self.nav.hazards()

    def hazard_costs(self, costs: CostGrid) -> CostGrid:
        """costs with the hazards' zones as the planner grows them (Navigator.leg's rings): a drop's, an edge's, a suspect's."""
        nav, suspected = self.nav, self.nav.suspects.points()
        costs = costs.covering(nav.drops + nav.edges + suspected).with_blocked(nav.drops, nav.drop_lethal_m, nav.drop_inflate_m)
        costs = costs.with_blocked(nav.edges, nav.edge_lethal_m, nav.edge_inflate_m)
        return costs.with_blocked(suspected, nav.edge_lethal_m, nav.edge_inflate_m)

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
                self.note(event=self.nav.stop_end or "stopped_by_guardrail", why=self.nav.abort)
                break
            grid = self.nav.mapd_grid()      # scaled, in the belief's frame: the frontiers are places the planner goes to
            moved_at = len(self.nav._moves)
            pose = self.nav.loc.pose()
            try:
                # covering() as the navigator does: a drop beyond mapd's grid still grows its zone into it
                # (trial 6 picked a goal the navigator then scored lethal).
                costs = self.nav.grid()
                seen = self.nav.blocked + self.nav.semantic_points()
                costs = self.hazard_costs(costs.covering([pose[:2]] + seen).with_points(seen))
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
                # The rim share (explore.rim_unseen) is recorded in `pick`, not enforced: at RIM_UNSEEN it raised challenge 22's
                # trapped runs from 1 in 20 to 4 in 10 (docs/wip/CH22-RIM.md).
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

            avoid = self.avoid()
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
                      target=[round(v, 3) for v in target] if target else None,
                      rim=round(rim_unseen(grid, target, lambda p: self.nav.floor_seen_near(p, FLOOR_CELL_M)), 3) if target else None)
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
