"""Dead reckoning with fixes (RFC-0002 §3.7): odometry is smooth and drifts, mapd's pose is a fix.

The navigator keeps one transform, map ← odom: at each mapd pose, the map pose composed with the
inverse of the odometry pose at the same t_ns. Between fixes, the pose on the map is that transform
applied to the latest odometry. Poses are (x, y, yaw).

Two things sit on top of that (RFC-0016 §4; the run explore-b10a-r1, where one fix moved the belief 0.9 m while the
duck pivoted and the duck later touched a landmark): a gate on a fix that would move the belief more than max_jump_m
(it is held, and taken only when hold_n fixes in a row agree with each other), and an offset, the landmarks' correction
(nudge), kept across fixes — each fix replaces the transform, so a correction made once would be gone in a second.

A large fix that is mapd's loop closure (K26) is held too, and hold_n fixes agreeing do not take it: after a closure mapd's
later fixes agree with the closure's frame whether it was right or not (the two closures of 2026-11-20 both stayed within
0.1 m of themselves for 15 s while 2.2 m and 0.4 m off the truth). Only the landmarks take it (accept_closure, called
when the relocaliser, placing sightings as the closure's frame would, finds them on their anchors), or mapd coming back to
the belief's frame (a fix that is not large).

The gate's numbers are the robot's, the profile's `localisation.fix` block, passed as `fix`:
  jump_m, jump_rad   a fix moving the belief further than this (or turning it further) is a large one
  hold_n             fixes in a row that must agree before a jump is taken (at one fix a second: 5 s), agreeing to within
                     hold_agree_m and hold_agree_rad
  offset_max_m       the landmarks' total correction never exceeds this ...
  offset_half_s      ... and it halves in this time: mapd corrects itself too, and an old correction would then double it
  move_m, move_rad   the memory follows the belief's frame once it has moved this far from where the memory sits: a fix a second
                     moves it by centimetres, and a memory re-keyed every second would only smear
  parted_m, parted_rad   the belief's frame and mapd's are "parted" past this: a held jump, or a landmarks' offset
"""

import math

FROM_FIX = ...           # Localizer(hold_n=FROM_FIX): the profile's hold_n (None: a held jump is never taken late)


def compose(a: tuple, b: tuple) -> tuple:
    """a ∘ b: b expressed in a's parent frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1], math.atan2(math.sin(a[2] + b[2]),
                                                                              math.cos(a[2] + b[2]))


def inverse(a: tuple) -> tuple:
    c, s = math.cos(a[2]), math.sin(a[2])
    return -c * a[0] - s * a[1], s * a[0] - c * a[1], -a[2]


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def move_xy(t: tuple, p: tuple) -> tuple:
    """A point (x, y, ...) moved by the frame change t (x, y, yaw): t ∘ p's position; anything past the position is kept."""
    c, s = math.cos(t[2]), math.sin(t[2])
    return (t[0] + c * p[0] - s * p[1], t[1] + s * p[0] + c * p[1]) + tuple(p[2:])


def move_grid(g: dict, t: tuple | None) -> dict:
    """mapd's grid (res_m, origin, width, height, cells; metres as the navigator uses them) expressed in the belief's
    frame, t = the belief's frame against mapd's (Localizer.delta). A shift when t does not turn: the origin moves. A turn
    is resampled onto a grid that stays axis-aligned (the cell centre of each new cell read from the old grid, "?" where
    it was off it). The grid is rendered from the same graph mapd's pose is, so the two frames move together
    (mapping-design §5): one transform for the whole grid."""
    if t is None or (t[0] == 0.0 and t[1] == 0.0 and t[2] == 0.0):
        return g
    res, (ox, oy), w, h, cells = g["res_m"], g["origin"], g["width"], g["height"], g["cells"]
    if abs(t[2]) < 1e-3:
        return {**g, "origin": [ox + t[0], oy + t[1]]}
    corners = [move_xy(t, (ox + i * w * res, oy + j * h * res)) for i in (0, 1) for j in (0, 1)]
    nx0, ny0 = min(c[0] for c in corners), min(c[1] for c in corners)
    nw, nh = math.ceil((max(c[0] for c in corners) - nx0) / res), math.ceil((max(c[1] for c in corners) - ny0) / res)
    back = inverse(t)
    out = []
    for cy in range(nh):
        for cx in range(nw):
            sx, sy = move_xy(back, (nx0 + (cx + 0.5) * res, ny0 + (cy + 0.5) * res))
            ix, iy = math.floor((sx - ox) / res), math.floor((sy - oy) / res)
            out.append(cells[iy * w + ix] if 0 <= ix < w and 0 <= iy < h else "?")
    return {**g, "origin": [nx0, ny0], "width": nw, "height": nh, "cells": "".join(out)}


class Localizer:
    def __init__(self, fix, history: int = 200, max_jump_m: float | None = None, hold_n=FROM_FIX):
        self.fix = fix                    # the profile's localisation.fix block: the gate's numbers
        self.map_from_odom = None
        self._odom = []          # (t_ns, pose), newest last
        self._history = history
        self.max_jump_m = max_jump_m      # None: every fix is taken
        self.hold_n = fix.hold_n if hold_n is FROM_FIX else hold_n   # fixes in a row that must agree before a held jump is taken; None: never
        self.offset = (0.0, 0.0)          # the landmarks' correction, added to every fix's transform
        self._held = []                   # the transforms of the fixes held back, in a row
        self._closure = None              # why a loop closure is held (a reason); None when none is
        self._fix_t_ns = None
        self.rejected = 0
        self.last_fix = None              # what the latest fix was, for the run's record
        self.mapd_from_odom = None        # mapd's own transform from its latest fix, held or taken: its frame, no offset
        self._mem = None                  # the map <- odom the navigator's memory is expressed in (memory_delta)

    def on_odom(self, t_ns: int, pose: tuple) -> None:
        self._odom.append((t_ns, pose))
        del self._odom[:-self._history]

    def on_fix(self, t_ns: int, map_pose: tuple, closure: str | None = None) -> bool:
        """A mapd pose. Returns False when no odometry near that time is held. With max_jump_m, a fix that would move the
        belief further is held (last_fix["status"] "held"; the belief stays) until hold_n in a row agree ("late"); it still
        returns True. last_fix says what it was: the raw pose, its t_ns, the odometry paired with it, the belief before and
        after and how far it moved. closure (a reason, e.g. "loop closure": mapd says it closed a loop): a large fix with it
        is held, and so is every large fix after it, with no "late": last_fix["closure"] says why, and only accept_closure
        or a fix that is not large ends it."""
        near = min(self._odom, key=lambda e: abs(e[0] - t_ns), default=None)
        if near is None or abs(near[0] - t_ns) > 100_000_000:
            return False
        if self._fix_t_ns is not None and t_ns > self._fix_t_ns:
            k = 0.5 ** ((t_ns - self._fix_t_ns) / 1e9 / self.fix.offset_half_s)
            self.offset = (self.offset[0] * k, self.offset[1] * k)
        self._fix_t_ns = t_ns
        new = compose(map_pose, inverse(near[1]))
        self.mapd_from_odom = new
        new = (new[0] + self.offset[0], new[1] + self.offset[1], new[2])
        before = None if self.map_from_odom is None else compose(self.map_from_odom, near[1])
        after = compose(new, near[1])
        jump = 0.0 if before is None else math.dist(before[:2], after[:2])
        status = "taken"
        large = before is not None and self.max_jump_m is not None and (jump > self.max_jump_m
                                                                      or abs(_wrap(after[2] - before[2])) > self.fix.jump_rad)
        if large and closure is not None:
            self._closure = closure
        if large:
            if self._held and (math.dist(self._held[-1][:2], new[:2]) > self.fix.hold_agree_m
                               or abs(_wrap(self._held[-1][2] - new[2])) > self.fix.hold_agree_rad):
                self._held = []
            self._held = (self._held + [new])[-(self.hold_n or self.fix.hold_n):]
            self.rejected += 1
            status = ("late" if self.hold_n is not None and len(self._held) >= self.hold_n and self._closure is None
                      else "held")
        elif before is not None:
            self._closure = None          # mapd is back where the belief is
        if status != "held":
            self.map_from_odom = new
            self._held = []
            if self._mem is None:
                self._mem = new       # the memory starts in the first fix's frame
        self.last_fix = {"status": status, "t_ns": t_ns, "raw": [round(v, 4) for v in map_pose],
                         "odom_t_ns": near[0], "odom": [round(v, 4) for v in near[1]],
                         "before": None if before is None else [round(v, 4) for v in before],
                         "after": [round(v, 4) for v in after], "moved_m": round(jump, 3)}
        if large and self._closure is not None:
            self.last_fix["closure"] = self._closure
        return True

    def closure_pending(self) -> bool:
        return self._closure is not None and bool(self._held)

    def closure_frame(self) -> tuple | None:
        """The frame change the held closure would make, h with belief' = h ∘ belief (x, y, yaw), from mapd's latest held fix;
        None when no closure is held. (The camera's thread asks while the navigator's thread takes fixes: each field is read once.)"""
        held, base = self._held, self.map_from_odom
        if self._closure is None or not held or base is None:
            return None
        return compose(held[-1], inverse(base))

    def accept_closure(self) -> tuple | None:
        """The landmarks agree with the held closure: the belief takes mapd's latest held frame. Returns the frame change made
        (closure_frame's), None when no closure is held."""
        held, base = self._held, self.map_from_odom
        if self._closure is None or not held or base is None:
            return None
        self.map_from_odom, self._held, self._closure = held[-1], [], None
        return compose(held[-1], inverse(base))

    def nudge(self, dx: float, dy: float) -> tuple:
        """The landmarks' correction: move the belief by (dx, dy) on the map, kept across fixes; the total is capped at
        offset_max_m. Returns the step taken."""
        ox, oy = self.offset[0] + dx, self.offset[1] + dy
        n = math.hypot(ox, oy)
        if n > self.fix.offset_max_m:
            ox, oy = ox * self.fix.offset_max_m / n, oy * self.fix.offset_max_m / n
        step = (ox - self.offset[0], oy - self.offset[1])
        self.offset = (ox, oy)
        if self.map_from_odom is not None:
            m = self.map_from_odom
            self.map_from_odom = (m[0] + step[0], m[1] + step[1], m[2])
        return step

    def delta(self) -> tuple | None:
        """The belief's frame against mapd's: the transform T with belief = T ∘ mapd's pose, (x, y, yaw); None before the
        first fix. A taken fix leaves only the landmarks' offset; a held one leaves the jump."""
        if self.map_from_odom is None or self.mapd_from_odom is None:
            return None
        return compose(self.map_from_odom, inverse(self.mapd_from_odom))

    def parted(self) -> bool:
        d = self.delta()
        return d is not None and (math.hypot(d[0], d[1]) > self.fix.parted_m or abs(d[2]) > self.fix.parted_rad)

    def memory_pending(self) -> bool:
        """The belief has moved from the frame the memory sits in by more than memory_delta acts on."""
        if self.map_from_odom is None or self._mem is None:
            return False
        d = compose(self.map_from_odom, inverse(self._mem))
        return math.hypot(d[0], d[1]) >= self.fix.move_m or abs(d[2]) >= self.fix.move_rad

    def memory_delta(self) -> tuple | None:
        """What to move the navigator's memory (everything it placed with the belief) by, once the belief's frame has moved
        from the one the memory sits in: the transform new <- old, applied to each point. None while it has moved less
        than move_m / move_rad."""
        if not self.memory_pending():
            return None
        d = compose(self.map_from_odom, inverse(self._mem))
        self._mem = self.map_from_odom
        return d

    def to_map(self, odom_pose: tuple) -> tuple | None:
        """An odometry pose on the map (None before the first fix): the pose at the odometry's own instant, not the latest."""
        return None if self.map_from_odom is None else compose(self.map_from_odom, odom_pose)

    def pose(self) -> tuple | None:
        """The latest pose on the map, or None before the first fix."""
        if self.map_from_odom is None or not self._odom:
            return None
        return compose(self.map_from_odom, self._odom[-1][1])
