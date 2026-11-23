"""The anomaly detectors and `observatory anomalies` (RFC-0019 steps 1-2): each rule at its threshold on small made-up runs,
each fixture coming out as the anomaly it was (tests/fixtures/anomalies, slices of real recordings), the command line, and
that nothing is written. Run: cd apps/observatory && uv run python tests/test_anomalies.py"""

import contextlib
import io
import json
import math
import sys
import tomllib
from pathlib import Path

from helpers import T0_NS, Checks, import_fixture  # noqa: F401  (helpers sets the test index)

from observatory import anomalies as A, cli
from runfile import mcapio
from runfile.adapters import duck
from observatory.importer import import_duck

ROOT = Path(__file__).resolve().parents[3]
SIM = ROOT / "robots" / "duck" / "sim"
FIX = Path(__file__).resolve().parent / "fixtures" / "anomalies"
check = Checks("ANOMALIES")


# ---- made-up runs ----------------------------------------------------------------------------------------------------

def make(ticks=(), events=(), worlds=(), name="syn", m2w=(0.0, 0.0, 0.0)):
    """A run: ticks (t, belief, truth, cmd), events (t, kind, raw), worlds (t, grid), the identity map-to-world unless m2w says."""
    recs = [(0.0, "epoch", {"map_to_world": list(m2w)})]
    recs += [(t, "tick", {"belief": b, "truth": tr, "tilt": None, "cmd": c, "depth": None, "t_src": t, "raw": {}}) for t, b, tr, c in ticks]
    recs += [(t, "event", {"kind": k, "text": "", "notable": True, "t_src": t, "raw": raw}) for t, k, raw in events]
    recs += [(t, "world", {"grid": g, "obstacles": [], "drops": [], "raw": {}}) for t, g in worlds]
    recs.sort(key=lambda r: r[0])
    run = mcapio.new_run(f"duck/apartment/{name}", {"name": "duck", "radius": 0.083, "height": 0.272}, "apartment", "exploration", T0_NS, "writer")
    return A.Run([(0.0, "run", run)] + recs)


def geom(name, kind, x, y, z, size, collides=True, yaw=0.0):
    return {"name": name, "type": kind, "pos": [x, y, z], "size": size, "yaw": yaw, "collides": collides}


LAYOUT = {"geoms": [
    geom("floor_a", "box", 0.0, 0.0, -0.005, [3.0, 2.0, 0.005]),
    geom("box1", "box", 1.0, 0.0, 0.1, [0.1, 0.1, 0.1]),
    geom("stair_1", "box", -1.0, -1.5, -0.2, [0.3, 0.2, 0.1]),
    geom("floor_r1", "box", -1.0, 0.0, 0.002, [1.0, 1.0, 0.002], collides=False),
    geom("floor_r2", "box", 1.0, 0.0, 0.002, [1.0, 1.0, 0.002], collides=False),
]}
TRUTH = A.Truth.from_layouts([LAYOUT])
SPLIT = A.Truth.from_layouts([{"geoms": LAYOUT["geoms"] + [geom("wall", "box", 0.0, 0.0, 0.5, [0.05, 2.0, 0.5])]}])


def still(n, truth, belief=None, cmd=(0.0, 0.0), dt=0.1):
    return [(i * dt, belief or truth, truth, list(cmd)) for i in range(n)]


def grid(res, origin, w, h, cells):
    """A map snapshot: `cells` maps (cx, cy) to a character, the rest is '?'."""
    s = [["?"] * w for _ in range(h)]
    for (cx, cy), ch in cells.items():
        s[cy][cx] = ch
    return {"res": res, "origin": list(origin), "w": w, "h": h, "cells": "".join("".join(r) for r in s)}


def found(run, id_, truth=TRUTH, **cfg):
    return A.analyse(run, truth, detectors=[id_], cfg=cfg)["anomalies"]


# near miss: footprint distance = the distance from the duck to box1's side minus nothing (the box's half size 0.1 at x = 1)
for gap, expect in ((0.089, True), (0.091, False)):
    r = make(still(20, [1.0, 0.1 + gap, 0.0]))
    out = found(r, "near_miss")
    check(f"near miss: {gap} m from an obstacle is {'one' if expect else 'none'} (the rule is under 0.090)", bool(out) == expect, len(out))
r = make(still(20, [1.0, 0.1 + 0.07, 0.0]))
out = found(r, "near_miss")
check("near miss: under the radius it is a contact, said critical and linked", len(out) == 1 and out[0]["severity"] == "critical"
      and out[0]["values"]["contact"] and out[0]["related"] == ["contact@0.0"], out and out[0]["related"])
check("near miss: the record has the RFC's fields", out and {"anomaly", "source", "module", "severity", "detector", "version", "t", "t_end",
                                                             "where", "summary", "values", "margin", "evidence", "related"} <= set(out[0])
      and out[0]["source"] == "analysis" and out[0]["detector"] == "near_miss" and out[0]["version"] == 1)
r = make(still(20, [1.0, 0.1 + 0.093, 0.0]))
check("near miss: 0.093 is quiet at 0.090 and fires at 0.093 + 0.001 (the threshold is data)",
      not found(r, "near_miss") and len(found(r, "near_miss", near_miss_m=0.094)) == 1)
check("near miss: a clear walk is quiet", not found(make(still(20, [0.0, 0.0, 0.0])), "near_miss"))

# dithering
walk_still = [(i * 0.1, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.3, 0.0]) for i in range(80)]
check("dithering: walking in place for 8 s is one episode", len(found(make(walk_still), "dithering")) == 1)
moving = [(i * 0.1, [0.03 * i, 0.0, 0.0], [0.03 * i, 0.0, 0.0], [0.3, 0.0]) for i in range(80)]
check("dithering: walking at 0.3 m/s is quiet", not found(make(moving), "dithering"))
pivot = [(i * 0.1, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.8]) for i in range(80)]
check("dithering: a pivot is not walking", not found(make(pivot), "dithering"))
slow = [(i * 0.1, [0.003 * i, 0.0, 0.0], [0.003 * i, 0.0, 0.0], [0.3, 0.0]) for i in range(80)]
check("dithering: 0.03 m/s of progress is under 0.12 m in 3 s", len(found(make(slow), "dithering")) == 1)
check("dithering: needs neither truth nor layout", not A.analyse(make(walk_still), None, detectors=["dithering"])["not_applied"])

# odometry scale
def odo(ratio, jump=False):
    rows, b = [], 0.0
    for i in range(101):
        tr = 0.03 * i
        b += 0.03 * ratio if i else 0.0
        if jump and i == 50:
            b += 1.0
        rows.append((i * 0.1, [b, 0.0, 0.0], [tr, 0.0, 0.0], [0.3, 0.0]))
    return rows


out = found(make(odo(0.9)), "odometry_scale")
check("odometry scale: 0.9 over 3 m is outside 0.95-1.05, major", len(out) == 1 and out[0]["severity"] == "major"
      and abs(out[0]["values"]["ratio"] - 0.9) < 0.01 and abs(out[0]["margin"] - 0.05) < 0.01, out and out[0]["values"])
check("odometry scale: 1.0 is quiet", not found(make(odo(1.0)), "odometry_scale"))
check("odometry scale: 0.96 is inside the band", not found(make(odo(0.96)), "odometry_scale"))
check("odometry scale: a fix's jump is left out, not counted as odometry", not found(make(odo(1.0, jump=True)), "odometry_scale"))
short = [(i * 0.1, [0.027 * i, 0.0, 0.0], [0.03 * i, 0.0, 0.0], [0.3, 0.0]) for i in range(50)]
check("odometry scale: under 2 m walked says nothing", not found(make(short), "odometry_scale"))

# belief against truth
def drift(dx, dyaw=0.0):
    return [(i * 0.1, [dx, 0.0, dyaw], [0.0, 0.0, 0.0], [0.0, 0.0]) for i in range(40)]


check("belief vs truth: 0.1 m is quiet", not found(make(drift(0.1)), "belief_vs_truth"))
check("belief vs truth: 0.3 m from the start is quiet (the clean runs' offset wanders to 0.28 m over twenty minutes; a constant offset is no jump)",
      not found(make(drift(0.3)), "belief_vs_truth"))
out = found(make(drift(0.4)), "belief_vs_truth")
check("belief vs truth: 0.4 m at the 95th percentile is a warning (minor)", len(out) == 1 and out[0]["severity"] == "minor" and out[0]["anomaly"] == "belief_off_truth")
out = found(make(drift(0.6)), "belief_vs_truth")
check("belief vs truth: 0.6 m is major", len(out) == 1 and out[0]["severity"] == "major")
out = found(make(drift(0.0, math.radians(30))), "belief_vs_truth")
check("belief vs truth: 30 degrees of heading is its own anomaly", len(out) == 1 and out[0]["anomaly"] == "heading_off_truth", out)


def stepped(dx, at=20, n=60, dt=0.1):
    return [(i * dt, [dx if i >= at else 0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0]) for i in range(n)]


out = [a for a in found(make(stepped(0.4)), "belief_vs_truth") if a["anomaly"] == "belief_jump"]
check("belief vs truth: the belief's offset stepping by 0.4 m in one tick is a jump (minor), at the tick it happened, with the size",
      len(out) == 1 and out[0]["anomaly"] == "belief_jump" and out[0]["severity"] == "minor" and abs(out[0]["values"]["change_m"] - 0.4) < 1e-6
      and abs(out[0]["t"] - 2.0) < 0.2, out and out[0]["values"])
out = found(make(stepped(0.9)), "belief_vs_truth")
check("belief vs truth: a jump of 0.9 m is major (K4's size)", any(a["anomaly"] == "belief_jump" and a["severity"] == "major" for a in out), [a["anomaly"] for a in out])
check("belief vs truth: 0.25 m in one tick is under the line", not found(make(stepped(0.25)), "belief_vs_truth"))
slow = [(i * 0.1, [0.4 * i / 400, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0]) for i in range(400)]
check("belief vs truth: 0.4 m over 40 s is a drift, not a jump (0.1 m in any 10 s)", not [a for a in found(make(slow), "belief_vs_truth") if a["anomaly"] == "belief_jump"])

# phantom obstacle: cells (cx, cy) at res 0.1 from (-3, -2): cell (10, 30) is the world point (-1.95, 1.05)
def world_with(cells, t=10.0):
    base = {(c, y): "." for c in range(0, 60) for y in (0,)}
    base.update(cells)
    return (t, grid(0.1, (-3.0, -2.0), 60, 40, base))


far3 = {(10, 30): "#", (10, 31): "#", (10, 32): "#"}
out = found(make(worlds=[world_with(far3)]), "phantom_obstacle")
check("phantom: 3 occupied cells far from any outline", len(out) == 1 and out[0]["values"]["cells"] == 3 and out[0]["margin"] > 0, out and out[0]["values"])
check("phantom: 2 cells are noise", not found(make(worlds=[world_with({(10, 30): "#", (10, 31): "#"})]), "phantom_obstacle"))
near3 = {(39, 18): "#", (39, 19): "#", (39, 20): "#"}      # world (0.95, -0.15 .. 0.05): at box1's face
check("phantom: cells at a real obstacle are not phantoms", not found(make(worlds=[world_with(near3)]), "phantom_obstacle"))
out = found(make(worlds=[world_with(far3, 10.0), world_with(far3, 20.0)]), "phantom_obstacle")
check("phantom: the same place over two snapshots is one record, with its span", len(out) == 1 and out[0]["t"] == 10.0 and out[0]["t_end"] == 20.0)
no_free = A.Truth.from_layouts([LAYOUT])
with_free = A.Truth.from_layouts([LAYOUT, {"geoms": [geom("obj_x_geom", "box", -1.95, 1.0, 0.035, [0.035, 0.035, 0.035])]}])
check("phantom: a free body in the truth is a real outline (the cube by the dock)",
      found(make(worlds=[world_with(far3)]), "phantom_obstacle", truth=no_free) and not found(make(worlds=[world_with(far3)]), "phantom_obstacle", truth=with_free))

# missed obstacle: box1 at (1, 0), half 0.1: outline samples at 0.9..1.1; the map knows everything with no '#'
known = {(cx, cy): "." for cx in range(30, 50) for cy in range(10, 30)}
out = found(make(worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, known))]), "missed_obstacle")
check("missed obstacle: an obstacle in known cells with nothing occupied near it", len(out) == 1 and out[0]["values"]["obstacle"] == "box1", out and out[0]["values"])
seen = {**known, **{(cx, cy): "#" for cx in range(38, 42) for cy in range(18, 22)}}
check("missed obstacle: occupied cells within 0.15 m of the samples are seen", not found(make(worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, seen))]), "missed_obstacle"))
check("missed obstacle: unknown cells prove nothing", not found(make(worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, {}))]), "missed_obstacle"))
# ... as the duck could have placed it: what it was in sight of, looked up where its belief put it, and nothing thinner than the map's cell
only_near = {**known, **{(cx, cy): "#" for cx in (37, 38) for cy in range(18, 22)}}       # x 0.75 and 0.85: the near face is there, the far face (x 1.1) is not
w_near = [(10.0, grid(0.1, (-3.0, -2.0), 60, 40, only_near))]
check("missed obstacle: with no truth poses the far face counts (nothing says it was not in sight)", len(found(make(worlds=w_near), "missed_obstacle")) == 1)
check("missed obstacle: the far face of a box the duck stood in front of was never in sight, so it is not missed",
      not found(make(still(20, [0.0, 0.0, 0.0]), worlds=w_near), "missed_obstacle"))
check("missed obstacle: a box beyond missed_seen_m (1.0 m) was not in sight either", not found(make(still(20, [-1.5, 0.0, 0.0]), worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, known))]), "missed_obstacle"))
check("missed obstacle: ... and the same box 0.9 m from the face, nothing occupied, is missed",
      len(found(make(still(20, [0.0, 0.0, 0.0]), worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, known))]), "missed_obstacle")) == 1)
shifted = {**known, **{(cx, cy): "#" for cx in (41, 42) for cy in range(18, 22)}}         # the map holds the box 0.3 m further on: the belief was 0.3 m off
check("missed obstacle: a map 0.3 m off the truth is the belief's offset, not a missed box (looked up where the belief would put it)",
      not found(make(still(20, [0.0, 0.0, 0.0], belief=[0.3, 0.0, 0.0]), worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, shifted))]), "missed_obstacle"))
check("missed obstacle: ... and the same map with a belief that was right says the box was missed",
      len(found(make(still(20, [0.0, 0.0, 0.0]), worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, shifted))]), "missed_obstacle")) == 1)
LEG = A.Truth.from_layouts([{"geoms": [geom("floor_a", "box", 0.0, 0.0, -0.005, [3.0, 2.0, 0.005]), geom("leg", "box", 1.0, 0.0, 0.1, [0.018, 0.018, 0.1]),
                                       geom("pole", "cylinder", 1.0, 0.5, 0.2, [0.015, 0.2, 0.0])]}])
check("missed obstacle: a leg and a pole under 5 cm across are not asked of the map", not found(make(worlds=[(10.0, grid(0.1, (-3.0, -2.0), 60, 40, known))]), "missed_obstacle", truth=LEG))

# misplaced edge: the stairwell is x -1.3..-0.7, y -1.7..-1.3
far_rim = {"rim_points": [[-1.0, -0.9], [-1.1, -0.92], [-0.9, -0.88]], "status": "drop"}
near_rim = {"rim_points": [[-1.0, -1.25], [-1.1, -1.27], [-0.9, -1.24]], "status": "drop"}
out = found(make(events=[(5.0, "glance", far_rim), (7.0, "refused", {})]), "misplaced_edge")
check("misplaced edge: a rim 0.4 m off with a refusal 2 s later", len(out) == 1 and abs(out[0]["values"]["median_m"] - 0.4) < 0.01 and out[0]["related"] == ["refused@7.0"], out and out[0]["values"])
check("misplaced edge: a refusal 6 s later is too late", not found(make(events=[(5.0, "glance", far_rim), (11.0, "refused", {})]), "misplaced_edge"))
check("misplaced edge: without a refusal or a trap it is not reported", not found(make(events=[(5.0, "glance", far_rim)]), "misplaced_edge"))
check("misplaced edge: a rim 0.05 m off is placed well", not found(make(events=[(5.0, "glance", near_rim), (7.0, "refused", {})]), "misplaced_edge"))

# wrong refusal: floor_a is 6 x 4 m; SPLIT has a wall across it from edge to edge
def leg(t, target, at):
    return (t, "leg", {"n": 1, "target": target, "status": "refused", "why": "no path on the map", "truth": at})


ticks = still(5, [-2.0, 0.0, 0.0])
check("wrong refusal: a goal on the same side, refused", len(found(make(ticks, [(0.2, *leg(0.2, [-1.0, 0.5], [-2.0, 0.0, 0.0])[1:])]), "wrong_refusal", truth=SPLIT)) == 1)
check("wrong refusal: a goal across a wall that fills the floor is rightly refused",
      not found(make(ticks, [(0.2, *leg(0.2, [2.0, 0.5], [-2.0, 0.0, 0.0])[1:])]), "wrong_refusal", truth=SPLIT))
check("wrong refusal: a goal inside the stairwell is rightly refused",
      not found(make(ticks, [(0.2, *leg(0.2, [-1.0, -1.5], [-2.0, 0.0, 0.0])[1:])]), "wrong_refusal", truth=SPLIT))

# area uncovered: r1 (x -2..0) known, r2 (x 0..2) not; grid origin (-3, -2) at 0.1: x = 0 is cell 30
left = {(cx, cy): "." for cx in range(10, 30) for cy in range(10, 30)}
w = (10.0, grid(0.1, (-3.0, -2.0), 60, 40, left))
out = found(make(events=[(11.0, "no_frontier_left", {})], worlds=[w]), "area_uncovered")
check("area uncovered: 'nothing left' with r2 unseen", len(out) == 1 and out[0]["values"]["room"] == "r2" and out[0]["values"]["covered"] == 0.0, out and out[0]["values"])
check("area uncovered: without that word it says nothing", not found(make(worlds=[w]), "area_uncovered"))

# the track and what did not apply
r = make(still(30, [0.0, 0.0, 0.0]))
res = A.analyse(r, None)
check("analyse: without a layout the layout detectors say they did not apply", set(res["not_applied"]) == {"near_miss", "phantom_obstacle", "misplaced_edge"}
      and all("layout" in v for v in res["not_applied"].values()), res["not_applied"])
default = {d.id for d in A.DETECTORS.values() if d.default}
check("analyse: the default track is the quiet detectors, the rest are named as not run", set(res["ran"]) | set(res["not_applied"]) == default
      and set(res["not_run"]) == set(A.DETECTORS) - default, (res["ran"], res["not_run"]))
res = A.analyse(r, TRUTH, experimental=True)
check("analyse: experimental adds the others (a run with no map snapshots says so for the map's)",
      set(res["ran"]) | set(res["not_applied"]) == set(A.DETECTORS) and not res["not_run"] and set(res["not_applied"]) == {"phantom_obstacle", "missed_obstacle", "area_uncovered"},
      res["not_applied"])
nopose = make([(i * 0.1, [0.0, 0.0, 0.0], None, [0.0, 0.0]) for i in range(30)])
res = A.analyse(nopose, TRUTH, experimental=True)
check("analyse: a run with no truth says so for the detectors that need it", "truth" in res["not_applied"]["odometry_scale"] and "dithering" in res["ran"], res["not_applied"])
res = A.analyse(make(still(20, [1.0, 0.1 + 0.07, 0.0])), TRUTH, detectors=["near_miss"], min_severity="major")
check("analyse: --min-severity keeps the critical, drops the minor", len(res["anomalies"]) == 1)
res = A.analyse(make(still(20, [1.0, 0.1 + 0.089, 0.0])), TRUTH, detectors=["near_miss"], min_severity="major")
check("analyse: ... and drops a minor one", not res["anomalies"])
try:
    A.analyse(r, TRUTH, detectors=["nope"])
    check("analyse: an unknown detector is refused", False)
except ValueError as e:
    check("analyse: an unknown detector is refused, naming the ones there are", "near_miss" in str(e), str(e))
check("every detector has a rule, a version and what it needs", all(d.rule and d.version >= 1 and isinstance(d.needs, tuple) for d in A.DETECTORS.values()))
check("the detectors that are not on the default track say why", all(d.note for d in A.DETECTORS.values() if not d.default))


# ---- tagged by the robot (RFC-0019 section 3.1): events of the run, read into the same record ----------------------------------------
def robot_event(kind="stuck", severity="major", belief=(1.0, 2.0), truth=(1.3, 2.4, 0.1), duration=2.7, margin=0.05, module="navigator", detector="stuck_watch"):
    """The raw of an `anomaly` event as the navigator writes it (duck_lab.nav.anomaly.record, plus the truth `record` adds to every row)."""
    return {"anomaly": kind, "source": "robot", "module": module, "severity": severity, "detector": detector, "version": 1,
            "summary": f"{kind} at {belief}", "values": {"moved_m": 0.01}, "margin": margin, "where": {"frame": "map", "belief": list(belief)},
            "evidence": {}, "related": [], "duration_s": duration, "truth": list(truth)}


r = make(still(30, [1.0, 1.0, 0.0]), events=[(1.5, "anomaly", robot_event()), (2.0, "anomaly", robot_event("room_disagrees", "info", duration=0.0, margin=320))],
         m2w=(1.0, 2.0, 0.0))
out = A.analyse(r, None, detectors=["dithering"] + ["stuck"])
rec = [a for a in out["anomalies"] if a["source"] == "robot"]
check("a robot-tagged anomaly is read from the run's events as a record: the fields of RFC-0019 section 2.1, source robot",
      len(rec) == 1 and {"anomaly", "source", "module", "severity", "detector", "version", "t", "t_end", "where", "summary", "values", "margin",
                         "evidence", "related"} <= set(rec[0]) and rec[0]["anomaly"] == "stuck" and rec[0]["module"] == "navigator"
      and rec[0]["detector"] == "stuck_watch" and rec[0]["severity"] == "major" and rec[0]["margin"] == 0.05, rec)
check("... t and t_end: the event's time and the duration the raise point knew", rec[0]["t"] == 1.5 and abs(rec[0]["t_end"] - 4.2) < 1e-9, (rec[0]["t"], rec[0]["t_end"]))
check("... where: the belief placed in the world by the epoch in force, the truth from the event's own row, both in the world frame",
      rec[0]["where"] == {"frame": "world", "belief": [2.0, 4.0], "truth": [1.3, 2.4]}, rec[0]["where"])
out = A.analyse(r, None)
check("analyse with no detector named: the robot's own are all there, beside the found detectors' run", sorted(a["anomaly"] for a in out["anomalies"]
      if a["source"] == "robot") == ["room_disagrees", "stuck"] and "dithering" in out["ran"], out["ran"])
out = A.analyse(r, None, detectors=["room_disagrees"])
check("analyse --detector names a robot kind: only that kind, no found detector runs", [a["anomaly"] for a in out["anomalies"]] == ["room_disagrees"]
      and out["ran"] == [], out["anomalies"])
out = A.analyse(r, None, detectors=["dithering"])
check("analyse --detector names only a found detector: the robot's are not shown", [a for a in out["anomalies"] if a["source"] == "robot"] == [])
check("analyse --min-severity: the robot's are filtered like the others", [a["anomaly"] for a in A.analyse(r, None, min_severity="major")["anomalies"]
                                                                          if a["source"] == "robot"] == ["stuck"])
nobody = A.analyse(make(still(10, [1.0, 1.0, 0.0])), None)
check("a run that carries none: no robot record", not [a for a in nobody["anomalies"] if a["source"] == "robot"])
real = make(still(10, [1.0, 1.0, 0.0]), events=[(1.0, "anomaly", {"anomaly": "stuck", "severity": "major"}), (1.1, "leg", {"status": "reached"})])
check("an anomaly event that does not say it is the robot's (source robot) is not read as one", not [a for a in A.analyse(real, None)["anomalies"]
                                                                                                                     if a["source"] == "robot"])
harness = {**robot_event("guardrail_broken", "critical", duration=0.0, margin=None, module="runner", detector="truth_guard"), "source": "harness"}
h = [a for a in A.analyse(make(still(10, [1.0, 1.0, 0.0]), events=[(2.0, "anomaly", harness)]), None)["anomalies"] if a["anomaly"] == "guardrail_broken"]
check("must fail: the harness's (the runner's truth guard, recorded by the navigator) is read too, keeping its source",
      [(a["source"], a["severity"], a["module"]) for a in h] == [("harness", "critical", "runner")], h)
check("the robot's kinds are the RFC's vocabulary, each named once", len(set(A.ROBOT_KINDS)) == len(A.ROBOT_KINDS) == 19 and "fix_jump_held" in A.ROBOT_KINDS)


# ---- fixtures: slices of real recordings -----------------------------------------------------------------------------

def sliced(name):
    d = FIX / name
    run = mcapio.new_run(f"duck/apartment/{name}", duck.ROBOT, "apartment", "exploration", T0_NS, "writer")
    return A.Run([(0.0, "run", run)] + duck.records(d, "apartment"))


LAYOUT_JSON = json.loads((SIM / "apartment_layout.json").read_text())
APT = A.Truth.from_layouts([LAYOUT_JSON])
# the layout as it was before it held the free bodies (obj_*, ball_*): the cube by the dock is then nothing
APT_NO_FREE = A.Truth.from_layouts([{"geoms": [g for g in LAYOUT_JSON["geoms"] if not g["name"].startswith(("obj_", "ball_"))]}])

out = found(sliced("graze_b10b_r2"), "near_miss", truth=APT)
check("b10b r2's graze: one near miss, kit_stool2, then a contact", len(out) == 1 and out[0]["values"]["obstacle"] == "kit_stool2"
      and out[0]["values"]["contact"] and abs(out[0]["values"]["clearance_m"] - 0.0709) < 1e-3 and 187.0 < out[0]["t"] < 188.5, out and out[0]["values"])

out = found(sliced("stall_ch17_s1"), "dithering", truth=None)
check("gate12 ch17 seed 1's stall: dithering, from about 27 s", len(out) == 1 and 26.0 < out[0]["t"] < 28.5 and out[0]["values"]["net_m"] < 0.12, out and out[0]["t"])

out = found(sliced("odometry_before_ch11_s1"), "odometry_scale", truth=None)
check("gate3 ch11 seed 1 (before the odometry fix): 0.89 of the truth, major", len(out) == 1 and abs(out[0]["values"]["ratio"] - 0.89) < 0.01
      and out[0]["severity"] == "major", out and out[0]["values"])
check("gate4 ch11 seed 1 (after the fix): quiet", not found(sliced("odometry_after_ch11_s1"), "odometry_scale", truth=None))
out = [a for a in found(sliced("jump_b10a_r1"), "belief_vs_truth", truth=None) if a["anomaly"] == "belief_jump"]
check("b10a r1's mapd jump (K4), ticks only: one belief_jump of 0.94 m within 10 s at about 822.6 s, major", len(out) == 1 and out[0]["anomaly"] == "belief_jump"
      and out[0]["severity"] == "major" and abs(out[0]["values"]["change_m"] - 0.94) < 0.03 and 822.0 < out[0]["t"] < 824.0, out and out[0]["values"])

edge = sliced("edge_b11_r2")
out = found(edge, "misplaced_edge", truth=APT)
check("b11 r2: the stairwell's rim placed off, then refused", len(out) == 1 and 32.0 < out[0]["t"] < 33.0 and out[0]["values"]["median_m"] > 0.25, out and out[0]["values"])
legs = found(edge, "wrong_refusal", truth=APT)
check("b11 r2: legs refused where a path existed by truth (the detector is experimental: it also fires on clean runs)", len(legs) >= 1, len(legs))

dock = sliced("dock_b9_r2")
out = found(dock, "phantom_obstacle", truth=APT_NO_FREE)
check("b9 r2's first map, the layout without the free bodies: the 'phantom' by the dock, 0.5 m from any outline", len(out) == 1 and 3 <= out[0]["values"]["cells"] <= 4
      and abs(out[0]["where"]["belief"][0] + 0.27) < 0.06 and abs(out[0]["where"]["belief"][1] - 0.13) < 0.06 and out[0]["values"]["nearest_outline_m"] > 0.4, out and out[0])
check("b9 r2's first map, the layout with its free bodies: it is the cube obj_3, nothing is phantom", not found(dock, "phantom_obstacle", truth=APT))

end = sliced("nothing_left_b11_r1")
out = found(end, "area_uncovered", truth=APT)
rooms = {a["values"]["room"]: a["values"]["covered"] for a in out}
check("b11 r1's 'nothing left': the kitchen and the bedroom under half covered", set(rooms) >= {"kitchen", "bedroom"} and rooms["kitchen"] < 0.3, rooms)

# the robot's own tags, from a real simulator run: mapd's pose shifted 0.9 m from 30 s on, so every fix is held and the frames part
tagged = A.analyse(sliced("robot_tagged_fault"), None)["anomalies"]
kinds = [a["anomaly"] for a in tagged if a["source"] == "robot"]
check("robot_tagged_fault: the navigator's own tags are read back: four held fixes and the frames parting, all robot, all major",
      sorted(kinds) == ["fix_jump_held"] * 4 + ["frames_parted"] and all(a["severity"] == "major" and a["source"] == "robot" for a in tagged), kinds)
jump = next(a for a in tagged if a["anomaly"] == "fix_jump_held")
check("... the record: the gate's detector, the margin past 0.3 m, the numbers it saw, mapd's raw pose in the evidence",
      jump["detector"] == "fix_gate" and jump["module"] == "localizer" and abs(jump["margin"] - 0.6) < 0.02 and abs(jump["values"]["jump_m"] - 0.9) < 0.02
      and jump["evidence"]["raw"] and jump["evidence"]["fix_t_ns"] > 0, jump)
w = jump["where"]
check("... where: the belief (it held) and the truth, in the world frame, 5 cm apart: the world the robot believed against the real one",
      w["frame"] == "world" and math.dist(w["belief"], w["truth"]) < 0.10, w)
check("... a tag is at the second the navigator said it", 31.9 < jump["t"] < 32.2 and jump["t_end"] == jump["t"], (jump["t"], jump["t_end"]))


# ---- the command line ------------------------------------------------------------------------------------------------

import atexit
import shutil
import tempfile

tmp = Path(tempfile.mkdtemp(prefix="anomalies-cli-"))
atexit.register(shutil.rmtree, tmp, ignore_errors=True)
data = tmp / "data"
for name in ("graze_b10b_r2", "odometry_before_ch11_s1", "edge_b11_r2", "robot_tagged_fault"):
    import_duck(FIX / name, "apartment", data, say=lambda *_: None, started_at_ns=T0_NS)
LAYOUTS = ["--layout", str(SIM / "apartment_layout.json")]


def cmdline(*args):
    argv, sys.argv = sys.argv, ["observatory", "--data", str(data), *args]
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        err.write(str(e.code) if isinstance(e.code, str) else "")
    finally:
        sys.argv = argv
    return code, out.getvalue(), err.getvalue()


def files(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())


before = files(tmp)
code, text, _ = cmdline("anomalies", "graze_b10b_r2", *LAYOUTS)
check("anomalies: the table has the near miss, its severity and its places", code == 0 and "near_miss" in text and "critical" in text and "kit_stool2" in text
      and "->" in text, text)
check("anomalies: the footer counts and names what did not run", "1 anomaly" in text and "not run" in text and "missed_obstacle" in text, text.splitlines()[-1][:90])
code, text, _ = cmdline("anomalies", "graze_b10b_r2", "--json", *LAYOUTS)
doc = json.loads(text)
check("anomalies --json: the records, what ran, what did not apply", code == 0 and doc["run"] == "duck/apartment/graze_b10b_r2" and len(doc["anomalies"]) == 1
      and doc["anomalies"][0]["detector"] == "near_miss" and "near_miss" in doc["ran"] and list(doc["not_applied"]) == ["phantom_obstacle"]
      and doc["layouts"] == [str(SIM / "apartment_layout.json")], doc.get("not_applied"))
code, text, _ = cmdline("anomalies", "graze_b10b_r2", "--json")
doc = json.loads(text)
check("anomalies: without a layout the near miss is said not to apply, not reported as zero", "near_miss" in doc["not_applied"] and not doc["anomalies"], doc["not_applied"])
code, text, _ = cmdline("anomalies", "graze_b10b_r2", "--json", "--detector", "dithering", *LAYOUTS)
check("anomalies --detector: only that one", json.loads(text)["ran"] == ["dithering"] and not json.loads(text)["anomalies"])
code, text, _ = cmdline("anomalies", "graze_b10b_r2", "--detector", "dithering", *LAYOUTS)
lines = [ln for ln in text.splitlines() if ln.strip().startswith("not run")]
check("anomalies --detector: the footer says why each other detector did not run (not selected, or experimental)",
      any("not selected" in ln and "near_miss" in ln and "missed_obstacle" not in ln for ln in lines)
      and any("experimental" in ln and "missed_obstacle" in ln and "near_miss" not in ln for ln in lines) and "default track" not in text, lines)
doc = json.loads(cmdline("anomalies", "graze_b10b_r2", "--json", "--detector", "dithering", *LAYOUTS)[1])
check("anomalies --json: not_run says why per detector", doc["not_run"]["near_miss"].startswith("not selected") and doc["not_run"]["missed_obstacle"].startswith("experimental"), doc["not_run"])
code, text, _ = cmdline("anomalies", "edge_b11_r2", "--json", "--detector", "misplaced_edge,wrong_refusal", *LAYOUTS)
check("anomalies --detector asks for an experimental detector by name", json.loads(text)["ran"] == ["misplaced_edge", "wrong_refusal"])
code, text, _ = cmdline("anomalies", "graze_b10b_r2", "--json", "--min-severity", "critical", *LAYOUTS)
check("anomalies --min-severity critical keeps the contact", len(json.loads(text)["anomalies"]) == 1)
code, text, _ = cmdline("anomalies", "edge_b11_r2", "--json", "--experimental", *LAYOUTS)
doc = json.loads(text)
check("anomalies --experimental runs the detectors that are not quiet, said so", set(doc["ran"]) == set(A.DETECTORS) and not doc["not_run"])
code, text, _ = cmdline("anomalies", "edge_b11_r2", "--experimental", *LAYOUTS)
check("anomalies --experimental: the table says which are not quiet", "not quiet" in text, text.splitlines()[-3:])
code, text, _ = cmdline("anomalies", "odometry_before_ch11_s1", "--json")
check("anomalies: the odometry scale needs no layout", code == 0 and [a["detector"] for a in json.loads(text)["anomalies"]] == ["odometry_scale"])
code, _, err = cmdline("anomalies", "no-such-run")
check("anomalies: an unknown run is said", code != 0 and "no run" in err, err)
code, _, err = cmdline("anomalies", "graze_b10b_r2", "--detector", "nope")
check("anomalies: an unknown detector is said", code != 0 and "nope" in err, err)
code, _, err = cmdline("anomalies", "graze_b10b_r2", "--layout", str(tmp / "missing.json"))
check("anomalies: a missing layout file is said", code != 0 and "missing.json" in err, err)
code, text, _ = cmdline("anomalies", "duck/apartment/graze_b10b_r2", "--json", *LAYOUTS)
check("anomalies: the run by its key", code == 0 and json.loads(text)["run"] == "duck/apartment/graze_b10b_r2")
check("anomalies: nothing is written, not into the run, not into the data folder", files(tmp) == before)

# the robot's own tags in the command line, from a recording that carries them
code, text, _ = cmdline("anomalies", "robot_tagged_fault", *LAYOUTS)
table = [ln for ln in text.splitlines() if ln.split()[2:3] in (["fix_jump_held"], ["frames_parted"])]
check("anomalies: the robot's tags are rows of the table, source robot, severity, margin, and the believed place against the true one",
      code == 0 and len(table) == 5 and all(" robot " in ln and "major" in ln and "belief (" in ln and "truth (" in ln and "->" in ln for ln in table), table[:2])
check("anomalies: the footer counts what the robot tagged, by kind", "tagged by the robot while it ran" in text and "fix_jump_held 4, frames_parted 1" in text,
      [ln for ln in text.splitlines() if "tagged by" in ln])
doc = json.loads(cmdline("anomalies", "robot_tagged_fault", "--json", *LAYOUTS)[1])
check("anomalies --json: the robot's records are in the list with source robot, beside the analysis ones' fields",
      sorted(a["anomaly"] for a in doc["anomalies"] if a["source"] == "robot") == ["fix_jump_held"] * 4 + ["frames_parted"]
      and all({"t", "t_end", "where", "summary", "values", "margin", "evidence", "related", "detector", "version"} <= set(a) for a in doc["anomalies"]))
doc = json.loads(cmdline("anomalies", "robot_tagged_fault", "--json", "--detector", "frames_parted", *LAYOUTS)[1])
check("anomalies --detector names a robot kind: only those, and no found detector ran", [a["anomaly"] for a in doc["anomalies"]] == ["frames_parted"] and doc["ran"] == [])
code, text, _ = cmdline("anomalies", "robot_tagged_fault", "--json", "--detector", "dithering", *LAYOUTS)
check("anomalies --detector dithering: the robot's tags are not shown, as only that one was asked for", not [a for a in json.loads(text)["anomalies"] if a["source"] == "robot"])
code, text, _ = cmdline("events", "robot_tagged_fault", "--kinds", "anomaly")
lines = [ln for ln in text.splitlines() if "anomaly" in ln]
check("events: the robot's anomalies are in the run's event list, one line each with the kind, the severity and what it said",
      code == 0 and len(lines) == 5 and sum("anomaly fix_jump_held (major): mapd's fix would move the belief 0.90 m" in ln for ln in lines) == 4
      and sum("anomaly frames_parted (major)" in ln for ln in lines) == 1, lines[:2])

scripts = tomllib.loads((ROOT / "apps" / "observatory" / "pyproject.toml").read_text())["project"]["scripts"]
check("`miniview anomalies` is the same command: the old name is kept in the scripts", scripts["miniview"] == scripts["observatory"] == "observatory.cli:main", scripts)

check.done()
