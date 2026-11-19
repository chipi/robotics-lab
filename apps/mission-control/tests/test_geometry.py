"""Areas are polygons the operator draws (RFC-0014 §3.5.3): validation, which area holds a point, merge
and split geometry. Pure functions.
Run: cd apps/mission-control && uv run python tests/test_geometry.py"""

from common import check, finish

from mission_control import geometry as g

SQUARE = [[0, 0], [4, 0], [4, 4], [0, 4]]
L_SHAPE = [[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]]


def refused(fn, *args):
    try:
        fn(*args)
    except g.GeometryError as exc:
        return str(exc)
    return None


check("a clockwise outline is returned counter-clockwise", g.signed_area(g.clean_outline(SQUARE[::-1])) > 0)
check("a closing point equal to the first is dropped", len(g.clean_outline(SQUARE + [SQUARE[0]])) == 4)
check("two points are not an outline", refused(g.clean_outline, [[0, 0], [1, 1]]) is not None)
check("a point that is not [x, y] is refused", "[x, y]" in (refused(g.clean_outline, [[0, 0], [1, "a"], [2, 2]]) or ""))
check("a flat outline has no area", "no area" in (refused(g.clean_outline, [[0, 0], [1, 1], [2, 2]]) or ""))
check("a bow-tie crosses itself", "cross" in (refused(g.clean_outline, [[0, 0], [5, 5], [4, 0], [0, 3]]) or ""))
check("a symmetric bow-tie has no area, and is refused too", refused(g.clean_outline, [[0, 0], [4, 4], [4, 0], [0, 4]]) is not None)
check("nan is refused", refused(g.clean_outline, [[0, 0], [float("nan"), 1], [2, 2]]) is not None)

check("area of a 4 m square", abs(g.area(SQUARE) - 16) < 1e-9)
check("centroid of the square", g.centroid(SQUARE) == [2.0, 2.0])
check("inside", g.point_in_polygon([1, 1], SQUARE))
check("outside", not g.point_in_polygon([5, 1], SQUARE))
check("the boundary counts as inside", g.point_in_polygon([4, 2], SQUARE) and g.point_in_polygon([0, 0], SQUARE))
check("the notch of an L is outside it", not g.point_in_polygon([4, 4], L_SHAPE))
check("an L's centroid may be outside, its interior point is inside",
      g.point_in_polygon(g.interior_point(L_SHAPE), L_SHAPE))
U_SHAPE = [[0, 0], [6, 0], [6, 6], [4, 6], [4, 2], [2, 2], [2, 6], [0, 6]]
check("a U's centroid is in the notch, its interior point is not", not g.point_in_polygon(g.centroid(U_SHAPE), U_SHAPE)
      and g.point_in_polygon(g.interior_point(U_SHAPE), U_SHAPE))

check("a segment through the square hits it", g.segment_hits_polygon([-1, 2], [5, 2], SQUARE))
check("a segment beside it misses", not g.segment_hits_polygon([-1, 5], [5, 5], SQUARE))
check("a segment that ends inside hits", g.segment_hits_polygon([-1, 2], [1, 2], SQUARE))
check("a segment across the L's notch misses it", not g.segment_hits_polygon([3, 3], [5, 5], L_SHAPE))

hull = g.convex_hull([[0, 0], [2, 0], [2, 2], [0, 2], [1, 1], [3, 1]])
check("convex hull drops interior points", [1, 1] not in hull and [3, 1] in hull and len(hull) == 5, hull)

left, right = g.split_polygon(SQUARE, [2, -1], [2, 5])
check("a line down the middle halves the square", abs(g.area(left) - 8) < 1e-9 and abs(g.area(right) - 8) < 1e-9)
check("left is the left of the directed line (p -> q going up: x below 2 is on the left)",
      all(p[0] <= 2 + 1e-9 for p in left) and all(p[0] >= 2 - 1e-9 for p in right), (left, right))
check("a line through a corner is refused", "corner" in (refused(g.split_polygon, SQUARE, [0, 0], [4, 4]) or ""))
check("a line that misses is refused", "does not cut" in (refused(g.split_polygon, SQUARE, [9, 0], [9, 5]) or ""))
check("a line across both arms of a U cuts it in four places and is refused",
      "more than two" in (refused(g.split_polygon, U_SHAPE, [-1, 4], [7, 4]) or ""))
check("a line across the L's long arm gives two simple polygons",
      all(g.is_simple(p) for p in g.split_polygon(L_SHAPE, [4, -1], [4, 3])))

finish("test_geometry")
