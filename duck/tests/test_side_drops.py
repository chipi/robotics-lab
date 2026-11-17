"""Drops beside the way, suspected and confirmed (nav/side_drops.py). Run: cd duck && uv run python tests/test_side_drops.py"""

import math
import sys

from duck_lab.nav.side_drops import (SUSPECT_FRAMES, SuspectMemory, below_counts, continuation, continues, edge_axis, edge_from_glance,
                                     head_settled, in_the_way, look_targets)

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        failures.append(name)


# Suspicion: a cell becomes a suspected drop after SUSPECT_FRAMES frames of below-floor returns, not before.
m = SuspectMemory()
got = [m.add_frame([(1.0, 0.5, "below")]) for _ in range(SUSPECT_FRAMES)]
check("a cell is suspected on its SUSPECT_FRAMES-th below-floor frame, not before",
      all(not g for g in got[:-1]) and got[-1] == [(20, 10)], got)
check("its point is the cell's centre", m.points() == [(1.0, 0.5)], m.points())
check("a suspected cell is not reported again", m.add_frame([(1.0, 0.5, "below")]) == [])

# A below-floor return counts toward a suspicion only when it is deep enough for its range: a far floor return read just
# past cliff.EXTRA_M (6 cm) is the trunk's pitch, not a hole (the false suspicions that closed challenge 10's goal: 6.6-7.9
# cm below, 1.1-2.4 m away). Replayed over 2 days of runs, 3.5 cm a metre: false cells 92 -> 17, drops suspected before
# the closest approach 157 -> 151 of 180, the lead unchanged (17 s).
check("a return 8 cm below the floor 0.5 m away counts (it needs 6 + 1.75 cm)", below_counts(-0.08, 0.5))
check("... 1.5 m away it does not (it needs 6 + 5.25 cm)", not below_counts(-0.08, 1.5))
check("a real drop's floor (11 cm and deeper) counts 1.4 m away", below_counts(-0.11, 1.4))
check("the threshold at the duck is cliff.EXTRA_M", below_counts(-0.0601, 0.0) and not below_counts(-0.0599, 0.0))

# The ratio: a cell seen as floor about as often as below is not suspected.
r = SuspectMemory()
for _ in range(SUSPECT_FRAMES * 2):
    r.add_frame([(0.0, 0.0, "below")])
    r.add_frame([(0.0, 0.0, "floor")])
check("a cell seen as floor as often as below stays unsuspected (ratio)", not r.suspected, r.below, )

# One frame's many returns in the same cell count once.
o = SuspectMemory()
for _ in range(SUSPECT_FRAMES - 1):
    o.add_frame([(2.0, 2.0, "below")] * 10)
check("a frame counts once per cell, however many returns it puts there", not o.suspected)

# Clearing: a glance that saw floor clears the suspicion, and the forward sensor cannot raise it again.
m.clear([(1.0, 0.51)])
check("a glance's floor clears the suspected cell", not m.suspected)
for _ in range(SUSPECT_FRAMES * 2):
    m.add_frame([(1.0, 0.5, "below")])
check("a cleared cell is not suspected again from the forward sensor", not m.suspected)
# A look aimed at a suspicion that sees floor around it clears it, with floor returns a few cm apart at 0.8 m and the map
# drifting between the suspicion and the look (challenge 10 seed 8: floor seen, the cell 0.1 m from the goal not cleared,
# the goal lethal, the leg refused).
cm = SuspectMemory()
for _ in range(SUSPECT_FRAMES):
    cm.add_frame([(2.65, -0.3, "below"), (1.0, 1.0, "below")])
cm.clear([(2.65 + 0.09, -0.3), (1.0 + 0.12, 1.0)])
check("floor 9 cm from a suspected cell clears it, 12 cm does not", cm.points() == [(1.0, 1.0)], cm.points())
check("near(): suspected cells within reach", (lambda s: (s.add_frame([(0.3, 0.0, "below")]) or True) and s.near((0.0, 0.0), 0.5))(
    (lambda s: [s.add_frame([(0.3, 0.0, "below")]) for _ in range(SUSPECT_FRAMES - 1)] and s)(SuspectMemory())))

# A suspicion next to an edge a glance measured is the same drop: confirmed without another look (challenge 10 seed 1
# looked 7 times in 56 s walking along one ledge, each look covering 0.4 m of it).
a = SuspectMemory()
for _ in range(SUSPECT_FRAMES):
    a.add_frame([(1.0, 0.5, "below"), (2.0, 0.5, "below")])
got = a.confirm_near([(1.1, 0.5)], 0.15)
check("a suspected cell within reach of a measured edge is confirmed, one farther stays suspected",
      got == [(1.0, 0.5)] and a.points() == [(2.0, 0.5)], (got, a.points()))
for _ in range(SUSPECT_FRAMES):
    a.add_frame([(1.0, 0.5, "below")])
check("a confirmed cell is not suspected again", a.points() == [(2.0, 0.5)], a.points())
check("confirm_near with no edges confirms nothing", a.confirm_near([], 0.15) == [] and a.points() == [(2.0, 0.5)])


# No path with the suspicions, a path without them: the suspicions on that path are what to look at, not a reason to
# refuse (challenge 11 seed 3: a false suspicion 0.15 m from the goal, 1.0 m off, beyond CONFIRM_M; the leg was refused).
way = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
check("suspicions within reach of the way are in the way, farther ones are not",
      in_the_way(way, [(1.5, 0.1), (1.0, 0.6), (2.1, -0.2)], 0.25) == [(1.5, 0.1), (2.1, -0.2)])
check("no way, nothing in it", in_the_way([], [(1.5, 0.1)], 0.25) == [])

# After a cliff stop the duck looks along the edge it stopped at, both ways, to see where the hole ends (the operator's
# choice 2026-11-17). The edge runs along the stop's points when they spread sideways; a stop that saw one column of
# them (a narrow look straight at it) is taken as an edge across the heading.
row = [(1.0, y) for y in (-0.1, -0.05, 0.0, 0.05, 0.1)]        # an edge along y, ahead of a duck at the origin facing +x
ax = edge_axis(row, 0.0)
check("an edge seen as a row: its axis runs along the row", abs(abs(ax[1]) - 1.0) < 1e-9, ax)
col = [(0.9, 0.0), (1.0, 0.0), (1.1, 0.01)]                    # one column: the beam's direction, not the edge's
ax1 = edge_axis(col, 0.0)
check("one column of points: the edge is taken across the heading, not along the beam", abs(abs(ax1[1]) - 1.0) < 1e-9, ax1)
ts = look_targets(row, 0.0, 0.4)
check("the looks go 0.4 m beyond each end of the seen edge, on its line",
      len(ts) == 2 and sorted(round(t[1], 3) for t in ts) == [-0.5, 0.5] and all(abs(t[0] - 1.0) < 1e-9 for t in ts), ts)
check("the drop goes on at a target when the glance's rim reaches it", continues([(1.0, 0.45), (1.0, 0.55)], (1.0, 0.5)))
check("... and not when the rim stops short of it (the hole ends there)", not continues([(1.0, 0.1), (1.0, 0.2)], (1.0, 0.5)))
cont = continuation(row, 0.0, side=+1, length_m=0.6)
check("a drop that goes on: points along its line, beyond the seen end on that side",
      cont and all(abs(p[0] - 1.0) < 1e-9 and 0.1 < p[1] <= 0.7 + 1e-9 for p in cont), cont)

# The head has settled when the sensor has held still and has moved from where it faced: yaw or pitch. Yaw alone never
# settled a look straight ahead (challenge 11 seed 5: after a cliff stop the head only pitched down; 3 s, no frames).
turning = [(0.0, -10.0)] + [(y, -10.0) for y in (10, 30, 50, 60)] + [(60.0, -10.0)] * 5
check("a head that turned and held still has settled", head_settled(turning))
check("... not while it is still turning", not head_settled(turning[:6]))
pitching = [(0.0, -10.0), (0.0, -20.0), (0.0, -35.0)] + [(0.5, -40.0)] * 5
check("a head that only pitched down (a look straight ahead) and held still has settled", head_settled(pitching))
check("a head that has not moved yet (the look not begun) has not settled", not head_settled([(0.0, -10.0)] * 8))


def rays(bearings_deg, edge_y, step=0.02, far=1.4):
    """Returns along rays from the origin over floor that ends at y = edge_y (a ledge running along x): floor until the
    edge, then the lower floor below it from a shadow on (0.35 m further along the ray), as the sensor sees a ledge."""
    pts = []
    for a in bearings_deg:
        ux, uy = math.cos(math.radians(a)), math.sin(math.radians(a))
        r_edge = edge_y / uy
        r = step
        while r < far:
            if r <= r_edge:
                pts.append((r * ux, r * uy, "floor"))
            elif r > r_edge + 0.35:
                pts.append((r * ux, r * uy, "below"))
            r += step
    return pts


# Looking along +y at a ledge 0.42 m away: the rim is the floor's boundary, the below-floor returns lie beyond it.
frame = rays(range(80, 101, 2), 0.42)
rim, below, floor = edge_from_glance([frame, frame], (0.0, 0.0), math.pi / 2)
check("looking straight at a ledge 0.42 m away, the rim lies on it (within 2 cm)",
      rim and all(0.40 <= p[1] <= 0.42 + 1e-9 for p in rim), sorted(round(p[1], 3) for p in rim)[:4])
check("below-floor returns beyond the rim are kept", below and all(p[1] > 0.42 for p in below), len(below))
check("all floor returns are returned (to clear suspicions and confirm floor)",
      len(floor) == 2 * sum(1 for p in frame if p[2] == "floor"), len(floor))
# Looking at 45 deg to the same ledge (challenge 11 seed 2's glance was at 30 deg): the rim must follow the ledge, not
# lie across the look. Taking the farthest floor along the look's own direction put it across the look, diagonal to the
# ledge, and its extension reached back toward the duck's way.
oblique = rays(range(25, 66, 2), 0.42)
rim45, _, _ = edge_from_glance([oblique], (0.0, 0.0), math.radians(45))
check("looking at 45 deg to a ledge, every rim point lies on the ledge (y within 2 cm of 0.42), spread along it",
      rim45 and all(0.40 <= p[1] <= 0.42 + 1e-9 for p in rim45) and max(p[0] for p in rim45) - min(p[0] for p in rim45) > 0.4,
      sorted((round(p[0], 2), round(p[1], 2)) for p in rim45)[:6])
# The pit's far wall beyond the ledge (challenge 10 seed 1's last glance): where the lower floor is in the ledge's shadow
# the ray meets the wall, whose band at floor height reads as floor and whose part below it as below, at the same range.
# That floor is not where the floor ends: the rim took it, the edge fitted through both ran diagonally, and its extension
# put the goal inside the edge's lethal ring.
walled = []
for a in range(80, 101, 2):
    ux, uy = math.cos(math.radians(a)), math.sin(math.radians(a))
    r = 0.02
    while r < 1.4:
        if r <= 0.42 / uy:
            walled.append((r * ux, r * uy, "floor"))
        r += 0.02
    rw = 0.85 / uy
    walled += [(rw * ux, rw * uy, "floor"), ((rw + 0.01) * ux, (rw + 0.01) * uy, "below")]
rimw, belw, _ = edge_from_glance([walled], (0.0, 0.0), math.pi / 2)
check("a wall standing in the drop beyond the ledge is not a rim: every rim point on the ledge",
      rimw and all(0.40 <= p[1] <= 0.42 + 1e-9 for p in rimw), sorted(round(p[1], 3) for p in rimw)[-4:])
check("the wall's below returns are still below returns beyond the rim", belw and all(p[1] > 0.84 for p in belw), len(belw))
only_wall = [p for p in walled if p[1] > 0.8]       # a frame that saw only the wall in these directions
rimp, _, _ = edge_from_glance([walled, only_wall], (0.0, 0.0), math.pi / 2)
check("a frame that saw only the far wall does not put the rim there (the frames are taken together)",
      rimp and all(0.40 <= p[1] <= 0.42 + 1e-9 for p in rimp), sorted(round(p[1], 3) for p in rimp)[-4:])
# A drop nearer than the sensor sees floor (challenge 11 seed 8: the duck stood ~0.17 m from the pit, the look saw ~30
# below-floor returns a frame and no floor before them in those directions): no floor-then-below boundary, so no rim, and
# the glance reported floor and cleared a true suspicion; the duck then passed 0.141 m from the pit. Such a direction is a
# drop whose edge is nearer than seen: its rim is the nearest below-floor return (the safe side).
near_pit = [[(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), "below")
             for a in range(80, 101, 2) for r in (0.35, 0.45, 0.55)] for _ in range(10)]
rimn, beln, _ = edge_from_glance(near_pit, (0.0, 0.0), math.pi / 2)
check("only below-floor returns in a look's directions: a drop, its rim at the nearest of them",
      rimn and all(abs(math.hypot(*p) - 0.35) < 1e-9 for p in rimn), sorted(round(math.hypot(*p), 2) for p in rimn)[:4])
# That rim is beyond the true edge: the edge lies somewhere nearer, unseen. But a look aimed far does not see the near
# floor at all, drop or not: the floor between is unknown, not drop (challenge 11 seed 6, 2026-11-17: marking it drop put
# a "drop" 0.11 m from the duck, and it could not turn). It is not floor either: it clears no suspicion there.
check("the unseen floor between the duck and that rim is not made drop", all(math.hypot(*p) >= 0.35 for p in beln))
stray = [[(0.0, 0.5, "below")]] + [[(0.1, 0.3, "floor")] for _ in range(9)]
check("a stray below-floor return (one, in one frame) with no floor before it is not a drop",
      edge_from_glance(stray, (0.0, 0.0), math.pi / 2)[0] == [])
flat = [(x, y, "floor") for x in (-0.1, 0.0, 0.1) for y in (0.1, 0.3, 0.5)]
check("a glance that saw no below-floor return gives no rim (no drop there)",
      edge_from_glance([flat], (0.0, 0.0), math.pi / 2)[0] == [])
behind = [(0.0, -0.5, "below")] + [(0.0, y, "floor") for y in (0.1, 0.3)]
check("a below-floor return behind the look's floor does not make the floor a rim",
      edge_from_glance([behind], (0.0, 0.0), math.pi / 2)[0] == [])

print("SIDE-DROPS", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
