"""Plan geometry for areas (RFC-0014 §3.5.3): an area is a polygon in the site frame, as a list of
[x, y]. Pure functions, metres."""

import math

EPS = 1e-9


class GeometryError(ValueError):
    pass


def clean_outline(raw) -> list:
    """A validated outline: at least three finite [x, y], no repeated neighbours, no zero area, no
    self-crossing, returned counter-clockwise."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise GeometryError("an outline is a list of at least three [x, y] points")
    pts = []
    for p in raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p)):
            raise GeometryError(f"an outline point is [x, y] in metres, got {p!r}")
        pt = [float(p[0]), float(p[1])]
        if not pts or pt != pts[-1]:
            pts.append(pt)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        raise GeometryError("an outline needs three distinct points")
    if abs(signed_area(pts)) < EPS:
        raise GeometryError("an outline has no area")
    if not is_simple(pts):
        raise GeometryError("an outline must not cross itself")
    return pts if signed_area(pts) > 0 else pts[::-1]


def signed_area(poly) -> float:
    s = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def area(poly) -> float:
    return abs(signed_area(poly))


def centroid(poly) -> list:
    a = signed_area(poly)
    cx = cy = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        w = x1 * y2 - x2 * y1
        cx += (x1 + x2) * w
        cy += (y1 + y2) * w
    return [cx / (6 * a), cy / (6 * a)]


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p, a, b) -> bool:
    if abs(_cross(a, b, p)) > 1e-9:
        return False
    return min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS


def point_in_polygon(pt, poly) -> bool:
    """Inside or on the boundary."""
    n = len(poly)
    inside = False
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if _on_segment(pt, a, b):
            return True
        if (a[1] > pt[1]) != (b[1] > pt[1]):
            x = a[0] + (pt[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > pt[0]:
                inside = not inside
    return inside


def segments_intersect(p1, p2, p3, p4) -> bool:
    """Touching counts."""
    d1, d2 = _cross(p3, p4, p1), _cross(p3, p4, p2)
    d3, d4 = _cross(p1, p2, p3), _cross(p1, p2, p4)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return (_on_segment(p1, p3, p4) or _on_segment(p2, p3, p4) or _on_segment(p3, p1, p2) or _on_segment(p4, p1, p2))


def is_simple(poly) -> bool:
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            if segments_intersect(a, b, poly[j], poly[(j + 1) % n]):
                return False
    return True


def segment_hits_polygon(a, b, poly) -> bool:
    if point_in_polygon(a, poly) or point_in_polygon(b, poly):
        return True
    n = len(poly)
    return any(segments_intersect(a, b, poly[i], poly[(i + 1) % n]) for i in range(n))


def interior_point(poly) -> list:
    """A point inside the outline: the centroid, or, for a shape that wraps round it, the middle of the
    longest chord at a few heights."""
    c = centroid(poly)
    if point_in_polygon(c, poly):
        return c
    ys = [p[1] for p in poly]
    lo, hi = min(ys), max(ys)
    best, best_len = None, -1.0
    for k in range(1, 20):
        y = lo + (hi - lo) * k / 20
        xs = []
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            if (a[1] > y) != (b[1] > y):
                xs.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
        xs.sort()
        for j in range(0, len(xs) - 1, 2):
            if xs[j + 1] - xs[j] > best_len:
                best_len = xs[j + 1] - xs[j]
                best = [(xs[j] + xs[j + 1]) / 2, y]
    return best


def convex_hull(points) -> list:
    pts = sorted({(round(p[0], 9), round(p[1], 9)) for p in points})
    if len(pts) < 3:
        return [list(p) for p in pts]

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and _cross(h[-2], h[-1], p) <= 0:
                h.pop()
            h.append(p)
        return h

    lower, upper = half(pts), half(reversed(pts))
    return [list(p) for p in lower[:-1] + upper[:-1]]


def _clip(poly, p, q, keep_left: bool) -> list:
    """Sutherland-Hodgman against one side of the line p -> q."""
    sign = 1.0 if keep_left else -1.0
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        sa, sb = sign * _cross(p, q, a), sign * _cross(p, q, b)
        if sa >= 0:
            out.append(a)
        if (sa > 0 and sb < 0) or (sa < 0 and sb > 0):
            t = sa / (sa - sb)
            out.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
    return out


def split_polygon(poly, p, q):
    """Cut an outline by the line through p and q. Returns (left, right) of the directed line p -> q.
    The line must cross the outline in exactly two places and miss every corner, so each half is
    one simple polygon."""
    sides = [_cross(p, q, v) for v in poly]
    if any(abs(s) < 1e-9 for s in sides):
        raise GeometryError("the line passes through a corner of the outline; move it")
    changes = sum(1 for i in range(len(sides)) if (sides[i] > 0) != (sides[(i + 1) % len(sides)] > 0))
    if changes == 0:
        raise GeometryError("the line does not cut the outline")
    if changes > 2:
        raise GeometryError("the line cuts the outline in more than two places; each half must be one polygon")
    return _clip(poly, p, q, True), _clip(poly, p, q, False)
